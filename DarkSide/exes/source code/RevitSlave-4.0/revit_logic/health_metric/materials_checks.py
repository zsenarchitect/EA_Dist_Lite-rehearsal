import traceback
from Autodesk.Revit import DB # pyright: ignore


def check_materials(doc):
    """Check materials count"""
    try:
        materials_data = {}
        materials = DB.FilteredElementCollector(doc).OfClass(DB.Material).ToElements()
        materials_data["materials"] = len(materials)
        
        return materials_data
    except Exception as e:
        return {"error": str(traceback.format_exc())}


def check_line_count(doc):
    """Check detail and model line usage with per-view breakdown - OPTIMIZED"""
    try:
        line_data = {}
        
        # BEST PRACTICE: Single collector call
        curve_elements = DB.FilteredElementCollector(doc).OfClass(DB.CurveElement).ToElements()
        
        # OPTIMIZATION: Single-pass iteration for all metrics
        detail_lines = []
        model_lines = []
        detail_lines_per_view = {}
        model_lines_per_view = {}
        
        for ce in curve_elements:
            try:
                # BEST PRACTICE: Use CurveElementType enum comparison instead of string
                curve_type = ce.CurveElementType
                
                if curve_type == DB.CurveElementType.DetailCurve:
                    detail_lines.append(ce)
                    
                    # OPTIMIZATION: Collect view info in same pass
                    try:
                        owner_view_id = ce.OwnerViewId
                        if owner_view_id and owner_view_id != DB.ElementId.InvalidElementId:
                            view = doc.GetElement(owner_view_id)
                            if view:
                                view_name = view.Name
                                detail_lines_per_view[view_name] = detail_lines_per_view.get(view_name, 0) + 1
                    except:
                        pass
                        
                elif curve_type == DB.CurveElementType.ModelCurve:
                    model_lines.append(ce)
                    
                    # ENHANCEMENT: Also track model lines per view
                    try:
                        owner_view_id = ce.OwnerViewId
                        if owner_view_id and owner_view_id != DB.ElementId.InvalidElementId:
                            view = doc.GetElement(owner_view_id)
                            if view:
                                view_name = view.Name
                                model_lines_per_view[view_name] = model_lines_per_view.get(view_name, 0) + 1
                    except:
                        pass
            except:
                continue
        
        # MAINTAIN BACKWARD COMPATIBILITY: Keep original keys
        line_data["detail_lines_total"] = len(detail_lines)
        line_data["model_lines_total"] = len(model_lines)
        line_data["detail_lines_per_view"] = detail_lines_per_view
        
        # ENHANCEMENT: Add model lines per view (optional field, backward compatible)
        line_data["model_lines_per_view"] = model_lines_per_view
        
        # ENHANCEMENT: Add top views with most lines (helps identify problem views)
        if detail_lines_per_view:
            sorted_detail_views = sorted(detail_lines_per_view.items(), key=lambda x: x[1], reverse=True)[:10]
            line_data["top_detail_line_views"] = [{"view": v, "count": c} for v, c in sorted_detail_views]
        
        return line_data
        
    except Exception as e:
        return {"error": str(traceback.format_exc())}

