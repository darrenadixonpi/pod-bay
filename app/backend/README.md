# Backend

RAG retrieval server and Claude tool-calling interface. Also serves the
single-page web UI in `app/frontend/` from the same process.

**Status:** working, **multi-vehicle** (one process serves all 6 built vehicles,
chosen per request). Hybrid keyword + local Chroma vector retrieval over the
workshop/owner's manuals + EVTM wiring tables and schematics, wired into a Claude
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
| `GET /api/health` | Liveness + default vehicle/model |
| `GET /api/vehicles` | All built vehicles + the default (populates the picker) |
| `GET /api/vehicle?vehicle_id=` | Vehicle label + diagram filenames |
| `POST /api/chat` | Claude tool-use loop; `{messages, vehicle_id}` → `{reply, tool_calls, diagrams}` |
| `GET /diagrams/<vid>/<file>` | Service-illustration GIFs (path-traversal guarded) |
| `GET /wiring/<vid>/<file>` | EVTM wiring-schematic GIFs (path-traversal guarded) |

## Layout

| File | Role |
|------|------|
| `config.py` | Per-vehicle registry (`get_vehicle(id)`) + model/search selection (env-overridable) |
| `retrieval.py` | Manual search/section + component tools over local files — no API key needed. Unit-testable in isolation. |
| `vectorstore.py` | Local Chroma index (ONNX `all-MiniLM-L6-v2`, no API); `search_manual` fuses it with keyword via RRF. Build: `python -m vectorstore [--force]`. |
| `wiring.py` | EVTM wiring index (`CELLS` + `*REF` tables → `wiring_diagrams/` GIFs); powers `get_wiring_diagram`. |
| `tools.py` | Claude tool schemas + dispatch to `retrieval` / `wiring` |
| `server.py` | FastAPI `/chat` running the Claude tool-use loop (system prompt + tools are prompt-cached) |

Override the model with `PODBAY_MODEL` (default `claude-sonnet-4-6`) and the
vehicle with `PODBAY_VEHICLE` (default `1996-mercury-grand-marquis`).

## Tool functions

- `search_manual(query, max_results)` → ranked page snippets, **hybrid** keyword + vector (RRF), each tagged `workshop`/`owners` ✅
- `get_section(section_id, around_page)` → a **page-windowed** slice (~5k-token cap) centered on `around_page` ✅
- `lookup_component(query)` → EVTM part #, location, connector, zone; each match also carries `schematic_pages` ✅
- `get_diagram(figure_id)` → resolves a `[FIGURE: name.gif]` reference to a `/diagrams/<vid>/<file>` URL + where it appears. Case-insensitive. The UI renders these inline. ✅
- `get_wiring_diagram(query)` → resolves a component/connector/ground/splice name OR a cell `diagram_id` to EVTM schematic image(s) at `/wiring/<vid>/<file>`, with each diagram's title + the other parts on the page. ✅

## Next steps

- Retrieval-quality tuning (reranking, chunking) behind the same `retrieval.py` signatures.
- `highlight_zone` and the 3D/CAD tool set (`isolate`/`explode`/`set_camera`/…) are
  reserved until a CAD viewer exists — see "3D / CAD layer" in `docs/ARCHITECTURE.md`.
