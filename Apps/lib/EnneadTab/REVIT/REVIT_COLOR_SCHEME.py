#!/usr/bin/python
# -*- coding: utf-8 -*-


import os
import sys

# Ensure parent lib/EnneadTab is on sys.path for sibling imports
_root = os.path.abspath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.append(_root)

import NOTIFICATION, COLOR, OUTPUT

# Revit-only names: set safe defaults so CPython import (for testing) succeeds.
UIDOC = None
DOC = None

try:
    import REVIT_SELECTION
    import REVIT_APPLICATION
    from Autodesk.Revit import DB # pyright: ignore
    from Autodesk.Revit import UI # pyright: ignore

    UIDOC = REVIT_APPLICATION.get_uidoc()
    DOC = REVIT_APPLICATION.get_doc()
    from pyrevit import script
except:
    pass



class ColorSchemeUpdater:
    """Manages updates to Revit color schemes from external template data.
    
    Args:
        doc (Document): The Revit document containing color schemes
        naming_map (dict): Mapping between excel data keys and Revit scheme names
        excel_path (str): Path to the excel template file
        is_remove_unused (bool): Whether to remove unused entries. Defaults to False
    """
    
    def __init__(self, doc, naming_map, excel_path, is_remove_unused = False):
        self.doc = doc
        self.naming_map = naming_map
        self.excel_path = excel_path
        self.is_remove_unused = is_remove_unused
        self.output = script.get_output()
    
    def load_color_template_from_excel(self):
        """Updates color schemes using data from template excel file.
        
        Loads color data from excel and updates or creates color scheme entries
        accordingly. Notifies user upon completion.
        """
        # Load data from color excel
        data = COLOR.get_color_template_data(self.excel_path)

        # Update color scheme, create if not exist, update color if exist
        t = DB.Transaction(self.doc, "Update Color Scheme")
        t.Start()
        for key, value in self.naming_map.items():
            if isinstance(value, str):
                value = [value]
            for color_scheme_name in value:
                self.update_color_scheme(data, key, color_scheme_name)
        t.Commit()
        
        NOTIFICATION.messenger("Color Scheme Updated!")
        print ("Finish updating Color Scheme")
        OUTPUT.display_output_on_browser()

    def update_color_scheme(self, data, lookup_key, color_scheme_name):
        """Updates a specific color scheme with template data.
        
        Args:
            data (dict): Color template data from excel
            lookup_key (str): Key to find matching data in template
            color_scheme_name (str): Name of the color scheme to update
        """
        if not data:
            NOTIFICATION.messenger("No data found in the template excel file.")
            print ("No data found in the template excel file.")
            return
        if not color_scheme_name:
            return
        color_schemes = get_color_schemes_by_name(color_scheme_name)
        if not color_schemes:
            print ("cannot find color scheme {}".format(color_scheme_name))
            NOTIFICATION.messenger("Color Scheme [{}] not found!\nCheck spelling".format(color_scheme_name))
            return

        for color_scheme in color_schemes:
            self.output.print_md("#Working on color scheme [{}]".format(color_scheme.Name))
        
            department_data = data[lookup_key]
            if not department_data:
                NOTIFICATION.messenger("No data found in the template excel file in [{}]".format(lookup_key))
                print ("No data found in the template excel file in [{}]".format(lookup_key))
                return

            is_abbr = False
            if "abbr" in lookup_key:
                lookup_key = lookup_key.replace("_abbr", "")
                is_abbr = True


            #  is abbr, then use abbr as the driver key
            if is_abbr:
                temp_data = {}
                for key, value in department_data.items():
                    abbr = value["abbr"]
                    temp_data[abbr] = value
                department_data = temp_data
            
            try:
                sample_entry = list(color_scheme.GetEntries())[0]
            except:
                NOTIFICATION.messenger("Please at least have one placeholder entry in the color scheme...")
                return
            storage_type = sample_entry.StorageType

            current_entry_names = [x.GetStringValue() for x in color_scheme.GetEntries()]
            if self.is_remove_unused:
                self.remove_non_used_entry(color_scheme)
            self.add_missing_entry(color_scheme, department_data, current_entry_names, storage_type)
            self.update_entry_color(color_scheme, department_data)

            # end of updaing single color_scheme

    @staticmethod
    def markdown_text(text, colorRGB):
        """Formats text with color for markdown output.
        
        Args:
            text (str): Text to format
            colorRGB (tuple): RGB color values
            
        Returns:
            str: HTML formatted text with color
        """
        return '<span style="color:rgb{};">{}</span>'.format(str(tuple(colorRGB)), text)


    def remove_non_used_entry(self, color_scheme):
        """Removes unused entries from color scheme.
        
        Args:
            color_scheme (ColorFillScheme): The color scheme to clean up
        """
        for existing_entry in color_scheme.GetEntries():
            if color_scheme.CanRemoveEntry (existing_entry):
                color_scheme.RemoveEntry(existing_entry)
                entry_title = existing_entry.GetStringValue()
                self.output.print_md("**---** entry [{}] removed{}".format(entry_title, ", not used" if existing_entry.IsInUse else ""))

    def add_missing_entry(self, color_scheme, department_data, current_entry_names, storage_type):
        """Adds new entries to color scheme that exist in template but not in Revit.
        
        Args:
            color_scheme (ColorFillScheme): Target color scheme
            department_data (dict): Template data for departments
            current_entry_names (list): Existing entry names
            storage_type (StorageType): Storage type for new entries
        """
        for department in department_data.keys():
            if department not in current_entry_names:
                entry = DB.ColorFillSchemeEntry(storage_type)
                entry.Color = COLOR.tuple_to_color(department_data[department]["color"])
                entry.SetStringValue(department)
                entry.FillPatternId = REVIT_SELECTION.get_solid_fill_pattern_id(self.doc)
                color_scheme.AddEntry(entry)
                self.output.print_md("**+++** entry [{}] added with **{}**".format(department, 
                                                                                   self.markdown_text("COLOR RGB={}".format(department_data[department]["color"]), department_data[department]["color"])))

    def update_entry_color(self, color_scheme, department_data):
        """Updates colors of existing entries to match template.
        
        Args:
            color_scheme (ColorFillScheme): Color scheme to update
            department_data (dict): Template color data
        """
        for existing_entry in color_scheme.GetEntries():
            entry_title = existing_entry.GetStringValue()
            existing_color = existing_entry.Color
            
            lookup_data = department_data.get(entry_title, None)
            if not lookup_data:
                
                self.output.print_md("###  ??? entry [{}] in current area scheme not found in template excel. Are you defining a new entry? Or the spelling is different?\nThis entry is skipped for now.\n".format(entry_title))
                print ("\n")
                continue
            
            lookup_color = COLOR.tuple_to_color(lookup_data["color"])
            
            if COLOR.is_same_color(existing_color, lookup_color):
                continue
            
            old_color = (existing_entry.Color.Red, existing_entry.Color.Green, existing_entry.Color.Blue)
            existing_entry.Color = lookup_color
            color_scheme.UpdateEntry(existing_entry)
            self.output.print_md("**$$$** entry [{}] updated from **{}** to **{}**".format(entry_title, 
                                                                                           self.markdown_text("OLD COLOR RGB={}".format(old_color), old_color), 
                                                                                           self.markdown_text("NEW COLOR RGB={}".format(lookup_data["color"]), lookup_data["color"])))

