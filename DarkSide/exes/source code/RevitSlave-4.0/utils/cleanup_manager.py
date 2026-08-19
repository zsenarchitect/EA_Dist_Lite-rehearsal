"""
Cleanup Manager for RevitSlave4
Prevents database folder from growing too large by removing old files.

Cleans up:
- Task output files (older than 2 days)
- Debug files (older than 2 days)
- Log files (older than 2 days)
- Journal backups in DEBUG folder (older than 2 days)
- Root status/heartbeat/launch files (older than 2 days)
- Empty directories
Preserves:
- GUID cache file (guid_cache.json)
"""

import os
import sys
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any

# Add parent directory to path for imports when running as standalone script
if __name__ == "__main__":
    script_dir = Path(__file__).parent
    revitslave_dir = script_dir.parent
    sys.path.insert(0, str(revitslave_dir))


class CleanupStats:
    """Track cleanup statistics"""
    def __init__(self):
        self.files_deleted = 0
        self.dirs_deleted = 0
        self.bytes_freed = 0
        self.errors = []
    
    def add_file(self, size_bytes: int):
        """Record a deleted file"""
        self.files_deleted += 1
        self.bytes_freed += size_bytes
    
    def add_dir(self):
        """Record a deleted directory"""
        self.dirs_deleted += 1
    
    def add_error(self, path: str, error: str):
        """Record an error"""
        self.errors.append((path, error))
    
    def get_summary(self) -> str:
        """Get formatted summary"""
        size_mb = self.bytes_freed / (1024 * 1024)
        size_gb = self.bytes_freed / (1024 * 1024 * 1024)
        
        if size_gb >= 1.0:
            size_str = f"{size_gb:.2f} GB"
        else:
            size_str = f"{size_mb:.2f} MB"
        
        summary = [
            f"Files deleted: {self.files_deleted}",
            f"Directories deleted: {self.dirs_deleted}",
            f"Space freed: {size_str}",
        ]
        
        if self.errors:
            summary.append(f"Errors: {len(self.errors)}")
        
        return " | ".join(summary)


