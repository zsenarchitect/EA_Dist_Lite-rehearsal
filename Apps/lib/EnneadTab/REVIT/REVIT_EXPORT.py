#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
EnneadTab REVIT Export Module

This module provides comprehensive export functionality for Revit documents, supporting:
- PDF export with configurable color and paper size settings
- DWG export with customizable export settings
- Image export (JPG) with resolution control
- Batch export capabilities with file organization

Key Features:
- Smart print setting detection based on sheet properties
- Multiple export methods for PDF to handle different scenarios
- Support for view-on-sheet exports
- Automatic file naming and organization
- PDF combination utilities
- Robust error handling and retry mechanisms

Dependencies:
    - pyrevit
    - Autodesk.Revit.DB
    - EnneadTab modules: FOLDER, IMAGE, DATA_CONVERSION, PDF, ERROR_HANDLE

Note:
    This module is part of the EnneadTab toolkit and requires Revit API access.
"""

import os
import sys
root_folder = os.path.abspath((os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(root_folder)

import FOLDER
import IMAGE
import DATA_CONVERSION
import PDF
import ERROR_HANDLE

try:
    from pyrevit import script # pyright: ignore
    from Autodesk.Revit import DB # pyright: ignore

except :

    pass

class NonExportableViewsException(Exception):
    """Custom exception for non-exportable views - used to skip export gracefully."""
    pass

def print_time(title, time_end, time_start, use_minutes = False):
    output = script.get_output()
    if not use_minutes:
        foot_note = "{} seconds".format( time_end - time_start)
        output.print_md("{} takes **{}** seconds".format(title, time_end - time_start))
        return foot_note
    mins = int((time_end - time_start)/60)
    output.print_md("{} takes **{}** mins".format(title, mins))
    foot_note = "{} mins".format( mins)
    return foot_note


def get_print_setting(doc, is_color_by_sheet, is_color = True, is_A1_paper = True):
    """Retrieves appropriate print settings based on color and paper size preferences.

    Args:
        doc (DB.Document): Active Revit document
        is_color_by_sheet (bool): Whether to use sheet-specific color settings
        is_color (bool, optional): Use color printing. Defaults to True.
        is_A1_paper (bool, optional): Use A1 paper size. Defaults to True.

    Returns:
        DB.PrintSetting: Selected print setting matching the specified criteria
    """


    all_print_settings = DB.FilteredElementCollector(doc).OfClass(DB.PrintSetting)

    if is_color_by_sheet:
        is_color = False

    if is_color:
        all_print_settings = filter(lambda x: "COLOR" in x.Name, all_print_settings)
    else:
        all_print_settings = filter(lambda x: "GRAYSCALE" in x.Name, all_print_settings)

    if is_A1_paper:
        all_print_settings = filter(lambda x: "A1" in x.Name, all_print_settings)
    else:
        all_print_settings = filter(lambda x: "A0" in x.Name, all_print_settings)

    #print all_print_settings[0].Name
    if len(all_print_settings) > 0:
        return all_print_settings[0]
    print ("!!!Cannot find print setting that has 'COLOR/GRAYSCALE' or 'A1/A0' in it. Use default")
    return DB.FilteredElementCollector(doc).OfClass(DB.PrintSetting).FirstElement()

def export_pdf(view_or_sheet, file_name_naked, output_folder, is_color_by_sheet):
    """Exports a view or sheet to PDF using optimal export method.

    The function attempts multiple export methods to ensure successful export:
    - Method 1: Uses PrintManager with Bluebeam PDF printer
    - Method 2: Uses native PDF export with custom naming rules

    Args:
        view_or_sheet (DB.View | DB.ViewSheet): View or sheet to export
        file_name_naked (str): Target filename (without .pdf extension)
        output_folder (str): Output directory path
        is_color_by_sheet (bool): Whether to use sheet-specific color settings

    Returns:
        str: Name of exported PDF file if successful, None if export was skipped due to non-exportable views
    """
    doc = view_or_sheet.Document

    # Check if views on sheet are exportable before attempting export
    non_exportable_views = []
    has_export_issue = False
    try:
        # Check if this is a sheet with views on it
        if view_or_sheet.ViewType.ToString() == "DrawingSheet":
            view_ids = view_or_sheet.GetAllPlacedViews()
            for view_id in view_ids:
                view = doc.GetElement(view_id)
                if view:
                    # Check if view can be printed/exported
                    try:
                        # Some view types cannot be exported (e.g., certain 3D views, schedules in some contexts)
                        # Try to access CanBePrinted property if available
                        if hasattr(view, 'CanBePrinted') and not view.CanBePrinted:
                            non_exportable_views.append("{} ({})".format(view.Name, view.ViewType.ToString()))
                            has_export_issue = True
                    except:
                        # If CanBePrinted is not available or throws error, check view type
                        # Some view types are known to be non-exportable
                        view_type_str = view.ViewType.ToString()
                        if view_type_str in ["Rendering", "Walkthrough"]:
                            non_exportable_views.append("{} ({})".format(view.Name, view_type_str))
                            has_export_issue = True
                        # Also check for invalid or broken views
                        try:
                            if not view.IsValidObject:
                                non_exportable_views.append("{} ({}) - Invalid view".format(view.Name, view_type_str))
                                has_export_issue = True
                        except:
                            pass
        # If it's a view (not a sheet), check if the view itself is exportable
        else:
            try:
                if hasattr(view_or_sheet, 'CanBePrinted') and not view_or_sheet.CanBePrinted:
                    non_exportable_views.append("{} ({})".format(view_or_sheet.Name, view_or_sheet.ViewType.ToString()))
                    has_export_issue = True
            except:
                # Check view type for known non-exportable types
                view_type_str = view_or_sheet.ViewType.ToString()
                if view_type_str in ["Rendering", "Walkthrough"]:
                    non_exportable_views.append("{} ({})".format(view_or_sheet.Name, view_type_str))
                    has_export_issue = True
                # Check for invalid views
                try:
                    if not view_or_sheet.IsValidObject:
                        non_exportable_views.append("{} ({}) - Invalid view".format(view_or_sheet.Name, view_type_str))
                        has_export_issue = True
                except:
                    pass
    except Exception as e:
        print("Warning: Could not check views for exportability: {}".format(str(e)))

    # If we detected non-exportable views, skip export gracefully
    if has_export_issue and non_exportable_views:
        if view_or_sheet.ViewType.ToString() == "DrawingSheet":
            item_info = "Sheet: {} ({})".format(view_or_sheet.SheetNumber, view_or_sheet.Name)
        else:
            item_info = "View: {} ({})".format(view_or_sheet.Name, view_or_sheet.ViewType.ToString())
        
        warning_msg = "SKIPPED: {} contains non-exportable views:\n  - {}".format(
            item_info, 
            "\n  - ".join(non_exportable_views)
        )
        print("PDF Export Warning: {}".format(warning_msg))
        # Return None to indicate export was skipped - calling code should handle this
        return None

    def override_blue_lines():
        pass

    def dry_transaction_decorator(f):
        def warper():
            t = DB.Transaction(doc, "dry T")
            t.Start()
            f()
            t.RollBack()
        return warper



    def pdf_method_1():
        #  ----- method 1 -----
        print ("$$$ Trying method 1")
        t = DB.Transaction(doc, "temp")
        t.Start()


        titleBlock = DB.FilteredElementCollector(doc, view_or_sheet.Id).OfCategory(DB.BuiltInCategory.OST_TitleBlocks).FirstElement()
        #print titleBlock.Symbol.Family.Name


        print_manager = doc.PrintManager
        print_manager.PrintToFile = True
        #print_manager.IsVirtual = True
        print_manager.SelectNewPrintDriver("Bluebeam PDF")
        # print_manager.Apply()

        if view_or_sheet.LookupParameter("Print_In_Color"):
            sheet_use_color = view_or_sheet.LookupParameter("Print_In_Color").AsInteger()
        else:
            sheet_use_color = 0
            print ("Cannot find 'Print_In_Color' in sheet para...Use NO color as default.")
        print_manager.PrintSetup.CurrentPrintSetting = get_print_setting(doc,
                                                                        is_color_by_sheet,
                                                                        is_color = sheet_use_color,
                                                                        is_A1_paper = "A1" in titleBlock.Symbol.Family.Name)
        # print_manager.Apply()
        #t.Commit()
        #"""
        print ("Print Setting Name = [{}]".format(print_manager.PrintSetup.CurrentPrintSetting.Name))
        print_manager.PrintToFileName = os.path.join(output_folder, "{}.pdf".format(file_name_naked))
        print_manager.PrintRange = DB.PrintRange.Select
        view_set = DB.ViewSet()
        view_set.Insert(view_or_sheet)
        try:
            print_manager.ViewSheetSetting.InSession.Views = view_set
        except:
            print ("InSession ViewSheetSet failed, trying with CurrentViewSheetSet...")
            print_manager.ViewSheetSetting.CurrentViewSheetSet.Views = view_set
        # print_manager.Apply()
        # t.Commit()
        #print print_manager.PrintToFileName

        """might be important again"""
        #reactivate_output()

        while True:
            try:
                try:
                    print_manager.SubmitPrint(view_or_sheet)
                except:
                    print ("2nd method")
                    print_manager.SubmitPrint()
                print ("PDF export successfully")
                break
            except Exception as e:
                if  "The files already exist!" in e:
                    raw_name = file_name_naked + "_same name"
                    new_name = print_manager.PrintToFileName = "{}\\{}.pdf".format(output_folder, file_name_naked)
                    print ("------**There is a file existing with same name, will attempt to save as {}**".format(new_name))

                elif "no views/sheets selected" in e:
                    print (e)
                    print ("...")
                    print (print_manager.PrintToFileName)
                    print ("problem sheet = {}".format(view_or_sheet.Name))
                    has_non_print_sheet = True
                else:
                    print (e)
                    print (print_manager.PrintToFileName)
                    print ("problem sheet = {}".format(view_or_sheet.Name))
                break

        t.RollBack()
        #print t.GetStatus()

        """might be important again"""
        #cleanup_pdf_name()
        FOLDER.secure_filename_in_folder(output_folder, file_name_naked, ".pdf")

        print ("$$$ end method 1")

    def pdf_method_2():
        #  ----- method 2 -----
        #print "$$$ Trying method 2"

        sheet_list = DATA_CONVERSION.list_to_system_list([view_or_sheet.Id])


        pdf_options = DB.PDFExportOptions ()
        pdf_options.Combine = False



        name_rule = pdf_options.GetNamingRule ()
        #print name_rule

        sheet_num_para_data = DB.TableCellCombinedParameterData.Create()
        sheet_num_para_data.ParamId = DB.ElementId(DB.BuiltInParameter.SHEET_NUMBER)
        if len(file_name_naked.split(view_or_sheet.SheetNumber)) == 1:
            sheet_num_para_data.Prefix = ""
        else:
            sheet_num_para_data.Prefix = file_name_naked.split(view_or_sheet.SheetNumber)[0]
        sheet_num_para_data.Separator = " - "

        sheet_name_para_data = DB.TableCellCombinedParameterData.Create()
        sheet_name_para_data.ParamId = DB.ElementId(DB.BuiltInParameter.SHEET_NAME)

        # IList<TableCellCombinedParameterData> GetNamingRule()
        new_rule = [sheet_num_para_data, sheet_name_para_data]
        new_rule = DATA_CONVERSION.list_to_system_list(new_rule, type = "TableCellCombinedParameterData", use_IList = False)
        pdf_options.SetNamingRule(new_rule)

        if view_or_sheet.LookupParameter("Print_In_Color"):
            sheet_color_setting = view_or_sheet.LookupParameter("Print_In_Color").AsInteger()
        else:
            sheet_color_setting = 0

        if not is_color_by_sheet:
            sheet_color_setting = 0
        if sheet_color_setting:
            pdf_options.ColorDepth = DB.ColorDepthType.Color
        else:
            pdf_options.ColorDepth = DB.ColorDepthType.GrayScale

        #pdf_options.ExportPaperFormat = DB.ExportPaperFormat.Default

        # Attempt export with error handling
        # Note: We check for non-exportable views before calling this function,
        # but we still handle export failures here in case some cases are missed
        try:
            doc.Export(output_folder, sheet_list, pdf_options)
        except Exception as e:
            error_msg = str(e)
            # Check for non-exportable view errors
            if "not printable" in error_msg.lower() or "not exportable" in error_msg.lower() or "exportable" in error_msg.lower() or "some of the views are not" in error_msg.lower():
                # Build detailed error message
                if view_or_sheet.ViewType.ToString() == "DrawingSheet":
                    item_info = "Sheet: {} ({})".format(view_or_sheet.SheetNumber, view_or_sheet.Name)
                else:
                    item_info = "View: {} ({})".format(view_or_sheet.Name, view_or_sheet.ViewType.ToString())
                
                detailed_msg = "SKIPPED: {} cannot be exported. This may be due to:\n  - Views with certain display modes\n  - Views with broken references\n  - Views that are not printable\n\nOriginal error: {}".format(item_info, error_msg)
                
                print("PDF Export Warning: {}".format(detailed_msg))
                # Raise a custom exception that we'll catch in the outer function
                raise NonExportableViewsException(detailed_msg)
            else:
                # Re-raise other exceptions as they are unexpected
                raise
        #print "$$$ end method 2"

    # Call pdf_method_2 and handle exceptions
    try:
        pdf_method_2()
    except NonExportableViewsException:
        # Export was skipped due to non-exportable views - return None gracefully
        return None
    
    return file_name_naked + ".pdf"




