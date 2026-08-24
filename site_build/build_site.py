#!/usr/bin/env python3
"""
Eagar Corpus Site Generator — Phase A.

Reads pipeline output from output/v1/lectures/ and produces a static
site at site/ with:
  - Per-lecture three-column reading pages
  - Browse pages (lectures, cases)
  - Per-case pages with paragraph appearances across the corpus
  - Full-text search via lunr.js
  - Editorial register tooltips

Usage:
    python3 build_site.py
    python3 build_site.py --serve         # also start a local server
    python3 build_site.py --port 8080

Requirements:
    pip install jinja2 markdown pyyaml

Output:
    site/
      index.html
      about.html
      lectures/
        index.html
        {video_id}.html  (per-lecture page)
      cases/
        index.html
        {cluster_id}.html
      search.html
      static/
        css/site.css
        js/{site,search,reader}.js
      data/
        search_index.json
        case_paragraph_map.json
        cross_references.json
        lectures_meta.json
        cases_meta.json
      raw/{video_id}.txt  (copied raw transcripts for browser access)
      lecture_data/{video_id}/  (per-lecture artifacts copied for fetch)
"""

import argparse
import http.server
import json
import re
import shutil
import socketserver
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    import markdown as md_lib
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install: pip install jinja2 markdown pyyaml")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path.cwd()
LECTURES_SRC = ROOT / "output" / "v1" / "lectures"
CASEMAP_SRC = ROOT / "output" / "v1" / "casemap_data.json"
REFS_DIR = ROOT / "pipeline_refs"
TEMPLATES_DIR = ROOT / "site_build" / "templates"
STATIC_DIR = ROOT / "site_build" / "static"
SITE_OUT = ROOT / "site"

REQUIRED_FILES = [
    "layer2.md", "layer3.md", "anchors.json",
    "transformation_log.md", "editorial_register.md",
    "case_index.md", "metadata.json",
]

FUNCTION_TAGS_PATH = ROOT / "output" / "v1" / "case_function_tags.json"


