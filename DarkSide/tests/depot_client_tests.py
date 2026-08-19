#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Unit tests for the EnneadTab/DEPOT client (Commit 2).

CPython 3, no host app. Run from the repo root:
    .venv/Scripts/python.exe -m unittest DarkSide.tests.depot_client_tests -v
or:
    PYTHONPATH=Apps/lib python -m unittest DarkSide.tests.depot_client_tests -v

The .NET (IronPython) transport branch is NOT exercised here -- per plan 13 it is
validated on a live Rhino 7 / Revit host. These tests cover the urllib branch,
the cache engine, and the ASSET degradation matrix.
"""

import os
import sys
import socket
import shutil
import tempfile
import unittest

# Make EnneadTab importable and find the stub server next to this file.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "Apps", "lib"))
sys.path.insert(0, _HERE)

from EnneadTab import ENVIRONMENT
from EnneadTab.DEPOT import ROUTES, _transport, _cache, ASSET, STATE, _alarm
import depot_stub_server


def _free_refused_port():
    """A local port with nothing listening -> connect() gets ECONNREFUSED fast."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class DepotTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="depotcache_")
        self._orig_folder = ENVIRONMENT.DEPOT_CACHE_FOLDER
        self._orig_index = ENVIRONMENT.DEPOT_CACHE_INDEX_FILE
        ENVIRONMENT.DEPOT_CACHE_FOLDER = self.tmp
        ENVIRONMENT.DEPOT_CACHE_INDEX_FILE = os.path.join(self.tmp, "cache_index.sexyDuck")
        _alarm._ANNOUNCED_THIS_PROCESS = False
        self._orig_env = os.environ.get("EA_DEPOT_URL")

    def tearDown(self):
        ENVIRONMENT.DEPOT_CACHE_FOLDER = self._orig_folder
        ENVIRONMENT.DEPOT_CACHE_INDEX_FILE = self._orig_index
        if self._orig_env is None:
            os.environ.pop("EA_DEPOT_URL", None)
        else:
            os.environ["EA_DEPOT_URL"] = self._orig_env
        shutil.rmtree(self.tmp, ignore_errors=True)


class CacheTests(DepotTestBase):
    def test_index_roundtrip(self):
        _cache.record("a/b", etag='"e"', sha256="deadbeef", size=10)
        rec = _cache.entry("a/b")
        self.assertEqual(rec["etag"], '"e"')
        self.assertEqual(rec["sha256"], "deadbeef")
        self.assertEqual(rec["size"], 10)
        self.assertIn("last_access", rec)

    def test_corrupt_index_self_heals(self):
        with open(ENVIRONMENT.DEPOT_CACHE_INDEX_FILE, "w") as f:
            f.write("{ this is not json ]")
        self.assertEqual(_cache.read_index(), {})

    def test_sha_verify_detects_tamper(self):
        from EnneadTab import INTEGRITY
        p = _cache.local_path("x/y.txt")
        os.makedirs(os.path.dirname(p))
        with open(p, "wb") as f:
            f.write(b"hello")
        _cache.record("x/y.txt", sha256=INTEGRITY.hash_file(p), size=5)
        self.assertTrue(_cache.has_valid_file("x/y.txt"))
        with open(p, "wb") as f:
            f.write(b"tampered")
        self.assertFalse(_cache.has_valid_file("x/y.txt"))

    def test_lru_prune_evicts_oldest(self):
        import time
        for i, k in enumerate(["k0", "k1", "k2"]):
            p = _cache.local_path(k)
            with open(p, "wb") as f:
                f.write(b"x" * 100)
            _cache.record(k, sha256="s", size=100)
            idx = _cache.read_index()
            idx[k]["last_access"] = 1000 + i   # k0 oldest
            _cache.write_index(idx)
        evicted = _cache.prune_to(150)  # keep ~1 of the 3
        self.assertIn("k0", evicted)          # oldest goes first
        self.assertNotIn("k2", evicted)       # newest survives
        self.assertLessEqual(_cache.total_size(), 150)


class TransportTests(DepotTestBase):
    def setUp(self):
        DepotTestBase.setUp(self)
        self.srv = depot_stub_server.StubDepot({"a.txt": b"hello world"})
        self.srv.start()
        os.environ["EA_DEPOT_URL"] = self.srv.base_url

    def tearDown(self):
        self.srv.stop()
        DepotTestBase.tearDown(self)

    def test_get_200_then_304(self):
        r = _transport.get(ROUTES.asset_url("a.txt"))
        self.assertTrue(r.ok())
        self.assertEqual(r.body, b"hello world")
        self.assertTrue(r.etag)
        r2 = _transport.get(ROUTES.asset_url("a.txt"), if_none_match=r.etag)
        self.assertTrue(r2.not_modified())

    def test_get_404_is_route_offline(self):
        r = _transport.get(ROUTES.asset_url("missing.txt"))
        self.assertEqual(r.status, 404)
        self.assertTrue(_transport.is_route_offline(r))   # C15: whole-route 404 = offline

    def test_offline_transport_failed(self):
        os.environ["EA_DEPOT_URL"] = "http://127.0.0.1:{0}".format(_free_refused_port())
        r = _transport.get(ROUTES.asset_url("a.txt"), timeout_ms=2000)
        self.assertTrue(r.transport_failed)
        self.assertTrue(_transport.is_route_offline(r))


