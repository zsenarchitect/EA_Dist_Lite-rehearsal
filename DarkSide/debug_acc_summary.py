#!/usr/bin/env python3
"""
Debug script to understand why ACC summary is not working
"""
import sys
import os
import traceback

# Add the 'Apps/lib' directory to sys.path
script_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
sys.path.insert(0, os.path.join(project_root, 'Apps', 'lib'))

def debug_acc_summary():
    """Debug the ACC summary process"""
    try:
        print("🔍 Starting ACC summary debug...")
        
        from EnneadTab.REVIT import REVIT_ACC
        print("✅ REVIT_ACC module imported successfully")
        
        # Check if we can access the cache files
        from EnneadTab import FOLDER
        shared_dump_path = FOLDER.get_shared_dump_folder_file("ACC_PROJECTS_CACHED_SUMMARY")
        print("📁 Shared dump path: {}".format(shared_dump_path))
        print("📁 Path exists: {}".format(os.path.exists(shared_dump_path)))
        
        # Try to get basic project data first
        print("📡 Trying to get basic ACC project data...")
        try:
            basic_data = REVIT_ACC.get_acc_projects_data(use_record=True)
            print("✅ Basic project data retrieved: {} hubs".format(len(basic_data) if basic_data else 0))
        except Exception as e:
            print("❌ Error getting basic project data: {}".format(str(e)))
            print(traceback.format_exc())
            return False
        
        # Try to get summary data
        print("📊 Trying to get ACC summary data...")
        try:
            summary_data = REVIT_ACC.get_ACC_summary_data(show_progress=True)
            print("✅ Summary data result: {}".format(bool(summary_data)))
            return bool(summary_data)
        except Exception as e:
            print("❌ Error getting summary data: {}".format(str(e)))
            print(traceback.format_exc())
            return False
            
    except Exception as e:
        print("❌ Critical error in debug: {}".format(str(e)))
        print(traceback.format_exc())
        return False

if __name__ == "__main__":
    success = debug_acc_summary()
    print("\n🎯 Debug result: {}".format("SUCCESS" if success else "FAILED"))
