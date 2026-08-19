"""
RevitSlave4 Settings
All configuration organized by category
"""

from pathlib import Path
from typing import Tuple


class CacheSettings:
    """GUID cache configuration"""
    EXPIRY_DAYS = 7
    FILE_NAME = "guid_cache.json"
    
    @classmethod
    def get_cache_dir(cls):
        """Get cache directory path - same as RevitSlave2"""
        import os
        from pathlib import Path
        username = os.environ.get('USERNAME', 'USERNAME')
        return Path("C:/Users") / username / "Documents" / "EnneadTab Ecosystem" / "Dump" / "RevitSlaveDatabase"


class FolderFilterSettings:
    """Folder path filtering configuration"""
    
    # Folder keywords to EXCLUDE (case-insensitive)
    # Files in folders containing these keywords will be skipped
    EXCLUDE_FOLDER_KEYWORDS = [
        'shared',
        'consumed',
        'study',
        'archive',
        'archived',
        'backup',
        'old',
        'test',
        'temp',
        '_temp',
        'do not use',
        'obsolete',
        'superseded',
        'legacy'
    ]
    
    @classmethod
    def should_exclude_folder(cls, folder_path: str) -> Tuple[bool, str]:
        """
        Check if folder path should be excluded based on keywords
        
        Args:
            folder_path: Folder path string (e.g., "Engineering/Archive/Models")
            
        Returns:
            (should_exclude, reason) - True if should skip, False otherwise
        """
        if not folder_path:
            return (False, "")
        
        folder_lower = folder_path.lower()
        
        for keyword in cls.EXCLUDE_FOLDER_KEYWORDS:
            if keyword in folder_lower:
                return (True, f"Folder contains '{keyword}'")
        
        return (False, "")


class FileIgnoreSettings:
    """Per-file ignore configuration"""
    
    ENABLED = True
    IGNORE_FILE_NAME = "ignore_files.txt"
    _cached_entries = None
    
    @classmethod
    def get_ignore_file_path(cls):
        """Get path to ignore list file"""
        return Path(__file__).parent / cls.IGNORE_FILE_NAME
    
    @classmethod
    def get_ignore_entries(cls):
        """
        Load ignore entries from file.
        
        Returns:
            List of dictionaries with raw and normalized values.
        """
        if not cls.ENABLED:
            return []
        
        if cls._cached_entries is not None:
            return cls._cached_entries
        
        path = cls.get_ignore_file_path()
        entries = []
        
        if not path.exists():
            cls._cached_entries = []
            return cls._cached_entries
        
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    entries.append({
                        "raw": stripped,
                        "normalized": stripped.lower()
                    })
        except Exception as exc:
            print(f"[WARNING] Could not load ignore file list ({path}): {exc}")
            entries = []
        
        cls._cached_entries = entries
        return cls._cached_entries
    
    @classmethod
    def reload(cls):
        """Clear cache and reload entries"""
        cls._cached_entries = None
        return cls.get_ignore_entries()
    
    @classmethod
    def should_ignore_file(cls, project_name: str, file_name: str, folder_path: str = "") -> Tuple[bool, str]:
        """
        Determine if a file should be ignored.
        
        Checks against:
            - File name
            - Project/file combination
            - Folder/file combination
        
        Args:
            project_name: ACC project name
            file_name: Revit file name
            folder_path: ACC folder path (may be empty)
        
        Returns:
            (should_ignore, reason)
        """
        if not cls.ENABLED:
            return (False, "")
        
        entries = cls.get_ignore_entries()
        if not entries:
            return (False, "")
        
        file_name_norm = file_name.lower()
        project_name_norm = project_name.lower()
        folder_norm = folder_path.lower() if folder_path else ""
        
        candidates = {
            file_name_norm,
            f"{project_name_norm}/{file_name_norm}",
        }
        
        if folder_norm:
            candidates.add(f"{folder_norm}/{file_name_norm}")
        
        for entry in entries:
            if entry["normalized"] in candidates:
                return (True, f"Ignore list match '{entry['raw']}'")
        
        return (False, "")


class ProjectFilterSettings:
    """Project name filtering configuration"""
    
    # Project filtering control
    ENABLED = False
    PROJECT_NAMES = []  # Empty = process all projects
    
    @classmethod
    def should_include_project(cls, project_name: str) -> bool:
        """
        Check if project should be included based on filter
        
        Args:
            project_name: Project name string (e.g., "2412_SPARC")
            
        Returns:
            True if should process, False if should skip
        """
        if not cls.ENABLED or not cls.PROJECT_NAMES:
            return True
        
        project_lower = project_name.lower()
        for filter_name in cls.PROJECT_NAMES:
            if filter_name.lower() in project_lower:
                return True
        return False


