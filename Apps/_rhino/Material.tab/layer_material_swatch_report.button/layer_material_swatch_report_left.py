__title__ = "LayerMaterialSwatchReport"
__doc__ = """Per-layer material swatch report with optional assignment.

Key Features:
- Lists every layer with its material name
- Shows diffuse color hex per material
- Flags layers falling back to the default material
- Optional one-click material assignment to layers"""
__is_popular__ = False

import rhinoscriptsyntax as rs
import scriptcontext as sc
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION
from EnneadTab.RHINO import RHINO_MATERIAL


def _layer_material_name(layer):
    try:
        render_material = layer.RenderMaterial
        if render_material is not None and render_material.Name:
            return render_material.Name
    except Exception:
        pass
    try:
        if layer.MaterialIndex >= 0:
            return sc.doc.Materials[layer.MaterialIndex].Name
    except Exception:
        pass
    return "(default)"


def _material_color_hex(material_name):
    try:
        material = RHINO_MATERIAL.get_material_by_name(material_name)
        if material is None:
            return "-"
        color = material.DiffuseColor
        return "#{:02X}{:02X}{:02X}".format(color.R, color.G, color.B)
    except Exception:
        return "-"


def _document_material_names():
    names = []
    try:
        for material in sc.doc.Materials:
            name = material.Name
            if name and name not in names:
                names.append(name)
    except Exception:
        pass
    names.sort()
    return names


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def layer_material_swatch_report():
    lines = []
    for i in range(sc.doc.Layers.Count):
        layer = sc.doc.Layers[i]
        if layer.IsDeleted:
            continue
        material_name = _layer_material_name(layer)
        color_hex = _material_color_hex(material_name)
        lines.append("  {0}  ->  {1}  [{2}]".format(layer.FullPath,
                                                    material_name,
                                                    color_hex))

    if not lines:
        NOTIFICATION.messenger("No layers found.")
        return

    print("EnneadTab Layer Material Swatches:")
    for line in lines:
        print(line)
    NOTIFICATION.messenger("Material swatch report: {0} layers listed.".format(len(lines)))

    if rs.MessageBox("Assign a material to picked layers?",
                     4, __title__) != 6:
        return

    material_names = _document_material_names()
    if not material_names:
        NOTIFICATION.messenger("No materials in the document.")
        return

    picked = rs.ListBox(material_names,
                        "Pick a material to assign",
                        __title__)
    if not picked:
        return

    objs = rs.GetObjects("Select objects on the layers to assign '{0}' to".format(picked))
    if not objs:
        NOTIFICATION.messenger("Nothing selected, assignment cancelled.")
        return

    material_index = RHINO_MATERIAL.get_material_by_name(picked, return_index=True)
    if material_index is None:
        NOTIFICATION.messenger("Could not resolve material '{0}'.".format(picked))
        return

    layer_indices = []
    for obj in objs:
        rhino_obj = sc.doc.Objects.FindId(obj)
        if rhino_obj is None:
            continue
        layer_index = rhino_obj.Attributes.LayerIndex
        if layer_index not in layer_indices:
            layer_indices.append(layer_index)

    assigned = 0
    for layer_index in layer_indices:
        try:
            layer = sc.doc.Layers[layer_index]
            layer.MaterialIndex = material_index
            layer.CommitChanges()
            assigned += 1
        except Exception:
            continue

    sc.doc.Views.Redraw()
    NOTIFICATION.messenger("Assigned '{0}' to {1} layer(s).".format(picked, assigned))


if __name__ == "__main__":
    layer_material_swatch_report()
