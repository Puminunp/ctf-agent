#!/usr/bin/env python
"""Build evaluation_manifest.json from a list of challenge IDs and the CTFTiny index.

(The course guide mentions an instructor script of this name; the professor confirmed on Nov 9 that
those kit files were artifacts, so this is our own version.) Reads only the index and the README's
published difficulty labels. It never opens challenge.json, so no flags are touched.

    python scripts/make_manifest.py --dataset external/ctftiny_files/CTFTiny-main/ctftiny.json \
        --ids-file evaluation_ids.txt --split evaluation --source-commit <sha> --out evaluation_manifest.json
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def difficulty_labels(readme: Path) -> dict[str, str]:
    """README rows look like: | cry | 2020f | hybrid2 | Very Easy |  ->  cry-hybrid2"""
    labels: dict[str, str] = {}
    if not readme.is_file():
        return labels
    for line in readme.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] in {"cry", "for", "msc", "pwn", "rev", "web"} and cells[3]:
            labels[f"{cells[0]}-{cells[2].replace('_', '-')}"] = cells[3]
    return labels


def build(dataset: Path, ids: list[str], split: str, source_commit: str) -> dict:
    index = json.loads(dataset.read_text(encoding="utf-8"))
    unknown = [i for i in ids if i not in index]
    if unknown:
        sys.exit(f"IDs not in {dataset.name}: {unknown}")
    if len(set(ids)) != len(ids):
        sys.exit("duplicate IDs in the ids file")
    labels = difficulty_labels(dataset.parent / "README.md")
    return {
        "split": split, "source": "CTFTiny", "source_commit": source_commit,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "challenges": [{"id": i, "category": index[i]["category"], "path": index[i]["path"],
                        "difficulty": labels.get(i, "Unrated")} for i in ids],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--split", default="evaluation")
    ap.add_argument("--source-commit", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ids = [l.strip() for l in Path(a.ids_file).read_text(encoding="utf-8").splitlines()
           if l.strip() and not l.startswith("#")]
    manifest = build(Path(a.dataset), ids, a.split, a.source_commit)
    Path(a.out).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {a.out}: {len(ids)} challenges")


if __name__ == "__main__":
    main()
