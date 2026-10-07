# -*- coding: utf-8 -*-
"""L2 tests: the EARTH_MODEL client against a local stub. No key, no Rhino.

Targets `request_model_with_token` (explicit token) rather than the blocking
`request_model` wrapper, so nothing here touches real auth.

Run:
    python -m pytest DarkSide/tests/get_earth/test_earth_model_client.py -q
"""

import os
import sys
import hashlib

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "..", "Apps", "lib")))
sys.path.insert(0, _HERE)

from EnneadTab import EARTH_MODEL as EM   # noqa: E402
from EnneadTab.AI import _common          # noqa: E402
import stub_server                        # noqa: E402


LAT, LON, SIZE = 40.7484, -73.9857, 500.0
TOKEN = "test-token-not-a-real-secret"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Never let a test write into the real EnneadTab dump folder."""
    monkeypatch.setattr(EM, "cache_dir", lambda: str(tmp_path))
    stub_server.SCENARIO = "ok"
    stub_server.requests_seen[:] = []
    yield


@pytest.fixture
def stub(monkeypatch):
    with stub_server.StubServer() as url:
        monkeypatch.setenv(EM.EARTH_MODEL_URL_ENV_VAR, url)
        yield url


# --- contract ---------------------------------------------------------------

def test_env_override_redirects_the_endpoint(stub):
    assert EM.get_base_url() == stub
    assert EM.model_endpoint().startswith(stub)
    assert EM.model_endpoint().endswith("/api/v1/model")


def test_happy_path_downloads_and_verifies(stub):
    path = EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    assert os.path.exists(path)
    assert path.endswith(".glb")
    assert EM.sha256_of_file(path) == stub_server.BLOB_SHA


def test_request_carries_the_aoi_and_the_bearer_token(stub):
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    seen = stub_server.requests_seen[-1]
    assert seen["payload"]["lat"] == pytest.approx(LAT)
    assert seen["payload"]["lon"] == pytest.approx(LON)
    assert seen["payload"]["size_m"] == pytest.approx(SIZE)
    assert seen["payload"]["format"] == "glb"
    assert TOKEN in (seen["authorization"] or "")


def test_source_is_forwarded_only_when_asked(stub):
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    assert "source" not in stub_server.requests_seen[-1]["payload"]
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE, source="osm3dep", force=True)
    assert stub_server.requests_seen[-1]["payload"]["source"] == "osm3dep"


def test_rotation_is_forwarded_only_when_asked(stub):
    """#4857: rotation_deg is additive on the wire, same pattern as `source`
    just above -- a plain request must look byte-for-byte like it did before
    this parameter existed."""
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    assert "rotation_deg" not in stub_server.requests_seen[-1]["payload"]
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE, rotation_deg=29, force=True)
    assert stub_server.requests_seen[-1]["payload"]["rotation_deg"] == pytest.approx(29.0)


# --- cache ------------------------------------------------------------------

def test_second_call_is_served_from_cache_without_hitting_the_server(stub):
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    assert len(stub_server.requests_seen) == 1
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    assert len(stub_server.requests_seen) == 1, "cache hit should not re-request"


def test_force_bypasses_the_cache(stub):
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE, force=True)
    assert len(stub_server.requests_seen) == 2


def test_different_aoi_is_a_different_cache_entry():
    a = EM.cache_key(LAT, LON, SIZE)
    assert a != EM.cache_key(LAT, LON, 1000.0)
    assert a != EM.cache_key(LAT + 0.01, LON, SIZE)
    assert a != EM.cache_key(LAT, LON, SIZE, fmt="obj")


def test_negligible_coordinate_jitter_reuses_one_cache_entry():
    # Sub-0.1 m differences must not re-bill a fresh server-side merge.
    assert EM.cache_key(LAT, LON, SIZE) == EM.cache_key(LAT + 1e-9, LON, SIZE)


# --- rotation (#4857) --------------------------------------------------------

def test_zero_rotation_cache_key_is_byte_identical_to_pre_rotation():
    """The one invariant that matters most: a local cache built before
    rotation_deg existed must stay a hit after this ships. Pinned against the
    same hash DarkSide/tests/get_earth/rhino_l3_aoi_ironpython.py hardcodes
    for the cross-runtime (IronPython vs CPython) agreement check -- if this
    ever drifts, that live-Rhino test is the other place it would be caught."""
    assert EM.cache_key(40.7484, -73.9857, 500.0) == "f1873085255f7559"
    assert EM.cache_key(40.7484, -73.9857, 500.0, rotation_deg=0) == "f1873085255f7559"


def test_rotated_aoi_is_a_different_cache_entry():
    a = EM.cache_key(LAT, LON, SIZE)
    assert a != EM.cache_key(LAT, LON, SIZE, rotation_deg=29)
    assert EM.cache_key(LAT, LON, SIZE, rotation_deg=29) != EM.cache_key(LAT, LON, SIZE, rotation_deg=90)


def test_rotation_travels_from_request_into_a_distinct_cache_file(stub):
    unrotated = EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    rotated = EM.request_model_with_token(TOKEN, LAT, LON, SIZE, rotation_deg=29)
    assert unrotated != rotated
    assert len(stub_server.requests_seen) == 2, "a different rotation must not be served from the other's cache"


def test_serve_stale_offline_fallback_respects_rotation(stub, monkeypatch):
    """_serve_stale must look up the SAME rotation-aware path
    request_model_with_token wrote to, or an offline fallback would silently
    serve the wrong (unrotated) mesh for a rotated request. Only the rotated
    AOI is ever downloaded here -- the offline lookup for the UNROTATED one
    must come back empty, not fall back to the rotated file that happens to
    share a lat/lon/size."""
    rotated_path = EM.request_model_with_token(TOKEN, LAT, LON, SIZE, rotation_deg=29)
    assert os.path.exists(rotated_path)

    monkeypatch.setenv(EM.EARTH_MODEL_URL_ENV_VAR, "http://127.0.0.1:9")
    assert EM._serve_stale(LAT, LON, SIZE, EM.FORMAT_GLB, 29) == rotated_path
    assert EM._serve_stale(LAT, LON, SIZE, EM.FORMAT_GLB) is None


# --- failure matrix ---------------------------------------------------------

def test_corrupt_sha_is_rejected_and_leaves_no_file(stub):
    stub_server.SCENARIO = "corrupt_sha"
    with pytest.raises(EM.EarthModelError) as e:
        EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    assert "Integrity check failed" in str(e.value)
    assert not os.path.exists(EM.cached_path(LAT, LON, SIZE))


def test_empty_body_is_rejected(stub):
    stub_server.SCENARIO = "empty_blob"
    with pytest.raises(EM.EarthModelError) as e:
        EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    assert "empty" in str(e.value).lower()


def test_server_error_field_surfaces_its_message(stub):
    stub_server.SCENARIO = "error_field"
    with pytest.raises(EM.EarthModelError) as e:
        EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    assert "AOI too large" in str(e.value)


def test_missing_model_url_is_a_clear_error(stub):
    stub_server.SCENARIO = "no_url"
    with pytest.raises(EM.EarthModelError) as e:
        EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    assert "model_url" in str(e.value)


def test_malformed_json_surfaces_as_a_transport_error_not_a_raw_traceback(stub):
    """A non-JSON body fails to decode INSIDE _common, so it arrives as
    AIRequestError rather than EarthModelError. That is the real architecture --
    the client must not re-decode what _common already parsed. Asserting the
    wrong exception here would have hidden a double-decode bug in the client."""
    stub_server.SCENARIO = "malformed"
    with pytest.raises(_common.AIRequestError):
        EM.request_model_with_token(TOKEN, LAT, LON, SIZE)


def test_no_partial_file_is_left_behind_on_failure(stub):
    stub_server.SCENARIO = "corrupt_sha"
    with pytest.raises(EM.EarthModelError):
        EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    dest = EM.cached_path(LAT, LON, SIZE)
    assert not os.path.exists(dest + ".part"), "temp file must not survive"


# --- offline ----------------------------------------------------------------

def test_stale_cache_is_served_when_the_service_is_unreachable(stub, monkeypatch, tmp_path):
    path = EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    assert os.path.exists(path)
    # 127.0.0.1:9 is guaranteed connection-refused -- the depot's own trick for
    # forcing "offline" without unplugging anything.
    monkeypatch.setenv(EM.EARTH_MODEL_URL_ENV_VAR, "http://127.0.0.1:9")
    assert EM._serve_stale(LAT, LON, SIZE, EM.FORMAT_GLB) == path


def test_offline_with_no_cache_returns_none(monkeypatch):
    monkeypatch.setenv(EM.EARTH_MODEL_URL_ENV_VAR, "http://127.0.0.1:9")
    assert EM._serve_stale(51.5, -0.12, 400.0, EM.FORMAT_GLB) is None


# --- integrity helper -------------------------------------------------------

def test_sha256_of_file_matches_hashlib(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello earth model")
    assert EM.sha256_of_file(str(p)) == hashlib.sha256(b"hello earth model").hexdigest()
