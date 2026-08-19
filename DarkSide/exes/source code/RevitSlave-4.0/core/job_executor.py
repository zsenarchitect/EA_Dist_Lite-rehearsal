"""
RevitSlave4 Job Executor
Handles launching pyRevit with version-specific empty docs
Following AutoExporter pattern
"""

import os
import json
import subprocess
from pathlib import Path
from datetime import datetime


class JobExecutor:
    """
    Executes Revit jobs using pyRevit CLI
    Uses version-specific empty docs to launch correct Revit version
    """
    
    def __init__(self):
        self.script_dir = Path(__file__).parent.parent
        self.assets_dir = self.script_dir / "assets"
        
        # Determine environment (dev vs dist)
        user_profile = os.environ.get('USERPROFILE', '')
        dev_root = Path(user_profile) / 'github' / 'EnneadTab-OS'
        dist_root = Path(user_profile) / 'Documents' / 'EnneadTab Ecosystem' / 'EA_Dist'
        
        if (dev_root / 'Apps' / '_revit' / 'KingDuck.lib').exists():
            self.root_path = dev_root
        else:
            self.root_path = dist_root
        
        self.import_path = self.root_path / 'Apps' / '_revit' / 'KingDuck.lib'
        
        # Path to the Revit entry script
        self.entry_script = self.script_dir / "revit_logic" / "entry_script.py"
        
        # Path to job payload file (in revit_logic folder where entry_script is)
        self.job_payload_path = self.script_dir / "revit_logic" / "current_job.sexyDuck"
        
        # Set up paths for task output (following RevitSlave2 structure)
        username = os.environ.get('USERNAME', 'USERNAME')
        self.database_folder = Path("C:/Users") / username / "Documents" / "EnneadTab Ecosystem" / "Dump" / "RevitSlaveDatabase"
        self.task_output_dir = self.database_folder / "task_output"
        self.debug_dir = self.database_folder / "debug"
        self.log_dir = self.database_folder / "logs"
    
    def get_empty_doc_path(self, revit_version):
        """
        Get path to empty doc for given Revit version
        
        Args:
            revit_version: Revit version year (e.g., 2025)
            
        Returns:
            Path to empty doc .rvt file
        """
        empty_doc = self.assets_dir / f"empty_doc_{revit_version}.rvt"
        
        if not empty_doc.exists():
            # Fallback to 2026
            empty_doc = self.assets_dir / "empty_doc_2026.rvt"
            print(f"[WARNING] empty_doc_{revit_version}.rvt not found, falling back to 2026")
        
        return empty_doc
    
    def _write_job_payload(self, job_payload):
        """
        Write job payload to disk for entry_script to read
        Matches RevitSlave2 structure
        
        Args:
            job_payload: Job payload dict (should be from JobPayload.to_dict())
            
        Returns:
            bool: True if successful
        """
        try:
            # Ensure parent directory exists
            self.job_payload_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write JSON
            with open(self.job_payload_path, 'w', encoding='utf-8') as f:
                json.dump(job_payload, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Force OS write
            
            return True
        except Exception as e:
            print(f"[ERROR] Failed to write job payload: {e}")
            return False
    
    def _prepare_job_payload(self, job_payload):
        """
        Prepare job payload with paths section (matching RevitSlave2)
        
        Args:
            job_payload: Original job payload dict
            
        Returns:
            Enhanced job payload dict with paths section
        """
        # Create model-specific task output directory
        project_name = job_payload.get("project_name", "unknown_project")
        model_name = job_payload.get("model_name", "unknown_model")
        
        # Sanitize names for file system (Windows doesn't allow trailing spaces or certain chars)
        # Strip leading/trailing whitespace first
        project_clean = project_name.strip()
        model_clean = model_name.strip()
        
        # Sanitize characters
        project_safe = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in project_clean)
        model_safe = "".join(c if c.isalnum() or c in (' ', '_', '-', '.') else '_' for c in model_clean)
        
        # Final strip to remove any trailing spaces that might have been preserved
        project_safe = project_safe.strip()
        model_safe = model_safe.strip()
        
        # Ensure names are not empty after sanitization
        if not project_safe:
            project_safe = "unknown_project"
        if not model_safe:
            model_safe = "unknown_model"
        
        # Create model-specific output directory
        model_output_dir = self.task_output_dir / project_safe / model_safe
        model_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Ensure other directories exist
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Add paths section (matching RevitSlave2 structure)
        job_payload['paths'] = {
            'database_folder': str(self.database_folder),
            'task_output_dir': str(model_output_dir),
            'debug_dir': str(self.debug_dir),
            'log_dir': str(self.log_dir),
            'project_name': project_name,
            'model_name': model_name
        }
        
        return job_payload
    
    def launch_job(self, job_payload, logger=None):
        """
        Launch Revit with pyrevit to process a job
        
        Args:
            job_payload: JobPayload object with all job details
            logger: Optional logger for detailed logging
            
        Returns:
            (success, error_message, process) - process is None if failed
        """
        def log(message, level="INFO"):
            """Helper to log with or without logger"""
            if logger:
                if level == "ERROR":
                    logger.error(message)
                elif level == "WARNING":
                    logger.warning(message)
                elif level == "DEBUG":
                    logger.debug(message)
                else:
                    logger.info(message)
            else:
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] [{level}] {message}")
        
        # Convert JobPayload object to dict if needed
        if hasattr(job_payload, 'to_dict'):
            payload_dict = job_payload.to_dict()
        else:
            payload_dict = job_payload
        
        # Get Revit version from payload
        revit_version = payload_dict.get("revit_version")
        job_id = payload_dict.get("job_id")
        project_name = payload_dict.get("project_name")
        model_name = payload_dict.get("model_name") or payload_dict.get("file_name")
        
        log(f"Job: {job_id}")
        log(f"Revit version: {revit_version}")
        log(f"Project: {project_name}")
        log(f"Model: {model_name}")
        
        # Prepare job payload with paths section
        payload_with_paths = self._prepare_job_payload(payload_dict)
        
        # Write job payload for entry_script to read
        log("Writing job payload to current_job.sexyDuck...")
        if not self._write_job_payload(payload_with_paths):
            error_msg = "Failed to write job payload"
            log(error_msg, "ERROR")
            return (False, error_msg, None)
        
        log(f"Job payload written: {self.job_payload_path}")
        
        # Get empty doc
        empty_doc = self.get_empty_doc_path(revit_version)
        if not empty_doc.exists():
            error_msg = f"Empty doc not found: {empty_doc}"
            log(error_msg, "ERROR")
            return (False, error_msg, None)
        
        log(f"Empty doc: {empty_doc}")
        
        # Check if entry script exists
        if not self.entry_script.exists():
            error_msg = f"Entry script not found: {self.entry_script}"
            log(error_msg, "ERROR")
            return (False, error_msg, None)
        
        # Build pyrevit command (following AutoExporter pattern)
        cmd = [
            'pyrevit', 'run',
            str(self.entry_script),
            str(empty_doc),
            f'--revit={revit_version}',
            '--purge',
            f'--import={self.import_path}'
        ]
        
        cmd_string = ' '.join(cmd)
        log(f"Launching Revit: {cmd_string}")
        
        # Write command to diagnostics file for debugging
        try:
            diagnostics_path = self.database_folder / f"launch_command_{job_id}.txt"
            with open(diagnostics_path, 'w', encoding='utf-8') as f:
                f.write(f"Job ID: {job_id}\n")
                f.write(f"Project: {project_name}\n")
                f.write(f"Model: {model_name}\n")
                f.write(f"Revit Version: {revit_version}\n")
                f.write(f"Model GUID: {payload_dict.get('model_guid')}\n")
                f.write(f"Project GUID: {payload_dict.get('project_guid')}\n")
                f.write(f"\nCommand:\n{cmd_string}\n")
                f.write(f"\nTimestamp: {datetime.now().isoformat()}\n")
            log(f"Launch command saved to: {diagnostics_path}")
        except Exception as diag_err:
            log(f"Warning: Could not write diagnostics file: {diag_err}", "WARNING")
        
        try:
            # Launch process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True
            )
            
            pid = process.pid if hasattr(process, 'pid') else 'unknown'
            log(f"Revit process started (PID: {pid})")
            
            return (True, None, process)
            
        except FileNotFoundError:
            error_msg = "pyrevit command not found in PATH. Please ensure pyRevit CLI is installed."
            log(error_msg, "ERROR")
            self._write_launch_error(job_id, error_msg, cmd_string)
            return (False, error_msg, None)
            
        except Exception as e:
            import traceback
            error_msg = f"Failed to launch Revit: {e}"
            error_tb = traceback.format_exc()
            log(error_msg, "ERROR")
            self._write_launch_error(job_id, f"{error_msg}\n\nTraceback:\n{error_tb}", cmd_string)
            return (False, error_msg, None)
    
    def _write_launch_error(self, job_id, error_msg, cmd_string):
        """Write launch error details to file for debugging"""
        try:
            error_path = self.database_folder / f"launch_error_{job_id}.txt"
            with open(error_path, 'w', encoding='utf-8') as f:
                f.write(f"Job ID: {job_id}\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"\nCommand:\n{cmd_string}\n")
                f.write(f"\nError:\n{error_msg}\n")
            print(f"[ERROR] Launch error saved to: {error_path}")
        except Exception as e:
            print(f"[WARNING] Could not write launch error file: {e}")
    
    def check_pyrevit_available(self):
        """
        Check if pyrevit command is available in PATH
        
        Returns:
            bool: True if pyrevit is available
        """
        try:
            result = subprocess.run(
                ['pyrevit', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def validate_assets(self):
        """
        Validate that all required assets exist
        
        Returns:
            (bool, list): (all_valid, missing_files)
        """
        required_versions = [2023, 2024, 2025, 2026]
        missing = []
        
        for version in required_versions:
            empty_doc = self.assets_dir / f"empty_doc_{version}.rvt"
            if not empty_doc.exists():
                missing.append(f"empty_doc_{version}.rvt")
        
        return (len(missing) == 0, missing)


if __name__ == "__main__":
    """Test job executor"""
    print("="*80)
    print("RevitSlave4 Job Executor Test")
    print("="*80)
    
    executor = JobExecutor()
    
    # Check pyRevit
    print("\n[CHECK] pyRevit availability...")
    if executor.check_pyrevit_available():
        print("[OK] pyrevit command found")
    else:
        print("[ERROR] pyrevit command not found in PATH")
    
    # Validate assets
    print("\n[CHECK] Asset validation...")
    all_valid, missing = executor.validate_assets()
    if all_valid:
        print("[OK] All empty doc files present")
    else:
        print(f"[WARNING] Missing files: {', '.join(missing)}")
    
    # Test empty doc path resolution
    print("\n[TEST] Empty doc path resolution...")
    for version in [2023, 2024, 2025, 2026, 2027]:
        path = executor.get_empty_doc_path(version)
        status = "OK" if path.exists() else "MISSING"
        print(f"  [{status}] Revit {version}: {path.name}")
    
    print("\n" + "="*80)

