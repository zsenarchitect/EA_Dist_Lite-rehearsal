# -*- coding: utf-8 -*-
"""The exact set of paths the AutoDist publisher may stage in its own checkout.

WHY THIS EXISTS (senzhang-todo #2372)
-------------------------------------
_schedule_publish.py used to run `git add .` from the repo root -- twice: in
git_pull_main() (a "temp commit before merge", every ~10 min in active mode) and in
push_back_to_github(). That stages ANYTHING written anywhere in the EnneadTab-OS
checkout -- a scratch file, a half-finished edit, an agent's deliberately malformed
test fixture -- and commits it on main with no human in the loop. It has already
swept malformed button scripts into a commit.

The publisher only legitimately produces a small, knowable set of files in its own
tree. Everything it writes comes from the live 7-stage pipeline
(DarkSide/publish/pipeline/stages/):

  * stage_02 _mirror_service_factory_installers: copies Installation/*installer*.exe
    to Apps/lib/ExeProducts/<same name>
  * stage_02 _generate_exe_hashes:               Installation/exe_hash.json
  * stage_03 _generate_pdf_handbooks:            Installation/EnneadTab_For_{Revit,Rhino}_HandBook.pdf
                                                 (DOCUMENTATION.generate_documentation)
  * stage_03 _generate_readmes:                  README.md (repo root)

Scheduler state files (publish_history.json, scheduler_state.json, ...) are
git-ignored, so they never appear in `git status`. stage_04+ write only into the
sibling EA_Dist / EA_Dist_Lite repos, outside this checkout.

If a generator starts writing somewhere new, add the path HERE. A missed path is
loud (reported as foreign, left uncommitted) -- never silently swept in.

CPython 3 only (the scheduler is CPython); kept free of tkinter/winsound so it can be
unit-tested anywhere.
"""

import os
import subprocess

EXACT_GENERATED_PATHS = frozenset((
    "README.md",
    "Installation/exe_hash.json",
    "Installation/EnneadTab_For_Revit_HandBook.pdf",
    "Installation/EnneadTab_For_Rhino_HandBook.pdf",
))

EXE_PRODUCTS_PREFIX = "Apps/lib/ExeProducts/"


def mirrored_installer_names(repo_dir):
    """Lower-cased names stage_02 mirrors from Installation/ into ExeProducts/."""
    installation = os.path.join(repo_dir, "Installation")
    try:
        names = os.listdir(installation)
    except OSError:
        return frozenset()
    return frozenset(
        n.lower() for n in names
        if n.lower().endswith(".exe") and "installer" in n.lower())


def is_generated(path, installer_names):
    """True if `path` (repo-relative, any separator) is a publisher-generated file."""
    norm = path.replace("\\", "/").strip()
    if norm.startswith('"') and norm.endswith('"'):
        norm = norm[1:-1]
    if norm in EXACT_GENERATED_PATHS:
        return True
    if norm.startswith(EXE_PRODUCTS_PREFIX):
        name = norm[len(EXE_PRODUCTS_PREFIX):]
        return "/" not in name and name.lower() in installer_names
    return False


def parse_porcelain_z(output):
    """Paths from `git status --porcelain -z --untracked-files=all` output.

    A rename/copy record ("R  new\\0old") is followed by its ORIGINAL path as a
    separate NUL field; that field is consumed so it is not misread as a record.
    Both the new and the original path are returned -- either side touching a
    foreign path makes the change foreign.
    """
    paths = []
    fields = (output or "").split("\0")
    i = 0
    while i < len(fields):
        record = fields[i]
        i += 1
        if len(record) < 4:
            continue
        status, path = record[:2], record[3:]
        paths.append(path)
        if status[0] in "RC" or status[1] in "RC":
            if i < len(fields) and fields[i]:
                paths.append(fields[i])
            i += 1
    return paths


def classify(paths, installer_names):
    """Split dirty paths into (generated, foreign), preserving order."""
    generated, foreign = [], []
    for p in paths:
        (generated if is_generated(p, installer_names) else foreign).append(p)
    return generated, foreign


def dirty_paths(git_exe, repo_dir, timeout=120):
    """Every dirty path in the checkout (raises RuntimeError if status fails).

    -uall is load-bearing: by default git collapses an untracked directory into one
    entry ("Apps/foo/"), which would hide what is actually in it.
    """
    res = subprocess.run(
        [git_exe, "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=repo_dir, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError("git status failed (rc={}): {}".format(
            res.returncode, (res.stderr or "").strip()[:300]))
    return parse_porcelain_z(res.stdout)


def stage_generated(git_exe, repo_dir, timeout=120):
    """Stage ONLY publisher-generated paths. Returns (staged, foreign).

    Never `git add -A` / `git add .`. Foreign paths are left exactly as they are --
    not staged, not deleted -- for the caller to report.
    Raises RuntimeError if git status or git add fails.
    """
    generated, foreign = classify(
        dirty_paths(git_exe, repo_dir, timeout=timeout),
        mirrored_installer_names(repo_dir))
    if generated:
        res = subprocess.run(
            [git_exe, "add", "--"] + generated,
            cwd=repo_dir, capture_output=True, text=True, timeout=timeout)
        if res.returncode != 0:
            raise RuntimeError("git add failed (rc={}): {}".format(
                res.returncode, (res.stderr or "").strip()[:500]))
    return generated, foreign


def describe_foreign(foreign, limit=10):
    """One-line operator message for paths the publisher refused to commit."""
    shown = ", ".join(foreign[:limit])
    more = "" if len(foreign) <= limit else " (+{} more)".format(len(foreign) - limit)
    return ("AutoDist: {} uncommitted change(s) in the publisher checkout are NOT "
            "publisher-generated and were NOT committed: {}{}. Something other than "
            "the publisher wrote here -- resolve them by hand.".format(
                len(foreign), shown, more))
