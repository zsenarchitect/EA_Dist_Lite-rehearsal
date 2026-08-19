import traceback
from Autodesk.Revit import DB # pyright: ignore


def check_sheets_views(doc):
    """Check sheets and views metrics"""
    try:
        views_data = {}
        
        # Sheets
        sheets = DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).ToElements()
        views_data["total_sheets"] = len(sheets)
        
        # Views
        views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
        views_data["total_views"] = len(views)
        
        # Views not on sheets
        views_not_on_sheets = [v for v in views if not isinstance(v, DB.ViewSheet) and v.CanBePrinted]
        views_data["views_not_on_sheets"] = len(views_not_on_sheets)
        
        # Schedules not on sheets
        schedules = DB.FilteredElementCollector(doc).OfClass(DB.ViewSchedule).ToElements()
        schedules_not_on_sheets = [s for s in schedules if s.CanBePrinted]
        views_data["schedules_not_on_sheets"] = len(schedules_not_on_sheets)
        
        # Copied views
        copied_views = [v for v in views if v.IsTemplate == False and hasattr(v, 'ViewTemplateId')]
        views_data["copied_views"] = len(copied_views)
        
        # View count by view type - comprehensive breakdown
        view_count_by_type = {}
        view_count_by_type_non_template = {}
        view_count_by_type_template = {}
        
        for view in views:
            view_type = view.ViewType.ToString()
            
            # Overall count
            current_count = view_count_by_type.get(view_type, 0)
            view_count_by_type[view_type] = current_count + 1
            
            # Separate templates from non-templates
            if view.IsTemplate:
                current_template_count = view_count_by_type_template.get(view_type, 0)
                view_count_by_type_template[view_type] = current_template_count + 1
            else:
                current_non_template_count = view_count_by_type_non_template.get(view_type, 0)
                view_count_by_type_non_template[view_type] = current_non_template_count + 1
        
        views_data["view_count_by_type"] = view_count_by_type
        views_data["view_count_by_type_non_template"] = view_count_by_type_non_template
        views_data["view_count_by_type_template"] = view_count_by_type_template
        
        return views_data
        
    except Exception as e:
        return {"error": str(traceback.format_exc())}

