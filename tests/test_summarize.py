import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _load("summarize")
M = _load("make_manifest")


def row(cid, trial, ok, status=None, inp=100, out=10, el=10.0):
    return {"run_id": f"agent-{cid}-t{trial}", "config_id": "agent", "challenge_id": cid, "trial": trial,
            "status": status or ("solved" if ok else "no_flag"), "verified": ok, "elapsed_s": el,
            "input_tokens": inp, "output_tokens": out}


class Summaries(unittest.TestCase):
    def test_guide_worked_example(self):
        s = S.summarize(["a"], [row("a", 1, True), row("a", 2, False), row("a", 3, True)])
        p = s["per_challenge"][0]
        self.assertEqual((p["success_rate_pct"], p["sample_sd_pp"]), (66.7, 57.7))

    def test_token_and_time_means_include_failures(self):
        rows = [row("a", t, t == 1, inp=i, out=o, el=e)
                for t, i, o, e in [(1, 100, 10, 10), (2, 200, 20, 20), (3, 300, 30, 30)]]
        p = S.summarize(["a"], rows)["per_challenge"][0]
        self.assertEqual((p["mean_total_tokens"], p["mean_elapsed_s"]), (220, 20.0))

    def test_all_fail_and_all_succeed_have_zero_sd(self):
        s = S.summarize(["a", "b"], [row("a", t, False) for t in (1, 2, 3)] + [row("b", t, True) for t in (1, 2, 3)])
        self.assertEqual([p["sample_sd_pp"] for p in s["per_challenge"]], [0.0, 0.0])
        self.assertEqual(s["overall_success_rate_pct"], 50.0)

    def test_incomplete_leaves_overall_null(self):
        s = S.summarize(["a", "b"], [row("a", t, True) for t in (1, 2, 3)] + [row("b", 1, True)])
        self.assertIsNone(s["overall_success_rate_pct"])
        self.assertEqual(s["incomplete_challenges"], ["b"])

    def test_incident_marks_challenge_incomplete(self):
        rows = [row("a", 1, False, "infrastructure_error"), row("a", 2, False), row("a", 3, False)]
        s = S.summarize(["a"], rows)
        self.assertFalse(s["per_challenge"][0]["complete"])
        self.assertIsNone(s["overall_success_rate_pct"])

    def test_missing_usage_stays_null_and_is_counted(self):
        rows = [row("a", 1, True, inp=None, out=None), row("a", 2, False), row("a", 3, False)]
        s = S.summarize(["a"], rows)
        self.assertEqual(s["per_challenge"][0]["attempts_missing_usage"], 1)
        self.assertEqual(s["attempts_with_missing_usage"], 1)

    def test_pass_at_k_and_variance(self):
        # a: solved only on trial 2; b: never; trial solve rates are 0, 50, 0
        rows = [row("a", 1, False), row("a", 2, True), row("a", 3, False)] + [row("b", t, False) for t in (1, 2, 3)]
        s = S.summarize(["a", "b"], rows)
        self.assertEqual(s["pass_at_k_pct"], {"1": 0.0, "2": 50.0, "3": 50.0})
        self.assertEqual(s["solve_rate_by_trial_pct"], [0.0, 50.0, 0.0])

    def test_other_config_rows_are_ignored(self):
        other = dict(row("a", 1, True), config_id="agent-fix")
        s = S.summarize(["a"], [other, row("a", 1, False), row("a", 2, False), row("a", 3, False)])
        self.assertEqual(s["total_successes"], 0)


class Manifest(unittest.TestCase):
    def test_build_rejects_unknown_and_duplicate_ids(self):
        import json, tempfile
        d = Path(tempfile.mkdtemp())
        (d / "ctftiny.json").write_text(json.dumps({"cry-a": {"category": "cry", "path": "p"}}))
        (d / "README.md").write_text("| cry | 2020f | a | Very Easy |\n")
        m = M.build(d / "ctftiny.json", ["cry-a"], "evaluation", "abc")
        self.assertEqual(m["challenges"][0]["difficulty"], "Very Easy")
        with self.assertRaises(SystemExit):
            M.build(d / "ctftiny.json", ["cry-zzz"], "evaluation", "abc")


if __name__ == "__main__":
    unittest.main()
