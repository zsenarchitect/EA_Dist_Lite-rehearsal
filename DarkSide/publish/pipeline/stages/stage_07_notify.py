# -*- coding: utf-8 -*-
"""Stage 07: Operator & Phone Notifications."""

import os
import sys
from ..stage_base import PublishStage


class NotifyStage(PublishStage):
    """Notification stage: sends completion alerts to desktop and mobile phone (ntfy)."""

    @property
    def name(self):
        return "Operator Notifications"

    @property
    def description(self):
        return "Dispatches completion signals to NotificationHost and ntfy.sh topic."

    def execute(self, context):
        elapsed = context.elapsed_time()
        mode_label = "PRODUCTION" if context.is_production else "Rehearsal"

        # Read what actually happened. This message used to be the hardcoded string
        # "completed successfully", sent with tags="tada,package" no matter what the run
        # did -- so a publish that shipped but could not write its rollback tags told the
        # operator's phone it was fine. senzhang-todo #4702.
        #
        # The pipeline breaks on the first PublishStageError, so this stage never runs
        # after a HARD failure -- the phone is silent, not wrong. The case that reaches
        # here is the non-fatal one: a DEGRADED stage. That is exactly what stage_06 now
        # reports instead of swallowing, so this branch is load-bearing, not defensive.
        degraded = [r for r in context.results if r.is_degraded]
        if degraded:
            detail = "; ".join("{}: {}".format(r.stage_name, r.error) for r in degraded)
            msg = "Publish [{}] completed in {} but {} stage(s) DEGRADED -- {}".format(
                mode_label, elapsed, len(degraded), detail)
            title = "EnneadTab Publish [{}] DEGRADED".format(mode_label)
            tags = "warning,package"
            level = "warning"
        else:
            msg = "Publish [{}] completed successfully in {}.".format(mode_label, elapsed)
            title = "EnneadTab Publish [{}] COMPLETE".format(mode_label)
            tags = "tada,package"
            level = "success"

        print("Sending operator completion notification...")

        # 1. Desktop Notification Host
        try:
            apps_lib = os.path.join(context.os_repo_folder, "Apps", "lib")
            if apps_lib not in sys.path:
                sys.path.insert(0, apps_lib)
            from EnneadTab import NOTIFICATION
            NOTIFICATION.messenger(msg, title=title, level=level)
            print("[OK] Sent NotificationHost completion toast.")
        except Exception as e:
            print("Notice: Desktop notification skipped: {}".format(e))

        # 2. Mobile Push via ntfy (_phone_notify)
        try:
            publish_dir = os.path.join(context.os_repo_folder, "DarkSide", "publish")
            if publish_dir not in sys.path:
                sys.path.insert(0, publish_dir)
            import _phone_notify
            _phone_notify.send_ntfy(
                title=title,
                message=msg,
                tags=tags,
            )
        except Exception as e:
            print("Notice: Mobile ntfy notification skipped: {}".format(e))
