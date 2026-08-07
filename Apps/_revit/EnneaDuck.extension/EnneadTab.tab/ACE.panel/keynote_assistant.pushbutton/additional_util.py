import os
import webbrowser

import proDUCKtion # pyright: ignore
proDUCKtion.validify()
# import sys
# for i, path in enumerate(sys.path):
#     print("{}: {}".format(i+1, path))

from EnneadTab import EXCEL, NOTIFICATION, AI, TEXT, OUTPUT, FOLDER, ERROR_HANDLE, EXE
# from EnneadTab import LOG
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_PROJ_DATA, REVIT_FORMS
from Autodesk.Revit import DB # pyright: ignore 

# UIDOC = REVIT_APPLICATION.get_uidoc()
# DOC = REVIT_APPLICATION.get_doc()

import keynotesdb as kdb
from natsort import natsorted # pyright: ignore 


from pyrevit import forms, script

# Setting key constants for better maintainability
EXTENDED_DB_EXCEL_PATH_KEY = "extended_db_excel_path"
EXCEL_PATH_EXTERIOR_KEY = "excel_path_EXTERIOR"
EXCEL_PATH_INTERIOR_KEY = "excel_path_INTERIOR"

# Worksheet name constants for Excel operations
EXTENDED_DB_WORKSHEET_NAME = "Keynote Extended DB"


# Key column name constants for Excel parsing
KEYNOTE_ID_COLUMN_NAME = "KEYNOTE ID"


def open_new_keynote_exporter():
    # Retired: the old bundled KeynoteExporter.exe was cut from EnneadTab-OS to shrink the
    # repo. Keynote Exporter is now the standalone service EnneadTab-KeynoteExporter;
    # redirect to it on the web instead of launching the legacy exe.
    webbrowser.open("https://enneadtab.com/keynote-exporter")


# Project data helper functions
def get_project_data(doc=None):
    """
    Get project data with proper null checking for IronPython 2.7 compatibility.
    
    Args:
        doc: Revit document (optional, will get current doc if not provided)
        
    Returns:
        dict: Project data dictionary, empty dict if None
    """
    if doc is None:
        doc = REVIT_APPLICATION.get_doc()
    
    project_data = REVIT_PROJ_DATA.get_revit_project_data(doc)
    if project_data is None:
        project_data = {}
    return project_data

def update_project_data(doc, project_data):
    """
    Update project data in the database.
    
    Args:
        doc: Revit document
        project_data: Project data dictionary to save
    """
    REVIT_PROJ_DATA.set_revit_project_data(doc, project_data)

def get_keynote_setting(doc, setting_key, default_value=None):
    """
    Get a specific keynote setting from project data.
    
    Args:
        doc: Revit document
        setting_key: The setting key to retrieve
        default_value: Default value if setting not found
        
    Returns:
        The setting value or default_value
    """
    project_data = get_project_data(doc)
    return project_data.get("keynote_assistant", {}).get("setting", {}).get(setting_key, default_value)

def set_keynote_setting(doc, setting_key, value):
    """
    Set a specific keynote setting in project data.
    
    Args:
        doc: Revit document
        setting_key: The setting key to set
        value: The value to set
    """
    project_data = get_project_data(doc)
    
    # Ensure the nested structure exists
    if "keynote_assistant" not in project_data:
        project_data["keynote_assistant"] = {}
    if "setting" not in project_data["keynote_assistant"]:
        project_data["keynote_assistant"]["setting"] = {}
    
    project_data["keynote_assistant"]["setting"][setting_key] = value
    update_project_data(doc, project_data)

# Smart Excel column configuration system
class ExcelColumnConfig:
    """Smart configuration for Excel columns with automatic letter assignment."""
    
    def __init__(self):
        # Define columns in order with their properties
        self.columns = [
            {"header": "MARKER", "width": 4, "description": "Marker column"},
            {"header": "KEYNOTE ID", "width": 10, "description": "Unique identifier for keynote"},
            {"header": "KEYNOTE DESCRIPTION", "width": 50, "description": "Detailed description of the keynote"},
            {"header": "SOURCE", "width": 40, "description": "Source of the product/material"},
            {"header": "PRODUCT", "width": 40, "description": "Product name or specification"},
            {"header": "CAT.NO", "width": 35, "description": "Catalog number"},
            {"header": "COLOR", "width": 35, "description": "Color specification"},
            {"header": "FINISH", "width": 35, "description": "Surface finish"},
            {"header": "SIZE", "width": 35, "description": "Dimensions or size"},
            {"header": "CONTACT", "width": 35, "description": "Contact information"},
            {"header": "SPEC SECTION", "width": 35, "description": "Specification section reference"},
            {"header": "REMARKS", "width": 70, "description": "Additional notes or remarks"},
            {"header": "FUNCTION AND LOCATION", "width": 70, "description": "Function and location details"},
        ]
        
        self._assign_letters()
        
        # Special merged columns
        self.merged_columns = {
            "BASE OF DESIGN": {"start": "SOURCE", "end": "PRODUCT", "width": 40}
        }
    
    def _assign_letters(self):
        """Automatically assign column letters starting from A."""
        for i, col in enumerate(self.columns):
            col["letter"] = chr(65 + i)  # 65 is ASCII for 'A'
    
    def get_column_letter(self, header):
        """Get column letter for a given header."""
        for col in self.columns:
            if col["header"] == header:
                return col["letter"]
        return None
    
    def get_column_width(self, header):
        """Get column width for a given header."""
        for col in self.columns:
            if col["header"] == header:
                return col["width"]
        return None
    
    def get_all_headers(self):
        """Get all column headers in order."""
        return [col["header"] for col in self.columns]
    
    def get_extended_db_headers(self, ignore_keynote_id_and_description=False, ignore_marker=False):
        """Get headers for extended database columns (excluding keynote ID and description)."""
        if ignore_keynote_id_and_description:
            # Simple list of core columns to exclude
            core_headers = ["KEYNOTE ID", "KEYNOTE DESCRIPTION"]
            if ignore_marker:
                core_headers.append("MARKER")
            return [col["header"] for col in self.columns if col["header"] not in core_headers]
        else:
            return [col["header"] for col in self.columns]

    
    def get_merge_range(self, header):
        """Get merge range for special columns like BASE OF DESIGN."""
        if header in self.merged_columns:
            merge_config = self.merged_columns[header]
            start_letter = self.get_column_letter(merge_config["start"])
            end_letter = self.get_column_letter(merge_config["end"])
            return start_letter, end_letter
        return None, None
    

# Global instance
COLUMN_CONFIG = ExcelColumnConfig()

# Convenience functions for backward compatibility
def get_column_letter(header):
    """Get column letter for a given header."""
    return COLUMN_CONFIG.get_column_letter(header)

def get_column_width(header):
    """Get column width for a given header."""
    return COLUMN_CONFIG.get_column_width(header)

# Smart helper functions for Excel data creation