def export_dwg(view_or_sheet, file_name, output_folder, dwg_setting_name, is_export_view_on_sheet = False):
    """Exports views or sheets to DWG format with specified settings.

    Features:
    - Supports both individual view/sheet export and view-on-sheet export
    - Automatic file naming based on sheet information
    - Retry mechanism for failed exports
    - Cleanup of temporary files

    Args:
        view_or_sheet (DB.View | DB.ViewSheet): View or sheet to export
        file_name (str): Target filename (without .dwg extension)
        output_folder (str): Output directory path
        dwg_setting_name (str): Name of DWG export settings to use
        is_export_view_on_sheet (bool, optional): Export individual views from sheets. Defaults to False.

    Returns:
        list: List of exported DWG filenames
    """
    files_exported = []
    doc = view_or_sheet.Document

    if is_export_view_on_sheet and view_or_sheet.ViewType.ToString() == "DrawingSheet":
        view_ids = view_or_sheet.GetAllPlacedViews()
        #useful_sheet_count = 0
        for view_id in view_ids:
            view = doc.GetElement(view_id)

            if view.ViewType.ToString() in [ "Legend","Schedule", "Rendering"]:
                continue

            if "{3D" in view.Name:
                continue

            #useful_sheet_count += 1
            detail_num_para_id = DB.BuiltInParameter.VIEWPORT_DETAIL_NUMBER
            detail_num = view.Parameter[detail_num_para_id].AsString() #get view detail num
            title_para_id = DB.BuiltInParameter.VIEW_DESCRIPTION
            title = view.Parameter[title_para_id].AsString() #get view title

            # prefix is that [2]_123_
            if len(file_name.split(view_or_sheet.SheetNumber)) == 1:
                prefix = ""
            else:
                prefix = file_name.split(view_or_sheet.SheetNumber)[0]

            view_file_name = "{}{}_{}_{}_[View On Sheet]".format(prefix, view_or_sheet.SheetNumber, detail_num, title)

            print ("Exporting view on sheet: {}.dwg".format(view_file_name))
            dwg_file = export_dwg(view, view_file_name, output_folder, dwg_setting_name, is_export_view_on_sheet)
            files_exported.extend(dwg_file)

    #DWG_export_setting = get_export_setting(doc, export_setting_name)
    DWG_option = DB.DWGExportOptions().GetPredefinedOptions(doc, dwg_setting_name)
    view_as_collection = DATA_CONVERSION.list_to_system_list([view_or_sheet.Id])
    max_attempt = 10
    attempt = 0
    while True:
        if attempt > max_attempt:
            print  ("Give up on <{}>, too many failed attempts, see reason above.".format(file_name))
            #global failed_export
            #failed_export.append(file_name)
            break
        attempt += 1
        try:
            doc.Export(output_folder, file_name, view_as_collection, DWG_option)
            #print "DWG export successfully: " + file_name
            break
        except Exception as e:
            if  "The files already exist!" in e:
                file_name = file_name + "_same name"
                #new_name = print_manager.PrintToFileName = r"{}\{}.pdf".format(output_folder, file_name)
                print("------**There is a file existing with same name, will attempt to save as {}**".format(file_name))

            else:
                print (e)
    FOLDER.cleanup_folder_by_extension(folder = output_folder, extension = ".pcp")
    files_exported.append(file_name + ".dwg")
    return files_exported



