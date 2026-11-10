"""Target and solver lifecycle, run by the trusted controller.

ComposeEnvironment is a thin wrapper that must be adapted to the instructor's released
course-compose.yaml (service names, how a challenge is selected, networks). It was written from the
guide's description and has NOT been run against that file. Inspect the compose file first:
    docker compose -f course-compose.yaml config --services --networks
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
from pathlib import Path
from typing import Protocol

from .config import EnvironmentConfig
from .executor import DockerExecutor, Executor, FakeExecutor


class EnvironmentError_(Exception):
    pass


class Environment(Protocol):
    def reset(self, challenge_id: str) -> str: ...
    def export(self, files: list[Path], workdir: str) -> list[dict]: ...
    def executor(self) -> Executor: ...
    def stop(self) -> None: ...


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


class ComposeEnvironment:
    def __init__(self, cfg: EnvironmentConfig, compose_cmd: tuple[str, ...] = ("docker", "compose")):
        self.cfg = cfg
        self._compose = list(compose_cmd) + ["-f", cfg.compose_file]
        self._container: str | None = None

    def _run(self, args: list[str], env: dict | None = None, timeout: float = 300):
        proc = subprocess.run(self._compose + args, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, **(env or {})})
        if proc.returncode != 0:
            raise EnvironmentError_(f"compose {' '.join(args)} failed: {proc.stderr.strip()[:500]}")
        return proc.stdout

    def reset(self, challenge_id: str) -> str:
        """Tear down everything including volumes, then start a clean target and solver."""
        self._run(["down", "-v", "--remove-orphans"])
        self._run(["up", "-d", "--wait"], env={"CHALLENGE_ID": challenge_id})
        cid = self._run(["ps", "-q", self.cfg.solver_service]).strip()
        if not cid:
            raise EnvironmentError_(f"solver service '{self.cfg.solver_service}' is not running")
        self._container = cid.splitlines()[0]
        return f"fresh-{uuid.uuid4().hex[:8]}"

    def export(self, files: list[Path], workdir: str) -> list[dict]:
        assert self._container, "reset() must run first"
        subprocess.run(["docker", "exec", self._container, "bash", "-c",
                        f'mkdir -p "{workdir}" && find "{workdir}" -mindepth 1 -delete'],
                       capture_output=True, check=True, timeout=60)
        inventory = []
        for p in files:
            subprocess.run(["docker", "cp", str(p), f"{self._container}:{workdir}/{p.name}"],
                           capture_output=True, check=True, timeout=120)
            inventory.append({"file": p.name, "sha256": sha256_file(p), "bytes": p.stat().st_size})
        return inventory

    def executor(self) -> Executor:
        assert self._container, "reset() must run first"
        return DockerExecutor(self._container, self.cfg.workdir)

    def stop(self) -> None:
        try:
            self._run(["down", "-v", "--remove-orphans"])
        except EnvironmentError_:
            pass


class FakeEnvironment:
    """Test double with the same interface."""

    def __init__(self, executor: Executor | None = None, fail_on: str | None = None):
        self._executor = executor or FakeExecutor()
        self.fail_on = fail_on
        self.resets = 0
        self.stopped = 0

    def reset(self, challenge_id: str) -> str:
        if self.fail_on == "reset":
            raise EnvironmentError_("simulated reset failure")
        self.resets += 1
        return f"fresh-test-{self.resets}"

    def export(self, files, workdir):
        return [{"file": p.name, "sha256": sha256_file(p), "bytes": p.stat().st_size} for p in files]

    def executor(self):
        return self._executor

    def stop(self):
        self.stopped += 1
