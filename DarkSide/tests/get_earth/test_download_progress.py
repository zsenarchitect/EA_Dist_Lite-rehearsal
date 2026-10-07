# -*- coding: utf-8 -*-
"""L1/L2 tests for GetEarth's progress UI. No Rhino, no key, no live service.

GetEarth blocks Rhino's main thread for 1-20 seconds and used to say nothing at
all. The fix has three layers, and this file covers each where it can actually
be observed:

  * the TRANSPORT (`_common.download_url_to_file`) now reports bytes as they
    land. Driven here against a FAKE STREAM rather than the stub server,
    because stub_server.BLOB is 1024 bytes -- smaller than one 8192-byte read,
    so a stub-server test would fire exactly ONE callback and would pass
    identically whether the code accumulated bytes or overwrote them. That
    test would be inert. The fake stream forces four reads, and
    `test_progress_is_chunked_monotonic_and_ends_at_the_total` asserts the
    call COUNT so it cannot quietly become inert again later.
  * the CLIENT (`EARTH_MODEL`) plumbs both callbacks through without learning
    anything about Rhino or about designer-facing wording.
  * the METER (`get_earth_utility.RhinoProgressMeter`), driven with a fake
    Rhino module. The invariant worth the most here is that the meter comes
    back DOWN on every exit path, exceptions included -- a meter left standing
    outlives the command and sits in the status bar for the rest of the
    session.

Only the urllib branch of the downloader is reachable from CPython. The .NET
`HttpWebRequest` branch is the one that actually runs inside Rhino and CANNOT
be exercised here; the two are written structurally parallel so that reading
them side by side is worth something, but that is review, not proof.

Run:
    python -m pytest DarkSide/tests/get_earth/test_download_progress.py -q
"""

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(
    os.path.join(_HERE, "..", "..", "..", "Apps", "lib")))
sys.path.insert(0, os.path.abspath(os.path.join(
    _HERE, "..", "..", "..", "Apps", "_rhino", "Render.tab",
    "get_earth.button")))
sys.path.insert(0, _HERE)

from EnneadTab import EARTH_MODEL as EM   # noqa: E402
from EnneadTab.AI import _common          # noqa: E402
import get_earth_utility as U             # noqa: E402
import stub_server                        # noqa: E402


LAT, LON, SIZE = 40.7484, -73.9857, 500.0
TOKEN = "test-token-not-a-real-secret"


# --- fake stream ------------------------------------------------------------

