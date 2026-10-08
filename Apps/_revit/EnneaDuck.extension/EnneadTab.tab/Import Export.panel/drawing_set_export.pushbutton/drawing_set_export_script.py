# -*- coding: utf-8 -*-
__title__ = "Drawing Set\nExport"
__doc__ = """Export a per-sheet drawing set for phone AR.

For each selected sheet with a placed floor plan, exports a 300-DPI plan image
(PNG) and a section-boxed 3D model of the sheet's level converted to .glb, then
uploads both to an ARVR room and writes drawings/manifest.json next to the files.
Tracked under ticket 7005 (sheet-anchored 3D for AR/VR)."""

import os
import re
import math
import json
from datetime import datetime

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System")
clr.AddReference("System.IO")

from Autodesk.Revit import DB
from Autodesk.Revit.UI import TaskDialog
from System.Diagnostics import Process, ProcessStartInfo
from System.Net import WebClient
from System.Security.Cryptography import SHA256Managed
from System.Windows.Controls import CheckBox
from System.Windows import Thickness

from pyrevit import revit, script
from EnneadTab import ARVR, NOTIFICATION, ERROR_HANDLE, LOG

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FT_TO_MM = 304.8

# Sheet-backdrop marker sizes (mm) for the AR paper anchor, from the anchor
# layout table in EnneadTab-ARVR (lib/paperAnchor/layout.ts). Emitted as
# markerMm when the titleblock paper matches; otherwise null so the phone
# falls back to the paper's physical size.
MARKER_MM_BY_PAPER = {
    "A4": 90,
    "LETTER": 90,
    "A3": 130,
    "TABLOID": 125,
    "11X17": 125,
    "ANSI B": 125,
}

# FBX -> .glb converter. Revit has no native glTF exporter; the reliable path
# is native FBX export (Document.Export + FBXExportOptions on the active
# section-boxed 3D view) converted by Facebook's FBX2glTF. The exe is looked
# for next to this script, then in the staging cache; if missing it is
# downloaded from the pinned release and verified by SHA256 before use.
FBX2GLTF_EXE_NAME = "FBX2glTF-windows-x64.exe"
FBX2GLTF_RELEASE_URL = ("https://github.com/facebookincubator/FBX2glTF/releases"
                        "/download/v0.9.7/" + FBX2GLTF_EXE_NAME)
FBX2GLTF_SHA256 = "8d90fb5e0a8d186a3d9a7ff8c75eaee541c3975ce4df0d80351f20092ae0877f"
FBX2GLTF_SIZE = 10550784

THREE_D_VIEW_PREFIX = "ARVR_DS_"
MANIFEST_VERSION = 1

logger = script.get_logger()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def sanitize_filename(name):
    """Strip characters illegal in Windows filenames."""
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()


