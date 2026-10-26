"""TEST DOUBLE — imitates the parts of Hugging Face's public API Claw uses:
GET /api/models/{repo}?blobs=true and GET /{repo}/resolve/main/{file} (with Range).
Serves files given by the test. It is not Hugging Face."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse


class FakeHub:
    def __init__(self):
        self.repos: dict[str, dict] = {}  # repo -> {"license": str, "files": {name: bytes}, "sha_override": {name: sha}}
        self.requests: list[str] = []
        self.chunk_delay = 0.0
        hub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                url = urlparse(self.path)
                hub.requests.append(url.path)
                if url.path.startswith("/api/models/"):
                    repo = url.path[len("/api/models/"):]
                    r = hub.repos.get(repo)
                    if r is None:
                        return self._json(404, {"error": "Repository not found"})
                    sib = []
                    for name, data in r["files"].items():
                        sha = r.get("sha_override", {}).get(name, hashlib.sha256(data).hexdigest())
                        sib.append({"rfilename": name, "size": len(data), "lfs": {"sha256": sha, "size": len(data)}})
                    sib.append({"rfilename": "README.md", "size": 10})
                    return self._json(200, {"id": repo, "cardData": {"license": r["license"]}, "tags": [f"license:{r['license']}"], "siblings": sib})
                if "/resolve/main/" in url.path:
                    repo, name = url.path.lstrip("/").split("/resolve/main/", 1)
                    data = hub.repos.get(repo, {}).get("files", {}).get(unquote(name))
                    if data is None:
                        return self._json(404, {"error": "not found"})
                    start = 0
                    rng = self.headers.get("Range")
                    if rng and rng.startswith("bytes="):
                        start = int(rng[6:].split("-")[0])
                        if start >= len(data):
                            self.send_response(416)
                            self.end_headers()
                            return
                        self.send_response(206)
                    else:
                        self.send_response(200)
                    body = data[start:]
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    import time
                    for i in range(0, len(body), 65536):
                        if hub.chunk_delay:
                            time.sleep(hub.chunk_delay)
                        try:
                            self.wfile.write(body[i:i + 65536])
                        except (BrokenPipeError, ConnectionResetError):
                            return
                    return
                self._json(404, {"error": "not found"})

            def _json(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base_url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._t = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *e):
        self._httpd.shutdown()
        self._httpd.server_close()
