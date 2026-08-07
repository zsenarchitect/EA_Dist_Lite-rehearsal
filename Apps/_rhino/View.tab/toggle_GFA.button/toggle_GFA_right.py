__title__ = "BakeGFADataToExcel"
__doc__ = """Export GFA (Gross Floor Area) data to Excel and manage area targets.

Features:
- Export area calculations to formatted Excel spreadsheet
- Generate checking surfaces for visual verification 
- Set and manage target areas for different GFA categories
- Compare actual vs target areas with variance analysis

Usage:
- Click to export current GFA data to Excel
- Right-click to access additional options:
  - Generate checking surfaces
  - Set target areas for GFA categories
  - Edit existing target values
"""



import os
import Rhino # pyright: ignore
import rhinoscriptsyntax as rs # pyright: ignore
import scriptcontext as sc # pyright: ignore
import Eto # pyright: ignore
from EnneadTab import ERROR_HANDLE, LOG, EXCEL, NOTIFICATION
from EnneadTab.RHINO import RHINO_PROJ_DATA, RHINO_UI
import gfa_excel_import
reload(gfa_excel_import)

FORM_KEY = 'gfa_target_form'

@ERROR_HANDLE.try_catch_error()
def bake_action(data):
    filename = "EnneadTab GFA Schedule"
    try:
        if sc.doc and hasattr(sc.doc, 'Name') and sc.doc.Name:
            doc_name = str(sc.doc.Name)
            filename = "{}_EnneadTab GFA Schedule".format(doc_name.replace(".3dm", ""))
    except:
        pass


    filepath = rs.SaveFileName(title = "Where to save the Excel?", filter = "Excel Files (*.xlsx)|*.xlsx||", filename = filename)
    if filepath is None:
        return
    EXCEL.save_data_to_excel(data, filepath, worksheet = "EnneadTab GFA")


