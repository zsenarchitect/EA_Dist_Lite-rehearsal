#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Rhino-specific processing for room2diagram export.
"""

import clr  # pyright: ignore
import os

try:
    import System  # pyright: ignore
    clr.AddReference('RhinoCommon')
    import Rhino  # pyright: ignore
    IMPORT_OK = True
except:
    IMPORT_OK = False

# Try to import RhinoInside converters if available
try:
    clr.AddReference('RhinoInside.Revit')
    from RhinoInside.Revit.Convert.Geometry import GeometryDecoder as RIR_DECODER  # pyright: ignore
    from RhinoInside.Revit.Convert.Geometry import GeometryEncoder as RIR_ENCODER  # pyright: ignore
    RIR_IMPORT_OK = True
except:
    RIR_IMPORT_OK = False

from EnneadTab import FOLDER, ENVIRONMENT
from EnneadTab.REVIT import REVIT_RHINO, REVIT_UNIT
from Autodesk.Revit import DB # pyright: ignore
from base_processor import BaseProcessor


class RhinoProcess(BaseProcessor):
    """Handles Rhino-specific processing for diagram export."""
    
    def __init__(self, revit_doc, fillet_radius, offset_distance):
        """Initialize Rhino processor.
        
        Args:
            revit_doc: Active Revit document
            fillet_radius: Corner fillet radius in feet
            offset_distance: Inner offset distance in feet
        """
        BaseProcessor.__init__(self, revit_doc, fillet_radius, offset_distance)
        
        self.rhino_doc = None
        self.current_level_name = None
        self.current_output_file = None
    
    def _setup_rhino_doc(self, level_name):
        """Setup Rhino document for export with level-specific file."""
        # Create level-specific output file name
        safe_level_name = "".join(c for c in level_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_level_name = safe_level_name.replace(' ', '_')
        self.current_level_name = safe_level_name
        self.current_output_file = FOLDER.get_local_dump_folder_file("{}BubbleDiagram_{}.3dm".format(ENVIRONMENT.PLUGIN_NAME, safe_level_name))
        
        # Setup Rhino document
        self.rhino_doc = REVIT_RHINO.setup_rhino_doc(self.revit_doc)
        self.rhino_doc.HatchPatterns.Add(Rhino.DocObjects.HatchPattern.Defaults.Solid)
    
    def _get_layer(self, layer_name, color=None):
        """Get or create a Rhino layer with specified name and color."""
        if not self.rhino_doc:
            return None
        layer = self.rhino_doc.Layers.FindName(layer_name)
        if not layer:
            layer = Rhino.DocObjects.Layer()
            layer.Name = layer_name
            if color:
                layer.Color = color
            self.rhino_doc.Layers.Add(layer)
            layer = self.rhino_doc.Layers.FindName(layer_name)
        return layer
    
    def _create_filleted_curve(self, curve, space_color_identifier):
        """Create filleted curve with offset if specified using shared processor."""
        if not self.rhino_doc:
            return None
        
        # Use base class curve processing
        processed_curves = self.process_curves([curve], "rhino")
        
        if processed_curves and len(processed_curves) > 0:
            curve = processed_curves[0]
        else:
            # Fallback to original curve if processing fails
            print("Curve processing failed - using original curve")
        
        # Add outline to Rhino
        if not self.rhino_doc:
            return curve
            
        attr = Rhino.DocObjects.ObjectAttributes()
        layer = self._get_layer("_Outline::" + space_color_identifier)
        if layer:
            attr.LayerIndex = layer.Index
            self.rhino_doc.Objects.AddCurve(curve, attr)
        
        return curve
    
    def _create_and_add_hatch(self, curve, space_color_identifier):
        """Create and add hatch for the curve."""
        if not self.rhino_doc:
            return
            
        attr = Rhino.DocObjects.ObjectAttributes()
        revit_color = self.color_dict[space_color_identifier]
        layer_color = System.Drawing.Color.FromArgb(revit_color.Red, revit_color.Green, revit_color.Blue)
        layer = self._get_layer("_Hatch::" + space_color_identifier, layer_color)
        if layer:
            attr.LayerIndex = layer.Index

        solid_pattern = Rhino.DocObjects.HatchPattern.Defaults.Solid
        hatch_pattern_index = solid_pattern.Index
        tolerance = self.rhino_doc.ModelAbsoluteTolerance
        breps = Rhino.Geometry.Brep.CreatePlanarBreps([curve], tolerance)
        if not breps:
            print("No hatch created for some shape, maybe radius too small or there is a gap in your line.")
            return
        for brep in breps:
            face_index = brep.Faces.Count - 1
            hatch = Rhino.Geometry.Hatch.CreateFromBrep(brep, 
                                                    face_index, 
                                                    hatch_pattern_index,
                                                    Rhino.RhinoMath.ToRadians(0), 
                                                    1,
                                                    Rhino.Geometry.Point3d.Origin)
            self.rhino_doc.Objects.AddHatch(hatch, attr)
    
    def _write_rhino_file(self):
        """Write Rhino file to disk."""
        if not self.rhino_doc or not self.current_output_file:
            return
            
        write_option = Rhino.FileIO.FileWriteOptions()
        write_option.FileVersion = 7
        self.rhino_doc.Write3dmFile(self.current_output_file, write_option)
        self.rhino_doc.Dispose()
        print("Successfully exported Revit Spaces to Rhino file: {}".format(self.current_output_file))
        if self.current_output_file:
            os.startfile(self.current_output_file)
    
    def _process_space_for_rhino(self, space_data):
        """Process a single space for Rhino export."""
        if not self.rhino_doc:
            return False
            
        space = space_data['space']
        space_color_identifier = space_data['identifier']
        space_area = space_data['area']
        boundary_curves = space_data['curves']

        # Add text label with area
        label_layer = self._get_layer("_Label", System.Drawing.Color.Black)
        if label_layer:
            label_attr = Rhino.DocObjects.ObjectAttributes()
            label_attr.LayerIndex = label_layer.Index

            text_content = "{}\n{} SF".format(space_color_identifier, space_area)
            text_geo = Rhino.Display.Text3d(text_content)
            text_geo.HorizontalAlignment = Rhino.DocObjects.TextHorizontalAlignment.Center
            # Create text plane safely - avoid casting issues
            try:
                if RIR_IMPORT_OK:
                    # Use RhinoInside converter if available
                    text_geo.TextPlane = RIR_DECODER.ToPlane(DB.Plane.CreateByNormalAndOrigin(DB.XYZ(0,0,1), space.Location.Point))
                else:
                    # Fallback: create Rhino plane directly
                    space_point = space.Location.Point
                    origin = Rhino.Geometry.Point3d(space_point.X, space_point.Y, space_point.Z)
                    normal = Rhino.Geometry.Vector3d(0, 0, 1)
                    text_geo.TextPlane = Rhino.Geometry.Plane(origin, normal)
            except Exception as plane_error:
                print("Warning: Failed to create text plane: {}. Using default plane.".format(str(plane_error)))
                # Use default plane as fallback
                text_geo.TextPlane = Rhino.Geometry.Plane.WorldXY
            self.rhino_doc.Objects.AddText(text_geo, label_attr)

        # Process boundary curves (convert from Revit to Rhino format)
        if boundary_curves:
            # Convert Revit curves to Rhino curves first
            rhino_curves = self._convert_to_rhino_curves(boundary_curves, "revit")
            
            if rhino_curves and len(rhino_curves) > 0:
                # Join curves if multiple
                if len(rhino_curves) > 1:
                    try:
                        joined_curves = Rhino.Geometry.Curve.JoinCurves(rhino_curves)
                        if joined_curves and len(joined_curves) > 0:
                            curve = joined_curves[0]
                        else:
                            curve = rhino_curves[0]  # Fallback to first curve if join fails
                    except Exception as join_error:
                        print("Warning: Failed to join curves: {}. Using first curve.".format(str(join_error)))
                        curve = rhino_curves[0]
                else:
                    curve = rhino_curves[0]
                
                filleted_crv = self._create_filleted_curve(curve, space_color_identifier)
                if filleted_crv:
                    self._create_and_add_hatch(filleted_crv, space_color_identifier)
            else:
                print("Warning: No valid Rhino curves converted from boundary curves")
        
        return True
    
    def _process_spaces_for_rhino(self, results):
        """Process spaces for Rhino export."""
        try:
            # Get level name and processed spaces
            level_name = results.get('level_name', 'Unknown_Level')
            processed_spaces = results.get('processed_spaces', [])
            
            print("Processing {} spaces for Rhino export (Level: {})".format(len(processed_spaces), level_name))
            
            # Setup Rhino document
            self._setup_rhino_doc(level_name)
            
            # Process each space
            for space_data in processed_spaces:
                self._process_space_for_rhino(space_data)
            
            # Write Rhino file
            self._write_rhino_file()
            return True
            
        except Exception as e:
            print("Error in Rhino processing: {}".format(str(e)))
            return False


if __name__ == "__main__":
    pass

