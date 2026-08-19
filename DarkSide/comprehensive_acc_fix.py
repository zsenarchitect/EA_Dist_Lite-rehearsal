#!/usr/bin/env python3
"""
Comprehensive ACC summary fix and test
"""
import sys
import os
import traceback
import time

# Add the 'Apps/lib' directory to sys.path
script_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
sys.path.insert(0, os.path.join(project_root, 'Apps', 'lib'))

def comprehensive_acc_test():
    """Comprehensive test of ACC summary functionality"""
    try:
        print("🔍 Starting comprehensive ACC summary test...")
        
        # Test 1: Import modules
        print("\n1️⃣ Testing imports...")
        from EnneadTab.REVIT import REVIT_ACC
        from EnneadTab import FOLDER, DATA_FILE
        print("✅ All modules imported successfully")
        
        # Test 2: Check file paths
        print("\n2️⃣ Testing file paths...")
        summary_path = FOLDER.get_shared_dump_folder_file("ACC_PROJECTS_CACHED_SUMMARY")
        print("📁 Summary path: {}".format(summary_path))
        print("📁 Path exists: {}".format(os.path.exists(summary_path)))
        
        # Test 3: Check if we can save a simple test file
        print("\n3️⃣ Testing file save capability...")
        test_data = {"test": "data", "timestamp": time.time()}
        save_result = DATA_FILE.set_data(test_data, "TEST_ACC_SAVE", is_local=False)
        print("💾 Save result: {}".format(save_result))
        
        if save_result:
            test_path = FOLDER.get_shared_dump_folder_file("TEST_ACC_SAVE")
            print("📁 Test file exists: {}".format(os.path.exists(test_path)))
            if os.path.exists(test_path):
                print("✅ File save capability working")
            else:
                print("❌ File save capability not working")
                return False
        else:
            print("❌ File save failed")
            return False
        
        # Test 4: Try to get basic project data
        print("\n4️⃣ Testing basic project data retrieval...")
        try:
            basic_data = REVIT_ACC.get_acc_projects_data(use_record=True)
            print("✅ Basic project data: {} hubs".format(len(basic_data) if basic_data else 0))
        except Exception as e:
            print("❌ Basic project data failed: {}".format(str(e)))
            print(traceback.format_exc())
            return False
        
        # Test 5: Try to get summary data with detailed error handling
        print("\n5️⃣ Testing ACC summary data retrieval...")
        try:
            print("📊 Starting ACC summary...")
            summary_data = REVIT_ACC.get_ACC_summary_data(show_progress=True)
            print("📊 ACC summary completed")
            print("📊 Summary data result: {}".format(bool(summary_data)))
            
            if summary_data:
                print("✅ ACC summary successful")
                return True
            else:
                print("❌ ACC summary returned False")
                return False
                
        except Exception as e:
            print("❌ ACC summary failed with error: {}".format(str(e)))
            print(traceback.format_exc())
            return False
            
    except Exception as e:
        print("❌ Critical error: {}".format(str(e)))
        print(traceback.format_exc())
        return False

if __name__ == "__main__":
    print("🚀 Starting comprehensive ACC summary test...")
    success = comprehensive_acc_test()
    print("\n🎯 Final result: {}".format("SUCCESS" if success else "FAILED"))
    
    if success:
        print("✅ ACC summary is working correctly!")
    else:
        print("❌ ACC summary needs more debugging")
