#!/usr/bin/env python3
"""
aliases.py — canonical cluster-id resolution for the Eagar corpus pipeline.

Four problems this solves, all of which caused silent data loss before:

1. Delimiter drift. Extracted `canonical_cluster_id` values appear variously
   double-quoted, single-quoted, backtick-delimited, asterisk-wrapped, or
   bare. Consumers recognising only double quotes skipped the rest — 505
   canonical references corpus-wide.

2. Name drift. The same case is extracted under different names in different
   lectures ("Seawolf submarine hydrogen cracking", "USS Seawolf HY-100
   hydrogen cracking", "SSN-21 Sea Wolf hull cracking problem"), fragmenting
   one case into a dozen clusters and splitting its counts. The alias table in
   ontology/aliases.json maps variants to canonical names.

3. Multi-value fields. Some fields carry several names in one value, as a
   semicolon list or as "Either X or Y". These are NOT alias lists —
   inspection shows they name cases a passage *touches*, mixing subject with
   context. "Liberty ships and SS Schenectady; ...; WWII Welded Merchant
   Vessel Structural Failures (Fleet-Wide)" pairs a case with a wider-scope
   study; "Lead pipe in residential plumbing; ...; Roman aqueducts" pairs two
   plainly distinct cases. Splitting them automatically would merge cases that
   are genuinely separate, so this module takes the FIRST value and reports
   the remainder for human review.

   Slash-separated values are deliberately NOT split. A slash appears both as
   a separator ("Dow Chemical magnesium price cartel / Alcoa monopoly and
   price fixing") and inside single legitimate names ("Deepwater Horizon / BP
   Macondo well blowout", "Pittsburgh Reduction Company / Alcoa environmental
   pollution", "Egyptian obelisk engineering mystery (Al Bakun / Wendell
   Wilkenning fracture analysis)"). No length or spacing heuristic separates
   the two reliably, and splitting truncates real names silently while failing
   to split merely leaves them visible in --scan. The safe error is the loud
   one.

4. Two source files. Substantive treatments are recorded in case_index.md;
   brief mentions in extended_case_references.md. A consumer reading only the
   first misses every brief-only cluster.

Unknown ids pass through unchanged rather than being discarded. Silent
dropping is what caused the original loss; --scan is how you find out what is
unrecognised.

Usage:
    from aliases import extract_cluster_ids, iter_corpus_ids, parse_fields, resolve

    for cid in extract_cluster_ids(text):
        ...                       # resolved to canonical form

Audit the corpus:
    python3 aliases.py --scan
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIAS_PATH = ROOT / "ontology" / "aliases.json"
LECTURES_DIR = ROOT / "output" / "v1" / "lectures"

CASE_INDEX = "case_index.md"
EXTENDED_REFS = "extended_case_references.md"
SOURCE_FILES = (CASE_INDEX, EXTENDED_REFS)

CLUSTER_ID_RE = re.compile(
    r'canonical_cluster_id:\s*\*?\*?\s*'
    r'(?:"([^"]+)"'             # "double quoted"
    r"|'([^']+)'"               # 'single quoted'
    r'|`([^`]+)`'               # `backticked`
    r'|([^\n]+?)\s*$)',         # bare, to end of line
    re.MULTILINE,
)

# Commentary the extractor appended to a value, and everything after it.
COMMENTARY_RE = re.compile(
    r'\s*(?:[\u2014\u2013]|--|\(|\[|\*)?\s*'
    r'(?:likely matches|candidates? from the canon|also recurs as|also touches|'
    r'also relates to|matches canonical cluster|matched from canon|'
    r'closest existing|closest aggregate match|closest match|closest|'
    r'one of several|partial match|probably|possibly|see also|adjacent|'
    r'overlapping|this is the signature)\b.*$',
    re.I,
)

# Fields recording an explicit non-match rather than a cluster id.
NON_MATCH_RE = re.compile(
    r'^\s*\*?(?:none directly|none|n/?a|not directly named|no match|unmatched|'
    r'not named|unclear)\b',
    re.I,
)

# "Either X or Y" — capture both sides.
EITHER_OR_RE = re.compile(
    r'^\s*either\s+(.+?)\s+or\s+(.+?)\s*$', re.I | re.S)

_cache: dict | None = None


# ----------------------------------------------------------------------
# Alias table
# ----------------------------------------------------------------------

def load_aliases(path: Path | None = None) -> dict:
    """Return {variant_lower: canonical}. A missing file is not an error."""
    global _cache
    if _cache is not None and path is None:
        return _cache
    p = path or ALIAS_PATH
    table: dict[str, str] = {}
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        for canonical, variants in data.get("aliases", {}).items():
            table[canonical.strip().lower()] = canonical
            for v in variants:
                key = v.strip().lower()
                if key in table and table[key] != canonical:
                    raise ValueError(
                        f"Alias {v!r} maps to both {table[key]!r} and {canonical!r}"
                    )
                table[key] = canonical
    if path is None:
        _cache = table
    return table


# ----------------------------------------------------------------------
# Field parsing
# ----------------------------------------------------------------------

def split_multivalue(raw: str) -> tuple[str, list[str]]:
    """
    Return (primary, others) for a possibly multi-value field.

    Handles semicolon lists and "Either X or Y". Slashes are left alone: see
    the module docstring for why. The remainder is returned for review rather
    than resolved, because these fields list related cases, not aliases.
    """
    s = raw.strip()

    m = EITHER_OR_RE.match(s)
    if m:
        a, b = m.group(1).strip(), m.group(2).strip()
        if a and b:
            return a, [b]

    if ";" in s:
        parts = [p.strip() for p in s.split(";") if p.strip()]
        if len(parts) > 1:
            return parts[0], parts[1:]

    return s, []


def clean_id(raw: str) -> str:
    """Strip delimiters, trailing commentary, and stray punctuation."""
    s = raw.strip().strip('`"\'* \t')
    if NON_MATCH_RE.match(s):
        return ""
    s = COMMENTARY_RE.sub("", s)
    s = s.strip().strip('`"\'*,; ').strip()
    # Discard anything reduced to a fragment.
    return s if len(s) > 2 else ""


def resolve(cluster_id: str, table: dict | None = None) -> str:
    """Map a raw cluster id to its canonical form. Unknown ids pass through."""
    cid = clean_id(cluster_id)
    if not cid:
        return cid
    t = table if table is not None else load_aliases()
    return t.get(cid.lower(), cid)


def parse_fields(text: str) -> list[tuple[str, list[str]]]:
    """Raw (primary, others) pairs for every canonical_cluster_id field."""
    out = []
    for m in CLUSTER_ID_RE.finditer(text):
        raw = next((g for g in m.groups() if g), "")
        if raw and raw.strip():
            out.append(split_multivalue(raw))
    return out


def extract_cluster_ids(text: str, table: dict | None = None,
                        include_proposed: bool = False) -> list[str]:
    """All cluster ids in one source file, resolved to canonical form."""
    out = []
    for primary, _others in parse_fields(text):
        cid = clean_id(primary)
        if not cid:
            continue
        if cid.startswith("PROPOSED:") and not include_proposed:
            continue
        out.append(resolve(cid, table))
    return out


def iter_corpus_ids(lectures_dir: Path | None = None,
                    table: dict | None = None,
                    include_proposed: bool = False):
    """
    Yield (lecture_id, source_file, cluster_id) across the whole corpus,
    reading both case_index.md and extended_case_references.md.
    """
    d = lectures_dir or LECTURES_DIR
    t = table if table is not None else load_aliases()
    for lec in sorted(d.iterdir()):
        if not lec.is_dir():
            continue
        for name in SOURCE_FILES:
            f = lec / name
            if not f.exists():
                continue
            for cid in extract_cluster_ids(f.read_text(encoding="utf-8"),
                                           t, include_proposed):
                yield lec.name, name, cid


# ----------------------------------------------------------------------
# Drift audit
# ----------------------------------------------------------------------

TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
GENERIC = {"case", "cases", "problem", "failure", "failures", "the", "of",
           "and", "in", "at", "on", "for", "to", "with", "a", "an"}


def _tokens(s: str) -> set[str]:
    return {t for t in TOKEN_RE.findall(s.lower())
            if t not in GENERIC and len(t) > 1}


def _compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    jac = len(ta & tb) / len(ta | tb) if (ta or tb) else 0.0
    return max(jac, SequenceMatcher(None, _compact(a), _compact(b)).ratio())


def scan(threshold: float = 0.72, show_fields: bool = False) -> None:
    table = load_aliases()
    canonicals = sorted(set(table.values()))
    if not canonicals:
        print("No alias table found; nothing to compare against.\n", file=sys.stderr)
    if not LECTURES_DIR.exists():
        sys.exit(f"No lectures directory at {LECTURES_DIR}")

    seen: dict[str, set[str]] = defaultdict(set)
    per_file: dict[str, int] = defaultdict(int)
    for lec, src, cid in iter_corpus_ids(table=table):
        seen[cid].add(lec)
        per_file[src] += 1

    multivalue: list[tuple[str, str, str, list[str]]] = []
    for lec in sorted(LECTURES_DIR.iterdir()):
        if not lec.is_dir():
            continue
        for name in SOURCE_FILES:
            f = lec / name
            if not f.exists():
                continue
            for primary, others in parse_fields(f.read_text(encoding="utf-8")):
                if others:
                    multivalue.append((lec.name, name, primary, others))

    known = {c.lower() for c in canonicals}
    findings = []
    for cid, lecs in seen.items():
        if cid.lower() in known:
            continue
        best, score = None, 0.0
        for canon in canonicals:
            s = similarity(cid, canon)
            if s > score:
                best, score = canon, s
        if score >= threshold:
            findings.append((score, cid, best, sorted(lecs)))
    findings.sort(reverse=True)

    print(f"Distinct resolved ids: {len(seen)}")
    for name in SOURCE_FILES:
        print(f"  references in {name}: {per_file.get(name, 0)}")
    print(f"Unresolved near-matches at threshold {threshold}: {len(findings)}")
    print(f"Multi-value fields needing review: {len(multivalue)}\n")

    if findings:
        print("=" * 72)
        print("UNRESOLVED NEAR-MATCHES")
        print("=" * 72)
        for score, cid, best, lecs in findings:
            print(f"\n  {score:.2f}  {cid}")
            print(f"        looks like: {best}")
            print(f"        in: {', '.join(lecs[:6])}"
                  f"{' ...' if len(lecs) > 6 else ''}")
        print("\nAdd confirmed variants to ontology/aliases.json, or leave them "
              "if they are genuinely distinct cases.\n")

    if multivalue:
        by_lec: dict[str, int] = defaultdict(int)
        for lec, _s, _p, _o in multivalue:
            by_lec[lec] += 1
        print("=" * 72)
        print("MULTI-VALUE FIELDS  (first value used; remainder NOT resolved)")
        print("=" * 72)
        print("These name cases a passage touches, not aliases. Splitting them")
        print("automatically would merge genuinely distinct cases.\n")
        for lec, count in sorted(by_lec.items(), key=lambda kv: -kv[1]):
            print(f"  {count:3d}  {lec}")
        if show_fields:
            for lec, src, primary, others in multivalue:
                print(f"\n  {lec}  ({src})")
                print(f"      used:    {clean_id(primary)}")
                for o in others:
                    c = clean_id(o)
                    if c:
                        print(f"      ignored: {c}")
        else:
            print("\n  Re-run with --show-fields to list them.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", action="store_true",
                    help="Audit the corpus for unresolved near-matches and multi-value fields")
    ap.add_argument("--show-fields", action="store_true",
                    help="With --scan, list every multi-value field in full")
    ap.add_argument("--threshold", type=float, default=0.72)
    ap.add_argument("--resolve", metavar="ID",
                    help="Resolve a single cluster id and print the result")
    args = ap.parse_args()

    if args.resolve:
        print(resolve(args.resolve))
    elif args.scan:
        scan(args.threshold, args.show_fields)
    else:
        table = load_aliases()
        canon = sorted(set(table.values()))
        print(f"Alias table: {len(table)} variants -> {len(canon)} canonical names")
        print(f"Source: {ALIAS_PATH}")


if __name__ == "__main__":
    main()
