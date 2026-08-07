# -*- coding: utf-8 -*-
"""
GFA Excel Import Utility

This module provides functionality to import GFA (Gross Floor Area) target data
from Excel files into the Rhino GFA system.

Features:
- Read Excel files with GFA target data
- Parse and validate imported data
- Merge with existing GFA targets
- Support for different Excel formats and structures

Usage:
- Called from GFA target dialog import button
- Simulates Excel reading with print statements for testing
"""

import rhinoscriptsyntax as rs # pyright: ignore
import scriptcontext as sc # pyright: ignore
from EnneadTab import ERROR_HANDLE, EXCEL, NOTIFICATION
from EnneadTab.RHINO import RHINO_PROJ_DATA

class GFAExcelImporter:
    """Handles importing GFA target data from Excel files"""
    
    def __init__(self):
        self.supported_formats = ['.xlsx', '.xls']
        self.expected_columns = ['Keyword', 'TargetArea']
        self.expected_worksheet = 'Target Area'
        
    def import_from_excel(self, filepath=None):
        """
        Import GFA targets from Excel file
        
        Args:
            filepath (str): Path to Excel file. If None, will prompt user to select.
            
        Returns:
            dict: Dictionary of imported GFA targets {keyword: area_value}
        """
        print("=== GFA Excel Import Process Started ===")
        
        if not filepath:
            filepath = self.select_excel_file()
            if not filepath:
                print("No Excel file selected")
                return None
                
        print("Selected Excel file: {}".format(filepath))
        
        # Read Excel file using EnneadTab.EXCEL
        imported_data = self.read_excel_file(filepath)
        
        if imported_data:
            print("Successfully imported {} GFA targets from Excel".format(len(imported_data)))
            return imported_data
        else:
            print("Failed to import data from Excel file")
            return None
    
    def select_excel_file(self):
        """Open file dialog to select Excel file"""
        print("Opening file selection dialog...")
        print("Looking for Excel files with extensions: {}".format(self.supported_formats))
        
        try:
            # Use Rhino's file dialog to select Excel file
            print("Calling rs.OpenFileName...")
            print("rs module available: {}".format(rs is not None))
            print("rs.OpenFileName available: {}".format(hasattr(rs, 'OpenFileName')))
            
            filepath = rs.OpenFileName("Select Excel file with GFA targets", "Excel Files (*.xlsx;*.xls)|*.xlsx;*.xls||")
            print("rs.OpenFileName returned: {}".format(filepath))
            
            if filepath:
                print("Selected Excel file: {}".format(filepath))
                return filepath
            else:
                print("No Excel file selected (user cancelled or error)")
                return None
                
        except Exception as ex:
            print("Error opening file dialog: {}".format(str(ex)))
            return None
    
    def read_excel_file(self, filepath):
        """
        Read Excel file and extract GFA target data using EnneadTab.EXCEL
        
        Args:
            filepath (str): Path to Excel file
            
        Returns:
            dict: Dictionary of GFA targets
        """
        print("=== Reading Excel File with EnneadTab.EXCEL ===")
        print("File path: {}".format(filepath))
        
        # Validate file format
        if not self.validate_file_format(filepath):
            return None
            
        print("File format validated successfully")
        
        try:
            # Read Excel data using EnneadTab.EXCEL with structured parsing
            print("Reading worksheet: 'Target Area'")
            excel_data = EXCEL.read_data_from_excel(filepath, worksheet="Target Area", return_dict=True)
            
            if excel_data and len(excel_data) > 0:
                print("Successfully read data from worksheet: 'Target Area'")
                print("Found {} cells of data".format(len(excel_data)))
                
                # Try EnneadTab.EXCEL's structured parsing method first
                gfa_targets = self.parse_excel_data_structured(excel_data)
                
                if gfa_targets:
                    print("Found {} GFA targets using structured parsing".format(len(gfa_targets)))
                    return gfa_targets
                else:
                    print("Structured parsing failed, trying manual parsing...")
                    # Fallback to manual parsing
                    gfa_targets = self.parse_excel_data(excel_data)
                    
                    if gfa_targets:
                        print("Found {} GFA targets using manual parsing".format(len(gfa_targets)))
                        return gfa_targets
                    else:
                        print("No valid GFA target data found in worksheet: 'Target Area'")
                        print("Expected headers: 'Keyword' and 'TargetArea' (or 'Target Area')")
                        print("Please ensure your Excel file has:")
                        print("  - Worksheet named exactly: 'Target Area'")
                        print("  - Headers: 'Keyword' and 'TargetArea' (or 'Target Area')")
                        return None
            else:
                print("No data found in worksheet: 'Target Area'")
                print("Please ensure your Excel file has:")
                print("  - Worksheet named exactly: 'Target Area'")
                print("  - Headers: 'Keyword' and 'TargetArea' (or 'Target Area')")
                return None
            
        except Exception as ex:
            print("Error reading Excel file: {}".format(str(ex)))
            NOTIFICATION.messenger(main_text="Error reading Excel file: {}".format(str(ex)))
            return None
    
    def parse_excel_data_structured(self, excel_data):
        """
        Parse Excel data using EnneadTab.EXCEL's structured parsing method
        
        Args:
            excel_data (dict): Excel data in (row, col) format
            
        Returns:
            dict: Dictionary of GFA targets
        """
        print("=== Using EnneadTab.EXCEL Structured Parsing ===")
        
        try:
            # Debug: Print the raw Excel data structure
            print("Raw Excel data structure:")
            for i, (key, value) in enumerate(excel_data.items()):
                if i < 10:  # Show first 10 entries
                    try:
                        print("  {}: {}".format(key, value))
                    except:
                        print("  {}: <unprintable>".format(key))
                else:
                    print("  ... and {} more entries".format(len(excel_data) - 10))
                    break
            
            # Use EnneadTab.EXCEL's parse_excel_data method with 'Keyword' as the key
            parsed_data = EXCEL.parse_excel_data(excel_data, key_name="Keyword", header_row=1)
            
            if not parsed_data:
                print("No structured data found using 'Keyword' as key")
                # Try with 'TargetArea' as key if 'Keyword' doesn't work
                parsed_data = EXCEL.parse_excel_data(excel_data, key_name="TargetArea", header_row=1)
                if not parsed_data:
                    print("No structured data found using 'TargetArea' as key")
                    return None
            
            print("Found {} structured data entries".format(len(parsed_data)))
            
            # Convert structured data to GFA targets format
            gfa_targets = {}
            
            for key, data_obj in parsed_data.items():
                try:
                    # Get the keyword (should be the key)
                    keyword = str(key).strip()
                    
                    # Get the target area value
                    # Try different possible attribute names
                    area_value = None
                    if hasattr(data_obj, 'TargetArea'):
                        area_value = getattr(data_obj, 'TargetArea')
                    elif hasattr(data_obj, 'Target_Area'):
                        area_value = getattr(data_obj, 'Target_Area')
                    elif hasattr(data_obj, 'targetarea'):
                        area_value = getattr(data_obj, 'targetarea')
                    elif hasattr(data_obj, 'target_area'):
                        area_value = getattr(data_obj, 'target_area')
                    
                    if area_value is not None:
                        try:
                            area_float = float(area_value)
                            if area_float > 0:  # Only accept positive areas
                                gfa_targets[keyword] = area_float
                                print("  - {}: {:.2f}".format(keyword, area_float))
                            else:
                                print("  - Skipping {}: invalid area value {}".format(keyword, area_value))
                        except (ValueError, TypeError):
                            print("  - Skipping {}: could not convert area '{}' to number".format(keyword, area_value))
                    else:
                        print("  - Skipping {}: no area value found".format(keyword))
                        
                except Exception as ex:
                    print("  - Error processing entry {}: {}".format(key, str(ex)))
                    continue
            
            print("Successfully parsed {} GFA targets using structured parsing".format(len(gfa_targets)))
            return gfa_targets if gfa_targets else None
            
        except Exception as ex:
            print("Error in structured parsing: {}".format(str(ex)))
            return None
    
    def parse_excel_data(self, excel_data):
        """
        Parse Excel data to extract GFA targets
        
        Args:
            excel_data (dict): Excel data in (row, col) format
            
        Returns:
            dict: Dictionary of GFA targets {keyword: area_value}
        """
        print("=== Parsing Excel Data for GFA Targets ===")
        
        gfa_targets = {}
        
        try:
            # Find header row and column indices
            header_info = self.find_header_columns(excel_data)
            
            if not header_info:
                print("Could not find required header columns")
                return None
            
            keyword_col = header_info['keyword_col']
            area_col = header_info['area_col']
            start_row = header_info['start_row']
            
            print("Found headers - Keyword column: {}, Area column: {}, Start row: {}".format(
                keyword_col, area_col, start_row))
            
            # Extract data rows
            for row in range(start_row + 1, 1000):  # Check up to row 1000
                keyword_cell = (row, keyword_col)
                area_cell = (row, area_col)
                
                if keyword_cell in excel_data and area_cell in excel_data:
                    keyword = str(excel_data[keyword_cell]).strip()
                    area_value = excel_data[area_cell]
                    
                    # Skip empty rows
                    if not keyword or keyword == "":
                        continue
                    
                    # Try to convert area to float
                    try:
                        area_float = float(area_value)
                        if area_float > 0:  # Only accept positive areas
                            gfa_targets[keyword] = area_float
                            print("  - {}: {:.2f}".format(keyword, area_float))
                        else:
                            print("  - Skipping {}: invalid area value {}".format(keyword, area_value))
                    except (ValueError, TypeError):
                        print("  - Skipping {}: could not convert area '{}' to number".format(keyword, area_value))
                else:
                    # No more data rows
                    break
            
            print("Parsed {} GFA targets from Excel data".format(len(gfa_targets)))
            return gfa_targets if gfa_targets else None
            
        except Exception as ex:
            print("Error parsing Excel data: {}".format(str(ex)))
            return None
    
    def find_header_columns(self, excel_data):
        """
        Find the column indices for Keyword and Target_Area columns
        
        Args:
            excel_data (dict): Excel data in (row, col) format
            
        Returns:
            dict: Dictionary with column indices and start row
        """
        print("Looking for exact header columns...")
        print("Expected headers: 'Keyword' and 'TargetArea' (or 'Target Area')")
        
        # Exact header names to look for
        keyword_headers = ['Keyword']
        area_headers = ['TargetArea', 'Target Area']
        
        keyword_col = None
        area_col = None
        start_row = None
        
        # Debug: Print all cell values in the first few rows
        print("Debug: All cell values in first 5 rows:")
        for row in range(1, 6):
            row_values = []
            for col in range(1, 11):  # Check first 10 columns
                cell_key = (row, col)
                if cell_key in excel_data:
                    try:
                        cell_value = str(excel_data[cell_key]).strip()
                        row_values.append("'{}'".format(cell_value))
                    except:
                        row_values.append("'<unprintable>'")
                else:
                    row_values.append("(empty)")
            print("  Row {}: [{}]".format(row, ", ".join(row_values)))
        
        # Search through the first 20 rows and columns
        for row in range(1, 21):
            for col in range(1, 21):
                cell_key = (row, col)
                if cell_key in excel_data:
                    cell_value = str(excel_data[cell_key]).strip()
                    
                    # Check if this is a keyword header
                    if cell_value in keyword_headers:
                        keyword_col = col
                        start_row = row
                        print("Found keyword header '{}' at row {}, col {}".format(cell_value, row, col))
                    
                    # Check if this is an area header
                    if cell_value in area_headers:
                        area_col = col
                        if start_row is None:
                            start_row = row
                        print("Found area header '{}' at row {}, col {}".format(cell_value, row, col))
        
        if keyword_col and area_col:
            return {
                'keyword_col': keyword_col,
                'area_col': area_col,
                'start_row': start_row
            }
        else:
            print("Could not find required header columns")
            print("Expected headers: 'Keyword' and 'TargetArea' (or 'Target Area')")
            print("Please ensure your Excel file has:")
            print("  - Worksheet named exactly: 'Target Area'")
            print("  - Headers: 'Keyword' and 'TargetArea' (or 'Target Area')")
            return None
    
    def validate_file_format(self, filepath):
        """Validate that the file is a supported Excel format"""
        print("Validating file format...")
        
        # Check file extension
        file_ext = filepath.lower().split('.')[-1]
        if '.' + file_ext not in self.supported_formats:
            print("ERROR: Unsupported file format: {}".format(file_ext))
            print("Supported formats: {}".format(self.supported_formats))
            return False
            
        print("File format is valid: {}".format(file_ext))
        return True
    
    
    def merge_with_existing_targets(self, imported_data):
        """
        Merge imported data with existing GFA targets
        
        Args:
            imported_data (dict): Imported GFA targets
            
        Returns:
            dict: Updated GFA targets dictionary
        """
        print("=== Merging Imported Data with Existing Targets ===")
        
        # Get current GFA targets from project data
        data = RHINO_PROJ_DATA.get_plugin_data()
        existing_targets = data.get(RHINO_PROJ_DATA.DocKeys.GFA_TARGET_DICT, {})
        
        print("Current GFA targets:")
        for key, value in existing_targets.items():
            print("  - {}: {:.2f}".format(key, value))
        
        # Track changes
        updated_items = []
        new_items = []
        unchanged_items = []
        
        # Merge imported data
        for keyword, area in imported_data.items():
            if keyword in existing_targets:
                if existing_targets[keyword] != area:
                    updated_items.append((keyword, existing_targets[keyword], area))
                else:
                    unchanged_items.append(keyword)
                existing_targets[keyword] = area
            else:
                new_items.append((keyword, area))
                existing_targets[keyword] = area
        
        # Report changes
        if updated_items:
            print("Updated existing targets:")
            for keyword, old_value, new_value in updated_items:
                print("  - {}: {:.2f} -> {:.2f}".format(keyword, old_value, new_value))
        
        if new_items:
            print("Added new targets:")
            for keyword, area in new_items:
                print("  - {}: {:.2f}".format(keyword, area))
        
        if unchanged_items:
            print("Unchanged targets:")
            for keyword in unchanged_items:
                print("  - {}: {:.2f}".format(keyword, existing_targets[keyword]))
        
        # Save updated targets
        data[RHINO_PROJ_DATA.DocKeys.GFA_TARGET_DICT] = existing_targets
        RHINO_PROJ_DATA.set_plugin_data(data)
        
        print("Merge completed successfully!")
        print("Total GFA targets: {}".format(len(existing_targets)))
        
        return existing_targets

@ERROR_HANDLE.try_catch_error()
def import_gfa_from_excel(filepath=None):
    """
    Main function to import GFA targets from Excel file
    
    Args:
        filepath (str, optional): Path to Excel file
        
    Returns:
        dict: Imported GFA targets or None if failed
    """
    print("=== GFA Excel Import Function Called ===")
    print("Input filepath: {}".format(filepath))
    
    importer = GFAExcelImporter()
    imported_data = importer.import_from_excel(filepath)
    
    if imported_data:
        print("Successfully imported data, merging with existing targets...")
        # Merge with existing targets
        final_targets = importer.merge_with_existing_targets(imported_data)
        return final_targets
    else:
        print("No data imported")
        return None

@ERROR_HANDLE.try_catch_error() 
def test_excel_import():
    """Test function to demonstrate Excel import functionality"""
    print("=== Testing GFA Excel Import Functionality ===")
    
    # Test the import process
    result = import_gfa_from_excel()
    
    if result:
        print("Test completed successfully!")
        print("Final GFA targets:")
        for keyword, area in result.items():
            print("  - {}: {:.2f}".format(keyword, area))
    else:
        print("Test failed - no data imported")

if __name__ == "__main__":
    test_excel_import()
