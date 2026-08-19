"""
EnneadTab Data File Management Module

A comprehensive data persistence system for EnneadTab that provides robust JSON file handling
and sticky data management. This module handles reading, writing, and managing data across
local and shared storage locations.

Key Features:
    - Safe JSON file operations with encoding support
    - Local and shared dump folder management
    - List-based file operations
    - Sticky data persistence
    - Context manager for safe data updates
    - Cross-platform compatibility (IronPython/CPython)
    - UTF-8 encoding support for international characters

Note:
    All file operations are designed to be safe and atomic, with proper error handling
    and temporary file management to prevent data corruption.
"""

__mcp_tools__ = [
    {
        "function": "get_data",
        "description": "Retrieve data from a JSON file by name or full path. Returns the file contents as a dictionary.",
        "args": [
            {"name": "file_name_or_full_path", "type": "str", "description": "Filename or full path to the JSON file"},
            {"name": "is_local", "type": "bool", "description": "Use local dump folder (True) or shared (False). Defaults to True."}
        ],
        "returns": "dict with the file contents"
    },
    {
        "function": "set_data",
        "description": "Save a dictionary to a JSON file by name or full path.",
        "args": [
            {"name": "data_dict", "type": "dict", "description": "Dictionary to save"},
            {"name": "file_name_or_full_path", "type": "str", "description": "Filename or full path"},
            {"name": "is_local", "type": "bool", "description": "Use local dump folder (True) or shared (False). Defaults to True."}
        ],
        "returns": "bool True if save successful"
    },
    {
        "function": "get_sticky",
        "description": "Retrieve persistent sticky data by name. Returns the stored value or a default.",
        "args": [
            {"name": "sticky_name", "type": "str", "description": "Identifier for the sticky data"},
            {"name": "default_value_if_no_sticky", "type": "str", "description": "Default value if sticky not found. Defaults to None."}
        ],
        "returns": "the stored sticky value, or the default"
    },
    {
        "function": "set_sticky",
        "description": "Save persistent sticky data that persists across sessions.",
        "args": [
            {"name": "sticky_name", "type": "str", "description": "Identifier for the sticky data"},
            {"name": "value_to_write", "type": "str", "description": "Value to store"}
        ],
        "returns": "bool True if save successful"
    },
    {
        "function": "pretty_print_dict",
        "description": "Return a formatted JSON string of a dictionary for display.",
        "args": [
            {"name": "data_dict", "type": "dict", "description": "Dictionary to format"}
        ],
        "returns": "None (prints to stdout)"
    },
]

import sys

import json
import io
import os
import time
from contextlib import contextmanager

# Import ENVIRONMENT first to avoid circular dependencies
import ENVIRONMENT

import COPY

# Try to import FOLDER, with a better fallback mechanism
FOLDER = None
try:
    # Try to import FOLDER using imp for IronPython 2.7 compatibility
    import imp
    import sys
    
    # Get the path to FOLDER.py
    folder_path = os.path.join(os.path.dirname(__file__), "FOLDER.py")
    
    if os.path.exists(folder_path):
        # Load FOLDER module from file path using imp
        FOLDER = imp.load_source("FOLDER", folder_path)
        
        # Test if the function works
        try:
            test_result = FOLDER.get_local_dump_folder_file("test")
        except:
            FOLDER = None
    else:
        FOLDER = None
        
except Exception as e:
    FOLDER = None

# If FOLDER import failed, create fallback
if FOLDER is None:
    # Provide fallback functions that use ENVIRONMENT directly
    class FOLDER_FALLBACK:
        @staticmethod
        def _add_extension_if_needed(file_name):
            """Add .sexyDuck extension if file doesn't have an extension."""
            _, ext = os.path.splitext(file_name)
            if not ext:
                return file_name + ".sexyDuck"
            return file_name
        
        @staticmethod
        def get_local_dump_folder_file(file_name):
            secured_name = FOLDER_FALLBACK._add_extension_if_needed(file_name)
            return os.path.join(ENVIRONMENT.DUMP_FOLDER, secured_name)
        
        @staticmethod
        def get_shared_dump_folder_file(file_name):
            secured_name = FOLDER_FALLBACK._add_extension_if_needed(file_name)
            return os.path.join(ENVIRONMENT.SHARED_DUMP_FOLDER, secured_name)
    
    FOLDER = FOLDER_FALLBACK()




