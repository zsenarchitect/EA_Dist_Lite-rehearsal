#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AUTO RECONNECT - Network Drive Reconnection Tool

This script automatically attempts to reconnect network drives
that have timed out. It maps predefined network paths to drive
letters based on your organization's configuration.

Includes enhanced path validation to verify drives are truly accessible.
Compatible with IronPython 2.7 and Python 3.
Includes 10-second timeout for connection attempts.
Uses retry mechanism for more reliable connections.

PARAMETERS:
    None

RETURNS:
    Reconnected network drives or error messages

AUTHOR:     EnneadTab Team
"""

import sys
import os
import traceback
import time
import threading
import socket
import _Exe_Util

# Define the network drives to reconnect
NETWORK_DRIVES = [
    {"path": r"\\ad.ennead.com\dfs", "drive": "I:", "name": "NYSH-jobs"},
    {"path": r"\\ea\dfs", "drive": "J:", "name": "JOBS"},
    {"path": r"\\ad.ennead.com\dfs\Library", "drive": "L:", "name": "LIBRARY"}
]

# Maximum time to wait for a drive connection (in seconds)
CONNECTION_TIMEOUT = 10

# Maximum number of retry attempts
MAX_RETRIES = 2

# Delay between retries in seconds
RETRY_DELAY = 2

def is_ironpython():
    """Check if the script is running in IronPython."""
    return "IronPython" in sys.version

class TimeoutError(Exception):
    """Exception raised when a timeout occurs."""
    pass

def run_with_timeout(func, args=(), kwargs={}, timeout_duration=10):
    """Run a function with a timeout."""
    result = [None]
    error = [None]
    completed = [False]

    def target():
        try:
            result[0] = func(*args, **kwargs)
            completed[0] = True
        except Exception as e:
            error[0] = e

    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout_duration)

    if not completed[0]:
        return "Timeout after {} seconds".format(timeout_duration)
    
    if error[0]:
        return "Error: {}".format(str(error[0]))
    
    return result[0]

def is_host_reachable(host, port=445):
    """Check if a host is reachable on the network."""
    try:
        # Extract hostname from UNC path
        if host.startswith(r'\\'):
            host = host[2:]
        if '\\' in host:
            host = host.split('\\')[0]
        if '/' in host:
            host = host.split('/')[0]
            
        # Try to connect to SMB port (default for file sharing)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)  # 3 second timeout for connection
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

def execute_command(command):
    """Execute a system command."""
    if is_ironpython():
        # IronPython approach
        import clr # type: ignore
        from System.Diagnostics import Process # type: ignore
        
        process = Process()
        process.StartInfo.FileName = "cmd.exe"
        process.StartInfo.Arguments = "/c " + command
        process.StartInfo.UseShellExecute = False
        process.StartInfo.RedirectStandardOutput = True
        process.StartInfo.CreateNoWindow = True
        
        process.Start()
        output = process.StandardOutput.ReadToEnd()
        process.WaitForExit()
        return output
    else:
        # Python 3 approach
        import subprocess
        result = subprocess.run(
            command, 
            shell=True, 
            capture_output=True, 
            text=True
        )
        return result.stdout

def run_command(command, timeout=None):
    """Execute a command with an optional timeout."""
    if timeout is None:
        return execute_command(command)
    
    return run_with_timeout(execute_command, args=(command,), timeout_duration=timeout)

def is_drive_connected(drive_letter):
    """
    Check if a drive is currently connected and accessible.
    
    The function performs multiple validation checks:
    1. Verifies the drive path exists
    2. Attempts to access directory contents
    3. Uses a fallback method if primary check fails
    
    Args:
        drive_letter (str): The drive letter to check (e.g., 'L:')
        
    Returns:
        bool: True if the drive is connected and accessible, False otherwise
    """
    drive_root = drive_letter + "\\"
    try:
        # Primary check: Does drive path exist?
        if not os.path.exists(drive_root):
            return False
            
        # Secondary check: Can we list contents?
        try:
            os.listdir(drive_root)
            return True
        except (PermissionError, OSError):
            pass
            
        # Fallback check: Try alternative method
        try:
            # Check if any system-reported drives match our drive letter
            import subprocess
            result = subprocess.check_output("net use", shell=True).decode('utf-8', errors='ignore')
            return drive_letter.lower().rstrip(':') + ":" in result.lower()
        except:
            return False
    except:
        return False

def get_server_from_path(path):
    """Extract the server name from a network path."""
    try:
        # Handle network paths (UNC paths)
        if path.startswith('\\\\'):
            parts = path.split('\\')
            if len(parts) > 2:
                return parts[2]
        # Handle local drive paths that point to network locations
        elif ':' in path:
            # Local drive path, don't attempt to extract server
            return None
        return None
    except:
        return None

def reconnect_network_drive(drive_info):
    """Reconnect a specific network drive."""
    drive_letter = drive_info["drive"]
    network_path = drive_info["path"]
    drive_name = drive_info["name"]
    server = get_server_from_path(network_path)
    
    print("Checking {} ({})...".format(drive_name, drive_letter))
    
    if is_drive_connected(drive_letter):
        print("  {} is already connected.".format(drive_name))
        return True
    
    # For local drive paths (like "I:\Library"), we handle differently
    if ":" in network_path:
        print("  {} refers to a local path: {}".format(drive_name, network_path))
        if os.path.exists(network_path):
            # Local path exists, attempt to map it
            connect_command = 'subst {} "{}"'.format(drive_letter, network_path)
            try:
                result = run_command(connect_command, timeout=CONNECTION_TIMEOUT)
                if is_drive_connected(drive_letter):
                    print("  Successfully mapped {} to local path {}.".format(drive_letter, network_path))
                    return True
                else:
                    print("  Failed to map to local path: {}".format(network_path))
                    return False
            except Exception as e:
                print("  Error mapping to local path: {}".format(str(e)))
                return False
        else:
            print("  Local path does not exist: {}".format(network_path))
            return False
    
    # First check if the server is reachable
    if server and not is_host_reachable(server):
        print("  Server {} is not reachable on the network.".format(server))
        return False
    
    # Connection attempts with retry
    retry_count = 0
    while retry_count <= MAX_RETRIES:
        if retry_count > 0:
            print("  Retry attempt {} of {}...".format(retry_count, MAX_RETRIES))
            time.sleep(RETRY_DELAY)
            
        # Try different connection methods
        if retry_count == 0:
            # First try: Standard connection
            connect_command = 'net use {} {} /persistent:yes'.format(drive_letter, network_path)
        else:
            # Alternative methods for retries
            # Force reconnection by disconnecting first if drive exists but is not accessible
            if retry_count == 1:
                disconnect_cmd = 'net use {} /delete /y'.format(drive_letter)
                run_command(disconnect_cmd, timeout=5)
                time.sleep(1)
                
            # Try with different flags
            connect_command = 'net use {} {} /persistent:yes /Y'.format(drive_letter, network_path)
            
        print("  Attempting to connect {} (timeout: {}s)...".format(drive_name, CONNECTION_TIMEOUT))
        
        try:
            result = run_command(connect_command, timeout=CONNECTION_TIMEOUT)
            
            if "Timeout" in str(result):
                print("  Connection attempt timed out after {} seconds.".format(CONNECTION_TIMEOUT))
                retry_count += 1
                continue
            
            # Check if connection was successful
            if is_drive_connected(drive_letter):
                print("  Successfully reconnected {} ({}).".format(drive_name, drive_letter))
                return True
            else:
                print("  Connection attempt failed.")
                if "System error 67" in str(result):
                    print("  Network path not found. Server may be unavailable.")
                    return False  # Don't retry if the path doesn't exist
                elif "System error 1219" in str(result):
                    # Handle the case where an existing connection exists
                    print("  Conflicting connection exists. Attempting to resolve...")
                    resolve_cmd = 'net use {} /delete /y && net use {} {} /persistent:yes'.format(
                        drive_letter, drive_letter, network_path
                    )
                    resolve_result = run_command(resolve_cmd, timeout=CONNECTION_TIMEOUT)
                    if is_drive_connected(drive_letter):
                        print("  Successfully reconnected after resolving conflict.")
                        return True
                
                retry_count += 1
        except Exception as e:
            print("  Error connecting to {}: {}".format(drive_name, str(e)))
            retry_count += 1
    
    print("  Failed to reconnect {} after {} retry attempts.".format(drive_name, MAX_RETRIES))
    return False

def main():
    if not _Exe_Util.IS_DEVELOPER:
        return
    """Main function to reconnect all network drives."""
    print("EnneadTab Network Drive Auto-Reconnection Tool")
    print("-" * 50)
    
    success_count = 0
    
    for drive_info in NETWORK_DRIVES:
        try:
            if reconnect_network_drive(drive_info):
                success_count += 1
            print("")  # Add blank line between drive results for better readability
        except Exception as e:
            print("  Error processing {}: {}".format(drive_info["name"], str(e)))
            print("")
    
    print("-" * 50)
    print("Reconnection complete. {}/{} drives connected.".format(success_count, len(NETWORK_DRIVES)))

if __name__ == "__main__":

    try:
        main()
    except Exception as e:
        print("Error occurred during execution:")
        print(str(e))
        print(traceback.format_exc())
