# -*- coding: utf-8 -*-
"""Stage 05: Git Commit, Push, & Remote Verification."""

import os
import subprocess
import time
from ..stage_base import PublishStage, PublishStageError


class GitPushStage(PublishStage):
    """Git push stage: commits staged dist content, force-pushes dist repos, and asserts origin/main parity via ls-remote."""

    @property
    def name(self):
        return "Git Push & Remote Verification"

    @property
    def description(self):
        return "Commits staged content, force-pushes dist repos, and confirms origin/main via ls-remote."

    def execute(self, context):
        self._push_distribution_repos(context)

    def _push_distribution_repos(self, context):
        """Commit staged files, force push EA_Dist and EA_Dist_Lite to origin main, and verify via ls-remote."""
        dist_repos = [
            (context.dist_folder, "EA_Dist"),
            (context.dist_lite_folder, "EA_Dist_Lite"),
        ]

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        for repo_folder, label in dist_repos:
            if not os.path.isdir(repo_folder):
                raise PublishStageError("Distribution directory missing for {}: {}".format(label, repo_folder))

            print("\nCommitting staged changes in {} ({})".format(label, repo_folder))

            # Stage all changes in dist repo
            try:
                subprocess.run(
                    [context.git_exe, "add", "-A"],
                    cwd=repo_folder,
                    check=True,
                    capture_output=True,
                )
            except Exception as e:
                raise PublishStageError("git add failed in {}: {}".format(label, e))

            # Commit staged changes
            commit_msg = "Publish EnneadTab-OS distribution at {}".format(timestamp)
            commit_res = subprocess.run(
                [context.git_exe, "commit", "-m", commit_msg],
                cwd=repo_folder,
                capture_output=True,
                text=True,
            )
            if commit_res.returncode == 0:
                print("    Committed distribution updates in {}".format(label))
            else:
                print("    No new changes to commit in {}".format(label))

            # Read local HEAD SHA
            try:
                head_sha = subprocess.check_output(
                    [context.git_exe, "rev-parse", "HEAD"], cwd=repo_folder, text=True
                ).strip()
            except Exception as e:
                raise PublishStageError("Failed to read local HEAD in {}: {}".format(label, e))

            # Force push
            print("Force pushing {} to origin main...".format(label))
            push_cmd = [context.git_exe, "push", "-f", "--no-verify", "--progress", "origin", "main"]
            try:
                push_res = subprocess.run(
                    push_cmd, capture_output=True, text=True, cwd=repo_folder, timeout=300
                )
                if push_res.returncode != 0:
                    print(push_res.stderr)
                    raise PublishStageError(
                        "git push failed for {} with exit code {}".format(label, push_res.returncode)
                    )
            except subprocess.TimeoutExpired:
                raise PublishStageError("git push for {} timed out after 300 seconds".format(label))
            except Exception as e:
                raise PublishStageError("git push for {} failed: {}".format(label, e))

            # Verify remote advanced using git ls-remote (never trust push exit code alone)
            print("Verifying {} origin/main ref via ls-remote...".format(label))
            verified = self._verify_remote_ref(context.git_exe, repo_folder, head_sha)
            if not verified:
                raise PublishStageError(
                    "Remote verification FAILED for {}: origin/main does not equal local HEAD ({})".format(
                        label, head_sha
                    )
                )

            print("[OK] Verified {} origin/main successfully advanced to {}".format(label, head_sha[:10]))

    def _verify_remote_ref(self, git_exe, repo_folder, expected_sha):
        """Use ls-remote to confirm origin/main matches expected_sha."""
        try:
            ls_res = subprocess.check_output(
                [git_exe, "ls-remote", "origin", "refs/heads/main"],
                cwd=repo_folder,
                text=True,
                timeout=30,
            ).strip()
            if not ls_res:
                return False
            remote_sha = ls_res.split()[0]
            return remote_sha.lower() == expected_sha.lower()
        except Exception as e:
            print("Warning: ls-remote verification check failed: {}".format(e))
            return False
