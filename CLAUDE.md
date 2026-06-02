# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Pod Bay is a platform for extracting factory automotive service manuals from proprietary OEM formats and packaging them for LLM consumption (and, eventually, a RAG backend + 3D viewer + mobile app — those parts are unbuilt). The only implemented component today is the **Ford TSO extractor**. The name comes from the `POD BAY` magic header in Ford's `.ARC` archive format, the first format reverse-engineered here.

## Commands

The extractor scripts are plain Python 3.8+ with **no third-party dependencies for the core ARC pipeline** (only stdlib). There is no build step, no test suite, no linter configured.

```bash
# Extract service/workshop manual from a Ford TSO .ARC file
python3 extractors/ford/scripts/extract_ford_arc.py STA.ARC -o ./output --format text --extract-images -v

# Export EVTM wiring databases (MDB -> CSV/JSON). Requires mdbtools.
python3 extractors/ford/scripts/extract_ford_mdb.py ./EN_databases/ -o ./wiring -v

# Package extracted data into a Claude skill tarball
python3 extractors/ford/scripts/build_skill.py \
    --vehicle "1996 Mercury Grand Marquis" --engine "4.6L SOHC V8" --platform "Panther" \
    --manual-dir ./output --wiring-dir ./wiring -o my-vehicle-skill.tar.gz
```

External tools (not Python packages): `mdbtools` (`mdb-tables`/`mdb-export`) for `extract_ford_mdb.py`; `7z` (p7zip) for unpacking OVA/VMDK discs to get `.ARC`/`.MDB` files; `capstone` (`pip install capstone`) only if reverse-engineering a *new* format.

## Platform note

The dev environment here is **Windows**, but the extractor scripts were written for Linux:
- `extract_ford_mdb.py` shells out to `mdbtools`, which is not available on Windows — run MDB extraction under WSL/Linux, or via Access/LibreOffice manually.
- `build_skill.py` hardcodes its scratch dir to `/tmp/skill_build` (line ~109). This will fail on native Windows; run it under WSL or change the path if working on Windows directly.

## Architecture

The extraction pipeline is three independent scripts chained by their file outputs (not imports). `extract_ford_arc.py` + `extract_ford_mdb.py` produce a directory of artifacts; `build_skill.py` consumes that directory by globbing for files (`*_manual.txt`, `*_section_index.json`, `*.csv`) — it does **not** take structured arguments pointing at specific files. So the contract between stages is filename conventions, documented in `docs/CONTRIBUTING.md` under "Required outputs":
- `<arc>_manual.txt` — one page per `=`-separator block
- `<arc>_section_index.json` — array of `{section, name, page_count, total_chars, first_page, last_page}`
- `images/` — extracted GIFs
- `<mdb>_<TABLE>.csv` / `.json` — wiring tables (CELLS, COMP, CONN, GRND, SPLICE, and their `*REF` cross-reference tables)

A new manufacturer extractor is expected to emit these same outputs so `build_skill.py` and downstream consumers stay format-agnostic. See `docs/ARCHITECTURE.md` for the planned full system (format-detection router → extraction handlers → unified knowledge base → RAG → LLM tool layer → mobile app) and the manufacturer-agnostic Claude tool interface (`search_manual`, `get_section`, `get_diagram`, `lookup_component`, `highlight_zone`).

### The IDICOMP decompressor

The heart of the Ford extractor is `decompress_ford()` in `extract_ford_arc.py`. It implements a custom LZSS-like hybrid RLE+LZ codec reverse-engineered by disassembling `tsobrowser.exe`. Key facts when touching it:
- Compressed stream is groups of ≤16 items, each group prefixed by a **16-bit little-endian flag word processed MSB-first** (mask starts at `0x8000`, shifts right; reload when it hits 0).
- Flag bit 0 = literal byte; flag bit 1 = reference token. The token's **high nibble** selects one of four decode paths: `0x0` RLE-short, `0x1` RLE-long, `0x2` LZ-long, `0x3`–`0xF` LZ-short (high nibble *is* the length).
- Distances/lengths and their byte layouts are exact and non-obvious — do not "simplify" the arithmetic. The full spec with annotated x86 disassembly and reference pseudocode is in `docs/FORMAT_SPECIFICATION.md` §3; treat it as the source of truth and the regression reference (verified at 0% error across 2,146 pages).

### Archive structure (parse_arc_header / extract_blocks)

`.ARC` files: `POD BAY` (or `BAY POD` v2) magic, uint32 record count at offset 9, then 15-byte records, then data. Data blocks are located by scanning for the `\x01IDICOMP\x01` marker, each followed by a **signed int16 block size**: positive = compressed, negative = raw (e.g. GIFs, already LZW-compressed), zero = end-of-stream. Content type (html/gif/wcf/xml) is sniffed from the first decompressed/raw bytes.

## Ford file naming

3-letter `.ARC`/`.MDB` names encode `[content][year][vehicle]`: content `S`=Service/`E`=EVTM/`V`=Other; year `S`=1995/`T`=1996/`V`=1997/`W`=1998/`X`=1999; vehicle `A`=Crown Vic/Grand Marquis/Town Car, `C`=Mark VIII, `D`=T-Bird/Cougar, `H`=Taurus/Sable, `L`=Explorer/Ranger, `O`=Econoline. Example: `STA.ARC` = Service manual, 1996, code A. Only code A is validated; B–O are untested but expected to work identically.

## Extracted vehicle data

`vehicles/1996-mercury-grand-marquis/` holds the one complete extraction (2,146 pages, EVTM CSVs, 50 GIF diagrams). Extracted OEM manual content may be under manufacturer copyright — the tooling is for media you legally own; do not commit redistributable OEM content casually.
