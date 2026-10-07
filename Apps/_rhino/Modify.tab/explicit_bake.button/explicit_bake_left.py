__title__ = "ExplicitBake"
__doc__ = """Bake with an explicit Push/Pull/Bake/Purge action mode.

Key Features:
- Mode picker mirrors Rhino 8 Content Cache semantics
- Unique base name required up front
- Destructive modes (Push/Purge) ask for explicit confirmation"""
__is_popular__ = False

import rhinoscriptsyntax as rs

from EnneadTab import LOG, ERROR_HANDLE

MODES = [
    "Push — replace existing set by name (destructive)",
    "Bake — duplicate with new names (additive)",
    "Pull — report only, no model changes",
    "Purge — delete named set (destructive)",
]


def find_named(base_name):
    hits = []
    for guid in rs.AllObjects():
        name = rs.ObjectName(guid)
        if name and (name == base_name or name.startswith(base_name + "_")):
            hits.append(guid)
    return hits


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def explicit_bake():
    choice = rs.ListBox(MODES, "Pick the model-write action mode.", __title__)
    if choice is None:
        return
    mode = choice.split(" — ")[0]

    base_name = rs.GetString("Unique base name for this bake set")
    if not base_name:
        return
    base_name = base_name.strip()
    if not base_name:
        return

    existing = find_named(base_name)

    if mode == "Pull":
        rs.MessageBox(
            "{0} object(s) currently carry the name '{1}'.".format(
                len(existing), base_name),
            0,
            __title__)
        return

    if mode == "Purge":
        if not existing:
            rs.MessageBox(
                "Nothing named '{0}' to purge.".format(base_name), 0, __title__)
            return
        confirm = rs.MessageBox(
            "Delete {0} object(s) named '{1}'? This cannot be undone.".format(
                len(existing), base_name),
            4,
            __title__)
        if confirm != 6:  # 6 = Yes
            return
        rs.DeleteObjects(existing)
        rs.MessageBox("Purged {0} object(s).".format(len(existing)), 0, __title__)
        return

    # Push / Bake need source objects.
    verb = "push" if mode == "Push" else "bake"
    sources = rs.GetObjects("Select source objects to " + verb, preselect=True)
    if not sources:
        return

    if mode == "Push" and existing:
        confirm = rs.MessageBox(
            "Push will replace {0} existing object(s) named '{1}'. Continue?".format(
                len(existing), base_name),
            4,
            __title__)
        if confirm != 6:  # 6 = Yes
            return
        rs.DeleteObjects(existing)

    copies = rs.CopyObjects(sources)
    for i, guid in enumerate(copies):
        rs.ObjectName(guid, "{0}_{1:03d}".format(base_name, i + 1))

    rs.MessageBox(
        "{0}: {1} object(s) written as '{2}_###'.".format(
            mode, len(copies), base_name),
        0,
        __title__)


if __name__ == "__main__":
    explicit_bake()
