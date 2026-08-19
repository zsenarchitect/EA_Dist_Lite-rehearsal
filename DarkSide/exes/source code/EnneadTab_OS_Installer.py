try:
    import os
    import traceback
    import shutil
    import time
    import sys
    import _Exe_Util
    from datetime import datetime, timedelta
    import logging
    import json

    # Set up logger
    logger = logging.getLogger('EnneadTab_OS_Installer')
    logger.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler
    log_file = os.path.join(_Exe_Util.DUMP_FOLDER, 'enneadtab_installer.log')
    file_handler = logging.FileHandler(log_file)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    import threading
    import requests
    import zipfile
    import tkinter as tk
    import tkinter.ttk as ttk
    from tkinter import scrolledtext

    IMPORT_FINE = True
except ImportError as e:
    print(f"Failed to import module: {e}")
    IMPORT_FINE = False
    

class RepositoryUpdater:
    def __init__(self, repo_config):
        self.repo_config = repo_config
        self.repo_url = repo_config['url']
        self.api_url = repo_config['api_url']
        self.repo_name = repo_config['name']
        
        self.session = requests.Session()  # Reuse connection
        self.session.headers.update({
            'User-Agent': 'EnneadTab-OS-Installer/1.0'
        })
        
        # Set up basic properties
        self.final_folder_name = "EA_Dist"  # Always use EA_Dist as target folder regardless of source
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.zip_path = os.path.join(_Exe_Util.WINDOW_TEMP_FOLDER, f"repo_{self.timestamp}.zip")
        self.temp_dir = os.path.join(_Exe_Util.WINDOW_TEMP_FOLDER, f"temp_extract_{self.timestamp}")
        
        # Use single ecosystem folder
        self.extract_to_eco_sys_folder = _Exe_Util.ECO_SYS_FOLDER
        self.final_dir = os.path.join(self.extract_to_eco_sys_folder, self.final_folder_name)
        # Only check final directory existence since dist_folder will always exist
        self.use_gui = not os.path.exists(self.final_dir)

        os.makedirs(self.extract_to_eco_sys_folder, exist_ok=True)
        os.makedirs(self.dump_folder, exist_ok=True)

        self.max_retries = 3
        self.retry_delay = 5  # seconds
        

        if self.use_gui:
            self.setup_gui()

    @property
    def dist_folder(self):
        folder = os.path.join(self.extract_to_eco_sys_folder, "EA_Dist")
        os.makedirs(folder, exist_ok=True)
        return folder

    @property
    def dump_folder(self):
        folder = os.path.join(self.extract_to_eco_sys_folder, "Dump")
        os.makedirs(folder, exist_ok=True)
        return folder
    


    def setup_gui(self):
        self.root = tk.Tk()
        self.root.title("EnneadTab OS Installer")

        # Set the window background color
        self.root.configure(bg="#2E2E2E")  # RGB (46, 46, 46)

        # Create the ScrolledText widget
        self.text_area = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, width=100, height=25, font=("Courier", 10))
        self.text_area.pack(padx=10, pady=10)

        # Configure the text area background and text color
        self.text_area.configure(bg="#2E2E2E", fg="white", insertbackground="white")  # Background and text color
        self.text_area.pack(padx=10, pady=10)

        # Create and pack the progress bar
        self.progress = ttk.Progressbar(self.root, orient="horizontal", length=100, mode="determinate")
        self.progress.pack(pady=10)

        self.redirect_print_to_widget(self.text_area)

    def redirect_print_to_widget(self, text_widget):
        class PrintRedirector:
            def __init__(self, widget):
                self.widget = widget

            def write(self, message):
                self.widget.insert(tk.END, message)
                self.widget.see(tk.END)

            def flush(self):
                pass

        sys.stdout = PrintRedirector(text_widget)

    def run_update(self):
        if self.use_gui:
            # Start the update in a new thread to avoid blocking the GUI
            update_thread = threading.Thread(target=self.start_update)
            update_thread.start()
            self.root.mainloop()
        else:
            self.start_update()

    def start_update(self):
        try:
            # Fetch the latest commit before downloading the zip
            self.commit_sha, self.commit_message = self.get_latest_commit()

            print(f"Latest commit: {self.commit_sha} - {self.commit_message}\n")

            # If using full version, update the usage tracking
            if self.repo_name == 'EA_Dist':
                # Create repository selector to update usage
                repo_selector = RepositorySelector(_Exe_Util.DUMP_FOLDER)
                repo_selector.update_full_version_usage()
                print("Updated full version usage tracking\n")

            self.cleanup_old_files()  # Use combined cleanup method
            self.download_zip()
            self.extract_zip()
            self.update_files()
            self.cleanup_current_cache()
            self.cleanup_empty_EA_dist_folder()
            self.create_duck_file(success=True)
            print("\n\nUpdate completed. You can now close this window!")
        except Exception as e:
            self.create_duck_file(success=False, error_details=traceback.format_exc())
            print(f"Update failed with error: {e}")

        if self.use_gui:
            self.root.after(10000, self.root.destroy)  # Close the GUI after 10 seconds

    def download_zip(self):
        for attempt in range(self.max_retries):
            try:
                print(f"Download attempt {attempt + 1} of {self.max_retries}...")
                
                # Add timeout and verify=True for security
                response = requests.get(self.repo_url, stream=True, timeout=30, verify=True)
                
                if response.status_code != 200:
                    raise Exception(f"HTTP {response.status_code}")
                
                # Verify content type
                content_type = response.headers.get('content-type', '')
                if 'zip' not in content_type.lower() and 'octet-stream' not in content_type.lower():
                    raise Exception(f"Invalid content type: {content_type}")

                total_size = int(response.headers.get('content-length', 0))
                
                if self.use_gui:
                    self.progress["maximum"] = total_size 

                with open(self.zip_path, "wb") as f:
                    downloaded_size = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if self.use_gui:
                                if total_size > 0:
                                    self.progress["value"] = downloaded_size
                                self.root.update_idletasks()  # Update the GUI
                                
                if total_size == 0 and self.use_gui:
                    self.progress.stop()  # Stop the indeterminate progress bar
                print("Zip file downloaded successfully.")

                # Verify zip file integrity
                if not zipfile.is_zipfile(self.zip_path):
                    raise Exception("Downloaded file is not a valid ZIP")
                    
                return  # Success!
                
            except Exception as e:
                print(f"Download attempt {attempt + 1} failed: {e}")
                if os.path.exists(self.zip_path):
                    os.remove(self.zip_path)
                if attempt < self.max_retries - 1:
                    print(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                else:
                    raise Exception(f"Failed to download after {self.max_retries} attempts")

    def extract_zip(self):
        """Extract downloaded zip file to temporary directory.
        Ensures clean extraction by removing existing temp directory if present.
        Handles long paths and continues even if some files fail to extract."""
        print("Unzipping downloaded file...")
        # Clean up existing temp directory if it exists
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                print(f"Warning: Could not remove existing temp directory: {e}")
                # If we can't remove it, create a new unique temp directory
                self.temp_dir = os.path.join(_Exe_Util.WINDOW_TEMP_FOLDER, f"temp_extract_{self.timestamp}_new")
        
        os.makedirs(self.temp_dir, exist_ok=True)
        
        self.extraction_errors = []  # Store as instance variable to access in create_duck_file
        with zipfile.ZipFile(self.zip_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                try:
                    # Skip files with paths too long for Windows
                    target_path = os.path.join(self.temp_dir, file_info.filename)
                    if len(target_path) >= 260:  # Windows MAX_PATH limit
                        error_msg = f"Path too long ({len(target_path)} chars): {file_info.filename}"
                        print(f"Warning: Skipping file with {error_msg}")
                        self.extraction_errors.append(error_msg)
                        continue
                    
                    # Try to extract the file
                    try:
                        zip_ref.extract(file_info, self.temp_dir)
                    except Exception as e:
                        error_msg = f"Failed to extract: {file_info.filename} - {str(e)}"
                        print(f"Warning: {error_msg}")
                        self.extraction_errors.append(error_msg)
                except Exception as e:
                    error_msg = f"Processing error: {getattr(file_info, 'filename', 'unknown file')} - {str(e)}"
                    print(f"Warning: {error_msg}")
                    self.extraction_errors.append(error_msg)

        if self.extraction_errors:
            print("\nThe following files had extraction issues:")
            for error in self.extraction_errors:
                print(f"- {error}")
            print("\nContinuing with successfully extracted files...")

        # Find the root directory after extraction
        extracted_contents = os.listdir(self.temp_dir)
        if extracted_contents:
            self.source_dir = os.path.join(self.temp_dir, extracted_contents[0])
            print("Zip file extracted.")
        else:
            raise Exception("No files were successfully extracted from the zip file.")

    def update_files(self):
        """Update files in target directory with optimized file operations."""
        print("Updating/Creating EnneadTab Content...")
        if not os.path.exists(self.final_dir):
            os.makedirs(self.final_dir)
        
        # Get all source files once
        source_files = {}
        for dp, dn, filenames in os.walk(self.source_dir):
            for f in filenames:
                src_path = os.path.join(dp, f)
                rel_path = os.path.relpath(src_path, self.source_dir)
                source_files[src_path] = rel_path
        
        # Process all files in a single pass
        for src_path, rel_path in source_files.items():
            tgt_path = os.path.join(self.final_dir, rel_path)
            tgt_dir = os.path.dirname(tgt_path)
            
            # Create directory if needed
            if not os.path.exists(tgt_dir):
                os.makedirs(tgt_dir)
            
            # Copy file
            try:
                shutil.copyfile(src_path, tgt_path)
            except Exception as e:
                logger.warning(f"Failed to copy {rel_path}: {str(e)}")
        
        # Only clean up old files when using the FULL version
        # Lite version is partial and should not delete existing files
        if self.repo_name == 'EA_Dist':  # Full version only
            print("Running full version cleanup of old files...")
            now = time.time()
            file_age_threshold = now - 3 * 24 * 60 * 60  # 3 days old
            
            # Clean up old files and empty directories
            for dp, dn, filenames in os.walk(self.final_dir, topdown=False):
                # Skip _engine folder
                if "_engine" in dp:
                    continue
                    
                # Remove old files
                for f in filenames:
                    file_path = os.path.join(dp, f)
                    if os.stat(file_path).st_mtime < file_age_threshold:
                        try:
                            os.remove(file_path)
                            print(f"Removed old file: {os.path.relpath(file_path, self.final_dir)}")
                        except Exception as e:
                            logger.warning(f"Failed to remove old file {file_path}: {str(e)}")
                
                # Try to remove empty directory
                try:
                    if not os.listdir(dp):
                        os.rmdir(dp)
                        print(f"Removed empty directory: {os.path.relpath(dp, self.final_dir)}")
                except OSError:
                    pass
        else:
            print("Using lite version - skipping old file cleanup to preserve existing content.")
                
        print("Files have been updated.")

    def cleanup_current_cache(self):
        print("Self cleaning cache contents...")
        try:
            shutil.rmtree(self.temp_dir)
        except PermissionError as e:
            print(f"Warning: Could not remove temp directory (files may be in use): {e}")
        except Exception as e:
            print(f"Warning: Error removing temp directory: {e}")
        
        try:
            os.remove(self.zip_path)
        except PermissionError as e:
            print(f"Warning: Could not remove zip file (file may be in use): {e}")
        except Exception as e:
            print(f"Warning: Error removing zip file: {e}")
        
        print("Cleanup current cache download completed.")

    def cleanup_empty_EA_dist_folder(self):
        """Walk through all the folders, remove if it is an empty folder"""
        for folder, _, filenames in os.walk(self.dist_folder):
            if not filenames:
                try:
                    os.removedirs(folder)
                except:
                    pass
        print("Cleanup empty EA folder completed.")

    def create_duck_file(self, success=True, error_details=None):
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        duck_file_path = os.path.join(self.extract_to_eco_sys_folder, f"{timestamp}.duck")
        
        # If there are extraction errors or other errors, mark as error duck file
        has_extraction_errors = hasattr(self, 'extraction_errors') and len(self.extraction_errors) > 0
        if not success or has_extraction_errors:
            duck_file_path = os.path.join(self.extract_to_eco_sys_folder, f"{timestamp}_ERROR.duck")

        with open(duck_file_path, 'w') as f:
            if success and not has_extraction_errors:
                f.write("Update succeeded.\n")
            else:
                f.write("Failed update.\n")
                if error_details:
                    f.write("Traceback details:\n{}\n".format(error_details))
                
                # Add extraction errors to the duck file if any exist
                if has_extraction_errors:
                    f.write("\nExtraction errors occurred:\n")
                    for error in self.extraction_errors:
                        f.write(f"- {error}\n")
                
            if self.commit_sha and self.commit_message:
                f.write(f"\nLatest commit: {self.commit_sha} - {self.commit_message}\n")
        
        print(f"Duck file created: {duck_file_path}")

    def cleanup_old_files(self):
        """Combined cleanup method for old files, cache, and duck files.
        Cleans up files from both ECO_SYS_FOLDER and WINDOW_TEMP_FOLDER."""
        print("Cleaning up old files...")
        now = datetime.now()
        cutoff_duck = now - timedelta(hours=8)
        cutoff_cache = now - timedelta(days=1)
        
        # Clean up files from ECO_SYS_FOLDER (duck files and any misplaced cache files)
        self._cleanup_directory(self.extract_to_eco_sys_folder, cutoff_duck, cutoff_cache, include_duck_files=True)
        
        # Clean up files from WINDOW_TEMP_FOLDER (zip files and temp directories)
        self._cleanup_directory(_Exe_Util.WINDOW_TEMP_FOLDER, cutoff_duck, cutoff_cache, include_duck_files=False)
    
    def _cleanup_directory(self, directory, cutoff_duck, cutoff_cache, include_duck_files=False):
        """Helper method to clean up files in a specific directory."""
        try:
            if not os.path.exists(directory):
                return
                
            for file in os.listdir(directory):
                try:
                    file_path = os.path.join(directory, file)
                    file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    
                    # Clean up old duck files (only in ECO_SYS_FOLDER)
                    if include_duck_files and file.endswith(".duck") and file_time < cutoff_duck:
                        os.remove(file_path)
                        print("Old duck file removed: {}".format(file_path))
                        continue
                    
                    # Clean up old zip files
                    if file.startswith("repo_") and file.endswith(".zip") and file_time < cutoff_cache:
                        try:
                            os.remove(file_path)
                            print(f"Old zip file removed: {file_path}")
                        except PermissionError:
                            print(f"Warning: Could not remove {file_path} - Permission denied")
                        continue
                    
                    # Clean up old temp folders
                    if os.path.isdir(file_path) and file.startswith("temp_extract_") and file_time < cutoff_cache:
                        try:
                            shutil.rmtree(file_path)
                            print(f"Old temp folder removed: {file_path}")
                        except PermissionError:
                            print(f"Warning: Could not remove {file_path} - Permission denied")
                            
                except Exception as e:
                    print(f"Warning: Error cleaning up {file}: {str(e)}")
                    
        except Exception as e:
            print(f"Warning: Error accessing directory {directory}: {str(e)}")

    def get_latest_commit(self):
        # Get the repository info to determine the default branch (main or master)
        try:
            repo_info_response = requests.get(self.api_url)
            if repo_info_response.status_code == 200:
                repo_data = repo_info_response.json()
                default_branch = repo_data.get('default_branch', 'master')
                
                # Now use the default branch in the commits API URL
                commits_url = f"{self.api_url}/commits/{default_branch}"
                response = requests.get(commits_url)
                
                if response.status_code == 200:
                    data = response.json()
                    return data['sha'][:7], data['commit']['message']  # Return short SHA and commit message
                else:
                    print(f"Failed to fetch latest commit: {response.status_code}")
                    return None, None
            else:
                print(f"Failed to fetch repository info: {repo_info_response.status_code}")
                return None, None
        except Exception as e:
            print(f"Error fetching commit: {e}")
            return None, None

    def __del__(self):
        """Cleanup resources when object is destroyed."""
        try:
            self.session.close()
        except:
            pass


class RepositorySelector:
    """Handles smart selection between EA_Dist and EA_Dist_Lite repositories."""
    
    def __init__(self, dump_folder):
        self.dump_folder = dump_folder
        self.lock_file_path = os.path.join(dump_folder, "full_repo_usage.lock")
        
        # Repository configurations
        #
        # !! BOTH DIST REPOS MUST STAY PUBLIC. !!
        # The installer downloads these with NO authentication (a plain archive
        # zip fetch). The moment either repo is made private, every user's
        # install 404s. EA_Dist_Lite now lives in EnneadTab-EcoSystem, where
        # EVERY OTHER REPO IS PRIVATE -- so it is the odd one out and a future
        # "make the org consistent" cleanup would silently break the fleet.
        # If you ever need these private, the download path must move to an
        # authenticated fetch FIRST.
        #
        # EA_Dist_Lite was transferred zsenarchitect -> EnneadTab-EcoSystem on
        # 2026-07-13. GitHub redirects the old URL, so a stale installer exe
        # still works -- but that redirect dies the instant anyone creates a new
        # repo at github.com/zsenarchitect/EA_Dist_Lite. Do not rely on it.
        self.repositories = {
            'lite': {
                'url': 'https://github.com/EnneadTab-EcoSystem/EA_Dist_Lite/archive/refs/heads/main.zip',
                'api_url': 'https://api.github.com/repos/EnneadTab-EcoSystem/EA_Dist_Lite',
                'name': 'EA_Dist_Lite',
                'description': 'Lite version (faster download, no heavy files)'
            },
            'full': {
                'url': 'https://github.com/Ennead-Architects-LLP/EA_Dist/archive/refs/heads/main.zip',
                'api_url': 'https://api.github.com/repos/Ennead-Architects-LLP/EA_Dist',
                'name': 'EA_Dist',
                'description': 'Full version (complete package, used max once per day)'
            }
        }
        
        # Configuration for dynamic frequency
        self.config = {
            'base_frequency': 13,  # Base frequency for full version
            'success_rate_threshold': 0.8,  # Success rate threshold for frequency adjustment
        }
    
    def can_use_full_version(self):
        """Check if the full version can be used (hasn't been used in the last 24 hours)."""
        if not os.path.exists(self.lock_file_path):
            return True
            
        try:
            with open(self.lock_file_path, 'r') as f:
                lock_data = json.load(f)
            
            last_used_str = lock_data.get('last_full_usage')
            if not last_used_str:
                return True
                
            last_used = datetime.fromisoformat(last_used_str)
            time_since_last_use = datetime.now() - last_used
            
            # Can use full version if more than 24 hours have passed
            return time_since_last_use > timedelta(hours=24)
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Error reading lock file: {e}. Allowing full version usage.")
            return True
    
    def _check_significant_changes(self):
        """Check if there are significant changes that warrant full version."""
        try:
            # Get latest commit info from both repositories
            lite_response = requests.get(f"{self.repositories['lite']['api_url']}/commits/main", timeout=5)
            full_response = requests.get(f"{self.repositories['full']['api_url']}/commits/main", timeout=5)
            
            if lite_response.status_code == 200 and full_response.status_code == 200:
                lite_commit = lite_response.json()
                full_commit = full_response.json()
                
                # Check if commits are different (significant changes)
                if lite_commit['sha'] != full_commit['sha']:
                    return True
                    
                # Check commit message for keywords indicating major changes
                commit_message = full_commit['commit']['message'].lower()
                major_keywords = ['major', 'breaking', 'update', 'release', 'version']
                if any(keyword in commit_message for keyword in major_keywords):
                    return True
                    
        except:
            pass
        
        return False
    
    def _calculate_adaptive_frequency(self, lock_data):
        """Calculate adaptive frequency for full version usage."""
        base_frequency = self.config['base_frequency']
        
        # Adjust based on success rate
        success_rate = lock_data.get('success_rate', 1.0)
        if success_rate > 0.9:
            base_frequency = max(base_frequency - 3, 7)  # More frequent if successful
        elif success_rate < 0.7:
            base_frequency = min(base_frequency + 5, 20)  # Less frequent if problematic
        
        # Adjust based on usage patterns
        usage_count = lock_data.get('total_usage_count', 0)
        if usage_count > 50:
            base_frequency = max(base_frequency - 2, 5)  # More frequent for active users
        
        return base_frequency
    
    def update_full_version_usage(self):
        """Update the lock file to record full version usage with success tracking."""
        current_data = self.get_lock_data()
        
        # Update usage counters
        current_data.update({
            'last_full_usage': datetime.now().isoformat(),
            'full_usage_count': current_data.get('full_usage_count', 0) + 1
        })
        
        # Track success rate (assuming success if this method is called)
        total_attempts = current_data.get('total_full_attempts', 0) + 1
        successful_attempts = current_data.get('successful_full_attempts', 0) + 1
        success_rate = successful_attempts / total_attempts
        
        current_data.update({
            'total_full_attempts': total_attempts,
            'successful_full_attempts': successful_attempts,
            'success_rate': success_rate
        })
        
        try:
            with open(self.lock_file_path, 'w') as f:
                json.dump(current_data, f, indent=2)
            logger.info("Updated full version usage timestamp and success tracking")
        except Exception as e:
            logger.error(f"Failed to update lock file: {e}")
    
    def record_failed_attempt(self, repo_type='full'):
        """Record a failed attempt to improve future selection decisions."""
        current_data = self.get_lock_data()
        
        if repo_type == 'full':
            total_attempts = current_data.get('total_full_attempts', 0) + 1
            successful_attempts = current_data.get('successful_full_attempts', 0)  # Don't increment
            success_rate = successful_attempts / total_attempts if total_attempts > 0 else 0
            
            current_data.update({
                'total_full_attempts': total_attempts,
                'success_rate': success_rate,
                'last_failed_attempt': datetime.now().isoformat()
            })
        else:
            # Track lite version failures too
            lite_failures = current_data.get('lite_failures', 0) + 1
            current_data.update({
                'lite_failures': lite_failures,
                'last_lite_failure': datetime.now().isoformat()
            })
        
        try:
            with open(self.lock_file_path, 'w') as f:
                json.dump(current_data, f, indent=2)
            logger.info(f"Recorded failed {repo_type} version attempt")
        except Exception as e:
            logger.error(f"Failed to update lock file: {e}")
    
    def should_fallback_to_lite(self):
        """Determine if we should fallback to lite version after full failure."""
        lock_data = self.get_lock_data()
        
        # Check recent full failures
        full_failures = lock_data.get('full_failures', 0)
        last_full_failure = lock_data.get('last_failed_attempt')
        
        if full_failures >= 2:  # Multiple recent failures
            if last_full_failure:
                try:
                    last_failure_time = datetime.fromisoformat(last_full_failure)
                    if datetime.now() - last_failure_time < timedelta(hours=2):
                        # Recent failures, consider fallback to lite
                        return True
                except:
                    pass
        
        return False
    
    def update_general_usage(self):
        """Update the general usage counter for all installations."""
        current_data = self.get_lock_data()
        current_data.update({
            'last_usage': datetime.now().isoformat(),
            'total_usage_count': current_data.get('total_usage_count', 0) + 1
        })
        
        try:
            with open(self.lock_file_path, 'w') as f:
                json.dump(current_data, f, indent=2)
            logger.info("Updated general usage counter")
        except Exception as e:
            logger.error(f"Failed to update lock file: {e}")
    
    def get_lock_data(self):
        """Get the current lock file data."""
        if not os.path.exists(self.lock_file_path):
            return {}
            
        try:
            with open(self.lock_file_path, 'r') as f:
                return json.load(f)
        except:
            return {}
    
    def get_usage_count(self):
        """Get the current total usage count."""
        return self.get_lock_data().get('total_usage_count', 0)
    
    def select_repository(self, force_full=False):
        """Select which repository to use based on usage rules with enhanced intelligence."""
        if force_full:
            if self.can_use_full_version():
                print("Using full version (forced)")
                self.update_full_version_usage()
                return self.repositories['full']
            else:
                print("Full version requested but was used recently. Using lite version instead.")
                return self.repositories['lite']
        
        # Check if this is first-time installation (EA_Dist folder doesn't exist)
        eco_sys_folder = _Exe_Util.ECO_SYS_FOLDER
        final_dir = os.path.join(eco_sys_folder, "EA_Dist")
        is_first_time_installation = not os.path.exists(final_dir)
        
        if is_first_time_installation:
            print("First-time installation detected - using lite version for fastest download")
            return self.repositories['lite']
        
        # Enhanced selection logic with content-based intelligence and adaptive frequency
        lock_data = self.get_lock_data()
        usage_count = self.get_usage_count()
        
        # Factor 1: Content-based intelligence - check for significant changes
        if self._check_significant_changes():
            if self.can_use_full_version():
                print("Significant changes detected - using full version for comprehensive update")
                self.update_full_version_usage()
                return self.repositories['full']
            else:
                print("Significant changes detected but full version locked - using lite version")
                return self.repositories['lite']
        
        # Factor 2: Dynamic frequency adjustment based on usage patterns
        if self.can_use_full_version():
            adaptive_frequency = self._calculate_adaptive_frequency(lock_data)
            should_use_full = usage_count > 0 and usage_count % adaptive_frequency == 0
            
            if should_use_full:
                print(f"Using full version (adaptive frequency: every {adaptive_frequency}th time)")
                self.update_full_version_usage()
                return self.repositories['full']
            else:
                print("Using lite version (default choice for faster download)")
                return self.repositories['lite']
        else:
            print("Using lite version (full version used recently)")
            return self.repositories['lite']
    
    def get_time_until_full_available(self):
        """Get time remaining until full version can be used again."""
        if self.can_use_full_version():
            return timedelta(0)
            
        try:
            with open(self.lock_file_path, 'r') as f:
                lock_data = json.load(f)
            
            last_used_str = lock_data.get('last_full_usage')
            if not last_used_str:
                return timedelta(0)
                
            last_used = datetime.fromisoformat(last_used_str)
            time_passed = datetime.now() - last_used
            time_remaining = timedelta(hours=24) - time_passed
            
            return max(time_remaining, timedelta(0))
            
        except:
            return timedelta(0)


@_Exe_Util.try_catch_error
def main():
    try:
        # Add system checks
        if not os.path.exists(_Exe_Util.DUMP_FOLDER):
            os.makedirs(_Exe_Util.DUMP_FOLDER)
            
        # Check write permissions
        test_file = os.path.join(_Exe_Util.DUMP_FOLDER, "test.txt")
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
        except Exception as e:
            raise PermissionError(f"No write permission in dump folder: {e}")

        # Smart repository selection
        repo_selector = RepositorySelector(_Exe_Util.DUMP_FOLDER)
        
        # Select repository based on usage rules (no command line args for exe)
        selected_repo = repo_selector.select_repository(force_full=False)
        
        # Update general usage counter after selection
        repo_selector.update_general_usage()
        
        print(f"Selected repository: {selected_repo['name']}")
        print(f"Description: {selected_repo['description']}")
        
        if not repo_selector.can_use_full_version():
            time_remaining = repo_selector.get_time_until_full_available()
            hours = int(time_remaining.total_seconds() // 3600)
            minutes = int((time_remaining.total_seconds() % 3600) // 60)
            print(f"Full version available in: {hours}h {minutes}m")
        
        print()  # Add blank line for readability

        # Create single updater instance for download and extraction
        updater = RepositoryUpdater(selected_repo)
        
        # Run the update process with error recovery
        try:
            updater.run_update()
        except Exception as e:
            # Record the failure
            repo_selector.record_failed_attempt(selected_repo['name'].lower().split('_')[-1])
            
            # Check if we should fallback to lite version (if full version failed)
            if selected_repo['name'] == 'EA_Dist' and repo_selector.should_fallback_to_lite():
                print("\nFull version failed. Attempting fallback to lite version...")
                try:
                    fallback_repo = repo_selector.repositories['lite']
                    fallback_updater = RepositoryUpdater(fallback_repo)
                    fallback_updater.run_update()
                    print("Fallback to lite version completed successfully.")
                except Exception as fallback_error:
                    logger.error(f"Fallback to lite version also failed: {fallback_error}")
                    raise e  # Re-raise original error
            else:
                raise e  # Re-raise original error
        
    except PermissionError as e:
        logger.error(f"Error: Permission denied. Please run as administrator or check file permissions.\nDetails: {str(e)}")
    except Exception as e:
        logger.error(f"Critical Error: {str(e)}")
        logger.error("Please contact IT support if this persists")
        time.sleep(10)  # Give user time to read error

if __name__ == '__main__':
    if IMPORT_FINE:
        main()
    else:
        print("Failed to import modules")
        time.sleep(10)
