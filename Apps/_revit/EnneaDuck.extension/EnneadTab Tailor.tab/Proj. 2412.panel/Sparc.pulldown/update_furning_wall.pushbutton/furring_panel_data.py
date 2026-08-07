from Autodesk.Revit import DB  # pyright: ignore

from EnneadTab.REVIT import REVIT_FAMILY

from furring_constants import (
    CHILD_FAMILY_NAME,
    EXPECTED_PIER_MARKER_COUNT,
    FAMILY_INSTANCE_FILTER,
    FULL_SPANDREL_PARAMETER,
    MARKER_INDEX_PARAMETER,
    MARKER_PREFIX_PARAMETER,
    PIER_MARKER_ORDER,
    PANEL_HEIGHT_PARAMETER,
    PANEL_LOG_PREVIEW_LIMIT,
    ROOM_SEPARATOR_MARKER_ORDER,
    SILL_MARKER_ORDER,
    SILL_RAISED_PARAMETER,
    SILL_RAISED_HIGHER_PARAMETER,
    TARGET_PANEL_FAMILIES,
    IGNORE_FURRING_PARAMETER,
)


def get_family_name(element):
    symbol = getattr(element, "Symbol", None)
    if symbol:
        family = symbol.Family
        if family:
            return family.Name
    param = element.get_Parameter(DB.BuiltInParameter.ELEM_FAMILY_PARAM)
    if param:
        return param.AsString()
    return None


def get_parameter_value(element, parameter_name):
    parameter = element.LookupParameter(parameter_name)
    if parameter is None:
        return None
    value = parameter.AsString()
    if value:
        return value
    value = parameter.AsValueString()
    if value:
        return value
    if parameter.StorageType == DB.StorageType.Integer:
        return str(parameter.AsInteger())
    if parameter.StorageType == DB.StorageType.Double:
        return str(parameter.AsDouble())
    return None


def get_parameter_double(element, parameter_name):
    parameter = element.LookupParameter(parameter_name)
    if parameter is None:
        return None
    return parameter.AsDouble()


def get_parameter_bool(element, parameter_name, parameter=None):
    if parameter is None:
        parameter = element.LookupParameter(parameter_name)
    if parameter is None:
        return None
    if parameter.StorageType == DB.StorageType.Integer:
        return bool(parameter.AsInteger())
    value = get_parameter_value(element, parameter_name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "yes", "1"):
        return True
    if lowered in ("false", "no", "0"):
        return False
    return bool(int(value))


def _get_parameter_raw_value(parameter):
    if parameter is None:
        return None
    storage_type = parameter.StorageType
    if storage_type == DB.StorageType.Integer:
        return parameter.AsInteger()
    if storage_type == DB.StorageType.Double:
        return parameter.AsDouble()
    value = parameter.AsString()
    if value:
        return value
    return parameter.AsValueString()


def get_child_family_instances(parent_element, source_doc, target_family_name):
    child_groups = {}
    prefix_order = []
    child_ids = parent_element.GetDependentElements(FAMILY_INSTANCE_FILTER)
    for child_id in child_ids:
        child_element = source_doc.GetElement(child_id)
        if not child_element:
            continue
        child_family = get_family_name(child_element)
        if child_family == target_family_name:
            prefix_value = get_parameter_value(child_element, MARKER_PREFIX_PARAMETER)
            prefix_key = _normalize_marker_prefix(prefix_value)
            if prefix_key not in child_groups:
                child_groups[prefix_key] = {}
                prefix_order.append(prefix_key)
            index_value = get_parameter_value(child_element, MARKER_INDEX_PARAMETER)
            key = index_value if index_value else "unknown"
            group = child_groups[prefix_key]
            if key in group:
                suffix = 1
                candidate = "{0}_{1}".format(key, suffix)
                while candidate in group:
                    suffix += 1
                    candidate = "{0}_{1}".format(key, suffix)
                key = candidate
            group[key] = child_element
    grouped_children = []
    for prefix_key in prefix_order:
        grouped_children.append((prefix_key, child_groups[prefix_key]))
    return grouped_children


def _normalize_marker_prefix(prefix_value):
    if prefix_value is None:
        return None
    value = str(prefix_value).strip()
    if not value:
        return None
    return value


def collect_levels_with_z(doc):
    levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).WhereElementIsNotElementType()
    level_data = []
    for level in levels:
        level_z = level.ProjectElevation
        level_data.append((level, level_z))
    return level_data


def find_nearest_level(point, level_data):
    if not level_data:
        return (None, None)
    nearest_level = None
    nearest_level_z = None
    min_distance = None
    for level, level_z in level_data:
        distance = abs(point.Z - level_z)
        if (min_distance is None) or (distance < min_distance):
            min_distance = distance
            nearest_level = level
            nearest_level_z = level_z
    return (nearest_level, nearest_level_z)


