__title__ = "ApplyColorBook"
__doc__ = """Apply the office Color Book to Rhino layer colors - no Excel needed.

Pulls the project's resolved color book from enneadtab.com (Department + Program swatches) and
recolors every layer whose name or abbreviation matches a swatch. Sign in once when prompted.

Key Features:
- Online source: colors live at enneadtab.com/color-book, not a scattered Excel
- Matches layers by name OR abbreviation (case-insensitive, exact)
- Reports how many layers were recolored
- Same office standard the Revit ColorScheme tool uses (shared COLOR library)"""
__is_popular__ = True

import rhinoscriptsyntax as rs  # pyright: ignore

from EnneadTab import COLOR, AUTH, NOTIFICATION, LOG, ERROR_HANDLE


def _leaf(layer_full_name):
    """Rhino layers are 'Parent::Child'; match on the leaf too."""
    return layer_full_name.split("::")[-1]


def _build_lookup(data):
    """{name/abbr(lower): (r,g,b)} from the department + program color maps."""
    lookup = {}
    for channel in ("department_color_map", "program_color_map"):
        for name, info in (data.get(channel, {}) or {}).items():
            color = info.get("color")
            if not color:
                continue
            rgb = (int(color[0]), int(color[1]), int(color[2]))
            lookup[name.strip().lower()] = rgb
            abbr = (info.get("abbr") or "").strip().lower()
            if abbr:
                lookup.setdefault(abbr, rgb)
    return lookup


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def apply_color_book():
    project_number = rs.StringBox("Project number (e.g. 2512):", "", "Online Color Book")
    if not project_number:
        return
    sector = rs.StringBox("Sector:", "HEALTHCARE", "Online Color Book")
    if not sector:
        return

    # Non-blocking token (safe on Rhino 7 IronPython and Rhino 8 CPython). On None: prompt + retry.
    token = AUTH.get_token()
    if not token:
        AUTH.request_auth()
        NOTIFICATION.messenger("Sign in to enneadtab.com, then re-run ApplyColorBook.", sticky=True)
        return

    # Always a dict (empty on auth/network trouble; never None).
    data = COLOR.get_color_template_data(
        source="online", project_number=project_number, sector=sector.upper(), token=token)
    lookup = _build_lookup(data)
    if not lookup:
        NOTIFICATION.messenger("No colors returned. Check sign-in, project number, and sector.", sticky=True)
        return

    layers = rs.LayerNames() or []
    matched = 0
    for layer in layers:
        rgb = lookup.get(layer.strip().lower()) or lookup.get(_leaf(layer).strip().lower())
        if rgb:
            rs.LayerColor(layer, rgb)
            matched += 1

    if matched:
        NOTIFICATION.messenger("Color Book applied: recolored {} of {} layers.".format(matched, len(layers)))
    else:
        NOTIFICATION.messenger(
            "No layers matched the {} color book. Name layers by department/program or abbreviation.".format(sector.upper()))


if __name__ == "__main__":
    apply_color_book()
