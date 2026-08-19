# -*- coding: utf-8 -*-
"""Stage 06: Atomic Rollback Tagging."""

import os
import subprocess
import time
from ..stage_base import PublishStage, PublishStageError


class RollbackTagsStage(PublishStage):
    """Rollback stage: creates and pushes rollback ref tags for dist repositories."""

    @property
    def name(self):
        return "Atomic Rollback Tagging"

    @property
    def description(self):
        return "Pushes dist-publish-rollback-* tags for instant disaster recovery."

    def execute(self, context):
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        tag_name = "dist-publish-rollback-{}".format(timestamp)

        dist_repos = [
            (context.dist_folder, "EA_Dist"),
            (context.dist_lite_folder, "EA_Dist_Lite"),
        ]

        for repo_folder, label in dist_repos:
            if not os.path.isdir(repo_folder):
                continue
            print("Creating rollback tag {} for {}...".format(tag_name, label))
            try:
                subprocess.run(
                    [context.git_exe, "tag", "-f", tag_name],
                    cwd=repo_folder,
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    [context.git_exe, "push", "-f", "origin", tag_name],
                    cwd=repo_folder,
                    check=True,
                    capture_output=True,
                )
                print("[OK] Pushed rollback tag {} to {}.".format(tag_name, label))
            except Exception as e:
                # Rollback tags are supplementary; log error but do not break green push
                print("Warning: Failed to push rollback tag for {}: {}".format(label, e))
