#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Mass family creation classes for Area2Mass conversion."""

import os
from Autodesk.Revit import DB # pyright: ignore 
from Autodesk.Revit import ApplicationServices # pyright: ignore 

from EnneadTab import ERROR_HANDLE
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_GEOMETRY, REVIT_SELECTION, REVIT_MATERIAL


class MassFamilyCreator:
    """Creates mass families from boundary data."""
    
    def __init__(self, template_path, family_name, extrusion_height, element_type=None, department=None):
        self.template_path = template_path
        self.family_name = family_name
        self.extrusion_height = extrusion_height
        self.element_type = element_type
        self.department = department
        self.family_doc = None
        self.debug_info = []
        
    def add_debug_info(self, message):
        """Add debug information."""
        self.debug_info.append(message)
        ERROR_HANDLE.print_note("DEBUG: {}".format(message))
    
    def create_from_boundaries(self, boundary_segments):
        """Create mass family from boundary segments."""
        # Validate boundary segments
        if not boundary_segments:
            ERROR_HANDLE.print_note("No boundary segments provided")
            return None
        
        # Create family document from template
        self.family_doc = self._create_family_doc_from_template()
        if not self.family_doc:
            ERROR_HANDLE.print_note("Failed to create family document from template")
            return None
        
        # Start transaction for family creation operations
        t = DB.Transaction(self.family_doc, "Create Mass Family")
        t.Start()
        
        try:
            # Create mass geometry
            geometry_result = self._create_mass_geometry(boundary_segments)
            if not geometry_result:
                ERROR_HANDLE.print_note("Failed to create mass geometry")
                t.RollBack()
                return None
            
            t.Commit()
            return self.family_doc
            
        except Exception as e:
            ERROR_HANDLE.print_note("Exception during mass family creation: {}".format(str(e)))
            t.RollBack()
            return None
    
    def _create_family_doc_from_template(self):
        """Create a family document from template path."""
        # Always use .rfa files for mass families to ensure proper template type
        if self.template_path.lower().endswith('.rfa'):
            # For .rfa files, open directly
            app = REVIT_APPLICATION.get_app()
            family_doc = app.OpenDocumentFile(self.template_path)
            if family_doc:
                return family_doc
        else:
            # If we have .rft, try to find the corresponding .rfa
            rfa_path = self.template_path.replace('.rft', '.rfa')
            if os.path.exists(rfa_path):
                app = REVIT_APPLICATION.get_app()
                family_doc = app.OpenDocumentFile(rfa_path)
                if family_doc:
                    return family_doc
        
        ERROR_HANDLE.print_note("Failed to create family document from template")
        return None
    
    def _create_mass_geometry(self, boundary_segments):
        """Create mass geometry from boundary segments."""
        if not self.family_doc:
            ERROR_HANDLE.print_note("No family document available for geometry creation")
            return False
            
        # Create extrusion directly from the boundary segments structure
        # GetBoundarySegments returns IList<IList<BoundarySegment>> which is perfect for NewExtrusion
        extrusion_result = self._create_extrusion_from_boundary_segments(boundary_segments)
        if not extrusion_result:
            ERROR_HANDLE.print_note("Failed to create extrusion from boundary segments")
            return False
        
        return True
    
    def _create_extrusion_from_boundary_segments(self, boundary_segments):
        """Create extrusion from boundary segments using NewExtrusionForm for mass families.
        
        GetBoundarySegments returns IList<IList<BoundarySegment>> which needs to be converted
        to ReferenceArray for NewExtrusionForm method.
        """
        # Validate boundary segments
        if not boundary_segments or len(boundary_segments) == 0:
            ERROR_HANDLE.print_note("No boundary segments provided")
            return False
        
        # Build ReferenceArray by creating ModelCurves on a SketchPlane, then collecting their References
        # NewExtrusionForm requires references to curve elements existing in the family doc
        origin = DB.XYZ(0, 0, 0)
        normal = DB.XYZ.BasisZ
        plane = DB.Plane.CreateByNormalAndOrigin(normal, origin)
        sketch_plane = DB.SketchPlane.Create(self.family_doc, plane)

        if not self.family_doc:
            ERROR_HANDLE.print_note("No family document available for creating model curves")
            return False
        factory = self.family_doc.FamilyCreate

        reference_array = DB.ReferenceArray()

        for i, segment_list in enumerate(boundary_segments):
            if not segment_list:
                continue

            valid_refs_in_list = 0
            for j, segment in enumerate(segment_list):
                curve = segment.GetCurve()
                if curve is None:
                    continue

                # Ensure curve is on the sketch plane (ground) by projecting/moving to plane
                flat_curve = REVIT_GEOMETRY.project_crv_to_ground(curve)

                # Create ModelCurve to obtain a stable Reference to feed NewExtrusionForm
                model_curve = factory.NewModelCurve(flat_curve, sketch_plane)
                if model_curve is None:
                    continue

                # Per API, we can construct a Reference from the element or use model_curve.Reference
                ref = DB.Reference(model_curve)
                reference_array.Append(ref)
                valid_refs_in_list += 1

            if valid_refs_in_list == 0:
                ERROR_HANDLE.print_note("List {}: no valid curve references created".format(i))
        
        if reference_array.Size == 0:
            ERROR_HANDLE.print_note("No valid references created")
            return False
        
        # Get default height for extrusion direction
        height = self.extrusion_height
        direction = DB.XYZ(0, 0, height)  # Extrude in Z direction
        
        # Create extrusion using NewExtrusionForm
        if not self.family_doc:
            ERROR_HANDLE.print_note("No family document available for extrusion")
            return False
            
        factory = self.family_doc.FamilyCreate
        
        # Use NewExtrusionForm which is designed for mass families
        form = factory.NewExtrusionForm(True, reference_array, direction)
        
        if form:
            # Assign subcategory and material based on element type and department
            try:
                self._tag_form_with_subcategory_and_material(form)
            except Exception as e:
                ERROR_HANDLE.print_note("Failed to tag form with subcategory/material: {}".format(str(e)))
            return True
        else:
            ERROR_HANDLE.print_note("Failed to create mass extrusion form")
            return False
    

    
    def get_debug_summary(self):
        """Get summary of debug information."""
        return "\n".join(self.debug_info)

    def _tag_form_with_subcategory_and_material(self, form):
        """Create/assign subcategory and material to the created mass form.
        Subcategory name: AreaMass_{Department} or RoomMass_{Department}
        Material: same name as subcategory, diffuse per color scheme, transparency 70%.
        """
        if not self.element_type or not self.department:
            return

        dept = str(self.department) if self.department else "NA"
        subcat_name = "{}Mass_{}".format("Area" if self.element_type == "Area" else "Room", dept)

        cat = self.family_doc.OwnerFamily.FamilyCategory if self.family_doc and self.family_doc.OwnerFamily else None
        if not cat:
            return

        # Ensure subcategory exists
        subcat = None
        try:
            for sc in cat.SubCategories:
                if sc.Name == subcat_name:
                    subcat = sc
                    break
            if subcat is None:
                if self.family_doc and self.family_doc.Settings:
                    subcat = self.family_doc.Settings.Categories.NewSubcategory(cat, subcat_name)
                    if not subcat:
                        ERROR_HANDLE.print_note("Failed to create subcategory: {}".format(subcat_name))
                        return
        except Exception as e:
            ERROR_HANDLE.print_note("Failed to create/get subcategory: {}".format(str(e)))
            return

        # Assign subcategory to the form
        try:
            form.Subcategory = subcat
        except Exception as e:
            ERROR_HANDLE.print_note("Failed to assign subcategory to form: {}".format(str(e)))

        # Create or get material using REVIT_MATERIAL module
        mat_name = subcat_name
        # Sanitize material name to ensure it's valid for Revit
        original_mat_name = mat_name
        mat_name = REVIT_MATERIAL.sanitize_material_name(mat_name)
        
        material = None
        try:
            # First try to get existing material
            material = REVIT_MATERIAL.get_material_by_name(mat_name, self.family_doc)
            if not material:
                # Create new material if it doesn't exist
                material_id = DB.Material.Create(self.family_doc, mat_name)
                if self.family_doc:
                    material = self.family_doc.GetElement(material_id)
                    if not material:
                        ERROR_HANDLE.print_note("Failed to get created material: {}".format(mat_name))
                        return
        except Exception as e:
            ERROR_HANDLE.print_note("Failed to create/get material: {}".format(str(e)))
            return

        # Compute color from department (simple hash to color)
        hashcode = abs(hash(dept))
        r = (hashcode & 0xFF)
        g = (hashcode >> 8) & 0xFF
        b = (hashcode >> 16) & 0xFF
        color = DB.Color(r, g, b)

        # Set material appearance using REVIT_MATERIAL.update_material_setting
        if material:
            try:
                # Create material settings map following the standard format
                material_settings = {
                    mat_name: {
                        "Color": (r, g, b),
                        "Transparency": 30,
                        "SurfaceForegroundPatternIsSolid": True,
                        "SurfaceForegroundPatternColor": (r, g, b)
                    }
                }
                
                # Update material properties using the standardized function
                REVIT_MATERIAL.update_material_setting(self.family_doc, material_settings)
                
            except Exception as e:
                ERROR_HANDLE.print_note("Failed to set material properties: {}".format(str(e)))
            
            # Assign material to subcategory if successful
            try:
                if subcat and material:
                    subcat.Material = material
            except Exception as e:
                ERROR_HANDLE.print_note("Failed to assign material to subcategory: {}".format(str(e)))


if __name__ == "__main__":
    """Test the MassFamilyCreator class when run as main module."""
    print("MassFamilyCreator module - This module provides mass family creation functionality.")
    print("To test this module, run it within a Revit environment with proper document context.")
