# -*- coding: utf-8 -*-
__title__ = "GetEarth"
__doc__ = """Pull a real-world site context model into Rhino from a coordinate.

Paste a Google Maps link (or a "lat, lon" pair), give it a size, and the
EnneadTab EarthModel service returns a georeferenced textured mesh you can
render against. No Blender detour, no plugin to install, no API key of your own.

How to use:
1. Paste a Google Maps URL, or type "40.7128, -74.0060".
2. Give a square size in metres.
3. The model arrives on its own layer, anchored to the file's EarthAnchorPoint.

Notes:
- Good enough to RENDER. Not survey geometry, and deliberately so: do not snap,
  section, or measure against it.
- Google attribution is attached to the layer and must not be stripped.
- Right-click this button for the diagnostic (is the service up, am I signed in,
  what is cached) and for cache purge.
- The boundary-curve sizing mode described in the service plan is NOT built yet;
  only the square-from-a-point mode ships here. get_earth_utility already has
  the bbox_from_points math it will need.
- Not to be confused with GoogleEarthTutorial in the Render tab. That one is the
  older MANUAL route: it opens a Blender walkthrough video. This button is the
  automatic one. They are separate tools, not two versions of the same thing.
"""
__is_popular__ = True

import os

import Rhino  # pyright: ignore
import rhinoscriptsyntax as rs  # pyright: ignore
import scriptcontext as sc  # pyright: ignore

from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION, DATA_FILE
from EnneadTab import EARTH_MODEL

# Sibling module in this .button folder. The folder is on sys.path at runtime
# inside Rhino, which is the same thing DarkSide/tests/get_earth mirrors with a
# sys.path.insert so the tests import exactly this module.
import get_earth_utility as UTIL


STICKY_SIZE = "GET_EARTH_SIZE_M"
DEFAULT_SIZE_M = 500.0

# Layer the imported context lands on. The name carries the attribution, because
# service plan section 5 makes "Google attribution visibly attached to imported
# geometry, never stripped" one of the four mitigations the firm's accepted-risk
# decision on Google's terms actually rests on. A layer name travels with the
# geometry through copy/paste and into a linked file, which a floating text
# object does not.
CONTEXT_LAYER = "EnneadTab_SiteContext_Imagery (c) Google"


# --- Georeferencing ---------------------------------------------------------

def anchor_is_set():
    """True when the document already carries a real EarthAnchorPoint.

    Rhino always HAS an anchor; an unconfigured one sits at 0,0. Null Island is
    a real coordinate but never a real site, so treating 0,0 as "unset" is the
    correct trade. The cost of being wrong is that a genuine Null Island model
    gets its anchor set instead of being offset from it.
    """
    anchor = sc.doc.EarthAnchorPoint
    if anchor is None:
        return False
    return abs(anchor.EarthBasepointLatitude) > 1e-9 or \
        abs(anchor.EarthBasepointLongitude) > 1e-9


def set_anchor(lat, lon):
    """Point the document's EarthAnchorPoint at this coordinate."""
    anchor = sc.doc.EarthAnchorPoint
    anchor.EarthBasepointLatitude = float(lat)
    anchor.EarthBasepointLongitude = float(lon)
    anchor.EarthBasepointElevation = 0.0
    anchor.ModelBasePoint = Rhino.Geometry.Point3d(0, 0, 0)
    sc.doc.EarthAnchorPoint = anchor


def offset_from_anchor_model_units(lat, lon, unit_name):
    """Model-space (dx, dy) from the existing anchor to this coordinate.

    The service returns geometry centred on its own AOI, so when the file is
    already anchored somewhere else the model has to be moved into place rather
    than the anchor being dragged to meet it. Moving the anchor would displace
    everything already modelled, which is the one outcome the plan forbids.
    """
    anchor = sc.doc.EarthAnchorPoint
    anchor_lat = anchor.EarthBasepointLatitude
    anchor_lon = anchor.EarthBasepointLongitude

    m_per_deg_lat, m_per_deg_lon = UTIL.meters_per_degree(anchor_lat)

    # normalize_lon keeps a site that straddles the antimeridian from being
    # placed half a planet away.
    d_lon = UTIL.normalize_lon(lon - anchor_lon)
    dx_m = d_lon * m_per_deg_lon
    dy_m = (lat - anchor_lat) * m_per_deg_lat

    return (UTIL.meters_to_model(dx_m, unit_name),
            UTIL.meters_to_model(dy_m, unit_name))