def _read_json_file_safely(filepath, use_encode=True, create_if_not_exist=False):
    """Safely read a JSON file by creating a temporary copy.
    
    Creates a temporary copy of the JSON file before reading to avoid file locking
    issues and ensure data integrity.

    Args:
        filepath (str): Path to the JSON file
        use_encode (bool, optional): Enable UTF-8 encoding for international characters.
            Defaults to True.
        create_if_not_exist (bool, optional): Create empty file if not found.
            Defaults to False.

    Returns:
        dict: File contents as dictionary, empty dict if file doesn't exist
    """
    if not os.path.exists(filepath):
        return dict()
    local_path = FOLDER.get_local_dump_folder_file("temp_data")
    try:
        COPY.copyfile(filepath, local_path)
    except IOError:
        local_path = FOLDER.get_local_dump_folder_file("temp_data_retry")
        COPY.copyfile(filepath, local_path)

    content = _read_json_as_dict(local_path, use_encode, create_if_not_exist)
    return content


def _read_json_as_dict(filepath, use_encode=True, create_if_not_exist=False):
    """Read JSON file and return contents as dictionary.
    
    Handles both IronPython and CPython environments with proper encoding support.
    Creates new file with empty dictionary if specified and file doesn't exist.

    Args:
        filepath (str): Path to the JSON file
        use_encode (bool, optional): Enable UTF-8 encoding for international characters.
            Defaults to True.
        create_if_not_exist (bool, optional): Create empty file if not found.
            Defaults to False.

    Returns:
        dict: File contents as dictionary, None if read error occurs
    """
    if create_if_not_exist and not os.path.exists(filepath):
        _save_dict_to_json({}, filepath, use_encode)
        return dict()

    try:
        if sys.platform == "cli":  # IronPython
            from System.IO import File, StreamReader
            from System.Text import Encoding
            
            if use_encode:
                # Use .NET's StreamReader with UTF8 encoding
                reader = StreamReader(filepath, Encoding.UTF8)
                content = reader.ReadToEnd()
                reader.Close()
                return json.loads(content)
            else:
                # Use basic file reading for non-encoded files
                content = File.ReadAllText(filepath)
                return json.loads(content)
        else:  # CPython
            if use_encode:
                with io.open(filepath, "r",encoding="utf-8") as f:
                    return json.load(f)
            else:
                with open(filepath, "r") as f:
                    return json.load(f)
    except Exception as e:
        print("Error reading JSON file {}: {}".format(filepath, str(e)))
        return None


def _read_json_as_dict_in_dump_folder(
    file_name, use_encode=True, create_if_not_exist=False
):
    """Read JSON file from EA dump folder.
    
    Provides direct access to files in the EA dump folder with proper encoding
    and file creation support.

    Args:
        file_name (str): Name of file in dump folder
        use_encode (bool, optional): Enable UTF-8 encoding for international characters.
            Defaults to True.
        create_if_not_exist (bool, optional): Create empty file if not found.
            Defaults to False.

    Returns:
        dict: File contents as dictionary
    """
    filepath = FOLDER.get_local_dump_folder_file(file_name)
    return _read_json_as_dict(filepath, use_encode, create_if_not_exist)


def _shared_state_key(file_name):
    """Map a legacy shared-dump file name to a DEPOT.STATE key.

    The office shared dump folder is retired (network-drive retirement epic,
    2026-07-29). Shared data now lives in DEPOT shared state. A file name like
    "REVIT_PROJ_DATA_2334.sexyDuck" becomes the state key "REVIT_PROJ_DATA_2334"
    -- stable across read and write so round-trips match.
    """
    name = os.path.basename(file_name)
    for ext in (".sexyduck", ".json"):
        if name.lower().endswith(ext):
            name = name[:-len(ext)]
            break
    return name


