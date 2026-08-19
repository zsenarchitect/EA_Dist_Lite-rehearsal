"""
Journal File Monitoring for RevitSlave4
Prevents massive journal files from consuming disk space

Incident: Oct 12-13, 2025 - A 151 GB journal file was created due to 
repeated error logging (240+ million identical errors in 22 hours)
"""

import os
import time
import threading
from pathlib import Path
from datetime import datetime


class JournalMonitor:
    """
    Monitor Revit journal file size during task execution.
    Aborts task if journal grows too large (indicates error loop).
    
    Usage:
        monitor = JournalMonitor(journal_path, max_size_mb=100)
        monitor.start()
        # ... run Revit task ...
        monitor.stop()
    """
    
    def __init__(self, journal_path, max_size_mb=100, check_interval=10, warning_threshold=0.5):
        """
        Initialize journal monitor
        
        Args:
            journal_path: Path to journal file
            max_size_mb: Maximum allowed size in MB before aborting
            check_interval: How often to check size (seconds)
            warning_threshold: Warn at this fraction of max_size (default 0.5 = 50%)
        """
        self.journal_path = Path(journal_path) if journal_path else None
        self.max_size_mb = max_size_mb
        self.check_interval = check_interval
        self.warning_threshold = warning_threshold
        self.monitoring = False
        self.thread = None
        self.size_exceeded = False
        self.current_size_mb = 0
    
    def start(self):
        """Start monitoring journal file size in background thread"""
        if not self.journal_path:
            print("[JOURNAL] No journal path provided, monitoring disabled")
            return False
        
        self.monitoring = True
        self.size_exceeded = False
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        print(f"[JOURNAL] Monitoring started: {self.journal_path.name}")
        print(f"[JOURNAL] Max size: {self.max_size_mb} MB, Check interval: {self.check_interval}s")
        return True
    
    def stop(self):
        """Stop monitoring"""
        self.monitoring = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        print(f"[JOURNAL] Monitoring stopped (final size: {self.current_size_mb:.1f} MB)")
    
    def is_size_exceeded(self):
        """Check if journal size exceeded limit"""
        return self.size_exceeded
    
    def _monitor_loop(self):
        """Background monitoring loop"""
        warning_issued = False
        
        while self.monitoring:
            try:
                if self.journal_path and self.journal_path.exists():
                    size_bytes = self.journal_path.stat().st_size
                    self.current_size_mb = size_bytes / (1024 * 1024)
                    
                    # Check for critical size
                    if self.current_size_mb > self.max_size_mb:
                        print("\n" + "="*80)
                        print("[CRITICAL] JOURNAL FILE SIZE EXCEEDED!")
                        print("="*80)
                        print(f"  Current size: {self.current_size_mb:.1f} MB")
                        print(f"  Maximum allowed: {self.max_size_mb} MB")
                        print(f"  Journal path: {self.journal_path}")
                        print("\n  POSSIBLE INFINITE ERROR LOOP DETECTED")
                        print("  Aborting task to prevent disk space disaster...")
                        print("="*80)
                        
                        self.size_exceeded = True
                        self.monitoring = False
                        
                        # Force abort (hard exit)
                        import sys
                        sys.exit(1)
                    
                    # Check for warning threshold
                    warning_size = self.max_size_mb * self.warning_threshold
                    if self.current_size_mb > warning_size and not warning_issued:
                        print(f"\n[WARNING] Journal file at {self.current_size_mb:.1f} MB "
                              f"({self.current_size_mb/self.max_size_mb*100:.0f}% of limit)")
                        warning_issued = True
                    
                    # Log size periodically (every 10 checks)
                    if hasattr(self, '_check_count'):
                        self._check_count += 1
                        if self._check_count % 10 == 0:
                            print(f"[JOURNAL] Current size: {self.current_size_mb:.1f} MB")
                    else:
                        self._check_count = 1
                
            except Exception as e:
                print(f"[JOURNAL] Error checking size: {e}")
            
            time.sleep(self.check_interval)
    
    def get_current_size(self):
        """Get current journal size in MB"""
        return self.current_size_mb


