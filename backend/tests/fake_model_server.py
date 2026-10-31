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
        # What /props reports as the context in force; None serves a 404,
        # the way a hosted provider without that route does.
        self.n_ctx: int | None = 8192
        # Downloads (/api/pull): which tags exist in the "library" (None = any), and pacing.
        self.library: set[str] | None = None
        self.pull_steps = 4
        self.pull_delay = 0.0
        self.pulls: list[str] = []
        self.unloads: list[str] = []
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
                if server.status_override:  # tests that need a 401/429 from the listing
                    return self._send(server.status_override, {"error": {"message": "refused"}})
                if self.path == "/api/tags":
                    self._send(200, {"models": [{"name": m, "size": 123, "details": {}} for m in server.models]})
                elif self.path == "/v1/models":
                    self._send(200, {"object": "list", "data": [{"id": m} for m in server.models]})
                elif self.path == "/props":
                    # llama-server reports the context actually in force here, which
                    # is not always the one -c asked for. None = a provider that
                    # does not offer this route at all.
                    if server.n_ctx is None:
                        self._send(404, {"error": "not found"})
                    else:
                        self._send(200, {"default_generation_settings": {"n_ctx": server.n_ctx}})
                else:
                    self._send(404, {"error": "not found"})

            def _pull(self, tag: str):
                import time as _t

                server.pulls.append(tag)
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()

                def line(obj):
                    self.wfile.write((json.dumps(obj) + "\n").encode())
                    self.wfile.flush()

                line({"status": "pulling manifest"})
                if server.library is not None and tag not in server.library:
                    line({"error": "pull model manifest: file does not exist"})
                    return
                total = 1000
                for i in range(1, server.pull_steps + 1):
                    _t.sleep(server.pull_delay)
                    line({"status": f"pulling {tag}", "digest": "sha256:x", "total": total, "completed": total * i // server.pull_steps})
                line({"status": "success"})
                if tag not in server.models:
                    server.models.append(tag)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/pull":
                    self._pull(body.get("model", ""))
                    return
                if self.path == "/api/chat" and body.get("keep_alive") == 0 and not body.get("messages"):
                    server.unloads.append(body.get("model"))
                    self._send(200, {"model": body.get("model"), "done": True, "done_reason": "unload"})
                    return
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
