"""
Autodesk Platform Services (APS) API Client for RevitSlave4
Learns from REVIT_ACC.py but with zero EnneadTab dependencies

Handles:
- Authentication with token reuse
- Fetching hubs, projects, files
- Extracting GUIDs from API responses
"""

import time
import sys

try:
    import requests
except ImportError:
    print("ERROR: requests library required")
    print("Install: pip install requests")
    sys.exit(1)


# ANSI Color Codes for better console output
class Colors:
    """ANSI color codes for terminal output"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    # Foreground colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright colors
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'


def cprint(tag, message="", color=Colors.RESET):
    """Color print with tag"""
    if message:
        print(f"{color}{tag}{Colors.RESET} {message}")
    else:
        print(f"{color}{tag}{Colors.RESET}")


class APSClient:
    """
    Client for Autodesk Platform Services API
    Implements token reuse strategy from REVIT_ACC (saves ~80% of API costs)
    """
    
    # Class-level token cache (shared across all instances)
    _token_cache = {
        "access_token": None,
        "expires_at": 0
    }
    
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_call_count = 0
    
    def get_access_token(self):
        """
        Get access token with reuse strategy (same as REVIT_ACC.get_reusable_access_token)
        
        Tokens are valid for 1 hour - reuse saves ~99% of token API calls!
        
        Returns:
            str: Access token or None if failed
        """
        from config.settings import APISettings
        
        current_time = time.time()
        buffer_seconds = APISettings.TOKEN_BUFFER_SECONDS
        
        # Try to reuse cached token
        if (self._token_cache["access_token"] and 
            current_time < self._token_cache["expires_at"] - buffer_seconds):
            
            remaining_min = (self._token_cache["expires_at"] - current_time) / 60
            cprint(f"[REUSE]", f"Token cached (expires in {remaining_min:.1f} min)", Colors.GREEN)
            return self._token_cache["access_token"]
        
        # Need new token
        cprint("[AUTH]", "Getting new access token from APS...", Colors.CYAN)
        
        token_url = "https://developer.api.autodesk.com/authentication/v2/token"
        token_data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": "data:read"
        }
        
        try:
            resp = requests.post(token_url, data=token_data, timeout=30)
            self.api_call_count += 1
            
            if resp.status_code != 200:
                print(f"[ERROR] Token request failed: {resp.status_code}")
                try:
                    error_data = resp.json()
                    print(f"[ERROR] API Response: {error_data}")
                except:
                    print(f"[ERROR] Response text: {resp.text}")
                print("[DEBUG] Credentials used:")
                print(f"  Client ID: {self.client_id[:10]}...")
                return None
            
            data = resp.json()
            access_token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)  # Default 1 hour
            
            # Cache the token (class-level, shared across instances)
            APSClient._token_cache = {
                "access_token": access_token,
                "expires_at": current_time + expires_in
            }
            
            cprint("[OK]", f"New token obtained (valid for {expires_in/60:.0f} min)", Colors.BRIGHT_GREEN)
            return access_token
            
        except Exception as e:
            print(f"[ERROR] Error getting token: {e}")
            return None
    
    def get_all_hubs(self):
        """
        Get all ACC hubs
        
        Returns:
            List of hub objects from API
        """
        token = self.get_access_token()
        if not token:
            return []
        
        url = "https://developer.api.autodesk.com/project/v1/hubs"
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            self.api_call_count += 1
            
            if resp.status_code == 200:
                return resp.json().get("data", [])
            else:
                print(f"[ERROR] Failed to get hubs: {resp.status_code}")
                return []
        except Exception as e:
            print(f"[ERROR] Error getting hubs: {e}")
            return []
    
    def get_hub_projects(self, hub_id):
        """
        Get all projects in a hub
        
        Args:
            hub_id: Hub ID
            
        Returns:
            List of project objects from API
        """
        token = self.get_access_token()
        if not token:
            return []
        
        url = f"https://developer.api.autodesk.com/project/v1/hubs/{hub_id}/projects"
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            self.api_call_count += 1
            
            if resp.status_code == 200:
                return resp.json().get("data", [])
            else:
                print(f"[ERROR] Failed to get projects for hub {hub_id}: {resp.status_code}")
                return []
        except Exception as e:
            print(f"[ERROR] Error getting projects: {e}")
            return []
    
    def get_project_revit_files(self, project_id, hub_id, project_name=""):
        """
        Get all Revit files for a project with GUIDs
        Same logic as REVIT_ACC.get_project_revit_files_data()
        
        Args:
            project_id: Project ID
            hub_id: Hub ID
            project_name: Project name (for logging)
            
        Returns:
            List of file detail objects from API (with GUIDs)
        """
        from config.settings import APISettings
        
        token = self.get_access_token()
        if not token:
            return []
        
        # Get root folder ID
        url = f"https://developer.api.autodesk.com/project/v1/hubs/{hub_id}/projects/{project_id}"
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            self.api_call_count += 1
            
            if resp.status_code != 200:
                return []
            
            root_folder_id = resp.json().get("data", {}).get("relationships", {}).get("rootFolder", {}).get("data", {}).get("id")
            if not root_folder_id:
                return []
        except Exception as e:
            print(f"  [ERROR] Error getting project data: {e}")
            return []
        
        revit_files = []
        file_count = [0]  # Use list for mutable closure
        file_folder_map = {}  # Map file_id to folder_path
        
        def search_folder(folder_id, depth=0, folder_path=""):
            """Recursively search folders for Revit files"""
            # Check max folder depth
            if depth > APISettings.MAX_FOLDER_DEPTH:
                print(f"      [WARNING] Max folder depth ({APISettings.MAX_FOLDER_DEPTH}) reached")
                return
            
            # Early exit if we've found enough files (only if limit is set)
            if APISettings.MAX_FILES_PER_PROJECT is not None and file_count[0] > APISettings.MAX_FILES_PER_PROJECT:
                print(f"      [INFO] Found {file_count[0]} files, stopping search to save API calls")
                return
            
            # Get folder contents
            url = f"https://developer.api.autodesk.com/data/v1/projects/{project_id}/folders/{folder_id}/contents"
            headers = {"Authorization": f"Bearer {token}"}
            
            # No delays - use early exit strategies like REVIT_ACC
            
            try:
                resp = requests.get(url, headers=headers, timeout=30)
                self.api_call_count += 1
                
                # Handle rate limiting with retry
                if resp.status_code == 429:
                    try:
                        retry_after = int(resp.headers.get('Retry-After', 5))
                    except (ValueError, TypeError):
                        retry_after = 5
                    print(f"      [RATE LIMIT] Waiting {retry_after}s before retry...")
                    time.sleep(retry_after)
                    resp = requests.get(url, headers=headers, timeout=30)
                    self.api_call_count += 1
                
                if resp.status_code != 200:
                    if resp.status_code != 429:  # Don't log 429 twice
                        print(f"      [WARNING] Folder API failed: {resp.status_code} at depth {depth}")
                    return
                
                items = resp.json().get("data", [])
                
                for item in items:
                    item_type = item.get("type")
                    
                    if item_type == "items":
                        # Check if Revit file
                        display_name = item.get("attributes", {}).get("displayName", "")
                        if display_name.lower().endswith(".rvt"):
                            file_count[0] += 1
                            item_id = item.get("id")
                            
                            # Store folder path for this file
                            file_folder_map[item_id] = folder_path
                            
                            # Get detailed file info (includes GUIDs)
                            detail_url = f"https://developer.api.autodesk.com/data/v1/projects/{project_id}/items/{item_id}"
                            try:
                                detail_resp = requests.get(detail_url, headers=headers, timeout=30)
                                self.api_call_count += 1
                                
                                # Handle rate limiting
                                if detail_resp.status_code == 429:
                                    try:
                                        retry_after = int(detail_resp.headers.get('Retry-After', 5))
                                    except (ValueError, TypeError):
                                        retry_after = 5
                                    print(f"      [RATE LIMIT] Waiting {retry_after}s before retry...")
                                    time.sleep(retry_after)
                                    detail_resp = requests.get(detail_url, headers=headers, timeout=30)
                                    self.api_call_count += 1
                                
                                if detail_resp.status_code == 200:
                                    file_data = detail_resp.json()
                                    # Add folder_path to file data
                                    file_data['folder_path'] = folder_path
                                    revit_files.append(file_data)
                                elif detail_resp.status_code != 429:
                                    print(f"      [WARNING] Failed to get file details: {display_name} (status: {detail_resp.status_code})")
                            except Exception as file_err:
                                print(f"      [WARNING] Error getting file {display_name}: {file_err}")
                    
                    elif item_type == "folders":
                        # Recurse into subfolder
                        folder_name = item.get("attributes", {}).get("name", "Unknown")
                        # Build folder path
                        new_folder_path = folder_path + "/" + folder_name if folder_path else folder_name
                        search_folder(item.get("id"), depth + 1, new_folder_path)
            
            except Exception as e:
                print(f"      [ERROR] Folder search failed at depth {depth}: {str(e)[:100]}")
                # Continue to next folder instead of stopping
        
        # Start recursive search
        search_folder(root_folder_id)
        
        return revit_files
    
    def _should_skip_project(self, project_name):
        """
        Smart filtering to skip projects unlikely to have processable files
        Reduces API calls by ~30-50%
        """
        skip_patterns = [
            'test', 'temp', '_temp', 'archived', 'archive', 'not active',
            'markup', 'meeting', 'sandbox', 'training', 'demo',
            'component library', 'twinmotion', 'upgrade'
        ]
        name_lower = project_name.lower()
        return any(pattern in name_lower for pattern in skip_patterns)
    
    def get_all_data(self, show_progress=True, use_version_fallback=True, guid_service=None):
        """
        Get complete data for all hubs/projects/files
        This is the main entry point that retrieves everything in one session
        
        Args:
            show_progress: Whether to print progress information
            use_version_fallback: Use local ACC file fallback if API doesn't provide version
            guid_service: Optional GUIDDiscoveryService to update cache immediately after fallback
            
        Returns:
            Dict with structured hub/project/file data, or None if failed
        """
        if show_progress:
            print("\n" + "="*80)
            print("Fetching ALL project/file data from Autodesk APS API")
            print("="*80)
        
        # Authenticate
        if not self.get_access_token():
            print("[ERROR] Authentication failed")
            return None
        
        # Get hubs
        if show_progress:
            print("\n[API] Step 1: Fetching all hubs...")
        
        hubs = self.get_all_hubs()
        if not hubs:
            print("[ERROR] No hubs found")
            return None
        
        if show_progress:
            print(f"[OK] Found {len(hubs)} hubs")
        
        result = {}
        
        # Process each hub
        for hub in hubs:
            hub_id = hub.get("id")
            hub_name = hub.get("attributes", {}).get("name", "Unknown")
            
        if show_progress:
            cprint(f"\n[HUB]", f"Hub: {hub_name}", Colors.BRIGHT_CYAN)
            print(f"   Getting projects...")
            
            hub_start = time.time()
            projects = self.get_hub_projects(hub_id)
            hub_elapsed = time.time() - hub_start
            
            if show_progress:
                cprint(f"   [OK]", f"Found {len(projects)} projects ({hub_elapsed:.1f}s)", Colors.BRIGHT_GREEN)
            
            hub_data = {
                "hub_id": hub_id,
                "projects": {}
            }
            
            # Process each project
            hub_process_start = time.time()
            for i, project in enumerate(projects, 1):
                # Batch cooldown: Every 10 projects, take a 5-second break to avoid rate limiting
                if i > 1 and (i - 1) % 10 == 0:
                    elapsed_so_far = time.time() - hub_process_start
                    if show_progress:
                        cprint(f"   [COOLDOWN]", f"Processed {i-1} projects in {elapsed_so_far:.0f}s, waiting 5s to avoid rate limits...", Colors.YELLOW)
                    time.sleep(5)
                
                project_id = project.get("id")
                project_name = project.get("attributes", {}).get("name", "Unknown")
                project_type = project.get("attributes", {}).get("extension", {}).get("data", {}).get("projectType", "Unknown")
                
                project_start = time.time()
                if show_progress:
                    print(f"   [{i}/{len(projects)}] {project_name}")
                
                # Smart filtering: Skip projects unlikely to have processable files
                if self._should_skip_project(project_name):
                    if show_progress:
                        print(f"       [SKIP] Filtered (test/archive/temp project)")
                    hub_data["projects"][project_name] = {
                        "project_id": project_id,
                        "files": {},
                        "total_files": 0,
                        "processable_files": 0
                    }
                    continue
                
                # Get Revit files
                files_data = self.get_project_revit_files(project_id, hub_id, project_name)
                
                # Process files and extract GUIDs
                processed_files = {}
                complete_count = 0
                fallback_count = 0
                
                for file_data in files_data:
                    if "included" not in file_data or len(file_data.get("included", [])) == 0:
                        continue
                    
                    file_attrs = file_data.get("included", [{}])[0].get("attributes", {})
                    in_depth = file_attrs.get("extension", {}).get("data", {})
                    
                    file_name = file_attrs.get("displayName", "")
                    model_guid = in_depth.get("modelGuid", "N/A")
                    project_guid = in_depth.get("projectGuid", "N/A")
                    version = in_depth.get("revitProjectVersion", "N/A")
                    folder_path = file_data.get("folder_path", "")  # Get folder_path from file_data
                    
                    # Version fallback: If API doesn't provide version but has GUIDs, try local file
                    if (use_version_fallback and 
                        (version == "N/A" or not isinstance(version, (int, float))) and
                        model_guid and model_guid != "N/A" and
                        project_guid and project_guid != "N/A"):
                        
                        try:
                            from .version_fallback import VersionFallbackDetector
                            
                            if show_progress:
                                cprint(f"       [FALLBACK]", f"{file_name}: API missing version, trying local...", Colors.MAGENTA)
                            
                            detector = VersionFallbackDetector()
                            fallback_version = detector.detect_version_from_local_file(
                                hub_name, project_name, file_name, timeout_minutes=3
                            )
                            
                            if fallback_version:
                                version = int(fallback_version)
                                fallback_count += 1
                                if show_progress:
                                    cprint(f"       [SUCCESS]", f"Fallback detected: Revit {version}", Colors.BRIGHT_GREEN)
                                
                                # Update cache immediately so next run can use cached version
                                if guid_service:
                                    guid_service.update_file_version(hub_name, project_name, file_name, version)
                            else:
                                if show_progress:
                                    cprint(f"       [SKIP]", "Fallback failed - version remains unknown", Colors.YELLOW)
                        
                        except Exception as e:
                            if show_progress:
                                print(f"       [ERROR] Fallback error: {type(e).__name__}")
                    
                    # Check if metadata is complete
                    has_complete = (
                        model_guid and model_guid != "N/A" and
                        project_guid and project_guid != "N/A" and
                        version and version != "N/A" and isinstance(version, (int, float))
                    )
                    
                    if has_complete:
                        complete_count += 1
                    
                    processed_files[file_name] = {
                        "file_id": file_data.get("data", {}).get("id", ""),
                        "model_guid": model_guid,
                        "project_guid": project_guid,
                        "version": int(version) if isinstance(version, (int, float)) else "N/A",
                        "file_size_bytes": file_attrs.get("storageSize", 0),
                        "last_modified": file_attrs.get("lastModifiedTime", ""),
                        "create_user": file_attrs.get("createUserName", ""),
                        "folder_path": folder_path,  # Include folder_path
                        "has_complete_metadata": has_complete,
                        "skip_reason": None if has_complete else "Missing version or GUIDs"
                    }
                
                hub_data["projects"][project_name] = {
                    "project_id": project_id,
                    "project_type": project_type,
                    "files": processed_files
                }
                
                if show_progress:
                    total_files = len(processed_files)
                    project_elapsed = time.time() - project_start
                    status_msg = f"{complete_count}/{total_files} files processable"
                    if fallback_count > 0:
                        status_msg += f" ({fallback_count} via fallback)"
                    status_msg += f" - {project_elapsed:.1f}s"
                    cprint(f"       [OK]", status_msg, Colors.BRIGHT_GREEN)
            
            result[hub_name] = hub_data
        
        if show_progress:
            total_elapsed = time.time() - hub_process_start
            minutes = int(total_elapsed // 60)
            seconds = int(total_elapsed % 60)
            print("\n" + "="*80)
            cprint(f"[OK]", f"API retrieval complete - {self.api_call_count} total API calls in {minutes}m {seconds}s", Colors.BRIGHT_GREEN)
            print("="*80)
        
        return result

