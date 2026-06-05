"""Claude tool definitions and dispatch.

The schemas are manufacturer-agnostic (per docs/ARCHITECTURE.md) — the same
tool contract works for any vehicle whose data is loaded behind retrieval.py.
"""
import json

import retrieval

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
            "Get the full text of a documentation section. Pass either a "
            "Workshop Manual section number (e.g. '06-03' for Front Disc Brakes) "
            "to read complete procedures/torque specs/pinpoint tests, OR an "
            "Owner's Manual chapter name (e.g. 'Warning Lights and Gauges') to "
            "read operating instructions. Use the locator returned by "
            "search_manual."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "Workshop section number (e.g. '06-03') or owner's chapter name",
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
]

_DISPATCH = {
    "search_manual": lambda i, v: retrieval.search_manual(i["query"], i.get("max_results", 5), v),
    "get_section": lambda i, v: retrieval.get_section(i["section_id"], v),
    "lookup_component": lambda i, v: retrieval.lookup_component(i["query"], v),
    "get_diagram": lambda i, v: retrieval.get_diagram(i["figure_id"], v),
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
