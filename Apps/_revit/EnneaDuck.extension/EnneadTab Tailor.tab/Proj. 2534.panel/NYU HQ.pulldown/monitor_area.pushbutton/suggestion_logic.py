#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Shared suggestion logic for the NYU HQ area monitor.

This module centralizes the fuzzy matching used to recommend the closest
Excel program entry for unmatched Revit areas. Both the HTML report and the
Revit parameter writeback rely on the same helpers to ensure consistent
behaviour and messaging.
"""

SUGGESTION_SEPARATOR = " | "


def _normalize_text(value):
    """Convert value to a comparable lowercase string."""
    if value is None:
        return ""
    # Ensure value is a string for IronPython compatibility
    return str(value).strip()


def build_valid_items(valid_matches):
    """
    Build a list of valid program items that can be used for suggestion lookup.

    Args:
        valid_matches (list): List of match dictionaries from the area matcher.

    Returns:
        list: Normalized dictionaries containing department, division, and function.
    """
    items = []

    if not valid_matches:
        return items

    for match in valid_matches:
        department = _normalize_text(match.get('department', ''))
        division = _normalize_text(match.get('division', ''))
        function = _normalize_text(match.get('room_name', ''))

        items.append({
            'department': department,
            'division': division,
            'function': function
        })

    return items


def _is_priority_better(new_priority, current_priority):
    """Return True if new_priority outranks current_priority."""
    if current_priority is None:
        return True

    for new_value, existing_value in zip(new_priority, current_priority):
        if new_value > existing_value:
            return True
        if new_value < existing_value:
            return False

    return False


def _calculate_score(unmatched_dept, unmatched_div, unmatched_func, valid_item):
    """Calculate similarity score and tie-break data for a valid item."""
    dept_match = unmatched_dept == valid_item['department']
    div_match = unmatched_div == valid_item['division']
    func_match = unmatched_func == valid_item['function']

    score = 3

    if dept_match:
        score -= 1
    if div_match:
        score -= 1
    if func_match:
        score -= 1

    dept_partial = (not dept_match and unmatched_dept and unmatched_dept in valid_item['department'])
    div_partial = (not div_match and unmatched_div and unmatched_div in valid_item['division'])
    func_partial = (not func_match and unmatched_func and unmatched_func in valid_item['function'])

    if dept_partial:
        score -= 0.3
    if div_partial:
        score -= 0.3
    if func_partial:
        score -= 0.3

    tie_priority = (
        1 if dept_match else 0,
        1 if func_match else 0,
        1 if div_match else 0,
        1 if dept_partial else 0,
        1 if func_partial else 0,
        1 if div_partial else 0
    )

    return score, tie_priority


def find_best_suggestion(unmatched_dept, unmatched_div, unmatched_func, valid_items):
    """
    Find the closest matching valid item using fuzzy matching.

    Args:
        unmatched_dept (str): Department name from the unmatched area.
        unmatched_div (str): Division/Program Type from the unmatched area.
        unmatched_func (str): Function/Room Name from the unmatched area.
        valid_items (list): List of valid program entries produced by build_valid_items.

    Returns:
        dict or None: The best matching item (contains department/division/function) or None.
    """
    if not valid_items:
        return None

    unmatched_dept_norm = _normalize_text(unmatched_dept).lower()
    unmatched_div_norm = _normalize_text(unmatched_div).lower()
    unmatched_func_norm = _normalize_text(unmatched_func).lower()

    best_match = None
    best_score = 9999
    best_priority = None

    for valid_item in valid_items:
        score, tie_priority = _calculate_score(unmatched_dept_norm, unmatched_div_norm, unmatched_func_norm, {
            'department': valid_item['department'].lower(),
            'division': valid_item['division'].lower(),
            'function': valid_item['function'].lower()
        })

        if score < best_score:
            best_score = score
            best_match = valid_item
            best_priority = tie_priority
        elif score == best_score and _is_priority_better(tie_priority, best_priority):
            best_match = valid_item
            best_priority = tie_priority

    if best_match and best_score < 3:
        return best_match

    return None


def get_plain_text(suggestion_dict):
    """Convert a suggestion dictionary to the plain text representation."""
    if not suggestion_dict:
        return None

    department = suggestion_dict.get('department', '')
    division = suggestion_dict.get('division', '')
    function = suggestion_dict.get('function', '')

    return SUGGESTION_SEPARATOR.join([department, division, function])


def get_no_suggestion_text():
    """Return the shared message for when no suggestion can be generated."""
    return "No matching suggestion found"


def get_suggestion_text(unmatched_dept, unmatched_div, unmatched_func, valid_items):
    """
    Convenience helper to return a plain-text suggestion or None.

    Args:
        unmatched_dept (str): Department name from the unmatched area.
        unmatched_div (str): Division/Program Type from the unmatched area.
        unmatched_func (str): Function/Room Name from the unmatched area.
        valid_items (list): List of valid program entries produced by build_valid_items.

    Returns:
        str or None: Plain text suggestion if a match is found.
    """
    suggestion = find_best_suggestion(unmatched_dept, unmatched_div, unmatched_func, valid_items)
    if suggestion:
        return get_plain_text(suggestion)
    return None


