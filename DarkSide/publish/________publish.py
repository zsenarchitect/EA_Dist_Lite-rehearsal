"""EnneadTab-OS publish entry point.

run-ci-publish.ps1 (CI) and a human running this file directly both land in
`publish()` below, which builds the 8-stage pipeline under pipeline/stages/.

This file used to be a ~4,300-line monolith (RepoPublisher, a second shadowed
publish(), push/repair helpers, tk dialogs). PR #176 (2026-08-18) moved every live
step into pipeline/stages/ and nothing has constructed RepoPublisher since. That
dead copy was removed in the old-publisher phase-out, Milestone 2
(docs/plans/2026-08-18-old-publisher-phaseout-epic.md). It cost real time while it
lived: fixes landed in it and silently ran against nothing (DIST_VERSION.json,
#2391; the EA_Dist README writer). Recover it from git history if ever needed, but
port behavior into a stage, never back into this file.
"""

import os
import sys

# Enable ANSI escape codes and proper Unicode handling on Windows
if os.name == 'nt':
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    
    # Force UTF-8 encoding for console output
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace') #pyright: ignore
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace') #pyright: ignore
    except (AttributeError, OSError):
        # Fallback for older Python versions or when reconfigure is not available
        pass
    
    # Set environment variable for subprocesses
    os.environ['PYTHONIOENCODING'] = 'utf-8'


# Setup paths
def find_repo_folder(start_folder=None):
    """
    Locates the repository root folder by traversing directory hierarchy.

    Searches upward through parent directories until finding a folder containing
    'EnneadTab-OS' or 'EA_Dist' in its name. This ensures scripts can run from
    any subdirectory while maintaining correct relative paths.

    If no ancestor carries either substring, falls back to the structural root:
    this file lives at <root>/DarkSide/publish/, so <root> is two levels up, and
    is accepted only when it really holds both Apps/ and DarkSide/. The name-only
    heuristic crashed rehearsal publish when the dedicated clone was renamed to
    REHEARSAL_NO_WORK_INSIDE (senzhang-todo TODO-5445, run 32307103724); a
    clone's folder name is an operator choice, the repo layout is not.

    Returns:
        str: Absolute path to the repository root folder

    Raises:
        Exception: If neither the name heuristic nor the layout check matches
    """
    if start_folder is None:
        start_folder = os.path.dirname(os.path.abspath(__file__))
    current_folder = start_folder
    while True:
        if any(name in os.path.basename(current_folder) for name in ["EnneadTab-OS", "EA_Dist"]):
            return current_folder
        parent_folder = os.path.dirname(current_folder)
        if parent_folder == current_folder:  # Reached the root directory
            break
        current_folder = parent_folder
    structural_root = os.path.normpath(os.path.join(start_folder, "..", ".."))
    if (os.path.isdir(os.path.join(structural_root, "Apps"))
            and os.path.isdir(os.path.join(structural_root, "DarkSide"))):
        return structural_root
    raise Exception(
        "Could not find a folder with 'EnneadTab-OS' or 'EA_Dist' in the name, "
        "and {} does not look like the repo root (no Apps/ + DarkSide/).".format(structural_root))


OS_REPO_FOLDER = find_repo_folder()
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DARKSIDE_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, ".."))

# RuiWriter, WikiBuilder, and other DarkSide packages import by bare name.
# This used to be a side effect of `from ei_pdf_uploader.main import ...`
# (retired 2026-08-11). Dropping that import dropped DarkSide from sys.path,
# so `import RuiWriter` failed with ModuleNotFoundError and the publish
# aborted. Put it back explicitly.
if DARKSIDE_DIR not in sys.path:
    sys.path.insert(0, DARKSIDE_DIR)
sys.path.append(OS_REPO_FOLDER + "\\Apps\\lib")


# Only ENVIRONMENT is still needed here (git location check below). The stages
# import whatever EnneadTab modules they use themselves.
from EnneadTab import ENVIRONMENT #pyright: ignore


class NoGoodSetupException(Exception):
    def __init__(self):
        super().__init__("The setup is not complete or you are working on a new computer.")

# Locate Git executable
locations = [
    "{}\\Local\\Programs\\Git\\cmd\\git.exe".format(ENVIRONMENT.USER_APPDATA_FOLDER),
    "C:\\Program Files\\Git\\cmd\\git.exe"
]
for location in locations:
    if os.path.exists(location):
        GIT_LOCATION = location
        break
else:
    raise NoGoodSetupException()


def remove_other_git_lock_and_action_files():
    """ 
    Remove other git lock and action files.
    """
    print("Begin removing other git lock and action files...")
    
    # Use the OS_REPO_FOLDER variable instead of the long relative path
    git_folder = os.path.join(OS_REPO_FOLDER, ".git")
    
    if not os.path.exists(git_folder):
        print("Git folder not found, skipping lock file removal...")
        return
    
    # List of common git lock files to remove
    lock_files = [
        "index.lock",
        "MERGE_HEAD.lock", 
        "refs/heads/main.lock",
        "refs/heads/master.lock",
        "HEAD.lock"
    ]
    
    removed_count = 0
    for lock_file in lock_files:
        lock_path = os.path.join(git_folder, lock_file)
        if os.path.exists(lock_path):
            try:
                os.chmod(lock_path, 0o777)  # Ensure we have permissions
                os.remove(lock_path)
                print(f"Removed lock file: {lock_file}")
                removed_count += 1
            except Exception as e:
                print(f"Warning: Could not remove {lock_file}: {e}")
    
    if removed_count == 0:
        print("No git lock files found to remove.")
    else:
        print(f"Removed {removed_count} git lock files.")

def publish(is_production=False, mode=None):
    """Execute modern modular publish pipeline for EnneadTab-OS."""
    if mode is None:
        mode = os.environ.get("ENNEADTAB_PUBLISH_MODE", "manual").lower()

    # Import Pipeline modules
    from pipeline.context import PublishContext
    from pipeline.runner import PipelineRunner
    from pipeline.stages.stage_01_preflight import PreflightStage
    from pipeline.stages.stage_02_build_assets import BuildAssetsStage
    from pipeline.stages.stage_03_docs_wiki import DocsWikiStage
    from pipeline.stages.stage_03b_wiki_ingest import WikiIngestStage
    from pipeline.stages.stage_04_stage_dist import StageDistStage
    from pipeline.stages.stage_05_git_push import GitPushStage
    from pipeline.stages.stage_06_rollback_tags import RollbackTagsStage
    from pipeline.stages.stage_07_notify import NotifyStage

    ctx = PublishContext(
        os_repo_folder=OS_REPO_FOLDER,
        mode=mode,
        is_production=is_production,
    )

    runner = PipelineRunner(ctx)
    runner.add_stage(PreflightStage())
    runner.add_stage(BuildAssetsStage())
    runner.add_stage(DocsWikiStage())
    runner.add_stage(WikiIngestStage())
    runner.add_stage(StageDistStage())
    runner.add_stage(GitPushStage())
    runner.add_stage(RollbackTagsStage())
    runner.add_stage(NotifyStage())

    try:
        runner.run()
        return True
    except SystemExit as e:
        return e.code == 0
    except Exception as e:
        print("[CI RED] Publish Pipeline failed with unhandled exception: {}".format(e))
        return False


if __name__ == '__main__':
    remove_other_git_lock_and_action_files()
    sys.exit(0 if publish() else 1)
