"""FastAPI server exposing a Claude-driven repair assistant.

POST /api/chat  { "messages": [...], "vehicle_id": "<id>" }
   -> runs the Claude tool-use loop against that vehicle's workshop manual +
      wiring data and returns the assistant's reply plus a trace of tool calls.

One process serves every extracted vehicle; the active vehicle is chosen per
request (defaults to config.DEFAULT_VEHICLE_ID).

Run:  ANTHROPIC_API_KEY=... uvicorn server:app --reload --port 8000
"""
import json
import sys

from anthropic import Anthropic, APIStatusError, APIError
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import tools

app = FastAPI(title="Pod Bay backend", version="0.2.0")
client = Anthropic()  # reads ANTHROPIC_API_KEY from env

FRONTEND_DIR = config.REPO_ROOT / "app" / "frontend"

MAX_TOOL_ROUNDS = 8


def system_prompt(vehicle_label: str) -> str:
    return f"""You are a factory-trained service assistant for a {vehicle_label}.

You have tools that read the complete Ford factory Workshop Manual, the Owner's
Manual (when available), and the EVTM wiring database for this exact vehicle.
Ground every answer in them:

- Call search_manual to find the relevant content, then get_section to read it
  before answering. It spans both manuals: the Workshop Manual for repair
  procedures, torque specs, and pinpoint tests, and the Owner's Manual for
  operating the vehicle, warning lights, maintenance intervals, fluid types,
  and tire pressures. When following up a workshop result, ALWAYS pass
  get_section the `page` from that search result as `around_page` — sections can
  be 100+ pages, and this returns the right procedure instead of the section's
  start. If the returned text doesn't cover what you need, the response notes
  the page range; call get_section again with a different `around_page`. Each
  result is tagged with its source — cite the Workshop Manual section number
  (e.g. "Section 06-03") or the Owner's Manual chapter name accordingly. Do not
  rely on memory for torque specs, pinpoint test steps, or sequences — quote
  them from the manual.
- For electrical work, use lookup_component to give the part number, physical
  location, connector id, and zone.
- The manual text contains inline figure markers like [FIGURE: Y5111B.gif].
  When a figure is directly relevant, call get_diagram with that exact filename,
  then embed it in your answer at the relevant point as a markdown image using
  the `url` field get_diagram returns, verbatim: ![short caption](<that url>).
  Embed each figure exactly once, next to the step or component it illustrates.
  Prefer the 1-3 most relevant figures rather than every one mentioned.
- Walk the user through diagnosis step by step. Adapt detail to their apparent
  skill level. Surface the manual's safety warnings when relevant.
- If the manual does not cover something, say so rather than guessing."""


class ChatRequest(BaseModel):
    messages: list[dict]
    vehicle_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[dict]
    diagrams: list[dict] = []  # resolved figures: {figure_id, url}


def _resolve_vehicle(vehicle_id: str | None) -> config.Vehicle:
    """Validate a requested vehicle id, falling back to the default."""
    try:
        return config.get_vehicle(vehicle_id)
    except ValueError:
        return config.get_vehicle(None)


def _cached_system(vehicle_label: str):
    # System prompt varies by vehicle; cache each so repeated turns don't re-bill.
    return [{"type": "text", "text": system_prompt(vehicle_label),
             "cache_control": {"type": "ephemeral"}}]


def _cached_tools():
    # Mark the last tool so the whole static tool block is cached as one prefix.
    t = [dict(x) for x in tools.TOOLS]
    t[-1] = {**t[-1], "cache_control": {"type": "ephemeral"}}
    return t


def _trim_history(messages: list) -> list:
    """Keep only the most recent messages, starting on a user turn.

    Bounds per-request input cost in long sessions. The Anthropic API requires
    the first message to be a user message, so drop a leading assistant turn.
    """
    msgs = list(messages)[-config.MAX_HISTORY_MESSAGES:]
    if msgs and msgs[0].get("role") != "user":
        msgs = msgs[1:]
    return msgs


def _with_cache_breakpoint(messages: list) -> list:
    """Copy of messages with a cache_control marker on the last content block.

    This caches the whole conversation prefix, so within the tool-use loop each
    round re-reads earlier tool results (e.g. a get_section payload) at ~10% cost
    instead of re-sending them at full price; it also warms the next turn within
    the 5-min cache TTL. (Marks only the latest message — total breakpoints stay
    under the limit: system + tools + this = 3 of 4.)
    """
    if not messages:
        return messages
    out = [dict(m) for m in messages]
    last = dict(out[-1])
    content = last["content"]
    content = [{"type": "text", "text": content}] if isinstance(content, str) \
        else [dict(b) for b in content]
    content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    last["content"] = content
    out[-1] = last
    return out


