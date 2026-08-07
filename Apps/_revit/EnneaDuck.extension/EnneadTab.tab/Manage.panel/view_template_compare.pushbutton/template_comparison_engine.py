# IronPython 2.7 Compatible
"""
Template Comparison Engine Module

This module handles the comparison logic for finding differences between view templates,
including special handling for uncontrolled parameters.
"""


class TemplateComparisonEngine:
    """
    Handles comparison logic between view templates.
    
    This class is responsible for comparing template data and finding differences,
    with special priority handling for uncontrolled parameters.
    """
    
    def __init__(self, comparison_data):
        """
        Initialize the comparison engine.
        
        Args:
            comparison_data: Dictionary containing template data for comparison
        """
        self.comparison_data = comparison_data
    
    def find_all_differences(self, template_names):
        """
        Find all differences between templates.
        
        Args:
            template_names: List of template names to compare
            
        Returns:
            dict: All differences found, organized by type
        """
        template_differences = {
            'category_graphic_overrides': {},      # Category line, pattern, color overrides
            'category_visibility_settings': {},    # Category show/hide settings
            'workset_visibility_settings': {},     # Workset show/hide settings
            'template_controlled_parameters': {},  # Parameters controlled by template
            'dangerous_uncontrolled_parameters': {}, # Parameters not controlled (can cause inconsistencies)
            'filter_settings': {},                 # Filter enable, visibility, and graphic overrides
            'import_category_overrides': {},       # Import category graphic overrides
            'revit_link_overrides': {},           # Revit link visibility and graphic overrides
            'category_detail_levels': {},         # Per-category detail level settings
            'view_behavior_properties': {}        # Core view properties (discipline, detail level, etc.)
        }
        
        # Compare category graphic overrides (lines, patterns, colors)
        template_differences['category_graphic_overrides'] = self._compare_dict_values('category_overrides', template_names)
        
        # Compare category visibility settings (show/hide)
        template_differences['category_visibility_settings'] = self._compare_dict_values('category_visibility', template_names)
        
        # Compare workset visibility settings (show/hide)
        template_differences['workset_visibility_settings'] = self._compare_dict_values('workset_visibility', template_names)
        
        # Compare template-controlled parameters (with values)
        template_differences['template_controlled_parameters'] = self._compare_parameter_values('view_parameters', template_names)
        
        # Compare dangerous uncontrolled parameters (can cause inconsistencies)
        # Based on Revit API: GetNonControlledTemplateParameterIds() returns parameters 
        # that are NOT marked as included when the view is used as a template
        # These can cause inconsistent behavior across views using the same template
        all_uncontrolled_params = set()
        for template_name, data in self.comparison_data.items():
            all_uncontrolled_params.update(data['uncontrolled_parameters'])
            
        for param in all_uncontrolled_params:
            param_values = {}
            for template_name in template_names:
                param_values[template_name] = param in self.comparison_data[template_name]['uncontrolled_parameters']
                    
            if len(set(param_values.values())) > 1:
                template_differences['dangerous_uncontrolled_parameters'][param] = param_values
        
        # Compare filter settings (enable, visibility, graphic overrides)
        template_differences['filter_settings'] = self._compare_filter_data('filters', template_names)
        
        # Compare import category overrides
        template_differences['import_category_overrides'] = self._compare_dict_values('import_categories', template_names)
        
        # Compare Revit link overrides
        template_differences['revit_link_overrides'] = self._compare_dict_values('revit_links', template_names)
        
        # Compare category detail level settings
        template_differences['category_detail_levels'] = self._compare_dict_values('detail_levels', template_names)
        
        # Compare view behavior properties (discipline, detail level, etc.)
        template_differences['view_behavior_properties'] = self._compare_dict_values('view_properties', template_names)
        
        return template_differences
    
    def _compare_dict_values(self, data_key, template_names):
        """
        Generic method to compare dictionary values across templates.
        
        Special handling for uncontrolled parameters:
        - If a parameter is uncontrolled in any template, it's marked as "UNCONTROLLED"
        - Uncontrolled parameters are highlighted with dark orange background in HTML
        - This takes priority over normal value comparison
        
        Args:
            data_key: Key in comparison_data to compare
            template_names: List of template names
            
        Returns:
            dict: Differences found
        """
        differences = {}
        
        # Collect all keys from all templates
        all_keys = set()
        for template_name, data in self.comparison_data.items():
            if data_key in data and data[data_key] is not None:
                all_keys.update(data[data_key].keys())
            else:
                print("Warning: {} not found in template {} data".format(data_key, template_name))
        
        # Compare each key across templates
        for key in all_keys:
            key_values = {}
            for template_name in template_names:
                if (data_key in self.comparison_data[template_name] and 
                    self.comparison_data[template_name][data_key] is not None and
                    key in self.comparison_data[template_name][data_key]):
                    key_values[template_name] = self.comparison_data[template_name][data_key][key]
                else:
                    key_values[template_name] = None
            
            # Check if values are different
            if self._has_differences(key_values):
                differences[key] = key_values
        
        return differences
    
    def _compare_parameter_values(self, data_key, template_names):
        """
        Compare parameter values across templates.
        
        Shows both control status and actual values:
        - If parameter is controlled in both templates, compares the values
        - If parameter is controlled in one but not the other, shows "Controlled" vs "Not Controlled"
        - If parameter values differ between controlled templates, shows the actual values
        - Excludes "Workset" parameter as it's not relevant for template comparison
        
        Args:
            data_key: Key in comparison_data to compare (should be 'view_parameters')
            template_names: List of template names
            
        Returns:
            dict: Differences found with parameter values
        """
        differences = {}
        
        # Collect all parameter names from all templates
        all_params = set()
        for template_name, data in self.comparison_data.items():
            # Get controlled parameters (dict)
            controlled_params = data[data_key]
            all_params.update(controlled_params.keys())
            
            # Get uncontrolled parameters (list)
            uncontrolled_params = data.get('uncontrolled_parameters', [])
            all_params.update(uncontrolled_params)
        
        # Compare each parameter across templates
        for param_name in all_params:
            # Skip the "Workset" parameter as it's not relevant for template comparison
            if param_name.lower() == "workset":
                continue
                
            param_data = {}
            
            for template_name in template_names:
                template_data = self.comparison_data[template_name]
                controlled_params = template_data[data_key]
                uncontrolled_params = template_data.get('uncontrolled_parameters', [])
                
                if param_name in controlled_params:
                    # Parameter is controlled, show its value
                    param_data[template_name] = controlled_params[param_name]
                elif param_name in uncontrolled_params:
                    # Parameter is not controlled
                    param_data[template_name] = "Not Controlled"
                else:
                    # Parameter doesn't exist in this template
                    param_data[template_name] = "Not Present"
            
            # Check if values are different across templates
            unique_values = set(param_data.values())
            if len(unique_values) > 1:
                differences[param_name] = param_data
        
        return differences
    
    def _compare_list_values(self, data_key, template_names):
        """
        Generic method to compare list values across templates.
        
        Special handling for uncontrolled parameters:
        - If a parameter is uncontrolled in any template, it's marked as "UNCONTROLLED"
        - Uncontrolled parameters are highlighted with dark orange background in HTML
        - This takes priority over normal value comparison
        
        Args:
            data_key: Key in comparison_data to compare
            template_names: List of template names
            
        Returns:
            dict: Differences found
        """
        differences = {}
        
        # Collect all values from all templates
        all_values = set()
        for template_name, data in self.comparison_data.items():
            all_values.update(data[data_key])
        
        # Compare each value across templates
        for value in all_values:
            value_presence = {}
            for template_name in template_names:
                value_presence[template_name] = value in self.comparison_data[template_name][data_key]
            
            # Check if presence is different across templates
            if len(set(value_presence.values())) > 1:
                differences[value] = value_presence
        
        return differences
    
    def _compare_filter_data(self, data_key, template_names):
        """
        Compare filter data across templates with enhanced structure.
        
        Compares:
        - Filter enable status (enabled/disabled)
        - Filter visibility status (visible/hidden)
        - Graphic override settings
        
        Args:
            data_key: Key in comparison_data to compare
            template_names: List of template names
            
        Returns:
            dict: Filter differences found
        """
        differences = {}
        
        # Collect all filter names from all templates
        all_filters = set()
        for template_name, data in self.comparison_data.items():
            if data_key in data:
                all_filters.update(data[data_key].keys())
        
        # Compare each filter across templates
        for filter_name in all_filters:
            filter_values = {}
            for template_name in template_names:
                template_data = self.comparison_data[template_name]
                if data_key in template_data and filter_name in template_data[data_key]:
                    filter_values[template_name] = template_data[data_key][filter_name]
                else:
                    filter_values[template_name] = None
            
            # Check if filter data is different across templates
            if self._has_filter_differences(filter_values):
                differences[filter_name] = filter_values
        
        return differences
    
    def _has_filter_differences(self, filter_values):
        """
        Check if filter values are different across templates.
        
        Args:
            filter_values: Dictionary of filter data per template
            
        Returns:
            bool: True if differences found, False if all the same
        """
        values = list(filter_values.values())
        if not values:
            return False
        
        # Remove None values for comparison
        non_none_values = [v for v in values if v is not None]
        if len(non_none_values) <= 1:
            return len(values) != len(non_none_values)  # True if some templates don't have this filter
        
        # Compare enable status
        first_enabled = non_none_values[0].get('enabled', False)
        if not all(v.get('enabled', False) == first_enabled for v in non_none_values):
            return True
        
        # Compare visibility status
        first_visible = non_none_values[0].get('visible', False)
        if not all(v.get('visible', False) == first_visible for v in non_none_values):
            return True
        
        # Compare graphic overrides
        first_overrides = non_none_values[0].get('graphic_overrides', {})
        if not all(v.get('graphic_overrides', {}) == first_overrides for v in non_none_values):
            return True
        
        return False
    
    def _has_differences(self, values_dict):
        """
        Check if values in a dictionary are different.
        
        Args:
            values_dict: Dictionary of values to compare
            
        Returns:
            bool: True if values are different, False if all the same
        """
        values = list(values_dict.values())
        if not values:
            return False
        
        # Check if all values are the same
        first_value = values[0]
        return not all(value == first_value for value in values)
    
    def get_summary_statistics(self, differences):
        """
        Get summary statistics of differences found.
        
        Args:
            differences: Dictionary of differences
            
        Returns:
            dict: Summary statistics
        """
        total_differences = sum(len(diff_dict) for diff_dict in differences.values())
        
        # Calculate category visibility breakdown for each template
        category_visibility_breakdown = {}
        for template_name, data in self.comparison_data.items():
            category_vis_data = data.get('category_visibility', {})
            on_visible_count = 0
            hidden_count = 0
            uncontrolled_count = 0
            
            for category, visibility_state in category_vis_data.items():
                if visibility_state in ['On', 'Visible']:
                    on_visible_count += 1
                elif visibility_state == 'Hidden':
                    hidden_count += 1
                elif visibility_state == 'UNCONTROLLED':
                    uncontrolled_count += 1
            
            category_visibility_breakdown[template_name] = {
                'on_visible': on_visible_count,
                'hidden': hidden_count,
                'uncontrolled': uncontrolled_count
            }
        
        return {
            'total_differences': total_differences,
            'category_graphic_overrides': len(differences['category_graphic_overrides']),
            'category_visibility_settings': len(differences['category_visibility_settings']),
            'workset_visibility_settings': len(differences['workset_visibility_settings']),
            'template_controlled_parameters': len(differences['template_controlled_parameters']),
            'dangerous_uncontrolled_parameters': len(differences['dangerous_uncontrolled_parameters']),
            'filter_settings': len(differences['filter_settings']),
            'import_category_overrides': len(differences['import_category_overrides']),
            'revit_link_overrides': len(differences['revit_link_overrides']),
            'category_detail_levels': len(differences['category_detail_levels']),
            'view_behavior_properties': len(differences['view_behavior_properties']),
            'category_visibility_breakdown': category_visibility_breakdown
        } 
    

if __name__ == "__main__":
    pass