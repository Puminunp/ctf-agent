"""Target and solver lifecycle, run by the trusted controller.

ComposeEnvironment generates one compose file per attempt. There is no instructor-supplied compose
file (the professor confirmed on Nov 9 that the guide's kit was an artifact), so the controls are ours:

  * solver: non-root, no sudo, all capabilities dropped, no-new-privileges, memory/CPU/pid limits,
    attached ONLY to an `internal: true` network (or `network_mode: none` when there is no target).
  * target: the challenge's published image, no privileged mode, no Docker socket, no published ports.
  * the generated file never mounts /var/run/docker.sock and never publishes a port.

The upstream challenge docker-compose.yml files do mount the socket and publish ports, so they are
only read to find the image name; they are never run.
"""

from __future__ import annotations

import hashlib
import io
import re
import subprocess
import tarfile
import uuid
from pathlib import Path
from typing import Protocol

from .config import EnvironmentConfig
from .executor import DockerExecutor, Executor, FakeExecutor


class EnvironmentError_(Exception):
    pass


class Environment(Protocol):
    def reset(self, challenge_id: str, chal) -> str: ...
    def export(self, files: list[Path], workdir: str) -> list[dict]: ...
    def executor(self) -> Executor: ...
    def stop(self) -> None: ...


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def target_image(challenge_dir: Path) -> str:
    """Read the published image name from the challenge's own compose file (the file itself is never run)."""
    for name in ("docker-compose.yml", "docker-compose.yaml"):
        p = Path(challenge_dir) / name
        if p.is_file():
            m = re.search(r"^\s*image:\s*['\"]?([^'\"\s]+)", p.read_text(encoding="utf-8"), re.MULTILINE)
            if m:
                return m.group(1)
            raise EnvironmentError_(f"{p} has no 'image:' line (a build-only challenge is not supported)")
    raise EnvironmentError_(f"no docker-compose file in {challenge_dir}")


def render_compose(cfg: EnvironmentConfig, target_image_name: str | None) -> str:
    """The compose file for one attempt. Pure function so it can be unit-tested without Docker."""
    solver_net = ("    networks:\n      - ctf_internal\n" if target_image_name
                  else "    network_mode: none\n")
    text = f"""services:
  solver:
    image: {cfg.solver_image}
    command: ["sleep", "infinity"]
    user: "1000:1000"
    working_dir: {cfg.workdir}
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    mem_limit: {cfg.memory}
    cpus: {cfg.cpus}
    pids_limit: {cfg.pids_limit}
{solver_net}"""
    if target_image_name:
        text += f"""  {cfg.target_host}:
    image: {target_image_name}
    security_opt: ["no-new-privileges:true"]
    mem_limit: {cfg.memory}
    cpus: {cfg.cpus}
    pids_limit: {cfg.pids_limit}
    networks:
      - ctf_internal
networks:
  ctf_internal:
    internal: true
"""
    return text


class ComposeEnvironment:
    def __init__(self, cfg: EnvironmentConfig, work_dir: str | Path = "runs/compose", docker: str = "docker"):
        self.cfg = cfg
        self.work_dir = Path(work_dir)
        self.docker = docker
        self._file: Path | None = None
        self._project: str | None = None
        self._container: str | None = None

    def _compose(self, args: list[str], timeout: float = 600):
        assert self._file and self._project
        proc = subprocess.run([self.docker, "compose", "-p", self._project, "-f", str(self._file), *args],
                              capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise EnvironmentError_(f"compose {' '.join(args)} failed: {proc.stderr.strip()[-600:]}")
        return proc.stdout

    def reset(self, challenge_id: str, chal) -> str:
        """Tear down everything including volumes, then start a clean solver (and target)."""
        image = target_image(Path(chal.challenge_dir)) if getattr(chal, "container", False) else None
        self._project = re.sub(r"[^a-z0-9_-]", "-", f"{self.cfg.project_prefix}-{challenge_id}".lower())
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._file = self.work_dir / f"{self._project}.yaml"
        self._file.write_text(render_compose(self.cfg, image), encoding="utf-8")
        self._compose(["down", "-v", "--remove-orphans"])
        self._compose(["up", "-d", "--wait", "--force-recreate"])
        cid = self._compose(["ps", "-q", "solver"]).strip()
        if not cid:
            raise EnvironmentError_("solver container is not running")
        self._container = cid.splitlines()[0]
        return f"fresh-{uuid.uuid4().hex[:8]}"

    def export(self, files: list[Path], workdir: str) -> list[dict]:
        """Stream the contestant files in as a tar archive, extracted by the unprivileged solver user.

        The solver has no capabilities (not even root could chown), so files must be created by the
        solver user itself. Windows files carry no exec bit, so every file is given mode 0755.
        """
        assert self._container, "reset() must run first"
        buf = io.BytesIO()
        inventory = []
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for p in files:
                info = tarfile.TarInfo(name=p.name)
                info.size, info.mode, info.mtime = p.stat().st_size, 0o755, int(p.stat().st_mtime)
                with p.open("rb") as fh:
                    tar.addfile(info, fh)
                inventory.append({"file": p.name, "sha256": sha256_file(p), "bytes": p.stat().st_size})
        proc = subprocess.run([self.docker, "exec", "-i", self._container, "tar", "-x", "-C", workdir, "-f", "-"],
                              input=buf.getvalue(), capture_output=True, timeout=120)
        if proc.returncode != 0:
            raise EnvironmentError_(f"exporting files failed: {proc.stderr.decode(errors='replace')[-300:]}")
        return inventory

    def executor(self) -> Executor:
        assert self._container, "reset() must run first"
        return DockerExecutor(self._container, self.cfg.workdir, self.docker)

    def stop(self) -> None:
        if self._file:
            try:
                self._compose(["down", "-v", "--remove-orphans"])
            except EnvironmentError_:
                pass


class FakeEnvironment:
    """Test double with the same interface."""

    def __init__(self, executor: Executor | None = None, fail_on: str | None = None):
        self._executor = executor or FakeExecutor()
        self.fail_on = fail_on
        self.resets = 0
        self.stopped = 0

    def reset(self, challenge_id, chal=None):
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
