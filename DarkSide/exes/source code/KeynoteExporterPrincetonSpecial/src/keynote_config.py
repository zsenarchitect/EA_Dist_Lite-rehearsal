"""
KeynoteConfig PrincetonSpecial - Configuration Management Module

This module handles all configuration loading and management for the KeynoteExporter PrincetonSpecial system.
It loads YAML configuration files and provides access to column mappings and settings tailored for PrincetonSpecial.
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class KeynoteConfig:
    """Configuration loader for KeynoteExporter PrincetonSpecial settings."""
    
    def __init__(self, config_path: str = ""):
        """
        Initialize configuration from YAML file.
        
        Args:
            config_path (str): Path to configuration file. If empty, uses default path.
        """
        if not config_path:
            # Default config path relative to this script
            script_dir = Path(__file__).parent
            config_path = str(script_dir / "keynote_config.yaml")
        
        self.config_path = Path(config_path)
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as file:
                config = yaml.safe_load(file)
                logger.info(f"Loaded configuration from {self.config_path}")
                return config
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {self.config_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Error parsing configuration file: {e}")
            raise
    
    def get_string_columns(self) -> List[str]:
        """Get list of string column names."""
        return self.config.get('column_types', {}).get('string_columns', [])
    
    def get_interior_scope_columns(self) -> List[str]:
        """Get list of interior scope column names."""
        return self.config.get('column_types', {}).get('interior_scope_columns', [])
    
    def get_exterior_scope_columns(self) -> List[str]:
        """Get list of exterior scope column names."""
        return self.config.get('column_types', {}).get('exterior_scope_columns', [])
    
    def get_all_boolean_columns(self) -> List[str]:
        """Get all boolean column names (interior + exterior scope)."""
        return self.get_interior_scope_columns() + self.get_exterior_scope_columns()
    
    def get_excel_settings(self) -> Dict[str, Any]:
        """Get Excel parsing settings."""
        return self.config.get('excel_settings', {})
    
    def get_sheet_name(self) -> str:
        """Get the Excel sheet name to read from."""
        return self.get_excel_settings().get('sheet_name', 'Database')
