"""
Version Fallback Detector for RevitSlave-3.0

When APS API doesn't provide Revit version metadata, this module
falls back to reading version from local ACC Desktop Connector files
using OLE BasicFileInfo method (learned from RevitSlave-2.0).

Process:
1. Map project/file name to ACC Desktop Connector path
2. Wait for file stability (ACC streams files slowly)
3. Extract version using OLE BasicFileInfo
4. Handle ZIP-compressed files (ACC packages linked models)
5. Clean up temp resources after extraction
"""

import os
import time
import re
import tempfile
import shutil
from pathlib import Path


# ANSI Color Codes
class Colors:
    """ANSI color codes for terminal output"""
    RESET = '\033[0m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    BRIGHT_GREEN = '\033[92m'


def cprint(tag, message="", color=Colors.RESET):
    """Color print with tag"""
    if message:
        print(f"{color}{tag}{Colors.RESET} {message}")
    else:
        print(f"{color}{tag}{Colors.RESET}")
from typing import Optional, Tuple


class VersionFallbackDetector:
    """
    Fallback version detector using local ACC Desktop Connector files.
    
    Used when APS API doesn't provide version metadata.
    """
    
    def __init__(self):
        self.acc_base_path = self._detect_acc_base_path()
    
    def _detect_acc_base_path(self) -> Optional[Path]:
        """
        Auto-detect ACC Desktop Connector base path.
        
        Standard location: C:/Users/<username>/ACC/
        
        Returns:
            Path to ACC folder or None if not found
        """
        username = os.environ.get('USERNAME', os.environ.get('USER', 'USERNAME'))
        
        # Standard ACC Desktop Connector locations
        # Note: Desktop Connector can be configured to use custom paths
        candidate_paths = [
            Path(f"C:/Users/{username}/DC/ACCDocs"),  # Custom DC path (common)
            Path(f"C:/Users/{username}/ACC"),
            Path(f"C:/Users/{username}/Autodesk/ACC"),
            Path(f"C:/Users/{username}/BIM 360"),
        ]
        
        for path in candidate_paths:
            if path.exists():
                cprint(f"[ACC]", f"Found Desktop Connector path: {path}", Colors.CYAN)
                return path
        
        cprint("[WARN]", "ACC Desktop Connector path not found", Colors.YELLOW)
        return None
    
    def find_local_file(self, hub_name: str, project_name: str, file_name: str) -> Optional[Path]:
        """
        Find local ACC file given hub, project, and file name.
        
        ACC structure: C:/Users/<user>/ACC/<HubName>/<ProjectName>/<FileName>
        
        Args:
            hub_name: Hub name from APS API
            project_name: Project name from APS API
            file_name: File name from APS API
            
        Returns:
            Path to local file or None if not found
        """
        if not self.acc_base_path:
            return None
        
        # Try direct path
        file_path = self.acc_base_path / hub_name / project_name / file_name
        if file_path.exists():
            return file_path
        
        # Try fuzzy matching (handle special characters)
        hub_folder = self.acc_base_path / hub_name
        if not hub_folder.exists():
            # Try finding hub with similar name
            for hub_dir in self.acc_base_path.iterdir():
                if hub_dir.is_dir() and hub_name.lower() in hub_dir.name.lower():
                    hub_folder = hub_dir
                    break
        
        if hub_folder.exists():
            project_folder = hub_folder / project_name
            if not project_folder.exists():
                # Try finding project with similar name
                for proj_dir in hub_folder.iterdir():
                    if proj_dir.is_dir() and project_name.lower() in proj_dir.name.lower():
                        project_folder = proj_dir
                        break
            
            if project_folder.exists():
                file_path = project_folder / file_name
                if file_path.exists():
                    return file_path
                
                # Try finding file with similar name (exact match first)
                for file in project_folder.iterdir():
                    if file.is_file() and file.name.lower() == file_name.lower():
                        return file
                
                # Recursive search through subdirectories (ACC has nested folders like Project Files/BIM/)
                # Limit depth to avoid performance issues
                try:
                    for file in project_folder.rglob(file_name):
                        if file.is_file():
                            return file
                    
                    # Case-insensitive recursive search
                    for file in project_folder.rglob("*.rvt"):
                        if file.is_file() and file.name.lower() == file_name.lower():
                            return file
                except Exception as e:
                    # Ignore errors during recursive search
                    pass
        
        return None
    
    def detect_version_from_local_file(self, hub_name: str, project_name: str, 
                                      file_name: str, timeout_minutes: int = 5) -> Optional[str]:
        """
        Detect Revit version from local ACC Desktop Connector file.
        
        Args:
            hub_name: Hub name
            project_name: Project name
            file_name: File name
            timeout_minutes: Max time to wait for file stability
            
        Returns:
            Version string (e.g., "2024") or None if failed
        """
        cprint(f"\n[FALLBACK]", f"Attempting local version detection for: {file_name}", Colors.MAGENTA)
        
        # Find local file
        local_path = self.find_local_file(hub_name, project_name, file_name)
        if not local_path:
            cprint(f"[FALLBACK]", "File not found in ACC Desktop Connector", Colors.YELLOW)
            return None
        
        cprint(f"[FALLBACK]", f"Found local file: {local_path}", Colors.GREEN)
        
        # Detect version using OLE method
        try:
            version = self._detect_version_from_ole(local_path, timeout_minutes * 60)
            if version and version != "Unknown":
                cprint(f"[FALLBACK]", f"✓ Detected version: {version}", Colors.BRIGHT_GREEN)
                return version
            else:
                cprint(f"[FALLBACK]", "✗ Could not detect version", Colors.YELLOW)
                return None
        except Exception as e:
            cprint(f"[FALLBACK]", f"Error: {e}", Colors.YELLOW)
            return None
    
    def _detect_version_from_ole(self, file_path: Path, timeout_seconds: int = 300) -> Optional[str]:
        """
        Extract version from OLE BasicFileInfo (learned from RevitSlave-2.0).
        
        Handles:
        - File stability waiting (ACC streams files)
        - ZIP-compressed files (ACC packages linked models)
        - Temp resource cleanup
        
        Args:
            file_path: Path to local Revit file
            timeout_seconds: Max wait time for file stability
            
        Returns:
            Version string or None
        """
        try:
            import olefile
        except ImportError:
            print("[ERROR] olefile library required: pip install olefile")
            return None
        
        try:
            import zipfile
            
            # Check if ZIP-compressed (ACC packages linked models)
            if zipfile.is_zipfile(file_path):
                print(f"[FALLBACK] File is ZIP package, extracting...")
                return self._extract_and_detect_from_zip(file_path, timeout_seconds)
            
            # Wait for file stability
            if not self._wait_for_file_stability(file_path, timeout_seconds):
                print(f"[FALLBACK] File not stable after {timeout_seconds}s")
                return None
            
            # Validate OLE format
            if not olefile.isOleFile(str(file_path)):
                print(f"[FALLBACK] File is not valid OLE/Revit format")
                return None
            
            # Read BasicFileInfo
            with olefile.OleFileIO(str(file_path)) as rvt_ole:
                if not rvt_ole.exists("BasicFileInfo"):
                    print(f"[FALLBACK] No BasicFileInfo stream found")
                    return None
                
                with rvt_ole.openstream("BasicFileInfo") as bfi:
                    file_info = bfi.read().decode("utf-16le", "ignore")
                    
                    # Extract version using regex patterns (from RevitSlave-2.0)
                    version = self._parse_version_from_info(file_info)
                    return version
        
        except Exception as e:
            print(f"[FALLBACK] OLE detection error: {type(e).__name__}: {str(e)[:100]}")
            return None
    
    def _wait_for_file_stability(self, file_path: Path, timeout_seconds: int) -> bool:
        """
        Wait for file size to stabilize (ACC Desktop Connector streams files).
        
        Args:
            file_path: Path to file
            timeout_seconds: Max wait time
            
        Returns:
            True if file is stable, False if timeout
        """
        print(f"[FALLBACK] Waiting for file stability (timeout: {timeout_seconds}s)...")
        
        start_time = time.time()
        last_size = -1
        stable_checks = 0
        stable_required = 3  # 3 consecutive stable checks (6 seconds)
        
        while time.time() - start_time < timeout_seconds:
            try:
                current_size = file_path.stat().st_size
                
                if current_size == last_size and current_size > 0:
                    stable_checks += 1
                    if stable_checks >= stable_required:
                        elapsed = int(time.time() - start_time)
                        print(f"[FALLBACK] File stable after {elapsed}s")
                        return True
                else:
                    stable_checks = 0
                    last_size = current_size
                    
                    # Log progress every 10 seconds
                    elapsed = int(time.time() - start_time)
                    if elapsed % 10 == 0 and elapsed > 0:
                        size_mb = current_size / (1024 * 1024)
                        print(f"[FALLBACK] Still downloading: {size_mb:.1f}MB ({elapsed}s)")
            
            except Exception as e:
                print(f"[FALLBACK] File access error: {type(e).__name__}")
            
            time.sleep(2)  # Check every 2 seconds
        
        return False
    
    def _extract_and_detect_from_zip(self, zip_path: Path, timeout_seconds: int) -> Optional[str]:
        """
        Extract host RVT from ACC ZIP package and detect version.
        
        ACC packages host + linked models in single ZIP.
        We only extract the HOST file (ignore linked files).
        IMPORTANT: Cleanup temp files after extraction.
        
        Args:
            zip_path: Path to ZIP file
            timeout_seconds: Timeout for extraction
            
        Returns:
            Version string or None
        """
        import zipfile
        
        temp_dir = None
        try:
            # Create temp directory
            temp_dir = Path(tempfile.mkdtemp(prefix="revitslave3_zip_"))
            print(f"[FALLBACK] Temp extraction dir: {temp_dir}")
            
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Find host RVT file (matches original filename)
                target_name = zip_path.stem  # Remove .zip extension
                
                for zip_info in zf.namelist():
                    if zip_info.endswith('.rvt'):
                        # Extract potential host file
                        extracted_path = temp_dir / Path(zip_info).name
                        
                        print(f"[FALLBACK] Extracting: {zip_info}")
                        with zf.open(zip_info) as source:
                            with open(extracted_path, 'wb') as target:
                                shutil.copyfileobj(source, target)
                        
                        # Try to detect version from this file
                        version = self._detect_version_from_ole(extracted_path, timeout_seconds)
                        
                        if version and version != "Unknown":
                            return version  # Found it!
            
            print(f"[FALLBACK] No valid RVT found in ZIP")
            return None
        
        except Exception as e:
            print(f"[FALLBACK] ZIP extraction error: {type(e).__name__}: {str(e)[:100]}")
            return None
        
        finally:
            # CRITICAL: Clean up temp resources
            if temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                    print(f"[FALLBACK] ✓ Cleaned up temp dir: {temp_dir}")
                except Exception as e:
                    print(f"[FALLBACK] ⚠ Failed to cleanup {temp_dir}: {e}")
    
    def _parse_version_from_info(self, file_info: str) -> Optional[str]:
        """
        Parse Revit version from BasicFileInfo content using regex patterns.
        
        Patterns learned from RevitSlave-2.0's proven patterns.
        
        Args:
            file_info: BasicFileInfo stream content
            
        Returns:
            Version string (e.g., "2024") or None
        """
        # Regex patterns (priority order) from RevitSlave-2.0
        patterns = [
            (r'Format["\s]*:?\s*(\d{4})', "Format field"),
            (r'Revit\s+Build[:\s]*(\d{4})', "Revit Build"),
            (r'Revit\s*(\d{4})', "Revit keyword"),
            (r'Version[:\s]*(\d{4})', "Version keyword"),
            (r'Autodesk\s+Revit\s+(\d{4})', "Autodesk Revit"),
            (r'RVT\s*(\d{4})', "RVT marker"),
            (r'Build:\s*Revit\s*(\d{4})', "Build Revit"),
            (r'\.rvt.{0,5}(20[12]\d).{0,5}\d{8}_\d{4}', "RVT with timestamp"),
            (r'(20[12]\d).{0,3}\d{8}_\d{4}\(x\d+\)', "Year before date(x64)"),
        ]
        
        for pattern, description in patterns:
            match = re.search(pattern, file_info, re.IGNORECASE)
            if match:
                version = match.group(1)
                # Validate it's a reasonable Revit version
                try:
                    version_int = int(version)
                    if 2015 <= version_int <= 2030:
                        print(f"[FALLBACK] Found version via {description}: {version}")
                        return version
                except ValueError:
                    continue
        
        # Log preview for debugging
        try:
            preview = file_info[:200].encode('ascii', errors='replace').decode('ascii')
            preview = preview.replace('\x00', ' ').strip()
            print(f"[FALLBACK] BasicFileInfo preview: {preview[:100]}...")
        except Exception:
            print(f"[FALLBACK] BasicFileInfo length: {len(file_info)} chars")
        
        return None


# Convenience function
def detect_version_fallback(hub_name: str, project_name: str, file_name: str, 
                           timeout_minutes: int = 5) -> Optional[str]:
    """
    Convenience function to detect version from local ACC file.
    
    Args:
        hub_name: Hub name
        project_name: Project name  
        file_name: File name
        timeout_minutes: Max wait time
        
    Returns:
        Version string or None
    """
    detector = VersionFallbackDetector()
    return detector.detect_version_from_local_file(hub_name, project_name, file_name, timeout_minutes)

