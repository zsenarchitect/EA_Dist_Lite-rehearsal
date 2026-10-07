__doc__ = """Attempt to fix blank keynote text on User Keynote tags by re-linking the key.

Some tags keep a valid key but Revit stops showing the text next to it, a known
display bug. This tool retries several ways of re-linking the key, but none of
them reliably brought the text back in testing. The only thing confirmed to
work is manually re-assigning the key value for each tag in the Properties
panel -- kept here for reference, not for regular use."""
__title__ = "UserKeynote Refresher"


import proDUCKtion # pyright: ignore
proDUCKtion.validify()
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_SELECTION
from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION
from pyrevit import DB, revit, script, forms

uidoc = REVIT_APPLICATION.get_uidoc()
doc = REVIT_APPLICATION.get_doc()

TEMP_KEY_PREFIX = "__ENNEADTAB_TEMP__"

OPTION_ADD_PREFIX = "Add temporary marker (step 1)"
OPTION_REMOVE_PREFIX = "Remove temporary marker (step 2)"

OPTION_CURRENT_VIEW = "Current view only (test run)"
OPTION_ENTIRE_PROJECT = "Entire project"

# https://www.revitapidocs.com/2018.2/fb011c91-be7e-f737-28c7-3f1e1917a0e0.htm
# Every BuiltInParameter that could plausibly drive the "Key Value" / "Keynote Text"
# shown in the Revit UI -- printed side by side per tag to pin down which one the UI
# actually reads from vs which one this tool has been writing to.
DIAGNOSTIC_PARAMS = [
    ("KEY_SOURCE_PARAM", DB.BuiltInParameter.KEY_SOURCE_PARAM),
    ("KEYNOTE_PARAM", DB.BuiltInParameter.KEYNOTE_PARAM),
    ("KEYNOTE_NUMBER", DB.BuiltInParameter.KEYNOTE_NUMBER),
    ("SHEET_KEY_NUMBER", DB.BuiltInParameter.SHEET_KEY_NUMBER),
    ("KEYNOTE_TEXT", DB.BuiltInParameter.KEYNOTE_TEXT),
    ("KEY_VALUE", DB.BuiltInParameter.KEY_VALUE),
]


def _param_as_string(element, bip):
    try:
        param = element.Parameter[bip]
    except Exception:
        return "<no such param on this element>"
    if not param:
        return "<none>"
    value = param.AsString()
    if value is None:
        value = param.AsValueString()
    if value is None:
        value = ""
    return "'{}'{}".format(value, " (RO)" if param.IsReadOnly else "")


def print_diagnostic_table(output, tags):
    table_data = []
    for tag in tags:
        row = [output.linkify(tag.Id)]
        row.extend(_param_as_string(tag, bip) for _, bip in DIAGNOSTIC_PARAMS)
        table_data.append(row)

    output.print_table(table_data=table_data,
                        title="User Keynote parameter diagnostic (before refresh)",
                        columns=["Tag Id"] + [name for name, _ in DIAGNOSTIC_PARAMS],
                        formats=['{}'] * (len(DIAGNOSTIC_PARAMS) + 1))


def _is_changable_tag_and_view(tag):
    if not REVIT_SELECTION.is_changable(tag):
        print ("---tag being owned, skip")
        return False
    view = revit.doc.GetElement(tag.OwnerViewId)
    if not REVIT_SELECTION.is_changable(view):
        print ("---view [{}] being owned, skip".format(view.Name))
        return False
    return True


def _collect_broken_user_keynotes(key_note_tags):
    """Tags to prefix in step 1: writable Key Value, blank Keynote Text, not already prefixed."""
    touchable = []  # (tag, key_param, new_value)
    skipped_owned_count = 0
    skipped_no_key_count = 0
    skipped_element_or_material_count = 0
    skipped_already_has_text_count = 0
    skipped_already_prefixed_count = 0

    for tag in key_note_tags:
        if not _is_changable_tag_and_view(tag):
            skipped_owned_count += 1
            continue

        key_param = tag.Parameter[DB.BuiltInParameter.KEY_VALUE]
        original_key = key_param.AsString() if key_param else None
        if not key_param or not original_key:
            skipped_no_key_count += 1
            continue

        # Element Keynote and Material Keynote tags derive their Key Value from the
        # tagged element/material, so Revit reports it as read-only on those (confirmed
        # live -- Set() throws "The parameter is read-only"). Only User Keynote tags
        # allow a direct Key Value edit, so this is what keeps this tool User-Keynote-only.
        if key_param.IsReadOnly:
            source_param = tag.Parameter[DB.BuiltInParameter.KEY_SOURCE_PARAM]
            source_text = source_param.AsString() if source_param else "unknown source"
            print ("---tag key value read-only ({}), skip -- not a User Keynote".format(source_text))
            skipped_element_or_material_count += 1
            continue

        if original_key.startswith(TEMP_KEY_PREFIX):
            skipped_already_prefixed_count += 1
            continue

        # KEY_VALUE is the key; KEYNOTE_TEXT is what the tag actually renders on screen
        # (confirmed live via the diagnostic table). Only tags whose Keynote Text is
        # blank are the broken ones -- skip tags that already display fine so a run
        # doesn't touch (and risk) tags that don't need it.
        text_param = tag.Parameter[DB.BuiltInParameter.KEYNOTE_TEXT]
        current_text = text_param.AsString() if text_param else None
        if current_text:
            skipped_already_has_text_count += 1
            continue

        touchable.append((tag, key_param, TEMP_KEY_PREFIX + original_key))

    skip_counts = {
        "owned": skipped_owned_count,
        "no_key": skipped_no_key_count,
        "element_or_material": skipped_element_or_material_count,
        "already_has_text": skipped_already_has_text_count,
        "already_prefixed": skipped_already_prefixed_count,
    }
    return touchable, skip_counts


