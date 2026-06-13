# 3D / CAD Viewer — Scoping Plan

**Status:** proposal / scoping. Nothing here is built yet. This document turns
the "3D / CAD layer" section of [`ARCHITECTURE.md`](ARCHITECTURE.md) into a
concrete, phased plan: what to build, in what order, how it slots into the
existing backend/frontend, and — most importantly — where the real risk is.

## 1. Goal and non-goals

**Goal.** Let the assistant *show* a repair in three dimensions: isolate the
part under discussion, explode an assembly, frame the camera on it, and let the
user orbit/zoom — driven by the same LLM-as-director tool pattern the wiring and
diagram features already use. The 3D view augments the 2D factory illustrations
and EVTM schematics; it does not replace them.

**Non-goals (firm).**

- **No AI-generated geometry.** For a service tool the geometry must be
  mechanically truthful — the actual bracket with the actual bolt pattern — or
  it is worse than nothing (confidently wrong). Generative/photogrammetry-guess
  3D is out of scope as load-bearing reference. This is the load-bearing
  principle of the whole layer.
- **Not "model the whole car."** 3D is a per-system, opportunistic layer
  (front brakes, steering linkage, one suspension corner), lit up when a good
  model of *that system* exists. The 2D manual + wiring remain the backbone.
- **The LLM never touches raw geometry** (B-rep surfaces, million-triangle
  meshes). It reasons over a *named assembly tree* and issues commands against
  named handles — exactly how `get_wiring_diagram` works over `CELLS`/`*REF`
  tables rather than over pixels.

## 2. The actual blocker: asset sourcing, not software

The software is a known quantity (Three.js + glTF + a tool layer that mirrors
what already exists). The hard problem is **sourcing mechanically-faithful CAD**
with an assembly hierarchy:

- Unlike the 2D illustrations and wiring — which we legally extract from TSO
  media the user owns — factory 3D CAD for these 1995–99 Ford/Mercury vehicles
  is OEM-proprietary and effectively unavailable.
- A survey of community sources (GrabCAD, Sketchfab, TurboSquid, Cults/STL
  sites) found only exterior body shells for rendering, single-mesh print
  models, and generic V8 engines — **none with the assembly structure or part
  fidelity a service tool needs.**

Realistic asset paths, all constrained:

| Path | Fidelity | Cost / effort | Licensing |
|------|----------|---------------|-----------|
| Aftermarket / community models | Variable, usually single-mesh | Low $ | Landmines — most disallow redistribution |
| Photogrammetry / 3D-scanning real parts | High (the real part) | High manual labor per part | Clean (you own the scan) |
| Commissioned CAD | High | Expensive | Clean |

**Implication for sequencing:** decouple the software risk from the sourcing
risk. Build and prove the entire stack against *one* placeholder assembly first
(Phase 0), so that the day a good model of a real system appears, lighting it up
is a data task, not an engineering project.

## 3. Phased plan

### Phase 0 — De-risk the stack against a placeholder (software only)

Build the complete vertical slice — data format, viewer, tools, director loop —
against a **single, deliberately fake** assembly: a hand-built blocky glTF (e.g.
a caliper + 2 pads + rotor as labeled boxes/cylinders) with a real assembly
tree. No sourcing required. Goal: prove the architecture end-to-end and lock the
data contract before any real CAD exists. Everything in Phases 1–4 is developed
here; Phase 5 swaps the placeholder for a real model.

### Phase 1 — Per-vehicle CAD data format

Define and document the assembly-tree index, mirroring the existing
filename-convention contract (`section_index.json`, `figures.json`, the EVTM
CSVs). Add a `cad/` directory under each vehicle:

```
vehicles/<id>/cad/
  <system>.glb                 # tessellated geometry + embedded node names
  <system>_assembly.json       # the indexed part tree the LLM reasons over
```

`<system>_assembly.json` (proposed shape, parallel to how `figures.json` maps
pages→figures):

