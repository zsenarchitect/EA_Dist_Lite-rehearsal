import os
import sys
root_folder = os.path.abspath((os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(root_folder)

import NOTIFICATION
import DATA_FILE
try:
    from Autodesk.Revit import DB # pyright: ignore
    from Autodesk.Revit import UI # pyright: ignore
    from pyrevit import forms
    import REVIT_PARAMETER
    import REVIT_COLOR_SCHEME
except:
    pass

PROJECT_DATA_PREFIX = "ProjectData_" # this is the prefix used in the shared dump folder to identify the project data file
PROJECT_DATA_PARA_NAME = "EnneadTab_Data" # this is the name of the parameter in the project information that stores the project data file name


TEMPLATE_DATA = {
    "container_file": None,
    "is_update_view_name_format": False,
    "parking_data": {
        "auto_update_enabled": False,
        "setting": {}
    },
    "area_tracking": {
        "auto_update_enabled": False,
        "para_dict": {
            "DEPARTMENT_KEY_PARA": "Area_$Department",
            "PROGRAM_TYPE_KEY_PARA": "Area_$Department_Program Type",
            "PROGRAM_TYPE_DETAIL_KEY_PARA": "Area_$Department_Program Type Detail"
        },
        "table_setting": {
            "DEPARTMENT_PARA_MAPPING": [
                            ("DIAGNOSTIC AND TREATMENT", "D&T"),
                            ("EMERGENCY DEPARTMENT", "ED"),
                            ("INPATIENT CARE", "BEDS"),
                            ("PUBLIC SUPPORT", "PUBLIC SUPPORT"),
                            ("ADMINISTRATION AND STAFF SUPPORT", "ADMIN"),
                            ("CLINICAL SUPPORT", "CLINICAL SUPPORT"),
                            ("BUILDING SUPPORT", "BUILDING SUPPORT"),
                            ("UNASSIGNED", "UNASSIGNED")
                            ],
            "DEPARTMENT_IGNORE_PARA_NAMES": ["PUBLIC CIRCULATION",
                                            "SERVICE CIRCULATION"]
        },

        "option_setting": {
            "primary_option": {
                "option_name": "",
                "levels": [],
                "OVERALL_AREA_SCHEME_NAME": "GFA Scheme",
                "DEPARTMENT_AREA_SCHEME_NAME": "DGSF Scheme"
            }
        }


    },
    "wall_type_update": {
        "auto_update_enabled": False,
        "setting": {}
    },
    "parking_update": {
        "auto_update_enabled": False,
        "setting": {}
    },
    "color_update": {
        "auto_update_enabled": False,
        "setting": {
            "excel_path": None,
            "naming_map": {
                "department_color_map":["Department Category_Primary"],
                "program_color_map":["Department Program Type_Primary"]
            }
        }
    },
    "keynote_assistant": {
        "setting": {
            "extended_db_excel_path": None
        }
    }
}

def is_setup_project_data_para_exist(doc):
    """Check if the EnneadTab_Data parameter exists in project information.
    
    Args:
        doc: Current Revit document
        
    Returns:
        bool: True if parameter exists, False otherwise
    """
    para = REVIT_PARAMETER.get_project_info_para_by_name(doc, PROJECT_DATA_PARA_NAME)
    if para:
        return True
    return False


def setup_project_data(doc):
    """Setup project data parameter and initialize project data file.
    
    Args:
        doc: Current Revit document
    """
    # Check if project data parameter already exists
    if is_setup_project_data_para_exist(doc):
        return

    # Create project data parameter first
    get_project_data_name(doc)  # This will create the parameter if it doesn't exist
    
    # Always use template data for new setup (avoid circular dependency)
    proj_data = TEMPLATE_DATA.copy()  # Use copy to avoid modifying template

    # Setup schedule update date parameter
    try:
        setup_schedule_update_date_parameter(doc)
    except Exception as e:
        print("  WARNING: Schedule update date parameter setup failed: {}".format(str(e)))
        # Continue with setup even if this fails

    # Save project data to shared storage
    try:
        set_revit_project_data(doc, proj_data)
    except Exception as e:
        print("  ERROR: Failed to save project data: {}".format(str(e)))
        print("  - This may indicate shared network folder connectivity issues")
        raise

    # Mark document to project data file
    try:
        mark_doc_to_project_data_file(doc)
    except Exception as e:
        print("  WARNING: Failed to mark document: {}".format(str(e)))
        # Continue even if marking fails, as the main data is already saved

    NOTIFICATION.messenger("Project data setup complete.")

def setup_schedule_update_date_parameter(doc):
    para_name = "Last_Update_Date"
    if not REVIT_PARAMETER.confirm_shared_para_exist_on_category(doc, 
                                                                 para_name,
                                                                 DB.BuiltInCategory.OST_Schedules):
        return False
    return True

def get_project_data_name(doc):
    """Get or create the project data identifier parameter.
    
    Creates the shared parameter if it doesn't exist and initializes it
    with the document title.
    
    Args:
        doc: Current Revit document
        
    Returns:
        str: Value of the project data parameter
    """
    # Check if parameter exists using the helper function
    if not is_setup_project_data_para_exist(doc):
        definition = REVIT_PARAMETER.get_shared_para_definition_in_txt_file_by_name(doc, PROJECT_DATA_PARA_NAME)
        if not definition:
            definition = REVIT_PARAMETER.create_shared_parameter_in_txt_file(doc, PROJECT_DATA_PARA_NAME, DB.SpecTypeId.String.Text)
        REVIT_PARAMETER.add_shared_parameter_to_project_doc(doc, 
                                                        definition, 
                                                        "Data", 
                                                        [DB.Category.GetCategory(doc,DB.BuiltInCategory.OST_ProjectInformation)])

        para = REVIT_PARAMETER.get_project_info_para_by_name(doc, PROJECT_DATA_PARA_NAME)
        if para is None:
            raise Exception("Failed to get project data parameter... this si not right because we just setup the parameter")

        para.Set(doc.Title)  # Set initial value to document title

    # Get the parameter value
    para = REVIT_PARAMETER.get_project_info_para_by_name(doc, PROJECT_DATA_PARA_NAME)
    if para is None:
        return None
    return para.AsString()

def get_project_data_file(doc):
    """Generate the project data file name based on project identifier.
    
    Args:
        doc: Current Revit document
        
    Returns:
        str: Full filename for project data storage
    """
    project_data_name = get_project_data_name(doc)
    return "{}{}".format(PROJECT_DATA_PREFIX, project_data_name)


def mark_doc_to_project_data_file(doc):
    """Record current document in the list of documents using this project data.
    
    Args:
        doc: Current Revit document
    """
    data = get_revit_project_data(doc)
    if "docs_attaching" not in data:
        data["docs_attaching"] = []
    data["docs_attaching"].append(doc.Title)
    set_revit_project_data(doc, data)

def reattach_project_data(doc):
    """Reattach project data from an existing setup file.
    
    Allows user to select from available project data files in the shared
    drive and updates the current document's project data reference.
    
    Args:
        doc: Current Revit document
    """
    # Print current project data file
    current_data_name = get_project_data_name(doc)
    print("Current project data file: {}".format(current_data_name))

    # Get all project data keys from depot shared state (network-drive
    # retirement epic, senzhang-todo #3171). State keys carry no file
    # extension -- see DATA_FILE._shared_state_key -- so no extension
    # filtering/stripping is needed here any more.
    from EnneadTab.DEPOT import STATE
    data_files = STATE.list_state(prefix=PROJECT_DATA_PREFIX)

    # Extract XXX parts for display
    display_options = [f.replace(PROJECT_DATA_PREFIX, "") for f in data_files]
    
    if not display_options:
        # STATE.list_state returns [] on a genuinely empty prefix AND on
        # offline/auth-failure/5xx alike, and (unlike read_state) never
        # alarms -- so this message cannot tell "nothing to reattach" from
        # "depot unreachable, list may be incomplete." Say so rather than
        # imply project data is missing.
        NOTIFICATION.messenger(
            "No project data found in the shared depot. If you are offline "
            "or the depot is unreachable, this list may be incomplete.")
        return
    
    # Let user pick from the list
    selected = forms.SelectFromList.show(
        display_options,
        multiselect=False,
        title="Select Project Data File to Attach",
        button_name="Select"
    )
        
    if not selected:
        return
    
    # Update project data file reference
    try:
        REVIT_PARAMETER.get_project_info_para_by_name(doc, PROJECT_DATA_PARA_NAME).Set("{}".format(selected))
        mark_doc_to_project_data_file(doc)
        NOTIFICATION.messenger("Successfully reattached project data.")
    except Exception as e:
        NOTIFICATION.messenger("Failed to reattach project data: {}".format(str(e)))


def get_revit_project_data(doc):
    """Retrieve project data from shared storage with auto-setup capability.
    
    Args:
        doc: Current Revit document
        
    Returns:
        dict: Project data dictionary from storage, None if retrieval fails
    """
    # Try to get project data directly first
    project_data = _retrieve_project_data_simple(doc)
    if project_data:
        return project_data
    
    # If retrieval fails, attempt auto-setup
    print("  - Project data retrieval failed, attempting auto-setup...")
    return auto_setup_project_data(doc)


def _retrieve_project_data_simple(doc):
    """Simple project data retrieval with basic error checking.
    
    Args:
        doc: Current Revit document
        
    Returns:
        dict: Project data dictionary from storage, None if retrieval fails
    """
    try:
        # 2026-08-31 (network-drive retirement epic, senzhang-todo #3171): the
        # office-shared-folder reachability pre-check (ENVIRONMENT.
        # alert_l_drive_not_available + IS_SHARED_DATA_LOST) is removed rather
        # than migrated. DATA_FILE.get_data(is_local=False) below now resolves
        # through DEPOT.STATE.read_state, which already degrades and alarms
        # (once/process, once/24h, plus a throttled ErrorDump report) on its
        # own when the depot is unreachable -- duplicating that check here
        # would just double the alarm/report with no depot-reachability probe
        # cheaper than the read itself.

        # Check if project data parameter exists
        if not is_setup_project_data_para_exist(doc):
            print("ERROR: Project data parameter does not exist")
            return None
        
        # Get project data file name
        project_data_file = get_project_data_file(doc)
        if not project_data_file:
            print("ERROR: Could not determine project data file name")
            return None
        
        # Attempt to get data from shared storage
        project_data = DATA_FILE.get_data(project_data_file, is_local=False)
        
        if project_data:
            return project_data
        else:
            print("ERROR: Project data is None or empty")
            print("  - Attempting to create fresh project data...")
            return create_fresh_project_data(doc)
            
    except Exception as e:
        print("ERROR: Error retrieving project data: {}".format(str(e)))
        return None


def get_revit_project_data_with_debugging(doc):
    """Enhanced project data retrieval with comprehensive debugging and auto-setup.
    
    This function provides detailed logging for troubleshooting project data issues.
    
    Args:
        doc: Current Revit document
        
    Returns:
        dict: Project data dictionary from storage, None if retrieval fails
    """
    # Step 1: Check project data parameter
    if not is_setup_project_data_para_exist(doc):
        print("ERROR: Project data parameter does not exist")
        print("Attempting auto-setup...")
        return auto_setup_project_data(doc)

    # Step 2: Get project data file name
    try:
        project_data_name = get_project_data_name(doc)
    except Exception as e:
        print("ERROR: Failed to get project data name: {}".format(str(e)))
        print("Attempting auto-setup...")
        return auto_setup_project_data(doc)

    # Step 3: Get project data file path
    try:
        project_data_file = get_project_data_file(doc)
    except Exception as e:
        print("ERROR: Failed to get project data file: {}".format(str(e)))
        print("Attempting auto-setup...")
        return auto_setup_project_data(doc)

    # Step 4 (network-drive retirement epic, senzhang-todo #3171): the old
    # "does the shared dump folder exist on disk" check is removed rather than
    # migrated -- depot state has no local folder to probe, and Step 5's
    # existing auto-setup fallback already covers a None/empty read (offline
    # with no cache), so no equivalent pre-check is needed.

    # Step 5: Attempt to retrieve project data
    try:
        project_data = _retrieve_project_data_simple(doc)
        if project_data:
            return project_data
        else:
            print("ERROR: Project data is None or empty")
            print("Attempting auto-setup...")
            return auto_setup_project_data(doc)
    except Exception as e:
        print("ERROR: Failed to retrieve project data: {}".format(str(e)))
        print("Attempting auto-setup...")
        return auto_setup_project_data(doc)


def get_revit_project_data_basic(doc):
    """Basic project data retrieval without auto-setup.
    
    This function is kept for backward compatibility.
    
    Args:
        doc: Current Revit document
        
    Returns:
        dict: Project data dictionary from storage, None if retrieval fails
    """
    return _retrieve_project_data_simple(doc)


def auto_setup_project_data(doc):
    """Automatically set up project data when retrieval fails"""
    try:
        # doc.IsModifiable is True precisely when a transaction is already open --
        # check it directly instead of using Transaction.Start() failure as a proxy,
        # which conflates "already in a transaction" with any other start failure.
        if not doc.IsModifiable:
            t = DB.Transaction(doc, "Auto Setup Project Data")
            t.Start()
            transaction_started = True
        else:
            print("  WARNING: Already in a transaction, working within existing transaction")
            t = None
            transaction_started = False
        
        try:
            # Call the setup function
            setup_project_data(doc)
            
            if transaction_started:
                t.Commit()
            
            # Now try to retrieve the data again
            proj_data = get_revit_project_data_basic(doc)
            if proj_data:
                return proj_data
            else:
                print("  ERROR: Still cannot retrieve project data after auto-setup")
                return None
                
        except Exception as setup_error:
            print("  ERROR: Auto-setup failed: {}".format(str(setup_error)))
            if transaction_started and t:
                t.RollBack()
            return None
            
    except Exception as e:
        print("  ERROR: Auto-setup transaction failed: {}".format(str(e)))
        return None


def create_fresh_project_data(doc):
    """Create fresh project data when file exists but is empty"""
    try:
        # Use template data
        proj_data = TEMPLATE_DATA.copy()
        
        # Save to shared storage
        set_revit_project_data(doc, proj_data)
        
        return proj_data
        
    except Exception as e:
        print("  ERROR: Failed to create fresh project data: {}".format(str(e)))
        return None


############### HEALTHCARE PROJECT SETUP FUNCTIONS ###############
def setup_healthcare_project(doc):
    """Setup healthcare project with comprehensive project data initialization.
    
    This function sets up a healthcare project with all necessary parameters,
    area tracking, and project data configuration.
    
    Args:
        doc: Current Revit document
    """
    try:
        # Step 1: Setup project data parameter and initial data
        t = DB.Transaction(doc, "setup ennedtab project data")
        t.Start()
        setup_project_data(doc)
        t.Commit()

        # Step 2: Retrieve project data with enhanced error handling and auto-setup
        # Enhanced debugging for project data retrieval with auto-setup
        proj_data = get_revit_project_data_with_debugging(doc)
        
        # Verify project data was retrieved successfully
        if not proj_data:
            error_msg = "Failed to retrieve project data even after auto-setup attempt. Please check shared network folder connectivity and try again."
            print("ERROR: " + error_msg)
            NOTIFICATION.messenger(error_msg)
            return

        # Step 3: Start transaction for healthcare-specific setup
        t = DB.Transaction(doc, "setup healthcare project")
        t.Start()
        
        try:
            # Step 4: Update project levels
            update_project_levels_in_project_data(doc, proj_data)

            # Step 5: Setup PIM number parameter
            setup_pim_number_parameter(doc)

            # Step 6: Setup area tracking parameters
            if not setup_area_tracking_parameters(doc, proj_data):
                t.RollBack()
                return

            # Step 7: Save updated project data
            set_revit_project_data(doc, proj_data)
            t.Commit()

            NOTIFICATION.messenger("Healthcare project setup complete.")
            
        except Exception as e:
            print("ERROR: Error during healthcare-specific setup: {}".format(str(e)))
            t.RollBack()
            raise
        
    except Exception as e:
        error_msg = "Error during healthcare project setup: {}".format(str(e))
        print("ERROR: " + error_msg)
        NOTIFICATION.messenger(error_msg)
        # Try to rollback any active transaction
        try:
            if 't' in locals() and t.HasStarted():
                t.RollBack()
        except:
            pass


def setup_pim_number_parameter(doc):
    """Sets up PIM Number parameter in project info"""
    try:
        para_name = "PIM_Number"
        para = REVIT_PARAMETER.get_project_info_para_by_name(doc, para_name)
        if not para:
            definition = REVIT_PARAMETER.get_shared_para_definition_in_txt_file_by_name(doc, para_name)
            if not definition:
                definition = REVIT_PARAMETER.create_shared_parameter_in_txt_file(doc, para_name, DB.SpecTypeId.String.Text)
            
            REVIT_PARAMETER.add_shared_parameter_to_project_doc(doc, 
                                                            definition, 
                                                            "Data", 
                                                            [DB.Category.GetCategory(doc,DB.BuiltInCategory.OST_ProjectInformation)])
            para = REVIT_PARAMETER.get_project_info_para_by_name(doc, para_name)

        default_value = "Replace Me with the real PIM Number"
        if para and para.AsString() != default_value:
            para.Set(default_value)
            
    except Exception as e:
        NOTIFICATION.messenger("Error setting up PIM Number parameter: {}".format(str(e)))


def setup_area_tracking_parameters(doc, proj_data):
    """Ensures required area parameters exist in the project"""
    # Add null checks to prevent KeyError
    if not proj_data:
        NOTIFICATION.messenger("Project data is not available. Please ensure project data is properly initialized.")
        return False
    
    area_tracking = proj_data.get("area_tracking")
    if not area_tracking:
        NOTIFICATION.messenger("Area tracking configuration is missing from project data.")
        return False
    
    para_dict = area_tracking.get("para_dict")
    if not para_dict:
        NOTIFICATION.messenger("Area tracking parameter dictionary is missing from project data.")
        return False
    
    # Check if any area elements exist
    existing_areas = list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Areas).WhereElementIsNotElementType().ToElements())
    temp_area_created = False
    
    try:
        # If no areas exist, create a temporary one for parameter setup
        if not existing_areas:
            temp_area_created = _create_temporary_area_for_setup(doc)
            if not temp_area_created:
                NOTIFICATION.messenger("Failed to create temporary area element. Please create at least one area manually and try again.")
                return False
        
        # Setup area parameters
        for para_name in para_dict.values():
            if not REVIT_PARAMETER.confirm_shared_para_exist_on_category(doc, para_name, DB.BuiltInCategory.OST_Areas):
                print("  ERROR: Failed to create parameter: {}".format(para_name))
                return False
        
        return True
        
    finally:
        # Clean up temporary area if we created one
        if temp_area_created:
            _cleanup_temporary_area(doc)