def _read_json_as_dict_in_shared_dump_folder(
    file_name, use_encode=True, create_if_not_exist=False
):
    """Read a shared JSON doc through DEPOT shared state.

    2026-07-29 (network-drive retirement, Commit 3): the office shared dump
    folder is gone. This resolves through DEPOT.STATE.read_state instead. The
    signature is unchanged so the ~34 is_local=False call sites are untouched;
    use_encode is now a no-op (DEPOT handles JSON/encoding). When the depot is
    unreachable (e.g. before the server ships) read_state returns the default
    and alarms once -- a loud, actionable failure instead of the old silent
    write to a private local sandbox nobody else ever saw.

    Args:
        file_name (str): Legacy shared-dump file name; mapped to a state key.
        use_encode (bool, optional): Ignored (kept for signature compatibility).
        create_if_not_exist (bool, optional): If True and the doc is absent,
            return an empty dict instead of None.

    Returns:
        dict: The stored data, {} when create_if_not_exist and absent, else None.
    """
    from EnneadTab.DEPOT import STATE
    key = _shared_state_key(file_name)
    data = STATE.read_state(key, default=None)
    if data is None and create_if_not_exist:
        return {}
    return data


def _save_dict_to_json(data_dict, filepath, use_encode=True):
    """Save dictionary to JSON file with proper encoding and file access conflict handling.
    
    Handles both IronPython and CPython environments, ensuring proper UTF-8
    encoding without BOM (Byte Order Mark). Includes automatic handling for
    non-serializable objects by converting them through a cascade of types:
    boolean -> integer -> float -> string.
    
    Uses temporary file approach to avoid file access conflicts.

    Args:
        data_dict (dict): Dictionary to save
        filepath (str): Target file path
        use_encode (bool, optional): Enable UTF-8 encoding for international characters.
            Defaults to True.

    Returns:
        bool: True if save successful, False otherwise
    """
    import time
    import shutil
    
    try:
        # Create a custom JSON encoder to handle non-serializable objects
        class AmazingJSONEncoder(json.JSONEncoder):
            def default(self, obj):
                try:
                    return super(AmazingJSONEncoder, self).default(obj)
                except TypeError:
                    # Try type conversion cascade: bool -> int -> float -> str
                    str_obj = str(obj).lower()
                    if str_obj == "true":
                        return True
                    elif str_obj == "false":
                        return False
                    
                    try:
                        return int(obj)
                    except (ValueError, TypeError):
                        try:
                            return float(obj)
                        except (ValueError, TypeError):
                            return str(obj)
        
        try:
            json_str = json.dumps(data_dict, ensure_ascii=False, indent=4, sort_keys=True, cls=AmazingJSONEncoder)
        except Exception as e:
            print("Failed to convert data_dict to json_str because of {}".format(str(e)))
            json_str = json.dumps(data_dict, ensure_ascii=True, indent=4, sort_keys=True, cls=AmazingJSONEncoder)
        
        # Use temporary file approach to avoid file access conflicts
        temp_filepath = filepath + ".tmp"
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                if sys.platform == "cli":  # IronPython
                    from System.IO import File, StreamWriter
                    from System.Text import Encoding, UTF8Encoding
                    
                    if use_encode:
                        # Use UTF8Encoding(False) to prevent BOM
                        utf8_no_bom = UTF8Encoding(False)
                        writer = StreamWriter(temp_filepath, False, utf8_no_bom)
                        writer.Write(json_str)
                        writer.Close()
                    else:
                        # Use basic file writing for non-encoded files
                        File.WriteAllText(temp_filepath, json_str)
                else:  # CPython
                    if use_encode:
                        with io.open(temp_filepath, "w", encoding="utf-8") as f:
                            f.write(json_str)
                    else:
                        with open(temp_filepath, "w") as f:
                            f.write(json_str)
                
                # Atomic move: temp file -> target file
                if os.path.exists(filepath):
                    os.remove(filepath)
                shutil.move(temp_filepath, filepath)
                return True
                
            except (OSError, IOError) as e:
                if "being used by another process" in str(e) or "WinError 32" in str(e):
                    print("File access conflict (attempt {}/{}): {}. Retrying in {}s...".format(
                        attempt + 1, max_retries, str(e), retry_delay))
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    raise e
            except Exception as e:
                print("Unexpected error saving JSON file {}: {}".format(filepath, str(e)))
                return False
        
        # If all retries failed
        print("Failed to save JSON file {} after {} attempts due to file access conflicts".format(filepath, max_retries))
        return False
        
    except Exception as e:
        print("Error saving JSON file {}: {}".format(filepath, str(e)))
        return False


