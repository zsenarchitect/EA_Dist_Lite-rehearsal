"""
KeynoteData Module for KeynoteExporter PrincetonSpecial

This module defines the KeynoteData class for structured PrincetonSpecial keynote data representation.
"""

import pandas as pd
import logging
from typing import Dict, Any
from .keynote_config import KeynoteConfig

logger = logging.getLogger(__name__)


class KeynoteData:
    """
    Dynamic class representing a single PrincetonSpecial keynote entry from Excel data.
    Fields are determined by the configuration file.
    """
    
    def __init__(self, data: Dict[str, Any], config: KeynoteConfig):
        """
        Initialize KeynoteData from a dictionary of values and configuration.
        
        Args:
            data (Dict[str, Any]): Dictionary of column values
            config (KeynoteConfig): Configuration object
        """
        self.config = config
        
        # Store all data in a dictionary for dynamic access
        self._data = {}
        
        # Process string columns
        for col in config.get_string_columns():
            value = data.get(col, "")
            if pd.isna(value):
                value = ""
            self._data[col] = str(value).replace('nan', '')
        
        # Process boolean columns (interior + exterior scope)
        for col in config.get_all_boolean_columns():
            value = data.get(col, "")
            self._data[col] = self._convert_to_boolean(value, config)
    
    def _convert_to_boolean(self, value: Any, config: KeynoteConfig) -> bool:
        """Convert a value to boolean based on simplified rules: non-empty = True, empty = False."""
        if pd.isna(value):
            return False
        
        str_value = str(value).strip()
        
        # Simple rule: any non-empty content = True, empty content = False
        return bool(str_value)
    
    def get_string_field(self, field_name: str) -> str:
        """Get a string field value."""
        return self._data.get(field_name, "")
    
    def get_boolean_field(self, field_name: str) -> bool:
        """Get a boolean field value."""
        return self._data.get(field_name, False)
    
    def get_interior_scope_fields(self) -> Dict[str, bool]:
        """Get all interior scope fields as a dictionary."""
        return {col: self._data.get(col, False) for col in self.config.get_interior_scope_columns()}
    
    def get_exterior_scope_fields(self) -> Dict[str, bool]:
        """Get all exterior scope fields as a dictionary."""
        return {col: self._data.get(col, False) for col in self.config.get_exterior_scope_columns()}
    
    def get_all_data(self) -> Dict[str, Any]:
        """Get all data as a dictionary."""
        return self._data.copy()
    
    def __str__(self) -> str:
        """String representation of the KeynoteData object."""
        result = []
        result.append(f"KeynoteData(")
        
        # Add string fields
        for col in self.config.get_string_columns():
            if col in self._data:
                result.append(f"  {col}: '{self._data[col]}'")
        
        # Add boolean fields
        for col in self.config.get_all_boolean_columns():
            if col in self._data:
                result.append(f"  {col}: {self._data[col]}")
        
        result.append(")")
        return "\n".join(result)
    
    def __repr__(self) -> str:
        """Detailed representation of the KeynoteData object."""
        return self.__str__()