def _create_temporary_area_for_setup(doc):
    """Create a temporary area element for parameter setup"""
    try:
        # Get the first level to place the area
        levels = list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Levels).WhereElementIsNotElementType().ToElements())
        if not levels:
            print("  ERROR: No levels found in project")
            return False
        
        # Get the first area scheme
        area_schemes = list(DB.FilteredElementCollector(doc).OfClass(DB.AreaScheme).ToElements())
        if not area_schemes:
            print("  ERROR: No area schemes found in project")
            return False
        
        # Create a simple rectangle for the temporary area
        level = levels[0]
        area_scheme = area_schemes[0]
        
        # Create a simple rectangle curve loop (1x1 foot)
        start_point = DB.XYZ(0, 0, level.Elevation)
        end_point = DB.XYZ(1, 1, level.Elevation)
        
        # Create curve loop
        curve_loop = DB.CurveLoop()
        curve_loop.Append(DB.Line.CreateBound(start_point, DB.XYZ(end_point.X, start_point.Y, start_point.Z)))
        curve_loop.Append(DB.Line.CreateBound(DB.XYZ(end_point.X, start_point.Y, start_point.Z), end_point))
        curve_loop.Append(DB.Line.CreateBound(end_point, DB.XYZ(start_point.X, end_point.Y, start_point.Z)))
        curve_loop.Append(DB.Line.CreateBound(DB.XYZ(start_point.X, end_point.Y, start_point.Z), start_point))
        
        # Create the area
        area = DB.Area.Create(doc, area_scheme.Id, level.Id, curve_loop)
        
        if area:
            return True
        else:
            print("  ERROR: Failed to create temporary area")
            return False
            
    except Exception as e:
        print("  ERROR: Exception creating temporary area: {}".format(str(e)))
        return False


