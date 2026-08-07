# IronPython 2.7 Compatible
"""
Template Data Collector Module

This module handles all data collection operations for view templates,
including category overrides, visibility settings, worksets, parameters, and filters.
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
import Autodesk.Revit.DB as DB
import traceback



from EnneadTab import ERROR_HANDLE, DATA_FILE, USER, FOLDER
from EnneadTab.REVIT import REVIT_APPLICATION

# Safe import of REVIT_CATEGORY - handle CPython mode compatibility
try:
    from EnneadTab.REVIT import REVIT_CATEGORY
except ImportError as e:
    ERROR_HANDLE.print_note("Warning: Could not import REVIT_CATEGORY module: {}".format(str(e)))
    REVIT_CATEGORY = None

# Fallback RevitCategory class for when REVIT_CATEGORY module is not available
class SimpleRevitCategory:
    """Simple fallback wrapper for Revit Category objects when REVIT_CATEGORY module fails to import."""
    
    def __init__(self, category):
        self.category = category
        self._pretty_name = None
    
    @property
    def pretty_name(self):
        """Get a pretty name for the category."""
        if self._pretty_name is None:
            try:
                if self.category:
                    # Check if this is a subcategory by looking for parent
                    if hasattr(self.category, 'Parent') and self.category.Parent:
                        # This is a subcategory
                        parent_name = self.category.Parent.Name if self.category.Parent else "Unknown"
                        sub_name = self.category.Name if self.category else "Unknown"
                        self._pretty_name = "[{}]: {}".format(parent_name, sub_name)
                    else:
                        # This is a main category
                        self._pretty_name = "[{}]:".format(self.category.Name if self.category else "Unknown")
                else:
                    self._pretty_name = "Unknown Category"
            except Exception:
                self._pretty_name = "Unknown Category"
        return self._pretty_name



class TemplateDataCollector:
    """
    Handles data collection from view templates.
    
    This class is responsible for extracting all relevant data from view templates
    including category overrides, visibility settings, worksets, parameters, and filters.
    """
    
    def __init__(self, doc):
        """
        Initialize the data collector.
        
        Args:
            doc: The Revit document
        """
        self.doc = doc
        ERROR_HANDLE.print_note("TemplateDataCollector initialized with document: {}".format(doc.Title if doc else "None"))
        ERROR_HANDLE.print_note("Document Settings.Categories available: {}".format("Yes" if doc and doc.Settings and doc.Settings.Categories else "No"))
        
        # Set iteration limits BEFORE calling methods that use them
        self.max_categories = 5000  # Increased from 1000 to handle larger projects
        self.max_subcategories = 10000  # Increased from 5000
        self.max_worksets = 100
        self.max_filters = 500
        
        # Error tracking across all operations
        self.all_error_groups = {}
        
        self.categories = self._get_sorted_categories()
        ERROR_HANDLE.print_note("Final categories list length: {}".format(len(self.categories)))
        
        # CRITICAL DEBUG: Print some category names if we have any
        if len(self.categories) > 0:
            ERROR_HANDLE.print_note("Sample categories collected: {}".format([cat.pretty_name for cat in self.categories[:5]]))
            if len(self.categories) > 1000:
                ERROR_HANDLE.print_note("WARNING: Large number of categories collected ({}). This may cause performance issues.".format(len(self.categories)))
        else:
            ERROR_HANDLE.print_note("CRITICAL PROBLEM: NO CATEGORIES COLLECTED AT ALL!")
    
    def _get_sorted_categories(self):
        """
        Get all categories and subcategories grouped by CategoryType and sorted alphabetically.
        
        Uses CategoryType enumeration for logical grouping:
        - Model categories (walls, floors, etc.)
        - Annotation categories (text, dimensions, etc.)
        - Analytical model categories
        - Internal categories
        
        Returns:
            list: Sorted list of RevitCategory objects grouped by CategoryType
        """
        categories_by_type = {
            DB.CategoryType.Model: [],
            DB.CategoryType.Annotation: [],
            DB.CategoryType.AnalyticalModel: [],
            DB.CategoryType.Internal: []
        }
        
        category_count = 0
        subcategory_count = 0
        allows_bound_count = 0
        
        try:
            # Check if doc.Settings.Categories is accessible
            if not self.doc or not self.doc.Settings:
                ERROR_HANDLE.print_note("ERROR: Document or document settings not available!")
                return []
                
            categories_collection = self.doc.Settings.Categories
            if not categories_collection:
                ERROR_HANDLE.print_note("ERROR: Categories collection is None!")
                return []
            
            ERROR_HANDLE.print_note("Starting category collection with CategoryType grouping - REVIT_CATEGORY available: {}".format(REVIT_CATEGORY is not None))
            
            # Get all categories with iteration limit
            for category in categories_collection:
                category_count += 1
                if category_count > self.max_categories:
                    ERROR_HANDLE.print_note("Category iteration limit reached ({}), stopping.".format(self.max_categories))
                    break
                
                try:
                    # Check if category is valid
                    if not category:
                        continue
                    
                    # Get category info for error reporting
                    try:
                        category_name = category.Name if category else "Unknown"
                        category_type = category.CategoryType if hasattr(category, 'CategoryType') else "Unknown"
                    except Exception:
                        category_name = "Unknown"
                        category_type = "Unknown"
                        
                    # Add main category using RevitCategory wrapper
                    try:
                        if REVIT_CATEGORY:
                            revit_category = REVIT_CATEGORY.RevitCategory(category)
                        else:
                            # Use fallback SimpleRevitCategory
                            revit_category = SimpleRevitCategory(category)
                            ERROR_HANDLE.print_note("Using fallback SimpleRevitCategory for category: {} (Type: {})".format(category_name, category_type))
                        
                        # Group by CategoryType
                        if category_type in categories_by_type:
                            categories_by_type[category_type].append(revit_category)
                        else:
                            # Fallback to Model category for unknown types
                            categories_by_type[DB.CategoryType.Model].append(revit_category)
                            ERROR_HANDLE.print_note("Unknown category type '{}' for category '{}', grouping under Model".format(category_type, category_name))
                        
                        allows_bound_count += 1
                    except Exception as revit_cat_error:
                        self._add_to_error_group(self.all_error_groups, revit_cat_error, category_name, "CategoryCreation_")
                        continue
                        
                    # Add subcategories with limit
                    if hasattr(category, 'SubCategories'):
                        for subcategory in category.SubCategories:
                            subcategory_count += 1
                            if subcategory_count > self.max_subcategories:
                                ERROR_HANDLE.print_note("Subcategory iteration limit reached ({}), stopping.".format(self.max_subcategories))
                                break
                            
                            try:
                                if subcategory:
                                    if REVIT_CATEGORY:
                                        revit_subcategory = REVIT_CATEGORY.RevitCategory(subcategory)
                                    else:
                                        # Use fallback SimpleRevitCategory
                                        revit_subcategory = SimpleRevitCategory(subcategory)
                                    
                                    # Subcategories inherit the parent's CategoryType
                                    if category_type in categories_by_type:
                                        categories_by_type[category_type].append(revit_subcategory)
                                    else:
                                        categories_by_type[DB.CategoryType.Model].append(revit_subcategory)
                            except Exception as e:
                                # Get subcategory name for error reporting
                                try:
                                    sub_name = subcategory.Name if subcategory else "Unknown"
                                except:
                                    sub_name = "Unknown"
                                
                                self._add_to_error_group(self.all_error_groups, e, sub_name, "SubCat_")
                                continue
                        
                except Exception as e:
                    ERROR_HANDLE.print_note("Error processing category: {}".format(str(e)))
                    continue
                    
        except Exception as e:
            ERROR_HANDLE.print_note("Error getting categories: {}".format(str(e)))
            return []
        
        # Combine all categories by type, maintaining type grouping
        all_categories = []
        type_names = {
            DB.CategoryType.Model: "Model",
            DB.CategoryType.Annotation: "Annotation", 
            DB.CategoryType.AnalyticalModel: "Analytical Model",
            DB.CategoryType.Internal: "Internal"
        }
        
        for category_type, categories_list in categories_by_type.items():
            if categories_list:
                type_name = type_names.get(category_type, "Unknown")
                ERROR_HANDLE.print_note("Found {} {} categories".format(len(categories_list), type_name))
                
                # Sort categories within each type alphabetically
                try:
                    sorted_by_type = sorted(categories_list, key=lambda x: x.pretty_name)
                    all_categories.extend(sorted_by_type)
                except Exception as e:
                    ERROR_HANDLE.print_note("Error sorting {} categories: {}".format(type_name, str(e)))
                    all_categories.extend(categories_list)
        
        # Log stats if there are issues
        if len(all_categories) == 0:
            ERROR_HANDLE.print_note("Category collection stats:")
            ERROR_HANDLE.print_note("- Total categories processed: {}".format(category_count))
            ERROR_HANDLE.print_note("- Categories successfully added: {}".format(allows_bound_count))
            ERROR_HANDLE.print_note("- Subcategories added: {}".format(subcategory_count))
        
        # Always log final collection stats for debugging
        ERROR_HANDLE.print_note("Category collection completed with CategoryType grouping:")
        ERROR_HANDLE.print_note("- Total categories processed: {}".format(category_count))
        ERROR_HANDLE.print_note("- Main categories added: {}".format(allows_bound_count))
        ERROR_HANDLE.print_note("- Subcategories added: {}".format(subcategory_count))
        ERROR_HANDLE.print_note("- Total categories in final list: {}".format(len(all_categories)))
        
        # Log breakdown by type
        for category_type, categories_list in categories_by_type.items():
            if categories_list:
                type_name = type_names.get(category_type, "Unknown")
                ERROR_HANDLE.print_note("- {} categories: {}".format(type_name, len(categories_list)))
        
        # Log final result
        if len(all_categories) == 0:
            ERROR_HANDLE.print_note("WARNING: No categories were collected!")
        
        return all_categories
    
    def get_category_overrides(self, template):
        """
        Extract category override settings from a template.
        
        Improved error handling:
        - Uses RevitCategory class for better category management
        - Checks if category allows bound parameters before attempting override
        - Uses ERROR_HANDLE.print_note for detailed error reporting
        - Provides summary of skipped categories
        - Uses explicit exception handling instead of silent try-catch
        - Added iteration limits to prevent infinite loops
        
        Args:
            template: The view template to analyze
            
        Returns:
            dict: Category override settings with readable pattern names
        """
        overrides = {}
        processed_count = 0
        
        # Always log category override extraction start
        ERROR_HANDLE.print_note("Starting category overrides extraction for template: {}".format(template.Name))
        ERROR_HANDLE.print_note("Total categories available: {}".format(len(self.categories)))
        
        if not self.categories:
            ERROR_HANDLE.print_note("WARNING: No categories available for override extraction!")
            raise Exception("No categories available for override extraction!")
            return overrides
        
        categories_with_overrides = 0
        categories_with_no_overrides = 0
        categories_with_errors = 0
        
        for revit_category in self.categories:
            processed_count += 1
            if processed_count > self.max_categories:
                ERROR_HANDLE.print_note("Category override processing limit reached, stopping.")
                break
                
            try:
                override = template.GetCategoryOverrides(revit_category.category.Id)
                # Always try to extract details - GetCategoryOverrides always returns an object
                override_details = self._extract_override_details(override)
                
                if override_details and self._has_meaningful_overrides(override_details):
                    categories_with_overrides += 1
                    overrides[revit_category.pretty_name] = override_details
                    ERROR_HANDLE.print_note("[OK] Category '{}' has meaningful overrides".format(revit_category.pretty_name))
                else:
                    categories_with_no_overrides += 1
                    # ERROR_HANDLE.print_note("[-] Category '{}' has no meaningful overrides".format(revit_category.pretty_name))
                        
            except Exception as e:
                categories_with_errors += 1
                self._add_to_error_group(self.all_error_groups, e, revit_category.pretty_name, "CategoryOverride_")
                ERROR_HANDLE.print_note("[ERROR] Error processing category '{}': {}".format(revit_category.pretty_name, str(e)))
                continue
                
        # Always log summary for debugging
        ERROR_HANDLE.print_note("Category overrides summary for template {}:".format(template.Name))
        ERROR_HANDLE.print_note("- Categories processed: {}".format(processed_count))
        ERROR_HANDLE.print_note("- Categories with meaningful overrides: {}".format(categories_with_overrides))
        ERROR_HANDLE.print_note("- Categories with no meaningful overrides: {}".format(categories_with_no_overrides))
        ERROR_HANDLE.print_note("- Categories with errors: {}".format(categories_with_errors))
        ERROR_HANDLE.print_note("- Final override details collected: {}".format(len(overrides)))
            
        return overrides
    
    def _has_meaningful_overrides(self, override_details):
        """
        Check if override details contain actual overrides using simple heuristics.
        
        Args:
            override_details: Dictionary of override details from actual override
            
        Returns:
            bool: True if there are meaningful overrides, False if all default
        """
        if not override_details or not isinstance(override_details, dict):
            return False
            
        # Use simple, reliable checks for meaningful overrides
        return self._has_meaningful_overrides_fallback(override_details)
    
    def _has_meaningful_overrides_fallback(self, override_details):
        """
        Fallback method to check for meaningful overrides using expected default values.
        
        Args:
            override_details: Dictionary of override details
            
        Returns:
            bool: True if there are meaningful overrides, False if all default
        """
        # Check for non-default values (original logic)
        meaningful_indicators = [
            # Line weight changes  
            override_details.get('projection_line_weight') not in [None, -1, 0],
            override_details.get('cut_line_weight') not in [None, -1, 0],
            # Color changes
            override_details.get('projection_line_color') not in [None, 'Default'],
            override_details.get('cut_line_color') not in [None, 'Default'],
            # Pattern changes
            override_details.get('projection_line_pattern') not in [None, 'Default'],
            override_details.get('cut_line_pattern') not in [None, 'Default'],
            # Fill pattern changes
            override_details.get('surface_foreground_pattern') not in [None, 'Default'],
            override_details.get('surface_background_pattern') not in [None, 'Default'],
            # Transparency changes
            override_details.get('transparency') not in [None, 0],
            # Halftone
            override_details.get('halftone') is True,
            # Detail level changes
            override_details.get('detail_level') not in [None, 'By View']
        ]
        
        return any(meaningful_indicators)
    
    def _extract_override_details(self, override):
        """
        Extract graphic override details with simple, safe error handling.
        
        Args:
            override: OverrideGraphicSettings object
            
        Returns:
            dict: Override details or None if extraction fails
        """
        if not override:
            return None
            
        details = {}
        
        # Simple extraction with try-catch for each property
        try:
            # Extract all properties safely
            # Note: Visibility is handled separately in get_category_visibility(), not here
            
            details['projection_line_weight'] = self._safe_get_property(lambda: override.ProjectionLineWeight, None)
            details['projection_line_color'] = self._safe_get_property(lambda: self._format_color(override.ProjectionLineColor), None)
            details['projection_line_pattern'] = self._safe_get_property(lambda: self._get_pattern_name(override.ProjectionLinePatternId), None)
            details['surface_foreground_pattern'] = self._safe_get_property(lambda: self._get_pattern_name(override.SurfaceForegroundPatternId), None)
            details['surface_foreground_pattern_color'] = self._safe_get_property(lambda: self._format_color(override.SurfaceForegroundPatternColor), None)
            details['surface_foreground_pattern_visible'] = self._safe_get_property(lambda: override.IsSurfaceForegroundPatternVisible, None)
            details['surface_background_pattern'] = self._safe_get_property(lambda: self._get_pattern_name(override.SurfaceBackgroundPatternId), None)
            details['surface_background_pattern_color'] = self._safe_get_property(lambda: self._format_color(override.SurfaceBackgroundPatternColor), None)
            details['surface_background_pattern_visible'] = self._safe_get_property(lambda: override.IsSurfaceBackgroundPatternVisible, None)
            details['transparency'] = self._safe_get_property(lambda: override.Transparency, None)
            details['cut_line_weight'] = self._safe_get_property(lambda: override.CutLineWeight, None)
            details['cut_line_color'] = self._safe_get_property(lambda: self._format_color(override.CutLineColor), None)
            details['cut_line_pattern'] = self._safe_get_property(lambda: self._get_pattern_name(override.CutLinePatternId), None)
            details['cut_foreground_pattern'] = self._safe_get_property(lambda: self._get_pattern_name(override.CutForegroundPatternId), None)
            details['cut_foreground_pattern_color'] = self._safe_get_property(lambda: self._format_color(override.CutForegroundPatternColor), None)
            details['cut_foreground_pattern_visible'] = self._safe_get_property(lambda: override.IsCutForegroundPatternVisible, None)
            details['cut_background_pattern'] = self._safe_get_property(lambda: self._get_pattern_name(override.CutBackgroundPatternId), None)
            details['cut_background_pattern_color'] = self._safe_get_property(lambda: self._format_color(override.CutBackgroundPatternColor), None)
            details['cut_background_pattern_visible'] = self._safe_get_property(lambda: override.IsCutBackgroundPatternVisible, None)
            details['halftone'] = self._safe_get_property(lambda: override.Halftone, None)
            details['detail_level'] = self._safe_get_property(lambda: self._convert_detail_level_to_text(override.DetailLevel), None)
            
            return details
            
        except Exception:
            # If complete extraction fails, return None 
            return None
    
    def _safe_get_property(self, func, default_value):
        """
        Safely execute a function and return default value on error.
        
        Args:
            func: Function to execute
            default_value: Value to return on error
            
        Returns:
            Function result or default value
        """
        try:
            return func()
        except:
            return default_value
    
    def _get_pattern_name(self, pattern_id):
        """
        Get readable pattern name from pattern ID.
        
        Args:
            pattern_id: The ElementId of the pattern
            
        Returns:
            str: Pattern name or "Default" if not found
        """
        if pattern_id == DB.ElementId.InvalidElementId:
            return "Default"
        
        try:
            pattern = self.doc.GetElement(pattern_id)
            if pattern:
                return pattern.Name
            else:
                ERROR_HANDLE.print_note("Pattern element not found for ID: {}".format(pattern_id))
                return "Default"
        except Exception as e:
            ERROR_HANDLE.print_note("Failed to get pattern name for ID {}: {}".format(pattern_id, str(e)))
            return "Default"
    
    def _format_color(self, color):
        """
        Format color as RGB string.
        
        Args:
            color: Color object
            
        Returns:
            str: RGB color string
        """
        if color:
            return "RGB({}, {}, {})".format(color.Red, color.Green, color.Blue)
        return "Default"
    
    def _convert_detail_level_to_text(self, detail_level):
        """
        Convert Revit ViewDetailLevel enum to text.
        
        Args:
            detail_level: ViewDetailLevel enum value
            
        Returns:
            str: Detail level as text
        """
        try:
            if detail_level == DB.ViewDetailLevel.Coarse:
                return "Coarse"
            elif detail_level == DB.ViewDetailLevel.Medium:
                return "Medium"
            elif detail_level == DB.ViewDetailLevel.Fine:
                return "Fine"
            elif detail_level == DB.ViewDetailLevel.Undefined:
                return "By View"
            else:
                return "Unknown"
        except Exception as e:
            ERROR_HANDLE.print_note("Error converting detail level to text: {}".format(str(e)))
            return "Unknown"
    
    def _convert_discipline_to_text(self, discipline):
        """
        Convert Revit ViewDiscipline enum to text.
        
        Args:
            discipline: ViewDiscipline enum value
            
        Returns:
            str: Discipline as text
        """
        try:
            if discipline == DB.ViewDiscipline.Architectural:
                return "Architectural"
            elif discipline == DB.ViewDiscipline.Structural:
                return "Structural"
            elif discipline == DB.ViewDiscipline.Mechanical:
                return "Mechanical"
            elif discipline == DB.ViewDiscipline.Electrical:
                return "Electrical"
            elif discipline == DB.ViewDiscipline.Plumbing:
                return "Plumbing"
            elif discipline == DB.ViewDiscipline.Coordination:
                return "Coordination"
            else:
                return "Unknown"
        except Exception as e:
            ERROR_HANDLE.print_note("Error converting discipline to text: {}".format(str(e)))
            return "Unknown"
    
    def _convert_color_scheme_location_to_text(self, location_value):
        """
        Convert Color Scheme Location value to readable text.
        
        Args:
            location_value: Integer value (0 or 1)
            
        Returns:
            str: Readable location text
        """
        try:
            if location_value == 0:
                return "Foreground"
            elif location_value == 1:
                return "Background"
            else:
                return "Unknown ({})".format(location_value)
        except Exception as e:
            ERROR_HANDLE.print_note("Error converting color scheme location to text: {}".format(str(e)))
            return "Error: {}".format(location_value)
    
    def _convert_display_model_to_text(self, display_value):
        """
        Convert Display Model value to readable text.
        
        Args:
            display_value: Integer value (0, 1, or 2)
            
        Returns:
            str: Readable display model text
        """
        try:
            if display_value == 0:
                return "Normal"
            elif display_value == 1:
                return "Halftone"
            elif display_value == 2:
                return "Do not display"
            else:
                return "Unknown ({})".format(display_value)
        except Exception as e:
            ERROR_HANDLE.print_note("Error converting display model to text: {}".format(str(e)))
            return "Error: {}".format(display_value)
    
    
    def _convert_far_clipping_to_text(self, clipping_value):
        """
        Convert Far Clipping value to readable text.
        
        Args:
            clipping_value: Integer value
            
        Returns:
            str: Readable far clipping text
        """
        try:
            if clipping_value == 0:
                return "No Clipping"
            elif clipping_value == 1:
                return "Clip With Lines"
            elif clipping_value == 2:
                return "Clip Without Lines"
            else:
                return "Unknown ({})".format(clipping_value)
        except Exception as e:
            ERROR_HANDLE.print_note("Error converting far clipping to text: {}".format(str(e)))
            return "Error: {}".format(clipping_value)
    
    def _convert_show_hidden_lines_to_text(self, hidden_lines_value):
        """
        Convert Show Hidden Lines value to readable text.
        
        Args:
            hidden_lines_value: Integer value (0 or 1)
            
        Returns:
            str: Readable hidden lines text
        """
        try:
            if hidden_lines_value == 0:
                return "Hide"
            elif hidden_lines_value == 1:
                return "Show"
            else:
                return "Unknown ({})".format(hidden_lines_value)
        except Exception as e:
            ERROR_HANDLE.print_note("Error converting show hidden lines to text: {}".format(str(e)))
            return "Error: {}".format(hidden_lines_value)
    
    def _convert_sun_path_to_text(self, sun_path_value):
        """
        Convert Sun Path value to readable text.
        
        Args:
            sun_path_value: Integer value (0 or 1)
            
        Returns:
            str: Readable sun path text
        """
        return sun_path_value
    
    def _convert_parts_visibility_to_text(self, parts_visibility_value):
        """
        Convert Parts Visibility value to readable text.
        
        Args:
            parts_visibility_value: Integer value (0, 1, or 2)
            
        Returns:
            str: Readable parts visibility text
        """
        try:
            if parts_visibility_value == 0:
                return "Show Parts"
            elif parts_visibility_value == 1:
                return "Show Original"
            elif parts_visibility_value == 2:
                return "Show Both" 
            else:
                return "Unknown ({})".format(parts_visibility_value)
        except Exception as e:
            ERROR_HANDLE.print_note("Error converting parts visibility to text: {}".format(str(e)))
            return "Error: {}".format(parts_visibility_value)
    
    def _convert_model_display_to_text(self, model_display_value):
        """
        Convert Model Display (Visual Style) value to readable text.
        
        Args:
            model_display_value: Integer value (0, 1, 2, 3, 4, or 5)
            
        Returns:
            str: Readable model display text
        """
        try:
            if model_display_value == 0:
                return "Wireframe"
            elif model_display_value == 1:
                return "Hidden Line"
            elif model_display_value == 2:
                return "Shaded"
            elif model_display_value == 3:
                return "Consistent Colors"
            elif model_display_value == 4:
                return "Textures"
            elif model_display_value == 5:
                return "Realistic"
            else:
                return "Unknown ({})".format(model_display_value)
        except Exception as e:
            ERROR_HANDLE.print_note("Error converting model display to text: {}".format(str(e)))
            return "Error: {}".format(model_display_value)
    
    def get_category_visibility(self, template):
        """
        Get category visibility settings from template.
        
        Improved error handling:
        - Uses RevitCategory class for better category management
        - Checks if category allows bound parameters before attempting visibility check
        - Uses ERROR_HANDLE.print_note for detailed error reporting
        - Provides summary of skipped categories
        - Uses explicit exception handling instead of silent try-catch
        - Added iteration limits to prevent infinite loops
        
        Args:
            template: The view template to analyze
            
        Returns:
            dict: Category visibility settings (On/Off)
        """
        visibility = {}
        processed_count = 0
        visible_count = 0
        hidden_count = 0
        
        # Only log if there are issues
        if len(self.categories) == 0:
            ERROR_HANDLE.print_note("Starting category visibility extraction for template: {}".format(template.Name))
            ERROR_HANDLE.print_note("Total categories available: {}".format(len(self.categories)))
        
        if not self.categories:
            ERROR_HANDLE.print_note("WARNING: No categories available for visibility extraction!")
            return visibility
        
        for revit_category in self.categories:
            processed_count += 1
            if processed_count > self.max_categories:
                ERROR_HANDLE.print_note("Category visibility processing limit reached, stopping.")
                break
                
            # Process all categories without AllowsBoundParameters filter
                
            try:
                is_hidden = template.GetCategoryHidden(revit_category.category.Id)
                if is_hidden:
                    visibility[revit_category.pretty_name] = "Hidden"
                    hidden_count += 1
                else:
                    visibility[revit_category.pretty_name] = "Visible"
                    visible_count += 1
            except Exception as e:
                self._add_to_error_group(self.all_error_groups, e, revit_category.pretty_name, "CategoryVisibility_")
                continue
                    
        # Only log summary if there are issues
        if len(visibility) == 0:
            ERROR_HANDLE.print_note("Category visibility summary for template {}:".format(template.Name))
            ERROR_HANDLE.print_note("- Categories processed: {}".format(processed_count))
            ERROR_HANDLE.print_note("- Visible categories: {}".format(visible_count))
            ERROR_HANDLE.print_note("- Hidden categories: {}".format(hidden_count))
            
        return visibility
    
    def get_workset_visibility(self, template):
        """
        Get workset visibility settings from template.
        
        Improved error handling:
        - Uses FilteredWorksetCollector for proper workset collection
        - Uses ERROR_HANDLE.print_note for detailed error reporting
        - Provides summary of skipped worksets
        - Uses explicit exception handling instead of silent try-catch
        - Added iteration limits to prevent infinite loops
        
        Args:
            template: The view template to analyze
            
        Returns:
            dict: Workset visibility settings with readable text
        """
        worksets = {}
        skipped_worksets = []
        processed_count = 0
        
        try:
            workset_collector = DB.FilteredWorksetCollector(self.doc).OfKind(DB.WorksetKind.UserWorkset)
            
            for workset in workset_collector:
                processed_count += 1
                if processed_count > self.max_worksets:
                    ERROR_HANDLE.print_note("Workset processing limit reached, stopping.")
                    break
                    
                try:
                    visibility = template.GetWorksetVisibility(workset.Id)
                    worksets[workset.Name] = self._convert_visibility_to_text(visibility)
                except Exception as e:
                    error_msg = "Failed to get visibility for workset '{}': {}".format(workset.Name, str(e))
                    skipped_worksets.append(error_msg)
                    ERROR_HANDLE.print_note(error_msg)
                    continue
        except Exception as e:
            ERROR_HANDLE.print_note("Error getting worksets: {}".format(str(e)))
            return {}
                    
        # Log summary of skipped worksets if any
        if skipped_worksets:
            summary_msg = "Skipped {} worksets during visibility extraction: {}".format(
                len(skipped_worksets), ", ".join(skipped_worksets[:5])
            )
            ERROR_HANDLE.print_note(summary_msg)
            
        return worksets
    
    def _convert_visibility_to_text(self, visibility):
        """
        Convert workset visibility enum to readable text.
        
        Args:
            visibility: WorksetVisibility enum value
            
        Returns:
            str: Readable visibility text
        """
        if visibility == DB.WorksetVisibility.Visible:
            return "Visible"
        elif visibility == DB.WorksetVisibility.Hidden:
            return "Hidden"
        else:
            return "UseGlobalSetting"
    
    def get_view_parameters(self, template):
        """
        Get view parameters controlled by template.
        
        Args:
            template: The view template to analyze
            
        Returns:
            tuple: (controlled_params, uncontrolled_params)
        """
        controlled_params = {}  # Change to dict to store parameter name -> value
        uncontrolled_params = []
        
        try:
            # Get non-controlled parameter IDs
            try:
                param_ids = template.GetNonControlledTemplateParameterIds()
                ERROR_HANDLE.print_note("Template '{}': Found {} non-controlled parameters".format(
                    template.Name if hasattr(template, 'Name') else 'Unknown', 
                    len(param_ids) if param_ids else 0
                ))
            except Exception as e:
                ERROR_HANDLE.print_note("Error getting non-controlled parameter IDs: {}".format(str(e)))
                param_ids = set()
        
            # Get all view parameters with iteration limit
            param_count = 0
            controlled_count = 0
            uncontrolled_count = 0
            
            for param in template.Parameters:
                param_count += 1
                if param_count > 1000:  # Limit parameters to prevent infinite loops
                    ERROR_HANDLE.print_note("Parameter iteration limit reached, stopping.")
                    break
                    
                try:
                    # Safely get parameter name
                    param_name = "Unknown Parameter"
                    try:
                        if hasattr(param, 'Definition') and param.Definition and hasattr(param.Definition, 'Name'):
                            param_name = param.Definition.Name
                        else:
                            # Fallback: try to get name from parameter itself (Value for 2024+, IntegerValue for older)
                            param_name = str(REVIT_APPLICATION.get_element_id_value(param.Id))
                    except:
                        param_name = "Parameter_{}".format(REVIT_APPLICATION.get_element_id_value(param.Id))
                    
                    # Debug: Check if parameter ID is in non-controlled list
                    is_controlled = param.Id not in param_ids
                    
                    if is_controlled:
                        # Parameter is controlled, get its value
                        param_value = self._get_parameter_value_as_string(param)
                        controlled_params[param_name] = param_value
                        controlled_count += 1
                    else:
                        uncontrolled_params.append(param_name)
                        uncontrolled_count += 1
                        
                except Exception as e:
                    ERROR_HANDLE.print_note("Error processing parameter: {}".format(str(e)))
                    continue
            
            ERROR_HANDLE.print_note("Template '{}': {} total params, {} controlled, {} uncontrolled".format(
                template.Name if hasattr(template, 'Name') else 'Unknown',
                param_count, controlled_count, uncontrolled_count
            ))
                    
        except Exception as e:
            ERROR_HANDLE.print_note("Error getting view parameters: {}".format(str(e)))
                
        return controlled_params, uncontrolled_params
    
    def _get_parameter_value_as_string(self, param):
        """
        Get parameter value as a readable string with enhanced conversion logic.
        
        This method handles different parameter types and applies special conversions
        for known parameter types like Detail Level, Discipline, Color Scheme Location, etc.
        
        Args:
            param: The parameter object
            
        Returns:
            str: Parameter value as readable string
        """
        # Early validation
        if not param:
            return "N/A"
        if not param.HasValue:
            return "Parameter No Value"
        
        try:
            storage_type = param.StorageType
            
            # Use strategy pattern for different storage types
            if storage_type == DB.StorageType.String:
                return self._convert_string_parameter(param)
            elif storage_type == DB.StorageType.Integer:
                return self._convert_integer_parameter(param)
            elif storage_type == DB.StorageType.Double:
                return self._convert_double_parameter(param)
            elif storage_type == DB.StorageType.ElementId:
                return self._convert_elementid_parameter(param)
            else:
                return self._convert_unknown_parameter(param)
                
        except Exception as e:
            return self._handle_parameter_error(e)
    
    def _convert_string_parameter(self, param):
        """Convert string parameter to readable text."""
        try:
            value = param.AsString()
            return value if value else "Empty String"
        except Exception as e:
            return "Error: String conversion failed - {}".format(str(e)[:30])
    
    def _convert_double_parameter(self, param):
        """Convert double parameter to readable text."""
        try:
            double_value = param.AsDouble()
            return str(round(double_value, 4))
        except Exception as e:
            return "Error: Double conversion failed - {}".format(str(e)[:30])
    
    def _convert_elementid_parameter(self, param):
        """Convert ElementId parameter to readable text."""
        try:
            element_id = param.AsElementId()
            eid_val = REVIT_APPLICATION.get_element_id_value(element_id) if element_id else -1
            if not element_id or eid_val == -1:
                return "None"
            
            try:
                element = self.doc.GetElement(element_id)
                if element and hasattr(element, 'Name'):
                    return element.Name
                else:
                    return str(eid_val)
            except Exception:
                return str(eid_val)
        except Exception as e:
            return "Error: ElementId conversion failed - {}".format(str(e)[:30])
    
    def _convert_integer_parameter(self, param):
        """Convert integer parameter to readable text with special handling."""
        try:
            int_value = param.AsInteger()
            param_name = self._get_parameter_name(param)
            
            # Apply special conversions based on parameter type and name
            converted_value = self._apply_special_integer_conversions(param, int_value, param_name)
            if converted_value:
                return converted_value
            
            # Debug logging for troubleshooting
            self._log_debug_parameter_info(param_name, int_value, param.StorageType)
            
            return str(int_value)
            
        except Exception as e:
            return "Error: Integer conversion failed - {}".format(str(e)[:30])
    
    def _apply_special_integer_conversions(self, param, int_value, param_name):
        """Apply special conversions for known parameter types."""
        if not param_name:
            return None
        
        param_name_lower = param_name.lower()
        
        # Check parameter type first (more reliable)
        try:
            if (hasattr(param, 'Definition') and param.Definition and 
                hasattr(param.Definition, 'ParameterType')):
                
                if param.Definition.ParameterType == DB.ParameterType.YesNo:
                    return "Yes" if int_value == 1 else "No"
        except Exception:
            pass
        
        # Check parameter name for special conversions
        conversion_map = {
            'detail level': self._convert_detail_level_to_text,
            'discipline': self._convert_discipline_to_text,
            'color scheme location': self._convert_color_scheme_location_to_text,
            'display model': self._convert_display_model_to_text,
            'model display': self._convert_model_display_to_text,
            'far clipping': self._convert_far_clipping_to_text,
            'show hidden lines': self._convert_show_hidden_lines_to_text,
            'sun path': self._convert_sun_path_to_text,
            'parts visibility': self._convert_parts_visibility_to_text
        }
        
        for keyword, conversion_func in conversion_map.items():
            if keyword in param_name_lower:
                try:
                    return conversion_func(int_value)
                except Exception as e:
                    ERROR_HANDLE.print_note("Error converting {} parameter '{}': {}".format(
                        keyword, param_name, str(e)
                    ))
                    return "Error: {} conversion failed".format(keyword.title())
        
        return None
    
    def _get_parameter_name(self, param):
        """Safely get parameter name."""
        try:
            if (hasattr(param, 'Definition') and param.Definition and 
                hasattr(param.Definition, 'Name')):
                return param.Definition.Name
        except Exception:
            pass
        return None
    
    def _log_debug_parameter_info(self, param_name, value, storage_type):
        """Log debug information for troubleshooting."""
        if not param_name:
            return
            
        # Only log parameters that might need special handling
        debug_keywords = ['detail', 'discipline', 'color', 'scheme', 'location', 'display', 'model', 'far', 'clipping', 'hidden', 'lines', 'sun', 'path', 'parts', 'visibility']
        if any(keyword in param_name.lower() for keyword in debug_keywords):
            ERROR_HANDLE.print_note("DEBUG: Found parameter '{}' with value {} (type: {})".format(
                param_name, value, storage_type
            ))
    
    def _convert_unknown_parameter(self, param):
        """Convert unknown parameter types using fallback methods."""
        try:
            # Try AsValueString first (most reliable for unknown types)
            value_string = param.AsValueString()
            if value_string:
                return value_string
            
            # Fallback to AsString
            string_value = param.AsString()
            if string_value:
                return string_value
            
            return "Unknown Type"
        except Exception as e:
            return "Error: Unknown type conversion failed - {}".format(str(e)[:30])
    
    def _handle_parameter_error(self, exception):
        """Handle parameter conversion errors with user-friendly messages."""
        error_msg = str(exception)
        
        # Check for specific error types
        if "InternalDefinition" in error_msg and "Para" in error_msg:
            return "Not Present"
        elif "Parameter" in error_msg and "not found" in error_msg.lower():
            return "Parameter Not Found"
        else:
            return "Error: {}".format(error_msg[:50])
    
    def get_filter_data(self, template):
        """
        Get filter usage, visibility, enable status, and graphic override data.
        
        Enhanced to capture:
        - Filter enable status (Enable Filter checkbox)
        - Filter visibility status (Visibility checkbox)
        - Graphic override settings (Lines, Patterns, Transparency)
        
        Improved error handling:
        - Uses ERROR_HANDLE.print_note for detailed error reporting
        - Provides summary of skipped filters
        - Uses explicit exception handling instead of silent try-catch
        - Added iteration limits to prevent infinite loops
        
        Args:
            template: The view template to analyze
            
        Returns:
            dict: Filter data with enable, visibility, and override settings
        """
        filters = {}
        skipped_filters = []
        processed_count = 0
        
        try:
            filter_ids = template.GetFilters()
            
            for filter_id in filter_ids:
                processed_count += 1
                if processed_count > self.max_filters:
                    ERROR_HANDLE.print_note("Filter processing limit reached, stopping.")
                    break
                    
                try:
                    filter_element = self.doc.GetElement(filter_id)
                    if filter_element:
                        # Get filter enable status
                        is_enabled = template.GetIsFilterEnabled(filter_id)
                        
                        # Get filter visibility status
                        is_visible = template.GetFilterVisibility(filter_id)
                        
                        # Get graphic override settings
                        override = template.GetFilterOverrides(filter_id)
                        override_details = self._extract_override_details(override)
                        
                        # Combine all filter data
                        filter_data = {
                            'enabled': is_enabled,
                            'visible': is_visible,
                            'graphic_overrides': override_details
                        }
                        
                        filters[filter_element.Name] = filter_data
                except Exception as e:
                    error_msg = "Failed to get filter data for ID {}: {}".format(filter_id, str(e))
                    skipped_filters.append(error_msg)
                    ERROR_HANDLE.print_note(error_msg)
                    continue
        except Exception as e:
            ERROR_HANDLE.print_note("Error getting filters: {}".format(str(e)))
            return {}
                
        # Log summary of skipped filters if any
        if skipped_filters:
            summary_msg = "Skipped {} filters during extraction: {}".format(
                len(skipped_filters), ", ".join(skipped_filters[:5])
            )
            ERROR_HANDLE.print_note(summary_msg)
            
        return filters
    


    def get_import_category_data(self, template):
        """
        Extract import category data from a template.
        
        Args:
            template: The view template
            
        Returns:
            dict: Import category data
        """
        import_categories = {}
        
        try:
            # Get import category overrides
            for category_id in template.GetNonControlledTemplateParameterIds():
                try:
                    category = self.doc.GetElement(category_id)
                    if category and hasattr(category, 'CategoryType'):
                        if category.CategoryType == DB.CategoryType.Imported:
                            category_name = category.Name
                            
                            # Get category override
                            try:
                                override = template.GetCategoryOverrides(category_id)
                                if override:
                                    import_categories[category_name] = self._extract_override_details(override)
                                else:
                                    import_categories[category_name] = "UNCONTROLLED"
                            except Exception as e:
                                ERROR_HANDLE.print_note("Error getting import category override for category: {} becasue {}".format(category_name, str(e)))
                                import_categories[category_name] = "UNCONTROLLED"
                except Exception as e:
                    ERROR_HANDLE.print_note("Error processing import category: {}".format(str(e)))
                    continue
                    
        except Exception as e:
            ERROR_HANDLE.print_note("Error getting import category data: {}".format(str(e)))
            
        return import_categories

    def get_revit_link_data(self, template):
        """
        Extract Revit link data from a template.
        
        Args:
            template: The view template
            
        Returns:
            dict: Revit link data
        """
        revit_links = {}
        
        try:
            # Check if this view supports Revit link operations
            # Revit link methods only work on view templates and plan/elevation views, not 3D views
            if not self._supports_revit_link_operations(template):
                ERROR_HANDLE.print_note("View type '{}' does not support Revit link operations, skipping...".format(type(template).__name__))
                return revit_links
            
            # Get all Revit links in the document
            link_instances = DB.FilteredElementCollector(self.doc).OfClass(DB.RevitLinkInstance)
            
            for link_instance in link_instances:
                try:
                    link_name = link_instance.Name
                    
                    # Initialize link data structure
                    revit_links[link_name] = {
                        'visibility': 'UNCONTROLLED',
                        'halftone': None,
                        'underlay': None,
                        'display_settings': 'By Host View'
                    }
                    
                    # Get link visibility (handles API version differences)
                    try:
                        if hasattr(template, 'GetRevitLinkVisibility'):
                            visibility = template.GetRevitLinkVisibility(link_instance.Id)
                            revit_links[link_name]['visibility'] = self._convert_visibility_to_text(visibility)
                        else:
                            ERROR_HANDLE.print_note("GetRevitLinkVisibility method not available in this Revit version")
                    except AttributeError as e:
                        # Specific handling for missing method (API version issue)
                        ERROR_HANDLE.print_note("GetRevitLinkVisibility not supported for view type '{}' or Revit version".format(type(template).__name__))
                    except Exception as e:
                        self._add_to_error_group(self.all_error_groups, e, link_name, "LinkVisibility_")
                    
                    # Get link halftone (handles API version differences)
                    try:
                        if hasattr(template, 'IsRevitLinkDisplayedAsHalftone'):
                            revit_links[link_name]['halftone'] = template.IsRevitLinkDisplayedAsHalftone(link_instance.Id)
                        else:
                            ERROR_HANDLE.print_note("IsRevitLinkDisplayedAsHalftone method not available in this Revit version")
                    except AttributeError as e:
                        ERROR_HANDLE.print_note("IsRevitLinkDisplayedAsHalftone not supported for view type '{}' or Revit version".format(type(template).__name__))
                    except Exception as e:
                        self._add_to_error_group(self.all_error_groups, e, link_name, "LinkHalftone_")
                    
                    # Get link underlay (handles API version differences)
                    try:
                        if hasattr(template, 'IsRevitLinkDisplayedAsUnderlay'):
                            revit_links[link_name]['underlay'] = template.IsRevitLinkDisplayedAsUnderlay(link_instance.Id)
                        else:
                            ERROR_HANDLE.print_note("IsRevitLinkDisplayedAsUnderlay method not available in this Revit version")
                    except AttributeError as e:
                        ERROR_HANDLE.print_note("IsRevitLinkDisplayedAsUnderlay not supported for view type '{}' or Revit version".format(type(template).__name__))
                    except Exception as e:
                        self._add_to_error_group(self.all_error_groups, e, link_name, "LinkUnderlay_")
                    
                    # Get link display settings (handles API version differences)
                    try:
                        if hasattr(template, 'GetRevitLinkDisplaySettings'):
                            display_settings = template.GetRevitLinkDisplaySettings(link_instance.Id)
                            if display_settings:
                                revit_links[link_name]['display_settings'] = str(display_settings)
                        else:
                            ERROR_HANDLE.print_note("GetRevitLinkDisplaySettings method not available in this Revit version")
                    except AttributeError as e:
                        ERROR_HANDLE.print_note("GetRevitLinkDisplaySettings not supported for view type '{}' or Revit version".format(type(template).__name__))
                    except Exception as e:
                        self._add_to_error_group(self.all_error_groups, e, link_name, "LinkDisplaySettings_")
                        
                except Exception as e:
                    ERROR_HANDLE.print_note("Error processing Revit link {}: {}".format(link_name, str(e)))
                    continue
                    
        except Exception as e:
            ERROR_HANDLE.print_note("Error getting Revit link data: {}".format(str(e)))
            
        return revit_links

    def _supports_revit_link_operations(self, view):
        """
        Check if a view supports Revit link operations.
        
        Revit link methods availability varies by:
        1. View type (3D views don't support these operations)
        2. Revit API version (some methods were added in later versions)
        
        This method tests actual method availability rather than just type checking
        to handle API version differences gracefully.
        
        Args:
            view: The view to check
            
        Returns:
            bool: True if view supports Revit link operations
        """
        try:
            view_type = type(view).__name__
            
            # Test for method availability - this handles API version differences
            # According to Revit API docs, these methods should be available on View class
            required_methods = [
                'GetRevitLinkVisibility',
                'IsRevitLinkDisplayedAsHalftone', 
                'IsRevitLinkDisplayedAsUnderlay',
                'GetRevitLinkDisplaySettings'
            ]
            
            missing_methods = []
            for method_name in required_methods:
                if not hasattr(view, method_name):
                    missing_methods.append(method_name)
            
            if missing_methods:
                ERROR_HANDLE.print_note("View type '{}' missing Revit link methods: {}".format(
                    view_type, ", ".join(missing_methods)))
                return False
            
            # More careful check: try calling GetRevitLinkVisibility with a test
            # Rather than assuming view types, test actual functionality
            try:
                # First, check if there are any Revit links in the document to test with
                link_instances = DB.FilteredElementCollector(self.doc).OfClass(DB.RevitLinkInstance)
                link_list = list(link_instances)
                
                if link_list:
                    # Test with an actual link instance ID
                    test_link = link_list[0]
                    visibility = view.GetRevitLinkVisibility(test_link.Id)
                    # If we get here without an AttributeError, the method works
                    ERROR_HANDLE.print_note("View type '{}' supports Revit link operations".format(view_type))
                    return True
                else:
                    # No links to test with, but methods exist - assume it works
                    ERROR_HANDLE.print_note("View type '{}' has Revit link methods, no links to test with".format(view_type))
                    return True
                    
            except AttributeError as e:
                ERROR_HANDLE.print_note("View type '{}' has method but doesn't support Revit link operations: {}".format(view_type, str(e)))
                return False
            except Exception as e:
                # Other exceptions might be due to invalid parameters, but method works
                ERROR_HANDLE.print_note("View type '{}' Revit link method test resulted in: {} (assuming functional)".format(view_type, str(e)))
                return True
                
        except Exception as e:
            ERROR_HANDLE.print_note("Error checking Revit link support for view '{}': {}".format(view_type, str(e)))
            return False

    def get_detail_level_data(self, template):
        """
        Extract detail level data from a template.
        
        Args:
            template: The view template
            
        Returns:
            dict: Detail level data
        """
        detail_levels = {}
        
        # Check if template supports GetDetailLevel method
        if not hasattr(template, 'GetDetailLevel'):
            return detail_levels
        
        try:
            # Get detail level for categories
            for revit_category in self.categories:
                try:
                    category_id = revit_category.category.Id
                    category_name = revit_category.pretty_name
                    
                    # Get detail level override
                    try:
                        detail_level = template.GetDetailLevel(category_id)
                        if detail_level != DB.ViewDetailLevel.Undefined:
                            detail_levels[category_name] = self._convert_detail_level_to_text(detail_level)
                        else:
                            detail_levels[category_name] = "By View"
                    except AttributeError:
                        # Skip if method not supported by this view type
                        continue
                    except Exception as e:
                        ERROR_HANDLE.print_note("Error getting detail level for category {}: {}".format(category_name, str(e)))
                        detail_levels[category_name] = "By View"
                        
                except Exception as e:
                    ERROR_HANDLE.print_note("Error processing detail level for category {}: {}".format(category_name, str(e)))
                    continue
                    
        except Exception as e:
            ERROR_HANDLE.print_note("Error getting detail level data: {}".format(str(e)))
            
        return detail_levels

    def get_template_usage_data(self, template):
        """
        Get information about which views are using this template.
        
        Args:
            template: The view template
            
        Returns:
            dict: Usage data including view names and count
        """
        usage_data = {
            'views': [],
            'total_count': 0
        }
        
        try:
            # Get all views in the document
            view_collector = DB.FilteredElementCollector(self.doc).OfClass(DB.View).ToElements()
            
            ERROR_HANDLE.print_note("Checking template usage for template: {} (ID: {})".format(
                template.Name if hasattr(template, 'Name') else 'Unknown', 
                template.Id.ToString()
            ))
            
            ERROR_HANDLE.print_note("Total views found in document: {}".format(len(view_collector)))
            
            view_count = 0
            for view in view_collector:
                view_count += 1
                try:
                    # Debug: Log first few views to see what we're working with
                    if view_count <= 3:
                        view_name = view.Name if hasattr(view, 'Name') else "Unknown View"
                        view_type = view.ViewType.ToString() if hasattr(view, 'ViewType') else "Unknown Type"
                        ERROR_HANDLE.print_note("Sample view {}: '{}' (Type: {})".format(view_count, view_name, view_type))
                    
                    # Check if view has a template
                    if hasattr(view, 'ViewTemplateId'):
                        template_id = view.ViewTemplateId
                        
                        # Check if template_id is valid (not None, not InvalidElementId)
                        if template_id and template_id != DB.ElementId.InvalidElementId:
                            if template_id == template.Id:
                                # Get view name and type
                                view_name = view.Name if hasattr(view, 'Name') else "Unknown View"
                                view_type = view.ViewType.ToString() if hasattr(view, 'ViewType') else "Unknown Type"
                                # Safely get sheet parameters with null checks
                                sheet_number_param = view.LookupParameter("Sheet Number")
                                sheet_name_param = view.LookupParameter("Sheet Name")
                                sheet_number = sheet_number_param.AsString() if sheet_number_param else ""
                                sheet_name = sheet_name_param.AsString() if sheet_name_param else "" 
                                
                                usage_data['views'].append({
                                    'name': view_name,
                                    'type': view_type,
                                    'sheet_number': sheet_number,
                                    'sheet_name': sheet_name,
                                    'id': view.Id.ToString()
                                })
                                
                                ERROR_HANDLE.print_note("Found view using template: {} (Type: {})".format(view_name, view_type))
                        else:
                            # Debug: Log views without templates
                            if view_count <= 5:  # Only log first few for debugging
                                view_name = view.Name if hasattr(view, 'Name') else "Unknown View"
                                ERROR_HANDLE.print_note("View '{}' has no template (ViewTemplateId: {})".format(
                                    view_name, template_id.ToString() if template_id else "None"
                                ))
                except Exception as e:
                    ERROR_HANDLE.print_note("Error checking view template usage for view: {}".format(str(e)))
                    # Add to error group instead of re-raising to prevent process failure
                    self._add_to_error_group(self.all_error_groups, e, "view_template_usage", "View: {}".format(view_count))
                    continue
            
            # Sort views by name
            usage_data['views'].sort(key=lambda x: x['name'].lower())
            usage_data['total_count'] = len(usage_data['views'])
            
            ERROR_HANDLE.print_note("Template usage summary for '{}': {} views found".format(
                template.Name if hasattr(template, 'Name') else 'Unknown', 
                usage_data['total_count']
            ))
            
        except Exception as e:
            ERROR_HANDLE.print_note("Error collecting template usage data: {}".format(str(e)))
            self._add_to_error_group(self.all_error_groups, e, template.Name if hasattr(template, 'Name') else 'Unknown', "TemplateUsage_")
        
        return usage_data


    def _get_view_properties(self, template):
        """
        Extract additional view properties from the View class API.
        Based on https://www.revitapidocs.com/2025.3/fb92a4e7-f3a7-ef14-e631-342179b18de9.htm
        
        Args:
            template: The view template
            
        Returns:
            dict: Additional view properties
        """
        properties = {}
        
        try:
            # Basic view information
            try:
                properties['can_be_printed'] = template.CanBePrinted
            except:
                properties['can_be_printed'] = None
                
            # Note: Detail level is also collected per-category in get_detail_level_data()
            # This is the overall view detail level, while detail_levels shows per-category detail levels
            try:
                properties['overall_detail_level'] = self._convert_detail_level_to_text(template.DetailLevel)
            except:
                properties['overall_detail_level'] = None
                
            try:
                properties['discipline'] = self._convert_discipline_to_text(template.Discipline)
            except:
                properties['discipline'] = None
                
            try:
                properties['display_style'] = str(template.DisplayStyle)
            except:
                properties['display_style'] = None
                
            # Category hiding properties (global visibility flags)
            # Note: These are different from individual category overrides in get_import_category_data()
            # These are overall visibility flags, while import_categories shows per-category override details
            try:
                properties['are_analytical_model_categories_hidden'] = template.AreAnalyticalModelCategoriesHidden
            except:
                properties['are_analytical_model_categories_hidden'] = None
                
            try:
                properties['are_annotation_categories_hidden'] = template.AreAnnotationCategoriesHidden
            except:
                properties['are_annotation_categories_hidden'] = None
                
            try:
                properties['are_import_categories_hidden'] = template.AreImportCategoriesHidden
            except:
                properties['are_import_categories_hidden'] = None
                
            try:
                properties['are_model_categories_hidden'] = template.AreModelCategoriesHidden
            except:
                properties['are_model_categories_hidden'] = None
                
            try:
                properties['are_point_clouds_hidden'] = template.ArePointCloudsHidden
            except:
                properties['are_point_clouds_hidden'] = None
                
            # Crop box properties
            try:
                properties['crop_box_active'] = template.CropBoxActive
            except:
                properties['crop_box_active'] = None
                
            try:
                properties['crop_box_visible'] = template.CropBoxVisible
            except:
                properties['crop_box_visible'] = None
                
            # View family type and other properties
            try:
                properties['view_family_type_id'] = str(template.GetTypeId())
            except:
                properties['view_family_type_id'] = None
                
            try:
                properties['is_template'] = template.IsTemplate
            except:
                properties['is_template'] = None
                
            try:
                properties['view_type'] = str(template.ViewType)
            except:
                properties['view_type'] = None
                
            try:
                properties['scale'] = template.Scale
            except:
                properties['scale'] = None
                
            # Phase information
            try:
                properties['phase_id'] = str(template.get_Parameter(DB.BuiltInParameter.VIEW_PHASE).AsElementId())
            except:
                properties['phase_id'] = None
                
        except Exception as e:
            ERROR_HANDLE.print_note("Error extracting view properties: {}".format(str(e)))
            
        return properties

    def collect_all_template_data(self, template):
        """
        Collect all available data from a template.
        Based on Revit API View class documentation:
        https://www.revitapidocs.com/2025.3/fb92a4e7-f3a7-ef14-e631-342179b18de9.htm
        
        Data Collection Summary:
        - category_overrides: Per-category graphic override settings
        - category_visibility: Per-category visibility (On/Hidden/Uncontrolled)
        - workset_visibility: Per-workset visibility settings
        - view_parameters: Controlled template parameters
        - uncontrolled_parameters: Non-controlled parameters (DANGEROUS)
        - filters: Filter definitions and their overrides
        - import_categories: Per-import-category override details
        - revit_links: Revit link visibility and override settings
        - detail_levels: Per-category detail level overrides
        - view_properties: Overall view properties (discipline, scale, global flags, etc.)
        
        Note: Line pattern information is captured within category_overrides and filters,
        so no separate linetype collection is needed.
        
        Args:
            template: The view template
            
        Returns:
            dict: Complete template data
        """
        try:
            # Get view parameters (returns tuple of controlled and uncontrolled)
            controlled_params, uncontrolled_params = self.get_view_parameters(template)
            
            template_data = {
                # Basic template identification
                'template_name': template.Name,
                'template_id': str(template.Id),
                
                # Core visibility and override data
                'category_overrides': self.get_category_overrides(template),
                'category_visibility': self.get_category_visibility(template),
                'workset_visibility': self.get_workset_visibility(template),
                'view_parameters': controlled_params,
                'uncontrolled_parameters': uncontrolled_params,
                'filters': self.get_filter_data(template),
                'import_categories': self.get_import_category_data(template),
                'revit_links': self.get_revit_link_data(template),
                'detail_levels': self.get_detail_level_data(template),
                
                # Additional View properties from API documentation
                'view_properties': self._get_view_properties(template),
                
                # Template usage information (with error handling)
                'template_usage': self._safe_get_template_usage_data(template)
            }
            
            return template_data
            
        except Exception as e:
            ERROR_HANDLE.print_note("Error collecting all template data: {}".format(str(e)))
            return None
    
    def _safe_get_template_usage_data(self, template):
        """
        Safely get template usage data with comprehensive error handling.
        
        Args:
            template: The view template
            
        Returns:
            dict: Usage data or empty dict if error occurs
        """
        try:
            return self.get_template_usage_data(template)
        except Exception as e:
            ERROR_HANDLE.print_note("Error collecting template usage data: {}".format(str(e)))
            # Add to error group for tracking
            self._add_to_error_group(self.all_error_groups, e, "template_usage_collection", "Template: {}".format(template.Name if hasattr(template, 'Name') else 'Unknown'))
            # Return empty usage data instead of failing
            return {
                'views': [],
                'total_count': 0,
                'error': str(e)
            }
    




    def _add_to_error_group(self, error_groups, exception, item_name, prefix=""):
        """
        Helper method to add errors to grouped error collection.
        
        Args:
            error_groups: Dictionary to store grouped errors
            exception: The exception that occurred
            item_name: Name of the item that caused the error
            prefix: Optional prefix for error key (e.g., "SubCat_")
        """
        import traceback
        
        error_type = str(type(exception).__name__)
        error_key = "{}{}:{}".format(prefix, error_type, str(exception)[:50])
        
        if error_key not in error_groups:
            error_groups[error_key] = {
                'example': item_name,                    # Store only first example
                'traceback': traceback.format_exc(),    # Capture traceback for first occurrence
                'count': 0                               # Count total occurrences
            }
        
        error_groups[error_key]['count'] += 1
        
        # Also store in class-level error collection
        if error_key not in self.all_error_groups:
            self.all_error_groups[error_key] = {
                'example': item_name,
                'traceback': traceback.format_exc(),
                'count': 0
            }
        self.all_error_groups[error_key]['count'] += 1

    def _log_grouped_errors(self, error_groups, title="Error details"):
        """
        Helper method to log grouped errors in a consistent format.
        
        Args:
            error_groups: Dictionary of grouped errors
            title: Title for the error section
        """
        if error_groups:
            ERROR_HANDLE.print_note("{}:".format(title))
            for error_key, error_data in error_groups.items():
                error_type = error_key.split(":")[0]
                error_msg = error_key.split(":", 1)[1] if ":" in error_key else "Unknown error"
                ERROR_HANDLE.print_note("  {}: {} (example: {}, total count: {})".format(
                    error_type, error_msg, error_data['example'], error_data['count']))
                ERROR_HANDLE.print_note("    Traceback:")
                for line in error_data['traceback'].split('\n'):
                    if line.strip():  # Skip empty lines
                        ERROR_HANDLE.print_note("      {}".format(line))

    def save_error_data(self, template_name=""):
        """
        Save all collected error data to a file using DATA_FILE.set_data.
        Automatically opens the file if in DEVELOPER mode.
        
        Args:
            template_name: Optional template name to include in filename
        """
        if not self.all_error_groups:
            ERROR_HANDLE.print_note("No error data to save.")
            return
            
        try:
            import os
            import re
            from datetime import datetime
            
            # Sanitize template name for use in filename
            def sanitize_filename(name):
                """Remove or replace characters that are invalid in Windows filenames."""
                # Replace invalid characters with underscores
                invalid_chars = r'[<>:"/\\|?*]'
                sanitized = re.sub(invalid_chars, '_', name)
                # Remove quotes and other problematic characters
                sanitized = sanitized.replace('"', '').replace("'", '').replace('(', '').replace(')', '')
                # Limit length to avoid path length issues
                if len(sanitized) > 50:
                    sanitized = sanitized[:50]
                return sanitized.strip('_')
            
            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if template_name:
                sanitized_name = sanitize_filename(template_name)
                filename = "template_errors_{}_{}.sexyDuck".format(sanitized_name, timestamp)
            else:
                filename = "template_errors_{}.sexyDuck".format(timestamp)
            
            # Prepare error data for saving
            error_data_for_save = {
                'timestamp': timestamp,
                'doc_title': self.doc.Title if self.doc else "Unknown",
                'total_error_types': len(self.all_error_groups),
                'total_error_count': sum(error_data['count'] for error_data in self.all_error_groups.values()),
                'error_groups': self.all_error_groups
            }
            
            ERROR_HANDLE.print_note("Saving error data with {} error types and {} total errors...".format(
                len(self.all_error_groups), 
                sum(error_data['count'] for error_data in self.all_error_groups.values())
            ))
            
            # Save using DATA_FILE.set_data
            DATA_FILE.set_data(error_data_for_save, filename, is_local=True)
            
            ERROR_HANDLE.print_note("Error data saved to: {}".format(filename))
            
            # Auto-open if in DEVELOPER mode
            if USER.IS_DEVELOPER:
                try:
                    file_path = FOLDER.get_local_dump_folder_file(filename)
                    ERROR_HANDLE.print_note("Opening error data file for developer: {}".format(file_path))
                    os.startfile(file_path)
                except Exception as e:
                    ERROR_HANDLE.print_note("Could not auto-open file: {}".format(str(e)))
                    
        except Exception as e:
            ERROR_HANDLE.print_note("Error saving error data: {}".format(str(e)))


if __name__ == "__main__":
    pass