import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from helpers import call, make_cfg, reply
from ctfagent.controller import A4_FIELDS, Controller
from ctfagent.environment import FakeEnvironment
from ctfagent.executor import FakeExecutor
from ctfagent.llm import ScriptedLLM
from scripts_check import check

FLAG = "flag{controller_test_flag}"


class Controllers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "chal.bin").write_bytes(b"\x00data")
        self.chal = SimpleNamespace(name="demo", category="rev", flag=FLAG, files=["chal.bin"],
                                    description="Find it at {box}:{port}", server_name="x", port=1337,
                                    challenge_dir=self.tmp)

    def controller(self, responses, env=None, out=None):
        self.out = out or self.tmp / "out"
        return Controller(make_cfg(), "sys", ScriptedLLM(responses), env or FakeEnvironment(FakeExecutor()),
                          self.out, lambda cid: self.chal, repo_dir=self.tmp)

    def test_solved_record_matches_a4_schema_and_files_exist(self):
        rec = self.controller([reply(call("submit_flag", flag=FLAG))]).run_one("rev-demo", 1)
        self.assertEqual(list(rec), A4_FIELDS)
        self.assertEqual((rec["status"], rec["verified"], rec["sample_type"], rec["config_id"]),
                         ("solved", True, "live", "agent"))
        self.assertTrue((self.out / rec["trace_file"]).is_file())
        self.assertTrue((self.out / "details" / "agent-rev-demo-t1.json").is_file())
        self.assertEqual(check(self.out / "results.jsonl"), [])

    def test_flag_never_reaches_trace_or_results_files(self):
        self.controller([reply(call("submit_flag", flag=FLAG))]).run_one("rev-demo", 1)
        for p in self.out.rglob("*"):
            if p.is_file():
                self.assertNotIn(FLAG, p.read_text(encoding="utf-8"), p.name)

    def test_task_prompt_is_sanitized_and_has_no_flag(self):
        ctl = self.controller([reply(call("submit_flag", flag=FLAG))])
        ctl.run_one("rev-demo", 1)
        events = [json.loads(l) for l in (self.out / "traces" / "agent-rev-demo-t1.jsonl").read_text().splitlines()]
        start = next(e for e in events if e["type"] == "attempt_start")
        self.assertIn("target:1337", start["task_prompt"])
        self.assertNotIn(FLAG, start["task_prompt"])

    def test_reset_failure_is_recorded_as_infrastructure_error(self):
        rec = self.controller([], env=FakeEnvironment(fail_on="reset")).run_one("rev-demo", 1)
        self.assertEqual((rec["status"], rec["verified"], rec["input_tokens"]), ("infrastructure_error", False, None))

    def test_environment_reset_before_and_stopped_after_each_attempt(self):
        env = FakeEnvironment(FakeExecutor())
        ctl = self.controller([reply(call("submit_flag", flag=FLAG))] * 2, env=env)
        ctl.run_one("rev-demo", 1)
        ctl.run_one("rev-demo", 2)
        self.assertEqual((env.resets, env.stopped), (2, 2))
        self.assertEqual(ctl.done_slots(), {("rev-demo", 1), ("rev-demo", 2)})


if __name__ == "__main__":
    unittest.main()