def create_revit_schedule_export_headers(row, cell_color=(200, 200, 200)):
    """Create headers for Excel files that will be linked to Revit schedules (Exterior/Interior).
    
    Requirements:
    - No borders (clean format for Revit linking)
    - Simple formatting for schedule compatibility
    - Merged BASE OF DESIGN header for better organization
    - 3-row header structure: main headers, sub-headers, data starts at row+2
    - Optimized for Revit schedule import/export workflow
    """
    items = []
    

    for header in ["KEYNOTE ID", "KEYNOTE DESCRIPTION"]:
        items.append(EXCEL.ExcelDataItem(
            header, 
            row, 
            get_column_letter(header),
            cell_color=cell_color,
            col_width=get_column_width(header),
            merge_with=[(row+1, get_column_letter(header))], 
            is_bold=True,
            bottom_border_style=EXCEL.BorderStyle.Thin,
            side_border_style=EXCEL.BorderStyle.Thin,
            top_border_style=EXCEL.BorderStyle.Thin
        ))

    start_letter, end_letter = COLUMN_CONFIG.get_merge_range("BASE OF DESIGN")
    items.append(EXCEL.ExcelDataItem(
        "BASE OF DESIGN", 
        row, 
        start_letter,
        cell_color=cell_color,
        merge_with=[(row, end_letter)],  
        is_bold=True,
        bottom_border_style=EXCEL.BorderStyle.Thin,
        side_border_style=EXCEL.BorderStyle.Thin,
        top_border_style=EXCEL.BorderStyle.Thin
    ))
    
    # Row 2: SOURCE and PRODUCT headers (under BASE OF DESIGN merge)
    for header in ["SOURCE", "PRODUCT"]:
        items.append(EXCEL.ExcelDataItem(
            header, 
            row+1, 
            get_column_letter(header),
            cell_color=cell_color,
            col_width=get_column_width(header),
            text_alignment=EXCEL.TextAlignment.Center,
            is_bold=True,
            bottom_border_style=EXCEL.BorderStyle.Thin,
            side_border_style=EXCEL.BorderStyle.Thin,
            top_border_style=EXCEL.BorderStyle.Thin
        ))
    
    # Row 1: Remaining headers after base of design merge
    headers_to_skip = {"KEYNOTE ID", "KEYNOTE DESCRIPTION", "SOURCE", "PRODUCT"}
    for header in COLUMN_CONFIG.get_extended_db_headers(ignore_keynote_id_and_description=True, ignore_marker=True):
        if header not in headers_to_skip:
            items.append(EXCEL.ExcelDataItem(
                header, 
                row, 
                get_column_letter(header),
                cell_color=cell_color,
                col_width=get_column_width(header),
                merge_with=[(row+1, get_column_letter(header))], 
                is_bold=True,
                bottom_border_style=EXCEL.BorderStyle.Thin,
                side_border_style=EXCEL.BorderStyle.Thin,
                top_border_style=EXCEL.BorderStyle.Thin
            ))
    
    return items

def create_extended_database_headers(row, cell_color=(200, 200, 200)):
    """Create single-row headers for the extended database Excel file that users will edit directly.
    
    Requirements:
    - Single row of headers (no merging or complex layout)
    - Full borders for clear data entry boundaries
    - Professional formatting for user editing
    - Read-only headers to prevent accidental modification
    - Simple, clean layout for easy data entry
    """
    items = []
    
    # Create simple single-row headers for all columns
    for col in COLUMN_CONFIG.columns:
        items.append(EXCEL.ExcelDataItem(
            col["header"], 
            row, 
            col["letter"],
            cell_color=cell_color if col["header"] != "MARKER" else None,
            col_width=col["width"],
            text_alignment=EXCEL.TextAlignment.Center,
            top_border_style=EXCEL.BorderStyle.Thin if col["header"] != "MARKER" else None,
            side_border_style=EXCEL.BorderStyle.Thin if col["header"] != "MARKER" else None,
            bottom_border_style=EXCEL.BorderStyle.Thin if col["header"] != "MARKER" else None,
            is_bold=True if col["header"] != "MARKER" else False
        ))
    
    return items

def exporter_row_writer(leaf, row, extend_db_item=None, highlight_missing=False):
    """Create a complete data row for a keynote item in Revit schedule export Excel files."""
    items = []
    cell_color = (255, 200, 200) if highlight_missing else None
    
    # Keynote ID and Description
    items.append(EXCEL.ExcelDataItem(
        leaf.key, 
        row, 
        get_column_letter("KEYNOTE ID"), 
        cell_color=cell_color, 
        tooltip={"title": "Wait a second!", "content": "DO NOT MODIFY THOSE CONTENT HERE, PLEASE!"},
        bottom_border_style=EXCEL.BorderStyle.Thin,
        side_border_style=EXCEL.BorderStyle.Thin,
        top_border_style=EXCEL.BorderStyle.Thin
    ))
    items.append(EXCEL.ExcelDataItem(
        leaf.text, 
        row, 
        get_column_letter("KEYNOTE DESCRIPTION"), 
        text_wrap=True, 
        cell_color=cell_color,
        tooltip={"title": "Wait a second!", "content": "DO NOT MODIFY THOSE CONTENT HERE, PLEASE!"},
        bottom_border_style=EXCEL.BorderStyle.Thin,
        side_border_style=EXCEL.BorderStyle.Thin,
        top_border_style=EXCEL.BorderStyle.Thin
    ))
    
    if extend_db_item:
        # Add extended DB data
        for header in COLUMN_CONFIG.get_extended_db_headers(ignore_keynote_id_and_description=True, ignore_marker=True):
            items.append(EXCEL.ExcelDataItem(
                extend_db_item.get(header, ""), 
                row, 
                get_column_letter(header),
                text_wrap=True,
                tooltip={"title": "Wait a second!", "content": "DO NOT MODIFY THOSE CONTENT HERE, PLEASE!"},
                bottom_border_style=EXCEL.BorderStyle.Thin,
                side_border_style=EXCEL.BorderStyle.Thin,
                top_border_style=EXCEL.BorderStyle.Thin
            ))
    else:
        # Highlight missing data with merged error message
        start_letter = get_column_letter("SOURCE")
        end_letter = get_column_letter("FUNCTION AND LOCATION")  # Include all extended DB columns
        items.append(EXCEL.ExcelDataItem(
            "Cannot find this item in extended DB", 
            row, 
            start_letter,
            cell_color=(211, 211, 211),
            merge_with=[(row, end_letter)],
            bottom_border_style=EXCEL.BorderStyle.Thin,
            side_border_style=EXCEL.BorderStyle.Thin,
            top_border_style=EXCEL.BorderStyle.Thin
        ))
    
    return items



