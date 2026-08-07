#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Template management classes for Area2Mass conversion."""

import os
import shutil
import time
from EnneadTab import SAMPLE_FILE, FOLDER, ERROR_HANDLE


class TemplateFinder:
    """Finds and manages mass family templates."""
    
    def __init__(self):
        self.template_path = None
    
    def get_mass_family_template(self):
        """Get the mass family template file path."""
        self.template_path = self._get_empty_mass_template()
        return self.template_path
    
    def _get_empty_mass_template(self):
        """Get EmptyMass template and copy to safe location."""
        # Get EmptyMass.rfa from SAMPLE_FILE
        source_path = SAMPLE_FILE.get_file("EmptyMass.rfa")
        
        if not source_path or not os.path.exists(source_path):
            ERROR_HANDLE.print_note("EmptyMass.rfa not found in SAMPLE_FILE")
            return None
        
        # Copy to DUMP folder with .rfa extension to maintain proper template type
        destination_path = FOLDER.get_local_dump_folder_file("EmptyMass_Template.rfa")
        
        # Ensure destination directory exists
        destination_dir = os.path.dirname(destination_path)
        if not os.path.exists(destination_dir):
            os.makedirs(destination_dir)
        
        # Check if destination file already exists and is accessible
        if os.path.exists(destination_path):
            try:
                # Try to open the file to see if it's accessible
                with open(destination_path, 'r') as test_file:
                    pass
                ERROR_HANDLE.print_note("Template already exists and is accessible: {}".format(destination_path))
                return destination_path
            except IOError:
                ERROR_HANDLE.print_note("Existing template file is locked, trying to remove and recopy...")
                try:
                    os.remove(destination_path)
                    ERROR_HANDLE.print_note("Removed locked template file")
                except Exception as e:
                    ERROR_HANDLE.print_note("Failed to remove locked file: {}".format(str(e)))
                    # Try with a different filename
                    destination_path = FOLDER.get_local_dump_folder_file("EmptyMass_Template_{}.rfa".format(int(time.time())))
        
        # Copy file with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                shutil.copy2(source_path, destination_path)
                ERROR_HANDLE.print_note("Template copied to: {}".format(destination_path))
                return destination_path
            except IOError as e:
                if attempt < max_retries - 1:
                    ERROR_HANDLE.print_note("Copy attempt {} failed: {}. Retrying...".format(attempt + 1, str(e)))
                    time.sleep(1)  # Wait a bit before retrying
                else:
                    ERROR_HANDLE.print_note("Failed to copy template after {} attempts: {}".format(max_retries, str(e)))
                    return None


if __name__ == "__main__":
    """Test the TemplateFinder class when run as main module."""
    print("TemplateFinder module - This module provides mass family template management functionality.")
    print("To test this module, run it within a Revit environment with proper document context.")
