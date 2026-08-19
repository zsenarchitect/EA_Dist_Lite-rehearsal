__context__ = "zero-doc"
#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = "RevitSlave4 Entry Script - Runs inside Revit (IronPython 2.7)"
__title__ = "RevitSlave4 Entry"


"""
RevitSlave4 Entry Script
========================

This script runs INSIDE Revit (IronPython 2.7) via pyRevit CLI.
It is the bridge between the orchestrator (CPython) and Revit (IronPython).

Architecture:
- Launched by: core/job_executor.py via pyrevit CLI
- Runs in: Revit process (IronPython 2.7 environment)
- Dependencies: STANDALONE - no EnneadTab dependencies
- HealthMetric: Modular health_metric/ package (copied from remote_revit_server)

Process Flow:
1. Read job payload from JSON (orchestrator writes this)
2. Open cloud model using GUIDs (model_guid, project_guid, version)
3. Run HealthMetric checks
4. Write results to JSON
5. Write status updates (for monitoring)
6. Close Revit cleanly

Status Stages:
- started: Script execution began
- opening: Opening cloud model
- opened: Model opened successfully
- analyzing: Running health metrics
- completed: Job finished successfully
- failed: Error occurred (with error message)

Learn from:
- remote_revit_server_script.py (HealthMetric integration)
- AutoExporter revit_server_entry_script.py (structure)
"""

from Autodesk.Revit import DB # pyright: ignore 
import os
import json
import time
import traceback
from datetime import datetime
import threading

# =============================================================================
# ERROR LOOP DETECTION AND TIMEOUT PROTECTION (adapted from AutoExporter)
# =============================================================================

class ErrorLoopDetector:
    """Detect and prevent infinite error loops."""
    def __init__(self, max_same_error=10, time_window=60):
        self.error_history = []
        self.max_same_error = max_same_error
        self.time_window = time_window

    def record_error(self, error_message):
        """Record an error and detect loops within time window."""
        now = time.time()

        # Keep only recent errors
        self.error_history = [
            (msg, ts) for msg, ts in self.error_history if now - ts < self.time_window
        ]

        # Add new error
        self.error_history.append((error_message, now))

        # Check for repetition
        recent_messages = [msg for msg, _ in self.error_history]
        if recent_messages.count(error_message) >= self.max_same_error:
            raise RuntimeError(
                "Error loop detected: '{}' occurred {} times in {}s".format(
                    error_message, recent_messages.count(error_message), self.time_window
                )
            )

    def reset(self):
        self.error_history = []


class OperationTimeout:
    """Enforce timeouts on operations to prevent hangs."""
    def __init__(self, timeout_seconds):
        self.timeout_seconds = timeout_seconds
        self.timer = None
        self.timed_out = False

    def __enter__(self):
        def timeout_handler():
            self.timed_out = True
            print("Operation timed out after {}s".format(self.timeout_seconds))

        self.timer = threading.Timer(self.timeout_seconds, timeout_handler)
        self.timer.start()
        return self

    def __exit__(self, *args):
        if self.timer:
            self.timer.cancel()

        if self.timed_out:
            raise TimeoutError(
                "Operation exceeded {}s timeout. Possible infinite loop or hung dialog.".format(
                    self.timeout_seconds
                )
            )

# =============================================================================
# CONSTANTS
# =============================================================================

JOB_PAYLOAD_FILENAME = "current_job.sexyDuck"  # Match RevitSlave2 naming

# Global variables for monitoring paths (set after loading job payload)
_JOB_ID = None
_DATABASE_FOLDER = None

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _script_dir():
    """Get script directory"""
    return os.path.dirname(os.path.abspath(__file__))

def _parent_dir():
    """Get parent directory (RevitSlave-3.0 root)"""
    return os.path.dirname(_script_dir())

def _join(*parts):
    """Join path parts"""
    return os.path.join(*parts)

def _load_json(path):
    """Load JSON file"""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print("ERROR: Failed to load JSON from {}: {}".format(path, str(e)))
        return None

def _save_json(path, data):
    """Save JSON file"""
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print("ERROR: Failed to save JSON to {}: {}".format(path, str(e)))
        return False

def _write_status(status, message="", error=None, job_payload=None):
    """
    Write job status for monitoring with enhanced diagnostic information
    
    Args:
        status: Status string (started, opening, opened, analyzing, completed, failed)
        message: Status message
        error: Error details if failed
        job_payload: Optional job payload for diagnostic info
    """
    # Use database folder and job_id if available
    if _DATABASE_FOLDER and _JOB_ID:
        status_path = _join(_DATABASE_FOLDER, "job_status_{}.json".format(_JOB_ID))
    else:
        # Fallback to parent directory for early status before payload is loaded
        status_path = _join(_parent_dir(), "current_job_status.json")
    
    status_data = {
        "status": status,
        "message": message,
        "timestamp": datetime.now().isoformat(),
        "error": error
    }
    
    # Add diagnostic information if job_payload is available
    if job_payload:
        status_data["diagnostics"] = {
            "project_guid": job_payload.get("project_guid"),
            "model_guid": job_payload.get("model_guid"),
            "version": job_payload.get("revit_version"),
            "project_name": job_payload.get("project_name"),
            "model_name": job_payload.get("model_name"),
            "job_id": job_payload.get("job_id")
        }
    
    _save_json(status_path, status_data)
    print("STATUS: {} - {}".format(status.upper(), message))

def _write_heartbeat(message, progress=0):
    """
    Write heartbeat for monitoring (optional, enhanced monitoring)
    
    Args:
        message: Progress message
        progress: Progress percentage (0-100)
    """
    # Only write if we have database folder and job_id
    if not _DATABASE_FOLDER or not _JOB_ID:
        return
    
    heartbeat_path = _join(_DATABASE_FOLDER, "revit_heartbeat_{}.txt".format(_JOB_ID))
    
    # Write as simple text file with just ISO timestamp (job_monitor expects plain timestamp)
    try:
        timestamp = datetime.now().isoformat()
        with open(heartbeat_path, 'w') as f:
            f.write(timestamp)  # Just timestamp, no formatting
        # Print message for console logging
        print("HEARTBEAT: {} ({}%)".format(message, progress))
    except Exception as e:
        print("WARNING: Failed to write heartbeat: {}".format(str(e)))