class CleanupManager:
    """
    Manages cleanup of old files in RevitSlave database folders.
    
    Usage:
        cleaner = CleanupManager(days_to_keep=2, dry_run=False)
        stats = cleaner.cleanup_all()
        print(stats.get_summary())
    """
    
    def __init__(self, days_to_keep: int = 2, dry_run: bool = False, verbose: bool = True):
        """
        Initialize cleanup manager
        
        Args:
            days_to_keep: Files older than this will be deleted (default 2)
            dry_run: If True, only report what would be deleted without actually deleting
            verbose: If True, print detailed progress (default True)
        """
        self.days_to_keep = days_to_keep
        self.dry_run = dry_run
        self.verbose = verbose
        self.cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        # Get database folder path
        from config.settings import CacheSettings
        self.database_folder = CacheSettings.get_cache_dir()
        self.protected_files = {CacheSettings.FILE_NAME.lower()}
        
        # Get workspace DEBUG folder (relative to script location)
        self.debug_folder = self._get_workspace_debug_folder()
    
    def _get_workspace_debug_folder(self) -> Path:
        """Get workspace DEBUG folder path"""
        # Go up from utils/ to workspace root
        script_dir = Path(__file__).parent
        workspace_root = script_dir.parent.parent.parent.parent  # up 4 levels
        return workspace_root / "DEBUG"
    
    def cleanup_all(self) -> CleanupStats:
        """
        Clean up all RevitSlave data folders
        
        Returns:
            CleanupStats with results
        """
        stats = CleanupStats()
        
        mode = "DRY RUN" if self.dry_run else "CLEANUP"
        
        if self.verbose:
            print(f"\n[{mode}] Starting cleanup (keeping files newer than {self.days_to_keep} days)")
            print(f"  Cutoff date: {self.cutoff_date.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  Database folder: {self.database_folder}")
        
        # Clean task outputs
        if self.verbose:
            print(f"\n[{mode}] Cleaning task outputs...")
        task_output_dir = self.database_folder / "task_output"
        if task_output_dir.exists():
            self._cleanup_directory(task_output_dir, stats, recursive=True)
        elif self.verbose:
            print(f"  Directory not found: {task_output_dir}")
        
        # Clean debug folder
        if self.verbose:
            print(f"\n[{mode}] Cleaning debug folder...")
        debug_dir = self.database_folder / "debug"
        if debug_dir.exists():
            self._cleanup_directory(debug_dir, stats, recursive=True)
        elif self.verbose:
            print(f"  Directory not found: {debug_dir}")
        
        # Clean log folder
        if self.verbose:
            print(f"\n[{mode}] Cleaning log folder...")
        log_dir = self.database_folder / "logs"
        if log_dir.exists():
            self._cleanup_directory(log_dir, stats, recursive=True)
        elif self.verbose:
            print(f"  Directory not found: {log_dir}")
        
        # Clean workspace DEBUG folder (journal backups)
        if self.verbose:
            print(f"\n[{mode}] Cleaning workspace DEBUG folder...")
        if self.debug_folder.exists():
            self._cleanup_directory(self.debug_folder, stats, recursive=True)
        elif self.verbose:
            print(f"  Directory not found: {self.debug_folder}")
        
        # Clean root-level files (status, heartbeat, etc.)
        if self.verbose:
            print(f"\n[{mode}] Cleaning database root files...")
        self._cleanup_directory(self.database_folder, stats, recursive=False)
        
        # Clean up empty directories
        if self.verbose:
            print(f"\n[{mode}] Removing empty directories...")
        self._cleanup_empty_dirs(task_output_dir, stats)
        self._cleanup_empty_dirs(debug_dir, stats)
        self._cleanup_empty_dirs(log_dir, stats)
        self._cleanup_empty_dirs(self.debug_folder, stats)
        
        # Print summary
        if self.verbose:
            print(f"\n[{mode}] Cleanup complete!")
            print(f"  {stats.get_summary()}")
            
            if stats.errors:
                print(f"\n[{mode}] Errors encountered:")
                for path, error in stats.errors[:10]:  # Show first 10 errors
                    print(f"  {path}: {error}")
                if len(stats.errors) > 10:
                    print(f"  ... and {len(stats.errors) - 10} more errors")
        
        return stats
    
    def _cleanup_directory(self, directory: Path, stats: CleanupStats, recursive: bool = True):
        """
        Clean up old files in a directory
        
        Args:
            directory: Directory to clean
            stats: Statistics tracker
            recursive: If True, recurse into subdirectories
        """
        if not directory.exists():
            return
        
        try:
            for item in directory.iterdir():
                try:
                    if item.is_file():
                        if not self._should_skip_file(item):
                            self._process_file(item, stats)
                    elif item.is_dir() and recursive:
                        # Recurse into subdirectories
                        self._cleanup_directory(item, stats, recursive=True)
                except Exception as e:
                    stats.add_error(str(item), str(e))
                    
        except Exception as e:
            stats.add_error(str(directory), f"Error scanning directory: {e}")
    
    def _process_file(self, file_path: Path, stats: CleanupStats):
        """
        Process a single file - delete if older than cutoff
        
        Args:
            file_path: File to process
            stats: Statistics tracker
        """
        try:
            # Get file modification time
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            
            # Check if file is older than cutoff
            if mtime < self.cutoff_date:
                # Get file size before deletion
                size_bytes = file_path.stat().st_size
                
                # Format dates for logging
                age_days = (datetime.now() - mtime).days
                
                if self.verbose:
                    if self.dry_run:
                        print(f"  [DRY RUN] Would delete: {file_path.name} ({age_days} days old, {size_bytes / (1024*1024):.2f} MB)")
                    else:
                        print(f"  Deleted: {file_path.name} ({age_days} days old)")
                
                if not self.dry_run:
                    file_path.unlink()
                
                stats.add_file(size_bytes)
                
        except Exception as e:
            stats.add_error(str(file_path), str(e))
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """
        Determine if a file should be skipped during cleanup.
        Preserves GUID cache file regardless of age.
        """
        return file_path.name.lower() in self.protected_files
    
    def _cleanup_empty_dirs(self, root_dir: Path, stats: CleanupStats):
        """
        Remove empty directories (bottom-up to handle nested empties)
        
        Args:
            root_dir: Root directory to start from
            stats: Statistics tracker
        """
        if not root_dir.exists():
            return
        
        try:
            # Walk bottom-up so we can remove nested empty dirs
            for dirpath, _dirnames, _filenames in os.walk(root_dir, topdown=False):
                dir_path = Path(dirpath)
                
                # Skip the root directory itself
                if dir_path == root_dir:
                    continue
                
                try:
                    # Check if directory is empty
                    if not any(dir_path.iterdir()):
                        if self.verbose:
                            if self.dry_run:
                                print(f"  [DRY RUN] Would remove empty dir: {dir_path.relative_to(root_dir)}")
                            else:
                                print(f"  Removed empty dir: {dir_path.relative_to(root_dir)}")
                        
                        if not self.dry_run:
                            dir_path.rmdir()
                        
                        stats.add_dir()
                        
                except Exception as e:
                    stats.add_error(str(dir_path), str(e))
                    
        except Exception as e:
            stats.add_error(str(root_dir), f"Error walking directory: {e}")
    
    def get_folder_size(self, folder: Path) -> int:
        """
        Calculate total size of a folder
        
        Args:
            folder: Folder to measure
            
        Returns:
            Total size in bytes
        """
        total_size = 0
        
        if not folder.exists():
            return 0
        
        try:
            for item in folder.rglob('*'):
                if item.is_file():
                    try:
                        total_size += item.stat().st_size
                    except Exception:
                        pass  # Skip files we can't read
        except Exception:
            pass
        
        return total_size
    
    def get_database_info(self) -> Dict[str, Any]:
        """
        Get information about database folder sizes
        
        Returns:
            Dictionary with folder sizes and file counts
        """
        info = {}
        
        # Task output
        task_output_dir = self.database_folder / "task_output"
        info['task_output'] = {
            'exists': task_output_dir.exists(),
            'size_bytes': self.get_folder_size(task_output_dir),
            'file_count': sum(1 for _ in task_output_dir.rglob('*') if _.is_file()) if task_output_dir.exists() else 0
        }
        
        # Debug
        debug_dir = self.database_folder / "debug"
        info['debug'] = {
            'exists': debug_dir.exists(),
            'size_bytes': self.get_folder_size(debug_dir),
            'file_count': sum(1 for _ in debug_dir.rglob('*') if _.is_file()) if debug_dir.exists() else 0
        }
        
        # Logs
        log_dir = self.database_folder / "logs"
        info['logs'] = {
            'exists': log_dir.exists(),
            'size_bytes': self.get_folder_size(log_dir),
            'file_count': sum(1 for _ in log_dir.rglob('*') if _.is_file()) if log_dir.exists() else 0
        }
        
        # Workspace DEBUG
        info['workspace_debug'] = {
            'exists': self.debug_folder.exists(),
            'size_bytes': self.get_folder_size(self.debug_folder),
            'file_count': sum(1 for _ in self.debug_folder.rglob('*') if _.is_file()) if self.debug_folder.exists() else 0
        }
        
        # Total
        info['total'] = {
            'size_bytes': sum(d['size_bytes'] for d in info.values() if isinstance(d, dict)),
            'file_count': sum(d['file_count'] for d in info.values() if isinstance(d, dict))
        }
        
        return info
    
    def print_database_info(self):
        """Print formatted database information"""
        info = self.get_database_info()
        
        print("\n[DATABASE INFO] Current folder sizes:")
        print(f"  Database location: {self.database_folder}")
        print()
        
        for folder_name, folder_info in info.items():
            if folder_name == 'total':
                continue
            
            if not folder_info['exists']:
                print(f"  {folder_name}: Not found")
                continue
            
            size_bytes = folder_info['size_bytes']
            size_gb = size_bytes / (1024 ** 3)
            size_mb = size_bytes / (1024 ** 2)
            
            if size_gb >= 1.0:
                size_str = f"{size_gb:.2f} GB"
            else:
                size_str = f"{size_mb:.2f} MB"
            
            print(f"  {folder_name}: {size_str} ({folder_info['file_count']} files)")
        
        print()
        total_gb = info['total']['size_bytes'] / (1024 ** 3)
        total_mb = info['total']['size_bytes'] / (1024 ** 2)
        total_str = f"{total_gb:.2f} GB" if total_gb >= 1.0 else f"{total_mb:.2f} MB"
        print(f"  TOTAL: {total_str} ({info['total']['file_count']} files)")
    
    def cleanup_windows_temp_folder(self, aggressive: bool = True) -> CleanupStats:
        """
        Clean Revit-related temp files from Windows TEMP folder.
        
        This targets the PRIMARY cause of 150+ GB temp folder buildup:
        - ACC CentralCache folders: {GUID}/_CC/{GUID}/LinkedModels/*.rvt
        - ACC CentralCache folders: {GUID}/_CC/{GUID}/CentralCache/*.rvt
        
        Real-world example: 640 Revit temp files = 185.18 GB!
        Typical pattern: C:\\Users\\USERNAME\\AppData\\Local\\Temp\\{GUID}\\_CC\\{GUID}\\*
        
        Args:
            aggressive: If True, clean all _CC folders. If False, only old ones
            
        Returns:
            CleanupStats with results
        """
        stats = CleanupStats()
        
        # Get Windows TEMP folder
        import tempfile
        temp_folder = Path(tempfile.gettempdir())
        
        mode = "DRY RUN" if self.dry_run else "CLEANUP"
        
        if self.verbose:
            print(f"\n[{mode}] Windows TEMP Folder Cleanup")
            print(f"  Location: {temp_folder}")
            print(f"  Targeting: ACC CentralCache (_CC) folders")
        
        try:
            # Find all folders with _CC pattern (ACC Desktop Connector cache)
            cc_folders_found = 0
            
            # Scan top-level GUID folders in temp
            for item in temp_folder.iterdir():
                if not item.is_dir():
                    continue
                
                # Look for _CC subfolder (ACC CentralCache)
                cc_folder = item / "_CC"
                if cc_folder.exists() and cc_folder.is_dir():
                    cc_folders_found += 1
                    
                    # Get size before deletion
                    folder_size = self._get_folder_size_recursive(cc_folder)
                    
                    if self.verbose:
                        size_gb = folder_size / (1024 ** 3)
                        size_mb = folder_size / (1024 ** 2)
                        size_str = f"{size_gb:.2f} GB" if size_gb >= 0.1 else f"{size_mb:.2f} MB"
                        
                        if self.dry_run:
                            print(f"  [DRY RUN] Would delete: {cc_folder.name} ({size_str})")
                        else:
                            print(f"  Deleting _CC cache: {item.name}/_CC ({size_str})")
                    
                    # Delete the entire _CC folder tree
                    if not self.dry_run:
                        try:
                            shutil.rmtree(cc_folder, ignore_errors=True)
                            stats.bytes_freed += folder_size
                            stats.dirs_deleted += 1
                        except Exception as e:
                            stats.add_error(str(cc_folder), str(e))
                    else:
                        # Dry run - just record stats
                        stats.bytes_freed += folder_size
                        stats.dirs_deleted += 1
            
            # Also clean other Revit-related temps (secondary targets)
            self._cleanup_revit_secondary_temps(temp_folder, stats)
            
            if self.verbose:
                if cc_folders_found == 0:
                    print(f"  No _CC folders found (already clean)")
                else:
                    print(f"  Found {cc_folders_found} _CC cache folders")
            
        except Exception as e:
            stats.add_error(str(temp_folder), f"Error scanning temp folder: {e}")
        
        return stats
    
    def _get_folder_size_recursive(self, folder: Path) -> int:
        """
        Calculate total size of a folder recursively
        
        Args:
            folder: Folder to measure
            
        Returns:
            Total size in bytes
        """
        total_size = 0
        
        try:
            for item in folder.rglob('*'):
                if item.is_file():
                    try:
                        total_size += item.stat().st_size
                    except Exception:
                        pass  # Skip files we can't read
        except Exception:
            pass  # Skip if we can't access folder
        
        return total_size
    
    def _cleanup_revit_secondary_temps(self, temp_folder: Path, stats: CleanupStats):
        """
        Clean secondary Revit temp files (journals, revitslave extractions)
        
        Args:
            temp_folder: Windows TEMP folder path
            stats: Statistics tracker
        """
        try:
            # Clean journal files
            for journal_file in temp_folder.glob("**/journal*.txt"):
                if journal_file.is_file():
                    try:
                        size_bytes = journal_file.stat().st_size
                        
                        if not self.dry_run:
                            journal_file.unlink()
                        
                        stats.add_file(size_bytes)
                    except Exception as e:
                        stats.add_error(str(journal_file), str(e))
            
            # Clean revitslave extraction temps
            for item in temp_folder.iterdir():
                if item.is_dir() and item.name.startswith("revitslave"):
                    try:
                        folder_size = self._get_folder_size_recursive(item)
                        
                        if not self.dry_run:
                            shutil.rmtree(item, ignore_errors=True)
                        
                        stats.bytes_freed += folder_size
                        stats.dirs_deleted += 1
                    except Exception as e:
                        stats.add_error(str(item), str(e))
                        
        except Exception as e:
            # Non-critical - don't break if secondary cleanup fails
            if self.verbose:
                print(f"  [WARNING] Secondary cleanup partial failure: {e}")