class GFATargetDialog(Eto.Forms.Dialog[bool]):
    def __init__(self, gfa_dict):
        self.Title = "GFA Target Dictionary"
        self.Padding = Eto.Drawing.Padding(5)
        self.Resizable = True
        self.Width = 600
        self.Height = 480
        
        # Store the dictionary
        self.gfa_dict = gfa_dict.copy()
        
        # Create main layout
        layout = Eto.Forms.DynamicLayout()
        layout.Padding = Eto.Drawing.Padding(5)
        layout.Spacing = Eto.Drawing.Size(5, 5)

        # Add instruction label at the top
        instruction_label = Eto.Forms.Label(Text="Keywords are case sensitive. If any layer name contains a keyword, its target data will be used.")
        layout.AddRow(instruction_label)
        
        # Create grid view
        self.grid = Eto.Forms.GridView()
        self.grid.ShowHeader = True
        self.grid.ShowCellBorders = True
        self.grid.Height = 300
        self.grid.CellEdited += self.OnCellEdited
        
        # Add columns with 1:1 ratio, slightly reduced to avoid horizontal scroll
        col_width = self.Width / 2 * 0.9
        keyword_column = Eto.Forms.GridColumn()
        keyword_column.HeaderText = "Keyword"
        keyword_column.Editable = True
        keyword_column.DataCell = Eto.Forms.TextBoxCell(0)
        keyword_column.Width = col_width
        self.grid.Columns.Add(keyword_column)
        
        value_column = Eto.Forms.GridColumn()
        value_column.HeaderText = "Target Area"
        value_column.Editable = True
        value_column.DataCell = Eto.Forms.TextBoxCell(1)
        value_column.Width = col_width
        self.grid.Columns.Add(value_column)
        
        # Update grid data
        self.update_grid_data()
        
        # Create buttons with consistent sizing
        add_button = Eto.Forms.Button(Text="Add Keyword")
        add_button.Width = 120
        add_button.Click += self.OnAddButtonClick
        
        delete_button = Eto.Forms.Button(Text="Delete Selected")
        delete_button.Width = 120
        delete_button.Click += self.OnDeleteButtonClick
        
        import_button = Eto.Forms.Button(Text="Import from Excel")
        import_button.Width = 140
        import_button.Click += self.OnImportButtonClick
        
        sample_button = Eto.Forms.Button(Text="Show Sample Excel")
        sample_button.Width = 140
        sample_button.Click += self.OnSampleButtonClick
        
        ok_button = Eto.Forms.Button(Text="OK")
        ok_button.Width = 80
        ok_button.Click += self.OnOkButtonClick
        
        cancel_button = Eto.Forms.Button(Text="Cancel")
        cancel_button.Width = 80
        cancel_button.Click += self.OnCancelButtonClick
        
        # Use TableLayout for buttons with better organization
        button_layout = Eto.Forms.TableLayout()
        button_layout.Spacing = Eto.Drawing.Size(5, 5)
        button_layout.Padding = Eto.Drawing.Padding(5)
        
        # First row: Action buttons
        button_layout.Rows.Add(Eto.Forms.TableRow(None, add_button, delete_button))
        # Second row: Import buttons  
        button_layout.Rows.Add(Eto.Forms.TableRow(None, import_button, sample_button))
        # Third row: OK/Cancel buttons
        button_layout.Rows.Add(Eto.Forms.TableRow(None, ok_button, cancel_button))
        
        # Add controls to layout
        layout.AddRow(self.grid)
        layout.AddRow(button_layout)
        
        # Set content
        self.Content = layout
        
        # Apply dark style
        RHINO_UI.apply_dark_style(self)
    
    def update_project_data_and_grid(self, gfa_dict):
        """Save gfa_dict to project data and update the grid from project data."""
        data = RHINO_PROJ_DATA.get_plugin_data()
        data[RHINO_PROJ_DATA.DocKeys.GFA_TARGET_DICT] = gfa_dict
        RHINO_PROJ_DATA.set_plugin_data(data)
        self.update_grid_data()

    def update_grid_data(self):
        """Always pull the latest from project data for the grid."""
        data = RHINO_PROJ_DATA.get_plugin_data()
        gfa_dict = data.get(RHINO_PROJ_DATA.DocKeys.GFA_TARGET_DICT, {})
        self.gfa_dict = gfa_dict.copy()
        self.grid.DataStore = [[k, str(v)] for k, v in sorted(self.gfa_dict.items())]

    def OnCellEdited(self, sender, e):
        row = e.Row
        col = e.Column
        item = self.grid.DataStore[row]
        data = RHINO_PROJ_DATA.get_plugin_data()
        gfa_dict = data.get(RHINO_PROJ_DATA.DocKeys.GFA_TARGET_DICT, {})
        updated = False
        if col == 0:  # Keyword column
            old_key = item[0]
            new_key = item[0]
            if new_key and new_key != old_key:
                value = gfa_dict.pop(old_key)
                gfa_dict[new_key] = value
                updated = True
        elif col == 1:  # Value column
            try:
                value = float(item[1])
                key = item[0]
                gfa_dict[key] = value
                updated = True
            except ValueError:
                NOTIFICATION.messenger(main_text = "Invalid number. Please enter a valid number.")
                self.update_grid_data()
                return
        if updated:
            self.update_project_data_and_grid(gfa_dict)

    def OnAddButtonClick(self, sender, e):
        base_name = "New Item"
        i = 1
        data = RHINO_PROJ_DATA.get_plugin_data()
        gfa_dict = data.get(RHINO_PROJ_DATA.DocKeys.GFA_TARGET_DICT, {})
        existing = set(gfa_dict.keys())
        new_name = "{} {}".format(base_name, i)
        while new_name in existing:
            i += 1
            new_name = "{} {}".format(base_name, i)
        gfa_dict[new_name] = -1
        self.update_project_data_and_grid(gfa_dict)

    def OnDeleteButtonClick(self, sender, e):
        data = RHINO_PROJ_DATA.get_plugin_data()
        gfa_dict = data.get(RHINO_PROJ_DATA.DocKeys.GFA_TARGET_DICT, {})
        selected_items = list(self.grid.SelectedItems)
        if not selected_items:
            return
        for item in selected_items:
            key = item[0]
            if key in gfa_dict:
                del gfa_dict[key]
        self.update_project_data_and_grid(gfa_dict)

    def OnOkButtonClick(self, sender, e):
        """Save changes and close"""
        self.Close(True)
    
    def OnCancelButtonClick(self, sender, e):
        """Discard changes and close"""
        self.Close(False)
    
    def OnImportButtonClick(self, sender, e):
        """Import GFA targets from Excel file"""
        print("=== GFA Excel Import Button Clicked ===")
        
        try:
            # Use the dedicated Excel import utility
            result = gfa_excel_import.import_gfa_from_excel()
            
            if result:
                print("Excel import completed successfully!")
                # Refresh the grid to show updated data
                self.update_grid_data()
                NOTIFICATION.messenger(main_text="GFA targets imported from Excel successfully!")
            else:
                print("Excel import failed")
                NOTIFICATION.messenger(main_text="Failed to import GFA targets from Excel")
                
        except Exception as ex:
            print("Error during Excel import: {}".format(str(ex)))
            NOTIFICATION.messenger(main_text="Error importing from Excel: {}".format(str(ex)))
    
    def OnSampleButtonClick(self, sender, e):
        """Show sample Excel file"""
        print("=== Show Sample Excel Button Clicked ===")
        
        try:
            # Get the directory where this script is located
            script_dir = os.path.dirname(os.path.abspath(__file__))
            sample_file = os.path.join(script_dir, "GFA_Sample_Targets.xlsx")
            
            print("Looking for sample Excel file: {}".format(sample_file))
            
            if os.path.exists(sample_file):
                print("Sample Excel file found!")
                print("Opening sample Excel file...")
                
                # Actually open the Excel file
                self.open_sample_excel(sample_file)
                
                NOTIFICATION.messenger(main_text="Sample Excel file opened successfully!")
            else:
                print("Sample Excel file not found.")
                NOTIFICATION.messenger(main_text="Sample Excel file not found. Please place GFA_Sample_Targets.xlsx in the script directory.")
                
        except Exception as ex:
            print("Error showing sample Excel: {}".format(str(ex)))
            NOTIFICATION.messenger(main_text="Error showing sample Excel: {}".format(str(ex)))
    
    def open_sample_excel(self, filepath):
        """Open the sample Excel file"""
        print("=== Opening Sample Excel File ===")
        print("File path: {}".format(filepath))
        
        try:
            # Open the Excel file using the system default application
            import subprocess
            import platform
            
            if platform.system() == "Windows":
                os.startfile(filepath)
            elif platform.system() == "Darwin":  # macOS
                subprocess.call(["open", filepath])
            else:  # Linux
                subprocess.call(["xdg-open", filepath])
            
            print("Sample Excel file opened successfully!")
            print("You can use this as a template for your own GFA targets.")
            
        except Exception as ex:
            print("Error opening Excel file: {}".format(str(ex)))
            print("Trying alternative method...")
            
            # Fallback: try to open with Excel directly
            try:
                import subprocess
                subprocess.Popen(['excel', filepath], shell=True)
                print("Sample Excel file opened with Excel application!")
            except:
                print("Could not open Excel file automatically.")
                print("Please manually open: {}".format(filepath))
    

