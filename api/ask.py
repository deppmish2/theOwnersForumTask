from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solution.web.app import ask_payload  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            body = json.dumps({"error": "bad request"}).encode()
            return self._send(400, body, "application/json")

        payload, code = ask_payload(
            req.get("question") or "",
            req.get("session_id") or "default",
            bool(req.get("use_llm")),
        )
        body = json.dumps(payload).encode()
        return self._send(code, body, "application/json")