def load_function_tags():
    """Load classifier-assigned function tags. Returns {cluster_id: tag} or empty."""
    if FUNCTION_TAGS_PATH.exists():
        try:
            return json.loads(FUNCTION_TAGS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  Warning: could not load {FUNCTION_TAGS_PATH}: {e}")
    return {}


# ---------------------------------------------------------------------------
# Lecture loading
# ---------------------------------------------------------------------------

def parse_yaml_frontmatter(text):
    """Extract YAML front matter and return (frontmatter, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, parts[2].lstrip("\n")


def parse_layer3_sections(body):
    """Parse layer3.md body into sections and paragraphs.

    Returns a list of section dicts:
        [
          {
            "section_id": "s1",
            "section_num": 1,
            "title": "Title",
            "timestamp": "02:30",
            "paragraphs": [
              {"l3_id": "§1.p1", "html": "...", "is_student": bool,
               "is_stage_direction": bool, "raw_text": "..."}
            ]
          }
        ]
    """
    sections = []
    # Section header: ## §N. Title [MM:SS]
    section_re = re.compile(
        r"^##\s*§(\d+)\.\s*(.+?)\s*\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*$",
        re.MULTILINE,
    )
    matches = list(section_re.finditer(body))
    if not matches:
        # No sections — single implicit section
        return [{
            "section_id": "s1",
            "section_num": 1,
            "title": "Lecture",
            "timestamp": "00:00",
            "paragraphs": parse_paragraphs(body, 1),
        }]

    for i, m in enumerate(matches):
        sec_num = int(m.group(1))
        title = m.group(2).strip()
        ts = m.group(3)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section_body = body[start:end]
        sections.append({
            "section_id": f"s{sec_num}",
            "section_num": sec_num,
            "title": title,
            "timestamp": ts,
            "paragraphs": parse_paragraphs(section_body, sec_num),
        })
    return sections


def parse_paragraphs(text, section_num):
    """Parse paragraphs from a section body.

    Each paragraph starts with `§N.pM` anchor and is followed by content.
    """
    paragraphs = []
    # Paragraph anchor: `§N.pM`
    para_re = re.compile(r"`§(\d+)\.p(\d+)`\s*(.*?)(?=`§\d+\.p\d+`|\Z)", re.DOTALL)
    for m in para_re.finditer(text):
        sec_n = int(m.group(1))
        para_n = int(m.group(2))
        content = m.group(3).strip()
        l3_id = f"§{sec_n}.p{para_n}"
        is_student = content.startswith("**Student:**")
        is_stage = content.startswith("*[") and content.rstrip().endswith("]*")
        html = md_lib.markdown(content, extensions=["extra"])
        # Extract raw text for search
        raw_text = re.sub(r"<[^>]+>", " ", html).strip()
        paragraphs.append({
            "l3_id": l3_id,
            "html": html,
            "is_student": is_student,
            "is_stage_direction": is_stage,
            "raw_text": raw_text,
        })
    return paragraphs


def parse_layer2_paragraphs(body):
    """Parse layer2.md body into a list of paragraph dicts.

    Each paragraph starts with `pN` anchor and [MM:SS] timestamp.
    """
    paragraphs = []
    # Match: `pN` [MM:SS] content...
    para_re = re.compile(
        r"`(p\d+)`\s*\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*?)(?=`p\d+`|\Z)",
        re.DOTALL,
    )
    for m in para_re.finditer(body):
        l2_id = m.group(1)
        ts = m.group(2)
        content = m.group(3).strip()
        html = md_lib.markdown(content, extensions=["extra"])
        raw_text = re.sub(r"<[^>]+>", " ", html).strip()
        paragraphs.append({
            "l2_id": l2_id,
            "timestamp": ts,
            "html": html,
            "raw_text": raw_text,
        })
    return paragraphs


def parse_register(text):
    """Parse editorial_register.md and return a dict {l3_id: html_note}.

    The register is heterogeneous in format — we use a heuristic:
    look for any heading or bold line containing §N.pM, and capture
    the following block until the next such heading.
    """
    register = {}
    # Find all l3_id references and capture text until next reference
    pattern = re.compile(
        r"(?:###?\s*|^\s*\*\*\s*)(§\d+\.p\d+)(.*?)(?=(?:###?\s*|^\s*\*\*\s*)§\d+\.p\d+|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    for m in pattern.finditer(text):
        l3_id = m.group(1)
        note = m.group(2).strip().lstrip("—").strip()
        if not note:
            continue
        # Render as HTML
        html = md_lib.markdown(note, extensions=["extra"])
        register[l3_id] = html
    return register


def parse_case_index(text):
    """Parse case_index.md and return a list of case entries.

    Returns: [
      {"cluster_id": str, "is_proposed": bool, "anchor": "§N.pM",
       "frame": str, "raw_md": str}
    ]
    """
    cases = []
    # Each case entry is a ### heading followed by - **Anchor:** etc.
    entry_re = re.compile(r"^###\s+(.+?)\n(.*?)(?=^###\s+|\Z)", re.MULTILINE | re.DOTALL)
    for m in entry_re.finditer(text):
        case_name = m.group(1).strip()
        body = m.group(2)

        # Look for canonical_cluster_id
        cluster_match = re.search(
            r"\*\*canonical_cluster_id:\*\*\s*[\"']?([^\"'\n]+?)[\"']?\s*$",
            body, re.MULTILINE,
        )
        cluster_id = cluster_match.group(1).strip() if cluster_match else case_name
        # Strip surrounding quotes
        cluster_id = cluster_id.strip("\"'")
        is_proposed = cluster_id.startswith("PROPOSED:")
        if is_proposed:
            cluster_id = cluster_id[len("PROPOSED:"):].strip()

        # Anchor(s)
        anchor_match = re.search(
            r"\*\*Anchor:\*\*\s*`?(§\d+\.p\d+)`?",
            body,
        )
        anchor = anchor_match.group(1) if anchor_match else ""

        # Frame in this lecture
        frame_match = re.search(
            r"\*\*Frame in this lecture:\*\*\s*(.+?)(?=^\s*-\s*\*\*|\Z)",
            body, re.MULTILINE | re.DOTALL,
        )
        frame = frame_match.group(1).strip() if frame_match else ""

        cases.append({
            "case_name": case_name,
            "cluster_id": cluster_id,
            "is_proposed": is_proposed,
            "anchor": anchor,
            "frame": frame,
            "raw_md": body,
        })
    return cases


def load_lecture(lec_dir):
    """Load and parse all files for one lecture."""
    lec = {"video_id": lec_dir.name, "src_dir": lec_dir}

    # Verify all required files present
    missing = [f for f in REQUIRED_FILES if not (lec_dir / f).exists()]
    if missing:
        lec["error"] = f"Missing files: {missing}"
        return lec

    # metadata
    lec["metadata"] = json.loads((lec_dir / "metadata.json").read_text(encoding="utf-8"))

    # layer 3
    l3_text = (lec_dir / "layer3.md").read_text(encoding="utf-8")
    l3_fm, l3_body = parse_yaml_frontmatter(l3_text)
    lec["title"] = (
        lec["metadata"].get("corpus_id")
        or l3_fm.get("title")
        or f"Lecture {lec_dir.name}"
    )
    lec["course"] = (
        l3_fm.get("course_canonical")
        or lec["metadata"].get("course_canonical")
        or l3_fm.get("course")
        or lec["metadata"].get("course", "")
    )
    lec["term"] = l3_fm.get("term", lec["metadata"].get("term", ""))
    lec["session"] = l3_fm.get("session", lec["metadata"].get("session", ""))
    lec["sections"] = parse_layer3_sections(l3_body)

    # layer 2
    l2_text = (lec_dir / "layer2.md").read_text(encoding="utf-8")
    _, l2_body = parse_yaml_frontmatter(l2_text)
    lec["layer2_paragraphs"] = parse_layer2_paragraphs(l2_body)

    # anchors
    try:
        anchors = json.loads((lec_dir / "anchors.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        anchors = {}
    # Normalize the two shapes into a flat list
    flat_anchors = []
    if "sections" in anchors:
        for sec in anchors.get("sections", []):
            for a in sec.get("anchors", []):
                flat_anchors.append(a)
    elif "anchors" in anchors:
        flat_anchors = anchors["anchors"]
    lec["anchors"] = flat_anchors
    # Build a quick map: l3_id -> {l2_ids, timestamp_range, raw_line_range}
    lec["anchor_map"] = {a["l3_id"]: a for a in flat_anchors if "l3_id" in a}

    # editorial register
    reg_text = (lec_dir / "editorial_register.md").read_text(encoding="utf-8")
    lec["register"] = parse_register(reg_text)

    # case index
    case_text = (lec_dir / "case_index.md").read_text(encoding="utf-8")
    lec["cases"] = parse_case_index(case_text)

    # transformation log (kept as raw markdown — viewable but not parsed deeply)
    lec["transformation_log"] = (lec_dir / "transformation_log.md").read_text(encoding="utf-8")

    # raw transcript (for layer 1 column)
    layer1_path = lec_dir / "layer1.txt"
    if layer1_path.exists():
        lec["layer1_text"] = layer1_path.read_text(encoding="utf-8")
    else:
        lec["layer1_text"] = ""

    return lec


def load_all_lectures():
    """Load all lectures from output/v1/lectures/."""
    lectures = []
    for lec_dir in sorted(LECTURES_SRC.iterdir()):
        if not lec_dir.is_dir():
            continue
        # Skip directories with FAILED.txt
        if (lec_dir / "FAILED.txt").exists():
            continue
        lec = load_lecture(lec_dir)
        if "error" in lec:
            print(f"  Skipping {lec_dir.name}: {lec['error']}")
            continue
        # Skip guest-taught lectures marked non-visible (Eagar lectures have
        # no 'visible' field, so .get returns None and they are kept).
        if lec["metadata"].get("visible") is False:
            print(f"  Hiding guest lecture {lec_dir.name}")
            continue
        lectures.append(lec)
    return lectures


# ---------------------------------------------------------------------------
# Inverted index: cluster_id -> [(video_id, l3_id, frame)]
# ---------------------------------------------------------------------------

def build_inverted_case_index(lectures):
    """Build the inverted index used by per-case pages."""
    inverted = defaultdict(list)
    for lec in lectures:
        for case in lec["cases"]:
            # Skip empty
            if not case["cluster_id"]:
                continue
            inverted[case["cluster_id"]].append({
                "video_id": lec["video_id"],
                "title": lec["title"],
                "course": lec["course"],
                "term": lec["term"],
                "anchor": case["anchor"],
                "is_proposed": case["is_proposed"],
                "frame": case["frame"],
                "case_name": case["case_name"],  # how this lecture named it
            })
    return dict(inverted)


# ---------------------------------------------------------------------------
# Search index
# ---------------------------------------------------------------------------

def build_search_index(lectures, inverted_case_index):
    """Build documents for lunr.js to index.

    Each document is one paragraph (layer 2 text) so search returns
    paragraph-level hits with deep links.
    """
    docs = []
    for lec in lectures:
        for p in lec["layer2_paragraphs"]:
            docs.append({
                "id": f"{lec['video_id']}#{p['l2_id']}",
                "type": "paragraph",
                "video_id": lec["video_id"],
                "lecture_title": lec["title"],
                "course": lec["course"],
                "term": lec["term"],
                "l2_id": p["l2_id"],
                "timestamp": p["timestamp"],
                "content": p["raw_text"],
            })

    # Also index cases
    for cluster_id, appearances in inverted_case_index.items():
        # Compose the case's text from its appearances' frames
        content = " ".join(a["frame"] for a in appearances if a["frame"])
        docs.append({
            "id": f"case:{cluster_id}",
            "type": "case",
            "cluster_id": cluster_id,
            "content": f"{cluster_id} {content}",
            "appearance_count": len(appearances),
        })

    # Lecture-level documents
    for lec in lectures:
        section_titles = " ".join(s["title"] for s in lec["sections"])
        docs.append({
            "id": f"lecture:{lec['video_id']}",
            "type": "lecture",
            "video_id": lec["video_id"],
            "lecture_title": lec["title"],
            "course": lec["course"],
            "term": lec["term"],
            "content": f"{lec['title']} {lec['course']} {section_titles}",
        })

    return docs


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def setup_jinja():
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


def render_all(lectures, inverted, env, search_docs):
    SITE_OUT.mkdir(parents=True, exist_ok=True)
    (SITE_OUT / "lectures").mkdir(exist_ok=True)
    (SITE_OUT / "cases").mkdir(exist_ok=True)
    (SITE_OUT / "data").mkdir(exist_ok=True)
    (SITE_OUT / "lecture_data").mkdir(exist_ok=True)
    # .nojekyll is required: lecture video_ids / case ids have leading
    # underscores that GitHub Pages' Jekyll would otherwise hide (404s).
    (SITE_OUT / ".nojekyll").touch()

    # Copy static assets
    site_static = SITE_OUT / "static"
    if site_static.exists():
        shutil.rmtree(site_static)
    shutil.copytree(STATIC_DIR, site_static)

    # Per-lecture pages
    # Compute prev/next within (course_module, term) for each lecture.
    # The same key the corpus_id uses to scope sequence numbering.
    from collections import defaultdict as _dd
    _groups = _dd(list)
    for _lec in lectures:
        _cm = _lec["metadata"].get("course_module") or _lec.get("course") or ""
        _tm = _lec.get("term") or ""
        _cid = _lec["metadata"].get("corpus_id") or ""
        _groups[(_cm, _tm)].append((_cid, _lec))
    for _key, _items in _groups.items():
        _items.sort(key=lambda x: x[0])
        for _i, (_cid, _lec) in enumerate(_items):
            _lec["prev_id"] = _items[_i - 1][0] if _i > 0 else None
            _lec["prev_vid"] = _items[_i - 1][1]["video_id"] if _i > 0 else None
            _lec["next_id"] = _items[_i + 1][0] if _i + 1 < len(_items) else None
            _lec["next_vid"] = _items[_i + 1][1]["video_id"] if _i + 1 < len(_items) else None

    lec_tmpl = env.get_template("lecture.html")
    for lec in lectures:
        # Build anchor_map JSON for the page's JS
        anchor_map_json = json.dumps(lec["anchor_map"])
        register_json = json.dumps(lec["register"])
        out = lec_tmpl.render(
            lec=lec,
            anchor_map_json=anchor_map_json,
            register_json=register_json,
        )
        (SITE_OUT / "lectures" / f"{lec['video_id']}.html").write_text(out, encoding="utf-8")

        # Per-lecture data directory for downloads
        lec_data_dir = SITE_OUT / "lecture_data" / lec["video_id"]
        lec_data_dir.mkdir(exist_ok=True)
        for f in REQUIRED_FILES:
            src = lec["src_dir"] / f
            if src.exists():
                shutil.copy(src, lec_data_dir / f)

    # Lectures browse page
    browse_tmpl = env.get_template("lectures_browse.html")
    lectures_meta = [
        {
            "video_id": l["video_id"],
            "title": l["title"],
            "course": l["course"],
            "term": l["term"],
            "session": l["session"],
            "section_count": len(l["sections"]),
            "case_count": len(l["cases"]),
        }
        for l in lectures
    ]
    out = browse_tmpl.render(lectures=lectures_meta)
    (SITE_OUT / "lectures" / "index.html").write_text(out, encoding="utf-8")

    # Per-case pages
    case_tmpl = env.get_template("case.html")
    for cluster_id, appearances in inverted.items():
        # Get a Layer 3 snippet for each appearance
        snippets = []
        for app in appearances:
            lec = next((l for l in lectures if l["video_id"] == app["video_id"]), None)
            if not lec:
                continue
            # Find the paragraph by l3_id across all sections
            para = None
            for sec in lec["sections"]:
                for p in sec["paragraphs"]:
                    if p["l3_id"] == app["anchor"]:
                        para = p
                        break
                if para:
                    break
            snippets.append({
                "video_id": app["video_id"],
                "lecture_title": app["title"],
                "course": app["course"],
                "term": app["term"],
                "anchor": app["anchor"],
                "frame": app["frame"],
                "paragraph_html": para["html"] if para else "",
            })
        out = case_tmpl.render(
            cluster_id=cluster_id,
            appearances=snippets,
            appearance_count=len(snippets),
            is_proposed=any(a["is_proposed"] for a in appearances),
        )
        # Sanitize cluster_id for filename
        safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", cluster_id)[:120]
        (SITE_OUT / "cases" / f"{safe_id}.html").write_text(out, encoding="utf-8")

    # Cases browse page
    cases_browse_tmpl = env.get_template("cases_browse.html")
    cases_meta = sorted(
        [
            {
                "cluster_id": cid,
                "safe_id": re.sub(r"[^a-zA-Z0-9_.-]", "_", cid)[:120],
                "appearance_count": len(appearances),
                "is_proposed": any(a["is_proposed"] for a in appearances),
            }
            for cid, appearances in inverted.items()
        ],
        key=lambda x: -x["appearance_count"],
    )
    out = cases_browse_tmpl.render(cases=cases_meta)
    (SITE_OUT / "cases" / "index.html").write_text(out, encoding="utf-8")

    # =========================================================
    # Case Map: render casemap.html + data/casemap_data.json
    # =========================================================
    function_tags = load_function_tags()
    print(f"  Loaded {len(function_tags)} function tags from classifier output")

    # Single source of truth: consume the casemap written by
    # build_casemap_data.py rather than regenerating it here. Two independently
    # maintained casemap writers is what produced the 1,594-vs-1,949 split.
    _src = json.loads(CASEMAP_SRC.read_text(encoding="utf-8"))
    _src_cases = _src["cases"] if isinstance(_src, dict) else _src
    print(f"  Loaded {len(_src_cases)} cases from {CASEMAP_SRC}")

    _lec_by_id = {l["video_id"]: l for l in lectures}
    _snippets = {}
    for _l in lectures:
        for _sec in _l.get("sections", []):
            for _p in _sec.get("paragraphs", []):
                _snippets[(_l["video_id"], _p.get("l3_id"))] = _p.get("raw_text", "")

    casemap_cases = []
    for _case in _src_cases:
        cluster_id = _case["cluster_id"]
        safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", cluster_id)[:120]

        lectures_list = []
        _seen = set()
        for _app in _case.get("lectures", []):
            _vid = _app.get("video_id")
            _anchor = _app.get("anchor", "")
            if (_vid, _anchor) in _seen:
                continue
            _seen.add((_vid, _anchor))
            _lec = _lec_by_id.get(_vid, {})
            _raw = _snippets.get((_vid, _anchor), "")
            _snip = (_raw[:140].rstrip() + "\u2026") if len(_raw) > 140 else _raw
            lectures_list.append({
                "video_id": _vid,
                "lecture_title": _lec.get("title", _vid),
                "course": _lec.get("course", ""),
                "term": _lec.get("term", ""),
                "anchor": _anchor,
                "treatment": _app.get("treatment", "substantive"),
                "snippet": _snip,
            })

        casemap_cases.append({
            "cluster_id": cluster_id,
            "safe_id": safe_id,
            "function_tag": _case.get("function_tag", "unclassified"),
            "n_substantive": _case.get("n_substantive", 0),
            "n_brief": _case.get("n_brief", 0),
            "n_total": _case.get("n_total", 0),
            "lectures": lectures_list,
        })

    casemap_cases.sort(key=lambda c: -c["n_total"])

    casemap_data = {
        "n_cases": len(casemap_cases),
        "cases": casemap_cases,
    }

    (SITE_OUT / "data").mkdir(parents=True, exist_ok=True)
    (SITE_OUT / "data" / "casemap_data.json").write_text(
        json.dumps(casemap_data), encoding="utf-8"
    )

    casemap_tmpl = env.get_template("casemap.html")
    out = casemap_tmpl.render(lecture_count=len(lectures))
    (SITE_OUT / "casemap.html").write_text(out, encoding="utf-8")
    print(f"  Wrote casemap.html ({len(casemap_cases)} cases)")

    # Quote Library: render quotes.html + data/quotes.json (from quotes_clean.json)
    import json as _json
    _qsrc = ROOT / "output" / "v1" / "quotes_clean.json"
    if _qsrc.exists():
        _quotes = _json.loads(_qsrc.read_text())
        _payload = [{
            "quote": q["quote"],
            "category": q.get("category", ""),
            "score": q.get("score", 0),
            "times_said": q.get("times_said", 1),
            "attribution": q.get("attribution", ""),
            "quoted_source": q.get("quoted_source", ""),
            "sources": [
                {
                    "corpus_id": s2["corpus_id"],
                    "link": _build_quote_link(s2["link"], q["quote"]),
                }
                for s2 in q.get("sources", []) if s2.get("link")
            ],
        } for q in _quotes]
        _payload.sort(key=lambda x: (-x["score"], -x["times_said"]))
        (SITE_OUT / "data" / "quotes.json").write_text(
            _json.dumps(_payload), encoding="utf-8")
        quotes_tmpl = env.get_template("quotes.html")
        out = quotes_tmpl.render(lecture_count=len(lectures))
        (SITE_OUT / "quotes.html").write_text(out, encoding="utf-8")
        print(f"  Wrote quotes.html ({len(_payload)} quotes)")
    else:
        print("  (skipped quotes.html — no quotes_clean.json)")

    # Research Library: render research.html + data/research.json (from research_curated.csv)
    import csv as _csv
    _rsrc = ROOT / "output" / "v1" / "research_curated.csv"
    if _rsrc.exists():
        _ideas = []
        with _rsrc.open(encoding="utf-8") as _f:
            for _r in _csv.DictReader(_f):
                _ideas.append({
                    "summary": _r.get("summary", ""),
                    "verbatim": _r.get("verbatim", ""),
                    "category": _r.get("category", ""),
                    "domain": _r.get("domain", ""),
                    "score": int(_r.get("score") or 0),
                    "corpus_id": _r.get("corpus_id", ""),
                    "anchor": _r.get("anchor", ""),
                    "link": _make_research_link(_r.get("link", "")),
                })
        _ideas.sort(key=lambda x: (-x["score"], x["category"], x["corpus_id"]))
        (SITE_OUT / "data" / "research.json").write_text(
            _json.dumps(_ideas), encoding="utf-8")
        research_tmpl = env.get_template("research.html")
        out = research_tmpl.render(lecture_count=len(lectures))
        (SITE_OUT / "research.html").write_text(out, encoding="utf-8")
        print(f"  Wrote research.html ({len(_ideas)} ideas)")
    else:
        print("  (skipped research.html — no research_curated.csv)")

    # Home page
    home_tmpl = env.get_template("home.html")
    out = home_tmpl.render(
        lecture_count=len(lectures),
        case_count=len(inverted),
        proposed_count=sum(
            1 for cid, apps in inverted.items() if any(a["is_proposed"] for a in apps)
        ),
        total_words=sum(
            sum(len(p["raw_text"].split()) for p in l["layer2_paragraphs"])
            for l in lectures
        ),
    )
    (SITE_OUT / "index.html").write_text(out, encoding="utf-8")

    # About page
    about_tmpl = env.get_template("about.html")
    out = about_tmpl.render()
    (SITE_OUT / "about.html").write_text(out, encoding="utf-8")

    # Search page
    search_tmpl = env.get_template("search.html")
    out = search_tmpl.render()
    (SITE_OUT / "search.html").write_text(out, encoding="utf-8")

    # Search index data
    (SITE_OUT / "data" / "search_docs.json").write_text(
        json.dumps(search_docs), encoding="utf-8"
    )
    (SITE_OUT / "data" / "lectures_meta.json").write_text(
        json.dumps(lectures_meta), encoding="utf-8"
    )
    (SITE_OUT / "data" / "cases_meta.json").write_text(
        json.dumps(cases_meta), encoding="utf-8"
    )
    (SITE_OUT / "data" / "case_paragraph_map.json").write_text(
        json.dumps(inverted), encoding="utf-8"
    )


def serve(port):
    handler = http.server.SimpleHTTPRequestHandler
    import os
    os.chdir(SITE_OUT)
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"\nServing site at http://localhost:{port}/")
        print("Ctrl-C to stop.")
        httpd.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--base-url", default="https://r-h-taylor.github.io",
                        help="Public base URL for sitemap.xml and robots.txt")
    args = parser.parse_args()

    print("Loading lectures...")
    lectures = load_all_lectures()
    print(f"  {len(lectures)} lectures loaded")

    print("Building inverted case index...")
    inverted = build_inverted_case_index(lectures)
    print(f"  {len(inverted)} unique cases referenced")

    print("Building search index...")
    search_docs = build_search_index(lectures, inverted)
    print(f"  {len(search_docs)} search documents")

    print("Setting up templates...")
    env = setup_jinja()

    print("Rendering site...")
    render_all(lectures, inverted, env, search_docs)
    print(f"  Site written to {SITE_OUT}")

    print("Building sitemap and robots.txt...")
    build_sitemap_and_robots(args.base_url)

    if args.serve:
        serve(args.port)


def _make_research_link(full_url):
    """Convert harvest's absolute research link to relative."""
    if "/lectures/" not in full_url:
        return full_url
    return "lectures/" + full_url.split("/lectures/", 1)[1]


def _build_quote_link(full_url, quote_text):
    """Convert harvest's absolute link to a relative one with ?q= prefix.

    Input:  https://r-h-taylor.github.io/lectures/VID.html#l3-s5-p3
    Output: lectures/VID.html?q=<first-60-urlencoded>#l3-s5-p3
    """
    import urllib.parse
    if "/lectures/" not in full_url:
        return full_url
    rel = full_url.split("/lectures/", 1)[1]
    rel = "lectures/" + rel
    if "#" not in rel:
        return rel
    base, frag = rel.split("#", 1)
    q = urllib.parse.quote(quote_text[:60], safe="")
    return f"{base}?q={q}#{frag}"


def build_sitemap_and_robots(base_url="https://r-h-taylor.github.io"):
    """Generate sitemap.xml and robots.txt by walking SITE_OUT."""
    import datetime
    today = datetime.date.today().isoformat()
    base_url = base_url.rstrip("/")
    urls = []
    for f in sorted(SITE_OUT.rglob("*.html")):
        rel = f.relative_to(SITE_OUT).as_posix()
        if rel == "index.html":
            url = f"{base_url}/"
        elif rel.endswith("/index.html"):
            url = f"{base_url}/{rel[:-10]}"
        else:
            url = f"{base_url}/{rel}"
        if rel == "index.html":
            prio = "1.0"
        elif rel in ("about.html", "cases/index.html", "lectures/index.html",
                     "casemap.html", "search.html"):
            prio = "0.9"
        elif rel.startswith("lectures/"):
            prio = "0.7"
        elif rel.startswith("cases/"):
            prio = "0.6"
        else:
            prio = "0.5"
        urls.append((url, prio))
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, prio in urls:
        sm.append("  <url>")
        sm.append(f"    <loc>{url}</loc>")
        sm.append(f"    <lastmod>{today}</lastmod>")
        sm.append(f"    <priority>{prio}</priority>")
        sm.append("  </url>")
    sm.append("</urlset>")
    (SITE_OUT / "sitemap.xml").write_text("\n".join(sm), encoding="utf-8")
    (SITE_OUT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {base_url}/sitemap.xml\n",
        encoding="utf-8",
    )
    print(f"  wrote sitemap.xml ({len(urls)} URLs) and robots.txt")


if __name__ == "__main__":
    main()
