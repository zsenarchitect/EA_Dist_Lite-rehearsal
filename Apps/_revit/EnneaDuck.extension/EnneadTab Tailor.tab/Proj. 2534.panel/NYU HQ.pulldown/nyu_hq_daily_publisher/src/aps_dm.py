from __future__ import annotations

from typing import List, Optional, Tuple

import requests


API_ROOT = "https://developer.api.autodesk.com"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def list_hubs(token: str) -> Optional[list]:
    url = f"{API_ROOT}/project/v1/hubs"
    try:
        resp = requests.get(url, headers=_auth_header(token), timeout=30)
        if resp.status_code != 200:
            return None
        return resp.json().get("data", [])
    except Exception:
        return None


def list_projects(token: str, hub_id: str) -> Optional[list]:
    url = f"{API_ROOT}/project/v1/hubs/{hub_id}/projects"
    try:
        resp = requests.get(url, headers=_auth_header(token), timeout=30)
        if resp.status_code != 200:
            return None
        return resp.json().get("data", [])
    except Exception:
        return None


def find_project_by_name(token: str, project_name: str) -> Optional[Tuple[str, str]]:
    """Return (b_prefixed_project_id, hub_id) or None."""
    hubs = list_hubs(token)
    if not hubs:
        return None
    for hub in hubs:
        hub_id = hub.get("id")
        projects = list_projects(token, hub_id)
        if not projects:
            continue
        for proj in projects:
            name = (proj.get("attributes", {}) or {}).get("name")
            pid = proj.get("id")
            if name == project_name and pid:
                # Ensure b. prefix for Data API project ids
                b_project_id = pid if pid.startswith("b.") else f"b.{pid}"
                return b_project_id, hub_id
    return None


def top_folders(token: str, hub_id: str, b_project_id: str) -> Optional[list]:
    url = f"{API_ROOT}/project/v1/hubs/{hub_id}/projects/{b_project_id}/topFolders"
    try:
        resp = requests.get(url, headers=_auth_header(token), timeout=30)
        if resp.status_code != 200:
            return None
        return resp.json().get("data", [])
    except Exception:
        return None


def folder_contents(token: str, b_project_id: str, folder_id: str) -> Optional[list]:
    url = f"{API_ROOT}/data/v1/projects/{b_project_id}/folders/{folder_id}/contents"
    try:
        resp = requests.get(url, headers=_auth_header(token), timeout=30)
        if resp.status_code != 200:
            return None
        return resp.json().get("data", [])
    except Exception:
        return None


def find_item_ids_by_names(token: str, b_project_id: str, hub_id: str, target_names: List[str]) -> dict:
    """Recursively traverse folders to locate item lineage ids by file names.

    Returns mapping name -> lineage id (if found).
    """
    targets = {name.lower(): None for name in target_names}

    roots = top_folders(token, hub_id, b_project_id) or []
    stack = [node.get("id") for node in roots if node.get("type") == "folders"]

    while stack and any(v is None for v in targets.values()):
        folder_id = stack.pop()
        entries = folder_contents(token, b_project_id, folder_id) or []
        for entry in entries:
            etype = entry.get("type")
            eid = entry.get("id")
            attrs = entry.get("attributes", {}) or {}
            name = (attrs.get("displayName") or attrs.get("name") or "").strip()

            if etype == "folders":
                stack.append(eid)
                continue
            if etype == "items":
                key = name.lower()
                if key in targets and targets[key] is None:
                    targets[key] = eid

    # convert back to requested-case keys
    result = {}
    for k in target_names:
        result[k] = targets.get(k.lower())
    return result


def publish_command(token: str, b_project_id: str, item_ids: List[str], extra_headers: Optional[dict] = None, extension_type: str = "commands:autodesk.bim360:C4RPublishWithoutLinks") -> tuple[bool, Optional[int], Optional[str], Optional[str]]:
    """Publish a single Revit model using APS Data Management API v1 commands.
    
    API Documentation References:
    - Publish Model: https://aps.autodesk.com/en/docs/data/v2/reference/http/PublishModel/
    - Publish Without Links: https://aps.autodesk.com/en/docs/data/v2/reference/http/PublishWithoutLinks/
    - Get Publish Job: https://aps.autodesk.com/en/docs/data/v2/reference/http/GetPublishModelJob/
    
    IMPORTANT: API requires exactly ONE resource per publish command.
    The item_ids list must contain only a single item ID.
    
    Publishing Strategies:
    - commands:autodesk.bim360:C4RPublishWithLinks:
      Publishes models while preserving their links/references.
      Important for coordinated multi-model projects (Shell + Site, etc.)
      
    - commands:autodesk.bim360:C4RPublishWithoutLinks:
      Publishes models independently without preserving links between them.
      Used as fallback when WITH links is not supported in the region.
    
    Args:
        token: Access token (2-legged or 3-legged OAuth)
        b_project_id: BIM 360/ACC project ID (with "b." prefix)
        item_ids: List containing exactly ONE item lineage URN to publish
        extra_headers: Optional impersonation headers for 2-legged auth
        extension_type: Command extension type (default: C4RPublishWithoutLinks)

    Returns: (success, http_status, command_id, error_text)
    """
    if not item_ids or len(item_ids) != 1:
        return False, None, None, f"Expected exactly 1 item_id, got {len(item_ids)}"
    
    # Use v1 commands API endpoint
    url = f"{API_ROOT}/data/v1/projects/{b_project_id}/commands"
    
    headers = {
        **_auth_header(token),
        "Content-Type": "application/vnd.api+json",
    }
    if extra_headers:
        headers.update(extra_headers)
    
    payload = {
        "jsonapi": {"version": "1.0"},
        "data": {
            "type": "commands",
            "attributes": {
                "extension": {
                    "type": extension_type,
                    "version": "1.0.0",
                }
            },
            "relationships": {
                "resources": {
                    "data": [{"type": "items", "id": iid} for iid in item_ids]
                }
            }
        }
    }
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code not in (200, 201, 202):
            try:
                err = resp.text
            except Exception:
                err = None
            return False, resp.status_code, None, err
        
        data = resp.json()
        cmd_id = (data.get("data", {}) or {}).get("id")
        return True, resp.status_code, cmd_id, None
    except Exception as ex:
        return False, None, None, str(ex)


def get_publish_job_status(token: str, b_project_id: str, item_id: str, job_id: str, extra_headers: Optional[dict] = None) -> Optional[dict]:
    """Get the status of a publish job.
    
    API Reference: https://aps.autodesk.com/en/docs/data/v2/reference/http/GetPublishModelJob/
    
    Args:
        token: Access token (2-legged or 3-legged OAuth)
        b_project_id: BIM 360/ACC project ID (with "b." prefix)
        item_id: Item lineage URN
        job_id: Job ID returned from publish command
        extra_headers: Optional impersonation headers for 2-legged auth
    
    Returns: Job status dict or None on error
    """
    url = f"{API_ROOT}/data/v2/projects/{b_project_id}/items/{item_id}/publish/{job_id}"
    headers = _auth_header(token)
    if extra_headers:
        headers.update(extra_headers)
    
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


