# -*- coding: utf-8 -*-

__title__ = "ChildrenPalaceMassing"
__doc__ = """Children Palace Massing Tool

Creates solid massing geometry from wall, roof, and base layers for Children Palace project.
Features:
- Processes massing layers (massing_1, massing_2, etc.) with sublayers (wall, roof, base)
- Creates solid geometry from closure shapes and moves them horizontally
- Generates area shapes by intersecting solids with level planes
- Creates planar surfaces from intersection curves for GFA calculations
- Organizes output into 'Updated Geo' and 'Slab[GFA]' layers

Usage:
1. Ensure massing layers exist with wall/roof/base sublayers
2. Place level reference points on 'Levels' layer
3. Run tool to generate massing solids and area calculations"""


import System
import Rhino
import rhinoscriptsyntax as rs
import scriptcontext

from EnneadTab import ERROR_HANDLE, LOG
from EnneadTab.RHINO import RHINO_OBJ_DATA

OUT_LAYER = "Updated Geo"
LEVEL_LAYER = "Levels"
SLAB_LAYER = "Slab[GFA]"

def get_xyz_from_object(obj):
    """Get XYZ coordinates from various Rhino object types.
    
    Args:
        obj: Rhino object ID
        
    Returns:
        tuple: (x, y, z) coordinates or None if failed
    """
    # Method 1: Try PointCoordinates (for point objects)
    point = rs.PointCoordinates(obj)
    if point:
        return (point[0], point[1], point[2])
    
    # Method 2: Try getting center of bounding box (for any object)
    try:
        center = RHINO_OBJ_DATA.get_center(obj)
        if center:
            return (center[0], center[1], center[2])
    except:
        pass
    
    # Method 3: Try getting object geometry and extract point
    try:
        geo = rs.coercegeometry(obj)
        if geo:
            bbox = geo.GetBoundingBox(False)
            if bbox:
                center_pt = (bbox.Min + bbox.Max) / 2
                return (center_pt.X, center_pt.Y, center_pt.Z)
    except:
        pass
    
    # Method 4: Try getting block insert point
    try:
        if rs.IsBlockInstance(obj):
            insert_pt = rs.BlockInstanceInsertPoint(obj)
            if insert_pt:
                return (insert_pt[0], insert_pt[1], insert_pt[2])
    except:
        pass
    
    # Method 5: Try getting text dot point
    try:
        obj_type = rs.ObjectType(obj)
        if obj_type == 8192:  # TextDot object type
            # Get the text dot's point
            text_dot = rs.coercegeometry(obj)
            if text_dot and hasattr(text_dot, 'Point'):
                pt = text_dot.Point
                return (pt.X, pt.Y, pt.Z)
    except:
        pass
    
    return None

def cleanup_layer(layer_name):
    """Delete all objects in a layer.
    
    Args:
        layer_name: Name of the layer to clean up
    """
    if rs.IsLayer(layer_name):
        old_objects = rs.ObjectsByLayer(layer_name)
        if old_objects:
            rs.DeleteObjects(old_objects)
            print("Cleaned up {} objects from layer: {}".format(len(old_objects), layer_name))

def ensure_layer_exists(layer_name):
    """Create layer if it doesn't exist.
    
    Args:
        layer_name: Name of the layer to ensure exists
    """
    if not rs.IsLayer(layer_name):
        rs.AddLayer(layer_name)
        print("Created layer: {}".format(layer_name))
    else:
        print("Layer already exists: {}".format(layer_name))

def process_layer(i):
    main_layer = "massing_{}".format(i)
    if not rs.IsLayer(main_layer):
        return
    wall_layer = "{}::wall".format(main_layer)
    roof_layer = "{}::roof".format(main_layer)
    base_layer = "{}::base".format(main_layer)

    walls = rs.ObjectsByLayer(wall_layer)
    roofs = rs.ObjectsByLayer(roof_layer)
    bases = rs.ObjectsByLayer(base_layer)

    closure_shapes = walls + roofs + bases
    if not closure_shapes:
        return

    closure_shapes = rs.CopyObjects(closure_shapes)
    rs.UnselectAllObjects()
    rs.SelectObjects(closure_shapes)
    rs.Command("_CreateSolid")
    solid = rs.LastCreatedObjects()
    if not solid:
        return
    
    
    if not rs.IsLayer(OUT_LAYER):
        rs.AddLayer(OUT_LAYER)

    for x in solid:
        rs.ObjectLayer(x, OUT_LAYER)

    a = rs.MoveObjects(solid, [-200 * i,0,0])

    rs.UnselectAllObjects()


