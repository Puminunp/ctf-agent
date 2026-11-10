"""Trusted controller: resets state, exports contestant files, runs one attempt, writes the records.

results.jsonl holds only the course's A4 fields. Everything extra goes in details/<run_id>.json.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from . import __version__
from .agent import run_attempt
from .challenges import Task, build_task, host_file_paths, task_prompt
from .config import Config, fingerprint
from .trace import Trace
from .verifier import HashVerifier

A4_FIELDS = ["run_id", "config_id", "challenge_id", "trial", "status", "verified", "elapsed_s",
             "input_tokens", "output_tokens", "cost_usd", "trace_file", "reset_id", "sample_type"]


def git_state(repo: Path) -> dict:
    def g(*a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True).stdout.strip()
    return {"commit": g("rev-parse", "HEAD") or None, "dirty": bool(g("status", "--porcelain"))}


class Controller:
    def __init__(self, cfg: Config, system_prompt: str, llm, env, out_dir: str | Path, loader,
                 repo_dir: str | Path = ".", sample_type: str = "live", secrets: list[str] | None = None):
        self.cfg, self.system_prompt, self.llm, self.env = cfg, system_prompt, llm, env
        self.out = Path(out_dir)
        self.loader = loader               # callable: challenge_id -> challenge object (holds the flag)
        self.repo_dir = Path(repo_dir)
        self.sample_type = sample_type
        self.secrets = secrets or []
        (self.out / "traces").mkdir(parents=True, exist_ok=True)
        (self.out / "details").mkdir(parents=True, exist_ok=True)

    def done_slots(self) -> set[tuple[str, int]]:
        p = self.out / "results.jsonl"
        if not p.exists():
            return set()
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        return {(r["challenge_id"], r["trial"]) for r in rows}

    def run_one(self, challenge_id: str, trial: int) -> dict:
        run_id = f"{self.cfg.config_id}-{challenge_id}-t{trial}"
        trace_path = self.out / "traces" / f"{run_id}.jsonl"
        trace = Trace(trace_path, secrets=self.secrets)
        detail: dict = {"run_id": run_id, "config_fingerprint": fingerprint(self.cfg, self.system_prompt),
                        "model": self.cfg.model, "agent_version": __version__,
                        "git": git_state(self.repo_dir), "started_unix": time.time()}
        reset_id = None
        t0 = time.monotonic()
        try:
            chal = self.loader(challenge_id)
            verifier = HashVerifier(chal.flag)
            task: Task = build_task(challenge_id, chal, self.cfg.environment.target_host)
            reset_id = self.env.reset(challenge_id)
            inventory = self.env.export(host_file_paths(chal), self.cfg.environment.workdir)
            detail["reset_s"] = round(time.monotonic() - t0, 3)
            detail["export_inventory"] = inventory
            trace.event("environment_ready", reset_id=reset_id, files=inventory)
            res = run_attempt(
                cfg=self.cfg, llm=self.llm, executor=self.env.executor(), verifier=verifier, trace=trace,
                system_prompt=self.system_prompt, task_prompt=task_prompt(task, self.cfg.environment.workdir),
                allowed_hosts=task.allowed_hosts)
            status, verified, elapsed = res.status, res.verified, res.elapsed_s
            tokens = (res.input_tokens, res.output_tokens)
            detail.update(stop_reason=res.stop_reason, steps=res.steps, llm_calls=res.llm_calls,
                          tool_calls=res.tool_calls, wrong_flags=res.wrong_flags,
                          usage_complete=res.usage_complete, submissions=res.submissions)
        except Exception as e:  # keep the record: infrastructure failures are reported, never dropped
            status, verified, elapsed, tokens = "infrastructure_error", False, round(time.monotonic() - t0, 3), (None, None)
            detail["error"] = f"{type(e).__name__}: {e}"
            trace.event("infrastructure_error", error=detail["error"])
        finally:
            try:
                self.env.stop()
            except Exception as e:
                detail["stop_error"] = f"{type(e).__name__}: {e}"

        record = {
            "run_id": run_id, "config_id": self.cfg.config_id, "challenge_id": challenge_id, "trial": trial,
            "status": status, "verified": verified, "elapsed_s": elapsed,
            "input_tokens": tokens[0], "output_tokens": tokens[1], "cost_usd": None,
            "trace_file": str(Path("traces") / trace_path.name).replace("\\", "/"),
            "reset_id": reset_id, "sample_type": self.sample_type,
        }
        (self.out / "details" / f"{run_id}.json").write_text(json.dumps(detail, indent=2), encoding="utf-8")
        with (self.out / "results.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return record
