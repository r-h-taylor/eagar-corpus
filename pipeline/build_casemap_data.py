#!/usr/bin/env python3
"""
build_casemap_data.py — scan the corpus and produce a JSON dataset for
the case-map visualization.

For each canonical cluster referenced in the corpus, produces:
  - cluster_id
  - n_substantive (lectures where the case is in case_index.md)
  - n_brief (lectures where the case is in extended_case_references.md only)
  - n_total
  - function_tag ("industrial-historical" | "forensic" | "biographical" |
                  "technical-narrative" | "unclassified")
  - lectures: list of {video_id, anchor, treatment} where treatment is
    "substantive" or "brief"

Function-tag assignment uses the Top 20 table from the JME paper as the
seed taxonomy; clusters outside the top-20 are tagged "unclassified" and
the visualization can choose to color them neutrally.

Output: output/v1/casemap_data.json
"""

import json
import re
from collections import defaultdict
from pathlib import Path

from aliases import parse_fields, resolve

LECTURES_DIR = Path("output/v1/lectures")
OUT_PATH = Path("output/v1/casemap_data.json")
TAGS_PATH = Path("output/v1/case_function_tags.json")  # produced by classify_cases.py


# Function tags from Table 1 of the JME paper — only the top-20 are seeded.
# Order matches how Table 1 groups them.
FUNCTION_TAGS = {
    "industrial-historical": [
        "Saugus Ironworks",
        "1973 Arab oil embargo",
        "Bethlehem Steel Burns Harbor",
        "Watertown Arsenal titanium development",
        "Basic oxygen furnace introduction in Austria",
        "Continuous casting and steel industry capacity collapse",
        "Wright brothers' aircraft engine",
        "British Welding Institute founding",
        "Andrew Mellon all-aluminum Pierce Arrow automobile",
        "Iron whiskers (1950s screw dislocation studies)",
        "Clayton Christensen innovator's dilemma research—steel mill cost data",
        "Air Force Buy-to-Fly Ratio in Aircraft Manufacturing",
        "Lakshmi Mittal steel mill acquisition strategy",
    ],
    "forensic": [
        "Liberty ships and SS Schenectady",
        "World Trade Center collapse",
        "V-22 Osprey aircraft",
        "Soviet Alpha-class submarine",
        "Space Shuttle Challenger",
        "Space Shuttle cost overrun",
    ],
    "biographical": [
        "Tom Eagar's steel company experience",
    ],
    "technical-narrative": [
        # Currently empty in top-20; clusters tagged technical via heuristics
    ],
}


