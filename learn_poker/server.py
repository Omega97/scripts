"""Local HTTP server for the trainer. Binds to loopback only."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from engine import Engine, NeedHistory

ENGINE: Engine | None = None
STATIC = Path(__file__).resolve().parent / "static"


def _engine() -> Engine:
    if ENGINE is None:
        raise RuntimeError("The app is not ready.")
    return ENGINE


def make_handler(base_handler):
    class Handler(base_handler):
        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def _route(self, method: str) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            try:
                if method == "GET" and path == "/":
                    self._file("index.html", "text/html; charset=utf-8")
                elif method == "GET" and path == "/style.css":
                    self._file("style.css", "text/css; charset=utf-8")
                elif method == "GET" and path == "/app.js":
                    self._file("app.js", "text/javascript; charset=utf-8")
                elif method == "GET" and path == "/api/dashboard":
                    self._json(200, _engine().dashboard())
                elif method == "GET" and path == "/api/hand":
                    mode = (query.get("mode") or [""])[0]
                    exclude = (query.get("exclude") or [""])[0] or None
                    self._json(200, _engine().next_hand(mode, exclude))
                elif method == "POST" and path == "/api/submit":
                    body = self._body()
                    self._json(200, _engine().submit(str(body.get("id") or ""), body.get("points")))
                elif method == "POST" and path == "/api/settings":
                    body = self._body()
                    self._json(200, _engine().set_dataset(str(body.get("dataset") or "")))
                else:
                    self._json(404, {"error": "Not found"})
            except NeedHistory as exc:
                self._json(409, {"error": str(exc)})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except KeyError:
                self._json(404, {"error": "Unknown spot."})
            except Exception:
                traceback.print_exc()
                self._json(500, {"error": "Something went wrong."})

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 1_000_000:
                raise ValueError("Request is too large.")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError("Expected JSON.") from exc
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object.")
            return data

        def _json(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _file(self, name: str, content_type: str) -> None:
            file_path = STATIC / name
            if not file_path.is_file():
                self._json(404, {"error": "Missing interface file."})
                return
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return Handler