def _crash_tracker_path():
    """Get path to crash tracker / metric debug file."""
    return _join(_parent_dir(), "current_check.txt")


def _clear_crash_tracker():
    """Remove crash tracker file if it exists."""
    path = _crash_tracker_path()
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            print("WARNING: Failed to remove crash tracker: {}".format(str(e)))


def _write_metric_debug_report(entries):
    """Write detailed metric run information for debugging purposes."""
    if not entries:
        _clear_crash_tracker()
        return

    # If every metric completed successfully, clear the tracker (no debug noise)
    if all(entry.get("status") == "completed" for entry in entries):
        _clear_crash_tracker()
        return

    path = _crash_tracker_path()
    lines = [
        "Health Metric Debug Report",
        "Timestamp: {}".format(datetime.now().isoformat()),
        "Total metrics tracked: {}".format(len(entries)),
        "",
    ]

    for entry in entries:
        lines.append("Metric: {}".format(entry.get("name", "<unknown>")))
        lines.append("  Status: {}".format(entry.get("status", "<unknown>")))
        if entry.get("execution_time") is not None:
            lines.append("  Execution Time: {:.2f}s".format(entry["execution_time"]))
        if entry.get("error"):
            lines.append("  Error: {}".format(entry["error"]))
        if entry.get("started_at"):
            lines.append("  Started: {}".format(entry["started_at"]))
        if entry.get("ended_at"):
            lines.append("  Ended: {}".format(entry["ended_at"]))
        lines.append("")

    try:
        with open(path, 'w') as f:
            f.write("\n".join(lines))
    except Exception as e:
        print("WARNING: Failed to write metric debug report: {}".format(str(e)))

# =============================================================================
# CLOUD MODEL OPENING
# =============================================================================

