#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Export logic for AutoExporter. Handles folder structure creation and export operations.
"""

import os
import shutil
import time
import threading
from datetime import datetime
from Autodesk.Revit import DB # pyright: ignore
import System # pyright: ignore
import config_loader

# =============================================================================
# ERROR LOOP DETECTION AND TIMEOUT PROTECTION
# =============================================================================

class ErrorLoopDetector:
    """Detect and prevent infinite error loops in Revit automation."""
    
    def __init__(self, max_same_error=10, time_window=60):
        self.error_history = []
        self.max_same_error = max_same_error
        self.time_window = time_window
    
    def record_error(self, error_message):
        """Record an error and check for loops."""
        now = time.time()
        
        # Clean old errors outside time window
        self.error_history = [
            (msg, ts) for msg, ts in self.error_history 
            if now - ts < self.time_window
        ]
        
        # Add new error
        self.error_history.append((error_message, now))
        
        # Check for repeated error
        recent_errors = [msg for msg, _ in self.error_history]
        if recent_errors.count(error_message) >= self.max_same_error:
            raise RuntimeError(
                "Error loop detected: '{}' occurred {} times in {}s".format(
                    error_message, recent_errors.count(error_message), self.time_window
                )
            )
    
    def reset(self):
        """Reset error tracking."""
        self.error_history.clear()


class OperationTimeout:
    """Enforce timeouts on Revit operations to prevent hangs."""
    
    def __init__(self, timeout_seconds):
        self.timeout_seconds = timeout_seconds
        self.timer = None
        self.timed_out = False
    
    def __enter__(self):
        def timeout_handler():
            self.timed_out = True
            print("Operation timed out after {}s".format(self.timeout_seconds))
        
        self.timer = threading.Timer(self.timeout_seconds, timeout_handler)
        self.timer.start()
        return self
    
    def __exit__(self, *args):
        if self.timer:
            self.timer.cancel()
        
        if self.timed_out:
            raise TimeoutError(
                "Operation exceeded {}s timeout. Possible infinite loop or hung dialog.".format(
                    self.timeout_seconds
                )
            )


# Session-scoped error loop detector. It MUST live at module scope: a per-call
# instance (the old behaviour) reset error_history on every sheet, so the
# max_same_error threshold was never reachable and the loop guard never fired.
# Hoisting it here lets errors accumulate across every sheet in a run so a
# repeating failure actually trips the guard.
_EXPORT_ERROR_DETECTOR = ErrorLoopDetector(max_same_error=5, time_window=30)


def safe_export_with_timeout(export_func, sheet, sheet_index, total_sheets, timeout_minutes=5):
    """Safely export a single sheet with timeout protection and error handling."""
    error_detector = _EXPORT_ERROR_DETECTOR

    try:
        with OperationTimeout(timeout_minutes * 60):
            return export_func(sheet, sheet_index, total_sheets)
    except TimeoutError as e:
        error_msg = "Sheet '{}' export timed out after {} minutes".format(
            sheet.Name, timeout_minutes
        )
        error_detector.record_error(error_msg)
        print("TIMEOUT: {}".format(error_msg))
        return None
    except Exception as e:
        error_msg = "Sheet '{}' export error: {}".format(sheet.Name, str(e))
        error_detector.record_error(error_msg)
        print("ERROR: {}".format(error_msg))
        return None


# =============================================================================
# LOAD CONFIGURATION
# =============================================================================

# Load export settings from config.json
EXPORT_SETTINGS = config_loader.get_export_settings()
PROJECT_INFO = config_loader.get_project_info()

# Extract commonly used settings
OUTPUT_BASE_PATH = EXPORT_SETTINGS.get('output_base_path', '')
SHEET_FILTER_PARAMETER = EXPORT_SETTINGS.get('sheet_filter_parameter', 'Sheet_$Issue_AutoPublish')
DWG_SETTING_NAME = EXPORT_SETTINGS.get('dwg_setting_name', 'to NYU dwg')
PDF_COLOR_PARAMETER = EXPORT_SETTINGS.get('pdf_color_parameter', 'Print_In_Color')
SUBFOLDERS = EXPORT_SETTINGS.get('subfolders', ['pdf', 'dwg', 'jpg'])
DATE_FORMAT = EXPORT_SETTINGS.get('date_format', '%Y-%m-%d')
PDF_OPTIONS = EXPORT_SETTINGS.get('pdf_options', {})
JPG_OPTIONS = EXPORT_SETTINGS.get('jpg_options', {})


def get_element_id_numeric_value(element_id):
    """Return a Python int for the given ElementId, handling Revit version differences.
    
    Args:
        element_id: Autodesk.Revit.DB.ElementId or None
    
    Returns:
        int or None: ElementId numeric value, or None if unavailable/invalid
    """
    if not element_id:
        return None
    
    try:
        if element_id == DB.ElementId.InvalidElementId:
            return None
    except Exception:
        # Some ElementId comparisons can raise if the API version differs; ignore and continue
        pass
    
    for attr_name in ("Value", "IntegerValue"):
        try:
            attr_value = getattr(element_id, attr_name)
        except AttributeError:
            continue
        except Exception:
            continue
        
        if callable(attr_value):
            try:
                attr_value = attr_value()
            except Exception:
                continue
        
        try:
            return int(attr_value)
        except Exception:
            continue
    
    return None


def get_staging_root():
    """Get the root staging directory for ACC-safe local operations
    
    Returns:
        str: Path to C:/temp/autoexport_staging
    """
    # Use C:/temp for staging (faster, avoids workspace clutter)
    staging_root = "C:/temp/autoexport_staging"
    
    # Ensure the staging root exists to avoid errors when creating subfolders
    if not os.path.exists(staging_root):
        try:
            os.makedirs(staging_root)
        except Exception:
            # If creation fails, let downstream logic surface a clearer error
            pass
    
    return staging_root


def get_staging_path(job_id):
    """Get the staging path for a specific job
    
    Args:
        job_id: Unique job identifier
    
    Returns:
        str: Path to staging folder for this job
    """
    staging_root = get_staging_root()
    return os.path.join(staging_root, job_id)


def get_weekly_folder_path():
    """Get the path for this week's export folder (yyyy-mm-dd {model_name} format)
    
    Returns:
        str: Full path to weekly folder (e.g., .../2025-10-21 2534_A_EA_NYU HQ_Shell)
    """
    date_stamp = datetime.now().strftime(DATE_FORMAT)
    model_name = config_loader.get_model_name()
    
    # Create folder name: "yyyy-mm-dd ModelName"
    folder_name = "{} {}".format(date_stamp, model_name)
    weekly_folder = os.path.join(OUTPUT_BASE_PATH, folder_name)
    return weekly_folder


def sanitize_filename(name):
    """Sanitize sheet name for use as Windows filename
    
    Args:
        name: Sheet name string
    
    Returns:
        str: Sanitized filename-safe string
    """
    # Replace illegal Windows filename characters with underscore
    safe_name = name
    for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        safe_name = safe_name.replace(char, '_')
    # Keep only alphanumeric, spaces, hyphens, and underscores
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    return safe_name


def get_pim_number(doc):
    """Extract PIM_Number from project info
    
    Args:
        doc: Revit Document object
    
    Returns:
        str: PIM_Number value or empty string if not found
    """
    try:
        # Ensure we have a Document object, not UIDocumentFile
        if hasattr(doc, 'Document'):
            doc = doc.Document
        
        # Get PIM parameter name from config
        pim_param_name = PROJECT_INFO.get('pim_parameter_name', 'PIM_Number')
        
        # If pim_parameter_name is None/null, don't use PIM prefix
        if pim_param_name is None:
            print("PIM parameter name is None - skipping PIM number in filename")
            return ""
        
        # Get project info
        project_info = doc.ProjectInformation
        if project_info:
            pim_param = project_info.LookupParameter(pim_param_name)
            if pim_param and pim_param.AsString():
                pim_value = pim_param.AsString().strip()
                print("Found {}: '{}'".format(pim_param_name, pim_value))
                return pim_value
        print("{} not found in project info".format(pim_param_name))
        return ""
    except Exception as e:
        print("Error extracting PIM_Number: {}".format(e))
        return ""


def get_sheets_to_export(doc, heartbeat_callback=None):
    """Get sheets that have the filter parameter with non-empty value
    
    Args:
        doc: Revit Document object
        heartbeat_callback: Optional function to call for logging progress
    
    Returns:
        list: List of ViewSheet objects to export
    """
    sheets_to_export = []
    
    # Ensure we have a Document object, not UIDocumentFile
    if hasattr(doc, 'Document'):
        doc = doc.Document
    
    # Get all sheets in the document
    sheet_collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)
    all_sheets = list(sheet_collector)
    
    if heartbeat_callback:
        heartbeat_callback("EXPORT", "Found {} total sheets in document".format(len(all_sheets)))
    
    # Production filtering logic - filter sheets by parameter value
    for sheet in all_sheets:
        try:
            param = sheet.LookupParameter(SHEET_FILTER_PARAMETER)
            if param:
                # Get parameter value based on storage type
                if param.StorageType == DB.StorageType.String:
                    param_value = param.AsString()
                elif param.StorageType == DB.StorageType.Integer:
                    param_value = param.AsInteger()
                elif param.StorageType == DB.StorageType.Double:
                    param_value = param.AsDouble()
                elif param.StorageType == DB.StorageType.ElementId:
                    param_value = param.AsElementId()
                else:
                    param_value = param.AsString()
                
                # Check if parameter has meaningful value (any non-empty, non-"None" value)
                has_value = False
                if param.StorageType == DB.StorageType.String:
                    has_value = (param_value and 
                               param_value.strip() != "" and 
                               param_value.strip().lower() != "none")
                elif param.StorageType == DB.StorageType.Integer:
                    has_value = param_value != 0
                elif param.StorageType == DB.StorageType.Double:
                    has_value = param_value != 0.0
                elif param.StorageType == DB.StorageType.ElementId:
                    element_numeric_value = get_element_id_numeric_value(param_value)
                    has_value = element_numeric_value is not None and element_numeric_value != -1
                else:
                    has_value = (param_value and 
                               str(param_value).strip() != "" and 
                               str(param_value).strip().lower() != "none")
                
                if has_value:
                    sheets_to_export.append(sheet)
                    if heartbeat_callback:
                        heartbeat_callback("EXPORT", "Sheet '{}' marked for export".format(sheet.Name))
        except Exception as e:
            pass  # Skip sheets with errors
    
    if heartbeat_callback:
        heartbeat_callback("EXPORT", "Found {} sheets to export (out of {} total)".format(len(sheets_to_export), len(all_sheets)))
    
    return sheets_to_export


def create_export_folders(use_staging=False, job_id=None):
    """Create the weekly folder structure with pdf, dwg, jpg subfolders
    
    Args:
        use_staging: If True, create folders in local staging area (ACC-safe)
        job_id: Job identifier for staging path (required if use_staging=True)
    
    Returns:
        dict: Dictionary with paths for each export type
            {"weekly": "path/to/2025-10-21",
             "pdf": "path/to/2025-10-21/PDF",
             "dwg": "path/to/2025-10-21/DWG",
             "jpg": "path/to/2025-10-21/JPG",
             "staging": True/False,
             "acc_path": "path/to/ACC/folder" (only if staging=True)}
        Note: Keys are lowercase for consistent access, values preserve config case
    """
    if use_staging and job_id:
        # Use local staging folder to avoid ACC Desktop Connector warnings
        staging_base = get_staging_path(job_id)
        date_stamp = datetime.now().strftime(DATE_FORMAT)
        model_name = config_loader.get_model_name()
        folder_name = "{} {}".format(date_stamp, model_name)
        weekly_folder = os.path.join(staging_base, folder_name)
        
        # Store ACC destination for later sync
        acc_weekly_folder = get_weekly_folder_path()
    else:
        # Direct to ACC (legacy behavior)
        weekly_folder = get_weekly_folder_path()
        acc_weekly_folder = None
    
    # Create weekly folder if it doesn't exist
    if not os.path.exists(weekly_folder):
        os.makedirs(weekly_folder)
    
    # Create subfolders
    folder_paths = {
        "weekly": weekly_folder,
        "staging": use_staging,
        "acc_path": acc_weekly_folder
    }
    for subfolder in SUBFOLDERS:
        subfolder_path = os.path.join(weekly_folder, subfolder)
        if not os.path.exists(subfolder_path):
            os.makedirs(subfolder_path)
        # Use lowercase key for consistent access regardless of config case
        folder_paths[subfolder.lower()] = subfolder_path
    
    return folder_paths


def export_pdf(doc, folder_paths, heartbeat_callback=None):
    """Export PDF files to the pdf subfolder
    
    Args:
        doc: Revit Document object
        folder_paths: Dictionary of folder paths from create_export_folders()
        heartbeat_callback: Optional function to call for logging progress
    
    Returns:
        list: List of exported PDF file paths
    """
    pdf_folder = folder_paths["pdf"]
    print("Exporting PDFs to: {}".format(pdf_folder))
    
    # Get PIM_Number for filename prefix
    pim_number = get_pim_number(doc)
    
    # Get sheets to export
    sheets_to_export = get_sheets_to_export(doc, heartbeat_callback)
    exported_files = []
    
    if not sheets_to_export:
        print("No sheets found with parameter '{}' - skipping PDF export".format(SHEET_FILTER_PARAMETER))
        return exported_files
    
    # Export each sheet as PDF with timeout protection
    from System.Collections.Generic import List
    
    total_sheets = len(sheets_to_export)
    for idx, sheet in enumerate(sheets_to_export, 1):
        def export_single_pdf(sheet, sheet_index, total_sheets):
            """Export a single PDF sheet with timeout protection."""
            # Create filename in format: {pim}-{sheetnum}_{sheetname}
            sheet_number = sheet.SheetNumber
            safe_name = sanitize_filename(sheet.Name)
            
            if pim_number:
                filename_base = "{}-{}_{}".format(pim_number, sheet_number, safe_name)
            else:
                filename_base = "{}_{}".format(sheet_number, safe_name)
            
            # Log progress for debugging stuck exports
            if heartbeat_callback:
                heartbeat_callback("EXPORT", "Exporting PDF {}/{}: {} - {}".format(
                    sheet_index, total_sheets, sheet_number, sheet.Name[:50]))
            
            pdf_path = os.path.join(pdf_folder, filename_base + ".pdf")
            
            # Delete existing file to allow overwrite (Revit won't overwrite by default)
            if os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except:
                    pass
            
            # Create export options from config
            export_options = DB.PDFExportOptions()
            export_options.HideCropBoundaries = PDF_OPTIONS.get('hide_crop_boundaries', True)
            export_options.HideScopeBoxes = PDF_OPTIONS.get('hide_scope_boxes', True)
            export_options.HideReferencePlane = PDF_OPTIONS.get('hide_reference_plane', True)
            export_options.Combine = PDF_OPTIONS.get('combine', False)
            export_options.StopOnError = PDF_OPTIONS.get('stop_on_error', False)
            
            # Set custom naming rule to match our filename format
            from EnneadTab import DATA_CONVERSION
            sheet_num_data = DB.TableCellCombinedParameterData.Create()
            sheet_num_data.ParamId = DB.ElementId(DB.BuiltInParameter.SHEET_NUMBER)
            if pim_number:
                sheet_num_data.Prefix = pim_number + "-"
            sheet_num_data.Separator = "_"
            
            sheet_name_data = DB.TableCellCombinedParameterData.Create()
            sheet_name_data.ParamId = DB.ElementId(DB.BuiltInParameter.SHEET_NAME)
            
            naming_rule = DATA_CONVERSION.list_to_system_list(
                [sheet_num_data, sheet_name_data], 
                type="TableCellCombinedParameterData", 
                use_IList=False
            )
            export_options.SetNamingRule(naming_rule)
            
            # Set color based on Print_In_Color parameter (boolean: 1=color, 0=grayscale)
            color_param = sheet.LookupParameter(PDF_COLOR_PARAMETER)
            if color_param and color_param.AsInteger() == 1:
                export_options.ColorDepth = DB.ColorDepthType.Color
            else:
                export_options.ColorDepth = DB.ColorDepthType.GrayScale
            
            # Create .NET List for view IDs
            view_ids = List[DB.ElementId]()
            view_ids.Add(sheet.Id)
            
            # Export the sheet
            doc.Export(pdf_folder, view_ids, export_options)
            
            # Verify export succeeded
            if os.path.exists(pdf_path):
                if heartbeat_callback:
                    heartbeat_callback("EXPORT", "PDF {}/{} complete: {}".format(
                        sheet_index, total_sheets, sheet_number))
                return pdf_path
            else:
                if heartbeat_callback:
                    heartbeat_callback("EXPORT", "PDF {}/{} WARNING: File not created: {}".format(
                        sheet_index, total_sheets, pdf_path), is_error=True)
                return None
        
        # Use safe export with timeout (5 minutes per PDF)
        result = safe_export_with_timeout(export_single_pdf, sheet, idx, total_sheets, timeout_minutes=5)
        if result:
            exported_files.append(result)
    
    return exported_files


def export_dwg(doc, folder_paths, heartbeat_callback=None):
    """Export DWG files to the dwg subfolder
    
    Args:
        doc: Revit Document object
        folder_paths: Dictionary of folder paths from create_export_folders()
        heartbeat_callback: Optional function to call for logging progress
    
    Returns:
        list: List of exported DWG file paths
    """
    dwg_folder = folder_paths["dwg"]
    print("Exporting DWGs to: {}".format(dwg_folder))
    
    # Get PIM_Number for filename prefix
    pim_number = get_pim_number(doc)
    
    # Get sheets to export
    sheets_to_export = get_sheets_to_export(doc, heartbeat_callback)
    exported_files = []
    
    if not sheets_to_export:
        return exported_files
    
    # Export each sheet as DWG with timeout protection
    from System.Collections.Generic import List
    
    total_sheets = len(sheets_to_export)
    for idx, sheet in enumerate(sheets_to_export, 1):
        def export_single_dwg(sheet, sheet_index, total_sheets):
            """Export a single DWG sheet with timeout protection."""
            # Create filename in format: {pim}-{sheetnum}_{sheetname}
            sheet_number = sheet.SheetNumber
            safe_name = sanitize_filename(sheet.Name)
            
            if pim_number:
                filename_base = "{}-{}_{}".format(pim_number, sheet_number, safe_name)
            else:
                filename_base = "{}_{}".format(sheet_number, safe_name)
            
            # Log progress for debugging stuck exports
            if heartbeat_callback:
                heartbeat_callback("EXPORT", "Exporting DWG {}/{}: {} - {}".format(
                    sheet_index, total_sheets, sheet_number, sheet.Name[:50]))
            
            dwg_path = os.path.join(dwg_folder, filename_base + ".dwg")
            
            # Delete existing file to allow overwrite
            if os.path.exists(dwg_path):
                try:
                    os.remove(dwg_path)
                except:
                    pass
            
            # Get DWG export options
            try:
                export_options = DB.DWGExportOptions.GetPredefinedOptions(doc, DWG_SETTING_NAME)
                if not export_options:
                    export_options = DB.DWGExportOptions()
                    export_options.MergedViews = False
                    export_options.ExportingAreas = False
            except:
                export_options = DB.DWGExportOptions()
                export_options.MergedViews = False
                export_options.ExportingAreas = False
            
            # Create .NET List for view IDs
            view_ids = List[DB.ElementId]()
            view_ids.Add(sheet.Id)
            
            # Export the sheet (filename without extension)
            doc.Export(dwg_folder, filename_base, view_ids, export_options)
            
            # Verify export succeeded
            if os.path.exists(dwg_path):
                if heartbeat_callback:
                    heartbeat_callback("EXPORT", "DWG {}/{} complete: {}".format(
                        sheet_index, total_sheets, sheet_number))
                return dwg_path
            else:
                if heartbeat_callback:
                    heartbeat_callback("EXPORT", "DWG {}/{} WARNING: File not created: {}".format(
                        sheet_index, total_sheets, dwg_path), is_error=True)
                return None
        
        # Use safe export with timeout (3 minutes per DWG)
        result = safe_export_with_timeout(export_single_dwg, sheet, idx, total_sheets, timeout_minutes=3)
        if result:
            exported_files.append(result)
    
    return exported_files


def export_jpg(doc, folder_paths, heartbeat_callback=None):
    """Export JPG images to the jpg subfolder
    
    Args:
        doc: Revit Document object
        folder_paths: Dictionary of folder paths from create_export_folders()
        heartbeat_callback: Optional function to call for logging progress
    
    Returns:
        list: List of exported JPG file paths
    """
    jpg_folder = folder_paths["jpg"]
    print("Exporting JPGs to: {}".format(jpg_folder))
    
    # Get PIM_Number for filename prefix
    pim_number = get_pim_number(doc)
    
    # Get sheets to export
    sheets_to_export = get_sheets_to_export(doc, heartbeat_callback)
    exported_files = []
    
    if not sheets_to_export:
        return exported_files
    
    # Export each sheet as JPG with timeout protection
    from System.Collections.Generic import List
    
    total_sheets = len(sheets_to_export)
    for idx, sheet in enumerate(sheets_to_export, 1):
        def export_single_jpg(sheet, sheet_index, total_sheets):
            """Export a single JPG sheet with timeout protection."""
            # Create filename in format: {pim}-{sheetnum}_{sheetname}
            sheet_number = sheet.SheetNumber
            safe_name = sanitize_filename(sheet.Name)
            
            if pim_number:
                filename_base = "{}-{}_{}".format(pim_number, sheet_number, safe_name)
            else:
                filename_base = "{}_{}".format(sheet_number, safe_name)
            
            # Log progress for debugging stuck exports
            if heartbeat_callback:
                heartbeat_callback("EXPORT", "Exporting JPG {}/{}: {} - {}".format(
                    sheet_index, total_sheets, sheet_number, sheet.Name[:50]))
            
            jpg_path = os.path.join(jpg_folder, filename_base + ".jpg")
            
            # Delete existing file to allow overwrite
            if os.path.exists(jpg_path):
                try:
                    os.remove(jpg_path)
                except:
                    pass
            
            # Create image export options from config
            export_options = DB.ImageExportOptions()
            # FilePath must be full path to OUTPUT FILE without extension (Revit adds .jpg)
            file_path_no_ext = os.path.join(jpg_folder, filename_base)
            export_options.FilePath = file_path_no_ext
            export_options.FitDirection = DB.FitDirectionType.Horizontal
            
            # Map resolution DPI to ImageResolution enum
            # Apply 2x resolution multiplier for higher quality exports
            base_resolution_dpi = JPG_OPTIONS.get('resolution_dpi', 150)
            resolution_dpi = base_resolution_dpi * 2  # 2x resolution for image exports
            
            if resolution_dpi <= 72:
                export_options.ImageResolution = DB.ImageResolution.DPI_72
            elif resolution_dpi <= 150:
                export_options.ImageResolution = DB.ImageResolution.DPI_150
            elif resolution_dpi <= 300:
                export_options.ImageResolution = DB.ImageResolution.DPI_300
            elif resolution_dpi <= 600:
                export_options.ImageResolution = DB.ImageResolution.DPI_600
            else:
                # For resolutions > 600, use highest available (600)
                export_options.ImageResolution = DB.ImageResolution.DPI_600
            
            export_options.ZoomType = DB.ZoomFitType.FitToPage
            # Apply 2x pixel size multiplier for higher quality exports
            base_pixel_size = JPG_OPTIONS.get('pixel_size', 1920)
            export_options.PixelSize = base_pixel_size * 2  # 2x pixel size for image exports
            export_options.ExportRange = DB.ExportRange.SetOfViews
            
            # Set the views/sheets to export
            view_ids = List[DB.ElementId]()
            view_ids.Add(sheet.Id)
            export_options.SetViewsAndSheets(view_ids)
            
            # Export the sheet
            # NOTE: Revit adds " - Sheet - " to the filename automatically!
            # We'll search for the exported file and rename it
            doc.ExportImage(export_options)
            
            # Find and rename the exported file
            # Revit exports with pattern: "filename - Sheet - sheetname.jpg"
            # We need to find it and rename to our desired format
            found_file = None
            
            # Search for files in the folder that match our base filename
            if os.path.exists(jpg_folder):
                for file in os.listdir(jpg_folder):
                    if filename_base in file and file.lower().endswith('.jpg'):
                        # Found a file with our base name
                        found_path = os.path.join(jpg_folder, file)
                        if found_path != jpg_path:
                            # Need to rename
                            try:
                                if os.path.exists(jpg_path):
                                    os.remove(jpg_path)
                                os.rename(found_path, jpg_path)
                                found_file = jpg_path
                                if heartbeat_callback:
                                    heartbeat_callback("EXPORT", "JPG exported and renamed: {} -> {}".format(
                                        file, os.path.basename(jpg_path)))
                                break
                            except Exception as rename_error:
                                # Rename failed, use the original filename
                                found_file = found_path
                                if heartbeat_callback:
                                    heartbeat_callback("EXPORT", "JPG exported but rename failed, using: {}".format(file))
                                break
                        else:
                            # File already has correct name
                            found_file = jpg_path
                            break
            
            if found_file:
                if heartbeat_callback:
                    heartbeat_callback("EXPORT", "JPG {}/{} complete: {}".format(
                        sheet_index, total_sheets, sheet_number))
                return found_file
            elif heartbeat_callback:
                heartbeat_callback("EXPORT", "JPG {}/{} WARNING: Not found after export '{}' (searched for: {})".format(
                    sheet_index, total_sheets, sheet.Name, filename_base), is_error=True)
            return None
        
        # Use safe export with timeout (2 minutes per JPG - shorter due to known issues)
        result = safe_export_with_timeout(export_single_jpg, sheet, idx, total_sheets, timeout_minutes=2)
        if result:
            exported_files.append(result)
    
    return exported_files


def sync_to_acc(staging_path, acc_path, heartbeat_callback=None):
    """Sync files from local staging to ACC destination with overwrite
    
    Only copies clean PDF, DWG, JPG files. Filters out:
    - .pcp files (plot configuration)
    - Embedded resource files (long Revit-generated names)
    - Other temporary files
    
    Args:
        staging_path: Source path (local staging folder)
        acc_path: Destination path (ACC folder)
        heartbeat_callback: Optional logging callback
    
    Returns:
        int: Number of files synced
    """
    def log(message):
        print(message)
        if heartbeat_callback:
            heartbeat_callback("SYNC", message)
    
    def should_copy_file(filepath):
        """Determine if a file should be copied to ACC"""
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filename)[1].lower()
        
        # Only copy our main export files
        if ext not in ['.pdf', '.dwg', '.jpg']:
            return False
        
        # Skip embedded resources (detect by very long names or embedded indicators)
        # Revit embeds resources with model name prefix like "EA_UCSCIIRB_A_Building____-"
        if '____-' in filename or len(filename) > 150:
            return False
        
        return True
    
    try:
        log("Syncing clean export files from staging to ACC...")
        log("  Source: {}".format(staging_path))
        log("  Destination: {}".format(acc_path))
        
        # Ensure destination exists
        if not os.path.exists(acc_path):
            os.makedirs(acc_path)
        
        # Copy files selectively with filtering
        file_count = 0
        skipped_count = 0
        
        for root, dirs, files in os.walk(staging_path):
            # Calculate relative path for destination
            rel_path = os.path.relpath(root, staging_path)
            dest_dir = os.path.join(acc_path, rel_path) if rel_path != '.' else acc_path
            
            # Ensure destination directory exists
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir)
            
            for file in files:
                src_file = os.path.join(root, file)
                
                if should_copy_file(src_file):
                    dest_file = os.path.join(dest_dir, file)
                    
                    # Remove existing file if present
                    if os.path.exists(dest_file):
                        try:
                            os.remove(dest_file)
                        except:
                            pass
                    
                    # Copy file
                    shutil.copy2(src_file, dest_file)
                    file_count += 1
                else:
                    skipped_count += 1
        
        log("Sync completed: {} clean files copied, {} temp files skipped".format(file_count, skipped_count))
        
        return file_count
    except Exception as e:
        error_msg = "Sync to ACC failed: {}".format(str(e))
        log(error_msg)
        if heartbeat_callback:
            heartbeat_callback("SYNC", error_msg, is_error=True)
        raise


def run_all_exports(doc, job_id=None, use_staging=True, heartbeat_callback=None):
    """Run all export operations with ACC-safe staging
    
    Args:
        doc: Revit Document object
        job_id: Job identifier for staging (required if use_staging=True)
        use_staging: If True, export to local staging then sync to ACC
        heartbeat_callback: Optional function to call for logging progress
            Should accept (step, message, is_error=False)
    
    Returns:
        dict: Dictionary with export results
            {"folder_paths": {...},
             "pdf_files": [...],
             "dwg_files": [...],
             "jpg_files": [...],
             "synced": True/False}
    """
    def log(message, is_error=False):
        """Helper to log messages"""
        print(message)
        if heartbeat_callback:
            heartbeat_callback("EXPORT", message, is_error=is_error)
    
    try:
        # Create folder structure (staging or direct)
        log("Creating export folder structure...")
        if use_staging and not job_id:
            log("WARNING: Staging requested but no job_id provided, using direct ACC export")
            use_staging = False
        
        folder_paths = create_export_folders(use_staging=use_staging, job_id=job_id)
        
        if use_staging:
            log("Using LOCAL STAGING (ACC-safe): {}".format(folder_paths["weekly"]))
            log("Will sync to ACC after exports: {}".format(folder_paths["acc_path"]))
        else:
            log("Folders created: {}".format(folder_paths["weekly"]))
        
        # Export PDFs
        log("Starting PDF export...")
        pdf_files = export_pdf(doc, folder_paths, heartbeat_callback)
        log("PDF export completed: {} files".format(len(pdf_files)))
        
        # Export DWGs
        log("Starting DWG export...")
        dwg_files = export_dwg(doc, folder_paths, heartbeat_callback)
        log("DWG export completed: {} files".format(len(dwg_files)))
        
        # Export JPGs
        log("Starting JPG export...")
        jpg_files = export_jpg(doc, folder_paths, heartbeat_callback)
        log("JPG export completed: {} files".format(len(jpg_files)))
        
        # Sync to ACC if using staging
        synced = False
        if use_staging and folder_paths.get("acc_path"):
            log("All exports complete, syncing to ACC...")
            try:
                sync_to_acc(
                    folder_paths["weekly"],
                    folder_paths["acc_path"],
                    heartbeat_callback
                )
                synced = True
                log("ACC sync successful - no deletion warnings!")
            except Exception as e:
                log("ACC sync failed: {}".format(str(e)), is_error=True)
                # Don't fail the whole export if sync fails
        
        export_results = {
            "folder_paths": folder_paths,
            "pdf_files": pdf_files,
            "dwg_files": dwg_files,
            "jpg_files": jpg_files,
            "synced": synced
        }
        
        return export_results
        
    except Exception as e:
        log("Export error: {}".format(str(e)), is_error=True)
        raise


if __name__ == "__main__":
    pass
