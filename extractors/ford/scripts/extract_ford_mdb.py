#!/usr/bin/env python3
"""
Ford EVTM (Electrical Vacuum Troubleshooting Manual) MDB Database Extractor

Extracts wiring data from Ford's Access MDB databases (ET*.MDB files) and
exports to CSV and JSON for use in diagnostic skills.

Reading engine (auto-detected): prefers `mdbtools` (mdb-tables/mdb-export) if on
PATH; otherwise falls back to the pure-Python `access_parser` (pip install
access-parser), which needs no external tools and runs natively on Windows where
mdbtools is unavailable. Both emit identical CSV/JSON outputs.

Usage:
    python3 extract_ford_mdb.py /path/to/EN/ --output-dir ./wiring_data
    python3 extract_ford_mdb.py ETA.MDB ETB.MDB --output-dir ./wiring_data
"""

import argparse
import contextlib
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path


# Standard tables found in Ford EVTM MDB files
EVTM_TABLES = [
    'CELLS',      # Wiring diagram cell data
    'COMP',       # Electrical components (descriptions, locations)
    'COMPREF',    # Component cross-references
    'CONN',       # Connectors (pin counts, locations)
    'CONNREF',    # Connector cross-references
    'GRND',       # Ground points
    'GRNDREF',    # Ground cross-references
    'LOCREF',     # Location references
    'PAGEREF',    # Page cross-references
    'SPLCREF',    # Splice cross-references
    'SPLICE',     # Splice locations
]


def check_mdbtools():
    """Verify mdbtools is installed."""
    try:
        subprocess.run(['mdb-tables', '--version'],
                       capture_output=True, check=False)
        return True
    except FileNotFoundError:
        return False


def check_access_parser():
    """Verify the pure-Python access_parser fallback is importable."""
    try:
        import access_parser  # noqa: F401
        return True
    except ImportError:
        return False


def select_engine():
    """Pick a reading engine: 'mdbtools' (preferred) or 'access' (fallback)."""
    if check_mdbtools():
        return 'mdbtools'
    if check_access_parser():
        return 'access'
    return None


# --- access_parser backend -------------------------------------------------
# Parsing the Jet system catalog (MSysObjects) prints recoverable warnings to
# stderr that don't affect user tables; suppress them so output stays clean.
_ACCESS_CACHE = {}


def _access_db(mdb_path: str):
    if mdb_path not in _ACCESS_CACHE:
        from access_parser import AccessParser
        with contextlib.redirect_stderr(io.StringIO()):
            _ACCESS_CACHE[mdb_path] = AccessParser(mdb_path)
    return _ACCESS_CACHE[mdb_path]


# --- engine-dispatching table I/O ------------------------------------------
def list_tables(mdb_path: str, engine: str) -> list:
    """List user tables in an MDB file."""
    if engine == 'mdbtools':
        result = subprocess.run(['mdb-tables', '-1', mdb_path],
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"mdb-tables failed: {result.stderr}")
        return [t.strip() for t in result.stdout.strip().split('\n') if t.strip()]
    # access_parser: catalog includes Jet system tables — drop them.
    db = _access_db(mdb_path)
    return [t for t in db.catalog if not t.startswith('MSys')]


def export_table_csv(mdb_path: str, table_name: str, output_path: str, engine: str):
    """Export a single table to CSV; returns row count."""
    if engine == 'mdbtools':
        result = subprocess.run(['mdb-export', mdb_path, table_name],
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"mdb-export failed for {table_name}: {result.stderr}")
        with open(output_path, 'w') as f:
            f.write(result.stdout)
        return len(result.stdout.strip().split('\n')) - 1  # minus header

    # access_parser: columns -> parallel value lists; write RFC4180 CSV.
    db = _access_db(mdb_path)
    with contextlib.redirect_stderr(io.StringIO()):
        table = db.parse_table(table_name)
    columns = list(table.keys())
    n = len(table[columns[0]]) if columns else 0
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for i in range(n):
            writer.writerow(['' if table[c][i] is None else table[c][i] for c in columns])
    return n


def csv_to_json(csv_path: str, json_path: str) -> int:
    """Convert CSV file to JSON array."""
    records = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Clean up values
            cleaned = {}
            for k, v in row.items():
                if v and v.strip():
                    cleaned[k.strip()] = v.strip()
            if cleaned:
                records.append(cleaned)

    with open(json_path, 'w') as f:
        json.dump(records, f, indent=2)

    return len(records)


