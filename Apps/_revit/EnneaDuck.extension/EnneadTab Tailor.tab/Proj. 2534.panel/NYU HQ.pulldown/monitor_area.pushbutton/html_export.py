#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
HTML Export Module - Handles area matching and HTML report generation
Uses exact matching on 3 parameters: Department, Program Type, Program Type Detail
"""

import os
import webbrowser
import subprocess
import io
import time
from datetime import datetime
import config
import suggestion_logic
import department_matrix
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
    
    def generate_html_report(self, excel_data, revit_data, color_hierarchy=None):
        """
        Generate consolidated HTML report with all schemes in tabs
        
        Args:
            excel_data: Dictionary of Excel data with RowData objects
            revit_data: Dictionary of area data by scheme {scheme_name: [areas]}
            color_hierarchy: Dict with color mappings at department/division/room levels
            
        Returns:
            tuple: (list of filepaths, all_matches, all_unmatched_areas)
        """
        # Store color hierarchy and revit_data for use in HTML generation
        self.color_hierarchy = color_hierarchy or {
            'department': {},
            'division': {},
            'room_name': {}
        }
        self.revit_data = revit_data
        
        # Track department-level matrices per scheme
        self.department_matrix_cache = {}

        # Match areas to requirements
        matcher = AreaMatcher()
        all_matches = matcher.match_areas_to_requirements(excel_data, revit_data)
        
        # Get unmatched areas for each scheme
        all_unmatched_areas = {}
        for scheme_name, areas_list in revit_data.items():
            if isinstance(areas_list, list):
                unmatched = matcher.get_unmatched_areas(excel_data, areas_list)
                all_unmatched_areas[scheme_name] = unmatched
        
        # Generate consolidated HTML with all schemes
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Generate single consolidated HTML
        report_creator = self._get_report_creator()
        html_content = self._create_consolidated_html(
            all_matches_dict=all_matches,
            all_unmatched_dict=all_unmatched_areas,
            current_time=current_time,
            report_creator=report_creator
        )
        
        # Save to timestamped file
        filename = "area_report_consolidated_{}.html".format(timestamp)
        filepath = os.path.join(self.reports_dir, filename)
        
        with io.open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Also save as latest_report.html for easy access
        latest_path = os.path.join(self.reports_dir, config.LATEST_REPORT_FILENAME)
        with io.open(latest_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Return single filepath in list for compatibility
        return [filepath], all_matches, all_unmatched_areas
    
    def _create_scheme_content(self, scheme_name, matches, unmatched_areas, is_first=False):
        """
        Create HTML content for a single scheme (without outer HTML structure)
        
        Args:
            scheme_name: Name of the area scheme
            matches: List of matched areas for this scheme
            unmatched_areas: Dictionary of unmatched areas for this scheme
            is_first: Whether this is the first scheme (will be visible by default)
        
        Returns:
            str: HTML content wrapped in a scheme container div
        """
        # Calculate summary statistics
        total_target_count = sum(match['target_count'] for match in matches if match['target_count'] is not None)
        total_actual_count = sum(match['actual_count'] for match in matches if match['actual_count'] is not None)
        total_target_dgsf = sum(match['target_dgsf'] for match in matches if match['target_dgsf'] is not None)
        total_actual_dgsf = sum(match['actual_dgsf'] for match in matches if match['actual_dgsf'] is not None)
        
        fulfilled_count = sum(1 for match in matches if match['status'] == 'Fulfilled')
        partial_count = sum(1 for match in matches if match['status'] == 'Partial')
        missing_count = sum(1 for match in matches if match['status'] == 'Missing')
        
        # Count alerts for high differences (skip None values)
        high_count_delta_alerts = sum(1 for match in matches if match['count_delta'] is not None and abs(match['count_delta']) >= config.COUNT_DELTA_ALERT_THRESHOLD)
        high_area_delta_alerts = sum(1 for match in matches if match['dgsf_percentage'] is not None and abs(match['dgsf_percentage']) >= config.AREA_PERCENTAGE_ALERT_THRESHOLD)
        extreme_difference_alerts = sum(1 for match in matches if 
            match['count_delta'] is not None and match['dgsf_percentage'] is not None and
            abs(match['count_delta']) >= config.COUNT_DELTA_ALERT_THRESHOLD and 
            abs(match['dgsf_percentage']) >= config.AREA_PERCENTAGE_ALERT_THRESHOLD)
        
        # Create safe scheme name for IDs and classes
        safe_scheme_name = scheme_name.replace(" ", "_").replace("/", "_").replace("-", "_")

        scheme_areas = self.revit_data.get(scheme_name, [])
        matrix_data = department_matrix.build_matrix(matches, scheme_areas, self.color_hierarchy)
        self.department_matrix_cache[scheme_name] = matrix_data
        matrix_html = department_matrix.render_html(matrix_data, safe_scheme_name)
        active_class = " active" if is_first else ""
        
        # Generate scheme-specific content
        content = """
<div class="scheme-content{active_class}" id="scheme-{safe_scheme_name}" data-scheme="{scheme_name}">
    <header class="report-header">
        <div class="area-scheme-badge">
            <span class="badge-label">Area Scheme</span>
            <span class="badge-value">{scheme_name}</span>
        </div>
        <div class="online-dashboard-note">
            <div class="dashboard-link-container">
                <div class="dashboard-link-item">
                    <div class="link-icon">🌐</div>
                    <div class="link-content">
                        <div class="link-title">Online Dashboard</div>
                        <div class="link-description">View this dashboard anywhere</div>
                        <a href="https://enneadtab.com/projects/nyu-hq" target="_blank" class="dashboard-link">
                            <span class="link-text">🚀 Live Dashboard</span>
                            <span class="link-arrow">↗</span>
                        </a>
                    </div>
                </div>
                <div class="dashboard-link-item">
                    <div class="link-icon">🔄</div>
                    <div class="link-content">
                        <div class="link-title">Data Flow Diagram</div>
                        <div class="link-description">See how data flows between Excel, Revit, and the web report</div>
                        <a href="https://enneadtab.com/projects/nyu-hq/diagram" target="_blank" class="dashboard-link">
                            <span class="link-text">📊 Flow Chart</span>
                            <span class="link-arrow">↗</span>
                        </a>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="legend-section">
            <h4>📌 Symbol Legend</h4>
            <div class="legend-grid">
                <div class="legend-item">
                    <span class="legend-icon status-fulfilled">✓</span>
                    <span class="legend-label"><strong>Fulfilled</strong> - All requirements met (count and area within tolerance)</span>
                </div>
                <div class="legend-item">
                    <span class="legend-icon status-partial">△</span>
                    <span class="legend-label"><strong>Partial</strong> - Some areas found but requirements not fully met</span>
                </div>
                <div class="legend-item">
                    <span class="legend-icon status-missing">✕</span>
                    <span class="legend-label"><strong>Missing</strong> - No areas found or zero count/area</span>
                </div>
                <div class="legend-item">
                    <span class="legend-icon status-unknown">?</span>
                    <span class="legend-label"><strong>Unknown</strong> - Status could not be determined</span>
                </div>
                <div class="legend-item">
                    <span class="legend-icon status-excessive">!</span>
                    <span class="legend-label"><strong>Excessive</strong> - Significantly exceeds requirements</span>
                </div>
            </div>
        </div>
    </header>
    
    <div class="department-matrix-section">
        <h2>📊 Department Area Matrix by Level</h2>
        <p class="section-description">This matrix focuses on approved departments only. Division and room-level accuracy is not evaluated here.</p>
        {matrix_html}
    </div>

    <div class="department-summary-section">
        <h2>📊 Department Fulfillment Summary</h2>
        <p class="section-description">This summary reflects total valid department, division, and room matches. Only fully validated elements count toward these totals.</p>
        {department_summary_table}
        {department_by_level_viz}
    </div>
    
    <div class="tree-view-section">
        <h2>🌳 TreeView</h2>
        <p class="section-description">The TreeView shows total valid department, division, and room matches—the same validated elements counted in the fulfillment summary.</p>
        <div class="tree-controls">
            <button onclick="expandAllTreeNodes()">Expand All</button>
            <button onclick="collapseAllTreeNodes()">Collapse All</button>
        </div>
        <div class="tree-container">
            {tree_view_html}
        </div>
    </div>
    
    {unmatched_section}
    
    <div class="summary-section">
        <h2>📊 Summary</h2>
        <div class="summary-cards">
            <div class="card">
                <h3>Total Requirements</h3>
                <div class="card-value" title="Total number of unique room types defined in the Excel program">{total_reqs}</div>
                <div class="card-label">Room Types</div>
            </div>
            <div class="card">
                <h3>Target Count</h3>
                <div class="card-value" title="Total number of areas required according to the Excel program">{target_count}</div>
                <div class="card-label">Areas Required</div>
            </div>
            <div class="card">
                <h3>Actual Count</h3>
                <div class="card-value" title="Total number of areas found in the Revit model">{actual_count}</div>
                <div class="card-label">Areas Found</div>
            </div>
            <div class="card">
                <h3>Target DGSF</h3>
                <div class="card-value" title="Target Department Gross Square Feet from the Excel program">{target_dgsf}</div>
                <div class="card-label">Square Feet</div>
            </div>
            <div class="card">
                <h3>Actual DGSF</h3>
                <div class="card-value" title="Actual Department Gross Square Feet measured in the Revit model">{actual_dgsf}</div>
                <div class="card-label">Square Feet</div>
            </div>
            <div class="card">
                <h3>Compliance</h3>
                <div class="card-value" title="Number of room types that have at least one instance in Revit out of total requirements">{fulfilled_count}/{total_reqs}</div>
                <div class="card-label">Fulfilled</div>
            </div>
            <div class="card">
                <h3>Count Alerts</h3>
                <div class="card-value" title="Room types with significant difference between target and actual count">{high_count_delta_alerts}</div>
                <div class="card-label">High Count Differences</div>
            </div>
            <div class="card">
                <h3>Area Alerts</h3>
                <div class="card-value" title="Room types with significant difference between target and actual DGSF">{high_area_delta_alerts}</div>
                <div class="card-label">High Area Differences</div>
            </div>
            <div class="card">
                <h3>Extreme Alerts</h3>
                <div class="card-value" title="Room types with both high count difference AND high area difference">{extreme_difference_alerts}</div>
                <div class="card-label">Both High Differences</div>
            </div>
        </div>
    </div>
    
    <div class="status-summary">
        <h2>📈 Status Breakdown</h2>
        <div class="status-cards">
            <div class="status-card fulfilled">
                <h3>✓ Fulfilled</h3>
                <div class="status-count">{fulfilled_count}</div>
            </div>
            <div class="status-card partial">
                <h3>△ Partial</h3>
                <div class="status-count">{partial_count}</div>
            </div>
            <div class="status-card missing">
                <h3>✕ Missing</h3>
                <div class="status-count">{missing_count}</div>
            </div>
        </div>
    </div>
    
    <div id="geometry-viewer-section-{safe_scheme_name}" class="geometry-viewer-section">
        <h2>🏗️ 3D Area Geometry Viewer</h2>
        <div class="viewer-controls">
            <div class="control-group">
                <label>View Mode:</label>
                <button id="btn-2d-{safe_scheme_name}" class="view-mode-btn" onclick="switchViewMode('2d', '{safe_scheme_name}')">2D Floor Plan</button>
                <button id="btn-3d-{safe_scheme_name}" class="view-mode-btn active" onclick="switchViewMode('3d', '{safe_scheme_name}')">3D Extrusion</button>
            </div>
            <div class="control-group">
                <label>Level:</label>
                <select id="level-filter-{safe_scheme_name}" onchange="filterByLevel('{safe_scheme_name}', this.value)">
                    <option value="all">All Levels</option>
                </select>
            </div>
            <div class="control-group">
                <label>Department:</label>
                <select id="dept-filter-{safe_scheme_name}" onchange="filterByDepartment('{safe_scheme_name}', this.value)">
                    <option value="all">All Departments</option>
                </select>
            </div>
            <div class="control-group">
                <label>
                    <input type="checkbox" id="target-overlay-{safe_scheme_name}" onchange="toggleTargetOverlay('{safe_scheme_name}', this.checked)">
                    Show Target Overlay
                </label>
            </div>
            <div class="control-group">
                <button onclick="resetCamera('{safe_scheme_name}')">Reset Camera</button>
                <button onclick="zoomToFit('{safe_scheme_name}')">Zoom to Fit</button>
                <button onclick="toggleAnimation('{safe_scheme_name}')">Animate</button>
            </div>
            <div class="control-group" style="font-size: 0.75rem; color: #9ca3af;">
                <span>🖱️ Right-Click: Orbit | Shift+Right: Pan | Scroll: Zoom | Double-Click: Select Area</span>
            </div>
        </div>
        <div class="viewer-container">
            <canvas id="geometry-canvas-{safe_scheme_name}" class="geometry-canvas"></canvas>
            <div id="area-info-popup-{safe_scheme_name}" class="area-info-popup" style="display: none;"></div>
        </div>
    </div>
