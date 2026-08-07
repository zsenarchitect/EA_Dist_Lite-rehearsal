#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Update Door Info by Room

This tool updates door 'Location' and 'Mark' parameters based on the room they belong to.
It analyzes all phases to find the most appropriate room for each door.

LOGIC:
1. Location:
   - Sets 'Location' parameter to the Room Name.
   - Prioritizes non-corridor rooms.
   - If a door connects two valid rooms, picks the smaller room.
   - Special handling for 'CORRIDOR', 'no room', 'missing room name'.

2. Mark:
   - Sets 'Mark' parameter to Room Number.
   - If multiple doors belong to the same room, appends a suffix (A, B, C...).
   - Doors are sorted by Element ID to ensure consistent suffix assignment.

USAGE:
Click the button to run. A transaction will be committed to update the parameters.
"""
__title__ = "Update Door Info\nby Room"

import proDUCKtion # pyright: ignore 
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, LOG
from EnneadTab.REVIT import REVIT_APPLICATION
from Autodesk.Revit import DB # pyright: ignore 

DOC = REVIT_APPLICATION.get_doc()
from pyrevit import script

# Setup output window
output = script.get_output()
output.close_others()

# Constants
IGNORE_ROOM_NAMES = ["corridor", "hallway", "lobby"]
DOOR_LOCATION_PARAM_NAME = "DoorLocation"
DOOR_NUMBER_PARAM_NAME = "Mark"
ROOM_NAME_PARAM = "Name"
ROOM_NUMBER_PARAM = "Number"
EXISTING_PHASE_NAME = "ExistingCondition"
MISSING_ROOM_NUMBER = "missing room number"
MISSING_ROOM_NAME = "missing room name"
NO_ROOM_DEFAULT = "no room"
NESTING_DOOR_COMMENT = "Nesting Door,No Location"


def get_id_value(element_id):
    """
    Get the integer value of an ElementId.
    Compatible with Revit 2024+ (Value) and older versions (IntegerValue).
    """
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def get_alpha_suffix(n):
    """
    Convert 0-based index to alpha suffix.
    0 -> a, 25 -> z, 26 -> aa, 27 -> ab...
    """
    result = ""
    while True:
        remainder = n % 26
        result = chr(97 + remainder) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result


class RoomInfo(object):
    """Helper class to store room information."""
    def __init__(self, room):
        self.room = room
        self.name = MISSING_ROOM_NAME
        self.number = MISSING_ROOM_NUMBER
        self.area = 0.0
        self.id = DB.ElementId.InvalidElementId

        if room:
            self.id = room.Id
            self.area = room.Area
            self._extract_params()

    def _extract_params(self):
        # Extract Name
        name_param = self.room.LookupParameter(ROOM_NAME_PARAM)
        if name_param:
            self.name = name_param.AsString() or ""
        
        # Extract Number
        number_param = self.room.LookupParameter(ROOM_NUMBER_PARAM)
        if number_param:
            val = number_param.AsString()
            if val:
                self.number = val

    @property
    def is_ignored(self):
        """Check if room should be treated as a corridor/ignored space."""
        # Check partial matches for flexibility (e.g. "Lobby 1", "Main Corridor")
        r_name = self.name.lower()
        for ignored in IGNORE_ROOM_NAMES:
            if ignored in r_name:
                 return True
        return False

    @property
    def is_valid(self):
        """Check if underlying room element exists."""
        return self.room is not None


def get_sorted_phases(doc):
    """Return all phases in the document sorted by name."""
    collector = DB.FilteredElementCollector(doc).OfClass(DB.Phase)
    phases = [doc.GetElement(pid) for pid in collector.ToElementIds()]
    phases.sort(key=lambda x: x.Name)
    return phases


class DoorFilter(object):
    """Filter to process doors and handle shared family caching."""
    def __init__(self):
        self._shared_cache = {}

    def filter(self, doors):
        """Return only valid doors (have room calculation attributes)."""
        valid_doors = []
        for d in doors:
            # Check for necessary attributes first
            if not hasattr(d, "ToRoom") or not hasattr(d, "FromRoom"):
                continue
            valid_doors.append(d)
        return valid_doors

    def is_shared_family(self, family):
        """Check if family is shared using internal cache."""
        if not family:
            return False
            
        fam_id = get_id_value(family.Id)
        
        if fam_id in self._shared_cache:
            return self._shared_cache[fam_id]
            
        is_shared = False
        p_shared = family.get_Parameter(DB.BuiltInParameter.FAMILY_SHARED)
        if p_shared and p_shared.AsInteger() == 1:
            is_shared = True
            
        self._shared_cache[fam_id] = is_shared
        return is_shared


def determine_best_room_for_door(door, phases):
    """
    Analyze a door across phases to find the best associated room.
    Prioritizes NON-IGNORED rooms found in any phase.
    If only IGNORED rooms are found, returns the best one.
    
    Returns:
        RoomInfo_object (or None)
    """
    best_room_info = None
    candidate_ignored_info = None

    # Iterate phases to find a valid room association
    for phase in phases:
        if not door.CreatedPhaseId:
            continue
            
        # Get To/From rooms for this phase
        try:
            to_room = door.ToRoom[phase]
            from_room = door.FromRoom[phase]
        except Exception:
            continue

        to_room_info = RoomInfo(to_room)
        from_room_info = RoomInfo(from_room)

        # Logic to pick the best room from this phase
        better_room_info = pick_better_room(to_room_info, from_room_info)

        if not better_room_info or not better_room_info.is_valid:
            continue
            
        # If we found a valid room logic
        if not better_room_info.is_ignored:
            # We found a "Good" room (not corridor/lobby). This is what we want.
            return better_room_info # FOUND IT!
        else:
            # It's an ignored room (Corridor/Lobby). Keep it as a backup candidate.
            if not candidate_ignored_info:
                candidate_ignored_info = better_room_info

    # If we finished loop and didn't return a "Good" room, see if we have a backup.
    if candidate_ignored_info:
        return candidate_ignored_info

    return best_room_info


def pick_better_room(info_a, info_b):
    """
    Compare two RoomInfo objects and return the preferred RoomInfo.
    
    Priority:
    1. Non-ignored rooms (non-corridors/lobbies).
    2. Smaller area (if both are valid non-corridors).
    3. If one is ignored (corridor), pick the other.
    4. If both are corridors, pick smaller area (or just first one).
    """
    # 1. Handle cases where one or both are missing
    if not info_a.is_valid and not info_b.is_valid:
        return None
    # If one is missing, return the other 
    if not info_a.is_valid:
        return info_b
    if not info_b.is_valid:
        return info_a

    # 2. Both exist. Check for corridors/ignored.
    if info_a.is_ignored and info_b.is_ignored:
        # Both ignored. Pick smaller.
        if info_a.area <= info_b.area:
            return info_a
        else:
            return info_b
            
    if info_a.is_ignored:
        # A is ignored, B is not. Prefer B.
        return info_b
    if info_b.is_ignored:
        # B is ignored, A is not. Prefer A.
        return info_a

    # 3. Both are valid non-corridors. Pick smaller area.
    if info_a.area <= info_b.area:
        return info_a
    else:
        return info_b


class DoorInfo(object):
    """Helper class to store and manage door information."""
    def __init__(self, door, phases, is_shared=False):
        self.door = door
        self.doc = door.Document
        self.is_shared = is_shared
        self.room_info = determine_best_room_for_door(door, phases)
        self.old_mark = self._get_param_value(DOOR_NUMBER_PARAM_NAME)
        self.new_mark = ""
        self.level_name = self._get_level_name()
        self.location_name = self._get_location_name()

    def _get_param_value(self, param_name):
        param = self.door.LookupParameter(param_name)
        return param.AsString() if param else ""

    def _get_level_name(self):
        if self.door.LevelId != DB.ElementId.InvalidElementId:
            level = self.doc.GetElement(self.door.LevelId)
            if level:
                return level.Name
        return "-"

    def _get_location_name(self):
        if self.is_shared:
            return NESTING_DOOR_COMMENT
            
        if self.room_info and self.room_info.is_valid:
            return self.room_info.name
        return NO_ROOM_DEFAULT

    def update_location(self):
        update_parameter(self.door, DOOR_LOCATION_PARAM_NAME, self.location_name)

    def update_mark(self):
        update_parameter(self.door, DOOR_NUMBER_PARAM_NAME, self.new_mark)

    @property
    def id(self):
        return self.door.Id
    
    @property
    def grouping_key(self):
        if self.room_info and self.room_info.id != DB.ElementId.InvalidElementId:
            return get_id_value(self.room_info.id)
        return self.location_name



def update_parameter(element, param_name, value):
    """Helper to safely set a parameter value."""
    param = element.LookupParameter(param_name)
    if not param:
        return False
    # If the user has a read-only parameter or other issue, this might fail silently or throw.
    # We'll just try strict set.
    try:
        param.Set(value)
        return True
    except Exception:
        return False


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main(doc):
    
    phases = get_sorted_phases(doc)
    if not phases:
        ERROR_HANDLE.print_note("No phases found in document.")
        return

    # Collect all doors
    all_doors = DB.FilteredElementCollector(doc)\
                  .OfCategory(DB.BuiltInCategory.OST_Doors)\
                  .WhereElementIsNotElementType()\
                  .ToElements()
    
    # Filter using DoorFilter class
    door_filter = DoorFilter()
    all_doors = door_filter.filter(all_doors)
    
    if not all_doors:
        output.print_md("## No doors found in the project.")
        return

    output.print_md("## Processing {} doors...".format(len(all_doors)))
    output.print_md("---")

    # We will process in two passes:
    # 1. Determine location for every entry (DoorInfo).
    # 2. Group by room to assign marks.

    door_infos = [] 

    transaction = DB.Transaction(doc, __title__)
    transaction.Start()

    # --- PASS 1: Determine Locations ---
    for door in all_doors:
        # Skip existing phase doors if necessary, matching original logic
        created_phase_id = door.CreatedPhaseId
        created_phase = doc.GetElement(created_phase_id)
        if created_phase and created_phase.Name == EXISTING_PHASE_NAME:
            continue

        try:
            is_shared = door_filter.is_shared_family(door.Symbol.Family)
        except Exception:
            is_shared = False

        door_info = DoorInfo(door, phases, is_shared=is_shared)
        
        # Update Location Parameter immediately
        door_info.update_location()
        
        door_infos.append(door_info)

    # --- PASS 2: Assign Marks ---
    # Group by Room ID (or location string if no room)
    grouped_doors = {}

    for info in door_infos:
        key = info.grouping_key
        if key not in grouped_doors:
            grouped_doors[key] = []
        grouped_doors[key].append(info)

    # Process each group
    table_data = []
    
    for key, infos in grouped_doors.items():
        # Sort by Door Element ID to ensure stability
        infos.sort(key=lambda x: get_id_value(x.id))
        
        # Determine base mark (Room Number)
        first_info = infos[0]
        room_info = first_info.room_info
        
        # Use Room Number for the Mark
        if room_info and room_info.is_valid:
             base_mark = room_info.number
        else:
             base_mark = first_info.location_name

        # Apply marks
        count = len(infos)
        for i, info in enumerate(infos):
            if count == 1:
                info.new_mark = base_mark
            else:
                # Append a, b, c... (or aa, ab...)
                suffix = get_alpha_suffix(i)
                info.new_mark = "{}.{}".format(base_mark, suffix)
            
            info.update_mark()
            table_data.append([info.id, info.level_name, info.location_name, info.old_mark, info.new_mark])
    
    transaction.Commit()
    
    # Sort table by Level Name
    table_data.sort(key=lambda x: x[1])

    # Print table
    if table_data:
        output.print_table(
            table_data=table_data,
            columns=["Door ID", "Level", "Location", "Old Numbering", "New Numbering"],
            formats=["", "", "", "", ""] # optional
        )
    
    output.print_md("## \n\nDone! Processed {} doors.".format(len(door_infos)))


if __name__ == "__main__":
    main(DOC)
