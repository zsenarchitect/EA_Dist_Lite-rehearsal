"""
RevitSlave4 - API-First Batch Processing with Model Pre-Validation
===================================================================

NEW in V4: Pre-validates models exist before launching Revit!
- Skips deleted/archived models immediately (saves 5-10 min per model)
- Reduces run time by 50-80% for projects with deleted models  
- Higher success rate (no wasted Revit launches)

Key Features:
- **Model pre-validation via APS API** (V4 exclusive!)
- API-first discovery (no ACC folder dependency)
- Guaranteed GUIDs in every payload (model_guid, project_guid, version)
- 7-day cached GUID data for fast lookups
- Intelligent timeout based on file size
- Dual monitoring (job status + Revit heartbeat)

Usage:
    python RevitSlave4.py [--force-refresh] [--project PROJECT_NAME]
    
    # Disable validation (fallback to V3 behavior):
    python RevitSlave4.py --no-validate

Requirements:
    - Autodesk Platform Services (APS) credentials
    - pyRevit installed and in PATH
    - requests library: pip install requests
"""

import sys
import os
import argparse
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Version info
__version__ = "4.0.0"
__author__ = "EnneadTab"

def main():
    """Main entry point for RevitSlave4"""
    
    print("\n" + "="*80)
    print("RevitSlave4 - API-First Batch Processing with Pre-Validation")
    print(f"Version: {__version__}")
    print("="*80)
    
    # Parse arguments
    parser = argparse.ArgumentParser(description="RevitSlave4 - With Model Pre-Validation")
    parser.add_argument('--force-refresh', action='store_true', 
                        help='Force cache refresh even if valid')
    parser.add_argument('--project', nargs='+', 
                        help='Filter to specific project(s) by name (substring match)')
    parser.add_argument('--no-validate', action='store_true',
                        help='Disable model pre-validation (fallback to V3 behavior)')
    args = parser.parse_args()
    
    # Handle --no-validate flag
    if args.no_validate:
        from config.settings import ValidationSettings
        ValidationSettings.ENABLED = False
        print("[MODE] Pre-validation DISABLED - using RevitSlave4 behavior")
    
    try:
        # Get credentials
        from config.credentials import CredentialManager
        
        cred_manager = CredentialManager()
        client_id, client_secret = cred_manager.get_credentials()
        
        if not client_id or not client_secret:
            print("\n[ERROR] APS credentials required")
            print("\nOptions:")
            print("  1. Create config/aps_credentials.json with your credentials")
            print("  2. Set environment variables: APS_CLIENT_ID, APS_CLIENT_SECRET")
            print("  3. Run script and enter credentials when prompted")
            return 1
        
        # Run orchestrator
        from orchestration.orchestrator import RevitSlave4Orchestrator
        
        orchestrator = RevitSlave4Orchestrator(client_id, client_secret, project_filter=args.project)
        success = orchestrator.run(force_refresh=args.force_refresh)
        
        if success:
            print("\n[SUCCESS] RevitSlave4 completed successfully")
            return 0
        else:
            print("\n[ERROR] RevitSlave4 completed with errors")
            return 1
            
    except KeyboardInterrupt:
        print("\n\n[WARNING] Interrupted by user (Ctrl+C)")
        return 130
    except Exception as e:
        import traceback
        print(f"\n[ERROR] Fatal error: {e}")
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())

