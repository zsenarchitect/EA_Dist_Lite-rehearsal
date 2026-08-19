"""
KeynoteExporter - Data Export Module

This module handles all data export functionality including JSON and Revit keynote file generation.
It provides clean interfaces for exporting keynote data in various formats.
"""

import json
import logging
from typing import List
from .keynote_data import KeynoteData

logger = logging.getLogger(__name__)


def export_keynote_data_to_json(keynote_data: List[KeynoteData], output_path: str) -> None:
    """
    Export keynote data to JSON file.
    
    Args:
        keynote_data: List of KeynoteData objects
        output_path: Path for output JSON file
    """
    export_data = []
    
    for keynote in keynote_data:
        entry = {
            'keynote_number': keynote.get_string_field('KEYNOTE #'),
            'keynote_description': keynote.get_string_field('KEYNOTE DESCRIPTION'),
            'division_number': keynote.get_string_field('DIVISION #'),
            'division_name': keynote.get_string_field('DIVISION NAME'),
            'section_number': keynote.get_string_field('SECTION #'),
            'section_name': keynote.get_string_field('SECTION NAME'),
            'string_fields': keynote.get_all_data(),
            'interior_scope': keynote.get_interior_scope_fields(),
            'exterior_scope': keynote.get_exterior_scope_fields()
        }
        export_data.append(entry)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Successfully exported {len(keynote_data)} keynote entries to {output_path}")


def export_keynote_data_to_revit_txt(keynote_data: List[KeynoteData], output_path: str) -> None:
    """
    Export complete keynote hierarchy to Revit keynote txt format.
    Groups all division nodes first, then all section nodes, then all keynote entries.
    
    Args:
        keynote_data: List of KeynoteData objects
        output_path: Path for output txt file
    """
    from .keynote_tree_visualizer import build_hierarchy
    from .keynote_config import KeynoteConfig

    config = KeynoteConfig()
    notes_marker = config.get_notes_format_suffix()
    notes_mode = config.get_notes_format_mode()

    # Build hierarchy to get divisions and sections
    tree = build_hierarchy(keynote_data)

    # Build (division_label, section_label) -> list of KeynoteData in same order as tree entries,
    # so we can look up FORMAT per entry when writing. We append the configured invisible char to
    # NOTE keys so Revit can use it in schedule filters to filter NOTES from other data types.
    section_to_items: dict = {}
    for item in keynote_data:
        div_no = item.get_string_field("DIVISION #").strip()
        div_name = item.get_string_field("DIVISION NAME").strip()
        sec_no = item.get_string_field("SECTION #").strip()
        sec_name = item.get_string_field("SECTION NAME").strip()
        if not div_no and not div_name:
            continue
        division_label = f"{div_no} - {div_name}".strip(" -")
        section_label = f"{sec_no} - {sec_name}".strip(" -") if (sec_no or sec_name) else "(Unsectioned)"
        key = (division_label, section_label)
        if key not in section_to_items:
            section_to_items[key] = []
        key_no = item.get_string_field("KEYNOTE #").strip()
        key_desc = item.get_string_field("KEYNOTE DESCRIPTION").strip()
        if key_no or key_desc:
            section_to_items[key].append(item)
    
    with open(output_path, 'w', encoding='utf-16-le') as f:
        # Write UTF-16 LE BOM (Byte Order Mark) for compatibility
        f.write('\ufeff')
        # PHASE 1: Export all division nodes first (root level)
        divisions = []
        for division_label in sorted(tree.keys(), key=_natural_sort_key):
            div_parts = division_label.split(' - ', 1)
            div_num = div_parts[0] if div_parts else ""
            div_name = div_parts[1] if len(div_parts) > 1 else div_parts[0]
            divisions.append((div_num, div_name))
            # Division node: Division Number | Division Name | (no parent)
            f.write(f"{div_num}\t{div_name}\t\n")
        
        # PHASE 2: Export all section nodes (with division as parent)
        sections = []
        for division_label, sections_dict in sorted(tree.items(), key=lambda x: _natural_sort_key(x[0])):
            div_parts = division_label.split(' - ', 1)
            div_num = div_parts[0] if div_parts else ""
            
            for section_label in sorted(sections_dict.keys()):
                sec_parts = section_label.split(' - ', 1)
                sec_num = sec_parts[0] if sec_parts else ""
                sec_name = sec_parts[1] if len(sec_parts) > 1 else sec_parts[0]
                sections.append((sec_num, sec_name, div_num))
                # Section node: Section Number | Section Name | Division Number (parent)
                f.write(f"{sec_num}\t{sec_name}\t{div_num}\n")
        
        # PHASE 3: Export all keynote entries (with section as parent)
        for division_label, sections_dict in sorted(tree.items(), key=lambda x: _natural_sort_key(x[0])):
            for section_label, entries in sorted(sections_dict.items()):
                sec_parts = section_label.split(' - ', 1)
                sec_num = sec_parts[0] if sec_parts else ""
                items_list = section_to_items.get((division_label, section_label), [])
                for idx, (keynote_num, keynote_desc) in enumerate(entries):
                    if not (keynote_num and keynote_desc):
                        continue
                    item = items_list[idx] if idx < len(items_list) else None
                    # Apply configured NOTES marker so Revit schedules can filter by type.
                    if item and item.get_string_field("FORMAT").strip().upper() == "NOTES":
                        if notes_mode == "prefix":
                            key = f"{notes_marker}{keynote_num}"
                        else:
                            # Default: suffix (original behavior, typically invisible whitespace)
                            key = f"{keynote_num}{notes_marker}"
                    else:
                        key = keynote_num
                    # Keynote entry: Keynote Number | Keynote Description | Section Number (parent)
                    f.write(f"{key}\t{keynote_desc}\t{sec_num}\n")
    
    logger.info(f"Successfully exported complete hierarchy to Revit txt file: {output_path}")


def _natural_sort_key(division_label):
    """Extract division number for natural sorting."""
    import re
    match = re.match(r'^(\d+)', division_label)
    return int(match.group(1)) if match else 999