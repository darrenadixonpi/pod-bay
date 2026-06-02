# Backend

RAG retrieval server and Claude tool-calling interface. Also serves the
single-page web UI in `app/frontend/` from the same process.

**Status:** MVP implemented for the `1996-mercury-grand-marquis` data. Keyword
retrieval over the workshop manual + EVTM wiring tables, wired into a Claude
tool-use loop behind a FastAPI `/api/chat` endpoint, with a browser chat UI.

## Run

```bash
pip install -r requirements.txt

# Put your key in a gitignored .env (loaded automatically on startup):
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env       # or create app/backend/.env by hand

uvicorn server:app --reload --port 8000
```

Then open **http://localhost:8000** for the chat UI. API directly:

```bash
curl localhost:8000/api/health
curl -X POST localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"How do I replace the front brake pads and what are the torque specs?"}]}'
```

`/api/chat` returns `{ "reply": "...", "tool_calls": [ ... ] }` — `tool_calls`
is a trace of which retrieval tools Claude invoked, surfaced in the UI's
"What I looked at" panel and useful for judging retrieval quality.

### Endpoints

| Route | Purpose |
|-------|---------|
| `GET /` | Chat web UI (served from `app/frontend/`) |
| `GET /api/health` | Liveness + active vehicle/model |
| `GET /api/vehicle` | Vehicle label + diagram filenames |
| `POST /api/chat` | Claude tool-use loop; `{messages}` → `{reply, tool_calls}` |
| `GET /diagrams/<file>` | Extracted GIF diagrams (static) |

## Layout

| File | Role |
|------|------|
| `config.py` | Paths to the vehicle data + model selection (env-overridable) |
| `retrieval.py` | The 4 tool functions over local files — stdlib only, no API key needed. Unit-testable in isolation. |
| `tools.py` | Claude tool schemas + dispatch to `retrieval` |
| `server.py` | FastAPI `/chat` running the Claude tool-use loop (system prompt + tools are prompt-cached) |

Override the model with `PODBAY_MODEL` (default `claude-sonnet-4-6`) and the
vehicle with `PODBAY_VEHICLE` (default `1996-mercury-grand-marquis`).

## Tool functions

- `search_manual(query, max_results)` → ranked page snippets (keyword scored) ✅
- `get_section(section_id)` → full section text ✅
- `lookup_component(query)` → EVTM part #, location, connector, zone ✅
- `get_diagram(figure_id)` → **stub.** Manual-text→diagram linkage was lost in
  extraction (`<img>` tags stripped; GIFs named by block index, not figure id).
  Returns the available diagram files. Fixing it requires re-extracting with
  `<img src>` preserved — see the get_diagram gap noted in `CLAUDE.md`.

## Next steps

- Swap keyword search for vector search behind the same `retrieval.py`
  signatures (ChromaDB or sqlite-vss) once retrieval quality demands it.
- Fix the diagram linkage in the Ford extractor, then make `get_diagram` real.
- `highlight_zone` (3D) is intentionally not implemented yet — deferred until a
  model viewer exists; the tool contract in `docs/ARCHITECTURE.md` reserves it.
