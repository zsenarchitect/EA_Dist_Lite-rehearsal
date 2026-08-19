# -*- coding: utf-8 -*-
"""Stage 04: Staging Distribution Repositories (EA_Dist & EA_Dist_Lite)."""

import os
import shutil
import time
from ..stage_base import PublishStage, PublishStageError

EXE_PRODUCTS_REL = os.path.join("Apps", "lib", "ExeProducts")


def try_remove_content(folder_path):
    """Safely remove contents of a directory."""
    if not os.path.exists(folder_path):
        return
    for item in os.listdir(folder_path):
        item_path = os.path.join(folder_path, item)
        try:
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
        except Exception as e:
            print("    Notice: Could not remove {}: {}".format(item_path, e))


def _count_exe_files(folder):
    """Count .exe files in directory."""
    if not os.path.isdir(folder):
        return 0
    return len([f for f in os.listdir(folder) if f.lower().endswith(".exe")])


class StageDistStage(PublishStage):
    """Staging stage: copies OS content into EA_Dist and EA_Dist_Lite with filtering."""

    @property
    def name(self):
        return "Staging Distribution Content"

    @property
    def description(self):
        return "Synchronizes Apps, Installation, and DarkSide trees to EA_Dist & EA_Dist_Lite."

    def execute(self, context):
        dist_targets = [
            (context.dist_folder, False, "EA_Dist (Full)"),
            (context.dist_lite_folder, True, "EA_Dist_Lite (Lite)"),
        ]

        for dist_folder, is_lite, label in dist_targets:
            if not os.path.exists(os.path.dirname(dist_folder)):
                raise PublishStageError("Parent directory for {} does not exist: {}".format(
                    label, dist_folder))
            self._sync_dist_repo(context, dist_folder, is_lite, label)

    def _sync_dist_repo(self, context, dist_folder, is_lite, label):
        """Synchronize OS repository into target distribution directory."""
        print("\nStaging content for {} at: {}".format(label, dist_folder))
        os.makedirs(dist_folder, exist_ok=True)

        folders_to_process = ["Apps", "Installation", "DarkSide"]
        lite_skip_folders = ["DuckMaker.extension", "_cad", "_engine", "DumpScripts", "dependency"]
        lite_allowed_exes = [
            "EnneadTab_OS_Installer.exe",
            "EnneadTab_OS_UnInstaller.exe",
            "EnneadTab_For_Revit_Installer.exe",
            "EnneadTab_For_Revit_UnInstaller.exe",
            "Emailer.exe",
            "NotificationHost.exe",
            "ProgressBar.exe",
        ]

        for folder in folders_to_process:
            exe_backup_dir = None
            src_exe_folder = os.path.join(context.os_repo_folder, EXE_PRODUCTS_REL)
            dist_exe_folder = os.path.join(dist_folder, EXE_PRODUCTS_REL)

            if folder == "Apps" and _count_exe_files(src_exe_folder) == 0 and _count_exe_files(dist_exe_folder) > 0:
                exe_backup_dir = os.path.join(dist_folder, ".publish_exe_products_backup")
                if os.path.exists(exe_backup_dir):
                    try_remove_content(exe_backup_dir)
                shutil.copytree(dist_exe_folder, exe_backup_dir)
                print("    Preserving {} existing dist exes".format(_count_exe_files(dist_exe_folder)))

            dest_subfolder = os.path.join(dist_folder, folder)
            try_remove_content(dest_subfolder)
            os.makedirs(dest_subfolder, exist_ok=True)

            src_subfolder = os.path.join(context.os_repo_folder, folder)
            if not os.path.exists(src_subfolder):
                continue

            # Batch file copy
            files_to_copy = []
            for root, dirs, files in os.walk(src_subfolder):
                if is_lite and any(skip.lower() in root.lower() for skip in lite_skip_folders):
                    continue
                if "DuckMaker.extension" in root:
                    continue

                for filename in files:
                    if is_lite:
                        if filename.lower().endswith(".exe") and filename not in lite_allowed_exes:
                            continue
                        if any(ext in filename.lower() for ext in [".dll", ".psd", ".ai"]):
                            continue

                    src_file = os.path.join(root, filename)
                    rel_path = os.path.relpath(src_file, src_subfolder)
                    dest_file = os.path.join(dest_subfolder, rel_path)
                    files_to_copy.append((src_file, dest_file))

            for src_file, dest_file in files_to_copy:
                os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                shutil.copy2(src_file, dest_file)

            if exe_backup_dir and os.path.isdir(exe_backup_dir):
                if _count_exe_files(dist_exe_folder) == 0:
                    os.makedirs(os.path.dirname(dist_exe_folder), exist_ok=True)
                    shutil.copytree(exe_backup_dir, dist_exe_folder)
                    print("    Restored dist ExeProducts from backup")
                try_remove_content(exe_backup_dir)

        print("[OK] Staging complete for {} ({} files copied).".format(label, len(files_to_copy)))