def _save_dict_to_json_in_dump_folder(data_dict, file_name, use_encode=True):
    """Save dictionary to JSON file in EA dump folder.
    
    Direct storage of dictionary data to the EA dump folder with encoding support.

    Args:
        data_dict (dict): Dictionary to save
        file_name (str): Target filename
        use_encode (bool, optional): Enable UTF-8 encoding for international characters.
            Defaults to True.

    Returns:
        bool: True if save successful, False otherwise
    """
    filepath = FOLDER.get_local_dump_folder_file(file_name)
    return _save_dict_to_json(data_dict, filepath, use_encode=use_encode)


def _save_dict_to_json_in_shared_dump_folder(data_dict, file_name, use_encode=True):
    """Save a shared JSON doc through DEPOT shared state.

    2026-07-29 (network-drive retirement, Commit 3): writes go to
    DEPOT.STATE.write_state, not the retired shared dump folder. Signature
    unchanged (use_encode now a no-op). Returns True on a server-confirmed write;
    when offline it queues to the depot outbox, alarms, and returns False -- the
    caller learns the shared write did not land instead of it silently vanishing
    into a private local folder.

    Args:
        data_dict (dict): Dictionary to save.
        file_name (str): Legacy shared-dump file name; mapped to a state key.
        use_encode (bool, optional): Ignored (kept for signature compatibility).

    Returns:
        bool: True if the write reached the depot, False if queued/failed.
    """
    from EnneadTab.DEPOT import STATE
    key = _shared_state_key(file_name)
    return STATE.write_state(key, data_dict)


def _describe_write_target(filepath):
    """Best-effort diagnostic string for a failed list-file write.

    IronPython 2.7 / CPython safe. os.access on Windows is not an ACL check,
    but the readonly-bit / existence bits still distinguish "file missing"
    from "file present but not writable" when we log access-denied.
    """
    bits = ["path={}".format(filepath)]
    try:
        bits.append("exists={}".format(os.path.exists(filepath)))
    except Exception:
        bits.append("exists=?")
    try:
        parent = os.path.dirname(filepath)
        bits.append("parent_exists={}".format(os.path.exists(parent)))
    except Exception:
        pass
    try:
        if os.path.exists(filepath):
            bits.append("os.access_W_OK={}".format(os.access(filepath, os.W_OK)))
        else:
            bits.append("parent_W_OK={}".format(
                os.access(os.path.dirname(filepath), os.W_OK)))
    except Exception:
        pass
    try:
        bits.append("user={}".format(os.environ.get("USERNAME", "?")))
        bits.append("computer={}".format(os.environ.get("COMPUTERNAME", "?")))
    except Exception:
        pass
    return " ".join(bits)


def _is_sharing_violation(error):
    """True when a write failed because another process holds the file."""
    msg = str(error)
    lower = msg.lower()
    return (
        "being used by another process" in msg
        or "WinError 32" in msg
        or "sharing" in lower
        or "used by another process" in lower
    )


def get_list(filepath):
    """Read file contents as list of strings.
    
    Each line in the file becomes an element in the returned list.
    Creates a temporary copy to avoid file locking issues.

    Args:
        filepath (str): Path to text file

    Returns:
        list: List of strings, empty list if file doesn't exist
    """
    if not os.path.exists(filepath):
        return []
    extention = FOLDER.get_file_extension_from_path(filepath)
    local_path = FOLDER.get_local_dump_folder_file("temp{}".format(extention))
    COPY.copyfile(filepath, local_path)

    with io.open(local_path,  "r", encoding="utf-8") as f:
        lines = f.readlines()

    return map(lambda x: x.replace("\n", ""), lines)


