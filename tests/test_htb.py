import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ctfagent.config import Config, EnvironmentConfig, Escalation, Limits, Rung, load_config  # noqa: E402
from ctfagent.environment import FakeEnvironment, render_remote_compose  # noqa: E402
from ctfagent.escalation import plan_rungs, run_challenge_ladder  # noqa: E402
from ctfagent.gateway_budget import budget_remaining  # noqa: E402
from ctfagent.htb import HtbError, parse_body, unwrap_tool_result  # noqa: E402
from ctfagent.htb_challenges import (  # noqa: E402
    HtbCatalog, HtbController, HtbVerifier, classify_submission)
from ctfagent.verifier import VerifierUnavailable  # noqa: E402


class FakeMcp:
    """Scripted MCP client: maps a tool name to a value or a callable, or a list consumed in order."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def call_tool(self, name, arguments=None, raise_on_tool_error=True):
        self.calls.append((name, arguments))
        item = self.script[name]
        if isinstance(item, list):
            item = item.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(arguments) if callable(item) else item


class ClassifyTest(unittest.TestCase):
    def test_correct_and_wrong_words(self):
        self.assertTrue(classify_submission({"message": "Congratulations, correct flag!"}))
        self.assertFalse(classify_submission({"message": "Incorrect flag, try again"}))
        self.assertTrue(classify_submission("Well done"))
        self.assertFalse(classify_submission("That is wrong"))

    def test_boolean_fields_win(self):
        self.assertTrue(classify_submission({"correct": True, "message": "whatever"}))
        self.assertFalse(classify_submission({"success": False}))

    def test_rate_limit_is_unavailable(self):
        with self.assertRaises(VerifierUnavailable):
            classify_submission({"status_code": 429, "error": "slow down"})

    def test_unreadable_is_unavailable(self):
        with self.assertRaises(VerifierUnavailable):
            classify_submission({"foo": "bar"})


class VerifierTest(unittest.TestCase):
    def test_correct(self):
        v = HtbVerifier(FakeMcp({"submit_flag": {"message": "Correct!"}}), 1)
        self.assertTrue(v.verify("HTB{x}"))

    def test_wrong(self):
        v = HtbVerifier(FakeMcp({"submit_flag": {"message": "Incorrect"}}), 1)
        self.assertFalse(v.verify("HTB{x}"))

    def test_transport_failure_is_unavailable(self):
        v = HtbVerifier(FakeMcp({"submit_flag": HtbError("connection problem")}), 1)
        with self.assertRaises(VerifierUnavailable):
            v.verify("HTB{x}")


class CatalogStartTest(unittest.TestCase):
    def test_polls_until_ready(self):
        statuses = [{"status": "starting"},
                    {"status": "ready", "hostname": "10.0.0.5", "ports": [31337]}]
        mcp = FakeMcp({"start_container": {"message": "Container starting."},
                       "container_status": statuses})
        cat = HtbCatalog(mcp, 3755, files_root="/tmp/none", poll_s=0, sleep=lambda s: None)
        host, ports = cat.start(99)
        self.assertEqual((host, ports), ("10.0.0.5", [31337]))

    def test_timeout_raises(self):
        mcp = FakeMcp({"start_container": {"ok": 1},
                       "container_status": lambda a: {"status": "starting"}})
        cat = HtbCatalog(mcp, 3755, files_root="/tmp/none", start_timeout_s=0.01, poll_s=0,
                         sleep=lambda s: None)
        with self.assertRaises(HtbError):
            cat.start(99)

    def test_retries_transient_server_error_then_succeeds(self):
        mcp = FakeMcp({"start_container": [{"error": "Server Error", "status_code": 500},
                                           {"message": "Container starting."}],
                       "container_status": [{"status": "ready", "hostname": "10.0.0.9", "ports": [1337]}]})
        cat = HtbCatalog(mcp, 3755, files_root="/tmp/none", poll_s=0, sleep=lambda s: None)
        host, ports = cat.start(99)
        self.assertEqual((host, ports), ("10.0.0.9", [1337]))
        self.assertEqual(sum(1 for c in mcp.calls if c[0] == "start_container"), 2)  # retried once

    def test_persistent_server_error_raises(self):
        mcp = FakeMcp({"start_container": lambda a: {"error": "Server Error", "status_code": 500}})
        cat = HtbCatalog(mcp, 3755, files_root="/tmp/none", poll_s=0, sleep=lambda s: None,
                         start_retries=2)
        with self.assertRaises(HtbError):
            cat.start(99)
        self.assertEqual(sum(1 for c in mcp.calls if c[0] == "start_container"), 3)  # 1 try + 2 retries


class RemoteComposeTest(unittest.TestCase):
    def setUp(self):
        self.env = EnvironmentConfig(platform="linux/amd64")

    def test_forward_relays_only_the_target(self):
        text = render_remote_compose(self.env, "203.0.113.9", [1337, 8080])
        self.assertIn("ctf_internal", text)
        self.assertIn("internal: true", text)
        self.assertIn("203.0.113.9", text)        # only inside the forwarder command
        self.assertIn('"1337"', text)
        self.assertIn("linux/amd64", text)

    def test_open_gives_egress_no_target(self):
        text = render_remote_compose(EnvironmentConfig(remote_network="open"), "203.0.113.9", [1337])
        self.assertIn("ctf_egress", text)
        self.assertNotIn("203.0.113.9", text)     # the solver dials the real host itself
        self.assertNotIn("internal: true", text)

    def test_no_target_is_offline(self):
        self.assertIn("network_mode: none", render_remote_compose(self.env, None, []))

    def test_unknown_mode_raises(self):
        from ctfagent.environment import EnvironmentError_
        with self.assertRaises(EnvironmentError_):
            render_remote_compose(EnvironmentConfig(remote_network="sideways"), "h", [1])


class StubCatalog:
    def __init__(self):
        self.stopped = []

    def find(self, cid):
        return {"id": cid, "name": "DNS Dossier", "challenge_category_id": 2, "difficulty": "easy",
                "points": 675, "hasDocker": 1, "filename": "", "description": "A web tool."}

    def start(self, cid):
        return "198.51.100.7", [37225]

    def download_files(self, cid, filename):
        return None, []

    def stop(self, cid):
        self.stopped.append(cid)


def make_cfg():
    return Config(config_id="agent-htb", model="m", limits=Limits(), environment=EnvironmentConfig())


class ControllerPrepareTest(unittest.TestCase):
    def test_prepare_builds_remote_task(self):
        from ctfagent.trace import Trace
        with tempfile.TemporaryDirectory() as d:
            env = FakeEnvironment()
            ctl = HtbController(make_cfg(), "sys", llm=None, env=env, out_dir=d, loader=None,
                                catalog=StubCatalog(), mcp=None)
            detail = {}
            ready = ctl.prepare("79390", Trace(None), detail)
            self.assertEqual(ready.allowed_hosts, {"target"})
            self.assertIn("target:37225", ready.task_prompt)
            self.assertIn("DNS Dossier", ready.task_prompt)
            self.assertEqual(detail["points"], 675)
            self.assertEqual(detail["target"], {"host": "198.51.100.7", "ports": [37225]})
            self.assertEqual(env.resets, 1)

    def test_cleanup_stops_container(self):
        from ctfagent.trace import Trace
        with tempfile.TemporaryDirectory() as d:
            cat = StubCatalog()
            ctl = HtbController(make_cfg(), "sys", llm=None, env=FakeEnvironment(), out_dir=d, loader=None,
                                catalog=cat, mcp=None)
            ctl.prepare("79390", Trace(None), {})
            ctl.cleanup("79390", {})
            self.assertEqual(cat.stopped, [79390])


class ProtocolHelpersTest(unittest.TestCase):
    def test_parse_sse_takes_last_data_line(self):
        body = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":1}}\n\n'
        self.assertEqual(parse_body("text/event-stream", body), {"jsonrpc": "2.0", "id": 1, "result": {"ok": 1}})

    def test_unwrap_prefers_structured(self):
        self.assertEqual(unwrap_tool_result({"structuredContent": {"result": [1, 2]}}), [1, 2])

    def test_unwrap_parses_text_json(self):
        self.assertEqual(unwrap_tool_result({"content": [{"type": "text", "text": '{"a":1}'}]}), {"a": 1})


def _esc_cfg():
    ladder = (Rung("claude-haiku-5-5", 0.05, 0.25, max_cost_usd=0.5),
              Rung("claude-sonnet-5-5", 1.0, 5.0, max_cost_usd=2.0),
              Rung("claude-opus-5-5", 2.0, 10.0, max_cost_usd=5.0))
    esc = Escalation(ladder=ladder, start_rung_by_difficulty={"insane": 1})
    return Config(config_id="agent-htb", model="claude-haiku-5-5", limits=Limits(max_cost_usd=1.0),
                  environment=EnvironmentConfig(platform="linux/amd64"), escalation=esc)


class WithRungTest(unittest.TestCase):
    def test_overrides_model_pricing_and_caps_inherits_rest(self):
        cfg = _esc_cfg()
        r = cfg.with_rung(Rung("claude-opus-5-5", 2.0, 10.0, max_cost_usd=5.0, max_steps=40))
        self.assertEqual(r.model, "claude-opus-5-5")
        self.assertEqual(r.config_id, "agent-htb-opus")
        self.assertEqual(r.pricing.input_usd_per_mtok, 2.0)
        self.assertEqual(r.pricing.output_usd_per_mtok, 10.0)
        self.assertEqual(r.limits.max_cost_usd, 5.0)
        self.assertEqual(r.limits.max_steps, 40)
        self.assertEqual(r.limits.max_wrong_flags, cfg.limits.max_wrong_flags)  # inherited
        self.assertEqual(r.environment.platform, "linux/amd64")                 # inherited

    def test_label_defaults_to_model_slug(self):
        r = _esc_cfg().with_rung(Rung("claude-sonnet-5-5", 1.0, 5.0))
        self.assertEqual(r.config_id, "agent-htb-sonnet")
        self.assertEqual(r.limits.max_cost_usd, 1.0)  # rung has no cap -> inherits base 1.0


class PlanRungsTest(unittest.TestCase):
    def test_default_and_difficulty_start(self):
        esc = _esc_cfg().escalation
        self.assertEqual(plan_rungs(esc, "easy"), [0, 1, 2])
        self.assertEqual(plan_rungs(esc, "insane"), [1, 2])
        self.assertEqual(plan_rungs(esc, ""), [0, 1, 2])

    def test_no_ladder_is_empty(self):
        self.assertEqual(plan_rungs(Escalation(), "easy"), [])


class LadderDriverTest(unittest.TestCase):
    def _run(self, cfg, run_rung, *, spent=0.0, budget=12.0, recorded=None, difficulty="easy"):
        return run_challenge_ladder(cfg, 79390, 1, difficulty=difficulty, spent_fn=lambda: spent,
                                    laptop_budget=budget, recorded=recorded or set(),
                                    run_rung=run_rung, log=lambda m: None)

    def test_stops_on_first_solve(self):
        calls = []

        def run_rung(rc):
            calls.append(rc.model)
            return {"verified": True, "status": "solved"}
        rec = self._run(_esc_cfg(), run_rung)
        self.assertEqual(calls, ["claude-haiku-5-5"])
        self.assertTrue(rec["verified"])

    def test_escalates_on_failure(self):
        calls = []
        out = {"claude-haiku-5-5": {"verified": False, "status": "no_flag"},
               "claude-sonnet-5-5": {"verified": True, "status": "solved"}}

        def run_rung(rc):
            calls.append(rc.model)
            return out[rc.model]
        rec = self._run(_esc_cfg(), run_rung)
        self.assertEqual(calls, ["claude-haiku-5-5", "claude-sonnet-5-5"])
        self.assertTrue(rec["verified"])

    def test_skips_rung_it_cannot_fund(self):
        calls = []

        def run_rung(rc):
            calls.append(rc.model)
            return {"verified": False, "status": "no_flag"}
        # $1.50 left: Haiku (cap 0.50) runs and fails; Sonnet (cap 2.00) is unaffordable -> stop.
        self._run(_esc_cfg(), run_rung, spent=10.5)
        self.assertEqual(calls, ["claude-haiku-5-5"])

    def test_terminal_status_does_not_escalate(self):
        calls = []

        def run_rung(rc):
            calls.append(rc.model)
            return {"verified": False, "status": "scope_violation"}
        self._run(_esc_cfg(), run_rung)
        self.assertEqual(calls, ["claude-haiku-5-5"])

    def test_infrastructure_error_does_not_escalate(self):
        calls = []

        def run_rung(rc):
            calls.append(rc.model)
            return {"verified": False, "status": "infrastructure_error"}
        self._run(_esc_cfg(), run_rung)
        self.assertEqual(calls, ["claude-haiku-5-5"])

    def test_recorded_rung_is_skipped(self):
        calls = []

        def run_rung(rc):
            calls.append(rc.model)
            return {"verified": True, "status": "solved"}
        rec = self._run(_esc_cfg(), run_rung, recorded={"agent-htb-haiku-79390-t1"})
        self.assertEqual(calls, ["claude-sonnet-5-5"])  # Haiku skipped as already recorded
        self.assertTrue(rec["verified"])

    def test_no_ladder_runs_base_model_once(self):
        cfg = Config(config_id="agent-htb", model="claude-haiku-5-5", limits=Limits(max_cost_usd=1.0))
        calls = []

        def run_rung(rc):
            calls.append(rc.model)
            return {"verified": False, "status": "no_flag"}
        self._run(cfg, run_rung)
        self.assertEqual(calls, ["claude-haiku-5-5"])


class BudgetRemainingTest(unittest.TestCase):
    def test_subtracts_spend_from_budget(self):
        self.assertAlmostEqual(budget_remaining({"max_budget": 1.0, "spend": 0.25}), 0.75)

    def test_no_max_budget_is_none(self):
        self.assertIsNone(budget_remaining({"spend": 5.0}))
        self.assertIsNone(budget_remaining({"max_budget": None, "spend": 5.0}))

    def test_overspend_clamps_to_zero(self):
        self.assertEqual(budget_remaining({"max_budget": 25.0, "spend": 30.0}), 0.0)


class ConfigLoadEscalationTest(unittest.TestCase):
    def test_parses_escalation_block(self):
        data = {"config_id": "x", "model": "claude-haiku-5-5",
                "escalation": {"ladder": [
                    {"model": "claude-haiku-5-5", "input_usd_per_mtok": 0.05, "output_usd_per_mtok": 0.25,
                     "max_cost_usd": 0.5},
                    {"model": "claude-opus-5-5", "input_usd_per_mtok": 2.0, "output_usd_per_mtok": 10.0,
                     "max_cost_usd": 5.0}],
                    "escalate_on": ["no_flag"], "start_rung_by_difficulty": {"insane": 1}}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        cfg = load_config(path)
        self.assertEqual(len(cfg.escalation.ladder), 2)
        self.assertEqual(cfg.escalation.ladder[1].model, "claude-opus-5-5")
        self.assertEqual(cfg.escalation.ladder[1].max_cost_usd, 5.0)
        self.assertEqual(cfg.escalation.escalate_on, ("no_flag",))
        self.assertEqual(cfg.escalation.start_rung_by_difficulty, {"insane": 1})

    def test_real_htb_config_loads(self):
        path = Path(__file__).resolve().parent.parent / "configs" / "agent-htb.json"
        cfg = load_config(str(path))
        self.assertEqual([r.model for r in cfg.escalation.ladder],
                         ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"])
        # policy: auto-climb is OFF — Haiku only unless a human authorizes a specific climb
        self.assertEqual(cfg.escalation.escalate_on, ())
        self.assertEqual(cfg.escalation.start_rung_by_difficulty, {})


if __name__ == "__main__":
    unittest.main()
