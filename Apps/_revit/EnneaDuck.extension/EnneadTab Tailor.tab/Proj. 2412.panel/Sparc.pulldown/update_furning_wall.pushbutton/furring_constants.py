from Autodesk.Revit import DB  # pyright: ignore

TARGET_PANEL_FAMILIES = [
    ("EA_CW-1 (Tower)", "Flat"),
    ("EA_CW-1 (TowerReturn)", "SD"),
    ("EA_CW-2 (Plate)", "Flat"),
    ("EA_CW-3 (Wrap)", "Flat"),
    ("EA_CW-3 (Wrap)", "WW2"),
    ("EA_CW-4 (Reveal)", "Flat"),
    ("EA_PC-1 (Precast)", "Flat"),
    ("EA_PC-1 (Precast)_Louver", "Flat"),
    ("EA_MP-1 (Podium)_Solid", "SD"),
    ("EA_MP-1 (Podium)_Glass", "SD"),
    ("EA_MP-2 (PodiumThin)", "SD"),
]
TARGET_LINK_TITLE = "SPARC_A_EA_Exterior"
CHILD_FAMILY_NAME = "RefMarker"
EXPECTED_PIER_MARKER_COUNT = 4
MARKER_PREFIX_PARAMETER = "prefix"
FULL_SPANDREL_PARAMETER = "is_full spandrel"
SILL_RAISED_PARAMETER = "is_sill raised"
SILL_RAISED_HIGHER_PARAMETER = "is_sill raised higher"
PIER_MARKER_ORDER = [
    "pier_furring_pt1",
    "pier_furring_pt2",
    "pier_furring_pt3",
    "pier_furring_pt4",
]
ROOM_SEPARATOR_MARKER_ORDER = [
    "rm_line_pt1",
    "rm_line_pt2",
    "rm_line_pt3",
    "rm_line_pt4",
    "rm_line_pt5",
    "rm_line_pt6",
]
SILL_MARKER_ORDER = [
    "sill_pt1",
    "sill_pt2",
]
PANEL_SELECTION_FILTER_PREFIX = "ShellFurringSelectionSet(DO_NOT_MANUAL_EDIT)"
ROOM_SEPARATION_FILTER_PREFIX = "ShellRoomSeparationSelectionSet(DO_NOT_MANUAL_EDIT)"
FURRING_WALL_TYPE_NAME = "FacadeFurringSpecial(DO_NOT_MANUAL_EDIT)"
PANEL_HEIGHT_PARAMETER = "CWPL_$Height"
MARKER_INDEX_PARAMETER = "index"
PANEL_LOG_PREVIEW_LIMIT = 10
HEIGHT_OFFSET = 3.0  # how much to reduce from the panel height
BASE_OFFSET = 0.0
SILL_WALL_HEIGHT_DEFAULT = 10.0 / 12.0  # 10inches converted to feet
SILL_WALL_HEIGHT_RAISED = 30.0 / 12.0  # 30inches converted to feet
SILL_WALL_HEIGHT_HIGHER = 40.0 / 12.0  # 40inches converted to feet
FAMILY_INSTANCE_FILTER = DB.ElementClassFilter(DB.FamilyInstance)
IGNORE_FURRING_PARAMETER = "is_ignore furring"
