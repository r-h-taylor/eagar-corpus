#!/usr/bin/env python3
"""
inspect_clusters.py

Print the lecture/anchor list for every cluster whose id matches a search term,
plus a pairwise overlap table. Used to decide whether two similarly-named
clusters are one case or two.

Reading the overlap table:
  * Shared lecture AND anchor  -> almost certainly the same passage extracted
    twice; merge.
  * Shared lecture, different anchors -> the same lecture covers both; usually
    one case discussed across sections, occasionally two genuinely distinct
    cases in one lecture.
  * No shared lectures -> he tells them in different lectures. Weak evidence
    either way; decide on content.

Usage:
    python3 inspect_clusters.py seawolf "sea wolf"
    python3 inspect_clusters.py --data output/v1/casemap_data.json titanium
"""

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path


def load(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    return d["cases"] if isinstance(d, dict) else d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("terms", nargs="+", help="Substrings to match against cluster_id")
    ap.add_argument("--data", default="output/v1/casemap_data.json")
    ap.add_argument("--anchors", action="store_true",
                    help="Print every lecture/anchor rather than a summary")
    args = ap.parse_args()

    if not Path(args.data).exists():
        sys.exit(f"No such file: {args.data} (run from the repo root)")

    cases = load(args.data)
    terms = [t.lower() for t in args.terms]
    hits = [c for c in cases
            if any(t in c["cluster_id"].lower() for t in terms)]

    if not hits:
        sys.exit("No clusters matched.")

    hits.sort(key=lambda c: -c["n_substantive"])
    print(f"{len(hits)} clusters matching {args.terms}\n")

    lecsets = {}
    for i, c in enumerate(hits, 1):
        lecs = c.get("lectures", [])
        vids = sorted({l["video_id"] for l in lecs})
        lecsets[i] = set(vids)
        print(f"[{i:2d}] {c['n_substantive']:3d} sub {c['n_brief']:3d} brief  "
              f"[{c['function_tag']}]")
        print(f"     {c['cluster_id']}")
        if args.anchors:
            for l in lecs:
                print(f"        {l['video_id']}  {l.get('anchor','')}  "
                      f"{l.get('treatment','')}")
        else:
            print(f"     lectures ({len(vids)}): {', '.join(vids)}")
        print()

    print("=" * 72)
    print("PAIRWISE LECTURE OVERLAP")
    print("=" * 72)
    any_overlap = False
    for a, b in combinations(sorted(lecsets), 2):
        shared = lecsets[a] & lecsets[b]
        if not shared:
            continue
        any_overlap = True
        ua, ub = lecsets[a] - lecsets[b], lecsets[b] - lecsets[a]
        print(f"\n[{a}] x [{b}]  shared {len(shared)}  "
              f"only-in-{a}: {len(ua)}  only-in-{b}: {len(ub)}")
        print(f"     shared: {', '.join(sorted(shared))}")
    if not any_overlap:
        print("\n  No lecture overlap between any pair.")

    allv = set().union(*lecsets.values()) if lecsets else set()
    tot_sub = sum(c["n_substantive"] for c in hits)
    print(f"\n{'=' * 72}")
    print(f"Combined substantive count if all merged: {tot_sub}")
    print(f"Distinct lectures across all matches:     {len(allv)}")
    print("=" * 72)


if __name__ == "__main__":
    main()
