# -*- coding: utf-8 -*-
"""GetEarth AOI math -- pure geometry, no Rhino dependency.

DELIBERATELY IMPORT-FREE OF RHINO. Every function here is testable under plain
CPython, which is what keeps the GetEarth test suite in the ~1s "L1" layer
instead of the ~15s "drive a live Rhino" layer. Any function that needs
rhinoscriptsyntax or Rhino imports it INSIDE the function body, never at module
top level. See docs/plans/2026-08-05-getearth-dev-mode-automation.md section 3.

IronPython 2.7 constraints apply (this loads inside Rhino): no f-strings, no type
hints, no pathlib.

Unit handling is a correctness requirement, not a nicety: Rhino's default
template is MILLIMETRES, so a 500 m AOI is 500,000 model units. A missing
conversion is a 1000x error, not a rounding error.
"""

import math
import re


# --- Unit conversion --------------------------------------------------------

# Rhino unit system names (rs.UnitSystemName()) -> metres per model unit.
_UNIT_TO_METERS = {
    "microns": 1.0e-6,
    "millimeter": 0.001,
    "millimeters": 0.001,
    "centimeter": 0.01,
    "centimeters": 0.01,
    "decimeter": 0.1,
    "decimeters": 0.1,
    "meter": 1.0,
    "meters": 1.0,
    "kilometer": 1000.0,
    "kilometers": 1000.0,
    "microinches": 2.54e-8,
    "mils": 2.54e-5,
    "inch": 0.0254,
    "inches": 0.0254,
    "foot": 0.3048,
    "feet": 0.3048,
    "yard": 0.9144,
    "yards": 0.9144,
    "mile": 1609.344,
    "miles": 1609.344,
}


def unit_to_meters(unit_name):
    """Metres per one model unit. Raises ValueError on an unknown unit name --
    silently defaulting to 1.0 would produce a 1000x scale error that looks like
    a geometry bug rather than a units bug."""
    if unit_name is None:
        raise ValueError("unit_name is None")
    key = str(unit_name).strip().lower()
    if key not in _UNIT_TO_METERS:
        raise ValueError("unknown Rhino unit system: %s" % unit_name)
    return _UNIT_TO_METERS[key]


def meters_to_model(length_m, unit_name):
    """Convert a real-world length in metres into model units."""
    return float(length_m) / unit_to_meters(unit_name)


def model_to_meters(length_model, unit_name):
    """Convert a model-unit length into real-world metres."""
    return float(length_model) * unit_to_meters(unit_name)


# --- Geodesy ----------------------------------------------------------------

def meters_per_degree(lat_deg):
    """Metres per degree of latitude and of longitude at a given latitude.

    Standard WGS84 series approximation. Accurate to well under a metre at
    site scale, which is far tighter than photogrammetric context needs, and it
    correctly collapses longitude spacing toward the poles -- a flat 111320
    constant would stretch a Helsinki site sideways by ~half.
    """
    lat = math.radians(_validate_lat(lat_deg))
    m_per_deg_lat = (111132.92
                     - 559.82 * math.cos(2 * lat)
                     + 1.175 * math.cos(4 * lat)
                     - 0.0023 * math.cos(6 * lat))
    m_per_deg_lon = (111412.84 * math.cos(lat)
                     - 93.5 * math.cos(3 * lat)
                     + 0.118 * math.cos(5 * lat))
    return (m_per_deg_lat, m_per_deg_lon)


def normalize_lon(lon_deg):
    """Wrap a longitude into [-180, 180). Makes antimeridian arithmetic safe."""
    lon = float(lon_deg)
    while lon >= 180.0:
        lon -= 360.0
    while lon < -180.0:
        lon += 360.0
    return lon


def _validate_lat(lat_deg):
    lat = float(lat_deg)
    if lat < -90.0 or lat > 90.0:
        raise ValueError("latitude out of range: %s" % lat_deg)
    return lat


# --- AOI construction -------------------------------------------------------