def collect_panels_from_doc(source_doc, source_name, printed_ids, levels, transform, target_panel_families=None):
    if target_panel_families is None:
        target_panel_families = TARGET_PANEL_FAMILIES
    collector = DB.FilteredElementCollector(source_doc).OfCategory(DB.BuiltInCategory.OST_CurtainWallPanels).WhereElementIsNotElementType()
    panel_records = []
    panel_logs = []
    for element in collector:
        family_name = get_family_name(element)
        type_name = REVIT_FAMILY.get_family_type_name(element)
        if not _is_target_panel(family_name, type_name, target_panel_families):
            continue
        unique_id = element.UniqueId
        if unique_id in printed_ids:
            continue
        printed_ids.add(unique_id)
        ref_marker_groups = get_child_family_instances(element, source_doc, CHILD_FAMILY_NAME)
        pier_marker_groups, first_pier_point = _build_marker_groups(ref_marker_groups, PIER_MARKER_ORDER, transform)
        room_marker_groups, first_room_point = _build_marker_groups(ref_marker_groups, ROOM_SEPARATOR_MARKER_ORDER, transform)
        sill_marker_groups, first_sill_point = _build_marker_groups(ref_marker_groups, SILL_MARKER_ORDER, transform)
        if first_pier_point is None and first_room_point is None and first_sill_point is None:
            print("Skipping panel {0}; marker locations unavailable.".format(unique_id))
            continue
        first_marker_point = first_pier_point or first_room_point or first_sill_point
        if first_marker_point is not None:
            nearest_level, level_z = find_nearest_level(first_marker_point, levels)
        else:
            nearest_level = None
            level_z = None
        height_value = get_parameter_double(element, PANEL_HEIGHT_PARAMETER)
        is_full_spandrel = get_parameter_bool(element, FULL_SPANDREL_PARAMETER)
        ignore_param = element.LookupParameter(IGNORE_FURRING_PARAMETER)
        ignore_furring_flag = get_parameter_bool(element, IGNORE_FURRING_PARAMETER, parameter=ignore_param)
        ignore_furring_raw = _get_parameter_raw_value(ignore_param)
        ignore_furring_storage = str(ignore_param.StorageType) if ignore_param is not None else None
        is_sill_raised = get_parameter_bool(element, SILL_RAISED_PARAMETER)
        is_sill_raised_higher = get_parameter_bool(element, SILL_RAISED_HIGHER_PARAMETER)
        primary_pier_markers = pier_marker_groups[0]["markers"] if pier_marker_groups else {}
        primary_room_markers = room_marker_groups[0]["markers"] if room_marker_groups else {}
        primary_sill_markers = sill_marker_groups[0]["markers"] if sill_marker_groups else {}
        pier_marker_count = _count_markers_in_groups(pier_marker_groups)
        room_marker_count = _count_markers_in_groups(room_marker_groups)
        sill_marker_count = _count_markers_in_groups(sill_marker_groups)
        pier_group_count = len(pier_marker_groups)
        panel_record = {
            "source_name": source_name,
            "panel_unique_id": unique_id,
            "family_name": family_name,
            "type_name": type_name,
            "markers": primary_pier_markers,
            "pier_markers": primary_pier_markers,
            "pier_marker_groups": pier_marker_groups,
            "room_markers": primary_room_markers,
            "room_marker_groups": room_marker_groups,
            "sill_markers": primary_sill_markers,
            "sill_marker_groups": sill_marker_groups,
            "ref_marker_count": pier_marker_count,
            "pier_marker_count": pier_marker_count,
            "room_marker_count": room_marker_count,
            "sill_marker_count": sill_marker_count,
            "pier_marker_group_count": pier_group_count,
            "nearest_level": nearest_level,
            "nearest_level_z": level_z,
            "first_marker_point": first_marker_point,
            "panel_element": element,
            "panel_height": height_value,
            "is_full_spandrel": is_full_spandrel,
            "ignore_furring_flag": ignore_furring_flag,
            "ignore_furring_raw": ignore_furring_raw,
            "ignore_furring_storage": ignore_furring_storage,
            "is_sill_raised": is_sill_raised,
            "is_sill_raised_higher": is_sill_raised_higher,
        }
        panel_records.append(panel_record)
        panel_logs.append(_format_panel_info(panel_record))
    return panel_records, panel_logs


