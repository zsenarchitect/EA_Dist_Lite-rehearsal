#!/usr/bin/python
# -*- coding: utf-8 -*-



__doc__ = """Toggle live sheet numbers between the firm Internal scheme and the client DOH scheme.

Both schemes are stored permanently, so nothing is lost when you switch.
Applying a scheme copies the stored numbers into the live sheet number slot."""
__title__ = "Apply DOH\nSheetNum"

import os
import sys

from pyrevit import forms  # noqa

import proDUCKtion  # pyright: ignore
proDUCKtion.validify()
from EnneadTab import ERROR_HANDLE, NOTIFICATION, LOG
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_SELECTION, REVIT_FORMS
from Autodesk.Revit import DB  # pyright: ignore
import System  # pyright: ignore
# Clipboard lives in System.Windows (PresentationCore), already loaded by
# pyrevit.forms' WPF stack -- safe to import at module scope here.
from System.Windows import Clipboard  # pyright: ignore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apply_logic as AL  # noqa

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()

INTERNAL_PARAM = "Sheet Number_Internal"
DOH_PARAM = "Sheet Number_DOH"


def get_all_sheets(doc):
    sheets = DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).ToElements()
    return list(sheets)


def _param_str(sheet, name):
    p = sheet.LookupParameter(name)
    if p is None:
        return None
    v = p.AsString()
    if v is None or v == "":
        return None
    return v


def _owner_of(doc, element_id):
    """Worksharing owner (borrower) of an element -- the user to ask for
    ownership -- or '' if the model isn't workshared / Revit can't report it."""
    try:
        tip = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, element_id)
        return tip.Owner or ""
    except Exception:
        return ""


def read_rows(doc):
    rows = []
    for s in get_all_sheets(doc):
        changable = bool(REVIT_SELECTION.is_changable(s))
        # Only pay for the worksharing lookup on sheets we can't edit -- those
        # are the ones we need to name an owner for.
        owner = "" if changable else _owner_of(doc, s.Id)
        rows.append(AL.SheetRow(
            REVIT_APPLICATION.get_element_id_value(s.Id),
            s.SheetNumber,
            _param_str(s, INTERNAL_PARAM),
            _param_str(s, DOH_PARAM),
            bool(s.IsPlaceholder),
            changable,
            owner,
        ))
    return rows


def params_bound(doc):
    sheets = get_all_sheets(doc)
    sample = None
    for s in sheets:
        if not s.IsPlaceholder:
            sample = s
            break
    if sample is None:
        sample = sheets[0] if sheets else None
    if sample is None:
        return (False, False)
    has_internal = sample.LookupParameter(INTERNAL_PARAM) is not None
    has_doh = sample.LookupParameter(DOH_PARAM) is not None
    return (has_internal, has_doh)


def reserved_placeholder_numbers(rows):
    return [r.live for r in rows if r.is_placeholder and r.live is not None]


def build_health(rows):
    internal_set = len([r for r in rows if not AL.is_empty(r.internal)])
    doh_set = len([r for r in rows if not AL.is_empty(r.doh)])
    return {
        "total": len(rows),
        "internal_set": internal_set,
        "doh_set": doh_set,
        "internal_dups": AL.find_duplicates(rows, AL.SOURCE_INTERNAL),
        "doh_dups": AL.find_duplicates(rows, AL.SOURCE_DOH),
        "incomplete": AL.find_incomplete(rows),
        "mode": AL.infer_mode(rows),
    }


def format_health_detail(rows):
    """Multi-line, target-independent breakdown for the report panel: the
    concrete issues that could block an Apply, or a ready message when clean."""
    lines = []
    idup = AL.duplicate_detail(rows, AL.SOURCE_INTERNAL)
    if idup:
        lines.append("Internal duplicates (value -> sheets currently numbered):")
        lines.extend(idup)
    ddup = AL.duplicate_detail(rows, AL.SOURCE_DOH)
    if ddup:
        lines.append("DOH duplicates (value -> sheets currently numbered):")
        lines.extend(ddup)
    incomplete = AL.find_incomplete(rows)
    if incomplete:
        lines.append("Incomplete (need both numbers): %d sheet(s)" % len(incomplete))
    drift_lines = AL.drift_detail(rows)
    if drift_lines:
        n = len(drift_lines)
        lines.append(
            "%d %s show a live number that isn't saved in either scheme "
            "(hand-edited or newly added). Applying DOH or Internal will "
            "replace it with that scheme's number -- the current number is "
            "lost. To keep it, use 'Capture live -> Internal' first." % (
                n, _plural(n)))
        lines.extend(_cap(drift_lines))
    if AL.infer_mode(rows) == AL.MODE_MIXED:
        lines.append("Mixed: some sheets show Internal, some DOH -- "
                     "Apply will offer to normalize")
    non_ch = AL.find_non_changable(rows)
    if non_ch:
        lines.append("Not yours to edit: %d sheet(s) owned by others" % len(non_ch))
    if not lines:
        return "No blocking issues detected. Ready to Apply."
    return "\n".join(lines)