def square_bbox(lat_deg, lon_deg, size_m):
    """A square AOI of `size_m` on a side, centred on a coordinate.

    Returns {"south","west","north","east"} in degrees. This is the radius-mode
    sizing path: one number, no modelled geometry required, which is the only
    mode that works before anything exists in the document.
    """
    if size_m is None or float(size_m) <= 0:
        raise ValueError("size_m must be positive, got: %s" % size_m)

    lat = _validate_lat(lat_deg)
    lon = normalize_lon(lon_deg)
    m_lat, m_lon = meters_per_degree(lat)

    half = float(size_m) / 2.0
    d_lat = half / m_lat
    # Near the poles the longitude scale collapses toward zero; guard rather
    # than divide by ~0 and produce a bbox spanning the globe.
    if abs(m_lon) < 1.0:
        raise ValueError("AOI too close to a pole to be well defined at lat %s" % lat_deg)
    d_lon = half / m_lon

    return {
        "south": lat - d_lat,
        "north": lat + d_lat,
        "west": normalize_lon(lon - d_lon),
        "east": normalize_lon(lon + d_lon),
    }


def bbox_from_points(points_latlon):
    """A bbox enclosing a list of (lat, lon) pairs.

    This is the boundary-curve sizing path: the user picked a closed curve so
    the AOI follows a parcel line or excludes a river. Both sizing modes
    collapse to the same bbox before the request, so the service never sees the
    difference.
    """
    if not points_latlon:
        raise ValueError("no points given")
    lats = [_validate_lat(p[0]) for p in points_latlon]
    lons = [normalize_lon(p[1]) for p in points_latlon]
    return {"south": min(lats), "north": max(lats),
            "west": min(lons), "east": max(lons)}


def bbox_size_m(bbox):
    """Real-world (width, height) of a bbox in metres, measured at its centre."""
    lat_mid = (bbox["south"] + bbox["north"]) / 2.0
    m_lat, m_lon = meters_per_degree(lat_mid)
    d_lat = bbox["north"] - bbox["south"]
    d_lon = bbox["east"] - bbox["west"]
    if d_lon < 0:              # bbox straddles the antimeridian
        d_lon += 360.0
    return (abs(d_lon) * m_lon, abs(d_lat) * m_lat)


def bbox_center(bbox):
    """Centre (lat, lon) of a bbox, antimeridian-safe."""
    lat = (bbox["south"] + bbox["north"]) / 2.0
    d_lon = bbox["east"] - bbox["west"]
    if d_lon < 0:
        d_lon += 360.0
    return (lat, normalize_lon(bbox["west"] + d_lon / 2.0))


def crosses_antimeridian(bbox):
    """True when the AOI wraps past +/-180 -- the tile server needs this split
    into two requests, so it must be detected rather than silently mis-fetched."""
    return bbox["east"] < bbox["west"]


# --- Coordinate input -------------------------------------------------------

# Google Maps puts the viewport centre in the @lat,lon,zoom segment and the
# dropped pin in !3dLAT!4dLON. Prefer the pin: when a designer drops one, that
# IS the site, and the viewport centre can sit a long way off it.
_RE_PIN = re.compile(r"!3d(-?\d+\.?\d*)!4d(-?\d+\.?\d*)")
_RE_QUERY = re.compile(r"[?&]q=(-?\d+\.?\d*),\s*(-?\d+\.?\d*)")
_RE_AT = re.compile(r"@(-?\d+\.?\d*),(-?\d+\.?\d*)")
_RE_PLAIN = re.compile(r"^\s*(-?\d+\.?\d*)\s*[,;\s]\s*(-?\d+\.?\d*)\s*$")

# Order matters and is the whole contract of this function: pin, then explicit
# query, then viewport centre, then a bare typed pair.
_COORD_PATTERNS = (_RE_PIN, _RE_QUERY, _RE_AT, _RE_PLAIN)


def parse_coordinate(text):
    """Return (lat, lon) parsed from a Google Maps URL or a plain pair.

    Returns None on anything unreadable rather than raising: a mistyped
    coordinate is an ordinary thing for a designer to do, and the caller turns
    None into a message instead of a traceback.

    Out-of-range values are treated as no-match rather than as an error, so a
    URL carrying some other !3d-style number cannot be mistaken for a location.
    """
    if not text:
        return None
    for pattern in _COORD_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            lat = float(match.group(1))
            lon = float(match.group(2))
        except ValueError:
            continue
        if abs(lat) > 90 or abs(lon) > 180:
            continue
        return (lat, lon)
    return None


# --- Progress reporting -----------------------------------------------------
#
# GetEarth has TWO phases, and the UI's whole job is to be honest about which
# one it is in:
#
#   1. GENERATION -- one blocking POST to /api/v1/model. There is NO progress
#      channel; the service answers only when the merge is finished. Measured
#      2026-08: about 1 s when the AOI is already cached server-side, 5-20 s
#      for a new one (worst measured 16.4 s, a dense 750 m urban block). This
#      phase gets WORDS and deliberately no bar. A synthetic percentage here
#      would be a number the designer learns to distrust, which would then
#      poison the one bar that IS real.
#   2. DOWNLOAD -- the GLB off blob storage, ~8 MB for a typical 500 m AOI.
#      Real bytes, therefore a real percentage.
#
# Everything below is pure and Rhino-free so it can be tested at the ~1s L1
# layer; RhinoProgressMeter at the bottom is the only part that touches Rhino,
# and it imports it inside its methods per this module's top rule.

