#!/usr/bin/env python3
"""
Assemble a Pod Bay vehicle directory from Ford TSO source archives.

Chains the two extractors (extract_ford_arc.py for the workshop manual +
service diagrams, extract_ford_mdb.py for the EVTM wiring tables) and lays the
results out under vehicles/<id>/ exactly as the backend expects:

    vehicles/<id>/
      references/workshop_manual.txt, section_index.json, figures.json
      references/<EVTM>_<TABLE>.csv / .json     (if an MDB is given)
      diagrams/*.gif
      vehicle.json                              (id, label, source provenance)

The vehicle id + label are derived from the manual's own title (e.g. a manual
that says "1998 Taurus/Sable Workshop Manual" -> id 1998-taurus-sable), so no
hardcoded vehicle-code map is needed. This is the regeneration path for the
fleet: source ARCs/MDBs stay on disk (gitignored), vehicle data is rebuildable.

Usage:
    python3 build_vehicle.py "archive/.ARC files/SWH.ARC" \
        --mdb "archive/.MDB files/EWH.MDB"
    python3 build_vehicle.py SVD.ARC --id 1997-thunderbird-cougar --label "1997 Thunderbird/Cougar"
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parents[2]  # scripts -> ford -> extractors -> repo root
_TITLE_RE = re.compile(r"(19\d\d)\s+(.{1,40}?)\s+Workshop Manual")


def _slug(s: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def derive_identity(manual_text: str, fallback: str):
    """(id, label) from the manual's most common '19XX <Model> Workshop Manual'."""
    hits = Counter(_TITLE_RE.findall(manual_text[:2_000_000]))
    if hits:
        year, model = hits.most_common(1)[0][0]
        model = re.sub(r"\s+", " ", model).strip()
        return f"{year}-{_slug(model)}", f"{year} {model}"
    return _slug(fallback), fallback


def run(cmd):
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description="Build a Pod Bay vehicle from Ford TSO archives")
    ap.add_argument("service_arc", help="Service/workshop .ARC file")
    ap.add_argument("--mdb", help="EVTM .MDB wiring database (optional)")
    ap.add_argument("--vehicles-root", default=str(REPO_ROOT / "vehicles"))
    ap.add_argument("--id", help="Override the derived vehicle id (dir name)")
    ap.add_argument("--label", help="Override the derived human label")
    args = ap.parse_args()

    service_arc = Path(args.service_arc)
    if not service_arc.is_file():
        sys.exit(f"ERROR: service ARC not found: {service_arc}")
    py = sys.executable

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        arc_out = tmp / "arc"

        print(f"[1/4] Extracting workshop manual + diagrams from {service_arc.name}")
        run([py, str(SCRIPTS_DIR / "extract_ford_arc.py"), str(service_arc),
             "-o", str(arc_out), "--format", "text", "--extract-images"])

        manual = next(arc_out.glob("*_manual.txt"))
        section_index = next(arc_out.glob("*_section_index.json"))
        figures = next(arc_out.glob("*_figures.json"))
        manual_text = manual.read_text(encoding="utf-8", errors="replace")

        vid = args.id or derive_identity(manual_text, service_arc.stem)[0]
        label = args.label or derive_identity(manual_text, service_arc.stem)[1]
        print(f"[2/4] Identity: id={vid!r}  label={label!r}")

        vdir = Path(args.vehicles_root) / vid
        refs = vdir / "references"
        refs.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(manual, refs / "workshop_manual.txt")
        shutil.copyfile(section_index, refs / "section_index.json")
        shutil.copyfile(figures, refs / "figures.json")

        # Diagrams: replace any existing set so re-runs are clean.
        diagrams = vdir / "diagrams"
        if diagrams.exists():
            shutil.rmtree(diagrams)
        shutil.move(str(arc_out / "images"), str(diagrams))
        n_gifs = sum(1 for _ in diagrams.glob("*.gif"))

        evtm = None
        if args.mdb:
            print(f"[3/4] Extracting wiring tables from {Path(args.mdb).name}")
            mdb_out = tmp / "mdb"
            run([py, str(SCRIPTS_DIR / "extract_ford_mdb.py"), args.mdb,
                 "-o", str(mdb_out), "--format", "both"])
            for f in sorted(mdb_out.glob("*.csv")) + sorted(mdb_out.glob("*.json")):
                if f.name == "extraction_summary.json":
                    continue
                shutil.copyfile(f, refs / f.name)
                evtm = evtm or f.stem.split("_")[0]
        else:
            print("[3/4] No MDB given — skipping wiring tables")

        print("[4/4] Writing vehicle.json")
        (vdir / "vehicle.json").write_text(json.dumps({
            "id": vid,
            "label": label,
            "source_archives": {
                "workshop": service_arc.name,
                "evtm_wiring_db": Path(args.mdb).name if args.mdb else None,
            },
            "owners_chapters": [],
        }, indent=2) + "\n", encoding="utf-8")

        print(f"\nDone: {vdir}")
        print(f"  manual pages source: {manual.name}")
        print(f"  diagrams: {n_gifs}")
        print(f"  wiring prefix: {evtm or '(none)'}")
        print("Next: build its search index with `python -m vectorstore` in app/backend.")


if __name__ == "__main__":
    main()
