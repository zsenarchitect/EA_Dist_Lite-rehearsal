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