def set_list(list, filepath, end_with_new_line=False):
    """Write list of strings to file.
    
    Each element in the list becomes a line in the file.
    Supports UTF-8 encoding for international characters.

    Network-share writes routinely fail with UnauthorizedAccessException /
    IOError when the caller can see the folder but cannot write it, or when
    another process holds the file. Callers already treat a False return as
    "no write access" -- this function used to throw instead.

    Args:
        list (list): List of strings to write
        filepath (str): Target file path
        end_with_new_line (bool, optional): Add newline at end of file.
            Defaults to False.

    Returns:
        bool: True if write successful, False if denied or otherwise failed
    """
    payload = "\n".join(list)
    if end_with_new_line:
        payload += "\n"

    max_retries = 3
    retry_delay = 0.5
    last_error = None
    for attempt in range(max_retries):
        try:
            with io.open(filepath, "w", encoding="utf-8") as f:
                f.write(payload)
            return True
        except (OSError, IOError) as e:
            last_error = e
            if _is_sharing_violation(e) and attempt < max_retries - 1:
                print("set_list sharing conflict (attempt {}/{}): {}. Retrying...".format(
                    attempt + 1, max_retries, e))
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            print("set_list failed: {} | {}".format(e, _describe_write_target(filepath)))
            return False
        except Exception as e:
            print("set_list unexpected error: {} | {}".format(
                e, _describe_write_target(filepath)))
            return False

    print("set_list failed after {} attempts: {} | {}".format(
        max_retries, last_error, _describe_write_target(filepath)))
    return False


#######################################################################################


def pretty_print_dict(data_dict):
    """Print dictionary with formatted indentation.
    
    Useful for debugging and data inspection.

    Args:
        data_dict (dict): Dictionary to print
    """
    pretty_string = json.dumps(data_dict, indent=4)
    print(pretty_string)


def get_data(file_name_or_full_path, is_local=True):
    """Retrieve data from JSON file.
    
    Supports both local and shared storage locations.
    Creates file with empty dictionary if it doesn't exist.

    Args:
        file_name_or_full_path (str): Filename or full path, extension is optional, if missing, will add plugin extension instead.
        is_local (bool, optional): Use local dump folder if True,
            shared if False. Defaults to True.

    Returns:
        dict: File contents as dictionary
    """
    if os.path.exists(file_name_or_full_path):
        return _read_json_as_dict(file_name_or_full_path, use_encode=True, create_if_not_exist=False)

    if is_local:
        return _read_json_as_dict_in_dump_folder(
            file_name_or_full_path, use_encode=True, create_if_not_exist=True
        )
    else:
        return _read_json_as_dict_in_shared_dump_folder(
            file_name_or_full_path, use_encode=True, create_if_not_exist=True
        )


def set_data(data_dict, file_name_or_full_path, is_local=True):
    """Save dictionary to JSON file.
    
    Supports both local and shared storage locations.
    Ensures proper encoding for international characters.

    Args:
        data_dict (dict): Dictionary to save
        file_name_or_full_path (str): Filename or full path
        is_local (bool, optional): Use local dump folder if True,
            shared if False. Defaults to True.

    Returns:
        bool: True if save successful
    """
    # Only use direct path if it's actually a full/absolute path, not just a filename
    is_full_path = os.path.isabs(file_name_or_full_path) or os.path.dirname(file_name_or_full_path)
    
    if is_full_path and os.path.exists(file_name_or_full_path):
        return _save_dict_to_json(data_dict, file_name_or_full_path, use_encode=True)
    
    if is_local:
        _save_dict_to_json_in_dump_folder(data_dict, file_name_or_full_path, use_encode=True)
    else:
        _save_dict_to_json_in_shared_dump_folder(data_dict, file_name_or_full_path, use_encode=True)


@contextmanager
def update_data(file_name, is_local=True, keep_holder_key=None):
    """Context manager for safe data updates.
    
    Provides atomic read-modify-write operations on JSON data files.
    Automatically handles file loading and saving.

    Example:
        with update_data("config.json") as data:
            data["setting"] = "new_value"

    Args:
        file_name (str): Name of JSON file
        is_local (bool, optional): Use local dump folder if True,
            shared if False. Defaults to True.
        keep_holder_key (str, optional): Key to preserve during updates.
            Defaults to None.

    Yields:
        dict: File contents for modification
    """
    if os.path.exists(file_name):
        file_name = os.path.basename(file_name)

    try:
        data = get_data(file_name, is_local) or {}  # Ensure we have a dict


        yield data

       
        if keep_holder_key is not None:
            data["key_holder"] = keep_holder_key
            # print("After setting key_holder:", data)


        set_data(data, file_name, is_local)
   
    except Exception as e:
        print("Error in DATA_FILE.py at update_data function:", str(e))
        try:
            import ERROR_HANDLE
            print(ERROR_HANDLE.get_alternative_traceback())
        except Exception as traceback_error:
            import traceback
            print("Failed to get alternative traceback: {}".format(str(traceback_error)))
            print("Original traceback:")
            print(traceback.format_exc())

        


