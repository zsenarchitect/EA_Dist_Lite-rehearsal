import traceback
from Autodesk.Revit import DB  # pyright: ignore

from .utils import get_element_id_value, is_invalid_element_id  # pyright: ignore[reportMissingImports]
def check_templates_filters(doc):
    """Collect basic view template metrics."""
    try:
        templates_data = {
            "view_templates": 0,
            "unused_view_templates": 0,
        }

        all_views = DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements()
        all_true_views = [v for v in all_views if not v.IsTemplate]
        all_templates = [v for v in all_views if v.IsTemplate]

        templates_data["view_templates"] = len(all_templates)

        used_template_ids = set()
        for view in all_true_views:
            try:
                template_id = view.ViewTemplateId
                if template_id and not is_invalid_element_id(template_id):
                    template_id_value = get_element_id_value(template_id)
                    if template_id_value is not None:
                        used_template_ids.add(template_id_value)
            except Exception:
                continue

        unused_templates = []
        for template in all_templates:
            try:
                template_value = get_element_id_value(template.Id)
                if template_value is None or template_value not in used_template_ids:
                    unused_templates.append(template)
            except Exception:
                continue
        templates_data["unused_view_templates"] = len(unused_templates)

        return templates_data

    except Exception:
        return {"error": str(traceback.format_exc())}