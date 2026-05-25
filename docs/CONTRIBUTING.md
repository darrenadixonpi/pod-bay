# Contributing to Mechanical

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
- `<vehicle>_manual.txt` — Plain text, one page per separator block
- `<vehicle>_section_index.json` — Array of `{section, name, page_count, total_chars}`

**Optional outputs:**
- `images/` — Extracted diagrams (GIF, PNG, SVG)
- `*_COMP.csv`, `*_CONN.csv`, etc. — Wiring/component data tables
- Any format-specific metadata

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

**RAG backend** (`app/backend/`): Vector search over extracted manuals. ChromaDB or SQLite-vss. Should expose the tool functions documented in `docs/ARCHITECTURE.md`.

**3D viewer** (`app/frontend/`): Three.js viewer loading glTF models with named mesh zones. Tap/click interaction, camera orbit animation, zone highlighting. Should accept `highlight_zone` commands from the chat interface.

**Testing Ford extractor on other vehicle codes**: We've validated code A (Crown Vic/Grand Marquis/Town Car). Codes B, C, D, H, L, O are untested but should work identically. If you have a Ford TSO disc for another vehicle, please test and report results.
