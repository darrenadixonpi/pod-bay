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
│  RAG RETRIEVAL      │    │  3D MODEL VIEWER                │
│  Vector embeddings  │    │  Three.js / WebGL               │
│  ChromaDB / SQLite  │    │  glTF models with named zones   │
│  Tool functions     │    │  Camera orbit + highlighting    │
└──────────┬──────────┘    └──────────────┬──────────────────┘
           │                              │
           ▼                              ▼
┌────────────────────────────────────────────────────────────┐
│              LLM LAYER (Claude API)                         │
│  Tool calling: search_manual, get_section, get_diagram,     │
│                lookup_component, highlight_zone,             │
│                identify_photo                                │
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
    {
        "name": "get_diagram",
        "description": "Get a technical diagram by figure number",
        "input_schema": {
            "type": "object",
            "properties": {
                "figure_id": {"type": "string", "description": "Figure number, e.g. 'A13648-C'"}
            },
            "required": ["figure_id"]
        }
    },
    {
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
    {
        "name": "highlight_zone",
        "description": "Highlight a zone on the 3D vehicle model",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone": {"type": "string", "description": "Zone name from the 3D model"}
            },
            "required": ["zone"]
        }
    }
]
```

## 3D visualization tiers

| Tier | Approach | Cost | Timeline | Quality |
|------|----------|------|----------|---------|
| 1 | Annotated hotspot models | $200–500 | 2–4 weeks | Spatial context, zone-based |
| 2 | Photogrammetry (phone camera) | ~$0 + time | 1–2 weeks capture | Accurate to specific car |
| 3 | Parametric CAD models | $5K–15K | Commissioned | Mechanically precise |
| 4 | AI-generated 3D | ~$0 | Future (2–3 years) | Placeholder quality today |

Tier 1 is the recommended starting point. See the concept PDF for details.
