# 1996 Mercury Grand Marquis

**Platform:** Panther (shared with Crown Victoria, Town Car)
**Engine:** 4.6L SOHC V8 (2-valve, Romeo/Windsor)
**Transmission:** 4R70W 4-speed automatic

## Extracted data

| File | Size | Contents |
|------|------|----------|
| `references/workshop_manual.txt` | 3.9 MB | Complete factory workshop manual (2,146 pages) |
| `references/owners_manual.txt` | 348 KB | Full owner's manual |
| `references/section_index.json` | 17 KB | Index of all 83 sections with page counts |
| `references/ETA_COMP.csv` | 30 KB | 286 electrical components |
| `references/ETA_CONN.csv` | 29 KB | 312 connectors with pin counts and locations |
| `references/ETA_GRND.csv` | 883 B | 13 ground points |
| `references/ETA_SPLICE.csv` | 11 KB | 167 splice locations |
| `references/ETA_PAGEREF.csv` | 75 KB | 1,271 page cross-references |
| `diagrams/` | ~50 files | Extracted GIF technical illustrations |

## Source

Extracted from Ford TSO (Technical Service Online) disc archive `STA.ARC` using `extractors/ford/scripts/extract_ford_arc.py`. Wiring data from EVTM MDB databases using `extract_ford_mdb.py`. Zero decompression errors.

## Key specifications

- **Engine oil:** 5W-30 Motorcraft, 5 quarts with filter
- **Coolant:** 50/50 Ford Premium (ESE-M97B44-A)
- **Transmission fluid:** Motorcraft MERCON (not Mercon V), ~12 qt total
- **Spark plugs:** Motorcraft AWSF-32PP, gap 0.054" (1.37mm)
- **Firing order:** 1-3-7-2-6-5-4-8
- **Lug nut torque:** 115–142 Nm (85–105 lb-ft)
