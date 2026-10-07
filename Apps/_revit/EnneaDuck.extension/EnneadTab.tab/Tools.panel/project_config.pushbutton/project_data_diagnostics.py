# -*- coding: utf-8 -*-
"""
Project Data Diagnostics Tool

This tool helps diagnose and troubleshoot issues with EnneadTab project data setup.
It provides comprehensive information about the current state of project data,
network connectivity, and file system access.
"""

from EnneadTab import NOTIFICATION, ENVIRONMENT, FOLDER
from EnneadTab.REVIT import REVIT_PROJ_DATA, REVIT_PARAMETER
from Autodesk.Revit import DB # pyright: ignore
import os
import sys

def run_project_data_diagnostics(doc):
    """Run comprehensive diagnostics on project data setup.
    
    Args:
        doc: Current Revit document
    """
    print("=" * 60)
    print("ENNEADTAB PROJECT DATA DIAGNOSTICS")
    print("=" * 60)
    print("Document: {}".format(doc.Title))
    print("Document Path: {}".format(doc.PathName))
    print("=" * 60)
    
    # Test 1: Environment Check
    print("\n1. ENVIRONMENT CHECK")
    print("-" * 30)
    _check_environment()
    
    # Test 2: Network Drive Check
    print("\n2. NETWORK DRIVE CHECK")
    print("-" * 30)
    _check_network_drives()
    
    # Test 3: Project Data Parameter Check
    print("\n3. PROJECT DATA PARAMETER CHECK")
    print("-" * 30)
    _check_project_data_parameter(doc)
    
    # Test 4: Project Data File Check
    print("\n4. PROJECT DATA FILE CHECK")
    print("-" * 30)
    _check_project_data_file(doc)
    
    # Test 5: Data Retrieval Test
    print("\n5. DATA RETRIEVAL TEST")
    print("-" * 30)
    _test_data_retrieval(doc)
    
    # Test 6: File System Permissions
    print("\n6. FILE SYSTEM PERMISSIONS")
    print("-" * 30)
    _check_file_permissions()
    
    # Summary
    print("\n" + "=" * 60)
    print("DIAGNOSTICS SUMMARY")
    print("=" * 60)
    _print_summary()


def _check_environment():
    """Check basic environment setup."""
    try:
        print("✓ Python Version: {}".format(sys.version))
        print("✓ Platform: {}".format(sys.platform))
        print("✓ Plugin Name: {}".format(ENVIRONMENT.PLUGIN_NAME))
        print("✓ Plugin Extension: {}".format(ENVIRONMENT.PLUGIN_EXTENSION))
        print("✓ Root Folder: {}".format(ENVIRONMENT.ROOT))
        print("✓ App Folder: {}".format(ENVIRONMENT.APP_FOLDER))
        print("✓ Lib Folder: {}".format(ENVIRONMENT.LIB_FOLDER))
        print("✓ Core Folder: {}".format(ENVIRONMENT.CORE_FOLDER))
        print("✓ Document Folder: {}".format(ENVIRONMENT.DOCUMENT_FOLDER))
        print("✓ Dump Folder: {}".format(ENVIRONMENT.DUMP_FOLDER))
        print("✓ Shared Dump Folder (in use): {}".format(ENVIRONMENT.SHARED_DUMP_FOLDER))
        print("✓ Shared Dump Folder (expected): {}".format(ENVIRONMENT.SHARED_DUMP_FOLDER_EXPECTED))
        print("✓ Shared Root: {}".format(ENVIRONMENT.SHARED_ROOT))
        print("✓ Shared Root resolved from: {}".format(ENVIRONMENT.SHARED_ROOT_SOURCE))
        print("✓ DB Folder: {}".format(ENVIRONMENT.DB_FOLDER))
        if ENVIRONMENT.IS_SHARED_DATA_LOST:
            print("❌ SHARED DATA IS NOT BEING SHARED - the shared root is unreachable.")
            print(ENVIRONMENT.get_shared_root_alarm_message())
        elif ENVIRONMENT.IS_DELIBERATELY_OFFLINE:
            print("✓ Deliberate offline mode - local-only operation is expected.")
    except Exception as e:
        print("❌ Environment check failed: {}".format(str(e)))


def _check_network_drives():
    """Check network drive connectivity."""
    try:
        # Check the resolved shared root (formerly hardcoded as "L:\"). #2360:
        # the drive letter is no longer an assumption -- probe whatever the
        # precedence chain actually resolved to.
        shared_root = ENVIRONMENT.SHARED_ROOT
        if os.path.exists(shared_root):
            print("✓ Shared Root is accessible: {}".format(shared_root))
            try:
                # Test write access
                test_file = os.path.join(shared_root, "test_write_access.tmp")
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
                print("✓ Shared Root has write access")
            except Exception as e:
                print("❌ Shared Root write access failed: {}".format(str(e)))
        else:
            print("❌ Shared Root is not accessible: {}".format(shared_root))

        # Check shared dump folder
        if os.path.exists(ENVIRONMENT.SHARED_DUMP_FOLDER):
            print("✓ Shared Dump Folder exists: {}".format(ENVIRONMENT.SHARED_DUMP_FOLDER))
        else:
            print("❌ Shared Dump Folder does not exist: {}".format(ENVIRONMENT.SHARED_DUMP_FOLDER))
            
        # Check DB folder
        if os.path.exists(ENVIRONMENT.DB_FOLDER):
            print("✓ DB Folder exists: {}".format(ENVIRONMENT.DB_FOLDER))
        else:
            print("❌ DB Folder does not exist: {}".format(ENVIRONMENT.DB_FOLDER))
            
    except Exception as e:
        print("❌ Network drive check failed: {}".format(str(e)))