def show_help():

    output = OUTPUT.get_output()
    output.write("What to do if:", OUTPUT.Style.Title)
    output.insert_divider()
    output.write("1. You are about to setup on a new project:", OUTPUT.Style.Subtitle)
    output.write("   - 1. Make sure your current keynote file is pointed at project folder, not from public template folder.")
    output.write("   - 2. (Optional, if you have existing keynote file you want to merge to the current list)"
                 "Click on \"Import Keynote\" button to merge another file into current file.")
    output.write("   - 3. (Optional, if you have some legacy quote mark around the description.)"
                 "Click on \"Cleanup quote mark around description\" button to cleanup them.")
    output.write("   - 4. Click on \"Edit Extend DB Excel\" button to pick a location for the extended DB excel file. "
                 "This will be the file storing all your other product information. The address will be recorded for future use.")
    output.write("   - 5. Click on \"Export Keynote as Excel\" button to pick a location to save your keynote as two separate excel files, "
                 "one for exterior and one for interior. Those locations will be recorded for future use.")
    output.write("      - You can use those two excel file to sticky link as schedule in Revit.")
    output.insert_divider()

    
    output.write("2. You are about to work with existing keynote setup:", OUTPUT.Style.Subtitle)
    output.write("   - 1. How to add a new keynote:", OUTPUT.Style.SubSubtitle)
    output.write("      - Click on \"Add Keynote\" button to add a new keynote to the current list.")
    output.write("      - Click on \"Pick Parent\" button to attach it to a new parent.")
    output.write("   - 2. How to edit an existing keynote:", OUTPUT.Style.SubSubtitle)
    output.write("      - Click on \"Edit Keynote\" button to edit an existing keynote.")
    output.write("      - Click on \"Pick Parent\" button to attach it to a new parent.")
    output.write("   - 3. How to reattach multiple keynotes to a new parent:", OUTPUT.Style.SubSubtitle)
    output.write("      - Click on \"Reattach Keynotes\" button to reattach multiple keynotes to a new parent.")
    output.write("      - Select the keynotes you want to reattach.")
    output.write("      - Select the new parent to attach to.")
    output.write("   - 4. How to translate single keynote description:", OUTPUT.Style.SubSubtitle)
    output.write("      - Click on \"Edit Keynote\" button to open the keynote description.")
    output.write("      - Click on \"Translate Keynote\" button to translate the keynote description.")
    output.write("   - 5. How to translate all keynote descriptions:", OUTPUT.Style.SubSubtitle)
    output.write("      - Click on \"Batch Translate Keynote\" button to translate the keynote description.")
    output.write("   - 6. How to export for Exterior and Interior excel:", OUTPUT.Style.SubSubtitle)
    output.write("      - Click on \"Export Keynote as Excel\" button to export the keynote as two separate excel files, "
                 "one for exterior and one for interior.")
    output.write("   - 7. How to edit extended DB excel:", OUTPUT.Style.SubSubtitle)
    output.write("      - Click on \"Edit Extend DB Excel\" button to open the extended DB excel file.")
    output.write("      - Edit as you prefer, the primary area to change is the Exterior and Interior category.")
    output.write("   - 8. How to regenerate extended DB excel:", OUTPUT.Style.SubSubtitle)
    output.write("      - Click on \"Regenerate Extended Database Excel\" button to recreate the extended DB file.")
    output.write("      - This will preserve existing data while adding new keynotes and removing orphaned entries.")
    output.write("      - A test file will be generated first for you to review before replacing the original.")
    output.write("   - 9. How to clean up empty categories and branches:", OUTPUT.Style.SubSubtitle)
    output.write("      - Click on \"Remove Empty Category and Branch\" button to find and remove empty items.")
    output.write("      - You can select which empty categories and branches to delete.")
    output.write("      - This helps keep your keynote structure clean and organized.")

    output.insert_divider()
    output.write("3. Maintenance and cleanup tasks:", OUTPUT.Style.Subtitle)
    output.write("   - 1. Regular cleanup:", OUTPUT.Style.SubSubtitle)
    output.write("      - Use \"Remove Empty Category and Branch\" to clean up unused organizational structure.")
    output.write("      - Use \"Cleanup Quote Around Description\" to fix imported keynote files.")
    output.write("   - 2. Data synchronization:", OUTPUT.Style.SubSubtitle)
    output.write("      - Use \"Regenerate Extended Database Excel\" when you add/remove keynotes to keep DB in sync.")
    output.write("      - Use \"Update Keynote From Excel\" to import changes from external Excel files.")
    output.write("   - 3. Translation workflow:", OUTPUT.Style.SubSubtitle)
    output.write("      - Use \"Batch Translate Keynote Text\" to translate all descriptions at once.")
    output.write("      - Individual translations can be done in the edit keynote dialog.")

    output.insert_divider()
    output.write("Why this way?", OUTPUT.Style.Subtitle)
    output.write("   - Revit keynote file is organized in a tree structure by Autodesk, for each keynote item, it will look like this:")
    output.write("   - KEY | DESCRIPTION | PARENT KEY")
    output.write("   - So when you want to organize under a 'folder', you are really just assigning many keynote items to the same parent.")


    output.insert_divider()
    output.write("What is Timeout messgae meaning?", OUTPUT.Style.Subtitle)
    output.write(os.path.join(os.path.dirname(__file__), "unlock timeout warning.png"))
    output.write("   - When you see this warning, it means someone else is editing the keynote file. We use a lock file to prevent multiple users from editing the same file at the same time.")
    output.write(os.path.join(os.path.dirname(__file__), "lock file.png"))
    output.write("   - Next to your keynote file, you will see a lock file. If you delete the lock file, you can bypass the lock and peek inside to see who is editing the file. Just be mindful to communicate with the other user to avoid overriding their changes.")


    
    output.insert_divider()
    pyrevit_help = "https://pyrevitlabs.notion.site/Manage-Keynotes-6f083d6f66fe43d68dc5d5407c8e19da"
    output.write("Need more information about the original pyRevit keynote function?", OUTPUT.Style.Subtitle)
    output.write(pyrevit_help, OUTPUT.Style.Link)
    
    output.plot()

def batch_reattach_keynotes(keynote_data_conn):
    """
    Batch attach keynotes to selected elements in Revit.
    
    This function allows you to attach keynotes to selected elements in Revit.
    
    Args:
        keynote_data_conn: Database connection to the keynote data
        
    Returns:
        None
    """
    class MyOption(forms.TemplateListItem):
        @property
        def name(self):
            return "[{}]<{}>: {}".format(self.parent_key, self.key, self.text)

    source = get_leaf_keynotes(keynote_data_conn)
    selected_keynotes = forms.SelectFromList.show(
        [MyOption(x) for x in source],
        title='Select Keynote',
        multiselect=True,
        button_name="Pick keynotes to attach..."
        )
    
    if not selected_keynotes:
        return
    
    categories = kdb.get_categories(keynote_data_conn)
    keynotes = kdb.get_keynotes(keynote_data_conn)
    available_parents = [x.key for x in categories]
    available_parents.extend([x.key for x in keynotes])
   
    # prompt to select a record
    new_parent = forms.SelectFromList.show(
        natsorted(available_parents),
        title='Select New Parent',
        multiselect=False,
        button_name="Pick new parent to attach to..."
        )
    
    if not new_parent:
        return
    
    with kdb.BulkAction(keynote_data_conn):
        for keynote in selected_keynotes:
            try:
                if keynote.parent_key == new_parent:
                    print ("Forbidden to reattach [{}]:{} to same parent".format(
                        keynote.key, keynote.text))
                    continue
                if keynote.key == new_parent:
                    print ("Forbidden to reattach [{}]:{} to itself".format(
                        keynote.key, keynote.text))
                    continue
                original_parent = keynote.parent_key
                kdb.move_keynote(keynote_data_conn, keynote.key, new_parent)
                print ("Reattach [{}]:{} parent from [{}] to [{}]".format(
                    keynote.key, keynote.text, original_parent, new_parent))
            except Exception as e:
                print ("Error reattaching [{}]:{} from [{}] to [{}]".format(
                    keynote.key, keynote.text, original_parent, new_parent))
                print(e)



def batch_translate_keynote(keynote_data_conn):
    """
    Translate keynote descriptions in batch.
    
    This function translates all keynote descriptions in the database by using AI translation
    and appends the translation to the original text.
    
    Args:
        keynote_data_conn: Database connection to the keynote data
        
    Returns:
        None
    """
    all_keynotes = kdb.get_keynotes(keynote_data_conn)
    input_texts = [TEXT.strip_chinese(x.text) for x in all_keynotes if x.text]
    print ("Going to translate those descriptions:")
    for x in input_texts:
        print (x)
    result_dict = AI.translate_multiple(input_texts)
    if not result_dict:
        print ("No result from translation, usually due to missing api key, please check your api key")
        return
    print ("\n\n\n\n\nResult:")
    for x in result_dict:
        print ("\t{} --> {}".format(TEXT.strip_chinese(x), result_dict[x]))
    with kdb.BulkAction(keynote_data_conn):
        for keynote in all_keynotes:
            if result_dict.get(keynote.text):
                final_text = TEXT.strip_chinese(keynote.text) + " " + str(result_dict.get(keynote.text, ""))
                kdb.update_keynote_text(keynote_data_conn, keynote.key, final_text)
    

def translate_keynote(input):
    """
    Translate a single keynote description.
    
    This function translates a single keynote description using AI translation
    and appends the translation to the original text.
    
    Args:
        input: The text to translate
        
    Returns:
        String containing original text and translation
    """
    return input + " " + AI.translate(input)



