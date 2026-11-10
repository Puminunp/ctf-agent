"""Frozen run configuration. The controller owns every limit; the model cannot change them."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    wall_clock_s: float = 900.0      # hard deadline for one attempt (model calls + tools)
    max_steps: int = 60              # model turns
    max_total_tokens: int = 400_000  # known input+output tokens across the attempt
    max_wrong_flags: int = 5         # wrong submissions before the attempt ends
    max_idle_turns: int = 3          # consecutive model turns with no tool call
    tool_timeout_s: float = 60.0     # default and upper bound per tool call
    max_output_chars: int = 8000     # tool output returned to the model
    llm_timeout_s: float = 120.0
    llm_retries: int = 2


@dataclass(frozen=True)
class EnvironmentConfig:
    solver_image: str = "ctf-solver:latest"    # built from docker/solver/Dockerfile
    target_host: str = "target"                # service name the solver uses to reach the target
    workdir: str = "/workspace"
    memory: str = "2g"
    cpus: float = 1.0
    pids_limit: int = 512
    project_prefix: str = "ctf"


@dataclass(frozen=True)
class Config:
    config_id: str = "agent"
    model: str = ""                  # must be set to an allowed Duke gateway model ID
    temperature: float = 0.0
    system_prompt_file: str = "prompts/system.md"
    repeat_hint: bool = False        # hypothesis switch: nudge the model after identical repeated calls
    limits: Limits = field(default_factory=Limits)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)

    def to_dict(self) -> dict:
        return asdict(self)


def load_config(path: str | Path) -> Config:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    limits = Limits(**raw.pop("limits", {}))
    env = EnvironmentConfig(**raw.pop("environment", {}))
    return Config(limits=limits, environment=env, **raw)


def fingerprint(cfg: Config, system_prompt: str) -> str:
    """Stable hash of everything that defines this configuration, for the run records."""
    blob = json.dumps({"config": cfg.to_dict(), "prompt": system_prompt}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
