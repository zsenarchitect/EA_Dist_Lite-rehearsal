import traceback
from Autodesk.Revit import DB  # pyright: ignore


def get_element_id_value(element_id, default=None):
    """Return a safe integer value for a Revit ElementId across Revit versions."""
    if element_id is None:
        return default

    # Prefer the newer Value property when available (Revit 2024+)
    try:
        value = element_id.Value  # type: ignore[attr-defined]
        if value is not None:
            return value
    except AttributeError:
        pass
    except Exception:
        pass

    # Fall back to the legacy IntegerValue property (deprecated in Revit 2024)
    try:
        value = element_id.IntegerValue  # type: ignore[attr-defined]
        if value is not None:
            return value
    except AttributeError:
        pass
    except Exception:
        pass

    # Last resort: attempt to coerce into int
    try:
        return int(element_id)
    except Exception:
        return default


def is_invalid_element_id(element_id):
    """Check whether an ElementId is invalid without assuming IntegerValue exists."""
    try:
        return element_id == DB.ElementId.InvalidElementId
    except Exception:
        invalid_value = get_element_id_value(DB.ElementId.InvalidElementId, default=None)
        return get_element_id_value(element_id, default=None) == invalid_value


def safe_element_id_list(element_ids):
    """Convert a sequence of ElementIds into a list of safe integer values, skipping failures."""
    safe_ids = []
    for element_id in element_ids or []:
        value = get_element_id_value(element_id)
        if value is not None:
            safe_ids.append(value)
    return safe_ids


__all__ = [
    "get_element_id_value",
    "is_invalid_element_id",
    "safe_element_id_list",
]

