"""Shared pytest setup for the Pod Bay test suite.

The backend modules (`config`, `retrieval`, `vectorstore`, `wiring`) import each
other as top-level modules and are normally run with the working directory set
to `app/backend/`. The extractor scripts live under `extractors/ford/scripts/`.
Neither location is an installable package, so we put both on `sys.path` here
rather than reorganising the project around the tests.

Everything under test imports only the standard library (the extractor) or the
local backend modules (retrieval pulls in config/vectorstore/wiring, none of
which import third-party packages at module load) — so the suite runs without
fastapi, anthropic, or chromadb installed.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

for rel in ("app/backend", "extractors/ford/scripts"):
    p = str(REPO_ROOT / rel)
    if p not in sys.path:
        sys.path.insert(0, p)
