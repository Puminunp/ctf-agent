"""Runs solver commands inside the solver container. Never runs model commands on the host."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from typing import Protocol

CAPTURE_BYTES = 200_000


@dataclass
class ExecResult:
    exit_code: int | None
    output: str
    timed_out: bool
    elapsed_s: float


class Executor(Protocol):
    def run(self, command: str, timeout_s: float) -> ExecResult: ...


class DockerExecutor:
    """docker exec into a running solver container.

    The command is wrapped in coreutils `timeout -s KILL` inside the container, and a host-side timer
    backs it up. A host timeout alone would not stop the process, so on host timeout the container is
    restarted. The controller still resets the whole environment between attempts.
    """

    def __init__(self, container: str, workdir: str = "/workspace", docker: str = "docker"):
        self.container = container
        self.workdir = workdir
        self.docker = docker

    def run(self, command: str, timeout_s: float) -> ExecResult:
        t = max(1, int(timeout_s))
        inner = f"set -o pipefail; bash -c \"$1\" 2>&1 | head -c {CAPTURE_BYTES}"
        argv = [self.docker, "exec", "-i", "-w", self.workdir, self.container,
                "timeout", "-s", "KILL", str(t), "bash", "-c", inner, "_", command]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(argv, capture_output=True, timeout=t + 5, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            subprocess.run([self.docker, "restart", "-t", "1", self.container], capture_output=True)
            return ExecResult(None, f"[command exceeded {t}s and the sandbox was restarted]", True,
                              time.monotonic() - t0)
        elapsed = time.monotonic() - t0
        text = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        timed_out = proc.returncode == 137 and elapsed >= t * 0.95
        if timed_out:
            text += f"\n[command killed after {t}s]"
        return ExecResult(proc.returncode, text, timed_out, elapsed)


@dataclass
class FakeExecutor:
    """Test double. Maps a command to a canned result, or runs a callable."""
    script: dict = field(default_factory=dict)
    default: ExecResult = field(default_factory=lambda: ExecResult(0, "", False, 0.01))
    seen: list = field(default_factory=list)
    delay_s: float = 0.0
    sleep: object = time.sleep

    def run(self, command: str, timeout_s: float) -> ExecResult:
        self.seen.append((command, timeout_s))
        if self.delay_s:
            self.sleep(self.delay_s)
        hit = self.script.get(command, self.default)
        return hit(command) if callable(hit) else hit
