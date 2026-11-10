import unittest

from helpers import FakeClock, call, make_cfg, reply
from ctfagent.agent import run_attempt
from ctfagent.executor import ExecResult, FakeExecutor
from ctfagent.llm import LLMError, ScriptedLLM
from ctfagent.trace import Trace
from ctfagent.verifier import HashVerifier

FLAG = "flag{unit_test_value}"


def run(responses, executor=None, cfg=None, clock=None, hosts=frozenset({"target"})):
    cfg = cfg or make_cfg()
    trace = Trace(None)
    res = run_attempt(cfg=cfg, llm=ScriptedLLM(list(responses)), executor=executor or FakeExecutor(),
                      verifier=HashVerifier(FLAG), trace=trace, system_prompt="sys", task_prompt="task",
                      allowed_hosts=set(hosts), clock=clock or FakeClock())
    return res, trace


class AttemptLoop(unittest.TestCase):
    def test_solve_uses_tool_result_then_submits(self):
        ex = FakeExecutor({"cat note.txt": ExecResult(0, FLAG, False, 0.1)})
        res, trace = run([reply(call("run_shell", command="cat note.txt")),
                          reply(call("submit_flag", flag=FLAG))], ex)
        self.assertEqual((res.status, res.verified, res.stop_reason), ("solved", True, "verified"))
        self.assertEqual((res.input_tokens, res.output_tokens, res.llm_calls, res.tool_calls), (200, 40, 2, 2))

    def test_verified_flag_is_not_written_to_trace(self):
        _, trace = run([reply(call("submit_flag", flag=FLAG))])
        self.assertNotIn(FLAG, str(trace.events))

    def test_wrong_flag_is_logged_and_limit_ends_attempt(self):
        res, trace = run([reply(call("submit_flag", flag=f"flag{{wrong{i}}}")) for i in range(5)])
        self.assertEqual((res.status, res.wrong_flags, res.stop_reason), ("wrong_flag", 3, "wrong_flag_limit"))
        subs = [e for e in trace.events if e["type"] == "submission"]
        self.assertEqual([s["verified"] for s in subs], [False] * 3)
        self.assertIn("flag{wrong0}", subs[0]["candidate"])

    def test_step_limit(self):
        res, _ = run([reply(call("run_shell", command=f"echo {i}")) for i in range(5)], cfg=make_cfg(max_steps=3))
        self.assertEqual((res.status, res.stop_reason, res.steps), ("budget_exhausted", "step_limit", 3))

    def test_token_limit(self):
        res, _ = run([reply(call("run_shell", command=f"echo {i}"), inp=4000, out=1000) for i in range(5)],
                     cfg=make_cfg(max_total_tokens=8000))
        self.assertEqual((res.status, res.stop_reason), ("budget_exhausted", "token_limit"))

    def test_wall_clock_limit_checked_before_each_model_call(self):
        clock = FakeClock()
        ex = FakeExecutor(delay_s=1, sleep=lambda s: clock.advance(60))
        res, _ = run([reply(call("run_shell", command=f"echo {i}")) for i in range(5)], ex,
                     cfg=make_cfg(wall_clock_s=100), clock=clock)
        self.assertEqual((res.status, res.stop_reason), ("timeout", "wall_clock_limit"))
        self.assertEqual(res.llm_calls, 2)

    def test_tool_timeout_is_capped_by_controller_and_remaining_time(self):
        ex = FakeExecutor()
        run([reply(call("run_shell", command="sleep 999", timeout_s=9999))], ex,
            cfg=make_cfg(tool_timeout_s=30, max_steps=1))
        self.assertEqual(ex.seen[0][1], 30)

    def test_model_stops_without_tools(self):
        res, _ = run([reply(content="giving up"), reply(content="still giving up")])
        self.assertEqual((res.status, res.stop_reason), ("no_flag", "model_stopped_without_tools"))

    def test_invalid_tool_call_returns_error_and_loop_continues(self):
        res, trace = run([reply(call("run_shell", command="")), reply(call("nope")),
                          reply(call("submit_flag", flag=FLAG))])
        self.assertTrue(res.verified)
        self.assertEqual(len([e for e in trace.events if e["type"] == "tool_error"]), 2)

    def test_long_output_is_truncated_and_flagged(self):
        ex = FakeExecutor({"big": ExecResult(0, "x" * 1000, False, 0.1)})
        _, trace = run([reply(call("run_shell", command="big"))], ex, cfg=make_cfg(max_steps=1))
        ev = [e for e in trace.events if e["type"] == "tool_result"][0]
        self.assertTrue(ev["truncated"])
        self.assertLess(len(ev["output"]), 400)

    def test_scope_violation_stops_attempt_and_command_never_runs(self):
        ex = FakeExecutor()
        res, trace = run([reply(call("run_shell", command="curl http://example.com/answer"))], ex)
        self.assertEqual((res.status, ex.seen), ("scope_violation", []))
        self.assertEqual(trace.events[-2]["type"], "scope_violation")

    def test_allowed_target_is_reachable(self):
        ex = FakeExecutor()
        run([reply(call("run_shell", command="curl http://target:8080/"))], ex, cfg=make_cfg(max_steps=1))
        self.assertEqual(len(ex.seen), 1)

    def test_llm_failure_is_infrastructure_error(self):
        class Boom:
            def complete(self, *a):
                raise LLMError("gateway call failed: HTTP 503")
        trace = Trace(None)
        res = run_attempt(cfg=make_cfg(), llm=Boom(), executor=FakeExecutor(), verifier=HashVerifier(FLAG),
                          trace=trace, system_prompt="s", task_prompt="t", allowed_hosts=set(), clock=FakeClock())
        self.assertEqual(res.status, "infrastructure_error")

    def test_missing_usage_stays_null(self):
        r = reply(call("submit_flag", flag=FLAG))
        r.input_tokens = r.output_tokens = None
        res, _ = run([r])
        self.assertEqual((res.input_tokens, res.output_tokens, res.usage_complete), (None, None, False))

    def test_repeat_hint_only_when_enabled(self):
        script = [reply(call("run_shell", command="ls")) for _ in range(4)]
        _, t_off = run(script, cfg=make_cfg())
        cfg_on = make_cfg()
        object.__setattr__(cfg_on, "repeat_hint", True)
        _, t_on = run(script, cfg=cfg_on)
        flags = lambda t: [e["repeat_hint"] for e in t.events if e["type"] == "tool_result"]
        self.assertEqual(flags(t_off), [False] * 4)
        self.assertEqual(flags(t_on), [False, False, True, True])

    def test_model_output_cannot_raise_limits(self):
        res, _ = run([reply(call("run_shell", command="echo hi", timeout_s=10**9, max_steps=10**9))],
                     cfg=make_cfg(max_steps=1))
        self.assertEqual(res.stop_reason, "step_limit")


if __name__ == "__main__":
    unittest.main()
