#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Record or apply CW-3 pier metadata.

Use "Record" in the source model to capture pier flags for every
"EA_CW-3 (Wrap)" curtain panel. Use "Apply" in the target model to
replay the captured flags on matching elements by UniqueId."""
__title__ = "Recover CW-3"

import proDUCKtion # pyright: ignore 
proDUCKtion.validify()

import json
import os

TARGET_FAMILY_NAME = "EA_CW-3 (Wrap)"
PIER_PARAMETERS = ("is_pier_left", "is_pier_right")
DATA_FILE_NAME = "recover_cw3_panel_state.json"

from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_FORMS
from Autodesk.Revit import DB # pyright: ignore 

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()


def _get_data_file_path():
    base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, DATA_FILE_NAME)


def _ask_user_action():
    result = REVIT_FORMS.dialogue(
        title=__title__,
        main_text="Do you want to record the current CW-3 pier flags or apply the saved values?",
        sub_text="Record: capture pier flags into JSON\nApply: load JSON and push pier flags into this model",
        options=["Record", "Apply", "Cancel"],
    )
    return result


def _collect_target_panels(doc):
    collector = DB.FilteredElementCollector(doc)
    collector = collector.OfCategory(DB.BuiltInCategory.OST_CurtainWallPanels)
    collector = collector.WhereElementIsNotElementType()
    panels = []
    for element in collector:
        symbol = getattr(element, "Symbol", None)
        if symbol is None:
            continue
        family = getattr(symbol, "Family", None)
        if family is None:
            continue
        if family.Name == TARGET_FAMILY_NAME:
            panels.append(element)
    return panels


def _get_yes_no_value(element, parameter_name):
    param = element.LookupParameter(parameter_name)
    if param is None:
        return None
    if param.StorageType == DB.StorageType.Integer:
        return param.AsInteger() == 1
    if param.StorageType == DB.StorageType.Double:
        return param.AsDouble() != 0.0
    return None


def _set_yes_no_value(element, parameter_name, value):
    if value is None:
        return False
    param = element.LookupParameter(parameter_name)
    if param is None or param.IsReadOnly:
        return False
    target_value = 1 if value else 0
    if param.StorageType == DB.StorageType.Integer:
        if param.AsInteger() != target_value:
            param.Set(target_value)
            return True
        return False
    if param.StorageType == DB.StorageType.Double:
        current = param.AsDouble()
        if (value and current == 0.0) or ((not value) and current != 0.0):
            param.Set(1.0 if value else 0.0)
            return True
        return False
    return False


def _record_panel_data(doc):
    panels = _collect_target_panels(doc)
    if not panels:
        return 0
    data = {}
    for panel in panels:
        panel_data = {}
        for parameter_name in PIER_PARAMETERS:
            panel_data[parameter_name] = _get_yes_no_value(panel, parameter_name)
        data[panel.UniqueId] = panel_data
    file_path = _get_data_file_path()
    with open(file_path, "w") as fp:
        json.dump(data, fp, indent=2, sort_keys=True)
    return len(data)


def _load_panel_data():
    file_path = _get_data_file_path()
    if not os.path.exists(file_path):
        return None
    with open(file_path, "r") as fp:
        return json.load(fp)


def _apply_panel_data(doc):
    panel_map = _load_panel_data()
    if panel_map is None:
        return None, None, None
    transaction = DB.Transaction(doc, __title__)
    transaction.Start()
    updated = 0
    missing = 0
    matched = 0
    try:
        for unique_id, parameter_map in panel_map.iteritems():
            element = doc.GetElement(unique_id)
            if element is None:
                missing += 1
                continue
            matched += 1
            changed = False
            for parameter_name in PIER_PARAMETERS:
                stored_value = parameter_map.get(parameter_name)
                if _set_yes_no_value(element, parameter_name, stored_value):
                    changed = True
            if changed:
                updated += 1
        transaction.Commit()
    except Exception:
        transaction.RollBack()
        raise
    return updated, missing, matched


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def recover_cw3(doc):
    action = _ask_user_action()
    if action == "Cancel" or action is None:
        NOTIFICATION.messenger("Recover CW-3 cancelled.")
        return
    if action == "Record":
        record_count = _record_panel_data(doc)
        if record_count:
            NOTIFICATION.messenger("Recorded pier flags for {0} panels.".format(record_count))
        else:
            NOTIFICATION.messenger("No \"{0}\" panels were found to record.".format(TARGET_FAMILY_NAME))
        return
    if action == "Apply":
        updated, missing, matched = _apply_panel_data(doc)
        if matched is None:
            NOTIFICATION.messenger("No saved data file was found in this folder.")
            return
        NOTIFICATION.messenger(
            "Matched {0} panels by UniqueId. Updated {1} panels. {2} panels were missing.".format(
                matched, updated, missing
            )
        )
        return
    raise ValueError("Unknown action \"{0}\".".format(action))



################## main code below #####################
if __name__ == "__main__":
    recover_cw3(DOC)