def open_cloud_model(job_payload):
    """
    Open cloud model using GUIDs from job payload
    
    Args:
        job_payload: Job payload dict with model_guid, project_guid, revit_version
        
    Returns:
        Revit Document object or None if failed
    """
    model_guid = job_payload.get("model_guid")
    project_guid = job_payload.get("project_guid")
    model_name = job_payload.get("model_name", "Unknown")
    
    # Validate GUIDs format
    if not model_guid or not project_guid:
        raise Exception("Missing model_guid or project_guid in job payload")
    
    # Validate GUID format (basic check)
    if len(model_guid) < 32 or len(project_guid) < 32:
        raise Exception("Invalid GUID format - model_guid: {}, project_guid: {}".format(model_guid, project_guid))
    
    print("Opening cloud model...")
    print("  Model: {}".format(model_name))
    print("  Model GUID: {}".format(model_guid))
    print("  Project GUID: {}".format(project_guid))
    
    _write_status("opening", "Opening cloud model via GUIDs...")
    _write_heartbeat("Connecting to Autodesk cloud...", 10)
    
    # Step-by-step heartbeat tracking during opening
    _write_heartbeat("Step 2.1: Building cloud path for model...", 15)
    
    try:
        # Get UIApplication
        uiapp = __revit__ # pyright: ignore
        app = uiapp.Application
        
        # Create cloud model path
        from Autodesk.Revit.DB import ModelPathUtils
        import System
        
        # Collect available cloud regions - EXPLICITLY include all regions (US, EMEA, APAC)
        # Pattern learned from AutoExporter and plugin_startup.py
        candidate_regions = []
        
        # Explicitly add all known regions to ensure comprehensive coverage
        if hasattr(ModelPathUtils, 'CloudRegionUS'):
            candidate_regions.append(ModelPathUtils.CloudRegionUS)
            print("  Found region constant: CloudRegionUS")
        
        if hasattr(ModelPathUtils, 'CloudRegionEMEA'):
            candidate_regions.append(ModelPathUtils.CloudRegionEMEA)
            print("  Found region constant: CloudRegionEMEA")
        
        if hasattr(ModelPathUtils, 'CloudRegionAPAC'):
            candidate_regions.append(ModelPathUtils.CloudRegionAPAC)
            print("  Found region constant: CloudRegionAPAC")
        else:
            # CRITICAL: Revit 2024 and earlier don't have APAC constant
            # Add APAC as string literal for older Revit versions
            if candidate_regions:  # Only if we found some constants (2024 has US/EMEA)
                candidate_regions.append("APAC")
                print("  CloudRegionAPAC constant not found - adding 'APAC' string for Revit 2024 compatibility")
        
        # Fallback: scan all CloudRegion attributes if explicit ones not found
        if not candidate_regions:
            print("  CloudRegion constants not found, scanning attributes...")
            region_attrs = [a for a in dir(ModelPathUtils) if a.startswith("CloudRegion")]
            for attr in region_attrs:
                try:
                    region_value = getattr(ModelPathUtils, attr)
                    candidate_regions.append(region_value)
                    print("  Found region: {} = {}".format(attr, region_value))
                except Exception as e:
                    print("  Failed to get region {}: {}".format(attr, e))
                    continue
        
        # String fallbacks for very old Revit versions (include ALL regions)
        if not candidate_regions:
            print("  WARNING: No CloudRegion constants found, using string fallbacks for all regions")
            candidate_regions = ["US", "EMEA", "APAC"]
        
        print("  Total regions to try: {} - {}".format(len(candidate_regions), candidate_regions))
        
        # Try cloud path creation with each region (AutoExporter pattern)
        cloud_path = None
        last_error = None
        successful_region = None
        
        for idx, region in enumerate(candidate_regions):
            try:
                print("  Attempt {}/{}: Trying region '{}'...".format(idx + 1, len(candidate_regions), region))
                
                # Validate GUID format before attempting
                try:
                    guid_project = System.Guid(project_guid)
                    guid_model = System.Guid(model_guid)
                except Exception as guid_error:
                    print("  ERROR: Invalid GUID format - {}".format(str(guid_error)))
                    raise Exception("Invalid GUID format: project={}, model={}".format(project_guid, model_guid))
                
                cloud_path = ModelPathUtils.ConvertCloudGUIDsToCloudPath(
                    region,
                    guid_project,
                    guid_model
                )
                successful_region = region
                print("  SUCCESS: Cloud path created with region '{}'".format(region))
                break
            except Exception as e:
                last_error = e
                error_str = str(e)
                print("  Region '{}' failed: {}".format(region, error_str))
                
                # Check for specific error types
                if "missing" in error_str.lower():
                    print("    -> Model not found in '{}' region (may be in different region or deleted)".format(region))
                elif "guid" in error_str.lower() or "format" in error_str.lower():
                    print("    -> GUID format issue - check if GUIDs are correct")
                elif "permission" in error_str.lower() or "access" in error_str.lower():
                    print("    -> Access permission issue - check user permissions")
                
                continue
        
        if cloud_path is None:
            error_msg = "Failed to create cloud path with any region.\nModel: {}\nRegions tried: {}\nLast error: {}\n\nPossible causes:\n- Model deleted/archived in ACC\n- Incorrect GUIDs (try --force-refresh)\n- Access permissions issue\n- Model in unsupported region".format(
                model_name, candidate_regions, last_error
            )
            raise Exception(error_msg)
        
        print("  Cloud path created successfully using region: '{}'".format(successful_region))
        
        print("  Cloud path: {}".format(cloud_path))
        _write_heartbeat("Step 2.2: Cloud path created successfully", 20)

        # Helper to log worksharing state after open
        def _log_doc_worksharing_state(doc_obj, detach_mode):
            doc_workshared = None
            doc_detached = None
            try:
                doc_workshared = bool(getattr(doc_obj, "IsWorkshared", False))
            except Exception as ws_err:
                print("  WARNING: Unable to read Document.IsWorkshared: {}".format(ws_err))
            try:
                doc_detached = getattr(doc_obj, "IsDetached", None)
            except Exception:
                doc_detached = None
            
            print("  Document.IsWorkshared -> {}".format(doc_workshared))
            if doc_detached is not None:
                print("  Document.IsDetached -> {}".format(doc_detached))
            
            if detach_mode and doc_workshared is False:
                print("  NOTE: Document reported as non-workshared after detach request (model may be single-user).")
            return doc_workshared, doc_detached

        # Determine worksharing status before opening to enforce detach requirements
        is_workshared_model = None
        try:
            is_workshared_model = DB.WorksharingUtils.IsModelWorkshared(cloud_path)
            print("  Worksharing status (pre-open): {}".format(is_workshared_model))
        except Exception as ws_err:
            is_workshared_model = None
            print("  WARNING: Could not determine worksharing status via WorksharingUtils: {}".format(ws_err))
        
        prefer_detach = True if is_workshared_model is not False else False
        if prefer_detach:
            print("  Opening strategy: DETACH and preserve worksets (workshared model enforcement)")
        else:
            print("  Opening strategy: Standard open (determine: model not workshared)")
        
        # Workset configuration - open all worksets
        workset_config = DB.WorksetConfiguration(DB.WorksetConfigurationOption.OpenAllWorksets)

        # Create shared open options
        open_options_normal = DB.OpenOptions()
        open_options_normal.Audit = True
        open_options_normal.SetOpenWorksetsConfiguration(workset_config)

        open_options_detached = None
        if prefer_detach:
            _write_heartbeat("Step 2.3: Configuring open options (detached, audit, all worksets)...", 25)
            open_options_detached = DB.OpenOptions()
            open_options_detached.DetachFromCentralOption = DB.DetachFromCentralOption.DetachAndPreserveWorksets
            open_options_detached.Audit = True
            open_options_detached.SetOpenWorksetsConfiguration(workset_config)
            print("  Opening with options: DETACHED (required), Audit=True, AllWorksets=True")
            print("  Detached mode prevents ownership lock conflicts (workshared models)")
        else:
            _write_heartbeat("Step 2.3: Configuring open options (standard, audit)...", 25)
            print("  Opening with options: STANDARD, Audit=True")
        
        _write_heartbeat("Step 2.4: Initiating document download and open from ACC (this may take 3-10 min for large models)", 30)
        
        doc = None
        primary_error = None
        
        if prefer_detach:
            try:
                print("  Attempting OpenDocumentFile with DETACH (primary method)...")
                _write_heartbeat("Step 2.5: Attempting OpenDocumentFile with DETACH...", 50)
                
                doc = app.OpenDocumentFile(cloud_path, open_options_detached)
                
                if doc is None:
                    raise Exception("OpenDocumentFile returned None")
                
                print("  SUCCESS: Model opened via OpenDocumentFile (DETACHED) - {}".format(doc.Title))
                doc_workshared, doc_detached = _log_doc_worksharing_state(doc, detach_mode=True)
                _write_status(
                    "opened",
                    "Model opened successfully (detached): {} [workshared={}, detached={}]".format(
                        doc.Title, doc_workshared, doc_detached
                    )
                )
                _write_heartbeat("Step 2.6: Document opened successfully via OpenDocumentFile (DETACHED) - {}".format(doc.Title), 70)
                
                return doc
            
            except Exception as e:
                primary_error = str(e)
                print("  OpenDocumentFile with DETACH failed: {}".format(primary_error))
            
            _write_heartbeat("Step 2.6: Primary detach method failed, trying OpenAndActivateDocument with DETACH (fallback)...", 60)
            
            try:
                print("  Attempting OpenAndActivateDocument with DETACH (fallback method)...")
                uidoc = uiapp.OpenAndActivateDocument(cloud_path, open_options_detached, False)
                doc = uidoc.Document
                
                print("  SUCCESS: Model opened via OpenAndActivateDocument (DETACHED) - {}".format(doc.Title))
                doc_workshared, doc_detached = _log_doc_worksharing_state(doc, detach_mode=True)
                _write_status(
                    "opened",
                    "Model opened successfully (fallback, detached): {} [workshared={}, detached={}]".format(
                        doc.Title, doc_workshared, doc_detached
                    )
                )
                _write_heartbeat("Step 2.7: Document opened successfully via OpenAndActivateDocument (DETACHED) - {}".format(doc.Title), 70)
                
                return doc
            except Exception as e2:
                fallback_error = str(e2)
                print("  OpenAndActivateDocument with DETACH failed: {}".format(fallback_error))
                
                error_msg = "Failed to detach-open workshared model. Primary: {} | Fallback: {}".format(primary_error, fallback_error)
                print("  FAILED: {}".format(error_msg))
                raise Exception(error_msg)
        else:
            try:
                print("  Attempting OpenDocumentFile without detach (non-workshared model)...")
                _write_heartbeat("Step 2.5: Attempting OpenDocumentFile (standard)...", 50)
                
                doc = app.OpenDocumentFile(cloud_path, open_options_normal)
                
                if doc is None:
                    raise Exception("OpenDocumentFile returned None")
                
                # Safety: if model reports workshared, enforce detach requirement
                try:
                    if getattr(doc, "IsWorkshared", False):
                        raise Exception("Model reported as workshared after standard open - detach is required")
                except AttributeError:
                    pass
                
                print("  SUCCESS: Model opened via OpenDocumentFile (standard) - {}".format(doc.Title))
                doc_workshared, doc_detached = _log_doc_worksharing_state(doc, detach_mode=False)
                _write_status(
                    "opened",
                    "Model opened successfully (standard): {} [workshared={}, detached={}]".format(
                        doc.Title, doc_workshared, doc_detached
                    )
                )
                _write_heartbeat("Step 2.6: Document opened successfully via OpenDocumentFile (standard) - {}".format(doc.Title), 70)
                
                return doc
            except Exception as e:
                primary_error = str(e)
                print("  OpenDocumentFile (standard) failed: {}".format(primary_error))
            
            _write_heartbeat("Step 2.6: Primary standard method failed, trying OpenAndActivateDocument (standard fallback)...", 60)
            
            try:
                print("  Attempting OpenAndActivateDocument without detach (fallback)...")
                uidoc = uiapp.OpenAndActivateDocument(cloud_path, open_options_normal, False)
                doc = uidoc.Document
                
                try:
                    if getattr(doc, "IsWorkshared", False):
                        # Close the document before raising to avoid locking central
                        try:
                            doc.Close(False)
                        except Exception as close_err:
                            print("  WARNING: Failed to close workshared document opened without detach: {}".format(close_err))
                        raise Exception("Model reported as workshared after fallback standard open - detach is required")
                except AttributeError:
                    pass
                
                print("  SUCCESS: Model opened via OpenAndActivateDocument (standard) - {}".format(doc.Title))
                doc_workshared, doc_detached = _log_doc_worksharing_state(doc, detach_mode=False)
                _write_status(
                    "opened",
                    "Model opened successfully (fallback, standard): {} [workshared={}, detached={}]".format(
                        doc.Title, doc_workshared, doc_detached
                    )
                )
                _write_heartbeat("Step 2.7: Document opened successfully via OpenAndActivateDocument (standard) - {}".format(doc.Title), 70)
                
                return doc
            except Exception as final_e:
                error_msg = "All standard open methods failed. Primary: {} | Fallback: {}".format(primary_error, str(final_e))
                print("  FAILED: {}".format(error_msg))
                raise Exception(error_msg)
        
    except Exception as e:
        error_msg = "Failed to open cloud model: {}".format(str(e))
        print("ERROR: {}".format(error_msg))
        print("Traceback: {}".format(traceback.format_exc()))
        _write_status("failed", error_msg, traceback.format_exc())
        raise

