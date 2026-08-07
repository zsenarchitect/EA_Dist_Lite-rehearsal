#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Revit Data Module - Handles Revit area data extraction and processing
Supports area schemes for design option comparisons
"""

from Autodesk.Revit import DB # pyright: ignore
import config
from EnneadTab.REVIT import REVIT_SPATIAL_ELEMENT
import geometry_extractor


def get_revit_area_data_by_scheme():
    """
    Extract area data from Revit document organized by area scheme
    Each area scheme acts like a design option and needs separate comparison
    
    Returns:
        dict: Dictionary with scheme names as keys and list of area objects as values
        {
            'area_scheme1': [area_object1, area_object2, ...],
            'area_scheme2': [area_object1, area_object2, ...]
        }
        Each area_object is a dict with: department, program_type, program_type_detail, area_sf
    """
    doc = __revit__.ActiveUIDocument.Document # pyright: ignore
    if not doc:
        raise Exception("No active Revit document found")
    
    # Get all area schemes in the document
    area_schemes = DB.FilteredElementCollector(doc).OfClass(DB.AreaScheme).ToElements()
    
    if not area_schemes:
        print("WARNING: No area schemes found in document")
        # Fallback: get all areas without scheme filtering
        return _get_all_areas_as_list(doc)
    
    scheme_data = {}
    
    for scheme in area_schemes:
        scheme_name = scheme.Name
        
        # Filter schemes based on configuration
        if config.AREA_SCHEMES_TO_PROCESS_PREFIX_KEYWORD and not scheme_name.startswith(config.AREA_SCHEMES_TO_PROCESS_PREFIX_KEYWORD):
            continue
        
        # Get all areas in the document
        all_areas = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Areas).WhereElementIsNotElementType().ToElements()
        
        areas_list = []
        
        for area in all_areas:
            # Check if this area belongs to the current scheme
            area_scheme = area.AreaScheme
            if area_scheme and area_scheme.Id == scheme.Id:
                # Get area value and level first
                area_sf = area.Area
                level = area.Level
                
                # Get the 3 key parameters for proper matching
                try:
                    department = _get_area_parameter_value(area, config.DEPARTMENT_KEY[config.APP_REVIT])
                except Exception as e:
                    department = ""
                
                try:
                    program_type = _get_area_parameter_value(area, config.PROGRAM_TYPE_KEY[config.APP_REVIT])
                except Exception as e:
                    program_type = ""
                
                try:
                    program_type_detail = _get_area_parameter_value(area, config.PROGRAM_TYPE_DETAIL_KEY[config.APP_REVIT])
                except Exception as e:
                    program_type_detail = ""
                
                # Get level name and elevation
                level_name = level.Name if level else "Not Placed"
                level_elevation = level.Elevation if level else 0
                
                # Determine area status using utility function
                area_status = REVIT_SPATIAL_ELEMENT.get_element_status(area)
                
                # Get creator and editor information
                creator_name = _get_element_creator(area, doc)
                editor_name = _get_element_last_editor(area, doc)
                
                # Extract geometry for 3D visualization
                geometry = None
                try:
                    geometry = geometry_extractor.extract_area_geometry(
                        area,
                        department=department,
                        program_type=program_type,
                        program_type_detail=program_type_detail,
                        area_sf=area_sf,
                        color=None  # Will be populated from color scheme later
                    )
                except Exception as e:
                    print("Warning: Failed to extract geometry for area {}: {}".format(area.Id, str(e)))
                
                # Create area object with all parameters plus metadata
                area_object = {
                    'department': department,
                    'program_type': program_type,
                    'program_type_detail': program_type_detail,
                    'area_sf': area_sf,
                    'level_name': level_name,
                    'level_elevation': level_elevation,
                    'area_status': area_status,
                    'creator': creator_name,
                    'last_editor': editor_name,
                    'revit_element': area,  # Store reference to Revit element for parameter updates
                    'geometry': geometry  # Add geometry data for 3D visualization
                }
                
                areas_list.append(area_object)
        
        scheme_data[scheme_name] = areas_list
    

    return scheme_data


def get_revit_area_data():
    """
    Extract area data from Revit document (fallback method for single scheme)
    
    Returns:
        dict: Dictionary of area names and their square footage values
    """
    doc = __revit__.ActiveUIDocument.Document # pyright: ignore
    if not doc:
        raise Exception("No active Revit document found")
    
    # Use BuiltInCategory to filter for Areas
    all_areas = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Areas).WhereElementIsNotElementType().ToElements()
    


    out = {}

    for area in all_areas:
        # Get area value and level first
        area_sf = area.Area
        level = area.Level
        
        # Get the 3 key parameters for proper matching
        department = _get_area_parameter_value(area, config.DEPARTMENT_KEY["revit"])
        program_type = _get_area_parameter_value(area, config.PROGRAM_TYPE_KEY["revit"])
        program_type_detail = _get_area_parameter_value(area, config.PROGRAM_TYPE_DETAIL_KEY["revit"])
        
        # Get level name and elevation
        level_name = level.Name if level else "Not Placed"
        level_elevation = level.Elevation if level else 0
        
        # Determine area status using utility function
        area_status = REVIT_SPATIAL_ELEMENT.get_element_status(area)
        
        # Get creator and editor information
        creator_name = _get_element_creator(area, doc)
        editor_name = _get_element_last_editor(area, doc)
        
        # Create comprehensive area data
        area_data = {
            'department': department,
            'program_type': program_type,
            'program_type_detail': program_type_detail,
            'area_sf': area_sf,
            'level_name': level_name,
            'level_elevation': level_elevation,
            'area_status': area_status,
            'creator': creator_name,
            'last_editor': editor_name
        }
        
        # Use a unique key that includes the 3 parameters for better matching
        unique_key = "{} | {} | {}".format(program_type_detail, department, program_type)
        out[unique_key] = area_data
    

    return out


def get_revit_areas_with_parameters():
    """
    Extract area data with additional parameter information for matching
    
    Returns:
        list: List of area dictionaries with parameter data
    """
    doc = __revit__.ActiveUIDocument.Document # pyright: ignore
    if not doc:
        raise Exception("No active Revit document found")
    
    all_areas = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Areas).WhereElementIsNotElementType().ToElements()
    
    areas = []
    for area in all_areas:
        area_data = {
            'name': area.get_Parameter(DB.BuiltInParameter.ROOM_NAME).AsString() or "Unnamed Area",
            'area_sf': area.get_Parameter(DB.BuiltInParameter.ROOM_AREA).AsDouble(),
            'department': _get_area_parameter_value(area, config.DEPARTMENT_KEY[config.APP_REVIT]),
            'program_type': _get_area_parameter_value(area, config.PROGRAM_TYPE_KEY[config.APP_REVIT]),
            'program_type_detail': _get_area_parameter_value(area, config.PROGRAM_TYPE_DETAIL_KEY[config.APP_REVIT])
        }
        areas.append(area_data)
    
    return areas


def _get_all_areas_as_list(doc):
    """
    Get all areas in the document organized by scheme (fallback when no schemes found)
    Groups areas by their area scheme, or creates a single "Default Scheme" if needed
    
    Args:
        doc: Revit document
        
    Returns:
        dict: Dictionary with scheme names as keys and list of area objects as values
        {
            'scheme_name': [area_object1, area_object2, ...]
        }
    """
    all_areas = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Areas).WhereElementIsNotElementType().ToElements()
    
    # Group areas by their area scheme
    scheme_areas = {}
    
    for area in all_areas:
        # Get area scheme
        area_scheme = area.AreaScheme
        if area_scheme:
            scheme_name = area_scheme.Name
        else:
            scheme_name = "Default Scheme"
        
        # Filter schemes based on configuration
        if config.AREA_SCHEMES_TO_PROCESS_PREFIX_KEYWORD and not scheme_name.startswith(config.AREA_SCHEMES_TO_PROCESS_PREFIX_KEYWORD):
            continue
        
        # Get area value and level first
        area_sf = area.Area
        level = area.Level
        
        # Get the 3 key parameters for proper matching
        department = _get_area_parameter_value(area, config.DEPARTMENT_KEY["revit"])
        program_type = _get_area_parameter_value(area, config.PROGRAM_TYPE_KEY["revit"])
        program_type_detail = _get_area_parameter_value(area, config.PROGRAM_TYPE_DETAIL_KEY["revit"])
        
        # Get level name
        level_name = level.Name if level else "Not Placed"
        
        # Determine area status using utility function
        area_status = REVIT_SPATIAL_ELEMENT.get_element_status(area)
        
        # Get creator and editor information
        creator_name = _get_element_creator(area, doc)
        editor_name = _get_element_last_editor(area, doc)
        
        # Extract geometry for 3D visualization
        geometry = None
        try:
            geometry = geometry_extractor.extract_area_geometry(
                area,
                department=department,
                program_type=program_type,
                program_type_detail=program_type_detail,
                area_sf=area_sf,
                color=None  # Will be populated from color scheme later
            )
        except Exception as e:
            print("Warning: Failed to extract geometry for area {}: {}".format(area.Id, str(e)))
        
        # Create area object with all 3 parameters plus level and metadata
        area_object = {
            'department': department,
            'program_type': program_type,
            'program_type_detail': program_type_detail,
            'area_sf': area_sf,
            'level_name': level_name,
            'area_status': area_status,
            'creator': creator_name,
            'last_editor': editor_name,
            'revit_element': area,  # Store reference to Revit element for parameter updates
            'geometry': geometry  # Add geometry data for 3D visualization
        }
        
        # Add to scheme's list
        if scheme_name not in scheme_areas:
            scheme_areas[scheme_name] = []
        scheme_areas[scheme_name].append(area_object)
    
    return scheme_areas


def _get_area_parameter_value(area, parameter_name):
    """
    Get parameter value from area element by parameter name
    Handles custom parameters only (not area name or area value)
    
    Args:
        area: Revit area element
        parameter_name: Name of the parameter to retrieve
        
    Returns:
        str: Parameter value or empty string if not found
    """

    # Try to get parameter by name (for custom parameters)
    param = area.LookupParameter(parameter_name)
    if param:
        # Try string value first
        if param.StorageType == DB.StorageType.String:
            value = param.AsString() or ""
            return value
        # Try double value for numeric parameters
        elif param.StorageType == DB.StorageType.Double:
            return str(param.AsDouble())
        # Try integer value
        elif param.StorageType == DB.StorageType.Integer:
            return str(param.AsInteger())
        # Fallback for element ID storage
        elif param.StorageType == DB.StorageType.ElementId:
            return ""
    
    # Parameter not found - return empty string
    return ""


def _get_element_creator(element, doc):
    """Get the creator of an element using Revit API"""
    try:
        # Use WorksharingUtils to get element ownership information
        info = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, element.Id)
        if info and info.Creator:
            return info.Creator
        else:
            return "Unknown"
    except:
        return "Unknown"


def _get_element_last_editor(element, doc):
    """Get the last editor of an element using Revit API"""
    try:
        # Use WorksharingUtils to get element ownership information
        info = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, element.Id)
        if info and info.LastChangedBy:
            return info.LastChangedBy
        else:
            return "Unknown"
    except:
        return "Unknown"
