#!/usr/bin/env python
"""Race mode: watch for the noon challenge drop, split the set 5/5 with Paul, and run OUR set in parallel.

    # sanity check now — show how a hypothetical split would look, run nothing:
    python scripts/race_htb.py --dry-run

    # at ~11:55: sit and watch; the instant the challenges drop, split and fire our 5 in parallel:
    python scripts/race_htb.py --watch --config configs/agent-htb.json --out runs/race

    # run exactly these ids as ours (skip the auto-split):
    python scripts/race_htb.py --assign 79390 --assign 80001

Orchestration here is PURE CODE — no model is consulted to decide what to run — so it fires with zero
"thinking" latency. Each of our challenges runs as its own `run_htb.py --only <id>` subprocess, which is
the already-proven single-challenge path: isolated compose project (named per challenge id), isolated
results dir, its own budget check. The Duke gateway still enforces the $25 key cap server-side across all
of them. Prints OUR list and PAUL'S list so you can forward Paul his ids immediately.

Caveat: this assumes HTB lets one team run several challenge containers at once (CTF events normally do).
If a concurrent start_container is refused, that challenge's own start() retries/backs off; worst case a
few wait their turn. Nothing here risks the other challenges.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ctfagent.envfile import load_env_file  # noqa: E402
from ctfagent.htb import DEFAULT_URL, HtbError, McpClient  # noqa: E402
from ctfagent.htb_challenges import CATEGORY_NAMES, HtbCatalog  # noqa: E402
from ctfagent.race import fmt, rank_challenges, split_challenges  # noqa: E402


def live_challenges(catalog: HtbCatalog) -> list[dict]:
    try:
        return list(catalog.challenges())
    except HtbError as e:
        print(f"  (challenge list not ready: {e})")
        return []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/agent-htb.json")
    ap.add_argument("--out", default="runs/race")
    ap.add_argument("--ctf-id", type=int, default=int(os.environ.get("HTB_CTF_ID", "3755")))
    ap.add_argument("--ours", type=int, default=5, help="how many challenges are ours")
    ap.add_argument("--easiest-to-us", type=int, default=2, help="reserve the N easiest for us (we start first)")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--laptop-budget", type=float, default=25.0, help="USD stop for our side (agreed $25 each; the gateway also hard-caps the key)")
    ap.add_argument("--assign", action="append", type=int, help="run exactly these ids as ours (repeatable; skips auto-split)")
    ap.add_argument("--all", action="store_true", help="take every (unsolved) challenge as ours; no Paul split")
    ap.add_argument("--skip-solved", action="store_true", help="drop challenges HTB already marks solved for us")
    ap.add_argument("--max-parallel", type=int, default=8, help="max concurrent solvers in flight (0 = all at once)")
    ap.add_argument("--watch", action="store_true", help="poll until the challenges drop, then go")
    ap.add_argument("--min", type=int, default=0, help="with --watch, fire once this many challenges are live (0 = fire on any increase)")
    ap.add_argument("--poll-interval", type=float, default=5.0)
    ap.add_argument("--status-interval", type=float, default=5.0, help="seconds between parallel-run status lines")
    ap.add_argument("--dry-run", action="store_true", help="show the split and exit; run nothing")
    args = ap.parse_args()

    load_env_file(ROOT / ".env")
    token = os.environ.get("HTB_MCP_TOKEN")
    if not token:
        sys.exit("HTB_MCP_TOKEN is not set (see .env).")
    out = Path(args.out)
    mcp = McpClient(os.environ.get("HTB_MCP_URL", DEFAULT_URL), token)
    catalog = HtbCatalog(mcp, args.ctf_id, files_root=out / "htb_files")

    if args.watch:
        base = len(live_challenges(catalog))
        target = args.min if args.min else base + 1
        print(f"watching event {args.ctf_id}: {base} challenge(s) live now; firing when >= {target}. Ctrl-C to stop.")
        while True:
            n = len(live_challenges(catalog))
            if n >= target:
                print(f"drop detected: {n} challenges live. Go.")
                break
            print(f"  {n} live ... waiting {args.poll_interval:.0f}s")
            time.sleep(args.poll_interval)

    chs = live_challenges(catalog)
    if not chs:
        sys.exit("no challenges to run.")
    if args.skip_solved:
        before = len(chs)
        chs = [c for c in chs if not c.get("solved")]
        print(f"skip-solved: dropped {before - len(chs)} already-solved; {len(chs)} remain")
        if not chs:
            sys.exit("nothing to run — every challenge is already solved.")

    if args.assign:
        by_id = {int(c["id"]): c for c in chs}
        missing = [i for i in args.assign if i not in by_id]
        if missing:
            sys.exit(f"assigned ids not in the event (or already solved): {missing}")
        assigned = set(args.assign)
        our = [by_id[i] for i in args.assign]
        paul = [c for c in chs if int(c["id"]) not in assigned]
    elif args.all:
        our, paul = rank_challenges(chs, cat_names=CATEGORY_NAMES), []
    else:
        our, paul = split_challenges(chs, ours=args.ours, easiest_to_us=args.easiest_to_us, cat_names=CATEGORY_NAMES)

    print(f"\n=== {len(chs)} challenges live -> split {len(our)} / {len(paul)} ===")
    print(f"\nOUR {len(our)} (we run these in parallel now):")
    for c in our:
        print(fmt(c, CATEGORY_NAMES))
    print(f"\nPAUL'S {len(paul)} (send him these):")
    for c in paul:
        print(fmt(c, CATEGORY_NAMES))
    print("\nPaul's ids:", ", ".join(str(c.get("id")) for c in paul) or "(none)")

    if args.dry_run:
        print("\n--dry-run: nothing launched.")
        return
    from ctfagent.config import load_config  # noqa: E402
    provider = getattr(load_config(args.config), "provider", "gateway")
    need_env = "ANTHROPIC_API_KEY" if provider == "anthropic" else "LITELLM_TOKEN"
    if not os.environ.get(need_env):
        sys.exit(f"\n{need_env} is not set in .env — add the key before running for real.")

    out.mkdir(parents=True, exist_ok=True)

    def launch(c):
        cid = int(c["id"])
        cdir = out / str(cid)
        cdir.mkdir(parents=True, exist_ok=True)
        log = open(cdir / "run.log", "w", encoding="utf-8")
        cmd = [sys.executable, str(ROOT / "scripts" / "run_htb.py"),
               "--config", args.config, "--out", str(cdir), "--only", str(cid),
               "--trials", str(args.trials), "--laptop-budget", str(args.laptop_budget)]
        print(f"  -> launching [{cid}] {c.get('name')}  (log: {cdir / 'run.log'})")
        return (cid, c.get("name"), subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT), log)

    cap = args.max_parallel if args.max_parallel and args.max_parallel > 0 else len(our)
    queue = list(our)
    running = []
    finished = 0
    print(f"\nrunning up to {cap} at a time ({len(our)} total). Ctrl-C stops watching, not the runs.\n")
    try:
        while queue and len(running) < cap:
            running.append(launch(queue.pop(0)))
        while running:
            time.sleep(args.status_interval)
            still = []
            for cid, name, p, log in running:
                if p.poll() is None:
                    still.append((cid, name, p, log))
                    continue
                log.close()
                finished += 1
                print(f"  [{cid}] {name}: finished (exit {p.returncode})  [{finished}/{len(our)}]")
                if queue:
                    still.append(launch(queue.pop(0)))
            running = still
    except KeyboardInterrupt:
        print("\n(stopped watching; running subprocesses continue in the background)")

    print("\n=== RESULTS ===")
    for c in our:
        cid = int(c["id"])
        rp = out / str(cid) / "results.jsonl"
        status = "(no result file)"
        if rp.exists():
            rows = [json.loads(line) for line in rp.read_text(encoding="utf-8").splitlines() if line.strip()]
            if rows:
                r = rows[-1]
                status = (f"{r.get('status')} verified={r.get('verified')} "
                          f"{r.get('elapsed_s')}s ${r.get('cost_usd') or 0:.3f}")
        print(f"  [{cid}] {c.get('name')}: {status}")


if __name__ == "__main__":
    main()
