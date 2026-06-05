# Architecture

## System overview

```
┌────────────────────────────────────────────────────────────┐
│                     INPUT SOURCES                          │
│  OVA/VMDK/ISO  │  PDF collections  │  Web portal scrapes  │
│  .ARC archives  │  MDB databases   │  SQLite databases    │
└────────┬───────────────┬───────────────────┬───────────────┘
         │               │                   │
         ▼               ▼                   ▼
┌────────────────────────────────────────────────────────────┐
│              FORMAT DETECTION & ROUTING                     │
│  Magic bytes → manufacturer ID → era classification        │
│  Routes to appropriate extraction handler                   │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│              EXTRACTION HANDLERS                            │
│  ford_arc   │ pdf    │ html    │ sqlite  │ web_scraper     │
│  mdb        │ cab    │ image   │ (new handlers added here) │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│              UNIFIED KNOWLEDGE BASE                         │
│  Structured text (procedures, specs, diagnostics)           │
│  Indexed diagrams (linked to procedures by figure number)   │
│  Component databases (parts, connectors, locations)         │
│  Cross-reference tables                                     │
└──────────┬─────────────────────────────┬───────────────────┘
           │                             │
           ▼                             ▼
┌─────────────────────┐    ┌─────────────────────────────────┐
│  RAG RETRIEVAL ✅   │    │  3D / CAD VIEWER (planned)      │
│  Hybrid kw+vector   │    │  Three.js / WebGL               │
│  ChromaDB (local)   │    │  glTF from CAD (assembly tree)  │
│  Tool functions     │    │  isolate · explode · highlight  │
└──────────┬──────────┘    └──────────────┬──────────────────┘
           │                              │
           ▼                              ▼
┌────────────────────────────────────────────────────────────┐
│              LLM LAYER (Claude API)                         │
│  Tool calling: search_manual, get_section, get_diagram,     │
│                lookup_component, get_wiring_diagram,         │
│                highlight_zone (planned), identify_photo (pl.)│
│  Adaptive tone: mechanic ↔ novice                           │
│  Input: text, voice (STT), photo (vision)                   │
└────────────────────────┬───────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│              MOBILE APP                                     │
│  React Native / Flutter                                     │
│  Screens: 3D viewer │ Chat │ Manual browser                 │
│  Offline data bundle + Claude API for reasoning             │
└────────────────────────────────────────────────────────────┘
```

## Extraction handlers

Each handler normalizes a specific input format into the unified schema.

| Handler | Input | Key logic | Output |
|---------|-------|-----------|--------|
| `ford_arc` | .ARC (POD BAY) | IDICOMP decompression (16-bit flags, RLE+LZ) | Text + images + index |
| `mdb` | .MDB (Access) | mdbtools export | CSV/JSON tables |
| `pdf` | PDF collections | pdfplumber text extraction, OCR for scans | Text + extracted images |
| `html` | HTML archives | Tag stripping, structure preservation | Text + section hierarchy |
| `sqlite` | SQLite DBs (ISTA+) | Schema analysis, table export | Structured data tables |
| `cab` | InstallShield CAB | Cabinet extraction, unpacking | Raw files for further processing |
| `image` | GIF/SVG/SVGZ/TIFF | Format conversion, label OCR | Indexed image library |
| `web_scraper` | Live portal URL | Playwright/Selenium, authenticated session | PDF/HTML archive |

## LLM tool interface

Claude accesses vehicle data through tool use (function calling). The tool interface is manufacturer-agnostic — the same tools work whether the source was a 1996 Ford IDICOMP archive or a 2024 Toyota PDF.

The **implemented** tools (✅) live in `app/backend/tools.py` with their retrieval logic in `app/backend/retrieval.py` / `app/backend/wiring.py`; the snippets below are the design reference, not the source of truth (the real schemas are richer — e.g. `get_section` takes an `around_page` window, `get_diagram`/`get_wiring_diagram` resolve to per-vehicle URLs). Tools marked *(reserved)* are part of the contract but await the 3D/CAD layer.

