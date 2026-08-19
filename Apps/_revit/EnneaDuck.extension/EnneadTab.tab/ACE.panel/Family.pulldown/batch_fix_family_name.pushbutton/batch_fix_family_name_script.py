#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Batch rename family names to the Healthcare standard convention.

Format: CATEGORY_MainDescription_FIRM[_AdditionalInfo][_HOSTING]

Edit the components inline in the grid, check the families to fix, and
Apply. Analysis and naming-rules helpers are one click away."""
__title__ = "Batch Format\nFamily Name"

import os
import traceback

from Autodesk.Revit import DB  # pyright: ignore
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent  # pyright: ignore
from Autodesk.Revit.Exceptions import InvalidOperationException  # pyright: ignore
from pyrevit.forms import WPFWindow

import System  # pyright: ignore

import proDUCKtion  # pyright: ignore
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION, OUTPUT, IMAGE
from EnneadTab.REVIT import REVIT_APPLICATION

import family_rename_row
from family_rename_row import FamilyRenameRow, FAMILY_NAME_PATTERN

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()
__persistentengine__ = True


def show_naming_rules():
    """Display the naming convention rules image."""
    script_dir = os.path.dirname(__file__)
    image_path = os.path.join(script_dir, "naming_rule.png")

    output = OUTPUT.get_output()
    output.write("HealthCare Family Naming Rules:", OUTPUT.Style.Title)
    output.write(image_path)

    HostingMethodMapper.print_desired_mapping()
    CategoryMapper.print_desired_mapping()
    output.plot()


class BaseMapper:
    """Base class for mapping and validation functionality."""

    mapping = {}  # To be overridden by child classes

    @classmethod
    def get_abbreviation(cls, key):
        """Get abbreviation for a given key."""
        return cls.mapping.get(key, "not defined AHHHHHHH ASK Sen for help!!!!!! He is a idiot.  " + key)

    @classmethod
    def print_desired_mapping(cls):
        """Prints the desired mapping to abbreviations."""
        output = OUTPUT.get_output()
        output.write("Desired Mapping for {}:".format(cls.__name__), OUTPUT.Style.Title)
        output.write(["{} -> {}".format(k, v) for k, v in sorted(cls.mapping.items())])
        output.plot()


class HostingMethodMapper(BaseMapper):
    """Maps and validates family hosting methods.

    Features:
        - Maps standard hosting methods to abbreviations
        - Validates family hosting against name suffix
        - Analyzes document-wide hosting behaviors
    """

    mapping = {
        "Wall": "WH",
        "Ceiling": "CH",
        "Floor": "FH",
        "Face": "FC",

        # Non-hosted cases
        "Not Hosted": None,
        "Invalid": None,
        "": None,

    }


    @staticmethod
    def get_hosting_abbreviation(family):
        """Get hosting method from family."""
        hosting_param = family.Parameter[DB.BuiltInParameter.FAMILY_HOSTING_BEHAVIOR]
        if not hosting_param:
            return None
        return HostingMethodMapper.mapping.get(hosting_param.AsValueString(), None)


    @staticmethod
    def validate_hosting_method(family, show_log = False):
        """
        Validates if the family's hosting method matches its name
        Args:
            family: Revit family element
            family_name (str): Name of the family
            name_match: Regex match object from family name pattern
        Returns:
            bool: True if hosting method is valid, False otherwise
        """
        # Get actual hosting method from family

        actual_abbr = HostingMethodMapper.get_hosting_abbreviation(family)
        if not actual_abbr:
            return True # ok to be not hosting

        # Get hosting method from name (last group in regex)
        name_match = FAMILY_NAME_PATTERN.match(family.Name)
        if not name_match:
            return True  # Skip validation if name doesn't match pattern, becasue it is ok to not have hosting abbreviation in the name

        groups = name_match.groups()
        name_hosting_abbr = groups[-1][1:] if groups[-1] else None  # Remove leading underscore if exists

        # Compare actual vs name-specified hosting
        if actual_abbr != name_hosting_abbr:
            # Only flag as error if:
            # 1. Family is hosted but name doesn't include correct hosting suffix
            # 2. Name includes hosting suffix but family isn't actually hosted
            if actual_abbr and show_log:  # Case 1
                print("[{}]: Hosting method mismatch - Name: {}, Actual: {} ({})".format(
                    family.Name,
                    name_hosting_abbr or "None",
                    actual_abbr,
                    family.Parameter[DB.BuiltInParameter.FAMILY_HOSTING_BEHAVIOR].AsValueString()
                ))
                return False
            elif name_hosting_abbr and show_log:  # Case 2
                print("[{}]: Family is not hosted but name suggests {} hosting".format(
                    family.Name,
                    name_hosting_abbr
                ))
                return False

        return True

    @classmethod
    def analyze_hosting_behaviors(cls):
        """Analyze hosting behaviors of families in the document."""
        doc = REVIT_APPLICATION.get_doc()
        families = DB.FilteredElementCollector(doc).OfClass(DB.Family).ToElements()

        output = OUTPUT.get_output()
        output.write("Analyzing Family Hosting Behaviors:", OUTPUT.Style.Title)

        # Create dictionary to group families by hosting type
        hosting_groups = {}

        for family in families:
            if not family.FamilyCategory or family.FamilyCategory.CategoryType != DB.CategoryType.Model:
                continue

            hosting_param = family.Parameter[DB.BuiltInParameter.FAMILY_HOSTING_BEHAVIOR]
            if not hosting_param:
                continue

            actual_hosting = hosting_param.AsValueString()
            actual_abbr = cls.get_abbreviation(actual_hosting)

            # Group by hosting abbreviation
            group_key = actual_hosting if actual_abbr else "Non-Hosted"
            if group_key not in hosting_groups:
                hosting_groups[group_key] = []

            hosting_groups[group_key].append(family.Name)

        # Output groups with subTitles - hosted families first, then non-hosted
        # Get all groups except "Non-Hosted"
        hosted_groups = {k: v for k, v in hosting_groups.items() if k != "Non-Hosted"}

        # Print hosted families first
        for abbr, families in sorted(hosted_groups.items()):
            output.write("\n{} Hosted Families ({}):".format(
                abbr,
                len(families)
            ), OUTPUT.Style.Subtitle)
            output.write(sorted(families))

        # Print non-hosted families last
        if "Non-Hosted" in hosting_groups:
            output.write("\nNon-Hosted Families ({}):".format(
                len(hosting_groups["Non-Hosted"])
            ), OUTPUT.Style.Subtitle)
            output.write(sorted(hosting_groups["Non-Hosted"]))

        output.plot()


class CategoryMapper(BaseMapper):
    """Maps Revit categories to standardized abbreviations."""

    mapping = {
        # Architectural Core Elements
        "Walls": "WALL",
        "Floors": "FLOR",
        "Ceilings": "CLNG",
        "Roofs": "ROOF",
        "Doors": "DOOR",
        "Windows": "WIND",

        # Architectural Circulation
        "Stairs": "STR",
        "Ramps": "RAMP",
        "Railings": "RAIL",
        "Balusters": "BLST",

        # Structural Elements
        "Columns": "CLMN",
        "Structural Columns": "SCLM",
        "Structural Foundations": "FNDN",
        "Structural Framing": "STRX",
        "Structural Connections": "SCON",
        "Structural Rebar": "RBAR",
        "Structural Stiffeners": "STIF",
        "Structural Tendons": "TEND",
        "Structural Trusses": "TRUS",

        # Bridge Components
        "Abutments": "ABUT",
        "Bearings": "BEAR",
        "Bridge Cables": "BCBL",
        "Bridge Decks": "BDCK",
        "Piers": "PIER",

        # Interior Elements
        "Casework": "CSWK",
        "Furniture": "FURN",
        "Furniture Systems": "FSYS",
        "Spaces": "SPCE",
        "Supports": "SUPP",

        # Equipment
        "Food Service Equipment": "FOOD",
        "Medical Equipment": "MEQP",
        "Specialty Equipment": "SEQP",
        "Nurse Call Devices": "NRSE",

        # MEP - Electrical
        "Electrical Equipment": "ELEC",
        "Electrical Fixtures": "ELFX",
        "Lighting Fixtures": "LITE",
        "Lighting Devices": "LDEV",
        "Security Devices": "SECU",
        "Communication Devices": "COMM",
        "Data Devices": "DATA",
        "Audio Visual Devices": "AVDV",
        "Fire Alarm Devices": "FIRE",
        "Wires": "WIRE",

        # MEP - Mechanical
        "Air Terminals": "ATRM",
        "Duct Accessories": "DACC",
        "Duct Fittings": "DFIT",
        "Duct Insulations": "DINS",
        "Duct Linings": "DLIN",
        "Ducts": "DUCT",
        "Mechanical Equipment": "MECH",
        "Mechanical Control Devices": "MCTL",
        "Zone Equipment": "ZEQP",

        # MEP - Plumbing
        "Plumbing": "PLBG",
        "Plumbing Equipment": "PEQP",
        "Plumbing Fixtures": "PFIX",
        "Pipe Accessories": "PACC",
        "Pipe Fittings": "PFIT",
        "Pipe Insulations": "PINS",
        "Pipes": "PIPE",
        "Sprinklers": "SPNK",

        # Distribution Systems
        "Cable Trays": "CTRY",
        "Conduits": "COND",
        "Curtain Panels": "CRTN",
        "Curtain Systems": "CSYS",
        "Curtain Wall Mullions": "MULL",

        # Site and Exterior
        "Entourage": "ETRG",
        "Hardscape": "HARD",
        "Parking": "PARK",
        "Planting": "PLNT",
        "Roads": "ROAD",
        "Site": "SITE",

        # Annotation Elements
        "Callout Heads": "CALL",
        "Detail Items": "DETL",
        "Elevation Marks": "ELEV",
        "Generic Annotations": "ANNO",
        "Generic Models": "GMOD",
        "Generic Annotation": "SYMBOL",
        "Grid Heads": "GRID",
        "Level Heads": "LEVL",
        "Section Marks": "SECT",
        "Span Direction Symbol": "SPAN",
        "Spot Elevation Symbols": "SPOT",
        "Title Blocks": "TITL",
        "View Reference": "VREF",
        "View Titles": "VTIT",

        # Special Elements
        "Expansion Joints": "EXPJ",
        "Mass": "MASS",
        "Parts": "PART",
        "Profiles": "PRFL",
        "Signage": "SIGN",
        "Temporary Structures": "TEMP",
        "Vibration Management": "VIBR",
    }

    @classmethod
    def add_tag_categories(cls):
        """Add TAG abbreviation for any category containing 'Tag'"""
        doc = REVIT_APPLICATION.get_doc()
        all_families = DB.FilteredElementCollector(doc).OfClass(DB.Family).ToElements()
        for family in all_families:
            if not family.FamilyCategory or family.FamilyCategory.CategoryType != DB.CategoryType.Model:
                continue
            category_name = family.FamilyCategory.Name
            if "Tag" in category_name and category_name not in cls.mapping:
                cls.mapping[category_name] = "TAG"

    @staticmethod
    def validate_category(family, show_log=False):
        """Validates if family category is supported and matches the name prefix"""
        family_name = family.Name
        if not family.FamilyCategory:
            if show_log:
                print("[{}]: Category is None, not supported.".format(family_name))
            return False

        family_category = family.FamilyCategory.Name
        abbreviation = CategoryMapper.get_abbreviation(family_category)
        if not abbreviation:
            if show_log:
                print("[{}] category [{}] not supported.".format(family_name, family_category))
            return False

        actual_prefix = family_name.split("_")[0]
        if actual_prefix != abbreviation:
            if show_log:
                print("[{}]: Category prefix should be [{}], found [{}]".format(
                    family_name, abbreviation, actual_prefix))
            return False

        return True

    @staticmethod
    def analyze_category_map():
        """Analyze and display category mapping status based on document families."""
        output = OUTPUT.get_output()
        output.write("Category Mapping Analysis:", OUTPUT.Style.Title)

        # Group categories
        registered_categories = {}  # Dict to store category counts
        unregistered_categories = {}

        all_families = DB.FilteredElementCollector(REVIT_APPLICATION.get_doc()).OfClass(DB.Family).ToElements()
        for family in all_families:
            if not family.FamilyCategory or family.FamilyCategory.CategoryType != DB.CategoryType.Model:
                continue

            category_name = family.FamilyCategory.Name

            # Skip if category name contains "Tag"
            if "Tag" in category_name:
                continue

            if category_name in CategoryMapper.mapping:
                registered_categories[category_name] = registered_categories.get(category_name, 0) + 1
            else:
                unregistered_categories[category_name] = unregistered_categories.get(category_name, 0) + 1

        # Output registered categories
        output.write("\nRegistered Categories ({}):".format(len(registered_categories)),
                    OUTPUT.Style.Subtitle)
        for category_name in sorted(registered_categories.keys()):
            output.write("    {} -> {} ({} families)".format(
                category_name,
                CategoryMapper.mapping[category_name],
                registered_categories[category_name]
            ))

        # Output unregistered categories
        output.write("\nUnregistered Categories ({}):".format(len(unregistered_categories)),
                    OUTPUT.Style.Subtitle)
        for category_name in sorted(unregistered_categories.keys()):
            output.write("    {} ({} families)".format(
                category_name,
                unregistered_categories[category_name]
            ))

        output.plot()

# Initialize CategoryMapper by calling class method after class definition
CategoryMapper.add_tag_categories()


def check_family_name_format(family, show_log=False):
    """Validates if family name follows the naming convention"""
    family_name = family.Name

    # Debug output for problematic names
    if show_log:
        match = FAMILY_NAME_PATTERN.match(family_name)
        if match:
            print("Groups found:", match.groups())
        else:
            print("No match for:", family_name)

    if not CategoryMapper.validate_category(family, show_log):
        return False

    # Validate hosting method using the mapper
    if not HostingMethodMapper.validate_hosting_method(family, show_log):
        return False

    return True

def get_families_with_wrong_prefix(doc):
    """Get list of families with incorrect or missing category prefix.

    Args:
        doc: Current Revit document

    Returns:
        list: Families where name prefix doesn't match current category or has no prefix
    """
    families_with_wrong_prefix = []

    for family in DB.FilteredElementCollector(doc).OfClass(DB.Family).ToElements():
        if not family.FamilyCategory:
            continue

        # Only process Model category families (exclude annotation categories)
        if family.FamilyCategory.CategoryType != DB.CategoryType.Model:
            continue

        family_name = family.Name
        family_category = family.FamilyCategory.Name

        # Get correct abbreviation for current category
        correct_abbreviation = CategoryMapper.get_abbreviation(family_category)
        if not correct_abbreviation:
            continue  # Skip unsupported categories

        # Check if family name has underscore (indicates it might have a prefix)
        if "_" in family_name:
            # Get current prefix from family name
            current_prefix = family_name.split("_")[0]

            # Check if prefix is wrong
            if current_prefix != correct_abbreviation:
                families_with_wrong_prefix.append(family)
        else:
            # No underscore means no prefix at all - needs to be added
            families_with_wrong_prefix.append(family)

    return families_with_wrong_prefix

def is_family_name_unique(family_name):
    doc = REVIT_APPLICATION.get_doc()
    return family_name not in set(f.Name for f in DB.FilteredElementCollector(doc).OfClass(DB.Family).ToElements())


class SimpleEventHandler(IExternalEventHandler):
    """Runs a passed-in function inside Revit's API context."""

    def __init__(self, do_this):
        self.do_this = do_this
        self.kwargs = None
        self.OUT = None

    def Execute(self, uiapp):
        try:
            try:
                self.OUT = self.do_this(*self.kwargs)
            except Exception as ex:
                # Surface the failure to the user instead of printing to an
                # invisible stream: a swallowed error here looks like the tool
                # did nothing ("no effect").
                tb = traceback.format_exc()
                print("apply failed")
                print(tb)
                try:
                    NOTIFICATION.messenger(
                        main_text="Apply failed: {}".format(ex))
                except Exception:
                    pass
        except InvalidOperationException:
            print("InvalidOperationException catched")

    def GetName(self):
        return "family rename external event"


