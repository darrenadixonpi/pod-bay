"""Live smoke test of the Claude tool-use loop against the vehicle data.

Reads ANTHROPIC_API_KEY from the environment or from a local .env file (which
is gitignored). Sends a few real repair questions through the same chat() the
server uses and prints the reply plus the tool-call trace, so we can judge
retrieval quality end to end.

Run:  .venv\\Scripts\\python.exe live_test.py
"""
import os

import config  # loads .env on import

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise SystemExit(
        "No ANTHROPIC_API_KEY found. Create app/backend/.env with:\n"
        "    ANTHROPIC_API_KEY=sk-ant-...\n"
        "(.env is gitignored)"
    )

import server  # noqa: E402

QUESTIONS = [
    "My blower motor only works on high. What's the likely cause and how do I diagnose it?",
    "How do I replace the front brake pads, and what are the caliper bolt torque specs?",
]


def main():
    for q in QUESTIONS:
        print("=" * 80)
        print("Q:", q)
        print("-" * 80)
        resp = server.chat(server.ChatRequest(messages=[{"role": "user", "content": q}]))
        print(resp.reply)
        print("\n[tool calls]")
        for t in resp.tool_calls:
            print("  ", t["tool"], t["input"])
        print()


if __name__ == "__main__":
    main()
