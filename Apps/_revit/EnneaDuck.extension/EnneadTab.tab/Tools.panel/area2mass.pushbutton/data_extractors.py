#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Data extraction classes for Area2Mass conversion."""

from Autodesk.Revit import DB # pyright: ignore 
from EnneadTab import ERROR_HANDLE
from EnneadTab.REVIT import REVIT_APPLICATION

# Global constants for mass family naming
MASS_FAMILY_PREFIX = "Space2Mass_"


class ElementInfoExtractor:
    """Extracts and validates element information."""
    
    def __init__(self, spatial_element, element_type):
        self.spatial_element = spatial_element
        self.element_type = element_type
        self.name = None
        self.department = None
        self.is_valid_flag = False
        self._extract_info()
    
    def _extract_info(self):
        """Extract element information and return as dictionary."""
        # For Areas and Rooms, try to get Department parameter
        if self.element_type in ["Area", "Room"]:
            self.department = self._extract_department_info()
        
        # Get name directly from Name lookup parameter - no fallbacks or modifications
        name_param = self.spatial_element.LookupParameter("Name")
        if name_param and name_param.AsString():
            name = name_param.AsString()
        else:
            name = None
        
        # Get level information
        level = self._get_level_info()
        
        # Return dictionary with requested fields
        return {
            'name': name,
            'department': self.department,
            'element_type': self.element_type,
            'level': level,
            'error': None,
            'item': self.spatial_element
        }
    
    def _extract_department_info(self):
        """Extract department information from Area/Room parameters."""
        # Only look for the two specific department parameters provided
        department_params = [
            "Department",
            "Area_$Department"
        ]
        
        for param_name in department_params:
            param = self.spatial_element.LookupParameter(param_name)
            if param and param.AsString():
                department_value = param.AsString().strip()
                if department_value:
                    return department_value
        
        return None
    
    def _sanitize_family_name(self, name):
        """Sanitize name for use as Revit family name."""
        # Remove or replace invalid characters
        invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in invalid_chars:
            name = name.replace(char, '_')
        
        # Limit length (accounting for prefix)
        max_name_length = 50 - len(MASS_FAMILY_PREFIX)
        if len(name) > max_name_length:
            name = name[:max_name_length]
        
        # Ensure it's not empty
        if not name.strip():
            name = "Unnamed"
        
        # Add the global prefix
        final_name = MASS_FAMILY_PREFIX + name.strip()
        
        return final_name
    
    def is_valid(self):
        return self.is_valid_flag and self.name is not None
    
    def get_department(self):
        """Get the extracted department information."""
        return self.department
    
    def _get_level_info(self):
        """Extract level information from the spatial element."""
        # Try to get level from the spatial element
        if hasattr(self.spatial_element, 'Level'):
            level = self.spatial_element.Level
            if level:
                level_id = REVIT_APPLICATION.get_element_id_value(level.Id)
                return {
                    'name': level.Name,
                    'id': level_id,
                    'elevation': level.Elevation
                }
        

        return None


class BoundaryDataExtractor:
    """Extracts boundary data from spatial elements."""
    
    def __init__(self, spatial_element):
        self.spatial_element = spatial_element
        self.segments = None
        self.is_valid_flag = False
        self._extract_boundaries()
    
    def _extract_boundaries(self):
        """Extract boundary segments."""
        options = DB.SpatialElementBoundaryOptions()
        self.segments = self.spatial_element.GetBoundarySegments(options)
        
        self.is_valid_flag = self.segments is not None and len(self.segments) > 0
        

    
    def is_valid(self):
        return self.is_valid_flag


if __name__ == "__main__":
    """Test the data extraction classes when run as main module."""
    print("DataExtractors module - This module provides element and boundary data extraction functionality.")
    print("To test this module, run it within a Revit environment with proper document context.")
