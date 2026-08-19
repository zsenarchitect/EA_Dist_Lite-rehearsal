"""
Model Validator for RevitSlave4
Pre-validates models exist before launching Revit

Adapted from acc_sdk (MIT License)
Repository: https://github.com/realdanielbyrne/acc_sdk
Author: Daniel Byrne (realdanielbyrne)
License: MIT (allows extraction and modification)

This module provides a simple way to check if models exist in ACC/BIM360
via the APS Data Management API before attempting to open them in Revit.

Key benefit: Skip deleted models immediately instead of wasting 5-10 minutes
launching Revit only to discover the model is missing.
"""

import requests
from typing import Tuple, Optional, Dict, List
import time


class ModelValidator:
    """
    Validate model existence via APS Data Management API
    
    Prevents wasted time launching Revit for deleted/archived models.
    Uses single API call per model to check status.
    """
    
    def __init__(self, access_token: str):
        """
        Initialize validator with APS access token
        
        Args:
            access_token: Bearer token from APS authentication
        """
        self.access_token = access_token
        self.base_url = "https://developer.api.autodesk.com/data/v1"
        self.api_call_count = 0
    
    def check_item_exists(
        self, 
        project_id: str, 
        item_id: str,
        model_name: str = "Unknown"
    ) -> Tuple[bool, Optional[Dict], Optional[str]]:
        """
        Check if item/model exists via APS Data Management API
        
        Adapted from acc_sdk's AccDataManagementApi.get_item() method
        
        Args:
            project_id: Project ID (format: b.xxxxx or just xxxxx)
            item_id: Item ID (format: urn:adsk.wipprod:dm.lineage:xxx)
            model_name: Model name for logging (optional)
        
        Returns:
            Tuple of (exists: bool, metadata: dict or None, error: str or None)
            
            exists: True if model is active and accessible
            metadata: Item data from API if exists
            error: Human-readable reason if doesn't exist
        
        API Endpoint:
            GET /data/v1/projects/{project_id}/items/{item_id}
            
        HTTP Status Codes:
            200 OK: Model exists and accessible
            404 Not Found: Model deleted or moved
            403 Forbidden: No access permissions
            401 Unauthorized: Token expired
        """
        # Ensure project_id has b. prefix (API requirement)
        if not project_id.startswith("b."):
            project_id = f"b.{project_id}"
        
        url = f"{self.base_url}/projects/{project_id}/items/{item_id}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        
        self.api_call_count += 1
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json().get("data", {})
                return (True, data, None)
            
            elif response.status_code == 404:
                return (False, None, "Model not found (deleted or moved)")
            
            elif response.status_code == 403:
                return (False, None, "Access denied (check permissions)")
            
            elif response.status_code == 401:
                return (False, None, "Authentication failed (token expired)")
            
            elif response.status_code == 429:
                return (False, None, "Rate limit exceeded (too many requests)")
            
            else:
                error_text = response.text[:200] if response.text else "Unknown error"
                return (False, None, f"HTTP {response.status_code}: {error_text}")
                
        except requests.exceptions.Timeout:
            # Timeout - assume exists to avoid false negatives (safe failure mode)
            return (True, None, "Validation timeout - assuming exists (fallback)")
        
        except requests.exceptions.ConnectionError:
            # Network error - assume exists to avoid blocking
            return (True, None, "Network error - assuming exists (fallback)")
        
        except requests.exceptions.RequestException as e:
            # Other request errors - assume exists for safety
            error_msg = str(e)[:200]
            return (True, None, f"Validation error - assuming exists: {error_msg}")
    
    def batch_validate(
        self, 
        project_id: str,
        items: List[Dict],
        verbose: bool = True
    ) -> Tuple[List[Dict], List[Tuple[Dict, str]], int]:
        """
        Validate multiple items in batch
        
        Args:
            project_id: ACC project ID
            items: List of dicts with 'item_id' and 'model_name' keys
            verbose: Print progress messages
        
        Returns:
            Tuple of:
            - valid_items: List of items that exist
            - invalid_items: List of (item, error_reason) tuples
            - api_call_count: Number of API calls made
        """
        valid = []
        invalid = []
        start_time = time.time()
        
        if verbose:
            print(f"\n[PRE-VALIDATION] Checking {len(items)} models via APS API...")
            print("-" * 80)
        
        for idx, item in enumerate(items, 1):
            model_name = item.get('model_name', 'Unknown')
            item_id = item.get('item_id') or item.get('file_id')
            
            if not item_id:
                if verbose:
                    print(f"[{idx}/{len(items)}] {model_name}: SKIP (no item_id)")
                invalid.append((item, "Missing item_id"))
                continue
            
            if verbose:
                print(f"[{idx}/{len(items)}] {model_name}... ", end="", flush=True)
            
            exists, metadata, error = self.check_item_exists(
                project_id, 
                item_id,
                model_name
            )
            
            if exists:
                valid.append(item)
                if verbose:
                    print("✓ Active")
            else:
                invalid.append((item, error))
                if verbose:
                    print(f"✗ {error}")
            
            # Rate limiting: Respect API limits (~100 requests/min)
            # Add small delay to avoid hitting rate limits
            if idx < len(items):  # Don't sleep after last item
                time.sleep(0.6)  # Max ~100 requests per minute
        
        elapsed = time.time() - start_time
        
        if verbose:
            print("-" * 80)
            print(f"[VALIDATION COMPLETE]")
            print(f"  Time: {elapsed:.1f} seconds")
            print(f"  Active models: {len(valid)}")
            print(f"  Skipped models: {len(invalid)}")
            print(f"  API calls made: {self.api_call_count}")
            
            if invalid and len(invalid) <= 10:
                print(f"\nSkipped Models:")
                for item, error in invalid:
                    print(f"  - {item.get('model_name', 'Unknown')}: {error}")
            elif invalid:
                print(f"\nSkipped Models (showing first 10 of {len(invalid)}):")
                for item, error in invalid[:10]:
                    print(f"  - {item.get('model_name', 'Unknown')}: {error}")
                print(f"  ... and {len(invalid) - 10} more")
        
        return (valid, invalid, self.api_call_count)
    
    def get_api_stats(self) -> Dict:
        """Get API call statistics for this validator instance"""
        return {
            "total_api_calls": self.api_call_count,
            "base_url": self.base_url
        }


# Standalone testing function
if __name__ == "__main__":
    print("ModelValidator Test")
    print("=" * 80)
    print("\nThis module requires:")
    print("  1. APS_CLIENT_ID environment variable")
    print("  2. APS_CLIENT_SECRET environment variable")
    print("\nUsage:")
    print("  from core.model_validator import ModelValidator")
    print("  validator = ModelValidator(access_token)")
    print("  exists, metadata, error = validator.check_item_exists(project_id, item_id)")
    print("\nSee: DEBUG/external_sdks/SDK_COMPARISON_ANALYSIS.md for details")