class FakeResponse(object):
    """Stand-in for what urlopen returns: .read(n), .info(), .close().

    A plain dict is a good enough .info(): `_common._header_value` probes for
    .get() before .getheader(), and a dict has .get().
    """

    def __init__(self, payload, send_content_length=True):
        self.payload = payload
        self.closed = False
        self._pos = 0
        self._headers = {}
        if send_content_length:
            self._headers["Content-Length"] = str(len(payload))

    def read(self, n):
        chunk = self.payload[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def info(self):
        return self._headers

    def close(self):
        self.closed = True


@pytest.fixture
def fake_stream(monkeypatch):
    """Serve a payload big enough to need several reads.

    Deliberately NOT a whole number of chunks: the short final read is the
    case that separates an accumulating byte count from an overwriting one.
    """
    payload = os.urandom(3 * _common.DOWNLOAD_CHUNK_BYTES + 137)
    holder = {"payload": payload, "response": None}

    def fake_urlopen(url, timeout=None):
        holder["response"] = FakeResponse(
            holder["payload"], holder.get("send_content_length", True))
        return holder["response"]

    monkeypatch.setattr(_common, "urlopen", fake_urlopen)
    return holder


# --- transport: chunked download + progress ---------------------------------

def test_progress_is_chunked_monotonic_and_ends_at_the_total(fake_stream, tmp_path):
    dest = str(tmp_path / "model.glb")
    calls = []

    _common.download_url_to_file(
        "http://example.invalid/model.glb", dest,
        on_progress=lambda done, total: calls.append((done, total)))

    # Guard against this test going inert. With a payload smaller than one
    # read the assertions below would hold for an overwriting implementation
    # too, and the whole file would stop testing anything.
    assert len(calls) >= 3, "payload must span several reads to be a real test"

    done = [c[0] for c in calls]
    assert all(b > a for a, b in zip(done, done[1:])), \
        "byte counts must accumulate, not restart at each chunk: {}".format(done)
    assert done[0] == _common.DOWNLOAD_CHUNK_BYTES
    assert done[-1] == len(fake_stream["payload"]), \
        "the last event must carry the full size, not stop a chunk short"
    assert all(c[1] == len(fake_stream["payload"]) for c in calls)

    with open(dest, "rb") as f:
        assert f.read() == fake_stream["payload"]


def test_no_callback_leaves_the_download_exactly_as_it_was(fake_stream, tmp_path):
    """The three AI_RENDER callers pass no callback and must be untouched."""
    dest = str(tmp_path / "model.glb")
    assert _common.download_url_to_file(
        "http://example.invalid/model.glb", dest) == dest
    with open(dest, "rb") as f:
        assert f.read() == fake_stream["payload"]
    assert fake_stream["response"].closed


def test_missing_content_length_reports_none_rather_than_guessing(fake_stream, tmp_path):
    """No Content-Length means no total. Inventing one would be a fake bar."""
    fake_stream["send_content_length"] = False
    dest = str(tmp_path / "model.glb")
    calls = []

    _common.download_url_to_file(
        "http://example.invalid/model.glb", dest,
        on_progress=lambda done, total: calls.append((done, total)))

    assert len(calls) >= 3
    assert all(c[1] is None for c in calls)
    assert calls[-1][0] == len(fake_stream["payload"])


def test_a_broken_callback_degrades_the_display_not_the_download(fake_stream, tmp_path, capsys):
    """A fault in the caller's UI must not cost the office a paid-for model."""
    dest = str(tmp_path / "model.glb")
    calls = []

    def exploding(done, total):
        calls.append(done)
        raise RuntimeError("status bar went away")

    _common.download_url_to_file(
        "http://example.invalid/model.glb", dest, on_progress=exploding)

    with open(dest, "rb") as f:
        assert f.read() == fake_stream["payload"]
    # Reporting is switched off after the first fault -- never one printed
    # line per 8 KB chunk for the rest of an 8 MB file.
    assert len(calls) == 1
    assert "progress callback failed" in capsys.readouterr().out


@pytest.mark.parametrize("raw,expected", [
    ("2048", 2048),
    (2048, 2048),
    (None, None),      # urllib: header absent
    (-1, None),        # .NET: HttpWebResponse.ContentLength when absent
    (0, None),
    ("not a number", None),
])
def test_content_length_normalisation_covers_both_runtimes(raw, expected):
    assert _common._content_length_or_none(raw) == expected


# --- client: the callbacks reach EARTH_MODEL --------------------------------

@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(EM, "cache_dir", lambda: str(tmp_path))
    stub_server.SCENARIO = "ok"
    stub_server.requests_seen[:] = []
    yield


@pytest.fixture
def stub(monkeypatch):
    with stub_server.StubServer() as url:
        monkeypatch.setenv(EM.EARTH_MODEL_URL_ENV_VAR, url)
        yield url


def test_on_response_fires_once_between_generation_and_download(stub):
    seen = []
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE,
                                on_response=lambda data: seen.append(data))
    assert len(seen) == 1
    assert seen[0]["model_url"].endswith("/blob/model.glb")


def test_on_progress_reaches_the_transport_through_the_client(stub):
    calls = []
    EM.request_model_with_token(
        TOKEN, LAT, LON, SIZE,
        on_progress=lambda done, total: calls.append((done, total)))
    assert calls, "the client must plumb on_progress down to the downloader"
    assert calls[-1][0] == len(stub_server.BLOB)


