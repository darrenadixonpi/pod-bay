# Ford TSO Extractor

Extracts factory service manuals from Ford's proprietary TSO (Technical Service Online) disc archives, used at Ford/Lincoln/Mercury dealerships from approximately 1995–2003.

## Format

Ford TSO discs use the **POD BAY** archive format with **IDICOMP** compressed blocks. See [`docs/FORMAT_SPECIFICATION.md`](../../docs/FORMAT_SPECIFICATION.md) for the complete specification.

## Scripts

| Script | Purpose |
|--------|---------|
| `extract_ford_arc.py` | Extract HTML pages and GIF diagrams from .ARC archives |
| `extract_ford_mdb.py` | Export EVTM wiring databases (MDB → CSV/JSON) |
| `build_skill.py` | Package extracted data into a Claude-compatible skill |

## Usage

```bash
# Extract service manual
python3 scripts/extract_ford_arc.py STA.ARC -o ./output --format text --extract-images -v

# Extract wiring data
python3 scripts/extract_ford_mdb.py ./mdb_folder/ -o ./wiring -v

# Build LLM skill package
python3 scripts/build_skill.py \
    --vehicle "1997 Ford Crown Victoria" \
    --engine "4.6L SOHC V8" \
    --manual-dir ./output \
    --wiring-dir ./wiring \
    -o crown-vic-skill.tar.gz
```

## Prerequisites

- Python 3.8+
- `mdbtools` for MDB export: `apt install mdbtools`
- `7z` for OVA/VMDK extraction: `apt install p7zip-full`

## Getting .ARC files from a TSO disc

```bash
# If starting from an OVA
tar xf vehicle.ova              # extract VMDK from OVA
7z x vehicle.vmdk -o./extracted # browse VMDK contents

# Service manual archives are typically at:
#   DATA/SERVICE/ST*.ARC
# Wiring diagram archives at:
#   DATA/EVTM/ET*.ARC
# MDB databases at:
#   DATA/DATABASE/US/EN/*.MDB
```
