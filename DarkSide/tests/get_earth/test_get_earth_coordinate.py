# -*- coding: utf-8 -*-
"""L1 tests for GetEarth coordinate input parsing.

Pure CPython, no Rhino. `parse_coordinate` lives in get_earth_utility rather
than in get_earth_left.py precisely so it can be tested here -- the button
module imports Rhino at top level and cannot be imported outside Rhino at all.

The behaviour under test is what a designer actually does: paste whatever
Google Maps gave them. That string has several shapes, and picking the WRONG
number out of it puts the site in the wrong place silently, which is worse
than refusing the input.
"""

import os
import sys

import pytest

# The button folder is on sys.path at runtime inside Rhino; mirror that here so
# the test imports exactly the module the button imports.
_BUTTON_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..",
    "Apps", "_rhino", "Render.tab", "get_earth.button")
sys.path.insert(0, os.path.abspath(_BUTTON_DIR))

import get_earth_utility as U


def _close(got, lat, lon):
    assert got is not None
    assert abs(got[0] - lat) < 1e-9
    assert abs(got[1] - lon) < 1e-9


def test_dropped_pin_wins_over_viewport_centre():
    """The !3d/!4d pin is the site; @lat,lon is only where the camera sat.

    This is the single most important case. Both numbers appear in the SAME
    url and they are different places, so a parser that takes the first match
    it finds returns a plausible, wrong location -- the failure mode that never
    announces itself.
    """
    url = ("https://www.google.com/maps/place/Empire+State+Building/"
           "@40.7484,-73.9857,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!"
           "3d40.7484405!4d-73.9856644")
    _close(U.parse_coordinate(url), 40.7484405, -73.9856644)


def test_viewport_url_without_a_pin():
    _close(U.parse_coordinate("https://www.google.com/maps/@40.7484,-73.9857,17z"),
           40.7484, -73.9857)


def test_query_form():
    _close(U.parse_coordinate("https://maps.google.com/?q=51.5074,-0.1278"),
           51.5074, -0.1278)


@pytest.mark.parametrize("text,lat,lon", [
    ("40.7128, -74.0060", 40.7128, -74.0060),
    ("40.7128,-74.0060", 40.7128, -74.0060),
    ("  -33.8688 151.2093  ", -33.8688, 151.2093),
    ("-33.8688; 151.2093", -33.8688, 151.2093),
    ("0, 0", 0.0, 0.0),
])
def test_plain_pairs(text, lat, lon):
    _close(U.parse_coordinate(text), lat, lon)


@pytest.mark.parametrize("text", [
    "",
    None,
    "somewhere near the park",
    "https://www.google.com/maps/place/Empire+State+Building",
])
def test_unreadable_returns_none_rather_than_raising(text):
    """A typo is ordinary. The caller turns None into a message, not a traceback."""
    assert U.parse_coordinate(text) is None


@pytest.mark.parametrize("text", [
    "999.0, 0.0",
    "0.0, 999.0",
    "-91.0, 10.0",
])
def test_out_of_range_is_rejected(text):
    """Out of range is a NON-MATCH, not an error.

    A url can carry other !3d-style numbers that are not a location; treating an
    impossible value as no-match lets a later pattern still find the real
    coordinate instead of the whole parse failing on a decoy.
    """
    assert U.parse_coordinate(text) is None


def test_negative_and_southern_hemisphere_survive_the_round_trip():
    """Sign handling is the classic silent error: a dropped minus puts a Sydney
    site in the North Atlantic, and the model still imports happily."""
    got = U.parse_coordinate("-33.8688, 151.2093")
    _close(got, -33.8688, 151.2093)
    assert got[0] < 0
    assert got[1] > 0
