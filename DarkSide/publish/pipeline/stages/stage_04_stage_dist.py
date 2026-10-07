# -*- coding: utf-8 -*-
"""Stage 04: Staging Distribution Repositories (EA_Dist & EA_Dist_Lite)."""

import datetime
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
from ..stage_base import PublishStage, PublishStageError

EXE_PRODUCTS_REL = os.path.join("Apps", "lib", "ExeProducts")

# The ONLY folders this stage wipes and recopies. The crash-restore below uses this
# exact list as its git pathspec, so the blast radius of a restore can never exceed
# what the sync already destroyed. Keep them derived from one another -- a restore
# scoped wider than the wipe would revert tracked paths this stage never touches
# (EA_Dist also carries CNAME, .github/, rhino-assistant/, README.md), and an
# uncommitted edit to one of those is unrecoverable: never staged, so not in the
# reflog and not in any git object.
FOLDERS_TO_PROCESS = ["Apps", "Installation", "DarkSide"]

# Tracked files at the dist ROOT that this stage rewrites (outside FOLDERS_TO_PROCESS).
# The crash-restore checks these out too, so a crash after a rewrite cannot leave the
# tree dirty. Checkout only, never clean: they are tracked, and clean at repo root is banned.
ROOT_FILES_WRITTEN = ["README.md"]

# What the Lite distribution drops. Module scope, NOT locals inside _sync_dist_repo,
# because stage_03's path-length scan has to reproduce EA_Dist_Lite's file set to know
# which paths actually land there. A second copy of these lists in another stage is how
# the scan and the sync quietly start disagreeing about what ships. senzhang-todo #4692.
LITE_SKIP_FOLDERS = ["DuckMaker.extension", "_cad", "_engine", "DumpScripts", "dependency"]
LITE_ALLOWED_EXES = [
    "EnneadTab_OS_Installer.exe",
    "EnneadTab_OS_UnInstaller.exe",
    "EnneadTab_For_Revit_Installer.exe",
    "EnneadTab_For_Revit_UnInstaller.exe",
    "Emailer.exe",
    "NotificationHost.exe",
    "ProgressBar.exe",
]

# Excluded from EVERY target, Full included -- checked unconditionally in
# path_excluded_from_target below, NOT gated on is_lite. It also appears first in
# LITE_SKIP_FOLDERS above, which makes it redundant for Lite specifically, but that
# list alone never excluded it from Full: without this separate unconditional check,
# stage_03's path-length scan measured EA_Dist (the Full root) as if this content
# shipped there, when stage_04's own walk never lets it. senzhang-todo #4747.
UNCONDITIONAL_SKIP_FOLDERS = ["DuckMaker.extension"]


def path_excluded_from_target(rel_path, is_lite):
    """Would `rel_path` (relative to a FOLDERS_TO_PROCESS folder) be excluded from the
    given target's staged content by _sync_dist_repo's walk?

    SINGLE SOURCE OF TRUTH for the exclusion rules _sync_dist_repo applies at
    walk-time -- stage_03's path-length scan must reproduce the same decision at
    scan-time to measure the roots it claims to measure, and a second copy of this
    logic is how the two silently drift. They already had: stage_03's own
    reimplementation was missing the extension filter below AND the unconditional
    DuckMaker.extension exclusion, so its Lite measurement over-counted and its Full
    measurement did too. senzhang-todo #4747.

    `rel_path` may name either a directory (for the walk's own prune decision) or a
    file -- the predicate is written to work identically either way, since it checks
    path SEGMENTS, and a directory exclusion here is what stage_03 uses to skip an
    entire subtree without needing to enumerate it.
    """
    normalized = rel_path.replace("\\", "/")
    segments = [s for s in normalized.split("/") if s and s != "."]
    filename = segments[-1] if segments else ""

    if any(skip.lower() in seg.lower() for seg in segments
           for skip in UNCONDITIONAL_SKIP_FOLDERS):
        return True

    if is_lite:
        low = normalized.lower()
        if any(skip.lower() in low for skip in LITE_SKIP_FOLDERS):
            return True
        if filename.lower().endswith(".exe") and filename not in LITE_ALLOWED_EXES:
            return True
        if any(ext in filename.lower() for ext in (".dll", ".psd", ".ai")):
            return True

    return False

