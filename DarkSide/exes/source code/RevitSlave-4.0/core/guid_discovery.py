"""
GUID Discovery and Caching Service for RevitSlave4
Manages 7-day cache of GUID data from APS API
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from models.file_models import RevitFileMetadata


class GUIDDiscoveryService:
    """
    Discovers and caches Revit file GUIDs via APS API
    
    Responsibilities:
    - Manage 7-day cache lifecycle
    - Coordinate API data retrieval
    - Filter files by metadata completeness
    - Provide fast lookup by hub/project/file
    """
    
    def __init__(self, cache_path: Optional[Path] = None):
        if cache_path is None:
            from config.settings import CacheSettings
            cache_dir = CacheSettings.get_cache_dir()
            cache_path = cache_dir / CacheSettings.FILE_NAME
        
        self.cache_path = Path(cache_path)
        self.cache_data = None
    
    def is_cache_valid(self) -> bool:
        """
        Check if cache exists and is < 7 days old
        
        Returns:
            True if cache is valid and fresh
        """
        if not self.cache_path.exists():
            return False
        
        try:
            with open(self.cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            expires_at_str = data.get("expires_at")
            if not expires_at_str:
                return False
            
            expires_at = datetime.fromisoformat(expires_at_str)
            is_valid = datetime.now() < expires_at
            
            if is_valid:
                age_days = (datetime.now() - datetime.fromisoformat(data.get("generated_at", ""))).days
                print(f"[OK] Cache is valid (age: {age_days} days, expires in {(expires_at - datetime.now()).days} days)")
            
            return is_valid
            
        except Exception as e:
            print(f"[WARNING] Error checking cache validity: {e}")
            return False
    
    def load_cache(self) -> bool:
        """
        Load cache from disk
        
        Returns:
            True if cache loaded successfully
        """
        if not self.cache_path.exists():
            print("[INFO] Cache file not found - will fetch from API")
            return False
        
        try:
            with open(self.cache_path, 'r', encoding='utf-8') as f:
                self.cache_data = json.load(f)
            
            stats = self.cache_data.get("stats", {})
            print(f"[OK] Cache loaded:")
            print(f"   Total files: {stats.get('total_files', 0)}")
            print(f"   Processable: {stats.get('processable_files', 0)}")
            print(f"   Skipped: {stats.get('skipped_files', 0)}")
            print(f"   (Folder filtering will be applied when getting processable files)")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Error loading cache: {e}")
            return False
    
    def save_cache(self, api_data: dict):
        """
        Save API data to cache with 7-day expiry
        
        Args:
            api_data: Structured data from APSClient.get_all_data()
        """
        from config.settings import CacheSettings
        
        now = datetime.now()
        expires = now + timedelta(days=CacheSettings.EXPIRY_DAYS)
        
        # Calculate statistics
        stats = self._calculate_stats(api_data)
        
        cache_payload = {
            "cache_version": "3.0",
            "generated_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "stats": stats,
            "data": api_data
        }
        
        # Ensure directory exists
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save to disk
        with open(self.cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_payload, f, indent=2, ensure_ascii=False)
        
        self.cache_data = cache_payload
        
        print(f"\n[OK] Cache saved to: {self.cache_path}")
        print(f"   Expires: {expires.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Total files: {stats['total_files']}")
        print(f"   Processable: {stats['processable_files']}")
        print(f"   Skipped (no version): {stats['skipped_files']}")
    
    def _calculate_stats(self, data: dict) -> dict:
        """Calculate statistics for reporting"""
        stats = {
            "total_hubs": 0,
            "total_projects": 0,
            "total_files": 0,
            "processable_files": 0,
            "skipped_files": 0
        }
        
        for hub_name, hub_data in data.items():
            stats["total_hubs"] += 1
            projects = hub_data.get("projects", {})
            stats["total_projects"] += len(projects)
            
            for project_name, project_data in projects.items():
                files = project_data.get("files", {})
                stats["total_files"] += len(files)
                
                for file_name, file_info in files.items():
                    if file_info.get("has_complete_metadata"):
                        stats["processable_files"] += 1
                    else:
                        stats["skipped_files"] += 1
        
        return stats
    
    def update_file_version(self, hub_name: str, project_name: str, file_name: str, version: int) -> bool:
        """
        Update a specific file's version in the cache after successful fallback detection.
        
        This allows future runs to skip the slow OLE detection and use the cached version.
        
        Args:
            hub_name: Hub name
            project_name: Project name
            file_name: File name
            version: Detected Revit version (e.g., 2024)
            
        Returns:
            True if updated successfully, False otherwise
        """
        if not self.cache_data:
            print("[WARN] Cannot update version - no cache loaded")
            return False
        
        try:
            api_data = self.cache_data.get("data", {})
            
            # Navigate to file entry
            if hub_name not in api_data:
                print(f"[WARN] Hub '{hub_name}' not found in cache")
                return False
            
            hub_data = api_data[hub_name]
            projects = hub_data.get("projects", {})
            
            if project_name not in projects:
                print(f"[WARN] Project '{project_name}' not found in cache")
                return False
            
            project_data = projects[project_name]
            files = project_data.get("files", {})
            
            if file_name not in files:
                print(f"[WARN] File '{file_name}' not found in cache")
                return False
            
            file_info = files[file_name]
            old_version = file_info.get("version", "N/A")
            
            # Update version and metadata status
            file_info["version"] = version
            
            # Recalculate has_complete_metadata
            has_complete_metadata = (
                file_info.get("model_guid") and file_info.get("model_guid") != "N/A" and
                file_info.get("project_guid") and file_info.get("project_guid") != "N/A" and
                file_info.get("version") and file_info.get("version") != "N/A"
            )
            file_info["has_complete_metadata"] = has_complete_metadata
            
            # Save updated cache to disk
            import time
            save_start = time.time()
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(self.cache_data, f, indent=2, ensure_ascii=False)
            save_elapsed = time.time() - save_start
            
            print(f"\033[92m[CACHE UPDATE]\033[0m {file_name}: version {old_version} → {version} (saved in {save_elapsed:.2f}s)")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to update cache: {e}")
            return False
    
    def get_processable_files(self) -> List[RevitFileMetadata]:
        """
        Get list of all files with complete metadata
        Filters out files in excluded folders (Archive, Study, Consumed, etc.)
        Filters by project name if ProjectFilterSettings is enabled
        
        Returns:
            List of RevitFileMetadata objects ready for processing
        """
        from config.settings import FolderFilterSettings, ProjectFilterSettings, FileIgnoreSettings
        
        if not self.cache_data:
            print("[ERROR] No cache data loaded")
            return []
        
        processable = []
        filtered_out = []
        filtered_projects = []
        ignored_files = []
        
        api_data = self.cache_data.get("data", {})
        
        for hub_name, hub_data in api_data.items():
            hub_id = hub_data.get("hub_id", "")
            
            for project_name, project_data in hub_data.get("projects", {}).items():
                project_id = project_data.get("project_id", "")
                
                # Check if project should be included
                if not ProjectFilterSettings.should_include_project(project_name):
                    # Skip entire project - not in filter
                    file_count = len(project_data.get("files", {}))
                    filtered_projects.append({
                        "project_name": project_name,
                        "file_count": file_count
                    })
                    continue
                
                for file_name, file_info in project_data.get("files", {}).items():
                    if file_info.get("has_complete_metadata"):
                        folder_path = file_info.get("folder_path", "")
                        
                        # Check if folder should be excluded
                        should_exclude, exclude_reason = FolderFilterSettings.should_exclude_folder(folder_path)
                        
                        if should_exclude:
                            # Skip this file - folder is excluded
                            filtered_out.append({
                                "file_name": file_name,
                                "project": project_name,
                                "folder": folder_path,
                                "reason": exclude_reason
                            })
                            continue
                        
                        # Check per-file ignore list
                        should_ignore, ignore_reason = FileIgnoreSettings.should_ignore_file(
                            project_name=project_name,
                            file_name=file_name,
                            folder_path=folder_path
                        )
                        
                        if should_ignore:
                            ignored_files.append({
                                "file_name": file_name,
                                "project": project_name,
                                "folder": folder_path,
                                "reason": ignore_reason
                            })
                            continue
                        
                        # Create RevitFileMetadata object
                        metadata = RevitFileMetadata(
                            hub_name=hub_name,
                            project_name=project_name,
                            file_name=file_name,
                            model_guid=file_info["model_guid"],
                            project_guid=file_info["project_guid"],
                            version=file_info["version"],
                            file_id=file_info.get("file_id", ""),
                            project_id=project_id,
                            hub_id=hub_id,
                            file_size_bytes=file_info.get("file_size_bytes", 0),
                            last_modified=file_info.get("last_modified", ""),
                            folder_path=folder_path,
                            has_complete_metadata=True,
                            skip_reason=None
                        )
                        processable.append(metadata)
        
        # Print project filtering summary
        if filtered_projects:
            total_filtered_files = sum(p["file_count"] for p in filtered_projects)
            print(f"\n[PROJECT FILTER] Excluded {len(filtered_projects)} project(s) ({total_filtered_files} files):")
            for proj in filtered_projects[:5]:
                print(f"  - {proj['project_name']} ({proj['file_count']} files)")
            if len(filtered_projects) > 5:
                print(f"  ... and {len(filtered_projects) - 5} more projects")
        
        # Print folder filtering summary
        if filtered_out:
            print(f"\n[FOLDER FILTER] Excluded {len(filtered_out)} files based on folder path:")
            # Group by reason
            reason_counts = {}
            for item in filtered_out:
                reason = item['reason']
                if reason not in reason_counts:
                    reason_counts[reason] = []
                reason_counts[reason].append(item)
            
            for reason, items in reason_counts.items():
                print(f"  [{reason}]: {len(items)} files")
                # Show first 3 examples
                for item in items[:3]:
                    print(f"    - {item['file_name']} ({item['folder']})")
                if len(items) > 3:
                    print(f"    ... and {len(items) - 3} more")
        
        if ignored_files:
            print(f"\n[FILE IGNORE] Skipped {len(ignored_files)} file(s) based on ignore list:")
            for item in ignored_files[:5]:
                folder_display = item['folder'] or "(root)"
                print(f"  - {item['file_name']} [{item['project']}] {folder_display}")
                print(f"    Reason: {item['reason']}")
            if len(ignored_files) > 5:
                print(f"  ... and {len(ignored_files) - 5} more")
        
        return processable
    
    def get_file_metadata(self, hub_name: str, project_name: str, file_name: str) -> Optional[RevitFileMetadata]:
        """
        Get metadata for a specific file
        
        Args:
            hub_name: Hub name
            project_name: Project name
            file_name: File name
            
        Returns:
            RevitFileMetadata if found, None otherwise
        """
        if not self.cache_data:
            return None
        
        try:
            api_data = self.cache_data.get("data", {})
            hub_data = api_data.get(hub_name)
            if not hub_data:
                return None
            
            project_data = hub_data.get("projects", {}).get(project_name)
            if not project_data:
                return None
            
            file_info = project_data.get("files", {}).get(file_name)
            if not file_info or not file_info.get("has_complete_metadata"):
                return None
            
            # Create RevitFileMetadata object
            return RevitFileMetadata(
                hub_name=hub_name,
                project_name=project_name,
                file_name=file_name,
                model_guid=file_info["model_guid"],
                project_guid=file_info["project_guid"],
                version=file_info["version"],
                file_id=file_info.get("file_id", ""),
                project_id=project_data.get("project_id", ""),
                hub_id=hub_data.get("hub_id", ""),
                file_size_bytes=file_info.get("file_size_bytes", 0),
                last_modified=file_info.get("last_modified", ""),
                folder_path=file_info.get("folder_path", ""),
                has_complete_metadata=True,
                skip_reason=None
            )
            
        except Exception as e:
            print(f"Error getting file metadata: {e}")
            return None