def cleanup_quote_text(keynote_data_conn):
    """
    Clean up quote text in the keynote database.
    
    This function cleans up quote text in the keynote database by removing
    leading and trailing quotes in keynote text, if any quotes exist.
    
    Args:
        keynote_data_conn: Database connection to the keynote data
        
    Returns:
        None
    """
    all_keynotes = kdb.get_keynotes(keynote_data_conn)
    bad_text_count = 0
    for keynote in all_keynotes:
        new_text = None
        if keynote.text.startswith('"') and keynote.text.endswith('"'):
            new_text = keynote.text[1:-1]
            bad_text_count += 1
        elif keynote.text.startswith("'") and keynote.text.endswith("'"):
            new_text = keynote.text[1:-1]
            bad_text_count += 1

        if new_text:
            print("{}: {} -> {}".format(keynote.key, keynote.text, new_text))
            kdb.update_keynote_text(keynote_data_conn, keynote.key, new_text)

    if bad_text_count > 0:
        print("{} Bad text found and cleaned up.".format(bad_text_count))
    else:
        print("No bad text found.")


def get_leaf_keynotes(keynote_data_conn):
    """
    Get all leaf keynotes from the database.
    
    This function retrieves all leaf keynotes (keynotes that are not parents of other keynotes)
    from the database.
    
    Args:
        keynote_data_conn: Database connection to the keynote data
        
    Returns:
        List of leaf keynotes
    """
    OUT = []
    all_keynotes = kdb.get_keynotes(keynote_data_conn)
    all_categories = kdb.get_categories(keynote_data_conn)
    for category in all_categories:
        top_branch = [x for x in all_keynotes if x.parent_key == category.key]
        for branch in top_branch:
            leafs = [x for x in all_keynotes if x.parent_key == branch.key]
            for leaf in leafs:
                OUT.append(leaf)
    return OUT

@ERROR_HANDLE.try_catch_error(is_silent=False)
def export_keynote_as_exterior_and_interior(keynote_data_conn):
    """
    Export keynotes from 'Exterior' and 'Interior' categories to separate Excel files.
    
    Creates a hierarchically organized Excel file with keynotes grouped by category
    and branch. Includes proper formatting for improved readability.
    
    Args:
        keynote_data_conn: Database connection to the keynotes database
        
    Returns:
        Path to generated Excel file
    """
    ERROR_HANDLE.print_note("Starting export_keynote_as_exterior_and_interior")
    
    try:
        doc = REVIT_APPLICATION.get_doc()
        ERROR_HANDLE.print_note("Got Revit document")
        
        # Setup project data with transaction
        t = DB.Transaction(doc, "edit extended db excel")
        t.Start()
        try:
            REVIT_PROJ_DATA.setup_project_data(doc)
            t.Commit()
            ERROR_HANDLE.print_note("Project data setup completed")
        except Exception as e:
            t.RollBack()
            ERROR_HANDLE.print_note("Error in project data setup: {}".format(str(e)))
            raise
        
        # Get extended database path and data
        ERROR_HANDLE.print_note("Getting extended DB path from settings...")
        extend_db_path = get_keynote_setting(doc, EXTENDED_DB_EXCEL_PATH_KEY)
        ERROR_HANDLE.print_note("Extended DB path: {}".format(extend_db_path))
        
        if extend_db_path and os.path.exists(extend_db_path):
            try:
                ERROR_HANDLE.print_note("Reading extended DB data from: {}".format(extend_db_path))
                ERROR_HANDLE.print_note("Note: If file has corrupted merged cells, Excel will repair automatically")
                
                # Check file size to give user context
                file_size = os.path.getsize(extend_db_path)
                ERROR_HANDLE.print_note("File size: {} bytes".format(file_size))
                
                db_data = EXCEL.read_data_from_excel(
                    extend_db_path, 
                    worksheet=EXTENDED_DB_WORKSHEET_NAME, 
                    return_dict=True
                )
                ERROR_HANDLE.print_note("Raw DB data read successfully, parsing...")

                db_data = EXCEL.parse_excel_data(
                    db_data, 
                    KEYNOTE_ID_COLUMN_NAME, 
                    ignore_keywords=["[Branch]", "[Category]"]
                )
                ERROR_HANDLE.print_note("DB data parsed successfully, {} items".format(len(db_data)))
                
            except Exception as e:
                ERROR_HANDLE.print_note("Error reading extended DB: {}".format(str(e)))
                ERROR_HANDLE.print_note("Error type: {}".format(type(e).__name__))
                ERROR_HANDLE.print_note("Error details: {}".format(str(e)))
                
                # Check if it's a timeout or corruption issue
                error_msg = str(e).lower()
                if "timeout" in error_msg or "hang" in error_msg:
                    NOTIFICATION.messenger("Excel file reading timed out. This may be due to corrupted merged cells. Please check the Excel file and try again.")
                elif "corrupt" in error_msg or "repair" in error_msg:
                    NOTIFICATION.messenger("Excel file has corruption issues. Excel may have repaired the file automatically. Please try again.")
                else:
                    NOTIFICATION.messenger("Error reading extended database: {}".format(str(e)))
                
                ERROR_HANDLE.print_note("Continuing with empty database data...")
                db_data = {}
        else:
            ERROR_HANDLE.print_note("No extended DB path or file not found, using empty data")
            if extend_db_path:
                ERROR_HANDLE.print_note("Path exists but file not found: {}".format(extend_db_path))
            else:
                ERROR_HANDLE.print_note("No path configured in settings")
            db_data = {}

        # Get the full keynote tree
        ERROR_HANDLE.print_note("Getting categories and keynotes from database")
        try:
            ERROR_HANDLE.print_note("Calling kdb.get_categories...")
            all_categories = kdb.get_categories(keynote_data_conn)
            ERROR_HANDLE.print_note("Got {} total categories from database".format(len(all_categories)))
            
            categorys = [x for x in all_categories 
                        if x.key.upper() in ["EXTERIOR", "INTERIOR"]]
            ERROR_HANDLE.print_note("Found {} matching categories: {}".format(len(categorys), [c.key for c in categorys]))
            
            ERROR_HANDLE.print_note("Calling kdb.get_keynotes...")
            all_keynotes = kdb.get_keynotes(keynote_data_conn)
            ERROR_HANDLE.print_note("Found {} total keynotes".format(len(all_keynotes)))
        except Exception as e:
            ERROR_HANDLE.print_note("Error getting keynote data: {}".format(str(e)))
            ERROR_HANDLE.print_note("Error type: {}".format(type(e).__name__))
            ERROR_HANDLE.print_note("Error details: {}".format(str(e)))
            NOTIFICATION.messenger("Error accessing keynote database: {}".format(str(e)))
            raise
        
        # Process each category
        for cate in categorys:
            ERROR_HANDLE.print_note("Processing category: {}".format(cate.key))
            data_collection = []
            pointer_row = 0
            
            try:
                # Create header rows using smart helper (3-row header structure)
                data_collection.extend(create_revit_schedule_export_headers(pointer_row))
                pointer_row += 3  # 3-row header: main headers, sub-headers, data starts at row+3
                ERROR_HANDLE.print_note("Headers created for category: {}".format(cate.key))
                
                print("\n== CATEGORY: {} ==".format(cate.key))
                top_branch = [x for x in all_keynotes if x.parent_key == cate.key]
                print("\tTop branchs in {}".format(cate.key))
                ERROR_HANDLE.print_note("Found {} branches in category {}".format(len(top_branch), cate.key))
                
                # Process each branch
                for i, branch in enumerate(top_branch):
                    ERROR_HANDLE.print_note("Processing branch {}/{}: {}".format(i+1, len(top_branch), branch.key))
                    pointer_row += 2  # skip 2 for adding empty line
                    bran_name = branch.text
                    if len(bran_name) == 0:
                        bran_name = "UnOrganized, please write something to the branch keynote description."
                    data_collection.append(EXCEL.ExcelDataItem(
                        bran_name, 
                        pointer_row, 
                        get_column_letter("KEYNOTE ID"), 
                        is_bold=True
                    ))
                    print("\t\t{}: [{}] {}".format(i+1, branch.key, branch.text))
                    
                    leafs = [x for x in all_keynotes if x.parent_key == branch.key]
                    ERROR_HANDLE.print_note("Found {} leafs in branch {}".format(len(leafs), branch.key))
                    
                    # Process each leaf
                    for j, leaf in enumerate(leafs):
                        ERROR_HANDLE.print_note("Processing leaf {}/{}: {}".format(j+1, len(leafs), leaf.key))
                        pointer_row += 1
                        
                        # Create keynote data row using smart helper
                        extend_db_item = db_data.get(leaf.key) if db_data else None
                        highlight_missing = extend_db_item is None
                        data_collection.extend(exporter_row_writer(
                            leaf, 
                            pointer_row, 
                            extend_db_item, 
                            highlight_missing
                        ))
                            
                        print("\t\t\t{}-{}: [{}] {}".format(i+1, j+1, leaf.key, leaf.text))
                
                # Handle Excel file path selection
                def _pick_excel_out_path():
                    try:
                        ERROR_HANDLE.print_note("Opening file picker for category: {}".format(cate.key))
                        excel_out_path = forms.pick_excel_file(
                            title="Pick Extended Keynote Database Excel File for [{}]".format(cate.key),
                            save=True
                        )
                        set_keynote_setting(doc, "excel_path_{}".format(cate.key), excel_out_path)
                        ERROR_HANDLE.print_note("File path selected: {}".format(excel_out_path))
                        return excel_out_path
                    except Exception as e:
                        ERROR_HANDLE.print_note("Error in file picker: {}".format(str(e)))
                        NOTIFICATION.messenger("Error selecting file path: {}".format(str(e)))
                        raise

                excel_out_path = get_keynote_setting(doc, "excel_path_{}".format(cate.key))
                if not excel_out_path:
                    note = "Excel output path for [{}] is not defined, please pick one".format(cate.key)
                    NOTIFICATION.messenger(note)
                    print(note)
                    excel_out_path = _pick_excel_out_path()
                elif not os.path.exists(excel_out_path):
                    print("Excel output path for [{}] is not found, please pick one again."
                          "\nOriginal path: {} is no longer valid".format(cate.key, excel_out_path))
                    excel_out_path = _pick_excel_out_path()

                # Save Excel file
                ERROR_HANDLE.print_note("Saving Excel file for category {} with {} items".format(cate.key, len(data_collection)))
                try:
                    EXCEL.save_data_to_excel(data_collection, excel_out_path, worksheet=cate.key, freeze_row=2)
                    ERROR_HANDLE.print_note("Excel file saved successfully: {}".format(excel_out_path))
                except Exception as e:
                    ERROR_HANDLE.print_note("Error saving Excel file: {}".format(str(e)))
                    NOTIFICATION.messenger("Error saving Excel file: {}".format(str(e)))
                    raise
                    
            except Exception as e:
                ERROR_HANDLE.print_note("Error processing category {}: {}".format(cate.key, str(e)))
                NOTIFICATION.messenger("Error processing category {}: {}".format(cate.key, str(e)))
                raise

        # Data validation and reporting
        if not db_data:
            ERROR_HANDLE.print_note("No extended DB data available for validation")
            return

        ERROR_HANDLE.print_note("Starting data validation between keynote file and extended DB")
        bug_collection = []
        
        try:
            # Get keynotes once to avoid multiple database calls
            leaf_keynotes = get_leaf_keynotes(keynote_data_conn)
            ERROR_HANDLE.print_note("Got {} leaf keynotes for validation".format(len(leaf_keynotes)))
            
            diff = set(db_data.keys()) - set([x.key for x in leaf_keynotes])
            if diff:
                ERROR_HANDLE.print_note("Found {} keys in extended DB not in keynote file".format(len(diff)))
                bug_collection.append("Warning: some keys in extended DB are not in keynote file:")
                for i, x in enumerate(diff):
                    bug_collection.append("-{}: [{}]{}".format(i+1, x, db_data[x].KEYNOTE_DESCRIPTION))

            keynote_keys = {keynote.key: keynote for keynote in leaf_keynotes}
            
            reverse_diff = set(keynote_keys.keys()) - set(db_data.keys())
            if reverse_diff:
                ERROR_HANDLE.print_note("Found {} keys in keynote file not in extended DB".format(len(reverse_diff)))
                bug_collection.append("Warning: some keys in keynote file are not in extended DB:")
                for i, key in enumerate(reverse_diff):
                    bug_collection.append("-{}: [{}]{}".format(i+1, key, keynote_keys[key].text))

            if diff or reverse_diff:
                print("\n\n")
                bug_collection.append("This is usually due to one of the following reasons:")
                bug_collection.append("1. You have renamed the key in keynote file but did not update the same item in the DB excel file: "
                                     "Please update the same item in the DB excel file")
                bug_collection.append("2. You have added a new keynote in keynote file, but not in extended DB: "
                                     "Please add the same item in the DB excel file")
                bug_collection.append("3. You have added a new keynote in extended DB, but not in keynote file: "
                                     "Please add the same item in the keynote file")

            if bug_collection:
                ERROR_HANDLE.print_note("Displaying validation warnings to user")
                output = script.get_output()
                output.print_md("## =====Please check the following=====")
                for x in bug_collection:
                    output.print_md(x)
            else:
                ERROR_HANDLE.print_note("Data validation completed - no issues found")
                
        except Exception as e:
            ERROR_HANDLE.print_note("Error during data validation: {}".format(str(e)))
            NOTIFICATION.messenger("Error during data validation: {}".format(str(e)))
            # Don't raise here as the main export was successful
            
    except Exception as e:
        ERROR_HANDLE.print_note("Critical error in export function: {}".format(str(e)))
        NOTIFICATION.messenger("Critical error during export: {}".format(str(e)))
        raise


