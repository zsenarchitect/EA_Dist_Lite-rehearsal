__title__ = "BakeNameClean"
__doc__ = """Delete previous bake outputs by bake-name pattern (idempotent bakes).

Features:
- Matches object names and/or the "BakeName" user-text key
- Wildcard patterns (e.g. BriseSoleil_*)
- Preview count with explicit Yes/No confirmation before deleting

Usage:
1. Enter a bake-name wildcard pattern
2. Choose the match source (name, BakeName user-text, or both)
3. Confirm the deletion"""
__is_popular__ = False

import fnmatch

import rhinoscriptsyntax as rs # pyright: ignore
import scriptcontext as sc # pyright: ignore

from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION, DATA_FILE

BAKE_NAME_KEY = "BakeName"
YES = 6  # rhinoscriptsyntax MessageBox returns 6 for "Yes"


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def bakename_clean():
    doc = sc.doc
    if doc is None:
        NOTIFICATION.messenger("No active document, action cancelled.")
        return

    default_pattern = DATA_FILE.get_sticky("BakeNameClean_Pattern", "")
    pattern = rs.StringBox(message="Bake-name wildcard pattern (* matches anything)",
                           default_value=default_pattern,
                           title="Bake Name Clean")
    if not pattern:
        NOTIFICATION.messenger("No pattern entered, action cancelled.")
        return
    pattern = pattern.strip()
    DATA_FILE.set_sticky("BakeNameClean_Pattern", pattern)

    source = rs.ListBox(["Object name", "BakeName user-text", "Both"],
                        message="Match previous outputs by:",
                        title="Bake Name Clean")
    if not source:
        NOTIFICATION.messenger("No match source picked, action cancelled.")
        return
    check_name = source in ("Object name", "Both")
    check_usertext = source in ("BakeName user-text", "Both")

    matched = []
    for obj in doc.Objects:
        if obj is None or obj.IsDeleted:
            continue
        hit = False
        reason = ""
        if check_name:
            try:
                name = obj.Attributes.Name
            except Exception:
                name = None
            if name and fnmatch.fnmatchcase(name, pattern):
                hit = True
                reason = "name \"{}\"".format(name)
        if not hit and check_usertext:
            try:
                user_strings = obj.Attributes.GetUserStrings()
                bake_name = user_strings[BAKE_NAME_KEY] if user_strings is not None else None
            except Exception:
                bake_name = None
            if bake_name and fnmatch.fnmatchcase(bake_name, pattern):
                hit = True
                reason = "{} \"{}\"".format(BAKE_NAME_KEY, bake_name)
        if hit:
            matched.append((obj.Id, reason))

    if not matched:
        NOTIFICATION.messenger("Pattern \"{}\" matched 0 objects, nothing to clean.".format(pattern))
        return

    preview = "\n".join(["  - {} ({})".format(rs.ObjectName(object_id) or object_id, reason)
                         for object_id, reason in matched[:20]])
    if len(matched) > 20:
        preview += "\n  ... and {} more".format(len(matched) - 20)

    answer = rs.MessageBox(
        "Delete {} object(s) matching \"{}\"?\n\n{}".format(len(matched), pattern, preview),
        buttons=4,  # Yes/No
        title="Bake Name Clean -- confirm")
    if answer != YES:
        NOTIFICATION.messenger("Clean cancelled, nothing deleted.")
        return

    ids = [object_id for object_id, _ in matched]
    deleted = rs.DeleteObjects(ids)
    NOTIFICATION.messenger(
        "Cleaned {} of {} matched object(s) for pattern \"{}\".".format(
            deleted, len(matched), pattern))


if __name__ == "__main__":
    bakename_clean()