def _sheet_by_id(doc, sid):
    # Revit 2026: DB.ElementId(<python int>) is ambiguous (Int64 vs the
    # BuiltInParameter/BuiltInCategory enum overloads). Cast to System.Int64
    # to bind the ElementId(Int64) overload explicitly.
    return doc.GetElement(DB.ElementId(System.Int64(sid)))


def _write_two_pass(doc, plan):
    """plan: list of (sheet_id, final_number). Single transaction, two passes,
    per-run GUID temp tokens. Rolls back then RE-RAISES on failure so the
    caller's @ERROR_HANDLE.try_catch_error() surfaces it to ErrorDump instead
    of swallowing it into a soft message."""
    rows = read_rows(doc)
    run_guid = str(System.Guid.NewGuid()).replace("-", "")[:8]
    if AL.temp_prefix_collision(rows, run_guid):
        run_guid = str(System.Guid.NewGuid()).replace("-", "")[:8]
    ids = [sid for sid, _ in plan]
    tokens = AL.make_temp_tokens(ids, run_guid)
    t = DB.Transaction(doc, "Apply DOH SheetNum")
    t.Start()
    try:
        for sid in ids:                       # Pass 1: vacate
            _sheet_by_id(doc, sid).SheetNumber = tokens[sid]
        doc.Regenerate()
        for sid, final_number in plan:        # Pass 2: assign
            _sheet_by_id(doc, sid).SheetNumber = final_number
        t.Commit()
    except Exception:
        t.RollBack()
        raise


def _write_param(doc, txn_name, param_name, assignments):
    """assignments: list of (sheet_id, value). Single transaction. Tolerates
    sheets that don't expose the param, or expose it read-only (some placeholder
    sheets): those are skipped and their ids returned instead of aborting the
    run. Any OTHER (unexpected) exception still rolls back and RE-RAISES so the
    caller's error handler surfaces it. Returns the list of skipped sheet_ids."""
    skipped = []
    t = DB.Transaction(doc, txn_name)
    t.Start()
    try:
        for sid, value in assignments:
            p = _sheet_by_id(doc, sid).LookupParameter(param_name)
            if p is None or p.IsReadOnly:
                skipped.append(sid)
                continue
            p.Set(value)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return skipped


def _plural(n):
    return "sheet" if n == 1 else "sheets"


def _cap(lines, limit=20):
    """Show at most `limit` detail lines; never silently truncate -- append an
    explicit '... and N more' so the user knows the list was shortened."""
    if len(lines) <= limit:
        return lines
    return lines[:limit] + ["  ... and %d more" % (len(lines) - limit)]


def _block(header, hint, lines):
    """One blocking issue: a header, a plain-language fix hint, then the exact
    sheets it applies to (capped)."""
    return "\n".join([header, "  Fix: " + hint] + _cap(lines))


def _apply_gate(rows, source):
    """SURGICAL execution gate: return only the blockers that would actually
    break THIS write (empty => allowed). Scoped to the sheets that change --
    problems on sheets we won't touch don't belong here (that's the strict
    verification report's job). Blocks on: duplicate final numbers (Revit rejects
    them), a target value reserved by a placeholder, and ownership of a sheet we
    must rewrite. Incomplete/drift are NOT execution blockers -- a sheet with no
    target value is simply skipped (reported by run_apply), and drift just means
    Apply overwrites the live number, which is the whole point."""
    label = "DOH" if source == AL.SOURCE_DOH else "Internal"
    blocks = []

    # The plan already excludes placeholders, unchanged sheets, and sheets with
    # no target value -- so `changing_ids` is exactly what we will rewrite.
    _, plan = AL.plan_apply(rows, source)
    changing_ids = set(sid for sid, _ in plan)

    dup_lines = AL.duplicate_detail(rows, source)
    if dup_lines:
        blocks.append(_block(
            "Duplicate %s numbers (%d) -- two sheets can't share one number." % (
                label, len(dup_lines)),
            "give one sheet in each pair a unique %s number, or clear it. "
            "Below: %s value -> the sheets that currently hold it." % (label, label),
            dup_lines))

    coll_lines = AL.collision_detail(rows, source, reserved_placeholder_numbers(rows))
    if coll_lines:
        blocks.append(_block(
            "Reserved-number clash (%d %s) -- a target %s value is already held "
            "by a placeholder sheet." % (
                len(coll_lines), _plural(len(coll_lines)), label),
            "renumber the placeholder sheet, or change the clashing %s value." % label,
            coll_lines))

    nc_lines = AL.non_changable_detail(rows, changing_ids)
    if nc_lines:
        blocks.append(_block(
            "Owned by others (%d %s that need renumbering) -- you can't edit "
            "these yet." % (len(nc_lines), _plural(len(nc_lines))),
            "take ownership from the Collaborate tab, or ask the owner to "
            "sync and relinquish, then try again.",
            nc_lines))

    return blocks


