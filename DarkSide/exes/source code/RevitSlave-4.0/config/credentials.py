"""
APS Credential Management for RevitSlave4
Handles loading credentials from config file or environment variables
Zero EnneadTab dependencies
"""

import json
import os
from pathlib import Path


class CredentialManager:
    """Manages Autodesk Platform Services (APS) credentials"""
    
    def __init__(self):
        self.config_dir = Path(__file__).parent
        self.cred_file = self.config_dir / "aps_credentials.json"
    
    def get_credentials(self):
        """
        Get APS credentials from:
        1. Config file (primary)
        2. Environment variables (fallback)
        3. User input (if neither available)
        
        Returns:
            Tuple of (client_id, client_secret) or (None, None)
        """
        # Try config file first
        creds = self._load_from_config()
        if creds:
            print("[OK] Loaded credentials from config file")
            return creds
        
        # Try environment variables
        creds = self._load_from_env()
        if creds:
            print("[OK] Loaded credentials from environment variables")
            return creds
        
        # Prompt user
        print("[WARNING] APS credentials not found in config or environment")
        return self._prompt_user()
    
    def _load_from_config(self):
        """Load from config/aps_credentials.json"""
        if self.cred_file.exists():
            try:
                with open(self.cred_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    client_id = data.get("client_id")
                    client_secret = data.get("client_secret")
                    if client_id and client_secret:
                        return (client_id, client_secret)
            except Exception as e:
                print(f"Warning: Error reading credentials file: {e}")
        return None
    
    def _load_from_env(self):
        """Load from environment variables APS_CLIENT_ID and APS_CLIENT_SECRET"""
        client_id = os.environ.get('APS_CLIENT_ID')
        client_secret = os.environ.get('APS_CLIENT_SECRET')
        if client_id and client_secret:
            return (client_id, client_secret)
        return None
    
    def _prompt_user(self):
        """Prompt user for credentials and optionally save"""
        print("\nPlease enter your Autodesk Platform Services credentials:")
        print("(Get credentials from: https://aps.autodesk.com/)")
        
        client_id = input("Client ID: ").strip()
        client_secret = input("Client Secret: ").strip()
        
        if not client_id or not client_secret:
            print("[ERROR] Invalid credentials")
            return None
        
        # Ask to save
        save = input("Save to config file for future runs? (y/n): ").strip().lower()
        if save == 'y':
            self._save_to_config(client_id, client_secret)
        
        return (client_id, client_secret)
    
    def _save_to_config(self, client_id, client_secret):
        """Save credentials to config file"""
        data = {
            "client_id": client_id,
            "client_secret": client_secret
        }
        
        try:
            with open(self.cred_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            print(f"[OK] Credentials saved to: {self.cred_file}")
            print("[WARNING] Make sure this file is in .gitignore!")
        except Exception as e:
            print(f"[ERROR] Failed to save credentials: {e}")

