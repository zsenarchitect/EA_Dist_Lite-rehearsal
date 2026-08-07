#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = "Assign panel type based on side frame width mapping."
__title__ = "Assign Panel Type"

import proDUCKtion # pyright: ignore 
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, LOG
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_VIEW
from Autodesk.Revit import DB # pyright: ignore 
from pyrevit import script

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()
output = script.get_output()

# Static mappings for side_frame_w to PanelType based on family type
# Note: 100 is not a valid mapping - removed to prevent invalid assignments
# Tower panels use TA/TB/TC naming convention
TOWER_MAIN_MAPPING = {
    400: "TA",
    600: "TB",
    800: "TC"
}

# Podium panels use PA/PB/PC/PD/PE naming convention
PODIUM_MAIN_MAPPING = {
    700: "PA",
    800: "PB",
    900: "PC",
    1000: "PD",
    1100: "PE"
}


def get_family_type(element):
    """Get the family type name from element."""
    try:
        if hasattr(element, 'Symbol') and element.Symbol:
            return element.Symbol.FamilyName
        elif hasattr(element, 'Family') and element.Family:
            return element.Family.Name
        return "Unknown"
    except:
        return "Unknown"


def get_panel_type_from_width(side_frame_width, family_name):
    """Get panel type based on side frame width and family type."""
    if "tower_main" in family_name.lower():
        return TOWER_MAIN_MAPPING.get(side_frame_width, "BAD")
    elif "tower_ground_main" in family_name.lower():
        return TOWER_MAIN_MAPPING.get(side_frame_width, "BAD")
    elif "podium_main" in family_name.lower():
        return PODIUM_MAIN_MAPPING.get(side_frame_width, "BAD")
    else:
        return "BAD"


