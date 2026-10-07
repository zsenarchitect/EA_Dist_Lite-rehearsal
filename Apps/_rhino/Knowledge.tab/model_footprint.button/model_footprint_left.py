__title__ = "ModelFootprint"
__doc__ = """Live footprint of layer patterns against the current model.

Features:
- One or more layer wildcard patterns, comma-separated (e.g. FACADE::*, *_Annotation)
- Per-pattern live object counts with layer color swatches (hex)
- Remembers the last patterns used

Usage:
1. Enter layer wildcard patterns
2. See the live match count per pattern"""
__is_popular__ = False

import fnmatch

import rhinoscriptsyntax as rs # pyright: ignore
import scriptcontext as sc # pyright: ignore

from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION, DATA_FILE


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def model_footprint():
    doc = sc.doc
    if doc is None:
        NOTIFICATION.messenger("No active document, action cancelled.")
        return

    default_patterns = DATA_FILE.get_sticky("ModelFootprint_Patterns", "*")
    raw = rs.StringBox(message="Layer wildcard patterns, comma-separated (* matches anything)",
                       default_value=default_patterns,
                       title="Model Footprint")
    if not raw:
        NOTIFICATION.messenger("No patterns entered, action cancelled.")
        return
    DATA_FILE.set_sticky("ModelFootprint_Patterns", raw)

    patterns = [p.strip() for p in raw.split(",") if p.strip()]
    if not patterns:
        NOTIFICATION.messenger("No patterns entered, action cancelled.")
        return

    layer_names = rs.LayerNames()
    if not layer_names:
        NOTIFICATION.messenger("Model has no layers.")
        return

    lines = []
    lines.append("MODEL FOOTPRINT  --  {}".format(doc.Name or "(unsaved)"))
    total_matches = 0
    for pattern in patterns:
        matched = [name for name in layer_names if fnmatch.fnmatchcase(name, pattern)]
        count = 0
        swatch = "-"
        detail = []
        for name in matched:
            try:
                ids = rs.ObjectsByLayer(name) or []
            except Exception:
                ids = []
            count += len(ids)
            try:
                color = rs.LayerColor(name)
                hex_color = "#{:02X}{:02X}{:02X}".format(color.R, color.G, color.B)
            except Exception:
                hex_color = "?"
            detail.append("    {}  --  {} object(s)  {}".format(name, len(ids), hex_color))
            if swatch == "-":
                swatch = hex_color
        total_matches += count
        lines.append("")
        lines.append("[layer] {}  --  {} object(s)  swatch {}".format(pattern, count, swatch))
        lines.extend(detail)

    lines.append("")
    lines.append("{} pattern(s), {} matched object(s) total.".format(len(patterns), total_matches))
    print ("\n".join(lines))

    NOTIFICATION.messenger(
        "Model footprint: {} pattern(s) matched {} object(s). Full report printed.".format(
            len(patterns), total_matches))


if __name__ == "__main__":
    model_footprint()
