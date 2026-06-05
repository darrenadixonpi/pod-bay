"""Backend configuration — paths and model selection.

A vehicle is a directory under vehicles/<id>/ holding references/ + diagrams/
and a vehicle.json (label, owner's-manual chapters, source provenance). The
active vehicle is chosen by PODBAY_VEHICLE; available_vehicles() discovers the
rest. Everything vehicle-specific lives in the data (vehicle.json), so the code
is vehicle- and manufacturer-agnostic.
"""
import json
import os
from pathlib import Path


def _load_dotenv():
    """Load app/backend/.env into the environment (gitignored, no dependency).

    Runs on import so both `uvicorn server:app` and direct script use pick up
    ANTHROPIC_API_KEY without the caller having to export it. Existing
    environment variables win over .env values.
    """
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

# Repo root: app/backend/config.py -> app/backend -> app -> <root>
REPO_ROOT = Path(__file__).resolve().parents[2]

VEHICLES_ROOT = REPO_ROOT / "vehicles"
VEHICLE_ID = os.environ.get("PODBAY_VEHICLE", "1996-mercury-grand-marquis")
VEHICLE_DIR = VEHICLES_ROOT / VEHICLE_ID
REFERENCES_DIR = VEHICLE_DIR / "references"
DIAGRAMS_DIR = VEHICLE_DIR / "diagrams"

WORKSHOP_MANUAL = REFERENCES_DIR / "workshop_manual.txt"
OWNERS_MANUAL = REFERENCES_DIR / "owners_manual.txt"
SECTION_INDEX = REFERENCES_DIR / "section_index.json"
FIGURES_INDEX = REFERENCES_DIR / "figures.json"


def _vehicle_meta(vehicle_dir: Path) -> dict:
    """Load vehicle.json for a vehicle dir ({} if absent)."""
    p = vehicle_dir / "vehicle.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def available_vehicles() -> list:
    """All extracted vehicles: [{id, label}], by id. A vehicle is any
    vehicles/<id>/ with an extracted workshop manual."""
    out = []
    if VEHICLES_ROOT.exists():
        for d in sorted(VEHICLES_ROOT.iterdir()):
            if (d / "references" / "workshop_manual.txt").exists():
                meta = _vehicle_meta(d)
                out.append({"id": d.name, "label": meta.get("label", d.name)})
    return out


_META = _vehicle_meta(VEHICLE_DIR)

# Human-readable label used in the system prompt.
VEHICLE_LABEL = _META.get("label", VEHICLE_ID)

# Owner's-manual chapter titles for this vehicle (empty if it has no owner's
# manual). retrieval.py segments owners_manual.txt on these headings.
OWNERS_CHAPTERS = _META.get("owners_chapters", [])

# Anthropic model. Sonnet is the sensible default for an interactive repair
# assistant — fast and cheap; bump to opus for harder diagnostic reasoning.
MODEL = os.environ.get("PODBAY_MODEL", "claude-sonnet-4-6")

# --- Retrieval / search ---------------------------------------------------
# search_manual fuses a keyword scorer with a local vector index (see
# vectorstore.py). Modes:
#   "hybrid"  — keyword + vector fused by reciprocal rank fusion (default)
#   "keyword" — original stdlib keyword-only scoring (no chromadb needed)
#   "vector"  — semantic only
# Hybrid falls back to keyword automatically if chromadb/the index is absent.
SEARCH_MODE = os.environ.get("PODBAY_SEARCH", "hybrid").lower()

# Persisted Chroma index for this vehicle (gitignored — rebuildable from the
# manual). Per-vehicle so the registry refactor later just keys off VEHICLE_ID.
INDEX_DIR = VEHICLE_DIR / ".index"

# Passage chunking for the vector index. all-MiniLM-L6-v2 truncates at ~256
# tokens, so keep chunks well under that (~160 words) with overlap so a
# procedure spanning a chunk boundary still embeds coherently.
CHUNK_WORDS = int(os.environ.get("PODBAY_CHUNK_WORDS", "160"))
CHUNK_OVERLAP_WORDS = int(os.environ.get("PODBAY_CHUNK_OVERLAP", "40"))
