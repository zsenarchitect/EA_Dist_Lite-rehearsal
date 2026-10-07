# -*- coding: utf-8 -*-
"""Pipeline Runner orchestrator for executing publish stages with zero silent failures."""

import os
import sys
import time
import traceback
from .stage_base import PublishStageError, StageStatus


class PipelineRunner(object):
    """Orchestrates publish pipeline execution, enforcing strict fail-fast policy."""

    def __init__(self, context):
        self.context = context
        self.stages = []

    def add_stage(self, stage):
        """Register a PublishStage in the pipeline sequence."""
        self.stages.append(stage)

    def run(self):
        """Execute all pipeline stages sequentially.
        
        Enforces Zero Silent Failures: any stage failure halts execution immediately
        with non-zero exit code (CI RED).
        """
        print("\n" + "#" * 75)
        print(" ENNEADTAB-OS PUBLISH PIPELINE INITIALIZED ")
        print(" Mode       : {}".format(self.context.publish_mode))
        print(" Production : {}".format(self.context.is_production))
        print(" CI Run     : {}".format(self.context.is_ci))
        print(" Repository : {}".format(self.context.os_repo_folder))
        print("#" * 75 + "\n")

        pipeline_failed = False
        failed_stage = None

        for stage in self.stages:
            try:
                result = stage.run(self.context)
                self.context.record_result(result)
            except PublishStageError as e:
                pipeline_failed = True
                failed_stage = stage
                break
            except Exception as e:
                pipeline_failed = True
                failed_stage = stage
                print("\n[UNHANDLED ERROR] In stage [{}]: {}".format(stage.name, e))
                traceback.print_exc()
                break
            except BaseException as e:
                # Only reached for what `except Exception` above cannot catch --
                # KeyboardInterrupt / SystemExit / GeneratorExit, i.e. a cancelled CI job.
                # stage.run() (stage_base.py) now catches this same shape, records the
                # partial result, and re-raises BARE -- so it lands here still carrying
                # its real type, not wrapped into an ordinary Exception. Print the summary
                # explicitly before propagating: the normal path below reaches
                # _print_summary() only after the for-loop, which a raise inside the loop
                # skips entirely. Without this, a cancelled run got a bare traceback and
                # NO stage table at all -- no indication of how far the publish got before
                # it was killed. senzhang-todo #4749.
                pipeline_failed = True
                failed_stage = stage
                print("\n[CANCELLED] Pipeline interrupted in stage [{}]: {}".format(
                    stage.name, e))
                self._print_summary(pipeline_failed, failed_stage)
                raise

        # Print Final Summary Report
        self._print_summary(pipeline_failed, failed_stage)

        if pipeline_failed:
            err_details = None
            for r in self.context.results:
                if not r.is_success and r.error:
                    err_details = r.error
                    break
            self._report_failure_to_errordump(failed_stage, err_details or "Pipeline failed")
            sys.exit(1)

    def _report_failure_to_errordump(self, failed_stage, error_detail):
        """Post pipeline failure to ErrorDump so publish failures are recorded in telemetry."""
        try:
            import urllib.request
            import json
            stage_name = failed_stage.name if failed_stage else "Unknown Stage"
            error_message = "[Publish Failure] Stage [{}]: {}".format(stage_name, error_detail)
            payload = json.dumps({
                "source_app": "EnneadTab-OS",
                "environment": "ci" if getattr(self.context, "is_ci", False) else "terminal",
                "error_message": error_message[:2000],
                "stack_trace": str(error_detail)[:10000],
                "function_name": "publish_pipeline",
                "user_name": os.environ.get("USERNAME", "ci_runner"),
                "machine_name": os.environ.get("COMPUTERNAME", "unknown"),
                "context": {
                    "stage": stage_name,
                    "is_production": getattr(self.context, "is_production", False),
                    "publish_mode": getattr(self.context, "publish_mode", "unknown"),
                    "target_sha": getattr(self.context, "target_sha", "") or os.environ.get("GITHUB_SHA", ""),
                    "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
                    "github_repository": os.environ.get("GITHUB_REPOSITORY", ""),
                }
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://error-dump-ennead-projects.vercel.app/error-dump/api/ingest",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
            print(" [ErrorDump] Reported publish failure to ErrorDump service.")
        except Exception as exc:
            print(" [ErrorDump] Notice: could not report to ErrorDump (non-fatal): {}".format(exc))

    def _announce_degraded(self, degraded):
        """Tell GITHUB ITSELF, not just the log, that this publish degraded.

        A DEGRADED run exits 0 on purpose -- the distribution shipped, and exiting
        non-zero would reintroduce the false-failed this whole change exists to kill. But
        exit 0 means GitHub renders the run plain green, and publish-production.yml's only
        notification is `if: failure()`, so it never fires. That leaves ONE out-of-band
        signal: stage_07's ntfy push -- and when that push itself fails, stage_07 catches
        it and prints a Notice into the same green log.

        The compounding case is the realistic one, not a hypothesis: when stage_05
        degrades because origin is unreadable, stage_06's tag push crosses that SAME
        network and degrades too. So the run that could neither confirm its push nor write
        its rollback handle is exactly the run most likely to be announced only in log
        text nobody opens.

        `::warning` puts it on the run's Annotations, and the step summary puts it on the
        run page. senzhang-todo #4702.
        """
        if not os.environ.get("GITHUB_ACTIONS"):
            return
        for res in degraded:
            # Newlines would split the annotation; keep it to one line.
            reason = " ".join(str(res.error or "").split())
            print("::warning title=Publish degraded ({})::{}".format(res.stage_name, reason))
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if not summary_path:
            return
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n### Publish completed with {} DEGRADED stage(s)\n\n".format(
                    len(degraded)))
                for res in degraded:
                    # Flatten here too. A raw multi-line reason breaks out of the list
                    # item and renders as loose body text on the run page -- the same
                    # reason the annotations above are flattened.
                    handle.write("- **{}** — {}\n".format(
                        res.stage_name, " ".join(str(res.error or "").split())))
                handle.write("\nThe distribution shipped; these are non-fatal problems "
                             "that still need an operator.\n")
        except Exception as exc:
            # Error-isolated: announcing must never fail a publish that succeeded, and
            # must not be silent about failing either.
            print("Notice: could not write the degraded summary ({}: {}). The warning "
                  "annotations above still stand.".format(type(exc).__name__, exc))

    def _print_summary(self, failed, failed_stage):
        """Print clean summary table of stage results."""
        elapsed = self.context.elapsed_time()
        print("\n" + "=" * 75)
        print(" PIPELINE EXECUTION SUMMARY ")
        print(" Total Time: {}".format(elapsed))
        print("=" * 75)

        # Three states, not two. `is_success else [ FAIL ]` also mislabelled DEGRADED and
        # SKIPPED as failures, and printed no error text for any of them -- so the row that
        # explains the run was the one row carrying no explanation. senzhang-todo #4658.
        for res in self.context.results:
            if res.is_success:
                status_str = "[ PASS ]"
            elif res.is_degraded:
                status_str = "[ WARN ]"
            elif res.status == StageStatus.SKIPPED:
                status_str = "[ SKIP ]"
            else:
                status_str = "[ FAIL ]"
            print(" {:<10} {:<35} ({:.2f}s)".format(status_str, res.stage_name, res.duration))
            if res.error:
                print(" {:<10} {}".format("", res.error))

        if failed:
            print("\n" + "!" * 75)
            print(" [CI RED] PUBLISH FAILED in stage: {}".format(
                failed_stage.name if failed_stage else "Unknown"))
            print("!" * 75 + "\n")
        else:
            degraded = [r for r in self.context.results if r.is_degraded]
            print("\n" + "*" * 75)
            if degraded:
                # Still green -- the distribution shipped -- but saying only "SUCCESSFULLY"
                # here is how a silently-absent rollback tag stays unnoticed until the day
                # it is needed. Graceful to the fleet, never silent to the operator.
                print(" [CI GREEN] PUBLISH COMPLETED IN {} -- WITH {} DEGRADED STAGE(S)".format(
                    elapsed, len(degraded)))
                for r in degraded:
                    print("   ! {}: {}".format(r.stage_name, r.error))
                self._announce_degraded(degraded)
            else:
                print(" [CI GREEN] PUBLISH COMPLETED SUCCESSFULLY IN {}".format(elapsed))
            print("*" * 75 + "\n")
