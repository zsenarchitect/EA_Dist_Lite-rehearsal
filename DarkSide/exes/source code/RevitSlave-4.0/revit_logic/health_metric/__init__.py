import traceback
from datetime import datetime

# STANDALONE VERSION - No EnneadTab or proDUCKtion dependencies
# This makes the HealthMetric completely independent and faster to import

# Import all check modules
from . import project_checks
from . import linked_files_checks
from . import elements_checks
from . import views_checks
from . import templates_checks
from . import cad_checks
from . import families_checks
from . import graphical_checks
from . import groups_checks
from . import reference_checks
from . import materials_checks
from . import warnings_checks
from . import file_checks
from . import regions_checks


class HealthMetric:
    def __init__(self, doc):
        self.doc = doc
        self.report = {
            "version": "v2",
            "timestamp": datetime.now().isoformat(),
            "document_title": doc.Title,
            "is_EnneadTab_Available": False,  # Standalone version
            "checks": {}
        }

    def check(self):
        """Run comprehensive health metric collection with progress logging"""
        try:
            # Define all checks to run (in order) with granular crash tracking
            checks_to_run = [
                ("project_info", "Project info", project_checks.check_project_info),
                ("linked_files", "Linked files", linked_files_checks.check_linked_files),
                ("critical_elements", "Critical elements", elements_checks.check_critical_elements),
                ("rooms", "Rooms", elements_checks.check_rooms),
                ("views_sheets", "Sheets/views", views_checks.check_sheets_views),
                ("templates_filters", "Templates/filters", templates_checks.check_templates_filters),
                ("cad_files", "CAD files", cad_checks.check_cad_files),
                ("families", "Families", families_checks.check_families),
                ("graphical_elements", "Graphical elements", graphical_checks.check_graphical_elements),
                ("groups", "Groups", groups_checks.check_groups),
                ("reference_planes", "Reference planes", reference_checks.check_reference_planes),
                ("materials", "Materials", materials_checks.check_materials),
                ("line_count", "Line counts", materials_checks.check_line_count),
                ("warnings", "Warnings", warnings_checks.check_warnings),
                ("file_size", "File size", file_checks.check_file_size),
                ("filled_regions", "Filled regions", regions_checks.check_filled_regions),
                ("grids_levels", "Grids/levels", reference_checks.check_grids_levels),
            ]
            
            # Run each check with individual try-catch for crash isolation
            for check_idx, (check_key, check_name, check_func) in enumerate(checks_to_run, 1):
                try:
                    print("=" * 60)
                    print("HEALTH CHECK [{}/{}]: {} - STARTING".format(check_idx, len(checks_to_run), check_name))
                    print("=" * 60)
                    
                    # Write crash tracker before each check (survives Revit hard crashes)
                    import os
                    crash_tracker_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "current_check.txt")
                    try:
                        with open(crash_tracker_path, 'w') as f:
                            f.write("CHECK: {}\n".format(check_name))
                            f.write("INDEX: {}/{}\n".format(check_idx, len(checks_to_run)))
                            f.write("TIME: {}\n".format(datetime.now().isoformat()))
                            f.write("KEY: {}\n".format(check_key))
                    except:
                        pass  # Don't fail if crash tracker fails
                    
                    result = check_func(self.doc)
                    self.report["checks"][check_key] = result
                    print("HEALTH CHECK [{}/{}]: {} - COMPLETED".format(check_idx, len(checks_to_run), check_name))
                    
                except Exception as check_error:
                    print("=" * 60)
                    print("HEALTH CHECK [{}/{}]: {} - FAILED".format(check_idx, len(checks_to_run), check_name))
                    print("Error: {}".format(str(check_error)))
                    print("=" * 60)
                    print("Traceback:")
                    print(traceback.format_exc())
                    print("=" * 60)
                    
                    # Store error but continue with other checks
                    self.report["checks"][check_key] = {
                        "error": str(check_error),
                        "traceback": traceback.format_exc(),
                        "check_name": check_name,
                        "check_index": "{}/{}".format(check_idx, len(checks_to_run))
                    }
                    # Continue with next check instead of failing completely
            
            print("STATUS: All health metric checks completed successfully!")
            
            return self.report
        except Exception as e:
            print("STATUS: HealthMetric failed at: {}".format(str(e)))
            # Add error to report and return partial results
            self.report["error"] = str(traceback.format_exc())
            return self.report
