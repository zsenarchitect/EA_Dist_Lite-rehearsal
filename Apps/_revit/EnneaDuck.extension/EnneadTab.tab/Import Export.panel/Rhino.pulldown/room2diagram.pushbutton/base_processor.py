#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Shared functionality between Rhino and Revit processing. Provides color scheme extraction and curve processor discovery.
"""

# ============================================================================
# RHINOINSIDE IMPORT CHECK - MUST BE FIRST
# ============================================================================
try:
    import clr  # pyright: ignore
    clr.AddReference('RhinoCommon')
    import Rhino  # pyright: ignore
    clr.AddReference('RhinoInside.Revit')
    from RhinoInside.Revit.Convert.Geometry import GeometryDecoder as RIR_DECODER  # pyright: ignore
    from RhinoInside.Revit.Convert.Geometry import GeometryEncoder as RIR_ENCODER  # pyright: ignore
    RHINO_IMPORT_OK = True
except:
    RHINO_IMPORT_OK = False

# ============================================================================
# STANDARD IMPORTS
# ============================================================================
# from EnneadTab import NOTIFICATION  # Commented out to avoid rate limiting
from EnneadTab.REVIT import REVIT_UNIT
from Autodesk.Revit import DB # pyright: ignore
from abc import abstractmethod


class BaseProcessor:
    """
    Base class for shared processing functionality between Rhino and Revit.
    
    This class provides common functionality for:
    - Color scheme extraction from Revit views
    - Curve processing (fillet and offset operations)
    - Space/room data extraction and processing
    - View validation and element collection
    - Common processing workflow orchestration
    """
    
    # ============================================================================
    # INITIALIZATION
    # ============================================================================
    
    def __init__(self, revit_doc, fillet_radius, offset_distance):
        """Initialize base processor.
        
        Args:
            revit_doc: Active Revit document
            fillet_radius: Corner fillet radius in feet (can be string or float)
            offset_distance: Inner offset distance in feet (can be string or float)
        """
        self.revit_doc = revit_doc
        
        # Convert to float if string values are passed
        try:
            self.fillet_radius = float(fillet_radius) if fillet_radius is not None else 0.0
        except (ValueError, TypeError) as e:
            print("WARNING: Invalid fillet_radius value '{}', using 0.0. Error: {}".format(fillet_radius, str(e)))
            self.fillet_radius = 0.0
            
        try:
            self.offset_distance = float(offset_distance) if offset_distance is not None else 0.0
        except (ValueError, TypeError) as e:
            print("WARNING: Invalid offset_distance value '{}', using 0.0. Error: {}".format(offset_distance, str(e)))
            self.offset_distance = 0.0
            
        self.color_dict = {}
        self.para_name = "Area_$Department"
    
    # ============================================================================
    # PUBLIC INTERFACE METHODS
    # ============================================================================
    
    def process_single_view(self, config, view, level_name=None):
        """Process a single view with comprehensive error handling.
        
        This is the main public interface for processing a single view.
        It orchestrates the entire processing workflow from validation to completion.
        
        Args:
            config: Processing configuration object
            view: Revit view object to process
            level_name: Optional level name override
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Validate view
            if not view:
                print("Cannot process: View is null")
                return False
            
            # SAFEGUARD: Check if view is still valid
            if not view.IsValidObject:
                print("Cannot process: View is no longer valid")
                return False
            
            if not self.is_view_suitable_for_processing(view):
                print("Cannot process view '{}': View type '{}' is not suitable for room/area processing".format(view.Name, view.ViewType))
                return False
            
            # Process the view using the integrated approach
            try:
                # Determine if we need to convert to Rhino format based on processor type
                # Use class name to avoid circular import issues
                convert_to_rhino = self.__class__.__name__ == "RhinoProcess"
                
                # Use the integrated view processing method
                results = self.process_view_with_elements(config.element_type, view, level_name, convert_to_rhino)
                if results:
                    # Delegate to appropriate processor with processed results
                    success = self.process_spaces_from_results(results, source_view=view)
                    if success:
                        print("Successfully processed view: {}".format(view.Name))
                        return True
                    else:
                        print("Failed to process spaces for view: {}".format(view.Name))
                        return False
                else:
                    print("No results from view processing - skipping view: {}".format(view.Name))
                    return False
                    
            except Exception as e:
                print("Error in view processing for view {}: {}. Skipping view.".format(view.Name, str(e)))
                return False
                
        except Exception as e:
            print("CRITICAL ERROR in process_single_view for view {}: {}. Skipping view.".format(
                view.Name if view else "Unknown", str(e)))
            return False
    
    def process_curves(self, input_curves, curve_type="rhino"):
        """Process curves with fillet and offset operations.
        
        This is the main public interface for curve processing.
        It handles the complete workflow from input curves to processed output.
        
        Args:
            input_curves: List of curves (Rhino or Revit)
            curve_type: "rhino" or "revit" to specify input type
            
        Returns:
            List of processed curves (same type as input)
        """
        # DEBUG logs removed for production; keep warnings/errors elsewhere
        
        if not input_curves or len(input_curves) == 0:
            #
            return input_curves
        
        if not RHINO_IMPORT_OK:
            print("RhinoInside not available - using original curves")
            return input_curves
        
        try:
            # Convert to Rhino curves for processing
            #
            rhino_curves = self._convert_to_rhino_curves(input_curves, curve_type)
            #
            
            if not rhino_curves:
                # print("  DEBUG: No Rhino curves converted, returning original")
                return input_curves
            
            # Join curves into a single curve
            #
            try:
                joined_curves = Rhino.Geometry.Curve.JoinCurves(rhino_curves)
                #
                
                if not joined_curves or len(joined_curves) == 0:
                    #
                    # If joining fails, try processing each curve individually
                    processed_curves = []
                    for curve in rhino_curves:
                        processed_curve = curve
                        
                        # Apply fillet if specified
                        if self.fillet_radius > 0:
                            processed_curve = self._apply_fillet_to_rhino_curve(processed_curve)
                            if not processed_curve:
                                processed_curve = curve  # Use original if fillet fails
                        
                        # Apply offset if specified
                        if self.offset_distance > 0:
                            processed_curve = self._apply_offset_to_rhino_curve(processed_curve)
                            if not processed_curve:
                                processed_curve = curve  # Use original if offset fails
                        
                        processed_curves.append(processed_curve)
                    
                    #
                    return processed_curves
                
                # Apply fillet if specified
                if self.fillet_radius > 0:
                    #
                    joined_curves[0] = self._apply_fillet_to_rhino_curve(joined_curves[0])
                    if not joined_curves[0]:
                        #
                        return input_curves
                
                # Apply offset if specified
                if self.offset_distance > 0:
                    #
                    joined_curves[0] = self._apply_offset_to_rhino_curve(joined_curves[0])
                    if not joined_curves[0]:
                        #
                        return input_curves
                
  
                return [joined_curves[0]]
                
            except Exception as e:
                #
                # If joining fails, try processing each curve individually
                processed_curves = []
                for curve in rhino_curves:
                    processed_curve = curve
                    
                    # Apply fillet if specified
                    if self.fillet_radius > 0:
                        processed_curve = self._apply_fillet_to_rhino_curve(processed_curve)
                        if not processed_curve:
                            processed_curve = curve  # Use original if fillet fails
                    
                    # Apply offset if specified
                    if self.offset_distance > 0:
                        processed_curve = self._apply_offset_to_rhino_curve(processed_curve)
                        if not processed_curve:
                            processed_curve = curve  # Use original if offset fails
                    
                    processed_curves.append(processed_curve)
                
                #
                return processed_curves
        
        except Exception as e:
            print("Error in curve processing: {}. Using original curves.".format(str(e)))
            return input_curves
    
    def process_spaces_from_results(self, results, processor_type="auto", source_view=None):
        """Process spaces from pre-processed results.
        
        This method delegates to the appropriate subclass method based on processor type.
        
        Args:
            results: Dictionary containing processed_spaces, level_name, etc.
            processor_type: "rhino", "revit", or "auto" (detects based on class type)
            source_view: Original source view (for getting scale and other properties)
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Auto-detect processor type if not specified
        if processor_type == "auto":
            if hasattr(self, 'rhino_doc'):
                processor_type = "rhino"
            else:
                processor_type = "revit"
        
        # Delegate to the appropriate subclass method
        if processor_type == "rhino":
            if hasattr(self, '_process_spaces_for_rhino'):
                return self._process_spaces_for_rhino(results)
            else:
                print("ERROR: RhinoProcessor not available - _process_spaces_for_rhino method not found")
                return False
        elif processor_type == "revit":
            if hasattr(self, '_process_spaces_for_revit'):
                return self._process_spaces_for_revit(results, source_view)
            else:
                print("ERROR: RevitProcessor not available - _process_spaces_for_revit method not found")
                return False
        else:
            print("ERROR: Unknown processor type: {}. Using default.".format(processor_type))
            # Try to auto-detect and use the available method
            if hasattr(self, '_process_spaces_for_rhino'):
                print("Falling back to Rhino processor")
                return self._process_spaces_for_rhino(results)
            elif hasattr(self, '_process_spaces_for_revit'):
                print("Falling back to Revit processor")
                return self._process_spaces_for_revit(results, source_view)
            else:
                print("ERROR: No processor methods available")
                return False
    

    

    @abstractmethod
    def _process_spaces_for_revit(self, results, source_view=None):
        raise NotImplementedError("Subclasses must implement this method")
    
    @abstractmethod
    def _process_spaces_for_rhino(self, results):
        raise NotImplementedError("Subclasses must implement this method")
    
    
    
    
 
    
    # ============================================================================
    # STATUS AND UTILITY METHODS
    # ============================================================================
    
    def get_curve_processor_status(self):
        """Get the status of the curve processor.
        
        Returns:
            bool: True if curve processor is available and working
        """
        return RHINO_IMPORT_OK
    
    def get_color_dict_status(self):
        """Get the status of the color dictionary.
        
        Returns:
            bool: True if color dictionary has entries
        """
        return len(self.color_dict) > 0
    
    # ============================================================================
    # VIEW PROCESSING METHODS
    # ============================================================================
    
    def process_view_with_elements(self, element_type, source_view, level_name, convert_to_rhino=False):
        """Main processing function for a single view with comprehensive error handling.
        
        This method orchestrates the view processing workflow including validation,
        element collection, and space processing.
        
        Args:
            element_type: Type of element ("Rooms" or "Areas")
            source_view: Source view to process
            level_name: Optional level name override
            convert_to_rhino: Boolean indicating if curves should be converted to Rhino format
            
        Returns:
            dict: Processing results or None if failed
        """
        try:
            # Validate document and view
            if not self.validate_document_and_view(source_view):
                return None
            
            # Check if view is suitable for processing
            if not self.is_view_suitable_for_processing(source_view):
                print("Cannot process view '{}': View type '{}' is not suitable for room/area processing".format(source_view.Name, source_view.ViewType))
                return None
            
            # Collect elements from view
            spaces = self.collect_elements_from_view(element_type, source_view)
            if not spaces:
                print("No elements found in view: {}".format(source_view.Name))
                return None
            
            # Process spaces using common logic
            results = self.process_spaces_common(spaces, element_type, level_name, source_view)
            
            print("Successfully processed view: {} ({} elements)".format(source_view.Name, len(spaces)))
            return results
            
        except Exception as e:
            print("Error processing view {}: {}. Skipping view.".format(source_view.Name, str(e)))
            return None
    
    def validate_document_and_view(self, source_view):
        """Validate that document and view are still valid.
        
        Args:
            source_view: View to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        # SAFEGUARD: Check if document is still valid
        if not self.revit_doc or not self.revit_doc.IsValidObject:
            print("ERROR: Revit document is no longer valid")
            return False
        
        # SAFEGUARD: Check if view is valid
        if not source_view or not source_view.IsValidObject:
            print("ERROR: Source view is no longer valid")
            return False
        
        return True
    
    def is_view_suitable_for_processing(self, view):
        """Check if a view is suitable for room/area diagram processing.
        
        Args:
            view: Revit view object
            
        Returns:
            bool: True if suitable, False otherwise
        """
        if not view:
            return False
        
        # Check view type - we want views that can show rooms/areas
        suitable_view_types = [
            DB.ViewType.FloorPlan,
            DB.ViewType.AreaPlan,
            DB.ViewType.CeilingPlan,
            DB.ViewType.EngineeringPlan
        ]
        
        return view.ViewType in suitable_view_types
    
    def collect_elements_from_view(self, element_type, source_view):
        """Collect elements from a specific view based on element type.
        
        Args:
            element_type: Type of element ("Rooms" or "Areas")
            source_view: Source view to collect elements from
            
        Returns:
            list: List of Revit elements
        """
        try:
            # Get the appropriate built-in category using the Enum
            from shared_constants import ElementType
            
            # Handle both enum objects and string values
            if hasattr(element_type, 'value'):
                # It's an enum with .value property
                element_type_str = element_type.value
            elif hasattr(element_type, 'name'):
                # It's an enum with .name property
                element_type_str = element_type.name
            elif hasattr(element_type, '__class__') and element_type.__class__.__name__ == 'ElementType':
                # It's the ElementType class itself, use the string value
                element_type_str = str(element_type)
            else:
                # It's already a string or other type
                element_type_str = str(element_type)
            
            built_in_category = ElementType.get_built_in_category(element_type_str)
            
            # Collect elements from the source view
            spaces = DB.FilteredElementCollector(self.revit_doc, source_view.Id)\
               .OfCategory(built_in_category).ToElements()
            
            # SAFEGUARD: Check if we got too many elements
            if len(spaces) > 1000:
                print("WARNING: Too many elements found ({}). Limiting to first 1000 to prevent memory issues.".format(len(spaces)))
                spaces = spaces[:1000]
            
            return spaces
            
        except Exception as e:
            print("ERROR: Failed to collect elements: {}. Stopping export.".format(str(e)))
            return []
    
    def get_level_and_scheme_info(self, view):
        """Get level name and area scheme information from a view.
        
        Args:
            view: Revit view object
            
        Returns:
            dict: Dictionary with level_name and area_scheme_name
        """
        level_name = "Unknown_Level"
        area_scheme_name = "Default"
        
        if view and view.GenLevel:
            level_name = view.GenLevel.Name
        
        # For area plans, also check the area scheme to avoid conflicts
        if view.ViewType == DB.ViewType.AreaPlan:
            try:
                # Use the proper AreaScheme property from ViewPlan
                if hasattr(view, 'AreaScheme') and view.AreaScheme:
                    area_scheme_name = view.AreaScheme.Name
                else:
                    area_scheme_name = "Default"
            except:
                area_scheme_name = "Default"
        
        return {
            'level_name': level_name,
            'area_scheme_name': area_scheme_name
        }
    
    def create_unique_identifier(self, view):
        """Create a unique identifier for a view based on level and area scheme.
        
        Args:
            view: Revit view object
            
        Returns:
            str: Unique identifier string
        """
        info = self.get_level_and_scheme_info(view)
        level_name = info['level_name']
        area_scheme_name = info['area_scheme_name']
        
        # Create a unique identifier combining level and area scheme (only for area plans)
        if view.ViewType == DB.ViewType.AreaPlan:
            unique_identifier = "{}_AreaScheme_{}".format(level_name, area_scheme_name)
        else:
            # For floor plans and other view types, just use level name
            unique_identifier = level_name
        
        return unique_identifier
    
    # ============================================================================
    # SPACE PROCESSING METHODS
    # ============================================================================
    
    def process_spaces_common(self, spaces, element_type, level_name, source_view):
        """Common space processing logic shared between Rhino and Revit.
        
        This method processes a list of spaces and extracts all necessary data
        including identifiers, areas, boundary curves, and color information.
        
        Args:
            spaces: List of Revit space objects
            element_type: Type of element ("Rooms" or "Areas")
            level_name: Optional level name override
            source_view: Optional source view for level info and color scheme
            
        Returns:
            dict: Processing results with color_dict, level_name, etc.
        """
        # Get color scheme from source view (each view maintains its own color scheme)
        self.get_color_dict(element_type, source_view)
        
        # Determine level name
        if level_name is None:
            level_name = "Unknown_Level"
            if source_view and source_view.GenLevel:
                level_name = source_view.GenLevel.Name
        
        # Create boundary options
        option = DB.SpatialElementBoundaryOptions()
        
        # Process each space
        processed_spaces = []
        for space in spaces:
            space_identifier = self.get_space_identifier(space)
            if not space_identifier:
                continue
                
            space_area = self.get_space_area(space)
            boundary_curves = self.get_boundary_curves(space, option)
            
            processed_spaces.append({
                'space': space,
                'identifier': space_identifier,
                'area': space_area,
                'curves': boundary_curves,
                'color': self.color_dict.get(space_identifier)
            })
        
        return {
            'color_dict': self.color_dict,
            'level_name': level_name,
            'processed_spaces': processed_spaces,
            'option': option
        }
    
    def get_color_dict(self, element_type, source_view):
        """Extract color mapping from source view's color fill scheme.
        
        Args:
            element_type: Type of element ("Rooms" or "Areas")
            source_view: Optional source view to get color scheme from (defaults to active view)
            
        Returns:
            dict: Color mapping dictionary {identifier: color}
        """
        self.color_dict = {}
        
        # Use source view if provided, otherwise use active view
        view_to_use = source_view if source_view else self.revit_doc.ActiveView
        
        # Get the appropriate built-in category using the Enum
        try:
            from shared_constants import ElementType
            
            # Handle both enum objects and string values
            if hasattr(element_type, 'value'):
                # It's an enum with .value property
                element_type_str = element_type.value
            elif hasattr(element_type, 'name'):
                # It's an enum with .name property
                element_type_str = element_type.name
            elif hasattr(element_type, '__class__') and element_type.__class__.__name__ == 'ElementType':
                # It's the ElementType class itself, use the string value
                element_type_str = str(element_type)
            else:
                # It's already a string or other type
                element_type_str = str(element_type)
            
            built_in_category = ElementType.get_built_in_category(element_type_str)
        except ValueError as e:
            print(str(e))
            return self.color_dict
        
        # Get the color scheme ID for the specified category from the source view
        try:
            color_scheme_id = view_to_use.GetColorFillSchemeId(DB.ElementId(built_in_category))
            if color_scheme_id == DB.ElementId.InvalidElementId:
                view_name = view_to_use.Name if view_to_use else "active view"
                print("No color scheme found for {} in {}".format(element_type, view_name))
                return self.color_dict
            
            # Get the color scheme element
            color_scheme = self.revit_doc.GetElement(color_scheme_id)
            if not color_scheme:
                print("Could not retrieve color scheme for {}".format(element_type))
                return self.color_dict
            
            # Extract color mappings from the scheme
            for entry in color_scheme.GetEntries():
                entry_value = entry.GetStringValue()
                if entry_value:  # Only add non-empty entries
                    self.color_dict[entry_value] = entry.Color
                    
            view_name = view_to_use.Name if view_to_use else "active view"
            print("Extracted {} color mappings from {}".format(len(self.color_dict), view_name))
                    
        except Exception as e:
            print("Error retrieving color scheme for {}: {}".format(element_type, str(e)))
        
        return self.color_dict
    
    def get_space_identifier(self, space):
        """Get space identifier from parameter.
        
        Args:
            space: Revit space object
            
        Returns:
            str: Space identifier or None
        """
        try:
            return space.LookupParameter(self.para_name).AsString()
        except:
            return None
    
    def get_space_area(self, space):
        """Get space area in square feet.
        
        Args:
            space: Revit space object
            
        Returns:
            float: Space area in square feet, rounded to nearest integer
        """
        try:
            area_sf = space.Area
            return int(round(area_sf)) if area_sf > 0 else 0
        except:
            return 0
    
    def get_boundary_curves(self, space, option):
        """Get boundary curves from space.
        
        Args:
            space: Revit space object
            option: SpatialElementBoundaryOptions
            
        Returns:
            list: List of Revit curve segments (not converted)
        """
        try:
            boundary_segments = space.GetBoundarySegments(option)
            curve_segments = []
            
            if not boundary_segments:
                # print("DEBUG: No boundary segments found")
                return curve_segments
                
            # print("DEBUG: Found {} boundary segment arrays".format(len(boundary_segments)))
            
            for i, segment_array in enumerate(boundary_segments):
                if not segment_array:
                    # print("DEBUG: Segment array {} is empty".format(i))
                    continue
                    
                # print("DEBUG: Processing segment array {} with {} segments".format(i, len(segment_array)))
                
                for j, segment in enumerate(segment_array):
                    try:
                        curve = segment.GetCurve()
                        if curve:
                            # According to Revit API docs, GetCurve() should return a valid Revit curve
                            # Check if it's a Revit curve (has IsValidObject property)
                            is_revit_curve = hasattr(curve, 'IsValidObject')
                            
                            if is_revit_curve:
                                # It's a Revit curve - check validity and clone immediately
                                if curve.IsValidObject:
                                    try:
                                        # Clone the curve immediately to preserve its validity
                                        cloned_curve = curve.Clone()
                                        if cloned_curve and cloned_curve.IsValidObject:
                                            curve_segments.append(cloned_curve)
                                            # print("DEBUG: Added cloned Revit curve from segment {}-{}".format(i, j))
                                        else:
                                            # print("DEBUG: Cloned Revit curve is invalid from segment {}-{}".format(i, j))
                                            pass # Removed DEBUG print
                                    except Exception as clone_error:
                                        # print("DEBUG: Failed to clone Revit curve from segment {}-{}: {}".format(i, j, str(clone_error)))
                                        # Try to use original curve as fallback if it's still valid
                                        if curve.IsValidObject:
                                            curve_segments.append(curve)
                                            # print("DEBUG: Added original Revit curve as fallback from segment {}-{}".format(i, j))
                                        else:
                                            # print("DEBUG: Original Revit curve also invalid from segment {}-{}".format(i, j))
                                            pass # Removed DEBUG print
                                else:
                                    # print("DEBUG: Revit curve is invalid from segment {}-{}".format(i, j))
                                    pass # Removed DEBUG print
                            else:
                                # It's not a Revit curve - this shouldn't happen with GetCurve() from boundary segments
                                # But if it does, try to treat it as a curve-like object
                                # print("DEBUG: Adding non-Revit curve (type: {}) from segment {}-{}".format(type(curve), i, j))
                                curve_segments.append(curve)
                        else:
                            # print("DEBUG: No curve from segment {}-{}".format(i, j))
                            pass # Removed DEBUG print
                    except Exception as segment_error:
                        # print("DEBUG: Error processing segment {}-{}: {}".format(i, j, str(segment_error)))
                        pass # Removed DEBUG print
                        
            # print("DEBUG: Total curves extracted: {}".format(len(curve_segments)))
            return curve_segments
            
        except Exception as e:
            print("Error getting boundary curves: {}".format(str(e)))
            return []
    
    # ============================================================================
    # CURVE PROCESSING METHODS (Internal)
    # ============================================================================
    
    def _convert_to_rhino_curves(self, input_curves, curve_type):
        """Convert input curves to Rhino curves.
        
        Args:
            input_curves: List of input curves
            curve_type: "rhino" or "revit" to specify input type
            
        Returns:
            list: List of Rhino curves or None if conversion fails
        """
        if not RHINO_IMPORT_OK:
            print("Rhino libraries not available - cannot convert curves")
            return None
        
        rhino_curves = []
        
        if curve_type.lower() == "rhino":
            # Input is already Rhino curves
            for curve in input_curves:
                if curve and hasattr(curve, 'IsValid') and curve.IsValid:
                    rhino_curves.append(curve)
        
        elif curve_type.lower() == "revit":
            # Convert Revit curves to Rhino curves
            for curve in input_curves:
                if curve:
                    # Check if it's a Revit curve (has IsValidObject property)
                    is_revit_curve = hasattr(curve, 'IsValidObject')
                    
                    if is_revit_curve:
                        # It's a Revit curve (Line, Arc, etc.) - convert using RIR_ENCODER
                        if curve.IsValidObject:
                            try:
                                rhino_curve = RIR_DECODER.ToCurve(curve)
                                if rhino_curve and hasattr(rhino_curve, 'IsValid') and rhino_curve.IsValid:
                                    rhino_curves.append(rhino_curve)
                                    # print("DEBUG: Converted Revit curve to Rhino curve")
                                else:
                                    print("Warning: Invalid Rhino curve converted from Revit curve")
                                    # Try fallback conversion
                                    rhino_curve = self._fallback_curve_conversion(curve)
                                    if rhino_curve:
                                        rhino_curves.append(rhino_curve)
                            except Exception as e:
                                print("Warning: Failed to convert Revit curve to Rhino curve: {}".format(str(e)))
                                # Try fallback conversion
                                rhino_curve = self._fallback_curve_conversion(curve)
                                if rhino_curve:
                                    rhino_curves.append(rhino_curve)
                        else:
                            # print("Warning: Revit curve is invalid")
                            pass # Removed DEBUG print
                    else:
                        # It's not a Revit curve - might already be a Rhino curve or other type
                        # print("DEBUG: Non-Revit curve detected (type: {}), checking if it's already a valid curve".format(type(curve)))
                        
                        # For non-Revit curves, try to create Rhino curves from their properties
                        try:
                            # Check if it's a Line type (which we saw in the debug output)
                            if hasattr(curve, 'From') and hasattr(curve, 'To'):
                                # It's a Line with From/To properties
                                start_point = curve.From
                                end_point = curve.To
                                rhino_line = Rhino.Geometry.Line(
                                    Rhino.Geometry.Point3d(start_point.X, start_point.Y, start_point.Z),
                                    Rhino.Geometry.Point3d(end_point.X, end_point.Y, end_point.Z)
                                )
                                if rhino_line.IsValid:
                                    # Convert Line to Curve for compatibility with Rhino methods
                                    rhino_curve = rhino_line.ToNurbsCurve()
                                    if rhino_curve and rhino_curve.IsValid:
                                        rhino_curves.append(rhino_curve)
                                        # print("DEBUG: Created Rhino curve from Line.From/To properties")
                                    else:
                                        # print("Warning: Converted Rhino curve is invalid")
                                        pass # Removed DEBUG print
                                else:
                                    # print("Warning: Created Rhino line is invalid")
                                    pass # Removed DEBUG print
                            elif hasattr(curve, 'GetEndPoint'):
                                # Try using GetEndPoint method (like Revit curves)
                                try:
                                    start_point = curve.GetEndPoint(0)
                                    end_point = curve.GetEndPoint(1)
                                    if start_point and end_point:
                                        # Create a Line first, then convert to Curve for compatibility
                                        rhino_line = Rhino.Geometry.Line(
                                            Rhino.Geometry.Point3d(start_point.X, start_point.Y, start_point.Z),
                                            Rhino.Geometry.Point3d(end_point.X, end_point.Y, end_point.Z)
                                        )
                                        if rhino_line.IsValid:
                                            # Convert Line to Curve for compatibility with Rhino methods
                                            rhino_curve = rhino_line.ToNurbsCurve()
                                            if rhino_curve and rhino_curve.IsValid:
                                                rhino_curves.append(rhino_curve)
                                                # print("DEBUG: Created Rhino curve from GetEndPoint method")
                                            else:
                                                # print("Warning: Converted Rhino curve from GetEndPoint is invalid")
                                                pass # Removed DEBUG print
                                        else:
                                            # print("Warning: Created Rhino line from GetEndPoint is invalid")
                                            pass # Removed DEBUG print
                                    else:
                                        # print("Warning: GetEndPoint returned None")
                                        pass # Removed DEBUG print
                                except Exception as get_endpoint_error:
                                    # print("Warning: GetEndPoint failed: {}".format(str(get_endpoint_error)))
                                    pass # Removed DEBUG print
                            elif hasattr(curve, 'IsValid') and curve.IsValid:
                                # It already has IsValid property (might be Rhino curve)
                                rhino_curves.append(curve)
                                # print("DEBUG: Added existing valid curve (likely already Rhino)")
                            else:
                                # Try to get curve properties through reflection
                                # print("DEBUG: Attempting to inspect Line object properties")
                                try:
                                    # Try to get start and end points through different methods
                                    start_point = None
                                    end_point = None
                                    
                                    # Try common property names
                                    for start_prop in ['StartPoint', 'Start', 'From', 'Point1']:
                                        if hasattr(curve, start_prop):
                                            start_point = getattr(curve, start_prop)
                                            # print("DEBUG: Found start point property: {}".format(start_prop))
                                            break
                                    
                                    for end_prop in ['EndPoint', 'End', 'To', 'Point2']:
                                        if hasattr(curve, end_prop):
                                            end_point = getattr(curve, end_prop)
                                            # print("DEBUG: Found end point property: {}".format(end_prop))
                                            break
                                    
                                    if start_point and end_point:
                                        rhino_line = Rhino.Geometry.Line(
                                            Rhino.Geometry.Point3d(start_point.X, start_point.Y, start_point.Z),
                                            Rhino.Geometry.Point3d(end_point.X, end_point.Y, end_point.Z)
                                        )
                                        if rhino_line.IsValid:
                                            # Convert Line to Curve for compatibility
                                            rhino_curve = rhino_line.ToNurbsCurve()
                                            if rhino_curve and rhino_curve.IsValid:
                                                rhino_curves.append(rhino_curve)
                                                # print("DEBUG: Created Rhino curve from discovered properties")
                                            else:
                                                # print("Warning: Converted Rhino curve from discovered properties is invalid")
                                                pass # Removed DEBUG print
                                        else:
                                            # print("Warning: Created Rhino line from discovered properties is invalid")
                                            pass # Removed DEBUG print
                                    else:
                                        # print("Warning: Could not find start/end point properties on Line object")
                                        # print("DEBUG: Available attributes: {}".format([attr for attr in dir(curve) if not attr.startswith('_')]))
                                        pass # Removed DEBUG print
                                except Exception as reflect_error:
                                    # print("Warning: Property reflection failed: {}".format(str(reflect_error)))
                                    pass # Removed DEBUG print
                        except Exception as e:
                             # print("Warning: Failed to convert non-Revit curve to Rhino: {}".format(str(e)))
                             pass # Removed DEBUG print
                else:
                    # print("Warning: Null curve in input")
                    pass # Removed DEBUG print
        
        # print("Converted {} valid Rhino curves from {} input curves".format(len(rhino_curves), len(input_curves) if input_curves else 0))
        return rhino_curves
    

    
    def _apply_fillet_to_rhino_curve(self, rhino_curve):
        """Apply fillet to a single Rhino curve.
        
        Args:
            rhino_curve: Rhino curve to apply fillet to
            
        Returns:
            Rhino.Geometry.Curve: Filleted curve or original if failed
        """
        if not rhino_curve or not RHINO_IMPORT_OK:
            return rhino_curve
        
        try:
            # Apply fillet using Rhino method
            filleted_curve = Rhino.Geometry.Curve.CreateFilletCornersCurve(
                rhino_curve,
                self.fillet_radius,
                0.001,  # tolerance
                0.1     # angle tolerance in degrees
            )
            
            if filleted_curve:
                # print("Applied fillet with radius {} feet".format(self.fillet_radius))
                return filleted_curve
            
            print("Fillet failed - using original curve")
            return rhino_curve
            
        except Exception as e:
            print("Error applying fillet: {}. Using original curve.".format(str(e)))
            return rhino_curve
    
    def _apply_offset_to_rhino_curve(self, rhino_curve):
        """Apply offset to a single Rhino curve using pure RhinoCommon with recursive retry.
        
        Args:
            rhino_curve: Rhino curve to apply offset to
            
        Returns:
            Rhino.Geometry.Curve: Offset curve or original if failed
        """
        if not rhino_curve or not RHINO_IMPORT_OK:
            return rhino_curve
        
        # Use recursive retry mechanism starting with full offset distance
        result = self._try_offset_with_retry(rhino_curve, self.offset_distance)
        return result if result else rhino_curve
    
    def _try_offset_with_retry(self, rhino_curve, offset_distance, min_distance=0.05):
        """Recursively try offset with progressively smaller distances.
        
        Args:
            rhino_curve: Rhino curve to apply offset to
            offset_distance: Current offset distance to try (in feet)
            min_distance: Minimum offset distance threshold (in feet)
            
        Returns:
            Rhino.Geometry.Curve: Offset curve or None if all attempts failed
        """
        if not rhino_curve or not RHINO_IMPORT_OK:
            return None
        
        # Check if we've reached minimum threshold
        if offset_distance < min_distance:
            print("Offset distance {} feet is below minimum threshold {} feet - giving up".format(offset_distance, min_distance))
            return None
        
        try:
            # Convert offset distance to Revit units
            offset_distance_revit = REVIT_UNIT.unit_to_internal(offset_distance, "feet")
            
            # Get a point inside the curve for direction (like slab offseter)
            direction_point = self._get_point_inside_curve(rhino_curve)
            
            if not direction_point:
                print("Could not determine offset direction for distance {} feet".format(offset_distance))
                return None
            
            # Get the normal vector for the curve plane (Z-axis for 2D curves)
            normal_vector = Rhino.Geometry.Vector3d.ZAxis
            
            # Use pure RhinoCommon Curve.Offset method with proper IronPython overload
            # Signature: Offset(point_on_curve, normal, distance, tolerance, corner_style)
            tolerance = 0.001  # Model tolerance
            corner_style = Rhino.Geometry.CurveOffsetCornerStyle.Sharp
            
            offset_curves = rhino_curve.Offset.Overloads[Rhino.Geometry.Point3d, Rhino.Geometry.Vector3d, float, float, Rhino.Geometry.CurveOffsetCornerStyle](direction_point, normal_vector, offset_distance_revit, tolerance, corner_style)
            
            if offset_curves and len(offset_curves) > 0:
                # Find the closed curve (like slab offseter does)
                for offset_curve in offset_curves:
                    if offset_curve.IsClosed:
                        print("Applied offset with distance {} feet (successfully)".format(offset_distance))
                        return offset_curve
                
                # If no closed curve found, use the first one
                print("Applied offset with distance {} feet (using first result)".format(offset_distance))
                return offset_curves[0]
            else:
                # Offset failed - try with half the distance
                half_distance = offset_distance / 2.0
                print("Offset failed with distance {} feet - retrying with {} feet".format(offset_distance, half_distance))
                return self._try_offset_with_retry(rhino_curve, half_distance, min_distance)
            
        except Exception as e:
            # Error occurred - try with half the distance
            half_distance = offset_distance / 2.0
            print("Error applying offset with distance {} feet: {}. Retrying with {} feet".format(offset_distance, str(e), half_distance))
            return self._try_offset_with_retry(rhino_curve, half_distance, min_distance)
    
    def _fallback_curve_conversion(self, curve):
        """Fallback method to convert Revit curve to Rhino curve when RIR_DECODER fails.
        
        Args:
            curve: Revit curve object
            
        Returns:
            Rhino.Geometry.Curve: Converted Rhino curve or None if failed
        """
        try:
            if hasattr(curve, 'GetEndPoint'):
                start_point = curve.GetEndPoint(0)
                end_point = curve.GetEndPoint(1)
                if start_point and end_point:
                    # Create a Rhino line from Revit curve endpoints
                    rhino_line = Rhino.Geometry.Line(
                        Rhino.Geometry.Point3d(start_point.X, start_point.Y, start_point.Z),
                        Rhino.Geometry.Point3d(end_point.X, end_point.Y, end_point.Z)
                    )
                    if rhino_line.IsValid:
                        # Convert Line to Curve for compatibility with Rhino methods
                        rhino_curve = rhino_line.ToNurbsCurve()
                        if rhino_curve and rhino_curve.IsValid:
                            return rhino_curve
        except Exception as e:
            print("Warning: Fallback curve conversion failed: {}".format(str(e)))
        
        return None
    
    # ============================================================================
    # INTERNAL UTILITY METHODS
    # ============================================================================
    
    def _get_point_inside_curve(self, rhino_curve):
        """Get a point inside the curve for offset direction.
        
        Args:
            rhino_curve: Rhino curve to find point inside
            
        Returns:
            Rhino.Geometry.Point3d: Point inside curve or None if failed
        """
        try:
            # Get the curve's bounding box
            bbox = rhino_curve.GetBoundingBox(True)
            
            # Get the center of the bounding box
            center = bbox.Center
            
            # Check if center is inside the curve
            if rhino_curve.IsClosed and self._is_point_inside_curve(rhino_curve, center):
                return center
            
            # If center is not inside, try to find a point inside
            # Use the slab offseter's approach: try random points within the bounding box
            import random
            max_attempts = 50
            
            for _ in range(max_attempts):
                # Generate a random point within the bounding box
                x = random.uniform(bbox.Min.X, bbox.Max.X)
                y = random.uniform(bbox.Min.Y, bbox.Max.Y)
                z = center.Z  # Keep the same Z as the curve
                
                test_point = Rhino.Geometry.Point3d(x, y, z)
                
                if self._is_point_inside_curve(rhino_curve, test_point):
                    return test_point
            
            # If we can't find a point inside, use the center anyway
            return center
            
        except Exception as e:
            print("Error finding point inside curve: {}".format(str(e)))
            return None
    
    def _is_point_inside_curve(self, rhino_curve, point):
        """Check if a point is inside a closed curve.
        
        Args:
            rhino_curve: Rhino curve to check against
            point: Point to check
            
        Returns:
            bool: True if point is inside curve, False otherwise
        """
        try:
            if not rhino_curve.IsClosed:
                return False
            
            # Use Rhino's point containment test
            containment = rhino_curve.PointAt(point)
            return containment == Rhino.Geometry.PointContainment.Inside
            
        except:
            # Fallback: use a simple ray casting method
            try:
                # Cast a ray from the point and count intersections
                ray = Rhino.Geometry.Ray3d(point, Rhino.Geometry.Vector3d.XAxis)
                intersections = Rhino.Geometry.Intersect.Intersection.CurveRay(rhino_curve, ray)
                
                if intersections:
                    # Odd number of intersections means point is inside
                    return len(intersections) % 2 == 1
                
                return False
            except:
                return False


if __name__ == "__main__":
    pass