def is_family_editable(family):
    """True if the current user can rename this family.

    Non-workshared docs: always True. Workshared docs: False when the
    element is owned/checked out by another user. Fail-open on any error
    so the guarded rename attempt decides the edge cases.
    """
    if not DOC.IsWorkshared:
        return True
    try:
        status = DB.WorksharingUtils.GetCheckoutStatus(DOC, family.Id)
        return status != DB.CheckoutStatus.OwnedByOtherUser
    except Exception:
        return True


def family_int_id(family):
    """Return a family's ElementId as a plain int (Revit 2026 uses .Value)."""
    try:
        return family.Id.Value
    except AttributeError:
        return family.Id.IntegerValue


def apply_renames(rows):
    """Rename each row's family to its new_name. Runs in API context.

    Skips families not editable by the current user (worksharing) and
    reports renamed / skipped / error counts. Idempotent against the LIVE
    family name so a second Apply (racing the grid reload) does not compare
    a stale row.current_name against an already-renamed family.
    """
    t = DB.Transaction(DOC, "Batch Format Family Names")
    t.Start()
    log = []
    ok = 0
    skipped = 0
    err = 0
    # Track names in Python so we never call DOC.Regenerate() inside the loop:
    # regenerating mid-transaction after a family rename corrupts the regen /
    # undo stack (journal: "Changing wrong atom in regeneration" +
    # "UndoMgr stacking is out of sync") and fatally crashes Revit on a
    # cloud-workshared model. Revit regenerates once at Commit.
    existing = set(f.Name for f in DB.FilteredElementCollector(DOC)
                   .OfClass(DB.Family).ToElements())
    for row in rows:
        target = row.new_name
        # Re-fetch the element by id here (inside the API context); the row
        # itself never holds the Revit element (see FamilyRenameRow).
        family = DOC.GetElement(DB.ElementId(row.family_id))
        if family is None:
            log.append("SKIPPED (not found): {}".format(row.current_name))
            skipped += 1
            continue
        if not is_family_editable(family):
            log.append("SKIPPED (owned by another user): {}".format(row.current_name))
            skipped += 1
            continue
        try:
            live_name = family.Name
            if target == live_name:
                continue  # already correctly named; idempotent no-op
            while target in existing and target != live_name:
                target = "{}*ConflictingName".format(target)
            if target == live_name:
                continue
            family.Name = target
            existing.discard(live_name)
            existing.add(target)
            log.append("{} ---> {}".format(live_name, target))
            ok += 1
        except Exception as e:
            log.append("FAILED {}: {}".format(row.current_name, e))
            err += 1
    t.Commit()

    output = OUTPUT.get_output()
    output.write("Batch Format Family Name Results:", OUTPUT.Style.Title)
    output.write("Renamed: {} | Skipped (not editable): {} | Errors: {}".format(
        ok, skipped, err), OUTPUT.Style.Subtitle)
    if log:
        output.write(log)
    output.plot()
    NOTIFICATION.messenger(
        main_text="Renamed {} | Skipped {} | Errors {}".format(ok, skipped, err),
        sticky=(err > 0))

    # No post-commit grid reload: reload_current_scope() runs a full family
    # FilteredElementCollector + per-family checks, and doing that on the API
    # thread right after a cloud checkout froze then crashed Revit. The proven
    # sibling (SuperRenamer) never reloads post-apply. The caller reads the
    # returned message; the user refreshes the list on demand via a scope button.
    return "Renamed {} | Skipped {} | Errors {}".format(ok, skipped, err)


