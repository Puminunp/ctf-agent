import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ctfagent.config import Config, EnvironmentConfig, Limits  # noqa: E402
from ctfagent.llm import LLMResponse, ToolCall  # noqa: E402


def call(name: str, **args) -> ToolCall:
    return ToolCall(id=f"c-{name}-{abs(hash(json.dumps(args, sort_keys=True))) % 10**6}", name=name,
                    arguments_raw=json.dumps(args))


def reply(*calls: ToolCall, content=None, inp=100, out=20) -> LLMResponse:
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [{"id": c.id, "type": "function",
                              "function": {"name": c.name, "arguments": c.arguments_raw}} for c in calls]
    return LLMResponse(content=content, tool_calls=list(calls), assistant_message=msg,
                       input_tokens=inp, output_tokens=out, finish_reason="tool_calls", latency_s=0.01)


def make_cfg(**limit_overrides) -> Config:
    base = dict(wall_clock_s=100.0, max_steps=10, max_total_tokens=10_000, max_wrong_flags=3,
                max_idle_turns=2, tool_timeout_s=30.0, max_output_chars=200)
    base.update(limit_overrides)
    return Config(model="test-model", limits=Limits(**base), environment=EnvironmentConfig())


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s