def _confirm(main_text, sub_text, ok_label, icon="warning"):
    """EnneadTab-styled Yes/No confirm via REVIT_FORMS.dialogue (our TaskDialog
    wrapper) instead of pyrevit forms.alert. Returns True only if the user picks
    ok_label. dialogue() may return (result, checkbox) -- normalize to the text."""
    res = REVIT_FORMS.dialogue(
        main_text=main_text, sub_text=sub_text,
        options=[ok_label, "Cancel"], icon=icon)
    if isinstance(res, (tuple, list)):
        res = res[0]
    return res == ok_label


def run_apply(target):
    rows = read_rows(DOC)
    target_label = "DOH" if target == AL.SOURCE_DOH else "Internal"
    problems = _apply_gate(rows, target)
    if problems:
        header = ("Can't apply %s numbering yet -- %d issue(s) to clear first:" % (
            target_label, len(problems)))
        NOTIFICATION.messenger(main_text=header + "\n\n" + "\n\n".join(problems), sticky=True)
        return
    kind, plan = AL.plan_apply(rows, target)
    # Sheets left out because they have no value in the target store -- surfaced
    # to the user rather than silently dropped.
    n_blank = len(AL.blank_target_detail(rows, target))
    blank_note = ((" %d %s skipped (no %s value)." % (
        n_blank, _plural(n_blank), target_label)) if n_blank else "")
    if kind == "noop":
        NOTIFICATION.messenger(
            main_text="Already in the requested mode. Nothing to change." + blank_note)
        return
    if AL.infer_mode(rows) == AL.MODE_MIXED:
        n_internal = len([r for r in rows
                          if not r.is_placeholder and not AL.is_empty(r.internal)
                          and not AL.is_empty(r.doh) and AL.classify(r) == "P"])
        n_doh = len([r for r in rows
                     if not r.is_placeholder and not AL.is_empty(r.internal)
                     and not AL.is_empty(r.doh) and AL.classify(r) == "Q"])
        if not _confirm(
                "Model is mixed: %d sheets on Internal, %d on DOH." % (
                    n_internal, n_doh),
                "Normalize all %d sheets to %s numbering?" % (
                    len(plan), target_label),
                "Normalize to %s" % target_label):
            return
    else:
        if not _confirm(
                "Apply %s numbering" % target_label,
                "%d %s will change SheetNumber. Continue?" % (
                    len(plan), _plural(len(plan))),
                "Apply %s" % target_label):
            return
    _write_two_pass(DOC, plan)
    NOTIFICATION.messenger(
        main_text=("Applied %s numbering to %d %s." % (
            target_label, len(plan), _plural(len(plan)))) + blank_note)


def run_capture():
    """Fold the live SheetNumber into Sheet Number_Internal for sheets whose
    Internal is empty or drifted (class N) -- the repair for drift. Refuses when
    the model is in DOH mode (capturing then would overwrite the firm's Internal
    numbers with the client's DOH numbers). Never touches already-correct sheets
    or placeholders."""
    rows = read_rows(DOC)
    kind, payload = AL.plan_capture(rows, AL.infer_mode(rows))
    if kind == "refused":
        NOTIFICATION.messenger(main_text=payload)
        return
    targets = payload
    if not targets:
        NOTIFICATION.messenger(
            main_text="Nothing to capture -- every sheet's Internal number "
                      "already matches its live number.")
        return
    if not _confirm(
            "Capture live numbers into Internal",
            "%d %s will have their current SheetNumber saved into "
            "Sheet Number_Internal (only sheets that are off-scheme or have an "
            "empty Internal). Existing correct Internal values are kept. "
            "Continue?" % (len(targets), _plural(len(targets))),
            "Capture", icon="shield"):
        return
    skipped = _write_param(DOC, "Capture Internal", INTERNAL_PARAM, targets)
    written = len(targets) - len(skipped)
    msg = "Captured live numbers into Internal on %d %s." % (
        written, _plural(written))
    if skipped:
        msg += (" Skipped %d %s that don't accept the parameter." % (
            len(skipped), _plural(len(skipped))))
    NOTIFICATION.messenger(main_text=msg)