def get_color_schemes_by_name(scheme_name, doc = DOC):
    """Retrieves a color scheme by its name.
    
    Args:
        scheme_name (str): Name of the color scheme to find
        doc (Document): The Revit document to query. Defaults to active document
    """
    color_schemes = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_ColorFillSchema).WhereElementIsNotElementType().ToElements()
    color_schemes = [x for x in color_schemes if x.Name == scheme_name]
    return color_schemes    
    

def _get_area_scheme_name(color_scheme, doc=DOC):
    """Returns the associated Area Scheme name for a ColorFillScheme if available."""
    try:
        area_scheme_id = color_scheme.AreaSchemeId
    except AttributeError:
        return None
    if not area_scheme_id or area_scheme_id == DB.ElementId.InvalidElementId:
        return None
    area_scheme = doc.GetElement(area_scheme_id) if doc else None
    if not area_scheme:
        return None
    return area_scheme.Name


def _parse_display_scheme_name(scheme_identifier):
    """Parses display name of format '[AreaScheme] SchemeName'."""
    if not scheme_identifier or scheme_identifier[0] != "[":
        return None, scheme_identifier
    closing_index = scheme_identifier.find("]")
    if closing_index <= 1:
        return None, scheme_identifier
    area_scheme = scheme_identifier[1:closing_index]
    scheme_name = scheme_identifier[closing_index + 1:].strip()
    return area_scheme, scheme_name


