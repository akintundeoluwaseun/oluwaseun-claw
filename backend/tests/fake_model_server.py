"""TEST DOUBLE — a tiny HTTP server that imitates the Ollama and llama-server APIs.

It is used ONLY by automated tests because this development workspace cannot
download real model weights. It returns scripted replies; it is not a model
and is never used by the application itself.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeModelServer:
    def __init__(self, models: list[str] | None = None):
        self.models = models if models is not None else ["qwen2.5:7b"]
        self.replies: deque[str] = deque()
        self.requests: list[dict] = []
        self.status_override: int | None = None
        self.default_reply = "{}"
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):  # silence
                pass

            def _send(self, code: int, payload: object):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._send(200, {"models": [{"name": m, "size": 123, "details": {}} for m in server.models]})
                elif self.path == "/v1/models":
                    self._send(200, {"object": "list", "data": [{"id": m} for m in server.models]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                server.requests.append({"path": self.path, "body": body})
                if server.status_override:
                    self._send(server.status_override, {"error": "scripted failure"})
                    return
                if body.get("model") not in server.models:
                    self._send(404, {"error": f"model '{body.get('model')}' not found"})
                    return
                reply = server.replies.popleft() if server.replies else server.default_reply
                if self.path == "/api/chat":
                    self._send(200, {"model": body["model"], "message": {"role": "assistant", "content": reply}, "done": True})
                elif self.path == "/v1/chat/completions":
                    self._send(200, {"choices": [{"index": 0, "message": {"role": "assistant", "content": reply}}]})
                else:
                    self._send(404, {"error": "not found"})

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
