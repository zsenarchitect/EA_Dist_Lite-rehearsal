# -*- coding: utf-8 -*-
"""Stage 01: Preflight Verification & Safety Gates."""

import os
import subprocess
import sys
from ..stage_base import PublishStage, PublishStageError


def clear_stale_git_locks(repo_folder):
    """Remove stale .git lock files for repo_folder."""
    removed = []
    git_dir = os.path.join(repo_folder, ".git")
    if not os.path.isdir(git_dir):
        return removed
    for lock_name in ("index.lock", "HEAD.lock", "config.lock", "packed-refs.lock"):
        lock_path = os.path.join(git_dir, lock_name)
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
                removed.append(lock_name)
            except OSError as exc:
                print("    Warning: could not remove {}: {}".format(lock_name, exc))
    if removed:
        print("    Cleared stale git lock(s) in {}: {}".format(
            os.path.basename(repo_folder.rstrip("\\/")), ", ".join(removed)))
    return removed


def find_ironpython_executable():
    """Locate IronPython 2.7 interpreter to use as Py2 syntax oracle."""
    override = os.environ.get("ENNEADTAB_IRONPYTHON_EXE", "").strip()
    candidates = []
    if override:
        candidates.append(override)
    candidates.extend([
        "ipy", "ipy.exe", "ipy64", "ipy64.exe",
        r"C:\Program Files\IronPython 2.7\ipy.exe",
        r"C:\Program Files (x86)\IronPython 2.7\ipy.exe",
    ])
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        for version in ("2.7.12", "2.7.11", "2.7"):
            candidates.append(os.path.join(
                local_app_data, "IronPython", version, "net45", "ipy.exe"))
    for candidate in candidates:
        try:
            subprocess.check_output([candidate, "-V"], stderr=subprocess.STDOUT, timeout=15)
            return candidate
        except Exception:
            continue
    return None


class PreflightStage(PublishStage):
    """Preflight stage: verifies publish_guard assertions, clears locks, checks Py2 syntax oracle, and asserts executable parity."""

    @property
    def name(self):
        return "Preflight & Safety Gates"

    @property
    def description(self):
        return "Validates environment, runs publish_guard assertions, clears git locks, and verifies executable files."

    def execute(self, context):
        print("Clearing stale git locks in OS repo...")
        clear_stale_git_locks(context.os_repo_folder)

        # Run publish_guard assertions BEFORE modifying dist repos
        self._run_publish_guard(context)

        # Locate IronPython
        ipy_exe = find_ironpython_executable()
        context.ironpython_exe = ipy_exe
        if ipy_exe:
            print("IronPython 2.7 syntax oracle located at: {}".format(ipy_exe))
        else:
            print("Notice: IronPython 2.7 syntax oracle not found; Py2 syntax check will be skipped.")

        # Confirm all executables exist against maker data
        self._confirm_all_exes_exist(context)

    def _run_publish_guard(self, context):
        """Execute publish_guard.py pre-publish assertion check."""
        print("Executing publish_guard pre-publish assertion...")
        guard_py = os.path.join(context.os_repo_folder, "DarkSide", "publish", "publish_guard.py")
        if not os.path.isfile(guard_py):
            raise PublishStageError("publish_guard.py missing at: {}".format(guard_py))

        python_bin = sys.executable
        cmd = [python_bin, guard_py]
        if context.is_production:
            cmd.append("--assert-production")
        else:
            cmd.append("--report")

        res = subprocess.run(cmd, capture_output=True, text=True, cwd=context.os_repo_folder)
        if res.returncode != 0:
            print(res.stdout)
            print(res.stderr)
            raise PublishStageError(
                "publish_guard assertion failed with exit code {}".format(res.returncode)
            )
        print("[OK] publish_guard pre-publish assertions passed.")

    def _confirm_all_exes_exist(self, context):
        """Verify all active maker data files have matching executables. Fails RED if missing."""
        print("Confirming executable parity against maker data files...")
        exe_folder = os.path.join(context.os_repo_folder, "Apps", "lib", "ExeProducts")
        data_folder = os.path.join(context.os_repo_folder, "DarkSide", "exes", "maker data")

        if not os.path.isdir(exe_folder):
            print("ExeProducts folder not found at {}, skipping check".format(exe_folder))
            return

        plugin_ext = ".sexyDuck"
        maker_files = set()
        for file in os.listdir(data_folder):
            if file.endswith(plugin_ext):
                maker_files.add(file[:-len(plugin_ext)])

        exe_files = set()
        for file in os.listdir(exe_folder):
            if file.endswith(".exe"):
                exe_files.add(file[:-4])

        missing_exes = sorted([name for name in maker_files if name not in exe_files])

        if missing_exes:
            alert = "\n" + "!" * 60 + "\n"
            alert += "ERROR: Missing executable files detected!\n"
            alert += "The following maker data files lack matching compiled .exe files:\n"
            for missing in missing_exes:
                alert += "  - {}\n".format(missing)
            alert += "Aborting publish process.\n"
            alert += "!" * 60 + "\n"
            print(alert)
            raise PublishStageError(
                "Missing executable files detected: {}. Build the missing exes or mark maker data files .RETIRED.".format(
                    ", ".join(missing_exes)
                )
            )

        print("[OK] All maker data files have matching compiled executables.")