class AssetTests(DepotTestBase):
    def setUp(self):
        DepotTestBase.setUp(self)
        self.body = b"# EA shared params\n"
        self.key = "revit/library/EA_SharedParam.txt"
        self.srv = depot_stub_server.StubDepot({self.key: self.body})
        self.srv.start()
        os.environ["EA_DEPOT_URL"] = self.srv.base_url

    def tearDown(self):
        self.srv.stop()
        DepotTestBase.tearDown(self)

    def test_download_verify_and_serve_cache(self):
        p = ASSET.get_asset_path(self.key)
        self.assertIsNotNone(p)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), self.body)
        # Second call within TTL serves cache -> no new asset request.
        before = self.srv.request_count
        p2 = ASSET.get_asset_path(self.key)
        self.assertEqual(p, p2)
        self.assertEqual(self.srv.request_count, before)  # zero network on the hot path

    def test_manifest_ttl_zero_network(self):
        ASSET.get_manifest()
        before = self.srv.request_count
        ASSET.get_manifest()          # within TTL
        self.assertEqual(self.srv.request_count, before)

    def test_offline_serves_stale(self):
        p = ASSET.get_asset_path(self.key)   # prime cache
        self.assertIsNotNone(p)
        self.srv.stop()                       # go offline
        os.environ["EA_DEPOT_URL"] = "http://127.0.0.1:{0}".format(_free_refused_port())
        p2 = ASSET.get_asset_path(self.key)
        self.assertEqual(p, p2)               # stale copy served, no raise

    def test_offline_no_cache_returns_none_or_raises(self):
        os.environ["EA_DEPOT_URL"] = "http://127.0.0.1:{0}".format(_free_refused_port())
        self.srv.stop()
        self.assertIsNone(ASSET.get_asset_path("never/seen.txt"))
        self.assertRaises(ASSET.DepotAssetError,
                          ASSET.get_asset_path, "never/seen.txt", True)

    def test_sha_mismatch_rejected(self):
        # Manifest advertises the real sha; corrupt the served bytes so the
        # download's sha != manifest sha -> ASSET must not serve garbage.
        self.srv.assets[self.key] = b"corrupted-bytes-different-length"
        # Rebuild manifest is automatic (build_manifest reads assets live), but
        # we want manifest sha to reflect the ORIGINAL, so re-point only the body
        # AFTER manifest is cached:
        ASSET.get_manifest()                              # caches manifest w/ original sha
        self.srv.assets[self.key] = b"corrupted-different"  # body now mismatches manifest sha
        # Force a fresh manifest fetch to keep original sha (already cached, TTL fresh),
        # then request the asset: download body != cached manifest sha -> None.
        p = ASSET.get_asset_path(self.key)
        self.assertIsNone(p)


