# Frontend

Web chat UI for the service assistant, plus (planned) 3D CAD viewer.

## Current MVP

A dependency-free single-page app (`index.html` + `styles.css` + `app.js`,
no build step) served by the backend at `http://localhost:8000`. Uses
`marked` (via CDN) to render the assistant's markdown.

- **Vehicle picker** — header dropdown (from `/api/vehicles`); switching reloads
  the diagram gallery and starts a fresh conversation
- **Chat** with the Claude-backed assistant (`POST /api/chat`)
- **Inline figures** — service illustrations *and* EVTM wiring schematics the
  assistant references render inline under the answer (lightbox on click)
- **"What I looked at"** panel — live trace of the retrieval tools Claude
  called each turn (searches, sections, components, diagrams, wiring schematics)
- **Diagrams** tab — gallery of the vehicle's extracted GIFs with a lightbox
- **⬇ Export** — download the conversation (messages + tool calls + diagrams) as JSON

Run the backend (see `app/backend/README.md`) and open the root URL; the page
calls the same-origin `/api/*` endpoints, so there's no separate dev server or
CORS setup.

## Planned: 3D CAD viewer

**Real CAD, system-by-system — not AI-generated geometry.** See "3D / CAD layer"
in `docs/ARCHITECTURE.md` for the full rationale and pipeline.

- **3D engine:** Three.js (WebGL) loading glTF 2.0 tessellated from CAD (STEP/JT),
  **with the assembly hierarchy preserved** as named, addressable nodes
- **Driven by the LLM over the part tree**, not raw geometry — accepts tool
  commands: `isolate`, `explode`, `set_camera`, `highlight` (`highlight_zone` is
  the reserved entry point)
- **Bidirectional:** tapping a part sends a prompt to the LLM
- **Mobile framework (later):** React Native or Flutter — screens: CAD viewer,
  chat, manual browser

Not yet implemented; gated on sourcing service-grade CAD per system.