def create_mapping_legend(doc):
    """Create mapping legend in 'Mapping' view with text notes using EnneadTab."""
    
    # Find or create the "Mapping" view using EnneadTab
    view = REVIT_VIEW.get_view_by_name("Mapping", doc)
    
    if view is None:
        print("Creating 'Mapping' view...")
        # Use first available view if Mapping view doesn't exist
        collector = DB.FilteredElementCollector(doc)
        views = collector.OfClass(DB.View).ToElements()
        if views:
            view = views[0]
            print("Using first available view: {}".format(view.Name))
        else:
            print("No views found in document")
            return
    
    print("Using view: {}".format(view.Name))
    
    # Start transaction using EnneadTab
    t = DB.Transaction(doc, "Create Mapping Legend")
    t.Start()
    
    try:
        # Get text note type using standard Revit API
        text_note_type = None
        for text_type in DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).ToElements():
            text_note_type = text_type
            break
        
        if text_note_type is None:
            print("No text note type found")
            t.RollBack()
            return
        
        # Create text notes for Tower Main mapping with improved formatting
        print("Creating Tower Main mapping legend...")
        tower_x = 0
        tower_y = 0
        tower_text = "TOWER PANEL TYPE:\n"
        # Sort by panel type (TA, TB, TC)
        sorted_tower_items = sorted(TOWER_MAIN_MAPPING.items(), key=lambda x: x[1])
        for side_frame_w, panel_type in sorted_tower_items:
            tower_text += "{}: {} mm\n".format(panel_type, side_frame_w)
        
        # Create text note for Tower Main
        tower_point = DB.XYZ(tower_x, tower_y, 0)
        tower_text_note = DB.TextNote.Create(doc, view.Id, tower_point, tower_text, text_note_type.Id)
        
        # Create text notes for Podium Main mapping with improved formatting
        print("Creating Podium Main mapping legend...")
        podium_x = 50  # Offset to the right
        podium_y = 0
        podium_text = "PODIUM PANEL TYPE:\n"
        # Sort by panel type (PA, PB, PC, PD, PE)
        sorted_podium_items = sorted(PODIUM_MAIN_MAPPING.items(), key=lambda x: x[1])
        for side_frame_w, panel_type in sorted_podium_items:
            podium_text += "{}: {} mm\n".format(panel_type, side_frame_w)
        
        # Create text note for Podium Main
        podium_point = DB.XYZ(podium_x, podium_y, 0)
        podium_text_note = DB.TextNote.Create(doc, view.Id, podium_point, podium_text, text_note_type.Id)
        
        print("Mapping legend created successfully!")
        print("Tower Main legend at: ({}, {})".format(tower_x, tower_y))
        print("Podium Main legend at: ({}, {})".format(podium_x, podium_y))
        
    except Exception as e:
        print("Error creating mapping legend: {}".format(e))
        t.RollBack()
        return
    
    t.Commit()


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def assign_panel_type(doc):
    """Assign panel type based on side frame width mapping for all tower_main, tower_ground_main, and podium_main panels."""
    
    # Get all family instances using standard Revit API
    collector = DB.FilteredElementCollector(doc)
    all_elements = collector.OfClass(DB.FamilyInstance).ToElements()
    
    # Filter for tower_main, tower_ground_main, and podium_main families
    target_panels = []
    for element in all_elements:
        family_name = get_family_type(element)
        if "tower_main" in family_name.lower() or "tower_ground_main" in family_name.lower() or "podium_main" in family_name.lower():
            target_panels.append(element)
    
    if not target_panels:
        print("No tower_main, tower_ground_main, or podium_main panels found in the document.")
        return
    
    print("Found {} panels to process...".format(len(target_panels)))
    
    t = DB.Transaction(doc, __title__)
    t.Start()
    
    processed_count = 0
    error_count = 0
    unique_side_frame_values = set()
    mapped_values = set()
    bad_values = set()
    bad_mappings_by_family = {}  # {side_frame_w: family_name}
    used_tower_mappings = set()
    used_podium_mappings = set()
    problematic_panels = []  # Track panels with problematic side_frame_w values
    
    for element in target_panels:
        # Get side_frame_w parameter as string
        side_frame_param = element.LookupParameter("side_frame_w")
        side_frame_str = "N/A"  # Default value for display
        
        if side_frame_param is None:
            panel_type = "BAD"
        else:
            # Get side_frame_w as string value using AsValueString()
            side_frame_str = side_frame_param.AsValueString()
            if not side_frame_str or side_frame_str == "":
                panel_type = "BAD"
            else:
                # Convert string to int for mapping - let ERROR_HANDLE catch any conversion errors
                side_frame_width = int(float(side_frame_str))
                unique_side_frame_values.add(side_frame_width)
                family_name = get_family_type(element)
                panel_type = get_panel_type_from_width(side_frame_width, family_name)
                
                # Track mapping status
                if panel_type == "BAD":
                    bad_values.add(side_frame_width)
                    bad_mappings_by_family[side_frame_width] = family_name
                    # Track problematic panels for debugging
                    problematic_panels.append({
                        'element': element,
                        'side_frame_w': side_frame_width,
                        'family_name': family_name,
                        'panel_type': panel_type
                    })
                else:
                    mapped_values.add(side_frame_width)
                    # Track which mappings are actually used
                    if "tower_main" in family_name.lower() or "tower_ground_main" in family_name.lower():
                        used_tower_mappings.add(side_frame_width)
                    elif "podium_main" in family_name.lower():
                        used_podium_mappings.add(side_frame_width)
        
        # Set PanelType parameter
        panel_type_param = element.LookupParameter("PanelType")
        if panel_type_param is None:
            error_count += 1
            continue
        
        panel_type_param.Set(panel_type)
        processed_count += 1
    
    t.Commit()
    print("\n" + "="*60)
    print("PANEL TYPE ASSIGNMENT SUMMARY")
    print("="*60)
    print("Total panels processed: {}".format(len(target_panels)))
    print("Successfully processed: {}".format(processed_count))
    print("Errors encountered: {}".format(error_count))
    
    # Summary of mappings
    print("\nMAPPING STATUS:")
    print("Mapped values: {}".format(len(mapped_values)))
    print("Bad mappings: {}".format(len(bad_values)))
    
    # Bad mappings by family
    if bad_values:
        print("\nBAD MAPPINGS BY FAMILY:")
        tower_bad = [v for v in bad_values if bad_mappings_by_family.get(v, "").lower().find("tower_main") != -1 or bad_mappings_by_family.get(v, "").lower().find("tower_ground_main") != -1]
        podium_bad = [v for v in bad_values if bad_mappings_by_family.get(v, "").lower().find("podium_main") != -1]
        other_bad = [v for v in bad_values if v not in tower_bad and v not in podium_bad]
        
        if tower_bad:
            print("  Tower Main (includes ground): {}".format(sorted(tower_bad)))
        if podium_bad:
            print("  Podium Main: {}".format(sorted(podium_bad)))
        if other_bad:
            print("  Other families: {}".format(sorted(other_bad)))
    
    # Display problematic panels with clickable links
    if problematic_panels:
        print("\n" + "="*60)
        print("PROBLEMATIC PANELS WITH INVALID MAPPINGS:")
        print("="*60)
        for i, panel_info in enumerate(problematic_panels, 1):
            element = panel_info['element']
            side_frame_w = panel_info['side_frame_w']
            family_name = panel_info['family_name']
            
            # Create clickable link to the panel
            panel_link = output.linkify(element.Id, title="Panel {}".format(i))
            print("{} - side_frame_w: {}, family: {}, panel: {}".format(
                i, side_frame_w, family_name, panel_link))
        
        print("\nTotal problematic panels: {}".format(len(problematic_panels)))
        print("Click on the panel links above to navigate to them in Revit")
    
    # All unique values found
    if unique_side_frame_values:
        print("\nALL UNIQUE SIDE_FRAME_W VALUES:")
        sorted_values = sorted(unique_side_frame_values)
        for value in sorted_values:
            if value in mapped_values:
                print("  {} -> MAPPED".format(value))
            elif value in bad_values:
                family_name = bad_mappings_by_family.get(value, "Unknown")
                print("  {} -> BAD (no mapping for {})".format(value, family_name))
            else:
                print("  {} -> UNKNOWN".format(value))
    
    # Unused mappings by family
    print("\nUNUSED MAPPINGS BY FAMILY:")
    
    # Tower Main unused mappings
    all_tower_keys = set(TOWER_MAIN_MAPPING.keys())
    unused_tower = all_tower_keys - used_tower_mappings
    if unused_tower:
        print("  Tower Main unused: {}".format(sorted(unused_tower)))
    else:
        print("  Tower Main: All mappings used")
    
    # Podium Main unused mappings
    all_podium_keys = set(PODIUM_MAIN_MAPPING.keys())
    unused_podium = all_podium_keys - used_podium_mappings
    if unused_podium:
        print("  Podium Main unused: {}".format(sorted(unused_podium)))
    else:
        print("  Podium Main: All mappings used")
    
    print("="*60)
    
    # Create mapping legend
    print("\nCreating mapping legend...")
    create_mapping_legend(doc)



################## main code below #####################
if __name__ == "__main__":
    assign_panel_type(DOC)







