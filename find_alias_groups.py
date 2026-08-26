#!/usr/bin/env python3
"""
find_alias_groups.py  (v3)

Surface candidate alias groups in the Eagar corpus case canon.

Reads output/v1/casemap_data.json and proposes groups of cluster_ids that look
like variant names for one underlying case. Nothing is modified; the output is
a worksheet for human review.

Why v3
------
v1 grouped by union-find over shared tokens and chained 783 unrelated cases
into one group. v2 grouped by rare "anchor" tokens and surfaced *topics* rather
than aliases: "collapse" pulled the World Trade Center, the Hyatt Regency and a
stadium I-beam into one group because they share a single word.

The distinguishing signal is whole-name similarity, not shared vocabulary.
Seawolf variants overlap on three or four tokens out of five; the World Trade
Center and the Hyatt Regency overlap on exactly one. This version scores every
candidate pair two ways and keeps the stronger:

  * Token Jaccard, on tokens with hyphenated forms (x-33, hy-100) preserved.
  * Character-sequence ratio on the compacted string (lowercase, alphanumeric,
    spaces removed). This is what lets "Sea Wolf" match "Seawolf", which no
    token-based measure can do.

Pairs scoring at or above --threshold become edges; connected components over
those edges become groups. At a high threshold, transitive chaining is safe
because each edge already means "these two names describe the same thing".

Candidate pairs are blocked on shared tokens so this stays fast rather than
comparing all ~840,000 pairs.

Usage:
    python3 find_alias_groups.py [--data PATH] [--threshold F] [--limit N]
                                 [--out PATH] [--pairs]
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

STOPWORDS = {
    "a", "an", "and", "the", "of", "in", "at", "on", "for", "to", "with", "by",
    "case", "cases", "problem", "problems", "issue", "issues",
}

MALFORMED_PATTERNS = [
    (re.compile(r"likely[_ ]matches", re.I), "leftover model commentary"),
    (re.compile(r"candidates?[_ ]from[_ ]the[_ ]canon", re.I), "leftover model commentary"),
    (re.compile(r"also[_ ]recurs[_ ]as", re.I), "embedded cross-reference"),
    (re.compile(r"also[_ ]touches", re.I), "embedded cross-reference"),
    (re.compile(r"^[\s_`'\"\-]+|[\s_`'\"\-]+$"), "leading/trailing delimiter"),
    (re.compile(r"`"), "backtick in id"),
    (re.compile(r"\bproposed\b", re.I), "PROPOSED marker in id"),
    (re.compile(r"\?\?|\bTODO\b|\bFIXME\b", re.I), "editorial marker"),
]

TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def tokenise(name):
    toks = TOKEN_RE.findall(name.lower())
    return {t for t in toks if t not in STOPWORDS and len(t) > 1}


def compact(name):
    """Lowercase, alphanumeric only, no spaces. 'Sea Wolf' -> 'seawolf'."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def score_pair(a, b, toks, comp):
    ta, tb = toks[a], toks[b]
    if ta or tb:
        jac = len(ta & tb) / len(ta | tb)
    else:
        jac = 0.0
    seq = SequenceMatcher(None, comp[a], comp[b]).ratio()
    return max(jac, seq), jac, seq