def update_keynote_from_excel(keynote_data_conn):
    """
    Update keynote data from an Excel file.
    
    This function allows you to update keynote data from an Excel file into the keynote database.
    It provides options to add missing keynotes and update existing ones with new descriptions.
    
    Args:
        keynote_data_conn: Database connection to the keynote data
        
    Returns:
        None
    """
    options = [
        ["Update Keynote from Excel", "Update keynote data from an Excel file."], 
        "Abort Abort Abort!!!!!!"
    ]

    res = REVIT_FORMS.dialogue(
        main_text="Update Keynote from Excel.", 
        sub_text="This is a dangerous game. I am going to use the 'Update' worksheet in the Excel file "
                "to update the keynote data. Adding one if missing, and updating the existing ones with new description."
                "\nIn the 'Update' worksheet, you will need the following columns:"
                "\n- KEYNOTE ID: The ID of the keynote to update."
                "\n- KEYNOTE DESCRIPTION: The description of the keynote to update."
                "\n- PARENT FOR NEW KEYNOTE: The parent of the new keynote."
                "\nYou will have a chance to pick a parent for the new keynotes, if you did not assign one in the Excel file.", 
        options=options, 
        icon="warning"
    )
    if res != options[0][0]:
        return

    excel_path = forms.pick_excel_file(
        title="Pick Keynote Excel File",
        save=False
    )
    if not excel_path:
        return

    data = EXCEL.read_data_from_excel(excel_path, worksheet="Update", return_dict=True)
    data = EXCEL.parse_excel_data(data, "KEYNOTE ID")
    
    categories = kdb.get_categories(keynote_data_conn)
    keynotes = kdb.get_keynotes(keynote_data_conn)
    available_parents = [x.key for x in categories]
    available_parents.extend([x.key for x in keynotes])
   
    # prompt to select a record
    new_parent_for_new_keynote = forms.SelectFromList.show(
        natsorted(available_parents),
        title='Select New Parent',
        multiselect=False,
        button_name="Pick new parent to attach to if you are creating a new keynote and did not assign in excel..."
    )
    
    if not new_parent_for_new_keynote:
        return

    all_keynotes = kdb.get_keynotes(keynote_data_conn)
    all_keys = [x.key for x in all_keynotes]
    with kdb.BulkAction(keynote_data_conn):
        for k, v in data.items():
            keynote_description = v.get("KEYNOTE DESCRIPTION")
           
            if k in all_keys:
                current_keynote_text = [x for x in all_keynotes if x.key == k][0].text
                if current_keynote_text != keynote_description:
                    kdb.update_keynote_text(keynote_data_conn, k, keynote_description)
                    print("Update [{}]: {}".format(k, keynote_description))
            else:
                assigned_parent = v.get("PARENT FOR NEW KEYNOTE")
                if assigned_parent is not None and assigned_parent not in all_keys:
                    print("You are trying to create [{}] and attach it to [{}] as parent, "
                          "but [{}] is not found in the keynote database. "
                          "I am going to use [{}] as parent instead.".format(
                            k, assigned_parent, assigned_parent, new_parent_for_new_keynote))
                    assigned_parent = None
                    
                if assigned_parent:
                    kdb.add_keynote(keynote_data_conn, k, keynote_description, assigned_parent)
                else:
                    kdb.add_keynote(keynote_data_conn, k, keynote_description, new_parent_for_new_keynote)
                print("Add [{}]: {}".format(k, keynote_description))
    

