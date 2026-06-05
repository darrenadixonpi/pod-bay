"""EVTM wiring-schematic index and lookup.

Joins the EVTM tables to the wiring GIFs extracted from the E*.ARC into
vehicles/<id>/wiring_diagrams/. Each EVTM *cell* is one schematic page:

  - CELLS maps (CELL, PAGE) -> FILENAME (a `.TIF` whose extracted `.gif` twin is
    the image) plus a human TITLE/SUBTITLE and a CELLTYPE (SCH=schematic,
    CON=connector face, LOC=location view, TST=test, …).
  - The *REF cross-reference tables map a named thing to the cells it appears on,
    all sharing the schema EVTM,CELL,PAGE,NAME:
        COMPREF -> components, CONNREF -> connectors,
        GRNDREF -> grounds,    SPLCREF -> splices.

So "blower motor" -> its schematic cells -> servable GIF URLs. Validated 100%:
every CELLS `.TIF` filename and every COMPREF row resolves to an extracted GIF
(see the FORMAT_SPECIFICATION diagram-linkage work).

Like retrieval.py, every entry point takes a `vehicle_id` (None =
config.DEFAULT_VEHICLE_ID) and the per-vehicle indexes are lru_cached by id.
"""
import csv
from functools import lru_cache

import config

# Cross-reference tables, by suffix -> the kind of thing they name. All share
# EVTM,CELL,PAGE,NAME so one reader handles them; the label tags each match.
_REF_TABLES = {
    "COMPREF": "component",
    "CONNREF": "connector",
    "GRNDREF": "ground",
    "SPLCREF": "splice",
}

# Max images returned from one get_wiring_diagram call (keeps the tool result
# and the inline render bounded for components that span many schematic pages).
_MAX_DIAGRAMS = 8


def _glob_one_suffix(refs, suffix):
    """EVTM table paths for a suffix; the prefix (ETA_, EVC_, …) varies per vehicle."""
    return list(refs.glob(f"*_{suffix}.csv"))


@lru_cache(maxsize=None)
def _wiring_files(vehicle_id):
    """Map lowercased wiring GIF filename -> actual filename on disk."""
    wdir = config.get_vehicle(vehicle_id).wiring_dir
    if not wdir.exists():
        return {}
    return {p.name.lower(): p.name for p in wdir.glob("*.gif")}