def get_color_scheme_by_name(scheme_identifier, doc = DOC):
    """Retrieves a color scheme by its name.
    
    Args:
        scheme_identifier (str or ColorFillScheme): Name (or display name) of the color scheme to find
        doc (Document): The Revit document to query. Defaults to active document
        
    Returns:
        ColorFillScheme: The matching color scheme, or None if not found
    """
    if hasattr(scheme_identifier, "GetEntries"):
        return scheme_identifier
    if not scheme_identifier:
        return None

    area_prefix, scheme_name = _parse_display_scheme_name(scheme_identifier)
    color_schemes = get_color_schemes_by_name(scheme_name, doc)
    if area_prefix:
        color_schemes = [scheme for scheme in color_schemes if _get_area_scheme_name(scheme, doc) == area_prefix]
    if len(color_schemes)== 0:
        print ("Cannot find the color scheme [{}].\nMaybe you renamed your color scheme recently? Talk to SZ for update.".format(scheme_identifier))
        NOTIFICATION.messenger(main_text = "Cannot find the color scheme [{}].\nMaybe you renamed your color scheme recently? Talk to SZ for update.".format(scheme_identifier))
        return

    
    if len(color_schemes) > 1 :
        print ("Found more than one color scheme with the name [{}].\nNeed better naming.".format(scheme_identifier))
        NOTIFICATION.messenger(main_text = "Found more than one color scheme with the name [{}].\nNeed better naming.".format(scheme_identifier))
        return
    
    return color_schemes[0]

def pick_color_scheme(doc = DOC,
                      title = "Select the color scheme",
                      button_name = "Select",
                      multiselect = False,
                      return_scheme = False):
    """Displays UI for selecting color schemes.
    
    If a color scheme is tied to an Area Scheme, the display text will be
    formatted as "[AreaScheme] ColorScheme". Otherwise only the color scheme
    name is shown. The returned value always remains the color scheme name.
    
    Args:
        doc (Document): The Revit document to query. Defaults to active document
        title (str): Dialog title. Defaults to "Select the color scheme"
        button_name (str): Button text. Defaults to "Select"
        multiselect (bool): Allow multiple selection. Defaults to False
        
    Returns:
        str/ColorFillScheme or list: Selected name(s) (default) or scheme object(s)
    """
    from pyrevit import forms

    class ColorSchemeOption(forms.TemplateListItem):
        def __init__(self, scheme, doc, return_scheme):
            if return_scheme:
                self.item = scheme
            else:
                area_scheme_name = _get_area_scheme_name(scheme, doc)
                if area_scheme_name:
                    self.item = "[{}] {}".format(area_scheme_name, scheme.Name)
                else:
                    self.item = scheme.Name
            area_scheme_name = _get_area_scheme_name(scheme, doc)
            if area_scheme_name:
                self._display_name = "[{}] {}".format(area_scheme_name, scheme.Name)
            else:
                self._display_name = scheme.Name

        @property
        def name(self):
            return self._display_name

    color_schemes = DB.FilteredElementCollector(doc)\
                        .OfCategory(DB.BuiltInCategory.OST_ColorFillSchema)\
                        .WhereElementIsNotElementType()\
                        .ToElements()
    options = [ColorSchemeOption(x, doc, return_scheme) for x in color_schemes]
    options.sort(key=lambda opt: opt.name)
    return forms.SelectFromList.show(options, multiselect=multiselect, title=title, button_name=button_name)

