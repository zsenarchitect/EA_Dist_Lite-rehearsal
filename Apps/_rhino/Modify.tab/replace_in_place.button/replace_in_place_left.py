__title__ = "ReplaceInPlace"
__doc__ = """Replace-in-place: swap same-named objects instead of duplicating.

Key Features:
- Matches incoming objects to existing by name
- Shows diff count before committing
- Deletes replaced originals, keeps newcomers
- Untouched objects and layers are never modified"""
__is_popular__ = False

import rhinoscriptsyntax as rs
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def replace_in_place():
    incoming = rs.GetObjects("Select incoming objects (matched to existing by name)",
                             preselect=True)
    if not incoming:
        NOTIFICATION.messenger("Nothing selected, replace cancelled.")
        return

    incoming_set = set(incoming)
    to_delete = []
    matched_incoming = 0
    for obj in incoming:
        name = rs.ObjectName(obj)
        if not name:
            continue
        matched = False
        for existing in rs.ObjectsByName(name) or []:
            if existing in incoming_set:
                continue
            if existing not in to_delete:
                to_delete.append(existing)
            matched = True
        if matched:
            matched_incoming += 1

    added = len(incoming) - matched_incoming
    message = "{0} object(s) will be replaced, {1} added. Commit?".format(
        len(to_delete), added)
    if rs.MessageBox(message, 4, __title__) != 6:
        NOTIFICATION.messenger("Replace-in-place cancelled, nothing changed.")
        return

    deleted = 0
    for obj in to_delete:
        if rs.DeleteObject(obj):
            deleted += 1

    sc.doc.Views.Redraw()
    NOTIFICATION.messenger(
        "Replace-in-place done: {0} replaced, {1} kept as new.".format(deleted, added))


if __name__ == "__main__":
    replace_in_place()
