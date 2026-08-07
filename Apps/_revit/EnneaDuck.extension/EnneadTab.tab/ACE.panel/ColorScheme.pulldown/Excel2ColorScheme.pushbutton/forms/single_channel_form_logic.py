# -*- coding: utf-8 -*-
"""Event handlers and view-model for the single-channel Excel2ColorScheme form."""
import os

from pyrevit import forms, script  # pyright: ignore
from System.Collections.ObjectModel import ObservableCollection  # pyright: ignore
from System.Windows.Media import SolidColorBrush, Color as MediaColor  # pyright: ignore
from System.Windows.Media.Animation import Storyboard  # pyright: ignore

from Autodesk.Revit import DB  # pyright: ignore

from EnneadTab import NOTIFICATION
from EnneadTab.REVIT import REVIT_COLOR_SCHEME

_XAML_PATH = os.path.join(os.path.dirname(__file__), "single_channel_form.xaml")
_SAMPLES_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "samples"))


class _Row(object):
    """View-model row for the color table DataGrid."""
    def __init__(self, name, hex_color, action):
        self.Name = name
        self.Hex = hex_color
        self.Action = action
        self.Brush = _hex_to_brush(hex_color) if hex_color else SolidColorBrush(MediaColor.FromRgb(0xEE, 0xEE, 0xEE))


def _hex_to_brush(hex_color):
    try:
        h = str(hex_color).lstrip("#")
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return SolidColorBrush(MediaColor.FromRgb(r, g, b))
    except (ValueError, IndexError, TypeError):
        return SolidColorBrush(MediaColor.FromRgb(0xEE, 0xEE, 0xEE))


def _get_all_color_schemes(doc):
    """Return list of (display_name, DB.ColorFillScheme element)."""
    out = []
    coll = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_ColorFillSchema)
    for cs in coll.WhereElementIsNotElementType().ToElements():
        out.append((cs.Name, cs))
    out.sort(key=lambda pair: pair[0])
    return out


def _extract_scheme_entries(scheme):
    """Return [(name, '#rrggbb'), ...] from a ColorFillScheme."""
    out = []
    for entry in scheme.GetEntries():
        try:
            color = entry.Color
            hex_color = "#{:02x}{:02x}{:02x}".format(
                int(color.Red), int(color.Green), int(color.Blue))
            out.append((entry.GetStringValue(), hex_color))
        except Exception:
            continue
    return out


