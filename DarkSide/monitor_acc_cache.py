#!/usr/bin/env python3
"""
ACC Cache Monitor

Monitors the ACC_PROJECTS_CACHED_SUMMARY file to ensure it's being updated.
Shows file status, age, size, and can trigger updates if needed.

Usage:
    python monitor_acc_cache.py
    python monitor_acc_cache.py --update  # Force update
    python monitor_acc_cache.py --watch   # Continuous monitoring
"""

import os
import sys
import time
import json
import datetime
import argparse
from pathlib import Path

# ACC cache file path. #2360: the L: drive is being retired -- resolve the
# shared root at runtime instead of hardcoding a drive letter.
def _resolve_acc_cache_dir():
    """ACC cache lives in local Dump; L: is retired."""
    shared_root = (os.environ.get("EA_SHARED_ROOT") or "").strip()
    if shared_root and shared_root.upper() != "OFFLINE" and not shared_root.upper().startswith("L:"):
        return os.path.join(shared_root, "05_EnneadTab-DB", "Shared Data Dump", "ACC_PROJECTS_CACHED_SUMMARY")
    eco = os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "EnneadTab Ecosystem")
    return os.path.join(eco, "Dump", "ACC_PROJECTS_CACHED_SUMMARY")


ACC_CACHE_PATH = _resolve_acc_cache_dir()

def format_size(size_bytes):
    """Format file size in human readable format."""
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {size_names[i]}"

def format_age(seconds):
    """Format age in human readable format."""
    if seconds < 60:
        return f"{int(seconds)} seconds"
    elif seconds < 3600:
        return f"{int(seconds/60)} minutes"
    elif seconds < 86400:
        return f"{int(seconds/3600)} hours"
    else:
        return f"{int(seconds/86400)} days"

def get_file_status():
    """Get detailed status of the ACC cache file."""
    print("🔍 ACC Cache Monitor")
    print("=" * 50)
    
    if not os.path.exists(ACC_CACHE_PATH):
        print(f"❌ File not found: {ACC_CACHE_PATH}")
        return False
    
    # Get file stats
    stat = os.stat(ACC_CACHE_PATH)
    size = stat.st_size
    mtime = stat.st_mtime
    current_time = time.time()
    age_seconds = current_time - mtime
    
    # Format timestamps
    mtime_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    current_str = datetime.datetime.fromtimestamp(current_time).strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"📁 File: {os.path.basename(ACC_CACHE_PATH)}")
    print(f"📂 Path: {ACC_CACHE_PATH}")
    print(f"📊 Size: {format_size(size)}")
    print(f"🕒 Last Modified: {mtime_str}")
    print(f"⏰ Current Time: {current_str}")
    print(f"⏳ Age: {format_age(age_seconds)}")
    
    # Determine status
    if age_seconds < 3600:  # Less than 1 hour
        status = "🟢 FRESH"
        status_color = "green"
    elif age_seconds < 86400:  # Less than 1 day
        status = "🟡 RECENT"
        status_color = "yellow"
    else:  # More than 1 day
        status = "🔴 STALE"
        status_color = "red"
    
    print(f"📈 Status: {status}")
    
    # Check if file is readable and contains valid JSON
    try:
        with open(ACC_CACHE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, dict):
            project_count = len(data)
            print(f"📋 Projects: {project_count}")
            
            # Show sample project names
            if project_count > 0:
                sample_projects = list(data.keys())[:3]
                print(f"📝 Sample Projects: {', '.join(sample_projects)}")
                if project_count > 3:
                    print(f"   ... and {project_count - 3} more")
        else:
            print("⚠️  File contains non-dictionary data")
            
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        return False
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return False
    
    return True

def force_update():
    """Force update the ACC cache by running the update script."""
    print("\n🔄 Forcing ACC cache update...")
    print("=" * 50)
    
    try:
        # Import and run the ACC update
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from Apps.lib.EnneadTab.REVIT import REVIT_ACC
        
        print("📊 Calling get_ACC_summary_data(show_progress=True)...")
        result = REVIT_ACC.get_ACC_summary_data(show_progress=True)
        
        if result:
            print("✅ ACC cache updated successfully!")
            print(f"📈 Found {len(result)} projects")
            return True
        else:
            print("⚠️  ACC cache update returned no data")
            return False
            
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're running this from the project root directory")
        return False
    except Exception as e:
        print(f"❌ Error updating ACC cache: {e}")
        import traceback
        print("Full traceback:")
        traceback.print_exc()
        return False

def watch_mode():
    """Continuous monitoring mode."""
    print("\n👀 Starting continuous monitoring...")
    print("Press Ctrl+C to stop")
    print("=" * 50)
    
    try:
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')  # Clear screen
            print(f"🕒 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print()
            
            get_file_status()
            
            print(f"\n⏳ Refreshing in 30 seconds... (Ctrl+C to stop)")
            time.sleep(30)
            
    except KeyboardInterrupt:
        print("\n\n👋 Monitoring stopped by user")

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Monitor ACC cache file")
    parser.add_argument("--update", action="store_true", help="Force update the cache")
    parser.add_argument("--watch", action="store_true", help="Continuous monitoring mode")
    
    args = parser.parse_args()
    
    if args.update:
        # Force update mode
        if force_update():
            print("\n" + "=" * 50)
            print("📊 Updated file status:")
            get_file_status()
    elif args.watch:
        # Watch mode
        watch_mode()
    else:
        # Single check mode
        get_file_status()
        
        # Suggest actions based on file age
        if os.path.exists(ACC_CACHE_PATH):
            stat = os.stat(ACC_CACHE_PATH)
            age_seconds = time.time() - stat.st_mtime
            
            if age_seconds > 86400:  # More than 1 day
                print(f"\n💡 Suggestion: File is {format_age(age_seconds)} old")
                print("   Run with --update to force refresh")
            elif age_seconds > 3600:  # More than 1 hour
                print(f"\n💡 Suggestion: File is {format_age(age_seconds)} old")
                print("   Consider running with --update if you need fresh data")

if __name__ == "__main__":
    main()
