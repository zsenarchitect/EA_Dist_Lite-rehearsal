"""
KeynoteExporter Source Package

This package contains all the specialized modules for the KeynoteExporter system.
"""

# Single source of truth for the app version. Surfaced in the GUI title bar and
# re-exported by the entry point. Bump on every shipped change.
__version__ = "1.2.0"
__description__ = "EnneadTab Keynote Exporter - Excel keynote database to Revit/HTML/JSON"

from .keynote_config import KeynoteConfig
from .keynote_data import KeynoteData
from .keynote_parser import parse_excel_keynote_data
from .keynote_tree_visualizer import build_hierarchy, generate_html_tree
from .keynote_exporter import export_keynote_data_to_json, export_keynote_data_to_revit_txt

__all__ = [
    'KeynoteConfig',
    'KeynoteData', 
    'parse_excel_keynote_data',
    'build_hierarchy',
    'generate_html_tree',
    'export_keynote_data_to_json',
    'export_keynote_data_to_revit_txt'
]
