#!/usr/bin/env python
"""Compare a separate re-run (for example config agent-fix) with the baseline records for the SAME slots.

    python scripts/compare_rerun.py --baseline runs/eval --rerun runs/rerun --out runs/rerun/comparison.json

The baseline records are never modified. Two views:
  * slot comparison: outcome, time, tokens, model and tool calls, estimated cost, on exactly the re-run slots
    (baseline attempts that stopped early on an error show the partial usage they had before stopping);
  * merged view: the baseline with ONLY the re-run slots replaced, for reporting next to (not instead of) the
    as-recorded baseline.
Cost is an ESTIMATE at Anthropic list prices for claude-haiku-5-5 ($0.10 in / $0.50 out per million tokens).
"""

import argparse
import json
from collections import Counter
from pathlib import Path

PRICE_IN_PER_M = 0.10
PRICE_OUT_PER_M = 0.50


def load(d: Path) -> list[dict]:
    return [json.loads(l) for l in (d / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def load_details(d: Path) -> dict[str, dict]:
    out = {}
    p = d / "details"
    if p.is_dir():
        for f in p.glob("*.json"):
            x = json.loads(f.read_text(encoding="utf-8"))
            out[x["run_id"]] = x
    return out


def totals(rows: list[dict], details: dict[str, dict]) -> dict:
    i = sum(r["input_tokens"] or 0 for r in rows)
    o = sum(r["output_tokens"] or 0 for r in rows)
    d = [details.get(r["run_id"], {}) for r in rows]
    return {
        "attempts": len(rows), "solved": sum(1 for r in rows if r["verified"]),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "elapsed_s": round(sum(r["elapsed_s"] for r in rows), 1),
        "input_tokens": i, "output_tokens": o,
        "model_calls": sum(x.get("llm_calls", 0) for x in d), "tool_calls": sum(x.get("tool_calls", 0) for x in d),
        "estimated_cost_usd": round(i / 1e6 * PRICE_IN_PER_M + o / 1e6 * PRICE_OUT_PER_M, 3),
    }


def compare(base_rows, re_rows, base_details=None, re_details=None) -> dict:
    base_details, re_details = base_details or {}, re_details or {}
    base = {(r["challenge_id"], r["trial"]): r for r in base_rows}
    slots, b_rows = [], []
    for r in re_rows:
        b = base.get((r["challenge_id"], r["trial"]))
        if b:
            b_rows.append(b)
        slots.append({
            "challenge_id": r["challenge_id"], "trial": r["trial"],
            "baseline_status": b["status"] if b else None, "rerun_status": r["status"],
            "rerun_verified": r["verified"], "rerun_elapsed_s": r["elapsed_s"],
            "rerun_input_tokens": r["input_tokens"], "rerun_output_tokens": r["output_tokens"],
            "baseline_elapsed_s": b["elapsed_s"] if b else None,
            "baseline_input_tokens": b["input_tokens"] if b else None,
            "baseline_output_tokens": b["output_tokens"] if b else None,
            "baseline_run_id": b["run_id"] if b else None, "rerun_run_id": r["run_id"],
        })
    ta, tb = totals(b_rows, base_details), totals(re_rows, re_details)
    n = len(re_rows)
    merged = dict(base)
    for r in re_rows:
        merged[(r["challenge_id"], r["trial"])] = r
    per: dict[str, list[dict]] = {}
    for (c, _), r in merged.items():
        per.setdefault(c, []).append(r)
    return {
        "slots_rerun": n,
        "same_slots": {
            "baseline": ta, "rerun": tb,
            "solve_rate_change_pp": round(100 * (tb["solved"] - ta["solved"]) / n, 1) if n else None,
            "elapsed_s_change": round(tb["elapsed_s"] - ta["elapsed_s"], 1),
            "tokens_change": (tb["input_tokens"] + tb["output_tokens"]) - (ta["input_tokens"] + ta["output_tokens"]),
            "model_calls_change": tb["model_calls"] - ta["model_calls"],
            "tool_calls_change": tb["tool_calls"] - ta["tool_calls"],
            "estimated_cost_usd_change": round(tb["estimated_cost_usd"] - ta["estimated_cost_usd"], 3),
        },
        "baseline_statuses_of_rerun_slots": dict(Counter(s["baseline_status"] for s in slots)),
        "rerun_statuses": dict(Counter(r["status"] for r in re_rows)),
        "slots": slots,
        "merged_successes_by_challenge": {c: f"{sum(1 for r in rs if r['verified'])}/{len(rs)}" for c, rs in sorted(per.items())},
        "merged_total": f"{sum(1 for r in merged.values() if r['verified'])}/{len(merged)}",
        "baseline_total_as_recorded": f"{sum(1 for r in base.values() if r['verified'])}/{len(base)}",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--rerun", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    result = compare(load(Path(a.baseline)), load(Path(a.rerun)),
                     load_details(Path(a.baseline)), load_details(Path(a.rerun)))
    text = json.dumps(result, indent=2)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
