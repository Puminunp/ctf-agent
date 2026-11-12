#!/usr/bin/env python
"""Report plots for two configurations: pass@k, solve rate by trial (mean and variance), successes per challenge,
and tokens / seconds per challenge.

    python scripts/make_plots.py --manifest evaluation_manifest.json --a runs/eval --b runs/fix --out runs/plots

Needs matplotlib (requirements-plots.txt). All attempts are counted; infrastructure errors count as failures in the
pass@k and solve-rate plots, as in compare_configs.py.
"""

import argparse
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

COLORS = ["#7A8AA0", "#0B7A75"]


def rows_of(d: Path) -> list[dict]:
    return [json.loads(l) for l in (d / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def pass_k(rows, ids, k):
    hits = 0
    for c in ids:
        rs = sorted([r for r in rows if r["challenge_id"] == c], key=lambda r: r["trial"])[:k]
        hits += any(r["verified"] for r in rs)
    return 100 * hits / len(ids)


def trial_rates(rows, trials=3):
    out = []
    for t in range(1, trials + 1):
        rs = [r for r in rows if r["trial"] == t]
        out.append(100 * sum(r["verified"] for r in rs) / len(rs))
    return out


def tot(r):
    return (r["input_tokens"] or 0) + (r["output_tokens"] or 0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    man = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    ids = [c["id"] if isinstance(c, dict) else c for c in man["challenges"]]
    ra, rb = rows_of(Path(a.a)), rows_of(Path(a.b))
    na, nb = ra[0]["config_id"], rb[0]["config_id"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    w = 0.38

    # 1. pass@k
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    ks = [1, 2, 3]
    for i, (n, rows) in enumerate([(na, ra), (nb, rb)]):
        vals = [pass_k(rows, ids, k) for k in ks]
        bars = ax.bar([k + (i - 0.5) * w for k in ks], vals, w, label=n, color=COLORS[i])
        for b_, v in zip(bars, vals):
            ax.text(b_.get_x() + b_.get_width() / 2, v + 1.5, f"{v:.0f}", ha="center", fontsize=9, clip_on=False)
    ax.set_xticks(ks, [f"Pass@{k}" for k in ks])
    ax.set_ylabel("Challenges solved within k trials (%)")
    ax.set_ylim(0, 112)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.set_title("Pass@k over 10 challenges (all attempts counted)", pad=22)
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, borderaxespad=0.2)
    fig.tight_layout()
    fig.savefig(out / "pass_at_k.png", dpi=200)
    plt.close(fig)

    # 2. solve rate by trial with mean and variance
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    for i, (n, rows) in enumerate([(na, ra), (nb, rb)]):
        vals = trial_rates(rows)
        mean, var = statistics.mean(vals), statistics.variance(vals)
        bars = ax.bar([t + (i - 0.5) * w for t in (1, 2, 3)], vals, w, color=COLORS[i],
                      label=f"{n}: mean {mean:.1f}%, variance {var:.1f} pp²")
        for b_, v in zip(bars, vals):
            ax.text(b_.get_x() + b_.get_width() / 2, v + 1.5, f"{v:.0f}", ha="center", fontsize=9)
        ax.hlines(mean, 0.55, 3.45, colors=COLORS[i], linestyles="dashed", linewidth=1)
    ax.set_xticks([1, 2, 3], ["Trial 1", "Trial 2", "Trial 3"])
    ax.set_ylabel("Solve rate in the trial (%)")
    ax.set_ylim(0, 140)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.set_title("Solve rate per trial (dashed line = mean)")
    ax.legend(frameon=False, loc="upper center", fontsize=8.5, ncol=1)
    fig.tight_layout()
    fig.savefig(out / "solve_rate_by_trial.png", dpi=200)
    plt.close(fig)

    # 3. successes out of 3 per challenge
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    for i, (n, rows) in enumerate([(na, ra), (nb, rb)]):
        vals = [sum(r["verified"] for r in rows if r["challenge_id"] == c) for c in ids]
        ax.bar([x + (i - 0.5) * w for x in range(len(ids))], vals, w, label=n, color=COLORS[i])
    ax.set_xticks(range(len(ids)), ids, rotation=40, ha="right", fontsize=8)
    ax.set_ylabel("Successes out of 3")
    ax.set_yticks([0, 1, 2, 3])
    ax.set_title("Successes per challenge", pad=22)
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, borderaxespad=0.2)
    fig.tight_layout()
    fig.savefig(out / "successes_per_challenge.png", dpi=200)
    plt.close(fig)

    # 4. mean tokens and mean seconds per challenge (all attempts, including those that stopped early)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    for ax, key, label in [(axes[0], tot, "Mean total tokens per attempt"),
                           (axes[1], lambda r: r["elapsed_s"], "Mean wall-clock seconds per attempt")]:
        for i, (n, rows) in enumerate([(na, ra), (nb, rb)]):
            vals = [statistics.mean(key(r) for r in rows if r["challenge_id"] == c) for c in ids]
            ax.barh([y + (i - 0.5) * w for y in range(len(ids))], vals, w, label=n, color=COLORS[i])
        ax.set_yticks(range(len(ids)), ids, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel(label)
        if key is tot:
            ax.xaxis.set_major_formatter(lambda x, _: f"{x / 1000:.0f}k")
        ax.legend(frameon=False, loc="lower right", fontsize=8.5)
    fig.suptitle("Resource use per challenge (attempts that stopped early on an error report partial usage)", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "tokens_and_seconds_per_challenge.png", dpi=200)
    plt.close(fig)
    print("wrote:", ", ".join(sorted(p.name for p in out.glob("*.png"))))


if __name__ == "__main__":
    main()