def cleanup_old_files(days_to_keep: int = 2, dry_run: bool = False) -> CleanupStats:
    """
    Convenience function to clean up old files
    
    Args:
        days_to_keep: Files older than this will be deleted (default 2)
        dry_run: If True, only report what would be deleted
        
    Returns:
        CleanupStats with results
    """
    cleaner = CleanupManager(days_to_keep=days_to_keep, dry_run=dry_run)
    return cleaner.cleanup_all()


def print_database_info():
    """Convenience function to print database information"""
    cleaner = CleanupManager()
    cleaner.print_database_info()


# Test/CLI interface
if __name__ == "__main__":
    import sys
    
    print("=" * 80)
    print("RevitSlave4 Cleanup Manager")
    print("=" * 80)
    
    # Parse arguments
    dry_run = "--dry-run" in sys.argv or "-d" in sys.argv
    days = 2
    
    for arg in sys.argv[1:]:
        if arg.startswith("--days="):
            try:
                days = int(arg.split("=")[1])
            except ValueError:
                print(f"Invalid days value: {arg}")
                sys.exit(1)
    
    # Show current state
    cleaner = CleanupManager(days_to_keep=days, dry_run=dry_run)
    cleaner.print_database_info()
    
    # Run cleanup
    if "--info-only" in sys.argv or "-i" in sys.argv:
        print("\n[INFO] Info-only mode, skipping cleanup")
    else:
        stats = cleaner.cleanup_all()
        
        # Show updated state if not dry run
        if not dry_run:
            print("\n" + "=" * 80)
            cleaner.print_database_info()
    
    print("\n" + "=" * 80)
    print("Usage:")
    print("  python cleanup_manager.py              # Run cleanup (2 days)")
    print("  python cleanup_manager.py --dry-run    # Preview what would be deleted")
    print("  python cleanup_manager.py --days=7     # Keep only last 7 days")
    print("  python cleanup_manager.py --info-only  # Show folder sizes only")
    print("=" * 80)

