#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Helper functions for Excel sheet creation from Excel data."""

from EnneadTab import EXCEL, NOTIFICATION


def read_excel_data(excel_path, worksheet="SheetList", header_row=4):
    """Read Excel data and get header map.
    
    Args:
        excel_path (str): Path to Excel file
        worksheet (str): Worksheet name. Defaults to "SheetList"
        header_row (int): Row number containing headers (1-based). Defaults to 4
    
    Returns:
        tuple: (raw_data, header_map) or (None, None) if error
    """
    raw_data = EXCEL.read_data_from_excel(excel_path, worksheet=worksheet, return_dict=True)
    if not raw_data:
        NOTIFICATION.messenger(main_text="Cannot open this excel, Check if the worksheet name is correct.")
        return None, None
    
    header_map = EXCEL.get_header_map(raw_data, header_row)
    if not header_map:
        NOTIFICATION.messenger(main_text="Cannot find headers in excel. Make sure row {} contains column headers.".format(header_row))
        return None, None
    
    return raw_data, header_map


def find_filter_column(header_map):
    """Find the column that contains "YES" values for filtering rows.
    
    Based on the Excel template, this should be "Process?" column.
    
    Args:
        header_map (dict): Header column mapping
    
    Returns:
        int or None: Column index of filter column, or None if not found
    """
    # Exact header name from template: "Process?"
    for col, header in header_map.items():
        header_str = str(header).strip()
        if header_str == "Process?":
            return col
    
    return None


def find_sheet_number_column(header_map):
    """Find the Sheet Number column in the header map.
    
    Based on the Excel template, this should be "Sheet Num" column.
    
    Args:
        header_map (dict): Header column mapping
    
    Returns:
        tuple: (column_index, header_name) or (None, None) if not found
    """
    # Exact header name from template: "Sheet Num"
    for col, header in header_map.items():
        header_str = str(header).strip()
        if header_str == "Sheet Num":
            return col, header_str
    
    return None, None


def parse_excel_data(raw_data, sheet_number_header, header_row=4):
    """Parse Excel data into structured format.
    
    Args:
        raw_data (dict): Raw Excel data dictionary
        sheet_number_header (str): Header name for sheet number column
        header_row (int): Row number containing headers (1-based). Defaults to 4
    
    Returns:
        dict: Parsed data dictionary keyed by sheet number
    """
    return EXCEL.parse_excel_data(raw_data, sheet_number_header, header_row=header_row)


def filter_data_by_yes(raw_data, parsed_data, filter_column, sheet_number_col, header_row=4):
    """Filter parsed data to only include rows marked with "YES".
    
    Args:
        raw_data (dict): Raw Excel data dictionary
        parsed_data (dict): Parsed Excel data dictionary
        filter_column (int): Column index for filter values
        sheet_number_col (int): Column index for sheet number
        header_row (int): Row number containing headers (1-based). Defaults to 4
    
    Returns:
        list: List of RowData objects for filtered rows
    """
    if filter_column is None:
        # If no filter column, use all parsed data
        return list(parsed_data.values())
    
    filtered_data = []
    # Find max row in raw_data
    max_row = header_row
    for key in raw_data:  # type: ignore
        row, _ = key
        if row > max_row:
            max_row = row
    
    for row in range(header_row + 1, max_row + 1):
        filter_cell = raw_data.get((row, filter_column), {})  # type: ignore
        if str(filter_cell.get("value", "")).strip().upper() == "YES":
            # Get sheet number for this row
            sheet_num_cell = raw_data.get((row, sheet_number_col), {})  # type: ignore
            sheet_num = str(sheet_num_cell.get("value", "")).strip()
            if sheet_num and sheet_num in parsed_data:
                filtered_data.append(parsed_data[sheet_num])
    
    return filtered_data


