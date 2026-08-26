#!/usr/bin/env python3
"""
remap_function_tags.py

Rewrite output/v1/case_function_tags.json so its keys are canonical cluster
names. The classifier ran before alias consolidation, so its keys are the old
variant names; after consolidation those no longer match any cluster and the
affected cases fall through as "unclassified".

Where several variants of one case carry different tags, the canonical entry
takes the majority tag. Ties are broken by the variant with the most
substantive appearances in casemap_data.json, on the grounds that the tagger
saw more of that telling. Every collision is reported.

Writes a .bak alongside the original unless --no-backup is given.

Usage:
    python3 pipeline/remap_function_tags.py --dry-run
    python3 pipeline/remap_function_tags.py
"""

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aliases import load_aliases, resolve  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TAGS_PATH = ROOT / "output" / "v1" / "case_function_tags.json"
CASEMAP_PATH = ROOT / "output" / "v1" / "casemap_data.json"


def substantive_weights():
    """{cluster_id: n_substantive} from the casemap, for tie-breaking."""
    if not CASEMAP_PATH.exists():
        return {}
    d = json.loads(CASEMAP_PATH.read_text(encoding="utf-8"))
    cases = d["cases"] if isinstance(d, dict) else d
    return {c["cluster_id"]: c.get("n_substantive", 0) for c in cases}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    if not TAGS_PATH.exists():
        sys.exit(f"No tags file at {TAGS_PATH}")

    table = load_aliases()
    tags = json.loads(TAGS_PATH.read_text(encoding="utf-8"))
    weights = substantive_weights()

    # canonical -> [(original_key, tag), ...]
    grouped = defaultdict(list)
    for key, tag in tags.items():
        grouped[resolve(key, table)].append((key, tag))

    out = {}
    collisions = []
    renamed = 0
    for canonical, entries in grouped.items():
        distinct = {t for _k, t in entries}
        if len(distinct) == 1:
            out[canonical] = entries[0][1]
        else:
            counts = Counter(t for _k, t in entries)
            top = counts.most_common()
            if len(top) > 1 and top[0][1] == top[1][1]:
                # Tie: prefer the tag of the heaviest variant.
                best = max(entries, key=lambda kt: weights.get(kt[0], 0))
                chosen = best[1]
                how = f"tie, took tag of heaviest variant ({best[0]!r})"
            else:
                chosen = top[0][0]
                how = f"majority {counts[chosen]}/{len(entries)}"
            out[canonical] = chosen
            collisions.append((canonical, chosen, how, entries))
        if any(k != canonical for k, _t in entries):
            renamed += 1

    print(f"Input keys:            {len(tags)}")
    print(f"Canonical keys out:    {len(out)}")
    print(f"Groups touched by alias resolution: {renamed}")
    print(f"Tag collisions resolved: {len(collisions)}\n")

    for canonical, chosen, how, entries in collisions:
        print(f"  {canonical}")
        print(f"      -> {chosen}   ({how})")
        for k, t in entries:
            w = weights.get(k, 0)
            mark = "*" if t == chosen else " "
            print(f"      {mark} [{t:22s}] {w:3d} sub  {k}")
        print()

    # How many clusters in the casemap will now find a tag
    if weights:
        matched = sum(1 for cid in weights if cid in out)
        print(f"Clusters in casemap with a tag after remap: "
              f"{matched}/{len(weights)}")

    if args.dry_run:
        print("\nDry run; nothing written.")
        return

    if not args.no_backup:
        shutil.copy2(TAGS_PATH, TAGS_PATH.with_suffix(".json.bak"))
        print(f"\nBackup: {TAGS_PATH.with_suffix('.json.bak')}")
    TAGS_PATH.write_text(
        json.dumps(dict(sorted(out.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"Wrote {TAGS_PATH}")


if __name__ == "__main__":
    main()
