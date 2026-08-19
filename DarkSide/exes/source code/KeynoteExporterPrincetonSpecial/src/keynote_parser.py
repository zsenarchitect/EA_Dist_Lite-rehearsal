"""
KeynoteParser PrincetonSpecial - Excel Data Parsing Module

This module handles all PrincetonSpecial Excel file parsing and KeynoteData object creation.
It reads Excel files, identifies headers, and creates structured data objects for the PrincetonSpecial workflow.
"""

import pandas as pd
import logging
from typing import List, Dict, Any, Optional
from .keynote_config import KeynoteConfig
from .keynote_data import KeynoteData

logger = logging.getLogger(__name__)


def parse_excel_keynote_data(excel_path: str, config: Optional[KeynoteConfig] = None) -> List[KeynoteData]:
    """
    Parse Excel file and return list of KeynoteData objects.
    
    Args:
        excel_path: Path to Excel file
        config: KeynoteConfig instance (optional, will create default if not provided)
    
    Returns:
        List of KeynoteData objects
    """
    if config is None:
        config = KeynoteConfig()
    
    try:
        logger.info(f"Reading Excel file: {excel_path}")
        
        # Read Excel file
        df = pd.read_excel(excel_path, sheet_name=config.get_sheet_name())
        logger.info(f"Raw data shape: {df.shape}")
        
        # Find header row (look for row with expected column names)
        header_row_index = None
        expected_columns = config.get_string_columns() + config.get_all_boolean_columns()
        
        for index, row in df.iterrows():
            row_values = [str(val).strip() for val in row.values if pd.notna(val)]
            if any(col in row_values for col in expected_columns):
                header_row_index = index
                logger.info(f"Found potential header row at index {index}: {row_values}")
                break
        
        if header_row_index is None:
            raise ValueError("Could not find header row in Excel file")
        
        # Use the identified header row
        df_clean = df.iloc[header_row_index:].copy()
        df_clean.columns = df_clean.iloc[0]
        df_clean = df_clean.drop(df_clean.index[0])
        df_clean = df_clean.reset_index(drop=True)
        
        logger.info(f"Successfully read {len(df_clean)} rows from {config.get_sheet_name()} tab")
        logger.info(f"Columns found: {list(df_clean.columns)}")
        
        # Create KeynoteData instances
        keynote_instances = []
        for index, row in df_clean.iterrows():
            try:
                # Convert row to dictionary
                row_dict = row.to_dict()
                
                # Create KeynoteData instance using configuration
                keynote = KeynoteData(row_dict, config)
                keynote_instances.append(keynote)
                
            except Exception as e:
                logger.warning(f"Error parsing row {index}: {e}")
                continue
        
        logger.info(f"Successfully created {len(keynote_instances)} KeynoteData instances")
        return keynote_instances
        
    except Exception as e:
        logger.error(f"Error reading Excel file: {e}")
        raise ValueError(f"Failed to read Excel file: {e}")
