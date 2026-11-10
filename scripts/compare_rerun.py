#!/usr/bin/env python
"""Compare a separate re-run (for example config agent-fix) with the baseline records for the same slots.

    python scripts/compare_rerun.py --baseline runs/eval --rerun runs/rerun --out runs/rerun/comparison.json

The baseline records are never modified. The "merged view" replaces ONLY the baseline slots that were re-run, and is for
reporting alongside (not instead of) the as-recorded baseline.
"""

import argparse
import json
from collections import Counter
from pathlib import Path


def load(d: Path) -> list[dict]:
    return [json.loads(l) for l in (d / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def compare(base_rows: list[dict], re_rows: list[dict]) -> dict:
    base = {(r["challenge_id"], r["trial"]): r for r in base_rows}
    slots = []
    for r in re_rows:
        b = base.get((r["challenge_id"], r["trial"]))
        slots.append({
            "challenge_id": r["challenge_id"], "trial": r["trial"],
            "baseline_status": b["status"] if b else None, "rerun_status": r["status"],
            "rerun_verified": r["verified"], "rerun_elapsed_s": r["elapsed_s"],
            "rerun_input_tokens": r["input_tokens"], "rerun_output_tokens": r["output_tokens"],
            "baseline_run_id": b["run_id"] if b else None, "rerun_run_id": r["run_id"],
        })
    merged = dict(base)
    for r in re_rows:
        merged[(r["challenge_id"], r["trial"])] = r
    per: dict[str, list[dict]] = {}
    for (c, _), r in merged.items():
        per.setdefault(c, []).append(r)
    return {
        "slots_rerun": len(re_rows),
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
    result = compare(load(Path(a.baseline)), load(Path(a.rerun)))
    text = json.dumps(result, indent=2)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
