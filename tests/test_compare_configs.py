import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("compare_configs", ROOT / "scripts" / "compare_configs.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def row(cid, trial, ok, status=None, inp=1000, out=100, el=10.0):
    return {"run_id": f"x-{cid}-t{trial}", "config_id": "x", "challenge_id": cid, "trial": trial,
            "status": status or ("solved" if ok else "no_flag"), "verified": ok, "elapsed_s": el,
            "input_tokens": inp, "output_tokens": out}


IDS = ["a", "b"]
# a: t1 infra error, t2 solved, t3 solved; b: always solved
ROWS = [row("a", 1, False, "infrastructure_error", None, None), row("a", 2, True), row("a", 3, True),
        row("b", 1, True), row("b", 2, True), row("b", 3, True)]


class Metrics(unittest.TestCase):
    def test_strict_pass_at_k_and_trial_rates(self):
        m = C.metrics(ROWS, IDS, {})
        self.assertEqual(m["pass_at_k_pct_strict"], {"1": 50.0, "2": 100.0, "3": 100.0})
        self.assertEqual(m["solve_rate_by_trial_pct_strict"], [50.0, 100.0, 100.0])
        self.assertEqual(m["mean_solve_rate_pct_strict"], 83.3)
        self.assertEqual(m["solve_rate_variance_pp2_strict"], 833.3)   # sample variance of 50, 100, 100

    def test_excluding_infra_view(self):
        m = C.metrics(ROWS, IDS, {})
        self.assertEqual(m["success_rate_pct_strict"], 83.3)
        self.assertEqual(m["success_rate_pct_excl_infra"], 100.0)
        self.assertEqual(m["pass_at_k_pct_excl_infra"]["1"], 100.0)   # a's first valid attempt is its t2 success

    def test_cost_estimate_uses_list_price_and_ignores_null_usage(self):
        m = C.metrics(ROWS, IDS, {})
        self.assertEqual((m["input_tokens"], m["output_tokens"], m["attempts_missing_usage"]), (5000, 500, 1))
        self.assertEqual(m["estimated_cost_usd"], round(5000 / 1e6 * 0.10 + 500 / 1e6 * 0.50, 3))

    def test_calls_come_from_details(self):
        d = {"x-b-t1": {"llm_calls": 4, "tool_calls": 5}, "x-b-t2": {"llm_calls": 2, "tool_calls": 2}}
        m = C.metrics(ROWS, IDS, d)
        self.assertEqual((m["model_calls"], m["tool_calls"]), (6, 7))

    def test_change_in_percentage_points(self):
        a = C.metrics(ROWS, IDS, {})
        better = [row(c, t, True) for c in IDS for t in (1, 2, 3)]
        b = C.metrics(better, IDS, {})
        ch = C.compare(a, b)
        self.assertEqual((ch["success_rate_strict_pp"], ch["infrastructure_errors"]), (16.7, -1))
        self.assertEqual(ch["pass_at_k_strict_pp"]["1"], 50.0)


if __name__ == "__main__":
    unittest.main()