class SingleChannelForm(forms.WPFWindow):
    def __init__(self, doc):
        forms.WPFWindow.__init__(self, _XAML_PATH)
        self._doc = doc
        self._color_dict = None         # parsed Excel content
        self._diagnostics = []          # most recent parsing diagnostics
        self._all_schemes = _get_all_color_schemes(doc)
        self._color_table_items = ObservableCollection[object]()
        self.ColorTableGrid.ItemsSource = self._color_table_items

        # Populate scheme dropdown
        self.SchemeCombo.ItemsSource = [name for name, _el in self._all_schemes]

        # Restore last settings if present
        self._settings = REVIT_COLOR_SCHEME.load_dialog_settings(doc) or {}
        last_single = self._settings.get("single", {}) if isinstance(self._settings.get("single"), dict) else {}
        last_path = self._settings.get("lastExcelPath", "")
        last_sheet = self._settings.get("lastWorksheet", "")
        last_scheme = last_single.get("schemeName", "")
        last_param = last_single.get("parameterName", "")

        if last_path and os.path.exists(last_path):
            self.ExcelPathBox.Text = last_path
            self._load_worksheet_list(last_path)
            if last_sheet and last_sheet in [w for w in self.WorksheetCombo.Items]:
                self.WorksheetCombo.SelectedItem = last_sheet
        if last_scheme and last_scheme in [n for n, _ in self._all_schemes]:
            self.SchemeCombo.SelectedItem = last_scheme

        # Prefill parameter: prefer saved value, else office-standard dept default (never blank)
        param_text = last_param
        if not param_text:
            param_text = REVIT_COLOR_SCHEME.OFFICE_STD_DEPT_PARAMETER
        self.ParameterOverrideBox.Text = param_text

        self._refresh_preview()

    # --- event handlers (XAML wires by name) -------------------------------

    def BrowseExcelButton_Click(self, sender, args):
        path = forms.pick_file(file_ext="xlsx;xls")
        if not path:
            return
        self.ExcelPathBox.Text = path
        self._load_worksheet_list(path)
        self._refresh_preview()

    def WorksheetCombo_SelectionChanged(self, sender, args):
        self._refresh_preview()

    def SchemeCombo_SelectionChanged(self, sender, args):
        # Parameter box always stays prefilled; never blank.
        if not self.ParameterOverrideBox.Text:
            self.ParameterOverrideBox.Text = REVIT_COLOR_SCHEME.OFFICE_STD_DEPT_PARAMETER
        self._refresh_preview()

    def ParameterOverrideBox_TextChanged(self, sender, args):
        # Just refresh enable state -- parameter override doesn't affect parsing/diff
        self._update_apply_button()

    def DownloadSampleButton_Click(self, sender, args):
        NOTIFICATION.messenger(
            "To get a single-channel Excel file, run the ColorScheme2Excel button first "
            "(ACE panel > ColorScheme pulldown > ColorScheme2Excel). "
            "That exports the target scheme to Excel. "
            "Then come back here and Browse to that exported file."
        )

    def mouse_down_main_panel(self, sender, args):
        self.DragMove()

    def CloseButton_Click(self, sender, args):
        self.Close()

    def CancelButton_Click(self, sender, args):
        self.Close()

    def ApplyButton_Click(self, sender, args):
        scheme_name = self.SchemeCombo.SelectedItem
        if not scheme_name or self._color_dict is None:
            return

        scheme_el = next((el for n, el in self._all_schemes if n == scheme_name), None)
        if scheme_el is None:
            NOTIFICATION.messenger("Scheme '{}' not found in document.".format(scheme_name))
            return

        t = DB.Transaction(self._doc, "Excel2ColorScheme (Single)")
        t.Start()
        try:
            added, updated, _skipped = REVIT_COLOR_SCHEME.apply_color_dict_to_scheme(
                self._doc, scheme_el, self._color_dict
            )

            # Persist settings in the same transaction
            self._settings["lastExcelPath"] = self.ExcelPathBox.Text
            self._settings["lastWorksheet"] = self.WorksheetCombo.SelectedItem or ""
            self._settings["mode"] = "single"
            self._settings.setdefault("single", {})
            self._settings["single"]["schemeName"] = scheme_name
            self._settings["single"]["parameterName"] = self.ParameterOverrideBox.Text or ""
            REVIT_COLOR_SCHEME.save_dialog_settings(self._doc, self._settings)

            t.Commit()
            NOTIFICATION.messenger(
                "Scheme '{}' updated.\nAdded: {} | Updated: {}".format(
                    scheme_name, added, updated
                )
            )
            self.Close()
        except Exception as ex:
            t.RollBack()
            NOTIFICATION.messenger("Failed: {}".format(ex))

    # --- internals --------------------------------------------------------

    def _load_worksheet_list(self, excel_path):
        from EnneadTab import EXCEL
        try:
            names = EXCEL.get_all_worksheets(excel_path) or []
        except Exception as ex:
            NOTIFICATION.messenger("Cannot read worksheets: {}".format(ex))
            names = []
        self.WorksheetCombo.ItemsSource = names

    def _refresh_preview(self):
        excel_path = self.ExcelPathBox.Text
        worksheet = self.WorksheetCombo.SelectedItem
        scheme_name = self.SchemeCombo.SelectedItem

        self._color_dict = None
        self._diagnostics = []
        self._color_table_items.Clear()
        self._set_badges(0, 0, 0, 0)
        self.DiagnosticBlock.Text = ""
        self.StatusText.Text = ""

        if not (excel_path and worksheet):
            self._update_apply_button()
            return

        try:
            color_dict, diagnostics = REVIT_COLOR_SCHEME.parse_single_channel_excel(
                excel_path, worksheet
            )
        except Exception as ex:
            self.DiagnosticBlock.Text = "Excel read failed: {}".format(ex)
            self._update_apply_button()
            return

        self._color_dict = color_dict
        self._diagnostics = diagnostics

        if diagnostics:
            self.DiagnosticBlock.Text = "\n".join(diagnostics)

        if color_dict is None:
            self._update_apply_button()
            return

        # Compute diff if a scheme is picked
        if scheme_name:
            scheme_el = next((el for n, el in self._all_schemes if n == scheme_name), None)
            if scheme_el is not None:
                entries = _extract_scheme_entries(scheme_el)
                diff = REVIT_COLOR_SCHEME.compute_scheme_diff(color_dict, entries)
                add_n = sum(1 for r in diff if r[1] == "add")
                upd_n = sum(1 for r in diff if r[1] == "update")
                unc_n = sum(1 for r in diff if r[1] == "unchanged")
                orph_n = sum(1 for r in diff if r[1] == "orphan")
                self._set_badges(add_n, upd_n, unc_n, orph_n)
                for row in diff:
                    name, action, _old, new = row
                    self._color_table_items.Add(_Row(name, new or row[2], action))
            else:
                for name, hex_color in color_dict.items():
                    self._color_table_items.Add(_Row(name, hex_color, u"\u2014"))
        else:
            for name, hex_color in color_dict.items():
                self._color_table_items.Add(_Row(name, hex_color, u"\u2014"))

        self._update_apply_button()

    def _set_badges(self, add_n, update_n, unchanged_n, orphan_n):
        self.AddBadge.Text = u"\u25cf Add {}".format(add_n)              # BLACK CIRCLE
        self.UpdateBadge.Text = u"\u21bb Update {}".format(update_n)     # CLOCKWISE OPEN CIRCLE ARROW
        self.UnchangedBadge.Text = u"\u00b7 Unchanged {}".format(unchanged_n)  # MIDDLE DOT
        self.OrphanBadge.Text = u"\u26a0 Orphan {}".format(orphan_n)    # WARNING SIGN

    def _update_apply_button(self):
        # Enable when all decision points pass
        excel_ok = bool(self.ExcelPathBox.Text)
        sheet_ok = bool(self.WorksheetCombo.SelectedItem)
        scheme_ok = bool(self.SchemeCombo.SelectedItem)
        parse_ok = self._color_dict is not None and len(self._color_dict) > 0

        ready = excel_ok and sheet_ok and scheme_ok and parse_ok
        self.ApplyButton.IsEnabled = ready

        # Trigger the glow storyboard when ready
        if ready:
            sb = self.Resources["ApplyGlow"]
            sb.Begin(self.ApplyButton, True)

        if not ready:
            missing = []
            if not excel_ok: missing.append("Excel file")
            if not sheet_ok: missing.append("worksheet")
            if not scheme_ok: missing.append("target scheme")
            if not parse_ok and excel_ok and sheet_ok: missing.append("valid Excel data")
            if missing:
                self.StatusText.Text = "Pick: " + ", ".join(missing)


def show(doc):
    """Entry point called from the wrapper script."""
    SingleChannelForm(doc).ShowDialog()
