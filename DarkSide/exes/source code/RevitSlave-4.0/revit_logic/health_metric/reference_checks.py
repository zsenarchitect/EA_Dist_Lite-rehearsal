import traceback
from Autodesk.Revit import DB # pyright: ignore


def check_reference_planes(doc):
    """Check reference planes metrics"""
    try:
        ref_planes_data = {}
        
        # Reference planes
        all_ref_planes = DB.FilteredElementCollector(doc).OfClass(DB.ReferencePlane).ToElements()
        # Only get ref planes whose workset is not read-only (project refs, not family refs)
        ref_planes = []
        for rp in all_ref_planes:
            try:
                workset_param = rp.LookupParameter("Workset")
                if workset_param and not workset_param.IsReadOnly:
                    ref_planes.append(rp)
            except:
                # If we can't check workset, include it (safer approach)
                ref_planes.append(rp)
        
        ref_planes_data["reference_planes"] = len(ref_planes)
        
        # Unnamed reference planes
        unnamed_ref_planes = [rp for rp in ref_planes if 
                             rp.Name == "Reference Plane" or 
                             not rp.Name or 
                             rp.Name.strip() == ""]
        ref_planes_data["reference_planes_no_name"] = len(unnamed_ref_planes)
        
        return ref_planes_data
        
    except Exception as e:
        return {"error": str(traceback.format_exc())}


def check_grids_levels(doc):
    """Check grids and levels pinning status - OPTIMIZED"""
    try:
        grids_levels_data = {}
        
        # BEST PRACTICE: Single collector call for grids
        grids = DB.FilteredElementCollector(doc).OfClass(DB.Grid).ToElements()
        grids_levels_data["total_grids"] = len(grids)
        
        # OPTIMIZATION: Single-pass collection with list comprehension
        unpinned_grids = [g for g in grids if not g.Pinned]
        grids_levels_data["unpinned_grids"] = len(unpinned_grids)
        grids_levels_data["pinned_grids"] = len(grids) - len(unpinned_grids)
        
        # BEST PRACTICE: Single collector call for levels
        levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
        grids_levels_data["total_levels"] = len(levels)
        
        # OPTIMIZATION: Single-pass collection with list comprehension
        unpinned_levels = [l for l in levels if not l.Pinned]
        grids_levels_data["unpinned_levels"] = len(unpinned_levels)
        grids_levels_data["pinned_levels"] = len(levels) - len(unpinned_levels)
        
        # OPTIMIZATION: Use list comprehension for name extraction with inline error handling
        unpinned_grid_names = []
        for grid in unpinned_grids:
            try:
                # ENHANCEMENT: Include grid name even if empty (helps debugging)
                grid_name = grid.Name if grid.Name else "<Unnamed Grid>"
                unpinned_grid_names.append(grid_name)
            except:
                unpinned_grid_names.append("<Error Reading Grid>")
        grids_levels_data["unpinned_grid_names"] = sorted(unpinned_grid_names)
        
        # OPTIMIZATION: Use list comprehension for level name extraction with elevation
        unpinned_level_details = []
        for level in unpinned_levels:
            try:
                level_name = level.Name if level.Name else "<Unnamed Level>"
                # ENHANCEMENT: Include elevation for better identification
                try:
                    elevation = level.Elevation
                    unpinned_level_details.append({
                        "name": level_name,
                        "elevation": elevation
                    })
                except:
                    unpinned_level_details.append({
                        "name": level_name,
                        "elevation": None
                    })
            except:
                unpinned_level_details.append({
                    "name": "<Error Reading Level>",
                    "elevation": None
                })
        
        # MAINTAIN BACKWARD COMPATIBILITY: Keep unpinned_level_names as list of strings
        grids_levels_data["unpinned_level_names"] = sorted([l["name"] for l in unpinned_level_details])
        
        # ENHANCEMENT: Add detailed level info (optional field, backward compatible)
        grids_levels_data["unpinned_level_details"] = sorted(unpinned_level_details, key=lambda x: x.get("elevation") or 0)
        
        return grids_levels_data
        
    except Exception as e:
        return {"error": str(traceback.format_exc())}

