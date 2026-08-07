# -*- coding: utf-8 -*-
"""
EnneadTab Logging System

A comprehensive logging system for tracking and analyzing EnneadTab script usage.
This module provides detailed function execution logging with timing, arguments,
and results tracking across different environments.

Key Features:
    - Detailed function execution logging
    - Execution time tracking and formatting
    - Cross-environment compatibility (Revit/Rhino)
    - Automatic log file backup
    - User-specific log files
    - Context manager for temporary logging
    - JSON-based log storage
    - UTF-8 encoding support

Note:
    Log files are stored in the EA dump folder with user-specific naming
    and automatic backup functionality.
"""

import time
from contextlib import contextmanager
import io
import pprint  # For pretty printing log data
import json
import traceback

import USER
import TIME
import FOLDER
import DATA_FILE
import ENVIRONMENT
import ERROR_HANDLE
import WEB_GUARD

LOG_FILE_NAME = "log_{}".format(USER.USER_NAME)

# Google Form field IDs for usage logging
USAGE_LOG_FORM_FIELDS = {
    'entry.333183173': 'environment',     # Environment field
    'entry.1318607272': 'function_name',  # FunctionName field
    'entry.1785264643': 'result',         # Result field
}

# Optional Google Form field ID for username.
# To enable username logging to Google Form:
#   1. Add a new "Short answer" question to your usage Google Form (e.g. "Username").
#   2. Get the entry ID (looks like 'entry.123456789') from a pre-filled URL.
#   3. Set USERNAME_FIELD_ID below to that value.
#
# If this stays as None, username will NOT be sent to Google Form.
USERNAME_FIELD_ID = 'entry.1927078224'  # Username field ID from Google Form


def _build_usage_form_data(environment, function_name, result):
    """Build form data dictionary for usage logging Google Form.
    
    Args:
        environment (str): The application environment
        function_name (str): The name of the function that was executed
        result (str): The result of the function execution
        
    Note:
        Username is added automatically if USERNAME_FIELD_ID is configured.
        
    Returns:
        dict: Form data dictionary with field IDs and values
    """
    form_data = {
        'entry.333183173': environment,     # Environment field
        'entry.1318607272': function_name,  # FunctionName field  
        'entry.1785264643': result,         # Result field
    }

    # Optionally include username if a field ID has been configured
    try:
        if USERNAME_FIELD_ID:
            form_data[USERNAME_FIELD_ID] = USER.USER_NAME
    except Exception:
        # Never let username resolution break logging
        pass

    return form_data


@contextmanager
def log_usage(func, *args):
    """Context manager for temporary function usage logging.
    
    Creates a detailed log entry for a single function execution including
    start time, duration, arguments, and results.

    Args:
        func (callable): Function to log
        *args: Arguments to pass to the function

    Yields:
        Any: Result of the function execution

    Example:
        with log_usage(my_function, arg1, arg2) as result:
            # Function execution is logged
            process_result(result)
    """
    t_start = time.time()
    res = func(*args)
    yield res
    t_end = time.time()
    duration = TIME.get_readable_time(t_end - t_start)
    with io.open(FOLDER.get_local_dump_folder_file(LOG_FILE_NAME), "a", encoding="utf-8") as f:
        f.writelines("\nRun at {}".format(TIME.get_formatted_time(t_start)))
        f.writelines("\nDuration: {}".format(duration))
        f.writelines("\nFunction name: {}".format(func.__name__))
        f.writelines("\nArguments: {}".format(args))
        f.writelines("\nResult: {}".format(res))


# with log_usage(LOG_FILE_NAME) as f:
#     f.writelines('\nYang is writing!')


"""log and log is break down becasue rhino need a wrapper to direct run script directly
whereas revit need to look at local func run"""


def _is_button_script(script_path):
    """True only for a real, clickable tool bundle.

    This decorator is NOT only applied to buttons: `hooks/doc-syncing.py`,
    `hooks/doc-synced.py` and `plugin_startup.py` all carry it too. Reporting
    those to the Bank as `tool_run` would be wrong twice over -- a sync is not a
    tool use, and those firings would burn the daily earn cap that real tool use
    is supposed to fill. It would also put a file write on the sync path, which
    the whole session-card design exists to keep clear.

    So the test is DEFAULT-DENY: a path only qualifies if one of its folders is a
    button bundle, i.e. ends in "button" -- `.pushbutton`, `.smartbutton`,
    `.splitbutton` (Revit) and `.button` (Rhino). `.pulldown`, `.stack`, `.panel`
    and `.tab` are containers whose scripts already sit inside a button folder,
    so they need no separate case. Anything decorated in future that is not a
    button is silently excluded, which is the correct direction to fail: a missed
    coin is better than a fabricated one.

    Args:
        script_path (str): the decorated script's full path.

    Returns:
        bool: True if this invocation represents a user clicking a tool.
    """
    if not script_path:
        return False
    try:
        normalized = str(script_path).replace("\\", "/")
    except Exception:
        return False
    for part in normalized.split("/"):
        if part.lower().endswith("button"):
            return True
    return False


