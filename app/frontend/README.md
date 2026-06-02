# Frontend

Web chat UI for the service assistant, plus (planned) 3D vehicle viewer.

## Current MVP

A dependency-free single-page app (`index.html` + `styles.css` + `app.js`,
no build step) served by the backend at `http://localhost:8000`. Uses
`marked` (via CDN) to render the assistant's markdown.

- **Chat** with the Claude-backed assistant (`POST /api/chat`)
- **"What I looked at"** panel — live trace of the retrieval tools Claude
  called each turn (searches, sections opened, components looked up)
- **Diagrams** tab — gallery of the extracted GIF diagrams with a lightbox

Run the backend (see `app/backend/README.md`) and open the root URL; the page
calls the same-origin `/api/*` endpoints, so there's no separate dev server or
CORS setup.

## Planned stack

- **3D engine:** Three.js (WebGL) loading glTF 2.0 models
- **Mobile framework:** React Native or Flutter
- **Screens:** 3D model viewer, chat interface, manual browser

## 3D viewer requirements

- Load glTF model with named mesh zones
- Tap/click zones to highlight and trigger info panel
- Camera orbit animation to preset viewpoints per zone
- Accept `highlight_zone` commands from the chat/backend
- Bidirectional: tapping a zone sends a prompt to the LLM

## Status

Not yet implemented. See `docs/ARCHITECTURE.md` for the design.
