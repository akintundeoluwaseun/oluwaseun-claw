"""TEST DOUBLE — imitates Google's Gemini REST API (models list + generateContent)
as documented, with scripted replies. Used only by tests; it is not Google."""

from __future__ import annotations

import json
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

VALID_KEY = "AIzaTEST-key-0123456789abcdefghijkl"


class FakeGemini:
    def __init__(self):
        self.models = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash-tts", "gemini-embedding-2"]
        self.replies: deque[str] = deque()
        self.default_reply = "{}"
        self.exhausted: set[str] = set()
        self.reject_response_format = False
        self.requests: list[dict] = []
        server = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _send(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authed(self):
                if self.headers.get("x-goog-api-key") != VALID_KEY:
                    self._send(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}})
                    return False
                return True

            def do_GET(self):
                if not self._authed():
                    return
                if urlparse(self.path).path == "/v1beta/models":
                    items = [
                        {"name": f"models/{m}", "supportedGenerationMethods": ["embedContent"] if "embedding" in m else ["generateContent"]}
                        for m in server.models
                    ]
                    self._send(200, {"models": items})
                else:
                    self._send(404, {"error": {"message": "not found"}})

            def do_POST(self):
                if not self._authed():
                    return
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                path = urlparse(self.path).path
                model = path.removeprefix("/v1beta/models/").removesuffix(":generateContent")
                server.requests.append({"model": model, "body": body})
                if model not in server.models:
                    self._send(404, {"error": {"message": f"models/{model} is not found"}})
                    return
                if server.reject_response_format and "responseFormat" in body.get("generationConfig", {}):
                    self._send(400, {"error": {"message": 'Invalid JSON payload received. Unknown name "responseFormat" at \'generation_config\': Cannot find field.'}})
                    return
                if model in server.exhausted:
                    self._send(429, {"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota).", "status": "RESOURCE_EXHAUSTED"}})
                    return
                text = server.replies.popleft() if server.replies else server.default_reply
                self._send(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}]})

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._t = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
