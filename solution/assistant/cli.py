"""REPL for the Owners Forum assistant.

Run from the repo root:  python -m solution.assistant.cli
Add a session note:      note: <text>       (or /note <text>)
Toggle Claude prose:     /llm on | /llm off (needs ANTHROPIC_API_KEY)
Quit:                    /quit
"""

from __future__ import annotations

import sys

from .engine import Engine
from . import llm

BANNER = """Owners Forum assistant — closed dataset, grounded answers only.
Commands: 'note: <text>' add session note | /llm on|off | /quit
"""


def main() -> None:
    engine = Engine()
    use_llm = False
    print(BANNER)
    if llm.available():
        print("(Claude composition available — '/llm on' to enable prose answers)\n")

    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q in ("/quit", "/exit", "quit", "exit"):
            break
        if q.startswith("/llm"):
            arg = q.split()[-1] if len(q.split()) > 1 else ""
            if arg == "on" and not llm.available():
                print("assistant> Claude layer unavailable (no credential or "
                      "anthropic package missing).\n")
                continue
            use_llm = arg == "on"
            print(f"assistant> Claude prose layer {'ON' if use_llm else 'OFF'}.\n")
            continue
        if q.startswith("/note "):
            q = "note: " + q[6:]

        answer = engine.ask(q)
        rendered = answer.render()
        if use_llm and answer.mode == "answer":
            try:
                rendered = llm.compose(q, rendered)
            except Exception as exc:  # network/credential issues → deterministic answer
                rendered += f"\n(llm layer failed, deterministic answer shown: {exc})"
        print(f"assistant> {rendered}\n")


if __name__ == "__main__":
    sys.exit(main())
