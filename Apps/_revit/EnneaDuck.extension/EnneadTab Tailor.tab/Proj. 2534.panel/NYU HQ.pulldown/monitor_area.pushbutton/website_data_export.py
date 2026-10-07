#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Website Data Export Module - Area matching and JSON data sync for the NYU HQ webapp
Revit syncs data only; the website repo owns all presentation (no HTML builder).
"""

import os
import json
import time
from datetime import datetime
import config
import nyu_hq_api
from EnneadTab import ENVIRONMENT

try:
    _BUILTINS_DICT = __builtins__ if isinstance(__builtins__, dict) else __builtins__.__dict__
    TEXT_TYPE = _BUILTINS_DICT.get('unicode', str)
except Exception:
    TEXT_TYPE = str


class AreaMatcher:
    """Exact matching between Excel requirements and Revit areas using 3 parameters"""
    
    def _safe_int(self, value):
        """Safely convert value to integer"""
        try:
            return int(float(value)) if value else 0
        except (ValueError, TypeError):
            return 0
    
    def _safe_float(self, value):
        """Safely convert value to float"""
        try:
            return float(value) if value else 0.0
        except (ValueError, TypeError):
            return 0.0

    def match_areas_to_requirements(self, excel_data, revit_data):
        """
        Match Revit areas to Excel requirements
        
        Args:
            excel_data: Dictionary of Excel data with RowData objects
            revit_data: Dictionary with scheme names as keys and list of area objects as values
                {
                    'scheme1': [area_object1, area_object2, ...],
                    'scheme2': [area_object1, area_object2, ...]
                }
            
        Returns:
            dict: Dictionary with scheme names as keys and match data as values
        """
        all_matches = {}
        
        for scheme_name, areas_list in revit_data.items():
            if isinstance(areas_list, list):
                matches = self._match_single_scheme(excel_data, areas_list)
                
                # Calculate scheme info
                total_sf = sum(self._safe_float(area['area_sf']) for area in areas_list)
                scheme_info = {
                    'name': scheme_name,
                    'count': len(areas_list),
                    'total_sf': total_sf
                }
                
                all_matches[scheme_name] = {
                    'matches': matches,
                    'scheme_info': scheme_info
                }
        
        return all_matches
    
    def _match_single_scheme(self, excel_data, areas_list):
        """
        Match areas for a single scheme
        
        Args:
            excel_data: Dictionary of Excel data with RowData objects
            areas_list: List of area objects
            
        Returns:
            list: List of match results
        """
        matches = []
        
        for room_key, requirement in excel_data.items():
            # Get actual Excel row number from RowData object
            excel_row_index = getattr(requirement, '_row_number', 0)
            # Extract requirement data from RowData object using Excel column names
            # Extract room name from composite key if needed
            if config.USE_COMPOSITE_KEY and config.COMPOSITE_KEY_SEPARATOR in room_key:
                parts = room_key.split(config.COMPOSITE_KEY_SEPARATOR)
                if len(parts) == 3:
                    room_name = parts[2]  # dept | division | room_name
                else:
                    room_name = room_key
            else:
                room_name = getattr(requirement, config.PROGRAM_TYPE_DETAIL_KEY[config.APP_EXCEL], room_key)
            department = getattr(requirement, config.DEPARTMENT_KEY[config.APP_EXCEL], '')
            program_type = getattr(requirement, config.PROGRAM_TYPE_KEY[config.APP_EXCEL], '')
            target_count = getattr(requirement, config.COUNT_KEY[config.APP_EXCEL], 0)
            target_dgsf = getattr(requirement, config.SCALED_DGSF_KEY[config.APP_EXCEL], 0)
            color = getattr(requirement, 'COLOR', None)  # Extract color from Excel
            
            # Convert to numeric types to ensure proper calculations
            target_count = self._safe_int(target_count)
            target_dgsf = self._safe_float(target_dgsf)
            
            # Find matching Revit areas using exact 3-parameter match
            matching_areas = self._find_matching_areas(
                room_name,  # program_type_detail
                department, 
                program_type, 
                areas_list
            )
            
            # Calculate actual counts and areas
            actual_count = len(matching_areas)
            actual_dgsf = sum(self._safe_float(area['area_sf']) for area in matching_areas)
            
            # Calculate deltas (handle None values)
            # If target is None or 0, delta should be None (no requirement)
            if target_count is None or target_count == 0:
                count_delta = None  # No count requirement
            else:
                count_delta = actual_count - target_count
                
            if target_dgsf is None or target_dgsf == 0:
                dgsf_delta = None  # No area requirement
                dgsf_percentage = None
            else:
                dgsf_delta = actual_dgsf - target_dgsf
                dgsf_percentage = (dgsf_delta / target_dgsf * 100)
            
            # Determine status
            status = self._determine_status(
                target_count, 
                target_dgsf, 
                actual_count, 
                actual_dgsf
            )
            
            # Get level information from matching areas
            levels = [area.get('level_name', 'Unknown Level') for area in matching_areas]
            level_summary = ', '.join(sorted(set(levels))) if levels else 'No Areas'
            
            match_result = {
                'excel_row_index': excel_row_index,  # Track Excel order
                'room_name': room_name,
                'department': department,
                'division': program_type,
                'color': color,  # Include color from Excel
                'target_count': target_count,
                'target_dgsf': target_dgsf,
                'actual_count': actual_count,
                'actual_dgsf': actual_dgsf,
                'count_delta': count_delta,
                'dgsf_delta': dgsf_delta,
                'dgsf_percentage': dgsf_percentage,
                'status': status,
                'matching_areas': matching_areas,
                'level_summary': level_summary,
                'match_quality': self._calculate_match_quality_simple(matching_areas, status)
            }
            
            matches.append(match_result)
        
        return matches
    
    def _find_matching_areas(self, req_detail, req_dept, req_type, areas_list):
        """
        Find Revit areas that EXACTLY match the requirement using 3 parameters
        
        Args:
            req_detail: Requirement program type detail
            req_dept: Requirement department
            req_type: Requirement program type
            areas_list: List of area objects
            
        Returns:
            list: List of matching area objects (exact match only)
        """
        matching_areas = []
        
        for area_object in areas_list:
            # Get the 3 parameters from area object (using dict keys, not config params)
            area_dept = area_object.get('department', '')
            area_type = area_object.get('program_type', '')
            area_detail = area_object.get('program_type_detail', '')
            
            # EXACT match on all 3 parameters (case-insensitive, whitespace-trimmed)
            if (req_detail.lower().strip() == area_detail.lower().strip() and 
                req_dept.lower().strip() == area_dept.lower().strip() and 
                req_type.lower().strip() == area_type.lower().strip()):
                matching_areas.append(area_object)
        
        return matching_areas
    
    def _determine_status(self, target_count, target_dgsf, actual_count, actual_dgsf):
        """Determine fulfillment status with proper overage handling"""
        # Define tolerance limits
        tolerance_percentage = config.AREA_TOLERANCE_PERCENTAGE / 100.0
        
        # Handle None/0 values (no requirement)
        has_count_requirement = target_count is not None and target_count > 0
        has_area_requirement = target_dgsf is not None and target_dgsf > 0
        
        # If no requirements at all, return "No Requirement"
        if not has_count_requirement and not has_area_requirement:
            return "No Requirement"
        
        # Check if we have any areas at all
        if actual_count == 0 and actual_dgsf == 0:
            return "Missing"
        
        # Calculate acceptable ranges for area (only if there's an area requirement)
        if has_area_requirement:
            min_area = target_dgsf * (1 - tolerance_percentage)
            max_area = target_dgsf * (1 + tolerance_percentage)
            area_overage_percentage = (actual_dgsf - target_dgsf) / target_dgsf
        else:
            area_overage_percentage = 0
        
        # Calculate count overage (only if there's a count requirement)
        if has_count_requirement:
            count_overage_percentage = (actual_count - target_count) / float(target_count)
        else:
            count_overage_percentage = 0
        
        # Check for excessive overage (more than 200% over target)
        if area_overage_percentage > 2.0 or count_overage_percentage > 2.0:
            return "Excessive"
        
        # Check fulfillment based on what requirements exist
        if has_count_requirement and has_area_requirement:
            # Both requirements exist - check both
            count_met = actual_count >= target_count
            area_met = min_area <= actual_dgsf <= max_area
            if count_met and area_met:
                return "Fulfilled"
            elif actual_count > 0 and actual_dgsf > 0:
                return "Partial"
        elif has_count_requirement:
            # Only count requirement exists
            if actual_count >= target_count:
                return "Fulfilled"
            elif actual_count > 0:
                return "Partial"
        elif has_area_requirement:
            # Only area requirement exists
            if min_area <= actual_dgsf <= max_area:
                return "Fulfilled"
            elif actual_dgsf > 0:
                return "Partial"
        
        return "Missing"
    
    def _calculate_match_quality_simple(self, matching_areas, status=None):
        """Calculate overall match quality based on number of matches and status"""
        if not matching_areas:
            return "No Match"
        
        # If status is Excessive, quality should be Low regardless of match count
        if status == "Excessive":
            return "Low"
        
        # For other statuses, base quality on number of matches
        if len(matching_areas) == 1:
            return "High"
        elif len(matching_areas) <= 3:
            return "Medium"
        else:
            return "Low"
    
    def get_unmatched_areas(self, excel_data, areas_list):
        """
        Get Revit areas that don't match any Excel requirements
        
        Args:
            excel_data: Dictionary of Excel data with RowData objects
            areas_list: List of area objects
            
        Returns:
            list: List of unmatched area objects
        """
        # Get all matched area objects
        all_matched_areas = []
        
        for room_key, requirement in excel_data.items():
            room_name = getattr(requirement, config.PROGRAM_TYPE_DETAIL_KEY[config.APP_EXCEL], room_key)
            department = getattr(requirement, config.DEPARTMENT_KEY[config.APP_EXCEL], '')
            program_type = getattr(requirement, config.PROGRAM_TYPE_KEY[config.APP_EXCEL], '')
            
            matching_areas = self._find_matching_areas(
                room_name,  # program_type_detail
                department, 
                program_type, 
                areas_list
            )
            all_matched_areas.extend(matching_areas)
        
        # Find unmatched areas by comparing object references
        matched_ids = set(id(area) for area in all_matched_areas)
        unmatched = [area for area in areas_list if id(area) not in matched_ids]
        
        return unmatched


class HTMLReportGenerator:
    """Generate HTML reports for area comparison"""
    
    def _get_report_creator(self):
        """Return the name of the user generating the report."""
        try:
            creator = getattr(ENVIRONMENT, "current_user_name", None)
            if creator:
                return creator
        except Exception:
            pass
        return "Unknown"

    def _safe_int(self, value):
        """Safely convert value to integer"""
        try:
            return int(float(value)) if value else 0
        except (ValueError, TypeError):
            return 0
    
    def _safe_float(self, value):
        """Safely convert value to float"""
        try:
            return float(value) if value else 0.0
        except (ValueError, TypeError):
            return 0.0
    
    def __init__(self):
        self.reports_dir = os.path.join(os.path.dirname(__file__), config.REPORTS_DIR)
        
        # Create reports directory if it doesn't exist
        if not os.path.exists(self.reports_dir):
            os.makedirs(self.reports_dir)
        
        # Initialize color hierarchy
        self.color_hierarchy = {
            'department': {},
            'division': {},
            'room_name': {}
        }
        
        # Clean up old reports
        self._cleanup_old_reports()
    
    def _cleanup_old_reports(self, max_days=2):
        """
        Delete report files older than max_days from the reports directory.
        Keeps latest_report.html regardless of age.
        
        Args:
            max_days: Maximum age of reports to keep in days (default: 2)
        """
        try:
            if not os.path.exists(self.reports_dir):
                return
            
            current_time = time.time()
            max_age_seconds = max_days * 24 * 60 * 60  # Convert days to seconds
            deleted_count = 0
            
            for filename in os.listdir(self.reports_dir):
                # Skip the latest_report.html - always keep it
                if filename == config.LATEST_REPORT_FILENAME:
                    continue
                
                # Only remove generated report files, e.g., area_report_*.html
                if not (filename.startswith('area_report_') and filename.endswith('.html')):
                    continue

                filepath = os.path.join(self.reports_dir, filename)
                
                # Check if file is older than max_days
                try:
                    file_age = current_time - os.path.getmtime(filepath)
                    if file_age > max_age_seconds:
                        os.remove(filepath)
                        deleted_count += 1
                        print("Deleted old report: {}".format(filename))
                except Exception as e:
                    print("Error deleting {}: {}".format(filename, str(e)))
            
            if deleted_count > 0:
                print("Cleaned up {} old report(s) older than {} days".format(deleted_count, max_days))
        except Exception as e:
            print("Error during report cleanup: {}".format(str(e)))
    
    def get_color(self, level, name, fallback='#6b7280'):
        """
        Get color from hierarchy with fallback logic.
        
        Args:
            level: 'department', 'division', or 'room_name'
            name: Name to look up
            fallback: Default color if not found
            
        Returns:
            str: Hex color code
        """
        return self.color_hierarchy.get(level, {}).get(name, fallback)
    

class WebsiteDataExporter:
    """Publishes NYU HQ area data to the website-owned webapp via its API.

    The website repo (EnneadTab-TailorProject-NYU-HQ) owns all presentation
    (HTML shell, CSS, JS renderers) and holds ZERO data: Postgres is the
    system of record. This class only PUBLISHES data documents through the
    webapp's API -- POST /api/report and POST /api/geometry -- authenticated
    with the NYU_HQ_SERVICE_TOKEN environment variable.
    See docs/DATA_CONTRACT.md in the website repo for the schema.
    """

    def __init__(self):
        self.color_hierarchy = {
            'department': {},
            'division': {},
            'room_name': {}
        }

    def get_color(self, level, name, fallback='#6b7280'):
        """Get color from hierarchy with fallback"""
        return self.color_hierarchy.get(level, {}).get(name, fallback)

    def export_website_data(self, excel_data, revit_data, color_hierarchy=None):
        """Match areas and publish the data documents to the webapp API.

        Args:
            excel_data: Dictionary of target data with RowData objects
                (from target_data.get_target_data -- clean API targets,
                same shape as the legacy Excel data)
            revit_data: Dictionary with scheme names as keys and list of area objects
            color_hierarchy: Dict with color mappings at department/division/room levels

        Returns:
            tuple: (sync_result dict, all_matches, all_unmatched_areas).
                sync_result describes the two POSTs that were made.

        Raises:
            nyu_hq_api.NyuHqApiError: if the API cannot be reached or
                rejects the publish (auth, validation, database).
        """
        self.color_hierarchy = color_hierarchy or {
            'department': {},
            'division': {},
            'room_name': {}
        }

        # Match areas to requirements
        matcher = AreaMatcher()
        all_matches = matcher.match_areas_to_requirements(excel_data, revit_data)

        # Get unmatched areas for each scheme
        all_unmatched_areas = {}
        for scheme_name, areas_list in revit_data.items():
            if isinstance(areas_list, list):
                unmatched = matcher.get_unmatched_areas(excel_data, areas_list)
                all_unmatched_areas[scheme_name] = unmatched

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Build report-data.json (see DATA_CONTRACT.md in the website repo)
        report_data = {
            'meta': {
                'report_title': config.REPORT_TITLE,
                'project_name': config.PROJECT_NAME,
                'generated_at': current_time,
                'report_creator': 'EnneadTab',
                'thresholds': {
                    'count_delta_alert': config.COUNT_DELTA_ALERT_THRESHOLD,
                    'area_percentage_alert': config.AREA_PERCENTAGE_ALERT_THRESHOLD
                }
            },
            'color_hierarchy': self.color_hierarchy,
            'schemes': {}
        }

        for scheme_name, scheme_data in all_matches.items():
            matches = scheme_data.get('matches', [])
            report_data['schemes'][scheme_name] = {
                'scheme_info': scheme_data.get('scheme_info', {}),
                'matches': [self._match_to_json(m) for m in matches],
                'unmatched_areas': [
                    self._area_to_json(a)
                    for a in all_unmatched_areas.get(scheme_name, [])
                ]
            }

        # Build geometry document
        geometry_data = self._generate_geometry_data(revit_data)

        # Publish both documents to the webapp API (Postgres is the system
        # of record; the website repo holds zero data). Auth via
        # NYU_HQ_SERVICE_TOKEN.
        report_resp = nyu_hq_api.post_report(report_data)
        geometry_resp = nyu_hq_api.post_geometry(geometry_data)
        sync_result = {
            'report': report_resp,
            'geometry': geometry_resp,
            'api_origin': config.NYU_HQ_API_URL,
        }
        print("Published report + geometry to {}".format(config.NYU_HQ_API_URL))

        return sync_result, all_matches, all_unmatched_areas

    def _clean(self, value):
        """JSON-safe value: preserve None (null), sanitize strings, pass through numbers."""
        if value is None:
            return None
        if isinstance(value, (int, float, bool)):
            return value
        try:
            if isinstance(value, bytes):
                return value.decode('utf-8', 'replace')
            return TEXT_TYPE(value)
        except Exception:
            return ''

    def _match_to_json(self, match):
        """Pick JSON-serializable fields from a match dict per DATA_CONTRACT.md."""
        return {
            'excel_row_index': match.get('excel_row_index', 0),
            'room_name': self._clean(match.get('room_name')),
            'department': self._clean(match.get('department')),
            'division': self._clean(match.get('division')),
            'color': self._clean(match.get('color')),
            'target_count': match.get('target_count'),
            'target_dgsf': match.get('target_dgsf'),
            'actual_count': match.get('actual_count'),
            'actual_dgsf': match.get('actual_dgsf'),
            'count_delta': match.get('count_delta'),
            'dgsf_delta': match.get('dgsf_delta'),
            'dgsf_percentage': match.get('dgsf_percentage'),
            'status': self._clean(match.get('status')),
            'level_summary': self._clean(match.get('level_summary')),
            'match_quality': self._clean(match.get('match_quality')),
            'matching_areas': [self._area_to_json(a) for a in match.get('matching_areas', [])]
        }

    def _area_to_json(self, area):
        """Pick JSON-serializable fields from a Revit area dict (excludes revit_element)."""
        return {
            'name': self._clean(area.get('program_type_detail') or area.get('name')),
            'department': self._clean(area.get('department')),
            'division': self._clean(area.get('program_type')),
            'area_sf': area.get('area_sf', 0),
            'level_name': self._clean(area.get('level_name'))
        }

    def _sanitize_for_json(self, value):
        """
        Sanitize value for JSON serialization (handle Unicode in Python 2.7)
        
        Args:
            value: Any value to sanitize
        
        Returns:
            Sanitized value safe for JSON
        """
        if value is None:
            return ""
        
        if isinstance(value, (int, float, bool)):
            return value
        
        # Handle strings - ensure they're TEXT_TYPE
        try:
            if isinstance(value, bytes):
                try:
                    return value.decode('utf-8', 'replace')
                except Exception:
                    return value
            if isinstance(value, TEXT_TYPE):
                return value
            return TEXT_TYPE(str(value))
        except Exception:
            try:
                return str(value)
            except Exception:
                return ""
    
    def _generate_geometry_data(self, revit_data):
        """
        Generate geometry data dict for website geometry.json
        
        Args:
            revit_data: Dictionary of area data by scheme {scheme_name: [areas]}
        
        Returns:
            str: JavaScript object literal with geometry data
        """
        import json
        
        # Build geometry data structure organized by scheme -> level -> areas
        geometry_data = {}
        
        
        for scheme_name, areas_list in revit_data.items():
            if not isinstance(areas_list, list):
                continue
            
            
            scheme_data = {}
            areas_with_geometry = 0
            
            for area_obj in areas_list:
                geometry = area_obj.get('geometry')
                if not geometry:
                    # Skip areas without geometry
                    continue
                
                areas_with_geometry += 1
                
                level_name = geometry.get('level_name', 'Unknown')
                
                # Initialize level if not exists
                if level_name not in scheme_data:
                    scheme_data[level_name] = []
                
                # Get metadata from area_obj (not geometry)
                department = area_obj.get('department', '')
                program_type = area_obj.get('program_type', '')
                program_type_detail = area_obj.get('program_type_detail', '')
                area_sf = area_obj.get('area_sf', 0)
                
                
                # Get department color from hierarchy
                dept_color = self.get_color('department', department)
                
                # Build area geometry object for JavaScript
                # Sanitize all values for JSON serialization (Python 2.7 compatible)
                area_geom = {
                    'area_id': int(geometry.get('area_id')) if geometry.get('area_id') else 0,
                    'department': self._sanitize_for_json(department),
                    'program_type': self._sanitize_for_json(program_type),
                    'program_type_detail': self._sanitize_for_json(program_type_detail),
                    'area_sf': float(area_sf),
                    'level_elevation': float(geometry.get('level_elevation', 0)),
                    'boundary_loops': geometry.get('boundary_loops', []),
                    'color': self._sanitize_for_json(dept_color)
                }
                
                scheme_data[level_name].append(area_geom)
            
            
            geometry_data[scheme_name] = scheme_data
        
        # Convert to JSON string
        try:
            # Python 2.7 compatible JSON serialization
            # Use ensure_ascii=True to avoid encoding issues in Python 2.7
            return geometry_data
        except Exception as e:
            print("Error generating geometry JSON: {}".format(str(e)))
            import traceback
            traceback.print_exc()
            return {}
    