def _cleanup_temporary_area(doc):
    """Remove the temporary area element created for setup"""
    try:
        # Find and delete the temporary area (1x1 foot area at origin)
        areas = list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Areas).WhereElementIsNotElementType().ToElements())
        
        for area in areas:
            # Check if this is our temporary area (1x1 foot at origin)
            try:
                area_curve_loop = area.AreaCurveLoop
                if area_curve_loop and len(area_curve_loop) == 4:
                    # Check if it's approximately 1x1 foot
                    area_value = area.Area
                    if 0.9 < area_value < 1.1:  # Allow small tolerance
                        doc.Delete(area.Id)
                        return
            except:
                continue
                
        print("  WARNING: Could not find temporary area to clean up")
        
    except Exception as e:
        print("  WARNING: Error cleaning up temporary area: {}".format(str(e)))


def update_project_levels_in_project_data(doc, proj_data):
    """Updates project levels in tracking data"""
    # Add null checks to prevent KeyError
    if not proj_data:
        NOTIFICATION.messenger("Project data is not available. Please ensure project data is properly initialized.")
        return
    
    area_tracking = proj_data.get("area_tracking")
    if not area_tracking:
        NOTIFICATION.messenger("Area tracking configuration is missing from project data.")
        return
    
    option_setting = area_tracking.get("option_setting")
    if not option_setting:
        NOTIFICATION.messenger("Area tracking option settings are missing from project data.")
        return
    
    levels = list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Levels).WhereElementIsNotElementType().ToElements())
    levels.sort(key=lambda x: x.Elevation, reverse=True)

    picked_levels = forms.SelectFromList.show(levels, name_attr="Name", title="Select Levels to include in calculation", button_name="Select Levels", multiselect=True)
    if not picked_levels:
        NOTIFICATION.messenger("No levels selected. Operation cancelled.")
        return
    
    level_names = [level.Name for level in picked_levels]

    for option_setting_item in option_setting.values():
        if isinstance(option_setting_item, dict):
            option_setting_item["levels"] = level_names


