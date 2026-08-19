import os
import io
import traceback
import time
import json
import shutil
import socket
from datetime import datetime


USER_NAME = os.environ["USERPROFILE"].split("\\")[-1]
IS_DEVELOPER = USER_NAME == "szhang"
COMPUTER_NAME = socket.gethostname()

PLUGIN_NAME = "EnneadTab"
PLUGIN_EXTENSION = ".sexyDuck"


WINDOW_TEMP_FOLDER = os.path.join("C:\\", "temp", "{}_Dump".format(PLUGIN_NAME))

GLOBAL_SETTING_FILE = 'setting_{}'.format(os.environ["USERPROFILE"].split("\\")[-1])


ECO_SYS_FOLDER = "{}\\Documents\\{} Ecosystem".format(os.environ["USERPROFILE"], PLUGIN_NAME)

DUMP_FOLDER = "{}\\Dump".format(ECO_SYS_FOLDER)
DIST_FOLDER = os.path.join(ECO_SYS_FOLDER, "EA_Dist")
CORE_LIB_FOLDER = os.path.join(DIST_FOLDER, "Apps","lib")
EXE_PRODUCT_FOLDER = os.path.join(CORE_LIB_FOLDER, "ExeProducts")
for _folder in [ECO_SYS_FOLDER, DUMP_FOLDER, WINDOW_TEMP_FOLDER]:
    if not os.path.exists(_folder):
        os.makedirs(_folder)


import sys
sys.path.append(os.path.join(CORE_LIB_FOLDER, "EnneadTab"))


def _fallback_resolve_shared_root():
    """Standalone twin of ENVIRONMENT._resolve_shared_root (#2360).

    The compiled EXEs must resolve the shared root the SAME way as the library,
    including when EnneadTab is not importable (a broken EA_Dist is exactly when
    these EXEs -- the installer, the repo assistant -- have to still work).
    Duplicating the precedence chain here is deliberate: this file cannot depend
    on the library it is meant to repair.

    Precedence: EA_SHARED_ROOT env var > per-user shared_root.json >
    EA_Dist shared_root.json > legacy L: path.

    Returns:
        str: The shared network root.
    """
    env_value = os.environ.get("EA_SHARED_ROOT")
    if env_value:
        env_value = env_value.strip()
    if env_value and env_value.upper() != "OFFLINE":
        return env_value

    candidates = [
        os.path.join(ECO_SYS_FOLDER, "shared_root.json"),
        os.path.join(CORE_LIB_FOLDER, "EnneadTab", "shared_root.json"),
    ]
    for config_path in candidates:
        if not os.path.exists(config_path):
            continue
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("shared_root"):
                return data["shared_root"]
        except Exception:
            continue

    return os.path.join("L:\\", "4b_Design Technology")


try:
    from ENVIRONMENT import DB_FOLDER, L_DRIVE_HOST_FOLDER, SHARED_DUMP_FOLDER
except Exception:
    L_DRIVE_HOST_FOLDER = _fallback_resolve_shared_root()
    DB_FOLDER = os.path.join(L_DRIVE_HOST_FOLDER, "05_EnneadTab-DB")
    SHARED_DUMP_FOLDER = os.path.join(DB_FOLDER, "Shared Data Dump")







def is_avd():
    computer_name = socket.gethostname()
    return "avd" in computer_name.lower() or "gpupd" in computer_name.lower()


     
def find_main_repo():
    for root, dirs, files in os.walk(os.environ['USERPROFILE']):
        if 'EnneadTab-OS' in dirs:
            return os.path.join(root, 'EnneadTab-OS')
    return os.path.join(ECO_SYS_FOLDER, 'EA_Dist')