def apply_prefix_only(family_ids):
    """Rewrite only the category prefix for the given families. API context.

    Takes family integer ids (not elements) and re-fetches each inside the
    API context, so no Revit element is held on a WPF-selected row. Skips
    families not editable by the current user (worksharing) and reports
    fixed / skipped / error counts.
    """
    t = DB.Transaction(DOC, "Fix Category Prefixes")
    t.Start()
    log = []
    ok = 0
    skipped = 0
    err = 0
    # Python-side name tracking; never DOC.Regenerate() inside the loop
    # (corrupts regen/undo state -> fatal crash on cloud-workshared models).
    existing = set(f.Name for f in DB.FilteredElementCollector(DOC)
                   .OfClass(DB.Family).ToElements())
    for fid in family_ids:
        family = DOC.GetElement(DB.ElementId(fid))
        if family is None:
            skipped += 1
            continue
        current = family.Name
        if not is_family_editable(family):
            log.append("SKIPPED (owned by another user): {}".format(current))
            skipped += 1
            continue
        try:
            abbr = CategoryMapper.get_abbreviation(family.FamilyCategory.Name)
            if "_" in current:
                parts = current.split("_")
                parts[0] = abbr
                new_name = "_".join(parts)
            else:
                new_name = "{}_{}".format(abbr, current)
            while new_name in existing and new_name != current:
                new_name = "{}*ConflictingName".format(new_name)
            if new_name == current:
                continue
            family.Name = new_name
            existing.discard(current)
            existing.add(new_name)
            log.append("{} ---> {}".format(current, new_name))
            ok += 1
        except Exception as e:
            log.append("FAILED {}: {}".format(current, e))
            err += 1
    t.Commit()

    output = OUTPUT.get_output()
    output.write("Fix Category Prefix Results:", OUTPUT.Style.Title)
    output.write("Fixed: {} | Skipped (not editable): {} | Errors: {}".format(
        ok, skipped, err), OUTPUT.Style.Subtitle)
    if log:
        output.write(log)
    output.plot()
    NOTIFICATION.messenger(
        main_text="Fixed {} | Skipped {} | Errors {}".format(ok, skipped, err))

    # No post-commit grid reload (see apply_renames): re-collecting families on
    # the API thread after a cloud checkout froze then crashed Revit.
    return "Fixed {} | Skipped {} | Errors {}".format(ok, skipped, err)