#######################################
class DataType:
    INT = "int"
    FLOAT = "float"
    STR = "str"
    BOOL = "bool"
    DICT = "dict"
    def __str__(self):
        return self.value
    def __repr__(self):
        return self.value
    def __json__(self):
        return self.value

    def __eq__(self, other):
        return self.value == other.value


STICKY_FILE = "sticky"


def get_sticky(sticky_name, default_value_if_no_sticky=None, 
               data_type_if_no_sticky=None, tiny_wait=False):
    """Retrieve persistent sticky data.
    
    Access sticky data that persists across sessions.
    Returns default value if sticky doesn't exist.

    Args:
        sticky_name (str): Identifier for sticky data
        default_value_if_no_sticky (any, optional): Default value if not found.
            Defaults to None.
        data_type_if_no_sticky (str, optional): Type of data to store.
            "int" for integer, "float" for float, "str" for string, "bool" for boolean, "dict" for dictionary.
            Defaults to None.

    Returns:
        any: Sticky data value or default
    """

    data = get_data(STICKY_FILE)
    if sticky_name not in data.keys():
        set_sticky(sticky_name, default_value_if_no_sticky, data_type_if_no_sticky)
        if tiny_wait:
            time.sleep(0.05)
        return default_value_if_no_sticky
    value = data[sticky_name]
    if tiny_wait:
        time.sleep(0.05)
    if isinstance(value, dict):
        data_type = value.get("type", None)
        if data_type == DataType.INT:
            return int(value.get("value", default_value_if_no_sticky))
        elif data_type == DataType.FLOAT:
            return float(value["value"])
        elif data_type == DataType.STR:
            return str(value["value"])
        elif data_type == DataType.BOOL:
            return bool(value["value"])
        elif data_type == DataType.DICT:
            return value["value"]
        else:
            return value
    else:
        return value


    
def set_sticky(sticky_name, value_to_write, 
               data_type=None, tiny_wait=False):
    """Save persistent sticky data.
    
    Store data that persists across sessions.
    Automatically handles JSON serialization.

    Args:
        sticky_name (str): Identifier for sticky data
        value_to_write (any): Value to store
        data_type (str, optional): Type of data to store.
            "int" for integer, "float" for float, "str" for string, "bool" for boolean.
            Defaults to None.
    Returns:
        bool: True if save successful
    """
    with update_data(STICKY_FILE) as data:
        if data_type == None:
            data[sticky_name] = value_to_write

        elif data_type == DataType.INT:
            data[sticky_name] = {"type": DataType.INT, "value": int(value_to_write)}
        elif data_type == DataType.FLOAT:
            data[sticky_name] = {"type": DataType.FLOAT, "value": float(value_to_write)}
        elif data_type == DataType.STR:
            data[sticky_name] = {"type": DataType.STR, "value": str(value_to_write)}
        elif data_type == DataType.BOOL:
            data[sticky_name] = {"type": DataType.BOOL, "value": bool(value_to_write)}
        elif data_type == DataType.DICT:
            data[sticky_name] = {"type": DataType.DICT, "value": value_to_write}

    if tiny_wait:
        time.sleep(0.05)


if __name__ == "__main__":


    test_names = ["BLOCKS2FAMILY", "BLOCKS2FAMILY_railing_middle", "BLOCKS2FAMILY_railing_start", "BLOCKS2FAMILY_railing_end", "BLOCKS2FAMILY_railing_extension", "any name"]


    for name in test_names:
        with update_data(name) as data:
            data["setting"] = "new_value"

        print ("data {}: {}".format(name, get_data(name)))