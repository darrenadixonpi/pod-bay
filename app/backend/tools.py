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
            "Search the factory workshop manual for relevant procedures, "
            "specifications, or diagnostic steps. Returns ranked page snippets "
            "with their section number. Follow up with get_section to read the "
            "full procedure."
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
            "Get the full text of a workshop manual section by its number "
            "(e.g. '06-03' for Front Disc Brakes). Use after search_manual to "
            "read complete procedures, torque specs, and pinpoint tests."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {"type": "string", "description": "Section number, e.g. '06-03'"},
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
    "search_manual": lambda i: retrieval.search_manual(i["query"], i.get("max_results", 5)),
    "get_section": lambda i: retrieval.get_section(i["section_id"]),
    "lookup_component": lambda i: retrieval.lookup_component(i["query"]),
    "get_diagram": lambda i: retrieval.get_diagram(i["figure_id"]),
}


def run_tool(name: str, tool_input: dict) -> str:
    """Execute a tool call and return its result as a JSON string."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool: {name}"})
    try:
        return json.dumps(fn(tool_input), ensure_ascii=False)
    except Exception as e:  # surface failures to the model rather than crashing
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