def load_cases(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    return d["cases"] if isinstance(d, dict) else d


def flag_malformed(cases):
    out = []
    for c in cases:
        cid = c["cluster_id"]
        for pat, reason in MALFORMED_PATTERNS:
            if pat.search(cid):
                out.append((cid, reason, c["n_substantive"], c["n_brief"]))
                break
    return out


def candidate_pairs(ids, toks, max_block):
    """Block on shared tokens so we score thousands of pairs, not ~840,000."""
    by_token = defaultdict(list)
    for cid in ids:
        for t in toks[cid]:
            by_token[t].append(cid)
    seen = set()
    for token, members in by_token.items():
        if len(members) > max_block:
            continue
        for a, b in combinations(sorted(members), 2):
            if (a, b) not in seen:
                seen.add((a, b))
                yield a, b


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="output/v1/casemap_data.json")
    ap.add_argument("--threshold", type=float, default=0.55,
                    help="Similarity at or above which two ids are linked (default 0.55)")
    ap.add_argument("--max-block", type=int, default=80,
                    help="Skip tokens shared by more than this many ids (default 80)")
    ap.add_argument("--limit", type=int, default=40,
                    help="Show only the top N groups (default 40; 0 for all)")
    ap.add_argument("--pairs", action="store_true",
                    help="List scored pairs instead of grouping them")
    ap.add_argument("--out", help="Optional CSV worksheet path (always written in full)")
    args = ap.parse_args()

    if not Path(args.data).exists():
        sys.exit(f"No such file: {args.data} (run from the repo root)")

    cases = load_cases(args.data)
    by_id = {c["cluster_id"]: c for c in cases}
    ids = list(by_id)
    toks = {c: tokenise(c) for c in ids}
    comp = {c: compact(c) for c in ids}

    print(f"Loaded {len(cases)} clusters from {args.data}")
    print(f"Threshold {args.threshold}\n")

    malformed = flag_malformed(cases)
    print("=" * 72)
    print(f"MALFORMED IDS  ({len(malformed)}) - repair, do not merge")
    print("=" * 72)
    if not malformed:
        print("  none found in the casemap")
    for cid, reason, ns, nb in sorted(malformed, key=lambda r: -r[2]):
        print(f"  [{ns:3d} sub {nb:3d} brief]  ({reason})")
        print(f"      {cid[:140]}")
    print()

    edges = []
    for a, b in candidate_pairs(ids, toks, args.max_block):
        s, jac, seq = score_pair(a, b, toks, comp)
        if s >= args.threshold:
            edges.append((s, jac, seq, a, b))
    edges.sort(reverse=True)

    if args.pairs:
        print("=" * 72)
        print(f"SCORED PAIRS  ({len(edges)})")
        print("=" * 72)
        for s, jac, seq, a, b in edges[:args.limit or len(edges)]:
            print(f"\n  score {s:.2f}  (jaccard {jac:.2f}, sequence {seq:.2f})")
            print(f"    {by_id[a]['n_substantive']:3d} sub  {a}")
            print(f"    {by_id[b]['n_substantive']:3d} sub  {b}")
        return

    parent = {c: c for c in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for s, jac, seq, a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    groups = defaultdict(list)
    for c in ids:
        groups[find(c)].append(c)
    groups = [g for g in groups.values() if len(g) > 1]
    for g in groups:
        g.sort(key=lambda m: (-by_id[m]["n_substantive"], m))
    groups.sort(key=lambda g: (-sum(by_id[m]["n_substantive"] for m in g), -len(g)))

    collapsed = sum(len(g) - 1 for g in groups)
    shown = groups if args.limit == 0 else groups[:args.limit]

    print("=" * 72)
    print(f"CANDIDATE ALIAS GROUPS  ({len(groups)} groups; showing {len(shown)})")
    print("=" * 72)
    for i, members in enumerate(shown, 1):
        tot_sub = sum(by_id[m]["n_substantive"] for m in members)
        tot_brief = sum(by_id[m]["n_brief"] for m in members)
        print(f"\nGroup {i}  -> {tot_sub} sub / {tot_brief} brief if merged  "
              f"({len(members)} ids)")
        for m in members:
            c = by_id[m]
            print(f"    {c['n_substantive']:3d} sub {c['n_brief']:3d} brief  "
                  f"[{c['function_tag']:22s}] {m}")

    print(f"\n{'=' * 72}")
    print(f"Clusters now:              {len(cases)}")
    print(f"Ids inside candidate groups: {collapsed + len(groups)}")
    print(f"If every group merged:     {len(cases) - collapsed}")
    print("Every group is a question. Review before applying anything.")
    print("=" * 72)

    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["group", "merge_into", "cluster_id", "n_substantive",
                        "n_brief", "function_tag"])
            for i, members in enumerate(groups, 1):
                for m in members:
                    c = by_id[m]
                    w.writerow([i, "", m, c["n_substantive"], c["n_brief"],
                                c["function_tag"]])
        print(f"\nWorksheet: {args.out}  ({len(groups)} groups)")
        print("Set 'merge_into' to the canonical name for rows to merge;")
        print("leave blank to keep a cluster as it stands.")


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.stderr.close()
