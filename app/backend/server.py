"""FastAPI server exposing a Claude-driven repair assistant for one vehicle.

POST /chat  { "messages": [{"role": "user", "content": "..."}, ...] }
   -> runs the Claude tool-use loop against the workshop manual + wiring data
      and returns the assistant's reply plus a trace of the tool calls made.

Run:  ANTHROPIC_API_KEY=... uvicorn server:app --reload --port 8000
"""
import os

from anthropic import Anthropic
from fastapi import FastAPI
from pydantic import BaseModel

import config
import tools

app = FastAPI(title="Pod Bay backend", version="0.1.0")
client = Anthropic()  # reads ANTHROPIC_API_KEY from env

MAX_TOOL_ROUNDS = 8

SYSTEM_PROMPT = f"""You are a factory-trained service assistant for a {config.VEHICLE_LABEL}.

You have tools that read the complete Ford factory Workshop Manual and the EVTM
wiring database for this exact vehicle. Ground every answer in them:

- Call search_manual to find the relevant procedure, then get_section to read
  it in full before answering. Do not rely on memory for torque specs, pinpoint
  test steps, or sequences — quote them from the manual.
- For electrical work, use lookup_component to give the part number, physical
  location, connector id, and zone.
- Cite the manual section number (e.g. "Section 06-03") in your answer.
- Walk the user through diagnosis step by step. Adapt detail to their apparent
  skill level. Surface the manual's safety warnings when relevant.
- If the manual does not cover something, say so rather than guessing."""


class ChatRequest(BaseModel):
    messages: list[dict]


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[dict]


def _cached_system():
    # Static system prompt — cache it so repeated turns don't re-bill it.
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


def _cached_tools():
    # Mark the last tool so the whole static tool block is cached as one prefix.
    t = [dict(x) for x in tools.TOOLS]
    t[-1] = {**t[-1], "cache_control": {"type": "ephemeral"}}
    return t


@app.get("/health")
def health():
    return {"status": "ok", "vehicle": config.VEHICLE_ID, "model": config.MODEL}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    messages = list(req.messages)
    trace = []

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(
            model=config.MODEL,
            max_tokens=2048,
            system=_cached_system(),
            tools=_cached_tools(),
            messages=messages,
        )

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            return ChatResponse(reply=text, tool_calls=trace)

        # Execute every tool call in this turn and feed results back.
        messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            output = tools.run_tool(block.name, block.input)
            trace.append({"tool": block.name, "input": block.input})
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })
        messages.append({"role": "user", "content": results})

    return ChatResponse(
        reply="(stopped: exceeded tool-call budget without a final answer)",
        tool_calls=trace,
    )