class BatchFormatFamilyNameWindow(WPFWindow):

    _instance = None

    def pre_actions(self):
        self.apply_handler = SimpleEventHandler(apply_renames)
        self.ext_event_apply = ExternalEvent.Create(self.apply_handler)
        self.prefix_handler = SimpleEventHandler(apply_prefix_only)
        self.ext_event_prefix = ExternalEvent.Create(self.prefix_handler)

    def __init__(self):
        self.pre_actions()
        WPFWindow.__init__(self, "BatchFormatFamilyName.xaml")
        self.Title = "EnneadTab Batch Format Family Name"
        self._form_closed = False
        BatchFormatFamilyNameWindow._instance = self
        self.Closed += self._on_closed

        try:
            logo_file = IMAGE.get_image_path_by_name("logo_vertical_light.png")
            self.set_image_source(self.logo_img, logo_file)
        except Exception:
            pass

        # Populate combo column item sources. Access via Columns[] rather than
        # x:Name attribute: pyRevit's WPFWindow does not reliably expose
        # x:Name on a DataGridComboBoxColumn as an attribute.
        self.main_grid.Columns[4].ItemsSource = family_rename_row.FIRM_OPTIONS
        self.main_grid.Columns[6].ItemsSource = family_rename_row.HOSTING_OPTIONS

        self.build_rows(self.collect_families(only_problematic=True))
        self.Show()

    def _on_closed(self, sender, e):
        # Mark closed for the _invoke_ui guard (covers X / Alt+F4, not just the
        # Close button) and release the single-instance reference so a later
        # launch opens a fresh window instead of stacking.
        self._form_closed = True
        if getattr(BatchFormatFamilyNameWindow, "_instance", None) is self:
            BatchFormatFamilyNameWindow._instance = None

    def _invoke_ui(self, fn):
        """Marshal a zero-arg callable onto the UI thread, safe after close."""
        if self._form_closed:
            return
        def _safe():
            if self._form_closed:
                return
            try:
                fn()
            except Exception as ex:
                print("dispatcher swallowed: {}".format(ex))
        try:
            self.Dispatcher.BeginInvoke(System.Action(_safe), [])
        except Exception as ex:
            print("dispatcher schedule failed: {}".format(ex))

    # ---- family collection -------------------------------------------
    def collect_families(self, only_problematic=True, from_selection=False):
        if from_selection:
            families = self.families_from_selection()
        else:
            families = [f for f in DB.FilteredElementCollector(DOC)
                        .OfClass(DB.Family).ToElements()
                        if f.FamilyCategory
                        and f.FamilyCategory.CategoryType == DB.CategoryType.Model]
        if only_problematic:
            families = [f for f in families
                        if (not family_rename_row.is_valid_family_name(f.Name))
                        or (not check_family_name_format(f))]
        return families

    def families_from_selection(self):
        result = {}
        for eid in UIDOC.Selection.GetElementIds():
            el = DOC.GetElement(eid)
            fam = None
            try:
                if isinstance(el, DB.Family):
                    fam = el
                elif hasattr(el, "Symbol") and el.Symbol:
                    fam = el.Symbol.Family
                elif isinstance(el, DB.FamilySymbol):
                    fam = el.Family
            except Exception:
                fam = None
            if fam and fam.FamilyCategory \
                    and fam.FamilyCategory.CategoryType == DB.CategoryType.Model:
                result[fam.Id.IntegerValue] = fam
        return list(result.values())

    def build_rows(self, families):
        rows = []
        for family in families:
            try:
                abbr = CategoryMapper.get_abbreviation(family.FamilyCategory.Name)
                host = HostingMethodMapper.get_hosting_abbreviation(family)
                row = FamilyRenameRow(family, abbr, host)
                row.is_checked = (row.new_name != row.current_name)
                rows.append(row)
            except Exception as e:
                print("skip {}: {}".format(getattr(family, "Name", "?"), e))
        rows.sort(key=lambda r: r.current_name)
        self.main_grid.ItemsSource = rows
        self.update_count()

    def refresh_grid(self):
        # Reassign ItemsSource (the proven pattern in super_exporter) instead
        # of Items.Refresh(): calling Refresh() during the DataGrid edit
        # transaction throws inside WPF and can leave the grid in a state that
        # fatally crashes Revit (CLR 0xE0434352) on the next interaction.
        # Reassign the SAME row objects so in-progress edits are preserved.
        rows = self.main_grid.ItemsSource
        self.main_grid.ItemsSource = None
        self.main_grid.ItemsSource = rows
        self.update_count()

    def update_count(self):
        rows = self.main_grid.ItemsSource or []
        checked = len([r for r in rows if r.is_checked])
        self.count_text.Text = "{} families loaded, {} checked.".format(len(rows), checked)

    def get_checked_rows(self):
        return [r for r in (self.main_grid.ItemsSource or []) if r.is_checked]

    def reload_current_scope(self):
        only_bad = not self.show_all_toggle.IsChecked
        self.build_rows(self.collect_families(only_problematic=only_bad))

    # ---- grid edit preview ---------------------------------------------
    @ERROR_HANDLE.try_catch_error()
    def grid_cell_edit_ending(self, sender, e):
        # IronPython does not reliably bind the DataGridEditAction enum type via
        # `from System.Windows.Controls import ...`; compare the member name instead.
        if str(e.EditAction) != "Commit":
            return
        row = e.Row.Item
        if row is None:
            return
        header = str(e.Column.Header)
        # Only the value columns affect the composed name. A checkbox ("Fix")
        # toggle also fires CellEditEnding, but it must NOT recompute/refresh:
        # reassigning ItemsSource mid-checkbox-commit re-enters the grid and
        # fatally crashes Revit. The checkbox's own binding updates is_checked.
        if header not in ("Description", "FIRM", "AddInfo", "Host", "New Name"):
            return
        # Duck-type the editing control instead of importing WPF types:
        # IronPython does not reliably bind TextBox/ComboBox via
        # `from System.Windows.Controls import ...` in this engine. A ComboBox
        # exposes SelectedItem; a TextBox does not. Both expose Text.
        editor = e.EditingElement
        value = None
        if editor is not None:
            selected = getattr(editor, "SelectedItem", None)
            if selected is not None:
                value = str(selected)
            else:
                value = getattr(editor, "Text", None)

        if value is not None:
            if header == "New Name":
                # Direct override: the user typed a final name. Use it as-is
                # and do NOT recompute from components (the override wins).
                row.new_name = value.strip()
                row.valid = "OK" if family_rename_row.is_valid_family_name(row.new_name) else "X"
                self._invoke_ui(self.refresh_grid)
                return
            if header == "Description":
                row.description = value.strip()
            elif header == "FIRM":
                row.firm = value.strip() or family_rename_row.DEFAULT_FIRM
            elif header == "AddInfo":
                row.additional = value.strip()
            elif header == "Host":
                row.hosting = value.strip()

        row.recompute()

        self._invoke_ui(self.refresh_grid)

    # ---- analysis + scope buttons ---------------------------------------
    @ERROR_HANDLE.try_catch_error()
    def analyze_hosting_click(self, sender, e):
        HostingMethodMapper.analyze_hosting_behaviors()

    @ERROR_HANDLE.try_catch_error()
    def analyze_category_click(self, sender, e):
        CategoryMapper.analyze_category_map()

    @ERROR_HANDLE.try_catch_error()
    def show_rules_click(self, sender, e):
        show_naming_rules()

    @ERROR_HANDLE.try_catch_error()
    def load_selection_click(self, sender, e):
        only_bad = not self.show_all_toggle.IsChecked
        fams = self.collect_families(only_problematic=only_bad, from_selection=True)
        if not fams:
            self.debug_textbox.Text = "No model families in current selection."
            return
        self.build_rows(fams)
        self.debug_textbox.Text = "Loaded {} families from selection.".format(len(fams))

    @ERROR_HANDLE.try_catch_error()
    def show_all_toggle_changed(self, sender, e):
        only_bad = not self.show_all_toggle.IsChecked
        self.build_rows(self.collect_families(only_problematic=only_bad))

    @ERROR_HANDLE.try_catch_error()
    def select_all_click(self, sender, e):
        for r in (self.main_grid.ItemsSource or []):
            r.is_checked = True
        self.refresh_grid()

    @ERROR_HANDLE.try_catch_error()
    def select_none_click(self, sender, e):
        for r in (self.main_grid.ItemsSource or []):
            r.is_checked = False
        self.refresh_grid()

    # ---- apply + prefix-only + close/drag --------------------------------
    @ERROR_HANDLE.try_catch_error()
    def apply_checked_click(self, sender, e):
        rows = self.get_checked_rows()
        if not rows:
            self.debug_textbox.Text = "Nothing checked."
            NOTIFICATION.messenger(main_text="Nothing checked to apply.")
            return
        valid_rows = [r for r in rows if r.valid == "OK" and r.new_name != r.current_name]
        invalid_count = len([r for r in rows if r.valid != "OK"])
        if not valid_rows:
            self.debug_textbox.Text = ("No applicable rows. {} checked row(s) have invalid "
                                       "names - edit their Description/fields first.".format(invalid_count))
            NOTIFICATION.messenger(main_text="No valid rows to apply.")
            return
        self.apply_handler.kwargs = (valid_rows,)
        self.ext_event_apply.Raise()
        # Read the handler result directly (SuperRenamer pattern) - no reload.
        res = self.apply_handler.OUT
        note = "Applied {} row(s)".format(len(valid_rows))
        if invalid_count:
            note += "; {} invalid skipped".format(invalid_count)
        note += ". Click a scope button (Show all / Load From Selection) to refresh the list."
        self.debug_textbox.Text = res if res else note

    @ERROR_HANDLE.try_catch_error()
    def fix_prefix_only_click(self, sender, e):
        checked = self.get_checked_rows()
        if checked:
            family_ids = [r.family_id for r in checked]
        else:
            family_ids = [family_int_id(f) for f in get_families_with_wrong_prefix(DOC)]
        if not family_ids:
            self.debug_textbox.Text = "No families with wrong/missing prefix."
            NOTIFICATION.messenger(main_text="No prefix fixes needed.")
            return
        self.prefix_handler.kwargs = (family_ids,)
        self.ext_event_prefix.Raise()
        res = self.prefix_handler.OUT
        self.debug_textbox.Text = (res if res else
                                   "Fixed {} prefix(es). Click a scope button to refresh.".format(
                                       len(family_ids)))

    def close_Click(self, sender, e):
        self._form_closed = True
        try:
            self.Close()
        except Exception as ex:
            print("close failed: {}".format(ex))

    def mouse_down_main_panel(self, sender, args):
        try:
            sender.DragMove()
        except Exception:
            pass


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main():
    # Single instance: the window is modeless on a persistent engine, so a
    # second launch would stack another live window + ExternalEvents over the
    # same grid. Focus the existing one instead of opening a duplicate.
    existing = getattr(BatchFormatFamilyNameWindow, "_instance", None)
    if existing is not None and not getattr(existing, "_form_closed", True):
        try:
            existing.Activate()
            return
        except Exception:
            pass
    BatchFormatFamilyNameWindow()


if __name__ == "__main__":
    main()