def try_catch_error(func):
    """Decorator for catching exceptions and logging errors.
    
    Args:
        func: The function to wrap with error handling
        
    Returns:
        The wrapped function that includes error handling
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except PermissionError:
            error_msg = "[WinError 32] The process cannot access the file because it is being used by another process"
            print(error_msg)
            return None
        except EOFError:
            print("fine.....")
            return None
        except Exception as e:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            error = f"[{timestamp}] Error in {func.__name__}:\n{traceback.format_exc()}"
            print(error)

            error += "\n\n######If you have any UI window open, just close the window. Do no more action, otherwise the program might crash.##########\n#########Not sure what to do? Msg Sen Zhang, you have dicovered a important bug and we need to fix it ASAP!!!!!########"
            error_file = get_file_in_dump_folder("error_log_{}.txt".format(func.__name__))

            try:
                with open(error_file, "w", encoding='utf-8') as f:
                    f.write(error)
            except Exception as write_error:
                print(f"Failed to write error log: {write_error}")

            username = os.environ["USERPROFILE"].split("\\")[-1]
            if username in ["szhang"]:
                try:
                    os.startfile(error_file)
                except Exception as start_error:
                    print(f"Failed to open error file: {start_error}")
            return None

    return wrapper


def get_file_in_dump_folder(file_name, is_local=True):
    base_folder = DUMP_FOLDER if is_local else SHARED_DUMP_FOLDER
    file_path = os.path.join(base_folder, file_name)
    if os.path.exists(file_path):
        return file_path
    if PLUGIN_EXTENSION in file_name or ".txt" in file_name or ".log" in file_name:
        return file_path

    return os.path.join(base_folder, file_name + PLUGIN_EXTENSION)

def get_data(file_name, is_local=True):
    """Get data from a JSON file.
    
    Args:
        file_name (str): Name of the file to read
        is_local (bool): Whether to use local or shared dump folder
        
    Returns:
        dict: The data from the file, or empty dict if file doesn't exist
    """
    if not os.path.exists(file_name):
        filepath = get_file_in_dump_folder(file_name, is_local)
    else:
        filepath = file_name

    if not os.path.exists(filepath):
        return {}

    try:
        with open(filepath, "r", encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"Error reading data file: {e}")
        return {}

def set_data(data, file_name, is_local=True):
    """Write data to a JSON file.
    
    Args:
        data (dict): Data to write to file
        file_name (str): Name of the file to write
        is_local (bool): Whether to use local or shared dump folder
    """
    filepath = get_file_in_dump_folder(file_name, is_local)
    temp_file = get_file_in_dump_folder("_temp_exe_data_" + os.path.basename(file_name))
    
    try:
        # Write to temp file first
        with open(temp_file, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        
        # Move temp file to final location
        shutil.move(temp_file, filepath)
    except Exception as e:
        print(f"Error writing data file: {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass

def get_openai_api_key(app_name):
    """Returns the API key for the specified app.
    Accepted keys:
    "EnneadTabAPI"

    Args:
        app_name (string): The name of the app to get the API key for.

    Returns:
        string: The API key for the specified app.
    """
    api_key_file = "EA_API_KEY.secret"
    L_drive_file_path = os.path.join(DB_FOLDER, api_key_file)
    
    data = get_data(L_drive_file_path)

    # Try to get value from specified app_name first, fallback to any key if not found
    for key in data:
        if key == app_name:
            return data[key]
    return next(iter(data.values()), None)

def list_api_keys():
    """open secret file and return a list of all API keys.
    Returns:
        list: A list of all API keys.
    """
    L_drive_file_path = os.path.join(DB_FOLDER, "EA_API_KEY.secret")
    data = get_data(L_drive_file_path)
    return list(data.keys())

def show_splash_screen(image):
    """create the data bit file and call SpalshScreen.exe"""
    dict = {"image":image}
    set_data(dict, "splash_data")
    exe = "{}\\EA_Dist\\Apps\\lib\\ExeProducts\\SplashScreen.exe"
    if os.path.exists(exe):
        os.startfile(exe)

def hide_splash_screen():
    """delete the data bit file"""
    data_file = get_file_in_dump_folder("splash_data")
    if os.path.exists(data_file):
        os.remove(data_file)



def get_setting(key, default_value=None):
    data = get_data(GLOBAL_SETTING_FILE)
    return data.get(key, default_value)


def get_username():
    return os.environ["USERPROFILE"].split("\\")[-1]




def get_list(filepath):
    extention = os.path.split(filepath)[1]
    local_path = get_file_in_dump_folder("exe_temp{}".format(extention))
    shutil.copyfile(filepath, local_path)


    with io.open(local_path, "r",encoding="utf8") as f:
        lines = f.readlines()
  
    return map(lambda x: x.replace("\n", ""), lines)


def try_open_app(app_name):
    
    exe_product_folder = os.path.join(CORE_LIB_FOLDER, "ExeProducts")


    app_name = app_name.replace(".exe", "")
    app_address = app_name + ".exe"
    if exe_product_folder not in app_address:
        app_address = os.path.join(exe_product_folder, app_address)

    if not os.path.exists(app_address):
        print ("App not found: {}".format(app_address))
        return
    
    temp_exe_name = "_temp_exe_{}_{}.exe".format(app_name, int(time.time()))
    temp_exe = DUMP_FOLDER + "\\" + temp_exe_name
    shutil.copyfile(app_address, temp_exe)
    os.startfile(temp_exe)
    for file in os.listdir(DUMP_FOLDER):
        if file.startswith("_temp_exe_"):
            # ignore if this temp file is less than 1 day old
            if time.time() - os.path.getmtime(os.path.join(DUMP_FOLDER, file)) < 86400:
                continue
            try:
                os.remove(os.path.join(DUMP_FOLDER, file))
            except:
                pass

def messenger(note):
    data = {}
    data["main_text"] = note
    data["animation_in_duration"] = 0.5
    data["animation_stay_duration"] = 5
    data["animation_fade_duration"] = 2
    data["width"] = 1200
    data["height"] =  150 + str(note).count("\n") * 40

    data["x_offset"] = 0

    set_data(data, "messenger_data")

    try_open_app("Messenger")

if __name__ == "__main__":
    messenger("Hello, world!")

    print (get_openai_api_key("EnneadTabAPI"))

    print (SHARED_DUMP_FOLDER)
