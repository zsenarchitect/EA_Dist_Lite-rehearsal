__title__ = "HarvestModelContext"
__doc__ = """Inventory the active model's context for catalog tagging.

Features:
- Per-layer object counts with layer colors
- Block definitions with instance counts
- User-text key frequencies across objects
- Object type frequencies

Usage:
1. Run in a model
2. Copy the reported layer/block/user-text patterns into a GH catalog sidecar "modelContext" tag"""
__is_popular__ = False

from collections import defaultdict

import rhinoscriptsyntax as rs # pyright: ignore
import scriptcontext as sc # pyright: ignore

import Rhino # pyright: ignore

from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def harvest_model_context():
    doc = sc.doc
    if doc is None:
        NOTIFICATION.messenger("No active document, action cancelled.")
        return

    layer_counts = defaultdict(int)
    type_counts = defaultdict(int)
    usertext_counts = defaultdict(int)
    block_counts = defaultdict(int)
    total = 0

    for obj in doc.Objects:
        if obj is None or obj.IsDeleted:
            continue
        total += 1
        try:
            layer_counts[doc.Layers[obj.Attributes.LayerIndex].FullPath] += 1
        except Exception:
            pass
        try:
            type_counts[str(obj.ObjectType)] += 1
        except Exception:
            pass
        try:
            user_strings = obj.Attributes.GetUserStrings()
            if user_strings is not None:
                for key in user_strings.AllKeys:
                    usertext_counts[key] += 1
        except Exception:
            pass
        try:
            if isinstance(obj, Rhino.DocObjects.InstanceObject):
                definition = obj.InstanceDefinition
                if definition is not None and definition.Name:
                    block_counts[definition.Name] += 1
        except Exception:
            pass

    lines = []
    lines.append("MODEL CONTEXT  --  {}".format(doc.Name or "(unsaved)"))
    lines.append("{} object(s) in model".format(total))
    lines.append("")
    lines.append("LAYERS ({}):".format(len(layer_counts)))
    for path in sorted(layer_counts.keys()):
        try:
            color = doc.Layers.FindByFullPath(path, True).Color
            swatch = "#{:02X}{:02X}{:02X}".format(color.R, color.G, color.B)
        except Exception:
            swatch = "?"
        lines.append("  [layer] {}  --  {} object(s)  {}".format(path, layer_counts[path], swatch))
    lines.append("")
    lines.append("BLOCKS ({}):".format(len(block_counts)))
    for name in sorted(block_counts.keys()):
        lines.append("  [block] {}  --  {} instance(s)".format(name, block_counts[name]))
    lines.append("")
    lines.append("USER-TEXT KEYS ({}):".format(len(usertext_counts)))
    for key in sorted(usertext_counts.keys()):
        lines.append("  [usertext] {}  --  on {} object(s)".format(key, usertext_counts[key]))
    lines.append("")
    lines.append("OBJECT TYPES:")
    for object_type in sorted(type_counts.keys()):
        lines.append("  [type] {}  --  {} object(s)".format(object_type, type_counts[object_type]))

    report = "\n".join(lines)
    print (report)

    NOTIFICATION.messenger(
        "Model context harvested: {} layer(s), {} block(s), {} user-text key(s). Full report printed.".format(
            len(layer_counts), len(block_counts), len(usertext_counts)))


if __name__ == "__main__":
    harvest_model_context()
