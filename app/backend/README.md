# Backend

RAG retrieval server and Claude tool-calling interface.

## Planned stack

- **Vector store:** ChromaDB (local) or SQLite with sqlite-vss (fully offline)
- **Embeddings:** Voyage AI, BGE, or OpenAI text-embedding-3-small
- **API:** FastAPI server exposing tool functions for Claude
- **LLM:** Anthropic Claude API with tool use

## Tool functions to implement

- `search_manual(query)` → vector search over manual pages
- `get_section(section_id)` → full section text retrieval
- `get_diagram(figure_id)` → image + linked procedure text
- `lookup_component(query)` → EVTM database search
- `highlight_zone(zone)` → 3D model zone command (relayed to frontend)

## Status

Not yet implemented. See `docs/ARCHITECTURE.md` for the design.
