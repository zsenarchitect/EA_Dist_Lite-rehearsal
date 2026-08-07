#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Config Loader Module for Auto Export System
Handles loading and parsing of config.json with template substitution
IronPython 2.7 compatible
"""

import os
import json

# Cache for loaded config to avoid repeated file reads
_cached_config = None
_config_file_mtime = None


def _get_config_path():
    """Get the path to the active config file
    
    Priority:
    1. Read from current_job_payload.json if it exists
    2. Look for single config in configs/ folder
    3. Fallback to AutoExportConfig_2534_NYU_HQ.json in configs/
    
    Returns:
        str: Full path to config file
    """
    script_dir = os.path.dirname(__file__)
    
    # Try to read from payload file
    payload_file = os.path.join(script_dir, "current_job_payload.json")
    if os.path.exists(payload_file):
        try:
            with open(payload_file, 'r') as f:
                payload = json.load(f)
            config_path = payload.get('config_path')
            if config_path and os.path.exists(config_path):
                return config_path
        except:
            pass
    
    # Try to find single config in configs folder
    configs_dir = os.path.join(script_dir, "configs")
    if os.path.exists(configs_dir):
        import glob
        config_files = glob.glob(os.path.join(configs_dir, "AutoExportConfig_*.json"))
        if len(config_files) == 1:
            return config_files[0]
        elif len(config_files) > 1:
            # Multiple configs found, return first alphabetically
            config_files.sort()
            return config_files[0]
    
    # Fallback to hardcoded path in configs folder
    config_path = os.path.join(configs_dir, "AutoExportConfig_2534_NYU_HQ.json")
    return config_path


def _substitute_templates(obj, replacements):
    """Recursively substitute template placeholders in strings
    
    Args:
        obj: Object to process (dict, list, string, or other)
        replacements: Dictionary of placeholder->value mappings
    
    Returns:
        Processed object with templates replaced
    """
    if isinstance(obj, dict):
        # Python 2/3 compatible iteration
        try:
            items = obj.iteritems()  # Python 2
        except AttributeError:
            items = obj.items()  # Python 3
        return dict((k, _substitute_templates(v, replacements)) for k, v in items)
    elif isinstance(obj, list):
        return [_substitute_templates(item, replacements) for item in obj]
    elif isinstance(obj, str):  # Python 3
        result = obj
        try:
            items = replacements.iteritems()  # Python 2
        except AttributeError:
            items = replacements.items()  # Python 3
        for placeholder, value in items:
            result = result.replace("{" + placeholder + "}", value)
        return result
    else:
        # Python 2 unicode/str handling
        try:
            if isinstance(obj, basestring):  # Python 2
                result = obj
                for placeholder, value in replacements.iteritems():
                    result = result.replace("{" + placeholder + "}", value)
                return result
        except NameError:
            pass  # Python 3, already handled above
        return obj


def load_config(force_reload=False):
    """Load and parse AutoExportConfig_2534_NYU_HQ.json with template substitution
    
    Args:
        force_reload: If True, reload config even if cached
    
    Returns:
        dict: Parsed configuration dictionary
    
    Raises:
        IOError: If AutoExportConfig_2534_NYU_HQ.json not found
        ValueError: If AutoExportConfig_2534_NYU_HQ.json is malformed
    """
    global _cached_config, _config_file_mtime
    
    config_path = _get_config_path()
    
    # Check if we need to reload
    if not force_reload and _cached_config is not None:
        try:
            current_mtime = os.path.getmtime(config_path)
            if current_mtime == _config_file_mtime:
                return _cached_config
        except:
            pass
    
    # Load config file
    if not os.path.exists(config_path):
        raise IOError("Config file not found: {}".format(config_path))
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except ValueError as e:
        raise ValueError("Invalid JSON in config file: {}".format(str(e)))
    except Exception as e:
        raise Exception("Failed to load config file: {}".format(str(e)))
    
    # Prepare template replacements
    replacements = {
        'username': os.environ.get('USERNAME', 'unknown'),
        'userprofile': os.environ.get('USERPROFILE', ''),
        'computername': os.environ.get('COMPUTERNAME', 'unknown')
    }
    
    # Substitute templates in config
    config = _substitute_templates(config, replacements)
    
    # Cache the config
    _cached_config = config
    try:
        _config_file_mtime = os.path.getmtime(config_path)
    except:
        _config_file_mtime = None
    
    return config


def get_project_info():
    """Get project information settings
    
    Returns:
        dict: Project info with keys: project_name, pim_parameter_name
    """
    config = load_config()
    return config.get('project', {
        'project_name': 'Unknown Project',
        'pim_parameter_name': 'PIM_Number'
    })


def get_model_data(doc_name=None):
    """Get model data configuration
    
    Args:
        doc_name: Optional specific model name to retrieve
    
    Returns:
        dict: Model data dictionary (all models or specific model)
    """
    config = load_config()
    models = config.get('models', {})
    
    if doc_name:
        return models.get(doc_name)
    return models


def get_export_settings():
    """Get export-related settings
    
    Returns:
        dict: Export settings including paths, parameters, and options
    """
    config = load_config()
    return config.get('export', {
        'output_base_path': '',
        'sheet_filter_parameter': 'Sheet_$Issue_AutoPublish',
        'dwg_setting_name': 'to NYU dwg',
        'pdf_color_parameter': 'Print_In_Color',
        'subfolders': ['pdf', 'dwg', 'jpg'],
        'date_format': '%Y-%m-%d',
        'pdf_options': {},
        'jpg_options': {}
    })


def get_email_settings():
    """Get email-related settings
    
    Returns:
        dict: Email settings including recipients, templates, and options
    """
    config = load_config()
    return config.get('email', {
        'recipients': [],
        'subject_template': 'Auto Export Completed - {date}',
        'enable_notifications': True
    })


def get_path_settings():
    """Get path-related settings
    
    Returns:
        dict: Path settings including dev_root, dist_root, lib_paths
    """
    config = load_config()
    return config.get('paths', {
        'dev_root': '',
        'dist_root': '',
        'lib_paths': []
    })


def get_heartbeat_settings():
    """Get heartbeat logging settings
    
    Returns:
        dict: Heartbeat settings including enabled, folder_name, date_format
    """
    config = load_config()
    return config.get('heartbeat', {
        'enabled': True,
        'folder_name': 'heartbeat',
        'date_format': '%Y%m%d'
    })


def validate_config():
    """Validate that required config fields exist
    
    Returns:
        tuple: (is_valid, list_of_errors)
    """
    errors = []
    
    try:
        config = load_config()
    except Exception as e:
        return (False, ["Failed to load config: {}".format(str(e))])
    
    # Check required top-level keys
    required_keys = ['project', 'models', 'export', 'email']
    for key in required_keys:
        if key not in config:
            errors.append("Missing required config section: {}".format(key))
    
    # Check project info
    if 'project' in config:
        if 'project_name' not in config['project']:
            errors.append("Missing project.project_name in config")
    
    # Check models
    if 'models' in config:
        if not config['models']:
            errors.append("No models defined in config")
        # Python 2/3 compatible iteration
        try:
            model_items = config['models'].iteritems()  # Python 2
        except AttributeError:
            model_items = config['models'].items()  # Python 3
        
        for model_name, model_data in model_items:
            required_model_keys = ['model_guid', 'project_guid', 'region', 'revit_version']
            for key in required_model_keys:
                if key not in model_data:
                    errors.append("Model '{}' missing required key: {}".format(model_name, key))
    
    # Check export settings
    if 'export' in config:
        if 'output_base_path' not in config['export']:
            errors.append("Missing export.output_base_path in config")
    
    # Check email settings
    if 'email' in config:
        if 'recipients' not in config['email']:
            errors.append("Missing email.recipients in config")
        elif not config['email']['recipients']:
            errors.append("email.recipients list is empty")
    
    is_valid = len(errors) == 0
    return (is_valid, errors)


def get_current_config_name():
    """Get the name of the currently active config file
    
    Returns:
        str: Config filename (e.g., 'AutoExportConfig_2534_NYU_HQ.json')
    """
    config_path = _get_config_path()
    return os.path.basename(config_path)


def get_current_job_id():
    """Get the current job ID from payload file
    
    Returns:
        str: Job ID or None if not available
    """
    script_dir = os.path.dirname(__file__)
    payload_file = os.path.join(script_dir, "current_job_payload.json")
    
    if os.path.exists(payload_file):
        try:
            with open(payload_file, 'r') as f:
                payload = json.load(f)
            return payload.get('job_id')
        except:
            pass
    
    return None


def get_model_name():
    """Get the name of the first model in the config
    
    Returns:
        str: Model name (key from models dict) or 'Unknown Model' if not found
    """
    config = load_config()
    models = config.get('models', {})
    
    if not models:
        return 'Unknown Model'
    
    # Get the first model name (key)
    # Python 2/3 compatible
    try:
        # Python 2
        return models.keys()[0]
    except TypeError:
        # Python 3 - keys() returns a view, need to convert to list
        return list(models.keys())[0]


# Helper function for backward compatibility
def get_all_config():
    """Get entire config dictionary (for debugging or advanced use)
    
    Returns:
        dict: Complete configuration
    """
    return load_config()


if __name__ == "__main__":
    pass