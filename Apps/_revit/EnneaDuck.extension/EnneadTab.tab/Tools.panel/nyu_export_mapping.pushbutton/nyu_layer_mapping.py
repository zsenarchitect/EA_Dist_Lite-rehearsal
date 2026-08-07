#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
NYU CAD Layer Standards Mapping
Maps Revit BuiltInCategory constants to NYU CAD layer standards.
Based on official NYU CAD Layer Standards table.

Revit API Reference: https://www.revitapidocs.com/2026/ba1c5b30-242f-5fdc-8ea9-ec3b61e6e722.htm
"""

import traceback
from Autodesk.Revit import DB # pyright: ignore

def validate_builtin_category(constant_name):
    """Test if a BuiltInCategory constant exists and is valid"""
    try:
        # Try to get the constant from DB.BuiltInCategory
        constant = getattr(DB.BuiltInCategory, constant_name)
        # Test if it's a valid BuiltInCategory enum value
        if isinstance(constant, DB.BuiltInCategory):
            return True, constant
        else:
            return False, None
    except AttributeError:
        return False, None

def show_all_available_ost_constants():
    """Display all available OST_ constants from BuiltInCategory"""
    print("=== All Available OST_ Constants ===")
    available_constants = []
    
    for attr in dir(DB.BuiltInCategory):
        if attr.startswith('OST_'):
            try:
                constant = getattr(DB.BuiltInCategory, attr)
                if isinstance(constant, DB.BuiltInCategory):
                    available_constants.append(attr)
                    print("✓ {}".format(attr))
            except:
                pass
    
    print("\n=== Summary ===")
    print("Total available OST_ constants: {}".format(len(available_constants)))
    return available_constants

def build_nyu_layer_mapping():
    """Dynamically build the NYU layer mapping, testing each constant"""
    
    # Raw mapping data - all potential entries (removed the 6 failed constants)
    raw_mapping_data = {
        # Architectural Elements
        "Walls/Interior": {"constant": "OST_Walls", "dwg_layer": "A-WALL-INTR", "color": 3},
        "Walls/Exterior": {"constant": "OST_Walls", "dwg_layer": "A-WALL-EXTR", "color": 5},
        "Doors": {"constant": "OST_Doors", "dwg_layer": "A-DOOR", "color": 1},
        "Door Identification": {"constant": "OST_Doors", "dwg_layer": "A-DOOR-IDEN", "color": 4},
        "Windows": {"constant": "OST_Windows", "dwg_layer": "A-WNDW", "color": 4},
        "Floors": {"constant": "OST_Floors", "dwg_layer": "A-FLOR", "color": 2},
        "Floor - Elevator": {"constant": "OST_Floors", "dwg_layer": "A-FLOR-EVTR", "color": 2},
        "Floor - Grating": {"constant": "OST_Floors", "dwg_layer": "A-FLOR-GRATE", "color": 2},
        "Floor - Shaft": {"constant": "OST_Floors", "dwg_layer": "A-FLOR-SHFT", "color": 2},
        "Floor - Stairs": {"constant": "OST_Stairs", "dwg_layer": "A-FLOR-STRS", "color": 2},
        "Ceilings": {"constant": "OST_Ceilings", "dwg_layer": "A-CLNG", "color": 2},
        "Roofs": {"constant": "OST_Roofs", "dwg_layer": "A-ROOF", "color": 1},
        "Curbs": {"constant": "OST_GenericModel", "dwg_layer": "A-CURB", "color": 2},
        "Signage": {"constant": "OST_GenericModel", "dwg_layer": "A-FLOR-SIGN", "color": 1},
        "Room Numbers": {"constant": "OST_Rooms", "dwg_layer": "A-FLOR-IDEN-ROOM", "color": 7},
        "Room Names": {"constant": "OST_Rooms", "dwg_layer": "A-FLOR-IDEN-TEXT", "color": 7},
        "Pre-EPIC Room Numbers": {"constant": "OST_Rooms", "dwg_layer": "A-FLOR-IDEN-PRE-EPIC", "color": 7},
        
        # Structural Elements
        "Structural Columns": {"constant": "OST_StructuralColumns", "dwg_layer": "S-COLS", "color": 2},
        "Grids": {"constant": "OST_Grids", "dwg_layer": "S-GRID", "color": 2},
        
        # Electrical Elements
        "Lighting Fixtures": {"constant": "OST_LightingFixtures", "dwg_layer": "E-LITE", "color": 3},
        "Lighting Devices": {"constant": "OST_LightingDevices", "dwg_layer": "E-LITE", "color": 3},
        "Exit Lighting": {"constant": "OST_LightingFixtures", "dwg_layer": "E-LITE-EXIT", "color": 3},
        "Electrical Equipment": {"constant": "OST_ElectricalEquipment", "dwg_layer": "E-POWR-WALL", "color": 3},
        "Electrical Fixtures": {"constant": "OST_ElectricalFixtures", "dwg_layer": "E-POWR-WALL", "color": 3},
        "Security Devices": {"constant": "OST_SecurityDevices", "dwg_layer": "E-SAFETY-CRDRDR", "color": 3},
        "Communication Devices": {"constant": "OST_CommunicationDevices", "dwg_layer": "E-SAFETY-ICDB", "color": 3},
        
        # Mechanical Elements
        "Mechanical Equipment": {"constant": "OST_MechanicalEquipment", "dwg_layer": "M-HVAC-EQPM", "color": 6},
        "Duct Curves": {"constant": "OST_DuctCurves", "dwg_layer": "M-HVAC-EQPM", "color": 6},
        "Duct Fitting": {"constant": "OST_DuctFitting", "dwg_layer": "M-HVAC-EQPM", "color": 6},
        "Duct Accessory": {"constant": "OST_DuctAccessory", "dwg_layer": "M-HVAC-EQPM", "color": 6},
        "Mechanical Control Devices": {"constant": "OST_MechanicalControlDevices", "dwg_layer": "M-HVAC-EQPM", "color": 6},
        "Zone Equipment": {"constant": "OST_ZoneEquipment", "dwg_layer": "M-HVAC-EQPM", "color": 6},
        
        # Plumbing Elements
        "Plumbing Fixtures": {"constant": "OST_PlumbingFixtures", "dwg_layer": "P-FIXT", "color": 6},
        "Plumbing Equipment": {"constant": "OST_PlumbingEquipment", "dwg_layer": "P-FIXT", "color": 6},
        "Pipe Curves": {"constant": "OST_PipeCurves", "dwg_layer": "P-FIXT", "color": 6},
        "Pipe Fitting": {"constant": "OST_PipeFitting", "dwg_layer": "P-FIXT", "color": 6},
        "Pipe Accessory": {"constant": "OST_PipeAccessory", "dwg_layer": "P-FIXT", "color": 6},
        "Sprinklers": {"constant": "OST_Sprinklers", "dwg_layer": "P-SAFETY-SHWSH", "color": 6},
        
        # Interior Elements
        "Furniture": {"constant": "OST_Furniture", "dwg_layer": "I-FURN", "color": 6},
        "Furniture Systems": {"constant": "OST_FurnitureSystems", "dwg_layer": "I-FURN", "color": 6},
        "Casework": {"constant": "OST_Casework", "dwg_layer": "I-MILLWORK", "color": 6},
        "Medical Equipment": {"constant": "OST_MedicalEquipment", "dwg_layer": "I-EQPM-FIX", "color": 6},
        "Food Service Equipment": {"constant": "OST_FoodServiceEquipment", "dwg_layer": "I-EQPM-FIX", "color": 6},
        "Nurse Call Devices": {"constant": "OST_NurseCallDevices", "dwg_layer": "I-EQPM-FIX", "color": 6},
        
        # Site/Landscaping Elements
        "Site": {"constant": "OST_Site", "dwg_layer": "L-SITE", "color": 4},
        "Planting": {"constant": "OST_Planting", "dwg_layer": "L-SITE", "color": 4},
        "Hardscape": {"constant": "OST_Hardscape", "dwg_layer": "L-SITE", "color": 4},
        "Roads": {"constant": "OST_Roads", "dwg_layer": "L-SITE", "color": 4},
        "Parking": {"constant": "OST_Parking", "dwg_layer": "L-SITE", "color": 4},
        
        # General/Annotation Elements
        "Generic Model": {"constant": "OST_GenericModel", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Detail Items": {"constant": "OST_DetailComponents", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Generic Annotation": {"constant": "OST_GenericAnnotation", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Title Blocks": {"constant": "OST_TitleBlocks", "dwg_layer": "G-ANNO-TTLB", "color": 7},
        "Title Block Text": {"constant": "OST_TitleBlocks", "dwg_layer": "G-ANNO-TTLB-TEXT", "color": 7},
        "Logo": {"constant": "OST_TitleBlocks", "dwg_layer": "G-LOGO", "color": 7},
        "Scale": {"constant": "OST_GenericAnnotation", "dwg_layer": "G-SCALE", "color": 7},
        "Viewports": {"constant": "OST_Viewports", "dwg_layer": "G-VP", "color": 7},
        "Levels": {"constant": "OST_Levels", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Sections": {"constant": "OST_Sections", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Elevation Marks": {"constant": "OST_ElevationMarks", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Callout Heads": {"constant": "OST_CalloutHeads", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Defpoints": {"constant": "OST_Lines", "dwg_layer": "DEFPOINTS", "color": 7},
        
        # Telecomm Elements
        "Telephone Devices": {"constant": "OST_TelephoneDevices", "dwg_layer": "T-JACK", "color": 3},
        "Data Devices": {"constant": "OST_DataDevices", "dwg_layer": "T-JACK", "color": 3},
        # Architectural (single key for Revit Category.Name lookup)
        "Walls": {"constant": "OST_Walls", "dwg_layer": "A-WALL-EXTR", "color": 5},
        "Columns": {"constant": "OST_Columns", "dwg_layer": "A-FLOR", "color": 2},
        "Railings": {"constant": "OST_Railings", "dwg_layer": "A-FLOR-STRS", "color": 2},
        "Ramps": {"constant": "OST_Ramps", "dwg_layer": "A-FLOR-STRS", "color": 2},
        "Stairs": {"constant": "OST_Stairs", "dwg_layer": "A-FLOR-STRS", "color": 2},
        "Curtain Panels": {"constant": "OST_CurtainWallPanels", "dwg_layer": "A-WNDW", "color": 4},
        "Curtain Systems": {"constant": "OST_CurtainSystems", "dwg_layer": "A-WNDW", "color": 4},
        "Curtain Wall Mullions": {"constant": "OST_CurtainWallMullions", "dwg_layer": "A-WNDW", "color": 4},
        "Mass": {"constant": "OST_Mass", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Topography": {"constant": "OST_Topography", "dwg_layer": "L-SITE", "color": 4},
        "Toposolid": {"constant": "OST_Toposolid", "dwg_layer": "L-SITE", "color": 4},
        "Entourage": {"constant": "OST_Entourage", "dwg_layer": "I-FURN", "color": 6},
        "Spaces": {"constant": "OST_Spaces", "dwg_layer": "M-HVAC-EQPM", "color": 6},
        "Conduits": {"constant": "OST_Conduit", "dwg_layer": "E-POWR-WALL", "color": 3},
        "Cable Trays": {"constant": "OST_CableTray", "dwg_layer": "E-POWR-WALL", "color": 3},
        "Wires": {"constant": "OST_Wire", "dwg_layer": "E-POWR-WALL", "color": 3},
        "Duct Insulations": {"constant": "OST_DuctInsulations", "dwg_layer": "M-HVAC-EQPM", "color": 6},
        "Pipe Insulations": {"constant": "OST_PipeInsulations", "dwg_layer": "P-FIXT", "color": 6},
        "Flex Ducts": {"constant": "OST_FlexDuctCurves", "dwg_layer": "M-HVAC-EQPM", "color": 6},
        "Flex Pipes": {"constant": "OST_FlexPipeCurves", "dwg_layer": "P-FIXT", "color": 6},
        "Structural Framing": {"constant": "OST_StructuralFraming", "dwg_layer": "S-COLS", "color": 2},
        "Structural Foundations": {"constant": "OST_StructuralFoundation", "dwg_layer": "S-COLS", "color": 2},
        "Areas": {"constant": "OST_Areas", "dwg_layer": "A-FLOR-IDEN-ROOM", "color": 7},
        "Parts": {"constant": "OST_Parts", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        # Annotation / tags -> G-ANNO-SYMB or G-ANNO-TEXT per RED+F
        "Door Tags": {"constant": "OST_DoorTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Wall Tags": {"constant": "OST_WallTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Window Tags": {"constant": "OST_WindowTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Room Tags": {"constant": "OST_RoomTags", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Area Tags": {"constant": "OST_AreaTags", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Ceiling Tags": {"constant": "OST_CeilingTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Floor Tags": {"constant": "OST_FloorTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Roof Tags": {"constant": "OST_RoofTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Column Tags": {"constant": "OST_ColumnTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Grid Heads": {"constant": "OST_GridHeads", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Level": {"constant": "OST_Levels", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Level Heads": {"constant": "OST_LevelHeads", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Elevations": {"constant": "OST_ElevationMarks", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Sections": {"constant": "OST_Sections", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Callouts": {"constant": "OST_CalloutHeads", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Detail Item Tags": {"constant": "OST_DetailComponentTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Generic Model Tags": {"constant": "OST_GenericModelTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Text Notes": {"constant": "OST_TextNotes", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Dimensions": {"constant": "OST_Dimensions", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Spot Elevations": {"constant": "OST_SpotElevations", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Spot Coordinates": {"constant": "OST_SpotCoordinates", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Spot Slopes": {"constant": "OST_SpotSlopes", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Keynote Tags": {"constant": "OST_KeynoteTags", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Revision Clouds": {"constant": "OST_RevisionClouds", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Raster Images": {"constant": "OST_RasterImages", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Reference Planes": {"constant": "OST_CLines", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Reference Lines": {"constant": "OST_Lines", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "View Titles": {"constant": "OST_ViewTitles", "dwg_layer": "G-ANNO-TEXT", "color": 7},
        "Furniture Tags": {"constant": "OST_FurnitureTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Furniture System Tags": {"constant": "OST_FurnitureSystemTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Casework Tags": {"constant": "OST_CaseworkTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Railing Tags": {"constant": "OST_RailingTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Stair Tags": {"constant": "OST_StairTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Site Tags": {"constant": "OST_SiteTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Planting Tags": {"constant": "OST_PlantingTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
        "Multi-Category Tags": {"constant": "OST_MultiCategoryTags", "dwg_layer": "G-ANNO-SYMB", "color": 7},
    }
    
    # Test each constant and build the final mapping
    valid_mapping = {}
    failed_constants = []
    
    print("=== Testing BuiltInCategory Constants ===")
    
    for human_name, data in raw_mapping_data.items():
        constant_name = data["constant"]
        try:
            is_valid, constant = validate_builtin_category(constant_name)
            
            if is_valid:
                valid_mapping[human_name] = {
                    "OST": constant,
                    "dwg_layer": data["dwg_layer"],
                    "color": data["color"]
                }
                print("✓ {} -> {}".format(human_name, constant_name))
            else:
                failed_constants.append((human_name, constant_name))
                print("✗ {} -> {} (FAILED)".format(human_name, constant_name))
        except Exception as e:
            failed_constants.append((human_name, constant_name))
            print("✗ {} -> {} (ERROR: {})".format(human_name, constant_name, str(e)))
    
    print("\n=== Summary ===")
    print("Valid constants: {}".format(len(valid_mapping)))
    print("Failed constants: {}".format(len(failed_constants)))
    
    if failed_constants:
        print("\n=== Failed Constants to Eliminate ===")
        for human_name, constant_name in failed_constants:
            print("'{}': '{}',".format(human_name, constant_name))
    
    # Add default fallback
    valid_mapping["DEFAULT"] = {
        "OST": None,
        "dwg_layer": "G-ANNO-TEXT",
        "color": 7
    }
    
    return valid_mapping

# Try to build the mapping dynamically, with detailed error handling
try:
    print("=== Starting NYU Layer Mapping Initialization ===")
    NYU_LAYER_MAPPING = build_nyu_layer_mapping()
    print("=== NYU Layer Mapping Initialization Completed Successfully ===")
except Exception as e:
    print("=== ERROR: Failed to initialize NYU_LAYER_MAPPING ===")
    print("Error Type: {}".format(type(e).__name__))
    print("Error Message: {}".format(str(e)))
    print("\n=== Full Traceback ===")
    print(traceback.format_exc())
    print("\n")
    show_all_available_ost_constants()
    
    # Create a minimal fallback mapping
    NYU_LAYER_MAPPING = {
        "DEFAULT": {
            "OST": None,
            "dwg_layer": None,
            "color": 7
        }
    }

def get_nyu_layer_info(category_name):
    """Get NYU layer information for a given category name or BuiltInCategory"""
    # If category_name is a BuiltInCategory, find the mapping by OST value
    if hasattr(category_name, 'IntegerValue'):
        # It's a BuiltInCategory enum
        for human_name, mapping_info in NYU_LAYER_MAPPING.items():
            if mapping_info.get("OST") == category_name:
                return mapping_info
        return NYU_LAYER_MAPPING["DEFAULT"]
    
    # If category_name is a string, try to find by human name
    return NYU_LAYER_MAPPING.get(category_name, NYU_LAYER_MAPPING["DEFAULT"])


if __name__ == "__main__":
    pass
