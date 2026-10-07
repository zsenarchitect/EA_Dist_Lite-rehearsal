# -*- coding: utf-8 -*-
__title__ = "LibraryAttrFilter"
__doc__ = """Select model objects by Elefront-style key/value user-text attributes.

Rhino port of the Grasshopper library attribute filtering
(EnneadTab-For-Grasshopper PR #39): pick user-text key/value criteria and
every model object whose attributes match ALL criteria gets selected.

Key Features:
- Key picker lists every user-text key already in the document
- '(key present)' matches any value for a key (Elefront-style presence check)
- Stack multiple criteria (AND); values compare case-insensitively
- Reports how many objects were selected"""
__is_popular__ = True

import rhinoscriptsyntax as rs # pyright: ignore
import scriptcontext as sc # pyright: ignore

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION

_ANY_VALUE = "(key present - match any value)"
_CUSTOM_KEY = "(type a custom key...)"
_CUSTOM_VALUE = "(type a custom value...)"


def _pick_one(options, title, message, button_name = "Select"):
    picked = RHINO_FORMS.select_from_list(options,
                                          title = title,
                                          message = message,
                                          button_names = [button_name],
                                          multi_select = False)
    if not picked:
        return None
    if isinstance(picked, (list, tuple)):
        return picked[0] if picked else None
    return picked


def _object_user_text(object_id):
    """Return {key: value} user text for one object; never raises."""
    try:
        keys = rs.GetUserText(object_id)
    except Exception:
        return {}
    if not keys:
        return {}
    result = {}
    for key in keys:
        try:
            result[key] = rs.GetUserText(object_id, key)
        except Exception:
            continue
    return result


def _collect_inventory(object_ids):
    """Return {normalized key: [display spelling, set(values)]} for the document."""
    inventory = {}
    for object_id in object_ids:
        for key, value in _object_user_text(object_id).items():
            norm = key.lower()
            if norm not in inventory:
                inventory[norm] = [key, set()]
            if value is not None:
                inventory[norm][1].add(value)
    return inventory


def _find_key(data, wanted):
    """Case-insensitive key lookup in a {key: value} dict; exact spelling wins."""
    if wanted in data:
        return wanted
    lowered = wanted.lower()
    for key in data:
        if key.lower() == lowered:
            return key
    return None


def _matches(data, criteria):
    for key, value in criteria:
        actual_key = _find_key(data, key)
        if actual_key is None:
            return False
        if value is None:
            continue  # key-presence check, Elefront-style
        actual = data[actual_key] or ""
        if actual.lower() != value.lower():
            return False
    return True


def _format_criteria(criteria):
    return ", ".join(["{}={}".format(key, value if value is not None else "*") for key, value in criteria])


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_attr_filter():
    object_ids = rs.AllObjects() or []
    if not object_ids:
        NOTIFICATION.messenger(main_text = "The document has no objects to filter.")
        return

    inventory = _collect_inventory(object_ids)
    if not inventory:
        NOTIFICATION.messenger(main_text = "No user text found on any object in this document.")
        return

    keys = sorted([display for display, _values in inventory.values()],
                  key = lambda text: text.lower())

    criteria = []
    while True:
        key = _pick_one(keys + [_CUSTOM_KEY],
                        title = "Filter By Attribute - Key",
                        message = "Pick a user-text key (Cancel when done adding criteria).",
                        button_name = "Next")
        if key is None:
            break
        if key == _CUSTOM_KEY:
            key = rs.StringBox(message = "Type the user-text key:",
                               title = "Custom attribute key")
            if not key:
                continue
            key = key.strip()
            if not key:
                continue

        norm = key.lower()
        observed = sorted(inventory[norm][1], key = lambda text: text.lower()) if norm in inventory else []
        value = _pick_one([_ANY_VALUE] + observed + [_CUSTOM_VALUE],
                          title = "Filter By Attribute - Value",
                          message = "Pick the value to match for key '{}'.".format(key),
                          button_name = "Add")
        if value is None:
            continue
        if value == _CUSTOM_VALUE:
            value = rs.StringBox(message = "Type the value to match for '{}':".format(key),
                                 title = "Custom attribute value")
            if value is None:
                continue
        elif value == _ANY_VALUE:
            value = None
        criteria.append((key, value))

        if rs.MessageBox("Criteria so far:\n{}\n\nAdd another criterion?".format(_format_criteria(criteria)),
                         buttons = 4,
                         title = "Filter By Attribute") != 6:
            break

    if not criteria:
        NOTIFICATION.messenger(main_text = "No criteria given, nothing selected.")
        return

    matches = []
    for object_id in object_ids:
        if _matches(_object_user_text(object_id), criteria):
            matches.append(object_id)

    rs.UnselectAllObjects()
    if matches:
        rs.SelectObjects(matches)
    NOTIFICATION.messenger(
        main_text = "{} of {} objects match {} criterion/criteria:\n{}".format(
            len(matches), len(object_ids), len(criteria), _format_criteria(criteria)))


if __name__ == "__main__":
    library_attr_filter()
