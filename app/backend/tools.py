"""Claude tool definitions and dispatch.

The schemas are manufacturer-agnostic (per docs/ARCHITECTURE.md) — the same
tool contract works for any vehicle whose data is loaded behind retrieval.py.
"""
import json

import retrieval
import wiring

TOOLS = [
    {
        "name": "search_manual",
        "description": (
            "Search the vehicle's documentation for relevant procedures, "
            "specifications, diagnostic steps, features, or operating "
            "instructions. Covers BOTH the factory Workshop Manual (repair "
            "procedures, torque specs, pinpoint tests) and the Owner's Manual "
            "(operating the vehicle, warning lights, maintenance schedule, fluid "
            "types, tire pressures). Each result has a `source`: \"workshop\" "
            "(with a section number + page) or \"owners\" (with a chapter name). "
            "Follow up with get_section using that locator to read the full text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_section",
        "description": (
            "Read a documentation section. Pass either a Workshop Manual section "
            "number (e.g. '06-03' for Front Disc Brakes) for procedures/torque "
            "specs/pinpoint tests, OR an Owner's Manual chapter name (e.g. "
            "'Warning Lights and Gauges'). Workshop sections can be 100+ pages, "
            "so this returns a window of pages: ALWAYS pass `around_page` set to "
            "the `page` from the search_manual result you're following up on, so "
            "you get the relevant procedure rather than the section's start. The "
            "response reports the full page range and which pages it returned; "
            "call again with a different `around_page` to read adjacent pages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "Workshop section number (e.g. '06-03') or owner's chapter name",
                },
                "around_page": {
                    "type": "integer",
                    "description": "Page number (from a search_manual result) to center the window on",
                },
            },
            "required": ["section_id"],
        },
    },
    {
        "name": "lookup_component",
        "description": (
            "Look up an electrical component, connector, ground, or splice in "
            "the EVTM wiring database. Returns part number, physical location, "
            "connector id, and zone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Component name, e.g. 'blower motor'"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_diagram",
        "description": (
            "Resolve a technical illustration to a viewable image. Pass a figure "
            "filename exactly as it appears inline in the manual text as "
            "[FIGURE: name.gif] (e.g. 'Y5111B.gif'). Returns a URL plus where the "
            "figure appears. Call this when a procedure references a figure so "
            "the user can see it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "figure_id": {
                    "type": "string",
                    "description": "Figure filename from a [FIGURE: ...] marker, e.g. 'Y5111B.gif'",
                },
            },
            "required": ["figure_id"],
        },
    },
    {
        "name": "get_wiring_diagram",
        "description": (
            "Show the EVTM wiring schematic(s) for an electrical item — the actual "
            "circuit diagram, distinct from the mechanical illustrations get_diagram "
            "returns. Pass either a component/connector/ground/splice name (e.g. "
            "'blower motor', 'C176', 'G101'), or a `diagram_id` from a "
            "lookup_component `schematic_pages` entry or a prior get_wiring_diagram "
            "result (e.g. 'EVC01001'). Returns viewable image URL(s), each schematic's "
            "title, and the other components on that page. Use this whenever the user "
            "needs to trace a circuit, find a wire color, or see how a component is "
            "wired; pair it with lookup_component for the part's location/connector."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Component/connector/ground/splice name, or a wiring diagram_id "
                        "(cell id like 'EVC01001')."
                    ),
                },
            },
            "required": ["query"],
        },
    },
]

_DISPATCH = {
    "search_manual": lambda i, v: retrieval.search_manual(i["query"], i.get("max_results", 5), v),
    "get_section": lambda i, v: retrieval.get_section(i["section_id"], v, i.get("around_page")),
    "lookup_component": lambda i, v: retrieval.lookup_component(i["query"], v),
    "get_diagram": lambda i, v: retrieval.get_diagram(i["figure_id"], v),
    "get_wiring_diagram": lambda i, v: wiring.get_wiring_diagram(i["query"], v),
}


def run_tool(name: str, tool_input: dict, vehicle_id=None) -> str:
    """Execute a tool call against a vehicle and return its result as JSON."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool: {name}"})
    try:
        return json.dumps(fn(tool_input, vehicle_id), ensure_ascii=False)
    except Exception as e:  # surface failures to the model rather than crashing
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
