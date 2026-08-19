"""
File Data Models for RevitSlave4
Structures for Revit file metadata from APS API
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict


@dataclass
class RevitFileMetadata:
    """
    Complete metadata for a Revit file from APS API
    Used during discovery and job creation
    """
    hub_name: str
    project_name: str
    file_name: str
    
    # GUIDs for cloud document opening
    model_guid: str
    project_guid: str
    version: int
    
    # IDs for reference
    file_id: str
    project_id: str
    hub_id: str
    
    # File metadata
    file_size_bytes: int
    last_modified: str
    folder_path: str  # Folder path in ACC (e.g., "Engineering/Models")
    
    # Processing metadata
    has_complete_metadata: bool
    skip_reason: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'hub_name': self.hub_name,
            'project_name': self.project_name,
            'file_name': self.file_name,
            'model_guid': self.model_guid,
            'project_guid': self.project_guid,
            'version': self.version,
            'file_id': self.file_id,
            'project_id': self.project_id,
            'hub_id': self.hub_id,
            'file_size_bytes': self.file_size_bytes,
            'last_modified': self.last_modified,
            'folder_path': self.folder_path,
            'has_complete_metadata': self.has_complete_metadata,
            'skip_reason': self.skip_reason
        }
    
    def get_size_mb(self) -> float:
        """Get file size in MB"""
        return self.file_size_bytes / (1024 * 1024)
    
    def is_processable(self) -> bool:
        """Check if file has complete metadata for processing"""
        return self.has_complete_metadata