def open_extended_db_excel(keynote_data_conn):
    """
    Open the extended DB Excel file for editing.
    
    This function opens the extended DB Excel file for editing. If the file does not exist,
    it creates a new one with a default structure.
    
    Args:
        keynote_data_conn: Database connection to the keynote data
        
    Returns:
        None
    """
    doc = REVIT_APPLICATION.get_doc()
    t = DB.Transaction(doc, "edit extended db excel")
    t.Start()
    REVIT_PROJ_DATA.setup_project_data(doc)
    t.Commit()
    keynote_excel_extend_db = get_keynote_setting(doc, EXTENDED_DB_EXCEL_PATH_KEY)
    if not keynote_excel_extend_db:
        
        keynote_excel_extend_db = forms.pick_excel_file(
            title="Pick Extended Keynote Database Excel File",
            save=True
        )
        set_keynote_setting(doc, EXTENDED_DB_EXCEL_PATH_KEY, keynote_excel_extend_db)

    if os.path.exists(keynote_excel_extend_db):
        os.startfile(keynote_excel_extend_db)
        return
    
    else:
        generate_default_extended_db_excel(keynote_data_conn, keynote_excel_extend_db)

def generate_default_extended_db_excel(keynote_data_conn, keynote_excel_extend_db, additional_data={}):
    # export a default one to this address, i am just here to setup EMPTY excel
    color_yellow = (252, 213, 180)
    color_green = (196, 215, 155)
    color_light_grey = (224, 224, 224)
    color_dark_grey = (200, 200, 200)
    data_collection = []
    pointer_row = 0
    
    # Create header rows with consistent formatting using smart helper
    header_items = create_extended_database_headers(pointer_row, color_dark_grey)
    for item in header_items:
        item.is_read_only = True
        data_collection.append(item)
    
    # Get the full keynote tree
    categorys = [x for x in kdb.get_categories(keynote_data_conn)]
    all_keynotes = kdb.get_keynotes(keynote_data_conn)
    for cate in categorys:
        pointer_row += 3
        print("\n== CATEGORY: {} ==".format(cate.key))
        
        # Add category header
        data_collection.append(EXCEL.ExcelDataItem(
            "[Category]: " + str(cate.key), 
            pointer_row, 
            get_column_letter("KEYNOTE ID"),
            cell_color=color_yellow, 
            is_bold=True, 
            is_read_only=True
        ))

        data_collection.append(EXCEL.ExcelDataItem(
            "", 
            pointer_row, 
            get_column_letter("KEYNOTE DESCRIPTION"),
            cell_color=color_yellow, 
            is_bold=True, 
            is_read_only=True
        ))
        
        # Fill category row with consistent formatting
        for header in COLUMN_CONFIG.get_extended_db_headers(ignore_keynote_id_and_description=True, ignore_marker=True):
            data_collection.append(EXCEL.ExcelDataItem(
                "", 
                pointer_row, 
                get_column_letter(header),
                cell_color=color_yellow, 
                is_bold=True, 
                is_read_only=True
            ))

        top_branch = [x for x in all_keynotes if x.parent_key == cate.key]
        print("\tTop branchs in {}".format(cate.key))
        
        for i, branch in enumerate(top_branch):
            pointer_row += 1
            bran_name = branch.text
            if len(bran_name) == 0:
                bran_name = "UnOrganized, please write something in the keynote description so the group has header."
            
            # Add branch header
            data_collection.append(EXCEL.ExcelDataItem(
                "[Branch]: " + str(bran_name), 
                pointer_row, 
                get_column_letter("KEYNOTE ID"),
                cell_color=color_green, 
                is_bold=True, 
                is_read_only=True
            ))

            data_collection.append(EXCEL.ExcelDataItem(
                "", 
                pointer_row, 
                get_column_letter("KEYNOTE DESCRIPTION"),
                cell_color=color_green, 
                is_bold=True, 
                is_read_only=True
            ))
            # Fill branch row with consistent formatting
            for header in COLUMN_CONFIG.get_extended_db_headers(ignore_keynote_id_and_description=True, ignore_marker=True):
                data_collection.append(EXCEL.ExcelDataItem(
                    "", 
                    pointer_row, 
                    get_column_letter(header),
                    cell_color=color_green, 
                    is_bold=True, 
                    is_read_only=True
                ))
                
            print("\t\t{}: [{}] {}".format(i+1, branch.key, branch.text))
            
            leafs = [x for x in all_keynotes if x.parent_key == branch.key]
            for j, leaf in enumerate(leafs):
                pointer_row += 1
                print("\t\t\t{}-{}: [{}] {}".format(i+1, j+1, leaf.key, leaf.text))

                # Add keynote ID and description cells (white background for actual data)
                data_collection.append(EXCEL.ExcelDataItem(
                    str(leaf.key), 
                    pointer_row, 
                    get_column_letter("KEYNOTE ID"),
                    cell_color=color_light_grey, 
                    is_bold=True, 
                    is_read_only=True,
                    top_border_style=EXCEL.BorderStyle.Thin,
                    bottom_border_style=EXCEL.BorderStyle.Thin,
                    side_border_style=EXCEL.BorderStyle.Thin,
                    tooltip={
                        "title": "Hold your beer!", 
                        "content": "If you want to change keynote Id, just write the new keynote ID on column A(MODIFIER). Please do not change original keynote otherwise I cannot track what you have changed."
                    }
                ))
                
                data_collection.append(EXCEL.ExcelDataItem(
                    str(leaf.text), 
                    pointer_row, 
                    get_column_letter("KEYNOTE DESCRIPTION"),
                    cell_color=color_light_grey, 
                    is_bold=True, 
                    is_read_only=True,
                    top_border_style=EXCEL.BorderStyle.Thin,
                    bottom_border_style=EXCEL.BorderStyle.Thin,
                    side_border_style=EXCEL.BorderStyle.Thin,
                    tooltip={
                        "title": "Hmmmm..", 
                        "content": "If you modify the description here, just know that you need to push that change to the keynote file as well afterward."
                    }
                ))

                # Add additional data for this specific keynote
                keynote_key = leaf.key
                if keynote_key in additional_data:
                    keynote_data = additional_data[keynote_key]
                    added_fields = []
                    for header in COLUMN_CONFIG.get_extended_db_headers(ignore_keynote_id_and_description=True):
                        value = keynote_data.get(header, "")
                        # Convert None to empty string, then check if there's actual content
                        if value is None:
                            value = ""
                        if value and str(value).strip():  # Only add if there's actual content
                            added_fields.append(header)
                            data_collection.append(EXCEL.ExcelDataItem(
                                str(value), 
                                pointer_row, 
                                get_column_letter(header)
                            ))
                    if added_fields:
                        print("  Added data for {}: {}".format(keynote_key, ", ".join(added_fields)))
    
    EXCEL.save_data_to_excel(
        data_collection, 
        keynote_excel_extend_db, 
        worksheet=EXTENDED_DB_WORKSHEET_NAME, 
        freeze_row=1, 
        freeze_column=get_column_letter("SOURCE"),
        open_after=True)



