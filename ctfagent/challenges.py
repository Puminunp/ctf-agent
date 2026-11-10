"""Controller-side challenge loading. CTFChallenge objects expose the flag, so they never leave the controller.

ADAPTATION POINT: attribute names below follow the nyuctf 1.1.1 loader as described in the course
guide (name, category, files, flag) plus the fields I expect it to have (description, server_name, port,
challenge_dir). Confirm them against the installed package on your machine before the first run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_CSAW_HOST = re.compile(r"[A-Za-z0-9.-]+\.(?:chal\.)?csaw\.io", re.IGNORECASE)


@dataclass
class Task:
    """Everything the solver is allowed to know."""
    challenge_id: str
    name: str
    category: str
    description: str
    files: list[str]
    target_host: str | None
    target_port: int | None
    allowed_hosts: set[str] = field(default_factory=set)


def sanitize_description(text: str, target_host: str, port: int | None) -> str:
    text = text.replace("{box}", target_host).replace("{port}", str(port) if port else "")
    return _CSAW_HOST.sub(target_host, text)


class Dataset:
    def __init__(self, dataset_json: str):
        from nyuctf.dataset import CTFDataset  # imported lazily: only needed for live runs
        self._ds = CTFDataset(dataset_json=dataset_json)

    def load(self, challenge_id: str):
        from nyuctf.challenge import CTFChallenge
        return CTFChallenge(self._ds.get(challenge_id), self._ds.basedir)


def build_task(challenge_id: str, chal, target_host: str) -> Task:
    server = getattr(chal, "server_name", None)
    port = getattr(chal, "port", None)
    has_service = bool(server or port)
    desc = sanitize_description(str(getattr(chal, "description", "") or ""), target_host, port)
    return Task(
        challenge_id=challenge_id, name=str(chal.name), category=str(chal.category),
        description=desc, files=[str(f) for f in (getattr(chal, "files", None) or [])],
        target_host=target_host if has_service else None,
        target_port=int(port) if port else None,
        allowed_hosts={target_host} if has_service else set(),
    )


def host_file_paths(chal) -> list[Path]:
    base = getattr(chal, "challenge_dir", None) or getattr(chal, "path", None)
    if base is None:
        raise RuntimeError("cannot locate the challenge directory on the loader object")
    paths = [Path(base) / f for f in (getattr(chal, "files", None) or [])]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise RuntimeError(f"contestant files not found: {missing}")
    return paths


def task_prompt(task: Task, workdir: str) -> str:
    lines = [f"Challenge: {task.name} (category: {task.category})", "", task.description.strip(), ""]
    if task.files:
        lines.append(f"Files provided in {workdir}: " + ", ".join(task.files))
    else:
        lines.append("No files are provided.")
    if task.target_host:
        port = f":{task.target_port}" if task.target_port else ""
        lines.append(f"Target service: {task.target_host}{port}")
    else:
        lines.append("There is no network target for this challenge.")
    return "\n".join(lines)
