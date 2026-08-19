# -*- coding: utf-8 -*-
"""Shared Context model for the EnneadTab publish pipeline."""

import os
import sys
import time


class PublishContext(object):
    """Execution context and state container passed across pipeline stages."""

    def __init__(self, os_repo_folder, mode="manual", is_production=False, sha=""):
        self.os_repo_folder = os.path.normpath(os_repo_folder)
        self.root_folder = os.path.dirname(self.os_repo_folder)
        self.publish_mode = mode.lower()
        self.is_ci = os.environ.get("ENNEADTAB_PUBLISH_CI", "").strip().lower() in ("1", "true", "yes")
        self.is_production = is_production
        self.sha = sha

        # Standard Distribution target directories
        self.dist_folder = os.path.join(self.root_folder, "EA_Dist")
        self.dist_lite_folder = os.path.join(self.root_folder, "EA_Dist_Lite")

        # Executable tools
        self.git_exe = self._resolve_git_exe()
        self.ironpython_exe = None  # Resolved in preflight stage

        # Metadata and progress tracking
        self.start_time = time.time()
        self.results = []
        self.data = {}

    def _resolve_git_exe(self):
        """Locate full path to git executable on Windows."""
        git_paths = [
            r"C:\Users\szhang\AppData\Local\Programs\Git\bin\git.exe",
            r"C:\Program Files\Git\bin\git.exe",
            r"C:\Program Files (x86)\Git\bin\git.exe",
        ]
        for git_path in git_paths:
            if os.path.exists(git_path):
                return git_path
        return "git"

    def record_result(self, stage_result):
        """Record stage execution result."""
        self.results.append(stage_result)

    def elapsed_time(self):
        """Format total elapsed execution time."""
        total_seconds = int(time.time() - self.start_time)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return "{}h {}m {}s".format(hours, minutes, seconds)
        elif minutes > 0:
            return "{}m {}s".format(minutes, seconds)
        else:
            return "{}s".format(seconds)
