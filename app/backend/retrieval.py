"""Retrieval over the extracted vehicle data.

These are the functions Claude calls as tools. `search_manual` is hybrid:
a stdlib keyword scorer fused with a local semantic index (vectorstore.py)
via reciprocal rank fusion. Keyword matching nails the exact tokens this
domain is full of — part numbers, torque values, connector ids, section
codes — while the vector side adds paraphrase/synonym recall. The fusion and
the vector index degrade gracefully to keyword-only.

Search spans two documents, each result tagged with a `source`:
  - "workshop" — the factory Workshop Manual, located by Section number + page.
  - "owners"   — the Owner's Manual, located by named chapter.
Both share one corpus (`_corpus()`), one search tool, and one read tool
(`get_section`, which accepts a workshop Section number or an owner's chapter).

Every entry point takes a `vehicle_id` (None = config.DEFAULT_VEHICLE_ID), so a
single process serves any extracted vehicle. Per-vehicle data is loaded once and
cached (the lru_caches below are keyed by vehicle_id).
"""
import csv
import json
import re
from functools import lru_cache

import config
import vectorstore
import wiring

_PAGE_SEP = re.compile(r"^=+\nPAGE (\d+)\n=+\n", re.MULTILINE)
_SECTION_RE = re.compile(r"Section (\d+-\d+)")
_SECTION_ID_RE = re.compile(r"^\d+-\d+$")  # workshop section ids look like 06-03
_WORD_RE = re.compile(r"[a-z0-9]+")

# Owner's manual chapter titles come from each vehicle's vehicle.json
# (Vehicle.owners_chapters) — in document order, matching its table of contents.
# Headings appear verbatim as standalone lines in the body (with irregular
# internal whitespace), so segmentation matches them with flexible spacing.
# Publishing control lines in the owner's manual source — noise, not content:
# typesetting markers ("File:rcpig.ex", "Update:...", "*[PI00400( ALL)05/95]",
# "thirty-six pica chart:...").
_OWNERS_NOISE = re.compile(
    r"(?m)^(?:File:.*|Update:.*|\*?\[[A-Z]{2}\d+\(.*?\).*?\]|thirty-six pica chart:.*)$"
)

# Wiring table types lookup_component searches, with the columns worth showing.
# Keyed by table suffix (the EVTM/MDB prefix varies per vehicle — ETA_, EVC_,
# … — so files are resolved by glob, not a hardcoded name).
_COMPONENT_TABLE_COLS = {
    "COMP": ["NAME", "PARTNO", "LOCATION", "CONN_NAME", "ZONE"],
    "CONN": ["NAME", "LOCATION", "COLOR", "TERMINAL", "ZONE"],
    "GRND": ["NAME", "LOCATION"],
    "SPLICE": ["NAME", "LOCATION"],
}


@lru_cache(maxsize=None)
def _pages(vehicle_id):
    """Parse the workshop manual into [{page, section, text}], cached per vehicle."""
    raw = config.get_vehicle(vehicle_id).workshop_manual.read_text(
        encoding="utf-8", errors="replace")
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


