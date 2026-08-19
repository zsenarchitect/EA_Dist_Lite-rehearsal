import os
import shutil
import datetime

def cleanup_revit_cache():
    base_path = "{}\\AppData\\Local\\Autodesk\\Revit".format(os.environ["USERPROFILE"])
    today = datetime.datetime.today()
    start_year = 2010
    end_year = 2030

    for year in range(start_year, end_year + 1):
        folder_path = os.path.join(base_path, f"Autodesk Revit {year}")
        
        if not os.path.exists(folder_path):
            continue
        
        for root, dirs, files in os.walk(folder_path):
            for dir_name in dirs:
                if "CentralCache" in dir_name:
                    local_cache_path = root
                    
                    for file_name in os.listdir(local_cache_path):
                        if file_name.endswith('.rvt'):
                            file_path = os.path.join(local_cache_path, file_name)
                            modification_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
                            if (today - modification_time).days > 30:
                                shutil.rmtree(local_cache_path)
                                print(f"Deleted {local_cache_path} becasue it is older than 30days")
                                break  # Exit loop since we've deleted the folder

    # Cleanup empty folders in CollaborationCache
    for root, dirs, files in os.walk(base_path, topdown=False):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            if not os.listdir(dir_path):
                os.rmdir(dir_path)
                print(f"Removed empty folder {dir_path}")


def cleanup_rhino_cache():
    base_path = "{}\\AppData\\Local\\McNeel\\Rhinoceros".format(os.environ["USERPROFILE"])
    today = datetime.datetime.today()
    start_version = 5
    end_version = 10

    for version in range(start_version, end_version + 1):
        folder_path = os.path.join(base_path, "{}.0".format(version))

        if not os.path.exists(folder_path):
            continue
        
        for root, dirs, files in os.walk(folder_path):
            for file_name in files:
                if file_name.endswith('.3dm'):
                    file_path = os.path.join(root, file_name)
                    modification_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
                    if (today - modification_time).days > 30:
                        os.remove(file_path)
                        print(f"Deleted {file_path} becasue it is older than 30 days")

    # Cleanup empty folders
    for root, dirs, files in os.walk(base_path, topdown=False):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            if not os.listdir(dir_path):
                os.rmdir(dir_path)
                print(f"Removed empty folder {dir_path}")


def main():
    cleanup_revit_cache()
    cleanup_rhino_cache()
    
if __name__ == "__main__":
    main()