def set_revit_project_data(doc, data):
    """Save project data to shared storage.
    
    Args:
        doc: Current Revit document
        data: Dictionary containing project data to save
    """
    DATA_FILE.set_data(data, get_project_data_file(doc), is_local=False)


############### FILE OPERATIONS ###############
def open_project_data_file(doc):
    """Retired (network-drive retirement epic, senzhang-todo #3171): project
    data now lives in depot shared state, not a local file with a stable path
    to hand to os.startfile. Opening/editing a raw local copy here would also
    reintroduce the exact silent-local-edit failure mode this epic exists to
    remove -- such edits would never round-trip through DEPOT.STATE's
    rev-checked write. Use the built-in editor instead."""
    NOTIFICATION.messenger(
        "Direct file access to project data has been retired. Use "
        "'Edit Project Data' to view or change it.")

def edit_project_data_file(doc):
    editor = ProjectDataEditor(doc)
    editor.edit_project_data()

############### PROJECT DATA EDITOR CLASS ###############
class ProjectDataEditor:
    def __init__(self, doc):
        self.doc = doc
        self.project_data = get_revit_project_data(doc)
        
        # Define menu configurations
        self.main_menu = {
            "1. Reattach Project Data To Exisitng Setup": self._reattach_project_data,
            "2. Healthcare Area Tracking": self._edit_area_tracking,
            "3. Auto View Name Update": self._edit_auto_view_name_update,
            "4. Color Update": self._edit_color_update,
            "5. Save and Close": None

        }
        
        self.area_tracking_menu = {
            "1. Enable/Disable Auto Update": self._edit_auto_update_enabled,
            "2. Edit Design Option": self._edit_design_option,
            "3. Duplicate Design Option": self._duplicate_design_option,
            "4. Delete Design Option": self._delete_design_option,
            "5. Return to Previous Menu": None
        }
        


        self.design_option_menu = {
            "1. Edit Levels": lambda opt: self._edit_levels(opt),
            "2. Edit Overall Area Scheme": lambda opt: self._edit_option_setting(opt, "OVERALL_AREA_SCHEME_NAME", "Overall Area Scheme"),
            "3. Edit Department Area Scheme": lambda opt: self._edit_option_setting(opt, "DEPARTMENT_AREA_SCHEME_NAME", "Department Area Scheme"),
            "4. Edit Option Name": lambda opt: self._edit_option_setting(opt, "option_name", "Option Name"),
            "5. Return to Previous Menu": None
        }

        self.color_update_menu = {
            "1. Edit Color Update": self._edit_color_update,
            "2. Edit Excel Path": self._edit_excel_path,
            "3. Edit ColorScheme Naming Map": self._edit_naming_map,
            "4. Return to Previous Menu": None
        }

    def edit_project_data(self):
        """Main entry point for editing project data"""
        if not self.project_data:
            NOTIFICATION.messenger("No project data found.")
            return

        while True:
            selection = self._show_menu("Project Data Editor", self.main_menu)
            if not selection:
                break
            function = self.main_menu[selection]
            if self._is_return_option(selection):
                break
            function()



    def _show_menu(self, title, options, **kwargs):
        """Generic menu display and handling"""
        return forms.SelectFromList.show(
            sorted(options.keys()),
            multiselect=False,
            title=title,
            button_name="Select",
            **kwargs
        )

    def _is_return_option(self, selection):
        """Check if the selected option is a return option"""
        return selection is None or "Return to Previous Menu" in str(selection) or "Save and Close" in str(selection)

    def _edit_color_update(self):
        """Edit color update options"""
        while True:
            res = self._show_menu("Auto Color Update Options", self.color_update_menu)
            if self._is_return_option(res):
                break
            
            if res in self.color_update_menu:
                self.color_update_menu[res]()

    def _edit_excel_path(self):
        """Edit excel path"""
        while True:
            res = forms.pick_file(
                title="Select Excel File",
                files_filter="Excel Files (*.xls;*.xlsx)|*.xls;*.xlsx"
            )
            if res:
                self.project_data["color_update"]["setting"]["excel_path"] = res
                self._save_changes()
                break

    def _edit_naming_map(self):
        """Edit naming map"""
        while True:
            department_color_scheme_names = REVIT_COLOR_SCHEME.pick_color_schemes(self.doc, 
                                                                                 title="Select the [DEPARTMENT] color schemes", 
                                                                                 button_name="Select [DEPARTMENT] color schemes")
            if not department_color_scheme_names:
                NOTIFICATION.messenger("No [DEPARTMENT] color scheme selected")
                continue
            
            program_color_scheme_names = REVIT_COLOR_SCHEME.pick_color_schemes(self.doc, 
                                                                                 title="Select the [PROGRAM] color schemes", 
                                                                                 button_name="Select [PROGRAM] color schemes")
            if not program_color_scheme_names:
                NOTIFICATION.messenger("No [PROGRAM] color scheme selected")
                continue
            
            self.project_data["color_update"]["setting"]["naming_map"]["department_color_map"] = department_color_scheme_names
            self.project_data["color_update"]["setting"]["naming_map"]["program_color_map"] = program_color_scheme_names
            self._save_changes()
            break
    


    def _edit_area_tracking(self):
        """Handle area tracking editing options"""
        while True:
            res = self._show_menu("Area Tracking Options", self.area_tracking_menu)
            if self._is_return_option(res):
                break
            
            if res in self.area_tracking_menu:
                self.area_tracking_menu[res]()

    def _edit_design_option(self):
        """Edit specific design option settings"""
        selected_option = self._select_design_option("Select Design Option")
        if not selected_option:
            return

        while True:
            res = self._show_menu(
                "Editing Option: {}".format(selected_option),
                self.design_option_menu
            )
            if self._is_return_option(res):
                break
            


            if res in self.design_option_menu:
                self.design_option_menu[res](selected_option)

    def _toggle_setting(self, setting_path, title):
        """Generic toggle setting handler"""
        options = {
            "1. Enable Auto Update": True,
            "2. Disable Auto Update": False,
            "3. Return to Previous Menu": None
        }
        
        while True:
            res = self._show_menu(
                title,
                options,
                
            )
            if self._is_return_option(res):
                break
            

            if res in options and options[res] is not None:
                self._set_nested_dict_value(
                    self.project_data,
                    setting_path,
                    options[res]
                )
                self._save_changes()
                break

    def _edit_option_setting(self, option_name, setting_key, title):
        """Generic option setting editor"""
        while True:
            if option_name not in self.project_data["area_tracking"]["option_setting"]:
                NOTIFICATION.messenger("Option '{}' not found due to renaming, return to previous menu and re-select option using the new name.".format(option_name))
                break
            
            current_value = self.project_data["area_tracking"]["option_setting"][option_name][setting_key]
            new_value = forms.ask_for_string(
                default=current_value,
                prompt="Enter {} (ESC to cancel)".format(title.lower()),
                title=title
            )


            

            if new_value is None:  # User pressed ESC
                break
            
            if new_value.strip():  # Ensure non-empty value
                self.project_data["area_tracking"]["option_setting"][option_name][setting_key] = new_value

                if setting_key == "option_name":
                    self.project_data["area_tracking"]["option_setting"][new_value] = self.project_data["area_tracking"]["option_setting"][option_name].copy()
                    del self.project_data["area_tracking"]["option_setting"][option_name]

                self._save_changes()
                break


    def _select_design_option(self, title):
        """Generic design option selector"""
        options = list(self.project_data["area_tracking"]["option_setting"].keys())
        options.append("Return to Previous Menu")
        
        return forms.SelectFromList.show(
            options,
            multiselect=False,
            title=title,
            button_name="Select"
        )

    def _duplicate_design_option(self):
        """Create a copy of an existing design option"""
        while True:
            source_option = self._select_design_option("Select Option to Duplicate")
            if self._is_return_option(source_option):
                break


            design_options = self.project_data["area_tracking"]["option_setting"].keys()
            new_name = forms.ask_for_unique_string(
                reserved_values=design_options,
                title="New Option Name (ESC to cancel)",
                button_name="Create"
            )

            
            if new_name is None:  # User pressed ESC
                continue
                
            if new_name:
                self.project_data["area_tracking"]["option_setting"][new_name] = \
                    self.project_data["area_tracking"]["option_setting"][source_option].copy()

                self.project_data["area_tracking"]["option_setting"][new_name]["option_name"] = new_name
                self._save_changes()
                break

    def _edit_levels(self, option_name):
        """Edit level selection for a design option"""
        while True:
            levels = list(DB.FilteredElementCollector(self.doc)
                         .OfCategory(DB.BuiltInCategory.OST_Levels)
                         .WhereElementIsNotElementType()
                         .ToElements())
            levels.sort(key=lambda x: x.Elevation, reverse=True)
            
            
            # Add return option
            level_options = list(levels)

            picked_levels = forms.SelectFromList.show(
                level_options,
                name_attr="Name",
                title="Select Levels for Calculation",
                button_name="Confirm",
                multiselect=True
            )
            
            if not picked_levels:
                break
            
            level_names = [level.Name for level in picked_levels]
            self.project_data["area_tracking"]["option_setting"][option_name]["levels"] = level_names
            self._save_changes()
            break

    def _edit_auto_update_enabled(self):
        """Toggle auto update setting for area tracking"""
        self._toggle_setting(
            ["area_tracking", "auto_update_enabled"],
            "Toggle auto update for area tracking"
        )

    def _edit_auto_view_name_update(self):
        """Toggle auto view name update setting"""
        self._toggle_setting(
            ["is_update_view_name_format"],
            "Toggle auto view name update"
        )

    def _set_nested_dict_value(self, dictionary, path, value):
        """Helper method to set nested dictionary value using a path list
        
        Example:
        dictionary = {
            "area_tracking": {
                "auto_update_enabled": False,
                "settings": {"color": "blue"}
            }
        }
        
        # To update auto_update_enabled:
        path = ["area_tracking", "auto_update_enabled"]
        value = True
        # Result: dictionary["area_tracking"]["auto_update_enabled"] = True
        
        # To update color:
        path = ["area_tracking", "settings", "color"]
        value = "red"
        # Result: dictionary["area_tracking"]["settings"]["color"] = "red"
        """
        current = dictionary
        for key in path[:-1]:  # Navigate through all keys except the last one
            current = current[key]
        current[path[-1]] = value  # Set the value at the final key

    def _save_changes(self):
        """Save changes to project data"""
        set_revit_project_data(self.doc, self.project_data)
        NOTIFICATION.messenger("Project data updated successfully!")

    def _delete_design_option(self):
        """Delete a selected design option"""
        while True:
            option_to_delete = self._select_design_option("Select Option to Delete")
            if self._is_return_option(option_to_delete):
                break
                


            confirm = forms.alert(
                msg="Are you sure you want to delete option '{}'?".format(option_to_delete),
                title="Confirm Deletion",
                ok=False,
                yes=True,
                no=True
            )
            
            if confirm:
                del self.project_data["area_tracking"]["option_setting"][option_to_delete]
                self._save_changes()
                NOTIFICATION.messenger("Design option '{}' has been deleted.".format(option_to_delete))
                break


    def _reattach_project_data(self):
        t = DB.Transaction(self.doc, "Reattach Project Data")
        t.Start()
        reattach_project_data(self.doc)
        t.Commit()