# =============================================================================
# HEALTH METRIC INTEGRATION
# =============================================================================

def safe_metric_check(metric_name, metric_func, doc, timeout_seconds=300):
    """
    Safely run a health metric check with timeout protection.
    Pattern adapted from AutoExporter's OperationTimeout usage.

    Returns: dict with status, data, error, execution_time
    """
    start_time = time.time()
    result = {"status": "pending", "data": None, "error": None, "execution_time": 0}

    print("  [METRIC START] {}".format(metric_name))
    _write_heartbeat("Starting metric: {}".format(metric_name))

    try:
        # Validate document is still available and open
        if doc is None:
            raise Exception("Document is None")
        
        try:
            if doc.IsClosed:
                raise Exception("Document is closed")
        except:
            pass  # Some doc versions may not have IsClosed
        
        with OperationTimeout(timeout_seconds):
            metric_result = metric_func(doc)
            result["status"] = "completed"
            result["data"] = metric_result
            
            elapsed = time.time() - start_time
            print("  [METRIC OK] {} completed in {:.1f}s".format(metric_name, elapsed))
            
            # Warn if metric took > 30 seconds (user threshold for fast completion)
            if elapsed > 30:
                print("  [WARNING] Metric took >{} seconds - may indicate issue (user threshold: 30s)".format(int(elapsed)))
                
    except TimeoutError:
        result["status"] = "timeout"
        result["error"] = "Timeout after {}s".format(timeout_seconds)
        print("  [METRIC TIMEOUT] {} after {}s".format(metric_name, timeout_seconds))
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        error_str = str(e)
        print("  [METRIC FAILED] {}: {}".format(metric_name, error_str))
        
        # Add context for common errors
        if "closed" in error_str.lower():
            print("    -> Document was closed during metric execution")
        elif "null" in error_str.lower() or "none" in error_str.lower():
            print("    -> Null reference error - element may not exist")
    finally:
        result["execution_time"] = time.time() - start_time

    return result

