__title__ = "QuickBakeTextDots"
__doc__ = """Quick-bake selected objects with text-dot labels.

Key Features:
- One-click bake of the current selection
- Text dots carry object names at bbox centers
- Dedicated quick-bake layer, no dialog digging
- Remembers the target layer between runs"""
__is_popular__ = False

import rhinoscriptsyntax as rs
import scriptcontext as sc
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION, DATA_FILE


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def quick_bake_text_dots():
    objs = rs.GetObjects("Select objects to quick-bake", preselect=True)
    if not objs:
        NOTIFICATION.messenger("Nothing selected, quick-bake cancelled.")
        return

    target_layer = DATA_FILE.get_sticky("QUICKBAKE_LAYER", "EnneadTab::QuickBake")
    new_layer = rs.GetString("Quick-bake target layer", target_layer)
    if not new_layer:
        return
    DATA_FILE.set_sticky("QUICKBAKE_LAYER", new_layer)
    rs.AddLayer(new_layer)

    baked = 0
    dotted = 0
    for obj in objs:
        new_id = rs.CopyObject(obj)
        if new_id is None:
            continue
        rs.ObjectLayer(new_id, new_layer)
        baked += 1

        name = rs.ObjectName(new_id)
        label = name if name else "(unnamed)"
        box = rs.BoundingBox(new_id)
        if not box:
            continue
        center = (box[0] + box[6]) / 2
        dot = rs.AddTextDot(label, center)
        if dot is None:
            continue
        rs.ObjectLayer(dot, new_layer)
        dotted += 1

    sc.doc.Views.Redraw()
    NOTIFICATION.messenger(
        "Quick-baked {0} objects with {1} text dots to '{2}'.".format(
            baked, dotted, new_layer))


if __name__ == "__main__":
    quick_bake_text_dots()