def _format_panel_info(panel_record):
    lines = []
    lines.append("\nPanel ({0}): {1}".format(panel_record["source_name"], panel_record["panel_unique_id"]))
    full_spandrel = panel_record.get("is_full_spandrel")
    if full_spandrel is None:
        full_spandrel_text = "Unknown"
    elif full_spandrel:
        full_spandrel_text = "Yes"
    else:
        full_spandrel_text = "No"
    lines.append("    Full spandrel: {0}".format(full_spandrel_text))
    ignore_flag = panel_record.get("ignore_furring_flag")
    if ignore_flag is None:
        ignore_text = "Not Set"
    elif ignore_flag:
        ignore_text = "True"
    else:
        ignore_text = "False"
    lines.append("    Ignore furring flag: {0}".format(ignore_text))
    raw_value = panel_record.get("ignore_furring_raw")
    storage_type = panel_record.get("ignore_furring_storage")
    lines.append("    Ignore furring raw value: {0} (StorageType: {1})".format(
        raw_value if raw_value is not None else "Not Available",
        storage_type if storage_type is not None else "Unknown",
    ))
    lines.append("    Pier marker total count: {0}".format(panel_record.get("pier_marker_count", 0)))
    pier_groups = panel_record.get("pier_marker_groups") or []
    if pier_groups:
        for group in pier_groups:
            prefix_label = _format_marker_prefix(group.get("prefix"))
            marker_data = group.get("markers", {})
            group_count = _count_markers(marker_data)
            lines.append("        Group {0}: {1}".format(prefix_label, group_count))
            for marker_key in PIER_MARKER_ORDER:
                entry = marker_data.get(marker_key)
                if entry is None or entry["element"] is None:
                    lines.append("            Missing pier marker for index \"{0}\".".format(marker_key))
                    continue
                point = entry["point_link"]
                if point is None:
                    lines.append("            {0}: Location not available.".format(marker_key))
                else:
                    lines.append("            {0}: {1}, {2}, {3} (UniqueId: {4})".format(
                        marker_key,
                        point.X,
                        point.Y,
                        point.Z,
                        entry["unique_id"]
                    ))
    else:
        pier_markers = panel_record.get("pier_markers", {})
        for marker_key in PIER_MARKER_ORDER:
            entry = pier_markers.get(marker_key)
            if entry is None or entry["element"] is None:
                lines.append("        Missing pier marker for index \"{0}\".".format(marker_key))
                continue
            point = entry["point_link"]
            if point is None:
                lines.append("        {0}: Location not available.".format(marker_key))
            else:
                lines.append("        {0}: {1}, {2}, {3} (UniqueId: {4})".format(
                    marker_key,
                    point.X,
                    point.Y,
                    point.Z,
                    entry["unique_id"]
                ))
    lines.append("    Room marker count: {0}".format(panel_record.get("room_marker_count", 0)))
    for marker_key in ROOM_SEPARATOR_MARKER_ORDER:
        entry = panel_record["room_markers"].get(marker_key)
        if entry is None or entry["element"] is None:
            lines.append("        Missing room marker for index \"{0}\".".format(marker_key))
            continue
        point = entry["point_link"]
        if point is None:
            lines.append("        {0}: Location not available.".format(marker_key))
        else:
            lines.append("        {0}: {1}, {2}, {3} (UniqueId: {4})".format(
                marker_key,
                point.X,
                point.Y,
                point.Z,
                entry["unique_id"]
            ))
    lines.append("    Sill marker count: {0}".format(panel_record.get("sill_marker_count", 0)))
    for marker_key in SILL_MARKER_ORDER:
        entry = panel_record["sill_markers"].get(marker_key)
        if entry is None or entry["element"] is None:
            lines.append("        Missing sill marker for index \"{0}\".".format(marker_key))
            continue
        point = entry["point_link"]
        if point is None:
            lines.append("        {0}: Location not available.".format(marker_key))
        else:
            lines.append("        {0}: {1}, {2}, {3} (UniqueId: {4})".format(
                marker_key,
                point.X,
                point.Y,
                point.Z,
                entry["unique_id"]
            ))
    group_total = panel_record.get("pier_marker_group_count", 0)
    if group_total < 1:
        group_total = 1
    expected_total = EXPECTED_PIER_MARKER_COUNT * group_total
    if panel_record["ref_marker_count"] != expected_total:
        lines.append("    Warning: Expected {0} pier RefMarker children but found {1}.".format(
            expected_total,
            panel_record["ref_marker_count"]
        ))
    nearest_level = panel_record["nearest_level"]
    level_z = panel_record["nearest_level_z"]
    first_point = panel_record.get("first_marker_point")
    if nearest_level is not None and level_z is not None and first_point is not None:
        offset = abs(first_point.Z - level_z)
        lines.append("    Closest level: {0} (Z={1}, delta={2})".format(nearest_level.Name, level_z, offset))
    else:
        lines.append("    Closest level: Not found.")
    return "\n".join(lines)


