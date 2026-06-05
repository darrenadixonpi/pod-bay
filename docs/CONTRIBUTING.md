# Contributing to Pod Bay

## Adding support for a new manufacturer

The highest-impact contribution is adding extraction support for a new OEM. Here's how:

### 1. Create the extractor directory

```
extractors/
└── <manufacturer>/
    ├── scripts/
    │   ├── extract_<format>.py    # Main extraction script
    │   └── ...
    └── README.md                  # Format documentation
```

### 2. Implement the extraction script

Your extractor should accept input files and produce the standard output schema:

**Required outputs:**
- `<vehicle>_manual.txt` — Plain text, one page per separator block; illustrations preserved inline as `[FIGURE: name.gif]` markers
- `<vehicle>_section_index.json` — Array of `{section, name, page_count, total_chars, first_page, last_page}`
- `<vehicle>_figures.json` — Array of `{page, section, figures:[...]}` (the manual→diagram linkage `get_diagram` resolves against)
- `images/` — Extracted diagrams, **named by their real filename** (e.g. `Y5111B.gif`) so `[FIGURE: ...]` markers resolve

**Optional outputs:**
- `*_COMP.csv`, `*_CONN.csv`, `*_CELLS.csv`, `*_COMPREF.csv`, etc. — Wiring/component tables (the EVTM schema `lookup_component` + `get_wiring_diagram` consume)
- Any format-specific metadata

See CLAUDE.md ("Architecture") for the exact filename contract the backend globs for.

### 3. Document the format

If you're reverse-engineering a proprietary format, document your findings in a `FORMAT_SPECIFICATION.md` file under `docs/`. Include:

- File header structure (magic bytes, offsets, field sizes)
- Record/block organization
- Compression algorithm (if applicable) with pseudocode
- How you identified the format (tools used, disassembly excerpts)

### 4. Add a vehicle data directory

```
vehicles/
└── <year>-<make>-<model>/
    ├── references/     # Extracted text, CSVs, index
    └── diagrams/       # Extracted illustrations
```

### 5. Test

Run your extractor against at least one complete archive/source and report:
- Total pages extracted
- Error rate (target: 0%)
- Output file sizes
- Sample content verification (spot-check 5–10 pages)

## Other contributions

**RAG backend** (`app/backend/`): hybrid keyword + local Chroma vector search is already implemented. Further work: retrieval-quality tuning, reranking, or alternative vector backends behind the same `retrieval.py` signatures.

**3D CAD viewer** (`app/frontend/`): Three.js + glTF 2.0 viewer that loads a CAD assembly (with its part hierarchy preserved) and accepts tool commands from the chat — `isolate`, `explode`, `set_camera`, `highlight` (`highlight_zone` is the reserved entry point). The model drives the viewer over the part tree; it does not touch raw geometry. See "3D / CAD layer" in `docs/ARCHITECTURE.md`. **Real CAD only — no AI-generated geometry.** Equally valuable: sourcing service-grade, assembly-structured CAD for individual systems of the built vehicles.

**Testing Ford extractor on other vehicle codes**: codes A, C, D, H, L, O are built and verified. Code **B** is untested but should work identically. If you have a Ford TSO disc for another vehicle or year, please test and report results.
