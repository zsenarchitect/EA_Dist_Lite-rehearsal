# -*- coding: utf-8 -*-
"""Base classes and interfaces for publish pipeline stages."""

import time
import traceback
from abc import ABC, abstractmethod


class StageStatus(object):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class StageResult(object):
    """Result object returned by a publish pipeline stage."""

    def __init__(self, stage_name, status, duration=0.0, error=None, details=None):
        self.stage_name = stage_name
        self.status = status
        self.duration = duration
        self.error = error
        self.details = details or {}

    @property
    def is_success(self):
        return self.status == StageStatus.SUCCESS

    @property
    def is_failed(self):
        return self.status == StageStatus.FAILED

    def __repr__(self):
        return "<StageResult name={} status={} duration={:.2f}s>".format(
            self.stage_name, self.status, self.duration
        )


class PublishStageError(Exception):
    """Exception raised when a pipeline stage fails and halts execution."""
    pass


class PublishStage(ABC):
    """Abstract Base Class for all publish stages."""

    @property
    @abstractmethod
    def name(self):
        """Return human-readable stage name."""
        pass

    @property
    def description(self):
        """Return detailed stage description."""
        return ""

    @abstractmethod
    def execute(self, context):
        """Execute the stage logic. Must raise PublishStageError on failure."""
        pass

    def _notify_progress(self, context, message, level="info"):
        """Best-effort desktop notification toast to NotificationHost."""
        try:
            import os
            import sys
            apps_lib = os.path.join(context.os_repo_folder, "Apps", "lib")
            if apps_lib not in sys.path:
                sys.path.insert(0, apps_lib)
            from EnneadTab import NOTIFICATION
            NOTIFICATION.messenger(message, title="Publish Pipeline: {}".format(self.name), level=level)
        except Exception:
            pass

    def run(self, context):
        """Run the stage with automatic timing and exception wrapping."""
        start_time = time.time()
        print("\n" + "=" * 70)
        print("STAGE: [{}] - {}".format(self.name, self.description))
        print("=" * 70)
        self._notify_progress(context, "Starting stage...")

        try:
            self.execute(context)
            duration = time.time() - start_time
            print("[SUCCESS] Stage [{}] completed in {:.2f}s".format(self.name, duration))
            self._notify_progress(context, "Completed in {:.1f}s".format(duration), level="success")
            return StageResult(self.name, StageStatus.SUCCESS, duration=duration)
        except Exception as e:
            duration = time.time() - start_time
            tb = traceback.format_exc()
            print("\n[FAILED] Stage [{}] FAILED after {:.2f}s".format(self.name, duration))
            print("Error: {}".format(e))
            print(tb)
            self._notify_progress(context, "FAILED after {:.1f}s: {}".format(duration, e), level="error")
            result = StageResult(
                self.name,
                StageStatus.FAILED,
                duration=duration,
                error=str(e),
                details={"traceback": tb},
            )
            # Fail RED: raise PublishStageError to halt pipeline execution immediately
            raise PublishStageError("Stage [{}] failed: {}".format(self.name, e))
