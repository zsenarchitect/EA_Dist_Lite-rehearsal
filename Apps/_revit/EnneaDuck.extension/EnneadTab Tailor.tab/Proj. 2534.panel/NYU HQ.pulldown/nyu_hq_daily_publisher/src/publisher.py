# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Optional, Tuple
from pathlib import Path

from aps_auth import get_access_token, get_impersonation_headers
from aps_dm import publish_command
from oauth3 import get_user_access_token
from logging_utils import get_logger


def publish_resources(b_project_id: str, item_ids: List[str], publish_with_links: bool = False) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
    """Publish provided lineage item ids via APS command with smart fallback strategy.
    
    Strategy:
    1. Always try publishing WITH links first (better coordination)
    2. If that fails (except auth errors), retry WITHOUT links (fallback)
    3. This ensures maximum coordination while gracefully handling unsupported regions
    
    The publish_with_links parameter is now used as a hint but will always try
    WITH links first for best results.

    Returns: (success, http_status, command_id, error_text)
    """
    logger = get_logger()
    
    if not b_project_id or not item_ids:
        return False, None, None, "Missing project_id or item_ids"

    config_dir = Path(__file__).resolve().parent.parent / "configs"
    
    # Helper function to try both strategies
    def try_publish(token: str, extra_headers: Optional[dict] = None) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
        """Try publishing with links first, then without links as fallback.
        
        Uses APS Data Management API v2 endpoints:
        - /publish (with links) for coordinated models
        - /publishWithoutLinks (without links) as fallback
        """
        
        # FIRST ATTEMPT: Try WITH links (best for model coordination)
        logger.info("Attempting publish WITH links (C4RPublishWithLinks)...")
        ext_type_with = "commands:autodesk.bim360:C4RPublishWithLinks"
        ok, status, cmd_id, err = publish_command(token, b_project_id, item_ids, extra_headers=extra_headers, extension_type=ext_type_with)
        
        # If successful, return immediately
        if ok:
            logger.info(f"✅ Successfully published WITH links - CommandId={cmd_id}")
            return True, status, cmd_id, f"Published with links - {err or ''}"
        
        # If auth error, don't retry - need to fix auth first
        if status == 401 or status == 403:
            logger.warning(f"Authentication/permission error (HTTP {status}), skipping fallback")
            return False, status, cmd_id, err
        
        # FALLBACK: Retry WITHOUT links
        logger.warning(f"Publish with links failed (HTTP {status}): {err}")
        logger.info("Retrying WITHOUT links (C4RPublishWithoutLinks) as fallback...")
        
        ext_type_without = "commands:autodesk.bim360:C4RPublishWithoutLinks"
        ok_fallback, status_fallback, cmd_id_fallback, err_fallback = publish_command(
            token, b_project_id, item_ids, extra_headers=extra_headers, extension_type=ext_type_without
        )
        
        if ok_fallback:
            logger.info(f"✅ Successfully published WITHOUT links (fallback) - CommandId={cmd_id_fallback}")
            return True, status_fallback, cmd_id_fallback, f"Published without links (fallback) - {err_fallback or ''}"
        else:
            logger.error(f"❌ Both publish strategies failed. With links: {err}, Without links: {err_fallback}")
            return False, status_fallback, cmd_id_fallback, f"Both failed - WithLinks: {err}, WithoutLinks: {err_fallback}"
    
    # Try 2-legged with impersonation first
    token2 = get_access_token(config_dir)
    if token2:
        extra = get_impersonation_headers(config_dir)
        ok, status, cmd, err = try_publish(token2, extra_headers=extra)
        if status != 401:  # If not auth error, return result (whether success or other error)
            return ok, status, cmd, err

    # Fallback to 3-legged user token if available
    token3 = get_user_access_token(config_dir)
    if token3:
        logger.info("2-legged auth failed, trying 3-legged user token...")
        return try_publish(token3, extra_headers=None)

    return False, None, None, "No valid token (2-legged unauthorized and no 3-legged token)"