def pick_color_schemes(doc = DOC,
                       title = "Select the color scheme",
                       button_name = "Select",
                       return_scheme = False):
    """Wrapper for picking multiple color schemes.
    
    Args:
        doc (Document): The Revit document to query. Defaults to active document
        title (str): Dialog title. Defaults to "Select the color scheme"
        button_name (str): Button text. Defaults to "Select"
        
    Returns:
        list: Selected names (default) or scheme objects, or None if canceled
    """
    return pick_color_scheme(doc, title, button_name, True, return_scheme)

def load_color_template(doc, naming_map, excel_path, is_remove_unused = False):
    """Updates color schemes from office template excel file.
    
    Excel Requirements:
    - Save as .xls format (not .xlsx)
    - Column headers must be:
        A: Department
        B: Department Abbr.
        C: Department Color
        D: Program
        E: Program Abbr.
        F: Program Color
    
    Args:
        doc (Document): The Revit document to update
        naming_map (dict): Maps excel sections to Revit scheme names
        excel_path (str): Path to template excel file
        is_remove_unused (bool): Remove unused entries. Defaults to False
        
    Example:
        naming_map = {
            "department_color_map": "Primary_Department Category",
            "program_color_map": "Primary_Department Program Type"
        }
    """
    updater = ColorSchemeUpdater(doc, naming_map, excel_path, is_remove_unused)
    updater.load_color_template_from_excel()


# ---------------------------------------------------------------------------
# Excel -> color dict parsers (Phase 2 firm-wide Excel2ColorScheme dialog)
# ---------------------------------------------------------------------------

# Office-standard parameter names used by the dual-channel dialog defaults.
OFFICE_STD_DEPT_PARAMETER = "Area_$Department"
OFFICE_STD_PROGRAM_PARAMETER = "Area_$Department_Program Type"

_SINGLE_NAME_HEADER_ALIASES = ("parameter value", "entryname", "entry name")
_SINGLE_COLOR_HEADER_ALIASES = ("color", "color(no rgb)", "color (no rgb)")


def _norm_header(value):
    """Normalize a header cell value for case-insensitive, whitespace-tolerant matching."""
    if value is None:
        return ""
    return str(value).strip().lower()


def _detect_header_row(raw_data, max_rows, name_aliases, color_aliases):
    """Scan first `max_rows` rows for a row containing both a name header and color header."""
    for row in range(1, max_rows + 1):
        headers = {}
        for (r, c), cell in raw_data.items():
            if r == row:
                headers[c] = _norm_header(cell.get("value"))
        if not headers:
            continue
        has_name = any(h in name_aliases for h in headers.values())
        has_color = any(h in color_aliases for h in headers.values())
        if has_name and has_color:
            return row, headers
    return None, {}


def _rgb_tuple_to_hex(rgb):
    """Convert (r, g, b) ints to '#rrggbb'. Returns None if any component is None."""
    if not rgb:
        return None
    r, g, b = rgb[0], rgb[1], rgb[2]
    if r is None or g is None or b is None:
        return None
    try:
        return "#{:02x}{:02x}{:02x}".format(int(r), int(g), int(b))
    except (TypeError, ValueError):
        return None