def natural_sort_key(text):
    """Human sort: A2 < A10."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", text or "")]


def copy_to_clipboard(text):
    """Copy text to the Windows clipboard (best effort)."""
    try:
        from System.Windows import Clipboard
        Clipboard.SetText(text)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Model collection: sheets, plans, levels
# ---------------------------------------------------------------------------

@ERROR_HANDLE.try_catch_error()
def collect_sheets_with_plans(doc):
    """Return [(ViewSheet, [ViewPlan floor plans])] sorted by sheet number.

    Only sheets with at least one placed FloorPlan view are included --
    elevations, sections, and legends do not get a 3D model.
    """
    sheets = (DB.FilteredElementCollector(doc)
              .OfClass(DB.ViewSheet)
              .ToElements())
    result = []
    for sheet in sheets:
        if not sheet.SheetNumber:
            continue
        plans = []
        for view_id in sheet.GetAllPlacedViews():
            view = doc.GetElement(view_id)
            if (isinstance(view, DB.ViewPlan)
                    and view.ViewType == DB.ViewType.FloorPlan):
                plans.append(view)
        if plans:
            plans.sort(key=lambda v: v.Name or "")
            result.append((sheet, plans))
    result.sort(key=lambda item: natural_sort_key(item[0].SheetNumber))
    return result


@ERROR_HANDLE.try_catch_error()
def get_sorted_levels(doc):
    """Return all levels sorted by elevation (ascending)."""
    levels = (DB.FilteredElementCollector(doc)
              .OfClass(DB.Level)
              .ToElements())
    return sorted(levels, key=lambda l: l.Elevation)


# ---------------------------------------------------------------------------
# Titleblock paper size (for the anchor metadata)
# ---------------------------------------------------------------------------

@ERROR_HANDLE.try_catch_error()
def get_sheet_paper(doc, sheet):
    """Return (paper_designation, width_mm, height_mm) from the titleblock.

    Reads the "Sheet Width"/"Sheet Height" type parameters of the placed
    titleblock family and converts feet -> mm. Missing parameters give None
    sizes; the phone then uses the paper table fallback.
    """
    designation = "Unknown"
    width_mm = None
    height_mm = None
    try:
        titleblock = (DB.FilteredElementCollector(doc, sheet.Id)
                      .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
                      .WhereElementIsNotElementType()
                      .FirstElement())
        if titleblock is None:
            return designation, width_mm, height_mm
        symbol = titleblock.Symbol
        family_name = symbol.Family.Name if symbol and symbol.Family else ""
        type_name = symbol.Name if symbol else ""
        designation = (type_name or family_name or "Unknown").strip()
        for param_name, setter in (("Sheet Width", "width"), ("Sheet Height", "height")):
            try:
                param = symbol.LookupParameter(param_name)
                if param is not None and param.HasValue:
                    value_mm = param.AsDouble() * FT_TO_MM
                    if setter == "width":
                        width_mm = round(value_mm, 1)
                    else:
                        height_mm = round(value_mm, 1)
            except Exception:
                pass
    except Exception:
        pass
    return designation, width_mm, height_mm


def marker_mm_for_paper(designation):
    """Marker size in mm for a paper designation, else None."""
    key = re.sub(r"[^A-Z0-9]", "", (designation or "").upper())
    return MARKER_MM_BY_PAPER.get(key)


# ---------------------------------------------------------------------------
# Section box: crop the 3D view to one sheet's level
# ---------------------------------------------------------------------------

def union_model_bbox_xy(doc):
    """Union XY bbox of walls/floors/columns/roofs, padded 5%.

    Fallback when the floor plan's crop box is inactive or invalid.
    """
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    categories = (DB.BuiltInCategory.OST_Walls,
                  DB.BuiltInCategory.OST_Floors,
                  DB.BuiltInCategory.OST_StructuralColumns,
                  DB.BuiltInCategory.OST_Roofs)
    for bic in categories:
        collector = (DB.FilteredElementCollector(doc)
                     .OfCategory(bic)
                     .WhereElementIsNotElementType())
        for element in collector:
            try:
                bbox = element.get_BoundingBox(None)
            except Exception:
                continue
            if bbox is None:
                continue
            xmin = min(xmin, bbox.Min.X)
            ymin = min(ymin, bbox.Min.Y)
            xmax = max(xmax, bbox.Max.X)
            ymax = max(ymax, bbox.Max.Y)
    if xmin == float("inf"):
        return None
    pad_x = (xmax - xmin) * 0.05
    pad_y = (ymax - ymin) * 0.05
    return (xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y)


@ERROR_HANDLE.try_catch_error()
def compute_section_bbox(doc, plan_view, level, levels_sorted):
    """Build a BoundingBoxXYZ: XY from the plan's crop (or model union),
    Z from the level elevation to the next level up.

    Also returns (min_x_ft, min_y_ft) -- the section-box corner in model
    coordinates, used as the anchor origin so the phone can align the GLB
    to the sheet's printed plan.
    """
    min_x = min_y = max_x = max_y = None

    # Primary: the plan view's crop box. For plan views the crop box is
    # expressed in model coordinates; sanity-checked below.
    try:
        if plan_view.CropBoxActive:
            crop = plan_view.CropBox
            if (crop is not None and crop.Min.X < crop.Max.X
                    and crop.Min.Y < crop.Max.Y):
                min_x, min_y = crop.Min.X, crop.Min.Y
                max_x, max_y = crop.Max.X, crop.Max.Y
    except Exception:
        pass

    if min_x is None:
        union = union_model_bbox_xy(doc)
        if union is None:
            return None, None
        min_x, min_y, max_x, max_y = union

    z_min = level.Elevation - 1.0  # 1 ft below the level: catch slabs/plinths
    z_max = None
    for other in levels_sorted:
        if other.Elevation > level.Elevation + 1e-6:
            z_max = other.Elevation
            break
    if z_max is None:
        z_max = level.Elevation + 10.0  # topmost level: default one storey

    bbox = DB.BoundingBoxXYZ()
    bbox.Min = DB.XYZ(min_x, min_y, z_min)
    bbox.Max = DB.XYZ(max_x, max_y, z_max)
    return bbox, (min_x, min_y)


@ERROR_HANDLE.try_catch_error()
def get_or_create_section_3d(doc, sheet_number, bbox):
    """Reuse or create a 3D view named ARVR_DS_<sheet number> with the section box."""
    view_name = THREE_D_VIEW_PREFIX + sanitize_filename(sheet_number)
    existing = None
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View3D).ToElements():
        if view.Name == view_name and not view.IsTemplate:
            existing = view
            break

    trans = DB.Transaction(doc, "Drawing Set: section-boxed 3D view")
    trans.Start()
    try:
        if existing is None:
            view_family_type_id = None
            for vft in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType).ToElements():
                if vft.ViewFamily == DB.ViewFamily.ThreeDimensional:
                    view_family_type_id = vft.Id
                    break
            if view_family_type_id is None:
                trans.RollBack()
                return None
            view = DB.View3D.CreateIsometric(doc, view_family_type_id)
            view.Name = view_name
        else:
            view = existing
        view.SectionBox = bbox
        trans.Commit()
        return view
    except Exception:
        try:
            trans.RollBack()
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Sheet plan image export (300 DPI PNG)
# ---------------------------------------------------------------------------

@ERROR_HANDLE.try_catch_error()
def export_sheet_image(doc, sheet, output_dir, base_name):
    """Export the sheet as a 300-DPI PNG. Returns the .png path or None.

    Same technique as the proven AutoExporter: ImageExportOptions with the
    FilePath given extension-less (Revit appends its own suffix and a
    " - Sheet - " infix), then find-and-rename to the desired filename.
    """
    target = os.path.join(output_dir, base_name + ".png")
    if os.path.exists(target):
        os.remove(target)

    options = DB.ImageExportOptions()
    # Extension-less base: Revit appends "- Sheet - <name>.png" itself.
    options.FilePath = os.path.join(output_dir, base_name)
    options.ImageResolution = DB.ImageResolution.DPI_300
    options.FitDirection = DB.FitDirectionType.Horizontal
    options.ZoomType = DB.ZoomFitType.FitToPage
    options.PixelSize = 300
    options.ExportRange = DB.ExportRange.SetOfViews
    options.SetViewsAndSheets(DB.List[DB.ElementId]([sheet.Id]))

    doc.ExportImage(options)

    for candidate in os.listdir(output_dir):
        if candidate.startswith(base_name + " - Sheet - ") and candidate.endswith(".png"):
            found = os.path.join(output_dir, candidate)
            if os.path.abspath(found) != os.path.abspath(target):
                if os.path.exists(target):
                    os.remove(target)
                os.rename(found, target)
            return target
    if os.path.exists(target):
        return target
    return None


# ---------------------------------------------------------------------------
# FBX export of the section-boxed 3D view
# ---------------------------------------------------------------------------

@ERROR_HANDLE.try_catch_error()
def export_section_fbx(doc, uidoc, view_3d, output_dir, base_name):
    """Export the active section-boxed 3D view to FBX. Returns .fbx path or None.

    Document.Export with FBXExportOptions exports the currently active 3D
    view, so the view is activated first (and restored afterwards).
    """
    target = os.path.join(output_dir, base_name + ".fbx")
    if os.path.exists(target):
        os.remove(target)

    previous_view = uidoc.ActiveView
    try:
        uidoc.ActiveView = view_3d
        fbx_options = DB.FBXExportOptions()
        doc.Export(output_dir, base_name, fbx_options)
    finally:
        try:
            if previous_view is not None:
                uidoc.ActiveView = previous_view
        except Exception:
            pass

    if os.path.exists(target) and os.path.getsize(target) > 0:
        return target
    # Revit sometimes decorates the filename; accept the closest match.
    matches = [f for f in os.listdir(output_dir)
               if f.startswith(base_name) and f.endswith(".fbx")]
    if matches:
        found = os.path.join(output_dir, sorted(matches)[0])
        if os.path.getsize(found) > 0:
            return found
    return None


# ---------------------------------------------------------------------------
# FBX -> .glb conversion via FBX2glTF (provisioned, hash-verified)
# ---------------------------------------------------------------------------

def sha256_of_file(filepath):
    """Hex SHA256 of a file via .NET (IronPython hashlib can be flaky)."""
    sha = SHA256Managed()
    with open(filepath, "rb") as handle:
        digest = sha.ComputeHash(bytearray(handle.read()))
    return "".join("{:02x}".format(b) for b in digest)


def is_valid_fbx2gltf(exe_path):
    """True when the exe exists with the pinned size and SHA256."""
    try:
        if not os.path.exists(exe_path):
            return False
        if os.path.getsize(exe_path) != FBX2GLTF_SIZE:
            return False
        return sha256_of_file(exe_path) == FBX2GLTF_SHA256
    except Exception:
        return False


@ERROR_HANDLE.try_catch_error()
def ensure_fbx2gltf(pushbutton_dir, staging_dir):
    """Return a verified FBX2glTF exe path, or None (FBX kept as fallback).

    Lookup order: next to this script -> staging cache -> download the pinned
    v0.9.7 release and verify SHA256. Nothing runs unverified: a corrupt or
    tampered exe is deleted and reported instead of executed.
    """
    candidates = [
        os.path.join(pushbutton_dir, FBX2GLTF_EXE_NAME),
        os.path.join(staging_dir, FBX2GLTF_EXE_NAME),
    ]
    for candidate in candidates:
        if is_valid_fbx2gltf(candidate):
            return candidate

    # Download the pinned release into the staging cache.
    dest = os.path.join(staging_dir, FBX2GLTF_EXE_NAME)
    try:
        if not os.path.isdir(staging_dir):
            os.makedirs(staging_dir)
        client = WebClient()
        client.DownloadFile(FBX2GLTF_RELEASE_URL, dest)
    except Exception as ex:
        logger.error("FBX2glTF download failed: {}".format(ex))
        return None

    if not is_valid_fbx2gltf(dest):
        logger.error("FBX2glTF failed hash/size verification; refusing to run it.")
        try:
            os.remove(dest)
        except Exception:
            pass
        return None
    return dest


@ERROR_HANDLE.try_catch_error()
def convert_fbx_to_glb(exe_path, fbx_path, glb_path):
    """Run FBX2glTF --binary. Returns True when a non-empty .glb exists."""
    if os.path.exists(glb_path):
        os.remove(glb_path)
    start_info = ProcessStartInfo()
    start_info.FileName = exe_path
    start_info.Arguments = '--binary --input "{}" --output "{}"'.format(
        fbx_path, glb_path)
    start_info.UseShellExecute = False
    start_info.RedirectStandardOutput = True
    start_info.RedirectStandardError = True
    start_info.CreateNoWindow = True

    process = Process()
    process.StartInfo = start_info
    process.Start()
    finished = process.WaitForExit(180000)  # 3 min per sheet model
    if not finished:
        try:
            process.Kill()
        except Exception:
            pass
        return False
    return (process.ExitCode == 0 and os.path.exists(glb_path)
            and os.path.getsize(glb_path) > 0)


# ---------------------------------------------------------------------------
# Anchor metadata (paper-sheet contract, epic TODO-6999)
# ---------------------------------------------------------------------------

def build_anchor(doc, plan_view, paper_designation, xy_min_ft):
    """Build the anchor dict the phone uses to place the model on paper.

    northYawDeg: project north rotation (degrees). NOTE -- this is the
    rotation angle reported by the project location's ProjectPosition; the
    AR side (TODO-7006) must validate the sign convention against a known
    north arrow before trusting it for alignment.
    """
    angle_deg = 0.0
    try:
        project_location = doc.ActiveProjectLocation
        if project_location is not None:
            position = project_location.GetProjectPosition(DB.XYZ.Zero)
            if position is not None:
                angle_deg = round(math.degrees(position.Angle), 2)
    except Exception:
        pass

    scale = 0
    try:
        scale = int(plan_view.Scale)
    except Exception:
        pass

    origin_mm = [0.0, 0.0]
    try:
        origin_mm = [round(xy_min_ft[0] * FT_TO_MM, 1),
                     round(xy_min_ft[1] * FT_TO_MM, 1)]
    except Exception:
        pass

    return {
        "origin": origin_mm,
        "northYawDeg": angle_deg,
        "scaleDenominator": scale,
        "paper": paper_designation,
        "markerMm": marker_mm_for_paper(paper_designation),
    }


# ---------------------------------------------------------------------------
# Per-sheet export pipeline
# ---------------------------------------------------------------------------

def export_one_sheet(doc, uidoc, sheet, plans, levels_sorted, bundle_dir,
                     fbx2gltf_exe, status_callback):
    """Export one sheet's plan image + section-boxed GLB. Returns sheet dict or None.

    The returned dict follows the manifest schema; local paths are kept under
    "local*" keys and replaced with blob URLs at beam time.
    """
    sheet_number = sheet.SheetNumber or "?"
    safe_number = sanitize_filename(sheet_number)
    sheet_name = sheet.Name or ""

    def note(message):
        if status_callback:
            status_callback("[{}] {}".format(sheet_number, message))

    plan_view = plans[0]
    level = plan_view.GenLevel
    if level is None:
        note("skipped: plan '{}' has no associated level".format(plan_view.Name))
        return None
    level_name = level.Name

    # --- plan image ---
    note("exporting plan image...")
    png_path = export_sheet_image(doc, sheet, bundle_dir, safe_number)
    if png_path is None:
        note("FAILED: plan image export produced no file")
        return None

    # --- section-boxed 3D view ---
    note("building section box for level '{}'...".format(level_name))
    bbox, xy_min_ft = compute_section_bbox(doc, plan_view, level, levels_sorted)
    if bbox is None:
        note("FAILED: could not determine a section box (empty model?)")
        return None
    view_3d = get_or_create_section_3d(doc, sheet_number, bbox)
    if view_3d is None:
        note("FAILED: could not create the section-boxed 3D view")
        return None

    # --- FBX export + .glb conversion ---
    note("exporting FBX...")
    fbx_path = export_section_fbx(doc, uidoc, view_3d, bundle_dir, safe_number)
    if fbx_path is None:
        note("FAILED: FBX export produced no file")
        return None

    glb_path = os.path.join(bundle_dir, safe_number + ".glb")
    glb_ok = False
    if fbx2gltf_exe:
        note("converting FBX -> glb...")
        glb_ok = convert_fbx_to_glb(fbx2gltf_exe, fbx_path, glb_path)

    model_path = glb_path if glb_ok else fbx_path
    model_kind = "glb" if glb_ok else "fbx"
    if not glb_ok:
        note("glb conversion unavailable; keeping FBX "
             "(upload manually or install the converter)")

    # --- paper + anchor metadata ---
    paper_designation, width_mm, height_mm = get_sheet_paper(doc, sheet)

    note("done ({}).".format(model_kind))
    return {
        "sheetNumber": sheet_number,
        "sheetName": sheet_name,
        "level": level_name,
        "paper": paper_designation,
        "paperWidthMm": width_mm,
        "paperHeightMm": height_mm,
        "modelKind": model_kind,
        "anchor": build_anchor(doc, plan_view, paper_designation, xy_min_ft),
        "localPlanImage": png_path,
        "localModel": model_path,
        "planImageUrl": None,
        "modelGlbUrl": None,
    }


def build_manifest(doc, sheet_entries):
    """Assemble the manifest dict (local paths -> blob URLs at beam time)."""
    sheets = []
    for entry in sheet_entries:
        sheets.append({
            "sheetNumber": entry["sheetNumber"],
            "sheetName": entry["sheetName"],
            "level": entry["level"],
            "paper": entry["paper"],
            "paperWidthMm": entry["paperWidthMm"],
            "paperHeightMm": entry["paperHeightMm"],
            "modelKind": entry["modelKind"],
            "planImage": entry["planImageUrl"],
            "modelGlb": entry["modelGlbUrl"],
            "anchor": entry["anchor"],
        })
    title = ""
    try:
        title = doc.Title or ""
    except Exception:
        pass
    return {
        "kind": "drawing-set",
        "version": MANIFEST_VERSION,
        "roomId": None,
        "source": {
            "docTitle": title,
            "exportedAt": datetime.now().isoformat(),
            "exporter": "EnneadTab drawing_set_export (TODO-7005)",
        },
        "sheets": sheets,
    }


def write_manifest_file(manifest, filepath):
    with open(filepath, "w") as handle:
        json.dump(manifest, handle, indent=2)


# ---------------------------------------------------------------------------
# WPF form
# ---------------------------------------------------------------------------

from System import Uri, UriKind
from System.Windows import Visibility
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from pyrevit.forms import WPFWindow
import proDUCKtion


class DrawingSetExportWindow(WPFWindow):
    def __init__(self, doc, uidoc, sheets_with_plans):
        WPFWindow.__init__(
            self,
            os.path.join(os.path.dirname(__file__), "Drawing_Set_Export_Form.xaml"),
        )
        self.doc = doc
        self.uidoc = uidoc
        self.sheets_with_plans = sheets_with_plans
        self.default_room_id = ARVR.generate_room_id()
        self.room_textbox.Text = self.default_room_id
        self.staging_dir = ARVR.get_staging_directory()

        for sheet, plans in sheets_with_plans:
            checkbox = CheckBox()
            plan_label = plans[0].Name if len(plans) == 1 else "{} plans".format(len(plans))
            checkbox.Content = "{} - {} [{}]".format(
                sheet.SheetNumber, sheet.Name, plan_label)
            checkbox.IsChecked = True
            checkbox.Tag = (sheet, plans)
            checkbox.Margin = Thickness(0, 2, 0, 2)
            self.sheet_checklist.Children.Add(checkbox)

        self.status_text.Text = (
            ">> {} sheet(s) with floor plans found - "
            "uncheck any sheet to skip it".format(len(sheets_with_plans)))

    # -- helpers ------------------------------------------------------------
    def get_room_id(self):
        txt = self.room_textbox.Text.strip()
        if not txt:
            txt = self.default_room_id
        return txt.upper()

    def selected_sheets(self):
        selected = []
        for child in self.sheet_checklist.Children:
            if isinstance(child, CheckBox) and child.IsChecked:
                selected.append(child.Tag)
        return selected

    def set_status(self, message):
        self.status_text.Text = message
        try:
            # Let the UI repaint between long export steps.
            from System.Windows.Forms import Application
            Application.DoEvents()
        except Exception:
            pass

    def _load_qr_image(self, image_control, file_path):
        if not file_path or not os.path.exists(file_path):
            return
        try:
            bmp = BitmapImage()
            bmp.BeginInit()
            bmp.CacheOption = BitmapCacheOption.OnLoad
            bmp.UriSource = Uri(file_path, UriKind.Absolute)
            bmp.EndInit()
            image_control.Source = bmp
        except Exception:
            pass

    def _show_share_card(self, room_id):
        mobile_url = ARVR.get_mobile_viewer_url(room_id)
        hub_url = "{}?room={}".format(ARVR.ARVR_URL_BASE, room_id)
        large_qr, small_qr = ARVR.download_qr_code_pair(room_id, hub_url)
        if large_qr:
            self._load_qr_image(self.qr_mobile_image, large_qr)
        if small_qr:
            self._load_qr_image(self.qr_room_image, small_qr)
        self.mobile_link_textbox.Text = mobile_url
        self.room_link_textbox.Text = hub_url
        self.share_link_card.Visibility = Visibility.Visible

    # -- export pipeline ----------------------------------------------------
    def run_export(self, beam):
        selected = self.selected_sheets()
        if not selected:
            self.set_status(">> No sheets selected.")
            return

        bundle_dir = os.path.join(
            self.staging_dir,
            "DrawingSet_{}".format(datetime.now().strftime("%Y%m%d_%H%M%S")))
        try:
            if not os.path.isdir(bundle_dir):
                os.makedirs(bundle_dir)
        except Exception as ex:
            self.set_status(">> Cannot create output folder: {}".format(ex))
            return

        self.set_status(">> Checking FBX -> glb converter...")
        fbx2gltf_exe = ensure_fbx2gltf(os.path.dirname(__file__), self.staging_dir)
        if fbx2gltf_exe:
            self.set_status(">> Converter ready.")
        else:
            self.set_status(">> WARNING: glb converter unavailable - "
                            "keeping FBX files (see status per sheet).")

        levels_sorted = get_sorted_levels(self.doc)
        exported = []
        for sheet, plans in selected:
            entry = export_one_sheet(
                self.doc, self.uidoc, sheet, plans, levels_sorted,
                bundle_dir, fbx2gltf_exe, self.set_status)
            if entry:
                exported.append(entry)

        if not exported:
            self.set_status(">> Nothing exported. Bundle folder: {}".format(bundle_dir))
            return

        manifest = build_manifest(self.doc, exported)
        manifest_path = os.path.join(bundle_dir, "manifest.json")
        write_manifest_file(manifest, manifest_path)

        if not beam:
            self.set_status(
                ">> Exported {} sheet(s) locally (no upload). Folder:\n{}".format(
                    len(exported), bundle_dir))
            NOTIFICATION.messenger(
                "Drawing set exported locally:\n{}".format(bundle_dir))
            return

        # -- beam to ARVR room --
        room_id = self.get_room_id()
        self.set_status(">> Beaming {} sheet(s) to room {}...".format(
            len(exported), room_id))

        url_of = {}
        failed = []
        uploads = []
        for entry in exported:
            safe = sanitize_filename(entry["sheetNumber"])
            ext_img = os.path.splitext(entry["localPlanImage"])[1] or ".png"
            ext_model = os.path.splitext(entry["localModel"])[1] or ".glb"
            uploads.append((entry["localPlanImage"],
                            "rooms/{}/drawings/{}/{}{}".format(
                                room_id, safe, safe, ext_img)))
            uploads.append((entry["localModel"],
                            "rooms/{}/drawings/{}/{}{}".format(
                                room_id, safe, safe, ext_model)))
        for local_path, blob_pathname in uploads:
            self.set_status(">> Uploading {}...".format(os.path.basename(local_path)))
            ok, blob_url, err = ARVR.put_blob_file(
                local_path, room_id, blob_pathname)
            if ok:
                url_of[local_path] = blob_url
            else:
                failed.append("{}: {}".format(os.path.basename(local_path), err))

        # Rewrite the manifest with blob URLs and upload it too.
        for entry in exported:
            entry["planImageUrl"] = url_of.get(entry["localPlanImage"])
            entry["modelGlbUrl"] = url_of.get(entry["localModel"])
        manifest = build_manifest(self.doc, exported)
        manifest["roomId"] = room_id
        write_manifest_file(manifest, manifest_path)
        manifest_blob_path = "rooms/{}/drawings/manifest.json".format(room_id)
        ok, manifest_url, err = ARVR.put_blob_file(
            manifest_path, room_id, manifest_blob_path)
        if not ok:
            failed.append("manifest.json: {}".format(err))
            manifest_url = None

        # Register the room. Primary model = first sheet's GLB so today's
        # viewer keeps working; manifestUrl + kind ride along as extras.
        primary = exported[0]
        primary_url = primary["modelGlbUrl"]
        if not primary_url:
            self.set_status(">> Uploads failed:\n" + "\n".join(failed))
            return
        ok, web_url, err = ARVR.register_room(
            room_id,
            primary_url,
            os.path.basename(primary["localModel"]),
            ARVR.content_type_for(primary["localModel"]),
            os.path.getsize(primary["localModel"]),
            extra={"kind": "drawing-set", "manifestUrl": manifest_url})
        if not ok:
            self.set_status(">> Room registration failed: {}".format(err))
            return

        if failed:
            self.set_status(">> Beamed with {} failed upload(s):\n{}".format(
                len(failed), "\n".join(failed)))
        else:
            self.set_status(
                ">> Beamed {} sheet(s) to Room {} - scan the BIG QR on your phone".format(
                    len(exported), room_id))
        self._show_share_card(room_id)
        NOTIFICATION.messenger(
            "Drawing set beamed to room {}:\n{}".format(room_id, web_url))

    # -- button handlers ----------------------------------------------------
    def on_export_beam_clicked(self, sender, e):
        self.run_export(beam=True)

    def on_export_only_clicked(self, sender, e):
        self.run_export(beam=False)

    def on_open_web_clicked(self, sender, e):
        ARVR.open_web_hub(self.get_room_id())

    def on_copy_mobile_clicked(self, sender, e):
        txt = self.mobile_link_textbox.Text
        if txt:
            copy_to_clipboard(txt)
            self.btn_copy_mobile.Content = "COPIED!"

    def on_copy_room_clicked(self, sender, e):
        txt = self.room_link_textbox.Text
        if txt:
            copy_to_clipboard(txt)
            self.btn_copy_room.Content = "COPIED!"

    def on_close_clicked(self, sender, e):
        self.Close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@ERROR_HANDLE.try_catch_error()
@LOG.log(__file__, __title__)
def main(doc):
    uidoc = revit.uidoc
    proDUCKtion.validify()

    sheets_with_plans = collect_sheets_with_plans(doc)
    if not sheets_with_plans:
        TaskDialog.Show(
            __title__,
            "No sheets with placed floor plans were found in this model.\n\n"
            "This tool exports one section-boxed 3D model per sheet that has "
            "a floor plan placed on it.")
        return

    window = DrawingSetExportWindow(doc, uidoc, sheets_with_plans)
    window.ShowDialog()


if __name__ == "__main__":
    main(revit.doc)