def get_area_shape():
    dots = rs.ObjectsByLayer(LEVEL_LAYER)
    if not dots:
        print("No dots found in LEVEL_LAYER")
        return
    
    # Get all solids from OUT_LAYER for intersection
    solids = rs.ObjectsByLayer(OUT_LAYER)
    if not solids:
        print("No solids found in OUT_LAYER")
        return
    
    rs.EnableRedraw(False)
    
    for dot in dots:
        # Get XYZ coordinates from the dot object
        xyz = get_xyz_from_object(dot)
        if not xyz:
            obj_type = rs.ObjectType(dot) if rs.ObjectType(dot) else "unknown"
            print("Failed to get XYZ coordinates for dot object: {} (type: {})".format(dot, obj_type))
            continue
            
        x, y, z = xyz
        level_h = z
        print("Got coordinates: X={}, Y={}, Z={}".format(x, y, z))
        
        # Create intersection plane at the dot's position
        plane_origin = [x, y, level_h]
            
        plane_normal = [0, 0, 1]  # Horizontal plane
        
        # Create a large plane for intersection
        plane = rs.PlaneFromNormal(plane_origin, plane_normal)
        if not plane:
            print("Failed to create plane at level {}".format(level_h))
            continue
            
        # Create intersection curves for all solids at this level
        intersection_curves = []
        for solid in solids:
            # Create a temporary plane surface for intersection
            plane_surface = rs.AddPlaneSurface(plane, 1000, 1000)  # Large plane
            if plane_surface:
                rs.MoveObject(plane_surface, [-500, -500, 0])
                intersections = rs.IntersectBreps(solid, plane_surface)
                if intersections:
                    intersection_curves.extend(intersections)
                rs.DeleteObject(plane_surface)  # Clean up temporary plane
        
        # If we have intersection curves, assign them to SLAB_LAYER
        if intersection_curves: #pyright: ignore
            print("Found {} intersection curves".format(len(intersection_curves)))
            if not rs.IsLayer(SLAB_LAYER):
                rs.AddLayer(SLAB_LAYER)
            for curve in intersection_curves:
                # Try to create a planar surface from the curve
                try:
                    # Method 1: Try AddPlanarSrf (most reliable for closed curves)
                    srf = rs.AddPlanarSrf(curve)
                    if srf:
                        rs.ObjectLayer(srf, SLAB_LAYER)
                        rs.DeleteObject(curve)
                    else:
                        print("use method 2")
                        # Method 2: Try to create surface from curve geometry
                        geo = rs.coercegeometry(curve)
                        if geo and geo.IsClosed:
                            # Create surface from closed curve using list
                            srf = rs.AddPlanarSrf([curve])
                            if srf:
                                rs.ObjectLayer(srf, SLAB_LAYER)
                                rs.DeleteObject(curve)
                            else:
                                print("use method 3")
                                # Method 3: Try to create surface from curve points
                                try:
                                    # Get curve points and create surface
                                    points = rs.CurvePoints(curve)
                                    if len(points) >= 3:
                                        srf = rs.AddSrfPt(points)
                                        if srf:
                                            rs.ObjectLayer(srf, SLAB_LAYER)
                                            rs.DeleteObject(curve)
                                        else:
                                            rs.ObjectLayer(curve, SLAB_LAYER)
                                    else:
                                        rs.ObjectLayer(curve, SLAB_LAYER)
                                except:
                                    rs.ObjectLayer(curve, SLAB_LAYER)
                        else:   
                            print("use method 4")
                            # For open curves, just keep the curve
                            rs.ObjectLayer(curve, SLAB_LAYER)
                except Exception as e:
                    print("Failed to create surface from curve because of: {}".format(e))
                    # If all methods fail, keep the curve
                    rs.ObjectLayer(curve, SLAB_LAYER)
    rs.EnableRedraw(True)

@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def children_palace_massing():
    # Ensure all required layers exist
    ensure_layer_exists(OUT_LAYER)
    ensure_layer_exists(LEVEL_LAYER)
    ensure_layer_exists(SLAB_LAYER)

    # Clean up old objects from output layers
    cleanup_layer(OUT_LAYER)
    cleanup_layer(SLAB_LAYER)


        
    for i in range(1, 10):
        process_layer(i)

    get_area_shape()

if __name__ == "__main__":
    children_palace_massing()

