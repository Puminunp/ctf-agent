"""Loads KEY=VALUE pairs from a local, git-ignored .env file into the controller's environment.

Secrets live only here and in the controller process. Nothing in this module prints a value.
"""

from __future__ import annotations

import os
from pathlib import Path


def read_env_file(path: str | Path) -> dict[str, str]:
    """Parse a .env file. Blank lines and # comments are skipped; quotes around a value are removed."""
    out: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load_env_file(path: str | Path, override: bool = False) -> list[str]:
    """Copy the file's non-empty values into os.environ. Returns the names that were set, never the values."""
    names = []
    for key, value in read_env_file(path).items():
        if not value:
            continue
        if override or not os.environ.get(key):
            os.environ[key] = value
            names.append(key)
    return names
