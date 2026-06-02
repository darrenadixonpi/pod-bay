"""Backend configuration — paths and model selection.

For the MVP this points directly at the single extracted vehicle. Once a
second vehicle exists this becomes a registry keyed by vehicle id.
"""
import os
from pathlib import Path

# Repo root: app/backend/config.py -> app/backend -> app -> <root>
REPO_ROOT = Path(__file__).resolve().parents[2]

VEHICLE_ID = os.environ.get("PODBAY_VEHICLE", "1996-mercury-grand-marquis")
VEHICLE_DIR = REPO_ROOT / "vehicles" / VEHICLE_ID
REFERENCES_DIR = VEHICLE_DIR / "references"
DIAGRAMS_DIR = VEHICLE_DIR / "diagrams"

WORKSHOP_MANUAL = REFERENCES_DIR / "workshop_manual.txt"
OWNERS_MANUAL = REFERENCES_DIR / "owners_manual.txt"
SECTION_INDEX = REFERENCES_DIR / "section_index.json"

# Human-readable label used in the system prompt.
VEHICLE_LABEL = "1996 Mercury Grand Marquis (4.6L SOHC V8, Panther platform)"

# Anthropic model. Sonnet is the sensible default for an interactive repair
# assistant — fast and cheap; bump to opus for harder diagnostic reasoning.
MODEL = os.environ.get("PODBAY_MODEL", "claude-sonnet-4-6")
