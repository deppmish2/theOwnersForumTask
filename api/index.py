from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solution.web.app import ask_payload, bootstrap_payload, index_html_bytes  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200):
        self._send(code, json.dumps(payload).encode(), "application/json")

    def _route(self) -> str:
        return urlparse(self.path).path

    def do_HEAD(self):
        path = self._route()
        if path in ("/", "/index.html"):
            body = index_html_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return

        if path in ("/api/bootstrap", "/bootstrap"):
            body = json.dumps(bootstrap_payload()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return

        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self._route()
        if path in ("/", "/index.html"):
            self._send(200, index_html_bytes(), "text/html; charset=utf-8")
            return

        if path in ("/api/bootstrap", "/bootstrap"):
            self._json(bootstrap_payload())
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self._route()
        if path not in ("/api/ask", "/ask"):
            self._json({"error": "not found"}, 404)
            return

        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "bad request"}, 400)
            return

        payload, code = ask_payload(
            req.get("question") or "",
            req.get("session_id") or "default",
            bool(req.get("use_llm")),
        )
        self._json(payload, code)