def _build_marker_entries(ref_markers, marker_keys, transform):
    marker_data = {}
    first_point = None
    for marker_key in marker_keys:
        marker_element = ref_markers.get(marker_key)
        entry = {
            "name": marker_key,
            "element": marker_element,
            "unique_id": None,
            "point_link": None,
            "point_host": None,
            "location_kind": "None",
            "diagnostic_note": None,
        }
        if marker_element is not None:
            entry["unique_id"] = marker_element.UniqueId
            point_link, point_host, location_kind, diagnostic_note = _extract_marker_points(marker_element, transform)
            entry["point_link"] = point_link
            entry["point_host"] = point_host
            entry["location_kind"] = location_kind
            entry["diagnostic_note"] = diagnostic_note
            if first_point is None and point_link is not None:
                first_point = point_link
        marker_data[marker_key] = entry
    return marker_data, first_point


def _extract_marker_points(marker_element, transform):
    location_kind = "None"
    diagnostic_parts = []
    point_link = None
    point_host = None
    if marker_element is None:
        diagnostic_parts.append("Marker element is None.")
        return point_link, point_host, location_kind, "; ".join(diagnostic_parts)
    location = getattr(marker_element, "Location", None)
    if location is None:
        diagnostic_parts.append("Location property is None.")
    else:
        location_kind = location.__class__.__name__
        point = getattr(location, "Point", None)
        if point is not None:
            point_link = point
        else:
            curve = getattr(location, "Curve", None)
            if curve is not None:
                try:
                    point_link = curve.Evaluate(0.5, True)
                    diagnostic_parts.append("Computed midpoint from LocationCurve.")
                except Exception as error:
                    diagnostic_parts.append("Failed to evaluate LocationCurve midpoint: {0}".format(error))
            else:
                diagnostic_parts.append("Location lacks Point/Curve data.")
    if point_link is None:
        if hasattr(marker_element, "GetTransform"):
            try:
                element_transform = marker_element.GetTransform()
                if element_transform is not None:
                    point_link = element_transform.Origin
                    diagnostic_parts.append("Using transform origin as fallback.")
            except Exception as error:
                diagnostic_parts.append("GetTransform failed: {0}".format(error))
        else:
            diagnostic_parts.append("Element missing GetTransform method.")
    if point_link is not None:
        if transform is not None:
            try:
                point_host = transform.OfPoint(point_link)
            except Exception as error:
                diagnostic_parts.append("Transform.OfPoint failed: {0}".format(error))
        else:
            point_host = point_link
    diagnostic_note = "; ".join(diagnostic_parts) if diagnostic_parts else None
    return point_link, point_host, location_kind, diagnostic_note


def _build_marker_groups(ref_marker_groups, marker_keys, transform):
    groups = []
    first_point = None
    if not ref_marker_groups:
        return groups, None
    for prefix, marker_map in ref_marker_groups:
        if marker_map is None:
            marker_map = {}
        marker_data, group_first_point = _build_marker_entries(marker_map, marker_keys, transform)
        group_entry = {
            "prefix": prefix,
            "markers": marker_data,
            "first_point": group_first_point,
        }
        groups.append(group_entry)
        if first_point is None and group_first_point is not None:
            first_point = group_first_point
    return groups, first_point


def _count_markers(marker_data):
    count = 0
    for marker_key in marker_data:
        entry = marker_data[marker_key]
        if entry is not None and entry.get("element") is not None:
            count += 1
    return count


def _count_markers_in_groups(marker_groups):
    total = 0
    if not marker_groups:
        return total
    for group in marker_groups:
        marker_data = group.get("markers", {})
        total += _count_markers(marker_data)
    return total


def _format_marker_prefix(prefix_value):
    if prefix_value is None:
        return "(no prefix)"
    return prefix_value


def print_panel_logs(panel_logs, preview_limit=None):
    total = len(panel_logs)
    if total == 0:
        return
    if preview_limit is None:
        preview_limit = PANEL_LOG_PREVIEW_LIMIT
    limit = min(preview_limit, total)
    for idx in range(limit):
        print(panel_logs[idx])
    if total > limit:
        print("\n... Skipping {0} additional panels (preview limited to {1}).".format(total - limit, limit))


def _is_target_panel(family_name, type_name, target_panel_families=None):
    if target_panel_families is None:
        target_panel_families = TARGET_PANEL_FAMILIES
    for target_family_name, target_type_name in target_panel_families:
        if family_name == target_family_name and (target_type_name is None or type_name == target_type_name):
            return True
    return False