def test_a_broken_on_response_does_not_lose_the_model(stub, capsys):
    def exploding(data):
        raise RuntimeError("meter went away")
    path = EM.request_model_with_token(TOKEN, LAT, LON, SIZE,
                                       on_response=exploding)
    assert os.path.exists(path)
    assert "response callback failed" in capsys.readouterr().out


def test_on_response_does_not_fire_on_a_cache_hit(stub):
    """Nothing was generated and nothing downloaded, so there is no phase
    transition to announce."""
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE)
    seen = []
    EM.request_model_with_token(TOKEN, LAT, LON, SIZE,
                                on_response=lambda data: seen.append(data))
    assert seen == []


# --- pure display logic -----------------------------------------------------

@pytest.mark.parametrize("num,expected", [
    (0, "0 B"),
    (512, "512 B"),
    (8192, "8 KB"),
    (8 * 1024 * 1024, "8.0 MB"),
])
def test_format_bytes(num, expected):
    assert U.format_bytes(num) == expected


def test_generation_status_names_a_duration_instead_of_a_percentage():
    text = U.generation_status(500)
    assert "500" in text
    assert "5-20 seconds" in text
    assert "%" not in text, "the generation phase has no measurable progress"


def test_download_status_promises_no_size_it_cannot_know_yet():
    """It fires on the POST's answer; the GLB's Content-Length arrives with
    the separate GET, one phase later."""
    text = U.download_status()
    assert "%" not in text
    assert "MB" not in text


def test_download_label_omits_the_percentage_when_there_is_no_total():
    assert "/" not in U.download_label(1024, None)
    assert "1.0 MB" in U.download_label(1024 * 1024, 4 * 1024 * 1024)


def test_progress_percent_is_none_without_a_total_and_clamped_with_one():
    assert U.progress_percent(500, None) is None
    assert U.progress_percent(0, 100) == 0.0
    assert U.progress_percent(50, 100) == 50.0
    # A short Content-Length must not drive the meter past its upper limit.
    assert U.progress_percent(300, 100) == 100.0


def test_should_redraw_always_paints_the_first_and_last_event():
    total = 8 * 1024 * 1024
    assert U.should_redraw(None, 8192, total) is True
    assert U.should_redraw(total - 1, total, total) is True


def test_should_redraw_throttles_the_middle():
    total = 8 * 1024 * 1024
    step = total * U.PROGRESS_PERCENT_STEP / 100.0
    assert U.should_redraw(1000, 1000 + int(step) - 1, total) is False
    assert U.should_redraw(1000, 1000 + int(step) + 1, total) is True


def test_should_redraw_falls_back_to_a_byte_cadence_with_no_total():
    assert U.should_redraw(0, U.PROGRESS_BYTE_STEP - 1, None) is False
    assert U.should_redraw(0, U.PROGRESS_BYTE_STEP, None) is True


def test_completion_note_reads_the_optional_fields_but_never_requires_them():
    # An older service sends neither field. Say nothing rather than "$None".
    assert U.completion_note({"model_url": "x"}) == ""
    assert U.completion_note(None) == ""
    assert "cost nothing" in U.completion_note({"cache_hit": True, "cost_usd": 0})
    assert "$0.030" in U.completion_note({"cache_hit": False, "cost_usd": 0.03})
    assert U.completion_note({"cost_usd": "unknowable"}) == ""


# --- the meter --------------------------------------------------------------

class FakeStatusBar(object):
    def __init__(self, log, explode=False):
        self.log = log
        self.explode = explode

    def ShowProgressMeter(self, lower, upper, label, embed_label, show_percent):
        if self.explode:
            raise TypeError("no overload matches")
        self.log.append(("show", lower, upper, label, embed_label, show_percent))
        return 1

    def UpdateProgressMeter(self, value, absolute):
        self.log.append(("update", value, absolute))

    def HideProgressMeter(self):
        self.log.append(("hide",))


class FakeRhinoApp(object):
    def __init__(self, log):
        self.log = log

    def SetCommandPromptMessage(self, text):
        self.log.append(("prompt", text))

    def Wait(self):
        self.log.append(("wait",))


