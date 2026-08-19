"""
Job Data Models for RevitSlave4
Structures for job payloads and results
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict


@dataclass
class JobPayload:
    """
    Job payload with guaranteed metadata
    Every job in RevitSlave4 ALWAYS has complete GUID data
    """
    job_id: str
    hub_name: str
    project_name: str
    file_name: str
    
    # GUARANTEED fields (always present in RevitSlave4)
    model_guid: str
    project_guid: str
    revit_version: int
    file_size_bytes: int
    
    # Metadata for reference
    project_id: str
    file_id: str
    folder_path: str  # Folder path in ACC (e.g., "Engineering/Models")
    
    # Status tracking
    timestamp: datetime
    status: str = 'job_created'
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'job_id': self.job_id,
            'hub_name': self.hub_name,
            'project_name': self.project_name,
            'file_name': self.file_name,
            'model_name': self.file_name,  # Alias for compatibility
            
            # Guaranteed metadata
            'model_guid': self.model_guid,
            'project_guid': self.project_guid,
            'revit_version': self.revit_version,
            'file_size_bytes': self.file_size_bytes,
            
            # Additional metadata
            'project_id': self.project_id,
            'file_id': self.file_id,
            'folder_path': self.folder_path,
            
            # Status
            'timestamp': self.timestamp.isoformat(),
            'status': self.status
        }


@dataclass
class JobResult:
    """Result of job execution"""
    job_id: str
    file_name: str
    status: str  # 'completed', 'failed', 'timeout', 'stuck'
    elapsed_seconds: float
    output_file: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'job_id': self.job_id,
            'file_name': self.file_name,
            'status': self.status,
            'elapsed_seconds': self.elapsed_seconds,
            'output_file': self.output_file,
            'errors': self.errors,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None
        }


@dataclass
class BatchResult:
    """Result of processing multiple jobs"""
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    timeout_jobs: int = 0
    stuck_jobs: int = 0
    total_duration_seconds: float = 0.0
    job_results: List[JobResult] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    def add_result(self, result: JobResult):
        """Add a job result and update statistics"""
        self.job_results.append(result)
        self.total_jobs += 1
        
        if result.status == 'completed':
            self.completed_jobs += 1
        elif result.status == 'failed':
            self.failed_jobs += 1
        elif result.status == 'timeout':
            self.timeout_jobs += 1
        elif result.status == 'stuck':
            self.stuck_jobs += 1
        
        self.total_duration_seconds += result.elapsed_seconds
    
    def get_summary(self) -> str:
        """Get summary string"""
        success_rate = (self.completed_jobs / self.total_jobs * 100) if self.total_jobs > 0 else 0
        return f"Batch: {self.completed_jobs}/{self.total_jobs} completed ({success_rate:.1f}%) in {self.total_duration_seconds:.1f}s"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'total_jobs': self.total_jobs,
            'completed_jobs': self.completed_jobs,
            'failed_jobs': self.failed_jobs,
            'timeout_jobs': self.timeout_jobs,
            'stuck_jobs': self.stuck_jobs,
            'total_duration_seconds': self.total_duration_seconds,
            'job_results': [r.to_dict() for r in self.job_results],
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None
        }

