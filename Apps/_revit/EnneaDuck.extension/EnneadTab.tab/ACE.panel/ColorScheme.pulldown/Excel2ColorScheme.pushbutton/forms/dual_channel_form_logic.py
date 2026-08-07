# -*- coding: utf-8 -*-
"""Event handlers and view-model for the dual-channel Excel2ColorScheme form."""
import os

from pyrevit import forms  # pyright: ignore
from System.Collections.ObjectModel import ObservableCollection  # pyright: ignore
from System.Windows.Media import SolidColorBrush, Color as MediaColor  # pyright: ignore

from Autodesk.Revit import DB  # pyright: ignore

from EnneadTab import NOTIFICATION, COLOR
from EnneadTab.REVIT import REVIT_COLOR_SCHEME

_XAML_PATH = os.path.join(os.path.dirname(__file__), "dual_channel_form.xaml")
_SAMPLES_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "samples"))


class _Row(object):
    def __init__(self, name, hex_color, action):
        self.Name = name
        self.Hex = hex_color
        self.Action = action
        self.Brush = _hex_to_brush(hex_color) if hex_color else SolidColorBrush(MediaColor.FromRgb(0xEE, 0xEE, 0xEE))


def _hex_to_brush(hex_color):
    try:
        h = str(hex_color).lstrip("#")
        return SolidColorBrush(MediaColor.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
    except (ValueError, IndexError, TypeError):
        return SolidColorBrush(MediaColor.FromRgb(0xEE, 0xEE, 0xEE))


def _get_all_color_schemes(doc):
    out = []
    coll = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_ColorFillSchema)
    for cs in coll.WhereElementIsNotElementType().ToElements():
        out.append((cs.Name, cs))
    out.sort(key=lambda pair: pair[0])
    return out


def _extract_scheme_entries(scheme):
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


def _fuzzy_default_scheme(schemes, keyword):
    """Return the first scheme name containing keyword (case-insensitive), or empty."""
    kw = keyword.lower()
    for name, _el in schemes:
        if kw in name.lower():
            return name
    return ""


