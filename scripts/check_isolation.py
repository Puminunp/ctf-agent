#!/usr/bin/env python
"""Start one challenge's environment and test the controls from INSIDE the solver. Writes evidence JSON.

    python scripts/check_isolation.py --dataset external/ctftiny_files/CTFTiny-main/ctftiny.json \
        --challenge pwn-puffin --out runs/controls

Run it for one challenge with a target and one without. Keep the output files: they are the evidence the
report needs for "answer separation, enforced scope, protected credentials". A FAIL means do not run attempts.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ctfagent.challenges import Dataset, build_task, host_file_paths  # noqa: E402
from ctfagent.config import load_config  # noqa: E402
from ctfagent.environment import ComposeEnvironment  # noqa: E402


def checks(task, files):
    """(name, command, predicate(exit_code, output) -> bool). 'blocked' checks must fail to connect."""
    c = [
        ("runs as non-root", "id -u", lambda rc, o: rc == 0 and o.strip().splitlines()[-1] != "0"),
        ("no sudo", "command -v sudo", lambda rc, o: rc != 0),
        ("no capabilities", "grep CapEff /proc/self/status", lambda rc, o: o.split()[-1].strip("0") == ""),
        ("no Docker socket", "test -e /var/run/docker.sock", lambda rc, o: rc != 0),
        ("internet blocked (https)", "curl -sS -m 6 -o /dev/null https://example.com", lambda rc, o: rc != 0),
        ("internet blocked (raw IP)", "curl -sS -m 6 -o /dev/null http://1.1.1.1", lambda rc, o: rc != 0),
        ("host blocked (host.docker.internal)", "curl -sS -m 6 -o /dev/null http://host.docker.internal",
         lambda rc, o: rc != 0),
        ("answer files absent", "ls /flag.txt /workspace/flag.txt /workspace/challenge.json /workspace/solve.txt "
                                "/workspace/solver.py 2>&1 | grep -c 'No such file'", lambda rc, o: o.strip() == "5"),
        ("workspace holds only listed files", "ls -A /workspace | sort | tr '\\n' ' '",
         lambda rc, o: sorted(o.split()) == sorted(f.name for f in files)),
    ]
    if task.target_host and task.target_port:
        c.append((f"target reachable ({task.target_host}:{task.target_port})",
                  f"nc -z -w 5 {task.target_host} {task.target_port}", lambda rc, o: rc == 0))
    return c


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--challenge", required=True)
    ap.add_argument("--config", default="configs/agent.json")
    ap.add_argument("--out", default="runs/controls")
    a = ap.parse_args()

    cfg = load_config(ROOT / a.config if not Path(a.config).is_absolute() else a.config)
    chal = Dataset(a.dataset).load(a.challenge)
    task = build_task(a.challenge, chal, cfg.environment.target_host)
    files = host_file_paths(chal)
    out_dir = Path(a.out)
    env = ComposeEnvironment(cfg.environment, work_dir=out_dir / "compose")
    results, ok_all = [], True
    try:
        reset_id = env.reset(a.challenge, chal)
        env.export(files, cfg.environment.workdir)
        ex = env.executor()
        for name, cmd, pred in checks(task, files):
            r = ex.run(cmd, 20)
            passed = bool(pred(r.exit_code, r.output))
            ok_all &= passed
            results.append({"check": name, "command": cmd, "exit_code": r.exit_code,
                            "output": r.output.strip()[:300], "passed": passed})
            print(f"{'PASS' if passed else 'FAIL'}  {name}")
    finally:
        env.stop()
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence = {"challenge_id": a.challenge, "when_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "has_target": bool(task.target_host), "all_passed": ok_all, "checks": results}
    path = out_dir / f"isolation_{a.challenge}.json"
    path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"\n{'ALL CONTROLS PASSED' if ok_all else 'SOME CONTROLS FAILED'}; evidence: {path}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
