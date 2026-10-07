"""Utility functions for EnneadTab.

This module provides common utility functions used across the EnneadTab ecosystem.
"""

import re
import logging

def sanitize_name_for_export(name, replacement_char="_", log_changes=True):
    """
    Sanitize names for export to Revit by removing/replacing forbidden characters.
    
    This function handles all forbidden characters that can cause issues when exporting
    from Rhino to Revit, including block names and layer names.
    
    Args:
        name (str): Original name to sanitize
        replacement_char (str): Character to replace forbidden characters with. Defaults to "_"
        log_changes (bool): Whether to log when names are changed. Defaults to True
        
    Returns:
        str: Sanitized name safe for Revit export
        
    Examples:
        >>> sanitize_name_for_export("Block:Name[1]")
        'Block_Name_1_'
        >>> sanitize_name_for_export("Layer\\Path")
        'Layer_Path'
    """
    if not name:
        return name
        
    original_name = name
    
    # Define all forbidden characters for Revit exports
    # Based on Revit error messages and Windows filename restrictions
    # Includes: \ / : * ? " < > | { } [ ] ; ` ~
    forbidden_chars = r'[\\/:*?"<>|{}[\];`~]'
    
    # Replace forbidden characters with replacement character
    sanitized_name = re.sub(forbidden_chars, replacement_char, name)
    
    # Remove leading/trailing whitespace and replacement characters
    sanitized_name = sanitized_name.strip(replacement_char)
    
    # Remove leading/trailing whitespace
    sanitized_name = sanitized_name.strip()
    
    # Ensure the name is not empty after sanitization
    if not sanitized_name:
        sanitized_name = "Unnamed"
    
    # Log changes if requested and name was modified
    if log_changes and sanitized_name != original_name:
        try:
            logger = logging.getLogger(__name__)
            logger.info("Sanitized name for export: '{}' -> '{}'".format(original_name, sanitized_name))
        except:
            # Fallback if logging is not available
            print("Sanitized name for export: '{}' -> '{}'".format(original_name, sanitized_name))
    
    return sanitized_name


def sanitize_block_name(block_name, replacement_char="_"):
    """
    Sanitize block names specifically for Revit export.
    
    Args:
        block_name (str): Original block name
        replacement_char (str): Character to replace forbidden characters with
        
    Returns:
        str: Sanitized block name
    """
    return sanitize_name_for_export(block_name, replacement_char, log_changes=True)


def sanitize_layer_name(layer_name, replacement_char="_"):
    """
    Sanitize layer names specifically for Revit export.
    
    Args:
        layer_name (str): Original layer name
        replacement_char (str): Character to replace forbidden characters with
        
    Returns:
        str: Sanitized layer name
    """
    return sanitize_name_for_export(layer_name, replacement_char, log_changes=True)


def sanitize_revit_name(name, replacement_char="_"):
    """
    Sanitize names specifically for Revit use (materials, subcategories, etc.).
    
    Based on Revit error messages and naming rules:
    - Material names: "{, }, [, ], |, ;, less-than sign, greater-than sign, ?, `, ~"
    - View names: "\\ : { } [ ] | ; < > ? ` ~"
    
    Args:
        name (str): Original name to sanitize
        replacement_char (str): Character to replace forbidden characters with
        
    Returns:
        str: Sanitized name safe for Revit use
    """
    if not name:
        return name
        
    original_name = name
    
    # Replace periods with underscores (common Revit rule)
    name = name.replace('.', '_')
    
    # Define Revit-specific forbidden characters
    # Based on Revit error messages: "{, }, [, ], |, ;, less-than sign, greater-than sign, ?, `, ~"
    # Also including other common problematic characters: \, :
    prohibited_chars = r'{}[]|;<>?`~\\:'
    
    # Replace forbidden characters with replacement character
    sanitized_name = name
    for char in prohibited_chars:
        sanitized_name = sanitized_name.replace(char, replacement_char)
    
    # Remove leading/trailing whitespace and replacement characters
    sanitized_name = sanitized_name.strip(replacement_char)
    
    # Remove leading/trailing whitespace
    sanitized_name = sanitized_name.strip()
    
    # Ensure the name is not empty after sanitization
    if not sanitized_name:
        sanitized_name = "Unnamed"
    
    # Log changes if name was modified
    if sanitized_name != original_name:
        try:
            logger = logging.getLogger(__name__)
            logger.info("Sanitized Revit name: '{}' -> '{}'".format(original_name, sanitized_name))
        except:
            # Fallback if logging is not available
            print("Sanitized Revit name: '{}' -> '{}'".format(original_name, sanitized_name))
    
    return sanitized_name