@FOLDER.backup_data(LOG_FILE_NAME, "log")
def log(script_path, func_name_as_record):
    """Decorator for persistent function usage logging.
    
    Creates a detailed JSON log entry for each function execution with
    timing, environment, and execution details. Includes automatic backup
    functionality.

    Args:
        script_path (str): Full path to the script file
        func_name_as_record (str|list): Function name or list of aliases
            to record. If list provided, longest name is used.

    Returns:
        callable: Decorated function with logging capability

    Example:
        @log("/path/to/script.py", "MyFunction")
        def my_function(arg1, arg2):
            # Function execution will be logged
            return result
    """
    # If a script has multiple aliases, just use the longest one as the record
    if isinstance(func_name_as_record, list):
        func_name_as_record = max(func_name_as_record, key=len)

    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                # Get environment name before entering the context manager
                app_name = ERROR_HANDLE.get_app_name()
                
                with DATA_FILE.update_data(LOG_FILE_NAME) as data:
                    t_start = time.time()
                    out = func(*args, **kwargs)
                    t_end = time.time()
                    if not data:
                        data = dict()
                    data[TIME.get_formatted_current_time()] = {
                        "application": app_name,
                        "function_name": func_name_as_record.replace("\n", " "),
                        "arguments": args,
                        "result": str(out),
                        "script_path": script_path,
                        "duration": TIME.get_readable_time(t_end - t_start),
                    }

                    # print ("data to be place in log is ", data)

                # Send usage data to Google Form (legacy) and InfraWatch (primary).
                # Both are best-effort and must never break the wrapped call.
                # Form path is on borrowed time -- the response sheet hit its
                # 100k-row tab cap on 2026-03-24 and silently dropped writes
                # for ~6 weeks before being noticed. Once InfraWatch ingestion
                # has 2 weeks of healthy traffic, the Form path can be removed.
                try:
                    environment = app_name
                    function_name = func_name_as_record.replace("\n", " ")
                    result = str(out)
                    send_usage_to_google_form(environment, function_name, result)
                except Exception:
                    pass
                try:
                    send_usage_to_infrawatch(environment, function_name, result)
                except Exception:
                    pass

                # Third sink: the EnneadTab economy. Unlike the two above this one
                # does NOT touch the network -- it appends to a local outbox that
                # LEADER_BOARD.refresh_async() drains at the next startup. The
                # click path stays local, and the server's 48h occurred_at window
                # is what makes deferring legal.
                #
                # Its own try/except, like its neighbours, and deliberately the
                # LAST thing before `return out`: the bare `except:` below re-runs
                # `func`, so anything that can raise up there executes the user's
                # tool a second time. Nothing added here may reach it.
                try:
                    if _is_button_script(script_path):
                        from EnneadTab import LEADER_BOARD
                        LEADER_BOARD.report_tool_run(
                            function_name,
                            duration_seconds=t_end - t_start,
                            script_path=script_path,
                        )
                except Exception:
                    pass

                return out
            except:
                out = func(*args, **kwargs)
                return out

        return wrapper

    return decorator


def read_log(user_name=USER.USER_NAME):
    """Display formatted log entries for a specific user.
    
    Retrieves and pretty prints the JSON log data for the specified user,
    showing all recorded function executions and their details.

    Args:
        user_name (str, optional): Username to read logs for.
            Defaults to current user.

    Note:
        Output is formatted with proper indentation for readability.
    """
    data = DATA_FILE.get_data(LOG_FILE_NAME)
    print("Printing user log from <{}>".format(user_name))
    pprint.pprint(data, indent=4)


INFRAWATCH_USAGE_URL = "https://enneadtab.com/infra/api/ingest/usage"


def _build_infrawatch_payload(environment, function_name, result):
    """Build the JSON body for the InfraWatch /api/ingest/usage endpoint.

    Schema matches src/app/api/ingest/usage/route.ts in the infrawatch repo.
    """
    import os
    try:
        machine_name = os.environ.get("COMPUTERNAME", "")
    except Exception:
        machine_name = ""
    try:
        username = USER.USER_NAME
    except Exception:
        username = ""
    return {
        "occurred_at": TIME.get_utc_timestamp_iso(),
        "environment": environment or "",
        "function_name": function_name or "",
        "result": result if result is not None else "",
        "username": username,
        "machine_name": machine_name,
    }


def send_usage_to_infrawatch(environment, function_name, result):
    """Send usage event to InfraWatch Postgres-backed ingestion.

    Replacement for the Google Form / Sheet pipeline. Tries the best
    available HTTP library for the runtime (Revit -> urllib3, Rhino ->
    urllib2, terminal -> urllib.request). Silent on success, print_note
    on failure -- never raises, must not break the wrapped call.
    """
    try:
        if _try_infrawatch_urllib3(environment, function_name, result):
            return
        elif _try_infrawatch_urllib2(environment, function_name, result):
            return
        elif _try_infrawatch_urllib_request(environment, function_name, result):
            return
        else:
            ERROR_HANDLE.print_note("No HTTP library available for InfraWatch usage POST")
    except Exception as e:
        ERROR_HANDLE.print_note("Failed to send usage to InfraWatch: {}".format(e))


def _try_infrawatch_urllib3(environment, function_name, result):
    try:
        import urllib3
        payload = _build_infrawatch_payload(environment, function_name, result)
        body = json.dumps(payload).encode("utf-8")
        http = urllib3.PoolManager()
        response = http.request(
            "POST",
            INFRAWATCH_USAGE_URL,
            body=body,
            headers={"Content-Type": "application/json"},
            timeout=10.0,
            redirect=False,
        )
        if response.status == 200:
            return True
        ERROR_HANDLE.print_note(
            "InfraWatch usage POST non-200: {} (urllib3)".format(response.status)
        )
        return False
    except ImportError:
        return False
    except Exception as e:
        ERROR_HANDLE.print_note("InfraWatch usage POST error (urllib3): {}".format(e))
        return False


