import os
import shutil
import subprocess
import time
import traceback
import sys
import tkinter as tk
import re
import gc  # Add garbage collection module
import json
import threading  # Add threading module for background backup
import datetime

# Enable ANSI escape codes and proper Unicode handling on Windows
if os.name == 'nt':
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    
    # Set UTF-8 encoding for stdout and stderr
    import codecs
    import sys
    
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

# Git executable path detection
def get_git_executable():
    """Get the full path to git executable."""
    git_paths = [
        r"C:\Users\szhang\AppData\Local\Programs\Git\bin\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
        r"C:\Program Files (x86)\Git\bin\git.exe"
    ]
    
    for git_path in git_paths:
        if os.path.exists(git_path):
            return git_path
    
    # Fallback to just 'git' if none found
    return "git"


def clear_stale_git_locks(repo_folder):
    """Remove stale .git lock files for ONE repo. Replaces a machine-wide taskkill.

    This publisher used to kill every git.exe on the machine by image name
    (no PID filter) at nine separate places. That kills EVERY git process,
    not just this publisher's. It was survivable when the publisher owned a
    dedicated box. It is not survivable now: this machine hosts 16 self-hosted CI
    runners plus interactive work, so a publish would force-kill unrelated jobs'
    checkouts mid-operation and leave THEIR repositories with torn indexes -- and
    those jobs would fail for reasons that look nothing like "a publish ran".

    The actual goal was only ever to clear a stale lock left behind by a crashed
    git. That is a per-repo, file-scoped operation, and this is it.

    Returns the list of lock filenames removed (empty when there was nothing to do).
    """
    removed = []
    git_dir = os.path.join(repo_folder, ".git")
    if not os.path.isdir(git_dir):
        return removed
    for lock_name in ("index.lock", "HEAD.lock", "config.lock", "packed-refs.lock"):
        lock_path = os.path.join(git_dir, lock_name)
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
                removed.append(lock_name)
            except OSError as exc:
                print("    Warning: could not remove {}: {}".format(lock_name, exc))
    if removed:
        print("    Cleared stale git lock(s) in {}: {}".format(
            os.path.basename(repo_folder.rstrip("\\/")), ", ".join(removed)))
    return removed


def find_ironpython_executable():
    """Locate an IronPython 2.7 interpreter to use as the syntax oracle.

    The shipped Apps/_revit, Apps/_rhino and Apps/lib/EnneadTab code runs under
    IronPython 2.7, so IronPython (not the CPython 3 interpreter running this
    publisher) is the only correct oracle for its syntax: CPython 3 would both
    false-reject valid Py2 idioms (print statement, .None attribute access) and
    false-accept the exact Py3-only constructs (f-strings, type hints) that
    break IronPython at load time. pyRevit bundles IronPython on the publish
    box, so it is normally present.

    Returns:
        str or None: path/name of a working IronPython exe, or None if none found.
    """
    override = os.environ.get("ENNEADTAB_IRONPYTHON_EXE", "").strip()
    candidates = []
    if override:
        candidates.append(override)
    candidates.extend([
        "ipy", "ipy.exe", "ipy64", "ipy64.exe",
        r"C:\Program Files\IronPython 2.7\ipy.exe",
        r"C:\Program Files (x86)\IronPython 2.7\ipy.exe",
    ])
    # Per-user install location. The machine-wide paths above need admin rights to
    # write, so a box without them (this publisher, 2026-08-07) installs the zip
    # release under LOCALAPPDATA instead. Listing it here means the gate works
    # without anyone remembering to set ENNEADTAB_IRONPYTHON_EXE -- including for
    # CI runner processes that started before the variable existed.
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        for version in ("2.7.12", "2.7.11", "2.7"):
            candidates.append(os.path.join(
                local_app_data, "IronPython", version, "net45", "ipy.exe"))
    for candidate in candidates:
        try:
            subprocess.check_output([candidate, "-V"], stderr=subprocess.STDOUT, timeout=15)
            return candidate
        except Exception:
            continue
    return None


class PublishValidationError(Exception):
    """Raised when a pre-publish safety gate refuses to ship the current tree."""
    pass


# Setup paths
def find_repo_folder():
    """
    Locates the repository root folder by traversing directory hierarchy.
    
    Searches upward through parent directories until finding a folder containing
    'EnneadTab-OS' or 'EA_Dist' in its name. This ensures scripts can run from
    any subdirectory while maintaining correct relative paths.
    
    Returns:
        str: Absolute path to the repository root folder
        
    Raises:
        Exception: If no matching folder is found in path hierarchy
    """
    current_folder = os.path.dirname(__file__)
    while True:
        if any(name in os.path.basename(current_folder) for name in ["EnneadTab-OS", "EA_Dist"]):
            return current_folder
        parent_folder = os.path.dirname(current_folder)
        if parent_folder == current_folder:  # Reached the root directory
            raise Exception("Could not find a folder with 'EnneadTab-OS' or 'EA_Dist' in the name.")
        current_folder = parent_folder

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

from EnneadTab import NOTIFICATION, SOUND, ENVIRONMENT, DOCUMENTATION, TIME, JOKE, EXE, INTEGRITY #pyright: ignore

PUBLISH_MODE = os.environ.get("ENNEADTAB_PUBLISH_MODE", "manual").lower()
IS_SCHEDULER_MODE = PUBLISH_MODE == "scheduler"
# ENNEADTAB_PUBLISH_CI is kept as a marker other tooling may set. Kill policy
# no longer branches on it: hung git is always reaped by ancestry of THIS
# publish process, never by image name. A machine-wide git kill is unsafe on
# this box (16 self-hosted runners plus interactive shells share one OS
# process table).
IS_CI_MODE = os.environ.get("ENNEADTAB_PUBLISH_CI", "").strip().lower() in ("1", "true", "yes")


def _reap_own_git(root_pid=None):
    """Kill ONLY git.exe processes descended from this publish process.

    Scoped strictly by live process ancestry (never a machine-wide taskkill and
    never a CommandLine/cwd match), so on a shared runner box it is impossible to
    kill another runner's git. No-op if psutil is unavailable -- killing nothing
    is always the safe fallback on a shared box. Known gap: a git grandchild
    (e.g. git-remote-https) reparented after its direct git.exe was killed on
    timeout can be orphaned off this ancestry tree and thus missed -- a
    completeness gap, not a safety one.
    """
    try:
        import psutil
    except Exception:
        return
    try:
        parent = psutil.Process(root_pid or os.getpid())
        descendants = parent.children(recursive=True)
    except Exception:
        return
    killed = 0
    for child in descendants:
        try:
            if (child.name() or "").lower() == "git.exe":
                child.kill()
                killed += 1
        except Exception:
            continue
    if killed:
        print("    Reaped {} stray git.exe descendant(s) of this publish process.".format(killed))


def _kill_stray_git():
    """Clear a hung/stray git before a force-push. ALWAYS process-scoped.

    Previously this killed every git.exe on the machine by image name unless
    ENNEADTAB_PUBLISH_CI was set, on the premise that a workstation publisher is
    the sole git owner on its box.

    That premise no longer holds anywhere we publish from. The machine that hosts
    the publisher also hosts 16 self-hosted CI runners and the operator's own
    shell, so it is a workstation AND a runner host simultaneously. Under the old
    shape, a manual publish that simply forgot the env var would kill git in every
    concurrent job -- and those jobs fail for reasons that look nothing like "a
    publish ran". An opt-in guard against a destructive default is the kind of
    protection that is correct in the diagram and missing in practice.

    Reaping only our own descendants is strictly safer and loses nothing: a git
    this publisher did not start is, by definition, not this publisher's to kill.
    """
    _reap_own_git()


# Hard wall-clock ceiling for the WHOLE publish run so a single hung in-flight
# git push cannot blow past the CI job timeout. Anchored at module import: this
# script is the CI / manual entry (`________publish.py`), so import ~= the
# start of the publish. Each push strategy's own subprocess timeout is
# additionally clamped to the budget remaining here (see reset_and_force_push).
PUBLISH_START_TIME = time.time()
try:
    PUBLISH_MAX_SECONDS = int(os.environ.get("ENNEADTAB_PUBLISH_MAX_SECONDS", "4500"))
except (TypeError, ValueError):
    PUBLISH_MAX_SECONDS = 4500


def _remaining_publish_seconds():
    """Seconds left in the total publish wall-clock budget (may go negative)."""
    return PUBLISH_MAX_SECONDS - (time.time() - PUBLISH_START_TIME)

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

def time_it(func):
    """
    Decorator that measures and reports execution time of operations.
    
    Wraps functions to:
    - Track start and end times
    - Calculate and display execution duration
    - Show completion notification with duck animation
    - Play success sound effect
    - Clean up memory after operation
    
    Args:
        func: Function to be timed and monitored
        
    Returns:
        wrapper: Decorated function that includes timing functionality
    """
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed_time = end_time - start_time
        elapsed_time = TIME.get_readable_time(elapsed_time)
        blue_text = "\033[34m"
        reset_color = "\033[0m"
        
        # Report the OUTCOME, not just the duration.
        #
        # This used to print "Publish took X to complete", pop a duck saying the
        # same, and play the success sound UNCONDITIONALLY -- whatever the wrapped
        # function returned. Once publish() started returning False on a failed
        # push, that meant a failed publish exited non-zero while simultaneously
        # announcing success to the operator, with a celebratory sound. The
        # machine-readable signal was honest and the human-facing one was not,
        # which is the worse half to get wrong: nobody reads exit codes off a
        # workstation, they hear the sound and walk away.
        #
        # Only `False` counts as failure. RepoPublisher.publish returns None and
        # signals failure by raising, so None must stay on the success path.
        succeeded = result is not False
        red_text = "\033[31m"

        if succeeded:
            print("\n\n{}Publish took {} to complete.{}\n\n".format(
                blue_text, elapsed_time, reset_color))
            NOTIFICATION.duck_pop("Publish took {} to complete.".format(elapsed_time))
            # Call directly - function already has try-except
            play_success_sound()
        else:
            print("\n\n{}Publish FAILED after {}. Nothing was published.{}\n\n".format(
                red_text, elapsed_time, reset_color))
            NOTIFICATION.duck_pop("Publish FAILED after {}.".format(elapsed_time))

        # Clean up memory after operation
        gc.collect()
        return result
    return wrapper

def commit_changes(repo_path, commit_message="Auto-commit: Update repository files"):
    """
    Commit changes in the repository with improved error handling.
    
    Args:
        repo_path (str): Path to the repository
        commit_message (str): Custom commit message (optional)
        
    Returns:
        bool: True if successful, False otherwise
    """
    import time
    # Add timestamp to commit message
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    if not commit_message.endswith(timestamp):
        commit_message = f"{commit_message} at {timestamp}"
    try:
        # Proactively kill any running git.exe processes before critical operations
        print("    Checking for running git.exe processes to avoid conflicts...")
        try:
            _kill_stray_git()
            clear_stale_git_locks(repo_path)
        except Exception as e:
            print(f"    Warning: Could not clear stale git locks: {e}")
        
        # Check for and remove any existing lock files, with retry logic
        lock_file = os.path.join(repo_path, ".git", "index.lock")
        max_retries = 3
        for attempt in range(max_retries):
            if os.path.exists(lock_file):
                print(f"    Attempt {attempt+1}/{max_retries}: Removing existing git lock file...")
                try:
                    os.chmod(lock_file, 0o777)  # Ensure we have full permissions
                    os.remove(lock_file)
                    print("    Lock file removed successfully.")
                    break
                except Exception as e:
                    print(f"    Warning: Could not remove lock file: {e}")
                    # Try to terminate git processes again
                    try:
                        _kill_stray_git()
                        clear_stale_git_locks(repo_path)
                    except Exception:
                        print("    Could not clear stale git locks or remove lock file")
                    if attempt < max_retries - 1:
                        print("    Waiting 10 seconds before retrying lock file removal...")
                        time.sleep(10)
                    else:
                        print("    Failed to remove lock file after multiple attempts. Aborting commit.")
                        return False
            else:
                break
        
        # Add all changes with increased timeout
        print("    Adding changes to git...")
        try:
            _kill_stray_git()
            clear_stale_git_locks(repo_path)
        except Exception:
            pass
        add_result = subprocess.call(
            [get_git_executable(), "add", "."],
            cwd=repo_path,
            timeout=180  # Increased from 30 to 180 seconds
        )
        
        if add_result != 0:
            raise Exception("Git add command failed with return code {}".format(add_result))
        
        # Commit changes with increased timeout
        print("    Committing changes...")
        try:
            _kill_stray_git()
            clear_stale_git_locks(repo_path)
        except Exception:
            pass
        commit_result = subprocess.call(
            [get_git_executable(), "commit", "-m", commit_message],
            cwd=repo_path,
            timeout=180  # Increased from 30 to 180 seconds
        )
        
        if commit_result != 0:
            # Non-zero could mean "nothing to commit" which is not an error
            if commit_result == 1:
                # Check if it's just "nothing to commit"
                print("    Nothing to commit - repository is up to date")
                return True
            else:
                raise Exception("Git commit command failed with return code {}".format(commit_result))
            
        return True
        
    except subprocess.TimeoutExpired:
        print("    Git operation timed out")
        return False
    except Exception as e:
        print("    An error occurred while committing changes")
        print("    {}".format(str(e)))
        return False

def try_remove_content(folder_path):
    """
    Safely removes content from a folder or file.
    
    Args:
        folder_path (str): Path to the folder or file to remove
    """
    if os.path.exists(folder_path):
        if os.path.isfile(folder_path):
            os.remove(folder_path)
        else:
            shutil.rmtree(folder_path)


def _count_exe_files(folder_path):
    """Return number of .exe files directly in folder_path (non-recursive)."""
    if not os.path.isdir(folder_path):
        return 0
    try:
        return len([f for f in os.listdir(folder_path) if f.lower().endswith(".exe")])
    except OSError:
        return 0


EXE_PRODUCTS_REL = os.path.join("Apps", "lib", "ExeProducts")



