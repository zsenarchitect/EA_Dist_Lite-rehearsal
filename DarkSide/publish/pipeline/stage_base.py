# -*- coding: utf-8 -*-
"""Base classes and interfaces for publish pipeline stages."""

import time
import traceback
from abc import ABC, abstractmethod


class StageStatus(object):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    # A stage that did its job but could not complete some non-fatal part of it.
    # Distinct from FAILED on purpose: FAILED halts the pipeline, DEGRADED does not.
    # It exists so a stage running AFTER the force-push (stage_06 rollback tags) can
    # report a real problem without turning a publish that actually shipped into a
    # red run -- which would break the operator's "red means it did not ship" model.
    DEGRADED = "DEGRADED"


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

    @property
    def is_degraded(self):
        return self.status == StageStatus.DEGRADED

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
        """Execute the stage logic. Must raise PublishStageError on failure.

        Return value contract, deliberately falsy-safe:

          * ``None`` (what every stage returns today)  -> SUCCESS
          * a non-empty string                         -> DEGRADED, string is the reason

        `None` MUST keep meaning SUCCESS. tools/check_publish_outcome_honesty.py -- WIRED
        into the publisher-ratchets job -- monkeypatches `cls.execute` with no-ops that
        return None and then drives the real `publish()`. A contract where None meant
        anything else would turn it red on every PR and every push to main.

        CI pins this contract ONCE, through that gate. Stated precisely because "two
        gates pin it" would invite someone to assume more coverage than exists -- the
        exact defect senzhang-todo #4656 was filed about. (A second, never-wired gate,
        check_push_landing_predicates.py, was deleted in the old-publisher phase-out.)
        """
        pass

    def _notify_progress(self, context, message, level="info"):
        """Best-effort desktop notification toast to NotificationHost.

        Two guards, per senzhang-todo #4715. try/except catches EXCEPTIONS; it does not
        bound TIME. If NOTIFICATION.messenger ever blocked -- NotificationHost.exe not
        responding, a modal, a pipe wait -- this call sits on the critical path of EVERY
        stage (fired at start and again at success/failure), and the best-effort wrapper
        provided no protection at all: a hang here hangs the whole publish with nothing
        raised and no summary printed. A publish that hangs is worse than one that fails.

        1. Skip entirely on CI (context.is_ci) -- there is no desktop to toast, so this
           was pure risk with no payoff there. Also removes noise for free: a gate that
           monkeypatches execute() to a no-op still fires these toasts, because
           _notify_progress runs BEFORE execute(), not through it.
        2. Off CI, fire the call on a daemon thread and do NOT wait for it. No join, no
           timeout to tune: the caller returns immediately regardless of whether the
           notification ever completes, and a daemon thread cannot block process exit
           even if NOTIFICATION.messenger never returns. The toast is best-effort by
           CONSTRUCTION now -- the caller genuinely does not depend on it -- not just by
           the exception wrapper's intent.
        """
        if getattr(context, "is_ci", False):
            return

        def _send():
            try:
                import os
                import sys
                apps_lib = os.path.join(context.os_repo_folder, "Apps", "lib")
                if apps_lib not in sys.path:
                    sys.path.insert(0, apps_lib)
                from EnneadTab import NOTIFICATION
                NOTIFICATION.messenger(
                    message, title="Publish Pipeline: {}".format(self.name), level=level)
            except Exception:
                pass

        import threading
        threading.Thread(target=_send, daemon=True).start()

    def run(self, context):
        """Run the stage with automatic timing and exception wrapping."""
        start_time = time.time()
        print("\n" + "=" * 70)
        print("STAGE: [{}] - {}".format(self.name, self.description))
        print("=" * 70)
        self._notify_progress(context, "Starting stage...")

        try:
            outcome = self.execute(context)
            duration = time.time() - start_time
            # Falsy (None) is SUCCESS -- see the execute() contract above.
            if outcome:
                reason = str(outcome)
                print("[DEGRADED] Stage [{}] finished in {:.2f}s with a non-fatal "
                      "problem:".format(self.name, duration))
                print("  {}".format(reason))
                self._notify_progress(
                    context, "DEGRADED after {:.1f}s: {}".format(duration, reason), level="error")
                return StageResult(
                    self.name, StageStatus.DEGRADED, duration=duration, error=reason)
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
            # Record BEFORE raising. runner._print_summary iterates context.results, and
            # runner only records on its own success path (runner.py, after stage.run
            # returns) -- the raise below skips that, so without this line the FAILED
            # stage has no row in the summary table at all: the operator sees the passing
            # stages, then a CI RED banner naming the stage, but no duration and no error
            # text. This result carries both. senzhang-todo #4658.
            #
            # Cannot double-record: runner's own record_result call is unreachable once
            # this raises.
            #
            # Error-isolated from the failure it is recording. This is a best-effort side
            # effect running INSIDE an except block: if it raised -- a caller passing a
            # context without record_result, a full disk -- that exception would REPLACE
            # the real one, and the operator would get a traceback about bookkeeping
            # instead of the traceback about what actually broke. That is the very defect
            # this line exists to fix, one level down. Every caller today passes a real
            # PublishContext, but PublishStage is a public ABC and nothing enforces that.
            try:
                context.record_result(result)
            except Exception as record_error:
                print("Notice: could not record the failed stage result ({}: {}). The "
                      "failure below is the real one; it just will not appear as a row "
                      "in the summary table.".format(
                          type(record_error).__name__, record_error))
            # Fail RED: raise PublishStageError to halt pipeline execution immediately
            raise PublishStageError("Stage [{}] failed: {}".format(self.name, e))
        except BaseException as e:
            # Only reached for what `except Exception` above cannot catch: KeyboardInterrupt,
            # SystemExit, GeneratorExit -- exactly the shape of a CANCELLED CI job.
            # stage_04_stage_dist.py:273 already catches BaseException for its own dist-repair
            # path, with the same reasoning: a cancelled job must still repair. That fixed the
            # WEDGE. This fixes the REPORTING of it, which was still lost -- the operator got a
            # bare traceback with no stage table and no indication of how far the publish got.
            # senzhang-todo #4749.
            #
            # Deliberately does NOT wrap into PublishStageError (unlike the Exception branch
            # above) -- that would swallow the cancellation signal and turn a real interrupt
            # into an ordinary failure the caller could catch and continue past. Record, then
            # re-raise BARE so the cancellation still propagates and actually terminates the run.
            duration = time.time() - start_time
            tb = traceback.format_exc()
            print("\n[CANCELLED] Stage [{}] interrupted after {:.2f}s: {}".format(
                self.name, duration, e))
            print(tb)
            result = StageResult(
                self.name,
                StageStatus.FAILED,
                duration=duration,
                error=str(e) or type(e).__name__,
                details={"traceback": tb, "cancelled": True},
            )
            try:
                context.record_result(result)
            except Exception as record_error:
                print("Notice: could not record the cancelled stage result ({}: {}).".format(
                    type(record_error).__name__, record_error))
            raise
