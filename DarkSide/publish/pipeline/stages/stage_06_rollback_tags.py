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

        problems = []
        for repo_folder, label in dist_repos:
            if not os.path.isdir(repo_folder):
                # This USED TO `continue` silently: no tag, no problems entry, so the
                # stage returned None and the DEGRADED contract read that as SUCCESS --
                # the identical shape to the tag-push failure fixed above (#4658), one
                # branch earlier. A missing dist folder here means the disaster-recovery
                # handle for THIS target was never even attempted. senzhang-todo #4748.
                msg = "{}: target folder missing, no rollback tag attempted".format(label)
                print("Warning: {}".format(msg))
                problems.append(msg)
                continue
            print("Creating rollback tag {} for {}...".format(tag_name, label))
            try:
                # timeout=, like stage_05's push (300s) and ls-remote (60s). Without one,
                # subprocess.run waits FOREVER -- and this runs AFTER stage_05 has already
                # force-pushed, so a hung tag push blocks the run at the point the
                # distribution has SHIPPED but nothing has been reported: no summary
                # table, no stage_07 notification, no phone push, and eventually (job
                # timeout-minutes: 90) a CI cancellation whose own reporting is lossy
                # (senzhang-todo #4749). 60s is generous for a tag push -- a few bytes of
                # ref update. subprocess.TimeoutExpired is an Exception subclass, so it
                # lands in the except block below and DEGRADES exactly like a push
                # failure, rather than hanging. senzhang-todo #4753.
                subprocess.run(
                    [context.git_exe, "tag", "-f", tag_name],
                    cwd=repo_folder,
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                subprocess.run(
                    [context.git_exe, "push", "-f", "origin", tag_name],
                    cwd=repo_folder,
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                print("[OK] Pushed rollback tag {} to {}.".format(tag_name, label))
            except Exception as e:
                # These tags are the disaster-recovery handle for a force-push that ~50
                # machines pull from. A tag that never landed used to look EXACTLY like one
                # that did -- a "Warning:" line in a log nobody reads -- so you found out it
                # was missing at the moment you needed it. It is still not fatal (see below),
                # but it must not be invisible either. senzhang-todo #4658.
                detail = getattr(e, "stderr", None) or ""
                if isinstance(detail, bytes):
                    detail = detail.decode("utf-8", "replace")
                # Capped, like stage_05 caps its git stderr. Uncapped, a verbose git
                # failure flows whole into the ntfy push and the GitHub annotation --
                # both of which are single-line channels where a wall of text buries the
                # one sentence that matters.
                detail = (detail.strip() or str(e))[:300]
                print("Warning: Failed to push rollback tag for {}: {}".format(label, detail))
                problems.append("{}: {}".format(label, detail))

        if problems:
            # DEGRADED, deliberately NOT raised. This stage runs AFTER stage_05 has already
            # force-pushed, so raising would exit 1 on a publish that genuinely shipped --
            # breaking the operator's "red means it did not ship" model, which is a worse
            # lie than the one being fixed. It would also break on the first
            # PublishStageError, so stage_07 would never run and there would be no phone
            # push at all on a publish that succeeded.
            return "rollback tag {} did not land for {} target(s) -- {}".format(
                tag_name, len(problems), "; ".join(problems))
