# -*- coding: utf-8 -*-
"""Pipeline Runner orchestrator for executing publish stages with zero silent failures."""

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

        # Print Final Summary Report
        self._print_summary(pipeline_failed, failed_stage)

        if pipeline_failed:
            sys.exit(1)

    def _print_summary(self, failed, failed_stage):
        """Print clean summary table of stage results."""
        elapsed = self.context.elapsed_time()
        print("\n" + "=" * 75)
        print(" PIPELINE EXECUTION SUMMARY ")
        print(" Total Time: {}".format(elapsed))
        print("=" * 75)

        for res in self.context.results:
            status_str = "[ PASS ]" if res.is_success else "[ FAIL ]"
            print(" {:<10} {:<35} ({:.2f}s)".format(status_str, res.stage_name, res.duration))

        if failed:
            print("\n" + "!" * 75)
            print(" [CI RED] PUBLISH FAILED in stage: {}".format(
                failed_stage.name if failed_stage else "Unknown"))
            print("!" * 75 + "\n")
        else:
            print("\n" + "*" * 75)
            print(" [CI GREEN] PUBLISH COMPLETED SUCCESSFULLY IN {}".format(elapsed))
            print("*" * 75 + "\n")
