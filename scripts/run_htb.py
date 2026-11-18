#!/usr/bin/env python
"""Run the agent against the live Hack The Box event.

    python scripts/run_htb.py --list                      # show the event's challenges and stop
    python scripts/run_htb.py --config configs/agent-htb.json --out runs/htb --only 79390
    python scripts/run_htb.py --config configs/agent-htb.json --out runs/htb --trials 1

Secrets come from .env (HTB_MCP_TOKEN, LITELLM_TOKEN). The team key has a hard $25 budget; this script
stops before a per-laptop share of it, counting only the spend in this --out directory. A challenge that
is already solved in results.jsonl is skipped, and so is any (challenge, trial) already recorded.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ctfagent.config import load_config  # noqa: E402
from ctfagent.envfile import load_env_file  # noqa: E402
from ctfagent.environment import ComposeEnvironment  # noqa: E402
from ctfagent.escalation import run_challenge_ladder  # noqa: E402
from ctfagent.gateway_budget import budget_remaining, key_info  # noqa: E402
from ctfagent.htb import DEFAULT_URL, HtbError, McpClient  # noqa: E402
from ctfagent.htb_challenges import CATEGORY_NAMES, HtbCatalog, HtbController  # noqa: E402
from ctfagent.llm import GatewayClient  # noqa: E402

DIFFICULTY_ORDER = {"very easy": 0, "easy": 1, "medium": 2, "hard": 3, "insane": 4, "": 2}


def spent(out_dir: Path) -> float:
    import json
    p = out_dir / "results.jsonl"
    if not p.exists():
        return 0.0
    total = 0.0
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            total += json.loads(line).get("cost_usd") or 0.0
    return total


def solved_ids(out_dir: Path) -> set[str]:
    import json
    p = out_dir / "results.jsonl"
    if not p.exists():
        return set()
    return {json.loads(l)["challenge_id"] for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l).get("verified")}


def recorded_ok_run_ids(out_dir: Path) -> set[str]:
    """run_ids already finished, so a resumed run skips those rungs. An infrastructure error does not
    count: the rung is retried next time rather than left half-done."""
    import json
    p = out_dir / "results.jsonl"
    if not p.exists():
        return set()
    ids = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("status") != "infrastructure_error":
            ids.add(r.get("run_id"))
    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/agent-htb.json")
    ap.add_argument("--out", default="runs/htb")
    ap.add_argument("--ctf-id", type=int, default=int(os.environ.get("HTB_CTF_ID", "3755")))
    ap.add_argument("--only", action="append", type=int, help="run just this HTB challenge id (repeatable)")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--laptop-budget", type=float, default=12.0, help="hard stop on this laptop's spend (USD)")
    ap.add_argument("--list", action="store_true", help="print the event's challenges and exit")
    args = ap.parse_args()

    load_env_file(ROOT / ".env")
    token = os.environ.get("HTB_MCP_TOKEN")
    if not token:
        sys.exit("HTB_MCP_TOKEN is not set (see .env).")
    mcp = McpClient(os.environ.get("HTB_MCP_URL", DEFAULT_URL), token)
    out = Path(args.out)
    catalog = HtbCatalog(mcp, args.ctf_id, files_root=out / "htb_files")

    if args.list:
        try:
            chs = sorted(catalog.challenges(),
                         key=lambda c: (DIFFICULTY_ORDER.get(str(c.get("difficulty", "")).lower(), 2),
                                        -int(c.get("points") or 0)))
        except HtbError as e:
            sys.exit(f"HTB error: {e}")
        print(f"{'id':>7}  {'diff':<9} {'cat':<10} {'pts':>5}  solved  name")
        for c in chs:
            cat = CATEGORY_NAMES.get(c.get("challenge_category_id"), str(c.get("challenge_category_id")))
            print(f"{c.get('id'):>7}  {str(c.get('difficulty','')):<9} {cat:<10} "
                  f"{int(c.get('points') or 0):>5}  {'yes' if c.get('solved') else 'no ':>5}   {c.get('name')}")
        return

    cfg = load_config(args.config)
    if not cfg.model:
        sys.exit("config 'model' is empty.")
    gw_token = os.environ.get("LITELLM_TOKEN")
    if not gw_token:
        sys.exit("LITELLM_TOKEN is not set in .env (the Duke gateway key).")
    base_url = os.environ.get("LITELLM_BASE_URL", "https://litellm.oit.duke.edu/v1")
    system_prompt = (ROOT / cfg.system_prompt_file).read_text(encoding="utf-8")
    lim = cfg.limits

    # One gateway client per model, built on demand and reused. All rungs share the one gateway key.
    llm_cache: dict[str, GatewayClient] = {}

    def llm_for(model: str) -> GatewayClient:
        if model not in llm_cache:
            llm_cache[model] = GatewayClient(
                base_url, gw_token, model, cfg.temperature, lim.llm_timeout_s, lim.llm_retries,
                backoff_cap_s=lim.llm_backoff_cap_s, honor_retry_after=lim.llm_honor_retry_after,
                retry_budget_s=lim.llm_retry_budget_s)
        return llm_cache[model]

    first_model = cfg.escalation.ladder[0].model if cfg.escalation.ladder else cfg.model
    env = ComposeEnvironment(cfg.environment, work_dir=out / "compose")
    ctl = HtbController(cfg, system_prompt, llm_for(first_model), env, out, loader=None, repo_dir=ROOT,
                        sample_type="live", secrets=[token, gw_token], catalog=catalog, mcp=mcp)

    # The gateway tracks REAL spend per key (across every machine using it) and enforces max_budget
    # server-side. Prefer those real numbers for the budget stop; fall back to the token-based estimate.
    gw_readable, gw_max = False, None
    try:
        info = key_info(base_url, gw_token)
        gw_readable, gw_max = True, info.get("max_budget")
        real = float(info.get("spend") or 0.0)
        if gw_max is not None:
            print(f"gateway key: real spend ${real:.6f} of ${float(gw_max):.2f} "
                  f"(remaining ${budget_remaining(info):.4f}, resets every {info.get('budget_duration') or '?'})")
        else:
            print(f"gateway key: real spend ${real:.6f} (no max_budget set on the key)")
    except Exception as e:  # /key/info may be restricted on some keys
        print(f"gateway /key/info not readable ({type(e).__name__}); using the token-based cost estimate.")

    effective_budget = args.laptop_budget
    if gw_max is not None:
        try:
            effective_budget = min(args.laptop_budget, float(gw_max))
        except (TypeError, ValueError):
            pass

    def spent_now() -> float:
        """Real gateway spend when we can read it (covers all machines on this key), else the estimate."""
        if gw_readable:
            try:
                return float(key_info(base_url, gw_token).get("spend") or 0.0)
            except Exception:
                pass
        return spent(out)

    try:
        all_ch = catalog.challenges()
    except HtbError as e:
        if not args.only:
            sys.exit(f"HTB error: {e}")
        all_ch = []
    diff_by_id = {int(c["id"]): str(c.get("difficulty", "")).lower() for c in all_ch if c.get("id") is not None}
    if args.only:
        ids = args.only
    else:
        ids = [int(c["id"]) for c in sorted(
            all_ch, key=lambda c: (DIFFICULTY_ORDER.get(str(c.get("difficulty", "")).lower(), 2),
                                   -int(c.get("points") or 0)))]

    solved, recorded_ok = solved_ids(out), recorded_ok_run_ids(out)
    for trial in range(1, args.trials + 1):
        for cid in ids:
            key = str(cid)
            if key in solved:
                print(f"skip {cid} trial {trial}: already solved")
                continue
            so_far = spent_now()
            if so_far >= effective_budget:
                print(f"budget stop: ${so_far:.4f} spent, cap ${effective_budget:.2f}. Stopping.")
                return
            print(f"\n=== challenge {cid} trial {trial}  (diff {diff_by_id.get(cid, '?')}, spent ${so_far:.4f})")

            def run_rung(rung_cfg, _key=key, _trial=trial):
                ctl.cfg = rung_cfg
                ctl.llm = llm_for(rung_cfg.model)
                print(f"  -> {rung_cfg.model}  (attempt cap ${rung_cfg.limits.max_cost_usd:.2f})")
                rec = ctl.run_one(_key, _trial)
                print(f"     {rec['run_id']}: {rec['status']} verified={rec['verified']} "
                      f"{rec['elapsed_s']}s cost=${rec['cost_usd'] or 0:.3f}")
                return rec

            rec = run_challenge_ladder(
                cfg, cid, trial, difficulty=diff_by_id.get(cid, ""),
                spent_fn=spent_now, laptop_budget=effective_budget,
                recorded=recorded_ok, run_rung=run_rung, log=lambda m: print("  " + m))
            if rec and rec.get("verified"):
                solved.add(key)
    print(f"\ndone. gateway real spend now: ${spent_now():.4f}  (this run's token estimate in {out}: ${spent(out):.4f})")


if __name__ == "__main__":
    main()