def extract_sheet_numbers(filtered_data, sheet_number_header):
    """Extract sheet numbers from filtered data.
    
    Args:
        filtered_data (list): List of RowData objects
        sheet_number_header (str): Header name for sheet number column
    
    Returns:
        list: List of sheet number strings
    """
    new_sheet_numbers = []
    for row_data in filtered_data:
        sheet_num = row_data.get(sheet_number_header, "")
        if sheet_num and str(sheet_num).strip():
            new_sheet_numbers.append(str(sheet_num).strip())
    return new_sheet_numbers


def get_sheet_name(row_data):
    """Extract sheet name from row data.
    
    Based on the Excel template, this should be "Sheet Name" column.
    
    Args:
        row_data: RowData object from parsed Excel data
    
    Returns:
        str: Sheet name, or "Unnamed Sheet" if not found
    """
    # Exact header name from template: "Sheet Name"
    sheet_name = row_data.get("Sheet Name")
    if sheet_name and str(sheet_name).strip():
        return str(sheet_name).strip()
    
    return "Unnamed Sheet"


def set_sheet_group_parameter(sheet, row_data):
    """Set Sheet_$Group parameter from row data.
    
    Based on the Excel template, this should be "Sheet Group" column.
    
    Args:
        sheet: Revit ViewSheet object
        row_data: RowData object from parsed Excel data
    """
    # Exact header name from template: "Sheet Group"
    sheet_group = row_data.get("Sheet Group")
    if sheet_group and str(sheet_group).strip():
        try:
            sheet.LookupParameter("Sheet_$Group").Set(str(sheet_group).strip())
        except:
            pass


def set_sheet_series_parameter(sheet, row_data):
    """Set Sheet_$Series parameter from row data.
    
    Based on the Excel template, this should be "Sheet Series" column.
    
    Args:
        sheet: Revit ViewSheet object
        row_data: RowData object from parsed Excel data
    """
    # Exact header name from template: "Sheet Series"
    sheet_series = row_data.get("Sheet Series")
    if sheet_series and str(sheet_series).strip():
        try:
            sheet.LookupParameter("Sheet_$Series").Set(str(sheet_series).strip())
        except:
            pass


def set_translation_parameter(sheet, row_data):
    """Set MC_$Translate parameter from row data if translation value exists.
    
    Based on the Excel template, this should be "Translation(If needed for China Proj)" column.
    Only sets the parameter if a translation value is provided.
    
    Args:
        sheet: Revit ViewSheet object
        row_data: RowData object from parsed Excel data
    """
    # Exact header name from template: "Translation(If needed for China Proj)"
    translation_value = row_data.get("Translation(If needed for China Proj)")
    if translation_value and str(translation_value).strip():
        try:
            sheet.LookupParameter("MC_$Translate").Set(str(translation_value).strip())
        except:
            pass


def create_sheet_from_row_data(doc, row_data, titleblock_type_id, sheet_number_header):
    """Create a Revit sheet from row data.
    
    Args:
        doc: Revit Document object
        row_data: RowData object from parsed Excel data
        titleblock_type_id: Titleblock type ID
        sheet_number_header (str): Header name for sheet number column
    
    Returns:
        ViewSheet or None: Created sheet, or None if creation failed
    """
    from Autodesk.Revit import DB  # pyright: ignore
    
    # Get sheet number
    sheet_number = row_data.get(sheet_number_header, "")
    if not sheet_number or str(sheet_number).strip() == "":
        print("Sheet number is empty")
        return None
    
    sheet_number = str(sheet_number).strip()
    
    # Create sheet
    sheet = DB.ViewSheet.Create(doc, titleblock_type_id)
    sheet.SheetNumber = sheet_number
    
    # Set sheet name
    sheet_name = get_sheet_name(row_data)
    sheet.LookupParameter("Sheet Name").Set(sheet_name)
    
    # Set Sheet Group parameter
    set_sheet_group_parameter(sheet, row_data)
    
    # Set Sheet Series parameter
    set_sheet_series_parameter(sheet, row_data)
    
    # Set Translation parameter (if translation value exists)
    set_translation_parameter(sheet, row_data)
    
    return sheet