def find_journal_files(temp_dir=None):
    """
    Find Revit journal files in temp directory
    
    Args:
        temp_dir: Temp directory path (default: system temp)
        
    Returns:
        List of journal file paths
    """
    import tempfile
    
    if temp_dir is None:
        temp_dir = Path(tempfile.gettempdir())
    else:
        temp_dir = Path(temp_dir)
    
    if not temp_dir.exists():
        return []
    
    # Look for journal files in GUID-named folders
    journal_files = []
    
    try:
        for item in temp_dir.iterdir():
            if item.is_dir():
                # Check for journal files in this folder
                for pattern in ["journal.*.txt", "journal.*.log"]:
                    journal_files.extend(item.glob(pattern))
    except Exception as e:
        print(f"[JOURNAL] Error searching for journals: {e}")
    
    return journal_files


def backup_journal_to_debug(journal_path, task_name, debug_dir="DEBUG/logs/journals"):
    """
    Backup journal file to DEBUG folder for investigation.
    Only copies if file is reasonable size (< 10 MB).
    
    Args:
        journal_path: Path to journal file
        task_name: Name/ID of the task
        debug_dir: Debug directory path (relative to workspace root)
        
    Returns:
        Path to backup file if successful, None otherwise
    """
    import shutil
    
    journal_path = Path(journal_path)
    debug_path = Path(debug_dir)
    
    if not journal_path.exists():
        print(f"[JOURNAL] File not found: {journal_path}")
        return None
    
    # Check size
    size_mb = journal_path.stat().st_size / (1024 * 1024)
    
    if size_mb > 10:
        print(f"[JOURNAL] File too large ({size_mb:.1f} MB), skipping backup")
        return None
    
    # Create debug directory
    debug_path.mkdir(parents=True, exist_ok=True)
    
    # Generate backup filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_task_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in task_name)
    backup_filename = f"{safe_task_name}_{timestamp}_journal.txt"
    backup_path = debug_path / backup_filename
    
    try:
        shutil.copy2(journal_path, backup_path)
        print(f"[JOURNAL] Backed up to: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"[JOURNAL] Backup failed: {e}")
        return None


def detect_error_loop_in_journal(journal_path, sample_lines=100, error_threshold=50):
    """
    Detect if journal contains repeated error patterns (error loop indicator)
    
    Args:
        journal_path: Path to journal file
        sample_lines: Number of recent lines to check
        error_threshold: Number of error indicators that suggests a loop
        
    Returns:
        (is_loop_detected, error_count, sample_errors)
    """
    journal_path = Path(journal_path)
    
    if not journal_path.exists():
        return (False, 0, [])
    
    # Error indicators in Revit journals
    error_indicators = [
        'Jrn.AutoConvertedMessageBox',
        'String_Revit_CantCreateFile',
        'MessageId:',
        '[ERROR]',
        'Exception'
    ]
    
    try:
        # Read last N lines
        with open(journal_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Seek to end and read backwards (simplified - just read last chunk)
            file_size = journal_path.stat().st_size
            chunk_size = min(100000, file_size)  # Read last 100KB
            
            f.seek(max(0, file_size - chunk_size))
            content = f.read()
            lines = content.split('\n')[-sample_lines:]
        
        # Count error indicators
        error_count = 0
        sample_errors = []
        
        for indicator in error_indicators:
            count = sum(1 for line in lines if indicator in line)
            if count > 0:
                error_count += count
                if count > 10:  # Sample first occurrence
                    for line in lines:
                        if indicator in line:
                            sample_errors.append(line.strip()[:200])
                            break
        
        # More than threshold errors in recent lines = likely loop
        is_loop = error_count > error_threshold
        
        return (is_loop, error_count, sample_errors[:5])
        
    except Exception as e:
        print(f"[JOURNAL] Error analyzing journal: {e}")
        return (False, 0, [])


if __name__ == "__main__":
    """Test journal monitoring"""
    import tempfile
    
    print("="*80)
    print("Journal Monitor Test")
    print("="*80)
    
    # Create test journal file
    test_journal = Path(tempfile.gettempdir()) / "test_journal.txt"
    
    print(f"\n[TEST] Creating test journal: {test_journal}")
    with open(test_journal, 'w') as f:
        f.write("Test journal file\n")
    
    # Test monitoring
    print("\n[TEST] Starting monitor (max 1 MB, 2s checks)...")
    monitor = JournalMonitor(test_journal, max_size_mb=1, check_interval=2)
    monitor.start()
    
    print("[TEST] Monitoring for 5 seconds...")
    time.sleep(5)
    
    print(f"[TEST] Current size: {monitor.get_current_size():.3f} MB")
    
    monitor.stop()
    
    # Cleanup
    test_journal.unlink()
    
    print("\n" + "="*80)
    print("[SUCCESS] Test completed")
    print("="*80)

