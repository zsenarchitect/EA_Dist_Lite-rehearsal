# -*- coding: utf-8 -*-
"""L1 tests for GetEarth AOI math -- no Rhino, no network, no API key.

Runs in ~1s. This layer exists so that the expensive layers (drive a live Rhino,
capture and judge a render) are reserved for what actually needs them.

Run:
    python -m pytest DarkSide/tests/get_earth/test_get_earth_aoi.py -q
"""

import os
import sys

import pytest

# The button folder is on sys.path at runtime inside Rhino; mirror that here so
# the test imports exactly the module the button imports.
_BUTTON_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "Apps", "_rhino", "Create.tab", "get_earth.button")
sys.path.insert(0, os.path.abspath(_BUTTON_DIR))

import get_earth_utility as U


# --- units ------------------------------------------------------------------

def test_millimeter_default_template_is_the_dangerous_case():
    # Rhino's default template is millimetres, so a 500 m AOI is 500,000 units.
    # This is the 1000x error the module exists to prevent.
    assert U.meters_to_model(500.0, "millimeter") == 500000.0


def test_unit_round_trip():
    for unit in ("millimeter", "meter", "foot", "inch"):
        assert abs(U.model_to_meters(U.meters_to_model(123.0, unit), unit) - 123.0) < 1e-9


def test_unknown_unit_raises_rather_than_defaulting():
    # Silently defaulting to 1.0 would look like a geometry bug, not a units bug.
    with pytest.raises(ValueError):
        U.unit_to_meters("smoots")
    with pytest.raises(ValueError):
        U.unit_to_meters(None)


def test_unit_name_is_case_and_space_tolerant():
    assert U.unit_to_meters("  Millimeter ") == 0.001


# --- geodesy ----------------------------------------------------------------

def test_longitude_spacing_collapses_toward_the_poles():
    _, lon_eq = U.meters_per_degree(0.0)
    _, lon_60 = U.meters_per_degree(60.0)
    # cos(60) = 0.5, so a degree of longitude is about half as wide.
    assert abs(lon_60 / lon_eq - 0.5) < 0.01


def test_latitude_spacing_is_nearly_constant():
    lat_eq, _ = U.meters_per_degree(0.0)
    lat_60, _ = U.meters_per_degree(60.0)
    assert abs(lat_60 - lat_eq) / lat_eq < 0.01


def test_invalid_latitude_raises():
    with pytest.raises(ValueError):
        U.meters_per_degree(91.0)
    with pytest.raises(ValueError):
        U.meters_per_degree(-90.5)


def test_normalize_lon_wraps():
    assert U.normalize_lon(190.0) == -170.0
    assert U.normalize_lon(-190.0) == 170.0
    assert U.normalize_lon(-73.9857) == -73.9857


# --- square AOI (radius mode) -----------------------------------------------

@pytest.mark.parametrize("lat,lon", [
    (0.0, 0.0),            # equator
    (40.7484, -73.9857),   # Empire State Building
    (60.1699, 24.9384),    # Helsinki -- longitude compression is severe here
    (-33.8688, 151.2093),  # Sydney, southern hemisphere
])
def test_square_bbox_round_trips_to_requested_size(lat, lon):
    """A request for N metres must produce ~N metres of geometry. This is THE
    assertion the whole tool rests on."""
    size = 500.0
    bbox = U.square_bbox(lat, lon, size)
    w, h = U.bbox_size_m(bbox)
    assert abs(w - size) < 1.0, "width off at lat %s: %s" % (lat, w)
    assert abs(h - size) < 1.0, "height off at lat %s: %s" % (lat, h)


def test_square_bbox_is_centred_on_the_request():
    lat, lon = 40.7484, -73.9857
    bbox = U.square_bbox(lat, lon, 800.0)
    c_lat, c_lon = U.bbox_center(bbox)
    assert abs(c_lat - lat) < 1e-9
    assert abs(c_lon - lon) < 1e-9


def test_high_latitude_needs_a_wider_longitude_span_in_degrees():
    eq = U.square_bbox(0.0, 0.0, 1000.0)
    hi = U.square_bbox(60.0, 0.0, 1000.0)
    span_eq = eq["east"] - eq["west"]
    span_hi = hi["east"] - hi["west"]
    # Same metres on the ground, roughly twice the degrees at 60 deg.
    assert span_hi > span_eq * 1.9


def test_non_positive_size_raises():
    for bad in (0, -1, -500.0):
        with pytest.raises(ValueError):
            U.square_bbox(40.0, -73.0, bad)


def test_pole_is_rejected_rather_than_producing_a_global_bbox():
    with pytest.raises(ValueError):
        U.square_bbox(90.0, 0.0, 500.0)


# --- boundary-curve mode ----------------------------------------------------

def test_bbox_from_points_encloses_all_points():
    pts = [(40.0, -74.0), (40.01, -73.99), (39.995, -74.02)]
    bbox = U.bbox_from_points(pts)
    for lat, lon in pts:
        assert bbox["south"] <= lat <= bbox["north"]
        assert bbox["west"] <= lon <= bbox["east"]


def test_bbox_from_points_rejects_empty():
    with pytest.raises(ValueError):
        U.bbox_from_points([])


def test_both_sizing_modes_agree():
    """Radius mode and boundary mode must collapse to the same thing -- the
    service never sees which the user picked."""
    lat, lon, size = 40.7484, -73.9857, 600.0
    from_radius = U.square_bbox(lat, lon, size)
    corners = [
        (from_radius["south"], from_radius["west"]),
        (from_radius["south"], from_radius["east"]),
        (from_radius["north"], from_radius["east"]),
        (from_radius["north"], from_radius["west"]),
    ]
    from_curve = U.bbox_from_points(corners)
    for k in ("south", "north", "west", "east"):
        assert abs(from_radius[k] - from_curve[k]) < 1e-9


# --- antimeridian -----------------------------------------------------------

def test_antimeridian_crossing_is_detected():
    # Taveuni, Fiji -- sits on the 180th meridian.
    bbox = U.square_bbox(-16.8, 179.9995, 500.0)
    assert U.crosses_antimeridian(bbox)


def test_antimeridian_bbox_still_reports_the_right_size():
    size = 500.0
    bbox = U.square_bbox(-16.8, 179.9995, size)
    w, h = U.bbox_size_m(bbox)
    assert abs(w - size) < 1.0
    assert abs(h - size) < 1.0


def test_ordinary_bbox_does_not_claim_to_cross():
    assert not U.crosses_antimeridian(U.square_bbox(40.7484, -73.9857, 500.0))