```json
{
  "system": "front-brakes",
  "title": "Front Disc Brake Assembly",
  "glb": "front-brakes.glb",
  "up_axis": "Y",
  "units": "mm",
  "manual_sections": ["06-03"],
  "nodes": [
    {
      "id": "fb.caliper",
      "name": "Brake Caliper",
      "parent": null,
      "gltf_node": "Caliper_RH",
      "bbox": [[-40,-60,-30],[40,60,30]],
      "manual_figures": ["Y5111B.gif"],
      "components": []
    },
    {
      "id": "fb.caliper.piston",
      "name": "Caliper Piston",
      "parent": "fb.caliper",
      "gltf_node": "Piston",
      "bbox": [[-20,-20,-10],[20,20,10]]
    }
  ]
}
```

Notes:
- `id` is the stable LLM-facing handle; `gltf_node` is the viewer-facing handle
  inside the GLB. Keeping them distinct means re-tessellating the GLB can't
  break the LLM's references as long as the mapping is maintained.
- `manual_sections` / `manual_figures` cross-link the 3D node to the 2D corpus,
  so the viewer ties back into the Section browser and figure rendering we
  already have (the same way wiring `schematic_pages` cross-links components).
- Commit policy mirrors diagrams/wiring: `*_assembly.json` committed (small,
  textual), `*.glb` gitignored as bulky/regenerable (add `vehicles/*/cad/*.glb`
  to `.gitignore`).

A small **pure-Python indexer** (`extractors/cad/index_assembly.py`) reads a GLB
node tree and emits `<system>_assembly.json` (node ids, names, parent links,
bboxes). Keeps the "indexes are generated, viewer just renders" contract.

### Phase 2 — Browser glTF viewer

A self-contained viewer module added to the existing frontend (no build step;
Three.js from the CDN, consistent with how `marked` is loaded). It:

- loads a vehicle's `<system>.glb` via `GLTFLoader` (+ Draco/meshopt
  decompression for size);
- supports orbit/zoom/pan, per-node select → show the node name + its
  `manual_sections`/`manual_figures` links;
- exposes an imperative API the director commands map onto: `isolate(nodeId)`,
  `explode(assemblyId, factor)`, `setCamera(view|nodeId)`, `highlight(nodeIds)`,
  `hide/show(nodeId)`, `sectionCut(plane)`, `resetView()`, `measure(a,b)`.

Placement: a fourth reference-panel tab ("3D") alongside Trace / Diagrams /
Sections, or a dedicated route. On mobile it reuses the existing drawer; the
canvas must size to the drawer and release its WebGL context when hidden.

### Phase 3 — Backend tools (`cad.py` + `tools.py` entries)

A new `app/backend/cad.py` loads `<system>_assembly.json` per vehicle (lru-cached
like `retrieval._pages`) and answers the structured queries. New tools, following
the exact `tools.py` schema + `_DISPATCH` pattern:

| Tool | Input | Returns |
|------|-------|---------|
| `list_systems` | — | systems with a CAD model for this vehicle |
| `list_parts` | `system` (or `assembly_id`) | child nodes (id, name) of that node |
| `highlight_zone` *(reserved today)* | `part_id` | resolved node + a `viewer_command` for the UI |
| `isolate` | `part_id` | viewer_command |
| `explode` | `assembly_id`, `factor?` | viewer_command |
| `set_camera` | `view` or `part_id` | viewer_command |
| `section_cut` | `plane` | viewer_command |

The query tools (`list_systems`, `list_parts`) return data the model reasons
over; the manipulation tools return a small **`viewer_command`** object that the
frontend executes against the Phase-2 viewer API. This keeps the backend
stateless about render state — same division as `get_diagram` returning a URL the
UI loads.

### Phase 4 — LLM director integration

- Extend the system prompt: when a CAD model exists for the relevant system,
  walk the named tree and drive the viewer (isolate the part under discussion,
  explode to show relationships), while still grounding torque specs/procedures
  in the manual via `get_section`. Geometry illustrates; the manual remains the
  source of truth.
- Transport: `viewer_command`s ride the **existing SSE channel**. The streaming
  endpoint already emits `tool_call` events; add a `viewer_command` event (or
  carry it in the tool result) that `app.js` dispatches to the viewer. The
  "What I looked at" trace can surface CAD director actions too.
- Cross-linking: a highlighted node's `manual_figures`/`manual_sections` become
  the same clickable affordances we just built (figure rendering, Section-browser
  jump), so 3D ↔ 2D ↔ wiring stay one connected experience.

