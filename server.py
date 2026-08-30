"""The web side: serves the map page and streams each turn to it over SSE.

Standard library only, so the whole thing runs with `python main.py` and no
build step.
"""

import json
import mimetypes
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from sessions import STORE
from world import ROOMS, DOORS, ITEMS, MONSTERS, START_ROOM

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# The map never changes, so build the payload once.
MAP_PAYLOAD = {
    "start": START_ROOM,
    "width": max(r.x for r in ROOMS) + 1,
    "height": max(r.y for r in ROOMS) + 1,
    "rooms": [{"key": r.key, "name": r.name, "x": r.x, "y": r.y,
               "dark": r.dark, "heat": r.heat} for r in ROOMS],
    "doors": [{"a": d.a, "b": d.b, "locked": bool(d.key), "secret": d.secret,
               "blocked": d.blocked_by} for d in DOORS],
    "items": [{"key": i.key, "name": i.name, "treasure": i.treasure} for i in ITEMS],
    "monsters": [{"key": m.key, "name": m.name} for m in MONSTERS],
}

# main.py fills these in so the page can tell the player who to call.
CALL_INFO = {"number": None, "ready": False}
COMMAND_HOOK = None  # set by main.py: (session, text) -> narration


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Kaldrath"

    def log_message(self, fmt, *args):
        pass  # the agent's own logging is noisy enough

    # ------------------------------------------------------------- utilities

    def _send(self, code, body, content_type="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except ValueError:
            return {}

    # --------------------------------------------------------------- routing

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        path = url.path

        if path == "/":
            return self._serve_static("index.html")
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        if path == "/api/map":
            return self._send(200, MAP_PAYLOAD)
        if path == "/api/new":
            session = STORE.create()
            return self._send(200, {"code": session.code, **self._env()})
        if path == "/api/state":
            session = STORE.get(query.get("code", [""])[0])
            if session is None:
                return self._send(404, {"error": "no such session"})
            return self._send(200, {**session.state(), **self._env()})
        if path == "/api/board":
            return self._send(200, {"leaderboard": STORE.leaderboard(),
                                    "ghosts": STORE.ghosts(), "summary": STORE.summary()})
        if path == "/api/events":
            return self._serve_events(query.get("code", [""])[0])
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/api/command":
            data = self._body()
            session = STORE.get(data.get("code"))
            if session is None:
                return self._send(404, {"error": "no such session"})
            if COMMAND_HOOK is None:
                return self._send(503, {"error": "game not ready"})
            narration = COMMAND_HOOK(session, data.get("text", ""))
            return self._send(200, {"narration": narration, **session.state()})
        if url.path == "/api/name":
            data = self._body()
            session = STORE.get(data.get("code"))
            if session is None:
                return self._send(404, {"error": "no such session"})
            session.player_name = (data.get("name") or "").strip()[:24] or None
            session.publish()
            return self._send(200, session.state())
        return self._send(404, {"error": "not found"})

    def _env(self):
        return {"call_number": CALL_INFO["number"], "phone_ready": CALL_INFO["ready"],
                "ghosts": STORE.ghosts(), "leaderboard": STORE.leaderboard(),
                "summary": STORE.summary()}

    # ---------------------------------------------------------------- static

    def _serve_static(self, name):
        name = os.path.normpath(name).lstrip("./")
        full = os.path.join(STATIC_DIR, name)
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self._send(404, "not found", "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    # ------------------------------------------------------------------- SSE

    def _serve_events(self, code):
        session = STORE.get(code)
        if session is None:
            return self._send(404, {"error": "no such session"})

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        # No Content-Length and no chunking, so the body runs until we close.
        self.send_header("Connection", "close")
        self.end_headers()

        q = session.subscribe()
        try:
            self._write_event(json.dumps({**session.state(), **self._env()}))
            while True:
                try:
                    payload = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")   # keep proxies and tabs awake
                    self.wfile.flush()
                    continue
                board = json.dumps({**json.loads(payload), **self._env()})
                self._write_event(board)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            session.unsubscribe(q)

    def _write_event(self, payload):
        self.wfile.write(b"data: " + payload.encode() + b"\n\n")
        self.wfile.flush()


def serve(port=8080):
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="web")
    thread.start()
    return httpd