# --- Import -----------------------------------------------------------------

def import_glb(path):
    """Import a GLB and return the ids of the objects it created.

    Rhino's importer gives no handle on what it made, so diff the document.
    Anything else would guess, and a wrong guess here moves the designer's own
    geometry instead of the context model.
    """
    before = set(rs.AllObjects(include_lights=True, include_grips=False) or [])
    rs.Command('_-Import "{}" _Enter'.format(path), echo=False)
    after = set(rs.AllObjects(include_lights=True, include_grips=False) or [])
    return list(after - before)


def ensure_context_layer():
    if not rs.IsLayer(CONTEXT_LAYER):
        rs.AddLayer(CONTEXT_LAYER)
    return CONTEXT_LAYER


# --- Entry ------------------------------------------------------------------

@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def get_earth():
    unit_name = rs.UnitSystemName(abbreviate=False)

    raw = rs.StringBox(
        message=("Paste a Google Maps link, or type  lat, lon\n"
                 "Example:  40.7128, -74.0060"),
        default_value="",
        title="GetEarth - where?")
    if not raw:
        return

    coord = UTIL.parse_coordinate(raw)
    if not coord:
        NOTIFICATION.messenger(
            main_text=("Could not read a coordinate out of that.\n"
                       "Paste a Google Maps link, or type  40.7128, -74.0060"))
        return
    lat, lon = coord

    default_size = DATA_FILE.get_sticky(STICKY_SIZE, DEFAULT_SIZE_M)
    size_m = rs.RealBox(
        message="Size of the square site area, in METRES (not file units).",
        default_number=float(default_size),
        title="GetEarth - how big?",
        minimum=1.0)
    if not size_m:
        return
    size_m = float(size_m)
    DATA_FILE.set_sticky(STICKY_SIZE, size_m)

    # The server owns the real bounds and its rejection text is written to be
    # shown to a designer verbatim. This pre-check exists only to avoid burning
    # a billed round trip on an input that cannot possibly succeed; it stays
    # deliberately looser than the server so the server stays authoritative.
    if size_m > 20000:
        NOTIFICATION.messenger(
            main_text=("{:.0f} m is far past what this tool can build.\n"
                       "Try something in the hundreds of metres.").format(size_m))
        return

    NOTIFICATION.messenger(
        main_text=("Asking for {:.0f} m of context at\n{:.5f}, {:.5f}\n"
                   "Photogrammetry takes a while. Hang tight.").format(
                       size_m, lat, lon))

    path = EARTH_MODEL.request_model(lat, lon, size_m)
    if not path:
        # request_model already printed the operator-facing reason. The designer
        # gets a calm one. Both faces, per the repo's rule 13.
        NOTIFICATION.messenger(
            main_text=("No site model came back.\n"
                       "Right-click GetEarth and run the diagnostic to see "
                       "whether the service is reachable and you are signed in."))
        return

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        NOTIFICATION.messenger(
            main_text="The downloaded site model was empty. Nothing imported.")
        return

    rs.EnableRedraw(False)
    try:
        anchor_was_set = anchor_is_set()
        if not anchor_was_set:
            set_anchor(lat, lon)

        new_objs = import_glb(path)
        if not new_objs:
            NOTIFICATION.messenger(
                main_text=("Rhino imported nothing from the site model.\n"
                           "The file may not be a readable GLB."))
            return

        layer = ensure_context_layer()
        for obj in new_objs:
            rs.ObjectLayer(obj, layer)

        if anchor_was_set:
            dx, dy = offset_from_anchor_model_units(lat, lon, unit_name)
            if abs(dx) > 1e-9 or abs(dy) > 1e-9:
                rs.MoveObjects(new_objs, [dx, dy, 0])

        rs.AddObjectsToGroup(new_objs, rs.AddGroup())
    finally:
        rs.EnableRedraw(True)
        sc.doc.Views.Redraw()

    if anchor_was_set:
        placement = ("Placed relative to this file's existing EarthAnchorPoint, "
                     "which was left where it was.")
    else:
        placement = ("This file had no EarthAnchorPoint, so it is now set to "
                     "{:.5f}, {:.5f}.").format(lat, lon)

    NOTIFICATION.messenger(
        main_text=("Site context imported: {} object(s) on layer\n{}\n\n{}\n\n"
                   "Imagery (c) Google. Render against it; do not measure "
                   "from it.").format(len(new_objs), CONTEXT_LAYER, placement))


if __name__ == "__main__":
    get_earth()