def _check_project_data_parameter(doc):
    """Check if project data parameter exists."""
    try:
        if REVIT_PROJ_DATA.is_setup_project_data_para_exist(doc):
            print("✓ Project data parameter exists")
            
            # Get parameter value
            try:
                para = REVIT_PARAMETER.get_project_info_para_by_name(doc, REVIT_PROJ_DATA.PROJECT_DATA_PARA_NAME)
                if para:
                    value = para.AsString()
                    print("✓ Parameter value: {}".format(value))
                else:
                    print("❌ Could not get parameter value")
            except Exception as e:
                print("❌ Error getting parameter value: {}".format(str(e)))
        else:
            print("❌ Project data parameter does not exist")
            print("  - This means the project has not been initialized with EnneadTab")
            
    except Exception as e:
        print("❌ Project data parameter check failed: {}".format(str(e)))


def _check_project_data_file(doc):
    """Check project data file status."""
    try:
        # Get project data file name
        project_data_file = REVIT_PROJ_DATA.get_project_data_file(doc)
        print("✓ Project data file name: {}".format(project_data_file))
        
        # Check if file exists in shared dump folder
        shared_dump_path = FOLDER.get_shared_dump_folder_file(project_data_file)
        print("✓ Full path: {}".format(shared_dump_path))
        
        if os.path.exists(shared_dump_path):
            print("✓ Project data file exists")
            
            # Check file size
            file_size = os.path.getsize(shared_dump_path)
            print("✓ File size: {} bytes".format(file_size))
            
            # Check file permissions
            if os.access(shared_dump_path, os.R_OK):
                print("✓ File is readable")
            else:
                print("❌ File is not readable")
                
            if os.access(shared_dump_path, os.W_OK):
                print("✓ File is writable")
            else:
                print("❌ File is not writable")
        else:
            print("❌ Project data file does not exist")
            print("  - This may indicate the project has not been properly initialized")
            
    except Exception as e:
        print("❌ Project data file check failed: {}".format(str(e)))


def _test_data_retrieval(doc):
    """Test project data retrieval."""
    try:
        print("Testing project data retrieval...")
        
        # Test basic retrieval
        project_data = REVIT_PROJ_DATA.get_revit_project_data(doc)
        
        if project_data:
            print("✓ Project data retrieved successfully")
            print("✓ Data type: {}".format(type(project_data)))
            print("✓ Data keys: {}".format(list(project_data.keys()) if isinstance(project_data, dict) else "Not a dict"))
            
            # Check for required sections
            if isinstance(project_data, dict):
                required_sections = ["area_tracking", "parking_data", "keynote_assistant"]
                for section in required_sections:
                    if section in project_data:
                        print("✓ {} section exists".format(section))
                    else:
                        print("❌ {} section missing".format(section))
        else:
            print("❌ Project data retrieval failed - returned None or empty")
            
    except Exception as e:
        print("❌ Data retrieval test failed: {}".format(str(e)))


def _check_file_permissions():
    """Check file system permissions."""
    try:
        # Test local dump folder
        if os.path.exists(ENVIRONMENT.DUMP_FOLDER):
            print("✓ Local dump folder exists: {}".format(ENVIRONMENT.DUMP_FOLDER))
            
            if os.access(ENVIRONMENT.DUMP_FOLDER, os.W_OK):
                print("✓ Local dump folder is writable")
            else:
                print("❌ Local dump folder is not writable")
        else:
            print("❌ Local dump folder does not exist: {}".format(ENVIRONMENT.DUMP_FOLDER))
            
        # Test shared dump folder
        if os.path.exists(ENVIRONMENT.SHARED_DUMP_FOLDER):
            print("✓ Shared dump folder exists: {}".format(ENVIRONMENT.SHARED_DUMP_FOLDER))
            
            if os.access(ENVIRONMENT.SHARED_DUMP_FOLDER, os.W_OK):
                print("✓ Shared dump folder is writable")
            else:
                print("❌ Shared dump folder is not writable")
        else:
            print("❌ Shared dump folder does not exist: {}".format(ENVIRONMENT.SHARED_DUMP_FOLDER))
            
    except Exception as e:
        print("❌ File permissions check failed: {}".format(str(e)))


def _print_summary():
    """Print diagnostic summary and recommendations."""
    print("\nRECOMMENDATIONS:")
    print("-" * 30)
    
    print("1. If shared network folder is not accessible:")
    print("   - Contact IT to ensure the office shared drive is properly mapped")
    print("   - Check network connectivity")
    print("   - Verify VPN connection if working remotely")
    
    print("\n2. If Project Data Parameter does not exist:")
    print("   - Run the Healthcare Project Setup tool first")
    print("   - This will create the necessary parameter and initialize project data")
    
    print("\n3. If Project Data File does not exist:")
    print("   - The project may not have been properly initialized")
    print("   - Run the Healthcare Project Setup tool to create the data file")
    
    print("\n4. If File Permissions are insufficient:")
    print("   - Contact IT to ensure proper access to shared folders")
    print("   - Check if user account has necessary permissions")
    
    print("\n5. If Data Retrieval fails:")
    print("   - Check the console output for specific error messages")
    print("   - Verify that the project data file is not corrupted")
    print("   - Try reinitializing the project data")
    
    print("\nFor additional help, contact the EnneadTab development team.")


if __name__ == "__main__":
    # This would be called from the Revit environment
    pass
