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
        msg = "Publish [{}] completed successfully in {}.".format(mode_label, elapsed)

        print("Sending operator completion notification...")

        # 1. Desktop Notification Host
        try:
            apps_lib = os.path.join(context.os_repo_folder, "Apps", "lib")
            if apps_lib not in sys.path:
                sys.path.insert(0, apps_lib)
            from EnneadTab import NOTIFICATION
            NOTIFICATION.messenger(msg, title="EnneadTab Publish Complete", level="success")
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
                title="EnneadTab Publish [{}] COMPLETE".format(mode_label),
                message=msg,
                tags="tada,package",
            )
        except Exception as e:
            print("Notice: Mobile ntfy notification skipped: {}".format(e))
