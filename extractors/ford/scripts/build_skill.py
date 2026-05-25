#!/usr/bin/env python3
"""
Build a Claude skill package from extracted Ford service manual data.

Takes the output of extract_ford_arc.py and extract_ford_mdb.py and packages
it into a skill tarball (.tar.gz) ready for upload to Claude.

Usage:
    python3 build_skill.py \
        --vehicle "1997 Ford Crown Victoria" \
        --engine "4.6L SOHC V8" \
        --manual-dir ./output \
        --wiring-dir ./wiring_data \
        --output my-vehicle-skill.tar.gz
"""

import argparse
import json
import os
import re
import shutil
import tarfile
from pathlib import Path


SKILL_TEMPLATE = '''---
name: {skill_name}
description: |
  Diagnose and repair a {vehicle_name} ({engine_desc}).
  This skill contains the complete Ford factory Workshop Manual ({page_count} pages),
  owner's manual (if available), and EVTM wiring database.
  Use whenever the user mentions their {vehicle_short}, or any repair, diagnosis,
  maintenance, or wiring question for this vehicle. Also trigger for DTC codes,
  electrical diagnosis, or any service procedure.
---

# {vehicle_name} — Complete Service Reference

## Vehicle Overview

| Attribute | Value |
|-----------|-------|
| **Vehicle** | {vehicle_name} |
| **Engine** | {engine_desc} |
| **Platform** | {platform} |

## How to Use This Skill

### Reference Data Available

All reference files are in `references/` relative to this skill:

1. **`workshop_manual.txt`** — Complete Ford Workshop Manual ({page_count} pages).
   Search by section number or keyword using grep or reading relevant pages.

2. **`section_index.json`** — Index of all {section_count} workshop manual sections
   with page counts and sizes. **Read this FIRST** to find which section covers a topic.

{owners_manual_line}
{wiring_data_lines}

### Diagnostic Workflow

When the user describes a problem:

1. **Read `section_index.json`** to identify which manual section(s) cover the system
2. **Search `workshop_manual.txt`** for the relevant section content
3. **Follow the manual's diagnostic procedure** — includes complete pinpoint tests
   with step-by-step yes/no decision trees
4. **Look up wiring** using the EVTM CSV files when electrical diagnosis is needed
5. **Provide torque specs, part numbers, and procedures** directly from the manual

### Workshop Manual Section Map

{section_map}

### Important Safety Notes

- **NEVER remove pressure relief cap while engine is hot**
- **Fuel system is pressurized** — relieve pressure before any fuel system service
- **Air bag system** — disconnect battery and wait 1 minute before servicing
- **Gas-pressurized shock absorbers** — do not apply heat or flame
- **Always use correct torque specifications** from the specific manual section
'''


def main():
    parser = argparse.ArgumentParser(
        description='Build a Claude skill from extracted Ford manual data'
    )
    parser.add_argument('--vehicle', required=True,
                        help='Full vehicle name (e.g., "1997 Ford Crown Victoria")')
    parser.add_argument('--engine', default='',
                        help='Engine description (e.g., "4.6L SOHC V8")')
    parser.add_argument('--platform', default='',
                        help='Platform name (e.g., "Panther")')
    parser.add_argument('--manual-dir', required=True,
                        help='Directory containing extracted manual text and index')
    parser.add_argument('--wiring-dir', default=None,
                        help='Directory containing extracted wiring CSV/JSON')
    parser.add_argument('--owners-manual', default=None,
                        help='Path to owners manual text file')
    parser.add_argument('--output', '-o', required=True,
                        help='Output path for skill tarball (.tar.gz)')

    args = parser.parse_args()

    manual_dir = Path(args.manual_dir)
    skill_dir = Path('/tmp/skill_build')
    refs_dir = skill_dir / 'references'

    # Clean and create
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    refs_dir.mkdir(parents=True)

    # Find the manual text file
    manual_files = list(manual_dir.glob('*_manual.txt')) + list(manual_dir.glob('*manual*.txt'))
    if not manual_files:
        print("ERROR: No manual text file found in manual-dir")
        return
    manual_file = manual_files[0]
    shutil.copy(manual_file, refs_dir / 'workshop_manual.txt')

    # Find the section index
    index_files = list(manual_dir.glob('*_section_index.json')) + list(manual_dir.glob('*index*.json'))
    section_count = 0
    page_count = 0
    section_map_lines = []

    if index_files:
        shutil.copy(index_files[0], refs_dir / 'section_index.json')
        with open(index_files[0]) as f:
            index = json.load(f)
        section_count = len(index)
        page_count = sum(s['page_count'] for s in index)

        # Build section map
        current_group = ''
        for s in index:
            group = s['section'].split('-')[0]
            if group != current_group:
                current_group = group
                section_map_lines.append(f"| **Group {group}** | |")
            name = s['name'][:60] if s['name'] else '(unnamed)'
            section_map_lines.append(
                f"| {s['section']} | {name} ({s['page_count']} pages) |"
            )

    # Copy wiring data
    wiring_lines = []
    if args.wiring_dir:
        wiring_dir = Path(args.wiring_dir)
        csv_files = list(wiring_dir.glob('*.csv'))
        for csv_file in csv_files:
            shutil.copy(csv_file, refs_dir / csv_file.name)
        if csv_files:
            wiring_lines.append(
                f"4. **EVTM Wiring Data** ({len(csv_files)} CSV files) — "
                "Component, connector, ground, and splice databases"
            )

    # Copy owners manual
    owners_line = ''
    if args.owners_manual and Path(args.owners_manual).exists():
        shutil.copy(args.owners_manual, refs_dir / 'owners_manual.txt')
        owners_line = "3. **`owners_manual.txt`** — Owner's manual with maintenance schedules and fluid specs"

    # Generate skill name
    vehicle_short = re.sub(r'^\d{4}\s+', '', args.vehicle)
    skill_name = re.sub(r'[^a-z0-9]+', '-', args.vehicle.lower()).strip('-')

    # Build SKILL.md
    section_map = '\n'.join(section_map_lines) if section_map_lines else '(section map not available)'
    wiring_data_text = '\n'.join(wiring_lines) if wiring_lines else ''

    skill_md = SKILL_TEMPLATE.format(
        skill_name=skill_name,
        vehicle_name=args.vehicle,
        vehicle_short=vehicle_short,
        engine_desc=args.engine or '(see manual)',
        platform=args.platform or '(see manual)',
        page_count=page_count,
        section_count=section_count,
        owners_manual_line=owners_line,
        wiring_data_lines=wiring_data_text,
        section_map=section_map,
    )

    (skill_dir / 'SKILL.md').write_text(skill_md)

    # Package as tarball
    output_path = Path(args.output)
    with tarfile.open(output_path, 'w:gz') as tar:
        for item in skill_dir.rglob('*'):
            arcname = str(item.relative_to(skill_dir))
            tar.add(item, arcname=arcname)

    size = output_path.stat().st_size
    print(f"Skill package created: {output_path} ({size:,} bytes)")
    print(f"  Vehicle: {args.vehicle}")
    print(f"  Pages: {page_count}")
    print(f"  Sections: {section_count}")
    print(f"  Wiring files: {len(wiring_lines)}")

    # Cleanup
    shutil.rmtree(skill_dir)


if __name__ == '__main__':
    main()
