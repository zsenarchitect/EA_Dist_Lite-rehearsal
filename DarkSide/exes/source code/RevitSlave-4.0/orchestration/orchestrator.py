"""
RevitSlave4 Orchestrator
Main workflow coordination for API-first batch processing
"""

from datetime import datetime
from pathlib import Path
from core.aps_api import APSClient
from core.guid_discovery import GUIDDiscoveryService
from core.job_factory import JobFactory
from core.job_executor import JobExecutor
from utils.job_monitor import JobMonitor
from utils.timeout_calculator import TimeoutCalculator
from utils.journal_monitor import JournalMonitor, find_journal_files, backup_journal_to_debug, detect_error_loop_in_journal
from utils.error_loop_detector import ErrorLoopDetector
from utils.cleanup_manager import CleanupManager
from models.job_models import BatchResult
from config.settings import ProcessingSettings
import time
import tempfile
import random

# Import notification system (graceful failure)
_notification_available = False
_show_notification_func = None

try:
    from utils.notification import show_loading_notification
    _notification_available = True
    _show_notification_func = show_loading_notification
except Exception:
    # Notification system not available - that's OK
    pass


class RevitSlave4Orchestrator:
    """
    Main orchestrator for RevitSlave4
    
    Phase 1: Cache system
    - Load/refresh GUID cache
    - Get processable files
    - Build job payloads
    - Display summary
    
    Phase 2: Job processing with intelligent timeout
    - Execute jobs with pyRevit
    - Monitor with dual system (status + heartbeat)
    - Apply intelligent timeout based on file size
    """
    
    def __init__(self, client_id: str, client_secret: str, project_filter: list = None):
        self.client_id = client_id
        self.client_secret = client_secret
        
        # Configure project filtering if requested
        if project_filter:
            from config.settings import ProjectFilterSettings
            ProjectFilterSettings.ENABLED = True
            ProjectFilterSettings.PROJECT_NAMES = project_filter
            print(f"\n[PROJECT FILTER] Enabled - filtering to project(s): {', '.join(project_filter)}")
        
        # Initialize services
        self.discovery = GUIDDiscoveryService()
        self.factory = JobFactory()
        self.executor = JobExecutor()
        self.timeout_calculator = TimeoutCalculator()
        
        # Results tracking
        self.batch_result = BatchResult()
        
        # Cancellation signal file
        self.cancel_signal_file = Path(__file__).parent.parent / "revitslave3.cancel"
        # Clear any existing cancel signal at startup
        if self.cancel_signal_file.exists():
            self.cancel_signal_file.unlink()
    
    def run(self, force_refresh: bool = False, process_jobs: bool = True) -> bool:
        """
        Main execution flow (Phase 1 + Phase 2)
        
        Args:
            force_refresh: Force cache refresh even if valid
            process_jobs: Whether to process jobs (Phase 2)
            
        Returns:
            True if successful
        """
        print("\n" + "="*80)
        print("RevitSlave4 - API-First Batch Processing")
        print("Phase 1: Cache System & Job Generation")
        print("="*80)
        
        self.batch_result.start_time = datetime.now()
        
        # Run automatic cleanup of old files (10+ days)
        self._run_automatic_cleanup()
        
        try:
            # Step 1: Ensure cache is fresh
            print("\n[CACHE] Step 1: GUID Cache Management")
            print("-" * 80)
            
            cache_valid = self.discovery.is_cache_valid()
            
            if force_refresh:
                print("[REFRESH] Force refresh requested - fetching from APS API...")
                self._refresh_cache_from_api()
            elif not cache_valid:
                print("[REFRESH] Cache expired or missing - fetching from APS API...")
                self._refresh_cache_from_api()
            else:
                print("[OK] Using existing valid cache")
                self.discovery.load_cache()
            
            # Step 2: Get processable files
            print("\n[STATS] Step 2: File Discovery")
            print("-" * 80)
            
            processable_files = self.discovery.get_processable_files()
            
            if not processable_files:
                print("[ERROR] No processable files found")
                return False
            
            print(f"[OK] Found {len(processable_files)} processable files")
            
            # Step 2.5: PRE-VALIDATE models (RevitSlave4 feature)
            from config.settings import ValidationSettings
            
            if ValidationSettings.ENABLED:
                print("\n[PRE-VALIDATION] Step 2.5: Model Validation (RevitSlave4)")
                print("-" * 80)
                
                validated_files, skipped_info = self._validate_models(processable_files)
                
                # Check if validation was too unreliable
                validation_success_rate = len(validated_files) / len(processable_files) if processable_files else 0
                
                if validation_success_rate < ValidationSettings.MIN_SUCCESS_RATE:
                    print(f"[WARNING] Validation success rate too low ({validation_success_rate:.0%} < {ValidationSettings.MIN_SUCCESS_RATE:.0%})")
                    print(f"[WARNING] Disabling validation for this run - API may be unreliable")
                    validated_files = processable_files  # Use all files (fallback to v3 behavior)
                else:
                    print(f"\n[OK] Validation complete: {len(validated_files)} active, {len(skipped_info)} skipped")
                    
                    # Suggest cache refresh if many skipped
                    if validation_success_rate < ValidationSettings.SUGGEST_REFRESH_THRESHOLD:
                        print(f"\n[SUGGESTION] {(1-validation_success_rate):.0%} of models skipped")
                        print(f"[SUGGESTION] Consider running: python RevitSlave4.py --force-refresh --project <name>")
                        print(f"[SUGGESTION] This will fetch fresh GUIDs and detect deleted models")
            else:
                print("\n[PRE-VALIDATION] Disabled in settings - using all files")
                validated_files = processable_files
            
            # Step 3: Build job payloads (only for validated files)
            print("\n[FACTORY] Step 3: Job Payload Creation")
            print("-" * 80)
            
            jobs = self.factory.create_batch(validated_files)
            
            print(f"[OK] Created {len(jobs)} job payloads")
            
            # Step 4: Display summary (Phase 1 - no processing yet)
            print("\n[SUMMARY] Job Summary")
            print("-" * 80)
            
            # Group jobs by project for summary
            projects = {}
            for job in jobs:
                proj_key = f"{job.hub_name}/{job.project_name}"
                if proj_key not in projects:
                    projects[proj_key] = []
                projects[proj_key].append(job)
            
            print(f"\n[HUB] {len(projects)} projects with processable files:")
            for proj_key, proj_jobs in projects.items():
                print(f"\n  {proj_key}")
                print(f"    Files: {len(proj_jobs)}")
                
                # Show first 3 files as examples
                for job in proj_jobs[:3]:
                    size_mb = job.file_size_bytes / (1024 * 1024)
                    print(f"      - {job.file_name} (Revit {job.revit_version}, {size_mb:.1f}MB)")
                    print(f"        Model GUID: {job.model_guid[:8]}...{job.model_guid[-8:]}")
                
                if len(proj_jobs) > 3:
                    print(f"      ... and {len(proj_jobs) - 3} more files")
            
            # Phase 1 complete message
            print("\n" + "="*80)
            print("[SUCCESS] PHASE 1 COMPLETE: Cache System Working!")
            print("="*80)
            print("\n[SUMMARY]:")
            print(f"   Total jobs ready: {len(jobs)}")
            print(f"   All jobs have guaranteed GUIDs [OK]")
            print(f"   All jobs have version numbers [OK]")
            print(f"   Cache expires in 7 days")
            
            # Phase 2: Job processing
            if not process_jobs:
                print("\n[SKIP] Phase 2 - Job processing skipped")
                print("="*80)
                self.batch_result.end_time = datetime.now()
                return True
            
            print("\n" + "="*80)
            print("Phase 2: Job Processing with Intelligent Timeout")
            print("="*80)
            
            success = self._process_jobs(jobs)
            
            self.batch_result.end_time = datetime.now()
            return success
            
        except Exception as e:
            import traceback
            print(f"\n[ERROR] Error in orchestrator: {e}")
            print(traceback.format_exc())
            return False
    
    def _process_jobs(self, jobs):
        """
        Process all jobs grouped by project (like RevitSlave2)
        
        Args:
            jobs: List of JobPayload objects
            
        Returns:
            True if all jobs completed successfully
        """
        # Group jobs by project_name
        projects = {}
        for job in jobs:
            project_name = job.project_name
            if project_name not in projects:
                projects[project_name] = []
            projects[project_name].append(job)
        
        print(f"\n[EXECUTOR] Processing {len(jobs)} jobs across {len(projects)} projects...")
        print("-" * 80)
        
        # Calculate weights for each project based on Revit version
        # Newer versions get exponentially higher probability
        project_weights = {}
        project_avg_versions = {}
        for project_name, project_jobs in projects.items():
            avg_version = sum(job.revit_version for job in project_jobs) / len(project_jobs)
            project_avg_versions[project_name] = avg_version
            # Exponential weight: 2020 gets weight 1, 2026 gets weight 64
            weight = 2 ** (avg_version - 2020)
            project_weights[project_name] = weight
        
        # Weighted random selection (newer versions more likely to be first)
        project_names = list(projects.keys())
        weights = [project_weights[name] for name in project_names]
        
        # Use weighted random sampling WITHOUT replacement
        shuffled_projects = []
        remaining_names = project_names.copy()
        remaining_weights = weights.copy()
        
        while remaining_names:
            # Pick one project based on weights
            selected = random.choices(remaining_names, weights=remaining_weights, k=1)[0]
            shuffled_projects.append(selected)
            
            # Remove selected from pool
            idx = remaining_names.index(selected)
            remaining_names.pop(idx)
            remaining_weights.pop(idx)
        
        # Log shuffling info
        print(f"\n[SHUFFLE] Weighted randomization applied:")
        print(f"  Strategy: Newer Revit versions have higher probability")
        print(f"  Projects with avg version 2026: {sum(1 for v in project_avg_versions.values() if v >= 2025.5)} (highest priority)")
        print(f"  Projects with avg version 2025: {sum(1 for v in project_avg_versions.values() if 2024.5 <= v < 2025.5)}")
        print(f"  Projects with avg version 2024: {sum(1 for v in project_avg_versions.values() if 2023.5 <= v < 2024.5)}")
        print(f"  Projects with avg version <=2023: {sum(1 for v in project_avg_versions.values() if v < 2023.5)} (lower priority)")
        
        # Show first 5 projects selected
        print(f"\n[ORDER] First 5 projects to process:")
        for i, pname in enumerate(shuffled_projects[:5], 1):
            avg_ver = project_avg_versions[pname]
            file_count = len(projects[pname])
            print(f"  {i}. {pname}")
            print(f"     Avg version: {avg_ver:.1f}, Files: {file_count}, Weight: {project_weights[pname]:.0f}")
        
        total_successful = 0
        total_failed = 0
        
        # Process each project in shuffled order
        for project_idx, project_name in enumerate(shuffled_projects, 1):
            project_jobs = projects[project_name]
            print(f"\n{'='*80}")
            print(f"PROJECT {project_idx}/{len(projects)}: {project_name}")
            print(f"{'='*80}")
            print(f"Files to process: {len(project_jobs)}")
            
            # Clean Windows TEMP folder before processing this project
            self._cleanup_windows_temp_before_project(project_name)
            
            project_successful = 0
            project_failed = 0
            retry_queue = []  # Failed jobs to retry at end
            
            # Add retry_count attribute to jobs
            for job in project_jobs:
                if not hasattr(job, 'retry_count'):
                    job.retry_count = 0
            
            # Process all jobs in this project (including retries)
            jobs_to_process = list(project_jobs)
            processed_count = 0
            
            while jobs_to_process:
                # Check for cancellation signal before starting new job
                if self.cancel_signal_file.exists():
                    print(f"\n[CANCELLED] Cancellation signal detected - stopping project processing")
                    print(f"Processed {processed_count-1} jobs in {project_name} before cancellation")
                    break
                
                job = jobs_to_process.pop(0)
                processed_count += 1
                
                retry_label = " (RETRY)" if job.retry_count > 0 else ""
                print(f"\n[FILE {processed_count}/{len(project_jobs) + len(retry_queue)}] {job.file_name}{retry_label}")
                print(f"  Folder: {job.folder_path or '(root)'}")
                print(f"  Size: {job.file_size_bytes / (1024*1024):.1f} MB")
                print(f"  Revit: {job.revit_version}")
                if job.retry_count > 0:
                    print(f"  Retry attempt: {job.retry_count + 1}")
                
                # Calculate idle timeout (how long without progress before aborting)
                timeout, timeout_details = self.timeout_calculator.calculate_timeout(
                    job.file_size_bytes, 
                    job.revit_version
                )
                print(f"  Idle Timeout: {timeout}s ({timeout//60}m {timeout%60}s) - Jobs can run indefinitely as long as making progress")
                
                # Launch job
                success, error_msg, process = self.executor.launch_job(job)
                
                if not success:
                    print(f"  [FAILED] {error_msg}")
                    # Add to retry queue if first attempt
                    if job.retry_count == 0:
                        job.retry_count = 1
                        retry_queue.append(job)
                        print(f"  [QUEUED] Will retry after other files")
                    else:
                        project_failed += 1
                        print(f"  [ABANDONED] Max retries reached")
                    continue
                
                # Find and monitor journal files
                print(f"  [SAFETY] Starting journal file monitoring...")
                time.sleep(2)  # Give Revit time to create journal
                journal_files = find_journal_files(Path(tempfile.gettempdir()))
                
                journal_monitor = None
                latest_journal = None
                
                if journal_files:
                    # Filter out files that no longer exist (race condition protection)
                    existing_journals = []
                    for j in journal_files:
                        try:
                            if j.exists():
                                stat_info = j.stat()  # Verify we can access it
                                existing_journals.append((j, stat_info.st_mtime))
                        except (FileNotFoundError, OSError):
                            # File was deleted between find and stat - skip it
                            continue
                    
                    if existing_journals:
                        # Monitor the most recently created journal
                        latest_journal, _ = max(existing_journals, key=lambda item: item[1])
                        print(f"  [JOURNAL] Monitoring: {latest_journal.name}")
                        
                        # Start journal monitoring (abort if > 100 MB)
                        journal_monitor = JournalMonitor(
                            latest_journal,
                            max_size_mb=100,
                            check_interval=10
                        )
                        journal_monitor.start()
                    else:
                        print(f"  [WARNING] Journal files found but no longer accessible (race condition)")
                else:
                    print(f"  [WARNING] No journal file found, monitoring disabled")
                
                # Monitor job status
                monitor = JobMonitor(
                    job.job_id,
                    timeout,
                    str(self.executor.database_folder)
                )
                
                if not monitor.start_monitoring():
                    print(f"  [FAILED] Could not start monitoring")
                    if journal_monitor:
                        journal_monitor.stop()
                    project_failed += 1
                    continue
                
                # Wait for completion with timeout
                job_success = self._wait_for_job(monitor, process, timeout, journal_monitor)
                
                if job_success:
                    print(f"  [SUCCESS] Job completed")
                    project_successful += 1
                else:
                    print(f"  [FAILED] Job timed out or failed")
                    # Add to retry queue if first attempt
                    if job.retry_count == 0:
                        job.retry_count = 1
                        retry_queue.append(job)
                        print(f"  [QUEUED] Will retry after other files")
                    else:
                        project_failed += 1
                        print(f"  [ABANDONED] Max retries reached")
                
                # Add retry queue to processing queue if this was last initial job
                if not jobs_to_process and retry_queue:
                    print(f"\n{'='*80}")
                    print(f"RETRY PHASE: {len(retry_queue)} file(s) to retry")
                    print(f"{'='*80}")
                    jobs_to_process.extend(retry_queue)
                    retry_queue = []
            
            # Project summary
            print(f"\n{'-'*80}")
            print(f"PROJECT {project_name} COMPLETE:")
            print(f"  Successful: {project_successful}/{len(project_jobs)}")
            print(f"  Failed: {project_failed}/{len(project_jobs)}")
            if retry_queue:
                print(f"  Still retrying: {len(retry_queue)}")
            print(f"{'-'*80}")
            
            # Update totals
            total_successful += project_successful
            total_failed += project_failed
            
            # Validate project outputs (check for missing output files)
            print(f"\n[VALIDATION] Checking output files for {project_name}...")
            validation_stats = self._validate_project_outputs(project_name)
            if validation_stats.get("without_output", 0) > 0:
                print(f"  [WARNING] {validation_stats['without_output']} models have no output (neither success nor failure markers)")
            else:
                print(f"  [OK] All {validation_stats['with_output']} models have output files")
            
            # Clean up empty folders (models that failed before creating any output)
            print(f"\n[CLEANUP] Removing empty model folders for {project_name}...")
            empty_count = self._cleanup_empty_folders(project_name)
            if empty_count > 0:
                print(f"  [OK] Removed {empty_count} empty folder(s)")
            else:
                print(f"  [OK] No empty folders to clean")
            
            # Run HealthMetricSender.exe after each project (like RevitSlave2)
            self._run_health_metric_sender(project_name)
        
        # Final summary
        print("\n" + "="*80)
        print("[BATCH COMPLETE]")
        print("="*80)
        print(f"  Projects: {len(projects)}")
        print(f"  Total Files: {len(jobs)}")
        print(f"  Successful: {total_successful}")
        print(f"  Failed: {total_failed}")
        print("="*80)
        
        return total_failed == 0
    
    def _wait_for_job(self, monitor, process, timeout, journal_monitor=None):
        """
        Wait for job to complete with monitoring
        
        Args:
            monitor: JobMonitor instance
            process: Subprocess instance
            timeout: Timeout in seconds (idle timeout for most phases)
            journal_monitor: Optional JournalMonitor instance
            
        Returns:
            True if job completed successfully
        """
        check_interval = 5  # Check every 5 seconds
        elapsed = 0
        last_activity_report = time.time()
        idle_time = 0
        opening_grace_period = 900  # 15 minutes grace for cloud model opening (no heartbeats possible)
        analyzing_grace_period = 1200  # 20 minutes grace for health metrics (RevitSlave4 - increased from V3's 900)
        # CRITICAL: Prevents killing Revit during health metrics
        # Individual metrics can timeout at 180-300s, but no heartbeats sent DURING execution
        # 20 min allows 4 slow metrics (5 min each) + buffer before timing out
        
        try:
            while True:  # Loop continues until timeout or completion
                time.sleep(check_interval)
                elapsed += check_interval
                
                if elapsed > ProcessingSettings.MAX_JOB_RUNTIME_SECONDS:
                    total_minutes = ProcessingSettings.MAX_JOB_RUNTIME_SECONDS // 60
                    print(f"  [TIMEOUT] Job exceeded {total_minutes} minute hard limit - terminating Revit process")
                    self._kill_process(process)
                    return False
                
                # Track activity-based timeout (reset on progress)
                activity_detected = False
                
                # Check for heartbeat/status updates (any activity)
                if monitor.has_heartbeat_updated() or monitor.has_status_updated():
                    activity_detected = True
                    idle_time = 0
                    last_activity_report = time.time()
                
                    # Show notification for heartbeat updates
                    if _notification_available:
                        try:
                            _show_notification_func(duration=6.0)
                        except:
                            pass
                else:
                    # No activity - track idle time
                    idle_time = time.time() - last_activity_report
                
                # Check current job status to determine appropriate timeout
                status, _ = monitor.check_status()
                
                # Special handling for phases that need longer grace periods:
                # - "opening": Cloud download/open can take 5+ min with NO heartbeats (Revit busy downloading)
                # - "analyzing": Health metrics - individual metrics can take up to 5 min (warnings: 300s timeout)
                #                Heartbeats only sent BETWEEN metrics, not during metric execution
                if status in ("opening", "started", "revit_ready"):
                    # During opening, allow up to 15 minutes for cloud download/open before killing Revit
                    effective_timeout = opening_grace_period
                    timeout_description = "opening grace"
                elif status == "analyzing" or status == "starting_metrics":
                    # During health metrics, use extended grace period (20 minutes)
                    # CRITICAL: Prevents killing Revit while metrics run
                    # RevitSlave4: Increased to 20min (vs V3's 15min) based on V3 timeout analysis
                    effective_timeout = analyzing_grace_period
                    timeout_description = "analyzing grace"
                else:
                    # Normal operations should have regular heartbeats
                    effective_timeout = timeout
                    timeout_description = "idle"
                
                # Report idle time periodically (every 5 minutes)
                if idle_time > 300 and int(idle_time) % 300 < check_interval:
                    idle_minutes = int(idle_time // 60)
                    print(f"  [IDLE] No progress for {idle_minutes} minutes (timeout: {effective_timeout//60} min {timeout_description}, status: {status})")
                
                # Activity-based timeout check: only timeout if idle too long (not total elapsed)
                if idle_time > effective_timeout:
                    print(f"  [TIMEOUT] No progress for {effective_timeout//60} minutes ({timeout_description} timeout, status: {status})")
                    self._kill_process(process)
                    return False
                
                # Check if journal size exceeded (critical - abort immediately)
                if journal_monitor and journal_monitor.is_size_exceeded():
                    print(f"  [CRITICAL] Journal size exceeded - ABORTING")
                    self._kill_process(process)
                    return False
                
                # Check for cancellation signal
                if self.cancel_signal_file.exists():
                    print(f"\n  [CANCELLED] Cancellation signal detected - stopping job")
                    self._kill_process(process)
                    return False
                
                # Check completion status
                if status == "completed":
                    return True
                elif status == "failed":
                    # Revit surfaced a blocking error dialog and cannot proceed.
                    # Ensure the orphaned Revit process is terminated so the batch can continue.
                    self._kill_process(process)
                    return False
                elif status == "timeout":
                    # Kill process
                    self._kill_process(process)
                    return False
                
                # Check if process died
                if process.poll() is not None:
                    # Process ended, check final status
                    time.sleep(2)  # Give it time to write status
                    status, _ = monitor.check_status()
                    return status == "completed"
            
            # Should not reach here (while True loop)
            
        finally:
            # Always stop journal monitor and check for errors
            if journal_monitor:
                journal_monitor.stop()
                
                # Check if journal indicates error loop
                if journal_monitor.journal_path and journal_monitor.journal_path.exists():
                    is_loop, error_count, sample_errors = detect_error_loop_in_journal(
                        journal_monitor.journal_path
                    )
                    
                    if is_loop:
                        print(f"  [WARNING] Error loop detected in journal ({error_count} errors)")
                        for err in sample_errors[:2]:
                            print(f"    Sample: {err}")
                        
                        # Backup journal for debugging
                        backup_journal_to_debug(
                            journal_monitor.journal_path,
                            monitor.job_id if hasattr(monitor, 'job_id') else "unknown"
                        )
    
    def _kill_process(self, process):
        """Kill a process safely"""
        try:
            process.terminate()
            time.sleep(2)
            if process.poll() is None:
                process.kill()
        except Exception as e:
            print(f"  [WARNING] Error killing process: {e}")
    
    def _run_health_metric_sender(self, project_name):
        """
        Run HealthMetricSender.exe after project completes (like RevitSlave2)
        Sends task_output to GitHub and updates WikiBuilder
        
        Args:
            project_name: Name of completed project
            
        Returns:
            bool: True if execution was successful
        """
        import subprocess
        import os
        
        print(f"\n{'='*80}")
        print(f"Running HealthMetricSender.exe for: {project_name}")
        print(f"{'='*80}")
        
        # Try multiple possible locations for HealthMetricSender.exe
        health_metric_path = None
        
        # Option 1: Repository location (for development)
        repo_root = Path(__file__).parent.parent.parent.parent.parent
        repo_exe_path = repo_root / "Apps" / "lib" / "ExeProducts" / "HealthMetricSender.exe"
        
        if repo_exe_path.exists():
            health_metric_path = repo_exe_path
            print(f"[OK] Using repository HealthMetricSender.exe")
        else:
            # Option 2: Deployed location (EnneadTab Ecosystem/EA_Dist)
            username = os.environ.get('USERNAME', 'USERNAME')
            dump_folder = Path("C:/Users") / username / "Documents" / "EnneadTab Ecosystem" / "Dump"
            deployed_exe_path = dump_folder.parent / "EA_Dist" / "Apps" / "lib" / "ExeProducts" / "HealthMetricSender.exe"
            
            if deployed_exe_path.exists():
                health_metric_path = deployed_exe_path
                print(f"[OK] Using deployed HealthMetricSender.exe")
        
        if not health_metric_path:
            print(f"[WARNING] HealthMetricSender.exe not found")
            print(f"  Checked: {repo_exe_path}")
            if 'deployed_exe_path' in locals():
                print(f"  Checked: {deployed_exe_path}")
            print("  Skipping GitHub upload for this project")
            print(f"{'='*80}")
            return True  # Don't fail the batch
        
        print(f"[INFO] HealthMetricSender.exe path: {health_metric_path}")
        
        try:
            # Run HealthMetricSender.exe with timeout
            result = subprocess.run(
                [str(health_metric_path)], 
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                print(f"[SUCCESS] HealthMetricSender.exe executed successfully")
                print(f"  Project '{project_name}' data sent to GitHub")
                if result.stdout:
                    print(f"  Output: {result.stdout}")
                print(f"{'='*80}")
                return True
            else:
                print(f"[WARNING] HealthMetricSender.exe returned code {result.returncode}")
                if result.stdout:
                    print(f"  Output: {result.stdout}")
                if result.stderr:
                    print(f"  Error: {result.stderr}")
                print(f"{'='*80}")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"[WARNING] HealthMetricSender.exe execution timed out")
            print(f"{'='*80}")
            return False
        except FileNotFoundError:
            print(f"[WARNING] HealthMetricSender.exe not found or not executable")
            print(f"{'='*80}")
            return False
        except Exception as e:
            print(f"[ERROR] Error running HealthMetricSender.exe: {e}")
            print(f"{'='*80}")
            return False
    
    def _cleanup_windows_temp_before_project(self, project_name: str):
        """
        Clean Windows TEMP folder before processing project.
        
        This prevents the 150+ GB temp folder buildup caused by ACC CentralCache.
        Real-world: 640 Revit temp files = 185.18 GB!
        
        Args:
            project_name: Name of project about to be processed
        """
        try:
            print(f"\n[TEMP CLEANUP] Cleaning Windows TEMP folder before project...")
            print(f"  Target: ACC CentralCache (_CC) folders")
            
            cleaner = CleanupManager(dry_run=False, verbose=False)
            stats = cleaner.cleanup_windows_temp_folder(aggressive=True)
            
            if stats.files_deleted > 0 or stats.dirs_deleted > 0:
                print(f"  {stats.get_summary()}")
            else:
                print(f"  No temp files to clean (already clean)")
            
            if stats.errors and len(stats.errors) > 5:
                # Only report if many errors (a few locked files are normal)
                print(f"  [WARNING] {len(stats.errors)} cleanup errors (non-critical)")
            
        except Exception as e:
            # Non-critical - don't break pipeline
            print(f"  [WARNING] Temp cleanup failed (non-critical): {e}")
        
        print("-" * 80)
    
    def _validate_models(self, processable_files):
        """
        Pre-validate models exist via APS API before launching Revit
        
        This is the key RevitSlave4 feature that prevents wasting time
        launching Revit for deleted/archived models.
        
        Args:
            processable_files: List of file metadata objects
        
        Returns:
            (validated_files, skipped_info)
            - validated_files: Files that exist and are accessible
            - skipped_info: List of (file, error_reason) tuples
        """
        from core.model_validator import ModelValidator
        from config.settings import ValidationSettings
        
        # Get access token
        token = None
        try:
            # Try to get token from aps_client
            if hasattr(self, 'aps_client') and self.aps_client:
                token = self.aps_client.get_access_token()
            else:
                # Fallback: Create new client
                from core.aps_api import APSClient
                aps_client = APSClient(self.client_id, self.client_secret)
                self.aps_client = aps_client  # Store for validation use later
                token = aps_client.get_access_token()
        except Exception as e:
            print(f"[ERROR] Failed to get APS token for validation: {e}")
            if ValidationSettings.FAIL_ON_API_ERROR:
                raise
            else:
                print(f"[FALLBACK] Proceeding without validation (RevitSlave4 behavior)")
                return (processable_files, [])
        
        if not token:
            print(f"[ERROR] No APS token available for validation")
            if ValidationSettings.FAIL_ON_API_ERROR:
                raise Exception("Cannot validate without APS token")
            else:
                print(f"[FALLBACK] Proceeding without validation")
                return (processable_files, [])
        
        # Initialize validator
        validator = ModelValidator(token)
        
        # Group files by project for efficient validation
        files_by_project = {}
        for file_info in processable_files:
            project_id = file_info.project_id
            if project_id not in files_by_project:
                files_by_project[project_id] = []
            files_by_project[project_id].append(file_info)
        
        # Validate each project
        all_validated = []
        all_skipped = []
        
        for project_id, project_files in files_by_project.items():
            # Prepare items for batch validation
            items_to_validate = [
                {
                    'item_id': f.file_id,
                    'model_name': f.file_name,
                    'file_info': f  # Keep reference to original object
                }
                for f in project_files
            ]
            
            # Batch validate
            valid_items, invalid_items, api_calls = validator.batch_validate(
                project_id,
                items_to_validate,
                verbose=ValidationSettings.VERBOSE_VALIDATION
            )
            
            # Extract file_info objects
            validated = [item['file_info'] for item in valid_items]
            skipped = [(item['file_info'], error) for item, error in invalid_items]
            
            all_validated.extend(validated)
            all_skipped.extend(skipped)
        
        return (all_validated, all_skipped)
    
    def _cleanup_empty_folders(self, project_name: str = None):
        """
        Remove empty model folders after batch completes.
        This prevents clutter from jobs that failed before writing output.
        
        Args:
            project_name: Optional project name to clean only that project.
                         If None, cleans all projects.
        
        Returns:
            int: Number of empty folders removed
        """
        try:
            empty_count = 0
            
            if project_name:
                # Clean specific project
                project_dir = self.executor.task_output_dir / project_name
                if not project_dir.exists():
                    return 0
                    
                projects_to_clean = [project_dir]
            else:
                # Clean all projects
                projects_to_clean = [p for p in self.executor.task_output_dir.iterdir() if p.is_dir()]
            
            for project_dir in projects_to_clean:
                for model_dir in project_dir.iterdir():
                    if model_dir.is_dir():
                        # Check if folder is truly empty (no files at all)
                        has_files = any(model_dir.glob('*'))
                        if not has_files:
                            try:
                                model_dir.rmdir()
                                empty_count += 1
                                print(f"  [CLEANUP] Removed empty folder: {model_dir.name}")
                            except Exception as e:
                                print(f"  [WARNING] Could not remove empty folder {model_dir.name}: {e}")
            
            return empty_count
            
        except Exception as e:
            print(f"  [WARNING] Error during empty folder cleanup: {e}")
            return 0
    
    def _validate_project_outputs(self, project_name: str):
        """
        Validate that all processed models have output files.
        Reports models with no output (neither success nor failure markers).
        
        Args:
            project_name: Project name to validate
            
        Returns:
            dict: Statistics about outputs
        """
        try:
            project_dir = self.executor.task_output_dir / project_name
            if not project_dir.exists():
                return {"total": 0, "with_output": 0, "without_output": 0}
            
            total_models = 0
            with_output = 0
            without_output = 0
            missing_models = []
            
            for model_dir in project_dir.iterdir():
                if model_dir.is_dir():
                    total_models += 1
                    
                    # Check for output files (.sexyDuck or FAILED_*.txt)
                    has_output = any(model_dir.glob('*.sexyDuck'))
                    has_failure = any(model_dir.glob('FAILED_*.txt'))
                    has_error = any(model_dir.glob('OPEN_ERROR_*.txt')) or any(model_dir.glob('METRICS_ERROR_*.txt'))
                    
                    if has_output or has_failure or has_error:
                        with_output += 1
                    else:
                        without_output += 1
                        missing_models.append(model_dir.name)
            
            # Report missing outputs
            if missing_models:
                print(f"\n  [VALIDATION WARNING] {without_output}/{total_models} models have NO output files:")
                for model in missing_models[:5]:  # Show first 5
                    print(f"    - {model}")
                if len(missing_models) > 5:
                    print(f"    ... and {len(missing_models) - 5} more")
            
            return {
                "total": total_models,
                "with_output": with_output,
                "without_output": without_output,
                "missing_models": missing_models
            }
            
        except Exception as e:
            print(f"  [WARNING] Error validating outputs: {e}")
            return {"total": 0, "with_output": 0, "without_output": 0}
    
    def _run_automatic_cleanup(self):
        """
        Run automatic cleanup of old files on startup.
        Removes files older than 2 days to prevent database from growing too large.
        """
        try:
            print("\n[CLEANUP] Automatic Cleanup")
            print("-" * 80)
            
            cleaner = CleanupManager(days_to_keep=2, dry_run=False, verbose=False)
            
            # Show current state before cleanup
            info = cleaner.get_database_info()
            total_mb = info['total']['size_bytes'] / (1024 * 1024)
            total_gb = info['total']['size_bytes'] / (1024 * 1024 * 1024)
            
            if total_gb >= 1.0:
                size_str = f"{total_gb:.2f} GB"
            else:
                size_str = f"{total_mb:.2f} MB"
            
            print(f"  Current database size: {size_str} ({info['total']['file_count']} files)")
            print(f"  Cleaning files older than {cleaner.days_to_keep} days...")
            
            # Run cleanup (quick and silent)
            stats = cleaner.cleanup_all()
            
            # Show brief summary
            if stats.files_deleted > 0 or stats.dirs_deleted > 0:
                print(f"  {stats.get_summary()}")
            else:
                print(f"  No old files to clean up")
            
            if stats.errors:
                print(f"  [WARNING] {len(stats.errors)} errors during cleanup (non-critical)")
            
            print("-" * 80)
            
        except Exception as e:
            # Cleanup errors should not stop the main workflow
            print(f"  [WARNING] Cleanup failed (non-critical): {e}")
            print("-" * 80)
    
    def _refresh_cache_from_api(self):
        """Refresh cache by fetching data from APS API"""
        print("\n[NETWORK] Connecting to Autodesk APS API...")
        print("   This will take 2-5 minutes depending on project count")
        
        from core.aps_api import APSClient
        client = APSClient(self.client_id, self.client_secret)
        self.aps_client = client  # Store for validation use later
        api_data = client.get_all_data(show_progress=True, guid_service=self.discovery)
        
        if not api_data:
            raise Exception("Failed to fetch data from APS API")
        
        print(f"\n[COST] API Cost: {client.api_call_count} total calls")
        print("   (Token reuse saves ~80% vs naive implementation)")
        
        self.discovery.save_cache(api_data)

