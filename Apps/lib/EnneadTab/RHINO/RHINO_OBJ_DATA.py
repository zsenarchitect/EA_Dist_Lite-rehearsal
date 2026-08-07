#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import sys
root_folder = os.path.abspath((os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(root_folder)
import ENVIRONMENT


if ENVIRONMENT.IS_RHINO_ENVIRONMENT:
    import rhinoscriptsyntax as rs
    import scriptcontext as sc
    import Rhino # type: ignore


def sort_pts_by_Z(pts):
    """Sort points by their Z coordinate in ascending order.

    Parameters
    ----------
    pts : list
        List of Rhino.Geometry.Point3d objects to sort

    Returns
    -------
    list
        Points sorted by ascending Z coordinate value
    """
    pts = sorted(pts, key=lambda x: x.Z)
    return pts

def sort_pts_along_crv(pts, crv):
    """Sort points by their parameter values along a curve.

    Parameters
    ----------
    pts : list
        List of Rhino.Geometry.Point3d objects to sort
    crv : Rhino.Geometry.Curve
        Reference curve to sort points along

    Returns
    -------
    list
        Points sorted by ascending parameter value along the curve
    """
    pts = sorted(pts, key=lambda x: rs.CurveClosestPoint(crv, x))
    return pts

def sort_AB_along_crv(pt0, pt1, crv):
    """Sort two points along a curve in ascending parameter order.

    Parameters
    ----------
    pt0 : Rhino.Geometry.Point3d
        First point to sort
    pt1 : Rhino.Geometry.Point3d
        Second point to sort
    crv : Rhino.Geometry.Curve
        Reference curve to sort points along

    Returns
    -------
    tuple
        (pt0, pt1) sorted so that pt0's parameter value is less than pt1's.
        For closed curves, points are sorted to minimize the parameter distance
        between them across the seam.

    Notes
    -----
    - Uses normalized curve parameters for comparison
    - Handles both open and closed curves
    - For closed curves, checks if sorting across the seam gives shorter parameter distance
    """
    t0 = rs.CurveClosestPoint(crv,pt0)
    t1 = rs.CurveClosestPoint(crv,pt1)
    t0 = rs.CurveNormalizedParameter(crv, t0)
    t1 = rs.CurveNormalizedParameter(crv, t1)


    if t1 < t0:
        t0, t1 = t1, t0
        pt0, pt1 = pt1, pt0

    if not rs.IsCurveClosed(crv):
        return pt0, pt1

    if abs(t1 - t0) > abs(t0) + abs(1-t1):
        pt0, pt1 = pt1, pt0

    return pt0, pt1



def get_center(obj):
    """Get the center point of an object's bounding box.

    Parameters
    ----------
    obj : Guid
        Object ID to calculate center for

    Returns
    -------
    Rhino.Geometry.Point3d or None
        Center point of the object's bounding box, or None if object is invalid
    """
    try:
        # Check if object exists and is valid
        if not rs.IsObject(obj):
            print("Warning: Object {} is not valid".format(obj))
            return None
            
        corners = rs.BoundingBox(obj)
        if not corners or len(corners) < 7:
            print("Warning: Could not get bounding box for object {}".format(obj))
            return None
            
        min = corners[0]
        max = corners[6]
        center = (min + max)/2
        return center
        
    except Exception as e:
        try:
            corners = rs.BoundingBox(obj)
            min = corners[0]
            max = corners[6]
            center = (min + max)/2
            return center
        except Exception as e:
            print("Error getting center for object {}: {}".format(obj, str(e)))
            return None

def get_obj_h(obj):
    """Get the height (Z dimension) of an object's bounding box.

    Parameters
    ----------
    obj : Guid
        Object ID to calculate height for

    Returns
    -------
    float or None
        Height of the object's bounding box, or None if object is invalid
    """
    try:
        # Check if object exists and is valid
        if not rs.IsObject(obj):
            print("Warning: Object {} is not valid".format(obj))
            return None
            
        corners = rs.BoundingBox(obj)
        if not corners or len(corners) < 7:
            print("Warning: Could not get bounding box for object {}".format(obj))
            return None
            
        min = corners[0]
        max = corners[6]
        z_diff = (max.Z - min.Z)
        return z_diff
        
    except Exception as e:
        print("Error getting height for object {}: {}".format(obj, str(e)))
        return None

def get_boundingbox_edge_length(obj):
    """Get the lengths of bounding box edges in X, Y, and Z directions.

    Parameters
    ----------
    obj : Guid
        Object ID to calculate bounding box dimensions for

    Returns
    -------
    tuple or None
        (X_length, Y_length, Z_length) of the bounding box edges, or None if object is invalid
    """
    try:
        # Check if object exists and is valid
        if not rs.IsObject(obj):
            print("Warning: Object {} is not valid".format(obj))
            return None
            
        corners = rs.BoundingBox(obj)
        if not corners or len(corners) < 7:
            print("Warning: Could not get bounding box for object {}".format(obj))
            return None
            
        X = rs.Distance(corners[0], corners[1])
        Y = rs.Distance(corners[1], corners[2])
        Z = rs.Distance(corners[0], corners[5])
        return X, Y, Z
        
    except Exception as e:
        print("Error getting bounding box edge length for object {}: {}".format(obj, str(e)))
        return None


def get_obj_min_center_pt(obj):
    """Get the center point of the minimum face of an object's bounding box.

    Parameters
    ----------
    obj : Guid
        Object ID to calculate minimum face center for

    Returns
    -------
    Rhino.Geometry.Point3d or None
        Center point of the minimum (bottom) face of the bounding box, or None if object is invalid
    """
    try:
        # Check if object exists and is valid
        if not rs.IsObject(obj):
            print("Warning: Object {} is not valid".format(obj))
            return None
            
        pts = rs.BoundingBox(obj)
        if not pts or len(pts) < 3:
            print("Warning: Could not get bounding box for object {}".format(obj))
            return None
            
        pt0 = pts[0]
        pt1 = pts[2]
        return (pt0 + pt1)/2
        
    except Exception as e:
        print("Error getting minimum center point for object {}: {}".format(obj, str(e)))
        return None


def get_instance_geo(block_instance):
    """Get all geometry objects from a block instance, including nested instances.

    Parameters
    ----------
    block_instance : Guid
        Block instance ID to extract geometry from

    Returns
    -------
    list
        All geometry objects contained in the block instance, transformed to 
        world coordinates

    Notes
    -----
    - Recursively processes nested block instances
    - Applies block instance transformation to all geometry
    - Returns actual geometry objects, not references
    """
    try:
        # Check if document is available
        if not sc.doc:
            print("Warning: No active document found")
            return []
            
        block_name = rs.BlockInstanceName(block_instance)
        non_block_objs, block_instance_objs = [], []

        for x in rs.BlockObjects(block_name):
            (block_instance_objs if rs.IsBlockInstance(x) else non_block_objs).append(x)
            
        non_block_geos = []
        for x in non_block_objs:
            try:
                obj = sc.doc.Objects.Find(x)
                if obj and obj.Geometry:
                    non_block_geos.append(obj.Geometry)
            except Exception as e:
                print("Warning: Could not get geometry for object {}: {}".format(x, str(e)))
                continue
                
        block_geos = []
        for x in block_instance_objs:
            try:
                block_geos.extend(get_instance_geo(x))
            except Exception as e:
                print("Warning: Could not process nested block instance {}: {}".format(x, str(e)))
                continue
                
        geo_contents = non_block_geos + block_geos
        
        transform = rs.BlockInstanceXform(block_instance)
        [x.Transform(transform) for x in geo_contents]
        return geo_contents
        
    except Exception as e:
        print("Error getting instance geometry for block {}: {}".format(block_instance, str(e)))
        return []


def geo_to_obj(geo, name = None):
    """Convert a Rhino geometry object to a native Rhino object.

    Parameters
    ----------
    geo : Rhino.Geometry.GeometryBase
        The geometry object to convert

    Returns
    -------
    Rhino.Geometry.GeometryBase or None
        The converted geometry object, or None if conversion fails
    """
    try:
        # Get the active document
        doc = Rhino.RhinoDoc.ActiveDoc
        if not doc:
            print("Warning: No active Rhino document found")
            return None
            
        if isinstance(geo, Rhino.Geometry.Point3d):
            out_obj = doc.Objects.AddPoint(geo)
        elif isinstance(geo, Rhino.Geometry.Curve):
            out_obj = doc.Objects.AddCurve(geo)
        elif isinstance(geo, Rhino.Geometry.Brep):
            out_obj = doc.Objects.AddBrep(geo)
        elif isinstance(geo, Rhino.Geometry.Mesh):
            out_obj = doc.Objects.AddMesh(geo)
        elif isinstance(geo, Rhino.Geometry.Surface):
            out_obj = doc.Objects.AddSurface(geo)
        elif isinstance(geo, Rhino.Geometry.Hatch):
            out_obj = doc.Objects.AddHatch(geo)
        elif isinstance(geo, Rhino.Geometry.Text):
            out_obj = doc.Objects.AddText(geo)
        elif isinstance(geo, Rhino.Geometry.TextDot):
            out_obj = doc.Objects.AddTextDot(geo)
        else:
            print("Unsupported geometry type: {}".format(type(geo)))
            return None

        if name and out_obj:
            out_obj.Attributes.Name = name
            out_obj.CommitChanges()
        return out_obj
        
    except Exception as e:
        print("Error converting geometry to object: {}".format(str(e)))
        return None