def _parse_single_channel_raw(raw_data, worksheet_name):
    """Pure parser for the single-channel Excel format.

    Input: raw_data dict shaped {(row, col): {'value': ..., 'color': (r,g,b)}}
           as returned by EXCEL.read_data_from_excel(..., return_dict=True).
    Returns: (color_dict, diagnostics)
        color_dict: {entry_name: '#rrggbb'} or None if file/header-level failure.
        diagnostics: list of human-readable warning strings.
    """
    diagnostics = []
    if not raw_data:
        diagnostics.append(
            "Excel read returned no data for worksheet '{}'.\n"
            "Possible causes: file moved or locked, worksheet renamed/removed "
            "after picking, or ExcelHandler did not respond.".format(worksheet_name)
        )
        return None, diagnostics

    header_row, headers = _detect_header_row(
        raw_data, max_rows=5,
        name_aliases=_SINGLE_NAME_HEADER_ALIASES,
        color_aliases=_SINGLE_COLOR_HEADER_ALIASES,
    )
    if header_row is None:
        # Show what we did find for easier debugging
        first_row_cells = sorted(
            ((c, _norm_header(cell.get("value"))) for (r, c), cell in raw_data.items() if r == 1),
            key=lambda x: x[0],
        )
        diagnostics.append(
            "Could not detect header row in first 5 rows of worksheet '{}'.\n"
            "Expected: 'Parameter Value' (or 'EntryName') + 'Color' columns.\n"
            "Row 1 had: {}".format(worksheet_name, first_row_cells)
        )
        return None, diagnostics

    name_col = None
    color_col = None
    for col, header_text in headers.items():
        if name_col is None and header_text in _SINGLE_NAME_HEADER_ALIASES:
            name_col = col
        if color_col is None and header_text in _SINGLE_COLOR_HEADER_ALIASES:
            color_col = col

    data_rows = sorted({r for (r, _c) in raw_data.keys() if r > header_row})

    color_dict = {}
    skipped = []
    for row in data_rows:
        name_cell = raw_data.get((row, name_col), {})
        color_cell = raw_data.get((row, color_col), {})

        entry_name = name_cell.get("value")
        if not entry_name or str(entry_name).strip() in ("", "None"):
            skipped.append("row {}: entry name cell is empty".format(row))
            continue

        hex_color = _rgb_tuple_to_hex(color_cell.get("color"))

        if not hex_color:
            value_text = color_cell.get("value")
            try:
                string_type = basestring  # IronPython 2 / Python 2
            except NameError:
                string_type = str
            if isinstance(value_text, string_type) and value_text.startswith("#"):
                hex_color = value_text

        if not hex_color:
            text_preview = color_cell.get("value", "")
            skipped.append(
                "row {} ('{}'): color cell has no fill RGB and text '{}' "
                "is not a '#RRGGBB' hex. If you painted the cell with "
                "Conditional Formatting or a Theme color, replace it with "
                "a direct Fill Color.".format(row, entry_name, text_preview)
            )
            continue

        color_dict[str(entry_name).strip()] = hex_color

    if skipped:
        head = skipped[:10]
        extra = len(skipped) - len(head)
        msg = "Skipped {} data row(s) in worksheet '{}':\n  - {}".format(
            len(skipped), worksheet_name, "\n  - ".join(head)
        )
        if extra > 0:
            msg += "\n  ... and {} more row(s) with the same kind of issue".format(extra)
        diagnostics.append(msg)

    return color_dict, diagnostics


def parse_single_channel_excel(filepath, worksheet):
    """File I/O wrapper around _parse_single_channel_raw.

    Reads the worksheet via EXCEL.read_data_from_excel then delegates to the
    pure parser. Only usable from IronPython under Revit (because of EXCEL).
    """
    # Lazy import to keep the pure parser CPython-importable.
    from EnneadTab import EXCEL
    raw_data = EXCEL.read_data_from_excel(filepath, worksheet=worksheet, return_dict=True)
    return _parse_single_channel_raw(raw_data, worksheet)


def compute_scheme_diff(color_dict, scheme_entries):
    """Compute the per-entry diff between an Excel-derived color_dict and current scheme state.

    Args:
        color_dict: {name: '#rrggbb'} from Excel parsing.
        scheme_entries: list of (name, '#rrggbb') tuples extracted from a Revit color scheme.
            (Pre-extraction makes this function pure -- callers in Revit do
             [(e.GetStringValue(), '#%02x%02x%02x' % (e.Color.Red, e.Color.Green, e.Color.Blue))
              for e in scheme.GetEntries()].)

    Returns:
        list of (name, action, old_color, new_color) where action in:
            'add'       - in color_dict, not in scheme
            'update'    - in both, hex differs (case-insensitive)
            'unchanged' - in both, hex matches
            'orphan'    - in scheme, not in color_dict

        Sort: non-orphan first (alphabetical), then orphans (alphabetical).
    """
    scheme_map = {name: hex_color for name, hex_color in scheme_entries}

    rows = []
    for name, new_hex in color_dict.items():
        if name in scheme_map:
            old_hex = scheme_map[name]
            if old_hex.lower() == new_hex.lower():
                rows.append((name, "unchanged", old_hex, new_hex))
            else:
                rows.append((name, "update", old_hex, new_hex))
        else:
            rows.append((name, "add", None, new_hex))

    for name, old_hex in scheme_map.items():
        if name not in color_dict:
            rows.append((name, "orphan", old_hex, None))

    def sort_key(row):
        is_orphan = 1 if row[1] == "orphan" else 0
        return (is_orphan, row[0])

    rows.sort(key=sort_key)
    return rows


