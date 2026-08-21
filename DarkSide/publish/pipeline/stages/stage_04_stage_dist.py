# -*- coding: utf-8 -*-
"""Stage 04: Staging Distribution Repositories (EA_Dist & EA_Dist_Lite)."""

import os
import shutil
import stat
import subprocess
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
        try:
            for dist_folder, is_lite, label in dist_targets:
                if not os.path.exists(os.path.dirname(dist_folder)):
                    raise PublishStageError("Parent directory for {} does not exist: {}".format(
                        label, dist_folder))
                touched.append((dist_folder, label))
                self._sync_dist_repo(context, dist_folder, is_lite, label)
        except BaseException:
            # BaseException so a cancelled CI job (KeyboardInterrupt) repairs too.
            # Repair, then re-raise the ORIGINAL with a bare raise: the traceback is
            # preserved and stage_base prints it. Repair problems are printed, never
            # raised, so they cannot replace the real cause.
            restore_dist_repos(context, touched, "staging failed -- undoing this stage's own damage")
            raise

    def _sync_dist_repo(self, context, dist_folder, is_lite, label):
        """Synchronize OS repository into target distribution directory."""
        print("\nStaging content for {} at: {}".format(label, dist_folder))
        os.makedirs(dist_folder, exist_ok=True)

        folders_to_process = FOLDERS_TO_PROCESS
        lite_skip_folders = ["DuckMaker.extension", "_cad", "_engine", "DumpScripts", "dependency"]
        lite_allowed_exes = [
            "EnneadTab_OS_Installer.exe",
            "EnneadTab_OS_UnInstaller.exe",
            "EnneadTab_For_Revit_Installer.exe",
            "EnneadTab_For_Revit_UnInstaller.exe",
            "Emailer.exe",
            "NotificationHost.exe",
            "ProgressBar.exe",
        ]

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
                exe_backup_dir = os.path.join(dist_folder, ".publish_exe_products_backup")
                if os.path.exists(exe_backup_dir):
                    # Surfaced, not fatal: this is scratch, and copytree below reports the
                    # real consequence (it has no dirs_exist_ok, so leftovers make it raise).
                    # The wider redesign of this backup window is senzhang-todo #4657.
                    for p, e in try_remove_content(exe_backup_dir):
                        print("    Warning: leftover in exe backup, could not remove {}: {}".format(p, e))
                shutil.copytree(dist_exe_folder, exe_backup_dir)
                print("    Preserving {} existing dist exes".format(_count_exe_files(dist_exe_folder)))

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
                if is_lite and any(skip.lower() in root.lower() for skip in lite_skip_folders):
                    dirs[:] = []
                    continue
                if "DuckMaker.extension" in root:
                    dirs[:] = []
                    continue

                for filename in files:
                    if is_lite:
                        if filename.lower().endswith(".exe") and filename not in lite_allowed_exes:
                            continue
                        if any(ext in filename.lower() for ext in [".dll", ".psd", ".ai"]):
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
                    os.makedirs(os.path.dirname(dist_exe_folder), exist_ok=True)
                    shutil.copytree(exe_backup_dir, dist_exe_folder)
                    print("    Restored dist ExeProducts from backup")
                # An orphaned backup dir is untracked and NOT gitignored in older dist
                # clones, and publish_guard counts untracked as dirty -- so leftovers here
                # can refuse the NEXT publish. Say so rather than dropping it. (#4657)
                for p, e in try_remove_content(exe_backup_dir):
                    print("    Warning: could not clean up exe backup {}: {}".format(p, e))

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
