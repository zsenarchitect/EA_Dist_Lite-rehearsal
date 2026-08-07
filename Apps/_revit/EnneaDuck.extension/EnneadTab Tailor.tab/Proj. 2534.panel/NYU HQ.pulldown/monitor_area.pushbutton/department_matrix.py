#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Department-Level Matrix Helper

Builds a level x department table of actual Revit areas, renders HTML, and
prepares Excel payloads for the NYU HQ area monitor report.
"""

import os
from EnneadTab import TIME

from EnneadTab import COLOR, EXCEL


DEFAULT_DEPARTMENT_NAME = "UNASSIGNED"
DEFAULT_LEVEL_NAME = "Unknown Level"


def _safe_float(value):
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _normalize_department(name):
    if name:
        text = str(name).strip()
        if text:
            return text
    return DEFAULT_DEPARTMENT_NAME


def _normalize_level(level_name):
    if level_name:
        text = str(level_name).strip()
        if text:
            return text
    return DEFAULT_LEVEL_NAME


def _get_department_color(department, color_hierarchy):
    if color_hierarchy:
        dept_colors = color_hierarchy.get('department', {})
        color_value = dept_colors.get(department)
        if color_value:
            return color_value
    return "#374151"


def _hex_to_rgba(hex_color, alpha):
    try:
        rgb = COLOR.hex_to_rgb(hex_color)
        return "rgba({0}, {1}, {2}, {3})".format(rgb[0], rgb[1], rgb[2], alpha)
    except Exception:
        return "rgba(55, 65, 81, {0})".format(alpha)


def _lighten_color(hex_color, blend_ratio):
    try:
        rgb = COLOR.hex_to_rgb(hex_color)
        r = int(rgb[0] + (255 - rgb[0]) * blend_ratio)
        g = int(rgb[1] + (255 - rgb[1]) * blend_ratio)
        b = int(rgb[2] + (255 - rgb[2]) * blend_ratio)
        return (r, g, b)
    except Exception:
        blend_value = int(55 + (255 - 55) * blend_ratio)
        return (blend_value, blend_value, blend_value)


def _format_area(value, show_sign=False):
    number = _safe_float(value)
    if show_sign:
        return "{0:+,.2f} SF".format(number)
    return "{0:,.2f} SF".format(number)


def _format_excel_area(value, show_sign=False):
    number = _safe_float(value)
    if show_sign:
        return "{0:+,.2f} SF".format(number)
    return "{0:,.2f} SF".format(number)


def _collect_departments(matches):
    ordered = []
    seen = set()

    for match in matches:
        dept = _normalize_department(match.get('department'))
        if dept not in seen:
            ordered.append(dept)
            seen.add(dept)

    if not ordered:
        ordered.append(DEFAULT_DEPARTMENT_NAME)

    return ordered


def _collect_levels(revit_areas):
    level_map = {}
    for area in revit_areas:
        level_name = _normalize_level(area.get('level_name'))
        elevation = area.get('level_elevation')
        elevation_value = _safe_float(elevation)
        if level_name not in level_map:
            level_map[level_name] = {'name': level_name, 'elevation': elevation_value}
        else:
            current = level_map[level_name]['elevation']
            if elevation_value != 0.0 and current == 0.0:
                level_map[level_name]['elevation'] = elevation_value

    levels = level_map.values()
    levels = sorted(levels, key=lambda item: item['elevation'], reverse=True)
    return levels


def build_matrix(matches, revit_areas, color_hierarchy=None):
    sorted_matches = sorted(matches, key=lambda item: item.get('excel_row_index', 0))

    departments = _collect_departments(sorted_matches)

    approved_set = set(departments)
    filtered_areas = []
    for area in revit_areas:
        dept = _normalize_department(area.get('department'))
        if dept in approved_set:
            filtered_areas.append(area)

    levels = _collect_levels(filtered_areas)

    cell_values = {}
    level_totals = {}
    department_totals = {}

    for level in levels:
        cell_values[level['name']] = {}
        level_totals[level['name']] = 0.0
        for dept in departments:
            cell_values[level['name']][dept] = 0.0

    for area in filtered_areas:
        dept = _normalize_department(area.get('department'))
        level_name = _normalize_level(area.get('level_name'))
        elevation = _safe_float(area.get('level_elevation'))
        area_value = _safe_float(area.get('area_sf'))

        if level_name not in cell_values:
            cell_values[level_name] = {}
            for dept_name in departments:
                cell_values[level_name][dept_name] = 0.0
            level_totals[level_name] = 0.0
            levels.append({'name': level_name, 'elevation': elevation})

        if dept not in cell_values[level_name]:
            cell_values[level_name][dept] = 0.0

        cell_values[level_name][dept] += area_value
        level_totals[level_name] += area_value

        if dept not in department_totals:
            department_totals[dept] = 0.0
        department_totals[dept] += area_value

    levels = sorted({level['name']: level for level in levels}.values(), key=lambda item: item['elevation'], reverse=True)

    target_totals = {}
    for match in sorted_matches:
        dept = _normalize_department(match.get('department'))
        target_value = _safe_float(match.get('target_dgsf'))
        if dept not in target_totals:
            target_totals[dept] = 0.0
        target_totals[dept] += target_value

    for dept in departments:
        if dept not in department_totals:
            department_totals[dept] = 0.0
        if dept not in target_totals:
            target_totals[dept] = 0.0

    delta_totals = {}
    for dept in departments:
        delta_totals[dept] = department_totals[dept] - target_totals.get(dept, 0.0)

    department_colors = {}
    for dept in departments:
        department_colors[dept] = _get_department_color(dept, color_hierarchy)

    total_actual = sum(department_totals.values())
    total_target = sum(target_totals.values())
    total_delta = total_actual - total_target

    matrix_data = {
        'departments': departments,
        'levels': levels,
        'cell_values': cell_values,
        'level_totals': level_totals,
        'department_totals': department_totals,
        'target_totals': target_totals,
        'delta_totals': delta_totals,
        'department_colors': department_colors,
        'grand_totals': {
            'actual': total_actual,
            'target': total_target,
            'delta': total_delta
        }
    }

    return matrix_data


def render_html(matrix_data, section_id):
    departments = matrix_data['departments']
    levels = matrix_data['levels']
    cell_values = matrix_data['cell_values']
    department_colors = matrix_data['department_colors']
    target_totals = matrix_data['target_totals']
    department_totals = matrix_data['department_totals']
    delta_totals = matrix_data['delta_totals']

    header_cells = []
    for dept in departments:
        color = department_colors.get(dept, "#374151")
        header_html = """
            <th class=\"dept-header\" style=\"background:{0};\">
                <span>{1}</span>
            </th>
        """.format(color, dept)
        header_cells.append(header_html)

    body_rows = []
    for level in levels:
        level_name = level['name']
        row_cells = []
        for dept in departments:
            actual_value = cell_values.get(level_name, {}).get(dept, 0.0)
            color = department_colors.get(dept, "#374151")
            rgba = _hex_to_rgba(color, 0.18)
            cell_class = "matrix-cell"
            if actual_value == 0:
                cell_class += " empty"
            cell_html = """
                <td class=\"{0}\" style=\"background:{1};\">
                    <span>{2}</span>
                </td>
            """.format(cell_class, rgba, _format_area(actual_value))
            row_cells.append(cell_html)

        row_html = """
            <tr>
                <td class=\"matrix-level\">{0}</td>
                {1}
            </tr>
        """.format(level_name, "".join(row_cells))
        body_rows.append(row_html)

    total_row_cells = []
    target_row_cells = []
    delta_row_cells = []

    for dept in departments:
        color = department_colors.get(dept, "#374151")
        light_rgb = _lighten_color(color, 0.45)
        total_cell = """
            <td class=\"summary-cell\" style=\"background:rgba({0}, {1}, {2}, 0.35);\">{3}</td>
        """.format(light_rgb[0], light_rgb[1], light_rgb[2], _format_area(department_totals.get(dept, 0.0)))
        total_row_cells.append(total_cell)

        target_value = target_totals.get(dept, 0.0)
        target_cell = """
            <td class=\"summary-cell program-target\">{0}</td>
        """.format(_format_area(target_value))
        target_row_cells.append(target_cell)

        delta_value = delta_totals.get(dept, 0.0)
        delta_class = "summary-cell delta"
        if delta_value > 0:
            delta_class += " positive"
        elif delta_value < 0:
            delta_class += " negative"
        delta_cell = """
            <td class=\"{0}\">{1}</td>
        """.format(delta_class, _format_area(delta_value, show_sign=True))
        delta_row_cells.append(delta_cell)

    table_html = """
        <section class=\"level-matrix-section\" id=\"matrix-{0}\">
            <h2>🏢 Department DGSF by Level</h2>
            <p class=\"matrix-description\">Actual Revit DGSF per department on each level, ranked by elevation.</p>
            <div class=\"matrix-scroll\">
                <table class=\"department-matrix\">
                    <thead>
                        <tr>
                            <th class=\"matrix-level-header\">Level</th>
                            {1}
                        </tr>
                    </thead>
                    <tbody>
                        {2}
                        <tr class=\"summary-row total\">
                            <td class=\"summary-title\">TOTAL DGSF</td>
                            {3}
                        </tr>
                        <tr class=\"summary-row target\">
                            <td class=\"summary-title\">PROGRAM TARGET</td>
                            {4}
                        </tr>
                        <tr class=\"summary-row delta\">
                            <td class=\"summary-title\">DELTA</td>
                            {5}
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>
    """.format(section_id, "".join(header_cells), "".join(body_rows), "".join(total_row_cells), "".join(target_row_cells), "".join(delta_row_cells))

    return table_html


def _sanitize_filename(value):
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    sanitized = value
    for ch in invalid_chars:
        sanitized = sanitized.replace(ch, '_')
    return sanitized.strip()


def build_excel_collection(matrix_data, scheme_name):
    departments = matrix_data['departments']
    levels = matrix_data['levels']
    cell_values = matrix_data['cell_values']
    department_totals = matrix_data['department_totals']
    target_totals = matrix_data['target_totals']
    delta_totals = matrix_data['delta_totals']
    department_colors = matrix_data['department_colors']

    collection = EXCEL.ExcelDataCollection()

    header_row_index = 0
    level_header_item = EXCEL.ExcelDataItem("LEVEL", header_row_index, 0, is_bold=True, cell_color=(55, 65, 81), text_color=(255, 255, 255))
    collection.add(level_header_item)

    for col_index, dept in enumerate(departments):
        color_hex = department_colors.get(dept, "#374151")
        rgb_color = COLOR.hex_to_rgb(color_hex)
        header_item = EXCEL.ExcelDataItem(
            dept,
            header_row_index,
            col_index + 1,
            is_bold=True,
            cell_color=rgb_color,
            text_color=(255, 255, 255),
            border_style=EXCEL.BorderStyle.Thick
        )
        collection.add(header_item)

    current_row = 1
    for level in levels:
        level_name = level['name']
        level_item = EXCEL.ExcelDataItem(level_name, current_row, 0,
                                      is_bold=True,
                                      cell_color=(31, 41, 55),
                                      text_color=(255, 255, 255),
                                      border_style=EXCEL.BorderStyle.Thin)
        collection.add(level_item)

        for col_index, dept in enumerate(departments):
            value = cell_values.get(level_name, {}).get(dept, 0.0)
            color_hex = department_colors.get(dept, "#374151")
            light_rgb = _lighten_color(color_hex, 0.65)
            cell_item = EXCEL.ExcelDataItem(_format_excel_area(value), current_row, col_index + 1,
                                            cell_color=light_rgb,
                                            border_style=EXCEL.BorderStyle.Thin,
                                            text_alignment=EXCEL.TextAlignment.Right)
            collection.add(cell_item)

        current_row += 1

    summary_specs = [
        ("TOTAL DGSF", department_totals, (16, 185, 129)),
        ("PROGRAM TARGET", target_totals, (59, 130, 246)),
        ("DELTA", delta_totals, (249, 115, 22))
    ]

    for title, data_map, base_rgb in summary_specs:
        title_item = EXCEL.ExcelDataItem(title, current_row, 0,
                                         is_bold=True,
                                         cell_color=base_rgb,
                                         text_color=(255, 255, 255),
                                         border_style=EXCEL.BorderStyle.Thin)
        collection.add(title_item)

        for col_index, dept in enumerate(departments):
            value = data_map.get(dept, 0.0)
            cell_color = (base_rgb[0], base_rgb[1], base_rgb[2])
            text_color = None
            if title == "DELTA":
                if value > 0:
                    cell_color = (22, 163, 74)
                    text_color = (255, 255, 255)
                elif value < 0:
                    cell_color = (220, 38, 38)
                    text_color = (255, 255, 255)

            cell_item = EXCEL.ExcelDataItem(
                _format_excel_area(value, show_sign=(title == "DELTA")),
                current_row,
                col_index + 1,
                cell_color=cell_color,
                text_color=text_color,
                is_bold=True,
                border_style=EXCEL.BorderStyle.Thin,
                text_alignment=EXCEL.TextAlignment.Right)
            collection.add(cell_item)

        current_row += 1

    timestamp = TIME.get_human_readable_datetime()
    timestamp_merge = [(current_row, col_index) for col_index in range(1, len(departments) + 1)]
    timestamp_item = EXCEL.ExcelDataItem(
        "Generated: {0}".format(timestamp),
        current_row,
        0,
        cell_color=(30, 41, 59),
        text_color=(203, 213, 225),
        border_style=EXCEL.BorderStyle.Thin,
        text_alignment=EXCEL.TextAlignment.Left,
        merge_with=timestamp_merge
    )
    collection.add(timestamp_item)

    total_columns = len(departments) + 1

    existing_items = collection.data
    for item in existing_items:
        item.row += 1
        if getattr(item, 'merge_with', None):
            shifted_merges = []
            for merge_entry in item.merge_with:
                try:
                    merge_row, merge_col = merge_entry
                except (TypeError, ValueError):
                    shifted_merges.append(merge_entry)
                    continue

                try:
                    new_row = merge_row + 1
                except TypeError:
                    new_row = merge_row

                shifted_merges.append((new_row, merge_col))
            item.merge_with = shifted_merges

    collection.data = []
    collection.used_coord = {}
    collection.row = 0
    collection.column = 0
    if hasattr(collection, 'header_row') and collection.header_row is not None:
        collection.header_row += 1

    merge_targets = [(0, col_index) for col_index in range(1, total_columns)]

    title_item = EXCEL.ExcelDataItem(
        "DGSF Delta: {0}".format(scheme_name),
        0,
        0,
        is_bold=True,
        cell_color=(17, 24, 39),
        text_color=(248, 250, 252),
        border_style=EXCEL.BorderStyle.Thin,
        text_alignment=EXCEL.TextAlignment.Left,
        merge_with=merge_targets
    )
    collection.add(title_item)

    for item in existing_items:
        collection.add(item)

    return collection


def write_excel(matrix_data, scheme_name, base_directory):
    if not base_directory or not os.path.isdir(base_directory):
        return False

    safe_scheme = _sanitize_filename(scheme_name)
    filename = "DGSF_DIFF_{0}.xlsx".format(safe_scheme)
    filepath = os.path.join(base_directory, filename)

    collection = build_excel_collection(matrix_data, scheme_name)

    try:
        EXCEL.save_data_to_excel(collection.data, filepath, worksheet=safe_scheme, open_after=False, freeze_row=2, freeze_column=1)
        return filepath
    except Exception as exc:
        print("Failed to write Excel for scheme {0}: {1}".format(scheme_name, exc))
        return False

