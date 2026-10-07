__title__ = "CleanStaleUserText"
__doc__ = """Audit and clean stale attribute user-text keys in the active model.

Key Features:
- Audits object + document user-text keys before changing anything
- Flags stale 'Grasshopper Bake Data' leftovers (known file-bloat cause)
- Flags empty-valued orphaned keys no definition reads anymore
- Checklist UI: you pick exactly which keys to remove
- Reports how many objects each key was removed from

Mirrors the community 'Grasshopper Bake Data' hygiene scripts and
Elefront's Remove User Text.
"""
__is_popular__ = False

import rhinoscriptsyntax as rs
import scriptcontext as sc

from EnneadTab import LOG, ERROR_HANDLE

# Key fragments that mark bake-metadata leftovers rather than real data.
# (Case-insensitive substring match.)
STALE_KEY_FRAGMENTS = (
    "grasshopper bake data",
    "grasshopperbakedata",
    "bake data",
)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def clean_stale_usertext():
    key_info = collect_key_info()
    if not key_info:
        rs.MessageBox("No attribute user-text keys found in this model.", 0, __title__)
        return

    items = []
    for key in sorted(key_info):
        info = key_info[key]
        flags = []
        if info["stale"]:
            flags.append("STALE")
        if info["empty_valued"]:
            flags.append("empty-valued")
        if info["object_count"] == 0:
            where = "doc-level only"
        else:
            where = "{} object(s)".format(info["object_count"])
            if info["on_document"]:
                where += ", doc-level"
        label = "{}  ({}{})".format(
            key, where,
            ", " + "/".join(flags) if flags else "")
        items.append((label, info["stale"] or info["empty_valued"], key))

    picked = rs.CheckListBox(
        [(label, checked) for label, checked, _key in items],
        "Check the keys to REMOVE. Stale bake-data leftovers and "
        "empty-valued keys are pre-checked.",
        __title__)
    if not picked:
        return

    picked_keys = set()
    for label in picked:
        for item_label, _checked, key in items:
            if item_label == label:
                picked_keys.add(key)

    removed = remove_keys(picked_keys)
    rs.MessageBox(
        "Removed {} key(s) from {} object(s){}.".format(
            len(picked_keys), removed,
            " and from document user text" if any(
                key_info[k]["on_document"] for k in picked_keys) else ""),
        0, __title__)
    sc.doc.Views.Redraw()


def collect_key_info():
    """Map key -> {object_count, on_document, stale, empty_valued}."""
    info = {}

    def note(key, on_document, value):
        entry = info.get(key)
        if entry is None:
            entry = {"object_count": 0, "on_document": False,
                     "stale": False, "empty_valued": True}
            info[key] = entry
        if not on_document:
            entry["object_count"] += 1
        entry["on_document"] = entry["on_document"] or on_document
        if value:
            entry["empty_valued"] = False
        lowered = key.lower()
        for frag in STALE_KEY_FRAGMENTS:
            if frag in lowered:
                entry["stale"] = True
                break

    for obj in sc.doc.Objects:
        try:
            keys = obj.Attributes.GetUserStrings()
        except Exception:
            continue
        if not keys:
            continue
        for key in keys:
            try:
                value = obj.Attributes.GetUserString(key)
            except Exception:
                value = None
            note(str(key), False, value)

    try:
        doc_keys = rs.GetDocumentUserText()
    except Exception:
        doc_keys = None
    if doc_keys:
        for key in doc_keys:
            try:
                value = rs.GetDocumentUserText(key)
            except Exception:
                value = None
            note(str(key), True, value)

    return info


def remove_keys(keys):
    removed_objects = 0
    for obj in sc.doc.Objects:
        try:
            obj_keys = obj.Attributes.GetUserStrings() or []
        except Exception:
            continue
        hit = False
        for key in keys:
            if key in obj_keys:
                # No value -> the key is removed (per McNeel user-text guide).
                rs.SetUserText(obj.Id, key)
                hit = True
        if hit:
            removed_objects += 1
    for key in keys:
        try:
            rs.SetDocumentUserText(key)
        except Exception:
            pass
    return removed_objects


if __name__ == "__main__":
    clean_stale_usertext()