def run_health_metrics(doc, job_payload):
    """
    Run health metrics with per-metric timeout protection and graceful degradation.
    Returns (health_report, error_message). error_message is None if success rate >= 70%.
    """
    _write_status("analyzing", "Running health metrics with per-metric timeouts...")
    _write_heartbeat("Analyzing model health...", 75)

    if doc is None:
        error_msg = "No active document available"
        print("ERROR: {}".format(error_msg))
        return {"error": error_msg, "checks": {}}, error_msg

    # Import check modules locally to avoid import errors at file load
    print("  [INIT] Importing health metric modules...")
    _write_heartbeat("Importing health check modules...", 55)
    
    try:
        from health_metric import (
            project_checks,
            linked_files_checks,
            elements_checks,
            views_checks,
            templates_checks,
            cad_checks,
            families_checks,
            graphical_checks,
            groups_checks,
            reference_checks,
            materials_checks,
            warnings_checks,
            file_checks,
            regions_checks,
        )
        print("  [OK] All health metric modules imported successfully")
        _write_heartbeat("Modules loaded, starting checks...", 60)
    except Exception as import_ex:
        error_msg = "Failed to import health_metric modules: {}".format(str(import_ex))
        print(error_msg)
        return {"error": error_msg, "checks": {}}, error_msg

    # Define metrics with timeouts (seconds)
    metrics_to_run = [
        ("project_info", project_checks.check_project_info, 120),
        ("linked_files", linked_files_checks.check_linked_files, 180),
        ("critical_elements", elements_checks.check_critical_elements, 180),
        ("rooms", elements_checks.check_rooms, 120),
        ("views_sheets", views_checks.check_sheets_views, 180),
        ("templates_filters", templates_checks.check_templates_filters, 180),  # RE-ENABLED: Accepting longer runtime for large cloud models (5-15 min total)
        ("cad_files", cad_checks.check_cad_files, 180),
        ("families", families_checks.check_families, 180),
        ("graphical_elements", graphical_checks.check_graphical_elements, 180),
        ("groups", groups_checks.check_groups, 120),
        ("reference_planes", reference_checks.check_reference_planes, 120),
        ("materials", materials_checks.check_materials, 120),
        ("line_count", materials_checks.check_line_count, 120),
        ("warnings", warnings_checks.check_warnings, 300),
        ("file_size", file_checks.check_file_size, 60),
        ("filled_regions", regions_checks.check_filled_regions, 120),
        ("grids_levels", reference_checks.check_grids_levels, 120),
    ]

    error_detector = ErrorLoopDetector(max_same_error=5, time_window=30)
    successful_metrics = 0
    total_metrics = len(metrics_to_run)
    metric_failures = []
    metrics_debug_entries = []

    health_report = {
        "version": "v2",
        "timestamp": datetime.now().isoformat(),
        "document_title": doc.Title if hasattr(doc, 'Title') else "Unknown",
        "is_EnneadTab_Available": False,
        "checks": {},
    }

    for idx, (metric_name, metric_func, timeout) in enumerate(metrics_to_run, 1):
        print("[METRIC {}/{}] {}".format(idx, total_metrics, metric_name))
        _write_status("analyzing", "Metric {}/{}: {}".format(idx, total_metrics, metric_name))

        metric_entry = {
            "name": metric_name,
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "execution_time": None,
            "error": None,
        }
        metrics_debug_entries.append(metric_entry)
        _write_metric_debug_report(metrics_debug_entries)

        result = safe_metric_check(metric_name, metric_func, doc, timeout_seconds=timeout)
        result_status = result.get("status", "unknown")

        metric_entry["status"] = result_status
        metric_entry["execution_time"] = result.get("execution_time")
        metric_entry["error"] = result.get("error")
        metric_entry["ended_at"] = datetime.now().isoformat()
        _write_metric_debug_report(metrics_debug_entries)

        health_report["checks"][metric_name] = result

        if result["status"] == "completed":
            successful_metrics += 1
            error_detector.reset()
            _write_heartbeat("Metric {} complete ({}/{})".format(metric_name, idx, total_metrics))
        elif result["status"] == "timeout":
            failure_detail = "Timeout after {}s".format(timeout)
            print("[METRIC WARNING] {} timed out: {}".format(metric_name, failure_detail))
            metric_failures.append((metric_name, "timeout", failure_detail))
            error_detector.record_error("Timeout: {}".format(metric_name))
            _write_status(
                "analyzing",
                "Metric {} timed out ({}/{})".format(metric_name, idx, total_metrics),
                failure_detail,
            )
            _write_heartbeat("Metric {} timed out ({}/{})".format(metric_name, idx, total_metrics))
        elif result["status"] == "failed":
            error_detail = result["error"] or "Unknown error"
            print("[METRIC WARNING] {} failed: {}".format(metric_name, error_detail))
            metric_failures.append((metric_name, "failed", error_detail))
            error_detector.record_error(error_detail)
            _write_status(
                "analyzing",
                "Metric {} failed ({}/{})".format(metric_name, idx, total_metrics),
                error_detail,
            )
            _write_heartbeat("Metric {} failed ({}/{})".format(metric_name, idx, total_metrics))
        else:
            # Unknown status - treat as failure for visibility
            detail = result.get("error") or "Status '{}'".format(result_status)
            print("[METRIC WARNING] {} returned unexpected status: {}".format(metric_name, result_status))
            metric_failures.append((metric_name, result_status, detail))
            error_detector.record_error(detail)
            _write_status(
                "analyzing",
                "Metric {} unexpected status ({}/{})".format(metric_name, idx, total_metrics),
                detail,
            )
            _write_heartbeat("Metric {} encountered unexpected status ({}/{})".format(metric_name, idx, total_metrics))

    # Graceful degradation: Success if >= 70% completed
    success_rate = float(successful_metrics) / total_metrics if total_metrics else 0.0
    if success_rate >= 0.70:
        print("[SUCCESS] {:.0%} metrics completed".format(success_rate))
        _write_heartbeat("Health metrics completed", 95)
        if metric_failures:
            summary_message = ", ".join("{}: {}".format(name, status) for name, status, _ in metric_failures)
            _write_status("analyzing", "Completed with warnings", summary_message)
        else:
            _clear_crash_tracker()
        return health_report, None
    else:
        error_msg = "Too many failures: {:.0%} success".format(success_rate)
        print("[FAILED] {}".format(error_msg))
        if metric_failures:
            failure_summary_lines = ["{} - {} ({})".format(name, status, detail) for name, status, detail in metric_failures]
            _write_status("analyzing", "Health metrics issues", "\n".join(failure_summary_lines))
        _write_metric_debug_report(metrics_debug_entries)
        return health_report, error_msg

