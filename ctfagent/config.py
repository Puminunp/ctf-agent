"""Frozen run configuration. The controller owns every limit; the model cannot change them."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
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
    # Retry policy for 429/5xx. Defaults reproduce the frozen baseline (frozen-eval-v1).
    llm_backoff_cap_s: float = 8.0         # longest single wait; wait = min(2**attempt, cap)
    llm_honor_retry_after: bool = False    # obey the gateway's Retry-After header (capped by the cap)
    llm_retry_budget_s: float = 1e9        # total time one call may spend waiting between retries
    # Competition controls. The defaults switch them off, so the A4 configurations behave as before.
    max_cost_usd: float = 0.0              # spend cap for one attempt, from the prices below (0 = no cap)
    keep_tool_outputs: int = 0             # newest tool results sent back in full (0 = all of them)
    old_output_chars: int = 600            # what an older tool result is shortened to


@dataclass(frozen=True)
class EnvironmentConfig:
    solver_image: str = "ctf-solver:latest"    # built from docker/solver/Dockerfile
    target_host: str = "target"                # service name the solver uses to reach the target
    workdir: str = "/workspace"
    memory: str = "2g"
    cpus: float = 1.0
    pids_limit: int = 512
    project_prefix: str = "ctf"
    platform: str = ""                         # e.g. "linux/amd64"; empty leaves the choice to Docker
    remote_network: str = "forward"            # remote targets: "forward" (only the target is reachable) or "open"


@dataclass(frozen=True)
class Pricing:
    """What the model costs, for the spend cap and the cost column. Zero means "not priced"."""
    input_usd_per_mtok: float = 0.0
    output_usd_per_mtok: float = 0.0

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_usd_per_mtok + output_tokens * self.output_usd_per_mtok) / 1_000_000


@dataclass(frozen=True)
class Rung:
    """One step on the model ladder: which model to try, what it costs, and how much to spend on it.

    A zero or None override inherits the base config's value. `label` tags the run records (and the
    run_id) for this rung; it defaults to a short slug of the model name.
    """
    model: str
    input_usd_per_mtok: float = 0.0
    output_usd_per_mtok: float = 0.0
    max_cost_usd: float = 0.0              # per-attempt spend cap for this rung (0 = inherit base limit)
    label: str = ""
    wall_clock_s: float | None = None
    max_steps: int | None = None
    max_total_tokens: int | None = None
    max_wrong_flags: int | None = None


@dataclass(frozen=True)
class Escalation:
    """How to climb the ladder. An empty ladder means "one model only" — the base config, unchanged.

    Policy: always probe the cheapest model first (it costs pennies and sometimes just solves it), and
    step up only when an attempt fails for a reason a stronger model could fix — not on a timer. An
    infrastructure error never escalates (a bigger model will not fix the gateway), and a rung is only
    started when the remaining laptop budget can fully fund its per-attempt cap.
    """
    ladder: tuple = ()                                   # cheapest first; tuple[Rung, ...]
    start_rung_by_difficulty: dict = field(default_factory=dict)   # e.g. {"insane": 1} to skip Haiku
    escalate_on: tuple = ("no_flag", "budget_exhausted", "timeout", "wrong_flag")
    reserve_usd: float = 0.0               # keep this much in reserve before escalating to a pricier rung


@dataclass(frozen=True)
class Config:
    config_id: str = "agent"
    model: str = ""                  # must be set to an allowed Duke gateway model ID
    temperature: float = 0.0
    system_prompt_file: str = "prompts/system.md"
    repeat_hint: bool = False        # hypothesis switch: nudge the model after identical repeated calls
    limits: Limits = field(default_factory=Limits)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    pricing: Pricing = field(default_factory=Pricing)
    escalation: Escalation = field(default_factory=Escalation)
    flag_format: str = ""            # regular expression a candidate must match before it is sent for checking
    handoff_notes: bool = False      # ask for a short summary when an attempt runs out, for the next attempt
    provider: str = "gateway"        # "gateway" = OpenAI-compatible Duke gateway; "anthropic" = direct Claude API
    effort: str = "high"             # reasoning effort for the anthropic provider (low|medium|high|xhigh|max)
    keep_target: bool = False        # swarm mode: do NOT stop the shared HTB target container on cleanup

    def to_dict(self) -> dict:
        return asdict(self)

    def with_rung(self, rung: Rung) -> "Config":
        """A copy of this config pinned to one ladder rung: its model, prices and per-attempt caps.

        Everything else (environment, flag format, prompt, handoff) carries over, so the trusted
        controller behaves identically; only the model, the prices and the limit overrides change.
        """
        limits = replace(
            self.limits,
            max_cost_usd=rung.max_cost_usd or self.limits.max_cost_usd,
            wall_clock_s=self.limits.wall_clock_s if rung.wall_clock_s is None else rung.wall_clock_s,
            max_steps=self.limits.max_steps if rung.max_steps is None else rung.max_steps,
            max_total_tokens=(self.limits.max_total_tokens if rung.max_total_tokens is None
                              else rung.max_total_tokens),
            max_wrong_flags=(self.limits.max_wrong_flags if rung.max_wrong_flags is None
                             else rung.max_wrong_flags),
        )
        label = rung.label or rung.model.replace("claude-", "").split("-")[0] or rung.model
        return replace(self, model=rung.model, config_id=f"{self.config_id}-{label}", limits=limits,
                       pricing=Pricing(rung.input_usd_per_mtok, rung.output_usd_per_mtok))


def load_config(path: str | Path) -> Config:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    limits = Limits(**raw.pop("limits", {}))
    env = EnvironmentConfig(**raw.pop("environment", {}))
    pricing = Pricing(**raw.pop("pricing", {}))
    escalation = _load_escalation(raw.pop("escalation", {}))
    return Config(limits=limits, environment=env, pricing=pricing, escalation=escalation, **raw)


def _load_escalation(raw: dict) -> Escalation:
    if not raw:
        return Escalation()
    raw = dict(raw)
    ladder = tuple(Rung(**r) for r in raw.pop("ladder", []))
    if "escalate_on" in raw:
        raw["escalate_on"] = tuple(raw["escalate_on"])
    return Escalation(ladder=ladder, **raw)


def fingerprint(cfg: Config, system_prompt: str) -> str:
    """Stable hash of everything that defines this configuration, for the run records."""
    blob = json.dumps({"config": cfg.to_dict(), "prompt": system_prompt}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