def run_initialize():
    """Seed both stores from the live SheetNumber, filling only empty cells."""
    rows = read_rows(DOC)
    internal_targets, doh_targets = AL.plan_initialize(rows)
    n_int = len(internal_targets)
    n_doh = len(doh_targets)
    if not internal_targets and not doh_targets:
        NOTIFICATION.messenger(
            main_text="Nothing to initialize -- Internal and DOH are already "
                      "filled on every editable sheet.")
        return
    if not _confirm(
            "Initialize Internal & DOH from live",
            "Seed Internal on %d sheet(s) and DOH on %d sheet(s) from the "
            "current SheetNumber (placeholder sheets included)? Only empty "
            "cells are written; existing values are kept." % (n_int, n_doh),
            "Initialize", icon="shield"):
        return
    skipped_int = (_write_param(DOC, "Initialize Internal", INTERNAL_PARAM,
                                internal_targets) if internal_targets else [])
    skipped_doh = (_write_param(DOC, "Initialize DOH", DOH_PARAM,
                                doh_targets) if doh_targets else [])
    written_int = n_int - len(skipped_int)
    written_doh = n_doh - len(skipped_doh)
    n_skipped = len(set(skipped_int) | set(skipped_doh))
    msg = "Initialized: Internal on %d, DOH on %d sheet(s)." % (
        written_int, written_doh)
    if n_skipped:
        msg += (" Skipped %d sheet(s) that don't accept the parameter "
                "(likely placeholders)." % n_skipped)
    NOTIFICATION.messenger(main_text=msg)


class ApplyDohWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, "ApplyDOH_UI.xaml")
        self._refresh()

    def _refresh(self):
        has_i, has_d = params_bound(DOC)
        if not (has_i and has_d):
            missing = []
            if not has_i:
                missing.append(INTERNAL_PARAM)
            if not has_d:
                missing.append(DOH_PARAM)
            self.ModeText.Text = "Setup required"
            self.HealthText.Text = "Missing parameter(s): %s" % ", ".join(missing)
            self.ReportText.Text = ("Add each as a Text parameter bound to the "
                                    "Sheets category, then reopen this tool.")
            for b in (self.ApplyDohButton, self.ApplyInternalButton,
                      self.InitializeButton, self.CaptureButton):
                b.IsEnabled = False
            return
        rows = read_rows(DOC)
        h = build_health(rows)
        self.ModeText.Text = "Mode: %s" % h["mode"]
        self.HealthText.Text = (
            "Sheets %d     Internal set %d (dup %d)     "
            "DOH set %d (dup %d)     incomplete %d" % (
                h["total"], h["internal_set"], len(h["internal_dups"]),
                h["doh_set"], len(h["doh_dups"]), len(h["incomplete"])))
        self.ReportText.Text = format_health_detail(rows)
        # Initialize is never gated by completeness (it satisfies it).
        # Apply buttons stay enabled (XAML default) -- run_apply() re-runs the
        # gate against the specific target and reports exact blocking reasons
        # on click, so no separate up-front disable is needed.
        self.InitializeButton.IsEnabled = True

    # Each click handler is individually wrapped so an exception during a
    # transaction surfaces to EnneadTab's error handler (ErrorDump + traceback
    # log + critical dialog) rather than dying silently inside the WPF modal.
    @ERROR_HANDLE.try_catch_error()
    def apply_doh_click(self, sender, args):
        self.Close()
        run_apply(AL.SOURCE_DOH)

    @ERROR_HANDLE.try_catch_error()
    def apply_internal_click(self, sender, args):
        self.Close()
        run_apply(AL.SOURCE_INTERNAL)

    @ERROR_HANDLE.try_catch_error()
    def capture_click(self, sender, args):
        self.Close()
        run_capture()

    @ERROR_HANDLE.try_catch_error()
    def initialize_click(self, sender, args):
        self.Close()
        run_initialize()

    @ERROR_HANDLE.try_catch_error()
    def copy_log_click(self, sender, args):
        # Copy exactly what the panel shows (mode + health + report) so the
        # user can paste the blocking reasons elsewhere. Does NOT close the
        # window -- they usually copy, then act on the same open dialog.
        text = "\n".join([
            "Apply DOH SheetNum",
            self.ModeText.Text or "",
            "",
            self.HealthText.Text or "",
            "",
            self.ReportText.Text or "",
        ])
        try:
            Clipboard.SetDataObject(text, True)  # True => persist after close
        except Exception:
            Clipboard.SetText(text)
        self.CopyLogButton.Content = "Copied"

    def close_Click(self, sender, args):
        self.Close()

    def mouse_down_main_panel(self, sender, args):
        # WindowStyle="None" removes the native title bar; drag by the chrome.
        try:
            self.DragMove()
        except Exception:
            pass


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main():
    ApplyDohWindow().ShowDialog()


################## main code below #####################

if __name__ == "__main__":
    main()
