#!/usr/bin/python
# -*- coding: utf-8 -*-


__doc__ = """Turn the EnneadTab AI bridge for this Revit session on or off.

While it is on, an AI assistant can look at the open model and carry out changes for you in
this session. The button shows the current state, so one click starts the bridge and the
next click shuts it down again.

Features:
- Only the Revit session you started it from is exposed
- The bridge stops as soon as you toggle it off or close Revit
- pyRevit Routes must be enabled first, and you are told if it is not"""
__title__ = "MCP\nServer"


import os
import subprocess

import proDUCKtion  # pyright: ignore
proDUCKtion.validify()
from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION, DATA_FILE
from pyrevit import script  # pyright: ignore


STATE_KEY = "mcp_server_state"
DETACHED_PROCESS = 0x00000008


def __selfinit__(script_cmp, ui_button_cmp, __rvt__):
    """Set initial icon state based on whether MCP Server is running."""
    state = DATA_FILE.get_data(STATE_KEY)
    if state and state.get("running") and state.get("pid"):
        try:
            import System  # pyright: ignore
            proc = System.Diagnostics.Process.GetProcessById(state["pid"])
            if not proc.HasExited:
                ui_button_cmp.set_icon(script_cmp.get_bundle_file("on.png"))
                return True
        except Exception:
            pass
    ui_button_cmp.set_icon(script_cmp.get_bundle_file("off.png"))
    return True


def find_python3():
    """Try to locate a Python 3 interpreter on this machine."""
    for cmd in ["python", "python3", "py"]:
        try:
            result = subprocess.check_output(
                [cmd, "--version"],
                stderr=subprocess.STDOUT
            )
            if "Python 3" in result.decode("utf-8", errors="replace"):
                return cmd
        except Exception:
            continue
    return None


def get_mcp_server_dir():
    """Walk up from this file to find Apps/_engine/mcp_server."""
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):
        candidate = os.path.join(current, "Apps", "_engine", "mcp_server")
        if os.path.isdir(candidate):
            return candidate
        current = os.path.dirname(current)
    return ""


def is_process_alive(pid):
    """Check whether a process with the given PID is still running.

    Uses .NET Process API when available (IronPython inside Revit) to avoid
    os.kill which can behave destructively on IronPython/Windows.
    """
    if pid is None:
        return False
    try:
        import System  # pyright: ignore
        proc = System.Diagnostics.Process.GetProcessById(pid)
        return not proc.HasExited
    except Exception:
        # .NET throws ArgumentException if PID doesn't exist
        return False


def ensure_pyrevit_routes():
    """Check that pyRevit Routes is running and return its port.

    Returns the active server port on success, or None on failure.
    pyRevit Routes port is dynamic (starts at 48884, increments if busy).

    IMPORTANT: We never call routes.activate_server() from a pushbutton —
    that can crash Revit. Routes must be started by pyRevit during its own
    startup. We only read the existing state here.
    """
    from pyrevit.userconfig import user_config  # pyright: ignore

    # Auto-enable Routes in config so it starts on next pyRevit load
    if not user_config.routes_server:
        user_config.routes_server = True
        user_config.save_changes()

    # Clean up stale serverinfo pickles from dead Revit processes
    _cleanup_stale_serverinfo()

    # Read port from the current Revit session's serverinfo pickle
    port = _get_current_routes_port()
    if not port:
        return None

    # Verify the port is open (TCP connect test).
    # Routes server returns errors on bare "/" so we can't use urllib2 —
    # just check that something is listening on the port.
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(("localhost", port))
        s.close()
        return port
    except Exception:
        return None


