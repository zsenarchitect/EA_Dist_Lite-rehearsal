#!/usr/bin/python
# -*- coding: utf-8 -*-
"""A tiny in-process depot server for testing the EnneadTab/DEPOT client.

CPython 3 only (test harness). Serves a fixture manifest and asset bytes,
honors If-None-Match -> 304, and can be forced to return 401/409/500 so the
client's degradation paths can be exercised without a real server.

Usage:
    srv = StubDepot({"revit/library/EA_SharedParam.txt": b"# params\n"})
    srv.start()
    os.environ["EA_DEPOT_URL"] = srv.base_url    # ROUTES reads this
    ... exercise DEPOT.ASSET ...
    srv.stop()
"""

import hashlib
import json
import threading

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs, unquote
except ImportError:  # pragma: no cover -- Py2 fallback, tests run on Py3
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from urlparse import urlparse, parse_qs
    from urllib import unquote


def _sha256(b):
    return hashlib.sha256(b).hexdigest()


def _etag(b):
    return '"' + _sha256(b)[:16] + '"'


class StubDepot(object):
    """Fixture depot. `assets` maps key -> bytes."""

    def __init__(self, assets=None, folders=None, state=None):
        self.assets = dict(assets or {})
        self.folders = dict(folders or {})
        # state: key -> {"rev": int, "data": obj}
        self.state = dict(state or {})
        self.force_status = None      # set to 401/409/500 to force that on every call
        self.conflict_once = False    # force ONE 409 on the next state PUT
        self.request_count = 0        # observe zero-network (TTL) behavior
        self._server = None
        self._thread = None
        self.port = None

    # --- lifecycle ---
    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass  # quiet

            def _send(self, code, body=None, headers=None):
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                if body is not None:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body is not None:
                    self.wfile.write(body)

            def do_GET(self):
                outer.request_count += 1
                if outer.force_status:
                    self._send(outer.force_status, b'{"ok":false,"error":"forced"}')
                    return
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/api/manifest":
                    outer._manifest(self)
                elif path.startswith("/api/asset/"):
                    key = unquote(path[len("/api/asset/"):])
                    outer._asset(self, key)
                elif path == "/api/state":
                    q = parse_qs(parsed.query)
                    prefix = (q.get("prefix") or [""])[0]
                    outer._state_list(self, prefix)
                elif path.startswith("/api/state/"):
                    key = unquote(path[len("/api/state/"):])
                    outer._state_get(self, key)
                else:
                    self._send(404, b'{"ok":false,"error":"not_found"}')

            def do_PUT(self):
                outer.request_count += 1
                if outer.force_status:
                    self._send(outer.force_status, b'{"ok":false,"error":"forced"}')
                    return
                parsed = urlparse(self.path)
                path = parsed.path
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                if path.startswith("/api/state/"):
                    key = unquote(path[len("/api/state/"):])
                    outer._state_put(self, key, raw)
                else:
                    self._send(404, b'{"ok":false,"error":"not_found"}')

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever)
        self._thread.daemon = True
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def base_url(self):
        return "http://127.0.0.1:{0}".format(self.port)

    # --- responses ---
    def build_manifest(self):
        assets = {}
        for key, body in self.assets.items():
            assets[key] = {"sha256": _sha256(body), "etag": _etag(body), "size": len(body)}
        return {"channel": "prod", "assets": assets, "folders": self.folders}

    def _manifest(self, handler):
        body = json.dumps(self.build_manifest()).encode("utf-8")
        etag = _etag(body)
        inm = handler.headers.get("If-None-Match")
        if inm and inm == etag:
            handler._send(304, None, {"ETag": etag})
            return
        handler._send(200, body, {"ETag": etag, "Content-Type": "application/json"})

    def _asset(self, handler, key):
        if key not in self.assets:
            handler._send(404, b'{"ok":false,"error":"asset_not_found"}')
            return
        body = self.assets[key]
        etag = _etag(body)
        inm = handler.headers.get("If-None-Match")
        if inm and inm == etag:
            handler._send(304, None, {"ETag": etag})
            return
        handler._send(200, body, {"ETag": etag, "X-Depot-Sha256": _sha256(body)})

    # --- state ---
    def _state_list(self, handler, prefix):
        keys = [k for k in self.state.keys() if k.startswith(prefix)]
        out = {"ok": True, "keys": sorted(keys)}
        handler._send(200, json.dumps(out).encode("utf-8"),
                      {"Content-Type": "application/json"})

    def _state_get(self, handler, key):
        doc = self.state.get(key)
        if doc is None:
            handler._send(404, b'{"ok":false,"error":"state_not_found"}')
            return
        rev = doc["rev"]
        etag = '"{0}"'.format(rev)
        inm = handler.headers.get("If-None-Match")
        if inm and inm == etag:
            handler._send(304, None, {"ETag": etag})
            return
        out = {"ok": True, "key": key, "rev": rev, "updated_at": 0,
               "updated_by": "stub", "data": doc["data"]}
        handler._send(200, json.dumps(out).encode("utf-8"),
                      {"ETag": etag, "Content-Type": "application/json"})

    def _state_put(self, handler, key, raw):
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            handler._send(400, b'{"ok":false,"error":"bad_json"}')
            return
        current = self.state.get(key)
        body_rev = payload.get("rev")

        def _win():
            cr = current["rev"] if current else 0
            cd = current["data"] if current else None
            return json.dumps({"ok": False, "error": "rev_conflict",
                               "rev": cr, "data": cd}).encode("utf-8")

        if self.conflict_once:
            self.conflict_once = False
            handler._send(409, _win())
            return
        # rev None = unconditional (outbox flush). Otherwise enforce the rev.
        if current is not None and body_rev is not None and body_rev != current["rev"]:
            handler._send(409, _win())
            return
        new_rev = (current["rev"] + 1) if current else 1
        self.state[key] = {"rev": new_rev, "data": payload.get("data")}
        out = {"ok": True, "key": key, "rev": new_rev, "data": payload.get("data")}
        handler._send(200, json.dumps(out).encode("utf-8"),
                      {"Content-Type": "application/json"})