@lru_cache(maxsize=None)
def _section_index(vehicle_id):
    return json.loads(config.get_vehicle(vehicle_id).section_index.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _diagram_files(vehicle_id):
    """Map lowercased diagram filename -> actual filename on disk."""
    return {p.name.lower(): p.name
            for p in config.get_vehicle(vehicle_id).diagrams_dir.glob("*.gif")}


@lru_cache(maxsize=None)
def _figure_locations(vehicle_id):
    """Map lowercased figure filename -> list of {page, section} that show it."""
    locs = {}
    figures_index = config.get_vehicle(vehicle_id).figures_index
    if not figures_index.exists():
        return locs
    for entry in json.loads(figures_index.read_text(encoding="utf-8")):
        for fig in entry.get("figures", []):
            locs.setdefault(fig.lower(), []).append(
                {"page": entry.get("page"), "section": entry.get("section")}
            )
    return locs


def _tokenize(s: str):
    return _WORD_RE.findall(s.lower())


@lru_cache(maxsize=None)
def _owners_chapters(vehicle_id):
    """Parse the owner's manual into [{chapter, text}], cached per vehicle.

    Segments the flowing text on its chapter headings (first body occurrence of
    each title, in TOC order) and strips publishing control lines. Returns [] if
    the owner's manual isn't present for this vehicle.
    """
    v = config.get_vehicle(vehicle_id)
    if not v.owners_manual.exists() or not v.owners_chapters:
        return []
    raw = v.owners_manual.read_text(encoding="utf-8", errors="replace")

    # Locate each chapter heading's first standalone occurrence in the body.
    bounds = []
    for title in v.owners_chapters:
        pat = re.compile(r"(?mi)^\s*" + r"\s+".join(map(re.escape, title.split())) + r"\s*$")
        m = pat.search(raw)
        if m:
            bounds.append((m.start(), title))
    bounds.sort()

    chapters = []
    for i, (start, title) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(raw)
        body = _OWNERS_NOISE.sub("", raw[start:end])
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        if body:
            chapters.append({"chapter": title, "text": body})
    return chapters


@lru_cache(maxsize=None)
def _corpus(vehicle_id):
    """Unified searchable corpus across both manuals, cached per vehicle.

    Each record: {id, source, section, chapter, page, text}. Workshop pages
    keep their section/page; owner's chapters carry a chapter name. `id` is the
    fusion key (W<page> / O<index>) shared by the keyword and vector rankers.
    """
    docs = []
    for pg in _pages(vehicle_id):
        docs.append({
            "id": f"W{pg['page']}", "source": "workshop",
            "section": pg["section"], "chapter": None,
            "page": pg["page"], "text": pg["text"],
        })
    for i, ch in enumerate(_owners_chapters(vehicle_id)):
        docs.append({
            "id": f"O{i}", "source": "owners",
            "section": None, "chapter": ch["chapter"],
            "page": None, "text": ch["text"],
        })
    return docs


@lru_cache(maxsize=None)
def _corpus_by_id(vehicle_id):
    return {d["id"]: d for d in _corpus(vehicle_id)}


def _locator(rec: dict) -> dict:
    """Source-appropriate locator fields for a result/section record."""
    if rec["source"] == "workshop":
        return {"source": "workshop", "section": rec["section"], "page": rec["page"]}
    return {"source": "owners", "chapter": rec["chapter"]}


# Reciprocal rank fusion constant. 60 is the value from the original RRF paper
# (Cormack et al.); it damps the influence of any single ranker's top hit so
# keyword and vector contribute comparably.
_RRF_K = 60


def _keyword_rank(query: str, limit: int, vehicle_id) -> list:
    """Rank corpus documents by keyword score; returns records best→worst."""
    terms = set(_tokenize(query))
    if not terms:
        return []
    scored = []
    for doc in _corpus(vehicle_id):
        toks = _tokenize(doc["text"])
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
        scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [doc for _, doc in scored[:limit]]


def search_manual(query: str, max_results: int = 5, vehicle_id=None) -> dict:
    """Hybrid search across the workshop manual and owner's manual.

    Fuses keyword ranking with semantic (vector) ranking by reciprocal rank
    fusion, then returns ranked snippets. Each result carries a `source`
    ("workshop"/"owners") and a source-appropriate locator (section + page, or
    chapter) so the model can follow up with get_section. Falls back to
    keyword-only when the vector index is unavailable (mode is config.SEARCH_MODE).
    """
    terms = set(_tokenize(query))
    mode = config.SEARCH_MODE
    use_vector = mode in ("hybrid", "vector") and vectorstore.available()
    use_keyword = mode in ("hybrid", "keyword") or not use_vector

    # Over-fetch each ranker so fusion has depth to reorder over.
    depth = max(max_results * 3, 10)
    kw_docs = _keyword_rank(query, depth, vehicle_id) if use_keyword else []
    vec_hits = vectorstore.vector_rank(query, depth, vehicle_id) if use_vector else []

    # Reciprocal rank fusion (keyed by corpus id): score = Σ 1/(k + rank).
    fused: dict[str, float] = {}
    passages: dict[str, str] = {}  # best vector passage per doc, for snippets
    for rank, doc in enumerate(kw_docs):
        fused[doc["id"]] = fused.get(doc["id"], 0.0) + 1.0 / (_RRF_K + rank)
    for rank, hit in enumerate(vec_hits):
        did = hit["id"]
        fused[did] = fused.get(did, 0.0) + 1.0 / (_RRF_K + rank)
        passages.setdefault(did, hit["passage"])

    ordered = sorted(fused, key=lambda d: fused[d], reverse=True)[:max_results]
    by_id = _corpus_by_id(vehicle_id)
    results = []
    for did in ordered:
        doc = by_id.get(did)
        if not doc:
            continue
        results.append({
            **_locator(doc),
            "snippet": _snippet(doc["text"], terms, passage=passages.get(did)),
        })
    return {"query": query, "result_count": len(results), "results": results}


def _snippet(text: str, terms: set, width: int = 320, passage: str = None) -> str:
    """A window of text centered on the first query-term hit.

    For a purely semantic match (no literal query term on the page) there is no
    hit to center on, so fall back to the vector passage that matched, then to
    the page head.
    """
    low = text.lower()
    pos = min((low.find(t) for t in terms if low.find(t) >= 0), default=-1)
    if pos < 0:
        if passage:
            return passage[:width] + ("…" if len(passage) > width else "")
        return text[:width]
    start = max(0, pos - width // 3)
    return ("…" if start else "") + text[start:start + width] + "…"


# A whole workshop section can be 100+ pages (~40k+ tokens) — far more than a
# single procedure needs, and enough to blow API rate limits. get_section
# therefore returns a bounded window of pages (centered on `around_page` when
# search gave one) and caps the text, telling the model how to read adjacent
# pages if it needs them.
_SECTION_CHAR_CAP = 20000      # ~5k tokens
_PAGE_WINDOW_BEFORE = 2
_PAGE_WINDOW_AFTER = 3


def _cap(text: str, max_chars: int) -> tuple:
    """(text, truncated?) — trim to max_chars on a paragraph/whitespace boundary."""
    if len(text) <= max_chars:
        return text, False
    cut = text.rfind("\n", 0, max_chars)
    if cut < max_chars // 2:
        cut = max_chars
    return text[:cut].rstrip(), True


def get_section(section_id: str, vehicle_id=None, around_page: int = None) -> dict:
    """Read a workshop manual section ('06-03') or owner's chapter.

    Workshop sections can be very long, so this returns a bounded window of
    pages. Pass `around_page` (the page number from a search_manual result) to
    center the window on the relevant procedure; omit it to read from the
    section's start. The response reports the section's full page range and
    which pages were returned, so the model can re-call with a different
    `around_page` to read more. Owner's-manual chapters are returned whole
    (capped). Use after search_manual with the locator it returned.
    """
    section_id = section_id.strip()

    # Owner's-manual chapter (anything that isn't a workshop section number).
    if not _SECTION_ID_RE.match(section_id):
        ch = next((c for c in _owners_chapters(vehicle_id)
                   if c["chapter"].lower() == section_id.lower()), None)
        if ch:
            text, truncated = _cap(ch["text"], _SECTION_CHAR_CAP)
            out = {
                "section_id": ch["chapter"],
                "source": "owners",
                "found": True,
                "name": ch["chapter"],
                "text": text,
            }
            if truncated:
                out["note"] = "Chapter truncated; this is the opening portion."
            return out
        return {
            "section_id": section_id,
            "found": False,
            "message": f"No section or chapter named {section_id!r}.",
            "available_chapters": [c["chapter"] for c in _owners_chapters(vehicle_id)],
        }

    pages = [p for p in _pages(vehicle_id) if p["section"] == section_id]  # doc order
    meta = next((s for s in _section_index(vehicle_id) if s["section"] == section_id), None)
    if not pages:
        avail = sorted({p["section"] for p in _pages(vehicle_id) if p["section"]})
        return {
            "section_id": section_id,
            "found": False,
            "message": f"No pages for section {section_id}.",
            "available_sections": avail,
        }

    # Pick the window of pages to return.
    if around_page is not None:
        idx = next((i for i, p in enumerate(pages) if p["page"] == around_page), None)
    else:
        idx = None
    if idx is None:
        window = pages  # from the start; the char cap bounds it
    else:
        lo = max(0, idx - _PAGE_WINDOW_BEFORE)
        window = pages[lo:idx + _PAGE_WINDOW_AFTER + 1]

    body = "\n\n".join(p["text"] for p in window)
    body, truncated = _cap(body, _SECTION_CHAR_CAP)
    returned = [p["page"] for p in window]
    full_range = [pages[0]["page"], pages[-1]["page"]]

    out = {
        "section_id": section_id,
        "source": "workshop",
        "found": True,
        "name": (meta or {}).get("name", "").strip(),
        "page_count": len(pages),
        "section_page_range": full_range,
        "returned_pages": [returned[0], returned[-1]] if returned else [],
        "text": body,
    }
    # Tell the model when there's more, and how to get it.
    if truncated or len(window) < len(pages):
        out["note"] = (
            f"Section spans pages {full_range[0]}–{full_range[1]} ({len(pages)} pages); "
            f"showing pages {out['returned_pages'][0]}–{out['returned_pages'][1]}"
            f"{' (truncated)' if truncated else ''}. "
            "To read adjacent material, call get_section again with around_page "
            "set to a page just outside this window."
        )
    return out


@lru_cache(maxsize=None)
def _component_tables(vehicle_id):
    """Resolve wiring CSVs for a vehicle: [(path, table_type, cols)].

    The EVTM prefix varies per vehicle (ETA_, EVC_, …), so match by suffix.
    """
    refs = config.get_vehicle(vehicle_id).references_dir
    found = []
    for ttype, cols in _COMPONENT_TABLE_COLS.items():
        for path in refs.glob(f"*_{ttype}.csv"):
            found.append((path, ttype, cols))
    return found


def lookup_component(query: str, vehicle_id=None) -> dict:
    """Search the EVTM wiring tables for a component, connector, ground, or splice."""
    q = query.lower().strip()
    matches = []
    for path, ttype, cols in _component_tables(vehicle_id):
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                name = (row.get("NAME") or "")
                if q in name.lower():
                    rec = {"table": ttype}
                    for c in cols:
                        val = (row.get(c) or "").strip()
                        if val:
                            rec[c] = val
                    # Note which wiring schematics show this exact entity, so the
                    # model can pull the actual diagram via get_wiring_diagram.
                    pages = wiring.schematic_pages_for_name(name, vehicle_id)
                    if pages:
                        rec["schematic_pages"] = pages
                    matches.append(rec)
    return {"query": query, "match_count": len(matches), "matches": matches[:25]}


def get_diagram(figure_id: str, vehicle_id=None) -> dict:
    """Resolve a figure filename (e.g. 'Y5111B.gif') to a servable image.

    Figure references appear inline in the manual text as [FIGURE: name.gif].
    Resolution is case-insensitive (manual src casing is inconsistent). Returns
    a per-vehicle URL the UI can load plus the page(s)/section(s) where the
    figure appears.
    """
    vid = config.get_vehicle(vehicle_id).id
    fid = figure_id.strip()
    if not fid.lower().endswith(".gif"):
        fid += ".gif"
    key = fid.lower()

    actual = _diagram_files(vehicle_id).get(key)
    if not actual:
        return {
            "figure_id": figure_id,
            "resolved": False,
            "reason": f"No diagram file named {fid}.",
        }
    return {
        "figure_id": actual,
        "resolved": True,
        "url": f"/diagrams/{vid}/{actual}",
        "appears_in": _figure_locations(vehicle_id).get(key, []),
    }