def _get_current_routes_port():
    """Find the Routes port for the current Revit process from serverinfo pickles.

    Each running Revit instance writes a serverinfo.pickle with its PID and
    assigned port. We match against our own PID to find our port.
    Falls back to checking any live Revit instance's port.
    """
    import re
    import glob

    appdata_dir = os.environ.get("APPDATA", "")
    if not appdata_dir:
        return None

    # Get current Revit process ID
    try:
        import System  # pyright: ignore
        current_pid = System.Diagnostics.Process.GetCurrentProcess().Id
    except Exception:
        current_pid = None

    pattern = os.path.join(appdata_dir, "pyRevit", "*", "*_serverinfo.pickle")
    candidates = []

    for filepath in glob.glob(pattern):
        basename = os.path.basename(filepath)
        match = re.search(r"_(\d+)_serverinfo\.pickle$", basename)
        if not match:
            continue
        pid = int(match.group(1))

        # Read port from pickle without importing pyrevit.routes
        port = _read_port_from_pickle(filepath)
        if port is None:
            continue

        # Exact PID match = this Revit instance's Routes server
        if current_pid and pid == current_pid:
            return port

        # Otherwise collect as fallback (if process is alive)
        if is_process_alive(pid):
            candidates.append(port)

    # Fallback: return the lowest live port (most likely 48884)
    if candidates:
        return min(candidates)
    return None


def _read_port_from_pickle(filepath):
    """Extract server_port from a serverinfo pickle without importing pyrevit.routes.

    The pickle contains a RoutesServerInfo object, but we can't unpickle it
    outside IronPython's full pyrevit context. Instead, read the raw pickle
    protocol 0 text format and extract the port integer.
    """
    try:
        with open(filepath, "rb") as f:
            data = f.read()
        # Pickle protocol 0 stores the port as:
        #   S'server_port'\np13\nI48884\n
        text = data.decode("latin-1")
        idx = text.find("server_port")
        if idx < 0:
            return None
        # Find the integer line after server_port
        # Format: ...server_port\npNN\nIPORT\n...
        rest = text[idx:]
        lines = rest.split("\n")
        for line in lines:
            if line.startswith("I") and line[1:].strip().isdigit():
                return int(line[1:].strip())
    except Exception:
        pass
    return None


def _cleanup_stale_serverinfo():
    """Remove serverinfo pickle files for Revit processes that are no longer running.

    pyRevit stores a serverinfo.pickle per Revit instance. If Revit crashes
    or closes without cleanup, stale files remain and cause the next instance
    to skip to a higher port number.
    """
    import re
    import glob

    appdata_dir = os.environ.get("APPDATA", "")
    if not appdata_dir:
        return

    pattern = os.path.join(appdata_dir, "pyRevit", "*", "*_serverinfo.pickle")
    for filepath in glob.glob(pattern):
        # Extract PID from filename: pyRevit_2025_19288_serverinfo.pickle
        basename = os.path.basename(filepath)
        match = re.search(r"_(\d+)_serverinfo\.pickle$", basename)
        if not match:
            continue
        pid = int(match.group(1))
        if not is_process_alive(pid):
            try:
                os.remove(filepath)
            except OSError:
                pass


def _auto_configure_claude(python_cmd, port, engine_dir):
    """Write MCP server config to Claude Desktop and Claude Code config files.

    Returns a status string describing what was configured.
    """
    import json

    mcp_entry = {
        "command": python_cmd,
        "args": ["-m", "mcp_server", "--app", "revit", "--port", str(port)],
        "cwd": engine_dir.replace("\\", "/")
    }

    configured = []

    # Claude Desktop: %APPDATA%/Claude/claude_desktop_config.json
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        desktop_config_path = os.path.join(appdata, "Claude", "claude_desktop_config.json")
        if _merge_mcp_config(desktop_config_path, "enneadtab-revit", mcp_entry):
            configured.append("Claude Desktop")

    # Claude Code: ~/.claude/settings.json (project-level .mcp.json)
    userprofile = os.environ.get("USERPROFILE", "")
    if userprofile:
        # Merge into .mcp.json in the engine dir for project-level config.
        # Never overwrite: the user may already have other MCP servers configured.
        mcp_json_path = os.path.join(os.path.dirname(engine_dir), ".mcp.json")
        if _merge_mcp_config(mcp_json_path, "enneadtab-revit", mcp_entry):
            configured.append("Claude Code (.mcp.json)")

    if configured:
        return "Auto-configured: {}".format(", ".join(configured))
    return "Config written. Open Claude to connect."


