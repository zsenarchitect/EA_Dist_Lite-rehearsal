from Autodesk.Revit import DB  # pyright: ignore


def is_document_workshared(doc):
    """Safely determine whether the active document has worksharing enabled."""
    if doc is None:
        return False

    # Primary: rely on Document.IsWorkshared (official API property)
    # Reference: https://www.revitapidocs.com/2025/7f368167-6543-9be9-67a3-c6e1696ae060.htm
    try:
        return bool(getattr(doc, "IsWorkshared", False))
    except Exception:
        pass

    # Fallback: attempt to infer from the active model path
    try:
        model_path = doc.GetCloudModelPath()
        if model_path:
            # Reference: WorksharingUtils helpers
            # https://www.revitapidocs.com/2025/205fa377-e6ad-aef0-e783-35b50152c336.htm
            return bool(DB.WorksharingUtils.IsModelWorkshared(model_path))
    except Exception:
        pass

    try:
        central_path = doc.GetWorksharingCentralModelPath()
        if central_path and not central_path.Empty:
            return True
    except Exception:
        pass

    return False









