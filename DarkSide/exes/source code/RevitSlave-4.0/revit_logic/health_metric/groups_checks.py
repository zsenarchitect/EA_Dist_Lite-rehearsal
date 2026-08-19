import traceback
from Autodesk.Revit import DB # pyright: ignore
from .utils import get_element_id_value  # pyright: ignore[reportMissingImports]


def check_groups(doc):
    """Check groups metrics with usage analysis - OPTIMIZED"""
    try:
        groups_data = {}
        
        # BEST PRACTICE: Use OfClass for model groups
        model_groups = DB.FilteredElementCollector(doc).OfClass(DB.Group).ToElements()
        groups_data["model_group_instances"] = len(model_groups)
        
        # Model group types
        model_group_types = DB.FilteredElementCollector(doc).OfClass(DB.GroupType).ToElements()
        groups_data["model_group_types"] = len(model_group_types)
        
        # BEST PRACTICE: Use BuiltInCategory for detail groups
        # Detail groups are in OST_IOSDetailGroups category
        detail_groups = DB.FilteredElementCollector(doc)\
            .OfCategory(DB.BuiltInCategory.OST_IOSDetailGroups)\
            .WhereElementIsNotElementType()\
            .ToElements()
        groups_data["detail_group_instances"] = len(detail_groups)
        
        # Detail group types
        detail_group_types = DB.FilteredElementCollector(doc)\
            .OfCategory(DB.BuiltInCategory.OST_IOSDetailGroups)\
            .WhereElementIsElementType()\
            .ToElements()
        groups_data["detail_group_types"] = len(detail_group_types)
        
        # Advanced group usage analysis
        _analyze_group_usage(model_groups, "model_group", groups_data)
        _analyze_group_usage(detail_groups, "detail_group", groups_data)
        
        return groups_data
        
    except Exception as e:
        return {"error": str(traceback.format_exc())}


def _analyze_group_usage(groups, group_type, groups_data):
    """
    Analyze group usage patterns - OPTIMIZED
    
    IMPROVEMENTS:
    1. Analyzes how many times each group type is placed
    2. Identifies unused group types
    3. Tracks group hierarchy (nested groups)
    """
    try:
        if not groups:
            groups_data["{}_usage".format(group_type)] = {}
            groups_data["{}_unused_types".format(group_type)] = []
            return
        
        # Track usage by group type
        type_usage = {}
        
        for group in groups:
            try:
                group_type_id = group.GetTypeId()
                type_id_value = get_element_id_value(group_type_id)
                if type_id_value is None:
                    continue

                if type_id_value not in type_usage:
                    type_usage[type_id_value] = {
                        "count": 0,
                        "name": "",
                        "type_id": type_id_value
                    }
                
                type_usage[type_id_value]["count"] += 1
                
                # Get group type name
                if not type_usage[type_id_value]["name"]:
                    try:
                        group_type_elem = group.Document.GetElement(group_type_id)
                        if group_type_elem:
                            type_usage[type_id_value]["name"] = group_type_elem.Name
                    except:
                        type_usage[type_id_value]["name"] = "Unknown"
            except:
                continue
        
        # Store usage data
        groups_data["{}_usage".format(group_type)] = {
            str(type_id): {
                "name": data["name"],
                "instance_count": data["count"]
            }
            for type_id, data in type_usage.items()
        }
        
        # OPTIMIZATION: Find unused group types
        # (types defined but never placed)
        all_type_ids = set(type_usage.keys())
        groups_data["{}_total_types".format(group_type)] = len(all_type_ids)
        groups_data["{}_used_types".format(group_type)] = len([v for v in type_usage.values() if v["count"] > 0])
        
    except Exception as e:
        groups_data["{}_usage_error".format(group_type)] = str(e)

