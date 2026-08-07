#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Geometry Extractor Module - Extracts area boundary geometry for 3D visualization
Handles boundary segment extraction and conversion to JSON-serializable point lists
"""

from Autodesk.Revit import DB # pyright: ignore
import json


class AreaGeometryExtractor:
    """Extract area boundary geometry for visualization"""
    
    def __init__(self, area_element):
        """
        Initialize geometry extractor
        
        Args:
            area_element: Revit Area element
        """
        self.area = area_element
        self.boundary_loops = []
        self.is_valid = False
        self.error_message = None
    
    def extract_geometry(self):
        """
        Extract boundary geometry from area element
        
        Returns:
            dict: Geometry data structure or None if extraction fails
        """
        try:
            # Get boundary segments
            options = DB.SpatialElementBoundaryOptions()
            boundary_segments = self.area.GetBoundarySegments(options)
            
            if not boundary_segments or len(boundary_segments) == 0:
                self.error_message = "No boundary segments found"
                return None
            
            # Get level elevation for Z coordinate
            level = self.area.Level
            if not level:
                self.error_message = "Area not placed on level"
                return None
            
            level_elevation = level.Elevation
            
            # Process each boundary loop (outer boundary + holes)
            for loop_index, segment_list in enumerate(boundary_segments):
                if not segment_list or len(segment_list) == 0:
                    continue
                
                loop_points = []
                
                # Process each segment in the loop
                for segment in segment_list:
                    try:
                        curve = segment.GetCurve()
                        if not curve:
                            continue
                        
                        # Extract points from curve
                        points = self._extract_points_from_curve(curve, level_elevation)
                        
                        # Add points to loop (avoid duplicating endpoints between segments)
                        if len(loop_points) == 0:
                            loop_points.extend(points)
                        else:
                            # Skip first point of current segment if it matches last point
                            if len(points) > 0:
                                last_pt = loop_points[-1]
                                first_pt = points[0]
                                if not self._points_are_close(last_pt, first_pt):
                                    loop_points.extend(points)
                                else:
                                    # Skip duplicate, add rest
                                    loop_points.extend(points[1:])
                    
                    except Exception as e:
                        # Continue processing other segments even if one fails
                        print("Warning: Failed to process segment: {}".format(str(e)))
                        continue
                
                # Add loop if valid (at least 3 points for a polygon)
                if len(loop_points) >= 3:
                    # First loop is typically outer boundary, rest are holes
                    is_outer = (loop_index == 0)
                    
                    self.boundary_loops.append({
                        'is_outer': is_outer,
                        'points': loop_points
                    })
            
            if len(self.boundary_loops) > 0:
                self.is_valid = True
                
                # Build complete geometry data structure
                geometry_data = {
                    'boundary_loops': self.boundary_loops,
                    'level_elevation': level_elevation,
                    'level_name': level.Name
                }
                
                return geometry_data
            else:
                self.error_message = "No valid boundary loops found"
                return None
        
        except Exception as e:
            self.error_message = "Geometry extraction error: {}".format(str(e))
            return None
    
    def _extract_points_from_curve(self, curve, z_elevation):
        """
        Extract points from a Revit curve
        
        Args:
            curve: Revit Curve object
            z_elevation: Z coordinate (level elevation)
        
        Returns:
            list: List of (x, y, z) tuples
        """
        points = []
        
        try:
            # Check if curve is a line
            if isinstance(curve, DB.Line):
                # For lines, just get start and end points
                start_pt = curve.GetEndPoint(0)
                end_pt = curve.GetEndPoint(1)
                
                points.append((start_pt.X, start_pt.Y, z_elevation))
                points.append((end_pt.X, end_pt.Y, z_elevation))
            
            else:
                # For arcs and other curves, tessellate to get polyline approximation
                # Tessellate returns IList<XYZ>
                tessellated_points = curve.Tessellate()
                
                for pt in tessellated_points:
                    points.append((pt.X, pt.Y, z_elevation))
        
        except Exception as e:
            print("Warning: Failed to extract points from curve: {}".format(str(e)))
            # Fallback: try to get any points we can
            try:
                if hasattr(curve, 'GetEndPoint'):
                    start_pt = curve.GetEndPoint(0)
                    end_pt = curve.GetEndPoint(1)
                    points.append((start_pt.X, start_pt.Y, z_elevation))
                    points.append((end_pt.X, end_pt.Y, z_elevation))
            except:
                pass
        
        return points
    
    def _points_are_close(self, pt1, pt2, tolerance=0.001):
        """
        Check if two points are within tolerance (to avoid duplicates)
        
        Args:
            pt1: (x, y, z) tuple
            pt2: (x, y, z) tuple
            tolerance: Distance tolerance in feet
        
        Returns:
            bool: True if points are close enough to be considered same
        """
        dx = pt1[0] - pt2[0]
        dy = pt1[1] - pt2[1]
        dz = pt1[2] - pt2[2]
        
        distance_sq = dx*dx + dy*dy + dz*dz
        tolerance_sq = tolerance * tolerance
        
        return distance_sq < tolerance_sq


def extract_area_geometry(area_element, department=None, program_type=None, 
                          program_type_detail=None, area_sf=0, color=None):
    """
    Extract geometry from area element and build complete data structure
    
    Args:
        area_element: Revit Area element
        department: Department name (optional, for metadata)
        program_type: Program type/division (optional)
        program_type_detail: Room name (optional)
        area_sf: Area square footage (optional)
        color: Department color (optional, hex string or RGB tuple)
    
    Returns:
        dict: Complete geometry data structure or None if extraction fails
    """
    extractor = AreaGeometryExtractor(area_element)
    geometry_data = extractor.extract_geometry()
    
    if geometry_data is None:
        return None
    
    # Get element ID (Revit 2024+ uses Value, older use IntegerValue)
    from EnneadTab.REVIT import REVIT_APPLICATION
    element_id = REVIT_APPLICATION.get_element_id_value(area_element.Id)
    
    # Build complete data structure
    complete_data = {
        'area_id': element_id,
        'department': department or '',
        'program_type': program_type or '',
        'program_type_detail': program_type_detail or '',
        'level_name': geometry_data['level_name'],
        'level_elevation': geometry_data['level_elevation'],
        'boundary_loops': geometry_data['boundary_loops'],
        'area_sf': area_sf,
        'color': color
    }
    
    return complete_data


def extract_geometries_for_areas(areas_list):
    """
    Extract geometry for multiple areas
    
    Args:
        areas_list: List of area objects (dicts with 'revit_element' and metadata)
    
    Returns:
        list: List of geometry data structures (successful extractions only)
    """
    geometries = []
    
    for area_obj in areas_list:
        try:
            area_element = area_obj.get('revit_element')
            if not area_element:
                continue
            
            # Extract geometry with metadata
            geometry = extract_area_geometry(
                area_element,
                department=area_obj.get('department'),
                program_type=area_obj.get('program_type'),
                program_type_detail=area_obj.get('program_type_detail'),
                area_sf=area_obj.get('area_sf', 0),
                color=area_obj.get('color')  # Will be added later from color scheme
            )
            
            if geometry:
                geometries.append(geometry)
        
        except Exception as e:
            print("Warning: Failed to extract geometry for area: {}".format(str(e)))
            continue
    
    return geometries


def convert_geometries_to_json(geometries):
    """
    Convert geometry data structures to JSON string
    
    Args:
        geometries: List of geometry data dicts
    
    Returns:
        str: JSON string
    """
    try:
        # Ensure all data is JSON-serializable
        # Python 2.7 compatible JSON serialization
        json_str = json.dumps(geometries, indent=2)
        return json_str
    except Exception as e:
        print("Error converting geometries to JSON: {}".format(str(e)))
        return "[]"


if __name__ == "__main__":
    print("Geometry Extractor Module - Use extract_area_geometry() or extract_geometries_for_areas()")

