"""Local web UI for the Owners Forum assistant.

Stdlib only. Binds to 127.0.0.1 for local review. The same root page is
shared with the Vercel entrypoint in api/index.py, while the API handlers live
in api/.

    python3 -m solution.web.server        # then open http://127.0.0.1:8765
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from solution.assistant import llm  # noqa: E402
from solution.web.app import ask_payload, bootstrap_payload, index_html_bytes  # noqa: E402

HOST, PORT = "127.0.0.1", 8765


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
            self._send(200, index_html_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/bootstrap":
            self._json(bootstrap_payload())
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
        payload, code = ask_payload(question, sid, use_llm)
        return self._json(payload, code)


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
