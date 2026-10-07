__title__ = "BakeWithAttributes"
__doc__ = """Bake selected objects with an explicit name / layer / color mapping.

Key Features:
- One dialog for the full attribute mapping, no hidden defaults
- Name template with {i} index token (e.g. 'Panel_{i}')
- Layer path with '::' nesting, created on demand
- Display color applied per object (color source = object)
- Copies the selection; originals are untouched

Rhino-side equivalent of the Grasshopper ModelObject -> ObjectAttributes
translation fallback: name, layer path and display color are documented
in the contract before anything is baked.
"""
__is_popular__ = False

from System import Guid
from System.Drawing import ColorTranslator

import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc

from EnneadTab import LOG, ERROR_HANDLE

# rs.ObjectColorSource codes: 0 = from layer, 1 = from object.
COLOR_SOURCE_FROM_OBJECT = 1


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def bake_with_attributes():
    ids = rs.GetObjects(
        "Select objects to bake with explicit attributes", preselect=True)
    if not ids:
        return

    name_template = rs.GetString(
        "Name template ('{i}' = index, blank = keep original name)",
        "Baked_{i}")
    if name_template is None:
        return

    layer_path = rs.GetString(
        "Layer path ('::' nests, e.g. EnneadTab::Baked)",
        "EnneadTab::Baked")
    if not layer_path:
        return

    color_hex = rs.GetString(
        "Display color as hex (blank = keep original color)",
        "#0078D7")
    if color_hex is None:
        return
    color = parse_hex_color(color_hex)

    target_layer = ensure_layer_path(layer_path)
    baked = 0
    for index, obj_id in enumerate(ids):
        new_id = rs.CopyObject(obj_id)
        if not new_id:
            continue
        if name_template:
            rs.ObjectName(new_id, name_template.replace("{i}", str(index)))
        rs.ObjectLayer(new_id, target_layer)
        if color is not None:
            rs.ObjectColor(new_id, color)
            rs.ObjectColorSource(new_id, COLOR_SOURCE_FROM_OBJECT)
        baked += 1

    rs.MessageBox(
        "Baked {} object(s):\n"
        "  name  : {}\n"
        "  layer : {}\n"
        "  color : {}".format(
            baked,
            name_template or "(original)",
            target_layer,
            color_hex or "(original)"),
        0, __title__)
    sc.doc.Views.Redraw()


def parse_hex_color(color_hex):
    text = (color_hex or "").strip()
    if not text:
        return None
    try:
        return ColorTranslator.FromHtml(text)
    except Exception:
        rs.MessageBox(
            "Could not parse color '{}'; original colors kept.".format(text),
            0, __title__)
        return None


def ensure_layer_path(full_path):
    """Return full_path, creating any missing '::'-nested layers."""
    index = sc.doc.Layers.FindByFullPath(full_path, -1)
    if index >= 0:
        return full_path
    parent_id = Guid.Empty
    current = ""
    for part in full_path.split("::"):
        current = part if not current else current + "::" + part
        index = sc.doc.Layers.FindByFullPath(current, -1)
        if index < 0:
            layer = Rhino.DocObjects.Layer()
            layer.Name = part
            if parent_id != Guid.Empty:
                layer.ParentLayerId = parent_id
            index = sc.doc.Layers.Add(layer)
        parent_id = sc.doc.Layers[index].Id
    return full_path


if __name__ == "__main__":
    bake_with_attributes()