def identify_vehicle_code(mdb_filename: str) -> dict:
    """
    Decode the Ford vehicle code from the MDB filename.

    Naming convention: XYZ.MDB where:
    - X = Content type: E=EVTM, S=Service, V=Other
    - Y = Model year: T=1996, V=1997, W=1998, X=1999
    - Z = Vehicle code: A=Crown Vic/Grand Marquis/Town Car,
                         C=Mark VIII, D=T-Bird/Cougar,
                         H=Taurus SHO, L=Explorer/Ranger,
                         O=Econoline Van
    """
    name = Path(mdb_filename).stem.upper()
    if len(name) < 3:
        return {'raw': name}

    content_types = {'E': 'EVTM', 'S': 'Service Manual', 'V': 'Other'}
    years = {'T': '1996', 'V': '1997', 'W': '1998', 'X': '1999',
             'S': '1995', 'U': '1996alt'}
    vehicles = {
        'A': 'Crown Victoria / Grand Marquis / Town Car',
        'C': 'Mark VIII',
        'D': 'Thunderbird / Cougar',
        'H': 'Taurus SHO',
        'L': 'Explorer / Ranger',
        'O': 'Econoline Van',
    }

    return {
        'raw': name,
        'content_type': content_types.get(name[0], f'Unknown ({name[0]})'),
        'model_year': years.get(name[1], f'Unknown ({name[1]})'),
        'vehicle': vehicles.get(name[2], f'Unknown ({name[2]})'),
    }


def main():
    parser = argparse.ArgumentParser(
        description='Extract Ford EVTM wiring data from MDB databases'
    )
    parser.add_argument('inputs', nargs='+',
                        help='MDB file(s) or directory containing MDB files')
    parser.add_argument('--output-dir', '-o', default='./wiring_data',
                        help='Output directory (default: ./wiring_data)')
    parser.add_argument('--format', choices=['csv', 'json', 'both'], default='both',
                        help='Output format (default: both)')
    parser.add_argument('--verbose', '-v', action='store_true')

    args = parser.parse_args()

    engine = select_engine()
    if engine is None:
        print("ERROR: no MDB reader available. Install mdbtools "
              "(apt install mdbtools) or access-parser (pip install access-parser).")
        sys.exit(1)
    print(f"MDB engine: {engine}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect all MDB files
    mdb_files = []
    for inp in args.inputs:
        p = Path(inp)
        if p.is_dir():
            mdb_files.extend(sorted(p.glob('*.MDB')) + sorted(p.glob('*.mdb')))
        elif p.is_file():
            mdb_files.append(p)
        else:
            print(f"WARNING: {inp} not found, skipping")

    if not mdb_files:
        print("No MDB files found.")
        sys.exit(1)

    print(f"Found {len(mdb_files)} MDB file(s)")

    summary = {}

    for mdb_path in mdb_files:
        mdb_name = mdb_path.stem
        vehicle_info = identify_vehicle_code(mdb_name)

        print(f"\n{'=' * 50}")
        print(f"Processing: {mdb_path.name}")
        if 'vehicle' in vehicle_info:
            print(f"  Type: {vehicle_info['content_type']}")
            print(f"  Year: {vehicle_info['model_year']}")
            print(f"  Vehicle: {vehicle_info['vehicle']}")

        try:
            tables = list_tables(str(mdb_path), engine)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        print(f"  Tables: {', '.join(tables)}")

        file_summary = {'tables': {}}

        for table in tables:
            csv_path = output_dir / f'{mdb_name}_{table}.csv'
            try:
                row_count = export_table_csv(str(mdb_path), table, str(csv_path), engine)
                file_summary['tables'][table] = row_count

                if args.format in ('json', 'both'):
                    json_path = output_dir / f'{mdb_name}_{table}.json'
                    csv_to_json(str(csv_path), str(json_path))

                if args.format == 'json':
                    csv_path.unlink()

                if args.verbose:
                    print(f"    {table}: {row_count} rows")
            except Exception as e:
                print(f"    ERROR on {table}: {e}")

        summary[mdb_name] = {**vehicle_info, **file_summary}

    # Write summary
    summary_path = output_dir / 'extraction_summary.json'
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'=' * 50}")
    print(f"Extraction complete. Output in: {output_dir}")
    print(f"Summary: {summary_path}")

    # Print stats
    total_tables = sum(len(s.get('tables', {})) for s in summary.values())
    total_rows = sum(
        sum(s.get('tables', {}).values())
        for s in summary.values()
    )
    print(f"Total: {len(summary)} databases, {total_tables} tables, {total_rows:,} rows")


if __name__ == '__main__':
    main()