# Load model-assisted tags if available
def load_classifier_tags() -> dict:
    if TAGS_PATH.exists():
        try:
            return json.loads(TAGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def assign_function_tag(cluster_id: str, classifier_tags: dict) -> str:
    """Return the function tag for a cluster_id.
    Priority: hand-seeded > classifier > heuristic > 'unclassified'."""
    # Hand-seeded from Table 1 wins
    for tag, names in FUNCTION_TAGS.items():
        if cluster_id in names:
            return tag
    # Classifier output
    if cluster_id in classifier_tags:
        return classifier_tags[cluster_id]
    # Heuristic fallback
    cid_lower = cluster_id.lower()
    forensic_kw = ["fracture", "failure", "collapse", "crack", "fatigue", "explosion",
                   "accident", "disaster"]
    if any(k in cid_lower for k in forensic_kw):
        return "forensic"
    industrial_kw = ["steel mill", "ironworks", "plant", "industry", "industrial",
                     "manufacturing"]
    if any(k in cid_lower for k in industrial_kw):
        return "industrial-historical"
    return "unclassified"


def parse_case_anchors(text: str) -> list[dict]:
    """Return list of {cluster_id, anchors:[...]}"""
    out = []
    for block in re.split(r"\n(?=### )", text):
        if not block.startswith("### "):
            continue
        fields = parse_fields(block)
        if not fields:
            continue
        # First value only; multi-value fields list related cases, not aliases.
        cluster_id = resolve(fields[0][0])
        if not cluster_id or cluster_id.startswith("PROPOSED:"):
            continue  # Skip PROPOSED and unparseable, focus on canonical
        anchor_m = re.search(r"\*\*Anchor:\*\*\s*([^\n]+)", block)
        anchors = []
        if anchor_m:
            for span in re.finditer(r"`§(\d+)\.p(\d+)(?:\s*[\-–—]\s*§(\d+)\.p(\d+))?`",
                                     anchor_m.group(1)):
                sec, para = span.group(1), span.group(2)
                anchors.append(f"§{sec}.p{para}")
        out.append({"cluster_id": cluster_id, "anchors": anchors or ["?"]})
    return out


def main():
    # Load classifier tags if classify_cases.py has been run
    classifier_tags = load_classifier_tags()
    if classifier_tags:
        print(f"Loaded {len(classifier_tags)} classifier-assigned tags from {TAGS_PATH}")
    else:
        print(f"No classifier tags found at {TAGS_PATH}; using heuristic fallback only")

    # cluster_id -> {n_substantive, n_brief, lectures:[]}
    data = defaultdict(lambda: {
        "n_substantive": 0,
        "n_brief": 0,
        "lectures": [],
    })

    for lec_dir in sorted(LECTURES_DIR.iterdir()):
        if not lec_dir.is_dir():
            continue
        vid = lec_dir.name

        ci = lec_dir / "case_index.md"
        if ci.exists():
            for entry in parse_case_anchors(ci.read_text(encoding="utf-8")):
                cid = entry["cluster_id"]
                data[cid]["n_substantive"] += 1
                for anchor in entry["anchors"]:
                    data[cid]["lectures"].append({
                        "video_id": vid,
                        "anchor": anchor,
                        "treatment": "substantive",
                    })

        ext = lec_dir / "extended_case_references.md"
        if ext.exists():
            for entry in parse_case_anchors(ext.read_text(encoding="utf-8")):
                cid = entry["cluster_id"]
                # Only count brief if not also substantive in this lecture
                already_substantive = any(
                    l["video_id"] == vid and l["treatment"] == "substantive"
                    for l in data[cid]["lectures"]
                )
                if not already_substantive:
                    data[cid]["n_brief"] += 1
                    for anchor in entry["anchors"]:
                        data[cid]["lectures"].append({
                            "video_id": vid,
                            "anchor": anchor,
                            "treatment": "brief",
                        })

    # Convert to output list with function tags and totals
    cases = []
    for cid, info in data.items():
        cases.append({
            "cluster_id": cid,
            "function_tag": assign_function_tag(cid, classifier_tags),
            "n_substantive": info["n_substantive"],
            "n_brief": info["n_brief"],
            "n_total": info["n_substantive"] + info["n_brief"],
            "lectures": info["lectures"],
        })

    # Sort by total frequency descending
    cases.sort(key=lambda c: -c["n_total"])

    # Build the output structure
    out = {
        "generated_at": __import__("datetime").datetime.now(
            tz=__import__("datetime").timezone.utc).isoformat(),
        "n_cases": len(cases),
        "summary": {
            "by_function_tag": {},
        },
        "cases": cases,
    }
    for tag in ["industrial-historical", "forensic", "biographical",
                "technical-narrative", "mixed", "unclassified"]:
        out["summary"]["by_function_tag"][tag] = sum(
            1 for c in cases if c["function_tag"] == tag
        )

    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    print(f"  Total cases: {len(cases)}")
    print(f"  By function tag:")
    for tag, n in out["summary"]["by_function_tag"].items():
        print(f"    {tag:30s} {n:>4}")

    print(f"\n  Top 10 by frequency:")
    for c in cases[:10]:
        sub = c["n_substantive"]
        brief = c["n_brief"]
        print(f"    {sub:>2}+{brief:>2}  [{c['function_tag']:22s}]  {c['cluster_id']}")


if __name__ == "__main__":
    main()
