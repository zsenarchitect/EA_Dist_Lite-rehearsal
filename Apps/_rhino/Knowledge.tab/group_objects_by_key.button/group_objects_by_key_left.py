__title__ = "GroupObjectsByKey"
__doc__ = """Group sample objects by a property key and preview the branch map.

Key Features:
- Branch key choices: Layer, Name, or any user-text key
- Reports one-branch-per-value counts (tree contract preview)
- Optionally organizes objects onto sublayers per branch value"""
__is_popular__ = False

import rhinoscriptsyntax as rs

from EnneadTab import LOG, ERROR_HANDLE

PARENT_LAYER = "EnneadTab_Grouped"


def sanitize_layer_name(name):
    for bad in (":", "/", "\\", "*", "?", '"', "<", ">", "|"):
        name = name.replace(bad, "_")
    name = name.strip()
    return name if name else "group"


def get_branch_value(guid, kind, user_text_key):
    if kind == "Layer":
        return rs.ObjectLayer(guid)
    if kind == "Name":
        return rs.ObjectName(guid) or "(unnamed)"
    return rs.GetUserText(guid, user_text_key) or "(no value)"


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def group_objects_by_key():
    kinds = ["Layer", "Name", "UserText"]
    kind = rs.ListBox(kinds, "Pick the property key to group by.", __title__)
    if kind is None:
        return

    user_text_key = None
    if kind == "UserText":
        user_text_key = rs.GetString("User text key to branch on (e.g. Panel_ID)")
        if not user_text_key:
            return

    guids = rs.GetObjects(
        "Select objects to sample (Enter = all visible objects)", preselect=True)
    if guids is None:
        return
    if not guids:
        guids = rs.VisibleObjects()
    if not guids:
        rs.MessageBox("No objects to sample.", 0, __title__)
        return

    groups = {}
    for guid in guids:
        value = get_branch_value(guid, kind, user_text_key)
        groups.setdefault(value, []).append(guid)

    key_label = user_text_key if user_text_key else kind
    lines = ["Branch map \xe2\x80\x94 one branch per {0}:".format(key_label), ""]
    for value in sorted(groups):
        lines.append("  {0}: {1} object(s)".format(value, len(groups[value])))
    report = "\n".join(lines)

    organize = rs.MessageBox(
        report + "\n\nMove objects onto sublayers per branch value?",
        4,
        __title__)
    if organize != 6:  # 6 = Yes
        return

    if not rs.IsLayer(PARENT_LAYER):
        rs.AddLayer(PARENT_LAYER)
    for value in groups:
        child = "{0}::{1}".format(PARENT_LAYER, sanitize_layer_name(value))
        if not rs.IsLayer(child):
            rs.AddLayer(child)
        for guid in groups[value]:
            rs.ObjectLayer(guid, child)

    rs.MessageBox(
        "Organized {0} object(s) into {1} sublayer(s) under '{2}'.".format(
            len(guids), len(groups), PARENT_LAYER),
        0,
        __title__)


if __name__ == "__main__":
    group_objects_by_key()
