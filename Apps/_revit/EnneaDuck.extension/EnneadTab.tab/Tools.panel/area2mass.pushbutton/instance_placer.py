#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Family instance placement classes for Area2Mass conversion."""

from Autodesk.Revit import DB # pyright: ignore
import datetime
from pyrevit.revit import ErrorSwallower  # pyright: ignore
from EnneadTab import ERROR_HANDLE
from EnneadTab.REVIT import REVIT_FAMILY 


class FamilyInstancePlacer:
    """Places family instances in the project."""
    
    def __init__(self, project_doc, family_name, spatial_element):
        self.project_doc = project_doc
        self.family_name = family_name
        self.spatial_element = spatial_element
        self.debug_info = []
        
    def add_debug_info(self, message):
        """Add debug information."""
        self.debug_info.append(message)
        ERROR_HANDLE.print_note("DEBUG: {}".format(message))
    
    def place_instance(self):
        """Place a family instance at the spatial element location."""
        
        # Start transaction for instance placement
        t = DB.Transaction(self.project_doc, "Place Area2Mass Instance")
        t.Start()
        # Attach a warnings swallower so Revit warning dialogs (e.g., mesh-only mass) are suppressed
        try:
            class _SwallowWarnings(DB.IFailuresPreprocessor):
                def PreprocessFailures(self, failures_accessor):
                    try:
                        for failure_message in list(failures_accessor.GetFailureMessages()):
                            if failure_message.GetSeverity() == DB.FailureSeverity.Warning:
                                failures_accessor.DeleteWarning(failure_message)
                        return DB.FailureProcessingResult.Continue
                    except:
                        return DB.FailureProcessingResult.Continue

            fho = t.GetFailureHandlingOptions()
            fho.SetFailuresPreprocessor(_SwallowWarnings())
            fho.SetClearAfterRollback(True)
            t.SetFailureHandlingOptions(fho)
        except Exception:
            pass
        
        try:
            # Step 1: Get spatial element location
            location = self._get_spatial_element_location()
            if not location:
                t.RollBack()
                return False
            
            # Step 2: Get boundary segments for orientation
            boundary_segments = self._get_boundary_segments()
            if not boundary_segments:
                t.RollBack()
                return False
            
            # Step 3: Get level for hosting
            level = self._get_spatial_element_level()
            if not level:
                t.RollBack()
                return False
            
            # Step 4: Find family symbol
            family_symbol = self._find_family_symbol()
            if not family_symbol:
                t.RollBack()
                return False
            
            # Step 5: If an instance already exists, delete it before placing new
            existing_instances = self._collect_existing_instances(family_symbol)
            if existing_instances:
                try:
                    for inst in existing_instances:
                        self.project_doc.Delete(inst.Id)
                except Exception as e:
                    t.RollBack()
                    return False
            
            # Step 6: Place instance
            try:
                placement_result = self._place_instance_at_location(family_symbol, location, level)
                if not placement_result:
                    t.RollBack()
                    return False
            except Exception as e:
                t.RollBack()
                return False
            
            # Commit transaction
            t.Commit()
            return True
            
        except Exception as e:
            t.RollBack()
            return False
    
    def _collect_existing_instances(self, family_symbol):
        """Collect existing instances of the specified family type to delete.
        This ensures only one instance per area/room by deleting all instances
        of families with matching names before creating a new one."""
        try:
            collector = DB.FilteredElementCollector(self.project_doc).OfClass(DB.FamilyInstance)
            instances = []
            target_family_name = self.family_name
            
            for instance in collector:
                try:
                    if not instance.Symbol:
                        continue
                    
                    # Get family of this instance
                    inst_family = instance.Symbol.Family
                    if not inst_family:
                        continue
                    
                    # Check if family name matches our target family name
                    inst_family_name = inst_family.Name
                    if inst_family_name == target_family_name:
                        instances.append(instance)
                except Exception:
                    pass
            return instances
        except Exception:
            return []
    
    def _get_spatial_element_location(self):
        """Get placement point. Use the actual level location instead of Internal Origin."""
        # Get the level elevation and place at that location
        level = self._get_spatial_element_level()
        if level:
            elevation = level.Elevation
            return DB.XYZ(0, 0, elevation)
        else:
            return DB.XYZ(0, 0, 0)
    
    def _get_boundary_segments(self):
        """Get boundary segments for orientation."""
        options = DB.SpatialElementBoundaryOptions()
        segments = self.spatial_element.GetBoundarySegments(options)
        
        if segments and len(segments) > 0:
            return segments
        else:
            return None
    
    def _get_spatial_element_level(self):
        """Get the level where the spatial element is hosted."""
        
        # Try to get level from spatial element
        if hasattr(self.spatial_element, 'Level'):
            level = self.spatial_element.Level
            if level:
                return level
        
    
        
        return None
    
    def _get_spatial_element_area(self):
        """Get the area of the spatial element in square feet."""
        try:
            # Try to get area from Area parameter
            area_param = self.spatial_element.LookupParameter("Area")
            if area_param:
                area_value = area_param.AsDouble()
                if area_value > 0:
                    # Convert from Revit internal units (square feet) to square feet
                    return area_value
            
            # Fallback: calculate area from boundary segments
            boundary_segments = self._get_boundary_segments()
            if boundary_segments and len(boundary_segments) > 0:
                # Get the first boundary loop
                first_loop = boundary_segments[0]
                if first_loop and len(first_loop) > 0:
                    # Create a curve loop from boundary segments
                    curve_loop = DB.CurveLoop()
                    for segment in first_loop:
                        if segment.GetCurve():
                            curve_loop.Append(segment.GetCurve())
                    
                    # Calculate area using CurveLoop.GetArea()
                    if curve_loop.IsValid:
                        area_value = curve_loop.GetArea()
                        if area_value > 0:
                            return area_value
            
            return None
            
        except Exception as e:
            return None
    
    def _find_family_symbol(self):
        """Find the family symbol to place using REVIT_FAMILY module."""
        
        # Use REVIT_FAMILY.get_all_types_by_family_name to get symbols directly
        family_symbols = REVIT_FAMILY.get_all_types_by_family_name(self.family_name, self.project_doc)
        
        if family_symbols:
            # Get the first available symbol
            first_symbol = family_symbols[0]
            
            # Check if it has the expected attributes - use try/catch instead of hasattr
            try:
                first_symbol.LookupParameter("Type Name").AsString()
            except Exception as e:
                return None
                
            try:
                first_symbol.Id
            except Exception as e:
                return None
                
            # Check if symbol is active and activate if needed
            try:
                is_active = first_symbol.IsActive
                
                if not is_active:
                    first_symbol.Activate()
                    
            except Exception as e:
                return None
                
            return first_symbol
        
        return None
    
    def _place_instance_at_location(self, family_symbol, location, level):
        """Place the family instance at Internal Origin on the specified level, using proven move2origin approach."""
        
        # Ensure symbol is active
        if not family_symbol.IsActive:
            family_symbol.Activate()
        
        # No working plane manipulation needed; avoid Level.GetReference warnings
        
        try:
            # Use correct document creation context (like move2origin does)
            if self.project_doc.IsFamilyDocument:
                doc_create = self.project_doc.FamilyCreate
            else:
                doc_create = self.project_doc.Create
            
            # Create instance using the proven method, suppressing UI warnings
            with ErrorSwallower() as swallower:
                instance = doc_create.NewFamilyInstance(
                    location, family_symbol, level, DB.Structure.StructuralType.NonStructural)
            
        except Exception as e:
            print("Failed to place instance: {}".format(str(e)))
            return False
        
        if not instance:
            return False

        # Set Offset from Host to 0
        try:
            for para_name in ["Elevation from Level", "Offset from Host"]:
                para = instance.LookupParameter(para_name)
                if para and not para.IsReadOnly:
                    para.Set(0)
        except Exception as e:
            pass

        # Pin instance
        try:
            instance.Pinned = True
        except Exception as e:
            pass
        
        # Set area as comment
        try:
            area_value = self._get_spatial_element_area()
            if area_value:
                comment_param = instance.LookupParameter("Comments")
                if comment_param and not comment_param.IsReadOnly:
                    comment_param.Set("Area: {:.2f} sq ft".format(area_value))
        except Exception as e:
            pass

        # Set last updated timestamp in Mark parameter
        try:
            mark_param = instance.LookupParameter("Mark")
            if mark_param and not mark_param.IsReadOnly:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                mark_param.Set(timestamp)
        except Exception:
            pass
        
        return True
    

    
    def get_debug_summary(self):
        """Get summary of debug information."""
        return "\n".join(self.debug_info)
    
    def create_dedicated_3d_view(self):
        """Create a dedicated 3D view for the mass instances."""
        view_name = "AREA2MASS - 3D VIEW"
        
        try:
            # Try to find existing view
            collector = DB.FilteredElementCollector(self.project_doc)
            views = collector.OfClass(DB.View3D).WhereElementIsNotElementType()
            
            for view in views:
                if view.Name == view_name:
                    return view
            
            # Create new 3D view if not found
            
            # Get default 3D view type
            view_family_types = DB.FilteredElementCollector(self.project_doc).OfClass(DB.ViewFamilyType)
            view_family_type = None
            
            for vft in view_family_types:
                if vft.ViewFamily == DB.ViewFamily.ThreeDimensional:
                    view_family_type = vft
                    break
            
            if not view_family_type:
                # Create isometric view
                view = DB.View3D.CreateIsometric(self.project_doc, DB.ElementId.InvalidElementId)
            else:
                view = DB.View3D.CreateIsometric(self.project_doc, view_family_type.Id)
            
            # Set view properties
            view.Name = view_name
            
            # Set view scale and other properties for better visualization
            try:
                view.Scale = 100  # 1:100 scale
            except:
                pass
            
            # Set view to show mass category prominently
            try:
                # Get mass category
                mass_category = self.project_doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Mass)
                if mass_category:
                    # Set category visibility
                    view.SetCategoryHidden(mass_category.Id, False)
            except Exception as e:
                pass
            
            return view
            
        except Exception as e:
            return None


if __name__ == "__main__":
    """Test the FamilyInstancePlacer class when run as main module."""
    print("FamilyInstancePlacer module - This module provides family instance placement functionality.")
    print("To test this module, run it within a Revit environment with proper document context.")