# =============================================================================
# HELPER FUNCTIONS FOR OUTPUT
# =============================================================================

def _get_file_size_info(doc):
    """Get file size information from document"""
    try:
        if doc and hasattr(doc, 'PathName') and doc.PathName:
            path = doc.PathName
            if os.path.exists(path):
                size_bytes = os.path.getsize(path)
                size_mb = size_bytes / (1024.0 * 1024.0)
                if size_mb < 1024:
                    size_readable = "{:.1f} MB".format(size_mb)
                else:
                    size_readable = "{:.2f} GB".format(size_mb / 1024.0)
                return {
                    "size_bytes": size_bytes,
                    "size_readable": size_readable
                }
        # Default values if can't get file size
        return {"size_bytes": 0, "size_readable": "Unknown"}
    except:
        return {"size_bytes": 0, "size_readable": "Unknown"}

def _format_time(seconds):
    """Format time in readable format (matching RevitSlave2)"""
    if seconds < 60:
        return "{:.1f}s".format(seconds)
    elif seconds < 3600:
        minutes = seconds / 60.0
        return "{:.1f}m".format(minutes)
    else:
        hours = seconds / 3600.0
        return "{:.1f}h".format(hours)

def _format_output_filename(job_payload):
    """Format output filename (matching RevitSlave2)"""
    job_id = job_payload.get("job_id", "unknown_job")
    return "{}.sexyDuck".format(job_id)

# =============================================================================
# RESULT WRITING (Matching RevitSlave2 Structure)
# =============================================================================

def write_failure_marker(job_payload, error_message, failure_stage):
    """
    Write failure marker file when job fails to prevent empty folders.
    
    Args:
        job_payload: Original job payload
        error_message: Error message describing failure
        failure_stage: Stage where failure occurred (e.g., "opening", "processing", "timeout")
    
    Returns:
        bool: True if marker written successfully
    """
    try:
        # Get paths from job payload
        paths = job_payload.get('paths', {})
        if not paths or not paths.get('task_output_dir'):
            print("WARNING: Cannot write failure marker - no task_output_dir")
            return False
        
        task_output_dir = paths['task_output_dir']
        if not os.path.exists(task_output_dir):
            os.makedirs(task_output_dir)
        
        # Generate failure marker filename
        job_id = job_payload.get("job_id", "unknown_job")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        marker_filename = "FAILED_{}_{}_{}.txt".format(failure_stage, job_id, timestamp)
        marker_path = _join(task_output_dir, marker_filename)
        
        # Write failure details
        with open(marker_path, 'w') as f:
            f.write("RevitSlave4 Job Failure Report\n")
            f.write("=" * 80 + "\n\n")
            f.write("Job ID: {}\n".format(job_id))
            f.write("Model: {}\n".format(job_payload.get("model_name", "Unknown")))
            f.write("Project: {}\n".format(job_payload.get("project_name", "Unknown")))
            f.write("Hub: {}\n".format(job_payload.get("hub_name", "Unknown")))
            f.write("Revit Version: {}\n".format(job_payload.get("revit_version", "Unknown")))
            f.write("Timestamp: {}\n".format(datetime.now().isoformat()))
            f.write("Failure Stage: {}\n".format(failure_stage))
            f.write("\nError Message:\n")
            f.write("-" * 80 + "\n")
            f.write("{}\n".format(error_message))
            f.write("-" * 80 + "\n")
        
        print("FAILURE MARKER: Written to {}".format(marker_path))
        return True
        
    except Exception as e:
        print("ERROR: Failed to write failure marker: {}".format(e))
        return False


