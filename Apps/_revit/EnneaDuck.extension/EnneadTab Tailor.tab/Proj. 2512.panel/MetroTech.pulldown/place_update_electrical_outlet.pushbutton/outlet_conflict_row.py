"""Plain-data row model for place_update_electrical_outlet_script.py.

Plain data only (ints, strings, floats/tuples) - never a live Revit API element,
since this crosses the resolve/apply boundary inside apply_marker_outlets and is
re-fetched by id there rather than trusted to still be valid.
"""


class OutletPlacementTarget(object):
    """A resolved marker with no existing outlet nearby: safe to place outright.

    `family_name`/`type_name` name the outlet to place here, read from the marker's
    own _para_map (see place_update_electrical_outlet_script.PARA_MAP_TEMPLATE) --
    different markers of the same marker family can each name a different outlet.

    `point` is at the host level's elevation (zero offset) -- `mount_height` is NOT
    baked into it. mount_height instead gets written onto the outlet's
    PLACEMENT_HEIGHT_PARAMETER_NAME instance parameter at placement time, and the
    outlet family's own internal geometry is what visually raises it.

    `stable_ref` (a string from DB.Reference.ConvertToStableRepresentation) is set
    for face-based placement and re-parsed back into a live DB.Reference inside the
    apply handler; it is None for wall-hosted (non-face) placement, where only the
    host wall id and point are needed.

    `level_name` is the HOST FURNITURE instance's level name (e.g. "4TH FLOOR"), not
    an outlet parameter -- carried through purely so apply_marker_outlets can tally
    created/replaced/updated/retagged counts per level for the run summary.
    """
    def __init__(self, host_id, point, family_name, type_name, mount_height, level_name, stable_ref=None,
                 is_horizontal=False, level_elevation=None):
        self.host_id = host_id  # int
        self.point = point  # (x, y, z) plain floats, at host level elevation
        self.family_name = family_name
        self.type_name = type_name
        self.mount_height = mount_height  # float, goes onto PLACEMENT_HEIGHT_PARAMETER_NAME
        self.level_name = level_name  # str, for the per-level summary only
        self.stable_ref = stable_ref  # str or None
        self.is_horizontal = is_horizontal  # bool, True for floor/furniture_horizontal
        self.level_elevation = level_elevation  # float or None, host-space level elevation
