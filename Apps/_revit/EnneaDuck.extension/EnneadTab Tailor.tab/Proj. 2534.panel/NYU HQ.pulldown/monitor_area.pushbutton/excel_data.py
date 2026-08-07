#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Excel Data Module - Handles Excel file reading and parsing
"""

import os
import config
from EnneadTab import EXCEL, NOTIFICATION


def enrich_sparse_data(raw_data, header_row):
    """
    Enrich sparse Excel data by filling in missing DEPARTMENT and DIVISION values.
    
    When a row has empty DEPARTMENT or DIVISION cells, searches upward through 
    previous rows to find the last non-empty value and fills it in.
    
    Args:
        raw_data (dict): Raw Excel data with (row, col) keys
        header_row (int): Row number of headers (1-based)
    
    Returns:
        dict: Enriched data with filled-in values
    """
    # Build header map to find column indices
    header_map = EXCEL.get_header_map(raw_data, header_row)
    
    # Find column indices for DEPARTMENT and DIVISION
    dept_col = None
    div_col = None
    for col, header in header_map.items():
        if header == config.DEPARTMENT_KEY[config.APP_EXCEL]:
            dept_col = col
        elif header == config.PROGRAM_TYPE_KEY[config.APP_EXCEL]:
            div_col = col
    
    if dept_col is None or div_col is None:
        print("Warning: Could not find DEPARTMENT or DIVISION columns for enrichment")
        return raw_data
    
    # Track last seen values for each column
    last_dept_value = None
    last_div_value = None
    
    # Get all unique row numbers after header
    row_numbers = sorted(set(row for row, col in raw_data.keys() if row > header_row))
    
    # Enrich data row by row
    for row in row_numbers:
        # Check DEPARTMENT column
        dept_key = (row, dept_col)
        if dept_key in raw_data:
            dept_value = raw_data[dept_key].get("value", "")
            if dept_value and dept_value.strip() and dept_value != "None":
                last_dept_value = dept_value
            elif last_dept_value:
                # Fill in missing value
                raw_data[dept_key]["value"] = last_dept_value
        elif last_dept_value:
            # Cell doesn't exist, create it
            raw_data[dept_key] = {"value": last_dept_value}
        
        # Check DIVISION column
        div_key = (row, div_col)
        if div_key in raw_data:
            div_value = raw_data[div_key].get("value", "")
            if div_value and div_value.strip() and div_value != "None":
                last_div_value = div_value
            elif last_div_value:
                # Fill in missing value
                raw_data[div_key]["value"] = last_div_value
        elif last_div_value:
            # Cell doesn't exist, create it
            raw_data[div_key] = {"value": last_div_value}
    
    return raw_data


def extract_color_from_color_column(raw_data, header_row):
    """
    Extract the actual cell background color from the COLOR column.
    
    The COLOR column's cell background color indicates the category color,
    not the text value in the cell.
    
    Args:
        raw_data (dict): Excel data with (row, col) keys containing 'value' and 'color'
        header_row (int): Row number of headers (1-based)
    
    Returns:
        dict: Enhanced data with COLOR column value replaced by actual cell color (RGB hex)
    """
    # Build header map to find COLOR column
    header_map = EXCEL.get_header_map(raw_data, header_row)
    
    # Find COLOR column index
    color_col = None
    for col, header in header_map.items():
        if header == "COLOR":
            color_col = col
            break
    
    if color_col is None:
        return raw_data
    
    # Get all unique row numbers after header
    row_numbers = sorted(set(row for row, col in raw_data.keys() if row > header_row))
    
    # Extract color from COLOR column cells
    for row in row_numbers:
        color_key = (row, color_col)
        if color_key in raw_data:
            # Get the cell's background color (RGB tuple)
            cell_color = raw_data[color_key].get("color", (None, None, None))
            
            # Convert RGB tuple to hex string if valid
            if cell_color and cell_color != (None, None, None):
                r, g, b = cell_color
                if r is not None and g is not None and b is not None:
                    # Convert to hex format: #RRGGBB
                    hex_color = "#{:02x}{:02x}{:02x}".format(r, g, b)
                    # Update the value to be the hex color
                    raw_data[color_key]["value"] = hex_color
                else:
                    raw_data[color_key]["value"] = None
            else:
                raw_data[color_key]["value"] = None
    
    return raw_data


def filter_rows_without_room_name(raw_data, header_row):
    """
    Filter out rows that don't have a ROOM NAME defined.
    
    These are typically section headers, department definitions, or comments
    that don't represent actual room data.
    
    Args:
        raw_data (dict): Excel data with (row, col) keys
        header_row (int): Row number of headers (1-based)
    
    Returns:
        dict: Filtered data with only rows that have ROOM NAME
    """
    # Build header map to find ROOM NAME column
    header_map = EXCEL.get_header_map(raw_data, header_row)
    
    # Find ROOM NAME column index
    room_name_col = None
    for col, header in header_map.items():
        if header == config.PROGRAM_TYPE_DETAIL_KEY[config.APP_EXCEL]:
            room_name_col = col
            break
    
    if room_name_col is None:
        print("Warning: Could not find ROOM NAME column for filtering")
        return raw_data
    
    # Get all unique row numbers after header
    row_numbers = sorted(set(row for row, col in raw_data.keys() if row > header_row))
    
    # Identify rows to keep (those with valid ROOM NAME)
    rows_to_keep = set()
    rows_to_remove = set()
    
    for row in row_numbers:
        room_name_key = (row, room_name_col)
        if room_name_key in raw_data:
            room_name_value = raw_data[room_name_key].get("value", "")
            # Keep row if ROOM NAME has a meaningful value
            if room_name_value and room_name_value.strip() and room_name_value != "None":
                rows_to_keep.add(row)
            else:
                rows_to_remove.add(row)
        else:
            # No ROOM NAME cell means empty, remove this row
            rows_to_remove.add(row)
    
    # Create filtered data dictionary
    filtered_data = {}
    for key, value in raw_data.items():
        row, col = key
        # Keep header row and all rows with valid ROOM NAME
        if row <= header_row or row in rows_to_keep:
            filtered_data[key] = value
    
    return filtered_data


def print_data_sample(data, header_row, title, max_rows=10):
    """
    Print a sample of Excel data for debugging.
    
    Args:
        data (dict): Excel data with (row, col) keys
        header_row (int): Row number of headers (1-based)
        title (str): Title for the output section
        max_rows (int): Maximum number of data rows to display
    """
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    
    # Get header map
    header_map = EXCEL.get_header_map(data, header_row)
    
    # Get unique row numbers
    row_numbers = sorted(set(row for row, col in data.keys() if row > header_row))[:max_rows]
    
    for row in row_numbers:
        print("\nRow {}:".format(row))
        for col in sorted(header_map.keys()):
            header = header_map[col]
            key = (row, col)
            value = data.get(key, {}).get("value", "<missing>")
            if value:
                print("  {} = {}".format(header, value))


def extract_color_hierarchy(raw_data, header_row):
    """
    Extract color mappings for DEPARTMENT, DIVISION, and ROOM NAME levels.
    
    This creates a hierarchical color map that is used to:
    1. Update Revit color schemes (Department Category_Primary, Division_Primary, RoomName_Primary)
    2. Style HTML reports with consistent colors
    
    Args:
        raw_data (dict): Raw Excel data with (row, col) keys
        header_row (int): Row number of headers (1-based)
    
    Returns:
        dict: Color hierarchy with mappings at all levels
        {
            'department': {'DEPARTMENT_NAME': '#color', ...},
            'division': {'DIVISION_NAME': '#color', ...},
            'room_name': {'ROOM_NAME': '#color', ...}
        }
    """
    # Build header map
    header_map = EXCEL.get_header_map(raw_data, header_row)
    
    # Find column indices
    dept_col = None
    div_col = None
    room_col = None
    color_col = None
    
    for col, header in header_map.items():
        if header == config.DEPARTMENT_KEY[config.APP_EXCEL]:
            dept_col = col
        elif header == config.PROGRAM_TYPE_KEY[config.APP_EXCEL]:
            div_col = col
        elif header == config.PROGRAM_TYPE_DETAIL_KEY[config.APP_EXCEL]:
            room_col = col
        elif header == "COLOR":
            color_col = col
    
    color_hierarchy = {
        'department': {},
        'division': {},
        'room_name': {}
    }
    
    if color_col is None:
        print("Warning: No COLOR column found for color hierarchy extraction")
        return color_hierarchy
    
    # Get all unique row numbers after header
    row_numbers = sorted(set(row for row, col in raw_data.keys() if row > header_row))
    
    for row in row_numbers:
        # Get values for this row
        dept_value = raw_data.get((row, dept_col), {}).get("value", "") if dept_col else ""
        div_value = raw_data.get((row, div_col), {}).get("value", "") if div_col else ""
        room_value = raw_data.get((row, room_col), {}).get("value", "") if room_col else ""
        color_value = raw_data.get((row, color_col), {}).get("value", "")
        
        # Skip rows without color
        if not color_value or not color_value.startswith("#"):
            continue
        
        # Map colors to each level independently
        # If row has a DEPARTMENT value and color, map it
        if dept_value and dept_value.strip() and dept_value != "None":
            if dept_value not in color_hierarchy['department']:
                color_hierarchy['department'][dept_value] = color_value
        
        # If row has a DIVISION value and color, map it
        if div_value and div_value.strip() and div_value != "None":
            if div_value not in color_hierarchy['division']:
                color_hierarchy['division'][div_value] = color_value
        
        # If row has a ROOM NAME value and color, map it
        if room_value and room_value.strip() and room_value != "None":
            if room_value not in color_hierarchy['room_name']:
                color_hierarchy['room_name'][room_value] = color_value
    
    print("Color hierarchy extracted: {} dept, {} div, {} room colors".format(
        len(color_hierarchy['department']),
        len(color_hierarchy['division']),
        len(color_hierarchy['room_name'])
    ))
    
    return color_hierarchy


def add_composite_key_column(raw_data, header_row):
    """
    Add a composite key column (DEPT|DIV|ROOM) to prevent data loss from duplicate room names.
    Must be called BEFORE parse_excel_data to preserve all rows.
    """
    if not config.USE_COMPOSITE_KEY:
        return raw_data
    
    # Get header map
    header_map = EXCEL.get_header_map(raw_data, header_row)
    
    # Find column indices
    dept_col = None
    div_col = None
    room_col = None
    
    for col, header in header_map.items():
        if header == config.DEPARTMENT_KEY[config.APP_EXCEL]:
            dept_col = col
        elif header == config.PROGRAM_TYPE_KEY[config.APP_EXCEL]:
            div_col = col
        elif header == config.PROGRAM_TYPE_DETAIL_KEY[config.APP_EXCEL]:
            room_col = col
    
    # Find next available column for composite key
    max_col = max(col for row, col in raw_data.keys())
    composite_col = max_col + 1
    
    # Add composite key header
    raw_data[(header_row, composite_col)] = {"value": config.COMPOSITE_KEY_COLUMN_NAME}
    
    # Get all unique row numbers after header
    row_numbers = sorted(set(row for row, col in raw_data.keys() if row > header_row))
    
    # Add composite key values
    for row in row_numbers:
        dept = raw_data.get((row, dept_col), {}).get("value", "") if dept_col else ""
        div = raw_data.get((row, div_col), {}).get("value", "") if div_col else ""
        room = raw_data.get((row, room_col), {}).get("value", "") if room_col else ""
        
        composite_key = "{}{}{}{}{}".format(
            dept,
            config.COMPOSITE_KEY_SEPARATOR,
            div,
            config.COMPOSITE_KEY_SEPARATOR,
            room
        )
        raw_data[(row, composite_col)] = {"value": composite_key}
    
    print("Added composite key column to {} rows".format(len(row_numbers)))
    return raw_data


def get_excel_data():
    """
    Read and parse Excel data using configuration from config.py
    
    Returns:
        tuple: (parsed_data, color_hierarchy)
        - parsed_data: dict with RowData objects keyed by room name
        - color_hierarchy: dict with color mappings at department/division/room levels
    """
    # Use absolute path if provided, otherwise treat as relative
    if os.path.isabs(config.EXCEL_FILENAME):
        excel_path = config.EXCEL_FILENAME
    else:
        excel_path = os.path.join(os.path.dirname(__file__), config.EXCEL_FILENAME)
    
    # Read and process Excel data
    print("Reading Excel: {}".format(excel_path))
    
    try:
        raw_data = EXCEL.read_data_from_excel(
            excel_path, 
            worksheet=config.EXCEL_WORKSHEET, 
            return_dict=True
        )
    except Exception as ex:
        error_message = str(ex)
        notification_message = "Cannot open Excel file at {}.\n\nYour J drive may be disconnected or the Excel file has been renamed.".format(excel_path)
        if error_message:
            notification_message = "{}\n\nError: {}".format(notification_message, error_message)
        NOTIFICATION.messenger(notification_message)
        raise
    
    # Extract colors from COLOR column
    color_extracted_data = extract_color_from_color_column(raw_data, config.EXCEL_HEADER_ROW)
    
    # Extract color hierarchy (Department/Division/Room levels)
    color_hierarchy = extract_color_hierarchy(color_extracted_data, config.EXCEL_HEADER_ROW)
    
    # Enrich sparse data
    enriched_data = enrich_sparse_data(color_extracted_data, config.EXCEL_HEADER_ROW)
    
    # Add composite key column if enabled (BEFORE parsing to prevent data loss)
    if config.USE_COMPOSITE_KEY:
        enriched_data = add_composite_key_column(enriched_data, config.EXCEL_HEADER_ROW)
    
    # Count rows before filtering
    rows_before = len(set(row for row, col in enriched_data.keys() if row > config.EXCEL_HEADER_ROW))
    print("Total rows in Excel (after header): {}".format(rows_before))
    
    # Filter out rows without ROOM NAME
    filtered_data = filter_rows_without_room_name(enriched_data, config.EXCEL_HEADER_ROW)
    
    # Count rows after filtering
    rows_after = len(set(row for row, col in filtered_data.keys() if row > config.EXCEL_HEADER_ROW))
    print("Rows with ROOM NAME filled: {}".format(rows_after))
    print("Rows filtered out (no ROOM NAME): {}".format(rows_before - rows_after))
    
    # Parse into structured format (use composite key if enabled)
    parse_key = config.COMPOSITE_KEY_COLUMN_NAME if config.USE_COMPOSITE_KEY else config.EXCEL_PRIMARY_KEY
    parsed_data = EXCEL.parse_excel_data(
        filtered_data, 
        key_name=parse_key, 
        header_row=config.EXCEL_HEADER_ROW
    )
    
    print("Excel processing complete - {} requirement entries loaded".format(len(parsed_data)))
    
    return parsed_data, color_hierarchy
