"""
Cache Data Models for RevitSlave4
Structures for GUID cache system
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class RevitFileGUID:
    """GUID metadata for a single Revit file"""
    model_guid: str
    project_guid: str
    version: int
    file_size_bytes: int
    
    # IDs for reference
    project_id: str
    file_id: str
    
    # Metadata
    last_modified: str
    has_complete_metadata: bool
    skip_reason: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'model_guid': self.model_guid,
            'project_guid': self.project_guid,
            'version': self.version,
            'file_size_bytes': self.file_size_bytes,
            'project_id': self.project_id,
            'file_id': self.file_id,
            'last_modified': self.last_modified,
            'has_complete_metadata': self.has_complete_metadata,
            'skip_reason': self.skip_reason
        }


@dataclass
class CacheStatistics:
    """Statistics about cached data"""
    total_hubs: int = 0
    total_projects: int = 0
    total_files: int = 0
    processable_files: int = 0
    skipped_files: int = 0
    cache_age_days: float = 0.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'total_hubs': self.total_hubs,
            'total_projects': self.total_projects,
            'total_files': self.total_files,
            'processable_files': self.processable_files,
            'skipped_files': self.skipped_files,
            'cache_age_days': self.cache_age_days
        }


@dataclass
class GUIDCache:
    """Complete GUID cache structure"""
    cache_version: str
    generated_at: datetime
    expires_at: datetime
    stats: CacheStatistics
    data: Dict  # Nested hub/project/file structure
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'cache_version': self.cache_version,
            'generated_at': self.generated_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
            'stats': self.stats.to_dict(),
            'data': self.data
        }

