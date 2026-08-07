"""used to retrive sample file in rhino, reivt and excel.
Good the sharing template"""

import os
import ENVIRONMENT
import NOTIFICATION
import FOLDER

def get_file(file_name):
    """Get the full path of a sample file.
    
    Args:
        file_name (str): Name of the file to locate
        
    Returns:
        str: Full path to the file if found, None otherwise
    """
    path = os.path.join(ENVIRONMENT.DOCUMENT_FOLDER, ENVIRONMENT.get_app_name(), file_name)

    if ENVIRONMENT.get_app_name() == "revit":
        if file_name.endswith(".rfa") or file_name.endswith(".rvt"):
            try:
                from EnneadTab.REVIT import REVIT_APPLICATION
                revit_version = REVIT_APPLICATION.get_revit_version()
                path = os.path.join(ENVIRONMENT.DOCUMENT_FOLDER, 
                                    ENVIRONMENT.get_app_name(), 
                                    str(revit_version), 
                                    file_name)
            except Exception as e:
                print("Warning: Could not get Revit version, using default path: {}".format(e))
                # Fallback to default path if version detection fails
                
    
    if os.path.exists(path):
        return path
    
    # Enhanced error reporting
    error_msg = "Cannot find sample file [{}] at path: {}".format(file_name, path)
    NOTIFICATION.messenger(error_msg)
    print(error_msg)
    
    # Additional debugging information
    print("Debug: DOCUMENT_FOLDER = {}".format(ENVIRONMENT.DOCUMENT_FOLDER))
    print("Debug: app_name = {}".format(ENVIRONMENT.get_app_name()))
    if ENVIRONMENT.get_app_name() == "revit":
        try:
            from EnneadTab.REVIT import REVIT_APPLICATION
            print("Debug: Revit version = {}".format(REVIT_APPLICATION.get_revit_version()))
        except:
            print("Debug: Could not get Revit version")
    
    # Try fallback to base folder (without version) for Revit
    if ENVIRONMENT.get_app_name() == "revit":
        fallback_path = os.path.join(ENVIRONMENT.DOCUMENT_FOLDER, 
                                    ENVIRONMENT.get_app_name(), 
                                    file_name)
        if os.path.exists(fallback_path):
            print("Debug: Found file in fallback location: {}".format(fallback_path))
            return fallback_path
    
    return None



def family_as_template(file_path):
    
    folder = os.path.dirname(file_path)
    file_name = os.path.basename(file_path)
    new_file_name = file_name.replace(".rfa", ".rft")
    new_file_path = os.path.join(folder, new_file_name)
    FOLDER.copy_file_to_local_dump_folder(file_path, new_file_path)
    return new_file_path


    

if __name__ == "__main__":
    print (get_file("LifeSafetyCalculator.rfa"))