@lru_cache(maxsize=None)
def _cells(vehicle_id):
    """Map (CELL, PAGE) -> cell dict, for cells whose image was extracted.

    Each value: {diagram_id, gif, title, subtitle, celltype}. Cells with no
    image twin (e.g. `.htm` text pages) or a missing GIF are skipped.
    """
    refs = config.get_vehicle(vehicle_id).references_dir
    files = _wiring_files(vehicle_id)
    cells = {}
    for path in _glob_one_suffix(refs, "CELLS"):
        with path.open(newline="", encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                fn = (r.get("FILENAME") or "").strip()
                if "." not in fn:
                    continue
                stem = fn.rsplit(".", 1)[0]
                gif = files.get(f"{stem.lower()}.gif")
                if not gif:
                    continue
                cells[(r["CELL"], r["PAGE"])] = {
                    "diagram_id": stem,
                    "gif": gif,
                    "title": (r.get("TITLE") or "").strip(),
                    "subtitle": (r.get("SUBTITLE") or "").strip(),
                    "celltype": (r.get("CELLTYPE") or "").strip(),
                }
    return cells


@lru_cache(maxsize=None)
def _name_to_cells(vehicle_id):
    """Map lowercased NAME -> [(kind, name, (CELL, PAGE))] from the *REF tables."""
    refs = config.get_vehicle(vehicle_id).references_dir
    out = {}
    for suffix, kind in _REF_TABLES.items():
        for path in _glob_one_suffix(refs, suffix):
            with path.open(newline="", encoding="utf-8", errors="replace") as f:
                for r in csv.DictReader(f):
                    name = (r.get("NAME") or "").strip()
                    if not name:
                        continue
                    out.setdefault(name.lower(), []).append(
                        (kind, name, (r["CELL"], r["PAGE"]))
                    )
    return out


@lru_cache(maxsize=None)
def _by_diagram_id(vehicle_id):
    """Map lowercased diagram_id (gif stem) -> (CELL, PAGE)."""
    return {c["diagram_id"].lower(): cp for cp, c in _cells(vehicle_id).items()}


@lru_cache(maxsize=None)
def _cell_to_names(vehicle_id):
    """Map (CELL, PAGE) -> [(kind, name)] of things shown on that schematic."""
    out = {}
    for entries in _name_to_cells(vehicle_id).values():
        for kind, name, cp in entries:
            out.setdefault(cp, []).append((kind, name))
    return out


def _diagram_record(vehicle_id, cp, cell, with_cross_refs=False):
    """Build a tool-facing diagram dict for cell (CELL, PAGE)."""
    vid = config.get_vehicle(vehicle_id).id
    rec = {
        "diagram_id": cell["diagram_id"],
        "title": cell["title"],
        "celltype": cell["celltype"],
        "url": f"/wiring/{vid}/{cell['gif']}",
    }
    if cell["subtitle"] and cell["subtitle"] != cell["title"]:
        rec["subtitle"] = cell["subtitle"]
    if with_cross_refs:
        names = _cell_to_names(vehicle_id).get(cp, [])
        # Distinct names, components first, capped — context for the schematic.
        seen, shows = set(), []
        for kind, name in sorted(names, key=lambda kn: kn[0] != "component"):
            if name not in seen:
                seen.add(name)
                shows.append(name)
            if len(shows) >= 20:
                break
        if shows:
            rec["also_shows"] = shows
    return rec


def schematic_pages_for_name(name, vehicle_id):
    """Lightweight [{diagram_id, title}] for an EXACT component name.

    Used to annotate lookup_component matches so the model knows wiring
    schematics exist for a found component (it then calls get_wiring_diagram).
    """
    cells = _cells(vehicle_id)
    out, seen = [], set()
    for _kind, _name, cp in _name_to_cells(vehicle_id).get(name.lower(), []):
        cell = cells.get(cp)
        if cell and cell["diagram_id"] not in seen:
            seen.add(cell["diagram_id"])
            out.append({"diagram_id": cell["diagram_id"], "title": cell["title"]})
    return out[:6]


def get_wiring_diagram(query, vehicle_id=None) -> dict:
    """Resolve a wiring query to servable schematic image(s).

    `query` is either a diagram id (a cell gif stem, e.g. 'EVC01001', as returned
    by lookup_component / a prior get_wiring_diagram), or the name of a component,
    connector, ground, or splice (substring match, e.g. 'blower motor', 'G101').
    """
    cells = _cells(vehicle_id)
    if not cells:
        return {"query": query, "resolved": False,
                "reason": "No wiring schematics are available for this vehicle."}

    q = query.strip()
    ql = q.lower().removesuffix(".gif")

    # 1) Direct diagram-id hit -> the single schematic, with its cross-references.
    cp = _by_diagram_id(vehicle_id).get(ql)
    if cp:
        return {
            "query": query, "resolved": True, "match_kind": "diagram_id",
            "count": 1,
            "diagrams": [_diagram_record(vehicle_id, cp, cells[cp], with_cross_refs=True)],
        }

    # 2) Named entity (component/connector/ground/splice), substring match.
    hits, seen_id = [], set()
    kinds = set()
    matched_names = []
    for name_l, entries in _name_to_cells(vehicle_id).items():
        if ql not in name_l:
            continue
        for kind, name, cp in entries:
            cell = cells.get(cp)
            if not cell or cell["diagram_id"] in seen_id:
                continue
            seen_id.add(cell["diagram_id"])
            kinds.add(kind)
            if name not in matched_names:
                matched_names.append(name)
            hits.append(_diagram_record(vehicle_id, cp, cell, with_cross_refs=True))

    if not hits:
        return {"query": query, "resolved": False,
                "reason": (f"No wiring schematic found for {query!r}. Try a component "
                           "name from lookup_component, or a connector/ground/splice id "
                           "(e.g. 'C176', 'G101', 'S100').")}

    out = {
        "query": query, "resolved": True,
        "match_kind": "/".join(sorted(kinds)) if kinds else "name",
        "matched_names": matched_names[:10],
        "count": len(hits),
        "diagrams": hits[:_MAX_DIAGRAMS],
    }
    if len(hits) > _MAX_DIAGRAMS:
        out["note"] = (f"{len(hits)} schematic pages match; showing the first "
                       f"{_MAX_DIAGRAMS}. Narrow the query or request a specific "
                       "diagram_id to see others.")
    return out
