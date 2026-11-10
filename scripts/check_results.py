#!/usr/bin/env python
"""Sanity-check results.jsonl before running the instructor's summarizer.

Checks A4 fields, duplicate slots, trial range, config_id, linked traces, and status values.
It does not replace reading the traces.
"""

import json
import sys
from pathlib import Path

REQUIRED = ["run_id", "config_id", "challenge_id", "trial", "status", "verified", "elapsed_s",
            "input_tokens", "output_tokens", "cost_usd", "trace_file", "reset_id", "sample_type"]
STATUSES = {"solved", "no_flag", "wrong_flag", "timeout", "budget_exhausted", "tool_error",
            "infrastructure_error", "scope_violation"}


def check(results_path: Path, expect_config: str = "agent", expect_sample: str = "live") -> list[str]:
    problems: list[str] = []
    seen: set = set()
    for n, line in enumerate(results_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"line {n}: not valid JSON")
            continue
        missing = [k for k in REQUIRED if k not in r]
        if missing:
            problems.append(f"line {n}: missing {missing}")
            continue
        slot = (r["challenge_id"], r["trial"])
        if slot in seen:
            problems.append(f"line {n}: duplicate slot {slot}")
        seen.add(slot)
        if r["config_id"] != expect_config:
            problems.append(f"line {n}: config_id {r['config_id']!r} != {expect_config!r}")
        if r["trial"] not in (1, 2, 3):
            problems.append(f"line {n}: trial {r['trial']} outside 1-3")
        if r["status"] not in STATUSES:
            problems.append(f"line {n}: unknown status {r['status']!r}")
        if r["verified"] != (r["status"] == "solved"):
            problems.append(f"line {n}: verified={r['verified']} disagrees with status {r['status']}")
        if r["sample_type"] != expect_sample:
            problems.append(f"line {n}: sample_type {r['sample_type']!r} (expected {expect_sample!r})")
        if not (results_path.parent / r["trace_file"]).is_file():
            problems.append(f"line {n}: trace file {r['trace_file']} not found")
    return problems


if __name__ == "__main__":
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/eval/results.jsonl")
    issues = check(path)
    print("\n".join(issues) if issues else f"{path}: no problems found")
    sys.exit(1 if issues else 0)
