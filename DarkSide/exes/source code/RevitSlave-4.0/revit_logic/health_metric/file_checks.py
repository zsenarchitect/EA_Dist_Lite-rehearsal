# -*- coding: utf-8 -*-
import traceback
from Autodesk.Revit import DB # pyright: ignore


def _normalize_title(title):
    try:
        if not title:
            return None
        name = title
        lower_name = name.lower()
        if lower_name.endswith("_detached"):
            name = name[: -len("_detached")]
        elif name.endswith("_已分离"):
            name = name[: -len("_已分离")]
        return name.lower()
    except:
        return None


def _find_accdocs_path(title):
    try:
        normalized = _normalize_title(title)
        if not normalized:
            return None

        import os

        username = os.environ.get("USERNAME")
        if not username:
            return None

        accdocs_root = os.path.join("C:\\Users", username, "DC", "ACCDocs")
        if not os.path.exists(accdocs_root):
            return None

        best_path = None
        best_mtime = None

        for root, _, files in os.walk(accdocs_root):
            for filename in files:
                if not filename.lower().endswith(".rvt"):
                    continue
                stem = filename[:-4]
                base_name = stem.lower()
                if base_name.endswith("_detached"):
                    stem = stem[: -len("_detached")]
                    base_name = stem.lower()
                elif stem.endswith("_已分离"):
                    stem = stem[: -len("_已分离")]
                    base_name = stem.lower()
                if base_name == normalized:
                    full_path = os.path.join(root, filename)
                    try:
                        mtime = os.path.getmtime(full_path)
                    except OSError:
                        mtime = None
                    if best_path is None or (mtime is not None and (best_mtime is None or mtime > best_mtime)):
                        best_path = full_path
                        best_mtime = mtime

        return best_path
    except:
        return None


def _get_visible_path(doc):
    try:
        if hasattr(doc, "IsModelInCloud") and doc.IsModelInCloud:
            try:
                model_path = doc.GetCloudModelPath()
                if model_path:
                    return DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(model_path)
            except:
                return "Cloud Model"

        model_path = None
        try:
            if hasattr(doc, "IsWorkshared") and doc.IsWorkshared:
                model_path = doc.GetWorksharingCentralModelPath()
        except:
            model_path = None

        if model_path:
            try:
                return DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(model_path)
            except:
                pass

        return getattr(doc, "PathName", None)
    except:
        return getattr(doc, "PathName", None)


def check_file_size(doc):
    """Check file size and resolved path"""
    try:
        file_size_data = {}

        file_path = _get_visible_path(doc)
        if file_path and file_path != "Cloud Model":
            try:
                import os

                if os.path.exists(file_path):
                    file_size_bytes = os.path.getsize(file_path)
                    file_size_mb = file_size_bytes / (1024.0 * 1024.0)
                    file_size_data["file_path"] = file_path
                    file_size_data["file_size_bytes"] = file_size_bytes
                    file_size_data["file_size_mb"] = round(file_size_mb, 2)
                    file_size_data["path_source"] = "direct"
                    return file_size_data
            except:
                pass

        accdocs_path = _find_accdocs_path(getattr(doc, "Title", None))
        if accdocs_path:
            try:
                import os

                if os.path.exists(accdocs_path):
                    file_size_bytes = os.path.getsize(accdocs_path)
                    file_size_mb = file_size_bytes / (1024.0 * 1024.0)
                    file_size_data["file_path"] = accdocs_path
                    file_size_data["file_size_bytes"] = file_size_bytes
                    file_size_data["file_size_mb"] = round(file_size_mb, 2)
                    file_size_data["path_source"] = "accdocs"
                    return file_size_data
            except:
                pass

        file_size_data["file_path"] = file_path
        file_size_data["file_size_bytes"] = 0
        file_size_data["file_size_mb"] = 0
        file_size_data["path_source"] = "cloud" if getattr(doc, "IsModelInCloud", False) else "unknown"
        file_size_data["note"] = "Could not resolve file size"

        return file_size_data

    except Exception:
        return {"error": str(traceback.format_exc())}

