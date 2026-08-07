#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Parameter Updater Module - Updates Revit area parameters with suggestions
Handles both matched areas (clear suggestion) and unmatched areas (set suggestion)
"""

from Autodesk.Revit import DB # pyright: ignore
from EnneadTab.REVIT import REVIT_SELECTION
import config
import suggestion_logic


def update_area_parameters(doc, matches_by_scheme, unmatched_by_scheme):
    """
    Update parameters for all areas:
    - Matched areas: Clear UnMatchedSuggestion, set RoomDataTarget to target DGSF
    - Unmatched areas: Set UnMatchedSuggestion text, clear RoomDataTarget
    
    Args:
        doc: Revit document
        matches_by_scheme: Dictionary of matches by scheme from AreaMatcher
        unmatched_by_scheme: Dictionary of unmatched areas by scheme
        
    Returns:
        dict: Statistics about the update operation
    """
    print("\n=== PARAMETER UPDATE DEBUG ===")
    print("Matches by scheme keys: {}".format(matches_by_scheme.keys()))
    print("Unmatched by scheme keys: {}".format(unmatched_by_scheme.keys()))
    
    stats = {
        'matched_cleared': 0,
        'matched_skipped': 0,
        'unmatched_updated': 0,
        'unmatched_skipped': 0,
        'target_dgsf_updated': 0,
        'errors': []
    }
    
    # Start a transaction to modify parameters
    transaction = DB.Transaction(doc, "Update Area Suggestions")
    transaction.Start()
    
    try:
        # Process matched areas - clear suggestion, set target DGSF (only if valid area)
        for scheme_name, scheme_data in matches_by_scheme.items():
            matches = scheme_data.get('matches', [])
            for match in matches:
                matching_areas = match.get('matching_areas', [])
                target_dgsf_excel = match.get('target_dgsf', 0)
                
                for area_object in matching_areas:
                    # Only set target DGSF if area is valid (not "Not Placed" or "Not Enclosed")
                    area_status = area_object.get('area_status', 'Good')
                    target_dgsf = target_dgsf_excel if area_status == 'Good' else 0
                    
                    result = _update_matched_area_parameters(area_object, target_dgsf)
                    if result['success']:
                        stats['matched_cleared'] += 1
                        if result.get('target_dgsf_set') and target_dgsf > 0:
                            stats['target_dgsf_updated'] += 1
                    else:
                        stats['matched_skipped'] += 1
                        if result.get('error'):
                            stats['errors'].append(result['error'])
        
        # Process unmatched areas - set suggestion text
        for scheme_name, unmatched_areas in unmatched_by_scheme.items():
            print("Processing {} unmatched areas for scheme: {}".format(len(unmatched_areas), scheme_name))

            scheme_matches = matches_by_scheme.get(scheme_name, {})
            valid_items = suggestion_logic.build_valid_items(scheme_matches.get('matches', []))

            for area_object in unmatched_areas:
                if not area_object.get('suggestion_text'):
                    suggestion_text = suggestion_logic.get_suggestion_text(
                        area_object.get('department', ''),
                        area_object.get('program_type', ''),
                        area_object.get('program_type_detail', ''),
                        valid_items
                    )
                    if suggestion_text:
                        area_object['suggestion_text'] = suggestion_text

                result = _set_suggestion_parameter(area_object)
                if result['success']:
                    stats['unmatched_updated'] += 1
                else:
                    stats['unmatched_skipped'] += 1
                    if result.get('error'):
                        stats['errors'].append(result['error'])
                        print("  Skipped area - Error: {}".format(result['error']))
        
        transaction.Commit()
        print("Transaction committed successfully")
        
    except Exception as e:
        transaction.RollBack()
        stats['errors'].append("Transaction failed: {}".format(str(e)))
        print("Transaction rolled back - Error: {}".format(str(e)))
    
    print("\n=== PARAMETER UPDATE STATS ===")
    print("Matched cleared: {}".format(stats['matched_cleared']))
    print("Target DGSF set: {}".format(stats['target_dgsf_updated']))
    print("Matched skipped: {}".format(stats['matched_skipped']))
    print("Unmatched updated: {}".format(stats['unmatched_updated']))
    print("Unmatched skipped: {}".format(stats['unmatched_skipped']))
    print("Errors: {}".format(len(stats['errors'])))
    if stats['errors']:
        print("Error details:")
        for error in stats['errors'][:5]:  # Show first 5 errors
            print("  - {}".format(error))
    print("=== END DEBUG ===\n")
    
    return stats


def _update_matched_area_parameters(area_object, target_dgsf):
    """
    Update parameters for a matched area:
    - Clear UnMatchedSuggestion (no longer needed)
    - Set RoomDataTarget to target DGSF from Excel
    
    Args:
        area_object: Dictionary containing area data including 'revit_element'
        target_dgsf: Target DGSF value from Excel requirements
        
    Returns:
        dict: Result with 'success' boolean, 'target_dgsf_set', and optional 'error' message
    """
    result = {'success': False, 'target_dgsf_set': False}
    
    try:
        area = area_object.get('revit_element')
        if not area:
            result['error'] = "No Revit element reference found"
            return result
        
        # Check if element is editable using EnneadTab utility
        if not REVIT_SELECTION.is_changable(area):
            result['error'] = "Element not editable (checked out by another user)"
            return result
        
        # Clear UnMatchedSuggestion parameter
        suggestion_param = area.LookupParameter(config.UNMATCHED_SUGGESTION_PARAM)
        if suggestion_param and not suggestion_param.IsReadOnly:
            suggestion_param.Set("")
        
        # Set RoomDataTarget parameter
        target_param = area.LookupParameter(config.TARGET_DGSF_PARAM)
        if target_param:
            if target_param.IsReadOnly:
                result['error'] = "RoomDataTarget parameter is read-only"
            else:
                # Set the target DGSF value
                target_param.Set(target_dgsf)
                result['target_dgsf_set'] = True
                result['success'] = True
        else:
            # Parameter doesn't exist - still mark as success since suggestion was cleared
            result['success'] = True
        
    except Exception as e:
        result['error'] = "Error updating parameters: {}".format(str(e))
    
    return result


def _set_suggestion_parameter(area_object):
    """
    Set the UnMatchedSuggestion parameter and clear RoomDataTarget for an unmatched area
    
    Args:
        area_object: Dictionary containing area data including suggestion info
        
    Returns:
        dict: Result with 'success' boolean and optional 'error' message
    """
    result = {'success': False}
    
    try:
        area = area_object.get('revit_element')
        if not area:
            result['error'] = "No Revit element reference found"
            return result
        
        # Check if element is editable using EnneadTab utility
        if not REVIT_SELECTION.is_changable(area):
            result['error'] = "Element not editable (checked out by another user)"
            return result
        
        # Set UnMatchedSuggestion parameter
        param = area.LookupParameter(config.UNMATCHED_SUGGESTION_PARAM)
        
        if param and not param.IsReadOnly:
            # Get suggestion from area_object or generate it
            suggestion_text = area_object.get('suggestion_text', '')

            # If no suggestion text is stored, use shared fallback text
            if not suggestion_text:
                suggestion_text = suggestion_logic.get_no_suggestion_text()

            param.Set(suggestion_text)
        
        # Clear RoomDataTarget parameter (unmatched areas have no target)
        target_param = area.LookupParameter(config.TARGET_DGSF_PARAM)
        if target_param and not target_param.IsReadOnly:
            target_param.Set(0.0)  # Clear to zero
        
        result['success'] = True
        
    except Exception as e:
        result['error'] = "Error setting parameter: {}".format(str(e))
    
    return result