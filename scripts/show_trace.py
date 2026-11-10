#!/usr/bin/env python
"""Print one attempt's trace as a readable step-by-step list.

    python scripts/show_trace.py runs/pilot/traces/agent-rev-checker-t1.jsonl [--width 400]
"""

import argparse
import json


def clip(text, width):
    text = (text or "").replace("\r", "")
    return text if len(text) <= width else text[:width] + f" [... {len(text) - width} more chars]"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--width", type=int, default=400)
    ap.add_argument("--no-output", action="store_true",
                    help="hide tool output (it may hold partial answers); show only exit code, size and timing")
    a = ap.parse_args()
    t0 = None
    for line in open(a.trace, encoding="utf-8"):
        e = json.loads(line)
        t0 = t0 or e["ts"]
        t, stamp = e["type"], f"+{e['ts'] - t0:6.1f}s"
        if t == "model_response":
            print(f"\n[{stamp}] step {e['step']}  MODEL  tokens in/out={e['input_tokens']}/{e['output_tokens']}")
            if e["content"]:
                print("  says:", clip(e["content"], a.width))
            for c in e["tool_calls"]:
                print(f"  calls {c['name']}: {clip(c['arguments'], a.width)}")
        elif t == "tool_result":
            print(f"  -> exit={e['exit_code']} {e['elapsed_s']}s truncated={e['truncated']}")
            if a.no_output:
                print(f"    [{len(e['output'])} chars of output hidden]")
            else:
                print("    " + clip(e["output"], a.width).replace("\n", "\n    "))
        elif t == "attempt_start":
            print(f"[{stamp}] START model={e['model']}\n  task: {clip(e['task_prompt'], a.width)}")
        elif t == "environment_ready":
            print(f"[{stamp}] ENV ready reset_id={e['reset_id']} files={[f['file'] for f in e['files']]}")
        else:
            print(f"  [{t}]", {k: clip(str(v), 200) for k, v in e.items() if k not in ('ts', 'type')})


if __name__ == "__main__":
    main()
