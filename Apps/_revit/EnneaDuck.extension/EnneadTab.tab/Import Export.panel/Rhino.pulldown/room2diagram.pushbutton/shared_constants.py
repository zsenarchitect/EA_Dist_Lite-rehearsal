#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Shared constants for room2diagram export.
"""

from Autodesk.Revit import DB # pyright: ignore


class ElementType:
    """Enum-like class for element types."""
    ROOMS = "Rooms"
    AREAS = "Areas"
    
    @classmethod
    def get_built_in_category(cls, element_type):
        """Get the corresponding BuiltInCategory for the element type."""
        if element_type == cls.ROOMS:
            return DB.BuiltInCategory.OST_Rooms
        elif element_type == cls.AREAS:
            return DB.BuiltInCategory.OST_Areas
        else:
            raise ValueError("Unsupported element type: {}".format(element_type))


class ExportMethod:
    """Enum-like class for export methods."""
    RHINO = "Rhino"
    REVIT = "Revit"


if __name__ == "__main__":
    pass

    
