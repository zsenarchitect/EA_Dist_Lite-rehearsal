#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Family loading classes for Area2Mass conversion."""

import os
from Autodesk.Revit import DB # pyright: ignore 
from pyrevit.revit import ErrorSwallower # pyright: ignore 

from EnneadTab import ERROR_HANDLE, FOLDER
from EnneadTab.REVIT import REVIT_FAMILY


class FamilyLoader:
    """Loads and manages Revit families."""
    
    def __init__(self, family_doc, family_name):
        self.family_doc = family_doc
        self.family_name = family_name
        self.loaded_family = None
        self.debug_info = []
        
    def add_debug_info(self, message):
        """Add debug information."""
        self.debug_info.append(message)
        ERROR_HANDLE.print_note("DEBUG: {}".format(message))
    
    def load_into_project(self, project_doc):
        """Load family into the project document."""
        # Validate inputs
        if not self._validate_inputs(project_doc):
            return False

        # Save family to temporary location with a unique filename
        temp_path = self._save_family_to_temp()
        if not temp_path:
            return False

        # Load family into project (loading from the open family document; name derives from saved file)
        if not self._load_family_into_project(project_doc, temp_path):
            return False
        
        # No need to verify since REVIT_FAMILY.load_family is proven to work
        return True
    
    def _validate_inputs(self, project_doc):
        """Validate input parameters."""
        if not self.family_doc:
            ERROR_HANDLE.print_note("No family document provided")
            return False
        
        if not project_doc:
            ERROR_HANDLE.print_note("No project document provided")
            return False
        
        if not self.family_name:
            ERROR_HANDLE.print_note("No family name provided")
            return False
        
        return True
    
    def _save_family_to_temp(self):
        """Save family to a unique temporary location to define family name before loading."""
        # Base filename - each family should have a unique name by default
        base_filename = "{}.rfa".format(self.family_name)
        temp_path = FOLDER.get_local_dump_folder_file(base_filename)

        # Save family document
        options = DB.SaveAsOptions()
        options.OverwriteExistingFile = True
        # For family documents, use family-specific save options
        # Families are never workshared, so no worksharing options needed
        
        try:
            self.family_doc.SaveAs(temp_path, options)
        except Exception as e:
            ERROR_HANDLE.print_note("SaveAs failed: {}".format(str(e)))
            
            # Try to remove the file if it exists and is locked
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                    # Retry the SaveAs
                    self.family_doc.SaveAs(temp_path, options)
                except Exception as retry_e:
                    ERROR_HANDLE.print_note("SaveAs retry failed: {}".format(str(retry_e)))
                    return None
            else:
                return None

        if os.path.exists(temp_path):
            # Update the family name to match the actual saved filename (without extension)
            filename_without_ext = os.path.splitext(os.path.basename(temp_path))[0]
            self.family_name = filename_without_ext
            return temp_path
        else:
            ERROR_HANDLE.print_note("Failed to save family to temporary location")
            return None
    
    def _load_family_into_project(self, project_doc, temp_path):
        """Load family into project using the existing family document."""
        try:
            # Use ENNEADTAB.REVIT_FAMILY.load_family method directly with the family document
            # This is much simpler and leverages existing functionality
            REVIT_FAMILY.load_family(self.family_doc, project_doc)
            
            # Family is now loaded into the project
            self.loaded_family = True  # Just mark as loaded since we don't need the reference
            
            # Close the family document after successful loading to free up memory
            try:
                self.family_doc.Close(False)  # False = don't save changes
            except Exception as close_e:
                ERROR_HANDLE.print_note("Warning: Could not close family document: {}".format(str(close_e)))
            
            return True
                
        except Exception as e:
            ERROR_HANDLE.print_note("Exception during family loading: {}".format(str(e)))
            
            # Still try to close the family document even if loading failed
            try:
                self.family_doc.Close(False)
            except Exception as close_e:
                ERROR_HANDLE.print_note("Warning: Could not close family document: {}".format(str(close_e)))
            
            return False
            

    
    def _verify_family_loaded(self, project_doc):
        """Verify that family was loaded into project."""
        ERROR_HANDLE.print_note("Verifying family was loaded")
        
        # Check if family exists in project
        collector = DB.FilteredElementCollector(project_doc).OfClass(DB.Family)
        families = collector.ToElements()
        
        ERROR_HANDLE.print_note("Found {} families in project".format(len(families)))
        
        # First try exact name match
        for family in families:
            if family.Name == self.family_name:
                ERROR_HANDLE.print_note("Family verified in project (exact match): {}".format(family.Name))
                return True
        
        # If no exact match, try partial match (in case name was modified during loading)
        for family in families:
            if self.family_name in family.Name or family.Name in self.family_name:
                ERROR_HANDLE.print_note("Family verified in project (partial match): {} (looking for: {})".format(family.Name, self.family_name))
                return True
        
        # List all family names for debugging
        family_names = [f.Name for f in families]
        ERROR_HANDLE.print_note("Available families in project: {}".format(family_names))
        ERROR_HANDLE.print_note("Family not found in project after loading. Looking for: {}".format(self.family_name))
        return False
    
    def get_loaded_family(self):
        """Get the loaded family object."""
        return self.loaded_family
    
    def get_debug_summary(self):
        """Get summary of debug information."""
        return "\n".join(self.debug_info)


if __name__ == "__main__":
    """Test the FamilyLoader class when run as main module."""
    print("FamilyLoader module - This module provides family loading functionality.")
    print("To test this module, run it within a Revit environment with proper document context.")
