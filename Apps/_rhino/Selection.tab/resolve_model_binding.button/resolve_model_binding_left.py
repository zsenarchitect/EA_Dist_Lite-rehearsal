__title__ = "ResolveModelBinding"
__doc__ = """Select model objects by layer or block-name wildcard pattern.

Features:
- Layer patterns with * wildcards and :: sublayer paths (e.g. FACADE::*)
- Block-name patterns (e.g. Panel_*)
- Remembers the last pattern used

Usage:
1. Choose layer or block-name matching
2. Enter a wildcard pattern
3. Matching objects are selected"""
__is_popular__ = False

import fnmatch

import rhinoscriptsyntax as rs # pyright: ignore
import scriptcontext as sc # pyright: ignore

import Rhino # pyright: ignore

from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION, DATA_FILE


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def resolve_model_binding():
    doc = sc.doc
    if doc is None:
        NOTIFICATION.messenger("No active document, action cancelled.")
        return

    kind = rs.ListBox(["Layer pattern", "Block name pattern"],
                      message="Resolve model binding by:",
                      title="Resolve Model Binding")
    if not kind:
        NOTIFICATION.messenger("No match kind picked, action cancelled.")
        return

    sticky_key = "ResolveModelBinding_Pattern_Layer" if kind == "Layer pattern" \
        else "ResolveModelBinding_Pattern_Block"
    default_pattern = DATA_FILE.get_sticky(sticky_key, "*")

    pattern = rs.StringBox(message="Wildcard pattern (* matches anything)",
                           default_value=default_pattern,
                           title="Resolve Model Binding -- {}".format(kind))
    if not pattern:
        NOTIFICATION.messenger("No pattern entered, action cancelled.")
        return
    pattern = pattern.strip()
    DATA_FILE.set_sticky(sticky_key, pattern)

    matched_ids = []
    if kind == "Layer pattern":
        layer_paths = []
        for layer in doc.Layers:
            if layer is None or layer.IsDeleted:
                continue
            if fnmatch.fnmatchcase(layer.FullPath, pattern):
                layer_paths.append(layer.FullPath)
        for path in layer_paths:
            try:
                ids = rs.ObjectsByLayer(path)
            except Exception:
                ids = None
            if ids:
                matched_ids.extend(ids)
    else:
        for obj in doc.Objects:
            if obj is None or obj.IsDeleted:
                continue
            if isinstance(obj, Rhino.DocObjects.InstanceObject):
                definition = obj.InstanceDefinition
                if definition is not None and definition.Name \
                        and fnmatch.fnmatchcase(definition.Name, pattern):
                    matched_ids.append(obj.Id)

    # de-dupe while keeping it simple
    seen = set()
    unique_ids = []
    for object_id in matched_ids:
        if object_id not in seen:
            seen.add(object_id)
            unique_ids.append(object_id)

    if not unique_ids:
        NOTIFICATION.messenger("Pattern \"{}\" matched 0 objects.".format(pattern))
        return

    rs.UnselectAllObjects()
    rs.SelectObjects(unique_ids)
    NOTIFICATION.messenger(
        "Pattern \"{}\" matched {} object(s), selected.".format(pattern, len(unique_ids)))


if __name__ == "__main__":
    resolve_model_binding()
