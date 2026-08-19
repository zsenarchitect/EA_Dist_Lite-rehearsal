"""
KeynoteExporter Pipeline - Core Processing Logic

This module contains the main pipeline orchestration logic that was previously
in KeynoteExporter.py. It handles the complete 6-step processing pipeline.
"""

import os
import logging

# Import specialized modules from src folder
from .keynote_config import KeynoteConfig
from .keynote_parser import parse_excel_keynote_data
from .keynote_tree_visualizer import build_hierarchy, generate_html_tree
from .keynote_exporter import export_keynote_data_to_json, export_keynote_data_to_revit_txt
from .scope_excel_exporter import export_keynote_data_to_scope_excel


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_pipeline(excel_path=None, output_dir=None):
    """
    High-Level KeynoteExporter Pipeline Orchestrator
    
    This function orchestrates the complete 6-step pipeline by delegating work
    to specialized modules. It provides a clean, high-level interface.
    """
    print("=" * 80)
    print("KEYNOTE EXPORTER PIPELINE - STARTING PROCESSING")
    print("=" * 80)
    
    # Default Excel path
    if excel_path is None:
        excel_path = r"C:\Users\szhang\github\ennead-llp\EnneadTab-OS\DarkSide\exes\source code\KeynoteExporter\sample excel\_WorkingIN_PORGRESS.xlsm"
    
    # Validate Excel file exists
    if not os.path.exists(excel_path):
        logger.error(f"Excel file not found: {excel_path}")
        return

    # Determine output directory
    if output_dir:
        output_dir = os.path.abspath(output_dir)
    else:
        output_dir = os.path.dirname(excel_path)
    os.makedirs(output_dir, exist_ok=True)
    
    outputs = []

    try:
        # ========================================================================
        # STEP 1: LOAD CONFIGURATION
        # ========================================================================
        print("\n[STEP 1] LOADING CONFIGURATION")
        print("-" * 50)
        config = KeynoteConfig()
        print(f"[OK] Configuration loaded from: {config.config_path}")
        print(f"     String columns: {len(config.get_string_columns())} fields")
        print(f"     Interior scope: {len(config.get_interior_scope_columns())} fields") 
        print(f"     Exterior scope: {len(config.get_exterior_scope_columns())} fields")
        
        # ========================================================================
        # STEP 2: PARSE EXCEL DATA
        # ========================================================================
        print("\n[STEP 2] PARSING EXCEL DATA")
        print("-" * 50)
        print(f"Reading Excel file: {excel_path}")
        keynote_data = parse_excel_keynote_data(excel_path, config)
        print(f"[OK] Successfully parsed {len(keynote_data)} keynote entries")
        print(f"     Data shape: {len(keynote_data)} entries with full field mapping")
        
        # ========================================================================
        # STEP 3: BUILD HIERARCHY TREE
        # ========================================================================
        print("\n[STEP 3] BUILDING HIERARCHY TREE")
        print("-" * 50)
        print("Organizing data into Division -> Section -> Entry structure")
        tree = build_hierarchy(keynote_data)
        print(f"[OK] Hierarchy built with natural numerical sorting")
        print(f"     Divisions: {len(tree)} categories")
        total_sections = sum(len(sections) for sections in tree.values())
        print(f"     Sections: {total_sections} groups")
        total_entries = sum(len(entries) for sections in tree.values() for entries in sections.values())
        print(f"     Entries: {total_entries} keynote items")
        
        # ========================================================================
        # STEP 4: GENERATE HTML VISUALIZATION
        # ========================================================================
        print("\n[STEP 4] GENERATING HTML VISUALIZATION")
        print("-" * 50)
        print("Creating interactive HTML tree visualization")
        base_name = os.path.splitext(os.path.basename(excel_path))[0]
        html_path = os.path.join(output_dir, f"{base_name}_hierarchy.html")
        print(f"     Output: {html_path}")
        generate_html_tree(tree, keynote_data, html_path)
        outputs.append(html_path)
        print(f"[OK] HTML visualization generated successfully")
        print(f"     Features: Search, expand/collapse, context menu, sticky toolbar")
        print(f"     JavaScript: Copied to output directory")
        
        # ========================================================================
        # STEP 5: EXPORT JSON DATA
        # ========================================================================
        print("\n[STEP 5] EXPORTING JSON DATA")
        print("-" * 50)
        print("Exporting structured JSON data")
        json_path = os.path.join(output_dir, f"{base_name}_export.json")
        print(f"     Output: {json_path}")
        export_keynote_data_to_json(keynote_data, json_path)
        outputs.append(json_path)
        print(f"[OK] JSON export completed")
        print(f"     Entries: {len(keynote_data)} keynote items with full field mapping")
        
        # ========================================================================
        # STEP 6: EXPORT REVIT KEYNOTE FILE
        # ========================================================================
        print("\n[STEP 6] EXPORTING REVIT KEYNOTE FILE")
        print("-" * 50)
        print("Generating Revit keynote file (UTF-16 LE, tab-separated)")
        txt_path = os.path.join(output_dir, f"{base_name}_keynotes.txt")
        print(f"     Output: {txt_path}")
        export_keynote_data_to_revit_txt(keynote_data, txt_path)
        outputs.append(txt_path)
        print(f"[OK] Revit keynote file generated successfully")
        print(f"     Format: Keynote | Description | Parent Keynote")
        print(f"     Ready for direct import into Revit")
        
        # ========================================================================
        # STEP 7: EXPORTING SCOPE-BASED EXCEL FILES
        # ========================================================================
        print("\n[STEP 7] EXPORTING SCOPE-BASED EXCEL FILES")
        print("-" * 50)
        print("Creating separate Exterior and Interior Excel files based on scope tags")
        print(f"     Output Directory: {output_dir}")
        exterior_path, interior_path = export_keynote_data_to_scope_excel(
            keynote_data, config, output_dir, base_name
        )
        if exterior_path:
            outputs.append(exterior_path)
            print(f"[OK] Exterior scope Excel file generated: {exterior_path}")
        else:
            print("[INFO] No exterior scope entries found; exterior Excel skipped")

        if interior_path:
            outputs.append(interior_path)
            print(f"[OK] Interior scope Excel file generated: {interior_path}")
        else:
            print("[INFO] No interior scope entries found; interior Excel skipped")

        if exterior_path or interior_path:
            print(f"     Format: 3-row headers with scope-based grouping")
            print(f"     Ready for Revit schedule linking")
        else:
            print("     No scope-based Excel files were required for this data set.")
        
        # ========================================================================
        # FINAL SUMMARY
        # ========================================================================
        print("\n" + "=" * 80)
        print("KEYNOTE EXPORTER PIPELINE COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        print(f"Processed: {len(keynote_data)} keynote entries")
        print(f"Output Directory: {output_dir}")
        print("Generated Files:")
        print(f"  * {base_name}_hierarchy.html - Interactive visualization")
        print(f"  * {base_name}_export.json - Structured data")
        print(f"  * {base_name}_keynotes.txt - Revit keynote file")
        js_path = os.path.join(output_dir, "keynote_viewer.js")
        if os.path.exists(js_path):
            outputs.append(js_path)
        print(f"  * keynote_viewer.js - JavaScript functionality")
        if exterior_path:
            print(f"  * {os.path.basename(exterior_path)} - Exterior scope Excel file")
        if interior_path:
            print(f"  * {os.path.basename(interior_path)} - Interior scope Excel file")
        print("\nAll outputs ready for use!")
        print("=" * 80)
        
        # Final verification to make sure every reported output exists
        missing_files = [path for path in outputs if not os.path.exists(path)]
        if missing_files:
            raise FileNotFoundError(
                "The following expected output files were not created: "
                + ", ".join(missing_files)
            )

        return {"output_dir": output_dir, "files": outputs}

    except Exception:
        logger.exception("Error while running KeynoteExporter pipeline")
        raise
