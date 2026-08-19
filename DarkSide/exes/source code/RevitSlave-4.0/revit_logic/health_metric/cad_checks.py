import traceback
from Autodesk.Revit import DB # pyright: ignore


def check_cad_files(doc):
    """Check CAD files metrics - OPTIMIZED"""
    try:
        cad_data = {}
        
        # BEST PRACTICE: Single collector call for all import instances
        all_imports = DB.FilteredElementCollector(doc)\
            .OfClass(DB.ImportInstance)\
            .WhereElementIsNotElementType()\
            .ToElements()
        
        # OPTIMIZATION: Filter in single pass instead of multiple collectors
        imported_dwgs = []
        linked_dwgs = []
        
        for import_instance in all_imports:
            try:
                if import_instance.IsLinked:
                    linked_dwgs.append(import_instance)
                else:
                    imported_dwgs.append(import_instance)
            except:
                continue
        
        cad_data["imported_dwgs"] = len(imported_dwgs)
        cad_data["linked_dwgs"] = len(linked_dwgs)
        cad_data["dwg_files"] = len(all_imports)
        
        return cad_data
        
    except Exception as e:
        return {"error": str(traceback.format_exc())}

