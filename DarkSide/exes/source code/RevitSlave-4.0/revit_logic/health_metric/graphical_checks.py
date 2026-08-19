import traceback
from Autodesk.Revit import DB # pyright: ignore


def check_graphical_elements(doc):
    """Check graphical 2D elements metrics"""
    try:
        graphical_data = {}
        
        # Detail lines - use CurveElement and filter for DetailCurve type
        curve_elements = DB.FilteredElementCollector(doc).OfClass(DB.CurveElement).ToElements()
        # BEST PRACTICE: Use enum comparison instead of string (version-safe, locale-safe)
        detail_lines = [ce for ce in curve_elements if ce.CurveElementType == DB.CurveElementType.DetailCurve]
        graphical_data["detail_lines"] = len(detail_lines)
        
        # Line patterns
        line_patterns = DB.FilteredElementCollector(doc).OfClass(DB.LinePatternElement).ToElements()
        graphical_data["line_patterns"] = len(line_patterns)
        
        # Text notes
        text_notes = DB.FilteredElementCollector(doc).OfClass(DB.TextNote).ToElements()
        graphical_data["text_notes_instances"] = len(text_notes)
        
        # Text note types
        text_note_types = DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).ToElements()
        graphical_data["text_notes_types"] = len(text_note_types)
        
        # Text notes with solid background (version-safe)
        # NOTE: TextNoteBackground enum might not exist in older Revit versions (pre-2020)
        try:
            if hasattr(DB, 'TextNoteBackground'):
                solid_background_notes = [tn for tn in text_note_types if hasattr(tn, 'Background') and tn.Background == DB.TextNoteBackground.Solid]
                graphical_data["text_notes_types_solid_background"] = len(solid_background_notes)
            else:
                graphical_data["text_notes_types_solid_background"] = 0
        except:
            graphical_data["text_notes_types_solid_background"] = 0
        
        # Text notes width factor != 1
        width_factor_notes = [tn for tn in text_note_types if hasattr(tn, 'WidthFactor') and tn.WidthFactor != 1.0]
        graphical_data["text_notes_width_factor_not_1"] = len(width_factor_notes)
        
        # Text notes all caps
        all_caps_notes = [tn for tn in text_note_types if hasattr(tn, 'AllCaps') and tn.AllCaps]
        graphical_data["text_notes_all_caps"] = len(all_caps_notes)
        
        # Dimensions
        dimensions = DB.FilteredElementCollector(doc).OfClass(DB.Dimension).ToElements()
        graphical_data["dimensions"] = len(dimensions)
        
        # Dimension types
        dimension_types = DB.FilteredElementCollector(doc).OfClass(DB.DimensionType).ToElements()
        graphical_data["dimension_types"] = len(dimension_types)
        
        # Dimension overrides (with null check)
        # BEST PRACTICE: Check for None before string comparison
        dimension_overrides = [d for d in dimensions if d.ValueOverride and d.ValueOverride != ""]
        graphical_data["dimension_overrides"] = len(dimension_overrides)
        
        # Revision clouds
        revision_clouds = DB.FilteredElementCollector(doc).OfClass(DB.RevisionCloud).ToElements()
        graphical_data["revision_clouds"] = len(revision_clouds)
        
        return graphical_data
        
    except Exception as e:
        return {"error": str(traceback.format_exc())}