def _log_usage(vehicle_id: str, usage) -> None:
    """Print per-call token usage so cache savings are observable."""
    print(
        f"[chat] {vehicle_id} in={usage.input_tokens} out={usage.output_tokens} "
        f"cache_read={getattr(usage, 'cache_read_input_tokens', 0)} "
        f"cache_write={getattr(usage, 'cache_creation_input_tokens', 0)}",
        file=sys.stderr,
    )


@app.get("/api/health")
def health():
    return {"status": "ok", "default_vehicle": config.DEFAULT_VEHICLE_ID, "model": config.MODEL}


@app.get("/api/vehicles")
def vehicles():
    """All extracted vehicles, and which one is the default."""
    return {"default": config.DEFAULT_VEHICLE_ID, "vehicles": config.available_vehicles()}


@app.get("/api/vehicle")
def vehicle(vehicle_id: str | None = None):
    """Vehicle label + available diagram filenames for the UI."""
    v = _resolve_vehicle(vehicle_id)
    diagrams = sorted(p.name for p in v.diagrams_dir.glob("*.gif"))
    return {"id": v.id, "label": v.label, "diagrams": diagrams}


@app.get("/diagrams/{vehicle_id}/{filename}")
def diagram(vehicle_id: str, filename: str):
    """Serve a single diagram GIF for a vehicle (path-traversal safe)."""
    if not config.vehicle_exists(vehicle_id):
        raise HTTPException(404, "unknown vehicle")
    path = (config.VEHICLES_ROOT / vehicle_id / "diagrams" / filename).resolve()
    diagrams_dir = (config.VEHICLES_ROOT / vehicle_id / "diagrams").resolve()
    if diagrams_dir not in path.parents or not path.is_file():
        raise HTTPException(404, "diagram not found")
    return FileResponse(path, media_type="image/gif")


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    vehicle = _resolve_vehicle(req.vehicle_id)
    messages = _trim_history(req.messages)
    trace = []
    diagrams = []  # resolved figures to show in the UI

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            resp = client.messages.create(
                model=config.MODEL,
                max_tokens=2048,
                system=_cached_system(vehicle.label),
                tools=_cached_tools(),
                messages=_with_cache_breakpoint(messages),
            )
            _log_usage(vehicle.id, resp.usage)
        except APIStatusError as e:
            # Surface API problems (429 rate limit, 529 overloaded, auth, …) as a
            # readable assistant message instead of an opaque HTTP 500.
            if e.status_code == 429:
                msg = ("⚠️ The Anthropic API rate limit was hit (your tier allows a "
                       "limited number of tokens per minute). Wait ~30s and try again.")
            elif e.status_code in (500, 502, 503, 529):
                msg = "⚠️ The Anthropic API is temporarily unavailable. Please try again shortly."
            else:
                msg = f"⚠️ Anthropic API error ({e.status_code}). Please try again."
            return ChatResponse(reply=msg, tool_calls=trace, diagrams=diagrams)
        except APIError as e:
            return ChatResponse(reply=f"⚠️ Could not reach the Anthropic API: {e}",
                                tool_calls=trace, diagrams=diagrams)

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            return ChatResponse(reply=text, tool_calls=trace, diagrams=diagrams)

        # Execute every tool call in this turn and feed results back.
        messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            output = tools.run_tool(block.name, block.input, vehicle.id)
            trace.append({"tool": block.name, "input": block.input})
            # Collect resolved diagrams so the UI can render them inline.
            if block.name == "get_diagram":
                parsed = json.loads(output)
                if parsed.get("resolved") and not any(d["url"] == parsed["url"] for d in diagrams):
                    diagrams.append({"figure_id": parsed["figure_id"], "url": parsed["url"]})
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })
        messages.append({"role": "user", "content": results})

    return ChatResponse(
        reply="(stopped: exceeded tool-call budget without a final answer)",
        tool_calls=trace,
        diagrams=diagrams,
    )


# Frontend — mounted last so /api/* and /diagrams/* routes take precedence.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
