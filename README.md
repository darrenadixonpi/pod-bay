# Pod Bay

*"Open the pod bay doors, HAL."*

**3D-guided automotive service application** — combining factory service manual data, interactive 3D vehicle models, and LLM-powered diagnostics.

> Extract OEM service manuals from proprietary formats. Search them with AI. Fix your car.

Named after the magic header bytes (`POD BAY`) found inside Ford's proprietary TSO archive format — the first format we cracked.

---

## What this is

Pod Bay is an open platform for extracting, indexing, and interacting with factory automotive service manuals. It started with reverse-engineering Ford's proprietary TSO (Technical Service Online) dealer disc format — cracking the IDICOMP compression algorithm by disassembling `tsobrowser.exe` — and extracting the complete 1996 Crown Victoria / Grand Marquis / Town Car workshop manual (2,146 pages, zero errors). It now serves **six Ford/Lincoln/Mercury vehicles** through a working chat assistant with hybrid (keyword + vector) search, factory service illustrations, and EVTM wiring schematics rendered inline.

The long-term vision: a mobile app where you describe what's wrong with your car (by voice, text, or photo), and an AI assistant walks you through the factory repair procedure step by step — with real **CAD models** (system-by-system, not AI-generated) it can isolate, explode, and rotate to show you exactly where to put your hands.

## Current status

| Component | Status |
|-----------|--------|
| Ford IDICOMP decompressor | ✅ Complete — 0% error rate across all tested archives |
| Ford ARC archive extractor | ✅ Complete — decodes record filenames, preserves inline `[FIGURE: …]` markers, emits a page→figures index |
| Ford MDB wiring DB exporter | ✅ Complete — exports all EVTM tables to CSV/JSON (native Windows via `access_parser`) |
| Vehicle skill builder | ✅ Complete — packages data for LLM consumption |
| Fleet (6 vehicles) | ✅ Grand Marquis, Mark VIII, Taurus/Sable, Ranger, Thunderbird/Cougar, F-250/350 Super Duty — built via `build_vehicle.py` |
| Retrieval backend + Claude tool-use | ✅ (`app/backend/`) — multi-vehicle; search_manual, get_section, lookup_component, get_diagram, get_wiring_diagram; FastAPI `/api/chat` |
| Web chat UI | ✅ (`app/frontend/`) — vehicle picker, chat + inline factory diagrams + wiring schematics + tool-call trace |
| Manual→diagram linkage | ✅ Complete — figures resolve to images and render inline |
| Vector/RAG search | ✅ Complete — hybrid keyword + local Chroma vector (RRF), behind `search_manual` |
| EVTM wiring-schematic linkage | ✅ Complete — `get_wiring_diagram` joins CELLS/COMPREF to the E*.ARC schematics |
| Multi-manufacturer extractors | 🔲 Planned — Toyota TIS, GM SI, BMW ISTA+, others |
| 3D CAD viewer | 🔲 Planned — real CAD (system-by-system); `highlight_zone` tool reserved |
| Mobile app | 🔲 Planned |

## Repository structure

```
pod-bay/
├── README.md                          # You are here
├── docs/
│   ├── FORMAT_SPECIFICATION.md    # Complete Ford IDICOMP format spec + RE process
│   ├── ARCHITECTURE.md            # App architecture and LLM integration design
│   └── CONTRIBUTING.md            # How to add support for a new manufacturer
├── extractors/
│   └── ford/
│       └── scripts/
│           ├── extract_ford_arc.py     # ARC archive → text + images + index
│           ├── extract_ford_mdb.py     # MDB wiring DBs → CSV/JSON
│           ├── build_vehicle.py        # Chain ARC+MDB → a vehicles/<id>/ dir
│           └── build_skill.py          # Package into LLM-ready skill
├── vehicles/                     # 6 built vehicles, each:
│   └── <id>/                     #   e.g. 1996-mercury-grand-marquis
│       ├── references/           #   manual text, section index, figures.json, wiring CSVs
│       ├── diagrams/             #   service illustration GIFs
│       ├── wiring_diagrams/      #   EVTM schematic GIFs (gitignored, regenerable)
│       └── vehicle.json          #   id, label, source provenance
└── app/
    ├── backend/                  # Hybrid RAG retrieval + Claude tool-calling server
    └── frontend/                 # Single-page chat UI (3D CAD viewer planned)
```

> Bulk diagram sets are gitignored and regenerable via `build_vehicle.py`; the two
> flagship vehicles (Grand Marquis, Mark VIII) keep their service diagrams committed
> as examples.

## Quick start

### Extract a Ford service manual