def _merge_mcp_config(config_path, server_name, server_config):
    """Merge an MCP server entry into an existing JSON config file.

    Creates the file and parent directory if they don't exist.
    Returns True on success, False on failure.
    """
    import json

    try:
        config_dir = os.path.dirname(config_path)
        if not os.path.isdir(config_dir):
            os.makedirs(config_dir)

        # Read existing config
        existing = {}
        if os.path.isfile(config_path):
            with open(config_path, "r") as f:
                existing = json.load(f)

        # Merge
        if "mcpServers" not in existing:
            existing["mcpServers"] = {}
        existing["mcpServers"][server_name] = server_config

        # Write back
        with open(config_path, "w") as f:
            json.dump(existing, f, indent=2)
        return True
    except Exception:
        return False


def get_state():
    """Load saved MCP server state."""
    data = DATA_FILE.get_data(STATE_KEY)
    if data is None:
        return {}
    return data


def set_state(data):
    """Persist MCP server state."""
    DATA_FILE.set_data(data, STATE_KEY)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def mcp_server():
    state = get_state()
    pid = state.get("pid")

    # If already running, stop it
    if pid and is_process_alive(pid):
        try:
            import System  # pyright: ignore
            proc = System.Diagnostics.Process.GetProcessById(pid)
            proc.Kill()
        except Exception:
            pass
        set_state({"pid": None, "running": False})
        script.toggle_icon(False)
        NOTIFICATION.messenger("MCP Server stopped.")
        return

    # Find Python 3
    python_cmd = find_python3()
    if not python_cmd:
        NOTIFICATION.messenger(
            "Python 3 is required for the MCP Server.\n"
            "Install from https://python.org"
        )
        return

    # Enable and verify pyRevit Routes
    routes_port = ensure_pyrevit_routes()
    if not routes_port:
        NOTIFICATION.messenger(
            "pyRevit Routes is not running.\n\n"
            "Routes has been enabled in config.\n"
            "Please reload pyRevit (right-click pyRevit tab > Reload)\n"
            "then click MCP Server again."
        )
        return

    # Launch the MCP server as a detached process
    mcp_dir = get_mcp_server_dir()
    if not mcp_dir:
        NOTIFICATION.messenger("MCP Server directory not found.")
        return

    engine_dir = os.path.dirname(mcp_dir)
    try:
        # Log file for debugging — detached processes can't use PIPE
        # (buffer fills and hangs the process)
        log_path = os.path.join(
            os.environ.get("USERPROFILE", ""),
            "Documents", "EnneadTab Ecosystem", "Dump",
            "mcp_server.log"
        )
        log_file = open(log_path, "w")
        proc = subprocess.Popen(
            [python_cmd, "-m", "mcp_server", "--app", "revit",
             "--port", str(routes_port), "--web"],
            cwd=engine_dir,
            creationflags=DETACHED_PROCESS,
            stdout=log_file,
            stderr=log_file
        )
        set_state({"pid": proc.pid, "running": True, "port": routes_port})
        script.toggle_icon(True)

        # Auto-configure Claude clients to use this MCP server
        claude_status = _auto_configure_claude(python_cmd, routes_port, engine_dir)

        # Open browser from the pushbutton (detached processes can't reliably do this)
        import webbrowser  # pyright: ignore
        webbrowser.open("http://localhost:5000")

        NOTIFICATION.messenger(
            "MCP Server is running.\n"
            "Browser opened to http://localhost:5000\n"
            "{}".format(claude_status)
        )
    except Exception as e:
        NOTIFICATION.messenger(
            "Failed to start MCP Server:\n{}".format(str(e))
        )


if __name__ == "__main__":
    mcp_server()