class TimeoutSettings:
    """Timeout configuration for cloud GUID opening"""
    
    # File size tiers (MB)
    SMALL_FILE_MB = 100
    MEDIUM_FILE_MB = 500
    LARGE_FILE_MB = 1000
    
    # Timeout values (minutes)
    SMALL_MINUTES = 5
    MEDIUM_MINUTES = 20
    LARGE_MINUTES = 30
    MAX_MINUTES = 45
    
    @classmethod
    def calculate_timeout(cls, file_size_bytes):
        """
        Calculate proportional timeout based on file size
        
        Args:
            file_size_bytes: File size from API metadata
            
        Returns:
            timeout_seconds: Maximum allowed time
        """
        file_size_mb = file_size_bytes / (1024 * 1024)
        
        if file_size_mb < cls.SMALL_FILE_MB:
            timeout_minutes = cls.SMALL_MINUTES
        elif file_size_mb < cls.MEDIUM_FILE_MB:
            # Linear scale: 5-20 min
            ratio = (file_size_mb - cls.SMALL_FILE_MB) / (cls.MEDIUM_FILE_MB - cls.SMALL_FILE_MB)
            timeout_minutes = cls.SMALL_MINUTES + (cls.MEDIUM_MINUTES - cls.SMALL_MINUTES) * ratio
        elif file_size_mb < cls.LARGE_FILE_MB:
            # Linear scale: 20-30 min
            ratio = (file_size_mb - cls.MEDIUM_FILE_MB) / (cls.LARGE_FILE_MB - cls.MEDIUM_FILE_MB)
            timeout_minutes = cls.MEDIUM_MINUTES + (cls.LARGE_MINUTES - cls.MEDIUM_MINUTES) * ratio
        else:
            # Cap at MAX_MINUTES
            extra_time = min((file_size_mb - cls.LARGE_FILE_MB) * 0.01, cls.MAX_MINUTES - cls.LARGE_MINUTES)
            timeout_minutes = cls.LARGE_MINUTES + extra_time
        
        return int(timeout_minutes * 60)  # Convert to seconds
    
    @classmethod
    def format_timeout(cls, timeout_seconds):
        """Format timeout for display"""
        minutes = timeout_seconds / 60
        return f"{minutes:.1f} min ({timeout_seconds}s)"


class MonitoringSettings:
    """Job monitoring configuration"""
    CHECK_INTERVAL_SECONDS = 2         # Check status every 2 seconds
    HEARTBEAT_TIMEOUT_SECONDS = 300    # 5 min without heartbeat = stuck


class ValidationSettings:
    """Model pre-validation configuration (RevitSlave4 feature)"""
    
    # Feature control
    ENABLED = True  # Enable pre-validation via APS API
    
    # Validation behavior
    SKIP_INVALID_MODELS = True  # Skip models that fail validation
    FAIL_ON_API_ERROR = False  # If False, proceed anyway on API errors (safer)
    
    # Performance
    VALIDATION_TIMEOUT_SECONDS = 10  # Per-model API call timeout
    RATE_LIMIT_DELAY_SECONDS = 0.6  # Delay between calls (~100/min limit)
    
    # Reporting
    VERBOSE_VALIDATION = True  # Print validation progress
    LOG_SKIPPED_MODELS = True  # Log all skipped models
    MAX_DISPLAYED_SKIPPED = 10  # Max skipped models to print
    
    # Thresholds
    MIN_SUCCESS_RATE = 0.1  # If <10% validate successfully, disable validation
    SUGGEST_REFRESH_THRESHOLD = 0.5  # If >50% skipped, suggest cache refresh


class APISettings:
    """APS API configuration - comprehensive discovery"""
    TOKEN_BUFFER_SECONDS = 300          # Refresh token 5 min before expiry
    REQUEST_TIMEOUT_SECONDS = 30        # API request timeout
    MAX_FOLDER_DEPTH = 50               # Allow deep folder structures
    MAX_FILES_PER_PROJECT = None        # No limit - find ALL files


class ProcessingSettings:
    """Job processing configuration"""
    REVIT_STARTUP_DELAY_SECONDS = 3     # Wait before launching Revit
    REVIT_STABILITY_WAIT_SECONDS = 10   # Wait between jobs
    MAX_JOB_RUNTIME_SECONDS = 15 * 60   # Kill Revit if job exceeds 15 minutes total runtime


class AppSettings:
    """Application-level settings"""
    APP_NAME = "RevitSlave4"
    APP_VERSION = "4.0.0"
    APP_DESCRIPTION = "API-First Batch Processing with Model Pre-Validation"