@ERROR_HANDLE.try_catch_error()
def set_target_dict():
    """Manage GFA target areas using a modern Eto form interface.
    
    Returns:
        dict: Updated GFA target dictionary
    """
    data = RHINO_PROJ_DATA.get_plugin_data()
    gfa_dict = data.get(RHINO_PROJ_DATA.DocKeys.GFA_TARGET_DICT, {})
    
    dialog = GFATargetDialog(gfa_dict)
    rc = Rhino.UI.EtoExtensions.ShowSemiModal(dialog, Rhino.RhinoDoc.ActiveDoc, Rhino.UI.RhinoEtoApp.MainWindow)
    if rc:
        # User clicked OK, save changes
        data[RHINO_PROJ_DATA.DocKeys.GFA_TARGET_DICT] = dialog.gfa_dict
        RHINO_PROJ_DATA.set_plugin_data(data)
        return dialog.gfa_dict
    
    return gfa_dict

@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def toggle_GFA():
    
    """
    key = "EA_GFA_EXCEL_PATH"
    sc.sticky[key] = filepath
    """


    items  = [
        ("Export Current GFA Numbers To Excel.", False),
        ("Bake Current GFA Calc Surfaces.", False),
        ("Set Target Dict.", False)
        ]
    results  = rs.CheckListBox(items, "What do you want to do?", "Bake GFA Massing Data")
    if not results:
        return

    

    key = "EA_GFA_IS_BAKING_EXCEL"
    sc.sticky[key] = results[0][1]

    key = "EA_GFA_IS_BAKING_CRV"
    sc.sticky[key] = results[1][1]

    set_target_dict() if results[2][1] else None

    if results[0][1] or results[1][1]:
        NOTIFICATION.messenger(main_text = "Shake your Rhino viewport camera to trigger baking.")
    

    
if __name__ == "__main__":
    toggle_GFA()


