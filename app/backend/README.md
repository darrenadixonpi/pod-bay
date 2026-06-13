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

### Serve on a phone (installable PWA)

The web UI is a PWA — addable to a phone's home screen, with the shell and seen
diagrams cached offline. The browser only installs it over HTTPS, so use the LAN
launcher instead of plain `uvicorn` when you want it on a phone:

```bash
pip install cryptography          # one-time; only LAN HTTPS needs it
python run_lan.py                 # self-signed cert + uvicorn on 0.0.0.0 over TLS
```

It prints a `https://<lan-ip>:8000/` URL to open on a phone on the same wifi.
Full walkthrough (cert trust on iOS, the warning-free Tailscale alternative) is
in [`docs/MOBILE_ACCESS.md`](../../docs/MOBILE_ACCESS.md).

### Endpoints

| Route | Purpose |
|-------|---------|
| `GET /` | Chat web UI (served from `app/frontend/`) |
| `GET /api/health` | Liveness + default vehicle/model + effective search mode |
| `GET /api/vehicles` | All built vehicles + the default (populates the picker) |
| `GET /api/vehicle?vehicle_id=` | Vehicle label, diagram filenames, per-vehicle search mode |
| `GET /api/sections?vehicle_id=` | Workshop section index + owner's chapters (Sections browser) |
| `POST /api/chat` | Claude tool-use loop; `{messages, vehicle_id}` → `{reply, tool_calls, diagrams}` |
| `POST /api/chat/stream` | Same loop, streamed as SSE (`text` / `tool_call` / `done` / `error` events) |
| `GET /diagrams/<vid>/<file>` | Service-illustration GIFs (path-traversal guarded) |
| `GET /wiring/<vid>/<file>` | EVTM wiring-schematic GIFs (path-traversal guarded) |

## Tests

A hermetic suite at the repo root exercises the trickiest code with synthetic
inputs — no vehicle data, no API key, none of the runtime third-party packages:

```bash
pip install -r requirements-dev.txt
python -m pytest            # from the repo root
```

`tests/test_idicomp.py` round-trips the IDICOMP decompressor against an
independent encoder (every token path, the 16-item flag-word reload, LZ overlap)
and checks record-name decoding + archive/header/chunk parsing. `tests/test_retrieval.py` covers tokenisation, BM25 ordering, reciprocal-rank
fusion, the section char-cap, snippet centering, owner's-manual TOC parsing, and
the page-windowed `get_section`.

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
- `get_secti