class DualChannelForm(forms.WPFWindow):
    def __init__(self, doc):
        forms.WPFWindow.__init__(self, _XAML_PATH)
        self._doc = doc
        self._parsed = None             # {"dept": dict, "program": dict} or None
        self._diagnostics = []
        self._all_schemes = _get_all_color_schemes(doc)
        self._dept_items = ObservableCollection[object]()
        self._prog_items = ObservableCollection[object]()
        self.DeptColorGrid.ItemsSource = self._dept_items
        self.ProgColorGrid.ItemsSource = self._prog_items

        scheme_names = [n for n, _ in self._all_schemes]
        self.DeptSchemeCombo.ItemsSource = scheme_names
        self.ProgSchemeCombo.ItemsSource = scheme_names

        # Restore last settings
        self._settings = REVIT_COLOR_SCHEME.load_dialog_settings(doc) or {}
        last_dual = self._settings.get("dual", {}) if isinstance(self._settings.get("dual"), dict) else {}
        last_path = self._settings.get("lastExcelPath", "")
        last_sheet = self._settings.get("lastWorksheet", "")

        if last_path and os.path.exists(last_path):
            self.ExcelPathBox.Text = last_path
            self._load_worksheet_list(last_path)
            if last_sheet and last_sheet in [w for w in self.WorksheetCombo.Items]:
                self.WorksheetCombo.SelectedItem = last_sheet

        # Department defaults: saved value -> office standard constant (never blank)
        dept_scheme = last_dual.get("deptSchemeName") or _fuzzy_default_scheme(self._all_schemes, "Department")
        if dept_scheme in scheme_names:
            self.DeptSchemeCombo.SelectedItem = dept_scheme
        dept_param = last_dual.get("deptParameterName", "")
        if not dept_param:
            dept_param = REVIT_COLOR_SCHEME.OFFICE_STD_DEPT_PARAMETER
        self.DeptParameterBox.Text = dept_param

        # Program defaults: saved value -> office standard constant (never blank)
        prog_scheme = last_dual.get("programSchemeName") or _fuzzy_default_scheme(self._all_schemes, "Program")
        if prog_scheme in scheme_names:
            self.ProgSchemeCombo.SelectedItem = prog_scheme
        prog_param = last_dual.get("programParameterName", "")
        if not prog_param:
            prog_param = REVIT_COLOR_SCHEME.OFFICE_STD_PROGRAM_PARAMETER
        self.ProgParameterBox.Text = prog_param

        self._refresh_preview()

    # --- handlers ----------------------------------------------------------

    def BrowseExcelButton_Click(self, sender, args):
        path = forms.pick_file(file_ext="xlsx;xls")
        if not path:
            return
        self.ExcelPathBox.Text = path
        self._load_worksheet_list(path)
        self._refresh_preview()

    def WorksheetCombo_SelectionChanged(self, sender, args): self._refresh_preview()

    def DeptSchemeCombo_SelectionChanged(self, sender, args):
        # On scheme change, fill parameter box with office-std default if blank
        if not self.DeptParameterBox.Text:
            self.DeptParameterBox.Text = REVIT_COLOR_SCHEME.OFFICE_STD_DEPT_PARAMETER
        self._refresh_preview()

    def ProgSchemeCombo_SelectionChanged(self, sender, args):
        # On scheme change, fill parameter box with office-std default if blank
        if not self.ProgParameterBox.Text:
            self.ProgParameterBox.Text = REVIT_COLOR_SCHEME.OFFICE_STD_PROGRAM_PARAMETER
        self._refresh_preview()

    def DeptParameterBox_TextChanged(self, sender, args): self._update_apply_button()
    def ProgParameterBox_TextChanged(self, sender, args): self._update_apply_button()

    def DownloadSampleButton_Click(self, sender, args):
        src = os.path.join(_SAMPLES_DIR, "Sample ColorScheme (Dual Channel).xlsx")
        dst = forms.save_file(file_ext="xlsx",
                              default_name="Sample ColorScheme (Dual Channel)")
        if not dst:
            return
        import shutil
        shutil.copyfile(src, dst)
        NOTIFICATION.messenger("Sample written to:\n{}".format(dst))
        try:
            os.startfile(dst)
        except Exception:
            pass

    def mouse_down_main_panel(self, sender, args):
        self.DragMove()

    def CloseButton_Click(self, sender, args):
        self.Close()

    def CancelButton_Click(self, sender, args):
        self.Close()

    def ApplyButton_Click(self, sender, args):
        dept_name = self.DeptSchemeCombo.SelectedItem
        prog_name = self.ProgSchemeCombo.SelectedItem
        if not (dept_name and prog_name and self._parsed):
            return

        dept_el = next((el for n, el in self._all_schemes if n == dept_name), None)
        prog_el = next((el for n, el in self._all_schemes if n == prog_name), None)
        if dept_el is None or prog_el is None:
            NOTIFICATION.messenger("One or both schemes not found in document.")
            return

        t = DB.Transaction(self._doc, "Excel2ColorScheme (Dual)")
        t.Start()
        try:
            d_add, d_upd, _ = REVIT_COLOR_SCHEME.apply_color_dict_to_scheme(
                self._doc, dept_el, self._parsed["dept"]
            )
            p_add, p_upd, _ = REVIT_COLOR_SCHEME.apply_color_dict_to_scheme(
                self._doc, prog_el, self._parsed["program"]
            )

            # Persist
            self._settings["lastExcelPath"] = self.ExcelPathBox.Text
            self._settings["lastWorksheet"] = self.WorksheetCombo.SelectedItem or ""
            self._settings["mode"] = "dual"
            self._settings.setdefault("dual", {})
            self._settings["dual"].update({
                "deptSchemeName": dept_name,
                "deptParameterName": self.DeptParameterBox.Text or "",
                "programSchemeName": prog_name,
                "programParameterName": self.ProgParameterBox.Text or "",
            })
            REVIT_COLOR_SCHEME.save_dialog_settings(self._doc, self._settings)

            t.Commit()
            NOTIFICATION.messenger(
                u"Applied:\n  Dept '{}': +{} / \u0394{}\n  Program '{}': +{} / \u0394{}".format(
                    dept_name, d_add, d_upd, prog_name, p_add, p_upd
                )
            )
            self.Close()
        except Exception as ex:
            t.RollBack()
            NOTIFICATION.messenger("Apply failed (rolled back both schemes): {}".format(ex))

    # --- internals ---------------------------------------------------------

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

        self._parsed = None
        self._dept_items.Clear()
        self._prog_items.Clear()
        self._zero_badges()

        if not (excel_path and worksheet):
            self._update_apply_button()
            return

        try:
            raw = COLOR.get_color_template_data(template=excel_path, worksheet=worksheet)
        except Exception as ex:
            NOTIFICATION.messenger("Excel read failed: {}".format(ex))
            self._update_apply_button()
            return

        # raw = {"department_color_map": {name: {"abbr": ..., "color": rgb}}, "program_color_map": {...}}
        dept_color_map = raw.get("department_color_map", {}) or {}
        prog_color_map = raw.get("program_color_map", {}) or {}

        # Convert each map to {name: "#rrggbb"}, skipping entries with bad colors.
        dept_dict = {}
        for name, info in dept_color_map.items():
            hex_color = REVIT_COLOR_SCHEME._rgb_tuple_to_hex(info.get("color"))
            if hex_color:
                dept_dict[name] = hex_color

        prog_dict = {}
        for name, info in prog_color_map.items():
            hex_color = REVIT_COLOR_SCHEME._rgb_tuple_to_hex(info.get("color"))
            if hex_color:
                prog_dict[name] = hex_color

        if not dept_dict and not prog_dict:
            self._update_apply_button()
            return

        self._parsed = {"dept": dept_dict, "program": prog_dict}

        for kind, items, badges_setter, combo in (
            ("dept", self._dept_items, self._set_dept_badges, self.DeptSchemeCombo),
            ("program", self._prog_items, self._set_prog_badges, self.ProgSchemeCombo),
        ):
            color_dict = self._parsed[kind]
            scheme_name = combo.SelectedItem
            scheme_el = next((el for n, el in self._all_schemes if n == scheme_name), None) if scheme_name else None
            if scheme_el is not None:
                entries = _extract_scheme_entries(scheme_el)
                diff = REVIT_COLOR_SCHEME.compute_scheme_diff(color_dict, entries)
                a = sum(1 for r in diff if r[1] == "add")
                u = sum(1 for r in diff if r[1] == "update")
                uc = sum(1 for r in diff if r[1] == "unchanged")
                o = sum(1 for r in diff if r[1] == "orphan")
                badges_setter(a, u, uc, o)
                for row in diff:
                    name, action, _old, new = row
                    items.Add(_Row(name, new or row[2], action))
            else:
                for name, hex_color in color_dict.items():
                    items.Add(_Row(name, hex_color, u"\u2014"))

        self._update_apply_button()

    def _zero_badges(self):
        self._set_dept_badges(0, 0, 0, 0)
        self._set_prog_badges(0, 0, 0, 0)

    def _set_dept_badges(self, a, u, uc, o):
        self.DeptAddBadge.Text = u"\u25cf Add {}".format(a)              # BLACK CIRCLE
        self.DeptUpdateBadge.Text = u"\u21bb Update {}".format(u)        # CLOCKWISE OPEN CIRCLE ARROW
        self.DeptUnchangedBadge.Text = u"\u00b7 Unchanged {}".format(uc) # MIDDLE DOT
        self.DeptOrphanBadge.Text = u"\u26a0 Orphan {}".format(o)        # WARNING SIGN

    def _set_prog_badges(self, a, u, uc, o):
        self.ProgAddBadge.Text = u"\u25cf Add {}".format(a)              # BLACK CIRCLE
        self.ProgUpdateBadge.Text = u"\u21bb Update {}".format(u)        # CLOCKWISE OPEN CIRCLE ARROW
        self.ProgUnchangedBadge.Text = u"\u00b7 Unchanged {}".format(uc) # MIDDLE DOT
        self.ProgOrphanBadge.Text = u"\u26a0 Orphan {}".format(o)        # WARNING SIGN

    def _update_apply_button(self):
        excel_ok = bool(self.ExcelPathBox.Text)
        sheet_ok = bool(self.WorksheetCombo.SelectedItem)
        dept_ok = bool(self.DeptSchemeCombo.SelectedItem)
        prog_ok = bool(self.ProgSchemeCombo.SelectedItem)
        parse_ok = self._parsed is not None and (self._parsed["dept"] or self._parsed["program"])

        ready = excel_ok and sheet_ok and dept_ok and prog_ok and parse_ok
        self.ApplyButton.IsEnabled = ready
        if ready:
            sb = self.Resources["ApplyGlow"]
            sb.Begin(self.ApplyButton, True)


def show(doc):
    DualChannelForm(doc).ShowDialog()
