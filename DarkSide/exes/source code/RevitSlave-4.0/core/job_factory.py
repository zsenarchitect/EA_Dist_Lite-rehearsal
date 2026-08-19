"""
Job Factory for RevitSlave4
Creates job payloads with guaranteed complete metadata
"""

from datetime import datetime
from models.job_models import JobPayload
from models.file_models import RevitFileMetadata


class JobFactory:
    """
    Creates job payloads with validation
    Every job in RevitSlave4 is guaranteed to have complete GUID data
    """
    
    def create_job(self, file_metadata: RevitFileMetadata, job_index: int) -> JobPayload:
        """
        Build job payload from file metadata with validation
        
        Args:
            file_metadata: RevitFileMetadata with complete data
            job_index: Job index number
            
        Returns:
            JobPayload with guaranteed complete metadata
            
        Raises:
            ValueError: If metadata is incomplete (should never happen after filtering)
        """
        # Validate complete metadata (defensive check)
        if not file_metadata.has_complete_metadata:
            raise ValueError(f"Cannot create job for file without complete metadata: {file_metadata.file_name}")
        
        # Validate required fields
        required_fields = {
            'model_guid': file_metadata.model_guid,
            'project_guid': file_metadata.project_guid,
            'version': file_metadata.version
        }
        
        for field_name, field_value in required_fields.items():
            if not field_value or field_value == "N/A":
                raise ValueError(f"Missing required field '{field_name}' for {file_metadata.file_name}")
        
        # Validate version is integer
        if not isinstance(file_metadata.version, int):
            raise ValueError(f"Version must be integer, got {type(file_metadata.version).__name__}: {file_metadata.version}")
        
        # Build job ID
        job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_index}"
        
        # Create job payload
        payload = JobPayload(
            job_id=job_id,
            hub_name=file_metadata.hub_name,
            project_name=file_metadata.project_name,
            file_name=file_metadata.file_name,
            
            # Guaranteed fields
            model_guid=file_metadata.model_guid,
            project_guid=file_metadata.project_guid,
            revit_version=file_metadata.version,
            file_size_bytes=file_metadata.file_size_bytes,
            
            # Additional metadata
            project_id=file_metadata.project_id,
            file_id=file_metadata.file_id,
            folder_path=file_metadata.folder_path,
            
            # Timestamp
            timestamp=datetime.now(),
            status='job_created'
        )
        
        return payload
    
    def create_batch(self, file_metadata_list: list) -> list:
        """
        Create multiple job payloads from list of file metadata
        
        Args:
            file_metadata_list: List of RevitFileMetadata objects
            
        Returns:
            List of JobPayload objects
        """
        jobs = []
        
        for i, file_meta in enumerate(file_metadata_list, 1):
            try:
                job = self.create_job(file_meta, i)
                jobs.append(job)
            except ValueError as e:
                print(f"[WARNING] Skipping file {file_meta.file_name}: {e}")
                continue
        
        return jobs