class FakeRhino(object):
    """Everything RhinoProgressMeter touches: Rhino.UI.StatusBar and
    Rhino.RhinoApp. Injected via `rhino_module=`, which is the whole reason
    the meter takes that argument."""

    def __init__(self, explode=False):
        self.log = []
        self.UI = type("UI", (object,), {})()
        self.UI.StatusBar = FakeStatusBar(self.log, explode=explode)
        self.RhinoApp = FakeRhinoApp(self.log)

    def kinds(self):
        return [entry[0] for entry in self.log]


def test_meter_is_taken_down_on_a_normal_exit():
    rhino = FakeRhino()
    with U.RhinoProgressMeter(rhino_module=rhino) as meter:
        meter.report(4096, 8192)
    assert "show" in rhino.kinds()
    assert rhino.kinds()[-2:] == ["hide", "prompt"]


def test_meter_is_taken_down_when_the_body_raises():
    """The bug this class exists to prevent: a meter that outlives the command
    and stays in the status bar until Rhino is restarted."""
    rhino = FakeRhino()
    with pytest.raises(ValueError):
        with U.RhinoProgressMeter(rhino_module=rhino) as meter:
            meter.report(4096, 8192)
            raise ValueError("import blew up")
    assert "hide" in rhino.kinds(), "a raised body must still hide the meter"


def test_a_status_only_run_still_clears_the_command_prompt():
    """The generation phase never shows a bar, but it does leave text behind."""
    rhino = FakeRhino()
    with U.RhinoProgressMeter(rhino_module=rhino) as meter:
        meter.set_status("building...")
    assert "show" not in rhino.kinds()
    assert rhino.log[-1] == ("prompt", "")


def test_hide_is_idempotent():
    rhino = FakeRhino()
    meter = U.RhinoProgressMeter(rhino_module=rhino)
    meter.report(4096, 8192)
    meter.hide()
    meter.hide()
    assert rhino.kinds().count("hide") == 1


def test_every_repaint_pumps_the_message_loop():
    """Rhino repaints nothing while the main thread is blocked, so a bar drawn
    without a Wait() is drawn once and then frozen."""
    rhino = FakeRhino()
    meter = U.RhinoProgressMeter(rhino_module=rhino)
    total = 1000000
    for done in range(0, total + 1, 10000):
        meter.report(done, total)
    updates = [e for e in rhino.log if e[0] == "update"]
    waits = [e for e in rhino.log if e[0] == "wait"]
    assert len(waits) >= len(updates)


def test_percentages_climb_and_reach_a_hundred():
    rhino = FakeRhino()
    meter = U.RhinoProgressMeter(rhino_module=rhino)
    total = 1000000
    for done in range(0, total + 1, 4096):
        meter.report(done, total)
    meter.report(total, total)
    values = [e[1] for e in rhino.log if e[0] == "update"]
    assert values == sorted(values)
    assert values[-1] == 100


def test_no_bar_is_drawn_when_the_size_is_unknown():
    """No total, no percentage -- the same honesty as the generation phase."""
    rhino = FakeRhino()
    meter = U.RhinoProgressMeter(rhino_module=rhino)
    meter.report(U.PROGRESS_BYTE_STEP, None)
    meter.report(3 * U.PROGRESS_BYTE_STEP, None)
    assert "show" not in rhino.kinds()
    assert "update" not in rhino.kinds()
    assert ("prompt", U.download_label(3 * U.PROGRESS_BYTE_STEP, None)) in rhino.log


def test_a_rhino_that_refuses_degrades_to_no_meter_not_to_a_dead_button(capsys):
    """An overload-resolution surprise inside Rhino must cost the display and
    nothing else, and must say so to the operator exactly once."""
    rhino = FakeRhino(explode=True)
    with U.RhinoProgressMeter(rhino_module=rhino) as meter:
        for done in range(0, 1000001, 100000):
            meter.report(done, 1000000)
    out = capsys.readouterr().out
    assert out.count("progress display unavailable") == 1
    assert "update" not in rhino.kinds()
