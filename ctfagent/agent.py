"""The attempt loop. The controller owns the clock, the budgets and the verifier.

Model output cannot change a limit, widen the target scope, or end the attempt except by
submitting a flag the verifier accepts or by stopping without a tool call.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import time
from dataclasses import dataclass, field

from .config import Config
from .executor import Executor
from .llm import LLMError
from .scope import find_violations
from .tools import TOOL_SPECS, check_call, truncate
from .trace import Trace
from .verifier import Verifier

SUCCESS = "solved"


@dataclass
class AttemptResult:
    status: str
    verified: bool
    elapsed_s: float
    input_tokens: int | None
    output_tokens: int | None
    stop_reason: str
    steps: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    wrong_flags: int = 0
    usage_complete: bool = True
    submissions: list = field(default_factory=list)


def run_attempt(*, cfg: Config, llm, executor: Executor, verifier: Verifier, trace: Trace,
                system_prompt: str, task_prompt: str, allowed_hosts: set[str],
                clock=time.monotonic) -> AttemptResult:
    lim = cfg.limits
    start = clock()
    messages: list[dict] = [{"role": "system", "content": system_prompt},
                            {"role": "user", "content": task_prompt}]
    trace.event("attempt_start", config_id=cfg.config_id, model=cfg.model, limits=cfg.limits.__dict__,
                task_prompt=task_prompt)

    in_tok = out_tok = 0
    usage_seen = False
    usage_complete = True
    steps = llm_calls = tool_calls = wrong = idle = 0
    seen_calls: dict[str, int] = {}
    submissions: list[dict] = []
    status, stop_reason, verified = "no_flag", "model_stopped", False

    def elapsed() -> float:
        return clock() - start

    while True:
        if elapsed() >= lim.wall_clock_s:
            status, stop_reason = "timeout", "wall_clock_limit"
            break
        if steps >= lim.max_steps:
            status, stop_reason = "budget_exhausted", "step_limit"
            break
        if in_tok + out_tok >= lim.max_total_tokens:
            status, stop_reason = "budget_exhausted", "token_limit"
            break

        try:
            resp = llm.complete(messages, TOOL_SPECS)
        except LLMError as e:
            status, stop_reason = "infrastructure_error", f"llm_error: {e}"
            trace.event("llm_error", error=str(e))
            break
        llm_calls += 1
        steps += 1
        if resp.input_tokens is None or resp.output_tokens is None:
            usage_complete = False
        if resp.input_tokens is not None:
            in_tok += resp.input_tokens
            usage_seen = True
        if resp.output_tokens is not None:
            out_tok += resp.output_tokens
            usage_seen = True

        # The flag argument is logged only by the submission event, so a verified flag is never
        # written to the trace in the clear.
        logged_calls = [{"id": c.id, "name": c.name,
                         "arguments": "[candidate flag: see submission event]" if c.name == "submit_flag"
                         else c.arguments_raw} for c in resp.tool_calls]
        trace.event("model_response", step=steps, content=resp.content, tool_calls=logged_calls,
                    input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                    finish_reason=resp.finish_reason, latency_s=round(resp.latency_s, 3))
        messages.append(resp.assistant_message)

        if not resp.tool_calls:
            idle += 1
            if idle >= lim.max_idle_turns:
                status, stop_reason = "no_flag", "model_stopped_without_tools"
                break
            messages.append({"role": "user", "content":
                             "No tool call received. Use a tool to make progress, or submit_flag if you have the flag."})
            continue
        idle = 0

        finished = False
        for call in resp.tool_calls:
            tool_calls += 1
            checked = check_call(call.name, call.arguments_raw, lim, cfg.environment.workdir)
            if checked.error:
                obs = f"error: {checked.error}"
                trace.event("tool_error", step=steps, tool=call.name, error=checked.error)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": obs})
                continue
            args = checked.args

            if call.name == "submit_flag":
                ok = verifier.verify(args["flag"])
                digest = hashlib.sha256(args["flag"].encode()).hexdigest()[:12]
                sub = {"step": steps, "verified": ok, "candidate_sha256_12": digest}
                if ok:
                    trace.event("submission", **sub, candidate="[verified flag withheld]")
                    trace.redact_everywhere(args["flag"])  # it may also appear in earlier tool output or text
                    submissions.append(sub)
                    verified, status, stop_reason, finished = True, SUCCESS, "verified", True
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": "correct"})
                    break
                wrong += 1
                trace.event("submission", **sub, candidate=args["flag"])
                submissions.append(sub)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": "incorrect"})
                if wrong >= lim.max_wrong_flags:
                    status, stop_reason, finished = "wrong_flag", "wrong_flag_limit", True
                    break
                continue

            if call.name == "run_shell":
                bad = find_violations(args["command"], allowed_hosts)
                if bad:
                    trace.event("scope_violation", step=steps, command=args["command"], hosts=bad)
                    status, stop_reason, finished = "scope_violation", f"out_of_scope: {', '.join(bad)}", True
                    break
                command = args["command"]
            else:  # read_file
                command = f"head -c {args['max_bytes']} -- {shlex.quote(args['path'])}"

            remaining = lim.wall_clock_s - elapsed()
            if remaining <= 0:
                status, stop_reason, finished = "timeout", "wall_clock_limit", True
                break
            timeout = min(args.get("timeout_s", lim.tool_timeout_s), remaining)
            res = executor.run(command, timeout)
            text, cut = truncate(res.output, lim.max_output_chars)
            obs = f"exit_code: {res.exit_code}\n{text}"

            key = json.dumps([call.name, args], sort_keys=True)
            seen_calls[key] = seen_calls.get(key, 0) + 1
            hint = False
            if cfg.repeat_hint and seen_calls[key] >= 3:
                obs += (f"\n[controller note: this exact call has now run {seen_calls[key]} times. "
                        "Change your approach or use a different tool.]")
                hint = True
            trace.event("tool_result", step=steps, tool=call.name, args=args, exit_code=res.exit_code,
                        output=text, truncated=cut, timed_out=res.timed_out,
                        elapsed_s=round(res.elapsed_s, 3), repeat_hint=hint)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": obs})

        if finished:
            break

    elapsed_s = round(elapsed(), 3)
    result = AttemptResult(
        status=status, verified=verified, elapsed_s=elapsed_s,
        input_tokens=in_tok if usage_seen else None, output_tokens=out_tok if usage_seen else None,
        stop_reason=stop_reason, steps=steps, llm_calls=llm_calls, tool_calls=tool_calls,
        wrong_flags=wrong, usage_complete=usage_complete, submissions=submissions)
    trace.event("attempt_end", status=status, verified=verified, stop_reason=stop_reason, elapsed_s=elapsed_s,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                steps=steps, llm_calls=llm_calls, tool_calls=tool_calls, wrong_flags=wrong,
                usage_complete=usage_complete)
    return result
