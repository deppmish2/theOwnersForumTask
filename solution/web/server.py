"""Local web UI for the Owners Forum assistant.

Stdlib only. Binds to 127.0.0.1 — this is a local review tool, not a
deployable service (no auth, no multi-tenancy; see NOTES.md).

    python3 -m solution.web.server        # then open http://127.0.0.1:8765
"""

from __future__ import annotations

import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from solution.assistant.engine import Engine  # noqa: E402
from solution.assistant.data import Store  # noqa: E402
from solution.assistant import llm  # noqa: E402
from solution.assistant.narrate import natural_text  # noqa: E402

HOST, PORT = "127.0.0.1", 8765
STATIC = Path(__file__).parent / "index.html"

# one Store shared by every session (read-only); one Engine per browser session
_STORE = Store()
_SESSIONS: dict[str, Engine] = {}

EXAMPLES = {
    "Core prompts": [
        "Which member guests are attending the Berlin Manufacturing Forum?",
        "note: Priya mentioned they may expand the Osaka hub next year",
        "Show recent activity for Northstar Holdings",
        "Which accounts have recent succession or ownership activity in Asia?",
        "Which German family-owned industrials are active in data centers?",
        "Prep call notes for an upcoming Valen Group call",
        "Is Meridian Foods attending the Berlin dinner?",
        "Has Cardso Precision been involved in Asian events?",
        "Who potentially knows someone at Hansei Textiles?",
        "What do we know about Priya Kapoor?",
        "Give me Priya Kapoor's contact details",
    ],
    "Bonus prompts": [
        "Which families are preparing for a sale or ownership change?",
        "Is Valen Group active in data centers?",
        "Tell me everything about Daniel Weber's succession plans",
        "Who should I contact about the Singapore dinner?",
        "Is Northstar Holdings active in renewable packaging?",
    ],
}


def _engine_for(sid: str) -> Engine:
    if sid not in _SESSIONS:
        _SESSIONS[sid] = Engine(store=_STORE)
    return _SESSIONS[sid]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter console
        pass

    # ------------------------------------------------------------------ util
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200):
        self._send(code, json.dumps(payload).encode(), "application/json")

    # ------------------------------------------------------------------- GET
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, STATIC.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/bootstrap":
            self._json({
                "examples": EXAMPLES,
                "llm_available": llm.available(),
                "counts": {name: len(rows) for name, rows in _STORE.tables.items()},
                "session_id": secrets.token_hex(8),
            })
        else:
            self._json({"error": "not found"}, 404)

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        if self.path != "/api/ask":
            return self._json({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "bad request"}, 400)

        question = (req.get("question") or "").strip()
        sid = req.get("session_id") or "default"
        use_llm = bool(req.get("use_llm"))
        if not question:
            return self._json({"error": "empty question"}, 400)

        engine = _engine_for(sid)
        try:
            answer = engine.ask(question)
        except Exception as exc:  # never 500 the UI on a bad parse
            return self._json({"mode": "refuse",
                               "text": f"The assistant could not handle that input ({exc}).",
                               "citations": [], "flags": [], "prose": None,
                               "notes": []})

        prose = None
        if use_llm and answer.mode == "answer" and llm.available():
            try:
                prose = natural_text(llm.compose(question, answer.render()))
            except Exception as exc:
                prose = f"(Claude layer unavailable this turn: {exc})"

        return self._json({
            "mode": answer.mode,
            "answer": natural_text(answer.prose),
            "detail": natural_text(answer.text),
            "citations": answer.citations,
            "flags": [natural_text(flag) for flag in answer.flags],
            "prose": prose,                  # optional Claude rewrite
            "notes": engine.session.all(),
        })


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Owners Forum assistant — http://{HOST}:{PORT}")
    print(f"Claude prose layer: {'available' if llm.available() else 'not configured'}")
    print("Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        server.server_close()


if __name__ == "__main__":
    main()