</div>
""".format(
            active_class=active_class,
            safe_scheme_name=safe_scheme_name,
            scheme_name=scheme_name,
            total_reqs=len(matches),
            target_count="{:,}".format(int(float(total_target_count))),
            actual_count="{:,}".format(int(float(total_actual_count))),
            target_dgsf="{:,.0f}".format(float(self._safe_float(total_target_dgsf))),
            actual_dgsf="{:,.0f}".format(float(self._safe_float(total_actual_dgsf))),
            fulfilled_count=fulfilled_count,
            partial_count=partial_count,
            missing_count=missing_count,
            high_count_delta_alerts=high_count_delta_alerts,
            high_area_delta_alerts=high_area_delta_alerts,
            extreme_difference_alerts=extreme_difference_alerts,
            unmatched_section=self._create_unmatched_section(unmatched_areas, matches, scheme_name),
            department_summary_table=self._create_department_summary_table(matches),
            department_by_level_viz=self._create_department_by_level_visualization(matches, unmatched_areas),
            matrix_html=matrix_html,
            tree_view_html=self._create_tree_view_html(matches)
        )
        
        return content
    
    def _create_consolidated_html(self, all_matches_dict, all_unmatched_dict, current_time, report_creator):
        """Create consolidated HTML for all schemes with tabbed navigation"""
        # Generate content for all schemes
        all_scheme_contents = []
        scheme_nav_items = []
        is_first = True
        
        # Sort schemes alphabetically by name
        sorted_scheme_names = sorted(all_matches_dict.keys())
        
        for scheme_name in sorted_scheme_names:
            scheme_data = all_matches_dict[scheme_name]
            matches = scheme_data.get('matches', [])
            unmatched_areas = all_unmatched_dict.get(scheme_name, {})
            
            # Generate scheme content
            scheme_content = self._create_scheme_content(scheme_name, matches, unmatched_areas, is_first)
            all_scheme_contents.append(scheme_content)
            
            # Generate navigation item
            safe_scheme_name = scheme_name.replace(" ", "_").replace("/", "_").replace("-", "_")
            active_class = " active" if is_first else ""
            nav_item = """
        <div class="minimap-item scheme-selector{active_class}" onclick="switchToScheme('{safe_scheme_name}')" data-scheme="{safe_scheme_name}">
            <span class="minimap-icon">📐</span>
            <span>{scheme_name}</span>
        </div>""".format(
                active_class=active_class,
                safe_scheme_name=safe_scheme_name,
                scheme_name=scheme_name
            )
            scheme_nav_items.append(nav_item)
            
            is_first = False
        
        # Combine all scheme contents
        combined_scheme_content = "\n".join(all_scheme_contents)
        combined_nav_items = "\n".join(scheme_nav_items)
        
        # Build complete HTML with outer structure
        html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report_title}</title>
    <style>
        {css_styles}
    </style>
</head>
<body>
    <!-- EnneadTab Logo - Lower Left with Parallax -->
    <div class="ennead-logo-container" id="enneadLogo">
        <img src="icon_logo_dark_background.png" alt="EnneadTab Logo" class="ennead-logo" onerror="this.onerror=null; this.src='../icon_logo_dark_background.png';">
    </div>
    
    <div class="container">
        <header class="main-header">
            <h1>🏥 {report_title}</h1>
            <div class="report-info">
                <p><strong>Generated by:</strong> {report_creator}</p>
                <p><strong>Generated at:</strong> {current_time}</p>
                <p><strong>Project:</strong> {project_name}</p>
            </div>
        </header>
        
        {combined_scheme_content}
        
        <footer class="report-footer">
            <p>Report generated by {report_creator} | {current_time}</p>
            <p style="margin-top: 10px; font-size: 0.9em; color: #9ca3af;">
                🦆 Powered by <strong style="color: #60a5fa;">EnneadTab</strong> | 
                For feature requests, contact <strong style="color: #60a5fa;">Sen Zhang</strong>
            </p>
        </footer>
    </div>
    
    <!-- Right-Click Context Menu -->
    <div id="contextMenu" class="context-menu">
        <!-- Search Bar -->
        <div class="context-menu-search">
            <input type="text" id="searchInput" placeholder="🔍 Search (Dept/Division/Room)..." autocomplete="off" />
        </div>
        <!-- Suggestions Dropdown (appears above search bar) -->
        <div id="searchSuggestions" class="search-suggestions"></div>
        
        <div class="context-menu-item" onclick="returnToTop()">
            <span class="context-menu-icon">⬆️</span>
            <span>Return to Top</span>
        </div>
        <div class="context-menu-item" onclick="expandAllViews()">
            <span class="context-menu-icon">▼</span>
            <span>Expand All</span>
        </div>
        <div class="context-menu-item" onclick="collapseAllViews()">
            <span class="context-menu-icon">▲</span>
            <span>Collapse All</span>
        </div>
    </div>
    
    <!-- Minimap Navigation Panel -->
    <div class="minimap-toggle" onclick="toggleMinimap()" title="Toggle Navigation Panel">
        🗺️ Nav
    </div>
    <nav class="minimap-nav" id="minimapNav">
        <!-- Scheme Switcher Section -->
        <div class="minimap-title">🔄 Area Schemes</div>
{scheme_nav_items}
        
        <div class="minimap-section-divider"></div>
        <div class="minimap-title">📍 Quick Navigation</div>
        <div class="minimap-item" onclick="scrollToSection('main-header')" data-section="main-header">
            <span class="minimap-icon">🏥</span>
            <span>Report Header</span>
        </div>
        <div class="minimap-item" onclick="scrollToSection('level-matrix-section')" data-section="level-matrix-section">
            <span class="minimap-icon">🏢</span>
            <span>Dept by Level</span>
        </div>
        <div class="minimap-item" onclick="scrollToSection('department-summary-section')" data-section="department-summary-section">
            <span class="minimap-icon">📊</span>
            <span>Department Summary</span>
        </div>
        <div class="minimap-item" onclick="scrollToSection('tree-view-section')" data-section="tree-view-section">
            <span class="minimap-icon">🌳</span>
            <span>TreeView</span>
        </div>
        <div class="minimap-item" onclick="scrollToSection('unmatched-section')" data-section="unmatched-section">
            <span class="minimap-icon">⚠️</span>
            <span>Unmatched Areas</span>
        </div>
        <div class="minimap-item" onclick="scrollToSection('summary-section')" data-section="summary-section">
            <span class="minimap-icon">📊</span>
            <span>Summary</span>
        </div>
        <div class="minimap-item" onclick="scrollToSection('status-summary')" data-section="status-summary">
            <span class="minimap-icon">📈</span>
            <span>Status Breakdown</span>
        </div>
        <div class="minimap-item" onclick="scrollToGeometryViewer()" data-section="geometry-viewer">
            <span class="minimap-icon">🏗️</span>
            <span>3D Viewer</span>
        </div>
    </nav>
    
    <script>
        // Area Geometry Data for 3D Visualization
        const AREA_GEOMETRY_DATA = {geometry_data};
        
        {javascript}
    </script>
</body>
</html>
""".format(
            report_title=config.REPORT_TITLE,
            css_styles=self._get_css_styles(),
            current_time=current_time,
            project_name=config.PROJECT_NAME,
            combined_scheme_content=combined_scheme_content,
            scheme_nav_items=combined_nav_items,
            geometry_data=self._generate_geometry_data_json(self.revit_data),
            javascript=self._get_javascript(),
            report_creator=report_creator
        )
        return html
    
    def _create_table_rows(self, matches):
        """Create table rows for the comparison table, grouped by department, preserving Excel order"""
        rows = []
        
        # Group matches by department while preserving Excel order
        from collections import OrderedDict
        department_groups = OrderedDict()
        for match in matches:
            dept = match['department'] or 'No Department'
            if dept not in department_groups:
                department_groups[dept] = []
            department_groups[dept].append(match)
        
        # Sort department groups by the first occurrence in Excel (using excel_row_index of first item)
        sorted_departments = sorted(department_groups.items(), key=lambda x: x[1][0]['excel_row_index'])
        
        # Generate rows for each department group
        for dept_index, (dept_name, dept_matches) in enumerate(sorted_departments):
            # Add department header row - use department-level color from hierarchy
            dept_color = self.get_color('department', dept_name)
            # Fallback to first room's color if no department color found
            if dept_color == '#6b7280' and dept_matches:
                dept_color = dept_matches[0].get('color', '#6b7280')
            
            # Make department header collapsible with toggle icon
            dept_id = "dept_{}".format(dept_index)
            rows.append("""
                <tr class="department-header" data-dept-id="{dept_id}" onclick="toggleDepartment('{dept_id}')" style="background: linear-gradient(90deg, {color} 0%, rgba(17, 24, 39, 0.8) 100%); cursor: pointer;">
                    <td colspan="13" style="padding: 12px 16px; font-weight: 600; font-size: 1.1em; color: white; border: 4px solid {color};">
                        <span class="collapse-icon" id="icon_{dept_id}" style="display: inline-block; margin-right: 8px; transition: transform 0.3s ease;">▼</span>
                        <span style="display: inline-block; width: 12px; height: 12px; background: {color}; border-radius: 50%; margin-right: 8px;"></span>
                        {dept_name}
                    </td>
                </tr>
            """.format(color=dept_color, dept_name=dept_name, dept_id=dept_id))
            
            # Sort matches within department by Excel order
            dept_matches_sorted = sorted(dept_matches, key=lambda x: x['excel_row_index'])
            
            # Calculate department totals
            dept_target_count = sum(m['target_count'] for m in dept_matches_sorted if m['target_count'] is not None)
            dept_target_dgsf = sum(m['target_dgsf'] for m in dept_matches_sorted if m['target_dgsf'] is not None)
            dept_actual_count = sum(m['actual_count'] for m in dept_matches_sorted)
            dept_actual_dgsf = sum(m['actual_dgsf'] for m in dept_matches_sorted)
            dept_count_delta = dept_actual_count - dept_target_count if dept_target_count > 0 else None
            dept_dgsf_delta = dept_actual_dgsf - dept_target_dgsf if dept_target_dgsf > 0 else None
            
            # Add rows for this department
            for match in dept_matches_sorted:
                status_class = match['status'].lower()
                
                # Check for high differences and apply alert styling (handle None values)
                count_delta_abs = abs(match['count_delta']) if match['count_delta'] is not None else 0
                area_percentage_abs = abs(match['dgsf_percentage']) if match['dgsf_percentage'] is not None else 0
                
                # Determine alert classes (handle None values)
                if match['count_delta'] is None:
                    count_delta_class = "neutral"
                else:
                    count_delta_class = "positive" if match['count_delta'] >= 0 else "negative"
                    
                if match['dgsf_delta'] is None:
                    dgsf_delta_class = "neutral"
                else:
                    dgsf_delta_class = "positive" if match['dgsf_delta'] >= 0 else "negative"
                    
                if match['dgsf_percentage'] is None:
                    percentage_class = "neutral"
                else:
                    percentage_class = "positive" if match['dgsf_percentage'] >= 0 else "negative"
                
                # Apply alert styling for high differences
                if count_delta_abs >= config.COUNT_DELTA_ALERT_THRESHOLD:
                    count_delta_class = "alert-count-delta"
                
                if area_percentage_abs >= config.AREA_PERCENTAGE_ALERT_THRESHOLD:
                    percentage_class = "alert-area-delta"
                
                # Check if entire row should be highlighted for extreme differences
                row_alert_class = ""
                if (count_delta_abs >= config.COUNT_DELTA_ALERT_THRESHOLD and 
                    area_percentage_abs >= config.AREA_PERCENTAGE_ALERT_THRESHOLD):
                    row_alert_class = "alert-high-difference"
                
                # Format count delta with descriptive text
                if match['count_delta'] is None:
                    count_delta_str = "N/A (No Req.)"
                elif match['count_delta'] > 0:
                    count_delta_str = "Exceeding {}".format(abs(match['count_delta']))
                elif match['count_delta'] < 0:
                    count_delta_str = "Missing {}".format(abs(match['count_delta']))
                else:
                    count_delta_str = "Exact Match"
                
                # Format area delta with descriptive text
                dgsf_delta = match['dgsf_delta']
                if dgsf_delta is None:
                    dgsf_delta_str = "N/A (No Req.)"
                elif dgsf_delta > 0:
                    dgsf_delta_str = "Exceeding {:,.0f} SF".format(float(abs(dgsf_delta)))
                elif dgsf_delta < 0:
                    dgsf_delta_str = "Missing {:,.0f} SF".format(float(abs(dgsf_delta)))
                else:
                    dgsf_delta_str = "Exact Match"
                
                # Format percentage
                if match['dgsf_percentage'] is None:
                    percentage_str = "N/A"
                else:
                    percentage_str = "{:+.1f}%".format(float(self._safe_float(match['dgsf_percentage'])))
                
                rows.append("""
                    <tr class="status-{status_class} {row_alert_class} dept-row" data-dept="{dept_id}" data-search-dept="{department}" data-search-division="{division}" data-search-function="{room_name}">
                        <td class="col-dept">{department}</td>
                        <td class="col-division">{division}</td>
                        <td class="col-function"><strong>{room_name}</strong></td>
                        <td class="col-count">{target_count}</td>
                        <td class="col-area">{target_dgsf}</td>
                        <td class="col-level">{level_summary}</td>
                        <td class="col-count">{actual_count}</td>
                        <td class="col-area">{actual_dgsf}</td>
                        <td class="col-delta {count_delta_class}">{count_delta}</td>
                        <td class="col-delta {dgsf_delta_class}">{dgsf_delta}</td>
                        <td class="col-delta {percentage_class}">{percentage}</td>
                        <td class="col-status"><span class="status-badge {status_class}">{status_icon} {status}</span></td>
                        <td class="col-quality"><span class="quality-badge {quality_class}">{match_quality}</span></td>
                    </tr>
                """.format(
                    dept_id=dept_id,
                    status_class=status_class,
                    row_alert_class=row_alert_class,
                    department=match['department'],
                    division=match['division'],
                    room_name=match['room_name'],
                    level_summary=match['level_summary'],
                    target_count="Any" if (match['target_count'] is None or match['target_count'] == 0) else "{:,}".format(int(float(match['target_count']))),
                    target_dgsf="N/A" if (match['target_dgsf'] is None or match['target_dgsf'] == 0) else "{:,.0f}".format(float(self._safe_float(match['target_dgsf']))),
                    actual_count="{:,}".format(int(float(match['actual_count']))),
                    actual_dgsf="{:,.0f}".format(float(self._safe_float(match['actual_dgsf']))),
                    count_delta_class=count_delta_class,
                    count_delta=count_delta_str,
                    dgsf_delta_class=dgsf_delta_class,
                    dgsf_delta=dgsf_delta_str,
                    percentage_class=percentage_class,
                    percentage=percentage_str,
                    status_icon=self._get_status_icon(match['status']),
                    status=match['status'],
                    quality_class=match['match_quality'].lower(),
                    match_quality=match['match_quality']
                ))
        
        return "".join(rows)
    
    def _create_department_summary_table(self, matches):
        """Create department-level fulfillment summary table with visual charts, preserving Excel order"""
        from collections import OrderedDict
        import json
        
        # Group matches by department
        department_groups = OrderedDict()
        for match in matches:
            dept = match['department'] or 'No Department'
            if dept not in department_groups:
                department_groups[dept] = {
                    'matches': []
                }
            department_groups[dept]['matches'].append(match)
        
        # Sort departments by the first occurrence in Excel (using excel_row_index of first item)
        sorted_departments = sorted(department_groups.items(), key=lambda x: x[1]['matches'][0]['excel_row_index'])
        
        # Data for charts
        chart_data = {
            'departments': [],
            'target_dgsf': [],
            'actual_dgsf': [],
            'colors': [],
            'percentages': []
        }
        
        # Generate department summary rows
        rows = []
        for dept_name, dept_data in sorted_departments:
            dept_matches = dept_data['matches']
            # Use department-level color from hierarchy
            dept_color = self.get_color('department', dept_name)
            # Fallback to first match's color if no department color found
            if dept_color == '#6b7280' and dept_matches:
                dept_color = dept_matches[0].get('color', '#6b7280')
            
            # Calculate department totals
            dept_target_count = sum(m['target_count'] for m in dept_matches if m['target_count'] is not None)
            dept_target_dgsf = sum(m['target_dgsf'] for m in dept_matches if m['target_dgsf'] is not None)
            dept_actual_count = sum(m['actual_count'] for m in dept_matches)
            dept_actual_dgsf = sum(m['actual_dgsf'] for m in dept_matches)
            
            # Calculate deltas and percentages
            if dept_target_count > 0:
                dept_count_delta = dept_actual_count - dept_target_count
                dept_count_percentage = (dept_count_delta / float(dept_target_count) * 100) if dept_target_count > 0 else 0
            else:
                dept_count_delta = None
                dept_count_percentage = None
                
            if dept_target_dgsf > 0:
                dept_dgsf_delta = dept_actual_dgsf - dept_target_dgsf
                dept_dgsf_percentage = (dept_dgsf_delta / dept_target_dgsf * 100) if dept_target_dgsf > 0 else 0
            else:
                dept_dgsf_delta = None
                dept_dgsf_percentage = None
            
            # Add to chart data
            chart_data['departments'].append(dept_name)
            chart_data['target_dgsf'].append(float(dept_target_dgsf) if dept_target_dgsf else 0)
            chart_data['actual_dgsf'].append(float(dept_actual_dgsf) if dept_actual_dgsf else 0)
            chart_data['colors'].append(dept_color)
            chart_data['percentages'].append(float(dept_dgsf_percentage) if dept_dgsf_percentage is not None else 0)
            
            # Status styling
            if dept_dgsf_percentage is not None:
                if abs(dept_dgsf_percentage) <= 5:
                    status_class = "fulfilled"
                    status_icon = "✓"
                    status_text = "On Target"
                elif dept_dgsf_percentage > 5:
                    status_class = "excessive"
                    status_icon = "↑"
                    status_text = "Over"
                else:
                    status_class = "partial"
                    status_icon = "△"
                    status_text = "Under"
            else:
                status_class = "no requirement"
                status_icon = "—"
                status_text = "N/A"
            
            # Format values
            count_delta_str = "N/A" if dept_count_delta is None else "{:+d}".format(int(dept_count_delta))
            dgsf_delta_str = "N/A" if dept_dgsf_delta is None else "{:+,.0f} SF".format(float(dept_dgsf_delta))
            dgsf_pct_str = "N/A" if dept_dgsf_percentage is None else "{:+.1f}%".format(float(dept_dgsf_percentage))
            
            rows.append("""
                <tr style="border: 4px solid {color};">
                    <td style="font-weight: 600;">
                        <span style="display: inline-block; width: 10px; height: 10px; background: {color}; border-radius: 50%; margin-right: 8px;"></span>
                        {dept_name}
                    </td>
                    <td class="col-count">{target_count}</td>
                    <td class="col-area">{target_dgsf}</td>
                    <td class="col-count">{actual_count}</td>
                    <td class="col-area">{actual_dgsf}</td>
                    <td class="col-delta">{count_delta}</td>
                    <td class="col-delta">{dgsf_delta}</td>
                    <td class="col-delta">{dgsf_pct}</td>
                    <td class="col-status"><span class="status-badge {status_class}">{status_icon} {status_text}</span></td>
                </tr>
            """.format(
                color=dept_color,
                dept_name=dept_name,
                target_count="Any" if dept_target_count == 0 else "{:,}".format(int(float(dept_target_count))),
                target_dgsf="N/A" if dept_target_dgsf == 0 else "{:,.0f}".format(float(dept_target_dgsf)),
                actual_count="{:,}".format(int(float(dept_actual_count))),
                actual_dgsf="{:,.0f}".format(float(dept_actual_dgsf)),
                count_delta=count_delta_str,
                dgsf_delta=dgsf_delta_str,
                dgsf_pct=dgsf_pct_str,
                status_class=status_class.lower().replace(" ", "_"),
                status_icon=status_icon,
                status_text=status_text
            ))
        
        # Serialize chart data to JSON for JavaScript
        chart_data_json = json.dumps(chart_data)
        
        table_html = """
            <div class="department-summary-container">
                <!-- Charts Section -->
                <div class="charts-section" style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 32px;">
                    <div class="chart-card" style="background: #1e293b; border-radius: 12px; padding: 24px; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                        <h3 style="color: #e2e8f0; margin: 0 0 16px 0; font-size: 16px; font-weight: 600;">📊 Target vs Actual DGSF</h3>
                        <canvas id="deptComparisonChart" style="max-height: 400px;"></canvas>
                    </div>
                    <div class="chart-card" style="background: #1e293b; border-radius: 12px; padding: 24px; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
                        <h3 style="color: #e2e8f0; margin: 0 0 16px 0; font-size: 16px; font-weight: 600;">📈 Fulfillment Percentage</h3>
                        <canvas id="deptPercentageChart" style="max-height: 400px;"></canvas>
                    </div>
                </div>
                
                <!-- Collapsible Data Table Section -->
                <div class="table-toggle-section" style="margin-top: 24px;">
                    <button onclick="toggleDepartmentTable()" 
                            style="background: #374151; color: #e5e7eb; border: none; padding: 12px 24px; 
                                   border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500;
                                   transition: all 0.3s ease; display: flex; align-items: center; gap: 8px;
                                   margin: 0 auto;">
                        <span id="tableToggleIcon">▼</span>
                        <span id="tableToggleText">Show Detailed Table</span>
                    </button>
                </div>
                
                <div id="departmentTableContainer" class="department-summary-table" style="display: none; margin-top: 16px; opacity: 0; transition: opacity 0.3s ease;">
                    <table class="comparison-table">
                        <thead>
                            <tr>
                                <th style="width: 20%;">Department</th>
                                <th style="width: 10%;">Target Count</th>
                                <th style="width: 12%;">Target DGSF</th>
                                <th style="width: 10%;">Actual Count</th>
                                <th style="width: 12%;">Actual DGSF</th>
                                <th style="width: 10%;">Count Δ</th>
                                <th style="width: 12%;">DGSF Δ</th>
                                <th style="width: 8%;">DGSF %</th>
                                <th style="width: 10%;">Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <script id="departmentChartData" type="application/json">
            {chart_data_json}
            </script>
            
            <script>
                function toggleDepartmentTable() {{
                    const container = document.getElementById('departmentTableContainer');
                    const icon = document.getElementById('tableToggleIcon');
                    const text = document.getElementById('tableToggleText');
                    
                    if (container.style.display === 'none') {{
                        container.style.display = 'block';
                        setTimeout(() => {{ container.style.opacity = '1'; }}, 10);
                        icon.textContent = '▲';
                        text.textContent = 'Hide Detailed Table';
                    }} else {{
                        container.style.opacity = '0';
                        setTimeout(() => {{ container.style.display = 'none'; }}, 300);
                        icon.textContent = '▼';
                        text.textContent = 'Show Detailed Table';
                    }}
                }}
            </script>
        """.format(rows="".join(rows), chart_data_json=chart_data_json)
        
        return table_html
    
    def _create_tree_structure(self, matches):
        """Create hierarchical tree structure: Department → Division → Room Name with aggregated metrics"""
        from collections import OrderedDict
        
        tree = OrderedDict()
        
        # Sort matches by Excel row index to preserve Excel ordering
        matches = sorted(matches, key=lambda x: x['excel_row_index'])
        
        # Build the hierarchy
        for match in matches:
            dept = match['department'] or 'No Department'
            division = match['division'] or 'No Division'
            room_name = match['room_name'] or 'Unknown Room'
            
            # Initialize department level
            if dept not in tree:
                tree[dept] = {
                    'color': self.get_color('department', dept),
                    'excel_row_index': match['excel_row_index'],
                    'divisions': OrderedDict(),
                    'metrics': {
                        'target_count': 0,
                        'target_dgsf': 0,
                        'actual_count': 0,
                        'actual_dgsf': 0
                    }
                }
            
            # Initialize division level
            if division not in tree[dept]['divisions']:
                tree[dept]['divisions'][division] = {
                    'color': self.get_color('division', division),
                    'excel_row_index': match['excel_row_index'],
                    'rooms': OrderedDict(),
                    'metrics': {
                        'target_count': 0,
                        'target_dgsf': 0,
                        'actual_count': 0,
                        'actual_dgsf': 0
                    }
                }
            
            # Initialize room level
            if room_name not in tree[dept]['divisions'][division]['rooms']:
                tree[dept]['divisions'][division]['rooms'][room_name] = {
                    'color': self.get_color('room_name', room_name),
                    'excel_row_index': match['excel_row_index'],
                    'matches': [],
                    'metrics': {
                        'target_count': 0,
                        'target_dgsf': 0,
                        'actual_count': 0,
                        'actual_dgsf': 0
                    }
                }
            
            # Add match to room
            tree[dept]['divisions'][division]['rooms'][room_name]['matches'].append(match)
            
            # Aggregate metrics at room level
            room_metrics = tree[dept]['divisions'][division]['rooms'][room_name]['metrics']
            room_metrics['target_count'] += match['target_count'] if match['target_count'] is not None else 0
            room_metrics['target_dgsf'] += match['target_dgsf'] if match['target_dgsf'] is not None else 0
            room_metrics['actual_count'] += match['actual_count']
            room_metrics['actual_dgsf'] += match['actual_dgsf']
            
            # Aggregate metrics at division level
            div_metrics = tree[dept]['divisions'][division]['metrics']
            div_metrics['target_count'] += match['target_count'] if match['target_count'] is not None else 0
            div_metrics['target_dgsf'] += match['target_dgsf'] if match['target_dgsf'] is not None else 0
            div_metrics['actual_count'] += match['actual_count']
            div_metrics['actual_dgsf'] += match['actual_dgsf']
            
            # Aggregate metrics at department level
            dept_metrics = tree[dept]['metrics']
            dept_metrics['target_count'] += match['target_count'] if match['target_count'] is not None else 0
            dept_metrics['target_dgsf'] += match['target_dgsf'] if match['target_dgsf'] is not None else 0
            dept_metrics['actual_count'] += match['actual_count']
            dept_metrics['actual_dgsf'] += match['actual_dgsf']
        
        # Sort tree by Excel order
        sorted_tree = OrderedDict(sorted(tree.items(), key=lambda x: x[1]['excel_row_index']))
        for dept in sorted_tree.values():
            dept['divisions'] = OrderedDict(sorted(dept['divisions'].items(), key=lambda x: x[1]['excel_row_index']))
            for division in dept['divisions'].values():
                division['rooms'] = OrderedDict(sorted(division['rooms'].items(), key=lambda x: x[1]['excel_row_index']))
        
        return sorted_tree
    
    def _create_tree_view_html(self, matches):
        """Generate tree view HTML with hierarchical structure and interactive expand/collapse"""
        tree_data = self._create_tree_structure(matches)
        
        html_parts = []
        dept_counter = 0
        
        for dept_name, dept_info in tree_data.items():
            dept_id = "tree_dept_{}".format(dept_counter)
            dept_color = dept_info['color']
            dept_metrics = dept_info['metrics']
            
            # Calculate department-level deltas and percentages
            dept_count_delta = dept_metrics['actual_count'] - dept_metrics['target_count']
            dept_dgsf_delta = dept_metrics['actual_dgsf'] - dept_metrics['target_dgsf']
            dept_dgsf_percentage = (dept_dgsf_delta / dept_metrics['target_dgsf'] * 100) if dept_metrics['target_dgsf'] > 0 else 0
            
            # Department node
            html_parts.append("""
            <div class="tree-node tree-node-dept" data-node-id="{dept_id}" data-search-dept="{dept_name}" data-search-division="" data-search-function="">
                <div class="tree-node-header" onclick="toggleTreeNode('{dept_id}')" style="border: 4px solid {dept_color};">
                    <span class="tree-toggle-icon" id="tree_icon_{dept_id}">▼</span>
                    <span class="tree-color-dot" style="background: {dept_color};"></span>
                    <span class="tree-node-label">{dept_name}</span>
                    <div class="tree-node-metrics">
                        <span class="tree-metric" title="Actual Count / Target Count - Number of areas found vs required"><strong>{actual_count}</strong>/{target_count} Count</span>
                        <span class="tree-metric-delta {delta_class}" title="Count difference: Actual minus Target">{count_delta_str}</span>
                        <span class="tree-metric" title="Actual DGSF / Target DGSF - Department Gross Square Feet found vs required"><strong>{actual_dgsf}</strong>/{target_dgsf} DGSF</span>
                        <span class="tree-metric-delta {delta_class}" title="DGSF difference: Actual minus Target">{dgsf_delta_str}</span>
                        <span class="tree-metric-percentage {percentage_class}" title="Percentage of target DGSF achieved">{dgsf_percentage}%</span>
                    </div>
                </div>
                <div class="tree-node-children" id="tree_children_{dept_id}">
            """.format(
                dept_id=dept_id,
                dept_color=dept_color,
                dept_name=dept_name,
                target_count=int(dept_metrics['target_count']),
                actual_count=int(dept_metrics['actual_count']),
                target_dgsf="{:,.0f}".format(float(dept_metrics['target_dgsf'])),
                actual_dgsf="{:,.0f}".format(float(dept_metrics['actual_dgsf'])),
                count_delta_str="{:+d}".format(int(dept_count_delta)),
                dgsf_delta_str="{:+,.0f} SF".format(float(dept_dgsf_delta)),
                dgsf_percentage="{:+.1f}".format(float(dept_dgsf_percentage)),
                delta_class="positive" if dept_count_delta >= 0 else "negative",
                percentage_class="positive" if dept_dgsf_percentage >= 0 else "negative"
            ))
            
            # Division nodes
            div_counter = 0
            for division_name, division_info in dept_info['divisions'].items():
                div_id = "{}_div_{}".format(dept_id, div_counter)
                div_color = division_info['color']
                div_metrics = division_info['metrics']
                
                # Calculate division-level deltas
                div_count_delta = div_metrics['actual_count'] - div_metrics['target_count']
                div_dgsf_delta = div_metrics['actual_dgsf'] - div_metrics['target_dgsf']
                div_dgsf_percentage = (div_dgsf_delta / div_metrics['target_dgsf'] * 100) if div_metrics['target_dgsf'] > 0 else 0
                
                html_parts.append("""
                <div class="tree-node tree-node-division" data-node-id="{div_id}" data-search-dept="{dept_name}" data-search-division="{division_name}" data-search-function="">
                    <div class="tree-node-header" onclick="toggleTreeNode('{div_id}')" style="border: 3px solid {div_color};">
                        <span class="tree-toggle-icon" id="tree_icon_{div_id}">▼</span>
                        <span class="tree-color-dot" style="background: {div_color};"></span>
                        <span class="tree-node-label">{division_name}</span>
                        <div class="tree-node-metrics">
                            <span class="tree-metric" title="Actual Count / Target Count - Number of areas found vs required"><strong>{actual_count}</strong>/{target_count} Count</span>
                            <span class="tree-metric-delta {delta_class}" title="Count difference: Actual minus Target">{count_delta_str}</span>
                            <span class="tree-metric" title="Actual DGSF / Target DGSF - Department Gross Square Feet found vs required"><strong>{actual_dgsf}</strong>/{target_dgsf} DGSF</span>
                            <span class="tree-metric-delta {delta_class}" title="DGSF difference: Actual minus Target">{dgsf_delta_str}</span>
                            <span class="tree-metric-percentage {percentage_class}" title="Percentage of target DGSF achieved">{dgsf_percentage}%</span>
                        </div>
                    </div>
                    <div class="tree-node-children" id="tree_children_{div_id}">
                """.format(
                    div_id=div_id,
                    dept_name=dept_name,
                    div_color=div_color,
                    division_name=division_name,
                    target_count=int(div_metrics['target_count']),
                    actual_count=int(div_metrics['actual_count']),
                    target_dgsf="{:,.0f}".format(float(div_metrics['target_dgsf'])),
                    actual_dgsf="{:,.0f}".format(float(div_metrics['actual_dgsf'])),
                    count_delta_str="{:+d}".format(int(div_count_delta)),
                    dgsf_delta_str="{:+,.0f} SF".format(float(div_dgsf_delta)),
                    dgsf_percentage="{:+.1f}".format(float(div_dgsf_percentage)),
                    delta_class="positive" if div_count_delta >= 0 else "negative",
                    percentage_class="positive" if div_dgsf_percentage >= 0 else "negative"
                ))
                
                # Room nodes
                for room_name, room_info in division_info['rooms'].items():
                    room_color = room_info['color']
                    room_metrics = room_info['metrics']
                    
                    # Calculate room-level deltas
                    room_count_delta = room_metrics['actual_count'] - room_metrics['target_count']
                    room_dgsf_delta = room_metrics['actual_dgsf'] - room_metrics['target_dgsf']
                    room_dgsf_percentage = (room_dgsf_delta / room_metrics['target_dgsf'] * 100) if room_metrics['target_dgsf'] > 0 else 0
                    
                    # Determine status from first match
                    room_status = room_info['matches'][0]['status'] if room_info['matches'] else 'Unknown'
                    status_icon = self._get_status_icon(room_status)
                    
                    # Create tooltip for status icon
                    status_tooltips = {
                        'Perfect Match': 'Perfect Match: Count and DGSF are both within acceptable range',
                        'Count Close': 'Count Close: Room count is close to target but DGSF needs attention',
                        'Area Close': 'Area Close: DGSF is close to target but count needs attention',
                        'High Count Diff': 'High Count Difference: Significant difference in number of areas',
                        'High Area Diff': 'High Area Difference: Significant difference in DGSF',
                        'Extreme Difference': 'Extreme Difference: Both count and DGSF have significant differences',
                        'Unknown': 'Unknown status'
                    }
                    status_tooltip = status_tooltips.get(room_status, 'Status: ' + str(room_status))
                    
                    # Pre-format all values to avoid IronPython format issues
                    room_target_count_int = int(room_metrics['target_count'])
                    room_actual_count_int = int(room_metrics['actual_count'])
                    room_target_dgsf_str = "{:,.0f}".format(float(room_metrics['target_dgsf']))
                    room_actual_dgsf_str = "{:,.0f}".format(float(room_metrics['actual_dgsf']))
                    room_count_delta_int = int(room_count_delta)
                    if room_count_delta_int >= 0:
                        room_count_delta_str = "+{0}".format(room_count_delta_int)
                    else:
                        room_count_delta_str = "{0}".format(room_count_delta_int)
                    room_dgsf_delta_str = "{:,.0f} SF".format(float(room_dgsf_delta))
                    if room_dgsf_delta >= 0:
                        room_dgsf_delta_str = "+" + room_dgsf_delta_str
                    room_dgsf_percentage_str = "{:.1f}".format(float(room_dgsf_percentage))
                    if room_dgsf_percentage >= 0:
                        room_dgsf_percentage_str = "+" + room_dgsf_percentage_str
                    room_delta_class = "positive" if room_count_delta >= 0 else "negative"
                    room_percentage_class = "positive" if room_dgsf_percentage >= 0 else "negative"
                    
                    html_parts.append("""
                    <div class="tree-node tree-node-room" data-search-dept="{dept_name}" data-search-division="{division_name}" data-search-function="{room_name}">
                        <div class="tree-node-header" style="border: 2px solid {room_color};">
                            <span class="tree-color-dot" style="background: {room_color};"></span>
                            <span class="tree-node-label">{room_name}</span>
                            <span class="tree-status-icon" title="{status_tooltip}">{status_icon}</span>
                            <div class="tree-node-metrics">
                                <span class="tree-metric" title="Actual Count / Target Count - Number of areas found vs required"><strong>{actual_count}</strong>/{target_count} Count</span>
                                <span class="tree-metric-delta {delta_class}" title="Count difference: Actual minus Target">{count_delta_str}</span>
                                <span class="tree-metric" title="Actual DGSF / Target DGSF - Department Gross Square Feet found vs required"><strong>{actual_dgsf}</strong>/{target_dgsf} DGSF</span>
                                <span class="tree-metric-delta {delta_class}" title="DGSF difference: Actual minus Target">{dgsf_delta_str}</span>
                                <span class="tree-metric-percentage {percentage_class}" title="Percentage of target DGSF achieved">{dgsf_percentage}%</span>
                            </div>
                        </div>
                    </div>
                    """.format(
                        dept_name=dept_name,
                        division_name=division_name,
                        room_color=room_color,
                        room_name=room_name,
                        status_icon=status_icon,
                        status_tooltip=status_tooltip,
                        target_count=room_target_count_int,
                        actual_count=room_actual_count_int,
                        target_dgsf=room_target_dgsf_str,
                        actual_dgsf=room_actual_dgsf_str,
                        count_delta_str=room_count_delta_str,
                        dgsf_delta_str=room_dgsf_delta_str,
                        dgsf_percentage=room_dgsf_percentage_str,
                        delta_class=room_delta_class,
                        percentage_class=room_percentage_class
                    ))
                
                # Close division node
                html_parts.append("""
                    </div>
                </div>
                """)
                div_counter += 1
            
            # Close department node
            html_parts.append("""
                </div>
            </div>
            """)
            dept_counter += 1
        
        return "".join(html_parts)
    
    def _create_department_by_level_visualization(self, matches, unmatched_areas):
        """Create visualization showing departments per Revit level with DGSF, highlighting unapproved ones"""
        from collections import OrderedDict
        
        # Dictionary to store departments by level with DGSF and elevation
        # Structure: {level_name: {'elevation': float, 'departments': {dept_name: {'dgsf': float, 'approved': bool}}}}
        levels_data = OrderedDict()
        
        # First, collect all approved department names globally
        all_approved_departments = set()
        for match in matches:
            dept_name = match.get('department', 'Unknown')
            all_approved_departments.add(dept_name)
        
        # Debug: Print approved departments
        print("DEBUG - Approved departments from Excel matches:")
        for dept in sorted(all_approved_departments):
            print("  - '{}'".format(dept))
        
        # Process matched (approved) departments with DGSF and collect elevations
        for match in matches:
            dept_name = match.get('department', 'Unknown')
            matching_areas = match.get('matching_areas', [])
            
            # Group areas by level and collect DGSF
            for area in matching_areas:
                level_name = area.get('level_name', 'Unknown Level')
                area_dgsf = area.get('area_sf', 0)
                level_elevation = area.get('level_elevation', 0)
                
                if level_name not in levels_data:
                    levels_data[level_name] = {'elevation': level_elevation, 'departments': {}}
                
                if dept_name not in levels_data[level_name]['departments']:
                    levels_data[level_name]['departments'][dept_name] = {'dgsf': 0, 'approved': True}
                
                levels_data[level_name]['departments'][dept_name]['dgsf'] += area_dgsf
        
        # Process unmatched (unapproved) departments with DGSF and elevation
        # Also collect unique unapproved departments for debug output
        unapproved_depts_found = set()
        
        for area in unmatched_areas:
            level_name = area.get('level_name', 'Unknown Level')
            dept_name = area.get('department', 'Unknown')
            area_dgsf = area.get('area_sf', 0)
            level_elevation = area.get('level_elevation', 0)
            
            if level_name not in levels_data:
                levels_data[level_name] = {'elevation': level_elevation, 'departments': {}}
            
            if dept_name not in levels_data[level_name]['departments']:
                # Check if this department is approved globally
                is_approved = dept_name in all_approved_departments
                levels_data[level_name]['departments'][dept_name] = {'dgsf': 0, 'approved': is_approved}
                
                # Track unapproved departments for debug
                if not is_approved:
                    unapproved_depts_found.add(dept_name)
            
            levels_data[level_name]['departments'][dept_name]['dgsf'] += area_dgsf
        
        # Debug: Print unapproved departments found in Revit
        if unapproved_depts_found:
            print("\nDEBUG - Unapproved departments found in Revit (not matching Excel):")
            for dept in sorted(unapproved_depts_found):
                print("  - '{}'".format(dept))
            print("\nPlease check spelling in Revit parameters to match Excel exactly.")
        
        if not levels_data:
            return ""
        
        # Sort levels by elevation (highest first, descending order)
        sorted_levels = sorted(levels_data.items(), key=lambda x: x[1]['elevation'], reverse=True)
        
        # Create HTML
        level_rows = []
        for level_name, level_data in sorted_levels:
            # Extract departments dictionary and elevation
            departments = level_data['departments']
            level_elevation = level_data['elevation']
            
            # Sort departments by name
            sorted_depts = sorted(departments.items())
            
            # Calculate level total DGSF
            level_total_dgsf = sum([dept_info['dgsf'] for dept_info in departments.values()])
            
            # Create department badges with DGSF
            dept_badges = []
            unapproved_count = 0
            
            for dept_name, dept_info in sorted_depts:
                dgsf_value = dept_info['dgsf']
                is_approved = dept_info['approved']
                
                # Explicitly cast to float for IronPython 2.7 compatibility
                dgsf_str = "{0:,.0f}".format(float(dgsf_value))
                
                # Get department color from color hierarchy
                dept_color = self.get_color('department', dept_name, '#374151')
                
                if is_approved:
                    # Use department color for approved badges
                    dept_badges.append('<span class="dept-badge dept-approved" style="border: 2px solid {0}; background: linear-gradient(135deg, rgba({1}, {2}, {3}, 0.2) 0%, rgba({1}, {2}, {3}, 0.35) 100%); color: #f8fafc;" title="Approved department: {4} DGSF">{5}<br><small style="color: #e5e7eb;">{6} SF</small></span>'.format(
                        dept_color,
                        int(dept_color[1:3], 16),  # R
                        int(dept_color[3:5], 16),  # G
                        int(dept_color[5:7], 16),  # B
                        dgsf_str, dept_name, dgsf_str))
                else:
                    unapproved_count += 1
                    # Keep red for unapproved with warning icon
                    dept_badges.append('<span class="dept-badge dept-unapproved" title="Unapproved department: {0} DGSF - Not in Excel program">⚠️ {1}<br><small>{2} SF</small></span>'.format(
                        dgsf_str, dept_name, dgsf_str))
            
            # Explicitly cast to float for IronPython 2.7 compatibility
            total_dgsf_str = "{0:,.0f}".format(float(level_total_dgsf))
            level_elevation_str = "{0:.2f}".format(float(level_elevation))
            
            level_rows.append("""
            <tr>
                <td class="level-name-col"><strong>{level_name}</strong><br><small class="level-elevation">Elev: {elevation} ft</small></td>
                <td class="dept-count-col">{total_count} departments<br><small class="level-total-dgsf">{total_dgsf} SF Total</small></td>
                <td class="unapproved-count-col {unapproved_class}">{unapproved_text}</td>
                <td class="dept-badges-col">{dept_badges}</td>
            </tr>
            """.format(
                level_name=level_name,
                elevation=level_elevation_str,
                total_count=len(departments),
                total_dgsf=total_dgsf_str,
                unapproved_class="has-unapproved" if unapproved_count > 0 else "no-unapproved",
                unapproved_text="{} UNAPPROVED".format(unapproved_count) if unapproved_count > 0 else "All Approved",
                dept_badges=" ".join(dept_badges)
            ))
        
        return """
        <div class="department-by-level-subsection">
            <h3>🏢 Departments by Revit Level</h3>
            <p class="section-description">Overview of all departments found on each level with DGSF (Department Gross Square Feet). <span class="unapproved-warning">⚠️ Unapproved departments</span> are not in the Excel program requirements and need review. Each badge shows the department name and its total DGSF on that level.</p>
            <div class="table-container">
                <table class="level-dept-table">
                    <thead>
                        <tr>
                            <th style="width: 15%;">Level</th>
                            <th style="width: 15%;">Departments & Total DGSF</th>
                            <th style="width: 15%;">Status</th>
                            <th style="width: 55%;">Department Details (with DGSF)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {level_rows}
                    </tbody>
                </table>
            </div>
        </div>
        """.format(level_rows="".join(level_rows))
    
    def _create_unmatched_section(self, unmatched_areas, valid_matches=None, scheme_name=None):
        """
        Create section for unmatched areas with suggestions
        
        Args:
            unmatched_areas: List of unmatched area objects
            valid_matches: List of valid match dictionaries (for suggestions)
            scheme_name: Name of the scheme (optional)
            
        Returns:
            str: HTML for unmatched section
        """
        if not unmatched_areas:
            return ""
        
        # Build list of valid items for fuzzy matching suggestions
        valid_items = suggestion_logic.build_valid_items(valid_matches)
        
        # Group unmatched areas by level
        areas_by_level = {}
        for area_object in unmatched_areas:
            level_name = area_object.get('level_name', 'Unknown Level')
            if level_name not in areas_by_level:
                areas_by_level[level_name] = []
            areas_by_level[level_name].append(area_object)
        
        # Create HTML for each level
        level_sections = []
        for level_name, level_areas in sorted(areas_by_level.items()):
            level_rows = []
            level_total_sf = 0
            
            for area_object in level_areas:
                area_sf = area_object.get('area_sf', 0)
                area_dept = area_object.get('department', '')
                area_type = area_object.get('program_type', '')
                area_detail = area_object.get('program_type_detail', '')
                creator = area_object.get('creator', 'Unknown')
                last_editor = area_object.get('last_editor', 'Unknown')
                level_total_sf += area_sf
                
                # Find best suggestion for this unmatched area
                plain_suggestion = suggestion_logic.get_suggestion_text(
                    area_dept,
                    area_type,
                    area_detail,
                    valid_items
                )
                if plain_suggestion:
                    area_object['suggestion_text'] = plain_suggestion
                    suggestion_text = '<span class="suggestion-text">Do you mean <strong>{}</strong>?</span>'.format(plain_suggestion)
                else:
                    area_object['suggestion_text'] = ''  # No suggestion
                    suggestion_text = '<span style="color: #6b7280;">{}</span>'.format(
                        suggestion_logic.get_no_suggestion_text()
                    )
                
                # Get area status (Not Placed, Not Enclosed, or Valid)
                area_status = area_object.get('area_status', 'Valid')
                is_zero = float(self._safe_float(area_sf)) == 0
                
                # Create badge for special statuses
                zero_area_badge = ''
                if area_status == 'Not Placed':
                    zero_area_badge = '<span class=\"zero-area-badge\" title=\"Area has not been placed in the model\">Not Placed</span>'
                elif area_status == 'Not Enclosed':
                    zero_area_badge = '<span class=\"zero-area-badge\" title=\"Area boundary is not properly enclosed\">Not Enclosed</span>'
                
                display_area_sf = "{:,.0f}".format(float(self._safe_float(area_sf))) if not is_zero else "0"
                level_rows.append("""
                    <tr class=\"{zero_row_class}\">\n                        <td class=\"col-dept\">{area_dept}</td>\n                        <td class=\"col-division\">{area_type}</td>\n                        <td class=\"col-function\">{area_detail}</td>\n                        <td class=\"col-area\">{area_sf} SF {zero_area_badge}</td>\n                        <td class=\"col-level\">{creator}</td>\n                        <td class=\"col-level\">{last_editor}</td>\n                        <td class=\"col-status\"><span class=\"status-badge unmatched\">○ Unmatched</span></td>\n                        <td class=\"col-suggestion\">{suggestion}</td>\n                </tr>
             """.format(
                    area_dept=area_dept,
                    area_type=area_type,
                        area_detail=area_detail,
                        area_sf=display_area_sf,
                        zero_area_badge=zero_area_badge,
                        zero_row_class=('zero-area-row' if is_zero else ''),
                        creator=creator,
                        last_editor=last_editor,
                        suggestion=suggestion_text
                    ))
            
            level_sections.append("""
            <div class="level-section">
                <h4>📍 {level_name} ({area_count} areas, {total_sf:,} SF)</h4>
            <div class="table-container">
                <table class="unmatched-table">
                    <thead>
                        <tr>
                                <th class="col-dept">Department</th>
                                <th class="col-division">Division</th>
                                <th class="col-function">Function</th>
                                <th class="col-area">Area (SF)</th>
                                <th class="col-level">Created By</th>
                                <th class="col-level">Last Edited By</th>
                                <th class="col-status">Status</th>
                                <th class="col-suggestion">Suggested Match</th>
                        </tr>
                    </thead>
                    <tbody>
                            {level_rows}
                    </tbody>
                </table>
            </div>
            </div>
            """.format(
                level_name=level_name.replace('/', ' / '),  # Add spaces around slashes
                area_count=len(level_areas),
                total_sf=int(round(level_total_sf)),  # Round to whole number for readability
                level_rows="".join(level_rows)
            ))
        
        section_title = "○ Unmatched Areas"
        if scheme_name:
            section_title = "{} - {}".format(section_title, scheme_name)
        
        return """
        <div class="unmatched-section">
            <h3>{section_title}</h3>
            <div class="unmatched-alert">
                <div class="alert-icon">⚠️</div>
                <div class="alert-content">
                    <strong>Action Required:</strong> These areas are not approved in the Excel program requirements. Please review and update the area parameters in Revit to match approved program entries, or add them to the Excel requirements if they are valid new spaces.
                </div>
            </div>
            <p>The following Revit areas were not matched to any Excel requirements, grouped by level. <span class="zero-area-hint">Note: entries showing <strong>0 SF</strong> are often <em>not placed</em> in the model yet or the boundary is <em>not enclosed</em> (room/area not bounding) in Revit.</span></p>
            {level_sections}
        </div>
        """.format(
            section_title=section_title,
            level_sections="".join(level_sections)
        )
    
    def _get_status_icon(self, status):
        """Get icon for status"""
        icons = {
            "Fulfilled": "✓",
            "Partial": "△",
            "Missing": "✕",
            "Excessive": "!"
        }
        return icons.get(status, "?")
    
    def _get_css_styles(self):
        """Get CSS styles for the report - High-Tech Minimalist Theme"""
        return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&family=Source+Code+Pro:wght@400;500;600&display=swap');
        
        html {
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            overflow-x: hidden;
            overflow-y: scroll;
            scroll-behavior: smooth;
        }
        
        body {
            margin: 0;
            padding: 0;
            width: 100%;
            min-height: 100%;
            font-family: 'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            line-height: 1.5;
            color: #f8fafc;
            background: #0a0e13;
            font-weight: 400;
            position: relative;
        }
        
        .container {
            max-width: 95vw;
            width: 100%;
            margin: 0 auto;
            padding: 24px;
            padding-bottom: 150px;
            padding-right: 260px; /* Add space for minimap navigation */
            animation: fadeInUp 0.8s ease-out;
        }
        
        @media (min-width: 1200px) {
            .container {
                min-width: 1200px;
            }
        }
        
        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translateY(30px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .report-header {
            text-align: center;
            margin-bottom: 48px;
            padding: 40px 32px;
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 8px;
            animation: slideInDown 1s ease-out;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        
        .report-header:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
        }
        
        @keyframes slideInDown {
            from {
                opacity: 0;
                transform: translateY(-50px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .report-header h1 {
            color: #ffffff;
            font-size: 2.25rem;
            margin-bottom: 16px;
            font-weight: 600;
            letter-spacing: -0.025em;
        }
        
        .report-info {
            color: #9ca3af;
            font-size: 0.875rem;
            font-weight: 400;
        }
        
        .report-info strong {
            color: #d1d5db;
            font-weight: 500;
        }
        
        /* Area Scheme Badge - Prominent Display */
        .area-scheme-badge {
            display: inline-flex;
            align-items: center;
            gap: 12px;
            margin: 20px 0;
            padding: 12px 24px;
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.15), rgba(147, 51, 234, 0.15));
            border: 2px solid rgba(59, 130, 246, 0.3);
            border-radius: 12px;
            backdrop-filter: blur(10px);
        }
        
        .area-scheme-badge .badge-label {
            color: #93c5fd;
            font-size: 0.875rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        .area-scheme-badge .badge-value {
            color: #ffffff;
            font-size: 1.25rem;
            font-weight: 700;
            letter-spacing: -0.025em;
        }
        
        .online-dashboard-note {
            margin-top: 20px;
            padding: 20px 24px;
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.15) 0%, rgba(59, 130, 246, 0.1) 100%);
            border: 1px solid rgba(16, 185, 129, 0.3);
            border-radius: 8px;
            font-size: 0.9rem;
            color: #d1d5db;
            line-height: 1.6;
        }
        
        .dashboard-link-container {
            display: flex;
            flex-direction: row;
            gap: 20px;
            align-items: stretch;
        }
        
        .dashboard-link-item {
            display: flex;
            align-items: flex-start;
            gap: 16px;
            padding: 16px 20px;
            background: rgba(31, 41, 55, 0.6);
            border: 1px solid rgba(75, 85, 99, 0.4);
            border-radius: 8px;
            transition: all 0.3s ease;
            flex: 1;
            min-width: 0;
        }
        
        .dashboard-link-item:hover {
            background: rgba(31, 41, 55, 0.8);
            border-color: rgba(96, 165, 250, 0.6);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }
        
        .link-icon {
            font-size: 1.5rem;
            line-height: 1;
            flex-shrink: 0;
            margin-top: 4px;
        }
        
        .link-content {
            flex: 1;
            min-width: 0;
        }
        
        .link-title {
            color: #ffffff;
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 4px;
        }
        
        .link-description {
            color: #9ca3af;
            font-size: 0.9rem;
            margin-bottom: 12px;
            line-height: 1.4;
        }
        
        .dashboard-link {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 16px;
            background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
            color: #ffffff !important;
            text-decoration: none !important;
            border-radius: 6px;
            font-weight: 500;
            font-size: 0.9rem;
            transition: all 0.3s ease;
            box-shadow: 0 2px 4px rgba(59, 130, 246, 0.3);
            border: 1px solid rgba(59, 130, 246, 0.5);
        }
        
        .dashboard-link:hover {
            background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%);
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(59, 130, 246, 0.4);
            border-color: rgba(59, 130, 246, 0.8);
        }
        
        .dashboard-link:active {
            transform: translateY(0);
            box-shadow: 0 2px 4px rgba(59, 130, 246, 0.3);
        }
        
        .link-text {
            flex: 1;
            min-width: 0;
            word-break: break-all;
            font-family: 'Source Code Pro', 'Monaco', 'Consolas', monospace;
            font-size: 0.85rem;
        }
        
        .link-arrow {
            font-size: 1rem;
            font-weight: bold;
            opacity: 0.8;
            transition: opacity 0.2s ease;
        }
        
        .dashboard-link:hover .link-arrow {
            opacity: 1;
        }
        
        @media (max-width: 768px) {
            .dashboard-link-container {
                flex-direction: column;
                gap: 12px;
            }
            
            .dashboard-link-item {
                flex-direction: column;
                gap: 12px;
                padding: 16px;
            }
            
            .link-icon {
                align-self: center;
                margin-top: 0;
            }
            
            .dashboard-link {
                justify-content: center;
                text-align: center;
            }
        }
        
        @media (min-width: 769px) and (max-width: 1024px) {
            .dashboard-link-container {
                gap: 16px;
            }
            
            .dashboard-link-item {
                padding: 14px 16px;
            }
            
            .link-description {
                font-size: 0.85rem;
            }
        }
        
        .visualization-note {
            margin-top: 24px;
            padding: 16px 20px;
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(16, 185, 129, 0.1) 100%);
            border: 1px solid rgba(59, 130, 246, 0.3);
            border-radius: 6px;
            font-size: 0.9rem;
            color: #d1d5db;
            line-height: 1.6;
        }
        
        .visualization-note strong {
            color: #60a5fa;
            font-weight: 600;
        }
        
        .visualization-note p {
            margin: 0;
        }
        
        .legend-section {
            margin-top: 24px;
            padding: 20px;
            background: rgba(31, 41, 55, 0.6);
            border: 1px solid rgba(75, 85, 99, 0.4);
            border-radius: 8px;
        }
        
        .legend-section h4 {
            color: #f3f4f6;
            font-size: 1rem;
            margin-bottom: 16px;
            font-weight: 600;
        }
        
        .legend-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 12px;
        }
        
        .legend-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 12px;
            background: rgba(17, 24, 39, 0.6);
            border-radius: 6px;
            border: 1px solid rgba(75, 85, 99, 0.3);
        }
        
        .legend-icon {
            font-size: 1.5rem;
            font-weight: bold;
            width: 32px;
            height: 32px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 4px;
            flex-shrink: 0;
        }
        
        .legend-icon.status-fulfilled {
            color: #10b981;
            background: rgba(16, 185, 129, 0.15);
        }
        
        .legend-icon.status-partial {
            color: #f59e0b;
            background: rgba(245, 158, 11, 0.15);
        }
        
        .legend-icon.status-missing {
            color: #ef4444;
            background: rgba(239, 68, 68, 0.15);
        }
        
        .legend-icon.status-unknown {
            color: #9ca3af;
            background: rgba(156, 163, 175, 0.15);
        }
        
        .legend-icon.status-excessive {
            color: #8b5cf6;
            background: rgba(139, 92, 246, 0.15);
        }
        
        .legend-label {
            color: #d1d5db;
            font-size: 0.9rem;
            line-height: 1.4;
        }
        
        .legend-label strong {
            color: #f3f4f6;
            font-weight: 600;
        }
        
        .level-matrix-section {
            margin: 32px 0;
            padding: 24px;
            background: rgba(17, 24, 39, 0.6);
            border: 1px solid rgba(75, 85, 99, 0.4);
            border-radius: 12px;
            box-shadow: 0 20px 45px rgba(15, 23, 42, 0.4);
        }

        .level-matrix-section h2 {
            margin: 0 0 12px 0;
            font-size: 1.35rem;
            color: #f9fafb;
            font-weight: 600;
        }

        .matrix-description {
            margin-bottom: 18px;
            color: #cbd5f5;
            font-size: 0.9rem;
        }

        .matrix-scroll {
            width: 100%;
            overflow-x: auto;
            padding-bottom: 8px;
        }

        .department-matrix {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            min-width: 960px;
        }

        .department-matrix thead th {
            position: sticky;
            top: 0;
            background: #1b2433;
            padding: 14px 18px;
            text-align: center;
            font-weight: 600;
            font-size: 1rem;
            color: #f9fafb;
            z-index: 2;
            letter-spacing: 0.03em;
            border-bottom: 1px solid rgba(148, 163, 184, 0.25);
        }

        .matrix-level-header {
            min-width: 180px;
            text-align: left;
            border-top-left-radius: 12px;
        }

        .dept-header span {
            display: block;
            word-break: break-word;
        }

        .department-matrix tbody tr:first-child .matrix-level {
            border-top-left-radius: 12px;
        }

        .matrix-level {
            padding: 12px 16px;
            background: rgba(17, 24, 39, 0.85);
            color: #e2e8f0;
            font-weight: 600;
            border-bottom: 1px solid rgba(148, 163, 184, 0.14);
        }

        .matrix-cell {
            padding: 12px 14px;
            text-align: right;
            color: #f1f5f9;
            font-family: 'Source Code Pro', 'Consolas', monospace;
            font-size: 0.9rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.14);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
        }

        .matrix-cell:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 18px rgba(15, 23, 42, 0.35);
            color: #ffffff;
        }

        .matrix-cell.empty {
            color: #94a3b8;
            font-style: italic;
        }

        .summary-row .summary-title {
            padding: 10px 16px;
            font-weight: 600;
            letter-spacing: 0.02em;
            color: #f8fafc;
        }

        .summary-cell {
            padding: 11px 14px;
            text-align: right;
            color: #0b1120;
            font-weight: 600;
            font-family: 'Source Code Pro', 'Consolas', monospace;
        }

        .summary-row.total .summary-title {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.75), rgba(5, 150, 105, 0.9));
        }

        .summary-row.total .summary-cell {
            background: linear-gradient(135deg, rgba(45, 212, 191, 0.35), rgba(16, 185, 129, 0.45));
            color: #032524;
        }

        .summary-row.target .summary-title {
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.75), rgba(37, 99, 235, 0.9));
        }

        .summary-row.target .summary-cell {
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.55), rgba(37, 99, 235, 0.65));
            color: #e8f2ff;
        }

        .summary-row.delta .summary-title {
            background: linear-gradient(135deg, rgba(249, 115, 22, 0.75), rgba(194, 65, 12, 0.9));
        }

        .summary-cell.delta {
            color: #0b1120;
        }

        .summary-cell.delta.positive {
            background: rgba(16, 185, 129, 0.75);
            color: #f8fafc;
        }

        .summary-cell.delta.negative {
            background: rgba(220, 38, 38, 0.8);
            color: #f8fafc;
        }

        .matrix-scroll::-webkit-scrollbar {
            height: 8px;
        }

        .matrix-scroll::-webkit-scrollbar-track {
            background: rgba(30, 41, 59, 0.8);
            border-radius: 999px;
        }

        .matrix-scroll::-webkit-scrollbar-thumb {
            background: rgba(96, 165, 250, 0.65);
            border-radius: 999px;
        }

        @media (max-width: 768px) {
            .legend-grid {
                grid-template-columns: 1fr;
            }
        }
        
        /* Department by Level Visualization Styles */
        .department-by-level-subsection {
            margin: 32px 0 0 0;
            padding: 24px;
            background: rgba(31, 41, 55, 0.4);
            border-radius: 8px;
            border: 1px solid rgba(75, 85, 99, 0.3);
            border-top: 3px solid #60a5fa;
        }
        
        .department-by-level-subsection h3 {
            color: #f3f4f6;
            margin-bottom: 12px;
            font-size: 1.25rem;
            font-weight: 600;
        }
        
        .section-description {
            color: #9ca3af;
            font-size: 0.95rem;
            margin-bottom: 20px;
            line-height: 1.5;
        }
        
        .unapproved-warning {
            color: #ef4444;
            font-weight: 600;
        }
        
        .level-dept-table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(17, 24, 39, 0.4);
        }
        
        .level-dept-table thead {
            background: rgba(31, 41, 55, 0.8);
        }
        
        .level-dept-table th {
            padding: 14px 16px;
            text-align: left;
            color: #f3f4f6;
            font-weight: 600;
            font-size: 0.9rem;
            border-bottom: 2px solid rgba(75, 85, 99, 0.5);
        }
        
        .level-dept-table td {
            padding: 14px 16px;
            border-bottom: 1px solid rgba(75, 85, 99, 0.2);
            color: #d1d5db;
            vertical-align: middle;
        }
        
        .level-dept-table tbody tr:hover {
            background: rgba(55, 65, 81, 0.3);
        }
        
        .level-name-col {
            font-size: 1.05rem;
            color: #f3f4f6;
        }
        
        .dept-count-col {
            color: #9ca3af;
            font-size: 0.9rem;
        }
        
        .unapproved-count-col {
            font-weight: 600;
            font-size: 0.95rem;
        }
        
        .unapproved-count-col.has-unapproved {
            color: #ef4444;
        }
        
        .unapproved-count-col.no-unapproved {
            color: #10b981;
        }
        
        .dept-badges-col {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        
        .dept-badge {
            display: inline-block;
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 500;
            white-space: normal;
            text-align: center;
            margin: 4px;
            min-width: 120px;
        }
        
        .dept-badge small {
            display: block;
            font-size: 0.75rem;
            margin-top: 4px;
            opacity: 0.85;
            font-weight: 400;
        }
        
        .dept-badge.dept-approved {
            background: rgba(96, 165, 250, 0.15);
            color: #f8fafc;
            border: 2px solid #60a5fa;
        }
        
        .dept-badge.dept-unapproved {
            background: rgba(239, 68, 68, 0.15);
            color: #ef4444;
            border: 1px solid rgba(239, 68, 68, 0.4);
            animation: badgePulse 2s ease-in-out infinite;
        }
        
        .level-total-dgsf {
            display: block;
            color: #60a5fa;
            font-weight: 600;
            margin-top: 6px;
            font-size: 0.9rem;
        }
        
        @keyframes badgePulse {
            0%, 100% {
                border-color: rgba(239, 68, 68, 0.4);
                box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4);
            }
            50% {
                border-color: rgba(239, 68, 68, 0.6);
                box-shadow: 0 0 0 4px rgba(239, 68, 68, 0);
            }
        }
        
        .summary-section, .status-summary, .unmatched-section, .scheme-summary, .scheme-section {
            margin-bottom: 32px;
        }
        
        .summary-section h2, .status-summary h2, .unmatched-section h2, .scheme-summary h2, .scheme-section h2 {
            color: #ffffff;
            margin-bottom: 24px;
            font-size: 1.5rem;
            font-weight: 600;
            letter-spacing: -0.025em;
        }
        
        .unmatched-section h3 {
            color: #f59e0b;
            margin-bottom: 16px;
            font-size: 1.125rem;
            font-weight: 500;
        }
        
        .unmatched-alert {
            display: flex;
            align-items: flex-start;
            gap: 16px;
            padding: 20px 24px;
            margin: 20px 0;
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.15) 0%, rgba(220, 38, 38, 0.1) 100%);
            border: 2px solid #ef4444;
            border-left: 6px solid #dc2626;
            border-radius: 8px;
            animation: alertPulse 2s ease-in-out infinite;
        }
        
        @keyframes alertPulse {
            0%, 100% {
                border-color: #ef4444;
                box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4);
            }
            50% {
                border-color: #dc2626;
                box-shadow: 0 0 0 8px rgba(239, 68, 68, 0);
            }
        }
        
        .alert-icon {
            font-size: 2rem;
            line-height: 1;
            flex-shrink: 0;
            animation: alertShake 3s ease-in-out infinite;
        }
        
        @keyframes alertShake {
            0%, 100% { transform: rotate(0deg); }
            10%, 30%, 50%, 70%, 90% { transform: rotate(-10deg); }
            20%, 40%, 60%, 80% { transform: rotate(10deg); }
        }
        
        .alert-content {
            flex: 1;
            color: #fca5a5;
            font-size: 0.95rem;
            line-height: 1.6;
        }
        
        .alert-content strong {
            color: #ef4444;
            font-weight: 700;
            font-size: 1.05rem;
            display: block;
            margin-bottom: 6px;
        }
        
        .summary-cards, .scheme-cards {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 20px;
        }
        
        @media (min-width: 1400px) {
            .summary-cards, .scheme-cards {
                grid-template-columns: repeat(5, 1fr);
            }
        }
        
        @media (min-width: 1024px) and (max-width: 1399px) {
            .summary-cards, .scheme-cards {
                grid-template-columns: repeat(4, 1fr);
            }
        }
        
        .summary-cards .card:nth-child(1) { animation-delay: 0.1s; }
        .summary-cards .card:nth-child(2) { animation-delay: 0.2s; }
        .summary-cards .card:nth-child(3) { animation-delay: 0.3s; }
        .summary-cards .card:nth-child(4) { animation-delay: 0.4s; }
        .summary-cards .card:nth-child(5) { animation-delay: 0.5s; }
        .summary-cards .card:nth-child(6) { animation-delay: 0.6s; }
        .summary-cards .card:nth-child(7) { animation-delay: 0.7s; }
        .summary-cards .card:nth-child(8) { animation-delay: 0.8s; }
        .summary-cards .card:nth-child(9) { animation-delay: 0.9s; }
        
        .card, .scheme-card {
            background: #111827;
            border: 1px solid #1f2937;
            padding: 16px 12px;
            border-radius: 6px;
            text-align: center;
            transition: all 0.3s ease;
            animation: fadeInScale 0.6s ease-out;
        }
        
        .card:hover, .scheme-card:hover {
            transform: translateY(-2px);
            border-color: #4b5563;
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.3);
        }
        
        @keyframes fadeInScale {
            from {
                opacity: 0;
                transform: scale(0.95);
            }
            to {
                opacity: 1;
                transform: scale(1);
            }
        }
        
        
        .card h3, .scheme-card h3 {
            font-size: 0.7rem;
            margin-bottom: 6px;
            color: #9ca3af;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            font-weight: 500;
        }
        
        .card-value {
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 4px;
            color: #ffffff;
            font-family: 'Source Code Pro', monospace;
        }
        
        .card-label {
            font-size: 0.7rem;
            color: #6b7280;
            font-weight: 400;
        }
        
        .scheme-stats {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
            margin-top: 15px;
        }
        
        .stat {
            text-align: center;
        }
        
        .stat-value {
            display: block;
            font-size: 1.5em;
            font-weight: 700;
            color: #60a5fa;
        }
        
        .stat-label {
            display: block;
            font-size: 0.8em;
            color: #9ca3af;
            margin-top: 4px;
        }
        
        .status-cards {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
        }
        
        @media (min-width: 1400px) {
            .status-cards {
                grid-template-columns: repeat(4, 1fr);
            }
        }
        
        @media (min-width: 1024px) and (max-width: 1399px) {
            .status-cards {
                grid-template-columns: repeat(3, 1fr);
            }
        }
        
        .status-card {
            padding: 25px;
            border-radius: 12px;
            text-align: center;
            color: #fff;
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 6px 20px rgba(0,0,0,0.3);
        }
        
        .status-card.fulfilled {
            background: linear-gradient(135deg, #059669 0%, #10b981 100%);
        }
        
        .status-card.partial {
            background: linear-gradient(135deg, #d97706 0%, #f59e0b 100%);
        }
        
        .status-card.missing {
            background: linear-gradient(135deg, #dc2626 0%, #ef4444 100%);
        }
        
        .status-card h3 {
            margin-bottom: 12px;
            font-size: 1.1em;
        }
        
        .status-count {
            font-size: 2.5em;
            font-weight: 700;
        }
        
        .table-container {
            overflow-x: auto;
            border-radius: 8px;
            background: #111827;
            border: 1px solid #1f2937;
            margin-bottom: 24px;
        }
        
        .comparison-table, .unmatched-table {
            width: 100%;
            border-collapse: collapse;
            border-spacing: 0;
            background-color: transparent;
            font-size: 0.875rem;
            border: 1px solid #374151;
            table-layout: fixed;
        }
        
        .comparison-table th, .unmatched-table th {
            background: #1f2937;
            color: #f9fafb;
            padding: 16px 20px;
            text-align: left;
            font-weight: 600;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            position: sticky;
            top: 0;
            z-index: 10;
            border: 1px solid #374151;
            border-bottom: 2px solid #4b5563;
            font-family: 'Roboto', sans-serif;
        }
        
        .comparison-table td, .unmatched-table td {
            padding: 16px 20px;
            border: 1px solid #374151;
            color: #e5e7eb;
            font-weight: 400;
            background-color: #111827;
            word-wrap: break-word;
            overflow-wrap: break-word;
        }
        
        /* Column width classes for responsive design - wider for better readability */
        .col-dept { width: 14%; }
        .col-division { width: 12%; }
        .col-function { width: 14%; }
        .col-level { width: 16%; }
        .col-count { width: 10%; }
        .col-area { width: 12%; }
        .col-delta { width: 14%; }
        .col-status { width: 10%; }
        .col-quality { width: 8%; }
        .col-suggestion { width: 20%; }
        
        /* Add thick division line between Required Area and Level */
        .comparison-table th:nth-child(5),
        .comparison-table td:nth-child(5) {
            border-right: 3px solid #4b5563;
        }
        
        .comparison-table tbody tr, .unmatched-table tbody tr {
            background-color: #111827;
            transition: all 0.3s ease;
            animation: slideInLeft 0.5s ease-out;
        }
        
        .comparison-table tbody tr:nth-child(even), .unmatched-table tbody tr:nth-child(even) {
            animation-delay: 0.1s;
        }
        
        .comparison-table tbody tr:nth-child(odd), .unmatched-table tbody tr:nth-child(odd) {
            animation-delay: 0.05s;
        }
        
        @keyframes slideInLeft {
            from {
                opacity: 0;
                transform: translateX(-20px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        
        .comparison-table tr:hover td, .unmatched-table tr:hover td {
            background-color: #1f2937;
            border-color: #4b5563;
        }
        
        .status-fulfilled {
            border: 2px solid #10b981;
            background: linear-gradient(90deg, rgba(16,185,129,0.1) 0%, transparent 100%);
        }
        
        .status-partial {
            border: 2px solid #f59e0b;
            background: linear-gradient(90deg, rgba(245,158,11,0.1) 0%, transparent 100%);
        }
        
        .status-missing {
            border: 2px solid #ef4444;
            background: linear-gradient(90deg, rgba(239,68,68,0.1) 0%, transparent 100%);
        }
        
        .positive {
            color: #10b981;
            font-weight: 700;
        }
        
        .negative {
            color: #ef4444;
            font-weight: 700;
        }
        
        .alert-high-difference {
            background: #7f1d1d !important;
            color: #fecaca !important;
            font-weight: 700;
            border: 2px solid #ef4444 !important;
            animation: alertPulse 2s infinite;
        }
        
        .alert-count-delta {
            background: #78350f !important;
            color: #fed7aa !important;
            font-weight: 700;
            border: 2px solid #f59e0b !important;
        }
        
        .alert-area-delta {
            background: #7c2d12 !important;
            color: #fed7aa !important;
            font-weight: 700;
            border: 2px solid #ea580c !important;
        }
        
        @keyframes alertPulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        
        .status-badge {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.6875rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.025em;
            display: inline-block;
            border: 1px solid transparent;
            transition: all 0.3s ease;
            animation: fadeInScale 0.6s ease-out;
        }
        
        .status-badge:hover {
            transform: scale(1.05);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }
        
        .status-badge.fulfilled {
            background: #065f46;
            color: #10b981;
            border-color: #10b981;
        }
        
        .status-badge.partial {
            background: #78350f;
            color: #f59e0b;
            border-color: #f59e0b;
        }
        
        .status-badge.missing {
            background: #7f1d1d;
            color: #ef4444;
            border-color: #ef4444;
        }
        
        .status-badge.excessive {
            background: #7c2d12;
            color: #ea580c;
            border-color: #ea580c;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        
        .status-badge.unmatched {
            background: #374151;
            color: #9ca3af;
            border-color: #6b7280;
        }
        
        .quality-badge {
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 0.625rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.025em;
        }
        
        .quality-badge.high {
            background-color: #0c4a6e;
            color: #38bdf8;
            border: 1px solid #0ea5e9;
        }
        
        .quality-badge.medium {
            background-color: #78350f;
            color: #fbbf24;
            border: 1px solid #f59e0b;
        }
        
        .quality-badge.low, .quality-badge.no {
            background-color: #7f1d1d;
            color: #f87171;
            border: 1px solid #ef4444;
        }
        
        .chart-section {
            margin: 48px 0;
            padding: 32px;
            background: #111827;
            border-radius: 12px;
            border: 1px solid #1f2937;
            text-align: center;
        }
        
        .chart-section h2 {
            color: #ffffff;
            margin-bottom: 24px;
            font-size: 1.5rem;
            font-weight: 600;
        }
        
        .chart-container {
            position: relative;
            width: 100%;
            height: 400px;
            max-width: 500px;
            margin: 0 auto;
        }
        
        .chart-card {
            position: relative;
            z-index: 1;
        }
        
        .section-diagram {
            margin: 48px 0;
            padding: 32px;
            background: #111827;
            border-radius: 12px;
            border: 1px solid #1f2937;
        }
        
        .section-diagram h2 {
            color: #ffffff;
            margin-bottom: 24px;
            font-size: 1.5rem;
            font-weight: 600;
            text-align: center;
        }
        
        .building-section {
            display: flex;
            justify-content: center;
            align-items: flex-end;
            min-height: 600px;
            padding: 20px;
            position: relative;
        }
        
        .level-stack {
            display: flex;
            flex-direction: column;
            align-items: center;
            margin: 0 20px;
            position: relative;
        }
        
        .level-label {
            color: #e5e7eb;
            font-size: 0.875rem;
            font-weight: 500;
            margin-bottom: 8px;
            text-align: center;
            min-width: 120px;
        }
        
        .level-elevation {
            display: block;
            color: #9ca3af;
            font-size: 0.8rem;
            margin-top: 4px;
            font-weight: 400;
        }
        
        .department-pills {
            display: flex;
            flex-direction: column;
            gap: 4px;
            width: 200px;
            min-height: 100px;
        }
        
        .department-pill {
            background: linear-gradient(135deg, var(--dept-color) 0%, var(--dept-color-dark) 100%);
            color: white;
            padding: 8px 12px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 500;
            text-align: center;
            border: 1px solid var(--dept-border);
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
            transition: all 0.3s ease;
            cursor: pointer;
            position: relative;
        }
        
        .department-pill:hover {
            transform: scale(1.05);
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
        }
        
        .department-pill::before {
            content: attr(data-area);
            position: absolute;
            top: -20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.65rem;
            opacity: 0;
            transition: opacity 0.3s ease;
            pointer-events: none;
        }
        
        .department-pill:hover::before {
            opacity: 1;
        }
        
        /* Department color variables */
        .dept-emergency { --dept-color: #dc2626; --dept-color-dark: #991b1b; --dept-border: #ef4444; }
        .dept-inpatient { --dept-color: #059669; --dept-color-dark: #047857; --dept-border: #10b981; }
        .dept-diagnostic { --dept-color: #2563eb; --dept-color-dark: #1d4ed8; --dept-border: #3b82f6; }
        .dept-mechanical { --dept-color: #7c3aed; --dept-color-dark: #6d28d9; --dept-border: #8b5cf6; }
        .dept-administration { --dept-color: #ea580c; --dept-color-dark: #c2410c; --dept-border: #f97316; }
        .dept-other { --dept-color: #6b7280; --dept-color-dark: #4b5563; --dept-border: #9ca3af; }
        
        .level-connector {
            position: absolute;
            right: -10px;
            top: 50%;
            transform: translateY(-50%);
            width: 2px;
            height: 100%;
            background: linear-gradient(to bottom, #4b5563, #6b7280, #4b5563);
            opacity: 0.6;
        }
        
        .section-legend {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 16px;
            margin-top: 24px;
            padding: 16px;
            background: #1f2937;
            border-radius: 8px;
        }
        
        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
            color: #e5e7eb;
            font-size: 0.875rem;
        }
        
        .legend-color {
            width: 16px;
            height: 16px;
            border-radius: 50%;
            border: 2px solid;
        }
        
        .viewer3d-section {
            margin: 48px 0;
            padding: 32px;
            background: #111827;
            border-radius: 12px;
            border: 1px solid #1f2937;
        }
        
        .viewer3d-section h2 {
            color: #ffffff;
            margin-bottom: 24px;
            font-size: 1.5rem;
            font-weight: 600;
            text-align: center;
        }
        
        .viewer3d-controls {
            display: flex;
            justify-content: center;
            gap: 12px;
            margin-bottom: 24px;
            flex-wrap: wrap;
        }
        
        .control-btn {
            padding: 8px 16px;
            background: #1f2937;
            color: #e5e7eb;
            border: 1px solid #374151;
            border-radius: 6px;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .control-btn:hover {
            background: #374151;
            border-color: #4b5563;
            transform: translateY(-1px);
        }
        
        .control-btn.active {
            background: #3b82f6;
            border-color: #2563eb;
            color: white;
        }
        
        .viewer3d-container {
            position: relative;
            width: 100%;
            height: 600px;
            background: #0f172a;
            border-radius: 8px;
            border: 1px solid #1f2937;
            overflow: hidden;
        }
        
        #viewer3d-canvas {
            width: 100%;
            height: 100%;
            display: block;
        }
        
        .viewer3d-info {
            position: absolute;
            top: 16px;
            right: 16px;
            z-index: 100;
        }
        
        .info-panel {
            background: rgba(17, 24, 39, 0.95);
            border: 1px solid #374151;
            border-radius: 8px;
            padding: 16px;
            color: #e5e7eb;
            font-size: 0.875rem;
            min-width: 200px;
            backdrop-filter: blur(8px);
        }
        
        .info-panel h4 {
            color: #ffffff;
            margin-bottom: 8px;
            font-size: 1rem;
        }
        
        .viewer3d-legend {
            margin-top: 24px;
            padding: 16px;
            background: #1f2937;
            border-radius: 8px;
        }
        
        .legend-title {
            color: #ffffff;
            font-size: 1rem;
            font-weight: 600;
            margin-bottom: 12px;
            text-align: center;
        }
        
        .legend-items {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 16px;
        }
        
        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
            color: #e5e7eb;
            font-size: 0.875rem;
        }
        
        .legend-color {
            width: 16px;
            height: 16px;
            border-radius: 50%;
            border: 2px solid;
        }
        
        /* Heatmap colors */
        .heatmap-excellent { background-color: #10b981; border-color: #059669; }
        .heatmap-good { background-color: #84cc16; border-color: #65a30d; }
        .heatmap-fair { background-color: #eab308; border-color: #ca8a04; }
        .heatmap-poor { background-color: #f97316; border-color: #ea580c; }
        .heatmap-critical { background-color: #ef4444; border-color: #dc2626; }
        
        .report-footer {
            text-align: center;
            margin-top: 48px;
            padding: 24px;
            background: #111827;
            border-radius: 8px;
            border: 1px solid #1f2937;
            color: #6b7280;
            font-size: 0.875rem;
        }
        
        .scheme-comparisons {
            display: flex;
            flex-direction: column;
            gap: 24px;
        }
        
        .scheme-section {
            background: #111827;
            padding: 24px;
            border-radius: 8px;
            border: 1px solid #1f2937;
        }
        
        @media (max-width: 1024px) {
            /* Stack charts vertically on tablets and smaller */
            .charts-section {
                grid-template-columns: 1fr !important;
            }
            
            .minimap-nav {
                display: none !important;
            }
            
            .container {
                padding-right: 24px !important;
            }
            
            /* Show 2 cards per row on tablets */
            .summary-cards, .scheme-cards {
                grid-template-columns: repeat(2, 1fr) !important;
            }
            
            .status-cards {
                grid-template-columns: repeat(2, 1fr) !important;
            }
        }
        
        @media (max-width: 600px) {
            .container {
                padding: 15px 10px;
                padding-right: 10px !important; /* Remove minimap spacing on mobile */
                padding-bottom: 100px !important;
            }
            
            /* Make department summary more compact */
            .department-summary-container {
                padding: 0 !important;
            }
            
            .chart-card {
                padding: 16px !important;
            }
            
            .chart-card h3 {
                font-size: 14px !important;
            }
            
            canvas {
                max-height: 300px !important;
            }
            
            /* Department by level table */
            .level-dept-table {
                font-size: 0.85rem !important;
            }
            
            .dept-badge {
                font-size: 0.75rem !important;
                padding: 4px 8px !important;
            }
            
            .comparison-table, .unmatched-table {
                font-size: 0.75rem;
            }
            
            .comparison-table th, .unmatched-table th,
            .comparison-table td, .unmatched-table td {
                padding: 8px 6px;
            }
            
            /* Adjust column widths for mobile */
            .col-dept { width: 15%; }
            .col-division { width: 12%; }
            .col-function { width: 15%; }
            .col-level { width: 15%; }
            .col-count { width: 10%; }
            .col-area { width: 12%; }
            .col-delta { width: 15%; }
            .col-status { width: 6%; }
            
            /* Summary cards - stack vertically on very small screens only */
            .summary-cards {
                grid-template-columns: repeat(2, 1fr) !important;
            }
            
            /* Tree view adjustments */
            .tree-node-header {
                flex-direction: column;
                align-items: flex-start !important;
            }
            
            .tree-node-metrics {
                width: 100%;
                margin-top: 8px;
            }
        }
        
        /* Department collapse styles */
        .dept-row.collapsed {
            display: none;
        }
        
        .department-header.collapsed .collapse-icon {
            transform: rotate(-90deg);
        }
        
        /* Suggestion column styles */
        .suggestion-text {
            color: #9ca3af;
            font-size: 0.9rem;
            font-style: italic;
        }
        
        .suggestion-text strong {
            color: #60a5fa;
            font-weight: 600;
            font-style: normal;
        }
        
        /* Context Menu Styles */
        .context-menu {
            position: fixed;
            background: #1f2937;
            border: 2px solid #374151;
            border-radius: 8px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6);
            z-index: 9999;
            min-width: 350px;
            display: none;
            overflow: visible;
        }
        
        .context-menu.active {
            display: block;
        }
        
        .context-menu-item {
            padding: 12px 16px;
            color: #f8fafc;
            cursor: pointer;
            transition: background 0.2s ease;
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 0.95rem;
            border-bottom: 1px solid #374151;
        }
        
        .context-menu-item:last-child {
            border-bottom: none;
        }
        
        .context-menu-item:hover {
            background: #374151;
        }
        
        .context-menu-icon {
            font-size: 1.1rem;
            color: #60a5fa;
            width: 20px;
            text-align: center;
        }
        
        /* Search Bar Styles */
        .context-menu-search {
            position: relative;
            padding: 12px;
            border-bottom: 1px solid #374151;
        }
        
        #searchInput {
            width: 100%;
            padding: 8px 12px;
            background: #111827;
            border: 1px solid #374151;
            border-radius: 6px;
            color: #f8fafc;
            font-size: 0.9rem;
            outline: none;
            transition: border-color 0.2s ease;
        }
        
        #searchInput:focus {
            border-color: #60a5fa;
            box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.2);
        }
        
        #searchInput::placeholder {
            color: #6b7280;
        }
        
        /* Search Suggestions Dropdown (appears ABOVE search bar) */
        .search-suggestions {
            position: absolute;
            bottom: 100%;
            left: 12px;
            right: 12px;
            margin-bottom: 8px;
            background: #1f2937;
            border: 2px solid #60a5fa;
            border-radius: 8px;
            max-height: 300px;
            overflow-y: auto;
            box-shadow: 0 -10px 40px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(96, 165, 250, 0.3);
            display: none;
            z-index: 99999;
        }
        
        .search-suggestions.active {
            display: block;
        }
        
        .suggestion-item {
            padding: 10px 12px;
            color: #f8fafc;
            cursor: pointer;
            border-bottom: 1px solid #374151;
            transition: background 0.2s ease;
        }
        
        .suggestion-item:last-child {
            border-bottom: none;
        }
        
        .suggestion-item:hover {
            background: #1f2937;
        }
        
        .suggestion-item.selected {
            background: #374151;
        }
        
        .suggestion-path {
            font-size: 0.85rem;
            color: #9ca3af;
            margin-top: 2px;
        }
        
        .suggestion-match {
            color: #60a5fa;
            font-weight: 600;
        }
        
        .no-results {
            padding: 12px;
            color: #6b7280;
            text-align: center;
            font-size: 0.9rem;
        }
        
        .suggestion-header {
            padding: 8px 12px;
            color: #9ca3af;
            font-size: 0.8rem;
            font-style: italic;
            border-bottom: 1px solid #374151;
            background: #0f172a;
        }
        
        /* Highlight animation for navigated nodes */
        @keyframes highlightFlash {
            0%, 100% { background: transparent; }
            50% { background: rgba(96, 165, 250, 0.3); }
        }
        
        .tree-node.highlighted {
            animation: highlightFlash 1.5s ease-in-out 2;
        }
        
        /* Minimap Navigation Styles */
        .minimap-nav {
            position: fixed;
            right: 24px;
            top: 50%;
            transform: translateY(-50%);
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 8px;
            padding: 16px 12px;
            z-index: 998;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6);
            max-height: 80vh;
            overflow-y: auto;
            min-width: 200px;
            transition: all 0.3s ease;
        }
        
        .minimap-nav:hover {
            border-color: #374151;
            box-shadow: 0 12px 50px rgba(0, 0, 0, 0.7);
        }
        
        .minimap-title {
            color: #9ca3af;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #1f2937;
            text-align: center;
        }
        
        .minimap-item {
            display: flex;
            align-items: center;
            padding: 8px 12px;
            margin: 4px 0;
            color: #9ca3af;
            font-size: 0.8rem;
            cursor: pointer;
            border-radius: 6px;
            transition: all 0.2s ease;
            border: 3px solid transparent;
            position: relative;
        }
        
        .minimap-item:hover {
            background: #1f2937;
            color: #f8fafc;
            border-color: #60a5fa;
            transform: translateX(-2px);
        }
        
        .minimap-item.active {
            background: #1f2937;
            color: #60a5fa;
            border-color: #60a5fa;
            font-weight: 600;
        }
        
        .minimap-item.active::before {
            content: '';
            position: absolute;
            left: -12px;
            top: 50%;
            transform: translateY(-50%);
            width: 8px;
            height: 8px;
            background: #60a5fa;
            border-radius: 50%;
            box-shadow: 0 0 8px rgba(96, 165, 250, 0.6);
        }
        
        .minimap-icon {
            margin-right: 8px;
            font-size: 1rem;
            min-width: 16px;
            text-align: center;
        }
        
        .minimap-toggle {
            position: fixed;
            right: 24px;
            top: 24px;
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 6px;
            padding: 8px 12px;
            color: #9ca3af;
            cursor: pointer;
            z-index: 999;
            font-size: 0.875rem;
            transition: all 0.3s ease;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }
        
        .minimap-toggle:hover {
            background: #1f2937;
            color: #60a5fa;
            border-color: #374151;
        }
        
        .minimap-nav.hidden {
            opacity: 0;
            pointer-events: none;
            transform: translateY(-50%) translateX(20px);
        }
        
        /* Scrollbar styling for minimap */
        .minimap-nav::-webkit-scrollbar {
            width: 6px;
        }
        
        .minimap-nav::-webkit-scrollbar-track {
            background: #0a0e13;
            border-radius: 3px;
        }
        
        .minimap-nav::-webkit-scrollbar-thumb {
            background: #374151;
            border-radius: 3px;
        }
        
        .minimap-nav::-webkit-scrollbar-thumb:hover {
            background: #4b5563;
        }
        
        /* Scheme Switcher Styles */
        .minimap-section-divider {
            height: 1px;
            background: linear-gradient(90deg, transparent 0%, #374151 50%, transparent 100%);
            margin: 16px 0;
        }
        
        .scheme-selector {
            position: relative;
        }
        
        .scheme-selector.active {
            background: #1f2937;
            color: #10b981 !important;
            border-color: #10b981 !important;
            font-weight: 600;
        }
        
        .scheme-selector.active::after {
            content: '✓';
            position: absolute;
            right: 12px;
            color: #10b981;
            font-weight: bold;
            font-size: 0.9rem;
        }
        
        .scheme-selector:hover {
            background: #1f2937;
            color: #10b981;
            border-color: #10b981;
        }
        
        /* Scheme Content Visibility */
        .scheme-content {
            display: none;
            animation: fadeInContent 0.4s ease-out;
        }
        
        .scheme-content.active {
            display: block;
        }
        
        @keyframes fadeInContent {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        /* Main Header Styles */
        .main-header {
            text-align: center;
            margin-bottom: 32px;
            padding: 24px;
            background: linear-gradient(135deg, rgba(17, 24, 39, 0.6) 0%, rgba(31, 41, 55, 0.4) 100%);
            border-radius: 12px;
            border: 1px solid rgba(75, 85, 99, 0.3);
        }
        
        .main-header h1 {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 16px;
            background: linear-gradient(135deg, #60a5fa 0%, #10b981 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .main-header .report-info {
            display: flex;
            justify-content: center;
            gap: 24px;
            font-size: 0.9rem;
            color: #9ca3af;
        }
        
        .main-header .report-info p {
            margin: 0;
        }
        
        /* Tree View Styles */
        .tree-view-section {
            margin: 32px 0;
            padding: 24px;
            background: linear-gradient(135deg, rgba(17, 24, 39, 0.6) 0%, rgba(31, 41, 55, 0.4) 100%);
            border-radius: 12px;
            border: 1px solid rgba(75, 85, 99, 0.3);
        }
        
        .tree-view-section h2 {
            color: #f3f4f6;
            margin-bottom: 20px;
            font-size: 1.5rem;
            font-weight: 600;
        }
        
        .tree-controls {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
        }
        
        .tree-controls button {
            padding: 8px 16px;
            background: linear-gradient(135deg, #374151 0%, #1f2937 100%);
            color: #e5e7eb;
            border: 1px solid rgba(75, 85, 99, 0.5);
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 500;
            transition: all 0.2s ease;
        }
        
        .tree-controls button:hover {
            background: linear-gradient(135deg, #4b5563 0%, #374151 100%);
            border-color: #60a5fa;
            transform: translateY(-1px);
        }
        
        .tree-container {
            background: rgba(17, 24, 39, 0.4);
            border-radius: 8px;
            padding: 16px;
            border: 1px solid rgba(75, 85, 99, 0.2);
        }
        
        .tree-node {
            margin-bottom: 4px;
            position: relative;
            overflow: visible;
        }
        
        .tree-node-dept {
            margin-bottom: 8px;
        }
        
        .tree-node-division {
            margin-left: 32px;
            margin-bottom: 6px;
        }
        
        .tree-node-division::before {
            content: '';
            position: absolute;
            left: -16px;
            top: 0;
            bottom: 0;
            width: 2px;
            background: rgba(75, 85, 99, 0.5);
        }
        
        .tree-node-division::after {
            content: '';
            position: absolute;
            left: -16px;
            top: 22px;
            width: 14px;
            height: 2px;
            background: rgba(75, 85, 99, 0.5);
        }
        
        .tree-node-room {
            margin-left: 32px;
            margin-bottom: 4px;
        }
        
        .tree-node-room::before {
            content: '';
            position: absolute;
            left: -16px;
            top: 0;
            bottom: 0;
            width: 2px;
            background: rgba(75, 85, 99, 0.4);
        }
        
        .tree-node-room::after {
            content: '';
            position: absolute;
            left: -16px;
            top: 22px;
            width: 14px;
            height: 2px;
            background: rgba(75, 85, 99, 0.4);
        }
        
        /* Hide vertical line extension for last child */
        .tree-node-division:last-child::before,
        .tree-node-room:last-child::before {
            height: 22px;
        }
        
        .tree-node-header {
            display: flex;
            align-items: center;
            padding: 10px 12px;
            background: rgba(31, 41, 55, 0.6);
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s ease;
            gap: 8px;
            border-width: 4px;
            border-style: solid;
            margin-right: 8px;
        }
        
        .tree-node-header:hover {
            background: rgba(75, 85, 99, 0.95);
            transform: translateX(-2px) scale(1.01);
            box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.5), 0 4px 12px rgba(0, 0, 0, 0.3);
        }
        
        .tree-node-dept .tree-node-header {
            background: rgba(31, 41, 55, 0.8);
            font-weight: 600;
            font-size: 1.05rem;
        }
        
        .tree-node-division .tree-node-header {
            background: rgba(31, 41, 55, 0.6);
            font-weight: 500;
            font-size: 0.95rem;
        }
        
        .tree-node-room .tree-node-header {
            background: rgba(31, 41, 55, 0.4);
            font-weight: 400;
            font-size: 0.9rem;
            cursor: default;
        }
        
        .tree-toggle-icon {
            width: 20px;
            text-align: center;
            font-size: 0.8rem;
            transition: transform 0.3s ease;
            color: #9ca3af;
        }
        
        .tree-toggle-icon.collapsed {
            transform: rotate(-90deg);
        }
        
        .tree-color-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        
        .tree-node-label {
            color: #f3f4f6;
            flex-grow: 1;
            min-width: 200px;
        }
        
        .tree-status-icon {
            margin-left: 8px;
            font-size: 1.1rem;
        }
        
        .tree-node-metrics {
            display: flex;
            gap: 12px;
            align-items: center;
            margin-left: auto;
            flex-wrap: wrap;
        }
        
        .tree-metric {
            color: #9ca3af;
            font-size: 0.85rem;
            white-space: nowrap;
            cursor: help;
        }
        
        .tree-metric strong {
            color: #e5e7eb;
            font-weight: 600;
        }
        
        /* Tooltip Enhancement */
        [title] {
            position: relative;
        }
        
        .card-value[title],
        .tree-metric[title],
        .tree-metric-delta[title],
        .tree-metric-percentage[title],
        .tree-status-icon[title] {
            cursor: help;
        }
        
        .tree-metric-delta {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
            white-space: nowrap;
        }
        
        .tree-metric-delta.positive {
            background: rgba(16, 185, 129, 0.2);
            color: #10b981;
        }
        
        .tree-metric-delta.negative {
            background: rgba(239, 68, 68, 0.2);
            color: #ef4444;
        }
        
        .tree-metric-percentage {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
            white-space: nowrap;
        }
        
        .tree-metric-percentage.positive {
            background: rgba(16, 185, 129, 0.2);
            color: #10b981;
        }
        
        .tree-metric-percentage.negative {
            background: rgba(239, 68, 68, 0.2);
            color: #ef4444;
        }
        
        .tree-node-children {
            margin-top: 4px;
            overflow: hidden;
            transition: max-height 0.3s ease, opacity 0.3s ease;
            position: relative;
        }
        
        /* Vertical connector line for department-level children */
        .tree-node-dept > .tree-node-children {
            margin-left: 24px;
            border-left: 2px solid rgba(75, 85, 99, 0.3);
            padding-left: 8px;
        }
        
        /* Vertical connector line for division-level children */
        .tree-node-division > .tree-node-children {
            border-left: 2px solid rgba(75, 85, 99, 0.25);
            padding-left: 8px;
        }
        
        .tree-node-children.collapsed {
            max-height: 0 !important;
            opacity: 0;
        }
        
        /* Responsive adjustments for tree view */
        @media (max-width: 1200px) {
            .tree-node-metrics {
                flex-direction: column;
                align-items: flex-start;
                gap: 4px;
            }
        }
        
        /* EnneadTab Logo - Lower Left with Parallax */
        .ennead-logo-container {
            position: fixed;
            left: 35px;
            bottom: 80px;
            z-index: 100;
            pointer-events: none;
            transform-origin: left center;
            transition: transform 0.3s ease-out;
        }
        
        .ennead-logo {
            height: 45px;
            width: auto;
            transform: rotate(-90deg);
            transform-origin: left center;
            opacity: 0.6;
            transition: opacity 0.3s ease;
        }
        
        .ennead-logo:hover {
            opacity: 1;
        }
        
        @media (max-width: 768px) {
            .ennead-logo-container {
                display: none;
            }
        }
        
        /* Zero-area clarifications */
        .zero-area-hint {
            color: #d1fae5;
        }
        .zero-area-badge {
            display: inline-block;
            margin-left: 6px;
            padding: 2px 6px;
            font-size: 0.75rem;
            color: #065f46;
            background: #a7f3d0;
            border-radius: 4px;
        }
        .zero-area-row .col-area {
            color: #fbbf24;
        }
        
        /* Geometry Viewer Styles */
        .geometry-viewer-section {
            margin: 48px 0;
            padding: 32px;
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 8px;
        }
        
        .geometry-viewer-section h2 {
            color: #ffffff;
            font-size: 1.75rem;
            margin-bottom: 24px;
            font-weight: 600;
        }
        
        .viewer-controls {
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            margin-bottom: 24px;
            padding: 20px;
            background: #1f2937;
            border-radius: 6px;
            align-items: center;
        }
        
        .control-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .control-group label {
            color: #9ca3af;
            font-size: 0.875rem;
            font-weight: 500;
        }
        
        .control-group select {
            padding: 8px 12px;
            background: #111827;
            color: #f8fafc;
            border: 1px solid #374151;
            border-radius: 4px;
            font-size: 0.875rem;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .control-group select:hover {
            border-color: #60a5fa;
        }
        
        .control-group select:focus {
            outline: none;
            border-color: #60a5fa;
            box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.1);
        }
        
        .control-group input[type="checkbox"] {
            width: 16px;
            height: 16px;
            cursor: pointer;
        }
        
        .control-group button {
            padding: 8px 16px;
            background: #374151;
            color: #f8fafc;
            border: none;
            border-radius: 4px;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .control-group button:hover {
            background: #4b5563;
        }
        
        .view-mode-btn {
            padding: 8px 16px;
            background: #374151;
            color: #9ca3af;
            border: 1px solid #4b5563;
            border-radius: 4px;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .view-mode-btn.active {
            background: #60a5fa;
            color: #ffffff;
            border-color: #60a5fa;
        }
        
        .view-mode-btn:hover:not(.active) {
            background: #4b5563;
            color: #f8fafc;
        }
        
        .viewer-container {
            position: relative;
            width: 100%;
            height: 600px;
            background: #0a0e13;
            border-radius: 6px;
            overflow: hidden;
            border: 1px solid #374151;
        }
        
        .geometry-canvas {
            width: 100%;
            height: 100%;
            display: block;
        }
        
        .area-info-popup {
            position: fixed;
            padding: 16px;
            background: rgba(17, 24, 39, 0.98);
            border: 2px solid #60a5fa;
            border-radius: 8px;
            color: #f8fafc;
            font-size: 0.875rem;
            pointer-events: auto;
            z-index: 99999;
            box-shadow: 0 8px 24px rgba(96, 165, 250, 0.3), 0 4px 12px rgba(0, 0, 0, 0.8);
            backdrop-filter: blur(12px);
            min-width: 250px;
            max-width: 400px;
        }
        
        .area-info-popup h4 {
            color: #60a5fa;
            font-size: 1rem;
            margin-bottom: 8px;
            font-weight: 600;
        }
        
        .area-info-popup p {
            margin: 4px 0;
            line-height: 1.5;
        }
        
        .area-info-popup strong {
            color: #9ca3af;
        }
        """
    
    def _get_javascript(self):
        """Get JavaScript for interactive features"""
        return """
        // Load Chart.js and Three.js from CDN
        const chartScript = document.createElement('script');
        chartScript.src = 'https://cdn.jsdelivr.net/npm/chart.js';
        chartScript.onload = function() {
            initializeChart();
        };
        document.head.appendChild(chartScript);
        
        // Load Three.js
        const threeScript = document.createElement('script');
        threeScript.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
        threeScript.onload = function() {
            console.log('Three.js loaded successfully');
            // Load OrbitControls after Three.js
            const controlsScript = document.createElement('script');
            controlsScript.src = 'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js';
            controlsScript.onload = function() {
                console.log('OrbitControls loaded successfully');
                // Initialize geometry viewers after Three.js and controls are loaded
                if (typeof initializeGeometryViewers === 'function') {
                    initializeGeometryViewers();
                } else {
                    console.log('initializeGeometryViewers not yet defined, will be called later');
                }
            };
            document.head.appendChild(controlsScript);
        };
        document.head.appendChild(threeScript);
        
        function initializeChart() {
            console.log('initializeChart called');
            // Wait for DOM to be ready
            if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
                    initializeComponents();
                });
            } else {
                initializeComponents();
            }
        }
        
        function initializeComponents() {
            console.log('Initializing components...');
            
            // Initialize context menu
            initializeContextMenu();
            
            // Table sorting disabled per user request
            // const table = document.querySelector('.comparison-table');
            // if (table) {
            //     console.log('Found comparison table, adding sorting...');
            //     const headers = table.querySelectorAll('th');
            //     headers.forEach((header, index) => {
            //         header.style.cursor = 'pointer';
            //         header.addEventListener('click', () => {
            //             sortTable(table, index);
            //         });
            //     });
            // } else {
            //     console.log('No comparison table found');
            // }
            
            // Initialize donut chart if canvas exists
            const ctx = document.getElementById('areaFulfillmentChart');
            if (ctx && typeof Chart !== 'undefined') {
                console.log('Creating donut chart...');
                createDonutChart(ctx);
            } else {
                console.log('Chart canvas or Chart.js not available');
            }
            
            // Initialize department charts
            initializeDepartmentCharts();
            
            // Initialize building section diagram
            console.log('Creating building section...');
            createBuildingSection();
        }
        
        function initializeDepartmentCharts() {
            console.log('Initializing department charts...');
            
            // Get chart data from script tag
            const chartDataElement = document.getElementById('departmentChartData');
            if (!chartDataElement) {
                console.log('No department chart data found');
                return;
            }
            
            const chartData = JSON.parse(chartDataElement.textContent);
            console.log('Department chart data:', chartData);
            
            // Create comparison chart
            const comparisonCanvas = document.getElementById('deptComparisonChart');
            if (comparisonCanvas) {
                createDepartmentComparisonChart(comparisonCanvas, chartData);
            }
            
            // Create percentage chart
            const percentageCanvas = document.getElementById('deptPercentageChart');
            if (percentageCanvas) {
                createDepartmentPercentageChart(percentageCanvas, chartData);
            }
        }
        
        function createDepartmentComparisonChart(canvas, data) {
            console.log('Creating department comparison chart...');
            
            canvas.chartInstance = new Chart(canvas, {
                type: 'bar',
                data: {
                    labels: data.departments,
                    datasets: [
                        {
                            label: 'Target DGSF',
                            data: data.target_dgsf,
                            backgroundColor: data.colors.map(c => c + '40'),
                            borderColor: data.colors,
                            borderWidth: 2,
                            borderRadius: 6,
                            borderSkipped: false
                        },
                        {
                            label: 'Actual DGSF',
                            data: data.actual_dgsf,
                            backgroundColor: data.colors.map(c => c + '80'),
                            borderColor: data.colors,
                            borderWidth: 2,
                            borderRadius: 6,
                            borderSkipped: false
                        }
                    ]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top',
                            labels: {
                                color: '#e5e7eb',
                                font: {
                                    family: "'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                                    size: 14
                                },
                                padding: 16,
                                usePointStyle: true
                            }
                        },
                        tooltip: {
                            backgroundColor: '#1f2937',
                            titleColor: '#f9fafb',
                            bodyColor: '#e5e7eb',
                            borderColor: '#374151',
                            borderWidth: 1,
                            padding: 12,
                            displayColors: true,
                            callbacks: {
                                label: function(context) {
                                    const label = context.dataset.label || '';
                                    const value = context.parsed.x;
                                    return label + ': ' + value.toLocaleString() + ' SF';
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            stacked: false,
                            grid: {
                                color: '#374151',
                                drawBorder: false
                            },
                            ticks: {
                                color: '#9ca3af',
                                font: {
                                    family: "'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                                    size: 11
                                },
                                callback: function(value) {
                                    return value.toLocaleString();
                                }
                            },
                            title: {
                                display: true,
                                text: 'Square Feet (SF)',
                                color: '#9ca3af',
                                font: {
                                    family: "'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                                    size: 12,
                                    weight: '500'
                                }
                            }
                        },
                        y: {
                            grid: {
                                display: false
                            },
                            ticks: {
                                color: '#e5e7eb',
                                font: {
                                    family: "'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                                    size: 14,
                                    weight: '400'
                                }
                            }
                        }
                    },
                    animation: {
                        duration: 1500,
                        easing: 'easeInOutQuart'
                    }
                }
            });
        }
        
        function createDepartmentPercentageChart(canvas, data) {
            console.log('Creating department percentage chart...');
            
            // Color code based on percentage
            const barColors = data.percentages.map(pct => {
                if (Math.abs(pct) <= 5) return '#10b981'; // Green - on target
                if (pct > 5) return '#f59e0b'; // Orange - over
                return '#ef4444'; // Red - under
            });
            
            canvas.chartInstance = new Chart(canvas, {
                type: 'bar',
                data: {
                    labels: data.departments,
                    datasets: [{
                        label: 'Fulfillment %',
                        data: data.percentages,
                        backgroundColor: barColors.map(c => c + '80'),
                        borderColor: barColors,
                        borderWidth: 2,
                        borderRadius: 6,
                        borderSkipped: false
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            backgroundColor: '#1f2937',
                            titleColor: '#f9fafb',
                            bodyColor: '#e5e7eb',
                            borderColor: '#374151',
                            borderWidth: 1,
                            padding: 12,
                            callbacks: {
                                label: function(context) {
                                    const value = context.parsed.x;
                                    const status = Math.abs(value) <= 5 ? 'On Target' : 
                                                   value > 5 ? 'Over' : 'Under';
                                    return status + ': ' + (value > 0 ? '+' : '') + value.toFixed(1) + '%';
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                color: '#374151',
                                drawBorder: false
                            },
                            ticks: {
                                color: '#9ca3af',
                                font: {
                                    family: "'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                                    size: 11
                                },
                                callback: function(value) {
                                    return (value > 0 ? '+' : '') + value + '%';
                                }
                            },
                            title: {
                                display: true,
                                text: 'Percentage Difference',
                                color: '#9ca3af',
                                font: {
                                    family: "'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                                    size: 12,
                                    weight: '500'
                                }
                            }
                        },
                        y: {
                            grid: {
                                display: false
                            },
                            ticks: {
                                color: '#e5e7eb',
                                font: {
                                    family: "'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                                    size: 14,
                                    weight: '400'
                                }
                            }
                        }
                    },
                    animation: {
                        duration: 1500,
                        easing: 'easeInOutQuart'
                    }
                }
            });
        }
        
        // Fuzzy Search Functions
        function levenshteinDistance(str1, str2) {
            var s1 = str1.toLowerCase();
            var s2 = str2.toLowerCase();
            var len1 = s1.length;
            var len2 = s2.length;
            
            var matrix = [];
            for (var i = 0; i <= len1; i++) {
                matrix[i] = [i];
            }
            for (var j = 0; j <= len2; j++) {
                matrix[0][j] = j;
            }
            
            for (var i = 1; i <= len1; i++) {
                for (var j = 1; j <= len2; j++) {
                    var cost = s1[i - 1] === s2[j - 1] ? 0 : 1;
                    matrix[i][j] = Math.min(
                        matrix[i - 1][j] + 1,
                        matrix[i][j - 1] + 1,
                        matrix[i - 1][j - 1] + cost
                    );
                }
            }
            
            return matrix[len1][len2];
        }
        
        function fuzzyMatch(query, target) {
            if (!query || !target) return 0;
            
            var q = query.toLowerCase();
            var t = target.toLowerCase();
            
            // Exact match gets highest score
            if (t === q) return 1.0;
            
            // Starts with query
            if (t.indexOf(q) === 0) return 0.9;
            
            // Contains query
            if (t.indexOf(q) !== -1) return 0.7;
            
            // Use Levenshtein distance for fuzzy matching
            var distance = levenshteinDistance(q, t);
            var maxLen = Math.max(q.length, t.length);
            
            if (distance <= 2 && maxLen > 3) {
                // Allow 1-2 character difference for typos
                return 0.6 - (distance * 0.1);
            }
            
            // Similarity score based on Levenshtein
            var similarity = 1 - (distance / maxLen);
            
            if (similarity > 0.5) {
                return similarity * 0.5; // Scale down partial matches
            }
            
            return 0;
        }
        
        function performSearch(query) {
            if (!query || query.trim().length < 2) {
                console.log('Search query too short:', query);
                return [];
            }
            
            console.log('Performing search for:', query);
            var results = [];
            var allNodes = document.querySelectorAll('[data-search-dept], [data-search-division], [data-search-function]');
            console.log('Found', allNodes.length, 'searchable nodes');
            
            allNodes.forEach(function(node) {
                var dept = node.getAttribute('data-search-dept') || '';
                var division = node.getAttribute('data-search-division') || '';
                var func = node.getAttribute('data-search-function') || '';
                
                // Skip nodes without any searchable content
                if (!dept && !division && !func) return;
                
                // Calculate fuzzy match scores for each field
                var deptScore = fuzzyMatch(query, dept);
                var divScore = fuzzyMatch(query, division);
                var funcScore = fuzzyMatch(query, func);
                
                // Overall score is the maximum of the three
                var maxScore = Math.max(deptScore, divScore, funcScore);
                
                if (maxScore > 0.3) {
                    results.push({
                        node: node,
                        department: dept,
                        division: division,
                        function: func,
                        score: maxScore,
                        matchedField: deptScore >= divScore && deptScore >= funcScore ? 'dept' : 
                                      divScore >= funcScore ? 'division' : 'function'
                    });
                }
            });
            
            // Sort by score descending
            results.sort(function(a, b) {
                return b.score - a.score;
            });
            
            console.log('Search found', results.length, 'results');
            
            // Return top 10 results
            return results.slice(0, 10);
        }
        
        function highlightMatch(text, query) {
            if (!query || !text) return text;
            
            var lowerText = text.toLowerCase();
            var lowerQuery = query.toLowerCase();
            var index = lowerText.indexOf(lowerQuery);
            
            if (index !== -1) {
                var before = text.substring(0, index);
                var match = text.substring(index, index + query.length);
                var after = text.substring(index + query.length);
                return before + '<span class="suggestion-match">' + match + '</span>' + after;
            }
            
            return text;
        }
        
        function displaySearchSuggestions(results, query) {
            console.log('displaySearchSuggestions called with', results.length, 'results');
            var suggestionsDiv = document.getElementById('searchSuggestions');
            
            if (!suggestionsDiv) {
                console.error('searchSuggestions div not found!');
                return;
            }
            
            if (!results || results.length === 0) {
                console.log('No results, showing no matches message');
                suggestionsDiv.innerHTML = '<div class="no-results">No matches found</div>';
                suggestionsDiv.classList.add('active');
                return;
            }
            
            var html = '';
            
            // Add "Do you mean..." header if there are results
            if (results.length > 0) {
                html += '<div class="suggestion-header">Do you mean...</div>';
            }
            
            results.forEach(function(result, index) {
                var dept = highlightMatch(result.department, query);
                var div = highlightMatch(result.division, query);
                var func = highlightMatch(result.function, query);
                
                var path = dept + ' | ' + div + ' | ' + func;
                
                html += '<div class="suggestion-item" data-index="' + index + '" onclick="selectSuggestion(' + index + ')">';
                html += '<div class="suggestion-path">' + path + '</div>';
                html += '</div>';
            });
            
            suggestionsDiv.innerHTML = html;
            suggestionsDiv.classList.add('active');
            
            console.log('Suggestions HTML set, classList:', suggestionsDiv.classList);
            console.log('Suggestions display style:', window.getComputedStyle(suggestionsDiv).display);
            console.log('Suggestions position:', window.getComputedStyle(suggestionsDiv).position);
            console.log('Suggestions innerHTML length:', suggestionsDiv.innerHTML.length);
            
            // Store results globally for selection
            window.currentSearchResults = results;
        }
        
        function clearSearchSuggestions() {
            var suggestionsDiv = document.getElementById('searchSuggestions');
            suggestionsDiv.classList.remove('active');
            suggestionsDiv.innerHTML = '';
            window.currentSearchResults = [];
        }
        
        function selectSuggestion(index) {
            if (!window.currentSearchResults || !window.currentSearchResults[index]) {
                return;
            }
            
            var result = window.currentSearchResults[index];
            navigateToNode(result.node);
            
            // Clear search
            var searchInput = document.getElementById('searchInput');
            searchInput.value = '';
            clearSearchSuggestions();
            
            // Hide context menu
            var contextMenu = document.getElementById('contextMenu');
            contextMenu.classList.remove('active');
            contextMenu.style.display = 'none';
        }
        
        function navigateToNode(nodeElement) {
            if (!nodeElement) return;
            
            // Expand all parent nodes
            var parent = nodeElement.parentElement;
            while (parent) {
                if (parent.classList && parent.classList.contains('tree-node-children')) {
                    // This is a children container, expand it
                    parent.classList.remove('collapsed');
                    parent.style.maxHeight = 'none';
                    
                    // Find and update the toggle icon
                    var parentNode = parent.previousElementSibling;
                    if (parentNode) {
                        var icon = parentNode.querySelector('.tree-toggle-icon');
                        if (icon) {
                            icon.textContent = '▼';
                            icon.classList.remove('collapsed');
                        }
                    }
                }
                parent = parent.parentElement;
            }
            
            // Update all parent heights
            setTimeout(function() {
                var allExpanded = document.querySelectorAll('.tree-node-children:not(.collapsed)');
                allExpanded.forEach(function(child) {
                    child.style.maxHeight = 'none';
                    var height = child.scrollHeight;
                    child.style.maxHeight = height + 'px';
                });
            }, 50);
            
            // Scroll to the node
            setTimeout(function() {
                nodeElement.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
                
                // Add highlight effect
                nodeElement.classList.add('highlighted');
                setTimeout(function() {
                    nodeElement.classList.remove('highlighted');
                }, 3000);
            }, 200);
        }
        
        // Context Menu Functions
        function initializeContextMenu() {
            const contextMenu = document.getElementById('contextMenu');
            
            if (!contextMenu) {
                console.error('Context menu element not found');
                return;
            }
            
            // Show context menu on right-click anywhere on the page
            document.addEventListener('contextmenu', function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                // Get mouse position
                var mouseX = e.clientX;
                var mouseY = e.clientY;
                
                // Show menu first to get its dimensions
                contextMenu.style.display = 'block';
                contextMenu.classList.add('active');
                
                var menuWidth = contextMenu.offsetWidth;
                var menuHeight = contextMenu.offsetHeight;
                var windowWidth = window.innerWidth;
                var windowHeight = window.innerHeight;
                
                // Calculate position - ensure menu stays within viewport
                var left = mouseX;
                var top = mouseY;
                
                // Adjust if menu would go off right edge
                if (mouseX + menuWidth > windowWidth) {
                    left = windowWidth - menuWidth - 10;
                }
                
                // Adjust if menu would go off bottom edge
                if (mouseY + menuHeight > windowHeight) {
                    top = windowHeight - menuHeight - 10;
                }
                
                // Ensure menu doesn't go off left or top edge
                if (left < 10) left = 10;
                if (top < 10) top = 10;
                
                // Position the context menu
                contextMenu.style.left = left + 'px';
                contextMenu.style.top = top + 'px';
                
                console.log('Context menu shown at:', left, top);
            });
            
            // Hide context menu on regular click
            document.addEventListener('click', function(e) {
                if (!e.target.closest('.context-menu')) {
                    contextMenu.classList.remove('active');
                    contextMenu.style.display = 'none';
                    clearSearchSuggestions();
                    var searchInput = document.getElementById('searchInput');
                    if (searchInput) searchInput.value = '';
                }
            });
            
            // Hide context menu on scroll
            document.addEventListener('scroll', function() {
                contextMenu.classList.remove('active');
                contextMenu.style.display = 'none';
                clearSearchSuggestions();
            });
            
            // Hide context menu on escape key
            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') {
                    contextMenu.classList.remove('active');
                    contextMenu.style.display = 'none';
                    clearSearchSuggestions();
                    var searchInput = document.getElementById('searchInput');
                    if (searchInput) searchInput.value = '';
                }
            });
            
            // Search input event handlers
            console.log('Setting up search handlers...');
            var searchInput = document.getElementById('searchInput');
            var searchSuggestions = document.getElementById('searchSuggestions');
            console.log('searchInput element:', searchInput);
            console.log('searchSuggestions element:', searchSuggestions);
            
            if (searchInput) {
                console.log('Attaching search event listeners...');
                // Prevent context menu from closing when clicking in search area
                searchInput.addEventListener('click', function(e) {
                    e.stopPropagation();
                });
                
                searchSuggestions.addEventListener('click', function(e) {
                    e.stopPropagation();
                });
                
                // Real-time search as user types
                searchInput.addEventListener('input', function(e) {
                    var query = e.target.value;
                    console.log('Search input changed:', query);
                    
                    if (!query || query.trim().length < 2) {
                        clearSearchSuggestions();
                        return;
                    }
                    
                    var results = performSearch(query);
                    displaySearchSuggestions(results, query);
                });
                
                // Keyboard navigation
                searchInput.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        // Select first suggestion
                        if (window.currentSearchResults && window.currentSearchResults.length > 0) {
                            selectSuggestion(0);
                        }
                    } else if (e.key === 'Escape') {
                        e.preventDefault();
                        searchInput.value = '';
                        clearSearchSuggestions();
                    }
                });
                
                // Focus search input when context menu opens
                var observer = new MutationObserver(function(mutations) {
                    mutations.forEach(function(mutation) {
                        if (mutation.attributeName === 'class') {
                            if (contextMenu.classList.contains('active')) {
                                setTimeout(function() {
                                    searchInput.focus();
                                }, 100);
                            } else {
                                searchInput.value = '';
                                clearSearchSuggestions();
                            }
                        }
                    });
                });
                
                observer.observe(contextMenu, {
                    attributes: true,
                    attributeFilter: ['class']
                });
                
                console.log('Search event listeners attached successfully!');
            } else {
                console.error('searchInput element not found! Cannot attach search listeners.');
            }
            
            console.log('Context menu initialized');
        }
        
        function initialize3DComponents() {
            console.log('Initializing 3D components...');
            const canvas = document.getElementById('viewer3d-canvas');
            if (canvas && typeof THREE !== 'undefined') {
                console.log('Creating 3D viewer...');
                create3DViewer(canvas);
            } else {
                console.log('3D canvas or Three.js not available');
            }
        }
        
        function createDonutChart(canvas) {
            console.log('Creating donut chart...');
            
            // Calculate data from the table rows
            let fulfilledArea = 0;
            let totalRequiredArea = 0;
            let mismatchedArea = 0;
            let missingArea = 0;
            
            // Extract data from table rows
            const tableRows = document.querySelectorAll('.comparison-table tbody tr');
            console.log('Found table rows for chart:', tableRows.length);
            
            if (tableRows.length === 0) {
                console.log('No table rows found, using demo data');
                // Use demo data
                fulfilledArea = 750000;
                totalRequiredArea = 1000000;
                mismatchedArea = 150000;
                missingArea = 100000;
            } else {
            tableRows.forEach(row => {
                const cells = row.cells;
                if (cells.length >= 8) {
                    const requiredArea = parseFloat(cells[5].textContent.replace(/[^0-9.-]/g, '')) || 0;
                    const actualArea = parseFloat(cells[7].textContent.replace(/[^0-9.-]/g, '')) || 0;
                    const status = cells[12].textContent.trim();
                    
                    totalRequiredArea += requiredArea;
                    
                    if (status.includes('Fulfilled')) {
                        fulfilledArea += actualArea;
                    } else if (status.includes('Partial') || status.includes('Excessive')) {
                        mismatchedArea += actualArea;
                    } else if (status.includes('Missing')) {
                        missingArea += requiredArea; // Missing areas count as required area
                    }
                }
            });
            }
            
            // Calculate percentages
            const totalArea = Math.max(totalRequiredArea, fulfilledArea + mismatchedArea);
            const fulfilledPercentage = totalArea > 0 ? (fulfilledArea / totalArea * 100) : 0;
            const mismatchedPercentage = totalArea > 0 ? (mismatchedArea / totalArea * 100) : 0;
            const missingPercentage = totalArea > 0 ? (missingArea / totalArea * 100) : 0;
            
            new Chart(canvas, {
                type: 'doughnut',
                data: {
                    labels: ['Fulfilled Areas', 'Mismatched Areas', 'Missing Areas'],
                    datasets: [{
                        data: [fulfilledPercentage, mismatchedPercentage, missingPercentage],
                        backgroundColor: [
                            '#10b981',  // Green for fulfilled
                            '#f59e0b',  // Orange for mismatched  
                            '#ef4444'   // Red for missing
                        ],
                        borderColor: [
                            '#059669',
                            '#d97706',
                            '#dc2626'
                        ],
                        borderWidth: 2,
                        hoverOffset: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: {
                                color: '#e5e7eb',
                                font: {
                                    family: "'Roboto', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                                    size: 14
                                },
                                padding: 20,
                                usePointStyle: true
                            }
                        },
                        tooltip: {
                            backgroundColor: '#1f2937',
                            titleColor: '#f9fafb',
                            bodyColor: '#e5e7eb',
                            borderColor: '#374151',
                            borderWidth: 1,
                            callbacks: {
                                label: function(context) {
                                    const label = context.label || '';
                                    const value = context.parsed;
                                    return label + ': ' + value.toFixed(1) + '%';
                                }
                            }
                        }
                    },
                    cutout: '60%',
                    animation: {
                        animateRotate: true,
                        animateScale: true,
                        duration: 2000,
                        easing: 'easeOutQuart'
                    }
                }
            });
        }
        
        function createBuildingSection() {
            const buildingSection = document.getElementById('buildingSection');
            const sectionLegend = document.getElementById('sectionLegend');
            
            if (!buildingSection) {
                console.log('Building section element not found');
                return;
            }
            
            console.log('Creating building section diagram...');
            
            // Debug: Check if table exists
            const table = document.querySelector('.comparison-table');
            if (!table) {
                console.log('Comparison table not found, showing demo content');
                showDemoBuildingSection(buildingSection, sectionLegend);
                return;
            }
            
            // Extract level and department data from table
            const levelData = {};
            const departmentColors = {
                'EMERGENCY': 'dept-emergency',
                'INPATIENT CARE': 'dept-inpatient',
                'DIAGNOSTIC AND TREATMENT': 'dept-diagnostic',
                'MECHANICAL': 'dept-mechanical',
                'ADMINISTRATION AND STAFF SUPPORT': 'dept-administration'
            };
            
            const tableRows = document.querySelectorAll('.comparison-table tbody tr');
            console.log('Found table rows:', tableRows.length);
            
            if (tableRows.length === 0) {
                buildingSection.innerHTML = '<p style="color: #9ca3af; text-align: center; padding: 40px;">No data rows found in comparison table.</p>';
                return;
            }
            
            tableRows.forEach((row, rowIndex) => {
                const cells = row.cells;
                console.log(`Row ${rowIndex}: ${cells.length} cells`);
                
                if (cells.length >= 8) {
                    const department = cells[0].textContent.trim(); // Department column
                    const levelText = cells[5].textContent.trim(); // Level column (moved to position 5)
                    const actualArea = parseFloat(cells[7].textContent.replace(/[^0-9.-]/g, '')) || 0; // Actual Area column
                    
                    console.log(`Row ${rowIndex}: Dept=${department}, Level=${levelText}, Area=${actualArea}`);
                    
                    // Extract level name and elevation from level text
                    const levelMatch = levelText.match(/(Level \d+)/);
                    if (levelMatch) {
                        const levelName = levelMatch[1];
                        
                        if (!levelData[levelName]) {
                            levelData[levelName] = {};
                        }
                        
                        if (!levelData[levelName][department]) {
                            levelData[levelName][department] = 0;
                        }
                        
                        levelData[levelName][department] += actualArea;
                    }
                }
            });
            
            console.log('Extracted level data:', levelData);
            
            // Sort levels by elevation (assuming Level 1, Level 2, etc.)
            const sortedLevels = Object.keys(levelData).sort((a, b) => {
                const aNum = parseInt(a.match(/\d+/)[0]);
                const bNum = parseInt(b.match(/\d+/)[0]);
                return aNum - bNum;
            });
            
            console.log('Sorted levels:', sortedLevels);
            
            // Generate level stacks
            let sectionHTML = '';
            let legendHTML = '';
            const usedDepartments = new Set();
            
            if (sortedLevels.length === 0) {
                buildingSection.innerHTML = '<p style="color: #9ca3af; text-align: center; padding: 40px;">No level data found. Please check that areas have level information.</p>';
                return;
            }
            
            sortedLevels.forEach((levelName, index) => {
                const departments = levelData[levelName];
                const levelNum = levelName.match(/\d+/)[0];
                const elevation = (parseInt(levelNum) * 10).toFixed(1); // Approximate elevation
                
                let pillsHTML = '';
                Object.entries(departments).forEach(([dept, area]) => {
                    if (area > 0) {
                        const deptClass = departmentColors[dept.toUpperCase()] || 'dept-other';
                        const areaSF = Math.round(area).toLocaleString();
                        pillsHTML += `<div class="department-pill ${deptClass}" data-area="${areaSF} SF">${dept}</div>`;
                        usedDepartments.add(dept);
                    }
                });
                
                if (pillsHTML) {
                    sectionHTML += `
                        <div class="level-stack">
                            <div class="level-label">${levelName}</div>
                            <div class="level-elevation">${elevation}'</div>
                            <div class="department-pills">${pillsHTML}</div>
                            ${index < sortedLevels.length - 1 ? '<div class="level-connector"></div>' : ''}
                        </div>
                    `;
                }
            });
            
            // Generate legend
            usedDepartments.forEach(dept => {
                const deptClass = departmentColors[dept.toUpperCase()] || 'dept-other';
                legendHTML += `
                    <div class="legend-item">
                        <div class="legend-color ${deptClass}"></div>
                        <span>${dept}</span>
                    </div>
                `;
            });
            
            if (sectionHTML === '') {
                // Fallback: Create a simple demo diagram
                sectionHTML = `
                    <div class="level-stack">
                        <div class="level-label">Level 1</div>
                        <div class="level-elevation">10.0'</div>
                        <div class="department-pills">
                            <div class="department-pill dept-emergency" data-area="2,500 SF">Emergency</div>
                            <div class="department-pill dept-administration" data-area="1,200 SF">Administration</div>
                        </div>
                    </div>
                    <div class="level-connector"></div>
                    <div class="level-stack">
                        <div class="level-label">Level 2</div>
                        <div class="level-elevation">20.0'</div>
                        <div class="department-pills">
                            <div class="department-pill dept-inpatient" data-area="15,000 SF">Inpatient Care</div>
                            <div class="department-pill dept-diagnostic" data-area="8,500 SF">Diagnostic & Treatment</div>
                        </div>
                    </div>
                    <div class="level-connector"></div>
                    <div class="level-stack">
                        <div class="level-label">Level 3</div>
                        <div class="level-elevation">30.0'</div>
                        <div class="department-pills">
                            <div class="department-pill dept-mechanical" data-area="3,200 SF">Mechanical</div>
                        </div>
                    </div>
                `;
                legendHTML = `
                    <div class="legend-item">
                        <div class="legend-color dept-emergency"></div>
                        <span>Emergency</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color dept-administration"></div>
                        <span>Administration</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color dept-inpatient"></div>
                        <span>Inpatient Care</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color dept-diagnostic"></div>
                        <span>Diagnostic & Treatment</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color dept-mechanical"></div>
                        <span>Mechanical</span>
                    </div>
                `;
            }
            
            buildingSection.innerHTML = sectionHTML;
            sectionLegend.innerHTML = legendHTML;
        }
        
        function showDemoBuildingSection(buildingSection, sectionLegend) {
            console.log('Showing demo building section');
            const demoHTML = `
                <div class="level-stack">
                    <div class="level-label">Level 1</div>
                    <div class="level-elevation">10.0'</div>
                    <div class="department-pills">
                        <div class="department-pill dept-emergency" data-area="2,500 SF">Emergency</div>
                        <div class="department-pill dept-administration" data-area="1,200 SF">Administration</div>
                    </div>
                </div>
                <div class="level-connector"></div>
                <div class="level-stack">
                    <div class="level-label">Level 2</div>
                    <div class="level-elevation">20.0'</div>
                    <div class="department-pills">
                        <div class="department-pill dept-inpatient" data-area="15,000 SF">Inpatient Care</div>
                        <div class="department-pill dept-diagnostic" data-area="8,500 SF">Diagnostic & Treatment</div>
                    </div>
                </div>
                <div class="level-connector"></div>
                <div class="level-stack">
                    <div class="level-label">Level 3</div>
                    <div class="level-elevation">30.0'</div>
                    <div class="department-pills">
                        <div class="department-pill dept-mechanical" data-area="3,200 SF">Mechanical</div>
                    </div>
                </div>
            `;
            
            const demoLegend = `
                <div class="legend-item">
                    <div class="legend-color dept-emergency"></div>
                    <span>Emergency</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color dept-administration"></div>
                    <span>Administration</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color dept-inpatient"></div>
                    <span>Inpatient Care</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color dept-diagnostic"></div>
                    <span>Diagnostic & Treatment</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color dept-mechanical"></div>
                    <span>Mechanical</span>
                </div>
            `;
            
            buildingSection.innerHTML = demoHTML;
            sectionLegend.innerHTML = demoLegend;
        }
        
        function create3DViewer(canvas) {
            console.log('Initializing 3D viewer...');
            
            if (typeof THREE === 'undefined') {
                console.error('Three.js not loaded');
                canvas.parentElement.innerHTML = '<p style="color: #ef4444; text-align: center; padding: 40px;">Three.js library failed to load. Please refresh the page.</p>';
                return;
            }
            
            // Scene setup
            const scene = new THREE.Scene();
            scene.background = new THREE.Color(0x0f172a);
            
            // Camera setup
            const camera = new THREE.PerspectiveCamera(75, canvas.clientWidth / canvas.clientHeight, 0.1, 1000);
            camera.position.set(50, 50, 50);
            
            // Renderer setup
            const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
            renderer.setSize(canvas.clientWidth, canvas.clientHeight);
            renderer.shadowMap.enabled = true;
            renderer.shadowMap.type = THREE.PCFSoftShadowMap;
            
            // Controls
            const controls = new THREE.OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true;
            controls.dampingFactor = 0.05;
            controls.enableZoom = true;
            controls.enablePan = true;
            
            // Lighting
            const ambientLight = new THREE.AmbientLight(0x404040, 0.6);
            scene.add(ambientLight);
            
            const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
            directionalLight.position.set(50, 100, 50);
            directionalLight.castShadow = true;
            directionalLight.shadow.mapSize.width = 2048;
            directionalLight.shadow.mapSize.height = 2048;
            scene.add(directionalLight);
            
            // Extract data from table
            const buildingData = extractBuildingData();
            
            // Create building geometry
            createBuildingGeometry(scene, buildingData);
            
            // Setup controls
            setup3DControls(controls, scene, camera, renderer);
            
            // Animation loop
            function animate() {
                requestAnimationFrame(animate);
                controls.update();
                renderer.render(scene, camera);
            }
            animate();
            
            // Handle window resize
            window.addEventListener('resize', function() {
                const width = canvas.clientWidth;
                const height = canvas.clientHeight;
                camera.aspect = width / height;
                camera.updateProjectionMatrix();
                renderer.setSize(width, height);
            });
        }
        
        function extractBuildingData() {
            console.log('Extracting building data for 3D viewer...');
            const levelData = {};
            const tableRows = document.querySelectorAll('.comparison-table tbody tr');
            
            console.log('Found table rows for 3D:', tableRows.length);
            
            if (tableRows.length === 0) {
                console.log('No table rows found, creating demo data');
                // Create demo data for 3D viewer
                return {
                    'Level 1': {
                        level: 1,
                        elevation: 10,
                        departments: {
                            'Emergency': { requiredArea: 2500, actualArea: 2500, status: 'Fulfilled' },
                            'Administration': { requiredArea: 1200, actualArea: 1200, status: 'Fulfilled' }
                        }
                    },
                    'Level 2': {
                        level: 2,
                        elevation: 20,
                        departments: {
                            'Inpatient Care': { requiredArea: 15000, actualArea: 18000, status: 'Excessive' },
                            'Diagnostic & Treatment': { requiredArea: 8500, actualArea: 7500, status: 'Partial' }
                        }
                    },
                    'Level 3': {
                        level: 3,
                        elevation: 30,
                        departments: {
                            'Mechanical': { requiredArea: 3200, actualArea: 3200, status: 'Fulfilled' }
                        }
                    }
                };
            }
            
            tableRows.forEach(row => {
                const cells = row.cells;
                if (cells.length >= 8) {
                    const department = cells[0].textContent.trim();
                    const levelText = cells[5].textContent.trim();
                    const requiredArea = parseFloat(cells[4].textContent.replace(/[^0-9.-]/g, '')) || 0;
                    const actualArea = parseFloat(cells[7].textContent.replace(/[^0-9.-]/g, '')) || 0;
                    const status = cells[12].textContent.trim();
                    
                    const levelMatch = levelText.match(/(Level \d+)/);
                    if (levelMatch) {
                        const levelName = levelMatch[1];
                        const levelNum = parseInt(levelName.match(/\d+/)[0]);
                        
                        if (!levelData[levelName]) {
                            levelData[levelName] = {
                                level: levelNum,
                                elevation: levelNum * 10,
                                departments: {}
                            };
                        }
                        
                        if (!levelData[levelName].departments[department]) {
                            levelData[levelName].departments[department] = {
                                requiredArea: 0,
                                actualArea: 0,
                                status: status
                            };
                        }
                        
                        levelData[levelName].departments[department].requiredArea += requiredArea;
                        levelData[levelName].departments[department].actualArea += actualArea;
                    }
                }
            });
            
            console.log('Extracted 3D building data:', levelData);
            return levelData;
        }
        
        function createBuildingGeometry(scene, buildingData) {
            const levels = Object.keys(buildingData).sort((a, b) => {
                return buildingData[a].level - buildingData[b].level;
            });
            
            levels.forEach((levelName, levelIndex) => {
                const levelInfo = buildingData[levelName];
                const elevation = levelInfo.elevation;
                
                // Create floor plane
                const floorGeometry = new THREE.PlaneGeometry(100, 100);
                const floorMaterial = new THREE.MeshLambertMaterial({ 
                    color: 0x374151,
                    transparent: true,
                    opacity: 0.3
                });
                const floor = new THREE.Mesh(floorGeometry, floorMaterial);
                floor.rotation.x = -Math.PI / 2;
                floor.position.y = elevation;
                scene.add(floor);
                
                // Create department zones
                const departments = Object.keys(levelInfo.departments);
                departments.forEach((dept, deptIndex) => {
                    const deptData = levelInfo.departments[dept];
                    const compliance = calculateCompliance(deptData.actualArea, deptData.requiredArea);
                    const color = getComplianceColor(compliance);
                    
                    // Create department box
                    const boxGeometry = new THREE.BoxGeometry(20, 5, 20);
                    const boxMaterial = new THREE.MeshLambertMaterial({ 
                        color: color,
                        transparent: true,
                        opacity: 0.8
                    });
                    const box = new THREE.Mesh(boxGeometry, boxMaterial);
                    
                    // Position boxes in a grid
                    const x = (deptIndex % 5 - 2) * 22;
                    const z = Math.floor(deptIndex / 5) * 22 - 22;
                    box.position.set(x, elevation + 2.5, z);
                    
                    // Add department label
                    const textGeometry = new THREE.PlaneGeometry(18, 3);
                    const textMaterial = new THREE.MeshBasicMaterial({ 
                        color: 0xffffff,
                        transparent: true,
                        opacity: 0.9
                    });
                    const textMesh = new THREE.Mesh(textGeometry, textMaterial);
                    textMesh.position.set(x, elevation + 6, z);
                    scene.add(textMesh);
                    
                    // Store metadata
                    box.userData = {
                        department: dept,
                        level: levelName,
                        compliance: compliance,
                        requiredArea: deptData.requiredArea,
                        actualArea: deptData.actualArea
                    };
                    
                    scene.add(box);
                });
            });
        }
        
        function calculateCompliance(actual, required) {
            if (required === 0) return 0;
            return Math.min(actual / required, 1.5); // Cap at 150% for visualization
        }
        
        function getComplianceColor(compliance) {
            if (compliance >= 0.9) return 0x10b981; // Green - Excellent
            if (compliance >= 0.7) return 0x84cc16; // Light Green - Good
            if (compliance >= 0.5) return 0xeab308; // Yellow - Fair
            if (compliance >= 0.3) return 0xf97316; // Orange - Poor
            return 0xef4444; // Red - Critical
        }
        
        function setup3DControls(controls, scene, camera, renderer) {
            // Control button handlers
            const controlButtons = document.querySelectorAll('.control-btn');
            controlButtons.forEach(btn => {
                btn.addEventListener('click', function() {
                    // Remove active class from all buttons
                    controlButtons.forEach(b => b.classList.remove('active'));
                    // Add active class to clicked button
                    this.classList.add('active');
                    
                    const mode = this.dataset.mode;
                    switch(mode) {
                        case 'compliance':
                            updateHeatmapMode(scene, 'compliance');
                            break;
                        case 'departments':
                            updateHeatmapMode(scene, 'departments');
                            break;
                        case 'areas':
                            updateHeatmapMode(scene, 'areas');
                            break;
                        case 'reset':
                            resetCameraView(controls, camera);
                            break;
                    }
                });
            });
            
            // Click handler for object selection
            const raycaster = new THREE.Raycaster();
            const mouse = new THREE.Vector2();
            
            renderer.domElement.addEventListener('click', function(event) {
                const rect = renderer.domElement.getBoundingClientRect();
                mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
                mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
                
                raycaster.setFromCamera(mouse, camera);
                const intersects = raycaster.intersectObjects(scene.children, true);
                
                if (intersects.length > 0) {
                    const object = intersects[0].object;
                    if (object.userData && object.userData.department) {
                        showObjectInfo(object.userData);
                    }
                }
            });
        }
        
        function updateHeatmapMode(scene, mode) {
            // Update legend
            const legendItems = document.getElementById('viewer3d-legend');
            let legendHTML = '';
            
            if (mode === 'compliance') {
                legendHTML = `
                    <div class="legend-item">
                        <div class="legend-color heatmap-excellent"></div>
                        <span>Excellent (90%+)</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color heatmap-good"></div>
                        <span>Good (70-89%)</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color heatmap-fair"></div>
                        <span>Fair (50-69%)</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color heatmap-poor"></div>
                        <span>Poor (30-49%)</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color heatmap-critical"></div>
                        <span>Critical (<30%)</span>
                    </div>
                `;
            } else if (mode === 'departments') {
                // Department color legend would go here
                legendHTML = `<div class="legend-item"><span>Department View Mode</span></div>`;
            } else if (mode === 'areas') {
                legendHTML = `<div class="legend-item"><span>Area Density View Mode</span></div>`;
            }
            
            legendItems.innerHTML = legendHTML;
        }
        
        function resetCameraView(controls, camera) {
            camera.position.set(50, 50, 50);
            controls.target.set(0, 0, 0);
            controls.update();
        }
        
        function showObjectInfo(userData) {
            const infoPanel = document.querySelector('.info-panel');
            infoPanel.innerHTML = `
                <h4>${userData.department}</h4>
                <p><strong>Level:</strong> ${userData.level}</p>
                <p><strong>Required Area:</strong> ${userData.requiredArea.toLocaleString()} SF</p>
                <p><strong>Actual Area:</strong> ${userData.actualArea.toLocaleString()} SF</p>
                <p><strong>Compliance:</strong> ${(userData.compliance * 100).toFixed(1)}%</p>
            `;
        }
        
        // Toggle department collapse
        function toggleDepartment(deptId) {
            const deptRows = document.querySelectorAll('.dept-row[data-dept="' + deptId + '"]');
            const deptHeader = document.querySelector('.department-header[data-dept-id="' + deptId + '"]');
            const icon = document.getElementById('icon_' + deptId);
            
            deptRows.forEach(row => {
                row.classList.toggle('collapsed');
            });
            
            deptHeader.classList.toggle('collapsed');
        }
        
        // Collapse all departments
        function collapseAllDepartments() {
            const allDeptHeaders = document.querySelectorAll('.department-header');
            allDeptHeaders.forEach(header => {
                const deptId = header.getAttribute('data-dept-id');
                const deptRows = document.querySelectorAll('.dept-row[data-dept="' + deptId + '"]');
                
                // Collapse if not already collapsed
                if (!header.classList.contains('collapsed')) {
                    deptRows.forEach(row => row.classList.add('collapsed'));
                    header.classList.add('collapsed');
                }
            });
        }
        
        // Expand all departments
        function expandAllDepartments() {
            const allDeptHeaders = document.querySelectorAll('.department-header');
            allDeptHeaders.forEach(header => {
                const deptId = header.getAttribute('data-dept-id');
                const deptRows = document.querySelectorAll('.dept-row[data-dept="' + deptId + '"]');
                
                // Expand if collapsed
                if (header.classList.contains('collapsed')) {
                    deptRows.forEach(row => row.classList.remove('collapsed'));
                    header.classList.remove('collapsed');
                }
            });
        }
        
        // Unified functions to control TreeView
        function expandAllViews() {
            // Expand TreeView nodes
            expandAllTreeNodes();
            
            // Also expand department sections (for backward compatibility)
            expandAllDepartments();
            
            // Hide context menu
            var menu = document.getElementById('contextMenu');
            menu.classList.remove('active');
            menu.style.display = 'none';
        }
        
        function collapseAllViews() {
            // Collapse TreeView nodes
            collapseAllTreeNodes();
            
            // Also collapse department sections (for backward compatibility)
            collapseAllDepartments();
            
            // Hide context menu
            var menu = document.getElementById('contextMenu');
            menu.classList.remove('active');
            menu.style.display = 'none';
        }
        
        // Return to top of page
        function returnToTop() {
            console.log('Return to top clicked');
            
            // Try smooth scroll first, fallback to instant scroll
            try {
                window.scrollTo({
                    top: 0,
                    left: 0,
                    behavior: 'smooth'
                });
            } catch (e) {
                // Fallback for older browsers
                window.scrollTo(0, 0);
            }
            
            // Also scroll body and html elements (for compatibility)
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
            
            // Hide context menu
            var menu = document.getElementById('contextMenu');
            if (menu) {
                menu.classList.remove('active');
                menu.style.display = 'none';
            }
            
            console.log('Scrolled to top, current position:', window.scrollY);
        }
        
        function sortTable(table, columnIndex) {
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            
            rows.sort((a, b) => {
                const aValue = a.cells[columnIndex].textContent.trim();
                const bValue = b.cells[columnIndex].textContent.trim();
                
                const aNum = parseFloat(aValue.replace(/[^0-9.-]/g, ''));
                const bNum = parseFloat(bValue.replace(/[^0-9.-]/g, ''));
                
                if (!isNaN(aNum) && !isNaN(bNum)) {
                    return aNum - bNum;
                }
                
                return aValue.localeCompare(bValue);
            });
            
            rows.forEach(row => tbody.appendChild(row));
        }
        
        // ========== Minimap Navigation Functions ==========
        
        // Toggle minimap visibility
        function toggleMinimap() {
            const minimap = document.getElementById('minimapNav');
            if (minimap) {
                minimap.classList.toggle('hidden');
            }
        }
        
        // Scroll to a specific section
        function scrollToSection(sectionClass) {
            console.log('Scrolling to section:', sectionClass);
            
            // Try to find element by class first
            var section = document.querySelector('.' + sectionClass);
            
            // If not found by class, try by ID
            if (!section) {
                section = document.getElementById(sectionClass);
            }
            
            // If still not found, try finding header or section containing the class
            if (!section) {
                section = document.querySelector('[class*="' + sectionClass + '"]');
            }
            
            if (section) {
                console.log('Section found:', section, 'offsetTop:', section.offsetTop);
                var headerOffset = 80; // Offset for fixed elements
                var targetPosition = section.offsetTop - headerOffset;
                
                console.log('Scrolling smoothly to position:', targetPosition);
                
                // Use smooth scroll behavior
                try {
                    window.scrollTo({
                        top: targetPosition,
                        left: 0,
                        behavior: 'smooth'
                    });
                } catch (e) {
                    // Fallback for older browsers - instant scroll
                    console.log('Smooth scroll not supported, using fallback');
                    document.documentElement.scrollTop = targetPosition;
                    document.body.scrollTop = targetPosition;
                }
                
                // Update minimap state after animation completes
                setTimeout(function() {
                    updateMinimapActiveState();
                }, 800);
            } else {
                console.error('Section not found:', sectionClass);
            }
        }
        
        // Scroll to the geometry viewer of the currently active scheme
        function scrollToGeometryViewer() {
            console.log('Scrolling to geometry viewer');
            
            // Find the currently active scheme
            var activeSchemeNav = document.querySelector('.scheme-selector.active');
            if (activeSchemeNav) {
                var schemeName = activeSchemeNav.getAttribute('data-scheme');
                console.log('Active scheme:', schemeName);
                
                // Scroll to the geometry viewer section for this scheme
                var geometryViewerId = 'geometry-viewer-section-' + schemeName;
                scrollToSection(geometryViewerId);
            } else {
                console.warn('No active scheme found, scrolling to first geometry viewer');
                // Fallback: scroll to first geometry viewer section
                var firstViewer = document.querySelector('.geometry-viewer-section');
                if (firstViewer) {
                    firstViewer.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }
        }
        
        // Update active state of minimap items based on scroll position
        function updateMinimapActiveState() {
            var sections = [
                'report-header',
                'level-matrix-section',
                'department-summary-section',
                'tree-view-section',
                'unmatched-section',
                'summary-section',
                'status-summary'
            ];
            
            var scrollPosition = window.scrollY + 200; // Offset for detection
            var activeSection = null;
            
            // Find which section is currently in view
            for (var i = 0; i < sections.length; i++) {
                var sectionClass = sections[i];
                var section = document.querySelector('.' + sectionClass);
                
                if (!section) {
                    section = document.getElementById(sectionClass);
                }
                
                if (!section) {
                    section = document.querySelector('[class*="' + sectionClass + '"]');
                }
                
                if (section) {
                    var sectionTop = section.offsetTop;
                    var sectionBottom = sectionTop + section.offsetHeight;
                    
                    if (scrollPosition >= sectionTop && scrollPosition < sectionBottom) {
                        activeSection = sectionClass;
                        break;
                    }
                }
            }
            
            // Update active class on minimap items
            var minimapItems = document.querySelectorAll('.minimap-item');
            for (var j = 0; j < minimapItems.length; j++) {
                var item = minimapItems[j];
                var itemSection = item.getAttribute('data-section');
                if (itemSection === activeSection) {
                    item.classList.add('active');
                } else {
                    item.classList.remove('active');
                }
            }
        }
        
        // Initialize minimap functionality
        function initializeMinimap() {
            console.log('Initializing minimap navigation...');
            
            const minimap = document.getElementById('minimapNav');
            const minimapItems = document.querySelectorAll('.minimap-item');
            
            console.log('Minimap found:', minimap);
            console.log('Minimap items found:', minimapItems.length);
            
            // Update active state on scroll
            window.addEventListener('scroll', function() {
                updateMinimapActiveState();
            });
            
            // Set initial active state
            updateMinimapActiveState();
            
            console.log('Minimap navigation initialized successfully');
        }
        
        // Call minimap initialization after DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initializeMinimap);
        } else {
            initializeMinimap();
        }
        
        // ========== EnneadTab Logo Parallax Effect ==========
        
        function initializeLogoParallax() {
            const logo = document.getElementById('enneadLogo');
            if (!logo) {
                console.log('Logo element not found');
                return;
            }
            
            let lastScrollY = window.scrollY;
            let currentY = 0;
            let scrollVelocity = 0;
            const dampingFactor = 0.15; // How much the logo moves with scroll (lower = less movement)
            const returnSpeed = 0.08; // How fast it returns to original position (lower = slower)
            
            // Update on scroll - calculate scroll velocity
            window.addEventListener('scroll', function() {
                const currentScrollY = window.scrollY;
                scrollVelocity = (currentScrollY - lastScrollY) * dampingFactor;
                lastScrollY = currentScrollY;
            }, { passive: true });
            
            // Smooth animation loop
            function animateLogo() {
                // Apply scroll velocity to current position (creates lag effect)
                // Invert velocity so logo lags behind: when scrolling down, logo stays up
                currentY -= scrollVelocity;
                
                // Gradually reduce velocity
                scrollVelocity *= 0.85;
                
                // Pull logo back to original position (0)
                currentY += (0 - currentY) * returnSpeed;
                
                // Apply transform - move logo based on scroll lag
                logo.style.transform = 'translateY(' + currentY + 'px)';
                
                // Continue animation
                requestAnimationFrame(animateLogo);
            }
            
            // Start animation
            animateLogo();
            
            console.log('Logo parallax effect initialized');
        }
        
        // Initialize logo parallax after DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initializeLogoParallax);
        } else {
            initializeLogoParallax();
        }
        
        // Tree View Functions
        function updateParentHeights(element) {
            // Traverse up and update all parent .tree-node-children heights
            var parent = element.parentElement;
            while (parent) {
                if (parent.classList && parent.classList.contains('tree-node-children')) {
                    if (!parent.classList.contains('collapsed')) {
                        parent.style.maxHeight = parent.scrollHeight + 'px';
                    }
                }
                parent = parent.parentElement;
            }
        }
        
        function toggleTreeNode(nodeId) {
            const icon = document.getElementById('tree_icon_' + nodeId);
            const children = document.getElementById('tree_children_' + nodeId);
            
            if (!children) return;
            
            if (children.classList.contains('collapsed')) {
                // Expand
                children.classList.remove('collapsed');
                // Need to temporarily set to 'none' to get true scrollHeight
                var currentMaxHeight = children.style.maxHeight;
                children.style.maxHeight = 'none';
                var height = children.scrollHeight;
                children.style.maxHeight = currentMaxHeight;
                
                // Trigger reflow and set the height
                setTimeout(function() {
                    children.style.maxHeight = height + 'px';
                }, 0);
                
                if (icon) {
                    icon.classList.remove('collapsed');
                    icon.textContent = '▼';
                }
                
                // Update parent heights after a short delay
                setTimeout(function() {
                    updateParentHeights(children);
                }, 50);
            } else {
                // Collapse
                children.classList.add('collapsed');
                children.style.maxHeight = '0';
                if (icon) {
                    icon.classList.add('collapsed');
                    icon.textContent = '▶';
                }
                
                // Update parent heights
                setTimeout(function() {
                    updateParentHeights(children);
                }, 50);
            }
        }
        
        function expandAllTreeNodes() {
            const allChildren = document.querySelectorAll('.tree-node-children');
            const allIcons = document.querySelectorAll('.tree-toggle-icon');
            
            // First, remove collapsed class from all
            allChildren.forEach(function(child) {
                child.classList.remove('collapsed');
            });
            
            // Set all icons
            allIcons.forEach(function(icon) {
                icon.classList.remove('collapsed');
                icon.textContent = '▼';
            });
            
            // Set all to maxHeight none to allow natural expansion
            allChildren.forEach(function(child) {
                child.style.maxHeight = 'none';
            });
            
            // Force reflow
            void document.body.offsetHeight;
            
            // Now set the calculated heights from deepest to shallowest
            setTimeout(function() {
                var childrenArray = Array.prototype.slice.call(allChildren);
                
                // Find depth of each element
                var childrenWithDepth = childrenArray.map(function(child) {
                    var depth = 0;
                    var parent = child.parentElement;
                    while (parent) {
                        if (parent.classList.contains('tree-node-children')) {
                            depth++;
                        }
                        parent = parent.parentElement;
                    }
                    return { element: child, depth: depth };
                });
                
                // Sort by depth descending (deepest first)
                childrenWithDepth.sort(function(a, b) {
                    return b.depth - a.depth;
                });
                
                // Set heights starting from deepest
                childrenWithDepth.forEach(function(item) {
                    var child = item.element;
                    child.style.maxHeight = 'none';
                    var height = child.scrollHeight;
                    child.style.maxHeight = height + 'px';
                });
                
                // Final pass after another reflow
                setTimeout(function() {
                    childrenWithDepth.forEach(function(item) {
                        var child = item.element;
                        child.style.maxHeight = 'none';
                        var height = child.scrollHeight;
                        child.style.maxHeight = height + 'px';
                    });
                }, 50);
            }, 10);
        }
        
        function collapseAllTreeNodes() {
            const allChildren = document.querySelectorAll('.tree-node-children');
            const allIcons = document.querySelectorAll('.tree-toggle-icon');
            
            allChildren.forEach(function(child) {
                child.classList.add('collapsed');
                child.style.maxHeight = '0';
            });
            
            allIcons.forEach(function(icon) {
                icon.classList.add('collapsed');
                icon.textContent = '▶';
            });
        }
        
        // Initialize tree view - set initial max-height for all children
        function initializeTreeView() {
            const allChildren = document.querySelectorAll('.tree-node-children');
            allChildren.forEach(function(child) {
                // Set initial max-height based on content
                child.style.maxHeight = child.scrollHeight + 'px';
            });
            
            console.log('Tree view initialized');
        }
        
        // Call tree view initialization after DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initializeTreeView);
        } else {
            initializeTreeView();
        }
        
        // ============================================================================
        // SCHEME SWITCHING FUNCTIONALITY
        // ============================================================================
        
        /**
         * Switch to a different area scheme
         * @param {string} schemeId - The safe scheme ID (e.g., "DGSF_Scheme_Opt1")
         */
        function switchToScheme(schemeId) {
            console.log('Switching to scheme:', schemeId);
            
            // Hide all scheme contents
            var allSchemes = document.querySelectorAll('.scheme-content');
            for (var i = 0; i < allSchemes.length; i++) {
                allSchemes[i].classList.remove('active');
            }
            
            // Show selected scheme
            var targetScheme = document.getElementById('scheme-' + schemeId);
            if (targetScheme) {
                targetScheme.classList.add('active');
                
                // Update URL hash without page reload
                if (history.pushState) {
                    history.pushState(null, null, '#' + schemeId);
                } else {
                    location.hash = '#' + schemeId;
                }
                
                // Update navigation highlighting
                updateSchemeNavigation(schemeId);
                
                // Re-initialize visualizations for the newly active scheme
                initializeSchemeVisualizations(targetScheme);
                
                // Initialize geometry viewer if it hasn't been created yet
                if (typeof geometryViewers !== 'undefined' && !geometryViewers[schemeId]) {
                    console.log('Initializing geometry viewer for newly visible scheme:', schemeId);
                    var canvas = document.getElementById('geometry-canvas-' + schemeId);
                    if (canvas && typeof AREA_GEOMETRY_DATA !== 'undefined') {
                        // Try exact match first
                        var schemeData = AREA_GEOMETRY_DATA[schemeId];
                        
                        // If not found, try with spaces instead of underscores
                        if (!schemeData) {
                            var schemeNameWithSpaces = schemeId.replace(/_/g, ' ');
                            schemeData = AREA_GEOMETRY_DATA[schemeNameWithSpaces];
                        }
                        
                        // Fuzzy match as fallback
                        if (!schemeData) {
                            var normalizedSchemeName = schemeId.toLowerCase().replace(/[_\s]/g, '');
                            for (var key in AREA_GEOMETRY_DATA) {
                                if (key.toLowerCase().replace(/[_\s]/g, '') === normalizedSchemeName) {
                                    schemeData = AREA_GEOMETRY_DATA[key];
                                    break;
                                }
                            }
                        }
                        
                        if (schemeData && typeof createGeometryViewer === 'function') {
                            console.log('Creating viewer for scheme:', schemeId);
                            var viewer = createGeometryViewer(canvas, schemeId, schemeData);
                            geometryViewers[schemeId] = viewer;
                            
                            // Populate filter dropdowns
                            if (typeof populateFilterDropdowns === 'function') {
                                populateFilterDropdowns(schemeId, schemeData);
                            }
                        } else {
                            console.warn('No geometry data found for scheme:', schemeId);
                        }
                    }
                }
                
                // Scroll to top smoothly
                window.scrollTo({ top: 0, behavior: 'smooth' });
                
                console.log('Switched to scheme:', schemeId);
            } else {
                console.error('Scheme not found:', schemeId);
            }
        }
        
        /**
         * Initialize or re-initialize all visualizations within a scheme
         * @param {HTMLElement} schemeElement - The scheme content element
         */
        function initializeSchemeVisualizations(schemeElement) {
            console.log('Initializing visualizations for scheme:', schemeElement.id);
            
            // Check if Chart.js is loaded
            if (typeof Chart === 'undefined') {
                console.warn('Chart.js not loaded yet, skipping chart initialization');
                return;
            }
            
            // Find and initialize department charts within this scheme
            var chartDataElement = schemeElement.querySelector('[id^="departmentChartData"]');
            if (chartDataElement) {
                try {
                    var chartData = JSON.parse(chartDataElement.textContent);
                    console.log('Found chart data for scheme:', chartData);
                    
                    // Initialize comparison chart
                    var comparisonCanvas = schemeElement.querySelector('[id^="deptComparisonChart"]');
                    if (comparisonCanvas) {
                        // Destroy existing chart if present
                        if (comparisonCanvas.chartInstance) {
                            comparisonCanvas.chartInstance.destroy();
                        }
                        createDepartmentComparisonChart(comparisonCanvas, chartData);
                    }
                    
                    // Initialize percentage chart
                    var percentageCanvas = schemeElement.querySelector('[id^="deptPercentageChart"]');
                    if (percentageCanvas) {
                        // Destroy existing chart if present
                        if (percentageCanvas.chartInstance) {
                            percentageCanvas.chartInstance.destroy();
                        }
                        createDepartmentPercentageChart(percentageCanvas, chartData);
                    }
                } catch (e) {
                    console.error('Error parsing chart data:', e);
                }
            }
            
            // Re-initialize building section diagram if present
            var buildingSection = schemeElement.querySelector('[id^="buildingSection"]');
            if (buildingSection && !buildingSection.dataset.initialized) {
                createBuildingSection();
                if (buildingSection) {
                    buildingSection.dataset.initialized = 'true';
                }
            }
            
            console.log('Visualizations initialized for scheme');
        }
        
        /**
         * Update active state of scheme navigation items
         * @param {string} activeSchemeId - The ID of the active scheme
         */
        function updateSchemeNavigation(activeSchemeId) {
            var schemeSelectors = document.querySelectorAll('.scheme-selector');
            for (var i = 0; i < schemeSelectors.length; i++) {
                var selector = schemeSelectors[i];
                var selectorScheme = selector.getAttribute('data-scheme');
                
                if (selectorScheme === activeSchemeId) {
                    selector.classList.add('active');
                } else {
                    selector.classList.remove('active');
                }
            }
        }
        
        /**
         * Initialize scheme from URL hash on page load
         */
        function initSchemeFromHash() {
            var hash = window.location.hash.substring(1); // Remove the '#'
            var activeScheme = null;
            
            if (hash) {
                console.log('Loading scheme from URL hash:', hash);
                
                // Check if scheme exists
                var targetScheme = document.getElementById('scheme-' + hash);
                if (targetScheme) {
                    // Hide all schemes first
                    var allSchemes = document.querySelectorAll('.scheme-content');
                    for (var i = 0; i < allSchemes.length; i++) {
                        allSchemes[i].classList.remove('active');
                    }
                    
                    // Show target scheme
                    targetScheme.classList.add('active');
                    updateSchemeNavigation(hash);
                    activeScheme = targetScheme;
                } else {
                    console.warn('Scheme from hash not found:', hash);
                    // Fall back to first scheme
                    var firstScheme = document.querySelector('.scheme-content');
                    if (firstScheme) {
                        firstScheme.classList.add('active');
                        activeScheme = firstScheme;
                    }
                }
            } else {
                // No hash - ensure first scheme is active
                var firstScheme = document.querySelector('.scheme-content');
                if (firstScheme) {
                    firstScheme.classList.add('active');
                    var firstSchemeId = firstScheme.id.replace('scheme-', '');
                    updateSchemeNavigation(firstSchemeId);
                    activeScheme = firstScheme;
                }
            }
            
            // Initialize visualizations for the active scheme
            if (activeScheme) {
                // Wait for Chart.js to load before initializing
                if (typeof Chart !== 'undefined') {
                    initializeSchemeVisualizations(activeScheme);
                } else {
                    // Chart.js not loaded yet, wait for it
                    console.log('Waiting for Chart.js to load before initializing scheme visualizations...');
                    var checkChartInterval = setInterval(function() {
                        if (typeof Chart !== 'undefined') {
                            clearInterval(checkChartInterval);
                            console.log('Chart.js loaded, initializing scheme visualizations');
                            initializeSchemeVisualizations(activeScheme);
                        }
                    }, 100);
                }
            }
        }
        
        /**
         * Handle browser back/forward buttons
         */
        function handleHashChange() {
            var hash = window.location.hash.substring(1);
            if (hash) {
                var targetScheme = document.getElementById('scheme-' + hash);
                if (targetScheme) {
                    // Hide all schemes
                    var allSchemes = document.querySelectorAll('.scheme-content');
                    for (var i = 0; i < allSchemes.length; i++) {
                        allSchemes[i].classList.remove('active');
                    }
                    
                    // Show target scheme
                    targetScheme.classList.add('active');
                    updateSchemeNavigation(hash);
                    
                    // Re-initialize visualizations for the scheme
                    initializeSchemeVisualizations(targetScheme);
                }
            }
        }
        
        // Initialize scheme on page load
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initSchemeFromHash);
        } else {
            initSchemeFromHash();
        }
        
        // Listen for hash changes (browser back/forward)
        window.addEventListener('hashchange', handleHashChange);
        
        console.log('Scheme switching initialized');
        
        // ============================================================================
        // GEOMETRY VIEWER IMPLEMENTATION - 2D and 3D Area Visualization
        // ============================================================================
        
        // Global storage for geometry viewers (one per scheme)
        var geometryViewers = {};
        
        /**
         * Initialize all geometry viewers after Three.js loads
         */
        function initializeGeometryViewers() {
            console.log('Initializing geometry viewers...');
            console.log('AREA_GEOMETRY_DATA:', AREA_GEOMETRY_DATA);
            
            // Find all geometry viewer canvases
            var canvases = document.querySelectorAll('.geometry-canvas');
            console.log('Found geometry canvases:', canvases.length);
            
            canvases.forEach(function(canvas) {
                var canvasId = canvas.id;
                var schemeName = canvasId.replace('geometry-canvas-', '');
                console.log('Initializing viewer for scheme:', schemeName);
                
                // Find matching scheme name in data (handle underscore vs space differences)
                var actualSchemeName = null;
                var schemeData = {};
                
                // Try exact match first
                if (AREA_GEOMETRY_DATA[schemeName]) {
                    actualSchemeName = schemeName;
                    schemeData = AREA_GEOMETRY_DATA[schemeName];
                } else {
                    // Try converting underscores to spaces
                    var schemeNameWithSpaces = schemeName.replace(/_/g, ' ');
                    if (AREA_GEOMETRY_DATA[schemeNameWithSpaces]) {
                        actualSchemeName = schemeNameWithSpaces;
                        schemeData = AREA_GEOMETRY_DATA[schemeNameWithSpaces];
                    } else {
                        // Try finding similar name (case-insensitive partial match)
                        for (var key in AREA_GEOMETRY_DATA) {
                            if (key.replace(/[_\s-]/g, '').toLowerCase() === schemeName.replace(/[_\s-]/g, '').toLowerCase()) {
                                actualSchemeName = key;
                                schemeData = AREA_GEOMETRY_DATA[key];
                                break;
                            }
                        }
                    }
                }
                
                if (!actualSchemeName || Object.keys(schemeData).length === 0) {
                    console.warn('No geometry data for scheme:', schemeName, 'Available schemes:', Object.keys(AREA_GEOMETRY_DATA));
                    canvas.parentElement.innerHTML = '<p style="color: #9ca3af; text-align: center; padding: 40px;">No geometry data available for this scheme.</p>';
                    return;
                }
                
                console.log('Found geometry data for scheme:', actualSchemeName);
                
                // Create viewer for this scheme
                var viewer = createGeometryViewer(canvas, schemeName, schemeData);
                geometryViewers[schemeName] = viewer;
                
                // Populate filter dropdowns
                populateFilterDropdowns(schemeName, schemeData);
            });
        }
        
        /**
         * Create a geometry viewer (starts in 2D mode)
         */
        function createGeometryViewer(canvas, schemeName, schemeData) {
            console.log('Creating geometry viewer for:', schemeName);
            
            var viewer = {
                canvas: canvas,
                schemeName: schemeName,
                schemeData: schemeData,
                scene: null,
                camera: null,
                renderer: null,
                controls: null,
                viewMode: '3d', // Start in 3D mode
                currentLevel: 'all',
                currentDepartment: 'all',
                areaMeshes: [],
                raycaster: new THREE.Raycaster(),
                mouse: new THREE.Vector2(),
                selectedArea: null,
                isAnimating: false,
                animationFrame: null
            };
            
            // Initialize renderer
            viewer.renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
            viewer.renderer.setSize(canvas.clientWidth, canvas.clientHeight);
            viewer.renderer.shadowMap.enabled = true;
            
            // Disable right-click context menu on the canvas
            viewer.renderer.domElement.addEventListener('contextmenu', function(e) {
                e.preventDefault();
                e.stopPropagation();
                return false;
            });
            
            // Start in 3D mode
            setup3DViewer(viewer);
            
            // Add interaction handlers
            setupViewerInteractions(viewer);
            
            // Start animation loop
            animate(viewer);
            
            return viewer;
        }
        
        /**
         * Setup 2D floor plan viewer (orthographic top-down view)
         */
        function setup2DViewer(viewer) {
            
            // Create scene
            viewer.scene = new THREE.Scene();
            viewer.scene.background = new THREE.Color(0x0a0e13);
            
            // Create orthographic camera (top-down view)
            var aspect = viewer.canvas.clientWidth / viewer.canvas.clientHeight;
            var frustumSize = 200;
            viewer.camera = new THREE.OrthographicCamera(
                frustumSize * aspect / -2,
                frustumSize * aspect / 2,
                frustumSize / 2,
                frustumSize / -2,
                0.1,
                1000
            );
            viewer.camera.position.set(0, 100, 0);
            viewer.camera.lookAt(0, 0, 0);
            
            // Add ambient light
            var ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
            viewer.scene.add(ambientLight);
            
            // Create area geometries
            createAreaGeometries2D(viewer);
            
            // Setup controls (no OrbitControls for 2D, use pan/zoom instead)
            setupPanZoomControls(viewer);
        }
        
        /**
         * Setup 3D extrusion viewer
         */
        function setup3DViewer(viewer) {
            
            // Create scene
            viewer.scene = new THREE.Scene();
            viewer.scene.background = new THREE.Color(0x0a0e13);
            
            // Create perspective camera
            viewer.camera = new THREE.PerspectiveCamera(
                60,
                viewer.canvas.clientWidth / viewer.canvas.clientHeight,
                0.1,
                10000
            );
            viewer.camera.position.set(200, 200, 200);
            
            // Lighting
            var ambientLight = new THREE.AmbientLight(0x404040, 0.6);
            viewer.scene.add(ambientLight);
            
            var directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
            directionalLight.position.set(100, 200, 100);
            directionalLight.castShadow = true;
            viewer.scene.add(directionalLight);
            
            // Create area geometries (extruded)
            createAreaGeometries3D(viewer);
            
            // Calculate bounding box center for camera positioning
            var centerPos = calculateBoundingBoxCenter(viewer);
            
            // Position camera to view all areas
            var distance = 200;
            viewer.camera.position.set(
                centerPos.x + distance,
                centerPos.y + distance,
                centerPos.z + distance
            );
            viewer.camera.lookAt(centerPos.x, centerPos.y, centerPos.z);
            
            // Setup OrbitControls with better mouse controls
            if (typeof THREE.OrbitControls !== 'undefined') {
                viewer.controls = new THREE.OrbitControls(viewer.camera, viewer.renderer.domElement);
                
                // Smooth damping for more fluid camera movement
                viewer.controls.enableDamping = true;
                viewer.controls.dampingFactor = 0.08;
                
                // Mouse button configuration
                viewer.controls.mouseButtons = {
                    LEFT: null,  // Disable left mouse (we'll use it for selection)
                    MIDDLE: THREE.MOUSE.DOLLY,  // Middle mouse for zoom
                    RIGHT: THREE.MOUSE.ROTATE   // Right mouse for orbit
                };
                
                // Enable panning with Shift+Right mouse
                viewer.controls.enablePan = true;
                viewer.controls.panSpeed = 0.8;
                viewer.controls.screenSpacePanning = true;  // More intuitive panning
                
                // Zoom settings - smoother and with better limits
                viewer.controls.enableZoom = true;
                viewer.controls.zoomSpeed = 1.2;
                viewer.controls.minDistance = 5;
                viewer.controls.maxDistance = 3000;
                
                // Rotation settings - smoother rotation
                viewer.controls.enableRotate = true;
                viewer.controls.rotateSpeed = 0.6;
                
                // Auto-rotate disabled by default (can be toggled)
                viewer.controls.autoRotate = false;
                viewer.controls.autoRotateSpeed = 0.5;
                
                // Limit vertical rotation to prevent flipping
                viewer.controls.maxPolarAngle = Math.PI * 0.95;  // Prevent going under the floor
                viewer.controls.minPolarAngle = 0;
                
                // Pan with shift+right mouse
                viewer.canvas.addEventListener('mousedown', function(e) {
                    if (e.button === 2 && e.shiftKey) {
                        viewer.controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
                    } else if (e.button === 2) {
                        viewer.controls.mouseButtons.RIGHT = THREE.MOUSE.ROTATE;
                    }
                });
                
                viewer.canvas.addEventListener('mouseup', function(e) {
                    if (e.button === 2) {
                        viewer.controls.mouseButtons.RIGHT = THREE.MOUSE.ROTATE;
                    }
                });
                
                // Add mouse wheel zoom with shift key for faster zoom
                viewer.canvas.addEventListener('wheel', function(e) {
                    if (e.shiftKey) {
                        viewer.controls.zoomSpeed = 2.0;
                    } else {
                        viewer.controls.zoomSpeed = 1.2;
                    }
                }, { passive: true });
                
                // Set orbit center to bounding box center
                viewer.controls.target.set(centerPos.x, centerPos.y, centerPos.z);
                viewer.controls.update();
            } else {
                console.warn('OrbitControls not available');
            }
        }
        
        /**
         * Create 2D area geometries (flat polygons)
         */
        function createAreaGeometries2D(viewer) {
            
            // Clear existing meshes
            viewer.areaMeshes.forEach(function(mesh) {
                viewer.scene.remove(mesh);
            });
            viewer.areaMeshes = [];
            
            var schemeData = viewer.schemeData;
            var allAreas = [];
            
            // Collect all areas from all levels
            for (var levelName in schemeData) {
                var levelAreas = schemeData[levelName];
                levelAreas.forEach(function(areaData) {
                    areaData.levelName = levelName;
                    allAreas.push(areaData);
                });
            }
            
            console.log('Total areas to render:', allAreas.length);
            
            // Calculate bounding box for camera positioning
            var minX = Infinity, maxX = -Infinity;
            var minY = Infinity, maxY = -Infinity;
            
            allAreas.forEach(function(areaData) {
                var boundaryLoops = areaData.boundary_loops || [];
                if (boundaryLoops.length === 0) return;
                
                var outerLoop = boundaryLoops[0];
                var points = outerLoop.points || [];
                
                if (points.length < 3) return;
                
                // Create THREE.Shape from boundary points
                var shape = new THREE.Shape();
                
                // Scale coordinates (Revit units are in feet, scale down for display)
                var scale = 0.1;
                
                points.forEach(function(pt, index) {
                    var x = pt[0] * scale;
                    var z = pt[1] * scale; // In 2D view, Y becomes Z
                    
                    // Track bounds
                    if (x < minX) minX = x;
                    if (x > maxX) maxX = x;
                    if (z < minY) minY = z;
                    if (z > maxY) maxY = z;
                    
                    if (index === 0) {
                        shape.moveTo(x, z);
                    } else {
                        shape.lineTo(x, z);
                    }
                });
                
                // Close the shape
                if (points.length > 0) {
                    var firstPt = points[0];
                    shape.lineTo(firstPt[0] * scale, firstPt[1] * scale);
                }
                
                // Handle holes (inner loops)
                for (var i = 1; i < boundaryLoops.length; i++) {
                    var holeLoop = boundaryLoops[i];
                    var holePoints = holeLoop.points || [];
                    if (holePoints.length < 3) continue;
                    
                    var holePath = new THREE.Path();
                    holePoints.forEach(function(pt, index) {
                        var x = pt[0] * scale;
                        var z = pt[1] * scale;
                        
                        if (index === 0) {
                            holePath.moveTo(x, z);
                        } else {
                            holePath.lineTo(x, z);
                        }
                    });
                    shape.holes.push(holePath);
                }
                
                // Create geometry from shape
                var geometry = new THREE.ShapeGeometry(shape);
                
                // Get color from department
                var color = areaData.color || '#6b7280';
                var material = new THREE.MeshBasicMaterial({
                    color: new THREE.Color(color),
                    transparent: true,
                    opacity: 0.7,
                    side: THREE.DoubleSide
                });
                
                var mesh = new THREE.Mesh(geometry, material);
                mesh.rotation.x = -Math.PI / 2; // Lay flat
                
                // Use level elevation for slight separation
                var levelElevation = areaData.level_elevation || 0;
                mesh.position.y = levelElevation * scale * 0.1; // Small offset per level
                
                // Store metadata
                mesh.userData = areaData;
                
                viewer.scene.add(mesh);
                viewer.areaMeshes.push(mesh);
                
                // Note: Wireframe edges disabled due to Three.js compatibility issues
            });
            
            // Position camera to view all areas
            var centerX = (minX + maxX) / 2;
            var centerZ = (minY + maxY) / 2;
            var rangeX = maxX - minX;
            var rangeZ = maxY - minY;
            var maxRange = Math.max(rangeX, rangeZ, 100);
            
            viewer.camera.position.set(centerX, maxRange * 1.5, centerZ);
            viewer.camera.lookAt(centerX, 0, centerZ);
            
            // Update orthographic camera frustum
            var aspect = viewer.canvas.clientWidth / viewer.canvas.clientHeight;
            var frustumSize = maxRange * 1.2;
            viewer.camera.left = frustumSize * aspect / -2;
            viewer.camera.right = frustumSize * aspect / 2;
            viewer.camera.top = frustumSize / 2;
            viewer.camera.bottom = frustumSize / -2;
            viewer.camera.updateProjectionMatrix();
            
            console.log('2D geometries created:', viewer.areaMeshes.length);
        }
        
        /**
         * Create 3D area geometries (extruded volumes)
         */
        function createAreaGeometries3D(viewer) {
            
            // Clear existing meshes
            viewer.areaMeshes.forEach(function(mesh) {
                viewer.scene.remove(mesh);
            });
            viewer.areaMeshes = [];
            
            var schemeData = viewer.schemeData;
            var scale = 0.1;
            var floorHeight = 1.2; // Height of each extruded area
            
            var totalAreas = 0;
            var skippedNoLoops = 0;
            var skippedFewPoints = 0;
            var created = 0;
            
            // Collect all areas
            for (var levelName in schemeData) {
                var levelAreas = schemeData[levelName];
                
                levelAreas.forEach(function(areaData) {
                    totalAreas++;
                    var boundaryLoops = areaData.boundary_loops || [];
                    if (boundaryLoops.length === 0) {
                        skippedNoLoops++;
                        return;
                    }
                    
                    var outerLoop = boundaryLoops[0];
                    var points = outerLoop.points || [];
                    if (points.length < 3) {
                        skippedFewPoints++;
                        return;
                    }
                    
                    // Create THREE.Shape
                    var shape = new THREE.Shape();
                    points.forEach(function(pt, index) {
                        var x = pt[0] * scale;
                        var z = pt[1] * scale;
                        
                        if (index === 0) {
                            shape.moveTo(x, z);
                        } else {
                            shape.lineTo(x, z);
                        }
                    });
                    
                    // Handle holes
                    for (var i = 1; i < boundaryLoops.length; i++) {
                        var holeLoop = boundaryLoops[i];
                        var holePoints = holeLoop.points || [];
                        if (holePoints.length < 3) continue;
                        
                        var holePath = new THREE.Path();
                        holePoints.forEach(function(pt, index) {
                            var x = pt[0] * scale;
                            var z = pt[1] * scale;
                            if (index === 0) {
                                holePath.moveTo(x, z);
                            } else {
                                holePath.lineTo(x, z);
                            }
                        });
                        shape.holes.push(holePath);
                    }
                    
                    // Extrude geometry
                    var extrudeSettings = {
                        depth: floorHeight,
                        bevelEnabled: false
                    };
                    var geometry = new THREE.ExtrudeGeometry(shape, extrudeSettings);
                    
                    // Material with department color
                    var color = areaData.color || '#6b7280';
                    var material = new THREE.MeshLambertMaterial({
                        color: new THREE.Color(color),
                        transparent: true,
                        opacity: 0.8
                    });
                    
                    var mesh = new THREE.Mesh(geometry, material);
                    mesh.rotation.x = -Math.PI / 2;
                    
                    // Position at level elevation
                    var levelElevation = (areaData.level_elevation || 0) * scale;
                    mesh.position.y = levelElevation;
                    
                    // Store metadata
                    mesh.userData = areaData;
                    
                    viewer.scene.add(mesh);
                    viewer.areaMeshes.push(mesh);
                    
                    // Note: Wireframe edges disabled due to Three.js compatibility issues
                    // causing "Cannot read properties of undefined (reading 'value')" errors
                    
                    created++;
                });
            }
            
            if (created > 0) {
                console.log('3D viewer: Loaded', created, 'areas');
            }
            if (skippedNoLoops + skippedFewPoints > 0) {
                console.warn('Skipped', skippedNoLoops + skippedFewPoints, 'areas (incomplete geometry)');
            }
        }
        
        /**
         * Setup pan/zoom controls for 2D view
         */
        function setupPanZoomControls(viewer) {
            var canvas = viewer.canvas;
            var isDragging = false;
            var previousMousePosition = { x: 0, y: 0 };
            
            canvas.addEventListener('mousedown', function(e) {
                isDragging = true;
                previousMousePosition = { x: e.clientX, y: e.clientY };
            });
            
            canvas.addEventListener('mousemove', function(e) {
                if (!isDragging) return;
                
                var deltaX = e.clientX - previousMousePosition.x;
                var deltaY = e.clientY - previousMousePosition.y;
                
                var panSpeed = 0.5;
                viewer.camera.position.x -= deltaX * panSpeed;
                viewer.camera.position.z += deltaY * panSpeed;
                
                previousMousePosition = { x: e.clientX, y: e.clientY };
            });
            
            canvas.addEventListener('mouseup', function() {
                isDragging = false;
            });
            
            canvas.addEventListener('wheel', function(e) {
                e.preventDefault();
                var zoomSpeed = 0.1;
                var delta = e.deltaY > 0 ? 1 + zoomSpeed : 1 - zoomSpeed;
                
                // Zoom orthographic camera by adjusting frustum
                viewer.camera.left *= delta;
                viewer.camera.right *= delta;
                viewer.camera.top *= delta;
                viewer.camera.bottom *= delta;
                viewer.camera.updateProjectionMatrix();
            });
        }
        
        /**
         * Setup viewer interactions (click, hover)
         */
        function setupViewerInteractions(viewer) {
            var canvas = viewer.canvas;
            
            // Simple click handler using dblclick to avoid conflicts with orbit controls
            canvas.addEventListener('dblclick', function(event) {
                var rect = canvas.getBoundingClientRect();
                viewer.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
                viewer.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
                
                viewer.raycaster.setFromCamera(viewer.mouse, viewer.camera);
                var intersects = viewer.raycaster.intersectObjects(viewer.areaMeshes, false);
                
                if (intersects.length > 0) {
                    var clickedMesh = intersects[0].object;
                    var areaData = clickedMesh.userData;
                    
                    if (areaData && areaData.area_id) {
                        console.log('Selected:', areaData.program_type_detail || 'Area ' + areaData.area_id);
                        showAreaPopup(viewer, areaData, event.clientX, event.clientY);
                        highlightArea(viewer, clickedMesh);
                        
                        // Update orbit center to selected area's center
                        if (viewer.controls) {
                            var meshCenter = getMeshCenter(clickedMesh);
                            viewer.controls.target.set(meshCenter.x, meshCenter.y, meshCenter.z);
                            viewer.controls.update();
                        }
                    }
                } else {
                    hideAreaPopup(viewer);
                    clearHighlight(viewer);
                    
                    // Reset orbit center to scene center
                    if (viewer.controls && viewer.viewMode === '3d') {
                        var sceneCenter = calculateSceneCenter(viewer);
                        viewer.controls.target.set(sceneCenter.x, sceneCenter.y, sceneCenter.z);
                        viewer.controls.update();
                    }
                }
            });
            
            // Hover handler
            canvas.addEventListener('mousemove', function(event) {
                var rect = canvas.getBoundingClientRect();
                viewer.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
                viewer.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
                
                viewer.raycaster.setFromCamera(viewer.mouse, viewer.camera);
                var intersects = viewer.raycaster.intersectObjects(viewer.areaMeshes, false);
                
                if (intersects.length > 0) {
                    canvas.style.cursor = 'pointer';
                } else {
                    canvas.style.cursor = 'default';
                }
            });
        }
        
        /**
         * Show area information popup
         */
        function showAreaPopup(viewer, areaData, x, y) {
            var popupId = 'area-info-popup-' + viewer.schemeName;
            var popup = document.getElementById(popupId);
            if (!popup) {
                console.warn('Popup element not found:', popupId);
                return;
            }
            
            var html = '<h4>' + (areaData.program_type_detail || 'Unnamed Area') + '</h4>';
            html += '<p><strong>Department:</strong> ' + (areaData.department || 'N/A') + '</p>';
            html += '<p><strong>Division:</strong> ' + (areaData.program_type || 'N/A') + '</p>';
            html += '<p><strong>Area:</strong> ' + Math.round(areaData.area_sf || 0) + ' SF</p>';
            html += '<p><strong>Level:</strong> ' + (areaData.levelName || viewer.schemeData ? Object.keys(viewer.schemeData)[0] : 'N/A') + '</p>';
            html += '<p style="font-size: 0.75rem; color: #9ca3af; margin-top: 8px;">Double-click outside to close</p>';
            
            popup.innerHTML = html;
            popup.style.display = 'block';
            popup.style.position = 'fixed';
            
            // Position next to mouse, but keep within viewport
            var popupWidth = 300;  // Approximate popup width
            var popupHeight = 200; // Approximate popup height
            var offsetX = 15;
            var offsetY = 15;
            
            var left = x + offsetX;
            var top = y + offsetY;
            
            // Prevent popup from going off right edge
            if (left + popupWidth > window.innerWidth) {
                left = x - popupWidth - offsetX;
            }
            
            // Prevent popup from going off bottom edge
            if (top + popupHeight > window.innerHeight) {
                top = y - popupHeight - offsetY;
            }
            
            popup.style.left = left + 'px';
            popup.style.top = top + 'px';
            popup.style.zIndex = '99999';
            
            console.log('Popup shown at:', left, top, 'for area:', areaData.program_type_detail || areaData.area_id);
        }
        
        /**
         * Hide area information popup
         */
        function hideAreaPopup(viewer) {
            var popupId = 'area-info-popup-' + viewer.schemeName;
            var popup = document.getElementById(popupId);
            if (popup) {
                popup.style.display = 'none';
            }
        }
        
        /**
         * Highlight selected area
         */
        function highlightArea(viewer, mesh) {
            clearHighlight(viewer);
            viewer.selectedArea = mesh;
            
            if (mesh.material) {
                mesh.material.opacity = 1.0;
                mesh.material.emissive = new THREE.Color(0x60a5fa);
                mesh.material.emissiveIntensity = 0.5;
            }
        }
        
        /**
         * Clear area highlight
         */
        function clearHighlight(viewer) {
            if (viewer.selectedArea && viewer.selectedArea.material) {
                viewer.selectedArea.material.opacity = viewer.viewMode === '2d' ? 0.7 : 0.8;
                viewer.selectedArea.material.emissive = new THREE.Color(0x000000);
                viewer.selectedArea.material.emissiveIntensity = 0;
            }
            viewer.selectedArea = null;
        }
        
        /**
         * Animation loop
         */
        function animate(viewer) {
            viewer.animationFrame = requestAnimationFrame(function() {
                animate(viewer);
            });
            
            if (viewer.controls) {
                viewer.controls.update();
            }
            
            viewer.renderer.render(viewer.scene, viewer.camera);
        }
        
        /**
         * Switch view mode (2D/3D)
         */
        function switchViewMode(mode, schemeName) {
            
            var viewer = geometryViewers[schemeName];
            if (!viewer) return;
            
            viewer.viewMode = mode;
            
            // Update button states
            var btn2d = document.getElementById('btn-2d-' + schemeName);
            var btn3d = document.getElementById('btn-3d-' + schemeName);
            
            if (mode === '2d') {
                btn2d.classList.add('active');
                btn3d.classList.remove('active');
                setup2DViewer(viewer);
                
                // In 2D mode, auto-select first level if currently showing all levels
                if (viewer.currentLevel === 'all') {
                    var levelSelect = document.getElementById('level-filter-' + schemeName);
                    if (levelSelect && levelSelect.options.length > 1) {
                        // Skip the "All Levels" option (index 0), select first actual level (index 1)
                        levelSelect.selectedIndex = 1;
                        var firstLevel = levelSelect.options[1].value;
                        viewer.currentLevel = firstLevel;
                    }
                }
            } else {
                btn3d.classList.add('active');
                btn2d.classList.remove('active');
                setup3DViewer(viewer);
                
                // In 3D mode, show all levels
                var levelSelect = document.getElementById('level-filter-' + schemeName);
                if (levelSelect) {
                    levelSelect.value = 'all';
                    viewer.currentLevel = 'all';
                }
            }
        }
        
        /**
         * Populate filter dropdowns
         */
        function populateFilterDropdowns(schemeName, schemeData) {
            var levelData = [];
            var departments = {};
            
            // Collect unique departments and level elevations
            for (var levelName in schemeData) {
                var areas = schemeData[levelName];
                
                // Get elevation from first area in this level
                var levelElevation = 0;
                if (areas.length > 0 && areas[0].level_elevation !== undefined) {
                    levelElevation = areas[0].level_elevation;
                }
                
                levelData.push({
                    name: levelName,
                    elevation: levelElevation
                });
                
                areas.forEach(function(area) {
                    var dept = area.department || 'Unknown';
                    departments[dept] = true;
                });
            }
            
            // Sort levels by elevation (ascending: B1, 1, 2, 3, etc.)
            levelData.sort(function(a, b) {
                return a.elevation - b.elevation;
            });
            
            // Populate level filter
            var levelSelect = document.getElementById('level-filter-' + schemeName);
            if (levelSelect) {
                levelData.forEach(function(level) {
                    var option = document.createElement('option');
                    option.value = level.name;
                    option.textContent = level.name;
                    levelSelect.appendChild(option);
                });
                
                // Set default selection based on view mode
                var viewer = geometryViewers[schemeName];
                if (viewer) {
                    if (viewer.viewMode === '2d' && levelData.length > 0) {
                        // In 2D mode, select first level by default
                        levelSelect.value = levelData[0].name;
                        viewer.currentLevel = levelData[0].name;
                    } else {
                        // In 3D mode, show all levels
                        levelSelect.value = 'all';
                        viewer.currentLevel = 'all';
                    }
                }
            }
            
            // Populate department filter (alphabetically sorted)
            var deptSelect = document.getElementById('dept-filter-' + schemeName);
            if (deptSelect) {
                Object.keys(departments).sort().forEach(function(dept) {
                    var option = document.createElement('option');
                    option.value = dept;
                    option.textContent = dept;
                    deptSelect.appendChild(option);
                });
            }
        }
        
        /**
         * Filter by level
         */
        function filterByLevel(schemeName, levelName) {
            console.log('Filter by level:', levelName);
            var viewer = geometryViewers[schemeName];
            if (!viewer) return;
            
            viewer.currentLevel = levelName;
            applyFilters(viewer);
        }
        
        /**
         * Filter by department
         */
        function filterByDepartment(schemeName, department) {
            console.log('Filter by department:', department);
            var viewer = geometryViewers[schemeName];
            if (!viewer) return;
            
            viewer.currentDepartment = department;
            applyFilters(viewer);
        }
        
        /**
         * Apply current filters to viewer
         */
        function applyFilters(viewer) {
            viewer.areaMeshes.forEach(function(mesh) {
                var areaData = mesh.userData;
                if (!areaData || !areaData.area_id) {
                    return; // Skip non-area meshes
                }
                
                var showLevel = viewer.currentLevel === 'all' || areaData.levelName === viewer.currentLevel;
                var showDept = viewer.currentDepartment === 'all' || areaData.department === viewer.currentDepartment;
                
                mesh.visible = showLevel && showDept;
            });
        }
        
        /**
         * Toggle target overlay (placeholder - to be implemented with Excel data)
         */
        function toggleTargetOverlay(schemeName, enabled) {
            console.log('Toggle target overlay:', enabled);
            // TODO: Implement target overlay based on Excel requirements
        }
        
        /**
         * Get center point of a mesh
         */
        function getMeshCenter(mesh) {
            if (!mesh.geometry.boundingBox) {
                mesh.geometry.computeBoundingBox();
            }
            
            var bbox = mesh.geometry.boundingBox;
            if (bbox) {
                var center = new THREE.Vector3();
                bbox.getCenter(center);
                
                // Transform to world space
                center.applyMatrix4(mesh.matrixWorld);
                return center;
            }
            
            return mesh.position.clone();
        }
        
        /**
         * Calculate bounding box center of all area geometries
         */
        function calculateBoundingBoxCenter(viewer) {
            var minX = Infinity, maxX = -Infinity;
            var minY = Infinity, maxY = -Infinity;
            var minZ = Infinity, maxZ = -Infinity;
            var count = 0;
            
            viewer.areaMeshes.forEach(function(mesh) {
                if (mesh.userData && mesh.userData.area_id) {
                    if (!mesh.geometry.boundingBox) {
                        mesh.geometry.computeBoundingBox();
                    }
                    
                    var bbox = mesh.geometry.boundingBox;
                    if (bbox) {
                        var worldMin = bbox.min.clone();
                        var worldMax = bbox.max.clone();
                        worldMin.applyMatrix4(mesh.matrixWorld);
                        worldMax.applyMatrix4(mesh.matrixWorld);
                        
                        if (worldMin.x < minX) minX = worldMin.x;
                        if (worldMax.x > maxX) maxX = worldMax.x;
                        if (worldMin.y < minY) minY = worldMin.y;
                        if (worldMax.y > maxY) maxY = worldMax.y;
                        if (worldMin.z < minZ) minZ = worldMin.z;
                        if (worldMax.z > maxZ) maxZ = worldMax.z;
                        count++;
                    }
                }
            });
            
            if (count > 0) {
                return {
                    x: (minX + maxX) / 2,
                    y: (minY + maxY) / 2,
                    z: (minZ + maxZ) / 2
                };
            } else {
                return { x: 0, y: 0, z: 0 };
            }
        }
        
        /**
         * Calculate scene center from all area geometries (simpler, uses position only)
         */
        function calculateSceneCenter(viewer) {
            var minX = Infinity, maxX = -Infinity;
            var minY = Infinity, maxY = -Infinity;
            var minZ = Infinity, maxZ = -Infinity;
            var count = 0;
            
            viewer.areaMeshes.forEach(function(mesh) {
                if (mesh.userData && mesh.userData.area_id) {
                    var pos = mesh.position;
                    if (pos.x < minX) minX = pos.x;
                    if (pos.x > maxX) maxX = pos.x;
                    if (pos.y < minY) minY = pos.y;
                    if (pos.y > maxY) maxY = pos.y;
                    if (pos.z < minZ) minZ = pos.z;
                    if (pos.z > maxZ) maxZ = pos.z;
                    count++;
                }
            });
            
            if (count > 0) {
                return {
                    x: (minX + maxX) / 2,
                    y: (minY + maxY) / 2,
                    z: (minZ + maxZ) / 2
                };
            } else {
                return { x: 0, y: 0, z: 0 };
            }
        }
        
        /**
         * Reset camera to initial view (zoom to fit all areas)
         */
        function resetCamera(schemeName) {
            var viewer = geometryViewers[schemeName];
            if (!viewer) return;
            
            if (viewer.viewMode === '2d') {
                setup2DViewer(viewer);
            } else {
                // Reset 3D camera
                var centerPos = calculateSceneCenter(viewer);
                
                // Position camera at 45-degree angle
                var distance = 200;
                viewer.camera.position.set(
                    centerPos.x + distance,
                    centerPos.y + distance,
                    centerPos.z + distance
                );
                
                if (viewer.controls) {
                    viewer.controls.target.set(centerPos.x, centerPos.y, centerPos.z);
                    viewer.controls.update();
                }
            }
        }
        
        /**
         * Zoom to fit all visible areas
         */
        function zoomToFit(schemeName) {
            var viewer = geometryViewers[schemeName];
            if (!viewer) return;
            
            console.log('Zooming to fit all areas');
            
            // Calculate bounding box of visible areas
            var minX = Infinity, maxX = -Infinity;
            var minY = Infinity, maxY = -Infinity;
            var minZ = Infinity, maxZ = -Infinity;
            var visibleCount = 0;
            
            viewer.areaMeshes.forEach(function(mesh) {
                if (!mesh.visible || !mesh.userData || !mesh.userData.area_id) return;
                
                // Get bounding box of this mesh
                if (!mesh.geometry.boundingBox) {
                    mesh.geometry.computeBoundingBox();
                }
                
                var bbox = mesh.geometry.boundingBox;
                if (bbox) {
                    var worldMin = bbox.min.clone();
                    var worldMax = bbox.max.clone();
                    
                    // Transform to world space
                    worldMin.applyMatrix4(mesh.matrixWorld);
                    worldMax.applyMatrix4(mesh.matrixWorld);
                    
                    if (worldMin.x < minX) minX = worldMin.x;
                    if (worldMax.x > maxX) maxX = worldMax.x;
                    if (worldMin.y < minY) minY = worldMin.y;
                    if (worldMax.y > maxY) maxY = worldMax.y;
                    if (worldMin.z < minZ) minZ = worldMin.z;
                    if (worldMax.z > maxZ) maxZ = worldMax.z;
                    visibleCount++;
                }
            });
            
            if (visibleCount === 0) {
                console.log('No visible areas to fit');
                return;
            }
            
            var center = {
                x: (minX + maxX) / 2,
                y: (minY + maxY) / 2,
                z: (minZ + maxZ) / 2
            };
            
            var size = {
                x: maxX - minX,
                y: maxY - minY,
                z: maxZ - minZ
            };
            
            var maxDim = Math.max(size.x, size.y, size.z);
            var distance = maxDim * 2.5; // Distance multiplier for nice framing
            
            if (viewer.viewMode === '2d') {
                // For 2D orthographic
                viewer.camera.position.set(center.x, center.y + 100, center.z);
                viewer.camera.lookAt(center.x, center.y, center.z);
                
                var aspect = viewer.canvas.clientWidth / viewer.canvas.clientHeight;
                var frustumSize = maxDim * 1.1;
                viewer.camera.left = frustumSize * aspect / -2;
                viewer.camera.right = frustumSize * aspect / 2;
                viewer.camera.top = frustumSize / 2;
                viewer.camera.bottom = frustumSize / -2;
                viewer.camera.updateProjectionMatrix();
            } else {
                // For 3D perspective
                viewer.camera.position.set(
                    center.x + distance * 0.7,
                    center.y + distance * 0.7,
                    center.z + distance * 0.7
                );
                
                if (viewer.controls) {
                    viewer.controls.target.set(center.x, center.y, center.z);
                    viewer.controls.update();
                }
            }
            
            console.log('Zoomed to fit', visibleCount, 'areas');
        }
        
        /**
         * Reset camera to initial view
         */
        function resetCamera(schemeName) {
            var viewer = geometryViewers[schemeName];
            if (!viewer) return;
            
            if (viewer.viewMode === '2d') {
                setup2DViewer(viewer);
            } else {
                setup3DViewer(viewer);
            }
        }
        
        /**
         * Toggle animation (explode view / fly-through)
         */
        function toggleAnimation(schemeName) {
            var viewer = geometryViewers[schemeName];
            if (!viewer) return;
            
            viewer.isAnimating = !viewer.isAnimating;
            
            if (viewer.isAnimating) {
                console.log('Starting animation');
                // TODO: Implement explode view animation
            } else {
                console.log('Stopping animation');
            }
        }
        
        // Auto-initialize geometry viewers when Three.js is available
        if (typeof THREE !== 'undefined' && typeof THREE.OrbitControls !== 'undefined') {
            console.log('Three.js already loaded, initializing geometry viewers now');
            initializeGeometryViewers();
        } else {
            console.log('Waiting for Three.js to load geometry viewers...');
        }
        
        """
    
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
    
    def _generate_geometry_data_json(self, revit_data):
        """
        Generate JavaScript-ready JSON data for area geometries
        
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
            json_str = json.dumps(geometry_data, indent=2, ensure_ascii=True)
            
            # Write to script folder for debugging
            try:
                import os
                # Debug JSON output (optional - comment out for production)
                # import io
                # script_dir = os.path.dirname(__file__)
                # debug_path = os.path.join(script_dir, "area_geometry_debug.json")
                # with io.open(debug_path, 'w', encoding='utf-8') as f:
                #     if isinstance(json_str, str):
                #         json_str_unicode = json_str.decode('utf-8')
                #     else:
                #         json_str_unicode = json_str
                #     f.write(json_str_unicode)
                
                # Summary
                total_areas = sum(sum(len(areas) for areas in levels.values()) for levels in geometry_data.values())
                if total_areas > 0:
                    print("3D geometry: {} areas loaded".format(total_areas))
            except Exception as debug_e:
                pass
            
            return json_str
        except Exception as e:
            print("Error generating geometry JSON: {}".format(str(e)))
            import traceback
            traceback.print_exc()
            return "{}"
    
    def open_report_in_browser(self, filepath=None):
        """Open the report in Microsoft Edge browser (preferred) or default browser"""
        if filepath is None:
            filepath = os.path.join(self.reports_dir, config.LATEST_REPORT_FILENAME)
        
        if not os.path.exists(filepath):
            return False
        
        abs_filepath = os.path.abspath(filepath)
        
        # Try to open in Microsoft Edge first
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        
        for edge_path in edge_paths:
            if os.path.exists(edge_path):
                try:
                    subprocess.Popen([edge_path, abs_filepath])
                    print("Opened in Microsoft Edge: {}".format(os.path.basename(filepath)))
                    return True
                except Exception as e:
                    print("Failed to open in Edge: {}".format(str(e)))
                    continue
        
        # Fallback to default browser if Edge not found
        print("Microsoft Edge not found, using default browser")
        webbrowser.open("file://{}".format(abs_filepath))
        return True
