"""Backend configuration — paths and model selection.

For the MVP this points directly at the single extracted vehicle. Once a
second vehicle exists this becomes a registry keyed by vehicle id.
"""
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

VEHICLE_ID = os.environ.get("PODBAY_VEHICLE", "1996-mercury-grand-marquis")
VEHICLE_DIR = REPO_ROOT / "vehicles" / VEHICLE_ID
REFERENCES_DIR = VEHICLE_DIR / "references"
DIAGRAMS_DIR = VEHICLE_DIR / "diagrams"

WORKSHOP_MANUAL = REFERENCES_DIR / "workshop_manual.txt"
OWNERS_MANUAL = REFERENCES_DIR / "owners_manual.txt"
SECTION_INDEX = REFERENCES_DIR / "section_index.json"
FIGURES_INDEX = REFERENCES_DIR / "figures.json"

# Human-readable label used in the system prompt.
VEHICLE_LABEL = "1996 Mercury Grand Marquis (4.6L SOHC V8, Panther platform)"

# Anthropic model. Sonnet is the sensible default for an interactive repair
# assistant — fast and cheap; bump to opus for harder diagnostic reasoning.
MODEL = os.environ.get("PODBAY_MODEL", "claude-sonnet-4-6")
