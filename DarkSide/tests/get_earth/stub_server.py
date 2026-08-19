# -*- coding: utf-8 -*-
"""L2 stub of the EnneadTab-EarthModel service.

Speaks the real contract and serves canned GLB bytes, so the whole client path --
POST, JSON parse, download, sha256 verification, atomic write, cache reuse,
offline degradation -- is exercisable with NO Google key and NO live service.

Its real value is the FAILURE MATRIX. Corrupt payloads, empty bodies, 401s, and
malformed JSON are exactly the paths that ship broken because nobody can
reproduce them by hand; here they are one variable away.

CPython 3 only. This is a test tool and never loads inside Rhino, so the
IronPython 2.7 restrictions do not apply.

Standalone:  python stub_server.py 8787
"""

import json
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Scenario switch. Tests set this before issuing a request.
#   ok | corrupt_sha | empty_blob | error_field | no_url | malformed | 401 | 500
SCENARIO = "ok"

# Canned "model" bytes. Not a real GLB -- the client never parses it, it only
# downloads, verifies, and hands a path to Rhino. Import fidelity is proven
# separately by rhino_l3_texture_format.py against a genuine textured glTF.
BLOB = b"GLB-STUB-PAYLOAD" * 64
BLOB_SHA = hashlib.sha256(BLOB).hexdigest()

requests_seen = []


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # keep pytest output readable

    def _send(self, code, body_bytes, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {"_unparsed": raw.decode("utf-8", "replace")}
        requests_seen.append({
            "path": self.path,
            "payload": payload,
            "authorization": self.headers.get("Authorization"),
        })

        if SCENARIO == "401":
            return self._send(401, b'{"error":"unauthorized"}')
        if SCENARIO == "500":
            return self._send(500, b'{"error":"internal"}')
        if SCENARIO == "malformed":
            return self._send(200, b"<html>not json at all</html>", "text/html")
        if SCENARIO == "error_field":
            return self._send(200, json.dumps(
                {"error": "AOI too large: 5000 m exceeds the 2000 m limit"}
            ).encode("utf-8"))
        if SCENARIO == "no_url":
            return self._send(200, json.dumps(
                {"sha256": BLOB_SHA, "format": "glb"}
            ).encode("utf-8"))

        host = self.headers.get("Host") or "127.0.0.1"
        body = {
            "model_url": "http://{}/blob/model.glb".format(host),
            "format": "glb",
            "sha256": ("0" * 64) if SCENARIO == "corrupt_sha" else BLOB_SHA,
            "bounds": {"south": 0.0, "west": 0.0, "north": 0.1, "east": 0.1},
        }
        self._send(200, json.dumps(body).encode("utf-8"))

    def do_GET(self):
        if not self.path.startswith("/blob/"):
            return self._send(404, b'{"error":"not found"}')
        if SCENARIO == "empty_blob":
            return self._send(200, b"", "model/gltf-binary")
        self._send(200, BLOB, "model/gltf-binary")


class StubServer(object):
    """Context manager: `with StubServer() as url:`"""

    def __init__(self, port=0):
        self._httpd = HTTPServer(("127.0.0.1", port), Handler)
        self.port = self._httpd.server_address[1]
        self.url = "http://127.0.0.1:{}".format(self.port)
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._httpd.serve_forever)
        self._thread.daemon = True
        self._thread.start()
        return self.url

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)
        return False


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    with StubServer(port) as url:
        print("earth-model stub on {} (scenario={})".format(url, SCENARIO))
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