def write_results(job_payload, health_report, error_message, doc, execution_time):
    """
    Write job results in RevitSlave2 format
    
    Args:
        job_payload: Original job payload
        health_report: HealthMetric report dict
        error_message: Error message if health metric had issues
        doc: Revit Document (for file size)
        execution_time: Total execution time in seconds
    """
    # Get paths from job payload (required by RevitSlave2)
    paths = job_payload.get('paths', {})
    if not paths or not paths.get('task_output_dir'):
        print("ERROR: Job payload missing 'paths' section with 'task_output_dir'")
        # Fallback to local directory
        task_output_dir = _join(_parent_dir(), "task_output")
        if not os.path.exists(task_output_dir):
            os.makedirs(task_output_dir)
    else:
        task_output_dir = paths['task_output_dir']
        if not os.path.exists(task_output_dir):
            os.makedirs(task_output_dir)
    
    # Get file size
    file_size_info = _get_file_size_info(doc)
    
    # Build output payload (EXACTLY matching RevitSlave2 structure)
    output_payload = {
        "job_metadata": {
            "job_id": job_payload.get("job_id"),
            "hub_name": job_payload.get("hub_name"),
            "project_name": job_payload.get("project_name"),
            "model_name": job_payload.get("model_name"),  # Note: model_name not file_name
            "model_file_size_bytes": file_size_info["size_bytes"],
            "model_file_size_readable": file_size_info["size_readable"],
            "revit_version": job_payload.get("revit_version"),
            "timestamp": datetime.now().isoformat(),
            "execution_time_seconds": round(execution_time, 2),
            "execution_time_readable": _format_time(execution_time)
        },
        "health_metric_result": health_report,  # Matching RevitSlave2 field name
        "export_data": None,  # RevitSlave4 doesn't export yet, but keep field for compatibility
        "status": "completed" + (" with error" if error_message else "")
    }
    
    # Generate filename (matching RevitSlave2)
    out_name = _format_output_filename(job_payload)
    out_path = _join(task_output_dir, out_name)
    
    # Write output file
    if _save_json(out_path, output_payload):
        print("SUCCESS: Output saved to {}".format(out_path))
        return True
    else:
        print("ERROR: Failed to write output file")
        return False

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point for RevitSlave4 Revit script"""
    start_time = time.time()
    
    # IMMEDIATE DEBUG LOG - write before loading job payload
    # Will write to repo DEBUG folder initially, then to job-specific log_dir after loading payload
    try:
        # Temporary location before job payload is loaded
        debug_folder_temp = _join(_parent_dir(), "DEBUG", "logs")
        if not os.path.exists(debug_folder_temp):
            os.makedirs(debug_folder_temp)
        
        debug_startup_path = _join(debug_folder_temp, "SCRIPT_STARTED_{}.txt".format(datetime.now().strftime("%Y%m%d_%H%M%S")))
        with open(debug_startup_path, 'w') as f:
            f.write("RevitSlave4 Entry Script Started\n")
            f.write("Timestamp: {}\n".format(datetime.now().isoformat()))
            f.write("Script Path: {}\n".format(_script_dir()))
            f.write("Parent Dir: {}\n".format(_parent_dir()))
        print("DEBUG: Startup log written to: {}".format(debug_startup_path))
    except Exception as debug_err:
        print("WARNING: Could not write startup debug log: {}".format(debug_err))
    
    print("")
    print("="*80)
    print("RevitSlave4 Entry Script")
    print("="*80)
    print("")
    
    _write_status("started", "Script execution began - Revit is ready")
    _write_heartbeat("Revit launched successfully, loading job configuration...", 5)
    
    try:
        # Step 1: Load job payload
        print("[STEP 1] Loading job payload...")
        payload_path = _join(_script_dir(), JOB_PAYLOAD_FILENAME)
        
        if not os.path.exists(payload_path):
            raise Exception("Job payload not found: {}".format(payload_path))
        
        job_payload = _load_json(payload_path)
        if not job_payload:
            raise Exception("Failed to load job payload")
        
        # Set global monitoring variables for status and heartbeat writing
        global _JOB_ID, _DATABASE_FOLDER
        _JOB_ID = job_payload.get("job_id")
        paths = job_payload.get("paths", {})
        _DATABASE_FOLDER = paths.get("database_folder")
        
        print("Job ID: {}".format(job_payload.get("job_id")))
        print("Project: {}".format(job_payload.get("project_name")))
        print("Model: {}".format(job_payload.get("model_name")))
        print("Model GUID: {}".format(job_payload.get("model_guid")))
        print("Project GUID: {}".format(job_payload.get("project_guid")))
        print("Version: {}".format(job_payload.get("revit_version")))
        
        # Now write startup log to the job-specific log_dir
        try:
            paths = job_payload.get('paths', {})
            log_dir = paths.get('log_dir')
            if log_dir and os.path.exists(log_dir):
                job_startup_path = _join(log_dir, "SCRIPT_STARTED_{}.txt".format(datetime.now().strftime("%Y%m%d_%H%M%S")))
                with open(job_startup_path, 'w') as f:
                    f.write("RevitSlave4 Entry Script Started\n")
                    f.write("Timestamp: {}\n".format(datetime.now().isoformat()))
                    f.write("Job ID: {}\n".format(_JOB_ID))
                    f.write("Project: {}\n".format(job_payload.get("project_name")))
                    f.write("Model: {}\n".format(job_payload.get("model_name")))
                print("Job startup log written to: {}".format(job_startup_path))
        except Exception as log_err:
            print("WARNING: Could not write job startup log: {}".format(log_err))
        
        # Update status: Revit is ready, about to open cloud model
        _write_status("revit_ready", "Revit launched successfully, preparing to open cloud model (may take 3-10 minutes)", job_payload=job_payload)
        _write_heartbeat("Job configured, starting cloud model download...", 8)
        
        # Step 2: Open cloud model
        print("")
        print("[STEP 2] Opening cloud model...")
        print("  Detailed Info:")
        print("    Model GUID: {}".format(job_payload.get("model_guid")))
        print("    Project GUID: {}".format(job_payload.get("project_guid")))
        print("    File: {}".format(job_payload.get("model_name")))
        
        try:
            doc = open_cloud_model(job_payload)
            print("  [SUCCESS] Model opened successfully: {}".format(doc.Title if doc else "Unknown"))
            
            # IMMEDIATE status update after successful open (before health metrics)
            _write_status("opened_success", "Model opened: {}".format(doc.Title if doc else "Unknown"), job_payload=job_payload)
            _write_heartbeat("Model opened, preparing health metrics...", 50)
            
        except Exception as open_err:
            error_msg = "Failed to open cloud model: {}".format(str(open_err))
            error_tb = traceback.format_exc()
            print("  [FAILED] {}".format(error_msg))
            print("  Traceback:")
            print(error_tb)
            
            # Write failure marker to prevent empty folder
            write_failure_marker(job_payload, "{}\n\nTraceback:\n{}".format(error_msg, error_tb), "opening")
            
            # Write detailed error to task output folder (or job debug_dir if not available)
            paths = job_payload.get('paths', {})
            task_output_dir = paths.get('task_output_dir')
            debug_dir = paths.get('debug_dir')
            
            if task_output_dir and os.path.exists(task_output_dir):
                error_file = _join(task_output_dir, "OPEN_ERROR_{}.txt".format(_JOB_ID or "unknown"))
            elif debug_dir and os.path.exists(debug_dir):
                # Fallback to job-specific debug folder
                error_file = _join(debug_dir, "OPEN_ERROR_{}.txt".format(_JOB_ID or "unknown"))
            else:
                # Last resort: repo DEBUG folder
                debug_folder = _join(_parent_dir(), "DEBUG", "logs", "errors")
                if not os.path.exists(debug_folder):
                    os.makedirs(debug_folder)
                error_file = _join(debug_folder, "OPEN_ERROR_{}.txt".format(_JOB_ID or "unknown"))
            
            try:
                with open(error_file, 'w') as f:
                    f.write("Cloud Model Open Error\n")
                    f.write("="*80 + "\n")
                    f.write("Job ID: {}\n".format(_JOB_ID))
                    f.write("Project: {}\n".format(job_payload.get("project_name")))
                    f.write("Model: {}\n".format(job_payload.get("model_name")))
                    f.write("Model GUID: {}\n".format(job_payload.get("model_guid")))
                    f.write("Project GUID: {}\n".format(job_payload.get("project_guid")))
                    f.write("Version: {}\n".format(job_payload.get("revit_version")))
                    f.write("\nError:\n{}\n".format(error_msg))
                    f.write("\nTraceback:\n{}\n".format(error_tb))
                    f.write("\nTimestamp: {}\n".format(datetime.now().isoformat()))
                print("  Error details saved to: {}".format(error_file))
            except Exception as file_err:
                print("  WARNING: Could not write error file: {}".format(file_err))
            
            # Update status and re-raise
            _write_status("failed", error_msg, error=error_tb, job_payload=job_payload)
            raise
        
        # Validate document is still open before running metrics
        try:
            if doc is None or doc.IsClosed:
                raise Exception("Document became invalid after opening")
        except:
            pass  # IsClosed may not be available in all versions
        
        # Step 3: Run health metrics
        print("")
        print("[STEP 3] Running health metrics...")
        print("  Document title: {}".format(doc.Title if doc else "Unknown"))
        _write_status("starting_metrics", "Initializing health metric checks...", job_payload=job_payload)
        
        try:
            health_report, error_msg = run_health_metrics(doc, job_payload)
            print("  [SUCCESS] Health metrics completed")
        except Exception as metrics_err:
            error_msg = "Health metrics crashed: {}".format(str(metrics_err))
            error_tb = traceback.format_exc()
            print("  [FAILED] {}".format(error_msg))
            print("  Traceback:")
            print(error_tb)
            
            # Write failure marker to prevent empty folder
            write_failure_marker(job_payload, "{}\n\nTraceback:\n{}".format(error_msg, error_tb), "processing")
            
            # Write detailed error to task output folder (or job debug_dir if not available)
            paths = job_payload.get('paths', {})
            task_output_dir = paths.get('task_output_dir')
            debug_dir = paths.get('debug_dir')
            
            if task_output_dir and os.path.exists(task_output_dir):
                error_file = _join(task_output_dir, "METRICS_ERROR_{}.txt".format(_JOB_ID or "unknown"))
            elif debug_dir and os.path.exists(debug_dir):
                # Fallback to job-specific debug folder
                error_file = _join(debug_dir, "METRICS_ERROR_{}.txt".format(_JOB_ID or "unknown"))
            else:
                # Last resort: repo DEBUG folder
                debug_folder = _join(_parent_dir(), "DEBUG", "logs", "errors")
                if not os.path.exists(debug_folder):
                    os.makedirs(debug_folder)
                error_file = _join(debug_folder, "METRICS_ERROR_{}.txt".format(_JOB_ID or "unknown"))
            
            try:
                with open(error_file, 'w') as f:
                    f.write("Health Metrics Crash\n")
                    f.write("="*80 + "\n")
                    f.write("Job ID: {}\n".format(_JOB_ID))
                    f.write("Project: {}\n".format(job_payload.get("project_name")))
                    f.write("Model: {}\n".format(job_payload.get("model_name")))
                    f.write("Document: {}\n".format(doc.Title if doc else "Unknown"))
                    f.write("\nError:\n{}\n".format(error_msg))
                    f.write("\nTraceback:\n{}\n".format(error_tb))
                    f.write("\nTimestamp: {}\n".format(datetime.now().isoformat()))
                print("  Error details saved to: {}".format(error_file))
            except Exception as file_err:
                print("  WARNING: Could not write error file: {}".format(file_err))
            
            _write_status("failed", error_msg, error=error_tb, job_payload=job_payload)
            raise
        
        # Step 4: Write results
        print("")
        print("[STEP 4] Writing results...")
        elapsed = time.time() - start_time
        write_results(job_payload, health_report, error_msg, doc, elapsed)
        
        # Step 5: Close document
        print("")
        print("[STEP 5] Closing document...")
        if doc and not doc.IsLinked:
            try:
                doc.Close(False)  # Don't save
                print("Document closed successfully")
            except Exception as e:
                print("WARNING: Failed to close document: {}".format(str(e)))
        
        # Final status
        final_elapsed = time.time() - start_time
        print("")
        print("="*80)
        print("SUCCESS: Job completed in {:.1f} seconds".format(final_elapsed))
        print("="*80)
        
        _write_status("completed", "Job completed successfully in {:.1f}s".format(final_elapsed), job_payload=job_payload)
        _write_heartbeat("Completed", 100)
        
        # Exit Revit (optional - pyrevit will handle this)
        # __revit__.Application.Quit() # Uncomment if you want to close Revit after job
        
    except Exception as e:
        error_msg = str(e)
        tb = traceback.format_exc()
        
        # Check crash tracker to identify which health check was running
        crash_tracker_path = _join(_parent_dir(), "current_check.txt")
        crash_check_info = None
        if os.path.exists(crash_tracker_path):
            try:
                with open(crash_tracker_path, 'r') as f:
                    crash_check_info = f.read()
                print("")
                print("="*80)
                print("CRASH TRACKER - Last Health Check Running:")
                print("="*80)
                print(crash_check_info)
                print("="*80)
                # Prepend crash info to error message
                error_msg = "CRASH DURING:\n{}\n\nError: {}".format(crash_check_info, error_msg)
            except:
                pass
        
        print("")
        print("="*80)
        print("ERROR: Job failed")
        print("="*80)
        print(error_msg)
        print("")
        print("Traceback:")
        print(tb)
        
        # Try to get job_payload for diagnostics (it might not be loaded if error is early)
        try:
            if 'job_payload' in locals():
                _write_status("failed", error_msg, error=tb, job_payload=job_payload)
            else:
                _write_status("failed", error_msg, error=tb)
        except:
            _write_status("failed", error_msg, error=tb)
        
        # Re-raise so pyrevit knows the script failed
        raise

# Run main
if __name__ == "__main__":
    main()

