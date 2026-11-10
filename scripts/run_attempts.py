#!/usr/bin/env python
"""Run trials for every challenge in the evaluation manifest with one fixed configuration.

Example (from the repo root, after setup in README.md):
    python scripts/run_attempts.py --manifest evaluation_manifest.json \
        --dataset external/CTFTiny/ctftiny.json --config configs/agent.json --out runs/eval --trials 3

Existing (challenge, trial) slots in results.jsonl are skipped, never overwritten or silently retried.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ctfagent.challenges import Dataset  # noqa: E402
from ctfagent.config import load_config  # noqa: E402
from ctfagent.controller import Controller  # noqa: E402
from ctfagent.environment import ComposeEnvironment  # noqa: E402
from ctfagent.llm import GatewayClient  # noqa: E402


def manifest_ids(path: str) -> list[str]:
    """Accepts the shapes I expect make_manifest.py to produce; adjust here if it differs."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else (raw.get("challenges") or raw.get("ids") or [])
    ids = [i if isinstance(i, str) else (i.get("id") or i.get("challenge_id") or i.get("name")) for i in items]
    if not ids or any(not i for i in ids):
        sys.exit(f"could not read challenge IDs from {path}; edit manifest_ids() to match its format")
    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--dataset", required=True, help="path to ctftiny.json (or development_dataset.json)")
    ap.add_argument("--config", default="configs/agent.json")
    ap.add_argument("--out", required=True, help="output directory (results.jsonl, traces/, details/)")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--only", action="append", help="run just this challenge ID (repeatable)")
    ap.add_argument("--max-attempts", type=int, help="stop after this many attempts (use for pilots)")
    ap.add_argument("--sample-type", default="live", choices=["live", "synthetic"])
    args = ap.parse_args()

    cfg = load_config(args.config)
    if not cfg.model:
        sys.exit("configs: 'model' is empty. Set an allowed Duke gateway model ID (see list_gateway_models.py).")
    token = os.environ.get("LITELLM_TOKEN")
    base_url = os.environ.get("LITELLM_BASE_URL", "https://litellm.oit.duke.edu/v1")
    if not token:
        sys.exit("set LITELLM_TOKEN in the controller environment (see README)")

    system_prompt = (ROOT / cfg.system_prompt_file).read_text(encoding="utf-8")
    llm = GatewayClient(base_url, token, cfg.model, cfg.temperature,
                        cfg.limits.llm_timeout_s, cfg.limits.llm_retries)
    ds = Dataset(args.dataset)
    ctl = Controller(cfg, system_prompt, llm,
                     ComposeEnvironment(cfg.environment, work_dir=Path(args.out) / "compose"), args.out, ds.load,
                     repo_dir=ROOT, sample_type=args.sample_type, secrets=[token])

    ids = args.only or manifest_ids(args.manifest)
    done, ran = ctl.done_slots(), 0
    for trial in range(1, args.trials + 1):
        for cid in ids:
            if (cid, trial) in done:
                print(f"skip {cid} trial {trial}: already recorded")
                continue
            if args.max_attempts is not None and ran >= args.max_attempts:
                print("attempt cap reached; stopping")
                return
            rec = ctl.run_one(cid, trial)
            ran += 1
            print(f"{rec['run_id']}: {rec['status']} verified={rec['verified']} {rec['elapsed_s']}s "
                  f"tokens in/out={rec['input_tokens']}/{rec['output_tokens']}")


if __name__ == "__main__":
    main()
