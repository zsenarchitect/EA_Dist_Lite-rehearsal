"""
KeynoteConfig - Configuration Management Module

This module handles all configuration loading and management for the KeynoteExporter system.
It loads YAML configuration files and provides access to column mappings and settings.
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Runtime overrides allow the GUI to control how NOTES entries are marked
# without requiring users to edit the YAML file on disk.
RUNTIME_NOTES_SUFFIX_OVERRIDE: Optional[str] = None
RUNTIME_NOTES_MODE_OVERRIDE: Optional[str] = None  # "suffix" or "prefix"


def set_runtime_notes_suffix_override(value: Optional[str]) -> None:
    """Set a runtime override for the NOTES marker string (whitespace or text)."""
    global RUNTIME_NOTES_SUFFIX_OVERRIDE
    if value is not None and not isinstance(value, str):
        raise TypeError("Runtime NOTES suffix override must be a string or None.")
    RUNTIME_NOTES_SUFFIX_OVERRIDE = value


def set_runtime_notes_mode_override(mode: Optional[str]) -> None:
    """Set a runtime override for how the NOTES marker is applied ('suffix' or 'prefix')."""
    global RUNTIME_NOTES_MODE_OVERRIDE
    if mode is not None:
        mode = mode.lower()
        if mode not in ("suffix", "prefix"):
            raise ValueError("Runtime NOTES mode override must be 'suffix', 'prefix', or None.")
    RUNTIME_NOTES_MODE_OVERRIDE = mode


class KeynoteConfig:
    """Configuration loader for KeynoteExporter settings."""
    
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
        """Get Excel parsing settings.

        Accepts either the ``excel`` (current YAML) or legacy ``excel_settings``
        top-level key, so the block is actually honored regardless of which name
        the config file uses. Previously only ``excel_settings`` was read while the
        YAML defined ``excel:``, silently falling back to defaults.
        """
        return self.config.get('excel') or self.config.get('excel_settings') or {}
    
    def get_sheet_name(self) -> str:
        """Get the Excel sheet name to read from."""
        return self.get_excel_settings().get('sheet_name', 'Database')

    def get_notes_format_suffix(self) -> str:
        """Get the marker appended to keynote key when FORMAT is NOTES (for Revit schedule filters)."""
        # Runtime override (e.g. from GUI) takes precedence so users can change this without editing YAML.
        if isinstance(RUNTIME_NOTES_SUFFIX_OVERRIDE, str) and len(RUNTIME_NOTES_SUFFIX_OVERRIDE) > 0:
            return RUNTIME_NOTES_SUFFIX_OVERRIDE
        # Default to zero-width space U+200B when not configured explicitly.
        char = self.config.get('revit_keynote', {}).get('notes_format_suffix', '\u200b')
        return char if isinstance(char, str) and len(char) > 0 else '\u200b'

    def get_notes_format_mode(self) -> str:
        """
        Get how the NOTES marker is applied to the keynote number.

        Returns:
            "suffix" (default) or "prefix".
        """
        # Runtime override (e.g. from GUI) takes precedence.
        if isinstance(RUNTIME_NOTES_MODE_OVERRIDE, str) and RUNTIME_NOTES_MODE_OVERRIDE.lower() in ("suffix", "prefix"):
            return RUNTIME_NOTES_MODE_OVERRIDE.lower()
        mode = (
            self.config.get("revit_keynote", {})
            .get("notes_format_mode", "suffix")
        )
        return mode if mode in ("suffix", "prefix") else "suffix"
