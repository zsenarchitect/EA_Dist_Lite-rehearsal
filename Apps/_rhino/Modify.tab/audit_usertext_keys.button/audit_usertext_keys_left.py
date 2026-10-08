__title__ = "AuditUsertextKeys"
__doc__ = """Audit user-text keys and report per-key object counts across the document.

Shows how many objects carry each key plus the number of distinct values, so missing, misspelled, or inconsistently filled keys surface before baking.
"""
__is_popular__ = False

import rhinoscriptsyntax as rs

from EnneadTab import ERROR_HANDLE, LOG


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def audit_usertext_keys():
    objs = rs.SelectedObjects()
    scope = "selected objects"
    if not objs:
        answer = rs.MessageBox(
            "No objects selected.\n\nAudit user-text keys on ALL objects in the document?",
            4 | 32,  # Yes/No buttons + question icon
            __title__)
        if answer != 6:  # 6 == Yes
            print("Audit cancelled.")
            return
        objs = rs.AllObjects()
        scope = "all document objects"

    if not objs:
        rs.MessageBox("The document contains no objects.", 0, __title__)
        return

    key_counts = {}
    key_values = {}
    objects_without_keys = 0
    for obj in objs:
        try:
            usertext = rs.GetUserText(obj)
        except Exception:
            continue
        if not usertext:
            objects_without_keys += 1
            continue
        for key, value in usertext.items():
            key_counts[key] = key_counts.get(key, 0) + 1
            key_values.setdefault(key, set()).add(value)

    print("=== Usertext key audit: {0} ({1} object(s)) ===".format(scope, len(objs)))
    if not key_counts:
        print("No user-text keys found on any object.")
    else:
        for key in sorted(key_counts, key=lambda k: (-key_counts[k], k.lower())):
            print("  '{0}': {1} object(s), {2} distinct value(s)".format(
                key, key_counts[key], len(key_values[key])))
    if objects_without_keys:
        print("  ({0} object(s) carry no user text at all.)".format(objects_without_keys))

    rs.MessageBox(
        "{0} distinct key(s) found on {1} object(s).\nSee the command history for the full table.".format(
            len(key_counts), len(objs)),
        0,
        __title__)


if __name__ == "__main__":
    audit_usertext_keys()