_MB = 1024.0 * 1024.0

# Only repaint when the transfer has moved by this share of the whole. At
# 8 KB per read an 8 MB file fires ~1000 callbacks, and each repaint also
# pumps Rhino's message loop -- 100 repaints look identical to 1000 and cost a
# tenth as much.
PROGRESS_PERCENT_STEP = 1.0

# With no Content-Length there is no percentage to step on, so fall back to a
# byte cadence.
PROGRESS_BYTE_STEP = 256 * 1024


def format_bytes(num_bytes):
    """Human-sized byte count, for a label a designer reads mid-download."""
    n = float(num_bytes or 0)
    if n < 1024.0:
        return "{:.0f} B".format(n)
    if n < _MB:
        return "{:.0f} KB".format(n / 1024.0)
    return "{:.1f} MB".format(n / _MB)


def generation_status(size_m):
    """Command-line text for the phase that has nothing measurable to report.

    It names the expected duration instead of drawing a bar, because "roughly
    how long" is the only thing anyone actually wants during a blocking wait.
    """
    return ("GetEarth: building {:.0f} m of site context on the server. "
            "About a second if this area is already cached, otherwise "
            "5-20 seconds. Rhino will be unresponsive until it lands."
            ).format(float(size_m))


def download_status():
    """Command-line text at the moment the download starts.

    Takes no size on purpose. This fires on `on_response`, which is the answer
    to the POST -- the GLB's Content-Length does not exist yet and will not
    until the separate GET is answered. Accepting a size here would be a
    parameter nothing could ever fill; the byte counts start arriving one
    chunk later, through download_label.
    """
    return "GetEarth: downloading the site model..."


def download_label(done_bytes, total_bytes):
    """Label shown while bytes move.

    With no total there is no percentage, so it says the byte count and
    nothing else -- the same honesty as the generation phase. Rhino draws the
    percent itself for the meter; this is the words beside it.
    """
    if total_bytes:
        return "GetEarth  {} / {}".format(
            format_bytes(done_bytes), format_bytes(total_bytes))
    return "GetEarth  {} downloaded".format(format_bytes(done_bytes))


def progress_percent(done_bytes, total_bytes):
    """0-100, clamped. None when there is no total to divide by.

    Clamped rather than trusted: a proxy that sets Content-Length short would
    otherwise drive the meter past its own upper limit.
    """
    if not total_bytes:
        return None
    pct = 100.0 * float(done_bytes) / float(total_bytes)
    if pct < 0.0:
        return 0.0
    if pct > 100.0:
        return 100.0
    return pct


def should_redraw(last_drawn_bytes, done_bytes, total_bytes):
    """True when this progress event is worth a repaint.

    `last_drawn_bytes` is the byte count at the previous repaint, or None if
    nothing has been drawn yet. The first event and the final byte always
    redraw, so the bar never starts late and never stops short of 100%.
    """
    if last_drawn_bytes is None:
        return True
    if total_bytes and done_bytes >= total_bytes:
        return True
    if total_bytes:
        step = float(total_bytes) * PROGRESS_PERCENT_STEP / 100.0
        if step < 1.0:
            step = 1.0
        return (done_bytes - last_drawn_bytes) >= step
    return (done_bytes - last_drawn_bytes) >= PROGRESS_BYTE_STEP


def completion_note(response_data):
    """One line about what the request cost, or "" when the server did not say.

    `cache_hit` and `cost_usd` are ADDITIVE OPTIONAL fields on the service's
    ModelResponse (EnneadTab-EarthModel lib/contract.ts). Reading them must
    never become a requirement: a server that predates them omits them, and
    the button has to fall silent rather than announce "cost $None".
    """
    if not isinstance(response_data, dict):
        return ""
    if response_data.get("cache_hit"):
        return "This area was already built, so the request cost nothing."
    cost = response_data.get("cost_usd")
    if cost is None:
        return ""
    try:
        cost = float(cost)
    except (TypeError, ValueError):
        return ""
    return "Freshly built. This request cost the office ${:.3f}.".format(cost)