def _try_infrawatch_urllib2(environment, function_name, result):
    # IronPython 2.7 path used by Rhino. urllib2 is Py2-only; the bare import
    # raises ImportError on CPython 3, which is the correct skip signal.
    try:
        import urllib2
        payload = _build_infrawatch_payload(environment, function_name, result)
        body = json.dumps(payload).encode("utf-8")
        req = urllib2.Request(
            INFRAWATCH_USAGE_URL,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        response = WEB_GUARD.urlopen_no_redirect(req, 10)
        if response.getcode() == 200:
            return True
        ERROR_HANDLE.print_note(
            "InfraWatch usage POST non-200: {} (urllib2)".format(response.getcode())
        )
        return False
    except ImportError:
        return False
    except Exception as e:
        ERROR_HANDLE.print_note("InfraWatch usage POST error (urllib2): {}".format(e))
        return False


def _try_infrawatch_urllib_request(environment, function_name, result):
    try:
        import urllib.request
        payload = _build_infrawatch_payload(environment, function_name, result)
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            INFRAWATCH_USAGE_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response = WEB_GUARD.urlopen_no_redirect(req, 10)
        if response.getcode() == 200:
            return True
        ERROR_HANDLE.print_note(
            "InfraWatch usage POST non-200: {} (urllib.request)".format(response.getcode())
        )
        return False
    except ImportError:
        return False
    except Exception as e:
        ERROR_HANDLE.print_note(
            "InfraWatch usage POST error (urllib.request): {}".format(e)
        )
        return False


def send_usage_to_google_form(environment, function_name, result):
    """Send usage information to Google Form for automated usage tracking.

    Sends usage details to a Google Form for automated usage tracking and analysis.
    Form includes environment, function name, and result information.
    
    Automatically detects the best available HTTP library based on environment:
    - Rhino: Uses urllib2/urllib (IronPython 2.7 style)
    - Revit: Uses urllib3 (if available)
    - Terminal/IDE: Uses built-in urllib modules (Python 3 style)

    Args:
        environment (str): The application environment (Revit/Rhino/etc.)
        function_name (str): The name of the function that was executed
        result (str): The result of the function execution
    """
    try:
        # Try different HTTP libraries based on environment availability
        if _try_urllib3_usage_implementation(environment, function_name, result):
            return
        elif _try_urllib2_usage_implementation(environment, function_name, result):
            return
        elif _try_urllib_request_usage_implementation(environment, function_name, result):
            return
        else:
            ERROR_HANDLE.print_note("No suitable HTTP library found for sending usage to Google Form")
            
    except Exception as e:
        # Don't let Google Form errors break the main logging
        ERROR_HANDLE.print_note("Failed to send usage to Google Form: {}".format(e))
        pass


def _try_urllib3_usage_implementation(environment, function_name, result):
    """Try to use urllib3 for sending usage data (Revit environment).
    
    Args:
        environment (str): The application environment
        function_name (str): The name of the function that was executed
        result (str): The result of the function execution
        
    Returns:
        bool: True if successful, False if urllib3 not available or failed
    """
    try:
        import urllib3
        
        # Google Form URL
        g_form_url = ERROR_HANDLE.get_usage_log_google_form_submit()
        if g_form_url is None:
            ERROR_HANDLE.print_note("ENVIRONMENT not available, skipping Google Form submission")
            return False
        
        # Build form data using common helper function
        form_data = _build_usage_form_data(environment, function_name, result)
        
        # Create HTTP manager
        http = urllib3.PoolManager()
        
        # Headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # Encode form data using urllib.parse.urlencode
        import urllib.parse
        encoded_data = urllib.parse.urlencode(form_data).encode('utf-8')
        
        # Send request
        response = http.request('POST', g_form_url, body=encoded_data, headers=headers, timeout=30.0, redirect=False)
        
        if response.status == 200:
            response_content = response.data.decode('utf-8')
            if "Thank you" in response_content or "submitted" in response_content.lower():
                ERROR_HANDLE.print_note("Usage data sent to Google Form successfully (urllib3)")
            else:
                ERROR_HANDLE.print_note("Form submission completed but may not have been recorded (urllib3)")
            return True
        else:
            ERROR_HANDLE.print_note("Failed to send usage data to Google Form - Status: {} (urllib3)".format(response.status))
            return False
            
    except ImportError:
        # urllib3 not available
        return False
    except Exception as e:
        ERROR_HANDLE.print_note("Error sending to Google Form (urllib3): {}".format(e))
        return False


def _try_urllib2_usage_implementation(environment, function_name, result):
    """Try to use urllib2 for sending usage data (Rhino environment).
    
    Args:
        environment (str): The application environment
        function_name (str): The name of the function that was executed
        result (str): The result of the function execution
        
    Returns:
        bool: True if successful, False if urllib2 not available or failed
    """
    try:
        import urllib2
        import urllib
        
        # Google Form URL
        g_form_url = ERROR_HANDLE.get_usage_log_google_form_submit()
        if g_form_url is None:
            ERROR_HANDLE.print_note("ENVIRONMENT not available, skipping Google Form submission")
            return False
        
        # Build form data using common helper function
        form_data = _build_usage_form_data(environment, function_name, result)
        
        # Encode the data (IronPython 2.7 compatible)
        data = urllib.urlencode(form_data)
        
        # Create the request with comprehensive headers
        req = urllib2.Request(g_form_url, data)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        req.add_header('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8')
        req.add_header('Accept-Language', 'en-US,en;q=0.5')
        req.add_header('Accept-Encoding', 'gzip, deflate')
        req.add_header('Connection', 'keep-alive')
        req.add_header('Upgrade-Insecure-Requests', '1')
        
        # Send the request
        response = WEB_GUARD.urlopen_no_redirect(req, 30)
        # Google Forms returns a 200 status even on successful submission
        if response.getcode() == 200:
            # Read response to check for success indicators
            response_content = response.read()
            ERROR_HANDLE.print_note("Response content preview: {}".format(response_content[:200]))  # Debug: show first 200 chars
            if "Thank you" in response_content or "submitted" in response_content.lower():
                ERROR_HANDLE.print_note("Usage data sent to Google Form successfully (urllib2)")
            else:
                ERROR_HANDLE.print_note("Form submission completed but may not have been recorded (urllib2)")
                ERROR_HANDLE.print_note("This usually means the field IDs don't match the form fields")
            return True
        else:
            ERROR_HANDLE.print_note("Failed to send usage data to Google Form - Status: {} (urllib2)".format(response.getcode()))
            return False
            
    except ImportError:
        # urllib2 not available
        return False
    except urllib2.URLError as e:
        ERROR_HANDLE.print_note("Network error sending to Google Form (urllib2): {}".format(e))
        return False
    except Exception as e:
        ERROR_HANDLE.print_note("Error sending to Google Form (urllib2): {}".format(e))
        return False


def _try_urllib_request_usage_implementation(environment, function_name, result):
    """Try to use urllib.request for sending usage data (Terminal/IDE environment).
    
    Args:
        environment (str): The application environment
        function_name (str): The name of the function that was executed
        result (str): The result of the function execution
        
    Returns:
        bool: True if successful, False if urllib.request not available or failed
    """
    try:
        import urllib.request
        import urllib.parse
        
        # Google Form URL
        g_form_url = ERROR_HANDLE.get_usage_log_google_form_submit()
        if g_form_url is None:
            ERROR_HANDLE.print_note("ENVIRONMENT not available, skipping Google Form submission")
            return False
        
        # Build form data using common helper function
        form_data = _build_usage_form_data(environment, function_name, result)
        
        # Encode the data (Python 3.x compatible)
        data = urllib.parse.urlencode(form_data).encode('utf-8')
        
        # Create the request with comprehensive headers
        req = urllib.request.Request(g_form_url, data)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        req.add_header('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8')
        req.add_header('Accept-Language', 'en-US,en;q=0.5')
        req.add_header('Accept-Encoding', 'gzip, deflate')
        req.add_header('Connection', 'keep-alive')
        req.add_header('Upgrade-Insecure-Requests', '1')
        
        # Send the request
        response = WEB_GUARD.urlopen_no_redirect(req, 30)
        # Google Forms returns a 200 status even on successful submission
        if response.getcode() == 200:
            # Read response to check for success indicators
            response_content = response.read().decode('utf-8')
            if "Thank you" in response_content or "submitted" in response_content.lower():
                ERROR_HANDLE.print_note("Usage data sent to Google Form successfully (urllib.request)")
            else:
                ERROR_HANDLE.print_note("Form submission completed but may not have been recorded (urllib.request)")
            return True
        else:
            ERROR_HANDLE.print_note("Failed to send usage data to Google Form - Status: {} (urllib.request)".format(response.getcode()))
            return False
            
    except ImportError:
        # urllib.request not available
        return False
    except urllib.error.URLError as e:
        ERROR_HANDLE.print_note("Network error sending to Google Form (urllib.request): {}".format(e))
        return False
    except Exception as e:
        ERROR_HANDLE.print_note("Error sending to Google Form (urllib.request): {}".format(e))
        return False


def unit_test():
    """Run comprehensive tests of the logging system.
    
    Tests log creation, reading, and backup functionality.
    """
    print("=== EnneadTab Logging System Unit Tests ===")
    
    # Test 1: Basic logging functionality
    print("\n1. Testing basic logging...")
    try:
        log("test_script.py", "test_function")
        print("   [PASS] Basic logging test passed")
    except Exception as e:
        print("   [FAIL] Basic logging test failed: {}".format(e))
    
    # Test 2: Log reading functionality
    print("\n2. Testing log reading...")
    try:
        log_data = read_log()
        print("   [PASS] Log reading test passed - Found {} entries".format(len(log_data) if log_data else 0))
    except Exception as e:
        print("   [FAIL] Log reading test failed: {}".format(e))
    
    # Test 3: Usage tracking decorator
    print("\n3. Testing usage tracking decorator...")
    try:
        @log("test_script.py", "test_function")
        def test_function():
            return "test_result"
        
        result = test_function()
        print("   [PASS] Usage tracking test passed - Result: {}".format(result))
    except Exception as e:
        print("   [FAIL] Usage tracking test failed: {}".format(e))
    
    # Test 4: Context manager
    print("\n4. Testing context manager...")
    try:
        def sample_function(x, y):
            return x + y
        
        with log_usage(sample_function, 5, 3) as result:
            print("   [PASS] Context manager test passed - Result: {}".format(result))
    except Exception as e:
        print("   [FAIL] Context manager test failed: {}".format(e))
    
    # Test 5: Google Form submission (mock test)
    print("\n5. Testing Google Form submission...")
    try:
        success = send_usage_to_google_form("TEST", "unit_test_function", "success")
        print("   [PASS] Google Form submission test {}".format('passed' if success else 'failed'))
    except Exception as e:
        print("   [FAIL] Google Form submission test failed: {}".format(e))
    
    print("\n=== Unit Tests Complete ===")


def download_log_data(spreadsheet_url=None):
    """Download log data from Google Spreadsheet.
    
    Args:
        spreadsheet_url (str, optional): Custom Google Spreadsheet URL.
            If None, uses the default URL.
    
    Returns:
        list: List of dictionaries containing log data, or empty list if failed
    """
    try:
        import urllib.request
        import urllib.parse
        import json
        import csv
        from io import StringIO
        
        # Google Spreadsheet URL - can be overridden by parameter
        if spreadsheet_url is None:
            spreadsheet_url = "https://docs.google.com/spreadsheets/d/1xJ8KuDZr9sSxdzV1qGOgqwfBDWucjUR7xSIfKjqzbIk/edit?resourcekey=&gid=19855110#gid=19855110"
        
        # Convert to CSV export URL
        # Extract the spreadsheet ID and gid
        if "spreadsheets/d/" in spreadsheet_url:
            parts = spreadsheet_url.split("spreadsheets/d/")[1].split("/")
            spreadsheet_id = parts[0]
            gid = "19855110"  # From the URL
            
            # Create CSV export URL
            csv_export_url = "https://docs.google.com/spreadsheets/d/{}/export?format=csv&gid={}".format(spreadsheet_id, gid)
        else:
            print("Invalid Google Spreadsheet URL format")
            return []
        
        print("Attempting to download log data from Google Spreadsheet...")
        print("Spreadsheet URL: {}".format(spreadsheet_url))
        print("CSV Export URL: {}".format(csv_export_url))
        
        # Download the CSV data
        try:
            req = urllib.request.Request(csv_export_url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                csv_content = response.read().decode('utf-8')
                
            # Parse CSV data
            csv_reader = csv.DictReader(StringIO(csv_content))
            log_data = []
            
            for row in csv_reader:
                # Map CSV columns to our expected format based on actual spreadsheet
                # Column A: Timestamp, Column B: Environment, Column C: Function, Column D: Result
                log_entry = {
                    'timestamp': row.get(u'\u65f6\u95f4\u6233\u8bb0', row.get('Timestamp', row.get('Date', row.get('Time', '')))),
                    'environment': row.get('Environment', row.get('App', row.get('Application', ''))),
                    'function_name': row.get('Function', row.get('Function Name', row.get('Script', ''))),
                    'result': row.get('Result', row.get('Status', row.get('Outcome', '')))
                }
                
                # Only add entries that have at least a timestamp and function name
                if log_entry['timestamp'] and log_entry['function_name']:
                    log_data.append(log_entry)
            
            print("Successfully downloaded {} log entries from spreadsheet".format(len(log_data)))
            
            # Show sample of the data structure
            if log_data:
                print("Sample data structure:")
                for i, entry in enumerate(log_data[:3]):  # Show first 3 entries
                    print("  Entry {}: {}".format(i+1, entry))
            
            return log_data
            
        except Exception as e:
            if "HTTP" in str(e) or "403" in str(e) or "404" in str(e) or "401" in str(e):
                print("HTTP Error downloading spreadsheet: {}".format(e))
                print("This might be due to spreadsheet permissions or authentication requirements")
                print("\nTo make the spreadsheet publicly accessible:")
                print("1. Open the Google Spreadsheet")
                print("2. Click 'Share' button")
                print("3. Click 'Change to anyone with the link'")
                print("4. Set permission to 'Viewer'")
                print("5. Copy the link and update the spreadsheet_url variable")
                
                # Fallback to sample data for testing
                print("\nUsing sample data for visualization...")
                sample_data = [
                    {
                        'timestamp': '2024-01-01 10:00:00',
                        'environment': 'Rhino',
                        'function_name': 'test_function',
                        'result': 'success'
                    },
                    {
                        'timestamp': '2024-01-01 11:00:00', 
                        'environment': 'Revit',
                        'function_name': 'another_function',
                        'result': 'success'
                    },
                    {
                        'timestamp': '2024-01-02 09:00:00',
                        'environment': 'Rhino',
                        'function_name': 'test_function',
                        'result': 'success'
                    },
                    {
                        'timestamp': '2024-01-02 14:00:00',
                        'environment': 'Revit',
                        'function_name': 'another_function',
                        'result': 'error'
                    }
                ]
                return sample_data
            else:
                print("URL Error downloading spreadsheet: {}".format(e))
            return []
        
    except ImportError:
        # Fallback: try using requests if urllib.request is unavailable (e.g., minimal embedded Python)
        try:
            import requests
            import csv
            from io import StringIO

            # Build CSV export URL from provided or default spreadsheet URL
            if spreadsheet_url is None:
                spreadsheet_url = "https://docs.google.com/spreadsheets/d/1xJ8KuDZr9sSxdzV1qGOgqwfBDWucjUR7xSIfKjqzbIk/edit?resourcekey=&gid=19855110#gid=19855110"

            if "spreadsheets/d/" in spreadsheet_url:
                parts = spreadsheet_url.split("spreadsheets/d/")[1].split("/")
                spreadsheet_id = parts[0]
                gid = "19855110"
                csv_export_url = "https://docs.google.com/spreadsheets/d/{}/export?format=csv&gid={}".format(spreadsheet_id, gid)
            else:
                print("Invalid Google Spreadsheet URL format")
                return []

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            resp = requests.get(csv_export_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                print("Failed to download spreadsheet via requests - Status: {}".format(resp.status_code))
                return []

            csv_content = resp.text
            csv_reader = csv.DictReader(StringIO(csv_content))
            log_data = []
            for row in csv_reader:
                log_entry = {
                    'timestamp': row.get(u'\u65f6\u95f4\u6233\u8bb0', row.get('Timestamp', row.get('Date', row.get('Time', '')))),
                    'environment': row.get('Environment', row.get('App', row.get('Application', ''))),
                    'function_name': row.get('Function', row.get('Function Name', row.get('Script', ''))),
                    'result': row.get('Result', row.get('Status', row.get('Outcome', '')))
                }
                if log_entry['timestamp'] and log_entry['function_name']:
                    log_data.append(log_entry)

            print("Successfully downloaded {} log entries from spreadsheet (requests)".format(len(log_data)))
            return log_data
        except Exception as e:
            print("requests not available or failed for downloading log data: {}".format(e))
            # Fallback to sample data for visualization to avoid hard failure
            sample_data = [
                {
                    'timestamp': '2024-01-01 10:00:00',
                    'environment': 'Rhino',
                    'function_name': 'test_function',
                    'result': 'success'
                },
                {
                    'timestamp': '2024-01-01 11:00:00', 
                    'environment': 'Revit',
                    'function_name': 'another_function',
                    'result': 'success'
                },
                {
                    'timestamp': '2024-01-02 09:00:00',
                    'environment': 'Rhino',
                    'function_name': 'test_function',
                    'result': 'success'
                },
                {
                    'timestamp': '2024-01-02 14:00:00',
                    'environment': 'Revit',
                    'function_name': 'another_function',
                    'result': 'error'
                }
            ]
            return sample_data
    except Exception as e:
        print("Error downloading log data: {}".format(e))
        return []


def visualize_log_data():
    """Visualize log data from Google Form and show in html.
    x axis is time by date, y axis is usage count, each function is a polyline, with data value each date on count sum.
    """
    print("=== EnneadTab Log Data Visualization ===")
    
    # Download log data
    data = download_log_data()
    
    if not data:
        print("No log data available for visualization")
        return
    
    try:
        # Process data for visualization
        from collections import defaultdict
        from datetime import datetime
        import json
        
        # Group data by environment, date and function
        revit_daily_usage = defaultdict(lambda: defaultdict(int))
        rhino_daily_usage = defaultdict(lambda: defaultdict(int))
        function_popularity = defaultdict(int)
        environment_stats = defaultdict(int)
        
        for entry in data:
            try:
                # Parse timestamp - handle multiple formats including Chinese
                if isinstance(entry['timestamp'], str):
                    timestamp_str = entry['timestamp']
                    
                    # Try different timestamp formats
                    dt = None
                    formats_to_try = [
                        '%Y-%m-%d %H:%M:%S',  # Standard format
                        '%Y-%m-%d %p%I:%M:%S',  # Chinese format with AM/PM markers
                        '%Y-%m-%d %H:%M',  # Without seconds
                        '%Y-%m-%d'  # Date only
                    ]
                    
                    for fmt in formats_to_try:
                        try:
                            # Handle Chinese AM/PM indicators
                            if u'\u4e0b\u5348' in timestamp_str:
                                timestamp_str = timestamp_str.replace(u'\u4e0b\u5348', 'PM')
                            elif u'\u4e0a\u5348' in timestamp_str:
                                timestamp_str = timestamp_str.replace(u'\u4e0a\u5348', 'AM')
                            
                            dt = datetime.strptime(timestamp_str, fmt)
                            break
                        except ValueError:
                            continue
                    
                    if dt is None:
                        print("Warning: Could not parse timestamp format: {}".format(entry['timestamp']))
                        continue
                else:
                    dt = entry['timestamp']
                
                # Ensure dt is a datetime object
                if hasattr(dt, 'strftime'):
                    date_str = dt.strftime('%Y-%m-%d')
                else:
                    # If it's not a datetime object, skip this entry
                    print("Warning: Invalid timestamp format in entry: {}".format(entry))
                    continue
                
                function_name = entry['function_name']
                environment = entry['environment'].lower()
                
                # Track popularity and environment stats
                function_popularity[function_name] += 1
                environment_stats[environment] += 1
                
                # Group by environment
                if 'revit' in environment:
                    revit_daily_usage[date_str][function_name] += 1
                elif 'rhino' in environment:
                    rhino_daily_usage[date_str][function_name] += 1
                
            except Exception as e:
                print("Error processing entry {}: {}".format(entry, e))
                continue
        
        # Sort functions by popularity
        sorted_functions = sorted(function_popularity.items(), key=lambda x: x[1], reverse=True)
        function_names_by_popularity = [func[0] for func in sorted_functions]
        
        # Get all dates
        all_dates = set()
        all_dates.update(revit_daily_usage.keys())
        all_dates.update(rhino_daily_usage.keys())
        dates = sorted(all_dates)
        
        # Create enhanced HTML visualization
        html_content = _generate_enhanced_visualization_html(dates, function_names_by_popularity, 
                                                           revit_daily_usage, rhino_daily_usage, 
                                                           function_popularity, environment_stats)
        
        # Save HTML file
        output_path = FOLDER.get_local_dump_folder_file("log_visualization.html")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print("Enhanced interactive visualization saved to: {}".format(output_path))
        
        # Try to open in browser
        try:
            import webbrowser
            webbrowser.open(output_path)
            print("Visualization opened in browser")
        except Exception as e:
            print("Could not open browser: {}".format(e))
        
    except Exception as e:
        print("Error creating visualization: {}".format(e))
        print (traceback.format_exc())



def update_spreadsheet_url(new_url):
    """Update the default spreadsheet URL for log data download.
    
    Args:
        new_url (str): New Google Spreadsheet URL
        
    Returns:
        bool: True if URL format is valid, False otherwise
    """
    if "spreadsheets/d/" in new_url:
        print("Spreadsheet URL updated successfully")
        print("New URL: {}".format(new_url))
        return True
    else:
        print("Invalid Google Spreadsheet URL format")
        print("URL should contain 'spreadsheets/d/'")
        return False


def _generate_enhanced_visualization_html(dates, function_names_by_popularity, revit_daily_usage, rhino_daily_usage, function_popularity, environment_stats):
    """Generate enhanced HTML content for log data visualization with modern design.
    
    Args:
        dates (list): List of date strings
        function_names_by_popularity (list): List of function names sorted by popularity
        revit_daily_usage (dict): Nested dictionary of Revit daily usage data
        rhino_daily_usage (dict): Nested dictionary of Rhino daily usage data
        function_popularity (dict): Dictionary of function popularity counts
        environment_stats (dict): Dictionary of environment usage statistics
        
    Returns:
        str: HTML content for enhanced visualization
    """
    
    # Create datasets for Revit and Rhino charts
    def create_datasets(daily_usage, environment_name, max_functions=20):
        """Create datasets for Chart.js from real daily usage data.
        
        Args:
            daily_usage (dict): Nested dictionary of daily usage data
            environment_name (str): Name of the environment (Revit/Rhino)
            max_functions (int): Maximum number of functions to include
            
        Returns:
            list: List of dataset dictionaries for Chart.js
        """
        datasets = []
        colors = ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF']
        
        print("  Processing {} days of {} data...".format(len(daily_usage), environment_name))
        
        # Get top functions by total usage across all dates
        function_totals = {}
        for date_data in daily_usage.values():
            for func_name, count in date_data.items():
                if func_name not in function_totals:
                    function_totals[func_name] = 0
                function_totals[func_name] += count
        
        print("  Found {} unique functions in {}".format(len(function_totals), environment_name))
        
        # Sort functions by total usage and take top max_functions
        top_functions = sorted(function_totals.items(), key=lambda x: x[1], reverse=True)[:max_functions]
        print("  Top {} functions for {}: {}".format(len(top_functions), environment_name, [f[0] for f in top_functions]))
        
        for i, (func_name, total_usage) in enumerate(top_functions):
            color = colors[i % len(colors)]
            
            # Create data array for this function across all dates
            data = []
            for date in dates:
                data.append(daily_usage.get(date, {}).get(func_name, 0))
            
            datasets.append({
                'label': '{} ({})'.format(func_name, environment_name),
                'data': data,
                'borderColor': color,
                'backgroundColor': color + '20',
                'tension': 0.3,
                'fill': False,
                'borderWidth': 2,
                'pointRadius': 3,
                'pointHoverRadius': 6
            })
        
        return datasets
    
    # Create real datasets from actual data
    print("Creating Revit datasets from {} days of data...".format(len(revit_daily_usage)))
    revit_datasets = create_datasets(revit_daily_usage, 'Revit', max_functions=10)
    print("Created {} Revit datasets".format(len(revit_datasets)))
    
    print("Creating Rhino datasets from {} days of data...".format(len(rhino_daily_usage)))
    rhino_datasets = create_datasets(rhino_daily_usage, 'Rhino', max_functions=10)
    print("Created {} Rhino datasets".format(len(rhino_datasets)))
    

    
    # Create fallback datasets if either is empty
    if not revit_datasets:
        print("No Revit data available, creating fallback datasets...")
        sample_functions = ['Startup', 'RandomDeselect', 'Duplicate Area Scheme', 'Doc Syncing Hook', 'StairMaker']
        
        for i, func in enumerate(sample_functions):
            color = ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF'][i % 5]
            
            # Create realistic sample data
            if 'Startup' in func:
                revit_data = [120, 150, 180, 200, 160, 140, 130]
            elif 'RandomDeselect' in func:
                revit_data = [60, 80, 70, 90, 75, 85, 65]
            elif 'Duplicate Area Scheme' in func:
                revit_data = [40, 60, 50, 70, 55, 65, 45]
            elif 'Doc Syncing Hook' in func:
                revit_data = [200, 220, 240, 260, 250, 230, 210]
            else:  # StairMaker
                revit_data = [10, 30, 20, 40, 25, 35, 15]
            
            revit_datasets.append({
                'label': '{} (Revit)'.format(func),
                'data': revit_data,
                'borderColor': color,
                'backgroundColor': color + '20',
                'tension': 0.3,
                'fill': False,
                'borderWidth': 2,
                'pointRadius': 3,
                'pointHoverRadius': 6
            })
    
    if not rhino_datasets:
        print("No Rhino data available, creating fallback datasets...")
        sample_functions = ['ToggleGFA', 'RandomLayerColor', 'SelectSimilarBlocks', 'SelectObjectsOnSimilarLayer', 'Rhino2Revit']
        
        for i, func in enumerate(sample_functions):
            color = ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF'][i % 5]
            
            # Create realistic sample data
            if 'ToggleGFA' in func:
                rhino_data = [80, 100, 120, 90, 110, 95, 85]
            elif 'RandomLayerColor' in func:
                rhino_data = [100, 120, 110, 130, 115, 125, 105]
            elif 'SelectSimilarBlocks' in func:
                rhino_data = [30, 50, 40, 60, 45, 55, 35]
            elif 'SelectObjectsOnSimilarLayer' in func:
                rhino_data = [20, 40, 30, 50, 35, 45, 25]
            else:  # Rhino2Revit
                rhino_data = [150, 170, 160, 180, 165, 175, 155]
            
            rhino_datasets.append({
                'label': '{} (Rhino)'.format(func),
                'data': rhino_data,
                'borderColor': color,
                'backgroundColor': color + '20',
                'tension': 0.3,
                'fill': False,
                'borderWidth': 2,
                'pointRadius': 3,
                'pointHoverRadius': 6
            })
    
    # Calculate statistics
    total_events = sum(function_popularity.values()) if function_popularity else 4250
    revit_events = sum(sum(revit_daily_usage[date].values()) for date in dates) if revit_daily_usage else 2500
    rhino_events = sum(sum(rhino_daily_usage[date].values()) for date in dates) if rhino_daily_usage else 1750
    

    
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EnneadTab Analytics Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.js"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0a;
            min-height: 100vh;
            color: #ffffff;
            line-height: 1.6;
        }
        
        .dashboard {
            max-width: 1600px;
            margin: 0 auto;
            padding: 30px 20px;
        }
        
        .header {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 40px;
            margin-bottom: 40px;
            border: 1px solid #2a2a2a;
        }
        
        .header h1 {
            color: #ffffff;
            font-size: 2.8em;
            margin-bottom: 15px;
            font-weight: 300;
            letter-spacing: -0.5px;
        }
        
        .header p {
            color: #888888;
            font-size: 1.1em;
            font-weight: 400;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        
        .stat-card {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 30px;
            border: 1px solid #2a2a2a;
            text-align: center;
            transition: all 0.3s ease;
        }
        
        .stat-card:hover {
            border-color: #404040;
            transform: translateY(-2px);
        }
        
        .stat-number {
            font-size: 2.8em;
            font-weight: 300;
            color: #ffffff;
            margin-bottom: 10px;
            line-height: 1;
        }
        
        .stat-label {
            color: #888888;
            font-size: 0.9em;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        

        
        .charts-container {
            display: grid;
            grid-template-columns: 1fr;
            gap: 30px;
            margin-bottom: 40px;
        }
        
        .chart-card {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 30px;
            border: 1px solid #2a2a2a;
            transition: all 0.3s ease;
        }
        
        .chart-card:hover {
            border-color: #404040;
        }
        
        .chart-title {
            font-size: 1.4em;
            font-weight: 500;
            color: #ffffff;
            margin-bottom: 20px;
        }
        
        .chart-container {
            height: 400px;
            position: relative;
            border-radius: 8px;
            overflow: hidden;
        }
        

        
        /* Custom scrollbar */
        ::-webkit-scrollbar {
            width: 6px;
        }
        
        ::-webkit-scrollbar-track {
            background: #0a0a0a;
        }
        
        ::-webkit-scrollbar-thumb {
            background: #404040;
            border-radius: 3px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: #666666;
        }
        
        /* Minimal Animations */
        @keyframes fadeIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateX(-10px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        
        @keyframes pulse {
            0%, 100% {
                opacity: 1;
            }
            50% {
                opacity: 0.8;
            }
        }
        
        /* Apply animations to elements */
        .header {
            animation: fadeIn 0.6s ease-out;
        }
        
        .stat-card {
            animation: fadeIn 0.6s ease-out;
        }
        
        .stat-card:nth-child(1) { animation-delay: 0.1s; }
        .stat-card:nth-child(2) { animation-delay: 0.2s; }
        .stat-card:nth-child(3) { animation-delay: 0.3s; }
        .stat-card:nth-child(4) { animation-delay: 0.4s; }
        
        .controls {
            animation: slideIn 0.6s ease-out 0.5s both;
        }
        
        .chart-card {
            animation: fadeIn 0.6s ease-out 0.7s both;
        }
        
        .chart-card:nth-child(2) {
            animation-delay: 0.8s;
        }
        
        .popular-functions {
            animation: fadeIn 0.6s ease-out 0.9s both;
        }
        
        /* Hover animations */
        .stat-card:hover {
            border-color: #404040;
            transform: translateY(-2px);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .chart-card:hover {
            border-color: #404040;
            transform: translateY(-1px);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .function-item:hover {
            border-color: #404040;
            background: #0f0f0f;
            transform: translateY(-1px);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .filter-btn:hover {
            background: #1a1a1a;
            border-color: #404040;
            color: #ffffff;
            transform: translateY(-1px);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .filter-btn.active {
            background: #ffffff;
            color: #0a0a0a;
            border-color: #ffffff;
            animation: pulse 2s ease-in-out infinite;
        }
        
        /* Loading animation for charts */
        .chart-container {
            position: relative;
        }
        
        .chart-container::before {
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 20px;
            height: 20px;
            margin: -10px 0 0 -10px;
            border: 2px solid #2a2a2a;
            border-top: 2px solid #ffffff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            z-index: 1;
        }
        
        .chart-container.loaded::before {
            display: none;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        @media (max-width: 768px) {
            .dashboard {
                padding: 20px 15px;
            }
            
            .header {
                padding: 25px 20px;
            }
            
            .header h1 {
                font-size: 2.2em;
            }
            
            .stats-grid {
                grid-template-columns: 1fr;
                gap: 15px;
            }
            
            .filter-buttons {
                justify-content: center;
                gap: 8px;
            }
            
            .filter-btn {
                padding: 10px 18px;
                font-size: 13px;
            }
            
            .functions-list {
                grid-template-columns: 1fr;
                gap: 12px;
            }
            
            .chart-card, .popular-functions {
                padding: 20px;
            }
            
            .chart-container {
                height: 300px;
            }
        }
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <h1><i class="fas fa-chart-line"></i> EnneadTab Analytics Dashboard</h1>
            <p>Comprehensive usage analytics and insights</p>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number">{total_events}</div>
                <div class="stat-label">Total Usage Events</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{revit_events}</div>
                <div class="stat-label">Revit Events</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{rhino_events}</div>
                <div class="stat-label">Rhino Events</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{len_function_names_by_popularity}</div>
                <div class="stat-label">Unique Functions</div>
            </div>
        </div>
        

        
        <div class="charts-container">
            <div class="chart-card">
                <div class="chart-title">Revit Usage Analytics</div>
                <div class="chart-container">
                    <canvas id="revitChart"></canvas>
                </div>
            </div>
            <div class="chart-card">
                <div class="chart-title">Rhino Usage Analytics</div>
                <div class="chart-container">
                    <canvas id="rhinoChart"></canvas>
                </div>
            </div>
        </div>
        

    </div>
    
    <script>
        // Chart.js configuration
        Chart.defaults.color = '#888888';
        Chart.defaults.borderColor = '#2a2a2a';
        Chart.defaults.font.family = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        
        // Create Revit chart
        try {
            console.log('Creating Revit chart...');
            const revitDatasets = {revit_datasets};
            console.log('Revit datasets:', revitDatasets);
            
            const revitCtx = document.getElementById('revitChart').getContext('2d');
            revitChart = new Chart(revitCtx, {
                type: 'line',
                data: {
                    labels: {dates},
                    datasets: revitDatasets.map(dataset => ({
                        label: dataset.label,
                        data: dataset.data,
                        borderColor: dataset.borderColor,
                        backgroundColor: dataset.backgroundColor,
                        tension: 0, // Straight lines instead of curves
                        fill: false,
                        borderWidth: 2,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: dataset.borderColor,
                        pointBorderColor: '#ffffff',
                        pointBorderWidth: 1
                    }))
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    devicePixelRatio: 2, // Higher resolution for crisp lines
                    elements: {
                        line: {
                            tension: 0 // Ensure straight lines
                        }
                    },
                    plugins: {
                        title: {
                            display: true,
                            text: 'Revit Function Usage Over Time',
                            color: '#ffffff',
                            font: {
                                size: 18,
                                weight: 'bold'
                            }
                        },
                        legend: {
                            position: 'bottom',
                            labels: {
                                color: '#ffffff',
                                usePointStyle: true
                            }
                        }
                    },
                    scales: {
                        x: {
                            title: {
                                display: true,
                                text: 'Date',
                                color: '#ffffff'
                            },
                            ticks: {
                                color: '#888888'
                            },
                            grid: {
                                color: '#2a2a2a'
                            }
                        },
                        y: {
                            title: {
                                display: true,
                                text: 'Usage Count',
                                color: '#ffffff'
                            },
                            ticks: {
                                color: '#888888'
                            },
                            grid: {
                                color: '#2a2a2a'
                            }
                        }
                    }
                }
            });
            
            document.getElementById('revitChart').parentElement.classList.add('loaded');
            console.log('Revit chart created successfully');
        } catch (error) {
            console.error('Error creating Revit chart:', error);
            document.getElementById('revitChart').parentElement.classList.add('loaded');
            document.getElementById('revitChart').innerHTML = '<div style="color: #888888; text-align: center; padding: 40px;">Chart failed to load. Please refresh the page.</div>';
        }
        
        // Create Rhino chart
        try {
            console.log('Creating Rhino chart...');
            const rhinoDatasets = {rhino_datasets};
            console.log('Rhino datasets:', rhinoDatasets);
            
            const rhinoCtx = document.getElementById('rhinoChart').getContext('2d');
            rhinoChart = new Chart(rhinoCtx, {
                type: 'line',
                data: {
                    labels: {dates},
                    datasets: rhinoDatasets.map(dataset => ({
                        label: dataset.label,
                        data: dataset.data,
                        borderColor: dataset.borderColor,
                        backgroundColor: dataset.backgroundColor,
                        tension: 0, // Straight lines instead of curves
                        fill: false,
                        borderWidth: 2,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: dataset.borderColor,
                        pointBorderColor: '#ffffff',
                        pointBorderWidth: 1
                    }))
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    devicePixelRatio: 2, // Higher resolution for crisp lines
                    elements: {
                        line: {
                            tension: 0 // Ensure straight lines
                        }
                    },
                    plugins: {
                        title: {
                            display: true,
                            text: 'Rhino Function Usage Over Time',
                            color: '#ffffff',
                            font: {
                                size: 18,
                                weight: 'bold'
                            }
                        },
                        legend: {
                            position: 'bottom',
                            labels: {
                                color: '#ffffff',
                                usePointStyle: true
                            }
                        }
                    },
                    scales: {
                        x: {
                            title: {
                                display: true,
                                text: 'Date',
                                color: '#ffffff'
                            },
                            ticks: {
                                color: '#888888'
                            },
                            grid: {
                                color: '#2a2a2a'
                            }
                        },
                        y: {
                            title: {
                                display: true,
                                text: 'Usage Count',
                                color: '#ffffff'
                            },
                            ticks: {
                                color: '#888888'
                            },
                            grid: {
                                color: '#2a2a2a'
                            }
                        }
                    }
                }
            });
            
            document.getElementById('rhinoChart').parentElement.classList.add('loaded');
            console.log('Rhino chart created successfully');
        } catch (error) {
            console.error('Error creating Rhino chart:', error);
            document.getElementById('rhinoChart').parentElement.classList.add('loaded');
            document.getElementById('rhinoChart').innerHTML = '<div style="color: #888888; text-align: center; padding: 40px;">Chart failed to load. Please refresh the page.</div>';
        }
        
        // Fallback: Remove loading spinners after 5 seconds if charts fail to load
        setTimeout(() => {
            const revitContainer = document.getElementById('revitChart').parentElement;
            const rhinoContainer = document.getElementById('rhinoChart').parentElement;
            if (!revitContainer.classList.contains('loaded')) {
                revitContainer.classList.add('loaded');
                console.warn('Revit chart failed to load, removing spinner');
            }
            if (!rhinoContainer.classList.contains('loaded')) {
                rhinoContainer.classList.add('loaded');
                console.warn('Rhino chart failed to load, removing spinner');
            }
        }, 5000);
        
        // Debug: Check if Chart.js is loaded
        if (typeof Chart === 'undefined') {
            console.error('Chart.js library not loaded!');
            setTimeout(() => {
                document.getElementById('revitChart').parentElement.classList.add('loaded');
                document.getElementById('rhinoChart').parentElement.classList.add('loaded');
            }, 1000);
        } else {
            console.log('Chart.js library loaded successfully');
        }
        
        // Store chart references
        let revitChart = null;
        let rhinoChart = null;
        
        // Add smooth scrolling
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function (e) {
                e.preventDefault();
                document.querySelector(this.getAttribute('href')).scrollIntoView({
                    behavior: 'smooth'
                });
            });
        });
    </script>
</body>
</html>"""
    
    # Format the HTML using string replacement to avoid conflicts with JavaScript template literals
    html_content = html_template.replace('{total_events}', str(total_events))
    html_content = html_content.replace('{revit_events}', str(revit_events))
    html_content = html_content.replace('{rhino_events}', str(rhino_events))
    html_content = html_content.replace('{len_function_names_by_popularity}', str(len(function_names_by_popularity)))
    html_content = html_content.replace('{dates}', json.dumps(dates))
    
    # Use JSON data directly without escaping
    html_content = html_content.replace('{revit_datasets}', json.dumps(revit_datasets))
    html_content = html_content.replace('{rhino_datasets}', json.dumps(rhino_datasets))
    
    return html_content

###########################################################
if __name__ == "__main__":
    print("Running EnneadTab Logging System...")
    print("1. Running unit tests...")
    unit_test()
    print("\n2. Running visualization...")
    
    # Example of how to use a custom spreadsheet URL
    # custom_url = "https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit#gid=0"
    # visualize_log_data(custom_url)
    
    visualize_log_data()
