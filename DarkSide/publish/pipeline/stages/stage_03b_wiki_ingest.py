# -*- coding: utf-8 -*-
"""Stage 03b: Wiki Data Ingestion.

WHY THIS IS A SEPARATE STAGE, NOT PART OF stage_03_docs_wiki.py
-----------------------------------------------------------------
stage_03 (DocsWikiStage) rebuilds LOCAL wiki HTML via WikiBuilder.wiki_builder.main()
and silently no-ops when that module is unavailable. This stage POSTs the current tool
catalog to the LIVE production site (https://enneadtab.com/wiki) so the handbook stays
current. The two are independent concerns with independent failure modes; keeping them
separate stages keeps the pass/fail/degraded reporting for each honest on its own.

WHY THIS EXISTS
---------------
The 2026-08-18 stage-pipeline migration (e32b261ec) ported the old monolithic
RepoPublisher.__main__ flow into pipeline/stages/*, but never ported
RepoPublisher._generate_wiki_website (________publish.py:2143-2370) -- the method that
resolves WIKI_API_KEY and calls wiki_ingest_client.ingest_platform_delta. That method is
still defined and still called from RepoPublisher's own old orchestration method, but
RepoPublisher itself is never instantiated by the current publish() entrypoint. Every
production publish since ~2026-08-18 has reported SUCCESS while never updating the live
wiki -- confirmed live in GitHub Actions run 34718572278 (2026-09-12), which never
printed a single ingest-related line. senzhang-todo TODO-6168.

This stage ports that logic into the PublishStage contract, preserving the exact
lesson learned on 2026-08-07 (a publish with no WIKI_API_KEY skipped ingestion and
still reported "ALL REPOSITORIES VERIFIED SUCCESSFULLY") and on 2026-08-12 (a
rehearsal run posted 368+156 real tools to the live wiki because the rehearsal gate
sat below key resolution instead of above it). Both gates are preserved here in the
same order and for the same reasons.
"""

import json
import os
import sys

from ..stage_base import PublishStage, PublishStageError