def regenerate_extended_db_excel(keynote_data_conn):
    """
    Regenerate the extended DB Excel file with smart data preservation.
    
    This function intelligently regenerates the extended DB Excel file by:
    1. Reading existing extended DB data
    2. Getting current keynote structure
    3. Merging existing data with new keynote items
    4. Preserving existing data for unchanged keynotes
    5. Adding new keynotes with empty extended DB fields
    6. Creating a backup before overwriting
    
    Args:
        keynote_data_conn: Database connection to the keynote data
        
    Returns:
        None
    """
    doc = REVIT_APPLICATION.get_doc()
    keynote_excel_extend_db = get_keynote_setting(doc, EXTENDED_DB_EXCEL_PATH_KEY)
    
    if not keynote_excel_extend_db:
        note = "Extended DB excel path is not defined, please define one first by using [Open Extended Database Excel] button."
        NOTIFICATION.messenger(note)
        print(note)
        return


    # Generate test file path with timestamp
    regenerated_excel_path = FOLDER.get_local_dump_folder_file("regenerated_extended_db_PLEASE_CHECK_AND_REPLACE_ORGINAL.xlsx")
    print("Generating test file: {}".format(regenerated_excel_path))

    # Read existing extended DB data
    print("Reading existing extended DB data...")
    try:
        existing_data = EXCEL.parse_excel_data(
            EXCEL.read_data_from_excel(keynote_excel_extend_db, worksheet=EXTENDED_DB_WORKSHEET_NAME, return_dict=True), 
            "KEYNOTE ID",
            ignore_keywords=["[Branch]", "[Category]", "UnOrganized", "please write something"]
        )
        print("Found {} existing extended DB entries".format(len(existing_data)))
        
        # Print existing data that is not empty
        print("\n=== EXISTING DATA WITH CONTENT ===")
        has_content_count = 0
        for keynote_key, data in existing_data.items():
            # Check if any field has content (not empty or None)
            has_content = False
            content_fields = []
            for header in COLUMN_CONFIG.get_extended_db_headers():
                value = data.get(header, "")
                # Convert None to empty string for proper checking
                if value is None:
                    value = ""
                if value and str(value).strip():  # Not empty or just whitespace
                    has_content = True
                    content_fields.append("{}: {}".format(header, value))
            
            if has_content:
                has_content_count += 1
                print("\n[{}] {}:".format(keynote_key, data.get("KEYNOTE DESCRIPTION", "No description")))
                for field in content_fields:
                    print("  - {}".format(field))
        
        if has_content_count == 0:
            print("No existing data with content found.")
        else:
            print("\nTotal entries with content: {}".format(has_content_count))
            
    except Exception as e:
        print("Warning: Could not read existing data: {}".format(e))
        existing_data = {}

    # Get current keynote structure
    print("Getting current keynote structure...")
    leaf_keynotes = get_leaf_keynotes(keynote_data_conn)
    current_keynote_keys = {keynote.key for keynote in leaf_keynotes}
    
    # Smart data merging
    print("Merging existing data with current keynote structure...")
    merged_data = {}
    
    # Preserve existing data for current keynotes
    for keynote_key in current_keynote_keys:
        if keynote_key in existing_data:
            merged_data[keynote_key] = existing_data[keynote_key]
            print("Preserved existing data for: {}".format(keynote_key))
            # Show what data is being preserved
            preserved_fields = []
            for header in COLUMN_CONFIG.get_extended_db_headers():
                value = existing_data[keynote_key].get(header, "")
                if value and str(value).strip():
                    preserved_fields.append("{}: {}".format(header, value))
            if preserved_fields:
                print("  Preserved fields: {}".format(", ".join(preserved_fields)))
        else:
            # New keynote - create empty extended DB entry
            merged_data[keynote_key] = {}
            for header in COLUMN_CONFIG.get_extended_db_headers():
                merged_data[keynote_key][header] = ""
            print("Added new keynote with empty extended DB: {}".format(keynote_key))
    
    # Report orphaned data (keynotes that exist in extended DB but not in current keynotes)
    orphaned_keys = set(existing_data.keys()) - current_keynote_keys
    if orphaned_keys:
        print("\nWarning: Found {} orphaned extended DB entries (keynotes no longer in keynote file):".format(len(orphaned_keys)))
        for key in orphaned_keys:
            print("  - {}: {}".format(key, existing_data[key].get("KEYNOTE DESCRIPTION", "No description")))
        print("These entries will be removed from the regenerated file.")
    
    # Generate new extended DB excel with merged data
    print("Generating new test extended DB excel...")
    print("Merged data keys: {}".format(list(merged_data.keys())))
    print("Sample merged data: {}".format(dict(list(merged_data.items())[:2])))  # Show first 2 items
    try:
        generate_default_extended_db_excel(keynote_data_conn, regenerated_excel_path, additional_data=merged_data)
        print("Successfully generated test extended DB excel!")
        
        # Show summary
        print("\n=== REGENERATION SUMMARY ===")
        print("Total keynotes in current file: {}".format(len(current_keynote_keys)))
        print("Existing extended DB entries preserved: {}".format(len(current_keynote_keys & set(existing_data.keys()))))
        print("New keynotes added: {}".format(len(current_keynote_keys - set(existing_data.keys()))))
        print("Orphaned entries removed: {}".format(len(orphaned_keys)))
        print("New DB excel re-generated at: {}".format(regenerated_excel_path))
        print("Original file unchanged: {}".format(keynote_excel_extend_db))
        NOTIFICATION.messenger("Test extended DB excel generated at: {}.\nPlease check and replace original file.".format(regenerated_excel_path))
        
    except Exception as e:
        print("Error generating test extended DB excel: {}".format(e))
        NOTIFICATION.messenger("Error generating test extended DB excel: {}".format(e))