def export_image(view_or_sheet, file_name_naked, output_folder, is_thumbnail = False, resolution = 6000, is_color_by_sheet = True):
    """Exports views or sheets to JPG format with configurable settings.

    Features:
    - Configurable resolution for both thumbnails and full-size exports
    - Support for color/grayscale conversion based on sheet settings
    - Automatic file management and cleanup
    - Retry mechanism for failed exports

    Args:
        view_or_sheet (DB.View | DB.ViewSheet): View or sheet to export
        file_name (str): Target filename (without .jpg extension)
        output_folder (str): Output directory path
        is_thumbnail (bool, optional): Create smaller thumbnail version. Defaults to False.
        resolution (int, optional): Image resolution in pixels. Defaults to 6000.
        is_color_by_sheet (bool, optional): Use sheet-specific color settings. Defaults to True.

    Returns:
        str: Name of exported JPG file if successful, False otherwise
    """
    
    doc = view_or_sheet.Document



    opts = DB.ImageExportOptions()
    try:
        opts.FilePath = output_folder + '\\{}.jpg'.format(file_name_naked)
    except Exception as e:
        print ("Error in export_image: {} - {}".format(file_name_naked, str(e)))
        return False
    

        
    opts.ImageResolution = DB.ImageResolution.DPI_300
    opts.ExportRange = DB.ExportRange.SetOfViews
    opts.ZoomType = DB.ZoomFitType.FitToPage

    opts.PixelSize = 1200 if is_thumbnail else resolution

    opts.SetViewsAndSheets(DATA_CONVERSION.list_to_system_list([view_or_sheet.Id]))

    attempt = 0
    max_attempt = 5
    if os.path.exists(opts.FilePath):
        try:
            os.remove(opts.FilePath)
        except:
            pass
        
        
    while True:
        if attempt > max_attempt:
            print  ("Give up on <{}>, too many failed attempts, see reason above.".format(file_name_naked))
            return False
            
        attempt += 1

        try:

            doc.ExportImage(opts)
            # print ("Image export successfully")

            break
        except Exception as e:
            if  "The files already exist!" in str(e):
                file_name_naked = file_name_naked + "_same name"
                opts.FilePath = output_folder + '\\{}.jpg'.format(file_name_naked)
                #new_name = print_manager.PrintToFileName = r"{}\{}.pdf".format(output_folder, file_name)
                print("------**There is a file existing with same name, will attempt to save as {}**".format(file_name_naked))

            else:
                print("Export failed: {}".format(str(e)))
                if attempt >= max_attempt:
                    return False


    # this si still needed becasue exported image will add a -Sheet- thing in file name.
    FOLDER.secure_filename_in_folder(output_folder, file_name_naked, ".jpg")
 

    if view_or_sheet.LookupParameter("Print_In_Color"):
        sheet_is_colored = view_or_sheet.LookupParameter("Print_In_Color").AsInteger() == 1
    else:
        sheet_is_colored = False

    if not is_color_by_sheet:
        sheet_is_colored = False
    if not sheet_is_colored:
        file_path = "{}\\{}.jpg".format(output_folder, file_name_naked)
        FOLDER.wait_until_file_is_ready(file_path)

        
        try:
            result = IMAGE.convert_image_to_greyscale(file_path)
            if result:
                # result is the actual filename that was saved (might be different from original)
                return result
            else:
                print("Greyscale conversion returned False")
                return file_name_naked + ".jpg"  # Return original file if conversion fails
        except Exception as e:
            print("Failed to convert image to greyscale in step 1: {}".format(str(e)))
            import traceback
            ERROR_HANDLE.print_note(traceback.format_exc())
            bw_file = "{}\\{}_BW.jpg".format(output_folder, file_name_naked)
            try:
                result = IMAGE.convert_image_to_greyscale(file_path, bw_file)
                if result:
                    # result is the actual filename that was saved
                    os.remove(file_path)
                    return result
                else:
                    print("Greyscale conversion step 2 returned False")
                    return file_name_naked + ".jpg"  # Return original file if conversion fails
            except Exception as e:
                print("Failed to convert image to greyscale in step 2: {}".format(str(e)))
                import traceback
                ERROR_HANDLE.print_note(traceback.format_exc())
                return file_name_naked + ".jpg"  # Return original file if conversion fails
    return file_name_naked + ".jpg"


                    