class StateTests(DepotTestBase):
    def setUp(self):
        DepotTestBase.setUp(self)
        self.srv = depot_stub_server.StubDepot()
        self.srv.start()
        os.environ["EA_DEPOT_URL"] = self.srv.base_url

    def tearDown(self):
        self.srv.stop()
        DepotTestBase.tearDown(self)

    def _offline(self):
        self.srv.stop()
        os.environ["EA_DEPOT_URL"] = "http://127.0.0.1:{0}".format(_free_refused_port())

    def test_write_then_read(self):
        self.assertTrue(STATE.write_state("k1", {"n": 7}))
        self.assertEqual(STATE.read_state("k1"), {"n": 7})

    def test_read_missing_returns_default(self):
        self.assertEqual(STATE.read_state("nope", default={"d": 1}), {"d": 1})

    def test_update_read_modify_write(self):
        STATE.write_state("cnt", {"n": 1})
        ok = STATE.update_state("cnt", lambda d: {"n": (d or {}).get("n", 0) + 1})
        self.assertTrue(ok)
        self.assertEqual(STATE.read_state("cnt"), {"n": 2})

    def test_update_reapplies_on_409(self):
        self.srv.state["cnt"] = {"rev": 5, "data": {"n": 1}}
        self.srv.conflict_once = True   # first PUT 409s with the winning doc
        ok = STATE.update_state("cnt", lambda d: {"n": (d or {}).get("n", 0) + 1})
        self.assertTrue(ok)                       # succeeded after re-apply
        self.assertEqual(self.srv.state["cnt"]["data"], {"n": 2})

    def test_offline_write_queues_then_flushes(self):
        self._offline()
        self.assertFalse(STATE.write_state("q1", {"v": "x"}))   # queued, not sent
        self.assertEqual(STATE._outbox_count(), 1)
        # Reconnect and flush.
        self.srv.start()
        os.environ["EA_DEPOT_URL"] = self.srv.base_url
        flushed, remaining = STATE.flush_outbox()
        self.assertEqual((flushed, remaining), (1, 0))
        self.assertEqual(self.srv.state["q1"]["data"], {"v": "x"})

    def test_list_state_by_prefix(self):
        STATE.write_state("proj/2334", {"a": 1})
        STATE.write_state("proj/2538", {"a": 2})
        STATE.write_state("other/x", {"a": 3})
        keys = STATE.list_state("proj/")
        self.assertEqual(sorted(keys), ["proj/2334", "proj/2538"])
        self.assertEqual(STATE.list_state("nomatch/"), [])

    def test_list_state_offline_empty(self):
        self._offline()
        self.assertEqual(STATE.list_state("proj/"), [])

    def test_offline_read_serves_stale(self):
        STATE.write_state("s1", {"v": 1})     # cache it
        self.assertEqual(STATE.read_state("s1"), {"v": 1})
        self._offline()
        stale = STATE.read_state("s1")
        self.assertEqual(stale.get("v"), 1)
        self.assertTrue(stale.get("_depot_stale"))   # annotated, not silent


class DataFileSeamTests(DepotTestBase):
    """Prove the DATA_FILE(is_local=False) seam holds after the Commit-3 rewrite
    (plan 13): the ~34 untouched call sites go through DEPOT.STATE now."""
    def setUp(self):
        DepotTestBase.setUp(self)
        self.srv = depot_stub_server.StubDepot()
        self.srv.start()
        os.environ["EA_DEPOT_URL"] = self.srv.base_url

    def tearDown(self):
        self.srv.stop()
        DepotTestBase.tearDown(self)

    def test_shared_round_trip(self):
        from EnneadTab import DATA_FILE
        DATA_FILE.set_data({"proj": "2334", "count": 3}, "SEAM_TEST", is_local=False)
        got = DATA_FILE.get_data("SEAM_TEST", is_local=False)
        self.assertEqual(got, {"proj": "2334", "count": 3})

    def test_state_key_strips_extension(self):
        from EnneadTab import DATA_FILE
        self.assertEqual(DATA_FILE._shared_state_key("FOO.sexyDuck"), "FOO")
        self.assertEqual(DATA_FILE._shared_state_key("bar/BAZ.json"), "BAZ")
        self.assertEqual(DATA_FILE._shared_state_key("PLAIN"), "PLAIN")


class SharePointTests(DepotTestBase):
    """§5.5 per-user SharePoint project-file resolver (D4)."""
    def setUp(self):
        DepotTestBase.setUp(self)
        from EnneadTab import SHAREPOINT
        self.SP = SHAREPOINT
        self._orig_cfg = ENVIRONMENT.USER_SHAREPOINT_ROOT_CONFIG
        ENVIRONMENT.USER_SHAREPOINT_ROOT_CONFIG = os.path.join(self.tmp, "sharepoint_root.json")

    def tearDown(self):
        ENVIRONMENT.USER_SHAREPOINT_ROOT_CONFIG = self._orig_cfg
        DepotTestBase.tearDown(self)

    def test_set_then_resolve(self):
        root = os.path.join(self.tmp, "SPRoot")
        os.makedirs(root)
        self.assertTrue(self.SP.set_project_root(root))
        self.assertEqual(self.SP.get_project_root(prompt_if_missing=False), root)

    def test_get_project_file_joins(self):
        root = os.path.join(self.tmp, "SPRoot")
        os.makedirs(root)
        self.SP.set_project_root(root)
        p = self.SP.get_project_file("2534/Model/x.xlsx", prompt_if_missing=False)
        self.assertEqual(p, os.path.join(root, "2534", "Model", "x.xlsx"))

    def test_unset_returns_none_no_prompt(self):
        self.assertIsNone(self.SP.get_project_root(prompt_if_missing=False))
        self.assertIsNone(self.SP.get_project_file("a/b", prompt_if_missing=False))

    def test_required_raises_when_unset(self):
        self.assertRaises(self.SP.ProjectRootNotSet,
                          self.SP.get_project_file, "a/b", True, False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
