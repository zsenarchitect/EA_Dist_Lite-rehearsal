__title__ = "PickSelectionContract"
__doc__ = """Pick-selection contract: capture viewport picks as GUIDs under a name.

Key Features:
- Prompts viewport selection at run time
- Captures picked object GUIDs into a named contract
- Re-select a stored contract in one click
- Skips deleted or missing objects on re-select"""
__is_popular__ = False

import rhinoscriptsyntax as rs
import scriptcontext as sc
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION, DATA_FILE


def _contract_key(name):
    return "PICK_SELECTION_CONTRACT_" + name


def _resolve_stored(stored):
    valid = []
    if not isinstance(stored, (list, tuple)):
        return valid
    for item in stored:
        guid = rs.coerceguid(item)
        if guid is None:
            continue
        rhino_obj = sc.doc.Objects.FindId(guid)
        if rhino_obj is None or rhino_obj.IsDeleted:
            continue
        valid.append(guid)
    return valid


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def pick_selection_contract():
    last_name = DATA_FILE.get_sticky("PICK_SELECTION_CONTRACT_LAST", "Default")
    name = rs.GetString("Selection contract name", last_name)
    if not name:
        return
    DATA_FILE.set_sticky("PICK_SELECTION_CONTRACT_LAST", name)

    key = _contract_key(name)
    stored = DATA_FILE.get_sticky(key)
    if stored:
        options = ["Pick a new selection",
                   "Re-select stored ({0} objects)".format(len(stored))]
        choice = rs.ListBox(options,
                            "Contract '{0}' already exists".format(name),
                            __title__)
        if choice is None:
            return
        if choice == options[1]:
            valid = _resolve_stored(stored)
            rs.UnselectAllObjects()
            if valid:
                rs.SelectObjects(valid)
            NOTIFICATION.messenger(
                "Re-selected {0} of {1} stored objects for contract '{2}'.".format(
                    len(valid), len(stored), name))
            return

    objs = rs.GetObjects("Pick objects for selection contract '{0}'".format(name),
                         preselect=True)
    if not objs:
        NOTIFICATION.messenger("Nothing picked, contract unchanged.")
        return

    DATA_FILE.set_sticky(key, [str(guid) for guid in objs])
    NOTIFICATION.messenger(
        "Stored {0} objects as selection contract '{1}'.".format(len(objs), name))


if __name__ == "__main__":
    pick_selection_contract()
