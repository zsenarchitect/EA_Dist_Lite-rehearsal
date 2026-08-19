"""
EnneadTab for Revit — install/uninstall core logic.

Framework-agnostic business logic shared by the modern guided wizards
EnneadTab_For_Revit_Installer.py and EnneadTab_For_Revit_UnInstaller.py.
No Tk here — every user-facing message goes through a `log` callback so the
same code drives the wizard's progress pane AND a plain console.

IMPORTANT: this runs inside a *windowed* (--noconsole) PyInstaller exe, where
sys.stdout is None. Never call bare print() on a hot path — use self.log().
"""

from __future__ import annotations

import codecs
import configparser
import json
import os
import subprocess
import time
from datetime import datetime
from typing import Callable, Optional

import psutil

import _Exe_Util


def safe_print(msg: str) -> None:
    """print() that never raises when stdout is None (windowed exe)."""
    try:
        print(msg)
    except Exception:
        pass


class EnneadTabRevitInstallationManager:
    """Handle EnneadTab for Revit attach (install) / detach (uninstall)."""

    def __init__(
        self,
        is_installing: bool = True,
        log: Optional[Callable[[str], None]] = None,
    ):
        self.config_path = None
        self.userextensions_path = None
        self.start_time_iso = None
        self.is_installing = is_installing
        # every message the user should see flows through here
        self.log = log or safe_print

    # ------------------------------------------------------------------
    # host / prerequisite checks
    # ------------------------------------------------------------------
    def check_revit_running(self) -> bool:
        """True only if the Revit app itself (revit.exe) is running.

        Not a substring test — see the exact-match note below.
        """
        for process in psutil.process_iter(['pid', 'name']):
            try:
                name = (process.info.get('name') or '').lower()
            except Exception:
                continue
            # Exact match only. A substring 'revit' also catches
            # RevitAccelerator.exe — a background Autodesk service that runs
            # even when Revit is CLOSED — plus RevitWorksharingMonitor etc.,
            # producing a false "Revit is running, please close it" warning.
            if name == 'revit.exe':
                return True
        return False

    def get_pyrevit_config_path(self) -> str:
        """Absolute path to pyRevit_config.ini (cached)."""
        if self.config_path is not None:
            return self.config_path

        user_profile = os.path.expanduser("~")
        default_path = os.path.join(
            user_profile, 'AppData', 'Roaming', 'pyRevit', 'pyRevit_config.ini'
        )
        program_data = os.getenv('PROGRAMDATA')
        program_data_path = (
            os.path.join(program_data, 'pyRevit', 'pyRevit_config.ini')
            if program_data else None
        )

        paths_checked = [default_path]
        if os.path.exists(default_path):
            self.log("Found pyRevit config: {}".format(default_path))
            self.config_path = default_path
            return self.config_path

        if program_data_path:
            paths_checked.append(program_data_path)
            if os.path.exists(program_data_path):
                self.log("Found pyRevit config (PROGRAMDATA): {}".format(program_data_path))
                self.config_path = program_data_path
                return self.config_path

        self.log("pyRevit config not found in: {}".format(paths_checked))
        self.config_path = default_path
        return self.config_path

    # ------------------------------------------------------------------
    # install-only: ensure pyRevit present + attach
    # ------------------------------------------------------------------
    def check_and_install_pyrevit(self) -> bool:
        """Install pyRevit from the shared DB if its config is missing."""
        pyrevit_config_path = self.get_pyrevit_config_path()
        if os.path.exists(pyrevit_config_path):
            self.log("pyRevit is already installed.")
            return True

        self.log("pyRevit not detected. Attempting to install...")

        installers_dir = os.path.join(_Exe_Util.DB_FOLDER, 'pyrevit-installers')
        installer_path = None
        latest_time = 0
        if os.path.exists(installers_dir):
            for file in os.listdir(installers_dir):
                if file.lower().endswith('.exe'):
                    file_path = os.path.join(installers_dir, file)
                    mod_time = os.path.getmtime(file_path)
                    if mod_time > latest_time:
                        latest_time = mod_time
                        installer_path = file_path

        if not installer_path or not os.path.exists(installer_path):
            self.log("Error: pyRevit installer not found in: {}".format(installers_dir))
            self.log("Connect the L drive, or install pyRevit manually, then retry.")
            return False

        try:
            self.log("Running pyRevit installer: {}".format(installer_path))
            result = subprocess.run(
                [installer_path], capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                self.log("pyRevit installer completed. Verifying...")
                time.sleep(5)
                if os.path.exists(pyrevit_config_path):
                    self.log("pyRevit installation verified.")
                    return True
                self.log("Warning: installer ran but config file not found.")
                return False
            self.log("pyRevit installer failed (code {}).".format(result.returncode))
            if result.stderr:
                self.log("Error: {}".format(result.stderr))
            return False
        except subprocess.TimeoutExpired:
            self.log("pyRevit installer timed out after 120 seconds.")
            return False
        except Exception as e:
            self.log("Error running pyRevit installer: {}".format(e))
            return False

    def attach_master_to_installed(self) -> bool:
        """Run 'pyrevit attach master default --installed' silently."""
        try:
            subprocess.run(
                ["pyrevit", "attach", "master", "default", "--installed"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                text=True,
            )
            return True
        except Exception as e:
            self.log("Error running 'pyrevit attach': {}".format(e))
            return False

    def find_enneadtab_revit_path(self) -> Optional[str]:
        """Locate the EnneadTab Revit extension folder (cached)."""
        if self.userextensions_path is not None:
            return self.userextensions_path

        self.log("Looking for EnneadTab OS...")
        potential_paths = [
            ("_revit", "Current"),
        ]
        for folder, desc in potential_paths:
            path = os.path.join(_Exe_Util.find_main_repo(), 'Apps', folder)
            if os.path.exists(path):
                self.userextensions_path = path
                self.log("Found {} path: {}".format(desc, path))
                return self.userextensions_path

        self.log("Error: could not find {} Revit folder.".format(_Exe_Util.PLUGIN_NAME))
        return None

    # ------------------------------------------------------------------
    # pyRevit config edits
    # ------------------------------------------------------------------
    def clear_pyrevit_userextensions(self, file_path) -> bool:
        """Detach: clear EnneadTab from pyRevit userextensions."""
        if not file_path or not os.path.exists(file_path):
            self.log("pyRevit config not found; nothing to detach.")
            return True

        config = configparser.ConfigParser()
        config.read(file_path)
        if 'core' not in config:
            config.add_section('core')
        config.set('core', 'userextensions', '[]')
        with codecs.open(file_path, 'w', encoding='utf-8') as configfile:
            config.write(configfile)

        self.log("{}-for-Revit has been detached from pyRevit.".format(_Exe_Util.PLUGIN_NAME))
        return True

    def update_pyrevit_config(self, file_path) -> bool:
        """Attach: register EnneadTab paths + color settings in pyRevit config."""
        if not self.is_installing:
            return self.clear_pyrevit_userextensions(file_path)

        config = configparser.ConfigParser()
        config.read(file_path)

        new_userextensions_path = self.find_enneadtab_revit_path()
        if not new_userextensions_path:
            return False

        if 'core' not in config:
            config.add_section('core')

        # json.dumps, NOT an f-string. pyRevit reads this back with json.loads;
        # the path must be JSON-encoded (backslashes escaped as \\, non-ASCII as
        # \uXXXX). An f-string writes a raw Windows path whose \U is not valid
        # JSON, so json.loads fails and pyRevit's Py2 string-escape fallback
        # raises UnicodeEncodeError on non-ASCII usernames — the extension path
        # is then never registered and every button dies at `import proDUCKtion`.
        config.set('core', 'userextensions', json.dumps([new_userextensions_path]))
        config.set('core', 'colorize_docs', 'true')

        if 'tabcoloring' not in config:
            config.add_section('tabcoloring')
        config.set('tabcoloring', 'sort_colorize_docs', 'true')
        config.set('tabcoloring', 'tabstyle_index', '3')
        config.set('tabcoloring', 'family_tabstyle_index', '8')

        with codecs.open(file_path, 'w', encoding='utf-8') as configfile:
            config.write(configfile)

        self.log("{}-for-Revit has been attached to pyRevit.".format(_Exe_Util.PLUGIN_NAME))
        self.log("Version: {}".format(new_userextensions_path))
        return True

    # ------------------------------------------------------------------
    # status file (monitored by other processes)
    # ------------------------------------------------------------------
    def _update_status(self, status: str, details: str, end_time: Optional[str] = None) -> None:
        payload = {
            "status": status,
            "details": details,
            "start_time": self.start_time_iso,
            "end_time": end_time,
        }
        logger = "revit_installer_status" if self.is_installing else "revit_uninstaller_status"
        try:
            _Exe_Util.set_data(payload, logger)
        except Exception as e:
            self.log("(status write skipped: {})".format(e))

    # ------------------------------------------------------------------
    # orchestrators
    # ------------------------------------------------------------------
    def run(self) -> bool:
        """Attach (install) or detach (uninstall). Returns True on success."""
        self.start_time_iso = datetime.now().isoformat()

        if not self.is_installing:
            return self._run_uninstall()
        return self._run_install()

    def _run_uninstall(self) -> bool:
        self._update_status("running", "Starting EnneadTab for Revit uninstaller")
        config_path = self.get_pyrevit_config_path()
        if not self.clear_pyrevit_userextensions(config_path):
            self._update_status(
                "failed", "pyRevit userextensions clear failed", datetime.now().isoformat()
            )
            return False
        self._update_status(
            "success",
            "EnneadTab for Revit uninstaller completed successfully",
            datetime.now().isoformat(),
        )
        self.log("EnneadTab has been detached from pyRevit. You can close this window.")
        return True

    def _run_install(self) -> bool:
        self._update_status("running", "Starting EnneadTab for Revit installer")

        # Step 1: ensure pyRevit is installed
        if not self.check_and_install_pyrevit():
            self.log("Cannot proceed without pyRevit. Install it manually and retry.")
            self._update_status("failed", "pyRevit installation failed", datetime.now().isoformat())
            return False

        # Step 2: locate pyRevit config (cached from step 1)
        config_path = self.get_pyrevit_config_path()
        if not os.path.exists(config_path):
            self.log("Error: pyRevit config file not found after installation attempt.")
            self._update_status(
                "failed", "pyRevit config file not found after installation attempt",
                datetime.now().isoformat(),
            )
            return False

        # Step 3: attach master clone to every installed Revit version
        self.attach_master_to_installed()

        # Step 4: update the config
        if not self.update_pyrevit_config(config_path):
            self._update_status("failed", "pyRevit config file update failed", datetime.now().isoformat())
            return False

        self._update_status(
            "success", "EnneadTab for Revit installer completed successfully",
            datetime.now().isoformat(),
        )
        self.log("Done. You can close this window and open Revit.")

        if _Exe_Util.IS_DEVELOPER:
            try:
                os.startfile(config_path)
            except Exception:
                pass
        return True