```bash
# Prerequisites
pip install capstone    # only needed if reverse-engineering new formats
apt install mdbtools    # for MDB wiring database export

# Extract workshop manual from a Ford TSO .ARC file
# (source archives live under "archive/.ARC files/" — quote the path)
python3 extractors/ford/scripts/extract_ford_arc.py "archive/.ARC files/STA.ARC" \
    -o ./output --format text --extract-images -v

# Extract wiring data from an MDB database (mdbtools, or pure-Python access_parser on Windows)
python3 extractors/ford/scripts/extract_ford_mdb.py "archive/.MDB files/ETA.MDB" \
    -o ./wiring -v

# Or do it all at once: chain ARC + MDB (+ wiring schematics) into a vehicles/<id>/ dir.
# id + label are derived from the manual's own title.
python3 extractors/ford/scripts/build_vehicle.py "archive/.ARC files/STA.ARC" \
    --mdb "archive/.MDB files/ETA.MDB" --evtm-arc "archive/.ARC files/ETA.ARC"
```

Then run the assistant over the built data — see [`app/backend/README.md`](app/backend/README.md).

### Ford vehicle codes

| Code | Vehicle | Built & verified |
|------|---------|------------------|
| A | Crown Victoria / Grand Marquis / Town Car | ✅ 1996 Grand Marquis |
| C | Lincoln Mark VIII | ✅ 1997 |
| D | Thunderbird / Cougar | ✅ 1997 |
| H | Taurus / Sable (incl. SHO) | ✅ 1998 |
| L | Explorer / Ranger | ✅ 1998 Ranger |
| O | F-250 Heavy Duty / F-350 / F-Super Duty | ✅ 1997 |

Filename convention: `STA.ARC` = **S**ervice manual, 199**6** (**T**), vehicle code **A**.
Year letters: S=1995, T=1996, V=1997, W=1998, X=1999.

> **Note:** code `O` is the F-Series Super Duty trucks, **not** Econoline — the
> earlier docs guessed wrong; `build_vehicle.py` derives identity from the manual's
> own title, which caught it. Six codes (A, C, D, H, L, O) are now built and verified.

## How the compression was cracked

The Ford TSO system stores service manual pages in `.ARC` archives using a proprietary format:

1. **POD BAY** file header with a record table (15 bytes per record)
2. **IDICOMP** block markers (`\x01IDICOMP\x01`) preceding each data chunk
3. **Hybrid RLE + LZ compression** with 16-bit flag words (MSB-first)

The decompressor was reverse-engineered by disassembling `tsobrowser.exe` using the Capstone x86 disassembler, tracing through three layers of function calls:

- `ArcDump::ExtractFile` (RVA 0x179D0) → orchestrator
- Block reader (0x18811) → reads signed int16 block sizes
- **The decompressor** (0x18579) → the actual RLE+LZ decode loop

Four token types, determined by the high nibble of the first token byte:

| Hi nibble | Type | Length range | Distance range |
|-----------|------|-------------|----------------|
| 0x0 | RLE short | 3–18 | N/A (repeat single byte) |
| 0x1 | RLE long | 19–4,114 | N/A |
| 0x2 | LZ long | 16–271 | 3–4,098 |
| 0x3–0xF | LZ short | 3–15 | 3–4,098 |

Full specification with pseudocode and annotated x86 disassembly: [`docs/FORMAT_SPECIFICATION.md`](docs/FORMAT_SPECIFICATION.md)

## Expansion targets

The platform is designed to support all manufacturers. The extraction challenge varies by era and OEM:

| Manufacturer | Era | Format | Difficulty |
|-------------|-----|--------|-----------|
| **Ford** | 1995–2003 disc | POD BAY / IDICOMP | ✅ Solved |
| **Toyota / Lexus** | 2000+ web | PDF per procedure via TIS portal | Low — batch PDF download |
| **Honda / Acura** | 2000+ web | Web-rendered + PDF via techinfo portal | Low–Medium |
| **Nissan / Infiniti** | 2000+ web | PDF via NissanTechInfo | Low |
| **GM** | 1996–2008 disc | InstallShield + HTML via TIS2000/SI | Medium |
| **GM** | 2008+ web | Techline Connect / Si (web-based) | Medium |
| **BMW** | 2006+ | ISTA+ SQLite databases | Medium |
| **Chrysler/Stellantis** | 1996–2005 disc | TechCONNECT CDs (proprietary) | Medium–High |
| **VW / Audi** | disc era | ELSA (encrypted) | High |
| **All modern** | 2015+ | Web portals (EPA mandated) | Low — authenticated scraping |

## Contributing

See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) for how to add support for a new manufacturer or vehicle.

The most impactful contributions right now:
- Extractors for non-Ford manufacturers (especially GM disc-era and Toyota TIS)
- A 3D CAD viewer (Three.js + glTF) and the part-hierarchy tooling that drives it (`highlight_zone` et al.) — see "3D / CAD layer" in `docs/ARCHITECTURE.md`
- Sourcing service-grade, assembly-structured CAD for individual systems (brakes, suspension, steering) of the built vehicles
- Testing the Ford extractor against the remaining vehicle code (B) and other model years

## License

MIT — see [LICENSE](LICENSE).

*Note: The extracted service manual content in `vehicles/` may be subject to the original manufacturer's copyright. This project provides tools for extracting data from media you legally own. Redistribution of extracted OEM content may not be permitted.*
