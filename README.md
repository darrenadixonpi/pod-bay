# Pod Bay

*"Open the pod bay doors, HAL."*

**3D-guided automotive service application** — combining factory service manual data, interactive 3D vehicle models, and LLM-powered diagnostics.

> Extract OEM service manuals from proprietary formats. Search them with AI. Fix your car.

Named after the magic header bytes (`POD BAY`) found inside Ford's proprietary TSO archive format — the first format we cracked.

---

## What this is

Mechanical is an open platform for extracting, indexing, and interacting with factory automotive service manuals. It started with reverse-engineering Ford's proprietary TSO (Technical Service Online) dealer disc format — cracking the IDICOMP compression algorithm by disassembling `tsobrowser.exe` — and extracting the complete 1996 Crown Victoria / Grand Marquis / Town Car workshop manual (2,146 pages, zero errors).

The long-term vision: a mobile app where you describe what's wrong with your car (by voice, text, or photo), and an AI assistant walks you through the factory repair procedure step by step, with 3D models showing you exactly where to put your hands.

## Current status

| Component | Status |
|-----------|--------|
| Ford IDICOMP decompressor | ✅ Complete — 0% error rate across all tested archives |
| Ford ARC archive extractor | ✅ Complete — handles STA, ETA, and other .ARC files |
| Ford MDB wiring DB exporter | ✅ Complete — exports all EVTM tables to CSV/JSON |
| Vehicle skill builder | ✅ Complete — packages data for LLM consumption |
| 1996 Grand Marquis data | ✅ Complete — 2,146 pages + 286 components + 50 diagrams |
| Multi-manufacturer extractors | 🔲 Planned — Toyota TIS, GM SI, BMW ISTA+, others |
| RAG retrieval backend | 🔲 Planned |
| 3D model viewer | 🔲 Planned |
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
│           └── build_skill.py          # Package into LLM-ready skill
├── vehicles/
│   └── 1996-mercury-grand-marquis/
│       ├── references/            # Extracted manual text, wiring CSVs, section index
│       └── diagrams/              # Extracted GIF technical illustrations
└── app/
    ├── backend/                   # RAG retrieval + Claude tool-calling server
    └── frontend/                  # Three.js 3D viewer + mobile chat interface
```

## Quick start

### Extract a Ford service manual

```bash
# Prerequisites
pip install capstone    # only needed if reverse-engineering new formats
apt install mdbtools    # for MDB wiring database export

# Extract workshop manual from a Ford TSO .ARC file
python3 extractors/ford/scripts/extract_ford_arc.py STA.ARC \
    --output-dir ./output --format text --extract-images -v

# Extract wiring data from MDB databases
python3 extractors/ford/scripts/extract_ford_mdb.py ./EN_databases/ \
    --output-dir ./wiring -v

# Package into an LLM-ready skill
python3 extractors/ford/scripts/build_skill.py \
    --vehicle "1996 Mercury Grand Marquis" \
    --engine "4.6L SOHC V8" \
    --platform "Panther" \
    --manual-dir ./output \
    --wiring-dir ./wiring \
    --output my-vehicle-skill.tar.gz
```

### Ford vehicle codes

| Code | Vehicle | Years |
|------|---------|-------|
| A | Crown Victoria / Grand Marquis / Town Car | 1995–2003 |
| C | Lincoln Mark VIII | 1996–1998 |
| D | Thunderbird / Cougar | 1996–1997 |
| H | Taurus / Sable (incl. SHO) | 1996–2003 |
| L | Explorer / Ranger | 1996–2003 |
| O | Econoline Van | 1996–2003 |

Filename convention: `STA.ARC` = **S**ervice manual, 199**6** (**T**), vehicle code **A**.

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
- RAG backend implementation
- Three.js 3D viewer with zone-based interaction
- Testing the Ford extractor against other vehicle codes (B, C, D, H, L, O)

## License

MIT — see [LICENSE](LICENSE).

*Note: The extracted service manual content in `vehicles/` may be subject to the original manufacturer's copyright. This project provides tools for extracting data from media you legally own. Redistribution of extracted OEM content may not be permitted.*