def _collect_prefixed_user_keynotes(key_note_tags):
    """Tags to restore in step 2: Key Value currently holds a temp-prefixed value."""
    touchable = []  # (tag, key_param, new_value)
    skipped_owned_count = 0
    skipped_not_prefixed_count = 0

    for tag in key_note_tags:
        if not _is_changable_tag_and_view(tag):
            skipped_owned_count += 1
            continue

        key_param = tag.Parameter[DB.BuiltInParameter.KEY_VALUE]
        current_key = key_param.AsString() if key_param else None
        if not key_param or not current_key or not current_key.startswith(TEMP_KEY_PREFIX):
            skipped_not_prefixed_count += 1
            continue

        touchable.append((tag, key_param, current_key[len(TEMP_KEY_PREFIX):]))

    skip_counts = {
        "owned": skipped_owned_count,
        "not_prefixed": skipped_not_prefixed_count,
    }
    return touchable, skip_counts


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main():
    operation = forms.SelectFromList.show([OPTION_ADD_PREFIX, OPTION_REMOVE_PREFIX],
                                           button_name="Next",
                                           multiselect=False,
                                           title="Step 1 of 2: which operation?")
    if not operation:
        return

    scope = forms.SelectFromList.show([OPTION_CURRENT_VIEW, OPTION_ENTIRE_PROJECT],
                                       button_name="Run",
                                       multiselect=False,
                                       title="Step 2 of 2: which tags?")
    if not scope:
        return

    key_note_tags = DB.FilteredElementCollector(revit.doc).OfCategory(DB.BuiltInCategory.OST_KeynoteTags).WhereElementIsNotElementType().ToElements()

    if scope == OPTION_CURRENT_VIEW:
        active_view = REVIT_APPLICATION.get_active_view()
        key_note_tags = [tag for tag in key_note_tags if tag.OwnerViewId == active_view.Id]

    if operation == OPTION_ADD_PREFIX:
        touchable, skip_counts = _collect_broken_user_keynotes(key_note_tags)
    else:
        touchable, skip_counts = _collect_prefixed_user_keynotes(key_note_tags)

    print_diagnostic_table(script.get_output(), [tag for tag, _, _ in touchable])

    # A manual edit in the Properties palette works because each edit commits as its own
    # transaction, with Revit's UI free to repaint before the next edit happens. Doing the
    # temp-then-restore round trip as two Transactions inside one script run does not give
    # the UI that idle/paint cycle, so this tool is split into two separate button clicks
    # (this run only does ONE Set() pass) to test whether the real handoff between clicks
    # is what actually triggers the redraw.
    with revit.Transaction("keynote refresh"):
        for tag, key_param, new_value in touchable:
            key_param.Set(new_value)

    # Confirmed live: the Key Value parameter can be written correctly while the tag's
    # on-screen glyph stays stale -- Regenerate() only updates the document model, not
    # view graphics. UpdateAllOpenViews() (2018+) forces a full graphics redraw regardless
    # of what changed, unlike RefreshActiveView(), which several Revit API reports say can
    # still miss tags. Must run outside any open transaction.
    if touchable:
        uidoc.UpdateAllOpenViews()

    if operation == OPTION_ADD_PREFIX:
        NOTIFICATION.messenger(main_text="{} tags marked with a temporary key (blank Keynote Text).\n{} already had text, left alone.\n{} already marked from a prior run.\n{} skipped due to ownership.\n{} skipped (no key value).\n{} skipped (Element/Material Keynote, not User Keynote).\nNow run again and pick 'Remove temporary marker' to finish.".format(
            len(touchable), skip_counts["already_has_text"], skip_counts["already_prefixed"],
            skip_counts["owned"], skip_counts["no_key"], skip_counts["element_or_material"]))
    else:
        NOTIFICATION.messenger(main_text="{} tags restored to their real key.\n{} skipped (not currently marked).\n{} skipped due to ownership.\nSee output for details".format(
            len(touchable), skip_counts["not_prefixed"], skip_counts["owned"]))
################## main code below #####################
if __name__ == "__main__":

    output = script.get_output()
    output.close_others()
    main()
