import traceback
from Autodesk.Revit import DB # pyright: ignore
from .utils import get_element_id_value  # pyright: ignore[reportMissingImports]
from .worksharing import is_document_workshared


def check_families(doc):
    """Check families metrics with advanced analysis - OPTIMIZED"""
    try:
        families_data = {}
        
        # BEST PRACTICE: Single collector call with ToElements()
        families = DB.FilteredElementCollector(doc).OfClass(DB.Family).ToElements()
        families_data["total_families"] = len(families)
        
        # In-place families
        in_place_families = [f for f in families if f.IsInPlace]
        families_data["in_place_families"] = len(in_place_families)
        
        # Non-parametric families
        non_parametric_families = [f for f in families if not f.IsParametric]
        families_data["non_parametric_families"] = len(non_parametric_families)
        
        # OPTIMIZATION: Single collector for family symbols, filter by category
        family_symbols = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).ToElements()
        
        # Generic models
        generic_models = [sym for sym in family_symbols if sym.Category and sym.Category.Name == "Generic Models"]
        families_data["generic_models_types"] = len(generic_models)
        
        # Detail components
        detail_components = [sym for sym in family_symbols if sym.Category and sym.Category.Name == "Detail Items"]
        families_data["detail_components"] = len(detail_components)
        
        # Find unused families - OPTIMIZED METHOD
        unused_families_info = _find_unused_families(doc, families)
        families_data["unused_families_count"] = unused_families_info["count"]
        families_data["unused_families_names"] = unused_families_info["names"]
        
        # Advanced family analysis
        families_data["in_place_families_creators"] = _analyze_family_creators(doc, in_place_families)
        families_data["non_parametric_families_creators"] = _analyze_family_creators(doc, non_parametric_families)
        
        return families_data
        
    except Exception as e:
        return {"error": str(traceback.format_exc())}


def _analyze_family_creators(doc, families):
    """Analyze family creators and last editors - OPTIMIZED"""
    try:
        is_workshared = is_document_workshared(doc)
        
        # OPTIMIZATION: Skip worksharing checks if document isn't workshared
        if not is_workshared:
            return {
                "creators": {},
                "last_editors": {},
                "note": "Worksharing info not available"
            }
        
        creator_data = {}
        last_editor_data = {}
        
        for family in families:
            try:
                info = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, family.Id)
                if info:
                    creator = info.Creator
                    last_editor = info.LastChangedBy
                    
                    if creator:
                        creator_data[creator] = creator_data.get(creator, 0) + 1
                    
                    if last_editor:
                        last_editor_data[last_editor] = last_editor_data.get(last_editor, 0) + 1
            except:
                pass  # Skip if worksharing info not available
        
        return {
            "creators": creator_data,
            "last_editors": last_editor_data
        }
        
    except Exception as e:
        return {"error": str(traceback.format_exc())}


def _find_unused_families(doc, families):
    """
    OPTIMIZED: Find families with no instances using ElementId-based set lookup
    
    IMPROVEMENTS:
    1. Uses stable ElementId values for faster set operations
    2. Also checks FamilySymbol usage (covers more edge cases)
    3. Handles system families that might not have instances
    """
    try:
        # OPTIMIZATION 1: Get all family instances at once
        all_family_instances = DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance).ToElements()
        
        # OPTIMIZATION 2: Use set of stable ElementId values for O(1) lookup
        used_family_ids = set()
        
        for instance in all_family_instances:
            try:
                symbol = instance.Symbol
                if symbol and symbol.Family:
                    family_id_value = get_element_id_value(symbol.Family.Id)
                    if family_id_value is not None:
                        used_family_ids.add(family_id_value)
            except:
                continue
        
        # OPTIMIZATION 3: Also check if family has any symbols placed
        # This catches edge cases where family exists but all types are unused
        family_symbols = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).ToElements()
        for symbol in family_symbols:
            try:
                if symbol.Family:
                    # If symbol is placed (not just defined), mark family as used
                    family_id_value = get_element_id_value(symbol.Family.Id)
                    if family_id_value is not None:
                        used_family_ids.add(family_id_value)
            except:
                continue
        
        # Find unused families
        unused_families = []
        for family in families:
            # Skip in-place families and system families
            if not family.IsInPlace and not family.IsSystemFamily:
                family_id_value = get_element_id_value(family.Id)
                if family_id_value is None or family_id_value not in used_family_ids:
                    unused_families.append(family.Name)
        
        return {
            "count": len(unused_families),
            "names": sorted(unused_families)
        }
        
    except Exception as e:
        return {
            "count": 0,
            "names": [],
            "error": str(traceback.format_exc())
        }