def combine_final_pdf(output_folder, files_exported_for_this_issue, combined_pdf_name, copy_folder = None):
    """Combines multiple PDFs into a single document with optional backup.

    Args:
        output_folder (str): Directory containing source PDFs
        files_exported_for_this_issue (list): List of PDF filenames to combine
        combined_pdf_name (str): Name for combined PDF file
        copy_folder (str, optional): Backup directory path. Defaults to None.
    """

    list_of_filepaths = []
    files = os.listdir(output_folder)

    for file in files:
        if ".pdf" not in file.lower():
            continue

        if file in files_exported_for_this_issue:
            file_path = os.path.join(output_folder, file)
            print ("--combining PDF: {}".format(file_path))
            list_of_filepaths.append(file_path)

    combined_pdf_file_path = os.path.join(output_folder, "{}.pdf".format(combined_pdf_name))
    PDF.pdfs2pdf(combined_pdf_file_path, list_of_filepaths, reorder = True)
    if copy_folder:
        FOLDER.copy_file_or_folder_to_folder(combined_pdf_file_path, copy_folder)


def dump_exported_files_to_copy_folder(output_folder, files_exported_for_this_issue, file_id_dict, copy_folder):
    """Organizes exported files into a structured directory hierarchy.

    Creates a organized directory structure based on file types and plot IDs:
    - PDFs/[plot_id]/
    - DWGs/[plot_id]/
    - JPGs/[plot_id]/

    Args:
        output_folder (str): Source directory containing exported files
        files_exported_for_this_issue (list): List of files to organize
        file_id_dict (dict): Mapping of filenames to plot IDs
        copy_folder (str): Root directory for organized file structure
    """


    for file in os.listdir(output_folder):
        if file in files_exported_for_this_issue:
            file_path = os.path.join(output_folder, file)


            try:
                plot_id = file_id_dict[file]
            except:
                plot_id = "Missing"



            if ".pdf" in file.lower():
                if plot_id:
                    new_folder = os.path.join(copy_folder, plot_id, "PDFs")
                else:
                    new_folder = os.path.join(copy_folder, "PDFs")
                new_folder = FOLDER.secure_folder(new_folder)

            elif ".dwg" in file.lower():
                if plot_id:
                    new_folder = os.path.join(copy_folder, plot_id, "DWGs")
                else:
                    new_folder = os.path.join(copy_folder, "DWGs")
                new_folder = FOLDER.secure_folder(new_folder)

            elif ".jpg" in file.lower():
                if plot_id:
                    new_folder = os.path.join(copy_folder, plot_id, "JPGs")
                else:
                    new_folder = os.path.join(copy_folder, "JPGs")
                new_folder = FOLDER.secure_folder(new_folder)

            else:
                new_folder = copy_folder[:]

            FOLDER.copy_file_or_folder_to_folder(file_path, new_folder, handle_BW_file = True)