"""Retrieval over the extracted vehicle data.

These are the functions Claude calls as tools. Deliberately dependency-free
(stdlib only) and keyword-based for the MVP — the data is small (~2,150 pages)
and already structured by section, so keyword + section lookup is enough to
prove the loop. Swap in vector search behind these same signatures later
without touching the tool layer or the server.
"""
import csv
import json
import re
from functools import lru_cache

import config

_PAGE_SEP = re.compile(r"^=+\nPAGE (\d+)\n=+\n", re.MULTILINE)
_SECTION_RE = re.compile(r"Section (\d+-\d+)")
_WORD_RE = re.compile(r"[a-z0-9]+")

# Wiring tables that lookup_component searches, with the columns worth showing.
_COMPONENT_TABLES = {
    "ETA_COMP.csv": ["NAME", "PARTNO", "LOCATION", "CONN_NAME", "ZONE"],
    "ETA_CONN.csv": ["NAME", "LOCATION", "COLOR", "TERMINAL", "ZONE"],
    "ETA_GRND.csv": ["NAME", "LOCATION"],
    "ETA_SPLICE.csv": ["NAME", "LOCATION"],
}


@lru_cache(maxsize=1)
def _pages():
    """Parse the workshop manual into [{page, section, text}], cached."""
    raw = config.WORKSHOP_MANUAL.read_text(encoding="utf-8", errors="replace")
    matches = list(_PAGE_SEP.finditer(raw))
    pages = []
    for i, m in enumerate(matches):
        page_no = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        text = raw[start:end].strip()
        sec = _SECTION_RE.search(text)
        pages.append({
            "page": page_no,
            "section": sec.group(1) if sec else None,
            "text": text,
        })
    return pages


@lru_cache(maxsize=1)
def _section_index():
    return json.loads(config.SECTION_INDEX.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _diagram_files():
    """Map lowercased diagram filename -> actual filename on disk."""
    return {p.name.lower(): p.name for p in config.DIAGRAMS_DIR.glob("*.gif")}


@lru_cache(maxsize=1)
def _figure_locations():
    """Map lowercased figure filename -> list of {page, section} that show it."""
    locs = {}
    if not config.FIGURES_INDEX.exists():
        return locs
    for entry in json.loads(config.FIGURES_INDEX.read_text(encoding="utf-8")):
        for fig in entry.get("figures", []):
            locs.setdefault(fig.lower(), []).append(
                {"page": entry.get("page"), "section": entry.get("section")}
            )
    return locs


def _tokenize(s: str):
    return _WORD_RE.findall(s.lower())


def search_manual(query: str, max_results: int = 5) -> dict:
    """Keyword search across workshop manual pages.

    Scores each page by how many distinct query terms it contains, weighted by
    term frequency. Returns ranked snippets with section + page so the model
    can follow up with get_section.
    """
    terms = set(_tokenize(query))
    if not terms:
        return {"query": query, "results": []}

    scored = []
    for pg in _pages():
        toks = _tokenize(pg["text"])
        if not toks:
            continue
        counts = {t: 0 for t in terms}
        for tok in toks:
            if tok in counts:
                counts[tok] += 1
        hit_terms = sum(1 for c in counts.values() if c)
        if not hit_terms:
            continue
        # distinct-term coverage dominates; raw frequency breaks ties
        score = hit_terms * 1000 + sum(counts.values())
        scored.append((score, pg))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, pg in scored[:max_results]:
        results.append({
            "page": pg["page"],
            "section": pg["section"],
            "snippet": _snippet(pg["text"], terms),
        })
    return {"query": query, "result_count": len(results), "results": results}


def _snippet(text: str, terms: set, width: int = 320) -> str:
    """A window of text centered on the first query-term hit."""
    low = text.lower()
    pos = min((low.find(t) for t in terms if low.find(t) >= 0), default=-1)
    if pos < 0:
        return text[:width]
    start = max(0, pos - width // 3)
    return ("…" if start else "") + text[start:start + width] + "…"


def get_section(section_id: str) -> dict:
    """Full text of a workshop manual section, e.g. '06-03'.

    Concatenates every page whose header names that section.
    """
    section_id = section_id.strip()
    pages = [p for p in _pages() if p["section"] == section_id]
    meta = next((s for s in _section_index() if s["section"] == section_id), None)
    if not pages:
        avail = sorted({p["section"] for p in _pages() if p["section"]})
        return {
            "section_id": section_id,
            "found": False,
            "message": f"No pages for section {section_id}.",
            "available_sections": avail,
        }
    body = "\n\n".join(p["text"] for p in pages)
    return {
        "section_id": section_id,
        "found": True,
        "name": (meta or {}).get("name", "").strip(),
        "page_count": len(pages),
        "text": body,
    }


def lookup_component(query: str) -> dict:
    """Search the EVTM wiring tables for a component, connector, ground, or splice."""
    q = query.lower().strip()
    matches = []
    for fname, cols in _COMPONENT_TABLES.items():
        path = config.REFERENCES_DIR / fname
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                name = (row.get("NAME") or "")
                if q in name.lower():
                    rec = {"table": fname.replace("ETA_", "").replace(".csv", "")}
                    for c in cols:
                        val = (row.get(c) or "").strip()
                        if val:
                            rec[c] = val
                    matches.append(rec)
    return {"query": query, "match_count": len(matches), "matches": matches[:25]}


def get_diagram(figure_id: str) -> dict:
    """Resolve a figure filename (e.g. 'Y5111B.gif') to a servable image.

    Figure references appear inline in the manual text as [FIGURE: name.gif].
    Resolution is case-insensitive (manual src casing is inconsistent). Returns
    a URL the UI can load plus the page(s)/section(s) where the figure appears.
    """
    fid = figure_id.strip()
    if not fid.lower().endswith(".gif"):
        fid += ".gif"
    key = fid.lower()

    actual = _diagram_files().get(key)
    if not actual:
        return {
            "figure_id": figure_id,
            "resolved": False,
            "reason": f"No diagram file named {fid}.",
        }
    return {
        "figure_id": actual,
        "resolved": True,
        "url": f"/diagrams/{actual}",
        "appears_in": _figure_locations().get(key, []),
    }
