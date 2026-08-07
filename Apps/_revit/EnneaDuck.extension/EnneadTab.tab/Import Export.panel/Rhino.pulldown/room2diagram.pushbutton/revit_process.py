#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Revit-specific processing for room2diagram export.
"""

# ============================================================================
# RHINOINSIDE IMPORT CHECK - MUST BE FIRST
# ============================================================================
try:
    import clr  # pyright: ignore
    clr.AddReference('RhinoCommon')
    import Rhino  # pyright: ignore
    clr.AddReference('RhinoInside.Revit')
    from RhinoInside.Revit.Convert.Geometry import GeometryEncoder as RIR_ENCODER  # pyright: ignore
    RHINO_IMPORT_OK = True
except:
    RHINO_IMPORT_OK = False

# ============================================================================
# STANDARD IMPORTS
# ============================================================================
import System  # pyright: ignore
from EnneadTab import TIME, SAMPLE_FILE
from EnneadTab.REVIT import REVIT_VIEW, REVIT_SELECTION, REVIT_UNIT, REVIT_FAMILY, REVIT_APPLICATION
from Autodesk.Revit import DB # pyright: ignore
from base_processor import BaseProcessor


class RevitProcess(BaseProcessor):
    """Handles Revit-specific processing for floor plan view export with filled regions."""
    
    def __init__(self, revit_doc, fillet_radius, offset_distance):
        """Initialize Revit processor.
        
        Args:
            revit_doc: Active Revit document
            fillet_radius: Corner fillet radius in feet
            offset_distance: Inner offset distance in feet
        """
        BaseProcessor.__init__(self, revit_doc, fillet_radius, offset_distance)
        print("RevitProcess initialized with fillet_radius={}, offset_distance={}".format(fillet_radius, offset_distance))
    
    def _has_curves(self, curve_loop):
        """Check if a CurveLoop has any curves using iterator approach."""
        if not curve_loop:
            return False
        
        try:
            curve_iterator = curve_loop.GetCurveLoopIterator()
            return curve_iterator.MoveNext()
        except Exception as e:
            print("Error checking curve loop: {}".format(str(e)))
            return False
    
    def _process_curves_for_drafting(self, curve_loop):
        """Process curves for drafting view with fillet and offset operations."""
        if not curve_loop:
            return None
        
        # Convert curve loop to list of curves
        curves = []
        curve_iterator = curve_loop.GetCurveLoopIterator()
        while curve_iterator.MoveNext():
            curves.append(curve_iterator.Current)
        
        print("Processing {} curves with fillet_radius={}, offset_distance={}".format(len(curves), self.fillet_radius, self.offset_distance))
        
        # Use base class curve processing (returns processed Rhino curves)
        processed_rhino_curves = self.process_curves(curves, "revit")
        
        if not processed_rhino_curves:
            return curve_loop  # Return original if processing fails
        
        # Convert processed Rhino curves back to Revit CurveLoop
        return self._convert_rhino_curves_to_curve_loop(processed_rhino_curves)
    
    def _convert_rhino_curves_to_curve_loop(self, rhino_curves):
        """Convert processed Rhino curves to Revit CurveLoop using ToCurveLoop."""
        if not rhino_curves or len(rhino_curves) == 0:
            return None
        
        try:
            # BaseProcessor typically returns a single joined polycurve with fillet and offset applied
            # RIR_ENCODER.ToCurveLoop() can convert this directly to a Revit CurveLoop
            if len(rhino_curves) > 0:
                rhino_curve = rhino_curves[0]  # Get the first (and typically only) curve
                
                if not rhino_curve:
                    return None
                
                if not hasattr(rhino_curve, 'IsValid') or not rhino_curve.IsValid:
                    return None
                
                # Use RIR_ENCODER.ToCurveLoop() to convert the joined polycurve directly to Revit CurveLoop
                try:
                    curve_loop = RIR_ENCODER.ToCurveLoop(rhino_curve)
                    if curve_loop and self._has_curves(curve_loop):
                        return curve_loop
                    else:
                        return None
                except Exception as e:
                    print("Error converting joined polycurve to CurveLoop: {}".format(str(e)))
                    return None
            else:
                return None
            
        except Exception as e:
            print("Error in _convert_rhino_curves_to_curve_loop: {}".format(str(e)))
            return None

    def _create_filled_region_from_curves(self, curve_loop, filled_region_type, floor_plan_view):
        """Create filled region from curve loop."""
        try:
            if not curve_loop or not filled_region_type or not floor_plan_view:
                return False, None
            
            # Create filled region within transaction
            t = DB.Transaction(self.revit_doc, "Create Bubble Diagram Filled Region")
            t.Start()
            try:
                # Create a list of curve loops - DB.FilledRegion.Create expects a collection
                curve_loops = System.Collections.Generic.List[DB.CurveLoop]()
                curve_loops.Add(curve_loop)
                
                # Create filled region
                filled_region = DB.FilledRegion.Create(
                    self.revit_doc,
                    filled_region_type.Id,
                    floor_plan_view.Id,
                    curve_loops
                )
                
                if filled_region:
                    t.Commit()
                    return True, filled_region
                else:
                    t.RollBack()
                    return False, None
                    
            except Exception as e:
                print("Error in transaction creating filled region: {}".format(str(e)))
                t.RollBack()
                return False, None
                
        except Exception as e:
            print("Error creating filled region: {}".format(str(e)))
            return False, None
    
    def _add_comment_to_filled_region(self, filled_region, space_identifier, space_area, space_object):
        """Add comment to filled region with space information including original area and department.
        
        Args:
            filled_region: Revit filled region object
            space_identifier: Space identifier string
            space_area: Area value in square feet
            space_object: Original Revit space object to get parameters from
        """
        try:
            if not filled_region or not space_object:
                return False
            
            # Get original area from space object
            original_area = 0
            try:
                area_param = space_object.LookupParameter("Area")
                if area_param:
                    original_area = area_param.AsDouble()
                    # Convert to square feet if needed
                    original_area_sf = DB.UnitUtils.ConvertFromInternalUnits(original_area, REVIT_UNIT.lookup_unit_id("squareFeet"))
                    original_area_rounded = int(round(original_area_sf)) if original_area_sf > 0 else 0
                else:
                    original_area_rounded = 0
            except Exception as e:
                print("Warning: Could not get original area from space: {}".format(str(e)))
                original_area_rounded = 0
            
            
            
            # Create comment content with original area and department
            comment_content = "{} - {:,} SF".format(space_identifier, original_area_rounded)
            
            # Add comment to filled region within transaction
            t = DB.Transaction(self.revit_doc, "Add Comment to Filled Region")
            t.Start()
            try:
                # Use only the "Comments" parameter per preference
                comment_param = filled_region.LookupParameter("Comments")
                if comment_param and not comment_param.IsReadOnly:
                    comment_param.Set(comment_content)
                    t.Commit()
                    return True
                
                print("Warning: 'Comments' parameter not found or read-only on filled region")
                t.RollBack()
                return False
            except Exception as e:
                print("Error in transaction adding comment: {}".format(str(e)))
                t.RollBack()
                return False
                
        except Exception as e:
            print("Error adding comment to filled region: {}".format(str(e)))
            return False
    
    def _get_or_create_bubble_diagram_tag_family(self):
        """Get or create bubble diagram tag family for filled regions."""
        try:
            # Try to get existing tag family or load from file if not found
            tag_family_name = "BubbleDiagram Tag"
            
            # Use SAMPLE_FILE.get_file to get the family file path
            family_file_path = SAMPLE_FILE.get_file("BubbleDiagram Tag.rfa")
            
            if family_file_path:
                # print("Found BubbleDiagram Tag.rfa at: {}".format(family_file_path))
                # Use get_family_by_name with load_path_if_not_exist parameter
                tag_family = REVIT_FAMILY.get_family_by_name(
                    tag_family_name, 
                    doc=self.revit_doc,
                    load_path_if_not_exist=family_file_path
                )
                
                if tag_family:
                    # print("Successfully loaded BubbleDiagram Tag family")
                    return tag_family
                else:
                    print("Failed to load BubbleDiagram Tag family from file")
                    return None
            else:
                print("BubbleDiagram Tag.rfa not found using SAMPLE_FILE.get_file")
                print("Please ensure the family file is available in the EnneadTab sample files folder")
                return None
                
        except Exception as e:
            print("Error getting or creating tag family: {}".format(str(e)))
            return None
    
    def _create_tag_for_filled_region(self, filled_region, space_identifier, floor_plan_view):
        """Create tag for filled region using tag family and type.
        
        Args:
            filled_region: Revit filled region object
            space_identifier: Space identifier string
            floor_plan_view: Revit floor plan view to create tag in
        """
        try:
            if not filled_region or not floor_plan_view:
                return False
            
            # Get or create tag family
            tag_family = self._get_or_create_bubble_diagram_tag_family()
            if not tag_family:
                print("Warning: Could not create or find tag family. Tags will be skipped.")
                return False
            
            # Find an IndependentTagType to use (by family or name)
            tag_type = None
            try:
                candidate_types = DB.FilteredElementCollector(self.revit_doc) \
                    .OfClass(DB.IndependentTagType) \
                    .WhereElementIsElementType() \
                    .ToElements()
                for tt in candidate_types:
                    try:
                        if hasattr(tt, 'FamilyName') and tt.FamilyName and 'BubbleDiagram' in tt.FamilyName:
                            tag_type = tt
                            break
                        if tt.Name and 'BubbleDiagram' in tt.Name:
                            tag_type = tt
                            break
                    except:
                        continue
                if not tag_type and candidate_types:
                    tag_type = candidate_types[0]
            except Exception as _e:
                tag_type = None
            
            # Create tag within transaction
            t = DB.Transaction(self.revit_doc, "Create Bubble Diagram Tag")
            t.Start()
            try:
                # Create tag for the filled region using the tag type
                # Determine a placement point from the filled region's bounding box (in view coordinates)
                bbox = filled_region.get_BoundingBox(floor_plan_view)
                if bbox and bbox.Min and bbox.Max:
                    center = DB.XYZ(
                        (bbox.Min.X + bbox.Max.X) / 2.0,
                        (bbox.Min.Y + bbox.Max.Y) / 2.0,
                        (bbox.Min.Z + bbox.Max.Z) / 2.0,
                    )
                else:
                    center = DB.XYZ(0, 0, 0)

                # Try to create an IndependentTag first (may not be supported for FilledRegion)
                tag = None
                try:
                    tag = DB.IndependentTag.Create(
                        self.revit_doc,
                        floor_plan_view.Id,
                        DB.Reference(filled_region),
                        False,
                        DB.TagMode.TM_ADDBY_CATEGORY,
                        DB.TagOrientation.Horizontal,
                        center,
                    )
                    if tag and tag_type:
                        try:
                            tag.ChangeTypeId(tag_type.Id)
                        except Exception as change_type_err:
                            print("Warning: Could not change tag type: {}".format(str(change_type_err)))
                except Exception:
                    tag = None
                
                if tag:
                    t.Commit()
                    return True
                

                
            except Exception as e:
                print("Error in transaction creating tag: {}".format(str(e)))
                t.RollBack()
                return False
                
        except Exception as e:
            print("Error creating tag for filled region {}: {}".format(space_identifier, str(e)))
            return False
    
    def _create_get_floor_plan_view(self, level_name, prefix):
        """Create or get existing floor plan view for Revit export and hide all model categories except detail items."""
        try:
            # Create floor plan view name
            view_name = "{}_{}".format(prefix, level_name)
            
            # First check if view already exists - if so, clean it and return it
            existing_view = REVIT_VIEW.get_view_by_name(view_name, self.revit_doc)
            if existing_view:
                print("Found existing floor plan view: '{}'. Cleaning existing filled regions and returning view.".format(view_name))
                
                # Delete all filled regions with type names beginning with _ColorScheme_
                self._delete_existing_color_scheme_filled_regions(existing_view)
                
                return existing_view
            
            # Find the level by name
            level = None
            levels = DB.FilteredElementCollector(self.revit_doc).OfClass(DB.Level).ToElements()
            for lvl in levels:
                if lvl.Name == level_name:
                    level = lvl
                    break
            
            if not level:
                print("Warning: Could not find level '{}', using first available level".format(level_name))
                if levels:
                    level = levels[0]
                else:
                    print("Error: No levels found in document")
                    return None
            
            # Create new floor plan view within transaction
            floor_plan_view = None
            t = DB.Transaction(self.revit_doc, "Create Bubble Diagram Floor Plan View")
            t.Start()
            try:
                # Get the floor plan view type
                view_types = DB.FilteredElementCollector(self.revit_doc).OfClass(DB.ViewFamilyType).ToElements()
                floor_plan_type = None
                for view_type in view_types:
                    if view_type.FamilyName == "Floor Plan":
                        floor_plan_type = view_type
                        break
                
                if not floor_plan_type:
                    print("Warning: Could not find Floor Plan view type, using first available")
                    if view_types:
                        floor_plan_type = view_types[0]
                    else:
                        print("Error: No view plan types found in document")
                        t.RollBack()
                        return None
                
                # Create floor plan view
                floor_plan_view = DB.ViewPlan.Create(self.revit_doc, 
                                                    floor_plan_type.Id, 
                                                    level.Id)
                
                if floor_plan_view:
                    # Set view name
                    floor_plan_view.Name = view_name
                    
                    # Set ViewGroup and ViewSeries properties
                    view_group_param = floor_plan_view.LookupParameter("Views_$Group")
                    if view_group_param and not view_group_param.IsReadOnly:
                        view_group_param.Set("EnneadTab")
                    
                    view_series_param = floor_plan_view.LookupParameter("Views_$Series")
                    if view_series_param and not view_series_param.IsReadOnly:
                        view_series_param.Set("BubbleDiagram")
                    
                    # print("Set Views_$Group to 'EnneadTab' and Views_$Series to 'BubbleDiagram'")
                    
                    # Set view scale to match the original source view
                    try:
                        scale_param = floor_plan_view.LookupParameter("View Scale")
                        if scale_param and not scale_param.IsReadOnly:
                            # Get scale from source view if available
                            if hasattr(self, 'source_view') and self.source_view:
                                try:
                                    source_scale_param = self.source_view.LookupParameter("View Scale")
                                    if source_scale_param:
                                        source_scale = source_scale_param.AsInteger()
                                        scale_param.Set(source_scale)
                                        # print("Set view scale to match source view: 1:{}".format(source_scale))
                                    else:
                                        # Fallback to 1/8" = 1'-0" scale (1:96)
                                        scale_param.Set(96)
                                        print("Set view scale to default 1/8\" = 1'-0\" (source view scale not available)")
                                except Exception as e:
                                    print("Warning: Could not get scale from source view: {}. Using default scale.".format(str(e)))
                                    scale_param.Set(96)
                                    print("Set view scale to default 1/8\" = 1'-0\"")
                            else:
                                # No source view available, use default scale
                                scale_param.Set(96)
                                print("Set view scale to default 1/8\" = 1'-0\" (no source view)")
                    except Exception as e:
                        print("Warning: Could not set view scale: {}".format(str(e)))
                    
                    # Set view discipline to Coordination for better category control
                    try:
                        discipline_param = floor_plan_view.LookupParameter("Discipline")
                        if discipline_param and not discipline_param.IsReadOnly:
                            discipline_param.Set(1)  # 1 = Coordination
                            # print("Set view discipline to Coordination")
                    except Exception as e:
                        print("Warning: Could not set view discipline: {}".format(str(e)))
                    
                    # Configure view categories for bubble diagram
                    self._configure_bubble_diagram_view_categories(floor_plan_view)
                
                t.Commit()
                
            except Exception as e:
                print("Error in transaction creating floor plan view: {}".format(str(e)))
                t.RollBack()
                return None
            
            return floor_plan_view
            
        except Exception as e:
            print("Error creating floor plan view: {}".format(str(e)))
            return None
    
    def _delete_existing_color_scheme_filled_regions(self, view):
        """Delete all filled regions in the view that have type names beginning with '_ColorScheme_'."""
        try:
            # Get all filled regions in the view
            filled_regions = DB.FilteredElementCollector(self.revit_doc, view.Id) \
                .OfClass(DB.FilledRegion) \
                .ToElements()
            
            if not filled_regions:
                return
            
            # Filter filled regions by type name
            regions_to_delete = []
            for region in filled_regions:
                try:
                    # Get the filled region type
                    region_type = self.revit_doc.GetElement(region.GetTypeId())
                    if region_type:
                        # Get type name using LookupParameter("Type Name")
                        type_name_param = region_type.LookupParameter("Type Name")
                        if type_name_param:
                            type_name = type_name_param.AsString()
                            if type_name and type_name.startswith('_ColorScheme_'):
                                regions_to_delete.append(region)
                except Exception as e:
                    print("Warning: Could not check type name for filled region: {}".format(str(e)))
                    continue
            
            if not regions_to_delete:
                return
            
            # Delete the filtered filled regions within a transaction
            t = DB.Transaction(self.revit_doc, "Delete Existing Color Scheme Filled Regions")
            t.Start()
            try:
                for region in regions_to_delete:
                    try:
                        self.revit_doc.Delete(region.Id)
                    except Exception as e:
                        print("Warning: Could not delete filled region: {}".format(str(e)))
                        continue
                
                t.Commit()
                
            except Exception as e:
                print("Error in transaction deleting filled regions: {}".format(str(e)))
                t.RollBack()
                    
        except Exception as e:
            print("Error deleting existing color scheme filled regions: {}".format(str(e)))
    
    def _configure_bubble_diagram_view_categories(self, view):
        """Configure view categories for bubble diagram - hide all except detail items, detail item tags, and grids."""
        try:
            # Define categories to keep visible
            visible_categories = [
                DB.BuiltInCategory.OST_DetailComponents,     # Detail items (detail components)
                DB.BuiltInCategory.OST_DetailComponentTags,  # Detail item tags
                DB.BuiltInCategory.OST_Grids                 # Grids
            ]
            
            print("Starting category configuration for bubble diagram view...")
            
            # Note: This method is called from within an active transaction in _create_get_floor_plan_view
            # so we don't need to create a new transaction here
            # Method 1: Use document settings categories (more reliable approach)
            for category in self.revit_doc.Settings.Categories:
                try:
                    # Skip categories that can't be hidden
                    if not view.CanCategoryBeHidden(category.Id):
                        continue
                    
                    # Check if this category should be visible
                    should_be_visible = category.Id in [DB.Category.GetCategory(self.revit_doc, cat).Id for cat in visible_categories]
                    
                    # Set category visibility using the standard pattern from codebase
                    view.SetCategoryHidden(category.Id, not should_be_visible)
                    
                    # Keep logging minimal; only errors/warnings are printed elsewhere
                        
                except Exception as e:
                    # Some categories might not be controllable, skip them
                    print("Warning: Could not control category {}: {}".format(category.Name, str(e)))
                    continue
            
            # Method 2 removed per request; rely solely on category visibility control above
            
        except Exception as e:
            print("Error hiding categories: {}".format(str(e)))
            import traceback
            print("Full traceback: {}".format(traceback.format_exc()))
    
    def _process_space_for_revit(self, space_data, floor_plan_view):
        """Process a single space for Revit export."""
        try:
            # Handle both space_data dictionary and direct space object
            if isinstance(space_data, dict):
                # Input is a processed space_data dictionary
                space = space_data['space']
                space_identifier = space_data['identifier']
                space_area = space_data['area']
                boundary_curves = space_data['curves']
                revit_color = space_data['color']
                
            else:
                # Input is a direct space object (legacy support)
                space = space_data
                space_identifier = space.LookupParameter(self.para_name).AsString()
                if not space_identifier:
                    return False
                
                # Get area from space object
                try:
                    space_area = int(round(space.Area)) if space.Area > 0 else 0
                except:
                    space_area = 0
                
                # Get color from color dictionary
                revit_color = self.color_dict.get(space_identifier)
                
                # Use boundary curves from space_data (already extracted by BaseProcessor)
                boundary_curves = space_data.get('curves', [])
            
            # Validate color
            if not revit_color:
                print("No color found, skipping space")
                return False
            
            # Get or create filled region type (wrapped in transaction for type creation)
            region_type_name = "_ColorScheme_{}".format(space_identifier)
            
            # First check if type exists
            filled_region_type = REVIT_SELECTION.get_filledregion_type(
                self.revit_doc,
                region_type_name,
                color_if_not_exist=None
            )
            
            # If type doesn't exist, create it within a transaction
            if not filled_region_type:
                t = DB.Transaction(self.revit_doc, "Create Filled Region Type")
                t.Start()
                try:
                    filled_region_type = REVIT_SELECTION.get_filledregion_type(
                        self.revit_doc,
                        region_type_name,
                        color_if_not_exist=(revit_color.Red, revit_color.Green, revit_color.Blue)
                    )
                    t.Commit()
                except Exception as e:
                    print("Error creating filled region type: {}".format(str(e)))
                    t.RollBack()
                    filled_region_type = None
            
            if not filled_region_type:
                print("Could not get or create filled region type")
                return False
            
            # Create filled region and add comment/tag
            filled_region_success = False
            comment_success = False
            tag_success = False
            
            # Process boundary curves and create filled region
            filled_region_success = False
            created_filled_region = None
            #
            if boundary_curves:
                try:
                    # First, process the curves through BaseProcessor to apply fillet and offset
                    #
                    processed_curves = self.process_curves(boundary_curves, "revit")
                    
                    if processed_curves and len(processed_curves) > 0:
                        #
                        
                        # Get the first (and typically only) processed curve from BaseProcessor
                        processed_curve = processed_curves[0]
                        if processed_curve and hasattr(processed_curve, 'IsValid') and processed_curve.IsValid:
                            #
                            try:
                                # Use RIR_ENCODER.ToCurveLoop() to convert the processed curve directly to Revit CurveLoop
                                curve_loop = RIR_ENCODER.ToCurveLoop(processed_curve)
                                if curve_loop and self._has_curves(curve_loop):
                                    #
                                    
                                    # Create filled region with the CurveLoop
                                    try:
                                        filled_region_success, created_filled_region = self._create_filled_region_from_curves(curve_loop, filled_region_type, floor_plan_view)
                                        if filled_region_success:
                                            # print("Created filled region with processed curves (fillet and offset applied)")
                                            pass
                                    except Exception as e:
                                        print("Failed to create filled region with processed curves for space {}: {}".format(space_identifier, str(e)))
                                else:
                                    #
                                    curve_loop = None
                            except Exception as e:
                                #
                                curve_loop = None
                        else:
                            #
                            curve_loop = None
                    else:
                        #
                        curve_loop = None
                    
                    if not curve_loop:
                        print("No valid curve loop created for space: {}".format(space_identifier))
                except Exception as e:
                    print("Error processing boundary curves for space {}: {}".format(space_identifier, str(e)))
            
            # Add comment and tag to the filled region if it was created successfully
            if filled_region_success and created_filled_region:
                try:
                    # Verify filled region creation and list available parameters
                    # print("Verifying filled region creation for space: {}".format(space_identifier))
                    self._verify_filled_region_creation(created_filled_region, space_identifier)
                    
                    # Add comment to filled region
                    # print("Adding comment to filled region for space: {}".format(space_identifier))
                    comment_success = self._add_comment_to_filled_region(created_filled_region, space_identifier, space_area, space)
                    
                    # Create tag for filled region
                    # print("Creating tag for filled region for space: {}".format(space_identifier))
                    tag_success = self._create_tag_for_filled_region(created_filled_region, space_identifier, floor_plan_view)
                except Exception as e:
                    print("Failed to add comment/tag for space {}: {}".format(space_identifier, str(e)))
                    import traceback
                    print("Full traceback: {}".format(traceback.format_exc()))
            
            # Return success if filled region was created successfully
            success = filled_region_success
            if success:
                # print("Successfully processed space: {} (region: {}, comment: {}, tag: {})".format(
                #     space_identifier, filled_region_success, comment_success, tag_success))
                pass
            else:
                print("Failed to process space: {} (region: {}, comment: {}, tag: {})".format(
                    space_identifier, filled_region_success, comment_success, tag_success))
            
            return success
            
        except Exception as e:
            print("Error processing space for Revit: {}".format(str(e)))
            return False
    
    def _process_spaces_for_revit(self, results, source_view=None):
        """Process spaces for Revit export."""
        try:
            # Store source view for use in floor plan creation
            if source_view:
                self.source_view = source_view
            
            # Get level name and processed spaces
            level_name = results.get('level_name', 'Unknown_Level')
            processed_spaces = results.get('processed_spaces', [])
            
            # Processing spaces for Revit export
            
            # Create floor plan view
            if self.source_view.ViewType == DB.ViewType.FloorPlan:
                prefix = "BubbleDiagram"
            else:
                area_scheme_name = self.source_view.AreaScheme.Name
                prefix = "BubbleDiagram_{}".format(area_scheme_name)
            floor_plan_view = self._create_get_floor_plan_view(level_name, prefix)
            if not floor_plan_view:
                return False
            
            # Process each space
            processed_count = 0
            for space_data in processed_spaces:
                if self._process_space_for_revit(space_data, floor_plan_view):
                    processed_count += 1
            
            # Set the floor plan view as active view after processing
            try:
                # Get the UIDocument to set active view
                uidoc = REVIT_APPLICATION.get_uidoc()
                uidoc.ActiveView = floor_plan_view
            except Exception as e:
                print("Warning: Could not set active view: {}".format(str(e)))
            
            # Done processing spaces for Revit
            return True
            
        except Exception as e:
            print("Error in Revit processing: {}".format(str(e)))
            return False
    
    def process_spaces_from_results(self, results, source_view=None):
        """Process spaces from results for Revit export.
        
        Args:
            results: Dictionary containing processed space data
            source_view: Original source view (for getting scale and other properties)
        """
        try:
            # Store source view for use in floor plan creation
            self.source_view = source_view
            
            # Delegate to Revit-specific processing
            return self._process_spaces_for_revit(results, source_view)
            
        except Exception as e:
            print("Error in Revit processing: {}".format(str(e)))
            return False
    
    def _verify_filled_region_creation(self, filled_region, space_identifier):
        """Verify that filled region was created successfully and has necessary parameters.
        
        Args:
            filled_region: The created filled region object
            space_identifier: Space identifier for debugging
            
        Returns:
            bool: True if filled region is valid and has parameters, False otherwise
        """
        try:
            if not filled_region:
                print("ERROR: Filled region is None for space: {}".format(space_identifier))
                return False
            
            if not filled_region.IsValidObject:
                print("ERROR: Filled region is not valid for space: {}".format(space_identifier))
                return False
            
            # Check if filled region has parameters
            if not filled_region.Parameters:
                print("WARNING: Filled region has no parameters for space: {}".format(space_identifier))
                return False
            
            
            
            return True
            
        except Exception as e:
            print("Error verifying filled region: {}".format(str(e)))
            return False


if __name__ == "__main__":
    pass

