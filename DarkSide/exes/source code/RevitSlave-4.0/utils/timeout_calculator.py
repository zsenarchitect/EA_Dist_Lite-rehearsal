"""
Intelligent Timeout Calculator for RevitSlave4
Calculates dynamic timeouts based on file size and Revit version
"""

from typing import Dict, Tuple
import math


class TimeoutCalculator:
    """
    Calculates intelligent timeouts for Revit job processing
    
    Based on:
    - File size (larger files = longer timeouts)
    - Revit version (newer versions = longer startup time)
    - Base processing time (minimum time for any file)
    """
    
    # Base IDLE timeout settings (in seconds)
    # These represent how long a job can be idle (no progress) before aborting
    # Note: Jobs can run indefinitely as long as they're making progress
    BASE_IDLE_TIMEOUT = 600          # 10 minutes minimum idle time
    STARTUP_TIME = 60                # 1 minute for Revit startup
    PER_MB_IDLE_TIMEOUT = 5          # 5 seconds per MB of file size (increased from 2)
    VERSION_MULTIPLIER = {           # Multiplier based on Revit version
        2020: 1.0,
        2021: 1.1,
        2022: 1.2,
        2023: 1.3,
        2024: 1.4,
        2025: 1.5
    }
    
    @classmethod
    def calculate_timeout(cls, file_size_bytes: int, revit_version: int) -> Tuple[int, Dict]:
        """
        Calculate intelligent timeout for a Revit file
        
        Args:
            file_size_bytes: Size of the Revit file in bytes
            revit_version: Revit version year (2020, 2021, etc.)
            
        Returns:
            Tuple of (timeout_seconds, calculation_details)
        """
        # Convert bytes to MB
        file_size_mb = file_size_bytes / (1024 * 1024)
        
        # Base idle timeout calculation
        base_idle_timeout = cls.BASE_IDLE_TIMEOUT + cls.STARTUP_TIME
        
        # File size component (how long we wait per MB of file)
        size_idle_timeout = file_size_mb * cls.PER_MB_IDLE_TIMEOUT
        
        # Version multiplier
        version_mult = cls.VERSION_MULTIPLIER.get(revit_version, 1.5)
        
        # Total idle timeout calculation
        # This is how long a job can be idle (no progress) before we abort it
        total_idle_timeout = int((base_idle_timeout + size_idle_timeout) * version_mult)
        
        # Cap at reasonable maximum (2 hours idle time)
        total_idle_timeout = min(total_idle_timeout, 7200)
        
        calculation_details = {
            "file_size_mb": round(file_size_mb, 1),
            "base_idle_timeout": cls.BASE_IDLE_TIMEOUT,
            "startup_time": cls.STARTUP_TIME,
            "size_idle_timeout": round(size_idle_timeout, 1),
            "version_multiplier": version_mult,
            "total_idle_timeout": total_idle_timeout,
            "idle_timeout_minutes": round(total_idle_timeout / 60, 1),
            "timeout_type": "idle"  # Indicate this is idle timeout
        }
        
        return total_idle_timeout, calculation_details
    
    @classmethod
    def get_timeout_summary(cls, jobs: list) -> Dict:
        """
        Get timeout summary for a batch of jobs
        
        Args:
            jobs: List of job payloads with file_size_bytes and revit_version
            
        Returns:
            Dictionary with timeout statistics
        """
        if not jobs:
            return {"total_jobs": 0, "avg_timeout_minutes": 0, "max_timeout_minutes": 0}
        
        timeouts = []
        for job in jobs:
            timeout, _ = cls.calculate_timeout(
                job.get("file_size_bytes", 0),
                job.get("revit_version", 2024)
            )
            timeouts.append(timeout)
        
        return {
            "total_jobs": len(jobs),
            "avg_idle_timeout_minutes": round(sum(timeouts) / len(timeouts) / 60, 1),
            "max_idle_timeout_minutes": round(max(timeouts) / 60, 1),
            "min_idle_timeout_minutes": round(min(timeouts) / 60, 1),
            "timeout_type": "idle"
        }
    
    @classmethod
    def format_timeout(cls, timeout_seconds: int) -> str:
        """Format timeout in human-readable format"""
        if timeout_seconds < 60:
            return f"{timeout_seconds}s"
        elif timeout_seconds < 3600:
            return f"{timeout_seconds // 60}m {timeout_seconds % 60}s"
        else:
            hours = timeout_seconds // 3600
            minutes = (timeout_seconds % 3600) // 60
            return f"{hours}h {minutes}m"
