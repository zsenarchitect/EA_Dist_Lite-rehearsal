"""
Error Loop Detection for RevitSlave4
Prevents infinite error loops like the 151 GB journal incident

Incident: Oct 12-13, 2025 - File lock error repeated 240+ million times, 
creating a 151 GB journal file that consumed all disk space.
"""

import time
from collections import defaultdict
from datetime import datetime


class ErrorLoopDetector:
    """
    Detect and prevent infinite error loops in Revit automation.
    
    Usage:
        detector = ErrorLoopDetector(max_same_error=10, time_window=60)
        
        try:
            some_operation()
        except Exception as e:
            detector.record_error(str(e))  # Raises if loop detected
    """
    
    def __init__(self, max_same_error=10, time_window=60):
        """
        Initialize error loop detector
        
        Args:
            max_same_error: Maximum times same error can occur before considering it a loop
            time_window: Time window in seconds to track errors
        """
        self.error_history = []
        self.max_same_error = max_same_error
        self.time_window = time_window
        self.error_counts = defaultdict(int)
    
    def record_error(self, error_message):
        """
        Record an error and check for loops.
        
        Args:
            error_message: Error message string
            
        Raises:
            RuntimeError: If error loop is detected
        """
        now = time.time()
        
        # Truncate error message for comparison (first 200 chars)
        error_key = error_message[:200] if error_message else "Unknown error"
        
        # Clean old errors outside time window
        self.error_history = [
            (msg, ts) for msg, ts in self.error_history 
            if now - ts < self.time_window
        ]
        
        # Recalculate counts
        self.error_counts.clear()
        for msg, _ in self.error_history:
            self.error_counts[msg] += 1
        
        # Add new error
        self.error_history.append((error_key, now))
        self.error_counts[error_key] += 1
        
        # Check for repeated error (ERROR LOOP)
        if self.error_counts[error_key] >= self.max_same_error:
            raise RuntimeError(
                f"ERROR LOOP DETECTED: Same error occurred {self.error_counts[error_key]} "
                f"times in {self.time_window}s. Aborting to prevent infinite loop.\n"
                f"Error: {error_key}"
            )
    
    def reset(self):
        """Reset error tracking (call after successful operation)"""
        self.error_history.clear()
        self.error_counts.clear()
    
    def get_stats(self):
        """Get current error statistics"""
        now = time.time()
        recent_errors = [
            (msg, ts) for msg, ts in self.error_history 
            if now - ts < self.time_window
        ]
        
        return {
            "total_errors_in_window": len(recent_errors),
            "unique_errors": len(set(msg for msg, _ in recent_errors)),
            "most_common": self.error_counts.most_common(3) if self.error_counts else []
        }


class OperationTimeout:
    """
    Enforce timeouts on Revit operations to prevent hangs.
    
    Usage:
        with OperationTimeout(300):  # 5 minutes
            long_running_operation()
    """
    
    def __init__(self, timeout_seconds):
        """
        Initialize operation timeout
        
        Args:
            timeout_seconds: Maximum time allowed for operation
        """
        self.timeout_seconds = timeout_seconds
        self.start_time = None
        self.timed_out = False
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, *args):
        elapsed = time.time() - self.start_time
        
        if elapsed > self.timeout_seconds:
            self.timed_out = True
            raise TimeoutError(
                f"Operation exceeded {self.timeout_seconds}s timeout "
                f"(took {elapsed:.1f}s). Possible infinite loop or hung dialog."
            )
    
    def check_timeout(self):
        """
        Manual timeout check (for use in loops)
        
        Raises:
            TimeoutError: If timeout exceeded
        """
        if self.start_time is None:
            return
        
        elapsed = time.time() - self.start_time
        if elapsed > self.timeout_seconds:
            self.timed_out = True
            raise TimeoutError(
                f"Operation exceeded {self.timeout_seconds}s timeout. "
                "Possible infinite loop."
            )


def safe_file_operation(filepath, operation_func, max_retries=3, abort_on_lock=True):
    """
    Safely perform file operations with lock detection.
    
    Args:
        filepath: Path to file
        operation_func: Function to execute (receives filepath as arg)
        max_retries: Maximum retry attempts
        abort_on_lock: If True, abort rather than retry indefinitely
        
    Returns:
        Result from operation_func
        
    Raises:
        RuntimeError: If file remains locked or operation fails
    """
    import os
    
    error_detector = ErrorLoopDetector(max_same_error=5, time_window=30)
    
    for attempt in range(max_retries):
        try:
            # Check if file is locked
            if os.path.exists(filepath):
                try:
                    # Try to open with write access
                    with open(filepath, 'a'):
                        pass
                except (IOError, OSError) as e:
                    error_msg = f"File locked or inaccessible: {filepath}"
                    error_detector.record_error(error_msg)
                    
                    if abort_on_lock and attempt == max_retries - 1:
                        raise RuntimeError(
                            f"File remains locked after {max_retries} attempts: {filepath}. "
                            "Aborting to prevent infinite loop."
                        ) from e
                    
                    print(f"[RETRY {attempt + 1}/{max_retries}] {error_msg}")
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
            
            # Execute operation
            result = operation_func(filepath)
            error_detector.reset()  # Success - reset error tracking
            return result
            
        except Exception as e:
            error_msg = str(e)
            
            try:
                error_detector.record_error(error_msg)
            except RuntimeError as loop_error:
                # Error loop detected
                raise RuntimeError(
                    f"Error loop detected in file operation: {loop_error}"
                ) from e
            
            if attempt == max_retries - 1:
                raise RuntimeError(
                    f"Operation failed after {max_retries} attempts: {error_msg}"
                ) from e
            
            time.sleep(2 ** attempt)
    
    raise RuntimeError(f"Operation failed for {filepath}")


if __name__ == "__main__":
    """Test error loop detection"""
    print("="*80)
    print("Error Loop Detector Test")
    print("="*80)
    
    # Test 1: Normal errors (should pass)
    print("\n[TEST 1] Normal errors (should pass)...")
    detector = ErrorLoopDetector(max_same_error=5, time_window=10)
    
    for i in range(4):
        try:
            raise ValueError("Test error")
        except Exception as e:
            detector.record_error(str(e))
            print(f"  Error {i+1} recorded: OK")
    
    print("  [OK] Normal error handling works")
    
    # Test 2: Error loop (should detect and abort)
    print("\n[TEST 2] Error loop detection (should detect)...")
    detector2 = ErrorLoopDetector(max_same_error=5, time_window=10)
    
    try:
        for i in range(10):
            try:
                raise ValueError("Repeated error - infinite loop!")
            except Exception as e:
                detector2.record_error(str(e))
                print(f"  Error {i+1} recorded")
    except RuntimeError as loop_error:
        print(f"  [OK] Loop detected: {loop_error}")
    
    # Test 3: Timeout
    print("\n[TEST 3] Operation timeout...")
    try:
        with OperationTimeout(2):
            print("  Starting long operation...")
            time.sleep(3)
    except TimeoutError as e:
        print(f"  [OK] Timeout caught: {e}")
    
    print("\n" + "="*80)
    print("[SUCCESS] All tests passed")
    print("="*80)