def remove_empty_categories_and_branches(keynote_data_conn):
    """
    Remove empty categories and branches from the database with user selection.
    
    Structure: Category -> Branch -> Item
    - Empty Category: A category with no branches
    - Empty Branch: A branch with no items
    
    Uses pyrevit SelectFromList to let user choose which items to delete.
    
    Args:
        keynote_data_conn: Database connection to the keynotes database
        
    Returns:
        dict: Summary of removed items with counts
    """
    print("=== REMOVING EMPTY CATEGORIES AND BRANCHES ===")
    print("Structure: Category -> Branch -> Item")
    
    try:
        # Get all categories and keynotes
        all_categories = kdb.get_categories(keynote_data_conn)
        all_keynotes = kdb.get_keynotes(keynote_data_conn)
        
        # Build parent-child relationships
        children_map = {}
        for keynote in all_keynotes:
            parent_key = keynote.parent_key
            if parent_key not in children_map:
                children_map[parent_key] = []
            children_map[parent_key].append(keynote)
        
        # Find empty categories (categories with no branches)
        empty_categories = []
        for category in all_categories:
            if category.key not in children_map or len(children_map[category.key]) == 0:
                empty_categories.append(category)
                print("Found empty category: [{}] {} (no branches)".format(category.key, category.text))
        
        # Find empty branches (branches with no items)
        # A branch is a keynote that has a category as parent but has no children (items)
        empty_branches = []
        for keynote in all_keynotes:
            # Check if this keynote is a branch (has category as parent)
            if keynote.parent_key in [cat.key for cat in all_categories]:
                # This is a branch, check if it has items (children)
                if keynote.key not in children_map or len(children_map[keynote.key]) == 0:
                    empty_branches.append(keynote)
                    print("Found empty branch: [{}] {} (no items)".format(keynote.key, keynote.text))
        
        if len(empty_categories) == 0 and len(empty_branches) == 0:
            print("No empty categories or branches found!")
            return {"empty_categories": 0, "empty_branches": 0, "total_removed": 0}
        
        # Let user select which items to delete
        items_to_delete = []
        
        # Show empty categories for selection
        if len(empty_categories) > 0:
            print("\nFound {} empty categories (categories with no branches):".format(len(empty_categories)))
            for cat in empty_categories:
                print("  - Category: [{}] {}".format(cat.key, cat.text))
            
            # Create selection list for categories
            category_options = []
            for cat in empty_categories:
                category_options.append("[{}] {}".format(cat.key, cat.text))
            
            selected_categories = forms.SelectFromList.show(
                category_options,
                title="Select Empty Categories to Delete",
                multiselect=True,
                button_name="Delete Selected Categories"
            )
            
            if selected_categories:
                # Find the actual category objects that were selected
                for selected_text in selected_categories:
                    for cat in empty_categories:
                        if "[{}] {}".format(cat.key, cat.text) == selected_text:
                            items_to_delete.append(("category", cat))
                            break
        
        # Show empty branches for selection
        if len(empty_branches) > 0:
            print("\nFound {} empty branches (branches with no items):".format(len(empty_branches)))
            for branch in empty_branches:
                print("  - Branch: [{}] {}".format(branch.key, branch.text))
            
            # Create selection list for branches
            branch_options = []
            for branch in empty_branches:
                branch_options.append("[{}] {}".format(branch.key, branch.text))
            
            selected_branches = forms.SelectFromList.show(
                branch_options,
                title="Select Empty Branches to Delete",
                multiselect=True,
                button_name="Delete Selected Branches"
            )
            
            if selected_branches:
                # Find the actual branch objects that were selected
                for selected_text in selected_branches:
                    for branch in empty_branches:
                        if "[{}] {}".format(branch.key, branch.text) == selected_text:
                            items_to_delete.append(("branch", branch))
                            break
        
        # Perform deletion of selected items
        if items_to_delete:
            print("\n=== DELETING SELECTED ITEMS ===")
            deleted_categories = 0
            deleted_branches = 0
            
            try:
                for item_type, item in items_to_delete:
                    if item_type == "category":
                        kdb.remove_category(keynote_data_conn, item.key)
                        print("Removed empty category: [{}] {}".format(item.key, item.text))
                        deleted_categories += 1
                    elif item_type == "branch":
                        kdb.remove_keynote(keynote_data_conn, item.key)
                        print("Removed empty branch: [{}] {}".format(item.key, item.text))
                        deleted_branches += 1
                
                print("Cleanup completed successfully!")
                NOTIFICATION.messenger("Removed {} empty categories and {} empty branches".format(
                    deleted_categories, deleted_branches))
                
                return {
                    "empty_categories": deleted_categories,
                    "empty_branches": deleted_branches,
                    "total_removed": deleted_categories + deleted_branches
                }
                
            except Exception as ex:
                print("Error during cleanup: {}".format(str(ex)))
                NOTIFICATION.messenger("Error during cleanup: {}".format(str(ex)))
                raise ex
        else:
            print("No items selected for deletion.")
            return {"empty_categories": 0, "empty_branches": 0, "total_removed": 0}
        
    except Exception as e:
        print("Error in remove_empty_categories_and_branches: {}".format(e))
        NOTIFICATION.messenger("Error removing empty categories and branches: {}".format(e))
        raise e



def change_extended_db_file_location(keynote_data_conn):
    """
    Change the saved location for extended DB file or Exterior/Interior Excel files.
    
    This function allows users to change the file paths for:
    1. Extended DB Excel file (main database file)
    2. Exterior Excel file (exported exterior keynotes)
    3. Interior Excel file (exported interior keynotes)
    
    Args:
        keynote_data_conn: Database connection to the keynote data
        
    Returns:
        None
    """
    doc = REVIT_APPLICATION.get_doc()
    t = DB.Transaction(doc, "change extended db file location")
    t.Start()
    REVIT_PROJ_DATA.setup_project_data(doc)
    t.Commit()
    
    # Get current settings
    extended_db_path = get_keynote_setting(doc, EXTENDED_DB_EXCEL_PATH_KEY)
    exterior_path = get_keynote_setting(doc, EXCEL_PATH_EXTERIOR_KEY)
    interior_path = get_keynote_setting(doc, EXCEL_PATH_INTERIOR_KEY)
    
    # Create options for what to change
    options = []
    if extended_db_path:
        options.append(["Extended DB Excel File", "Change location of the main extended database Excel file"])
    else:
        options.append(["Extended DB Excel File", "Set location of the main extended database Excel file (currently not set)"])
    
    if exterior_path:
        options.append(["Exterior Excel File", "Change location of the exported exterior keynotes Excel file"])
    else:
        options.append(["Exterior Excel File", "Set location of the exported exterior keynotes Excel file (currently not set)"])
    
    if interior_path:
        options.append(["Interior Excel File", "Change location of the exported interior keynotes Excel file"])
    else:
        options.append(["Interior Excel File", "Set location of the exported interior keynotes Excel file (currently not set)"])
    
    options.append("Cancel")
    
    # Show dialog to select what to change
    selected_option = REVIT_FORMS.dialogue(
        main_text="Change Extended DB File Location",
        sub_text="What would you like to change the location for?",
        options=options,
        icon="information"
    )
    
    if not selected_option or selected_option == "Cancel":
        print("Operation cancelled by user.")
        return
    
    # Determine which file type was selected
    if "Extended DB Excel File" in selected_option:
        current_path = extended_db_path
        setting_key = EXTENDED_DB_EXCEL_PATH_KEY
        file_description = "Extended Database Excel File"
    elif "Exterior Excel File" in selected_option:
        current_path = exterior_path
        setting_key = EXCEL_PATH_EXTERIOR_KEY
        file_description = "Exterior Keynotes Excel File"
    elif "Interior Excel File" in selected_option:
        current_path = interior_path
        setting_key = EXCEL_PATH_INTERIOR_KEY
        file_description = "Interior Keynotes Excel File"
    else:
        print("Invalid selection.")
        return
    
    # Show current path if it exists
    if current_path:
        print("Current {} location: {}".format(file_description, current_path))
        if os.path.exists(current_path):
            print("Current file exists and is accessible.")
        else:
            print("Warning: Current file does not exist at the specified location.")
    else:
        print("No current location set for {}.".format(file_description))
    
    # Prompt for new file location
    new_path = forms.pick_excel_file(
        title="Select New Location for {}".format(file_description),
        save=True
    )
    
    if not new_path:
        print("No new location selected. Operation cancelled.")
        return
    
    # Validate new path
    if new_path == current_path:
        print("New location is the same as current location. No changes made.")
        NOTIFICATION.messenger("New location is the same as current location. No changes made.")
        return
    
    # Check if file already exists at new location
    if os.path.exists(new_path):
        overwrite_options = [
            ["Yes, Overwrite", "Overwrite the existing file at the new location"],
            "Cancel"
        ]
        overwrite_choice = REVIT_FORMS.dialogue(
            main_text="File Already Exists",
            sub_text="A file already exists at the new location: {}\n\nDo you want to overwrite it?".format(new_path),
            options=overwrite_options,
            icon="warning"
        )
        
        if not overwrite_choice or overwrite_choice == "Cancel":
            print("Operation cancelled - file already exists at new location.")
            return
    
    # Update project data with new path
    try:
        set_keynote_setting(doc, setting_key, new_path)
        
        print("Successfully updated {} location to: {}".format(file_description, new_path))
        NOTIFICATION.messenger("Successfully updated {} location to:\n{}".format(file_description, new_path))
        
    except Exception as e:
        print("Error updating file location: {}".format(e))
        NOTIFICATION.messenger("Error updating file location: {}".format(e))
        return



if __name__ == "__main__":
    pass