### Phase 5 — Asset acquisition (the long pole)

Per-system, opportunistic, and the gate on everything being *useful* rather than
*demonstrated*. For each candidate system: confirm a model with a real assembly
tree and clean license exists (or scan/commission one) → tessellate STEP/JT →
GLB preserving hierarchy + names (OpenCASCADE / Assimp / CAD Exchanger) → run the
Phase-1 indexer → drop into `vehicles/<id>/cad/`. First target should be a
high-value, geometrically simple system (front brakes is the natural pilot:
small part count, common service job, already well-covered by the manual for
cross-linking).

## 4. Effort sizing (relative)

| Phase | Scope | Size | Gated by |
|-------|-------|------|----------|
| 0 | Placeholder asset + vertical slice | M | nothing — start here |
| 1 | Data format + Python indexer | S–M | Phase 0 contract |
| 2 | Three.js viewer + API | M–L | — |
| 3 | `cad.py` + tool schemas | S–M | Phase 1 format |
| 4 | Director prompt + SSE wiring | M | Phases 2–3 |
| 5 | Real CAD per system | **XL, recurring** | **asset sourcing** |

Phases 0–4 are bounded, conventional engineering and could land as a working
placeholder demo. Phase 5 is open-ended and external — it is where the project
either becomes genuinely useful or stays a tech demo.

## 5. Tech choices and dependencies

- **Render:** Three.js + `GLTFLoader`, `OrbitControls`, Draco/meshopt decoders —
  CDN-loaded, no front-end build step (matches current setup).
- **Format:** glTF 2.0 / GLB (hierarchy + node names + metadata in one file).
- **Tessellation (offline):** OpenCASCADE (open-source) or CAD Exchanger
  (commercial, best JT/STEP fidelity); Assimp for format glue. Not a runtime dep.
- **Backend:** new `cad.py` is pure-stdlib JSON indexing (parallels
  `retrieval.py`); no new runtime packages. The indexer may use `trimesh`/`pygltflib`
  as a **dev/extractor** dependency only (like `mdbtools`/`capstone` today).

## 6. Risks and mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| No faithful CAD is ever sourced | High | Phase 0 proves the stack regardless; ship it as an opt-in per-system feature; never block the 2D backbone on it |
| Licensing of community models | High | Treat like OEM content: only ship assets you can legally redistribute; keep GLBs gitignored and local |
| "Truthful geometry" erosion | High | Hard rule: no generative/guessed meshes as reference; label provenance per asset in `*_assembly.json` |
| Coordinate frame / unit mismatches | Med | Record `up_axis`/`units` in the index; normalize at tessellation |
| Mobile WebGL performance | Med | Draco compression, per-system (small) models, release GL context when the drawer closes |
| LLM references a node that isn't in the GLB | Med | `cad.py` validates `id`→`gltf_node` mapping on load; tools reject unknown ids with a helpful error (same pattern as `get_section` unknown-section) |

## 7. Recommendation and open decisions

**Recommended first move:** Phase 0 — build the full vertical slice against a
placeholder front-brake assembly. It de-risks the architecture, exercises the
data contract, and produces a real (if synthetic) demo, all without waiting on
sourcing. Then pursue a real front-brake model as the Phase-5 pilot.

**Decisions needed before starting (yours to make):**

1. **First system** — front brakes (recommended: simple, high-value, well
   cross-linked) or something else?
2. **Asset path** — accept community models where licensing allows, invest in
   photogrammetry of real parts, or commission CAD? This determines Phase 5
   timeline more than any code decision.
3. **Viewer placement** — a fourth "3D" tab in the reference panel, or a
   dedicated full-screen route? (Affects mobile layout.)
4. **Scope of the placeholder demo** — isolate/explode/camera only, or the full
   tool set (section_cut, measure) from the start?

## 8. Definition of done (pilot)

A user asks about a front-brake service on a vehicle that has a CAD model; the
assistant isolates the caliper, explodes the assembly to show the pads and
rotor, frames the camera, and the user can orbit it — while the torque specs and
procedure still come verbatim from the Workshop Manual via `get_section`, and the
highlighted parts link back to their factory figures and section. The same build
runs unchanged for vehicles without a model (the 3D tab simply reports "no CAD
model for this vehicle yet").
