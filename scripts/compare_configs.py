#!/usr/bin/env python
"""Required metrics for one or two configurations, and the change between them.

    python scripts/compare_configs.py --manifest evaluation_manifest.json \
        --a runs/eval --b runs/fix --out runs/comparison.json --md runs/comparison.md

Per configuration (all attempts counted, infrastructure errors counted as failures = "strict"):
  success rate, pass@1/2/3 (share of challenges solved at least once within the first k trials),
  solve rate per trial with its mean and sample variance (percentage points squared),
  per-challenge successes, wall-clock (total and per attempt), model and tool calls, tokens, estimated cost.
A second view excludes infrastructure_error attempts ("excluding infra") because those are gateway
rate limits, not agent behaviour; report both and say which is which.

COST IS AN ESTIMATE at Anthropic list prices for claude-haiku-5-5 ($0.10 in / $0.50 out per million tokens for
prompts up to 100K tokens, no caching). The Duke AI Gateway's own billing may differ.
"""

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

PRICE_IN_PER_M = 0.10
PRICE_OUT_PER_M = 0.50
INFRA = {"infrastructure_error"}


def load_rows(d: Path) -> list[dict]:
    return [json.loads(l) for l in (d / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def load_details(d: Path) -> dict[str, dict]:
    out = {}
    for p in (d / "details").glob("*.json"):
        x = json.loads(p.read_text(encoding="utf-8"))
        out[x["run_id"]] = x
    return out


def pass_at_k(by: dict[str, list[dict]], ids: list[str], k: int, exclude_infra: bool) -> float | None:
    hits = n = 0
    for c in ids:
        rs = [r for r in by.get(c, []) if not (exclude_infra and r["status"] in INFRA)][:k]
        if not rs:
            continue
        n += 1
        hits += any(r["verified"] for r in rs)
    return round(100 * hits / n, 1) if n else None


def metrics(rows: list[dict], ids: list[str], details: dict[str, dict], trials: int = 3) -> dict:
    rows = [r for r in rows if r["challenge_id"] in ids]
    by: dict[str, list[dict]] = {c: sorted([r for r in rows if r["challenge_id"] == c], key=lambda r: r["trial"]) for c in ids}
    solved = sum(1 for r in rows if r["verified"])
    infra = sum(1 for r in rows if r["status"] in INFRA)

    per_trial = []
    for t in range(1, trials + 1):
        rs = [r for r in rows if r["trial"] == t]
        per_trial.append(round(100 * sum(1 for r in rs if r["verified"]) / len(rs), 1) if rs else None)
    known = [x for x in per_trial if x is not None]

    in_tok = sum(r["input_tokens"] or 0 for r in rows)
    out_tok = sum(r["output_tokens"] or 0 for r in rows)
    d = [details[r["run_id"]] for r in rows if r["run_id"] in details]
    return {
        "attempts": len(rows), "solved": solved, "infrastructure_errors": infra,
        "statuses": dict(Counter(r["status"] for r in rows)),
        "success_rate_pct_strict": round(100 * solved / len(rows), 1) if rows else None,
        "success_rate_pct_excl_infra": round(100 * solved / (len(rows) - infra), 1) if len(rows) > infra else None,
        "pass_at_k_pct_strict": {str(k): pass_at_k(by, ids, k, False) for k in range(1, trials + 1)},
        "pass_at_k_pct_excl_infra": {str(k): pass_at_k(by, ids, k, True) for k in range(1, trials + 1)},
        "solve_rate_by_trial_pct_strict": per_trial,
        "mean_solve_rate_pct_strict": round(statistics.mean(known), 1) if known else None,
        "solve_rate_variance_pp2_strict": round(statistics.variance(known), 1) if len(known) > 1 else None,
        "successes_by_challenge": {c: f"{sum(1 for r in by[c] if r['verified'])}/{len(by[c])}" for c in ids},
        "total_elapsed_s": round(sum(r["elapsed_s"] for r in rows), 1),
        "mean_elapsed_s_per_attempt": round(sum(r["elapsed_s"] for r in rows) / len(rows), 1) if rows else None,
        "model_calls": sum(x.get("llm_calls", 0) for x in d), "tool_calls": sum(x.get("tool_calls", 0) for x in d),
        "input_tokens": in_tok, "output_tokens": out_tok, "total_tokens": in_tok + out_tok,
        "attempts_missing_usage": sum(1 for r in rows if r["input_tokens"] is None or r["output_tokens"] is None),
        "estimated_cost_usd": round(in_tok / 1e6 * PRICE_IN_PER_M + out_tok / 1e6 * PRICE_OUT_PER_M, 3),
    }


def delta(a, b):
    return None if a is None or b is None else round(b - a, 1)


def compare(ma: dict, mb: dict) -> dict:
    return {
        "success_rate_strict_pp": delta(ma["success_rate_pct_strict"], mb["success_rate_pct_strict"]),
        "success_rate_excl_infra_pp": delta(ma["success_rate_pct_excl_infra"], mb["success_rate_pct_excl_infra"]),
        "pass_at_k_strict_pp": {k: delta(ma["pass_at_k_pct_strict"][k], mb["pass_at_k_pct_strict"][k]) for k in ma["pass_at_k_pct_strict"]},
        "infrastructure_errors": mb["infrastructure_errors"] - ma["infrastructure_errors"],
        "total_elapsed_s": delta(ma["total_elapsed_s"], mb["total_elapsed_s"]),
        "total_tokens": mb["total_tokens"] - ma["total_tokens"],
        "model_calls": mb["model_calls"] - ma["model_calls"], "tool_calls": mb["tool_calls"] - ma["tool_calls"],
        "estimated_cost_usd": round(mb["estimated_cost_usd"] - ma["estimated_cost_usd"], 3),
    }


def markdown(ids, a_name, ma, b_name=None, mb=None, cmp=None) -> str:
    cols = [(a_name, ma)] + ([(b_name, mb)] if mb else [])
    L = ["| Metric | " + " | ".join(n for n, _ in cols) + (" | Change |" if mb else " |"),
         "|---|" + "---|" * (len(cols) + (1 if mb else 0))]

    def row(label, f, ch=None):
        L.append(f"| {label} | " + " | ".join(str(f(m)) for _, m in cols) + (f" | {ch if ch is not None else ''} |" if mb else " |"))
    row("Attempts / solved", lambda m: f"{m['attempts']} / {m['solved']}")
    row("Infrastructure errors", lambda m: m["infrastructure_errors"], cmp and f"{cmp['infrastructure_errors']:+d}")
    row("Success rate, all attempts (pp)", lambda m: m["success_rate_pct_strict"], cmp and f"{cmp['success_rate_strict_pp']:+} pp")
    row("Success rate, excluding infra errors", lambda m: m["success_rate_pct_excl_infra"], cmp and f"{cmp['success_rate_excl_infra_pp']:+} pp")
    for k in ma["pass_at_k_pct_strict"]:
        row(f"Pass@{k} (all attempts)", lambda m, k=k: m["pass_at_k_pct_strict"][k], cmp and f"{cmp['pass_at_k_strict_pp'][k]:+} pp")
    row("Solve rate by trial 1/2/3", lambda m: m["solve_rate_by_trial_pct_strict"])
    row("Mean solve rate / variance (pp^2)", lambda m: f"{m['mean_solve_rate_pct_strict']} / {m['solve_rate_variance_pp2_strict']}")
    row("Total wall-clock (s)", lambda m: m["total_elapsed_s"], cmp and f"{cmp['total_elapsed_s']:+}")
    row("Mean seconds per attempt", lambda m: m["mean_elapsed_s_per_attempt"])
    row("Model calls / tool calls", lambda m: f"{m['model_calls']} / {m['tool_calls']}", cmp and f"{cmp['model_calls']:+d} / {cmp['tool_calls']:+d}")
    row("Tokens in / out (known)", lambda m: f"{m['input_tokens']:,} / {m['output_tokens']:,}", cmp and f"{cmp['total_tokens']:+,} total")
    row("Estimated cost (USD, list price)", lambda m: m["estimated_cost_usd"], cmp and f"{cmp['estimated_cost_usd']:+}")
    L += ["", "| Challenge | " + " | ".join(n for n, _ in cols) + " |", "|---|" + "---|" * len(cols)]
    for c in ids:
        L.append(f"| {c} | " + " | ".join(m["successes_by_challenge"][c] for _, m in cols) + " |")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--a", required=True, help="run folder of the baseline (results.jsonl, details/)")
    ap.add_argument("--b", help="run folder of the changed configuration")
    ap.add_argument("--out")
    ap.add_argument("--md")
    a = ap.parse_args()
    man = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    ids = [c["id"] if isinstance(c, dict) else c for c in man["challenges"]]
    da = Path(a.a)
    ra = load_rows(da)
    name_a = ra[0]["config_id"] if ra else "A"
    ma = metrics(ra, ids, load_details(da))
    result = {"manifest": a.manifest, "price_per_million_tokens_usd": {"input": PRICE_IN_PER_M, "output": PRICE_OUT_PER_M},
              "a": {"config_id": name_a, "folder": a.a, "metrics": ma}}
    mb = cmp = name_b = None
    if a.b:
        db = Path(a.b)
        rb = load_rows(db)
        name_b = rb[0]["config_id"] if rb else "B"
        mb = metrics(rb, ids, load_details(db))
        cmp = compare(ma, mb)
        result["b"] = {"config_id": name_b, "folder": a.b, "metrics": mb}
        result["change_b_minus_a"] = cmp
    md = markdown(ids, name_a, ma, name_b, mb, cmp)
    print(md)
    if a.out:
        Path(a.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    if a.md:
        Path(a.md).write_text(md + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