# Fault injection for testing the restore path. A repair that has never been WATCHED
# to fire is unverified -- "silently does nothing" and "works" look identical. Set
# ENNEADTAB_PUBLISH_FAULT_INJECT=<n> to raise after n files have been copied.
# Refuses to arm outside a rehearsal, so it can never wedge a production publish.
FAULT_INJECT_ENV = "ENNEADTAB_PUBLISH_FAULT_INJECT"


def _fault_inject_after():
    """Return the copy count to fail after, or None. Rehearsal-only, by construction."""
    raw = os.environ.get(FAULT_INJECT_ENV, "").strip()
    if not raw:
        return None
    if not os.environ.get("ENNEADTAB_PUBLISH_REHEARSAL_TARGETS", "").strip():
        print("    Notice: {} is set but this is not a rehearsal -- IGNORING it. "
              "Fault injection is never armed against the production "
              "distribution.".format(FAULT_INJECT_ENV))
        return None
    try:
        return int(raw)
    except ValueError:
        print("    Notice: {}={!r} is not an integer; ignoring.".format(FAULT_INJECT_ENV, raw))
        return None


def _force_writable_retry(func, path, exc_info):
    """rmtree handler: clear the read-only bit and retry once, else re-raise.

    Uses the `onerror=` signature deliberately -- `onexc=` is 3.12+, and the publisher and
    rehearsal clones do not report the same Python version. `onerror` is deprecated but
    functional in both, so it is the portable choice here.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        raise


def try_remove_content(folder_path):
    """Remove a directory's contents. Returns [(path, error)] for anything it could NOT remove.

    Callers must not discard the return value. The copy loop only writes paths present in
    SOURCE and never removes extras, so a file that survives this wipe survives into the
    PUBLISHED distribution. That is silently-wrong content shipped to the fleet, not a nit
    -- and it raises no exception, so nothing else in the pipeline notices.
    """
    failures = []
    if not os.path.exists(folder_path):
        return failures
    for item in os.listdir(folder_path):
        item_path = os.path.join(folder_path, item)
        # Retry with backoff before calling it a failure. A transient holder -- an
        # antivirus scan, an indexer, a read-only attribute -- is common enough that a
        # single attempt would turn a blip into a refused publish, and this repo's own
        # guidance requires retries around file locks. Deliberately short: a PERSISTENT
        # lock must still surface rather than being waited out.
        last_error = None
        for attempt in range(3):
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.chmod(item_path, stat.S_IWRITE)  # clears the read-only case
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path, onerror=_force_writable_retry)
                last_error = None
                break
            except Exception as e:
                last_error = e
                if attempt < 2:
                    time.sleep(0.25 * (2 ** attempt))
        if last_error is not None:
            failures.append((item_path, str(last_error)))
    return failures


def _count_exe_files(folder):
    """Count .exe files in directory."""
    if not os.path.isdir(folder):
        return 0
    return len([f for f in os.listdir(folder) if f.lower().endswith(".exe")])


def _git(context, repo, args, timeout=1800):
    """Run git in `repo`. Returns (rc, stdout+stderr). Never raises on non-zero."""
    try:
        proc = subprocess.run(
            [context.git_exe] + list(args),
            cwd=repo, capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:  # timeout, git missing, permissions
        return 1, "{}: {}".format(type(exc).__name__, exc)


def _is_git_worktree(context, repo):
    """A restore is only meaningful in a git repo. stage_04 will happily os.makedirs a
    plain directory, and `git checkout` there would raise and MASK the real error."""
    rc, out = _git(context, repo, ["rev-parse", "--is-inside-work-tree"], timeout=60)
    return rc == 0 and out.strip().lower().startswith("true")


def _dump_forensics(context, repo, label):
    """Write the wedged tree's state to a durable file BEFORE repairing it.

    The wedged tree IS the diagnostic artifact: on 2026-08-21 it was the 1802 stray
    deletions that identified the copy-loop crash. Repairing without recording first
    trades a 3-day outage for an unexplainable one.
    """
    rc, out = _git(context, repo, ["status", "--porcelain"], timeout=300)
    if rc != 0:
        return None, 0
    lines = [ln for ln in out.splitlines() if ln.strip()]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(
        os.path.dirname(repo),
        "publish-crash-{}-{}.txt".format(os.path.basename(repo.rstrip("\\/")), stamp),
    )
    try:
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write("Dist tree state at crash -- {} ({})\n".format(label, stamp))
            fh.write("repo: {}\n".format(repo))
            fh.write("dirty paths: {}\n\n".format(len(lines)))
            fh.write("\n".join(lines))
        return dest, len(lines)
    except Exception as exc:
        print("    Notice: could not write forensics file: {}".format(exc))
        return None, len(lines)


def _restore_dist_tree(context, repo, label):
    """Undo this stage's own damage, scoped to exactly the folders it wipes.

    checkout restores tracked deletions/modifications; clean removes files the copy
    loop wrote that are absent from HEAD (a new file leaves the tree dirty, and the
    guard treats ANY porcelain output as dirty, so checkout alone cannot unwedge it).

    Both are pathspec-scoped. `clean` must NEVER run at repo root -- that would delete
    untracked work, stray worktrees, and .env files that survive by design.
    """
    problems = []
    # Per folder, NOT one command listing all three. `git checkout -- A B C` fails
    # WHOLESALE if any single pathspec matches nothing in the index, so one absent
    # folder means NOTHING is restored -- including the folders that were present and
    # broken. Verified against a repo tracking only Apps/: a trivially restorable
    # deletion was left broken because 'Installation' and 'DarkSide' did not match.
    # Both dist repos track all three today, so this was latent, not live.
    for folder in FOLDERS_TO_PROCESS:
        rc, out = _git(context, repo, ["checkout", "--", folder])
        if rc != 0:
            msg = out.strip()
            if "did not match any file" in msg:
                continue  # folder simply isn't tracked here; nothing to restore
            problems.append("checkout {} failed: {}".format(folder, msg[:300]))
        rc, out = _git(context, repo, ["clean", "-fd", "--", folder])
        if rc != 0:
            problems.append("clean {} failed: {}".format(folder, out.strip()[:300]))
    for root_file in ROOT_FILES_WRITTEN:
        rc, out = _git(context, repo, ["checkout", "--", root_file])
        if rc != 0 and "did not match any file" not in out:
            problems.append("checkout {} failed: {}".format(root_file, out.strip()[:300]))
    rc, out = _git(context, repo, ["status", "--porcelain"], timeout=300)
    remaining = len([ln for ln in out.splitlines() if ln.strip()]) if rc == 0 else -1
    return problems, remaining


def restore_dist_repos(context, repos, reason):
    """Best-effort repair of every dist repo touched. NEVER raises.

    Errors here must not replace the exception that triggered the repair, and must not
    be swallowed either -- both get reported (global rule #13).
    """
    if not repos:
        return
    print("\n" + "=" * 70)
    print("DIST REPAIR -- {}".format(reason))
    print("=" * 70)
    for repo, label in repos:
        try:
            if not os.path.isdir(repo):
                print("  {}: gone from disk, nothing to repair".format(label))
                continue
            if not _is_git_worktree(context, repo):
                print("  {}: NOT a git repo -- cannot repair, leaving as-is: {}".format(label, repo))
                continue
            dump, dirty = _dump_forensics(context, repo, label)
            if dirty == 0:
                print("  {}: already clean, nothing to repair".format(label))
                continue
            print("  {}: {} dirty path(s){}".format(
                label, dirty, "; recorded at {}".format(dump) if dump else ""))
            problems, remaining = _restore_dist_tree(context, repo, label)
            for p in problems:
                print("  {}: REPAIR PROBLEM -- {}".format(label, p))
            if remaining == 0:
                print("  {}: repaired, tree clean".format(label))
            else:
                print("  {}: STILL DIRTY after repair ({} path(s)). The next publish will "
                      "refuse until this is cleared by hand.".format(label, remaining))
        except Exception as exc:
            # Repair is best-effort. It must never become the reported failure.
            print("  {}: repair raised {}: {}".format(label, type(exc).__name__, exc))
    print("=" * 70 + "\n")


def _resolve_source_commit(context):
    """The exact SHA this publish is shipping, for the version stamp.

    Prefers ENNEADTAB_PUBLISH_SHA (set by run-ci-publish.ps1 right after its own reset,
    following workflow_dispatch's inputs.sha override) over GITHUB_SHA (Actions' own
    trigger-commit var, which does NOT follow that override) over a live `git rev-parse
    HEAD` on os_repo_folder -- ported unchanged from the legacy ________publish.py
    _write_dist_version_stamp, which senzhang-todo #4417 fixed. See that history for why
    this precedence, not a fresher one, is correct.
    """
    source_commit = (
        os.environ.get("ENNEADTAB_PUBLISH_SHA")
        or os.environ.get("GITHUB_SHA")
        or None
    )
    if source_commit:
        source_commit = source_commit.strip()
    if source_commit:
        return source_commit
    try:
        return subprocess.check_output(
            [context.git_exe, "rev-parse", "HEAD"],
            cwd=context.os_repo_folder, universal_newlines=True, timeout=30).strip()
    except Exception as exc:
        print("    Could not resolve source commit for version stamp: {}".format(exc))
        return "unknown"


def _write_dist_version_stamp(dist_folder, stamp):
    """Write Apps/lib/EnneadTab/DIST_VERSION.json into the dist copy.

    Runtime code (ENVIRONMENT.get_dist_version) reads this so every error report carries
    the exact publish a machine is running; absence of the file means a dev tree.

    MUST run after _sync_dist_repo (which wipes Apps/) and before stage_05 commits --
    ported from the legacy, now-dead ________publish.py._write_dist_version_stamp. That
    function kept working correctly through the 2026-08-18 stage-pipeline migration, but
    the migration never called it: StageDistStage replaced the monolith's copy-and-commit
    method without carrying this step over, so the stamp silently stopped shipping on
    every publish since (senzhang-todo #2391, confirmed against EA_Dist's own git history
    -- the file was removed in the first post-migration commit and never reappeared).
    """
    stamp_path = os.path.join(dist_folder, "Apps", "lib", "EnneadTab", "DIST_VERSION.json")
    os.makedirs(os.path.dirname(stamp_path), exist_ok=True)
    with open(stamp_path, "w") as f:
        json.dump(stamp, f, indent=4)
    print("    DIST_VERSION stamp written: {}".format(stamp["version"]))


def _write_dist_manifest(dist_folder, stamp):
    """Write Installation/dist_manifest.json into the dist copy.

    A SHA-256 of every shipped .py file under Apps/lib/EnneadTab and
    Apps/_revit/EnneaDuck.extension -- the integrity manifest that lets a user machine
    prove its install is internally consistent. EnneadTab.INTEGRITY.verify() reads it.
    Scope lives in INTEGRITY.MANIFEST_TREES so the writer and reader cannot drift.

    Same provenance and same "must run after copy, before commit" rule as
    _write_dist_version_stamp above -- ported from the same dead legacy method for the
    same reason.

    Imports EnneadTab.INTEGRITY lazily: this stage must remain importable (for tests,
    for a rehearsal with no EnneadTab lib on sys.path) even when the real package is not
    reachable. A missing INTEGRITY module degrades to "no manifest this run", loud on
    stdout, never a hard failure -- write failures here must never block the fleet from
    getting the rest of the publish.
    """
    try:
        from EnneadTab import INTEGRITY
    except Exception as exc:
        print("    Warning: EnneadTab.INTEGRITY not importable, skipping dist_manifest.json: "
              "{}: {}".format(type(exc).__name__, exc))
        return

    files = INTEGRITY.build_manifest_files(dist_folder)
    manifest = {
        "version": stamp["version"],
        "source_commit": stamp["source_commit"],
        "published_at": stamp["published_at"],
        "trees": INTEGRITY.MANIFEST_TREES,
        "files": files,
    }
    manifest_dir = os.path.join(dist_folder, "Installation")
    os.makedirs(manifest_dir, exist_ok=True)
    manifest_path = os.path.join(manifest_dir, INTEGRITY.MANIFEST_NAME)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=4, sort_keys=True)
    print("    dist_manifest written: {} files hashed".format(len(files)))


_LITE_README_NOTE = """# LITE VERSION

This is the **LITE VERSION** of the distribution repository, optimized for quick installation.

## Excluded Content
The following content has been removed to reduce size:
- Most executable files (.exe), **except installers, uninstallers and a few core utilities**
- Dynamic link libraries (.dll)
- CAD-related files and folders
- Engine files and folders
- Dump scripts
- Dependency files

## Included Executable Files
{installers}

For the full version with all features, please use the standard distribution."""

_DIST_README_TEMPLATE = """# EnneadTab Distribution Repository

## 📅 Last Updated
{updated}

{lite_note}

## 📦 Contents
This repository contains:
- 📂 Apps
- 📂 Installation

## ⚠️ Important Notes
- For support, please contact szhang@ennead.com directly

## 🙏 Acknowledgments
- Special thanks to all users who have provided feedback and suggestions
- Special thanks to Ehsan and the pyRevit team for providing the foundation for the Revit Extension

## 💭 Wisdom of the Day
{joke}

---
*Have a nice day! Hope you enjoy using this product.*
"""


def _random_joke():
    """Lazy, never-fatal JOKE import, same reasoning as INTEGRITY in _write_dist_manifest."""
    try:
        from EnneadTab import JOKE
        return JOKE.random_joke()
    except Exception as exc:
        print("    Warning: EnneadTab.JOKE unavailable for README: {}: {}".format(
            type(exc).__name__, exc))
        return "Keep calm and model on."


def _write_dist_readme(dist_folder, is_lite, stamp):
    """Write the public README.md at the dist repo root.

    Ported from the dead legacy ________publish.py._copy_files_to_dist_repo. Same story
    as _write_dist_version_stamp: the 2026-08-18 stage-pipeline migration never carried
    this step over, so EA_Dist's README froze at "Last Updated 2026-08-18 14:54:01" while
    every publish after it shipped normally. README.md sits outside FOLDERS_TO_PROCESS,
    so the sync never touches it; stage_05's `git add -A` commits this rewrite.

    The internal "automatically generated and not manually maintained" note is
    deliberately NOT carried over: EA_Dist is public and that line is for us only.
    """
    lite_note = ""
    if is_lite:
        lite_note = _LITE_README_NOTE.format(
            installers="\n".join("- {}".format(name) for name in LITE_ALLOWED_EXES))
    updated = stamp["published_at"].replace("T", " ")
    content = _DIST_README_TEMPLATE.format(
        updated=updated, lite_note=lite_note, joke=_random_joke())
    with open(os.path.join(dist_folder, "README.md"), "w", encoding="utf-8") as f:
        f.write(content)
    print("    README.md written (Last Updated {})".format(updated))


class StageDistStage(PublishStage):
    """Staging stage: copies OS content into EA_Dist and EA_Dist_Lite with filtering."""

    @property
    def name(self):
        return "Staging Distribution Content"

    @property
    def description(self):
        return "Synchronizes Apps, Installation, and DarkSide trees to EA_Dist & EA_Dist_Lite."

    def execute(self, context):
        dist_targets = [
            (context.dist_folder, False, "EA_Dist (Full)"),
            (context.dist_lite_folder, True, "EA_Dist_Lite (Lite)"),
        ]

        # Every repo we START syncing is a repair candidate, recorded BEFORE the work
        # begins: the damage is done by try_remove_content at the top of the sync, so a
        # crash one file in still leaves a wiped tree. Tracking all touched targets (not
        # just the failing one) matters -- a crash in Lite otherwise leaves EA_Dist fully
        # copied and dirty, and the next publish refuses on IT instead.
        touched = []
        # Temp ExeProducts backups created during this stage, cleaned in the finally below.
        # A crash between creating one and restoring from it must not leave it on disk:
        # it is outside the repo so it cannot wedge a publish any more, but an unbounded
        # pile of multi-hundred-MB exe copies in %TEMP% is its own slow failure.
        self._exe_backup_dirs = []
        # Computed once, shared by both targets, so EA_Dist and EA_Dist_Lite from the same
        # publish run carry an identical version -- same intent as the legacy (now dead)
        # ________publish.py._write_dist_version_stamp this was ported from.
        now = datetime.datetime.now()
        dist_version_stamp = {
            "version": now.strftime("%Y.%m.%d.%H%M"),
            "source_commit": _resolve_source_commit(context),
            "published_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        try:
            for dist_folder, is_lite, label in dist_targets:
                if not os.path.exists(os.path.dirname(dist_folder)):
                    raise PublishStageError("Parent directory for {} does not exist: {}".format(
                        label, dist_folder))
                touched.append((dist_folder, label))
                self._sync_dist_repo(context, dist_folder, is_lite, label)

                # Written AFTER the sync (which wipes Apps/lib/EnneadTab and Installation/)
                # and BEFORE stage_05 commits, so the stamp rides the same auto-commit.
                # Never allowed to block the publish: a missing stamp only degrades version
                # reporting for one run, a skipped commit stops fleet updates entirely.
                try:
                    _write_dist_version_stamp(dist_folder, dist_version_stamp)
                except Exception as exc:
                    print("    Warning: failed to write DIST_VERSION.json for {}: {}".format(
                        label, exc))
                try:
                    _write_dist_manifest(dist_folder, dist_version_stamp)
                except Exception as exc:
                    print("    Warning: failed to write dist_manifest.json for {}: {}".format(
                        label, exc))

            # READMEs only AFTER every target synced. README.md sits at the dist root,
            # outside FOLDERS_TO_PROCESS, so writing it per target meant a crash while
            # staging Lite left EA_Dist's README modified -- a dirty tree the guard then
            # refuses every later publish on. _restore_dist_tree also restores it, for a
            # cancel that lands inside this short loop.
            for dist_folder, is_lite, label in dist_targets:
                try:
                    _write_dist_readme(dist_folder, is_lite, dist_version_stamp)
                except Exception as exc:
                    print("    Warning: failed to write README.md for {}: {}".format(
                        label, exc))
        except BaseException:
            # BaseException so a cancelled CI job (KeyboardInterrupt) repairs too.
            # Repair, then re-raise the ORIGINAL with a bare raise: the traceback is
            # preserved and stage_base prints it. Repair problems are printed, never
            # raised, so they cannot replace the real cause.
            restore_dist_repos(context, touched, "staging failed -- undoing this stage's own damage")
            raise
        finally:
            # Error-isolated: cleanup must never replace the exception that brought us
            # here, and a cleanup problem must not be silent either (global rule #13).
            for backup in self._exe_backup_dirs:
                parent = os.path.dirname(backup)
                try:
                    shutil.rmtree(parent, onerror=_force_writable_retry)
                except Exception as exc:
                    print("    Warning: could not remove temp exe backup {}: {}: {}".format(
                        parent, type(exc).__name__, exc))
            self._exe_backup_dirs = []

    def _sync_dist_repo(self, context, dist_folder, is_lite, label):
        """Synchronize OS repository into target distribution directory."""
        print("\nStaging content for {} at: {}".format(label, dist_folder))
        os.makedirs(dist_folder, exist_ok=True)

        folders_to_process = FOLDERS_TO_PROCESS

        # Accumulates across folders. It used to be rebound per folder, so the "[OK]
        # ... N files copied" line below reported only the LAST folder's count (and
        # raised UnboundLocalError if every folder hit the `continue`).
        files_to_copy = []
        copied_count = 0
        fail_after = _fault_inject_after()

        for folder in folders_to_process:
            exe_backup_dir = None
            src_exe_folder = os.path.join(context.os_repo_folder, EXE_PRODUCTS_REL)
            dist_exe_folder = os.path.join(dist_folder, EXE_PRODUCTS_REL)

            if folder == "Apps" and _count_exe_files(src_exe_folder) == 0 and _count_exe_files(dist_exe_folder) > 0:
                # OUTSIDE the dist repo, deliberately. This used to be
                # <dist_folder>/.publish_exe_products_backup -- inside the very tree the
                # publisher must leave clean. That directory is gitignored in NEITHER dist
                # repo (verified: `git check-ignore` exits 1 in EA_Dist, EA_Dist_Lite and
                # here), so an orphan left behind was UNTRACKED, and publish_guard's dirty
                # predicate counts any porcelain output (publish_guard.py:306-308) -- one
                # leftover refused every later publish. Worse, it sat at the repo ROOT,
                # outside the FOLDERS_TO_PROCESS pathspec that _restore_dist_tree cleans,
                # so neither the crash-repair nor `git checkout -- .` nor the documented
                # #4456 manual procedure could clear it. And if a file survived in it,
                # stage_05's `git add -A` would have COMMITTED AND FORCE-PUSHED the backup
                # to the fleet.
                #
                # A temp dir cannot be any of that: it is not in the repo, so it cannot
                # appear in porcelain, cannot be committed, and needs no .gitignore change
                # in two repos this PR does not touch. The defect stops existing rather
                # than being compensated for. senzhang-todo #4657.
                exe_backup_dir = os.path.join(
                    tempfile.mkdtemp(prefix="enneadtab-publish-exe-"), "ExeProducts")
                self._exe_backup_dirs.append(exe_backup_dir)
                shutil.copytree(dist_exe_folder, exe_backup_dir)
                print("    Preserving {} existing dist exes at {}".format(
                    _count_exe_files(dist_exe_folder), exe_backup_dir))

            dest_subfolder = os.path.join(dist_folder, folder)
            src_subfolder = os.path.join(context.os_repo_folder, folder)

            # A missing source folder used to `continue`, which left dest_subfolder WIPED
            # AND NOT REPOPULATED -- the whole folder then got committed as deleted and
            # force-pushed to the fleet, with the stage still reporting OK. There is no
            # legitimate case for it: FOLDERS_TO_PROCESS is a fixed three-element list and
            # the publisher clone is a reset --hard checkout of the OS repo.
            if not os.path.exists(src_subfolder):
                raise PublishStageError(
                    "{}: source folder {} does not exist. Staging it would publish an empty "
                    "{}/ to the fleet.".format(label, src_subfolder, folder))

            # PLAN BEFORE DESTROYING. The walk reads SOURCE only, so doing it first makes
            # every source-read failure non-destructive: the dist tree is still intact and
            # nothing needs repairing. Wiping first meant a source problem destroyed the
            # DESTINATION and then leaned on the crash-repair to put it back.
            #
            # os.walk swallows errors by default: an unreadable subtree is SKIPPED SILENTLY
            # and simply never appears in folder_files, so the distribution ships short a
            # whole directory with nothing raised and a green check. onerror makes that loud.
            folder_files = []
            walk_errors = []
            for root, dirs, files in os.walk(src_subfolder, onerror=walk_errors.append):
                # dirs[:] = [] PRUNES the walk. Without it os.walk still DESCENDS into these
                # excluded subtrees, so an unreadable directory inside one of them would
                # abort the publish over content that was never going to ship -- an
                # availability regression with no correctness gain.
                #
                # path_excluded_from_target is the SAME predicate stage_03's path-length
                # scan calls to reproduce this decision at scan-time (senzhang-todo #4747)
                # -- consolidated here so there is exactly one copy of these rules, not two
                # that can silently drift.
                rel_root = os.path.relpath(root, src_subfolder)
                if path_excluded_from_target(rel_root, is_lite):
                    dirs[:] = []
                    continue

                for filename in files:
                    rel_file = filename if rel_root == "." else os.path.join(rel_root, filename)
                    if path_excluded_from_target(rel_file, is_lite):
                        continue

                    src_file = os.path.join(root, filename)
                    rel_path = os.path.relpath(src_file, src_subfolder)
                    dest_file = os.path.join(dest_subfolder, rel_path)
                    folder_files.append((src_file, dest_file))

            if walk_errors:
                detail = "; ".join("{}: {}".format(getattr(e, "filename", "?"), e)
                                   for e in walk_errors[:5])
                raise PublishStageError(
                    "{}: could not read {} director(ies) under {} -- their contents would be "
                    "MISSING from the published distribution, with no other symptom. "
                    "First few: {}".format(label, len(walk_errors), src_subfolder, detail))

            # Empty-plan floor. Wiping the destination and copying nothing back publishes an
            # empty folder to the fleet, and every count-based check downstream reads 0 == 0
            # and agrees. The catastrophic case is exactly the one a "did everything match?"
            # assertion cannot see, so it needs its own predicate.
            if not folder_files:
                raise PublishStageError(
                    "{}: planned ZERO files to stage for {}/ from {}. Wiping the destination "
                    "and copying nothing back would publish an empty {}/ to the fleet.".format(
                        label, folder, src_subfolder, folder))

            # Only now destroy. Everything above is read-only against SOURCE.
            # A file that survives this wipe survives into the published distribution: the
            # copy loop only writes paths present in SOURCE and never removes extras.
            removal_failures = try_remove_content(dest_subfolder)
            if removal_failures:
                detail = "; ".join("{} ({})".format(p, e) for p, e in removal_failures[:5])
                raise PublishStageError(
                    "{}: could not clear {} path(s) under {} -- they would persist into the "
                    "published distribution as stale content. First few: {}".format(
                        label, len(removal_failures), dest_subfolder, detail))
            os.makedirs(dest_subfolder, exist_ok=True)

            files_to_copy.extend(folder_files)

            for src_file, dest_file in folder_files:
                os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                shutil.copy2(src_file, dest_file)
                copied_count += 1
                if fail_after is not None and copied_count >= fail_after:
                    raise PublishStageError(
                        "FAULT INJECTION ({}={}): deliberately failing after {} copied "
                        "files to exercise the crash-restore path. This is a test, and it "
                        "only ever arms in a rehearsal.".format(
                            FAULT_INJECT_ENV, fail_after, copied_count))

            if exe_backup_dir and os.path.isdir(exe_backup_dir):
                if _count_exe_files(dist_exe_folder) == 0:
                    # REMOVE the destination before copying rather than relying on
                    # copytree's dirs_exist_ok. dirs_exist_ok is 3.8+, and the publisher
                    # and rehearsal clones do not run the same interpreter (measured
                    # 2026-08-21: production 3.13.14 from the Microsoft Store, rehearsal
                    # 3.11.9) -- remove-then-copy is version-agnostic and does not quietly
                    # depend on that staying true when a clone venv is rebuilt.
                    if os.path.isdir(dist_exe_folder):
                        shutil.rmtree(dist_exe_folder, onerror=_force_writable_retry)
                    os.makedirs(os.path.dirname(dist_exe_folder), exist_ok=True)
                    shutil.copytree(exe_backup_dir, dist_exe_folder)
                    print("    Restored dist ExeProducts from backup")

        # Final assertion: every file the plan named is on disk.
        #
        # Note what this does and does NOT cover. It compares the result against the PLAN,
        # so on its own it is vacuous when the plan is empty -- 0 planned, 0 missing, green.
        # The empty case is caught earlier, by the per-folder zero floor and the missing
        # source raise, NOT here. Those three together are what make the staged tree equal
        # the filtered source; this line alone guarantees nothing about completeness.
        missing = [d for _, d in files_to_copy if not os.path.exists(d)]
        if missing:
            raise PublishStageError(
                "{}: {} of {} staged file(s) are not on disk after copying -- the "
                "distribution is incomplete and must not be published. First few: {}".format(
                    label, len(missing), len(files_to_copy), "; ".join(missing[:5])))

        print("[OK] Staging complete for {} ({} files copied, {} verified present).".format(
            label, copied_count, len(files_to_copy)))