class WikiIngestStage(PublishStage):
    """Posts the current Revit/Rhino tool catalog to the live production wiki."""

    @property
    def name(self):
        return "Wiki Data Ingestion"

    @property
    def description(self):
        return "POSTs the current tool catalog to enneadtab.com/wiki so the handbook stays current."

    def execute(self, context):
        darkside_dir = os.path.normpath(os.path.join(context.os_repo_folder, "DarkSide"))
        publish_dir = os.path.join(darkside_dir, "publish")
        if publish_dir not in sys.path:
            sys.path.insert(0, publish_dir)
        try:
            from publish_guard import is_rehearsal, load_darkside_dotenv, resolve_wiki_api_key
        finally:
            if sys.path and sys.path[0] == publish_dir:
                sys.path.pop(0)

        # REHEARSAL GATE -- must come before key resolution, not just before the POST.
        # 2026-08-12, CI run 31609967538: a rehearsal posted 368 revit + 156 rhino tools
        # to the live enneadtab.com/wiki. resolve_wiki_api_key pulls the PRODUCTION key
        # from Vercel and persists it to disk; a rehearsal has no business fetching
        # production credentials it must not use. Gating only the POST would still leave
        # the secret pulled and written into the clone.
        #
        # Gated SOLELY on is_rehearsal() (ENNEADTAB_PUBLISH_REHEARSAL_TARGETS), matching
        # the old, proven _generate_wiki_website exactly -- NOT on context.is_production.
        # That flag is never actually True on any real invocation: ________publish.py's
        # `if __name__ == '__main__': sys.exit(0 if publish() else 1)` calls publish()
        # with zero arguments, so `is_production=False` always applies, and
        # run-ci-publish.ps1's `-Production` switch is never threaded through to the
        # Python call at all (it only drives publish_guard --assert-production vs
        # --report, and rehearsal-target validation, at the PowerShell layer). Gating on
        # `not context.is_production` here would make this stage skip on EVERY run,
        # rehearsal or production alike -- reproducing the exact bug this stage exists to
        # fix, just silently instead of loudly. senzhang-todo TODO-6168 note.
        if is_rehearsal():
            print("    Rehearsal run: refusing to write the production wiki "
                  "(expected -- this is not a failure).")
            return None

        # load_darkside_dotenv BEFORE reading WIKI_API_URL -- the old code's exact
        # order (________publish.py:2219-2223). DarkSide/.env is a documented override
        # point for WIKI_API_URL (e.g. redirecting ingest during an incident); reading
        # os.environ first would silently ignore an override that lives only there.
        load_darkside_dotenv(context.os_repo_folder)
        api_url = os.environ.get(
            "WIKI_API_URL", "https://ennead-tab-wiki.vercel.app/wiki/api/ingest/"
        )
        if not api_url.startswith("https://"):
            raise PublishStageError(
                "WIKI_API_URL must use https:// (refusing to send API key over an "
                "insecure channel)"
            )

        api_key = resolve_wiki_api_key(context.os_repo_folder, persist=True)
        if not api_key:
            raise PublishStageError(
                "WIKI_API_KEY missing after env, DarkSide/.env, and Vercel pull "
                "(ennead-projects/ennead-tab-wiki). Wiki ingest cannot skip -- it is "
                "the handbook channel."
            )

        wikibuilder_dir = os.path.join(darkside_dir, "WikiBuilder")
        if wikibuilder_dir not in sys.path:
            sys.path.insert(0, wikibuilder_dir)
        try:
            from wiki_ingest_client import ingest_platform_delta
        except ImportError as e:
            # NOT ATTEMPTED must fail the stage. The entire point of the 2026-08-07 fix
            # was that a step which cannot run must not read as success.
            raise PublishStageError("wiki_ingest_client not found: {}".format(e))

        apps_lib = os.path.join(context.os_repo_folder, "Apps", "lib")
        if apps_lib not in sys.path:
            sys.path.insert(0, apps_lib)
        from EnneadTab import ENVIRONMENT

        cache_path = os.path.join(darkside_dir, ".wiki_ingest_cache.json")
        platforms = {
            "revit": {
                "data_file": ENVIRONMENT.KNOWLEDGE_REVIT_FILE,
                "icons_dir": ENVIRONMENT.REVIT_PRIMARY_EXTENSION,
            },
            "rhino": {
                "data_file": ENVIRONMENT.KNOWLEDGE_RHINO_FILE,
                "icons_dir": ENVIRONMENT.RHINO_FOLDER,
            },
        }

        results = []
        for platform, cfg in platforms.items():
            data_file = cfg["data_file"]
            if not os.path.exists(data_file):
                print("    Warning: {} knowledge file not found, skipping".format(platform))
                results.append((platform, "NOT ATTEMPTED", "knowledge file not found"))
                continue

            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print("    {}: loaded {} tools from {}".format(
                    platform, len(data), os.path.basename(data_file)))
            except Exception as e:
                print("    Error loading {} data: {}".format(platform, e))
                results.append((platform, "ATTEMPTED AND FAILED",
                                "could not load knowledge data: {}".format(e)))
                continue

            ok, err, result = ingest_platform_delta(
                platform=platform,
                data=data,
                icons_dir=cfg["icons_dir"],
                api_url=api_url,
                api_key=api_key,
                cache_path=cache_path,
                log_fn=lambda msg: print(msg),
            )
            if not ok:
                print("    {}: ingest failed - {}".format(platform, err))
                results.append((platform, "ATTEMPTED AND FAILED", str(err)))
                continue
            if result.get("status") == "skipped":
                # An up-to-date wiki IS a delivered wiki -- the delta protocol skips
                # when the server already holds this exact manifest. Not a failure.
                print("    {}: skipped ({})".format(platform, result.get("reason", "unchanged")))
                results.append((platform, "INGESTED",
                                "already current ({})".format(result.get("reason", "unchanged"))))
                continue
            print("    {}: added={}, updated={}, unchanged={}, deleted={}, "
                  "icons_uploaded={}, icons_skipped={} ({}ms)".format(
                      platform,
                      result.get("tools_added", 0),
                      result.get("tools_updated", 0),
                      result.get("tools_unchanged", 0),
                      result.get("tools_deleted", 0),
                      result.get("icons_uploaded", 0),
                      result.get("icons_skipped", 0),
                      result.get("duration_ms", "?")))
            results.append((platform, "INGESTED", "added={} updated={} deleted={}".format(
                result.get("tools_added", 0),
                result.get("tools_updated", 0),
                result.get("tools_deleted", 0))))

        # Roll the per-platform states up. Any hard failure dominates; a platform that
        # never ran keeps the whole step out of INGESTED -- a wiki missing half its
        # tools is not a delivered wiki. Wiki is the handbook channel: fail closed here
        # so a publish that ships the fleet cannot also leave the wiki stale in silence.
        if not results:
            raise PublishStageError("Wiki ingest did not land: no platforms were processed")

        failed = [(p, d) for p, s, d in results if s == "ATTEMPTED AND FAILED"]
        if failed:
            raise PublishStageError("Wiki ingest did not land: {}".format(
                "; ".join("{}: {}".format(p, d) for p, d in failed)))

        not_attempted = [(p, d) for p, s, d in results if s == "NOT ATTEMPTED"]
        if not_attempted:
            raise PublishStageError("Wiki ingest did not land: {}".format(
                "; ".join("{}: {}".format(p, d) for p, d in not_attempted)))

        print("    Wiki data ingestion completed")
        return None