def diagnose_and_fix_push_issues(repo_folder):
    """
    Diagnose and attempt to fix common issues that cause push failures.
    
    Args:
        repo_folder (str): Path to the repository
        
    Returns:
        bool: True if issues were found and fixed, False otherwise
    """
    print("🔍 Diagnosing potential push issues...")
    issues_found = False
    
    # Set a timeout for the entire diagnosis process
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Diagnosis timed out")
    
    # Set timeout to 2 minutes
    try:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(120)
    except:
        # Windows doesn't support SIGALRM, we'll rely on individual timeouts
        pass
    
    try:
        # Check repository size
        print("📊 Checking repository size...")
        size_result = subprocess.run(
            [get_git_executable(), 'count-objects', '-vH'], 
            cwd=repo_folder, 
            capture_output=True, 
            text=True, 
            timeout=60
        )
        
        if size_result.returncode == 0:
            size_output = size_result.stdout
            print("Repository size info:")
            print(size_output)
            
            # Check for large pack files
            if "pack" in size_output.lower():
                pack_size_match = re.search(r'pack: (\d+(?:\.\d+)?)\s*(\w+)', size_output)
                if pack_size_match:
                    pack_size = float(pack_size_match.group(1))
                    pack_unit = pack_size_match.group(2)
                    
                    # Convert to MB for comparison
                    if pack_unit.lower() == 'gb':
                        pack_size_mb = pack_size * 1024
                    elif pack_unit.lower() == 'mb':
                        pack_size_mb = pack_size
                    else:
                        pack_size_mb = pack_size / 1024
                    
                    if pack_size_mb > 500:  # 500MB threshold
                        print("⚠️ Large repository detected ({} MB). This may cause push issues.".format(pack_size_mb))
                        issues_found = True
                        
                        # Try to optimize the repository
                        print("🔄 Attempting repository optimization...")
                        try:
                            # Aggressive garbage collection
                            subprocess.run([get_git_executable(), 'gc', '--aggressive', '--prune=now'], 
                                         cwd=repo_folder, 
                                         timeout=300)
                            print("✅ Repository optimization completed")
                        except Exception as e:
                            print("❌ Repository optimization failed: {}".format(str(e)))
        
        # Check for large files (simplified check)
        print("📁 Checking for large files...")
        try:
            # Use a faster approach - check only recent commits
            large_files_result = subprocess.run(
                [get_git_executable(), 'rev-list', '--objects', 'HEAD~10..HEAD'], 
                cwd=repo_folder, 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            if large_files_result.returncode == 0:
                # Quick check for obvious large files
                large_files = []
                for line in large_files_result.stdout.strip().split('\n'):
                    if ' ' in line and any(ext in line.lower() for ext in ['.exe', '.dll', '.zip', '.7z', '.rar']):
                        parts = line.split(' ')
                        if len(parts) >= 2:
                            file_hash = parts[0]
                            file_path = ' '.join(parts[1:])
                            
                            # Quick size check
                            try:
                                size_result = subprocess.run(
                                    [get_git_executable(), 'cat-file', '-s', file_hash], 
                                    cwd=repo_folder, 
                                    capture_output=True, 
                                    text=True, 
                                    timeout=10
                                )
                                
                                if size_result.returncode == 0:
                                    size = int(size_result.stdout.strip())
                                    if size > 100 * 1024 * 1024:  # 100MB threshold
                                        large_files.append((file_path, size))
                            except:
                                continue
                
                if large_files:
                    print("⚠️ Found {} large files (>100MB):".format(len(large_files)))
                    for file_path, size in sorted(large_files, key=lambda x: x[1], reverse=True)[:3]:
                        size_mb = size / (1024 * 1024)
                        print("   - {} ({:.1f} MB)".format(file_path, size_mb))
                    issues_found = True
                else:
                    print("✅ No obvious large files detected")
            else:
                print("⚠️ Could not check large files (timeout or error)")
        except subprocess.TimeoutExpired:
            print("⏰ Large file check timed out - skipping")
        except Exception as e:
            print("❌ Error checking large files: {}".format(str(e)))
        
        # Check Git configuration
        print("⚙️ Checking Git configuration...")
        config_checks = [
            'http.postBuffer',
            'http.maxRequestBuffer', 
            'core.compression',
            'http.lowSpeedLimit',
            'http.lowSpeedTime'
        ]
        
        for config in config_checks:
            try:
                result = subprocess.run(
                    [get_git_executable(), 'config', '--get', config], 
                    cwd=repo_folder, 
                    capture_output=True, 
                    text=True, 
                    timeout=30
                )
                
                if result.returncode == 0:
                    value = result.stdout.strip()
                    print("   {}: {}".format(config, value))
                else:
                    print("   {}: not set (using default)".format(config))
            except Exception as e:
                print("   {}: error checking - {}".format(config, str(e)))
        
        # Check network connectivity
        print("🌐 Checking network connectivity...")
        try:
            # Test GitHub connectivity
            ping_result = subprocess.run(
                ['ping', '-n', '3', 'github.com'], 
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            if ping_result.returncode == 0:
                print("✅ GitHub connectivity: OK")
            else:
                print("❌ GitHub connectivity: Failed")
                issues_found = True
        except Exception as e:
            print("❌ Network check failed: {}".format(str(e)))
            issues_found = True
        
        # Check for Git lock files
        print("🔒 Checking for lock files...")
        lock_files = [
            os.path.join(repo_folder, '.git', 'index.lock'),
            os.path.join(repo_folder, '.git', 'MERGE_HEAD.lock'),
            os.path.join(repo_folder, '.git', 'refs', 'heads', 'main.lock')
        ]
        
        for lock_file in lock_files:
            if os.path.exists(lock_file):
                print("⚠️ Found lock file: {}".format(lock_file))
                try:
                    os.remove(lock_file)
                    print("✅ Removed lock file: {}".format(lock_file))
                    issues_found = True
                except Exception as e:
                    print("❌ Failed to remove lock file: {}".format(str(e)))
        
        # Check repository status
        print("📋 Checking repository status...")
        try:
            status_result = subprocess.run(
                [get_git_executable(), 'status', '--porcelain'], 
                cwd=repo_folder, 
                capture_output=True, 
                text=True, 
                timeout=60
            )
            
            if status_result.returncode == 0:
                if status_result.stdout.strip():
                    print("⚠️ Repository has uncommitted changes:")
                    print(status_result.stdout)
                    issues_found = True
                else:
                    print("✅ Repository is clean")
        except Exception as e:
            print("❌ Error checking repository status: {}".format(str(e)))
        
        if issues_found:
            print("🔧 Issues were found and some were automatically fixed.")
            print("💡 Consider running 'git gc --aggressive' manually if push still fails.")
        else:
            print("✅ No obvious issues detected.")
        
        return issues_found
        
    except Exception as e:
        print("❌ Error during diagnosis: {}".format(str(e)))
        return False

def reset_and_force_push(repo_folder):
    """
    Implements a robust multi-strategy approach for force pushing changes to a git repository.
    
    This function employs progressive fallback strategies to handle challenging push scenarios,
    particularly with large repositories or unreliable network conditions.
    """
    try:
        lightweight_mode = IS_SCHEDULER_MODE
        max_push_duration = 1800 if lightweight_mode else None
        push_start_time = time.time()

        def _check_time_budget():
            if max_push_duration is not None:
                elapsed = time.time() - push_start_time
                if elapsed >= max_push_duration:
                    raise TimeoutError(f"Exceeded scheduler push time budget ({max_push_duration} seconds)")

        # First, diagnose and fix any obvious issues
        if lightweight_mode:
            print("Scheduler mode detected - skipping deep git diagnostics for speed.")
        else:
            try:
                diagnose_and_fix_push_issues(repo_folder)
            except Exception as e:
                print("⚠️ Diagnosis failed, continuing with push: {}".format(str(e)))
        
        # Enhanced Git configuration for better reliability
        configs = [
            ['core.compression', '0'],  # Disable compression
            ['http.postBuffer', '1048576000'],  # 1GB buffer (increased)
            ['http.maxRequestBuffer', '100M'],
            ['http.lowSpeedLimit', '500'],  # Reduced for better tolerance
            ['http.lowSpeedTime', '1200'],  # Increased timeout
            ['protocol.version', '2'],  # Use Git protocol v2
            ['pack.windowMemory', '200m'],  # Increased memory
            # Do NOT set pack.packSizeLimit. 200m was written here as "increased"
            # and persists in each dist clone's local config; on EA_Dist it
            # shards an 11 GB pack into hundreds of 200 MB packs, then gc/repack
            # needs ~2x free disk and fills the publisher box.
            ['gc.auto', '0'],
            ['pack.threads', '1'],
            ['core.bigFileThreshold', '100m'],  # Increased threshold
            # NOTE: transfer.fsckObjects=false and http.sslVerify=false used to be
            # set here. Both are removed deliberately and must not come back.
            #
            # These are written to each distribution repo's LOCAL config, so they
            # PERSIST for anyone who later pushes from that clone -- and those are
            # the repos the whole firm installs from (EA_Dist is public). Disabling
            # TLS verification on the distribution channel, and switching off object
            # integrity checking on the same path, weakens exactly the link that
            # should be the most trustworthy. The inline justification was
            # "for troubleshooting", but it shipped unconditionally in production.
            #
            # If TLS genuinely fails against github.com, that is a machine trust-store
            # problem to fix on the machine, not something to mute repo-by-repo.
            ['http.receivepack', 'true'],       # Enable receive-pack
            ['lfs.concurrenttransfers', '1'],   # Limit concurrent LFS transfers
            ['http.version', 'HTTP/1.1'],       # Use HTTP/1.1 for better compatibility
            ['http.keepAlive', 'false'],        # Disable keep-alive to avoid connection issues
            ['http.followRedirects', 'true'],   # Follow redirects
            ['http.extraHeader', 'User-Agent: git/2.x'],  # Set user agent
            ['http.sslBackend', 'openssl'],     # Use OpenSSL backend
            ['core.autocrlf', 'false'],         # Disable auto CRLF conversion
            ['core.safecrlf', 'false'],         # Disable safe CRLF check
        ]
        
        for config in configs:
            try:
                subprocess.run([get_git_executable(), 'config', config[0], config[1]], cwd=repo_folder, timeout=30)
            except Exception as e:
                print(f"⚠️ Failed to set config {config[0]}: {str(e)}")
        
        # Never gc/repack here. Scheduler already skipped this for speed; manual
        # mode still ran `gc --prune=now` + `repack -a -d --window=250` on EA_Dist
        # (~11 GB) and filled the publisher box (post-#122 rehearsal: Out of
        # diskspace on tmp_pack; post-#124 retries then failed the 5 GB gate).
        # A force-push does not need a local repack.
        print("Skipping heavy repository gc/repack (fills disk on EA_Dist).")
        
        # Verify connectivity before pushing
        if lightweight_mode:
            print("Skipping deep repository connectivity checks in scheduler mode.")
        else:
            print("Verifying repository connectivity...")
            try:
                subprocess.run([get_git_executable(), 'fsck', '--full'], cwd=repo_folder, timeout=300)
                print("✅ Repository integrity check passed")
            except Exception as e:
                print(f"⚠️ Repository integrity check failed: {str(e)}")
        
        # Enhanced push strategies with better error handling and retry logic
        git_exe = get_git_executable()
        push_strategies = [
            # Strategy 1: Standard force push with progress
            {
                'command': [git_exe, 'push', '-f', '--no-verify', '--progress', 'origin', 'main'],
                'name': 'Standard force push with progress',
                'timeout': 2400,  # 40 minutes
                'retries': 2
            },
            # Strategy 2: No-thin push (avoids delta compression)
            {
                'command': [git_exe, 'push', '-f', '--no-verify', '--no-thin', '--progress', 'origin', 'main'],
                'name': 'No-thin push',
                'timeout': 2400,
                'retries': 2
            },
            # Strategy 3: Atomic push (all-or-nothing)
            {
                'command': [git_exe, 'push', '-f', '--no-verify', '--atomic', '--progress', 'origin', 'main'],
                'name': 'Atomic push',
                'timeout': 2400,
                'retries': 1
            },
            # Strategy 4: Push with verbose output
            {
                'command': [git_exe, 'push', '-f', '--no-verify', '--verbose', '--progress', 'origin', 'main'],
                'name': 'Verbose push',
                'timeout': 2400,
                'retries': 1
            },
            # Strategy 5: Push with different protocol
            {
                'command': [git_exe, 'push', '-f', '--no-verify', '--porcelain', 'origin', 'main'],
                'name': 'Porcelain push',
                'timeout': 1800,
                'retries': 1
            },
            # Strategy 6: Push with shallow depth (for very large repos)
            {
                'command': [git_exe, 'push', '-f', '--no-verify', '--progress', '--depth=1', 'origin', 'main'],
                'name': 'Shallow push',
                'timeout': 3600,  # 60 minutes
                'retries': 1
            }
        ]
        
        if lightweight_mode:
            for strategy in push_strategies:
                strategy['timeout'] = min(strategy['timeout'], 900)
                strategy['retries'] = min(strategy['retries'], 1)

        # Set longer timeouts for Git operations
        os.environ['GIT_HTTP_MAX_REQUEST_BUFFER'] = '100M'
        os.environ['GIT_HTTP_LOW_SPEED_LIMIT'] = '1000'
        os.environ['GIT_HTTP_LOW_SPEED_TIME'] = '600'
        
        # Try each push strategy with enhanced retry logic
        for strategy_index, strategy in enumerate(push_strategies, 1):
            _check_time_budget()
            # Hard total-publish budget check BEFORE starting a strategy.
            if _remaining_publish_seconds() <= 0:
                raise TimeoutError(
                    "Exceeded total publish budget ({}s) before strategy '{}'".format(
                        PUBLISH_MAX_SECONDS, strategy['name']))
            print("Attempting push strategy {}/{}: {}...".format(
                strategy_index, len(push_strategies), strategy['name']))
            
            # Try each strategy with its own retry count
            for retry_attempt in range(strategy['retries'] + 1):
                _check_time_budget()
                if retry_attempt > 0:
                    print("  Retry attempt {}/{} for strategy {}".format(
                        retry_attempt, strategy['retries'], strategy['name']))
                
                print("  Command: {}".format(' '.join(strategy['command'])))

                # Clamp this in-flight push to the smaller of its own timeout and
                # the whole-publish budget remaining, so no single push can run
                # past the total ceiling. Re-checked here (not just per strategy)
                # because retries and prior strategies consume the budget.
                remaining_budget = _remaining_publish_seconds()
                if remaining_budget <= 0:
                    raise TimeoutError(
                        "Exceeded total publish budget ({}s) before strategy '{}'".format(
                            PUBLISH_MAX_SECONDS, strategy['name']))
                effective_timeout = max(1, int(min(strategy['timeout'], remaining_budget)))

                try:
                    # Kill any existing git processes before attempting
                    try:
                        _kill_stray_git()
                        clear_stale_git_locks(repo_folder)
                    except Exception:
                        pass

                    result = subprocess.run(
                        strategy['command'],
                        cwd=repo_folder,
                        capture_output=True,
                        text=True,
                        timeout=effective_timeout
                    )
                    
                    if result.returncode == 0:
                        print("✅ Push successful using {}!".format(strategy['name']))
                        return
                    else:
                        error_output = result.stderr.strip()
                        print("❌ Push failed with error:\n{}".format(error_output))
                        
                        # Enhanced error analysis
                        if "HTTP 500" in error_output or "curl 22" in error_output:
                            print("🔍 Detected HTTP 500 error - this is a server-side issue")
                            print("💡 This usually indicates:")
                            print("   - Server is overloaded")
                            print("   - Repository is too large")
                            print("   - Network connectivity issues")
                            print("   - GitHub service problems")
                        elif "timeout" in error_output.lower():
                            print("⏰ Detected timeout error")
                        elif "connection" in error_output.lower():
                            print("🌐 Detected connection error")
                        elif "authentication" in error_output.lower():
                            print("🔐 Detected authentication error")
                        elif "permission" in error_output.lower():
                            print("🚫 Detected permission error")
                        
                        # Determine wait time based on error type
                        if "HTTP 500" in error_output:
                            wait_time = 180  # 3 minutes for server errors
                        elif "timeout" in error_output.lower():
                            wait_time = 120  # 2 minutes for timeouts
                        elif "connection" in error_output.lower():
                            wait_time = 90   # 1.5 minutes for connection issues
                        else:
                            wait_time = 60   # 1 minute for other errors
                        
                        # Check if we should retry this strategy
                        if retry_attempt < strategy['retries']:
                            print("⏳ Waiting {} seconds before retry...".format(wait_time))
                            time.sleep(wait_time)
                            
                            # Clean up before retry
                            try:
                                _kill_stray_git()
                                clear_stale_git_locks(repo_folder)
                            except Exception:
                                pass
                        else:
                            # Strategy exhausted, move to next strategy
                            if strategy_index < len(push_strategies):
                                print("⏳ Moving to next strategy...")
                                time.sleep(30)  # Brief pause between strategies
                            break
                            
                except subprocess.TimeoutExpired:
                    print("⏰ Push timed out after {} minutes using {}".format(
                        strategy['timeout'] // 60, strategy['name']))
                    
                    if retry_attempt < strategy['retries']:
                        print("⏳ Waiting 120 seconds before retry...")
                        time.sleep(120)
                    else:
                        if strategy_index < len(push_strategies):
                            print("⏳ Moving to next strategy...")
                            time.sleep(30)
                        break
        
        # Last resort: Try pushing in smaller chunks
        if lightweight_mode:
            print("\n🔄 Skipping chunked push strategies in scheduler mode to stay within time budget.")
            raise Exception("Push strategies failed within scheduler mode time budget")

        print("\n🔄 All standard push strategies failed. Attempting chunked push strategy...")
        
        # Get repository size to determine chunking strategy
        try:
            size_result = subprocess.run(
                [get_git_executable(), 'count-objects', '-vH'], 
                cwd=repo_folder, 
                text=True, 
                timeout=60
            )
            if size_result.returncode == 0:
                print("📊 Repository size info:")
                print(size_result.stdout)
        except:
            pass
        
        # Try pushing with different chunk sizes
        chunk_strategies = [
            {'size': 5, 'name': 'Small chunks (5 files)'},
            {'size': 10, 'name': 'Medium chunks (10 files)'},
            {'size': 20, 'name': 'Large chunks (20 files)'}
        ]
        
        for chunk_strategy in chunk_strategies:
            _check_time_budget()
            print("\n📦 Trying {}...".format(chunk_strategy['name']))
            
            try:
                # Get list of all files that have changed
                diff_result = subprocess.run(
                    [get_git_executable(), 'diff', '--name-only', 'HEAD~1', 'HEAD'], 
                    cwd=repo_folder, 
                    text=True,
                    timeout=300
                )
                
                if diff_result.returncode == 0:
                    changed_files = [f.strip() for f in diff_result.stdout.strip().split('\n') if f.strip()]
                    print("📁 Found {} changed files to push incrementally".format(len(changed_files)))
                    
                    if not changed_files:
                        print("ℹ️ No changed files detected, trying simple push...")
                        simple_result = subprocess.run(
                            [get_git_executable(), 'push', 'origin', 'main'], 
                            cwd=repo_folder, 
                            capture_output=True, 
                            text=True,
                            timeout=600
                        )
                        if simple_result.returncode == 0:
                            print("✅ Simple push successful!")
                            return
                        else:
                            print("❌ Simple push failed: {}".format(simple_result.stderr))
                            continue
                    
                    # Group files into manageable chunks
                    chunk_size = chunk_strategy['size']
                    file_chunks = [changed_files[i:i + chunk_size] for i in range(0, len(changed_files), chunk_size)]
                    
                    print("📦 Processing {} chunks of {} files each...".format(len(file_chunks), chunk_size))
                    
                    success_count = 0
                    for i, chunk in enumerate(file_chunks):
                        print("📤 Pushing chunk {}/{} ({} files)...".format(i + 1, len(file_chunks), len(chunk)))
                        
                        try:
                            # Create a temporary branch for this chunk
                            temp_branch = "temp_push_{}_{}".format(i, int(time.time()))
                            
                            # Create and switch to temp branch
                            subprocess.run([get_git_executable(), 'checkout', '-b', temp_branch], 
                                         cwd=repo_folder, 
                                         check=True,
                                         timeout=60)
                            
                            # Add only the files in this chunk
                            for file in chunk:
                                if os.path.exists(os.path.join(repo_folder, file)):
                                    subprocess.run([get_git_executable(), 'add', file], 
                                                 cwd=repo_folder, 
                                                 check=True,
                                                 timeout=30)
                            
                            # Commit this chunk
                            commit_msg = 'Temporary chunk commit {} - {} files'.format(i + 1, len(chunk))
                            subprocess.run([get_git_executable(), 'commit', '-m', commit_msg], 
                                         cwd=repo_folder, 
                                         check=True,
                                         timeout=60)
                            
                            # Push this chunk
                            push_result = subprocess.run(
                                [get_git_executable(), 'push', '-f', '--no-verify', 'origin', '{}:main'.format(temp_branch)], 
                                cwd=repo_folder, 
                                capture_output=True, 
                                text=True,
                                timeout=600
                            )
                            
                            if push_result.returncode == 0:
                                success_count += 1
                                print("✅ Chunk {}/{} pushed successfully".format(i + 1, len(file_chunks)))
                            else:
                                print("❌ Failed to push chunk {}/{}: {}".format(
                                    i + 1, len(file_chunks), push_result.stderr))
                            
                            # Return to main branch and clean up
                            subprocess.run([get_git_executable(), 'checkout', 'main'], 
                                         cwd=repo_folder, 
                                         timeout=30)
                            subprocess.run([get_git_executable(), 'branch', '-D', temp_branch], 
                                         cwd=repo_folder, 
                                         timeout=30)
                            
                            # Wait between chunks to avoid overwhelming the server
                            time.sleep(10)
                            
                        except Exception as e:
                            print("❌ Error processing chunk {}/{}: {}".format(i + 1, len(file_chunks), str(e)))
                            continue
                    
                    # If most chunks succeeded, try final push
                    if success_count > len(file_chunks) * 0.7:  # 70% success rate
                        print("🔄 {}% of chunks succeeded, attempting final push...".format(
                            int(success_count / len(file_chunks) * 100)))
                        
                        final_result = subprocess.run(
                            [get_git_executable(), 'push', '-f', '--no-verify', 'origin', 'main'],
                            cwd=repo_folder,
                            capture_output=True,
                            text=True,
                            timeout=max(1, int(min(1800, _remaining_publish_seconds())))
                        )
                        
                        if final_result.returncode == 0:
                            print("✅ Final push successful after chunked approach!")
                            return
                        else:
                            print("❌ Final push failed: {}".format(final_result.stderr))
                    else:
                        print("❌ Chunked approach failed - only {}% success rate".format(
                            int(success_count / len(file_chunks) * 100)))
                        
            except Exception as e:
                print("❌ Error in chunked push strategy: {}".format(str(e)))
                continue
        
        # If all strategies fail, provide detailed guidance
        print("\n" + "="*80)
        print("🚨 ALL AUTOMATED PUSH STRATEGIES FAILED")
        print("="*80)
        print("\n📋 Manual intervention required. Please try the following:")
        print("\n1️⃣  Check your internet connection and GitHub status:")
        print("   - Visit: https://www.githubstatus.com/")
        print("   - Try: ping github.com")
        print("\n2️⃣  Try manual push from command line:")
        print("   cd {}".format(repo_folder))
        print("   git status")
        print("   git push -f origin main")
        print("\n3️⃣  If still failing, try these alternatives:")
        print("   - Use GitHub Desktop")
        print("   - Try pushing from a different network")
        print("   - Consider splitting the repository")
        print("   - Contact GitHub support if persistent")
        print("\n4️⃣  Repository information:")
        print("   - Location: {}".format(repo_folder))
        print("   - Remote: origin/main")
        print("   - Last error: HTTP 500 (Server Error)")
        print("\n" + "="*80)
        
        raise Exception("All push strategies failed! Manual intervention required.")
        
    except TimeoutError as e:
        print(f"⏰ Push aborted: {e}")
        raise
    except Exception as e:
        print("❌ Error during push: {}".format(str(e)))
        raise

class CompileConfirmation:
    def __init__(self):
        self.should_compile = False

    def get_result(self):
        self.root = tk.Tk()
        self.root.title("Compile Confirmation")
        window_width = 500
        window_height = 300
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        position_top = int(screen_height / 2 - window_height / 2)
        position_right = int(screen_width / 2 - window_width / 2)
        self.root.geometry(f'{window_width}x{window_height}+{position_right}+{position_top}')
        self.label = tk.Label(self.root, text="", font=('Helvetica', 16))
        self.label.pack(pady=20)
        button_yes = tk.Button(self.root, text="Yes", font=('Helvetica', 16), command=self.on_yes)
        button_yes.pack(side="left", padx=20, pady=20)
        button_no = tk.Button(self.root, text="No", font=('Helvetica', 16), command=self.on_no)
        button_no.pack(side="right", padx=20, pady=20)
        self.countdown(15)
        self.root.mainloop()
        return self.should_compile

    def countdown(self, count):
        if count > 0:
            note = "default as Yes" if self.should_compile else "default as No"
            self.label['text'] = f"Do you want to compile all the exes today?\n(Excluding the OS-Installer)\n{note}\nTime remaining: {count} seconds"
            self.root.after(1000, self.countdown, count-1)
        else:
            self.root.quit()
            self.root.destroy()

    def on_yes(self):
        self.should_compile = True
        self.root.quit()
        self.root.destroy()

    def on_no(self):
        self.should_compile = False
        self.root.quit()
        self.root.destroy()

class RepoPublisher:
    """
    Manages the publishing workflow for EnneadTab project distribution.
    
    Handles compilation, verification, and distribution of project files including:
    - Executable files
    - Installation packages
    - Documentation
    - Repository synchronization
    
    Attributes:
        os_repo_folder (str): Root directory of the repository
        should_compile (bool): Flag indicating if executables should be recompiled
    """
    def _print_title(self, text):
        """Print formatted section title."""
        large_text = "\033[1m" + text + "\033[0m"
        print(large_text)

    def __init__(self):
        """Initialize the publisher with repository paths"""
        self.os_repo_folder = OS_REPO_FOLDER
        # Force-push failures collected during _sync_repositories. A non-empty list
        # means the distribution did NOT fully publish, and the process must exit
        # non-zero even though every individual step printed and carried on.
        self.push_failures = []
        # Publish steps that could not run because a precondition was absent (today:
        # the shared drive). Recorded rather than swallowed so the run summary can
        # say what did NOT happen -- a publish that skipped half its work must not
        # look identical to one that did all of it.
        self.skipped_jobs = []
        # Background threads this publish started, joined with a bound before the
        # run ends so the process cannot hang on one and cannot silently abandon it.
        self._background_threads = []
        self._dist_repo_folders = []
        
        # Look in the parent directory (where sibling folders exist)
        parent_dir = os.path.dirname(self.os_repo_folder)
        print("Searching for distribution repositories in: {}".format(parent_dir))
        
        try:
            for folder in os.listdir(parent_dir):
                full_path = os.path.join(parent_dir, folder)
                if folder.startswith("EA_Dist") and os.path.isdir(full_path):
                    print("Found distribution repository: {}".format(folder))
                    self._dist_repo_folders.append(full_path)
            
            # Sort repositories to process Lite version first
            self._dist_repo_folders.sort(key=lambda x: 0 if "lite" in x.lower() else 1)
            
        except Exception as e:
            print("Error finding distribution repositories: {}".format(str(e)))

        if not self._dist_repo_folders:
            orange_text = "\033[33m"
            reset_text = "\033[0m"
            print(f"{orange_text}No distribution repositories found. Ok this is ok.{reset_text}")

        self.should_compile = False
        # D1: records (repo_name, reason) for any dist repo whose force-push did
        # NOT land on origin. _post_publish_verification folds this into overall
        # success and fails loud, so a swallowed push failure cannot report healthy.
        self._push_landing_failures = []

    def _get_compilation_confirmation(self):
        """Prompt user for compilation preference using GUI dialog."""
        # Check if running in headless mode (no GUI available)
        try:
            import tkinter as tk
            # Test if we can create a root window
            test_root = tk.Tk()
            test_root.withdraw()  # Hide the test window
            test_root.destroy()
            
            # If we get here, GUI is available
            self.should_compile = CompileConfirmation().get_result()
        except Exception as e:
            # GUI not available, use default (no compilation)
            print("GUI not available for compilation confirmation: {}".format(str(e)))
            print("Defaulting to NO compilation...")
            self.should_compile = False
            
        if self.should_compile:
            NOTIFICATION.messenger("Recompiling all exes...kill VScode if you want to cancel..")
        else:
            NOTIFICATION.messenger("NOT compiling exes today...")
    
    def _handle_compilation(self):
        """Manage executable compilation based on user preference."""
        if self.should_compile:
            self._print_title("\n\nBegin compiling all exes...")
            sys.path.append(os.path.join(DARKSIDE_DIR, "exes"))
            from ExeMaker import recompile_exe  # pyright: ignore
            recompile_exe()
                    
    def _update_rui_files(self):
        """
        Updates RUI (Revit User Interface) configuration files.
        
        Uses RuiWriter module to:
        - Process template RUI files
        - Update ribbon configurations
        - Generate new RUI files for distribution
        - Maintain consistent UI across installations
        """
       
        try:
            if DARKSIDE_DIR not in sys.path:
                sys.path.insert(0, DARKSIDE_DIR)
            import RuiWriter
            self._print_title("\n\nBegin updating RUI files...")
            RuiWriter.run()
        except ImportError as e:
            raise PublishValidationError(
                "RuiWriter import failed ({}); RUI files would not be updated. "
                "If this is yaml: pip install pyyaml. If PIL: pip install Pillow."
                .format(e)
            )
        except Exception as e:
            raise PublishValidationError(
                "RUI file update failed: {}".format(e)
            )
    
    
    def _generate_documentation(self):
        """
        Generate documentation for the project.
        """
    
        try:
            self._print_title("\n\nBegin generating documentation...")
            DOCUMENTATION.generate_documentation()
        except Exception as e:
            raise PublishValidationError(
                "Documentation PDF generation failed: {}".format(e)
            )
    
            
    # Roots the publisher is allowed to have generated into. Anything dirty
    # OUTSIDE these did not come from a generation step, so it is somebody else's
    # work and must never be swept into an automated commit.
    # DarkSide/RuiWriter/ is load-bearing: GuidHandler.update_database() writes
    # guid_database.knowledge there on every RUI pass. Without this root the
    # run aborts after both handbooks as "foreign" (post-#121 rehearsal).
    GENERATED_ROOTS = ("Apps/", "Installation/", "DarkSide/RuiWriter/")

    # Executables copied out of Apps/lib/ExeProducts into their shipping folders.
    # Hoisted from inline literals so the fixtures in
    # tools/check_never_delete_unreplaceable.py can exercise the never-delete-what-
    # you-cannot-replace invariant against their OWN list, instead of breaking every
    # time this production data changes.
    INSTALLER_EXES = (
        "EnneadTab_OS_Installer.exe",
        "EnneadTab_OS_UnInstaller.exe",
        "EnneadTab_For_Revit_Installer.exe",
        "EnneadTab_For_Revit_UnInstaller.exe",
    )

    # 2026-08-07: emptied. AccFileOpenner.exe was the only entry, and PR #110
    # ("retire 16 legacy exes") untracked its source in Apps/lib/ExeProducts while
    # leaving Apps/_indesign/AccFileOpenner.exe tracked. That inconsistency crashed
    # the first production publish -- the step deleted the InDesign copy, then could
    # not restore it. Retirement is now confirmed, so the tracked copy is removed in
    # this same change and the list is empty. The STEP is kept rather than deleted:
    # it is the natural home for the next InDesign tool, and it now carries the
    # delete-safety guard from PR #114. Add a filename here and it works again.
    INDESIGN_APP_EXES = ()

    def _commit_generated_artifacts(self):
        """Commit what this run generated into the OS repo. Bounded, never blanket.

        WHY THIS EXISTS (2026-08-07): the publish writes generated artifacts into
        its OWN working tree -- Installation/exe_hash.json, the mirrored
        Apps/lib/ExeProducts/*.exe installers, RUI files, generated docs, and
        DarkSide/RuiWriter/guid_database.knowledge. Before
        PR #97 a blanket stage + "Auto-commit before publish" absorbed them.
        Removing that was right: it staged whatever happened to be open and
        shipped it to the whole firm. But nothing replaced it, so:

          - the 3-attempt retry loop became structurally dead. Attempt 1 always
            dirtied the tree, so attempts 2 and 3 could never pass the dirty-tree
            health check. Observed in the first rehearsal: both retries died in
            ~20 lines on 11 uncommitted changes attempt 1 had just created.
          - worse, EVERY subsequent publish refused until a human intervened.

        HOW THE SET IS DERIVED: not by enumerating each writer's outputs -- those
        live inside RuiWriter / DOCUMENTATION and would drift the moment a
        generator is added. Instead it leans on a fact already established:
        _pre_publish_health_check PROVED this tree was clean before any step ran.
        So anything dirty now was produced by this run, by definition.

        Blast radius is still bounded. Only paths under GENERATED_ROOTS are
        committed, each named explicitly; anything dirty outside them aborts. A
        concurrent editor save or a peer session's edit therefore stops the
        publish instead of being silently authored into it.
        """
        self._print_title("\n\nRecording generated artifacts...")

        git_exe = get_git_executable()
        try:
            # -uall is load-bearing, not a detail. By default git COLLAPSES an
            # untracked directory into one entry ("Apps/lib/"), and the pathspec
            # built from it would then stage that whole DIRECTORY -- so the blast
            # radius becomes every file in it, present and future, rather than the
            # files this run actually wrote. That is the blanket-stage behaviour
            # PR #97 removed, re-entering through the back door. It also reports a
            # directory name to the operator instead of what changed.
            status = subprocess.run(
                [git_exe, "status", "--porcelain", "-z", "--untracked-files=all"],
                cwd=self.os_repo_folder, capture_output=True, text=True, timeout=120)
        except Exception as e:
            raise PublishValidationError(
                "Could not read repository status to record generated artifacts: "
                "{}".format(e))
        if status.returncode != 0:
            raise PublishValidationError(
                "Could not read repository status to record generated artifacts: "
                "{}".format(status.stderr.strip()))

        # -z gives NUL-separated "XY path" records, so paths with spaces (this repo
        # has many) survive intact and no quoting/unescaping is needed.
        generated, foreign = [], []
        for record in (status.stdout or "").split("\0"):
            if not record.strip():
                continue
            path = record[3:] if len(record) > 3 else ""
            if not path:
                continue
            normalized = path.replace("\\", "/")
            if normalized.startswith(self.GENERATED_ROOTS):
                generated.append(path)
            else:
                foreign.append(path)

        if foreign:
            raise PublishValidationError(
                "Refusing to publish: {} uncommitted change(s) outside {} appeared "
                "during this run and were NOT generated by it -- {}. The tree was "
                "verified clean before publishing, so something else wrote here. "
                "Resolve them and publish again.".format(
                    len(foreign), " / ".join(self.GENERATED_ROOTS),
                    ", ".join(foreign[:10])))

        if not generated:
            print("    Nothing was generated into the repo; nothing to record.")
            return

        print("    Recording {} generated path(s):".format(len(generated)))
        for path in generated[:20]:
            print("      + {}".format(path))
        if len(generated) > 20:
            print("      ... and {} more".format(len(generated) - 20))

        # Explicit pathspec, delivered via a NUL-separated file. Naming each path
        # is what keeps this from being a blanket stage; the file (rather than
        # argv) is what keeps hundreds of long Windows paths under the ~32 KB
        # command-line limit.
        import tempfile
        spec_handle, spec_path = tempfile.mkstemp(suffix=".pathspec")
        try:
            with os.fdopen(spec_handle, "w", encoding="utf-8", newline="") as handle:
                handle.write("\0".join(generated))
            add = subprocess.run(
                [git_exe, "add", "--pathspec-from-file", spec_path,
                 "--pathspec-file-nul"],
                cwd=self.os_repo_folder, capture_output=True, text=True, timeout=600)
            if add.returncode != 0:
                raise PublishValidationError(
                    "Could not stage generated artifacts: {}".format(add.stderr.strip()))

            commit = subprocess.run(
                [git_exe, "commit", "-m",
                 "chore(publish): record generated artifacts\n\n"
                 "Written by the publish run itself (exe hashes, mirrored "
                 "installers, RUI files, generated docs). Committed with an "
                 "explicit pathspec so the tree is clean for the next publish."],
                cwd=self.os_repo_folder, capture_output=True, text=True, timeout=600)
            if commit.returncode != 0:
                raise PublishValidationError(
                    "Could not commit generated artifacts: {}\n{}".format(
                        commit.stdout.strip(), commit.stderr.strip()))
        finally:
            try:
                os.remove(spec_path)
            except Exception:
                pass

        print("    Recorded. The tree is clean, so the next publish will not be "
              "blocked by this run's own output.")

    def _sync_repositories(self):
        """
        Synchronize repositories with direct force push approach.
        
        Overrides distribution repositories with the latest files:
        - Cleans the git state of target repository
        - Skips pulling changes (per user preference)
        - Copies latest files directly from source
        - Commits and force pushes changes
        - Ensures clients always get the most recent version
        """
        self._print_title("\n\nBegin repository synchronization...")
        start_time = time.time()

        # Hard validity gate: refuse to force-push a syntax-broken tree to the
        # whole fleet. Runs BEFORE the try/except below on purpose -- that block
        # swallows everything and returns, so a gate abort must propagate from
        # out here to actually stop the publish.
        self._validate_shipping_python_syntax()

        # Hard safety gate: refuse to publish from a clone that is stale, dirty,
        # pointed at the wrong remote, or missing an expected target. This force-
        # pushes without pulling, so a BEHIND clone silently destroys every
        # published commit made since it last synced. Like the syntax gate above,
        # this must run OUTSIDE the try/except below so an abort actually stops
        # the publish instead of being swallowed.
        self._verify_publish_targets()

        try:
            print("Found {} distribution repositories to sync".format(len(self._dist_repo_folders)))
            
            for index, dist_folder in enumerate(self._dist_repo_folders):
                repo_name = os.path.basename(dist_folder)
                print("\n{}/{}. Processing repository: {} [{}]".format(
                    index + 1, 
                    len(self._dist_repo_folders),
                    repo_name,
                    dist_folder
                ))
                
                # First, ensure we're in a clean state
                print("  - Cleaning git state...")
                clean_start = time.time()
                self._clean_git_state(dist_folder)
                print("    Completed in {:.2f} seconds".format(time.time() - clean_start))

                # Capture the current (pre-copy) HEAD: this is the last-known-good
                # published commit, and what the rollback tag must point at. It
                # must be read AFTER clean and BEFORE the copy/commit overwrites
                # the tree -- tagging the new commit would be useless for revert.
                # Read origin/main, not local HEAD: on a stale clone the two differ
                # and the rollback tag must point at what is actually PUBLISHED.
                prev_head = self._get_published_head(dist_folder)

                # Skip pulling latest changes - we will override everything

                # Copy and commit changes
                print("  - Copying files to repository...")
                copy_start = time.time()
                self._copy_to_DistRepo_and_commit(dist_folder)
                print("    Completed in {:.2f} seconds".format(time.time() - copy_start))

                # Rollback affordance: tag + push the last-known-good commit to
                # origin BEFORE the destructive force-push so a bad publish can
                # be reverted with one command. `push -f origin main` does not
                # carry tags, so the tag gets its own push inside this helper.
                self._tag_last_known_good(dist_folder, prev_head)

                # Force push changes
                print("  - Force pushing changes to remote...")
                push_start = time.time()
                try:
                    reset_and_force_push(dist_folder)
                    print("    Force push completed in {:.2f} seconds".format(time.time() - push_start))
                    # D1: "push completed" only means reset_and_force_push returned; it does
                    # NOT prove origin advanced. Fetch origin and assert origin/main == the
                    # HEAD we just pushed. A mismatch (or a raised push) is a hard failure and
                    # must never be swallowed into apparent success -- record it loudly so
                    # _post_publish_verification can fail the whole publish.
                    landed, reason = self._verify_push_landed(dist_folder)
                    if landed:
                        print("    Verified origin/main advanced to the pushed commit.")
                    else:
                        print("    Push did NOT land for {}: {}".format(repo_name, reason))
                        self._push_landing_failures.append((repo_name, reason))
                except Exception as e:
                    reason = "force-push raised: {}".format(e)
                    print("    Force push FAILED for {}: {}".format(repo_name, reason))
                    print(traceback.format_exc())
                    print("    You may need to push manually.")
                    self._push_landing_failures.append((repo_name, reason))
            
            print("\nRepository synchronization completed in {:.2f} seconds".format(time.time() - start_time))

        except Exception as e:
            print("Error during repository sync:")
            print(str(e))
            print("Traceback:")
            print(traceback.format_exc())
            # The remaining publish steps still run (unchanged behaviour), but the
            # failure is recorded so the process cannot exit 0 having not published.
            self.push_failures.append(("<repository sync>", str(e)))
            return

    def _join_background_threads(self, timeout=300):
        """Wait a bounded time for background threads, and say if one did not finish.

        The alternative shapes are both bad: a non-daemon thread lets a stalled
        background job hang a CI runner forever, and an unjoined daemon thread gets
        killed at exit with nobody told its work was incomplete.
        """
        for thread in self._background_threads:
            if not thread.is_alive():
                continue
            print("  Waiting up to {}s for background task '{}'...".format(timeout, thread.name))
            thread.join(timeout=timeout)
            if thread.is_alive():
                print("  [WARNING] Background task '{}' did not finish within {}s and will be "
                      "abandoned when this process exits. Its work is INCOMPLETE."
                      .format(thread.name, timeout))
                self.skipped_jobs.append("{} (timed out after {}s)".format(thread.name, timeout))

    def all_publish_failures(self):
        """Every reason this publish did not fully succeed, from BOTH detectors.

        Two independent mechanisms exist and each has a hole the other covers:

          _push_landing_failures  set by _verify_push_landed -- catches a push that
                                  did not actually advance origin, INCLUDING one
                                  that raised no exception at all.
          push_failures           sync-level errors that abort before any push is
                                  attempted, so no landing check ever runs.

        The exit code and the run summary consider both. Reading only one is how a
        failed publish reports success.
        """
        combined = list(getattr(self, "_push_landing_failures", []))
        combined.extend(getattr(self, "push_failures", []))
        return combined

    def _print_run_summary(self):
        """State plainly what did and did not happen. Never let a partial run read as complete."""
        failures = self.all_publish_failures()
        print("\n" + "=" * 60)
        print("PUBLISH RUN SUMMARY")
        print("=" * 60)
        if failures:
            print("  Distribution pushes FAILED ({}):".format(len(failures)))
            for repo_name, err in failures:
                print("    * {}: {}".format(repo_name, err))
        else:
            print("  Distribution pushes: OK")
        if self.skipped_jobs:
            print("  Steps SKIPPED / incomplete ({}):".format(len(self.skipped_jobs)))
            for job in self.skipped_jobs:
                print("    * {}".format(job))
        else:
            print("  Steps skipped: none")
        print("=" * 60)

    def _verify_publish_targets(self):
        """Abort the publish unless every distribution target is safe to force-push.

        Delegates to publish_guard.verify_publish_preconditions, which is the single
        source of truth for the discovery rule and the target checks. Importing it
        (rather than re-implementing the checks here) is deliberate: two copies of
        "which repos are we publishing to" would drift, and the drift would be
        invisible until it force-pushed somewhere wrong.

        Raises PublishValidationError if the publish must not proceed. Callers must
        NOT catch this -- see the call site comment in _sync_repositories.
        """
        sys.path.insert(0, _SCRIPT_DIR)
        try:
            from publish_guard import verify_publish_preconditions
        finally:
            if sys.path and sys.path[0] == _SCRIPT_DIR:
                sys.path.pop(0)

        print("Verifying distribution targets before force-push...")
        problems, infos = verify_publish_preconditions(OS_REPO_FOLDER, fetch=True)

        for info in infos:
            print("  {} -> {} (HEAD {}, behind {})".format(
                info["name"],
                info["remote_normalized"] or "<no remote>",
                (info["head"] or "?")[:12],
                info["behind"],
            ))

        if problems:
            print("\n[ABORT] Refusing to publish -- {} target problem(s):".format(len(problems)))
            for p in problems:
                print("  * {}".format(p))
            raise PublishValidationError(
                "Publish target verification failed ({} problem(s)): {}".format(
                    len(problems), "; ".join(str(p) for p in problems)))

        print("  All distribution targets verified: present, correct remote, current, clean.")

    def _get_published_head(self, dist_folder):
        """Return the SHA currently PUBLISHED on origin/main, or None.

        Used for the rollback tag. Reading local HEAD instead would be wrong on a
        stale clone -- the tag would point at the stale commit rather than at what
        was actually live, so the documented one-command revert would restore the
        wrong tree. _verify_publish_targets should already have rejected a stale
        clone by the time this runs; this is defence in depth, not a substitute.
        """
        try:
            head = subprocess.check_output(
                [get_git_executable(), "rev-parse", "origin/main"],
                cwd=dist_folder, universal_newlines=True, timeout=30).strip()
            return head or None
        except Exception as e:
            print("    Could not resolve origin/main for rollback tag: {}".format(str(e)))
            return None
    def _verify_push_landed(self, repo_path, attempts=3):
        """Return (True, '') iff origin's main now equals the local HEAD we pushed.

        Reads the remote tip with `git ls-remote`, NOT `git fetch`.

        WHY (2026-08-07): this used to fetch, clamped to 180s. On EA_Dist (5.4 GB)
        a fetch triggers `git gc --auto` -> repack -> pack-objects across the whole
        clone, which blows far past that ceiling. The first end-to-end rehearsal
        force-pushed EA_Dist successfully -- origin genuinely advanced, confirmed
        independently -- and this function reported "push-landed verification timed
        out", which raised and failed the whole publish. EA_Dist_Lite verified fine
        in 14s, so the bug is purely size-dependent and no small-repo test could
        have found it.

        That is a FALSE FAILURE, the mirror of the false-success bug fixed in #99
        and worse in kind: an operator who believes a good publish failed may roll
        it back, and the rollback is the destructive operation.

        ls-remote asks exactly the question being asked -- "what commit is origin's
        main at?" -- over the wire in seconds. It downloads no objects and cannot
        trigger gc. fetch answered a far more expensive question nobody asked.

        Fail-closed is preserved, but the two outcomes are now DISTINGUISHED,
        because conflating them is the actual defect. A timeout is absence of
        evidence, not evidence of absence:

        - the remote tip differs from what we pushed -> VERIFIED NOT LANDED
        - we could not read the remote tip at all    -> COULD NOT VERIFY

        Both still block the publish. Only the second is retried, since a transient
        network blip is worth another cheap round-trip while a genuine mismatch is
        not going to change.

        Returns:
            (True, "") on success, else (False, reason) where reason begins with
            "VERIFIED NOT LANDED" or "COULD NOT VERIFY".
        """
        git_exe = get_git_executable()
        try:
            local = subprocess.run(
                [git_exe, "rev-parse", "HEAD"],
                cwd=repo_path, capture_output=True, text=True, timeout=30)
            if local.returncode != 0 or not local.stdout.strip():
                return False, "COULD NOT VERIFY: could not read local HEAD: {}".format(
                    local.stderr.strip())
            local_head = local.stdout.strip()
        except Exception as e:
            return False, "COULD NOT VERIFY: reading local HEAD failed: {}".format(e)

        last_reason = "COULD NOT VERIFY: no attempt completed"
        for attempt in range(1, attempts + 1):
            # Clamp to the remaining publish budget so an unreachable origin cannot
            # hang past the total ceiling. ls-remote is a metadata round-trip, so
            # 60s is generous rather than tight.
            timeout = max(1, int(min(60, _remaining_publish_seconds())))
            try:
                listing = subprocess.run(
                    [git_exe, "ls-remote", "origin", "refs/heads/main"],
                    cwd=repo_path, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                last_reason = ("COULD NOT VERIFY: git ls-remote timed out after {}s "
                               "(attempt {}/{})".format(timeout, attempt, attempts))
                continue
            except Exception as e:
                last_reason = "COULD NOT VERIFY: git ls-remote failed: {}".format(e)
                continue

            if listing.returncode != 0:
                last_reason = ("COULD NOT VERIFY: git ls-remote exited {} "
                               "(attempt {}/{}): {}".format(
                                   listing.returncode, attempt, attempts,
                                   listing.stderr.strip()))
                continue

            output = (listing.stdout or "").strip()
            if not output:
                # An empty listing means the ref genuinely is not there. After a
                # push that is a real failure, not an unreadable channel.
                return False, ("VERIFIED NOT LANDED: origin has no refs/heads/main "
                               "after pushing {}".format(local_head[:12]))

            remote_head = output.split()[0].strip()
            if remote_head != local_head:
                return False, ("VERIFIED NOT LANDED: origin/main is {} but pushed "
                               "HEAD is {}".format(remote_head[:12], local_head[:12]))
            return True, ""

        return False, last_reason

    def _syntax_gate_file_plan(self):
        """Decide which shipping .py files the gate compiles, and how each ranks.

        Deliberately does NOT re-derive scope. tools/check_ironpython.py already
        owns "is this file IronPython" (IRONPYTHON_GLOBS + NOT_IRONPYTHON) and
        tools/.ironpython_lint_allowlist owns "which known violators are
        grandfathered". Re-deriving either is how the two drift apart and start
        answering the same question differently.

        Returns:
            (hard_paths, soft_paths, allowed_paths) -- absolute paths.

        NOTE: is_ironpython_target() takes a REPO-RELATIVE, forward-slashed path.
        The base must be the OS repo root, never the process cwd -- a wrong base
        classifies everything out of scope and the gate silently checks nothing.
        The caller treats an empty total as a hard failure for exactly that reason.
        """
        import importlib.util

        checker_path = os.path.join(self.os_repo_folder, "tools", "check_ironpython.py")
        spec = importlib.util.spec_from_file_location(
            "_ennead_ironpython_scope", checker_path)
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)

        allowlist = checker.load_allowlist()

        hard, soft, allowed = [], [], []
        apps_root = os.path.join(self.os_repo_folder, "Apps")
        for dirpath, dirnames, filenames in os.walk(apps_root):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", ".git", ".venv")]
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                absolute = os.path.join(dirpath, filename)
                rel = os.path.relpath(absolute, self.os_repo_folder).replace("\\", "/")
                if not checker.is_ironpython_target(rel):
                    continue
                if rel in allowlist:
                    allowed.append(absolute)
                elif rel.startswith("Apps/_revit/") or rel.startswith("Apps/_rhino/"):
                    hard.append(absolute)
                else:
                    soft.append(absolute)
        return hard, soft, allowed

    def _validate_shipping_python_syntax(self):
        """Compile-check the IronPython trees about to ship; abort on breakage.

        Asks an IronPython 2.7 interpreter (the runtime that actually loads this
        code on clients) to compile each shipping .py. IronPython -- not the
        CPython 3 interpreter running this publisher -- is the only correct
        oracle: CPython 3 both false-rejects valid Py2 idioms (print statement,
        .None attribute access) and false-accepts the exact Py3-only syntax
        (f-strings, type hints) this gate exists to catch.

        Scope is NOT decided here. tools/check_ironpython.py already owns the
        answer to "is this file IronPython" (IRONPYTHON_GLOBS + NOT_IRONPYTHON)
        and which known violators are grandfathered (.ironpython_lint_allowlist).
        This gate CONSUMES those decisions -- see _syntax_gate_file_plan.

        Three outcomes per file:
        - HARD (abort): Apps/_revit and Apps/_rhino, not grandfathered.
        - SOFT (warn): Apps/lib/EnneadTab. Ships genuine CPython-only helpers, so
          a break is surfaced without gating the fleet on it.
        - ALLOWLISTED (warn): compiled anyway and reported LOUDLY. Grandfathered
          is not the same as invisible (rule: never-silent-to-operator).

        WHY THIS SCOPING EXISTS (2026-08-07): the gate previously derived its own
        scope from bare path prefixes, and on its first-ever real run it aborted
        on 19 files. 17 of those were already classified by the two mechanisms
        above -- 10 excluded by NOT_IRONPYTHON (which literally names
        /nyu_hq_daily_publisher/), 7 grandfathered in the allowlist. Two
        mechanisms answering the same question and disagreeing is the bug; the
        fix is to consume the sibling's answer, not to reproduce it.

        Graceful degradation (rule: graceful-to-user, never-silent-to-operator):
        - Unreadable files (e.g. Windows >260-char paths) are WARNED and skipped,
          not failed -- they ship regardless and cannot be opened here.
        - With no IronPython interpreter located, the gate SKIPS with a loud
          warning rather than falling back to the wrong (CPython 3) oracle.
        - If scope cannot be computed at all, the gate SKIPS loudly rather than
          guessing: a wrong scope is worse than a declared-absent check.

        Raises:
            PublishValidationError: if any HARD file fails to compile, or if the
                scope resolves to ZERO files (which means the scoping broke --
                a gate that checks nothing is indistinguishable from one that
                passes, so it must never be allowed to look green).
        """
        import tempfile

        self._print_title("\n\nValidating Python syntax of shipping trees...")

        try:
            hard_paths, soft_paths, allowed_paths = self._syntax_gate_file_plan()
        except Exception as e:
            print("    WARNING: could not compute syntax-gate scope ({}); skipping "
                  "gate -- shipping trees were NOT syntax-checked.".format(str(e)))
            return

        to_check = hard_paths + soft_paths + allowed_paths
        print("    Scope: {} hard (_revit/_rhino), {} soft (lib/EnneadTab), "
              "{} grandfathered -- {} file(s) to compile.".format(
                  len(hard_paths), len(soft_paths), len(allowed_paths), len(to_check)))

        # A gate that checks nothing reports exactly like a gate that checks
        # thousands and finds nothing. This tree has thousands; zero means the
        # scoping is broken (most likely a relpath base mistake), and shipping
        # unchecked while printing a pass is the failure this gate exists to stop.
        if not to_check:
            raise PublishValidationError(
                "Pre-publish syntax gate resolved ZERO files to check. The tree "
                "has thousands, so the gate's scoping is broken -- refusing to "
                "publish an unchecked tree behind a green check.")

        ipy = find_ironpython_executable()
        if not ipy:
            print("    WARNING: No IronPython 2.7 interpreter found "
                  "(set ENNEADTAB_IRONPYTHON_EXE to enable).")
            print("    WARNING: Skipping pre-publish syntax gate -- shipping trees "
                  "were NOT syntax-checked against their real runtime.")
            return

        print("    Using IronPython oracle: {}".format(ipy))

        # Py2-safe walker: IronPython runs this, so no f-strings / py3-only syntax.
        # It no longer walks or filters -- it compiles exactly the paths it is
        # handed, one per line, so scope lives in ONE place (the CPython side).
        # The list arrives via a file, not argv: thousands of paths would blow the
        # ~32 KB Windows command-line limit.
        walker_src = (
            "import sys\n"
            "lf = open(sys.argv[1], 'rb')\n"
            "paths = lf.read().split('\\n')\n"
            "lf.close()\n"
            "for p in paths:\n"
            "    p = p.strip()\n"
            "    if not p:\n"
            "        continue\n"
            "    try:\n"
            "        f = open(p, 'rb')\n"
            "        src = f.read()\n"
            "        f.close()\n"
            "    except Exception, e:\n"
            "        sys.stdout.write('UNREADABLE\\t' + p + '\\t' + str(e) + '\\n')\n"
            "        continue\n"
            "    if src[:3] == '\\xef\\xbb\\xbf':\n"
            "        src = src[3:]\n"
            "    src = src.replace('\\r\\n', '\\n').replace('\\r', '\\n')\n"
            # Py2/IronPython compile() requires the source to END IN A NEWLINE.
            # A file whose final line is whitespace-only with no terminating
            # newline otherwise raises a bogus 'unindent does not match any outer
            # indentation level' pointing at that last line. Two shipping files
            # tripped this on the gate's first real run (2026-08-07) and were
            # very nearly reported as broken source. rstrip() before appending:
            # that exact form is the one verified to fix both.
            "    src = src.rstrip() + '\\n'\n"
            "    try:\n"
            "        compile(src, p, 'exec')\n"
            "    except SyntaxError, e:\n"
            "        sys.stdout.write('SYNTAXERR\\t' + p + '\\t' + str(e) + '\\n')\n"
            "    except Exception, e:\n"
            "        sys.stdout.write('UNREADABLE\\t' + p + '\\t' + str(e) + '\\n')\n"
        )

        walker_path = os.path.join(
            tempfile.gettempdir(), "ennead_publish_syntax_gate.py")
        list_path = os.path.join(
            tempfile.gettempdir(), "ennead_publish_syntax_gate_files.txt")
        try:
            with open(walker_path, "w") as f:
                f.write(walker_src)
            with open(list_path, "w", encoding="utf-8") as f:
                f.write("\n".join(to_check))
        except Exception as e:
            print("    WARNING: could not write syntax-gate walker ({}); "
                  "skipping gate.".format(str(e)))
            return

        try:
            result = subprocess.run(
                [ipy, walker_path, list_path],
                capture_output=True, text=True, timeout=900
            )
        except subprocess.TimeoutExpired:
            print("    WARNING: syntax gate timed out; skipping (tree NOT fully checked).")
            return
        except Exception as e:
            print("    WARNING: syntax gate failed to run ({}); skipping.".format(str(e)))
            return
        finally:
            for tmp in (walker_path, list_path):
                try:
                    os.remove(tmp)
                except Exception:
                    pass

        def _norm(path):
            return os.path.normcase(os.path.abspath(path))

        hard_set = set(_norm(p) for p in hard_paths)
        allowed_set = set(_norm(p) for p in allowed_paths)

        hard_errors = []
        soft_errors = []
        allowed_errors = []
        unreadable = []
        for line in (result.stdout or "").splitlines():
            if line.startswith("SYNTAXERR\t"):
                parts = line.split("\t", 2)[1:]
                path = parts[0] if parts else "?"
                key = _norm(path)
                if key in allowed_set:
                    allowed_errors.append(parts)
                elif key in hard_set:
                    hard_errors.append(parts)
                else:
                    soft_errors.append(parts)
            elif line.startswith("UNREADABLE\t"):
                unreadable.append(line.split("\t", 2)[1:])

        if unreadable:
            print("    WARNING: {} file(s) could not be opened for checking "
                  "(long paths / permissions); they ship unchecked.".format(len(unreadable)))
            for parts in unreadable[:10]:
                print("      - {}".format(parts[0] if parts else ""))

        # Grandfathered is not invisible. These are suppressed by
        # tools/.ironpython_lint_allowlist, so they do not block -- but a publish
        # must never quietly ship a file it knows will not compile.
        if allowed_errors:
            print("    WARNING: {} grandfathered file(s) do not compile under "
                  "IronPython 2.7 (suppressed via tools/.ironpython_lint_allowlist, "
                  "NOT blocking -- remove the allowlist line once fixed):".format(
                      len(allowed_errors)))
            for parts in allowed_errors:
                path = parts[0] if parts else "?"
                msg = parts[1] if len(parts) > 1 else ""
                print("      ~ {}\n          {}".format(path, msg))

        if soft_errors:
            print("    WARNING: {} lib/EnneadTab file(s) do not compile under "
                  "IronPython 2.7 (NOT blocking -- may be CPython-only helpers, "
                  "but check they are not IronPython-loaded):".format(len(soft_errors)))
            for parts in soft_errors:
                path = parts[0] if parts else "?"
                msg = parts[1] if len(parts) > 1 else ""
                print("      ? {}\n          {}".format(path, msg))

        if hard_errors:
            print("    SYNTAX GATE FAILED -- {} _revit/_rhino file(s) will NOT "
                  "compile under IronPython 2.7:".format(len(hard_errors)))
            for parts in hard_errors:
                path = parts[0] if parts else "?"
                msg = parts[1] if len(parts) > 1 else ""
                print("      x {}\n          {}".format(path, msg))
            raise PublishValidationError(
                "Pre-publish syntax gate blocked the publish: {} _revit/_rhino "
                "file(s) fail to compile under IronPython 2.7. Fix them before "
                "republishing.".format(len(hard_errors)))

        # Report the count, not just the verdict: "0 errors out of 0 files checked"
        # and "0 errors out of 3000" print the same word otherwise.
        print("    Syntax gate passed: {} file(s) compiled under IronPython 2.7, "
              "{} hard (_revit/_rhino) with zero errors.".format(
                  len(to_check), len(hard_paths)))

    def _tag_last_known_good(self, dist_folder, prev_head, keep_last=10):
        """Tag + push the last-known-good commit before the destructive push.

        Creates an annotated tag (dist-YYYYMMDD-HHMMSS) on prev_head and pushes
        it to origin so a bad publish can be reverted with:
            git reset --hard <tag> && git push -f origin main
        Prunes older dist-* tags, keeping the most recent `keep_last`. All steps
        are best-effort: a tagging failure must not block the publish, but it is
        reported loudly so the operator knows no rollback point was recorded.
        """
        if not prev_head:
            print("    No prior commit to tag (fresh repo?); skipping rollback tag.")
            return

        git = get_git_executable()
        tag_name = "dist-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            rc = subprocess.call(
                [git, "tag", "-a", tag_name, prev_head,
                 "-m", "Last-known-good dist before publish {}".format(tag_name)],
                cwd=dist_folder, timeout=60)
            if rc != 0:
                print("    WARNING: could not create rollback tag {} "
                      "(no rollback point recorded).".format(tag_name))
                return
        except Exception as e:
            print("    WARNING: rollback tag creation failed ({}); "
                  "no rollback point recorded.".format(str(e)))
            return

        try:
            rc = subprocess.call([git, "push", "origin", tag_name],
                                 cwd=dist_folder, timeout=300)
            if rc == 0:
                print("    Rollback tag pushed: {} -> {}".format(tag_name, prev_head[:10]))
            else:
                print("    WARNING: rollback tag {} created locally but push failed "
                      "(rollback point not on origin).".format(tag_name))
        except Exception as e:
            print("    WARNING: rollback tag push failed ({}).".format(str(e)))

        # Prune old dist-* tags, keeping the most recent keep_last.
        try:
            listing = subprocess.check_output(
                [git, "tag", "-l", "dist-*"],
                cwd=dist_folder, universal_newlines=True, timeout=60)
            tags = sorted(t.strip() for t in listing.splitlines() if t.strip())
            for old in tags[:-keep_last] if len(tags) > keep_last else []:
                try:
                    subprocess.call([git, "tag", "-d", old], cwd=dist_folder, timeout=30)
                    subprocess.call([git, "push", "origin", "--delete", old],
                                    cwd=dist_folder, timeout=120)
                except Exception:
                    pass
        except Exception as e:
            print("    WARNING: could not prune old rollback tags ({}).".format(str(e)))

    def _clean_git_state(self, dist_folder):
        """
        Clean up git state by removing lock files and resetting if needed.
        Enhanced with better process handling and timeouts.
        """
        try:
            # Kill any running git processes more thoroughly
            try:
                print("    Terminating any running git processes...")
                _kill_stray_git()
                clear_stale_git_locks(dist_folder)
            except Exception:
                pass
            
            # Remove any existing lock files
            lock_file = os.path.join(dist_folder, ".git", "index.lock")
            if os.path.exists(lock_file):
                print("    Removing existing git lock file...")
                try:
                    os.chmod(lock_file, 0o777)  # Ensure we have permissions
                    os.remove(lock_file)
                    print("    Lock file removed successfully")
                except Exception as e:
                    print("    Warning: Could not remove lock file: {}".format(str(e)))
            
            # Clean the repository more thoroughly
            print("    Cleaning repository...")
            try:
                # Soft reset any uncommitted changes
                subprocess.call(
                    [get_git_executable(), "reset", "--hard", "HEAD"],
                    cwd=dist_folder,
                    timeout=60
                )
                
                # Clean untracked files to ensure clean state
                subprocess.call(
                    [get_git_executable(), "clean", "-fd"],
                    cwd=dist_folder,
                    timeout=60
                )
                
                print("    Repository cleaned successfully")
            except subprocess.TimeoutExpired:
                print("    Warning: Repository cleaning timed out")
            except Exception as e:
                print("    Warning: Git cleanup operation failed - {}".format(str(e)))
            
        except Exception as e:
            print("    Warning: Git cleanup failed - {}".format(str(e)))

    def _generate_wiki_website(self):
        """
        Push tool knowledge data to the EnneadTab Wiki API (delta ingest).

        Two-phase protocol: manifest hash compare, then partial data + icons only
        for changed tools. Skips entirely when local cache matches.

        Records a structured outcome on ``self._wiki_ingest_outcome`` so post-publish
        verification can report what actually happened. Three states, deliberately
        kept greppable and distinct the way ``VERIFIED NOT LANDED`` /
        ``COULD NOT VERIFY`` already are in ``_verify_push_landed``:

          INGESTED             the wiki received this publish's tool data
          SKIPPED (rehearsal)  correctly did not touch the production wiki
          NOT ATTEMPTED        wanted to run and could not (missing client/data file)
          ATTEMPTED AND FAILED ran and the API rejected it / errored

        Only NOT ATTEMPTED and ATTEMPTED AND FAILED are problems. SKIPPED is the
        EXPECTED outcome of a rehearsal and is reported neutrally -- see the
        rehearsal gate below for why that distinction is load-bearing.

        2026-08-07: this method previously only printed. A publish with no
        WIKI_API_KEY skipped ingestion, and post-publish verification -- which
        checked an unrelated, long-archived git clone -- still printed a green
        check and "ALL REPOSITORIES VERIFIED SUCCESSFULLY". The wiki silently went
        stale while every publish reported total success. Never let a step that did
        not run be indistinguishable from one that succeeded.
        """
        self._print_title("\n\nBegin wiki data ingestion...")
        self._wiki_ingest_outcome = {
            "state": "NOT ATTEMPTED",
            "reason": "ingestion step did not reach a conclusion",
            "platforms": [],
        }

        sys.path.insert(0, _SCRIPT_DIR)
        try:
            from publish_guard import (
                is_rehearsal, load_darkside_dotenv, resolve_wiki_api_key)
        finally:
            if sys.path and sys.path[0] == _SCRIPT_DIR:
                sys.path.pop(0)

        # REHEARSAL GATE -- must come before key resolution, not just before the POST.
        #
        # 2026-08-12, CI run 31609967538. run-ci-publish.ps1 says "It never publishes
        # to production" and rehearsal_banner() promises "Nothing published here
        # reaches the fleet". Both were true for the dist repos and FALSE here: the
        # first CI rehearsal posted 368 revit + 156 rhino tools to the live
        # enneadtab.com/wiki, and the production /api/ingest/last confirmed it.
        # publish_guard has exposed is_rehearsal() the whole time; this module simply
        # never asked.
        #
        # It was benign only by luck -- that run rehearsed current main, so the data
        # happened to be newer than what was live. Rehearsing a feature branch would
        # publish that branch's tools to the firm's handbook with nothing to flag it.
        #
        # The gate sits ABOVE resolve_wiki_api_key on purpose. That call pulls the
        # PRODUCTION key from Vercel and persists it to disk; a rehearsal has no
        # business fetching production credentials it must not use. Gating only the
        # POST would still leave the secret pulled and written into the clone.
        #
        # SKIPPED is deliberately NOT 'degraded'. In rehearsal, not writing the
        # production wiki is the CORRECT outcome, and a banner that is yellow on
        # every single rehearsal teaches everyone to ignore yellow -- the same
        # information-free status this whole state machine exists to prevent.
        # Follow-up: a ?dryRun=1 on /api/ingest so rehearsals exercise the real
        # payload/auth/validation path without mutating. See senzhang-todo #3901.
        if is_rehearsal():
            reason = ("rehearsal mode: refusing to write the production wiki "
                      "(expected -- this is not a failure)")
            print("    " + reason)
            self._wiki_ingest_outcome = {
                "state": "SKIPPED (rehearsal)", "reason": reason, "platforms": []}
            return

        load_darkside_dotenv(self.os_repo_folder)
        api_url = os.environ.get(
            "WIKI_API_URL",
            "https://ennead-tab-wiki.vercel.app/wiki/api/ingest/"
        )
        if not api_url.startswith("https://"):
            reason = "WIKI_API_URL must use https:// (refusing to send API key over insecure channel)"
            raise PublishValidationError(reason)
        api_key = resolve_wiki_api_key(self.os_repo_folder, persist=True)
        if not api_key:
            raise PublishValidationError(
                "WIKI_API_KEY missing after env, DarkSide/.env, and Vercel pull "
                "(ennead-projects/ennead-tab-wiki). Wiki ingest cannot skip -- "
                "it is the handbook channel."
            )

        sys.path.insert(0, os.path.join(DARKSIDE_DIR, "WikiBuilder"))
        try:
            from wiki_ingest_client import ingest_platform_delta
        except ImportError as e:
            reason = "wiki_ingest_client not found: {}".format(e)
            print("    Error: {}".format(reason))
            self._wiki_ingest_outcome = {
                "state": "NOT ATTEMPTED", "reason": reason, "platforms": []}
            return

        cache_path = os.path.join(DARKSIDE_DIR, ".wiki_ingest_cache.json")

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

        platform_results = []

        for platform, cfg in platforms.items():
            data_file = cfg["data_file"]
            icons_dir = cfg["icons_dir"]

            if not os.path.exists(data_file):
                print("    Warning: {} knowledge file not found, skipping".format(platform))
                platform_results.append((platform, "NOT ATTEMPTED", "knowledge file not found"))
                continue

            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print("    {}: loaded {} tools from {}".format(
                    platform, len(data), os.path.basename(data_file)
                ))
            except Exception as e:
                print("    Error loading {} data: {}".format(platform, e))
                platform_results.append((platform, "ATTEMPTED AND FAILED",
                                         "could not load knowledge data: {}".format(e)))
                continue

            ok, err, result = ingest_platform_delta(
                platform=platform,
                data=data,
                icons_dir=icons_dir,
                api_url=api_url,
                api_key=api_key,
                cache_path=cache_path,
                log_fn=lambda msg: print(msg),
            )
            if not ok:
                print("    {}: ingest failed — {}".format(platform, err))
                platform_results.append((platform, "ATTEMPTED AND FAILED", str(err)))
                continue
            if result.get("status") == "skipped":
                print("    {}: skipped ({})".format(platform, result.get("reason", "unchanged")))
                # An up-to-date wiki IS a delivered wiki -- the delta protocol skips
                # when the server already holds this exact manifest. Not a failure.
                platform_results.append((platform, "INGESTED",
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
                result.get("duration_ms", "?"),
            ))
            platform_results.append((platform, "INGESTED", "added={} updated={} deleted={}".format(
                result.get("tools_added", 0),
                result.get("tools_updated", 0),
                result.get("tools_deleted", 0),
            )))

        # Roll the per-platform states up. Any hard failure dominates; otherwise a
        # platform that never ran keeps the whole step out of "INGESTED" -- a wiki
        # missing half its tools is not a delivered wiki.
        states = [state for _, state, _ in platform_results]
        if not platform_results:
            self._wiki_ingest_outcome = {
                "state": "NOT ATTEMPTED",
                "reason": "no platforms were processed",
                "platforms": platform_results,
            }
        elif "ATTEMPTED AND FAILED" in states:
            self._wiki_ingest_outcome = {
                "state": "ATTEMPTED AND FAILED",
                "reason": "; ".join("{}: {}".format(p, d)
                                    for p, s, d in platform_results
                                    if s == "ATTEMPTED AND FAILED"),
                "platforms": platform_results,
            }
        elif "NOT ATTEMPTED" in states:
            self._wiki_ingest_outcome = {
                "state": "NOT ATTEMPTED",
                "reason": "; ".join("{}: {}".format(p, d)
                                    for p, s, d in platform_results
                                    if s == "NOT ATTEMPTED"),
                "platforms": platform_results,
            }
        else:
            self._wiki_ingest_outcome = {
                "state": "INGESTED",
                "reason": "; ".join("{}: {}".format(p, d) for p, _, d in platform_results),
                "platforms": platform_results,
            }

        print("    Wiki data ingestion completed")

        # Wiki is the handbook channel. A publish that ships the fleet and leaves
        # the wiki stale used to still print [OK] and exit 0 (post-#122 rehearsal:
        # missing `requests`). Fail closed here so the operator cannot miss it.
        # Not retried -- PublishValidationError is terminal, and a retry would
        # re-run the destructive dist copy.
        if self._wiki_ingest_outcome.get("state") != "INGESTED":
            raise PublishValidationError(
                "Wiki ingest did not land: {} -- {}".format(
                    self._wiki_ingest_outcome.get("state"),
                    self._wiki_ingest_outcome.get("reason"),
                )
            )

    def _post_publish_verification(self):
        """
        Verify that the published repositories (dist repos and wiki repo) are properly synced.
        This method checks the actual repositories that were published in the previous steps.
        """
        self._print_title("\n\nBegin post-publish verification...")
        start_time = time.time()
        
        verification_results = {
            'dist_repos': [],
            # 'degraded' is deliberately distinct from 'overall_success': the fleet
            # can be correctly updated (success) while a side channel like the wiki
            # silently did not run (degraded). Collapsing the two is what let a
            # never-ingested wiki print a green banner. See _print_verification_summary.
            'wiki_ingest': None,
            'degraded': False,
            'overall_success': True
        }
        
        # Verify distribution repositories
        print("🔍 Verifying distribution repositories...")
        for dist_folder in self._dist_repo_folders:
            repo_name = os.path.basename(dist_folder)
            print(f"  - Checking {repo_name}...")
            
            repo_status = self._verify_repository_status(dist_folder, repo_name)
            verification_results['dist_repos'].append(repo_status)
            
            if not repo_status['is_clean']:
                verification_results['overall_success'] = False
        
        # Verify the wiki actually received this publish's data.
        #
        # 2026-08-07: this used to git-status a local clone named "EnneadTabWiki"
        # in the parent folder. That check was VESTIGIAL and actively misleading:
        #   - the publisher has never written to or pushed a wiki git repo; it POSTs
        #     to https://enneadtab.com/wiki/api/ingest (see _generate_wiki_website)
        #   - "EnneadTabWiki" is the Ennead-Architects-LLP repo, ARCHIVED 2026-05-28.
        #     The live wiki is EnneadTab-EcoSystem/EnneadTab-Wiki (note the hyphen),
        #     so the folder could never be found and the branch never ran
        #   - the not-found branch recorded is_clean=True, which printed a GREEN CHECK
        #     and left overall_success untouched -- so a publish that shipped nothing
        #     to the wiki still announced "ALL REPOSITORIES VERIFIED SUCCESSFULLY"
        # A clean local git clone would not have proven ingestion succeeded anyway.
        # The only thing worth verifying is whether the data landed.
        print("🔍 Verifying wiki data ingestion...")
        wiki_outcome = getattr(self, "_wiki_ingest_outcome", None) or {
            "state": "NOT ATTEMPTED",
            "reason": "wiki ingestion step never ran",
            "platforms": [],
        }
        verification_results['wiki_ingest'] = wiki_outcome
        print("  - {}: {}".format(wiki_outcome["state"], wiki_outcome["reason"]))

        if wiki_outcome["state"] == "ATTEMPTED AND FAILED":
            # We tried to update the wiki and it rejected us. That is a real failure.
            verification_results['overall_success'] = False
        elif wiki_outcome["state"].startswith("SKIPPED"):
            # Rehearsal. Not writing the production wiki is the POINT, so this is
            # neither a failure nor a degradation. Marking it degraded would make
            # every rehearsal yellow and train everyone to ignore the colour.
            pass
        elif wiki_outcome["state"] != "INGESTED":
            # We never tried. The fleet still got its code, so this is not a failed
            # publish -- but the wiki is now stale, and the operator must be told in
            # the banner, not in a line above a green banner.
            verification_results['degraded'] = True
        
        # D1: a force-push that never landed on origin is a hard publish failure,
        # even when every working tree is clean. Fold recorded push-landing
        # failures into overall_success so a false-healthy "all clean" cannot mask
        # a fleet that never actually received the new code.
        push_failures = list(getattr(self, "_push_landing_failures", []))
        if push_failures:
            verification_results['overall_success'] = False
            print("\n❌ Push-landing failures detected (origin did not advance):")
            for repo_name, reason in push_failures:
                print("   - {}: {}".format(repo_name, reason))

        # Print verification summary
        self._print_verification_summary(verification_results)

        # 2026-08-07: this restates the banner _print_verification_summary just
        # printed, so it must agree with it in all THREE states. It previously had
        # its own two-state copy and an unconditional green check, which meant a
        # degraded run printed the honest yellow banner and was then immediately
        # contradicted two lines later by "All repositories verified successfully!".
        # One outcome, several renderings -- every one of them has to tell the truth.
        elapsed = time.time() - start_time
        green_text = "\033[92m"
        yellow_text = "\033[93m"
        red_text = "\033[91m"
        reset_text = "\033[0m"

        if not verification_results['overall_success']:
            print(f"\n❌ Post-publish verification completed in {elapsed:.2f} seconds")
            print(f"{red_text}⚠️ Some repositories have issues that need attention.{reset_text}")
        elif verification_results.get('degraded'):
            print(f"\n⚠️ Post-publish verification completed in {elapsed:.2f} seconds")
            print(f"{yellow_text}⚠️ Fleet updated, but some steps did not run "
                  f"(see above).{reset_text}")
        else:
            print(f"\n✅ Post-publish verification completed in {elapsed:.2f} seconds")
            print(f"{green_text}🎉 All repositories verified successfully!{reset_text}")

        # D1: a force-push that did not land is a HARD failure -- fail loud so the
        # publish exits non-zero. Success MUST mean origin advanced to our commit;
        # never let a swallowed force-push failure report a healthy publish. This
        # raise propagates out of publish() -> __main__ maps False to exit 1
        # so CI sees the job fail (never-silent to the operator). Scoped to
        # push-landing failures on purpose: a merely-dirty working tree
        # (is_clean=False) still flips the
        # summary to "issues need attention" above but keeps the pre-existing
        # non-fatal behavior, so this change adds a gate without escalating
        # unrelated warnings into false job failures.
        if push_failures:
            detail = "; ".join("{}: {}".format(n, r) for n, r in push_failures)
            NOTIFICATION.messenger(
                "Publish verification FAILED -- origin did not advance: {}".format(detail))
            raise PublishValidationError(
                "Post-publish verification failed -- force-push did not land on origin. "
                "Push-landing failures: {}".format(detail))

    def _verify_repository_status(self, repo_path, repo_name):
        """
        Verify the status of a specific repository.
        
        Args:
            repo_path (str): Path to the repository
            repo_name (str): Name of the repository for display
            
        Returns:
            dict: Repository status information
        """
        status = {
            'name': repo_name,
            'path': repo_path,
            'is_clean': False,
            'status': 'Unknown',
            'last_commit': 'Unknown',
            'remote_status': 'Unknown'
        }
        
        try:
            # Check if repository exists and is a git repo
            if not os.path.exists(repo_path):
                status['status'] = 'Repository path does not exist'
                return status
            
            git_folder = os.path.join(repo_path, ".git")
            if not os.path.exists(git_folder):
                status['status'] = 'Not a git repository'
                return status
            
            # Check git status (clean working directory)
            result = subprocess.run(
                [get_git_executable(), "status", "--porcelain"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                if not result.stdout.strip():
                    status['is_clean'] = True
                    status['status'] = 'Clean working directory'
                else:
                    status['status'] = f'Uncommitted changes: {len(result.stdout.strip().split(chr(10)))} files'
            else:
                status['status'] = f'Git status failed: {result.stderr.strip()}'
            
            # Get last commit information
            result = subprocess.run(
                [get_git_executable(), "log", "--oneline", "-1"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout.strip():
                status['last_commit'] = result.stdout.strip()
            else:
                status['last_commit'] = 'No commits found'
            
            # Check remote status (ahead/behind)
            result = subprocess.run(
                [get_git_executable(), "status", "--porcelain", "--branch"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split(chr(10))
                for line in lines:
                    if line.startswith('##'):
                        if 'ahead' in line and 'behind' in line:
                            status['remote_status'] = 'Diverged from remote'
                        elif 'ahead' in line:
                            status['remote_status'] = 'Ahead of remote'
                        elif 'behind' in line:
                            status['remote_status'] = 'Behind remote'
                        else:
                            status['remote_status'] = 'Up to date with remote'
                        break
                else:
                    status['remote_status'] = 'Unknown remote status'
            else:
                status['remote_status'] = f'Remote status check failed: {result.stderr.strip()}'
                
        except subprocess.TimeoutExpired:
            status['status'] = 'Verification timed out'
        except Exception as e:
            status['status'] = f'Verification error: {str(e)}'
        
        return status

    def _print_verification_summary(self, verification_results):
        """
        Print a detailed summary of the verification results.
        
        Args:
            verification_results (dict): Results from verification process
        """
        print("\n" + "="*80)
        print("📋 POST-PUBLISH VERIFICATION SUMMARY")
        print("="*80)
        
        # Distribution repositories
        print("\n📦 DISTRIBUTION REPOSITORIES:")
        print("-" * 50)
        
        for repo_status in verification_results['dist_repos']:
            status_icon = "✅" if repo_status['is_clean'] else "❌"
            print(f"{status_icon} {repo_status['name']}")
            print(f"   Path: {repo_status['path']}")
            print(f"   Status: {repo_status['status']}")
            print(f"   Last Commit: {repo_status['last_commit']}")
            print(f"   Remote: {repo_status['remote_status']}")
            print()
        
        # Wiki data ingestion. Only "INGESTED" earns a green check -- a step that
        # never ran must never be visually indistinguishable from one that passed.
        print("📚 WIKI DATA INGESTION:")
        print("-" * 50)

        wiki_ingest = verification_results.get('wiki_ingest')
        if wiki_ingest:
            state = wiki_ingest["state"]
            status_icon = {"INGESTED": "✅",
                           "SKIPPED (rehearsal)": "⏭",
                           "NOT ATTEMPTED": "⚠️",
                           "ATTEMPTED AND FAILED": "❌"}.get(state, "❓")
            print(f"{status_icon} {state}")
            # Same default as _generate_wiki_website -- a summary that reports a
            # different URL than the one actually posted to sends the operator to
            # check the wrong service.
            print(f"   Target: {os.environ.get('WIKI_API_URL', 'https://ennead-tab-wiki.vercel.app/wiki/api/ingest/')}")
            print(f"   Detail: {wiki_ingest['reason']}")
            for platform, pstate, detail in wiki_ingest.get("platforms", []):
                print(f"   - {platform}: {pstate} ({detail})")
            if state.startswith("SKIPPED"):
                # Expected in rehearsal. Say so plainly rather than with the
                # remediation warning below, which would be actively wrong advice.
                print("   This is correct for a rehearsal: the production wiki is")
                print("   intentionally left untouched.")
            elif state != "INGESTED":
                print("   NOTE: the wiki does NOT reflect this publish. Fleet code shipped;")
                print("         wiki tool data did not. Pull WIKI_API_KEY from Vercel")
                print("         (ennead-projects/ennead-tab-wiki) or DarkSide/.env.")
        else:
            print("❓ Wiki ingestion status not available")

        print("\n" + "="*80)

        # Overall status. THREE outcomes, not two -- a publish can succeed for the
        # fleet while a side channel silently did not run, and that state needs its
        # own banner rather than being folded into the green one.
        green_text = "\033[92m"
        yellow_text = "\033[93m"
        red_text = "\033[91m"
        reset_text = "\033[0m"

        if not verification_results['overall_success']:
            print(f"{red_text}⚠️ OVERALL STATUS: SOME REPOSITORIES NEED ATTENTION{reset_text}")
        elif verification_results.get('degraded'):
            print(f"{yellow_text}⚠️ OVERALL STATUS: FLEET UPDATED, BUT SOME STEPS DID NOT RUN{reset_text}")
        else:
            print(f"{green_text}🎉 OVERALL STATUS: ALL REPOSITORIES VERIFIED SUCCESSFULLY{reset_text}")
        
        print("="*80)



    def _copy_to_DistRepo_and_commit(self, dist_folder):
        """
        Copy files to distribution repository and commit changes.
        Enhanced with better retry logic and progress reporting.
        """
        try:
            # Copy files to distribution repository with status updates
            print("    Copying files to distribution repository...")
            self._copy_files_to_dist_repo(dist_folder)

            # Version stamp must be written AFTER the copy (the copy wipes
            # Apps/) and BEFORE the commit so it rides the same auto-commit.
            # Its failure must never block the commit: a missing stamp only
            # degrades version reporting, a skipped commit stops fleet updates.
            try:
                self._write_dist_version_stamp(dist_folder)
            except Exception as e:
                print("    Warning: failed to write DIST_VERSION.json: {}".format(str(e)))

            # Same rules as the version stamp: AFTER the copy, BEFORE the commit,
            # and never allowed to block the commit.
            try:
                self._write_dist_manifest(dist_folder)
            except Exception as e:
                print("    Warning: failed to write dist_manifest.json: {}".format(str(e)))

            # Try to commit changes with improved retry logic
            max_retries = 3
            for attempt in range(max_retries):
                print("    Commit attempt {} of {}...".format(attempt + 1, max_retries))
                if commit_changes(dist_folder, commit_message="Auto-commit: Update distribution repository"):
                    print("    Successfully committed changes to distribution repository")
                    return
                else:
                    if attempt < max_retries - 1:
                        wait_time = 15 + (15 * attempt)  # Exponential backoff
                        print("    Commit attempt {} failed, retrying in {} seconds...".format(
                            attempt + 1, wait_time))
                        
                        # Clean up between attempts
                        lock_file = os.path.join(dist_folder, ".git", "index.lock")
                        if os.path.exists(lock_file):
                            print("    Removing existing git lock file...")
                            try:
                                os.chmod(lock_file, 0o777)
                                os.remove(lock_file)
                            except Exception as e:
                                print("    Warning: Could not remove lock file: {}".format(str(e)))
                        
                        # Terminate git processes that might be causing issues
                        try:
                            _kill_stray_git()
                            clear_stale_git_locks(dist_folder)
                        except Exception:
                            pass
                        
                        time.sleep(wait_time)
                    else:
                        print("    Failed to commit changes after {} attempts".format(max_retries))
                        # Continue with the process even if commit fails
                        return
                    
        except Exception as e:
            print("    Error during distribution repository update:")
            print("    {}".format(str(e)))
            # Continue with the process even if there's an error
            return

    def _write_dist_version_stamp(self, dist_folder):
        """Write Apps/lib/EnneadTab/DIST_VERSION.json into the dist copy.

        Runtime code (ENVIRONMENT.get_dist_version) reads this so every error
        report carries the exact publish a machine is running; absence of the
        file means a dev tree. The stamp is computed once per publish run so
        EA_Dist and EA_Dist_Lite from the same run carry an identical version.
        """
        if not hasattr(self, "_dist_version_stamp"):
            source_commit = "unknown"
            try:
                source_commit = subprocess.check_output(
                    [get_git_executable(), "rev-parse", "HEAD"],
                    cwd=OS_REPO_FOLDER, universal_newlines=True).strip()
            except Exception as e:
                print("    Could not resolve source commit for version stamp: {}".format(str(e)))
            now = datetime.datetime.now()
            self._dist_version_stamp = {
                "version": now.strftime("%Y.%m.%d.%H%M"),
                "source_commit": source_commit,
                "published_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        stamp_path = os.path.join(dist_folder, "Apps", "lib", "EnneadTab", "DIST_VERSION.json")
        with open(stamp_path, "w") as f:
            json.dump(self._dist_version_stamp, f, indent=4)
        print("    DIST_VERSION stamp written: {}".format(self._dist_version_stamp["version"]))

    def _write_dist_manifest(self, dist_folder):
        """Write Installation/dist_manifest.json into the dist copy.

        A SHA-256 of every shipped .py file under Apps/lib/EnneadTab and
        Apps/_revit/EnneaDuck.extension -- the integrity manifest that lets a user
        machine prove its install is internally consistent.

        WHY: the updater copies file-by-file into the LIVE EA_Dist folder. A failure
        partway (Revit holding a file open, network blip) leaves a machine running a
        NEW hook against an OLD lib. Nothing in this repo can see that -- the repo is
        internally consistent -- so the check has to happen on the deployed tree, and
        it needs a per-file fingerprint from publish time to check against. This is
        that fingerprint. EnneadTab.INTEGRITY.verify() reads it.

        Scope lives in INTEGRITY.MANIFEST_TREES, not here, so the writer and the
        reader cannot drift on which files are covered.

        Written AFTER the copy (the copy wipes Apps/) so it fingerprints exactly the
        bytes that ship. exe_hash.json is the same idea for executables; this is its
        source-file counterpart.
        """
        if not hasattr(self, "_dist_version_stamp"):
            self._write_dist_version_stamp(dist_folder)

        files = INTEGRITY.build_manifest_files(dist_folder)

        manifest = {
            "version": self._dist_version_stamp["version"],
            "source_commit": self._dist_version_stamp["source_commit"],
            "published_at": self._dist_version_stamp["published_at"],
            "trees": INTEGRITY.MANIFEST_TREES,
            "files": files,
        }

        manifest_dir = os.path.join(dist_folder, "Installation")
        if not os.path.isdir(manifest_dir):
            os.makedirs(manifest_dir)
        manifest_path = os.path.join(manifest_dir, INTEGRITY.MANIFEST_NAME)
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=4, sort_keys=True)
        print("    dist_manifest written: {} files hashed".format(len(files)))

    def _purge_by_extension(self):
        """
        Removes unwanted backup and temporary files from repository.
        """
        print("Begin purging by extension...")
        sys.stdout.flush()
        
        bad_extensions = [".3dmbak", ".rui_bak"]
        revit_backup_pattern = re.compile(r'\.\d{4}\.rfa$')
        
        # Skip directories that don't need purging
        skip_dirs = {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache'}
        
        removed_count = 0
        processed_count = 0
        
        print("Scanning for files to purge...")
        sys.stdout.flush()
        
        # Process files directly without collecting them first
        for root, dirs, files in os.walk(self.os_repo_folder):
            # Skip unwanted directories
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            
            for file_name in files:
                processed_count += 1
                
                
                try:
                    file_path = os.path.join(root, file_name)
                    
                    # Check for bad extensions
                    for ext in bad_extensions:
                        if file_name.endswith(ext):
                            os.remove(file_path)
                            removed_count += 1
                            break
                    else:
                        # Check for Revit backup pattern
                        if revit_backup_pattern.search(file_name):
                            os.remove(file_path)
                            removed_count += 1
                            
                except Exception as e:
                    # Only print errors for actual failures, not missing files
                    if "No such file" not in str(e):
                        print(f"Failed to remove {file_path}: {e}")
        
        print(f"Purge completed: processed {processed_count} files, removed {removed_count} unwanted files.")
        sys.stdout.flush()

    def _confirm_all_exe_existing(self):
        """
        Verifies all required executables exist in project.
        
        Checks:
        - Compares maker data files against compiled executables
        - Reports missing executables with clear formatting
        - Raises exception if any executables missing
        - Uses streaming file operations
        """
        print("Begin confirming all exes exist...")
        self._print_title("\n\nBegin confirming all exes exist...")
        exe_folder = os.path.join(self.os_repo_folder, "Apps", "lib", "ExeProducts")
        data_folder = os.path.join(self.os_repo_folder, "DarkSide", "exes", "maker data")

        if not os.path.isdir(exe_folder):
            print("ExeProducts folder not found at {}, skipping exe check".format(exe_folder))
            return
        
        # Use streaming operations for file lists
        maker_files = set()
        for file in os.listdir(data_folder):
            if file.endswith(ENVIRONMENT.PLUGIN_EXTENSION):
                maker_files.add(file[:-9])
        
        exe_files = set()
        for file in os.listdir(exe_folder):
            if file.endswith('.exe'):
                exe_files.add(file[:-4])
        
        missing_exes = [name for name in maker_files if name not in exe_files]
        
        if missing_exes:
            red_text = "\033[91m"
            bold_text = "\033[1m"
            reset_text = "\033[0m"
            alert = "\n{}{}{}".format(red_text, bold_text, '!'*50)
            alert += "\nERROR: Missing executable files detected!\n"
            alert += "The following maker data files don't have corresponding exes:\n"
            for missing in missing_exes:
                alert += "- {}\n".format(missing)
            alert += "Aborting publish process due to missing executables.\n"
            alert += "{}{}\n".format('!'*50, reset_text)
            print(alert)
            raise PublishValidationError(
                "Missing executable files detected: {}. Build the missing exes or mark unneeded maker data files .RETIRED.".format(
                    ", ".join(missing_exes)
                )
            )
        else:
            green_text = "\033[92m"
            reset_text = "\033[0m"
            print("{}All maker data files have corresponding executables.{}".format(
                green_text, reset_text))
        
        # Clean up memory
        gc.collect()

    def _remind_all_to_do_items(self):
        """
        Scans project files for TODO items and displays them with context.
        """
        print("Begin scanning for 'to-do' items...")
        self._print_title("\n\nBegin scanning for 'to-do' items...")
        print('-' * 40)
        todo_pattern = re.compile(r'to-do', re.IGNORECASE)
        todo_count = 0
        current_file = os.path.abspath(__file__)

        # Process files in batches with progress tracking
        batch_size = 50
        files_to_process = []
        
        # Use os.scandir for better performance
        for entry in os.scandir(self.os_repo_folder):
            if entry.is_file() and entry.name.endswith('.py'):
                files_to_process.append(entry.path)
            elif entry.is_dir() and entry.name not in ['.venv', '.git', 'dependency', 'venv']:
                for root, _, files in os.walk(entry.path):
                    for file in files:
                        if file.endswith('.py'):
                            files_to_process.append(os.path.join(root, file))
        
        total_files = len(files_to_process)
        for i in range(0, total_files, batch_size):
            batch = files_to_process[i:i + batch_size]
            for file_path in batch:
                if file_path == current_file:
                    continue
                    
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                except UnicodeDecodeError:
                    continue
                    
                for line_num, line in enumerate(lines):
                    if todo_pattern.search(line):
                        todo_count += 1
                        start = max(line_num - 2, 0)
                        end = min(line_num + 3, len(lines))
                        print("File: {}".format(file_path))
                        for j in range(start, end):
                            print("{}: {}".format(j + 1, lines[j].rstrip()))
                        print('-' * 40)
            
        red_color = "\033[91m"
        reset_color = "\033[0m"
        print("{}Total \"to-do\" items found: {}\n When you have time you should review.{}".format(
            red_color, todo_count, reset_color))

    def _update_installer_folder_exes(self):
        """
        Updates installation folder with latest executables.
        
        Process:
        1. Removes existing .exe files from installation folder
        2. Copies latest versions of required executables
        3. Includes core tools and installers
        4. Reports copy status with color-coded output
        5. Processes files in batches
        """
        self._print_title("\n\nBegin updating installation folder in main repository...")
        installation_folder = os.path.join(OS_REPO_FOLDER, "Installation")
        exe_source_folder = os.path.join(OS_REPO_FOLDER, "Apps", "lib", "ExeProducts")

        app_list = self.INSTALLER_EXES

        red_text = "\033[91m"
        green_text = "\033[92m"
        bold_text = "\033[1m"
        reset_text = "\033[0m"

        # NEVER DELETE WHAT YOU CANNOT REPLACE (2026-08-07). Same defect as
        # _update_indesign_apps, and here it fails WORSE: the delete-everything
        # loop ran first, and the copy was wrapped in `except: continue`, so a
        # missing source silently un-shipped the installer while the publish went
        # on to exit 0. An operator would have no reason to look.
        #
        # These are the files the entire firm installs from. Resolve sources
        # first; remove only what can actually be put back.
        available = [f for f in app_list
                     if os.path.isfile(os.path.join(exe_source_folder, f))]
        missing = [f for f in app_list if f not in available]

        if missing:
            print("\n{}{}WARNING: {} installer(s) have NO source in ExeProducts and "
                  "were NOT refreshed: {}{}".format(
                      red_text, bold_text, len(missing), ", ".join(missing), reset_text))
            print("  The existing copy is left in place rather than deleted -- the "
                  "firm installs from these, and a missing build must never "
                  "un-ship one.\n")

        # Remove only the ones we are about to put back.
        for file in available:
            target = os.path.join(installation_folder, file)
            if not os.path.isfile(target):
                continue
            try:
                os.remove(target)
            except Exception as e:
                print("{}Could not remove existing {} ({}); it will be overwritten "
                      "in place.{}".format(red_text, file, e, reset_text))

        # Process files in batches
        batch_size = 3
        for i in range(0, len(available), batch_size):
            batch = available[i:i + batch_size]
            for file in batch:
                print("Copying {}/{} [{}] to EA_dist installer folder".format(
                    i + 1, len(available), file))
                try:
                    shutil.copyfile(
                        os.path.join(exe_source_folder, file),
                        os.path.join(installation_folder, file))
                    print(f"{green_text}Successfully copied {file}{reset_text}")
                except Exception as e:
                    print(f"{red_text}Failed to copy {file}: {str(e)}{reset_text}")
                    continue

            # Clean up memory after each batch
            gc.collect()

    def _mirror_service_factory_installers(self):
        """Mirror each standalone service-factory product's SIGNED installer into ExeProducts.

        For every product in ``service_factory_products.json`` this downloads the latest signed
        NSIS installer from its public update feed (``https://enneadtab.com/<slug>/updates/``) into
        ``Apps/lib/ExeProducts/<installer>`` (stable de-versioned name, overwrite = keep only the
        latest). The existing publish sequence then hashes it into ``exe_hash.json``, AppStore lists
        it automatically (``os.listdir``), and ``_sync_repositories`` ships it to the fleet via
        EA_Dist. This is a quick-onboarding convenience that COEXISTS with the Rhino/Revit toolbar
        redirect button — it does not replace it, and it never removes the retired PyInstaller tool
        exe (a different filename).

        HARD CONTRACT (do not break):
        - Must run SYNCHRONOUSLY and to completion BEFORE ``_start_exe_hash_thread()`` — the hash
          thread enumerates the folder once at run time, so a still-downloading installer would be
          missed. Do NOT move this into its own thread.
        - Must NEVER let an exception reach ``publish()``'s try/except (that would abort the whole
          publish). Every failure degrades to a visible WARN + operator notification and is skipped
          (graceful to the run, never silent to the operator).
        - Download is atomic: temp file -> verify sha512 -> ``os.replace``. A corrupt/truncated
          download never lands in the shipped folder. On mismatch the previous good installer is
          kept.
        - sha512-conditional: if the on-disk installer already matches the feed's sha512, skip the
          download entirely (no wasted bandwidth, no gratuitous git blob / fleet re-pull).

        Stdlib only (urllib/hashlib/base64) — no ``requests``/``pyyaml`` dependency in the publish
        critical path; ``latest.yml`` is flat so its top-level ``path:``/``sha512:`` are line-parsed.
        """
        import hashlib
        import base64
        import urllib.request
        import urllib.parse

        self._print_title("\n\nBegin mirroring service-factory installers into ExeProducts...")
        print("Begin mirroring service-factory installers into ExeProducts...")

        green_text = "\033[92m"
        red_text = "\033[91m"
        yellow_text = "\033[93m"
        reset_text = "\033[0m"

        # Method-level guard: a catastrophic failure (missing driver file, DNS dead) degrades the
        # WHOLE step to "skipped", it never aborts publish().
        try:
            driver_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "service_factory_products.json")
            if not os.path.isfile(driver_path):
                print("{}WARNING: service_factory_products.json not found at {} - skipping installer "
                      "mirror.{}".format(yellow_text, driver_path, reset_text))
                NOTIFICATION.messenger("Service-factory installer mirror skipped: driver list missing.")
                return

            with open(driver_path, "r", encoding="utf-8") as f:
                driver = json.load(f)
            products = driver.get("products", [])

            exe_product_folder = os.path.join(self.os_repo_folder, "Apps", "lib", "ExeProducts")
            if not os.path.isdir(exe_product_folder):
                print("{}WARNING: ExeProducts folder not found at {} - skipping installer mirror.{}".format(
                    yellow_text, exe_product_folder, reset_text))
                NOTIFICATION.messenger("Service-factory installer mirror skipped: ExeProducts missing.")
                return

            def _sha512_b64_of(path):
                h = hashlib.sha512()
                with open(path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                        h.update(chunk)
                return base64.b64encode(h.digest()).decode("ascii")

            updated, skipped, failed = [], [], []

            for i, product in enumerate(products):
                slug = product.get("slug", "")
                installer_name = product.get("installer", "")
                label = product.get("product", slug)
                print("[{}/{}] {} ({})".format(i + 1, len(products), label, slug))

                # Per-product guard: one product's 404 / bad feed skips only that product.
                try:
                    if not slug or not installer_name:
                        raise ValueError("driver row missing 'slug' or 'installer'")

                    feed_base = "https://enneadtab.com/{}/updates/".format(slug)
                    feed_url = urllib.parse.urljoin(feed_base, "latest.yml")

                    with urllib.request.urlopen(feed_url, timeout=30) as resp:
                        latest_yml = resp.read().decode("utf-8", errors="replace")

                    # Read files[0].url (the URL-safe, dash-form asset name). The deprecated
                    # top-level `path:` regressed to SPACES under app-builder-lib >=26.15.x
                    # (raw `${productName} Setup ${version}` template) and no longer matches the
                    # uploaded asset, which is dash-form -> a spaces URL 404s. url is authoritative.
                    # The column-0 sha512 below equals files[0].sha512 in these single-installer feeds.
                    url_match = re.search(r"(?m)^\s*-?\s*url:\s*(.+?)\s*$", latest_yml)
                    if not url_match:
                        # Backward-compat fallback for any older feed that only has top-level path.
                        url_match = re.search(r"(?m)^path:\s*(.+?)\s*$", latest_yml)
                    sha_match = re.search(r"(?m)^sha512:\s*(.+?)\s*$", latest_yml)
                    if not url_match or not sha_match:
                        raise ValueError("could not parse files[].url / sha512 from latest.yml")
                    remote_name = url_match.group(1).strip()
                    remote_sha512_b64 = sha_match.group(1).strip()
                    # Validate the hash is real base64 of a 64-byte SHA-512 digest.
                    if len(base64.b64decode(remote_sha512_b64)) != 64:
                        raise ValueError("feed sha512 is not a 64-byte digest")

                    dest_path = os.path.join(exe_product_folder, installer_name)

                    # sha512-conditional: already have the latest bytes? skip.
                    if os.path.isfile(dest_path) and _sha512_b64_of(dest_path) == remote_sha512_b64:
                        print("   - {}up to date{} ({})".format(yellow_text, reset_text, installer_name))
                        skipped.append(installer_name)
                        continue

                    # Download to a temp file (streamed), verify, then atomically replace.
                    exe_url = urllib.parse.urljoin(feed_base, urllib.parse.quote(remote_name))
                    tmp_path = dest_path + ".part"
                    print("   downloading {} ...".format(remote_name))
                    h = hashlib.sha512()
                    with urllib.request.urlopen(exe_url, timeout=120) as resp, open(tmp_path, "wb") as out:
                        while True:
                            chunk = resp.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                            h.update(chunk)
                    got_sha512_b64 = base64.b64encode(h.digest()).decode("ascii")

                    if got_sha512_b64 != remote_sha512_b64:
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                        raise ValueError("sha512 mismatch after download (feed vs bytes) - kept previous")

                    os.replace(tmp_path, dest_path)
                    print("   {}mirrored{} -> {}".format(green_text, reset_text, installer_name))
                    updated.append(installer_name)

                except Exception as e:
                    print("   {}FAILED{} to mirror {} ({}): {}".format(
                        red_text, reset_text, label, slug, e))
                    failed.append("{} ({})".format(label, slug))
                    # leave any stray .part behind cleaned
                    try:
                        stray = os.path.join(exe_product_folder, installer_name + ".part")
                        if os.path.isfile(stray):
                            os.remove(stray)
                    except OSError:
                        pass
                finally:
                    gc.collect()

            print("Installer mirror summary: {}{} updated{}, {} up-to-date, {}{} failed{}.".format(
                green_text, len(updated), reset_text, len(skipped), red_text, len(failed), reset_text))
            if failed:
                # Never silent to the operator: surface exactly which products were skipped.
                NOTIFICATION.messenger(
                    "Service-factory installer mirror: {} product(s) skipped - {}".format(
                        len(failed), ", ".join(failed)))

        except Exception as e:
            # Whole-step failure must not break publish.
            print("{}WARNING: service-factory installer mirror step failed entirely: {}{}".format(
                yellow_text, e, reset_text))
            NOTIFICATION.messenger("Service-factory installer mirror step failed (publish continues): {}".format(e))
        finally:
            gc.collect()

    def _update_indesign_apps(self):
        """
        Updates InDesign application folder with latest tools.
        
        Actions:
        1. Removes existing executables
        2. Copies latest versions of InDesign-specific tools
        3. Handles permission errors for in-use files
        4. Reports progress for each file
        5. Processes files in batches
        """
        print("Begin updating indesign apps folder...")
        self._print_title("\n\nBegin updating indesign apps folder...")
        indesign_app_folder = os.path.join(OS_REPO_FOLDER, "Apps", ENVIRONMENT.INDESIGN_FOLDER_KEYNAME)
        exe_source_folder = os.path.join(OS_REPO_FOLDER, "Apps", "lib", "ExeProducts")

        app_list = self.INDESIGN_APP_EXES

        # No tools configured is a different statement from "their sources are
        # missing", and saying the second when the first is true sends the next
        # operator looking for a broken build that does not exist.
        if not app_list:
            print("No InDesign tools are configured to ship; nothing to update.")
            return

        # NEVER DELETE WHAT YOU CANNOT REPLACE (2026-08-07).
        #
        # This used to delete EVERY .exe in the InDesign folder and then copy the
        # replacements in. When a source went missing the delete had already
        # happened and the copy raised FileNotFoundError -- so it destroyed a
        # tracked, shipped artifact AND killed the publish, in that order.
        #
        # That is not hypothetical: PR #110 ("retire 16 legacy exes -- untrack,
        # keep source") removed Apps/lib/ExeProducts/AccFileOpenner.exe while
        # Apps/_indesign/AccFileOpenner.exe stayed tracked. The next publish
        # deleted the InDesign copy, could not restore it, and aborted. Had it
        # aborted one stage later, the whole firm would have lost the tool.
        #
        # So sources are resolved BEFORE anything is removed, and only files that
        # can actually be replaced are removed.
        available = [f for f in app_list
                     if os.path.isfile(os.path.join(exe_source_folder, f))]
        missing = [f for f in app_list if f not in available]

        if missing:
            red_text = "\033[91m"
            bold_text = "\033[1m"
            reset_text = "\033[0m"
            print("\n{}{}WARNING: {} InDesign tool(s) have NO source in ExeProducts "
                  "and were NOT refreshed: {}{}".format(
                      red_text, bold_text, len(missing), ", ".join(missing), reset_text))
            print("  The existing copy is left in place rather than deleted -- a "
                  "missing build must not silently un-ship a tool.")
            print("  If these are retired on purpose, remove them from app_list "
                  "here and untrack the InDesign copy in the same change.\n")

        if not available:
            print("No InDesign tools have a usable source; nothing to update.")
            return

        # Remove only the ones we are about to put back.
        for file in available:
            target = os.path.join(indesign_app_folder, file)
            if not os.path.isfile(target):
                continue
            try:
                os.remove(target)
            except PermissionError:
                red_text = "\033[91m"
                bold_text = "\033[1m"
                reset_text = "\033[0m"
                print(f"\n{red_text}{bold_text}WARNING: Cannot remove {file} - File is in use{reset_text}\n")
                continue

        # Process files in batches
        batch_size = 2
        for i in range(0, len(available), batch_size):
            batch = available[i:i + batch_size]
            for file in batch:
                print("Copying {}/{} [{}] to EA_dist indesign folder".format(
                    i + 1, len(available), file))
                shutil.copyfile(
                    os.path.join(exe_source_folder, file),
                    os.path.join(indesign_app_folder, file))

            # Clean up memory after each batch
            gc.collect()

    def _copy_files_to_dist_repo(self, dist_folder):
        """
        Copy files to distribution repository with improved performance.
        Ignores DuckMaker.extension folders to reduce repository size.
        Also copies the .gitignore file from the main repository root to the distribution repo root to maintain consistent ignore rules.
        """
        print("Begin copying files to distribution repository...")
        try:
            # Copy .gitignore to the root of the distribution repo
            src_gitignore = os.path.join(self.os_repo_folder, ".gitignore")
            dest_gitignore = os.path.join(dist_folder, ".gitignore")
            if os.path.exists(src_gitignore):
                shutil.copy2(src_gitignore, dest_gitignore)

            # Process folders in batches with progress tracking
            folders_to_process = ["Apps", "Installation"]
            total_folders = len(folders_to_process)

            is_lite_version = "lite" in dist_folder.lower()
            
            # Define folders to skip for lite version
            lite_skip_folders = [
                'DuckMaker.extension',
                '_cad',
                '_engine',
                'DumpScripts',
                'dependency'
            ]
            
            # Define .exe files that should be included in lite version
            lite_allowed_exes = [
                'EnneadTab_OS_Installer.exe',
                'EnneadTab_OS_UnInstaller.exe',
                'EnneadTab_For_Revit_Installer.exe',
                'EnneadTab_For_Revit_UnInstaller.exe',
                'Emailer.exe',
                'NotificationHost.exe',
                'ProgressBar.exe'
            ]
            
            for folder_index, folder in enumerate(folders_to_process, 1):
                exe_backup_dir = None
                src_exe_folder = os.path.join(self.os_repo_folder, EXE_PRODUCTS_REL)
                dist_exe_folder = os.path.join(dist_folder, EXE_PRODUCTS_REL)
                if folder == "Apps":
                    if (
                        _count_exe_files(src_exe_folder) == 0
                        and _count_exe_files(dist_exe_folder) > 0
                    ):
                        exe_backup_dir = os.path.join(
                            dist_folder, ".publish_exe_products_backup"
                        )
                        if os.path.exists(exe_backup_dir):
                            try_remove_content(exe_backup_dir)
                        shutil.copytree(dist_exe_folder, exe_backup_dir)
                        print(
                            "Preserving {} existing dist exes (source ExeProducts empty)".format(
                                _count_exe_files(dist_exe_folder)
                            )
                        )

                try_remove_content(os.path.join(dist_folder, folder))
                time_stamp = time.time()
                
                src_folder = os.path.join(self.os_repo_folder, folder)
                dest_folder = os.path.join(dist_folder, folder)
                
                # Create destination folder
                os.makedirs(dest_folder, exist_ok=True)
                
                # Process files in batches with progress tracking
                batch_size = 50
                files = []
                
                # Use os.scandir for better performance
                for entry in os.scandir(src_folder):
                    if entry.is_file():
                        # Apply lite version filtering to root level files too
                        if is_lite_version:
                            # Check if it's an .exe file
                            if entry.name.lower().endswith('.exe'):
                                # Only skip if it's not in the allowed list
                                if entry.name not in lite_allowed_exes:
                                    continue
                            elif any(ext in entry.name.lower() for ext in [
                                '.dll', ".psd", ".ai"
                            ]):
                                continue
                        files.append((entry.path, entry.name))
                    elif entry.is_dir():
                        for root, _, filenames in os.walk(entry.path):
                            # Skip specified folders for lite version
                            if is_lite_version:
                                if any(skip_folder.lower() in root.lower() for skip_folder in lite_skip_folders):
                                    continue
                            # Skip duck maker extension folders for all versions
                            elif any(img_dir.lower() in root.lower() for img_dir in ['DuckMaker.extension']):
                                continue
                            for filename in filenames:
                                if is_lite_version:
                                    # Check if it's an .exe file
                                    if filename.lower().endswith('.exe'):
                                        # Only skip if it's not in the allowed list
                                        if filename not in lite_allowed_exes:
                                            continue
                                    elif any(ext in filename.lower() for ext in [
                                        '.dll', ".psd", ".ai"
                                    ]):
                                        continue
                                files.append((os.path.join(root, filename), filename))
                
                total_files = len(files)
                for i in range(0, total_files, batch_size):
                    batch = files[i:i + batch_size]
                    for src_path, filename in batch:
                        rel_path = os.path.relpath(src_path, src_folder)
                        dest_path = os.path.join(dest_folder, rel_path)
                        
                        # Create destination directory if it doesn't exist
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        
                        # Copy file with metadata preservation
                        shutil.copy2(src_path, dest_path)
                
                print("Copying to {} took {} seconds".format(
                    os.path.join(dist_folder, folder),
                    int(time.time() - time_stamp)
                ))

                if exe_backup_dir and os.path.isdir(exe_backup_dir):
                    restored_dest = os.path.join(dist_folder, EXE_PRODUCTS_REL)
                    if _count_exe_files(restored_dest) == 0:
                        os.makedirs(os.path.dirname(restored_dest), exist_ok=True)
                        shutil.copytree(exe_backup_dir, restored_dest)
                        print(
                            "Restored dist ExeProducts from backup ({} exes)".format(
                                _count_exe_files(restored_dest)
                            )
                        )
                    try_remove_content(exe_backup_dir)

            lite_note = ""
            if is_lite_version:
                lite_note = """# ⚠️ LITE VERSION ⚠️

This is the **LITE VERSION** of the distribution repository, optimized for quick installation.

## Excluded Content
The following content has been removed to reduce size:
- ❌ Most executable files (.exe) - **except installer files**
- ❌ Dynamic link libraries (.dll)
- ❌ CAD-related files and folders
- ❌ Engine files and folders
- ❌ Dump scripts
- ❌ Dependency files

## Included Installer Files
The following essential installer files are still included:
- ✅ EnneadTab_OS_Installer.exe
- ✅ EnneadTab_For_Revit_Installer.exe
- ✅ Emailer.exe
- ✅ NotificationHost.exe
- ✅ ProgressBar.exe

For the full version with all features, please use the standard distribution."""

            # Generate README.md
            readme_path = os.path.join(dist_folder, "README.md")
            with open(readme_path, "w", encoding='utf-8') as f:
                readme_content = """# EnneadTab Distribution Repository

## 📅 Last Updated
{}

{}

## 📦 Contents
This repository contains:
- 📂 Apps
- 📂 Installation

## ⚠️ Important Notes
- This repository is **automatically generated** and not manually maintained
- For support, please contact szhang@ennead.com directly

## 🙏 Acknowledgments
- Special thanks to all users who have provided feedback and suggestions
- Special thanks to Ehsan and the pyRevit team for providing the foundation for the Revit Extension

## 💭 Wisdom of the Day
{}

---
*Have a nice day! Hope you enjoy using this product.*
""".format(time.strftime("%Y-%m-%d %H:%M:%S"), lite_note, JOKE.random_joke())
                f.write(readme_content)
        except Exception as e:
            print("Error copying files to distribution repository: {}".format(str(e)))
            raise e

    def _start_longest_path_check_thread(self):
        """
        Start longest file path checking in a background thread.
        This prevents blocking the main publishing workflow.
        """

        msg = "🗂️ [BACKGROUND] Longest path scan started in background. Main publishing will continue..."
        print(msg)
        print("Note: Path scan results will be saved to longest_paths.json when complete.")
        sys.stdout.flush()
        self._print_title("\n\nStarting longest file path scan in background thread...")
        longest_path_thread = threading.Thread(
            target=self._perform_longest_path_check,
            name="LongestPathCheckThread"
        )
        longest_path_thread.daemon = True  # Thread will not prevent main process from exiting
        longest_path_thread.start()

    def _perform_longest_path_check(self):
        """
        Perform the actual longest file path checking in a separate thread.
        This method handles all the heavy lifting of scanning file paths.
        """
        try:
            print("[LONGEST PATH THREAD] Begin scanning for longest file paths...")
            
            # Store file paths and their lengths
            file_paths = []
            
            # Walk through the repository
            for root, _, files in os.walk(self.os_repo_folder):
                for file in files:
                    full_path = os.path.join(root, file)
                    # Skip .git directory
                    if '.git' in full_path:
                        continue
                    file_paths.append((full_path, len(full_path)))
            
            # Sort by path length in descending order
            file_paths.sort(key=lambda x: x[1], reverse=True)
            
            # Save to JSON file in DarkSide folder
            json_data = []
            for path, length in file_paths:
                json_data.append({
                    "path": path,
                    "length": length
                })
            
            json_path = os.path.join(os.path.dirname(__file__), "longest_paths.json")
            with open(json_path, "w") as f:
                json.dump(json_data, f, indent=4)
            
            # Print top 10 longest paths
            yellow_text = "\033[93m"
            red_text = "\033[91m"
            reset_text = "\033[0m"
            
            print("\n[LONGEST PATH THREAD] Top 10 longest file paths:")
            print("-" * 100)
            
            for i, (path, length) in enumerate(file_paths[:10], 1):
                color = red_text if length > 250 else yellow_text if length > 200 else reset_text
                print(f"{i}. {color}Length: {length}{reset_text}")
                print(f"   {path}")
                print("-" * 100)
            
            # Print summary
            if file_paths:
                max_length = file_paths[0][1]
                if max_length > 250:
                    print(f"\n{red_text}[LONGEST PATH THREAD] WARNING: Some file paths exceed 250 characters!{reset_text}")
                    print("Windows has a maximum path length limit of 260 characters.")
                    print("Consider shortening these paths to avoid potential issues.")
                elif max_length > 200:
                    print(f"\n{yellow_text}[LONGEST PATH THREAD] NOTE: Some file paths are approaching the Windows limit.{reset_text}")
                    print("Consider monitoring these paths for future growth.")
                
                print(f"\n[LONGEST PATH THREAD] Results saved to: {json_path}")
                print("[LONGEST PATH THREAD] Longest path scan completed successfully!")
                
                # Show completion notification
                try:
                    NOTIFICATION.duck_pop("Longest file path scan completed!")
                except:
                    pass  # Ignore notification errors
                    
        except Exception as e:
            print("[LONGEST PATH THREAD] Error during longest path scan: {}".format(str(e)))
            print("[LONGEST PATH THREAD] Traceback:")
            print(traceback.format_exc())

    def _print_longest_file_paths(self):
        """
        Find and display the top 10 longest file paths in the repository.
        This helps identify potential Windows path length issues (max 260 chars).
        Also saves results to a JSON file in the DarkSide folder for future reference.
        """

        self._print_title("\n\nBegin scanning for longest file paths...")
        
        # Store file paths and their lengths
        file_paths = []
        
        # Walk through the repository
        for root, _, files in os.walk(self.os_repo_folder):
            for file in files:
                full_path = os.path.join(root, file)
                # Skip .git directory
                if '.git' in full_path:
                    continue
                file_paths.append((full_path, len(full_path)))
        
        # Sort by path length in descending order
        file_paths.sort(key=lambda x: x[1], reverse=True)
        
        # Save to JSON file in DarkSide folder
        json_data = []
        for path, length in file_paths:
            json_data.append({
                "path": path,
                "length": length
            })
        
        json_path = os.path.join(os.path.dirname(__file__), "longest_paths.json")
        with open(json_path, "w") as f:
            json.dump(json_data, f, indent=4)
        
        # Print top 10 longest paths
        yellow_text = "\033[93m"
        red_text = "\033[91m"
        reset_text = "\033[0m"
        
        print("\nTop 10 longest file paths:")
        print("-" * 100)
        
        for i, (path, length) in enumerate(file_paths[:10], 1):
            color = red_text if length > 250 else yellow_text if length > 200 else reset_text
            print(f"{i}. {color}Length: {length}{reset_text}")
            print(f"   {path}")
            print("-" * 100)
        
        # Print summary
        if file_paths:
            max_length = file_paths[0][1]
            if max_length > 250:
                print(f"\n{red_text}WARNING: Some file paths exceed 250 characters!{reset_text}")
                print("Windows has a maximum path length limit of 260 characters.")
                print("Consider shortening these paths to avoid potential issues.")
            elif max_length > 200:
                print(f"\n{yellow_text}NOTE: Some file paths are approaching the Windows limit.{reset_text}")
                print("Consider monitoring these paths for future growth.")
            
            print(f"\nResults saved to: {json_path}")

    def _generate_exe_hash_file(self):
        """
        Generate a hash data file for all exe files in the Apps/lib/ExeProducts folder.
        
        Creates a JSON file containing SHA256 hash of each executable.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            exe_folder = os.path.join(self.os_repo_folder, "Apps", "lib", "ExeProducts")
            hash_file = os.path.join(self.os_repo_folder, "Installation", "exe_hash.json")

            print("Looking for executables in: {}".format(exe_folder))
            print("Will save hash file to: {}".format(hash_file))

            if not os.path.isdir(exe_folder):
                print("ExeProducts folder not found at {}, skipping hash generation".format(exe_folder))
                return False

            # get all exe files in the folder
            exe_files = [f for f in os.listdir(exe_folder) if f.endswith(".exe")]
            
            if not exe_files:
                print("No executable files found in {}".format(exe_folder))
                return False

            # generate hash for each exe file
            hash_data = {}
            total_files = len(exe_files)
            
            print("\nGenerating hashes for {} executable files...".format(total_files))
            print("Found files: {}".format(", ".join(exe_files)))
            
            for index, exe in enumerate(exe_files, 1):
                try:
                    file_path = os.path.join(exe_folder, exe)
                    print("Processing {}/{}: {}".format(index, total_files, exe))
                    
                    # Generate SHA256 hash
                    import hashlib
                    sha256_hash = hashlib.sha256()
                    with open(file_path, "rb") as f:
                        # Read file in chunks to handle large files
                        while True:
                            byte_block = f.read(4096)
                            if not byte_block:
                                break
                            sha256_hash.update(byte_block)
                
                    # Store hash
                    hash_data[exe] = sha256_hash.hexdigest()
                    print("Generated hash for {}: {}".format(exe, hash_data[exe][:10] + "..."))
                    
                except Exception as e:
                    print("Error processing {}: {}".format(exe, str(e)))
                    continue
            
            # Save hash data to JSON file
            with open(hash_file, "w") as f:
                json.dump(hash_data, f, indent=4)
            
            print("\nHash data saved to: {}".format(hash_file))
            return True
            
        except Exception as e:
            print("Error generating hash file: {}".format(str(e)))
            print("Full error details:")
            import traceback
            traceback.print_exc()
            return False

    def _run_acc_project_summary(self):
        """Run ACC project summary in a separate thread."""
        # Always run ACC summary - removed random skip logic
        
        print("📊 [BACKGROUND] ACC project summary will run in background.")
        sys.stdout.flush()
        def _run_in_thread():
            try:
                from REVIT import REVIT_ACC # type: ignore
                REVIT_ACC.get_ACC_summary_data(show_progress=True)
            except Exception as e:
                print("Error in ACC project summary thread: {}".format(str(e)))
                print(traceback.format_exc())
        # Daemon, tracked and joined with a bound -- NOT survive-the-process.
        #
        # This was non-daemon, commented "ensures the thread survives main program
        # termination". Under a Scheduled Task nobody noticed a lingering python,
        # but a CI runner waits on every non-daemon thread before the job can end,
        # so an ACC summary that stalls stalls the entire job with nothing to time
        # it out. publish() now joins it with a timeout and says so if it did not
        # finish, instead of the process silently hanging or silently not waiting.
        thread = threading.Thread(target=_run_in_thread, name="acc-project-summary")
        thread.daemon = True
        thread.start()
        self._background_threads.append(thread)
        return True

    def _sign_exeproducts(self):
        """Code-sign the ExeProducts exes via Azure Trusted Signing (best-effort, non-fatal).

        Runs DarkSide/exes/sign-exeproducts.ps1, which signs each exe with signtool + the Trusted
        Signing dlib using the runner-local AZURE_* credential. The script self-degrades to a no-op
        when AZURE_CLIENT_SECRET is absent, so this never blocks a publish -- it only signs when the
        publish job lands on the `signing` runner. MUST be called BEFORE _generate_exe_hash_file so
        exe_hash.json fingerprints the signed bytes. Never raises: a signing failure logs loudly and
        continues (the unsigned exes still publish).
        """
        exe_dir = os.path.join(self.os_repo_folder, "Apps", "lib", "ExeProducts")
        script = os.path.join(DARKSIDE_DIR, "exes", "sign-exeproducts.ps1")
        if not os.path.isfile(script):
            print("    sign-exeproducts.ps1 not found at {}, skipping signing".format(script))
            return
        if not os.path.isdir(exe_dir):
            print("    ExeProducts folder not found, skipping signing")
            return
        print("Begin signing ExeProducts (Azure Trusted Signing)...")
        try:
            # -ExecutionPolicy Bypass so a Restricted runner policy can't block the script.
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
                 "-ExeProductsDir", exe_dir],
                cwd=self.os_repo_folder, capture_output=True, text=True, timeout=1800)
            if result.stdout:
                print(result.stdout.strip())
            if result.returncode != 0:
                # Non-fatal: unsigned exes still publish. Surface loudly (never silent).
                print("    WARNING: sign-exeproducts.ps1 exited {} -- publishing UNSIGNED exes.".format(result.returncode))
                if result.stderr:
                    print(result.stderr.strip())
        except Exception as e:
            print("    WARNING: signing step failed ({}) -- publishing UNSIGNED exes.".format(str(e)))

    def _start_exe_hash_thread(self):
        """
        Start exe hash file generation in a background thread.
        This prevents blocking the main publishing workflow.
        """
        msg = "🚀 [BACKGROUND] Exe hash file generation started in background. Main publishing will continue..."
        print(msg)
        print("Note: Hash results will be saved to exe_hash.json when complete.")
        sys.stdout.flush()
        self._print_title("\n\nStarting exe hash file generation in background thread...")
        exe_hash_thread = threading.Thread(
            target=self._perform_exe_hash_generation,
            name="ExeHashGenerationThread"
        )
        exe_hash_thread.daemon = True
        exe_hash_thread.start()

    def _perform_exe_hash_generation(self):
        """
        Perform the actual exe hash file generation in a separate thread.
        """
        try:
            print("[EXE HASH THREAD] Begin generating exe hashes...")
            self._generate_exe_hash_file()
            print("[EXE HASH THREAD] Exe hash generation completed!")
            try:
                NOTIFICATION.duck_pop("Exe hash generation completed!")
            except:
                pass
        except Exception as e:
            print(f"[EXE HASH THREAD] Error: {e}")
            import traceback
            print(traceback.format_exc())

    @time_it
    def publish(self):
        """
        Execute complete publishing workflow.
        """
        try:
            # Clean repository
            self._purge_by_extension()

            # Mirror standalone service-factory installers into ExeProducts. MUST run synchronously
            # and to completion BEFORE _start_exe_hash_thread() so the hash thread's one-shot folder
            # enumeration includes the fresh installers. Never raises (skips-with-warning on failure).
            self._mirror_service_factory_installers()

            # Sign the ExeProducts exes with Azure Trusted Signing so the copy that ships to
            # EA_Dist (the fleet) is signed and passes corporate endpoint security. MUST run
            # synchronously here -- BEFORE the exe-hash thread below -- so exe_hash.json reflects
            # the SIGNED bytes. Degrades to a no-op when AZURE_CLIENT_SECRET is absent, so it never
            # blocks publish. The monolith's own commit is local-only (never pushed), so nothing
            # signed is committed to EnneadTab-OS history; only the EA_Dist copy ships signed.
            # Requires this job to run on the `signing` runner (see publish-production.yml runs-on).
            self._sign_exeproducts()

            # generate exe hash file in background
            self._start_exe_hash_thread()

            # find longest file path that is in danger of being too long and exceed window path limit
            # print rank top 10 longest file paths - now runs in background thread
            self._start_longest_path_check_thread()
            
            # Handle compilation
            self._get_compilation_confirmation()
            self._handle_compilation()
            
            # Verify and update files
            self._confirm_all_exe_existing()
            
            # Update installation folder in main repo first
            self._update_installer_folder_exes()
            
            # Update other distribution files
            self._update_indesign_apps()

            # Update RUI files
            self._update_rui_files()

            # Update documentation (local PDFs). Handbook distribution is wiki
            # ingest (_generate_wiki_website below), not EI upload — retired 2026-08-11.
            self._generate_documentation()

            # Record everything the steps above generated INTO this repo, before
            # the copy ships it. Must run after all generation and before the sync.
            self._commit_generated_artifacts()

            # Sync repositories
            self._sync_repositories()
            
            # Final tasks
            self._remind_all_to_do_items()

            # 2026-08-11: publisher no longer writes to the office shared root
            # (standalone exe collection, NightRunner scripts). L: is not a
            # publish destination. The Shanghai BackupRepo mirror is retired;
            # updates go through EnneadTab_OS_Installer only.
            self._run_acc_project_summary()

            # generate wiki website
            self._generate_wiki_website()
            
            # Post-publish verification
            self._post_publish_verification()

            self._join_background_threads()
            self._print_run_summary()

        except Exception as e:
            NOTIFICATION.messenger("Publishing failed: {}".format(str(e)))
            raise
        finally:
            # Final memory cleanup
            gc.collect()

    def _update_pc_version_lookup(self):
        print("Begin updating pc version lookup...")
        python_script = os.path.join(self.os_repo_folder, "Apps", "lib", "EnneadTab", "scripts", "ApplicationListToExcel.py")
        self._run_python_script(python_script)

    def _run_python_script(self, script_path):
        """
        Run a Python script using the virtual environment's Python interpreter.
        
        Args:
            script_path (str): Path to the Python script to run
        """
        # Get the virtual environment's Python interpreter path
        venv_python = os.path.join(self.os_repo_folder, ".venv", "Scripts", "python.exe")
        
        if not os.path.exists(venv_python):
            print("Warning: Virtual environment Python not found at {}".format(venv_python))
            print("Falling back to system Python...")
            venv_python = "python"
        
        # Run the script using the virtual environment's Python
        try:
            result = subprocess.run([venv_python, script_path], 
                                  capture_output=True, 
                                  text=True,
                                  check=True)
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print("Script errors/warnings:")
                print(result.stderr)
        except subprocess.CalledProcessError as e:
            print("Error running script:")
            print(e.stderr)


def play_success_sound():
    """
    Play a success sound effect with improved error handling for paths with spaces.
    """
    try:
        # Try to use the SOUND module first
        
        SOUND.play_sound("sound_effect_spring")
    except Exception as e:
        # Silently fail if all sound methods fail
        print("Warning: Could not play sound effect - {}".format(str(e)))
        pass

@time_it
def publish():
    """Main publish function with enhanced error handling and retry mechanisms"""
    max_retries = 3
    retry_delay = 60  # seconds
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"\n{'='*80}")
            print(f"Publish attempt {attempt}/{max_retries}")
            print(f"{'='*80}")
            
            # Pre-publish health check
            if not _pre_publish_health_check():
                print("[ERROR] Pre-publish health check failed")
                if attempt < max_retries:
                    print(f"⏳ Waiting {retry_delay} seconds before retry...")
                    time.sleep(retry_delay)
                    continue
                else:
                    raise Exception("Pre-publish health check failed after all retries")
            
            publisher = RepoPublisher()
            publisher.publish()

            # A publish that could not push is NOT a success, however many
            # individual steps printed OK. Deliberately NOT retried: the retry loop
            # re-runs the whole destructive copy, and a push failure is not the
            # transient class the health-check retry was built for.
            publish_failures = publisher.all_publish_failures()
            if publish_failures:
                print("\n[FAILED] Publish did not complete -- {} target(s) not pushed:".format(
                    len(publish_failures)))
                for repo_name, err in publish_failures:
                    print("  * {}: {}".format(repo_name, err))
                return False

            play_success_sound()

            print("[OK] Publish completed successfully")
            return True

        except PublishValidationError as e:
            # TERMINAL. A safety gate said no; retrying re-runs the whole
            # destructive copy + force-push against the same tree and the same
            # verdict, so it can only waste time and add noise.
            #
            # The all_publish_failures path above already documents this decision
            # ("Deliberately NOT retried"), but it only covers failures RETURNED.
            # _post_publish_verification RAISES, so it fell through to the generic
            # handler below and got retried anyway -- the 2026-08-07 rehearsal hit
            # exactly that, burning a second full copy + push before dying. Same
            # decision, both paths.
            print("\n[FAILED] Publish blocked by a safety gate on attempt {}:".format(attempt))
            print("  {}".format(str(e)))
            print("  Not retried -- the gate would reach the same verdict, and the "
                  "retry re-runs the destructive copy and force-push.")
            return False

        except Exception as e:
            print(f"\n[ERROR] Publish attempt {attempt} failed:")
            print("-" * 50)
            import traceback
            traceback.print_exc()
            print("-" * 50)
            print(f"Error: {str(e)}")
            
            if attempt < max_retries:
                print(f"⏳ Waiting {retry_delay} seconds before retry...")
                time.sleep(retry_delay)
                # Increase delay for next attempt
                retry_delay = min(retry_delay * 2, 300)  # Max 5 minutes
            else:
                print("[ERROR] All publish attempts failed")
                raise e
    
    return False

def _pre_publish_health_check():
    """
    Perform pre-publish health checks to identify potential issues.
    
    Returns:
        bool: True if all checks pass, False otherwise
    """
    print("🔍 Performing pre-publish health checks...")
    
    try:
        # Check disk space
        repo_path = find_repo_folder()
        import shutil
        total, used, free = shutil.disk_usage(repo_path)
        free_gb = free / (1024**3)
        
        if free_gb < 5:  # Less than 5GB free
            print(f"❌ Insufficient disk space: {free_gb:.1f}GB free (need at least 5GB)")
            return False
        else:
            print(f"✅ Disk space: {free_gb:.1f}GB free")
        
        # Check network connectivity
        try:
            import urllib.request
            urllib.request.urlopen('https://github.com', timeout=10)
            print("✅ Network connectivity: OK")
        except Exception as e:
            print(f"❌ Network connectivity failed: {str(e)}")
            return False
        
        # Check Git availability
        try:
            result = subprocess.run([get_git_executable(), '--version'], 
                                  capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print("✅ Git availability: OK")
            else:
                print("❌ Git not available")
                return False
        except Exception as e:
            print(f"❌ Git check failed: {str(e)}")
            return False
        
        # Check for running Git processes
        try:
            _kill_stray_git()
            cleared = clear_stale_git_locks(repo_path)
        except Exception as e:
            print(f"⚠️ Could not check for stale git locks: {str(e)}")
        
        # Check repository status
        try:
            result = subprocess.run([get_git_executable(), 'status', '--porcelain'], 
                                  cwd=repo_path, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                if result.stdout.strip():
                    # A dirty tree is a HARD ABORT, never an auto-commit.
                    #
                    # This used to stage the entire tree and commit it as
                    # "Auto-commit before publish", after which the copy step
                    # shipped that tree to every machine in the firm. Whatever
                    # happened to be open -- half-finished edits, debug prints, an
                    # experiment -- became the distribution, and the OS history
                    # collected Auto-commit noise nobody wrote on purpose.
                    #
                    # Nothing about "there is uncommitted work here" implies "and
                    # it is ready to publish". The operator has to say so, by
                    # committing or stashing. Refusing costs one command; guessing
                    # wrong ships unreviewed code to everyone.
                    changed = result.stdout.strip().splitlines()
                    print("[ABORT] Repository has {} uncommitted change(s); refusing to publish."
                          .format(len(changed)))
                    for line in changed[:20]:
                        print("    {}".format(line))
                    if len(changed) > 20:
                        print("    ... and {} more".format(len(changed) - 20))
                    print("  Commit or stash them, then publish again.")
                    print("  (This used to auto-commit and publish the tree as-is.)")
                    return False
                else:
                    print("✅ Repository is clean")
            else:
                print("❌ Could not check repository status")
                return False
        except Exception as e:
            print(f"❌ Repository status check failed: {str(e)}")
            return False
        
        sys.path.insert(0, _SCRIPT_DIR)
        try:
            from publish_guard import (
                check_ruiwriter_yaml, check_wiki_api_key, check_wiki_requests)
        finally:
            if sys.path and sys.path[0] == _SCRIPT_DIR:
                sys.path.pop(0)
        capability = (
            check_ruiwriter_yaml()
            + check_wiki_requests()
            + check_wiki_api_key(repo_path)
        )
        if capability:
            for problem in capability:
                print("[ABORT] {}".format(problem))
            raise PublishValidationError(str(capability[0]))
        print("✅ RuiWriter yaml: importable")
        print("✅ Wiki ingest requests: importable")
        print("✅ Wiki API key: present")
        
        print("✅ All pre-publish health checks passed")
        return True

    except PublishValidationError:
        raise
    except Exception as e:
        print(f"❌ Pre-publish health check failed: {str(e)}")
        return False

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