```python
# Tool definitions for Claude API
tools = [
    {
        "name": "search_manual",
        "description": "Search the workshop manual for relevant procedures",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "max_results": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_section",
        "description": "Get the full text of a specific manual section",
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {"type": "string", "description": "Section number, e.g. '03-00'"}
            },
            "required": ["section_id"]
        }
    },
    {   # ✅ implemented
        "name": "get_diagram",
        "description": "Resolve a service illustration to a viewable image",
        "input_schema": {
            "type": "object",
            "properties": {
                "figure_id": {"type": "string", "description": "Figure filename from an inline [FIGURE: …] marker, e.g. 'Y5111B.gif'"}
            },
            "required": ["figure_id"]
        }
    },
    {   # ✅ implemented
        "name": "lookup_component",
        "description": "Look up an electrical component in the EVTM database",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Component name, part number, or description"}
            },
            "required": ["query"]
        }
    },
    {   # ✅ implemented — see app/backend/wiring.py
        "name": "get_wiring_diagram",
        "description": "Show the EVTM wiring schematic(s) for a component, connector, ground, or splice",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Component/connector/ground/splice name, or a wiring diagram_id (cell id, e.g. 'EVC01001')"}
            },
            "required": ["query"]
        }
    },
    {   # (reserved) — awaits the 3D/CAD layer; see "3D / CAD layer" below
        "name": "highlight_zone",
        "description": "Isolate/highlight a part or assembly in the 3D CAD viewer and frame the camera on it",
        "input_schema": {
            "type": "object",
            "properties": {
                "part_id": {"type": "string", "description": "Part or assembly node id from the model's hierarchy (or a named zone)"}
            },
            "required": ["part_id"]
        }
    }
]
```

## 3D / CAD layer

The 3D layer uses **real CAD models, not AI-generated geometry.** For a *service*
tool the geometry must be mechanically truthful — the actual bracket with the
actual bolt pattern — or it is worse than nothing (confidently wrong). Generative
3D is fine for concept art, never for load-bearing reference, so it is explicitly
out of scope.

### How the LLM works with a CAD model

The model **never touches raw geometry** (B-rep NURBS surfaces, or millions of
triangles) — that would be hopeless and inefficient. Instead it works exactly the
way the wiring feature works (`get_wiring_diagram` over the `CELLS`/`COMPREF`
tables): over **structured metadata**, with a viewer doing the rendering.

- A CAD asset carries an **assembly hierarchy** — a named tree of parts with
  parent/child structure, transforms, and bounding boxes
  ("Front Suspension → Lower Control Arm → Ball Joint", each with a position).
- We index *that tree* into per-vehicle reference data, the same way `CELLS` and
  `COMPREF` index the wiring.
- A browser **3D viewer** (Three.js / WebGL, glTF 2.0) does all rendering and
  manipulation.
- The LLM is the **director**, driving the viewer through tools — the same pattern
  as `get_diagram`/`get_wiring_diagram`:
  `list_parts(assembly)`, `isolate(part_id)`, `explode(assembly_id)`,
  `hide/show`, `set_camera(view)`, `highlight(part_ids)`, `section_cut(plane)`,
  `measure(a, b)`. `highlight_zone` (reserved above) is the first of these.

So "teach a model to break it apart and navigate around" = the LLM reasons over a
labeled tree and issues camera/visibility/explode commands against **named
handles**. That is a structured-reasoning task LLMs are good at, and it slots into
the existing tool architecture rather than being a new paradigm.

### Asset pipeline (when models exist)

Native CAD (**STEP / JT** — both preserve the assembly tree + part names; JT is the
automotive-PLM standard) → tessellate to **glTF/GLB** preserving the hierarchy and
metadata (OpenCASCADE, Assimp, or CAD Exchanger) → index the part tree into
`vehicles/<id>/` → web glTF viewer + the LLM tool layer. Mechanical precision is
preserved; the LLM only steers.

### Strategy: system-by-system, opportunistically

The hard problem is **not** the software — it is **sourcing the CAD.** Unlike the
2D service illustrations and wiring (which we legally extract from TSO media you
own), factory 3D CAD for these vehicles is OEM-proprietary and effectively
unavailable. A survey of community sources (GrabCAD, Sketchfab, TurboSquid,
Cults/STL sites) found only **exterior body models for rendering and single-mesh
prints, plus generic V8 engines** — none with the assembly structure or part
fidelity a service tool needs.

Therefore 3D is a **per-system, opportunistic layer**, not a "model the whole car"
milestone: light up an individual assembly (front brakes, steering linkage,
suspension) when a good model of *that system* becomes available, and let the 2D
illustrations + wiring remain the backbone. Realistic asset paths, all
constrained: aftermarket/community models (sparse, licensing landmines),
photogrammetry/3D-scanning of real parts (accurate but per-part manual labor),
or commissioned CAD (expensive).
