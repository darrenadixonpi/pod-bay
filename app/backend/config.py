"""Backend configuration — vehicle registry and model selection.

A vehicle is a directory under vehicles/<id>/ holding references/ + diagrams/
and a vehicle.json (label, owner's-manual chapters, source provenance).
`get_vehicle(id)` returns an immutable Vehicle with all its paths;
`available_vehicles()` lists them. The backend resolves a vehicle per request,
so one process serves every extracted vehicle. PODBAY_VEHICLE only sets the
default when a request doesn't specify one. Everything vehicle-specific lives in
the data (vehicle.json), so the code is vehicle- and manufacturer-agnostic.
"""
import json
import os
from dataclasses import dataclass
from functools import lru_cache
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

# Default vehicle when a request doesn't name one.
DEFAULT_VEHICLE_ID = os.environ.get("PODBAY_VEHICLE", "1996-mercury-grand-marquis")


@dataclass(frozen=True)
class Vehicle:
    """An extracted vehicle and the paths to its data."""
    id: str
    label: str
    owners_chapters: tuple  # tuple (not list) so Vehicle stays hashable/cacheable

    @property
    def dir(self) -> Path:
        return VEHICLES_ROOT / self.id

    @property
    def references_dir(self) -> Path:
        return self.dir / "references"

    @property
    def diagrams_dir(self) -> Path:
        return self.dir / "diagrams"

    @property
    def workshop_manual(self) -> Path:
        return self.references_dir / "workshop_manual.txt"

    @property
    def owners_manual(self) -> Path:
        return self.references_dir / "owners_manual.txt"

    @property
    def section_index(self) -> Path:
        return self.references_dir / "section_index.json"

    @property
    def figures_index(self) -> Path:
        return self.references_dir / "figures.json"

    @property
    def index_dir(self) -> Path:
        # Persisted Chroma index (gitignored — rebuildable from the manual).
        return self.dir / ".index"


def _vehicle_meta(vehicle_dir: Path) -> dict:
    """Load vehicle.json for a vehicle dir ({} if absent)."""
    p = vehicle_dir / "vehicle.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def vehicle_exists(vehicle_id: str) -> bool:
    return (VEHICLES_ROOT / vehicle_id / "references" / "workshop_manual.txt").exists()


@lru_cache(maxsize=None)
def get_vehicle(vehicle_id: str = None) -> Vehicle:
    """Resolve a Vehicle by id (defaults to DEFAULT_VEHICLE_ID). Cached.

    Raises ValueError for an unknown id so callers can fall back deliberately.
    """
    vid = vehicle_id or DEFAULT_VEHICLE_ID
    vdir = VEHICLES_ROOT / vid
    if not (vdir / "references" / "workshop_manual.txt").exists():
        raise ValueError(f"unknown vehicle: {vid!r}")
    meta = _vehicle_meta(vdir)
    return Vehicle(
        id=vid,
        label=meta.get("label", vid),
        owners_chapters=tuple(meta.get("owners_chapters", [])),
    )


def available_vehicles() -> list:
    """All extracted vehicles: [{id, label}], by id. A vehicle is any
    vehicles/<id>/ with an extracted workshop manual."""
    out = []
    if VEHICLES_ROOT.exists():
        for d in sorted(VEHICLES_ROOT.iterdir()):
            if (d / "references" / "workshop_manual.txt").exists():
                out.append({"id": d.name, "label": _vehicle_meta(d).get("label", d.name)})
    return out


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

# Passage chunking for the vector index. all-MiniLM-L6-v2 truncates at ~256
# tokens, so keep chunks well under that (~160 words) with overlap so a
# procedure spanning a chunk boundary still embeds coherently.
CHUNK_WORDS = int(os.environ.get("PODBAY_CHUNK_WORDS", "160"))
CHUNK_OVERLAP_WORDS = int(os.environ.get("PODBAY_CHUNK_OVERLAP", "40"))
