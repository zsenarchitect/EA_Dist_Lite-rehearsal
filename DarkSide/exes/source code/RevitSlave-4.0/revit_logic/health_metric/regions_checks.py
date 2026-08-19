import traceback
from Autodesk.Revit import DB # pyright: ignore


def check_filled_regions(doc):
    """Check filled regions count - OPTIMIZED"""
    try:
        filled_regions_data = {}
        
        # BEST PRACTICE: Single collector call
        collector = DB.FilteredElementCollector(doc).OfClass(DB.FilledRegion)
        filled_regions = collector.WhereElementIsNotElementType().ToElements()
        filled_region_types = collector.WhereElementIsElementType().ToElements()

        filled_regions_data["filled_region_types"] = len(filled_region_types)
        filled_regions_data["filled_regions"] = len(filled_regions)
        
        return filled_regions_data
        
    except Exception as e:
        return {"error": str(traceback.format_exc())}

