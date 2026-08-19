import traceback
from Autodesk.Revit import DB # pyright: ignore


def check_linked_files(doc):
    """Check linked files information"""
    try:
        linked_files = []
        link_instances = DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance)
        
        for link in link_instances:
            link_doc = link.GetLinkDocument()
            if link_doc:
                link_info = {
                    "linked_file_name": link_doc.Title,
                    "instance_name": link.Name,
                    "loaded_status": "Loaded" if link.IsHidden == False else "Hidden",
                    "pinned_status": "Pinned" if link.Pinned else "Unpinned"
                }
                linked_files.append(link_info)
        
        return {
            "linked_files": linked_files,
            "linked_files_count": len(linked_files)
        }
    except Exception as e:
        return {"error": str(traceback.format_exc())}