# Prefix applied to scheme entries that have no counterpart in the Excel
# definition. Visible in the Revit legend and reversible: if the stripped name
# later reappears in Excel the entry is restored to solid fill + Excel color.
# Same literal as the Kips Bay load_color_template script (TODO-1149 lift).
ORPHAN_PREFIX = "NO MATCH IN EXCEL-"

_FORBIDDEN_ENTRY_CHARS = {
    '\\': '-', ':': '-', '{': '-', '}': '-', '[': '-', ']': '-',
    '|': '-', ';': '-', '<': '', '>': '', '?': '', '`': '', '~': '',
}


def sanitize_entry_name(entry_name):
    """Return the Revit-legal form of an Excel entry name (forbidden chars replaced/stripped)."""
    sanitized = str(entry_name)
    for forbidden, replacement in _FORBIDDEN_ENTRY_CHARS.items():
        sanitized = sanitized.replace(forbidden, replacement)
    while '--' in sanitized:
        sanitized = sanitized.replace('--', '-')
    while '  ' in sanitized:
        sanitized = sanitized.replace('  ', ' ')
    return sanitized.strip(' -')


def plan_orphan_action(current_name, excel_names):
    """Decide what to do with one scheme entry. Pure, so it is testable in CPython.

    Args:
        current_name: the entry's current string value in Revit.
        excel_names: set of sanitized entry names present in the Excel definition.

    Returns:
        (action, new_name) where action is one of:
            'matched'  - name is in Excel, nothing to rename
            'mark'     - not in Excel, not yet prefixed: rename to new_name, no-fill
            'keep'     - already prefixed and still not in Excel (idempotent)
            'restore'  - prefixed, but Excel now has the base name: rename to new_name
    """
    if current_name.startswith(ORPHAN_PREFIX):
        base = current_name[len(ORPHAN_PREFIX):]
        if base in excel_names:
            return ("restore", base)
        return ("keep", None)
    if current_name in excel_names:
        return ("matched", None)
    return ("mark", ORPHAN_PREFIX + current_name)


def mark_orphan_entries(doc, color_scheme, excel_name_to_hex):
    """Rename/restore scheme entries against the Excel definition. CALLER owns the transaction.

    Orphans (in the scheme, not in Excel) get ORPHAN_PREFIX and no-fill; prefixed
    entries whose base name is back in Excel are restored (solid fill + Excel color).
    Idempotent. Returns (marked, restored).

    Args:
        excel_name_to_hex: {sanitized_name: '#rrggbb'} for every valid Excel entry.
    """
    from Autodesk.Revit import DB  # pyright: ignore
    from EnneadTab import COLOR
    from EnneadTab.REVIT import REVIT_SELECTION

    invalid_id = DB.ElementId.InvalidElementId
    excel_names = set(excel_name_to_hex.keys())
    marked = 0
    restored = 0

    # Snapshot first: mutating while iterating a live collection can skip entries.
    for entry in list(color_scheme.GetEntries()):
        try:
            current_name = entry.GetStringValue()
        except Exception:
            continue
        action, new_name = plan_orphan_action(current_name, excel_names)
        try:
            if action == "mark":
                entry.SetStringValue(new_name)
                entry.FillPatternId = invalid_id
                color_scheme.UpdateEntry(entry)
                marked += 1
                print("  Orphan marked '{}' -> '{}'".format(current_name, new_name))
            elif action == "keep":
                if entry.FillPatternId != invalid_id:
                    entry.FillPatternId = invalid_id
                    color_scheme.UpdateEntry(entry)
            elif action == "restore":
                entry.SetStringValue(new_name)
                entry.Color = COLOR.tuple_to_color(COLOR.hex_to_rgb(excel_name_to_hex[new_name]))
                entry.FillPatternId = REVIT_SELECTION.get_solid_fill_pattern_id(doc)
                color_scheme.UpdateEntry(entry)
                restored += 1
                print("  Orphan restored '{}' -> '{}'".format(current_name, new_name))
        except Exception as ex:
            print("  ERROR orphan-marking '{}': {}".format(current_name, str(ex)))
    return (marked, restored)


