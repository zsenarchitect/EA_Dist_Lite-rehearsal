"""
ExeMaker - A tool for building and managing executable files for EnneadTab.

This module provides functionality to:
- Build executables using PyInstaller
- Manage executable configurations
- Handle file operations and versioning
- Provide a GUI interface for building executables
"""

import os
import json
import shutil
import subprocess
import traceback  # noqa: F401
import sys
import time
import re
import logging
import argparse
from pathlib import Path  # noqa: F401
from typing import List, Dict, Optional, Union  # noqa: F401
import tkinter as tk
from tkinter import ttk
from fuzzywuzzy import fuzz
import tkinter.messagebox as messagebox

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Color codes for better console output
class Colors:
    """ANSI color codes for console output"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    # Standard colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright colors
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    # Background colors
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'

def print_progress(message: str, color: str = Colors.CYAN) -> None:
    """Print progress message with color and formatting"""
    print(f"{color}{Colors.BOLD}[PROGRESS]{Colors.RESET} {color}{message}{Colors.RESET}")

def print_success(message: str) -> None:
    """Print success message with green color"""
    print(f"{Colors.BRIGHT_GREEN}{Colors.BOLD}[SUCCESS]{Colors.RESET} {Colors.BRIGHT_GREEN}{message}{Colors.RESET}")

def print_error(message: str) -> None:
    """Print error message with red color"""
    print(f"{Colors.BRIGHT_RED}{Colors.BOLD}[ERROR]{Colors.RESET} {Colors.BRIGHT_RED}{message}{Colors.RESET}")

def print_warning(message: str) -> None:
    """Print warning message with yellow color"""
    print(f"{Colors.BRIGHT_YELLOW}{Colors.BOLD}[WARNING]{Colors.RESET} {Colors.BRIGHT_YELLOW}{message}{Colors.RESET}")

def print_info(message: str) -> None:
    """Print info message with blue color"""
    print(f"{Colors.BRIGHT_BLUE}{Colors.BOLD}[INFO]{Colors.RESET} {Colors.BRIGHT_BLUE}{message}{Colors.RESET}")

def print_debug(message: str) -> None:
    """Print debug message with gray color"""
    print(f"{Colors.BRIGHT_BLACK}[DEBUG] {message}{Colors.RESET}")

def print_step(step: int, total: int, name: str) -> None:
    """Print step progress with formatting"""
    percentage = int((step / total) * 100)
    bar_length = 20
    filled_length = int((step / total) * bar_length)
    bar = '#' * filled_length + '.' * (bar_length - filled_length)
    print(f"{Colors.BRIGHT_CYAN}{Colors.BOLD}[{step:2d}/{total:2d}]{Colors.RESET} {Colors.CYAN}[{bar}] {percentage:3d}% - {Colors.BRIGHT_WHITE}{name}{Colors.RESET}")

# Disable pygame support prompt
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "True"

# Add EnneadTab to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))) + "\\Apps\\lib\\EnneadTab")

from ENVIRONMENT import ROOT, EXE_PRODUCT_FOLDER, PLUGIN_EXTENSION  # pyright: ignore
import NOTIFICATION  # pyright: ignore
import SOUND   # pyright: ignore

# Constants
DARKSIDE_FOLDER = os.path.dirname(os.path.dirname(__file__))
EXE_FOLDER = os.path.join(DARKSIDE_FOLDER, "exes")
EXE_MAKER_FOLDER = os.path.join(EXE_FOLDER, "maker data")
EXE_SOURCE_CODE_FOLDER = os.path.join(EXE_FOLDER, "source code")
TEMP_SPEC_FOLDER = os.path.join(EXE_FOLDER, "temp_specs")

PYGAME_ALLOWS = [
    "Speaker",
    "LastSyncMonitor",
    "ScheduleOpener",
    "AutoClicker"
]
PYGAME_EXCLUDES = [x + PLUGIN_EXTENSION for x in PYGAME_ALLOWS]

PY_INSTALLER_LOCATION = "pyinstaller"
# Prefer invoking PyInstaller via the project's .venv python
VENV_PYTHON = os.path.join(ROOT, ".venv", "Scripts", "python.exe")

class NoGoodSetupException(Exception):
    """Exception raised when the setup is incomplete or on a new computer."""
    def __init__(self):
        super().__init__("The setup is not complete or you are working on a new computer.")

class ExeBuilder:
    """Handles the building and management of executable files."""
    
    def __init__(self):
        """Initialize the ExeBuilder with default settings."""
        self.logger = logging.getLogger(__name__)
    
    def move_exes(self) -> None:
        """Move compiled executables from dist folder to product folder."""
        src_folder = os.path.join(EXE_FOLDER, "dist")
        print_progress("Starting executable file movement process...")
        print_debug(f"Source folder: {src_folder}")
        print_debug(f"Destination folder: {EXE_PRODUCT_FOLDER}")
        
        if not os.path.exists(src_folder):
            print_warning("Source dist folder does not exist - no files to move")
            print_debug(f"Expected dist folder at: {src_folder}")
            
            # Check for dist folder in other common locations
            alt_locations = [
                os.path.join(ROOT, "dist"),
                os.path.join(EXE_SOURCE_CODE_FOLDER, "dist"),
                os.path.join(os.getcwd(), "dist")
            ]
            for alt_loc in alt_locations:
                if os.path.exists(alt_loc):
                    print_warning(f"Found dist folder at unexpected location: {alt_loc}")
            return
            
        items = os.listdir(src_folder)
        if not items:
            print_warning("No files found in dist folder")
            return
            
        print_info(f"Found {len(items)} items to move")
        move_errors = []
        
        for i, item in enumerate(items, 1):
            src_item = os.path.join(src_folder, item)
            dest_item = os.path.join(EXE_PRODUCT_FOLDER, item)
            
            print_step(i, len(items), f"Moving {item}")
            
            for attempt in range(3):
                try:
                    if os.path.isdir(src_item):
                        if os.path.exists(dest_item):
                            shutil.rmtree(dest_item)
                        shutil.copytree(src_item, dest_item)
                    else:
                        shutil.copyfile(src_item, dest_item)
                    print_success(f"Successfully moved {item}")
                    break
                except Exception as e:
                    self.logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
                    print_debug(f"Attempt {attempt + 1} failed: {str(e)}")
                    if attempt < 2:
                        print_warning(f"Retrying in 2 seconds... (attempt {attempt + 2}/3)")
                        time.sleep(2)
                    else:
                        print_error(f"Failed to move {item} after 3 attempts")
                        move_errors.append(f"{item}: {str(e)}")
        
        print_progress("Cleaning up temporary files...")
        try:
            shutil.rmtree(src_folder)
            print_success("Removed temporary dist folder")
        except Exception as e:
            self.logger.error(f"Failed to remove dist folder: {str(e)}")
            print_error(f"Failed to remove dist folder: {str(e)}")
        
        if move_errors:
            error_msg = "Some files could not be moved to ExeProducts:\n\n" + "\n".join(move_errors)
            print_error("File movement completed with errors:")
            for error in move_errors:
                print_error(f"  - {error}")
            try:
                messagebox.showerror("Move Error", error_msg)
            except Exception as e:
                print_debug(f"Could not show messagebox: {e}")
                NOTIFICATION.messenger(error_msg)
        else:
            print_success("All files moved successfully!")

    def make_exe(self, maker_json: str) -> None:
        """Build an executable using the provided JSON configuration.
        
        Args:
            maker_json: Path to the JSON configuration file
        """
        exe_name = os.path.basename(maker_json).replace('.sexyDuck', '')
        print_progress(f"Building executable: {exe_name}")
        
        try:
            print_debug(f"Opening configuration file: {maker_json}")
            # utf-8-sig tolerates a UTF-8 BOM, which auto-py-to-exe sometimes writes
            # into .sexyDuck files; a plain text open would feed the BOM to json.load
            # and fail with "Expecting value: line 1 column 1".
            with open(maker_json, "r", encoding="utf-8-sig") as f:
                command = self._json_to_command(f)
                print_info(f"Generated PyInstaller command with {len(command)} arguments")
                print_debug(f"Command: {' '.join(command)}")
                
                print_progress("Running PyInstaller...")
                start_time = time.time()
                result = subprocess.run(command, check=False, capture_output=True, text=True)
                end_time = time.time()
                
                build_time = end_time - start_time
                print_info(f"PyInstaller completed in {build_time:.1f} seconds")
                print_debug(f"PyInstaller return code: {result.returncode}")
                
                if result.returncode == 0:
                    print_success(f"Successfully built {exe_name}")
                else:
                    print_error(f"PyInstaller failed for {exe_name}")
                    if result.stderr:
                        print_error("PyInstaller stderr:")
                        for line in result.stderr.strip().split('\n'):
                            print_error(f"  {line}")
                    
        except Exception as e:
            # Get detailed traceback information
            import traceback
            tb_lines = traceback.format_exc().splitlines()
            
            self.logger.error(f"Error building executable: {str(e)}")
            self.logger.error(f"Full traceback: {traceback.format_exc()}")
            
            print_error(f"Exception occurred while building {exe_name}: {str(e)}")
            print_error("Full traceback:")
            for line in tb_lines:
                print_error(f"  {line}")
            raise

    def _repath(self, path: str) -> str:
        """Convert paths to be compatible with any repository name.
        
        Args:
            path: Original path
            
        Returns:
            str: Converted path
        """
        return path.replace("C:\\Users\\szhang\\github\\ennead-llp\\EnneadTab-OS", ROOT)

    def _json_to_command(self, json_file) -> List[str]:
        """Convert JSON configuration to PyInstaller command.
        
        Args:
            json_file: File object containing JSON configuration
            
        Returns:
            List[str]: PyInstaller command arguments
        """
        json_config = json.load(json_file)
        # Build base command: prefer the project .venv Python, then fall back to the
        # interpreter currently running ExeMaker. Invoking `python -m PyInstaller`
        # avoids depending on a `pyinstaller.exe` being on PATH, which is not
        # guaranteed on machines without an activated .venv (WinError 2 otherwise).
        if os.path.exists(VENV_PYTHON):
            command: List[str] = [VENV_PYTHON, "-m", "PyInstaller"]
        else:
            command = [sys.executable, "-m", "PyInstaller"]
        final_path = None

        for option in json_config['pyinstallerOptions']:
            if option["optionDest"] == "filenames":
                final_path = self._repath(option["value"])
                continue

            if option["optionDest"] == "icon_file":
                command.extend(["--icon", self._repath(option['value'])])
                continue

            if option["optionDest"] == "splash":
                command.extend(["--splash", self._repath(option['value'])])
                continue

            if option["optionDest"] == "console":
                command.append("--console" if option['value'] else "--windowed")
                continue

            if option["optionDest"] == "datas":
                command.extend(["--add-data", self._repath(option['value'])])
                continue
            
            if option["optionDest"] == "additional-hooks-dir":
                command.extend(["--additional-hooks-dir", self._repath(option['value'])])
                continue

            if option["optionDest"] == "pathex":
                # auto-py-to-exe's JSON dest name matches the PyInstaller spec-file
                # argument ("pathex"), not the CLI flag, which is --paths.
                command.extend(["--paths", self._repath(option['value'])])
                continue

            if option["optionDest"] == "collect-submodules":
                command.extend(["--collect-submodules", str(option['value'])])
                continue

            if option['value'] is True:
                command.append(f"--{option['optionDest']}")
            elif option['value'] is not False:
                command.extend([f"--{option['optionDest']}", str(option['value'])])

        # Add output path specifications
        dist_path = os.path.join(EXE_FOLDER, "dist")
        work_path = os.path.join(EXE_FOLDER, "build")
        print_debug(f"Setting distpath to: {dist_path}")
        print_debug(f"Setting workpath to: {work_path}")
        command.extend(["--distpath", dist_path])
        command.extend(["--workpath", work_path])
        
        command.append("--log-level=WARN")
        if final_path is None:
            raise ValueError("Missing 'filenames' entry in pyinstallerOptions; cannot determine target script")
        command.append(final_path)

        # Fix: Strip extension for PYGAME_ALLOWS check and add debug info
        exe_base_name = os.path.splitext(os.path.basename(json_file.name))[0]
        if exe_base_name not in PYGAME_ALLOWS:
            print_debug(f"[PYGAME] Excluding pygame for {exe_base_name}")
            command.extend(["--exclude-module", "pygame"])
        else:
            print_debug(f"[PYGAME] Including pygame for {exe_base_name}")

        self.logger.info("Generated command: %s", " ".join(command))
        return command

def create_version_file(final_path):
    with open(os.path.join(EXE_FOLDER, "enneadtab_spec_template.txt"), "r") as template_file:
        template = template_file.read()

    version_info = {
        "CompanyName": "Ennead Architects",
        "FileDescription": "EnneadTab Application",
        "FileVersion": "1.0.0.0",
        "InternalName": "EnneadTab",
        "LegalCopyright": f"Copyright (c) Ennead Architects {time.strftime('%Y')}",
        "OriginalFilename": os.path.basename(final_path),
        "ProductName": "EnneadTab",
        "ProductVersion": "1.0.0.0"
    }


    with open(final_path, "r") as main_py_file:
        main_py_content = main_py_file.read()
        version_info.update(parse_version_info(main_py_content))

    version_file_content = template.format(**version_info)

    if not os.path.exists(TEMP_SPEC_FOLDER):
        os.makedirs(TEMP_SPEC_FOLDER)

    version_file_path = os.path.join(TEMP_SPEC_FOLDER, "{}_version_info.txt".format(os.path.basename(final_path).replace(".py", "")))
    with open(version_file_path, "w") as version_file:
        version_file.write(version_file_content)

    return version_file_path

def parse_version_info(content):
    info = {}
    keys = ["__version__", "__description__"]
    for key in keys:
        match = re.search(r'{} = ["\']([^"\']+)["\']'.format(key), content)
        if match:
            info[key.strip("_")] = match.group(1)
    return info

def commit_and_sync():
    """Commit changes and sync with remote repository"""
    print_progress("Starting Git commit and sync process...")
    
    try:
        # Change to the repository root directory
        os.chdir(ROOT)
        print_info(f"Changed directory to: {ROOT}")
        
        # Add all changes
        print_progress("Adding all changes to Git...")
        subprocess.run(["git", "add", "."], check=True)
        print_success("All changes added to Git")
        
        # Commit with a timestamp message
        print_progress("Creating commit...")
        commit_message = f"Auto-commit: Updated exes at {time.strftime('%Y-%m-%d %H:%M:%S')}"
        # Do not raise on non-zero; treat "nothing to commit" as success
        result = subprocess.run(["git", "commit", "-m", commit_message], check=False, capture_output=True, text=True)
        stdout = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            print_success(f"Commit created: {commit_message}")
        elif "nothing to commit" in stdout.lower():
            print_info("No changes to commit (working tree clean)")
        else:
            raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)
        
        # Push to remote
        print_progress("Pushing to remote repository...")
        subprocess.run(["git", "push"], check=True)
        print_success("Successfully pushed to remote repository")
        
        print_success(f"{Colors.BG_GREEN}{Colors.WHITE}{Colors.BOLD} GIT SYNC COMPLETED SUCCESSFULLY {Colors.RESET}")
        NOTIFICATION.messenger("Git commit and sync completed")
        
    except subprocess.CalledProcessError as e:
        print_error(f"Git operation failed with return code {e.returncode}")
        if e.stderr:
            print_error(f"Error details: {e.stderr}")
        NOTIFICATION.messenger("Git commit and sync failed")
    except Exception as e:
        print_error(f"Unexpected error during git operations: {e}")
        NOTIFICATION.messenger("Git commit and sync failed")

def recompile_exe(single_exe = None, rebuild_installer=False, commit_and_sync_after=False):
    print(f"{Colors.BG_BLUE}{Colors.WHITE}{Colors.BOLD} STARTING EXE COMPILATION PROCESS {Colors.RESET}")
    
    builder = ExeBuilder()
    jobs = os.listdir(EXE_MAKER_FOLDER)
    
    # Filter and count jobs
    actual_jobs = []
    for file in jobs:
        if single_exe and single_exe != file:
            continue
        if "os_installer" in file.lower() and not rebuild_installer:
            print_warning(f"Skipping OS installer: {file} (not rebuilding unless required)")
            continue
        if file.endswith(".sexyDuck"):
            actual_jobs.append(file)
    
    print_info(f"Found {len(actual_jobs)} executables to compile")
    
    if not actual_jobs:
        print_warning("No executables to compile!")
        return
    
    print(f"\n{Colors.BRIGHT_CYAN}{'=' * 60}")
    print(f"{Colors.BRIGHT_CYAN}{Colors.BOLD}COMPILATION QUEUE:")
    for i, file in enumerate(actual_jobs, 1):
        print(f"{Colors.BRIGHT_CYAN}{i:2d}. {Colors.WHITE}{file}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 60}{Colors.RESET}\n")
    
    # Compile each executable
    for i, file in enumerate(actual_jobs, 1):
        print(f"\n{Colors.BG_YELLOW}{Colors.BLACK}{Colors.BOLD} COMPILING {i}/{len(actual_jobs)}: {file} {Colors.RESET}")
        try:
            builder.make_exe(os.path.join(EXE_MAKER_FOLDER, file))
            print_success(f"Completed {file} ({i}/{len(actual_jobs)})")
        except Exception as e:
            import traceback
            tb_lines = traceback.format_exc().splitlines()
            print_error(f"Failed to compile {file}: {str(e)}")
            print_error("Full traceback:")
            for line in tb_lines:
                print_error(f"  {line}")
        print(f"{Colors.BRIGHT_BLACK}{'-' * 80}{Colors.RESET}")

    print(f"\n{Colors.BG_MAGENTA}{Colors.WHITE}{Colors.BOLD} MOVING EXECUTABLES TO PRODUCT FOLDER {Colors.RESET}")
    builder.move_exes()
    
    print_success("Exe compilation process completed!")
    NOTIFICATION.messenger("Exe finish compiling")
    SOUND.play_sound()
    
    # Commit and sync if requested
    if commit_and_sync_after:
        print(f"\n{Colors.BG_CYAN}{Colors.WHITE}{Colors.BOLD} STARTING POST-COMPILATION GIT SYNC {Colors.RESET}")
        commit_and_sync()

class ExeBuilderGUI:
    """GUI interface for building executables."""
    
    def __init__(self):
        """Initialize the GUI with default settings."""
        self.root = tk.Tk()
        self.root.title("EnneadTab Exe Maker")
        self.root.geometry("600x800")  # Made window taller and wider
        
        self.builder = ExeBuilder()
        self.setup_gui()
        
    def setup_gui(self):
        """Set up the GUI components."""
        # Add rebuild installer checkbox
        self.rebuild_var = tk.BooleanVar(value=False)
        self.rebuild_check = ttk.Checkbutton(
            self.root,
            text="Rebuild OS Installer (Warning: Danger! Danger!)",
            variable=self.rebuild_var,
            style='Bold.TCheckbutton'
        )
        self.rebuild_check.pack(pady=10, padx=10, anchor='w')
        
        # Add commit and sync checkbox
        self.commit_sync_var = tk.BooleanVar(value=False)
        self.commit_sync_check = ttk.Checkbutton(
            self.root,
            text="Commit and sync after all done",
            variable=self.commit_sync_var
        )
        self.commit_sync_check.pack(pady=(0, 10), padx=10, anchor='w')
        
        # Create style for bold checkbox
        style = ttk.Style()
        style.configure('Bold.TCheckbutton', font=('TkDefaultFont', 10, 'bold'))
        
        # Create main frame
        frame = ttk.Frame(self.root, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Create search and sort frame
        top_frame = ttk.Frame(frame)
        top_frame.pack(fill=tk.X, pady=(0, 5))
        
        # Create search label and entry
        search_label = ttk.Label(top_frame, text="Search:")
        search_label.pack(side=tk.LEFT, padx=(0, 5))
        
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(top_frame, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Add sort options
        sort_frame = ttk.Frame(frame)
        sort_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.sort_var = tk.StringVar(value="date")
        ttk.Radiobutton(sort_frame, text="Sort by Name", variable=self.sort_var, 
                       value="name", command=self.update_listbox).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(sort_frame, text="Sort by Date", variable=self.sort_var,
                       value="date", command=self.update_listbox).pack(side=tk.LEFT, padx=5)
        
        # Create label
        label = ttk.Label(frame, text="Select exe(s) to compile:")
        label.pack(pady=(0, 5))
        
        # Create canvas and scrollbar for the checkbox frame
        canvas = tk.Canvas(frame)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        self.checkbox_frame = ttk.Frame(canvas)
        
        # Configure canvas
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Pack scrollbar and canvas
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Create window in canvas
        canvas.create_window((0, 0), window=self.checkbox_frame, anchor="nw")
        
        # Configure canvas scrolling
        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self.checkbox_frame.bind("<Configure>", configure_scroll)
        
        # Store all exe files and their checkboxes
        self.exe_files = [f for f in os.listdir(EXE_MAKER_FOLDER) if f.endswith('.sexyDuck')]
        self.checkboxes = {}
        
        # Bind search entry to update function
        self.search_var.trace_add('write', self.update_listbox)
        
        # Initial population of checkboxes
        self.update_listbox()
        
        # Remove previous button frame packing
        # Create buttons frame at the bottom
        button_frame = ttk.Frame(self.root)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=20)

        # Create large buttons
        compile_btn = ttk.Button(button_frame, text="Compile Selected", command=self.compile_selected)
        compile_btn.pack(side=tk.LEFT, padx=20, expand=True, fill=tk.BOTH, ipadx=30, ipady=20)

        compile_all_btn = ttk.Button(button_frame, text="Compile All", command=self.compile_all)
        compile_all_btn.pack(side=tk.RIGHT, padx=20, expand=True, fill=tk.BOTH, ipadx=30, ipady=20)
    
    def update_listbox(self, *args):
        """Update the checkbox list based on search term and sort option."""
        search_term = self.search_var.get().lower()
        
        # Clear existing checkboxes
        for widget in self.checkbox_frame.winfo_children():
            widget.destroy()
        self.checkboxes.clear()
        
        # Filter files based on search term
        filtered_files = []
        for file in self.exe_files:
            if not search_term or fuzz.partial_ratio(search_term, file.lower()) > 60:
                filtered_files.append(file)
        
        # Sort files
        if self.sort_var.get() == "date":
            def get_source_mtime(sexyduck_file):
                import json
                import datetime  # noqa: F401
                try:
                    with open(os.path.join(EXE_MAKER_FOLDER, sexyduck_file), 'r') as f:
                        data = json.load(f)
                        for opt in data.get('pyinstallerOptions', []):
                            if opt.get('optionDest') == 'filenames':
                                source_path = opt.get('value')
                                # Normalize path for current repo
                                if source_path:
                                    # Use the same repath logic as in ExeBuilder
                                    source_path = source_path.replace("C:\\Users\\szhang\\github\\ennead-llp\\EnneadTab-OS", ROOT)
                                    if os.path.exists(source_path):
                                        return os.path.getmtime(source_path)
                except Exception as e:
                    print_debug(f"Failed to get mtime for {sexyduck_file}: {e}")
                # If not found or error, return a very old date
                return 0
            filtered_files.sort(key=get_source_mtime, reverse=True)
        else:
            filtered_files.sort()
        
        # Create checkboxes for filtered files
        for file in filtered_files:
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(self.checkbox_frame, text=file, variable=var)
            cb.pack(anchor='w', padx=5, pady=2)
            self.checkboxes[file] = var
    
    def compile_selected(self):
        """Compile selected executables."""
        print_progress("Starting selected executable compilation")
        selected_files = [file for file, var in self.checkboxes.items() if var.get()]
        print_debug(f"Selected files: {selected_files}")
        
        if not selected_files:
            print_warning("No files selected for compilation")
            return
        
        print_info(f"Compiling {len(selected_files)} selected executables")
        
        print(f"\n{Colors.BRIGHT_CYAN}{'=' * 60}")
        print(f"{Colors.BRIGHT_CYAN}{Colors.BOLD}SELECTED COMPILATION QUEUE:")
        for i, file in enumerate(selected_files, 1):
            print(f"{Colors.BRIGHT_CYAN}{i:2d}. {Colors.WHITE}{file}")
        print(f"{Colors.BRIGHT_CYAN}{'=' * 60}{Colors.RESET}\n")
        
        # Compile each selected file without committing/syncing
        for i, file in enumerate(selected_files, 1):
            print(f"\n{Colors.BG_YELLOW}{Colors.BLACK}{Colors.BOLD} COMPILING {i}/{len(selected_files)}: {file} {Colors.RESET}")
            try:
                self.builder.make_exe(os.path.join(EXE_MAKER_FOLDER, file))
                print_success(f"Completed {file} ({i}/{len(selected_files)})")
            except Exception as e:
                import traceback
                tb_lines = traceback.format_exc().splitlines()
                print_error(f"Failed to compile {file}: {str(e)}")
                print_error("Full traceback:")
                for line in tb_lines:
                    print_error(f"  {line}")
            print(f"{Colors.BRIGHT_BLACK}{'-' * 80}{Colors.RESET}")
        
        print(f"\n{Colors.BG_MAGENTA}{Colors.WHITE}{Colors.BOLD} MOVING EXECUTABLES TO PRODUCT FOLDER {Colors.RESET}")
        self.builder.move_exes()
        
        # Only commit and sync once at the end if requested
        if self.commit_sync_var.get():
            print(f"\n{Colors.BG_CYAN}{Colors.WHITE}{Colors.BOLD} STARTING POST-COMPILATION GIT SYNC {Colors.RESET}")
            self.commit_and_sync()
        
        print_success("Selected compilation process completed!")
        print_info("Closing GUI...")
        self.root.destroy()
    
    def compile_all(self):
        """Compile all executables."""
        print_progress("Starting full executable compilation")
        total_files = len(self.exe_files)
        print_info(f"Found {total_files} total executable files")
        
        # Filter files based on settings
        actual_files = []
        for file in self.exe_files:
            if "os_installer" in file.lower() and not self.rebuild_var.get():
                print_warning(f"Skipping OS installer: {file} (not rebuilding unless required)")
                logger.info("Skipping OS installer compilation")
                continue
            actual_files.append(file)
        
        print_info(f"Will compile {len(actual_files)} executables")
        
        if not actual_files:
            print_warning("No executables to compile!")
            return
        
        print(f"\n{Colors.BRIGHT_CYAN}{'=' * 60}")
        print(f"{Colors.BRIGHT_CYAN}{Colors.BOLD}FULL COMPILATION QUEUE:")
        for i, file in enumerate(actual_files, 1):
            print(f"{Colors.BRIGHT_CYAN}{i:2d}. {Colors.WHITE}{file}")
        print(f"{Colors.BRIGHT_CYAN}{'=' * 60}{Colors.RESET}\n")
        
        # Compile each file
        for i, file in enumerate(actual_files, 1):
            print(f"\n{Colors.BG_YELLOW}{Colors.BLACK}{Colors.BOLD} COMPILING {i}/{len(actual_files)}: {file} {Colors.RESET}")
            try:
                self.builder.make_exe(os.path.join(EXE_MAKER_FOLDER, file))
                print_success(f"Completed {file} ({i}/{len(actual_files)})")
            except Exception as e:
                import traceback
                tb_lines = traceback.format_exc().splitlines()
                print_error(f"Failed to compile {file}: {str(e)}")
                print_error("Full traceback:")
                for line in tb_lines:
                    print_error(f"  {line}")
            print(f"{Colors.BRIGHT_BLACK}{'-' * 80}{Colors.RESET}")
        
        print(f"\n{Colors.BG_MAGENTA}{Colors.WHITE}{Colors.BOLD} MOVING EXECUTABLES TO PRODUCT FOLDER {Colors.RESET}")
        self.builder.move_exes()
        
        if self.commit_sync_var.get():
            print(f"\n{Colors.BG_CYAN}{Colors.WHITE}{Colors.BOLD} STARTING POST-COMPILATION GIT SYNC {Colors.RESET}")
            self.commit_and_sync()
        
        print_success("Full compilation process completed!")
        print_info("Closing GUI...")
        self.root.destroy()
    
    def commit_and_sync(self):
        """Commit changes and sync with remote repository."""
        print_progress("Starting Git commit and sync process...")
        
        try:
            os.chdir(ROOT)
            print_info(f"Changed directory to: {ROOT}")
            
            print_progress("Adding all changes to Git...")
            subprocess.run(["git", "add", "."], check=True)
            print_success("All changes added to Git")
            
            print_progress("Creating commit...")
            commit_message = f"Auto-commit: Updated exes at {time.strftime('%Y-%m-%d %H:%M:%S')}"
            result = subprocess.run(["git", "commit", "-m", commit_message], check=False, capture_output=True, text=True)
            out = (result.stdout or "") + (result.stderr or "")
            if result.returncode == 0:
                print_success(f"Commit created: {commit_message}")
            elif "nothing to commit" in out.lower():
                print_info("No changes to commit (working tree clean)")
            else:
                raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)
            
            print_progress("Pushing to remote repository...")
            subprocess.run(["git", "push"], check=True)
            print_success("Successfully pushed to remote repository")
            
            print_success(f"{Colors.BG_GREEN}{Colors.WHITE}{Colors.BOLD} GIT SYNC COMPLETED SUCCESSFULLY {Colors.RESET}")
            logger.info("Successfully committed and synced changes")
            NOTIFICATION.messenger("Git commit and sync completed")
        except subprocess.CalledProcessError as e:
            print_error(f"Git operation failed with return code {e.returncode}")
            if hasattr(e, 'stderr') and e.stderr:
                print_error(f"Error details: {e.stderr}")
            logger.error(f"Error during git operations: {e}")
            NOTIFICATION.messenger("Git commit and sync failed")
        except Exception as e:
            print_error(f"Unexpected error during git operations: {e}")
            logger.error(f"Unexpected error during git operations: {e}")
            NOTIFICATION.messenger("Git commit and sync failed")
    
    def run(self):
        """Run the GUI application."""
        self.root.mainloop()
    
    def compile_from_cli(self, sexyduck_file):
        """Compile executable from CLI using .sexyDuck file"""
        try:
            print(f"Loading configuration from: {sexyduck_file}")
            
            # Load the .sexyDuck file (utf-8-sig tolerates a leading BOM)
            with open(sexyduck_file, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
            
            # Extract PyInstaller options
            pyinstaller_options = config.get('pyinstallerOptions', [])
            non_pyinstaller_options = config.get('nonPyinstallerOptions', {})
            
            # Build PyInstaller command
            cmd = [sys.executable, '-m', 'PyInstaller']
            
            # Extract app name from .sexyDuck filename
            app_name = os.path.splitext(os.path.basename(sexyduck_file))[0]
            print(f"[INFO] App name: {app_name}")
            
            # Add PyInstaller options
            for option in pyinstaller_options:
                option_dest = option.get('optionDest')
                value = option.get('value')
                
                if option_dest == 'filenames':
                    cmd.append(value)
                elif option_dest == 'onefile' and value:
                    cmd.append('--onefile')
                elif option_dest == 'console' and not value:
                    cmd.append('--noconsole')
                elif option_dest == 'icon_file' and value:
                    cmd.extend(['--icon', value])
                elif option_dest == 'clean_build' and value:
                    cmd.append('--clean')
                elif option_dest == 'strip' and value:
                    cmd.append('--strip')
                elif option_dest == 'noupx' and value:
                    cmd.append('--noupx')
                elif option_dest == 'disable_windowed_traceback' and value:
                    cmd.append('--disable-windowed-traceback')
                elif option_dest == 'uac_admin' and value:
                    cmd.append('--uac-admin')
                elif option_dest == 'uac_uiaccess' and value:
                    cmd.append('--uac-uiaccess')
                elif option_dest == 'argv_emulation' and value:
                    cmd.append('--argv-emulation')
                elif option_dest == 'bootloader_ignore_signals' and value:
                    cmd.append('--bootloader-ignore-signals')
                elif option_dest == 'hidden-import' and value:
                    cmd.extend(['--hidden-import', value])
                elif option_dest == 'noconfirm' and value:
                    cmd.append('--noconfirm')
            
            # Add --name option to use app name
            cmd.extend(['--name', app_name])
            
            # Add manual arguments if any
            manual_args = non_pyinstaller_options.get('manualArguments', '')
            if manual_args:
                cmd.extend(manual_args.split())
            
            print(f"Running PyInstaller command: {' '.join(cmd)}")
            print(f"Working directory: {os.path.dirname(sexyduck_file)}")
            
            # Run PyInstaller
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(sexyduck_file))
            
            print(f"PyInstaller return code: {result.returncode}")
            if result.stdout:
                print(f"PyInstaller stdout: {result.stdout}")
            if result.stderr:
                print(f"PyInstaller stderr: {result.stderr}")
            
            if result.returncode == 0:
                print(f"[SUCCESS] Compilation successful!")
                
                # Check if dist folder was created
                dist_folder = os.path.join(os.path.dirname(sexyduck_file), "dist")
                if os.path.exists(dist_folder):
                    print(f"[INFO] Dist folder found: {dist_folder}")
                    items = os.listdir(dist_folder)
                    print(f"[INFO] Found {len(items)} items in dist folder: {items}")
                else:
                    print(f"[WARNING] Dist folder not found at: {dist_folder}")
                
                # Move compiled exe to ExeProducts folder (same as GUI mode)
                print(f"[INFO] Moving compiled files to ExeProducts folder...")
                self._move_exes_cli(os.path.dirname(sexyduck_file))
                
                return True
            else:
                print(f"[ERROR] Compilation failed!")
                return False
                
        except Exception as e:
            import traceback
            tb_lines = traceback.format_exc().splitlines()
            print(f"[ERROR] Error during compilation: {e}")
            print("Full traceback:")
            for line in tb_lines:
                print(f"  {line}")
            logger.error(f"CLI compilation error: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    def _move_exes_cli(self, source_dir):
        """Move compiled executables from CLI compilation to ExeProducts folder."""
        src_folder = os.path.join(source_dir, "dist")
        dest_folder = EXE_PRODUCT_FOLDER
        
        print(f"[PROGRESS] Starting executable file movement process...")
        print(f"[DEBUG] Source folder: {src_folder}")
        print(f"[DEBUG] Destination folder: {dest_folder}")
        
        if not os.path.exists(src_folder):
            print(f"[WARNING] Source dist folder does not exist - no files to move")
            return
            
        items = os.listdir(src_folder)
        if not items:
            print(f"[WARNING] No files found in dist folder")
            return
            
        print(f"[INFO] Found {len(items)} items to move")
        
        # Ensure destination folder exists
        os.makedirs(dest_folder, exist_ok=True)
        
        move_errors = []
        
        for i, item in enumerate(items, 1):
            src_path = os.path.join(src_folder, item)
            dest_path = os.path.join(dest_folder, item)
            
            print(f"[PROGRESS] Moving {i}/{len(items)}: {item}")
            
            try:
                if os.path.exists(dest_path):
                    if os.path.isdir(dest_path):
                        shutil.rmtree(dest_path)
                    else:
                        os.remove(dest_path)
                
                if os.path.isdir(src_path):
                    shutil.move(src_path, dest_path)
                else:
                    shutil.move(src_path, dest_path)
                    
                print(f"[SUCCESS] Moved: {item}")
                
            except Exception as e:
                error_msg = f"Failed to move {item}: {e}"
                print(f"[ERROR] {error_msg}")
                move_errors.append(error_msg)
        
        if move_errors:
            print(f"[WARNING] {len(move_errors)} items failed to move:")
            for error in move_errors:
                print(f"  - {error}")
        else:
            print(f"[SUCCESS] All {len(items)} items moved successfully!")
            
        # Clean up source dist folder
        try:
            shutil.rmtree(src_folder)
            print(f"[INFO] Cleaned up source dist folder")
        except Exception as e:
            print(f"[WARNING] Failed to clean up source dist folder: {e}")

def main():
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(description='ExeMaker - Build executables from .sexyDuck files')
    parser.add_argument('sexyduck_file', nargs='?', help='Path to .sexyDuck configuration file')
    parser.add_argument('--cli', action='store_true', help='Force CLI mode even with GUI available')
    
    args = parser.parse_args()
    
    try:
        # If a .sexyDuck file is provided, compile it via ExeBuilder CLI workflow
        if args.sexyduck_file:
            sexyduck_path = args.sexyduck_file
            if not os.path.exists(sexyduck_path):
                print(f"[ERROR] Error: File not found: {sexyduck_path}")
                return 1
            if not sexyduck_path.endswith(".sexyDuck"):
                print(f"[ERROR] Error: File must have .sexyDuck extension: {sexyduck_path}")
                return 1

            print(f"[INFO] Starting CLI compilation of: {sexyduck_path}")
            builder = ExeBuilder()
            try:
                builder.make_exe(sexyduck_path)
                builder.move_exes()
                print("[SUCCESS] CLI compilation finished successfully.")
                return 0
            except Exception as build_error:
                logger.error("CLI compilation failed", exc_info=build_error)
                print(f"[ERROR] CLI compilation failed: {build_error}")
                return 1

        # If no arguments, open GUI
        print("Opening ExeMaker GUI...")
        gui = ExeBuilderGUI()
        gui.run()
        return 0

    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        if not args.sexyduck_file:  # Only show notification in GUI mode
            NOTIFICATION.messenger("Application error occurred")
        raise

if __name__ == "__main__":
    sys.exit(main())