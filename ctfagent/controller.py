"""Trusted controller: resets state, exports contestant files, runs one attempt, writes the records.

results.jsonl holds only the course's A4 fields. Everything extra goes in details/<run_id>.json.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .agent import run_attempt
from .challenges import Task, build_task, host_file_paths, task_prompt
from .config import Config, fingerprint
from .trace import Trace
from .verifier import HashVerifier, Verifier

A4_FIELDS = ["run_id", "config_id", "challenge_id", "trial", "status", "verified", "elapsed_s",
             "input_tokens", "output_tokens", "cost_usd", "trace_file", "reset_id", "sample_type"]


def git_state(repo: Path) -> dict:
    def g(*a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True).stdout.strip()
    # untracked files (such as the run's own output folder) do not make the code "dirty"
    return {"commit": g("rev-parse", "HEAD") or None,
            "dirty": bool(g("status", "--porcelain", "--untracked-files=no"))}


@dataclass
class Prepared:
    """What one attempt needs once its environment is up."""
    reset_id: str
    verifier: Verifier
    task_prompt: str
    allowed_hosts: set


NOTES_HEADER = ("\n\nNotes left by earlier attempts at this challenge (most recent first). They may be wrong or "
                "incomplete, so check anything you rely on:\n")


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

    def prepare(self, challenge_id: str, trace: Trace, detail: dict) -> Prepared:
        """Reset the environment and hand out the files for a local (CTFTiny) challenge."""
        t0 = time.monotonic()
        chal = self.loader(challenge_id)
        verifier = HashVerifier(chal.flag)
        task: Task = build_task(challenge_id, chal, self.cfg.environment.target_host)
        reset_id = self.env.reset(challenge_id, chal)
        inventory = self.env.export(host_file_paths(chal), self.cfg.environment.workdir)
        detail["reset_s"] = round(time.monotonic() - t0, 3)
        detail["export_inventory"] = inventory
        trace.event("environment_ready", reset_id=reset_id, files=inventory)
        return Prepared(reset_id, verifier, task_prompt(task, self.cfg.environment.workdir), task.allowed_hosts)

    def cleanup(self, challenge_id: str, detail: dict) -> None:
        self.env.stop()

    def prior_notes(self, challenge_id: str, limit: int = 3) -> str | None:
        """The most recent notes earlier attempts left for this challenge (newest first), from any
        configuration, so a new attempt sees the accumulated history rather than only the last one.
        Notes that mention a content filter are skipped on purpose: telling the agent its output was
        filtered has no upside and risks it self-censoring."""
        cands = []
        for path in (self.out / "details").glob("*.json"):
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            notes = d.get("notes")
            if d.get("challenge_id") != challenge_id or not notes:
                continue
            if any(w in notes.lower() for w in ("content_filter", "content policy", "flagged for")):
                continue
            cands.append((d.get("started_unix", 0), d.get("model", "?"), notes))
        if not cands:
            return None
        cands.sort(key=lambda c: c[0], reverse=True)   # newest first
        return "\n\n".join(f"-- earlier attempt ({model}):\n{notes}"
                           for _, model, notes in cands[:limit])

    def run_one(self, challenge_id: str, trial: int) -> dict:
        run_id = f"{self.cfg.config_id}-{challenge_id}-t{trial}"
        trace_path = self.out / "traces" / f"{run_id}.jsonl"
        trace = Trace(trace_path, secrets=self.secrets)
        detail: dict = {"run_id": run_id, "challenge_id": challenge_id,
                        "config_fingerprint": fingerprint(self.cfg, self.system_prompt),
                        "model": self.cfg.model, "agent_version": __version__,
                        "git": git_state(self.repo_dir), "started_unix": time.time()}
        reset_id, cost = None, None
        t0 = time.monotonic()
        try:
            ready = self.prepare(challenge_id, trace, detail)
            reset_id = ready.reset_id
            prompt = ready.task_prompt
            notes = self.prior_notes(challenge_id) if self.cfg.handoff_notes else None
            if notes:
                prompt += NOTES_HEADER + notes
                detail["used_prior_notes"] = True
            res = run_attempt(
                cfg=self.cfg, llm=self.llm, executor=self.env.executor(), verifier=ready.verifier, trace=trace,
                system_prompt=self.system_prompt, task_prompt=prompt, allowed_hosts=ready.allowed_hosts)
            status, verified, elapsed = res.status, res.verified, res.elapsed_s
            tokens, cost = (res.input_tokens, res.output_tokens), res.cost_usd
            detail.update(stop_reason=res.stop_reason, steps=res.steps, llm_calls=res.llm_calls,
                          tool_calls=res.tool_calls, wrong_flags=res.wrong_flags,
                          usage_complete=res.usage_complete, submissions=res.submissions)
            if res.notes:
                detail["notes"] = res.notes
        except Exception as e:  # keep the record: infrastructure failures are reported, never dropped
            status, verified, elapsed, tokens = "infrastructure_error", False, round(time.monotonic() - t0, 3), (None, None)
            detail["error"] = f"{type(e).__name__}: {e}"
            trace.event("infrastructure_error", error=detail["error"])
        finally:
            try:
                self.cleanup(challenge_id, detail)
            except Exception as e:
                detail["stop_error"] = f"{type(e).__name__}: {e}"

        record = {
            "run_id": run_id, "config_id": self.cfg.config_id, "challenge_id": challenge_id, "trial": trial,
            "status": status, "verified": verified, "elapsed_s": elapsed,
            "input_tokens": tokens[0], "output_tokens": tokens[1], "cost_usd": cost,
            "trace_file": str(Path("traces") / trace_path.name).replace("\\", "/"),
            "reset_id": reset_id, "sample_type": self.sample_type,
        }
        (self.out / "details" / f"{run_id}.json").write_text(json.dumps(detail, indent=2), encoding="utf-8")
        with (self.out / "results.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return record