def apply_color_dict_to_scheme(doc, color_scheme, color_dict, mark_orphans=False):
    """Apply a {name: hex} dict to one Revit color scheme.

    CALLER must wrap in DB.Transaction. This function does NOT manage transactions.

    Returns (added_count, updated_count, skipped_count). Prints per-entry actions
    to the pyRevit output for the user to see.

    With mark_orphans=True (opt-in; off by default until verified in live Revit) scheme entries that are absent from color_dict
    are renamed with ORPHAN_PREFIX and set to no-fill, and previously marked ones
    whose name is back in Excel are restored (TODO-1149). Orphans are never deleted.

    Entry names with forbidden characters (\\ : { } [ ] | ; < > ? ` ~) are
    sanitized -- backslash/colon/brackets/pipe/semicolon become '-', the rest
    are stripped.
    """
    # Lazy imports keep this CPython-importable for static analysis.
    from Autodesk.Revit import DB  # pyright: ignore
    from EnneadTab import COLOR
    from EnneadTab.REVIT import REVIT_SELECTION

    if not color_dict:
        print("apply_color_dict_to_scheme: empty color_dict, nothing to do.")
        return (0, 0, 0)

    try:
        sample_entry = list(color_scheme.GetEntries())[0]
        storage_type = sample_entry.StorageType
    except (IndexError, AttributeError):
        print("apply_color_dict_to_scheme: scheme has no entries; "
              "add at least one placeholder entry in Revit first.")
        return (0, 0, 0)

    if mark_orphans:
        # Must run BEFORE the add/update loop: a restored entry has to be back
        # under its real name or the loop would add a duplicate of it.
        excel_name_to_hex = {}
        for k, v in color_dict.items():
            if not k or not str(k).strip() or k == "None" or str(k).strip().startswith('#'):
                continue
            if not v or not str(v).startswith('#'):
                continue
            excel_name_to_hex[sanitize_entry_name(k)] = v
        mark_orphan_entries(doc, color_scheme, excel_name_to_hex)

    current_entries = {x.GetStringValue(): x for x in color_scheme.GetEntries()}

    added = 0
    updated = 0
    skipped = 0

    for entry_name, hex_color in color_dict.items():
        if not entry_name or not str(entry_name).strip() or entry_name == "None":
            skipped += 1
            continue
        if str(entry_name).strip().startswith('#'):
            skipped += 1
            continue
        if not hex_color or not str(hex_color).startswith('#'):
            skipped += 1
            continue

        sanitized = sanitize_entry_name(entry_name)

        if sanitized != str(entry_name):
            print("  Sanitized '{}' -> '{}'".format(entry_name, sanitized))

        rgb = COLOR.hex_to_rgb(hex_color)
        revit_color = COLOR.tuple_to_color(rgb)

        if sanitized in current_entries:
            existing = current_entries[sanitized]
            old_color = existing.Color
            if not COLOR.is_same_color(old_color, revit_color):
                existing.Color = revit_color
                color_scheme.UpdateEntry(existing)
                updated += 1
                print("  Updated '{}'".format(sanitized))
        else:
            try:
                entry = DB.ColorFillSchemeEntry(storage_type)
                entry.Color = revit_color
                entry.SetStringValue(sanitized)
                entry.FillPatternId = REVIT_SELECTION.get_solid_fill_pattern_id(doc)
                color_scheme.AddEntry(entry)
                added += 1
                print("  Added '{}'".format(sanitized))
            except Exception as ex:
                print("  ERROR adding '{}': {}".format(sanitized, str(ex)))
                skipped += 1

    return (added, updated, skipped)


