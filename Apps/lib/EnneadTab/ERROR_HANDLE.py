#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Error handling and logging utilities for EnneadTab.

This module provides comprehensive error handling, logging, and reporting
functionality across the EnneadTab ecosystem. It includes automated error
reporting, developer debugging tools, and user notification systems.

Key Features:
- Automated error catching and logging
- Developer-specific debug messaging
- Error email notifications
- Stack trace formatting
- Silent error handling options
"""

import traceback

# Import modules with error handling
try:
    import ENVIRONMENT
except Exception as e:
    print("Error importing ENVIRONMENT in ERROR_HANDLE.py: {}".format(traceback.format_exc()))
    ENVIRONMENT = None

try:
    import WEB_GUARD
except Exception as e:
    print("Error importing WEB_GUARD in ERROR_HANDLE.py: {}".format(traceback.format_exc()))
    WEB_GUARD = None

try:
    import EMAIL
except Exception as e:
    print("Error importing EMAIL in ERROR_HANDLE.py: {}".format(traceback.format_exc()))
    EMAIL = None

try:
    import USER
except Exception as e:
    print("Error importing USER in ERROR_HANDLE.py: {}".format(traceback.format_exc()))
    USER = None

try:
    import TIME
except Exception as e:
    print("Error importing TIME in ERROR_HANDLE.py: {}".format(traceback.format_exc()))
    TIME = None

try:
    import NOTIFICATION
except Exception as e:
    print("Error importing NOTIFICATION in ERROR_HANDLE.py: {}".format(traceback.format_exc()))
    NOTIFICATION = None

try:
    import OUTPUT
except Exception as e:
    print("Error importing OUTPUT in ERROR_HANDLE.py: {}".format(traceback.format_exc()))
    OUTPUT = None

try:
    import FOLDER
except Exception as e:
    print("Error importing FOLDER in ERROR_HANDLE.py: {}".format(traceback.format_exc()))
    FOLDER = None

try:
    import DATA_CONVERSION
except Exception as e:
    print("Error importing DATA_CONVERSION in ERROR_HANDLE.py: {}".format(traceback.format_exc()))
    DATA_CONVERSION = None


# Add recursion depth tracking
_error_handler_recursion_depth = 0
_max_error_handler_recursion_depth = 50  # Set a reasonable limit


####################################################################################################
"""
temp solution to debug where the error is coming from
"""


# Safe ENVIRONMENT accessor functions
def get_plugin_name():
    """Safely get plugin name with fallback."""
    if ENVIRONMENT is not None:
        try:
            return ENVIRONMENT.PLUGIN_NAME
        except:
            print(traceback.format_exc())
            pass
    return "EnneadTab"  # Default fallback

def get_plugin_extension():
    """Safely get plugin extension with fallback."""
    if ENVIRONMENT is not None:
        try:
            return ENVIRONMENT.PLUGIN_EXTENSION
        except:
            print(traceback.format_exc())
            pass
    return ".sexyDuck"  # Default fallback

def get_document_folder():
    """Safely get document folder with fallback."""
    if ENVIRONMENT is not None:
        try:
            return ENVIRONMENT.DOCUMENT_FOLDER
        except:
            print(traceback.format_exc())
            pass
    return None

def get_one_drive_desktop_folder():
    """Safely get OneDrive desktop folder with fallback."""
    if ENVIRONMENT is not None:
        try:
            return ENVIRONMENT.ONE_DRIVE_DESKTOP_FOLDER
        except:
            print(traceback.format_exc())
            pass
    return None

def get_usage_log_google_form_submit():
    """Safely get usage log Google form URL with fallback."""
    if ENVIRONMENT is not None:
        try:
            return ENVIRONMENT.USAGE_LOG_GOOGLE_FORM_SUBMIT
        except:
            print(traceback.format_exc())
            pass
    return None

def get_app_name():
    """Safely get app name with fallback."""
    if ENVIRONMENT is not None:
        try:
            return ENVIRONMENT.get_app_name()
        except:
            print(traceback.format_exc())
            pass
    return "unknown"  # Default fallback

def is_revit_environment():
    """Safely check if in Revit environment."""
    if ENVIRONMENT is not None:
        try:
            return ENVIRONMENT.IS_REVIT_ENVIRONMENT
        except:
            print(traceback.format_exc())
            pass
    return False
####################################################################################################



def _ensure_recursion_depth_is_int():
    """Ensure _error_handler_recursion_depth is an integer, reset to 0 if not."""
    global _error_handler_recursion_depth
    if not isinstance(_error_handler_recursion_depth, int):
        print("WARNING: _error_handler_recursion_depth was {} with value {}, resetting to 0".format(type(_error_handler_recursion_depth), _error_handler_recursion_depth))
        _error_handler_recursion_depth = 0

def _safe_increment_recursion_depth():
    """Safely increment the recursion depth counter."""
    global _error_handler_recursion_depth
    _ensure_recursion_depth_is_int()
    _error_handler_recursion_depth += 1

def _safe_decrement_recursion_depth():
    """Safely decrement the recursion depth counter."""
    global _error_handler_recursion_depth
    _ensure_recursion_depth_is_int()
    _error_handler_recursion_depth -= 1

def get_alternative_traceback():
    """Generate a formatted stack trace for the current exception.

    Creates a human-readable stack trace including exception type,
    message, and file locations. Output is visible to developers only.

    Returns:
        str: Formatted stack trace information
    """
    import sys
    OUT = []
    exc_type, exc_value, exc_traceback = sys.exc_info()
    
    # Handle exception type
    type_str = str(exc_type.__name__ if hasattr(exc_type, '__name__') else exc_type)
    OUT.append("Exception Type: {}".format(type_str))
    
    # Handle exception message
    try:
        msg = str(exc_value)
    except:
        msg = "Unable to convert error message to string"
    OUT.append("Exception Message: {}".format(msg))
    
    # Handle stack trace
    while exc_traceback:
        filename = str(exc_traceback.tb_frame.f_code.co_filename)
        lineno = str(exc_traceback.tb_lineno)
        OUT.append("File: {}, Line: {}".format(filename, lineno))
        exc_traceback = exc_traceback.tb_next

    result = "\n".join(OUT)
    if USER.IS_DEVELOPER:
        print(result)
    return result


def save_recent_traceback_to_log(error_info, func_name="unknown", additional_context=""):
    """Save recent traceback information to RECENT_TRACEBACK.LOG file.
    
    This function creates a persistent log file that can be monitored locally
    to track errors that occur in Rhino, Revit, or other environments.
    
    Args:
        error_info (str): The error traceback information to log
        func_name (str): Name of the function where the error occurred
        additional_context (str): Any additional context information
    """
    try:
        # Get the log file path
        if FOLDER is not None:
            log_file_path = FOLDER.get_local_dump_folder_file("RECENT_TRACEBACK.LOG")
        else:
            # Fallback if FOLDER is not available
            import os
            user_docs = os.path.expanduser("~/Documents")
            if not os.path.exists(user_docs):
                user_docs = os.path.join(os.environ.get("USERPROFILE", ""), "Documents")
            
            enneadtab_folder = os.path.join(user_docs, "EnneadTab Ecosystem", "Dump")
            if not os.path.exists(enneadtab_folder):
                try:
                    os.makedirs(enneadtab_folder)
                except:
                    pass
            
            log_file_path = os.path.join(enneadtab_folder, "RECENT_TRACEBACK.LOG")
        
        # Get current timestamp
        if TIME is not None:
            timestamp = TIME.get_formatted_current_time()
        else:
            import time
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Get user name
        if USER is not None:
            user_name = USER.USER_NAME
        else:
            import os
            user_name = os.environ.get("USERNAME", "unknown")
        
        # Get plugin name
        plugin_name = get_plugin_name()
        
        # Format the log entry
        log_entry = []
        log_entry.append("=" * 80)
        log_entry.append("TIMESTAMP: {}".format(timestamp))
        log_entry.append("USER: {}".format(user_name))
        log_entry.append("PLUGIN: {}".format(plugin_name))
        log_entry.append("FUNCTION: {}".format(func_name))
        if additional_context:
            log_entry.append("CONTEXT: {}".format(additional_context))
        log_entry.append("-" * 80)
        log_entry.append(error_info)
        log_entry.append("=" * 80)
        log_entry.append("")  # Empty line for readability
        
        # Write to log file (append mode)
        import io
        with io.open(log_file_path, "a", encoding="utf-8") as f:
            f.write("\n".join(log_entry))
        
        # Keep log file size manageable (max 1000 lines, ~50KB)
        try:
            with io.open(log_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            if len(lines) > 1000:
                # Keep only the last 800 lines to prevent file from growing too large
                with io.open(log_file_path, "w", encoding="utf-8") as f:
                    f.writelines(lines[-800:])
        except Exception:
            # If we can't manage the file size, just continue
            pass
            
    except Exception as e:
        # Don't let logging errors break the main error handling
        print_note("Failed to save traceback to RECENT_TRACEBACK.LOG: {}".format(str(e)))

def try_catch_error(is_silent=False, is_pass = False):
    """Decorator for catching exceptions and sending automated error log emails.

    Wraps functions to provide automated error handling, logging, and notification.
    Can operate in silent mode or pass-through mode for different error handling needs.

    Args:
        is_silent (bool, optional): If True, sends error email without user notification.
            Defaults to False.
        is_pass (bool, optional): If True, ignores errors without notification or email.
            Defaults to False.

    Returns:
        function: Decorated function with error handling
    """
    def decorator(func):
        def error_wrapper(*args, **kwargs):
            global _error_handler_recursion_depth, _max_error_handler_recursion_depth
            
            # Check if we've reached max depth
            _ensure_recursion_depth_is_int()
            if _error_handler_recursion_depth >= _max_error_handler_recursion_depth:
                print("Maximum error handler recursion depth reached ({})".format(str(_max_error_handler_recursion_depth)))
                # Just call the function directly without error handling
                return func(*args, **kwargs)
                
            # Increment depth counter
            _safe_increment_recursion_depth()
            
            try:
                out = func(*args, **kwargs)
                # Decrement depth counter before returning
                _safe_decrement_recursion_depth()
                return out
            except Exception as e:
                if is_pass:
                    # Ensure we decrement even when passing
                    _safe_decrement_recursion_depth()
                    return
                    
                # Safely convert error message to string, handling Array[str] objects
                try:
                    if e is None:
                        error_msg = "Unknown error (None)"
                    elif hasattr(e, '__iter__') and not isinstance(e, (str, bytes)):
                        # Handle array-like objects by joining them
                        try:
                            error_msg = " ".join(str(item) for item in e)
                        except:
                            error_msg = str(e)
                    else:
                        error_msg = str(e)
                except Exception as convert_error:
                    error_msg = "Unable to convert error to string: {}".format(str(convert_error))
                
                print_note(error_msg)
                print_note("error_Wrapper func for EA Log -- Error: " + error_msg)
                error_time = "Oops at {}\n\n".format(TIME.get_formatted_current_time())
                error = get_alternative_traceback()
                if not error:
                    try:
                        import traceback
                        error = traceback.format_exc()
                    except Exception as new_e:
                        error = error_msg
                        print(new_e)
                
                # Save traceback to RECENT_TRACEBACK.LOG for local monitoring
                try:
                    save_recent_traceback_to_log(
                        error_info=error_time + error,
                        func_name=func.__name__,
                        additional_context="Silent: {} | Pass: {}".format(is_silent, is_pass)
                    )
                except Exception as log_error:
                    print_note("Failed to save to RECENT_TRACEBACK.LOG: {}".format(str(log_error)))

                # Safely get plugin name with fallback
                plugin_name = get_plugin_name()
                
                subject_line = plugin_name + " Auto Error Log"
                if is_silent:
                    subject_line += "(Silent)"
                try:
                    EMAIL.email_error(error_time + error, func.__name__, USER.USER_NAME, subject_line=subject_line)
                except Exception as e:
                    print_note("Cannot send email: {}".format(get_alternative_traceback()))

                try:
                    send_error_to_error_dump(
                        error_message=error,
                        func_name=func.__name__,
                        user_name=USER.USER_NAME if USER else "unknown",
                        is_silent=is_silent
                    )
                except Exception as e:
                    pass

                if not is_silent:
                    try:
                        error_file = FOLDER.get_local_dump_folder_file("error_general_log.txt")
                        
                        # Ensure the directory exists before writing the file
                        import os
                        error_dir = os.path.dirname(error_file)
                        if not os.path.exists(error_dir):
                            try:
                                os.makedirs(error_dir)
                            except Exception as dir_error:
                                print_note("Cannot create error directory [{}]: {}".format(error_dir, str(dir_error)))
                                # Fallback to current directory
                                error_file = "error_general_log.txt"
                    except Exception as path_error:
                        # Fallback if FOLDER is not available - create a simple path
                        try:
                            import os
                            # Try to get user documents folder as fallback
                            user_docs = os.path.expanduser("~/Documents")
                            if not os.path.exists(user_docs):
                                user_docs = os.path.join(os.environ.get("USERPROFILE", ""), "Documents")
                            
                            # Create EnneadTab folder in documents if it doesn't exist
                            enneadtab_folder = os.path.join(user_docs, "EnneadTab Ecosystem", "Dump")
                            if not os.path.exists(enneadtab_folder):
                                try:
                                    os.makedirs(enneadtab_folder)
                                except:
                                    pass
                            
                            error_file = os.path.join(enneadtab_folder, "error_general_log.txt")
                        except:
                            # Ultimate fallback to current directory
                            error_file = "error_general_log.txt"
              
                        error += "\n\n######If you have " + plugin_name + " UI window open, just close the original " + plugin_name + " window. Do no more action, otherwise the program might crash.##########\n#########Not sure what to do? Msg Sen Zhang, you have dicovered a important bug and we need to fix it ASAP!!!!!########BTW, a local copy of the error is available at {}".format(error_file)
                    try:
                        import io
                        with io.open(error_file, "w", encoding="utf-8") as f:
                            f.write(error)
                    except IOError as e:
                        print_note("Cannot write error file [{}]: {}".format(error_file, str(e)))

                    if OUTPUT is not None:
                        output = OUTPUT.get_output()
                        output.write(error_time, OUTPUT.Style.Subtitle)
                        output.write(error)
                        output.insert_divider()
                        output.plot()

                if is_revit_environment() and not is_silent and NOTIFICATION is not None and hasattr(NOTIFICATION, 'messenger'):
                    NOTIFICATION.messenger(
                        "!Critical Warning, close all Revit UI window from " + plugin_name + " and reach to Sen Zhang.")
                
                # Make sure to decrement the counter even in case of exception
                _safe_decrement_recursion_depth()
                    
        error_wrapper.original_function = func
        return error_wrapper
    return decorator

_LAST_UPDATE_DUCK_CACHE = [None]

def _get_last_update_duck_cached():
    """Timestamp of the newest successful update record (.duck filename).

    Deliberate cycle-free twin of VERSION_CONTROL.get_last_update_time():
    VERSION_CONTROL imports ERROR_HANDLE, so this module re-implements the
    tiny read instead of importing back. Cached for the process lifetime --
    an error storm must not pay a listdir per event.
    """
    if _LAST_UPDATE_DUCK_CACHE[0] is None:
        import os
        result = ""
        try:
            if ENVIRONMENT is not None and hasattr(ENVIRONMENT, "ECO_SYS_FOLDER"):
                records = [f for f in os.listdir(ENVIRONMENT.ECO_SYS_FOLDER)
                           if f.endswith(".duck") and "_ERROR" not in f]
                if records:
                    records.sort()
                    result = records[-1].replace(".duck", "")
        except Exception:
            result = ""
        _LAST_UPDATE_DUCK_CACHE[0] = result
    return _LAST_UPDATE_DUCK_CACHE[0]


def send_error_to_error_dump(error_message, func_name, user_name, is_silent=False):
    """Send error to the universal ErrorDump service at enneadtab.com.

    Public endpoint - no API key needed. Fires and forgets with a 5s timeout.
    Compatible with IronPython 2.7, CPython 2.7, and CPython 3.x.

    Transport order:
      1. .NET HttpWebRequest (IronPython 2.7 inside Revit/Rhino) - only HTTPS
         path proven reliable on our user machines; urllib2/urllib.request
         have TLS/DNS issues on some office network segments that cause silent
         failures (see memory: feedback_ironpython_networking).
      2. urllib.request (CPython 3.x)
      3. urllib2 (legacy CPython 2.7)
      4. urllib3 (Revit venv fallback)

    When an earlier transport fails, its exception repr is captured and
    attached to the next attempt's context under ``prev_transport_attempts``
    so that the first successful send reveals why prior transports failed.

    Args:
        error_message (str): The error traceback or message
        func_name (str): Name of the function that threw
        user_name (str): Windows username
        is_silent (bool): Whether this was a silent error
    """
    import json
    import os

    # Detect environment
    env = "terminal"
    try:
        if ENVIRONMENT is not None:
            if ENVIRONMENT.IS_REVIT_ENVIRONMENT:
                env = "revit"
            elif ENVIRONMENT.IS_RHINO_ENVIRONMENT:
                env = "rhino"
    except Exception:
        pass

    # Build context with available metadata
    base_context = {
        "is_silent": is_silent,
        "computer_name": os.environ.get("COMPUTERNAME", "unknown"),
    }
    try:
        if ENVIRONMENT is not None:
            if hasattr(ENVIRONMENT, "get_revit_version"):
                base_context["revit_version"] = str(ENVIRONMENT.get_revit_version())
            if hasattr(ENVIRONMENT, "get_pyrevit_version"):
                base_context["pyrevit_version"] = str(ENVIRONMENT.get_pyrevit_version())
    except Exception:
        pass
    try:
        if ENVIRONMENT is not None and hasattr(ENVIRONMENT, "get_dist_version"):
            base_context["dist_version"] = str(ENVIRONMENT.get_dist_version())
    except Exception:
        pass
    try:
        last_update = _get_last_update_duck_cached()
        if last_update:
            base_context["last_update"] = str(last_update)
    except Exception:
        pass

    url = "https://error-dump-ennead-projects.vercel.app/error-dump/api/ingest"
    headers = {"Content-Type": "application/json"}
    prev_attempts = []

    def _payload_str(transport):
        ctx = dict(base_context)
        ctx["transport"] = transport
        if prev_attempts:
            ctx["prev_transport_attempts"] = prev_attempts
        return json.dumps({
            "source_app": "EnneadTab-OS",
            "environment": env,
            "error_message": str(error_message)[:5000],
            "stack_trace": str(error_message)[:10000],
            "function_name": str(func_name),
            "user_name": str(user_name),
            "machine_name": os.environ.get("COMPUTERNAME", "unknown"),
            "context": ctx,
        })

    # Transport 1: .NET HttpWebRequest (reliable from IronPython 2.7 in Revit/Rhino).
    # urllib paths below have silently failed for a known cohort of users
    # whose office network or IronPython TLS stack rejects urllib HTTPS but
    # accepts .NET HttpWebRequest. If clr is unavailable (CPython), fall through.
    try:
        import clr  # noqa: F401  (IronPython interop gate)
        clr.AddReference("System")
        from System.Net import WebRequest, ServicePointManager, SecurityProtocolType
        from System.Text import Encoding

        try:
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        except Exception:
            pass

        payload_str = _payload_str("dotnet-http")
        body_bytes = Encoding.UTF8.GetBytes(payload_str)

        req = WebRequest.Create(url)
        req.Method = "POST"
        req.ContentType = "application/json"
        req.Timeout = 5000  # milliseconds
        # AllowAutoRedirect defaults to True; an SSO bounce would otherwise be
        # read as a delivered error report. See WEB_GUARD.
        if WEB_GUARD is not None:
            WEB_GUARD.harden_dotnet_request(req)

        req.ContentLength = body_bytes.Length
        req_stream = req.GetRequestStream()
        try:
            req_stream.Write(body_bytes, 0, body_bytes.Length)
        finally:
            req_stream.Close()
        resp = req.GetResponse()
        try:
            resp.Close()
        except Exception:
            pass
        return
    except ImportError:
        pass  # not running under IronPython / .NET - fall through to urllib paths
    except Exception as e:
        prev_attempts.append({"type": "dotnet-http", "error": repr(e)[:200]})

    # Transport 2: urllib.request (CPython 3.x)
    try:
        import urllib.request
        payload = _payload_str("urllib.request").encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers)
        WEB_GUARD.urlopen_no_redirect(req, 5)
        return
    except ImportError:
        pass
    except Exception as e:
        prev_attempts.append({"type": "urllib.request", "error": repr(e)[:200]})

    # Transport 3: urllib2 (legacy CPython 2.7)
    try:
        import urllib2
        payload = _payload_str("urllib2").encode("utf-8")
        req = urllib2.Request(url, data=payload, headers=headers)
        WEB_GUARD.urlopen_no_redirect(req, 5)
        return
    except ImportError:
        pass
    except Exception as e:
        prev_attempts.append({"type": "urllib2", "error": repr(e)[:200]})

    # Transport 4: urllib3 (Revit venv fallback)
    try:
        import urllib3
        http = urllib3.PoolManager()
        payload = _payload_str("urllib3").encode("utf-8")
        http.request("POST", url, body=payload, headers=headers, timeout=5.0, redirect=False)
        return
    except ImportError:
        pass
    except Exception as e:
        prev_attempts.append({"type": "urllib3", "error": repr(e)[:200]})


def _should_report_to_error_dump_throttled(throttle_key, ttl_seconds=86400):
    """Rate-limit a silent ErrorDump report to once per machine per ttl.

    Mirrors ENVIRONMENT._should_report_shared_root_alarm so that a fleet-wide
    infra outage (every user x every click) does not flood ErrorDump. Uses a
    marker file in the local DUMP_FOLDER keyed by throttle_key.

    Fails OPEN (returns True) if the marker cannot be resolved -- a duplicate
    report is preferable to a lost developer signal.

    Args:
        throttle_key (str): Stable identifier for the warning being throttled.
        ttl_seconds (int): Minimum seconds between reports. Defaults to 24h.

    Returns:
        bool: True if this machine has not reported throttle_key within ttl.
    """
    import os
    import time
    if ENVIRONMENT is None:
        return True
    try:
        dump_folder = ENVIRONMENT.DUMP_FOLDER
    except Exception:
        return True
    # Sanitize to a filesystem-safe key so an odd throttle_key (e.g. a pip
    # target carrying '>=' or '/') can't break the marker file and silently
    # disable throttling (which fails open -> flood).
    safe_key = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(throttle_key))
    marker = os.path.join(dump_folder, "errdump_throttle_{}.DuckLock".format(safe_key))
    try:
        if os.path.exists(marker):
            if os.path.getmtime(marker) > (time.time() - ttl_seconds):
                return False
    except Exception:
        pass
    try:
        with open(marker, "w") as f:
            f.write(str(throttle_key))
    except Exception:
        pass
    return True


def report_infra_warning_to_error_dump(message, func_name, throttle_key=None, ttl_seconds=86400):
    """Silent, optionally rate-limited ErrorDump report for an infra/dev warning.

    Use for operational warnings (shared drive unreachable, module missing,
    etc.) that are hidden from the average user but MUST stay visible to
    developers across the fleet. The user sees nothing (is_silent=True); the
    developer sees it in ErrorDump. Never raises.

    Pass throttle_key for high-frequency call sites so a fleet-wide outage does
    not flood ErrorDump; omit it for naturally-rare sites.

    Args:
        message (str): Warning text for the ErrorDump entry.
        func_name (str): "MODULE.function" that detected the condition.
        throttle_key (str): Optional per-machine 24h throttle key.
        ttl_seconds (int): Throttle window used when throttle_key is given.
    """
    try:
        if throttle_key and not _should_report_to_error_dump_throttled(throttle_key, ttl_seconds):
            return
        user_name = "unknown"
        try:
            if USER is not None:
                user_name = getattr(USER, "USER_NAME", "unknown")
        except Exception:
            pass
        send_error_to_error_dump(message, func_name, user_name, is_silent=True)
    except Exception:
        pass


def report_infra_warning_to_error_dump_async(message, func_name, throttle_key=None, ttl_seconds=86400):
    """Non-blocking variant of report_infra_warning_to_error_dump.

    Fires the report on a background daemon thread so it is safe to call from an
    import-time / package-init path WITHOUT adding the <=5s ErrorDump POST to
    Revit/Rhino startup latency. (ENVIRONMENT.announce_shared_root_status is
    deliberately never called at import for exactly this reason.) Never raises.

    Args:
        message (str): Warning text for the ErrorDump entry.
        func_name (str): "MODULE.function" that detected the condition.
        throttle_key (str): Optional per-machine 24h throttle key.
        ttl_seconds (int): Throttle window used when throttle_key is given.
    """
    # Throttle SYNCHRONOUSLY (fast local file op) before spawning, so a cascade
    # of correlated failures (e.g. every module failing on one broken dependency
    # at package init) spawns at most one thread / one POST per key per ttl,
    # instead of racing dozens of threads that each pass their own in-thread check.
    try:
        if throttle_key and not _should_report_to_error_dump_throttled(throttle_key, ttl_seconds):
            return
    except Exception:
        pass

    def _worker():
        try:
            user_name = "unknown"
            try:
                if USER is not None:
                    user_name = getattr(USER, "USER_NAME", "unknown")
            except Exception:
                pass
            send_error_to_error_dump(message, func_name, user_name, is_silent=True)
        except Exception:
            pass
    try:
        import threading
        t = threading.Thread(target=_worker)
        t.daemon = True
        t.start()
    except Exception:
        pass


def print_note(*args):
    """Print debug information visible only to developers.

    Formats and displays debug information with type annotations.
    Supports single or multiple arguments of any type.

    Args:
        *args: Variable number of items to display

    Example:
        print_note("hello", 123, ["a", "b"])
        Output:
            [Dev Debug Only Note]
            - str: hello
            - int: 123
            - list: ['a', 'b']
    """
    if not USER.IS_DEVELOPER:
        return
        
    try:
        from pyrevit import script #pyright: ignore
        output = script.get_output()
        
        # If single argument, keep original behavior
        if len(args) == 1:
            # Use utility function to safely convert to string
            if DATA_CONVERSION:
                arg_str = DATA_CONVERSION.safe_convert_to_string(args[0])
            else:
                try:
                    arg_str = str(args[0])
                except:
                    # Handle .NET Array objects that don't have .replace()
                    if hasattr(args[0], '__iter__') and not isinstance(args[0], (str, bytes)):
                        arg_str = "[" + ", ".join(str(item) for item in args[0]) + "]"
                    else:
                        arg_str = "Unable to convert to string"
            output.print_md("***[Dev Debug Only Note]***:{}".format(arg_str))
            return
            
        # For multiple arguments, print type and value for each
        output.print_md("***[Dev Debug Only Note]***")
        for arg in args:
            if DATA_CONVERSION:
                arg_str = DATA_CONVERSION.safe_convert_to_string(arg)
            else:
                try:
                    arg_str = str(arg)
                except:
                    # Handle .NET Array objects that don't have .replace()
                    if hasattr(arg, '__iter__') and not isinstance(arg, (str, bytes)):
                        arg_str = "[" + ", ".join(str(item) for item in arg) + "]"
                    else:
                        arg_str = "Unable to convert to string"
            output.print_md("- *{}*: {}".format(type(arg).__name__, arg_str))
            
    except Exception as e:
        # Fallback to print if pyrevit not available
        if len(args) == 1:
            if DATA_CONVERSION:
                arg_str = DATA_CONVERSION.safe_convert_to_string(args[0])
            else:
                try:
                    arg_str = str(args[0])
                except:
                    # Handle .NET Array objects that don't have .replace()
                    if hasattr(args[0], '__iter__') and not isinstance(args[0], (str, bytes)):
                        arg_str = "[" + ", ".join(str(item) for item in args[0]) + "]"
                    else:
                        arg_str = "Unable to convert to string"
            print("[Dev Debug Only Note]:{}".format(arg_str))
            return
            
        print("[Dev Debug Only Note]")
        for arg in args:
            if DATA_CONVERSION:
                arg_str = DATA_CONVERSION.safe_convert_to_string(arg)
            else:
                try:
                    arg_str = str(arg)
                except:
                    # Handle .NET Array objects that don't have .replace()
                    if hasattr(arg, '__iter__') and not isinstance(arg, (str, bytes)):
                        arg_str = "[" + ", ".join(str(item) for item in arg) + "]"
                    else:
                        arg_str = "Unable to convert to string"
            print("- {}: {}".format(type(arg).__name__, arg_str))


if __name__ == "__main__":
    pass