class RhinoProgressMeter(object):
    """Status-bar progress for an operation that blocks Rhino's main thread.

    Used as a context manager so the one invariant that matters cannot be
    forgotten at a call site:

        with RhinoProgressMeter() as meter:
            ...
        # hidden here, including when the body raised

    A meter that survives an exception does not just look untidy -- it stays
    in Rhino's status bar for the rest of the session. Hiding therefore lives
    in __exit__, in THIS module, where a CPython test can prove it, rather
    than in a `finally:` in the button, where nothing outside Rhino can.

    Two Rhino facts shape the rest of it:

    * Rhino repaints nothing while the main thread is blocked, so every update
      pumps the message loop with RhinoApp.Wait(). Without that the bar is
      painted once and then frozen, which is worse than no bar at all.
    * The meter is only shown once a real total is known. An indeterminate
      area gets words, never a bar sliding on a number nobody measured.

    Rhino is imported INSIDE the methods per this module's top rule, and the
    whole module can be swapped via `rhino_module=` so the lifecycle is
    testable under plain CPython. Every Rhino call is guarded: an availability
    or overload-resolution surprise degrades to no meter plus one printed line
    for the operator, and never to a dead button.
    """

    def __init__(self, rhino_module=None):
        self._rhino = rhino_module
        self._shown = False        # the status-bar meter is up
        self._prompt_set = False   # the command prompt carries our text
        self._last_drawn = None
        self._disabled = False

    # -- context manager ----------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.hide()
        return False   # never swallow the caller's exception

    # -- internals ----------------------------------------------------------

    def _get_rhino(self):
        if self._disabled:
            return None
        if self._rhino is None:
            try:
                import Rhino  # pyright: ignore
            except ImportError as e:
                self._disable("Rhino is not importable here: {}".format(e))
                return None
            self._rhino = Rhino
        return self._rhino

    def _disable(self, reason):
        """Give up on the display for good, and say so exactly once.

        Graceful to the designer (the download carries on), never silent to
        the operator (rule 13) -- and one line, not one per 8 KB chunk.
        """
        self._disabled = True
        print("GetEarth: progress display unavailable ({}). The operation "
              "itself is unaffected.".format(reason))

    # -- public -------------------------------------------------------------

    def set_status(self, text):
        """Say what is happening during a phase with no measurable progress."""
        rhino = self._get_rhino()
        if rhino is None:
            return
        try:
            rhino.RhinoApp.SetCommandPromptMessage(text)
            rhino.RhinoApp.Wait()
        except Exception as e:
            self._disable(e)
            return
        self._prompt_set = True

    def report(self, done_bytes, total_bytes):
        """The on_progress callback handed to EARTH_MODEL.request_model."""
        rhino = self._get_rhino()
        if rhino is None:
            return
        if not should_redraw(self._last_drawn, done_bytes, total_bytes):
            return
        try:
            if total_bytes and not self._shown:
                # Full positional 5-arg form on purpose: RhinoCommon also
                # carries doc-serial-number overloads of ShowProgressMeter and
                # IronPython picks between them by arity, so leaving an
                # argument to its default is not a safe economy here.
                rhino.UI.StatusBar.ShowProgressMeter(
                    0, 100, "GetEarth", True, True)
                self._shown = True
            if self._shown:
                pct = progress_percent(done_bytes, total_bytes)
                if pct is not None:
                    rhino.UI.StatusBar.UpdateProgressMeter(int(pct), True)
            rhino.RhinoApp.SetCommandPromptMessage(
                download_label(done_bytes, total_bytes))
            rhino.RhinoApp.Wait()
        except Exception as e:
            self._disable(e)
            self.hide()
            return
        self._prompt_set = True
        self._last_drawn = done_bytes

    def hide(self):
        """Take the meter and the status text back down. Called by __exit__.

        Idempotent and never raises. Deliberately does NOT consult
        self._disabled: whatever went wrong may well have happened AFTER the
        meter went up, and a meter left standing -- which outlives the command
        and sits in the status bar for the rest of the session -- is the one
        outcome this class exists to prevent.
        """
        if not self._shown and not self._prompt_set:
            return
        was_shown = self._shown
        self._shown = False
        self._prompt_set = False
        rhino = self._rhino
        if rhino is None:
            return
        try:
            if was_shown:
                rhino.UI.StatusBar.HideProgressMeter()
            rhino.RhinoApp.SetCommandPromptMessage("")
        except Exception as e:
            print("GetEarth: could not clear the progress meter: {}".format(e))
