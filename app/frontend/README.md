# Frontend

3D vehicle viewer and chat interface.

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
