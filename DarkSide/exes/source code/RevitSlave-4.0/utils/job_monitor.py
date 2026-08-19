"""
Job Monitor for RevitSlave4
Dual monitoring system: job status file + Revit heartbeat file
"""

import os
import time
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from pathlib import Path


class JobMonitor:
    """
    Monitors job execution with dual monitoring system:
    1. Job status file - tracks job completion
    2. Revit heartbeat file - tracks Revit process activity
    """
    
    def __init__(self, job_id: str, timeout_seconds: int, database_dir: str):
        """
        Initialize job monitor
        
        Args:
            job_id: Unique job identifier
            timeout_seconds: Maximum timeout for this job
            database_dir: Database directory for status files
        """
        self.job_id = job_id
        self.timeout_seconds = timeout_seconds
        self.database_dir = Path(database_dir)
        
        # File paths
        self.status_file = self.database_dir / f"job_status_{job_id}.json"
        self.heartbeat_file = self.database_dir / f"revit_heartbeat_{job_id}.txt"
        self.log_file = self.database_dir / f"job_log_{job_id}.txt"
        
        # Monitoring state
        self.start_time = datetime.now()
        self.last_heartbeat = None
        self.last_status = None
        self.last_heartbeat_content = None  # Track heartbeat content for change detection
        self.last_status_content = None  # Track status content for change detection
        
        # Activity-based timeout tracking
        # Initialize last_activity_time to job start (not old heartbeat/stale timestamps)
        # This prevents inheriting stale timestamps from previous jobs
        self.last_activity_time = self.start_time
        
    def start_monitoring(self) -> bool:
        """
        Start monitoring the job
        
        Returns:
            True if monitoring started successfully
        """
        try:
            # Create initial status file
            initial_status = {
                "job_id": self.job_id,
                "status": "monitoring_started",
                "start_time": self.start_time.isoformat(),
                "timeout_seconds": self.timeout_seconds,
                "last_heartbeat": None,
                "last_status": None
            }
            
            with open(self.status_file, 'w') as f:
                json.dump(initial_status, f, indent=2)
            
            print(f"[MONITOR] Started monitoring job {self.job_id}")
            print(f"[MONITOR] Timeout: {self.timeout_seconds}s ({self.timeout_seconds//60}m)")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to start monitoring: {e}")
            return False
    
    def check_status(self) -> Tuple[str, Dict]:
        """
        Check current job status
        
        Returns:
            Tuple of (status, details)
        """
        try:
            # Check if job completed successfully
            if self.status_file.exists():
                with open(self.status_file, 'r') as f:
                    status_data = json.load(f)
                
                if status_data.get("status") == "completed":
                    return "completed", status_data
                elif status_data.get("status") == "failed":
                    return "failed", status_data
            
            # Check for early completion (Revit closed cleanly)
            if self._check_early_completion():
                return "completed_early", {"reason": "Revit process completed before timeout"}
            
            # Check for stuck process (no heartbeat for too long)
            if self._check_stuck_process():
                return "stuck", {"reason": "No heartbeat for 5+ minutes"}
            
            # Check timeout
            if self._check_timeout():
                return "timeout", {"reason": f"Exceeded {self.timeout_seconds}s timeout"}
            
            # Still running
            return "running", {"elapsed": self._get_elapsed_seconds()}
            
        except Exception as e:
            return "error", {"error": str(e)}
    
    def _check_early_completion(self) -> bool:
        """Check if job completed early (Revit closed cleanly)"""
        # If status file shows completed, job is done
        if self.status_file.exists():
            try:
                with open(self.status_file, 'r') as f:
                    status_data = json.load(f)
                return status_data.get("status") in ["completed", "failed"]
            except:
                pass
        
        # Check if Revit process is still running
        # (This would require process monitoring in a real implementation)
        return False
    
    def _check_stuck_process(self) -> bool:
        """Check if process is stuck (no heartbeat for too long)"""
        if not self.heartbeat_file.exists():
            return False
        
        try:
            # Check last heartbeat time
            with open(self.heartbeat_file, 'r') as f:
                last_heartbeat_str = f.read().strip()
            
            if last_heartbeat_str:
                last_heartbeat = datetime.fromisoformat(last_heartbeat_str)
                time_since_heartbeat = datetime.now() - last_heartbeat
                
                # Consider stuck if no heartbeat for 5+ minutes
                return time_since_heartbeat > timedelta(minutes=5)
        
        except Exception:
            pass
        
        return False
    
    def _check_timeout(self) -> bool:
        """Check if job has exceeded timeout (activity-based - idle time only)"""
        # Activity-based timeout: only timeout if idle for too long
        # NOT based on total elapsed time
        idle_time = datetime.now() - self.last_activity_time
        idle_seconds = int(idle_time.total_seconds())
        return idle_seconds > self.timeout_seconds
    
    def _get_elapsed_seconds(self) -> int:
        """Get elapsed time in seconds"""
        return int((datetime.now() - self.start_time).total_seconds())
    
    def get_progress_info(self) -> Dict:
        """Get detailed progress information"""
        elapsed = self._get_elapsed_seconds()
        idle_time = datetime.now() - self.last_activity_time
        idle_seconds = int(idle_time.total_seconds())
        remaining = max(0, self.timeout_seconds - idle_seconds)
        
        return {
            "job_id": self.job_id,
            "elapsed_seconds": elapsed,
            "idle_seconds": idle_seconds,
            "remaining_seconds": remaining,
            "elapsed_minutes": round(elapsed / 60, 1),
            "idle_minutes": round(idle_seconds / 60, 1),
            "remaining_minutes": round(remaining / 60, 1),
            "progress_percent": min(100, round((elapsed / self.timeout_seconds) * 100, 1)),
            "start_time": self.start_time.isoformat(),
            "last_activity_time": self.last_activity_time.isoformat(),
            "timeout_seconds": self.timeout_seconds,
            "timeout_type": "idle"  # Indicate this is idle timeout, not total timeout
        }
    
    def cleanup(self):
        """Clean up monitoring files"""
        try:
            if self.status_file.exists():
                self.status_file.unlink()
            if self.heartbeat_file.exists():
                self.heartbeat_file.unlink()
            if self.log_file.exists():
                self.log_file.unlink()
        except Exception as e:
            print(f"[WARNING] Failed to cleanup monitoring files: {e}")
    
    def log_message(self, message: str):
        """Log a message to the job log file"""
        try:
            timestamp = datetime.now().isoformat()
            with open(self.log_file, 'a') as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception as e:
            print(f"[WARNING] Failed to log message: {e}")
    
    def has_heartbeat_updated(self) -> bool:
        """
        Check if heartbeat has been updated since last check.
        Updates last_activity_time to track idle time.
        
        Returns:
            True if heartbeat file changed, False otherwise
        """
        try:
            if not self.heartbeat_file.exists():
                return False
            
            # Read current heartbeat content
            with open(self.heartbeat_file, 'r') as f:
                current_heartbeat = f.read().strip()
            
            # Check if heartbeat changed
            if current_heartbeat and current_heartbeat != self.last_heartbeat_content:
                # Heartbeat updated! Reset activity time
                self.last_heartbeat_content = current_heartbeat
                self.last_heartbeat = datetime.now()
                self.last_activity_time = datetime.now()  # RESET timeout
                return True
            
            return False
            
        except Exception as e:
            # If we can't read heartbeat, assume no update
            return False
    
    def has_status_updated(self) -> bool:
        """
        Check if status file has been updated since last check.
        Updates last_activity_time to track idle time.
        
        Returns:
            True if status file changed, False otherwise
        """
        try:
            if not self.status_file.exists():
                return False
            
            # Read current status content
            with open(self.status_file, 'r') as f:
                current_status_json = f.read()
            
            # Check if status changed (by comparing JSON content)
            if current_status_json and current_status_json != self.last_status_content:
                # Status updated! Reset activity time
                self.last_status_content = current_status_json
                self.last_activity_time = datetime.now()  # RESET timeout
                return True
            
            return False
            
        except Exception as e:
            # If we can't read status, assume no update
            return False
    
    def get_idle_seconds(self) -> int:
        """
        Get the number of seconds since last activity (heartbeat or status update)
        
        Returns:
            Number of seconds idle
        """
        idle_time = datetime.now() - self.last_activity_time
        return int(idle_time.total_seconds())


class JobMonitorManager:
    """Manages multiple job monitors"""
    
    def __init__(self, database_dir: str):
        self.database_dir = Path(database_dir)
        self.active_monitors = {}
    
    def start_job_monitor(self, job_id: str, timeout_seconds: int) -> JobMonitor:
        """Start monitoring a new job"""
        monitor = JobMonitor(job_id, timeout_seconds, str(self.database_dir))
        if monitor.start_monitoring():
            self.active_monitors[job_id] = monitor
        return monitor
    
    def check_all_jobs(self) -> Dict[str, str]:
        """Check status of all active jobs"""
        results = {}
        for job_id, monitor in self.active_monitors.items():
            status, details = monitor.check_status()
            results[job_id] = status
            
            # Clean up completed jobs
            if status in ["completed", "completed_early", "failed", "timeout", "stuck"]:
                monitor.cleanup()
                del self.active_monitors[job_id]
        
        return results
    
    def get_active_job_count(self) -> int:
        """Get number of active jobs being monitored"""
        return len(self.active_monitors)