# ---------------------------------------------------------------------------
# Dialog settings persistence (DataStorage + ExtensibleStorage)
# ---------------------------------------------------------------------------

# IMMUTABLE -- changing this orphans every project's persisted settings.
_DIALOG_SETTINGS_SCHEMA_GUID = "af7549c5-290a-4836-8993-2c48b0f99f90"
_DIALOG_SETTINGS_SCHEMA_NAME = "EnneadTab_Excel2ColorScheme_Settings"
_DIALOG_SETTINGS_FIELD_NAME = "SettingsJson"
_DIALOG_SETTINGS_SCHEMA_VERSION = 1


def _get_or_define_settings_schema():
    """Return the ExtensibleStorage Schema, defining it if not already in this session."""
    from Autodesk.Revit import DB  # pyright: ignore
    import System  # pyright: ignore

    schema_guid = System.Guid(_DIALOG_SETTINGS_SCHEMA_GUID)
    schema = DB.ExtensibleStorage.Schema.Lookup(schema_guid)
    if schema is not None:
        return schema

    builder = DB.ExtensibleStorage.SchemaBuilder(schema_guid)
    builder.SetSchemaName(_DIALOG_SETTINGS_SCHEMA_NAME)
    builder.SetReadAccessLevel(DB.ExtensibleStorage.AccessLevel.Public)
    builder.SetWriteAccessLevel(DB.ExtensibleStorage.AccessLevel.Public)
    builder.SetVendorId("EnneadArchitects")

    field_builder = builder.AddSimpleField(_DIALOG_SETTINGS_FIELD_NAME, System.String)
    field_builder.SetDocumentation("Excel2ColorScheme dialog settings (JSON)")

    return builder.Finish()


def _find_settings_datastorage(doc):
    """Return the DataStorage element holding our settings, or None if not present."""
    from Autodesk.Revit import DB  # pyright: ignore
    schema = _get_or_define_settings_schema()
    collector = DB.FilteredElementCollector(doc).OfClass(DB.ExtensibleStorage.DataStorage)
    for storage in collector:
        entity = storage.GetEntity(schema)
        if entity is not None and entity.IsValid():
            return storage
    return None


def load_dialog_settings(doc):
    """Load per-document dialog settings. Returns dict (possibly empty) -- never None."""
    import json
    schema = _get_or_define_settings_schema()
    storage = _find_settings_datastorage(doc)
    if storage is None:
        return {}
    entity = storage.GetEntity(schema)
    if entity is None or not entity.IsValid():
        return {}
    try:
        raw = entity.Get[str](_DIALOG_SETTINGS_FIELD_NAME)
    except Exception as ex:
        print("load_dialog_settings: failed to read field: {}".format(ex))
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception as ex:
        print("load_dialog_settings: JSON decode failed: {}".format(ex))
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_dialog_settings(doc, settings):
    """Persist settings dict to DataStorage. CALLER must wrap in DB.Transaction.

    Auto-tags with schema version. Existing DataStorage element is reused;
    a new one is created on first save.
    """
    from Autodesk.Revit import DB  # pyright: ignore
    import json

    if not isinstance(settings, dict):
        raise ValueError("save_dialog_settings: settings must be a dict")

    settings = dict(settings)  # shallow copy so we don't mutate caller's dict
    settings.setdefault("version", _DIALOG_SETTINGS_SCHEMA_VERSION)

    schema = _get_or_define_settings_schema()
    storage = _find_settings_datastorage(doc)
    if storage is None:
        storage = DB.ExtensibleStorage.DataStorage.Create(doc)

    entity = DB.ExtensibleStorage.Entity(schema)
    entity.Set[str](_DIALOG_SETTINGS_FIELD_NAME, json.dumps(settings))
    storage.SetEntity(entity)