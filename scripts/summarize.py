#!/usr/bin/env python
"""Per-challenge and overall metrics from results.jsonl (our own version of the guide's summarizer).

    python scripts/summarize.py --manifest evaluation_manifest.json --results runs/eval/results.jsonl \
        --config agent --out runs/eval/summary.json --csv runs/eval/per_challenge.csv

Per challenge (3 attempts): success rate = successes/attempts x 100; sample SD of the 0/1 outcomes x 100
(denominator n-1, percentage points); mean input/output/total tokens; mean elapsed seconds. Failed,
timed-out and wrong-flag attempts count. Missing token values stay null and are reported as such.
A challenge is incomplete if it lacks 3 attempts or has an infrastructure_error or scope_violation;
the overall rate is then left null instead of being computed from partial data.
"""

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

INCIDENTS = {"infrastructure_error", "scope_violation"}


def sample_sd_pp(outcomes: list[int]) -> float | None:
    if len(outcomes) < 2:
        return None
    p = sum(outcomes) / len(outcomes)
    return 100 * math.sqrt(sum((x - p) ** 2 for x in outcomes) / (len(outcomes) - 1))


def mean_known(values: list) -> tuple[float | None, int]:
    known = [v for v in values if v is not None]
    return (sum(known) / len(known) if known else None), len(values) - len(known)


def summarize(ids: list[str], rows: list[dict], config_id: str = "agent", trials: int = 3,
              details: dict[str, dict] | None = None) -> dict:
    rows = [r for r in rows if r["config_id"] == config_id]
    by = {i: sorted([r for r in rows if r["challenge_id"] == i], key=lambda r: r["trial"]) for i in ids}
    per = []
    for cid in ids:
        rs = by[cid]
        outcomes = [1 if r["verified"] else 0 for r in rs]
        mi, miss_i = mean_known([r["input_tokens"] for r in rs])
        mo, miss_o = mean_known([r["output_tokens"] for r in rs])
        totals = [None if (r["input_tokens"] is None or r["output_tokens"] is None)
                  else r["input_tokens"] + r["output_tokens"] for r in rs]
        mt, miss_t = mean_known(totals)
        statuses = Counter(r["status"] for r in rs)
        incident = sorted(set(statuses) & INCIDENTS)
        per.append({
            "challenge_id": cid, "attempts": len(rs), "successes": sum(outcomes),
            "success_rate_pct": round(100 * sum(outcomes) / len(rs), 1) if rs else None,
            "sample_sd_pp": None if sample_sd_pp(outcomes) is None else round(sample_sd_pp(outcomes), 1),
            "mean_input_tokens": mi, "mean_output_tokens": mo, "mean_total_tokens": mt,
            "attempts_missing_usage": max(miss_i, miss_o, miss_t),
            "mean_elapsed_s": round(sum(r["elapsed_s"] for r in rs) / len(rs), 1) if rs else None,
            "statuses": dict(statuses), "incident": incident,
            "complete": len(rs) == trials and not incident,
        })
    complete = all(p["complete"] for p in per)
    n_success = sum(p["successes"] for p in per)

    out: dict = {"config_id": config_id, "challenges": len(ids), "trials_expected": trials,
                 "attempts_recorded": sum(p["attempts"] for p in per), "all_complete": complete,
                 "incomplete_challenges": [p["challenge_id"] for p in per if not p["complete"]],
                 "overall_success_rate_pct": round(100 * n_success / (trials * len(ids)), 1) if complete else None,
                 "total_successes": n_success, "per_challenge": per}
    if complete:
        # pass@k: share of challenges solved at least once within the first k trials
        out["pass_at_k_pct"] = {str(k): round(100 * sum(
            any(r["verified"] for r in by[c][:k]) for c in ids) / len(ids), 1) for k in range(1, trials + 1)}
        per_trial = [100 * sum(by[c][t]["verified"] for c in ids) / len(ids) for t in range(trials)]
        out["solve_rate_by_trial_pct"] = [round(x, 1) for x in per_trial]
        out["mean_solve_rate_pct"] = round(statistics.mean(per_trial), 1)
        out["solve_rate_variance_pp2"] = round(statistics.variance(per_trial), 2) if trials > 1 else None
    out["total_elapsed_s"] = round(sum(r["elapsed_s"] for r in rows if r["challenge_id"] in ids), 1)
    known_tok = [(r["input_tokens"], r["output_tokens"]) for r in rows if r["challenge_id"] in ids]
    out["total_input_tokens_known"] = sum(i for i, _ in known_tok if i is not None)
    out["total_output_tokens_known"] = sum(o for _, o in known_tok if o is not None)
    out["attempts_with_missing_usage"] = sum(1 for i, o in known_tok if i is None or o is None)
    if details:
        d = [details[r["run_id"]] for r in rows if r["run_id"] in details]
        out["total_llm_calls"] = sum(x.get("llm_calls", 0) for x in d)
        out["total_tool_calls"] = sum(x.get("tool_calls", 0) for x in d)
    out["note"] = ("Three attempts per challenge is limited evidence. The SD describes variation in binary "
                   "outcomes and is not a confidence interval.")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--config", default="agent")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--out", required=True)
    ap.add_argument("--csv", required=True)
    a = ap.parse_args()

    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    ids = [c["id"] if isinstance(c, dict) else c for c in manifest["challenges"]]
    rpath = Path(a.results)
    rows = [json.loads(l) for l in rpath.read_text(encoding="utf-8").splitlines() if l.strip()]
    details = {}
    for p in (rpath.parent / "details").glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        details[d["run_id"]] = d
    s = summarize(ids, rows, a.config, a.trials, details)
    Path(a.out).write_text(json.dumps(s, indent=2), encoding="utf-8")
    cols = ["challenge_id", "attempts", "successes", "success_rate_pct", "sample_sd_pp", "mean_input_tokens",
            "mean_output_tokens", "mean_total_tokens", "attempts_missing_usage", "mean_elapsed_s", "complete"]
    with open(a.csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in s["per_challenge"]:
            w.writerow({k: ("" if p[k] is None else p[k]) for k in cols})
    print(f"overall success rate: {s['overall_success_rate_pct']}  (complete={s['all_complete']}); "
          f"incomplete: {s['incomplete_challenges']}")
    sys.exit(0)


if __name__ == "__main__":
    main()
