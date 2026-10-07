#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Configuration file for Monitor Area System
Single source of truth for all configuration settings
"""

from EnneadTab import SHAREPOINT
import os

# =============================================================================
# PARAMETER MAPPING (Excel ↔ Revit)
# =============================================================================
# Maps logical keys to their Excel column names and Revit parameter names
# This allows Excel to have convenient headers while Revit uses legacy parameter names

APP_EXCEL = "excel"
APP_REVIT = "revit"

DEPARTMENT_KEY = {
    APP_REVIT: "_HealthCare_Department",
    APP_EXCEL: "DEPARTMENT"
}

PROGRAM_TYPE_KEY = {
    APP_REVIT: "_HealthCare_Division",
    APP_EXCEL: "DIVISION"
}

PROGRAM_TYPE_DETAIL_KEY = {
    APP_REVIT: "_HealthCare_Room",
    APP_EXCEL: "ROOM NAME"
}

COUNT_KEY = {
    APP_EXCEL: "KEY UNIT"
}

SCALED_DGSF_KEY = {
    APP_EXCEL: "DGSF+"
}

# Parameter for storing unmatched area suggestions
UNMATCHED_SUGGESTION_PARAM = "UnMatchedSuggestion"

# Parameter for storing target DGSF from Excel
TARGET_DGSF_PARAM = "RoomDataTarget"

# =============================================================================
# EXCEL CONFIGURATION
# =============================================================================

# Excel file settings
EXCEL_FILENAME = SHAREPOINT.get_project_file("2534/2_Master File/B-70_Programming/01_Program & Analysis/EA_NYULLI Melville Program.xlsx")
EXCEL_WORKSHEET = "Hospital Program TARGET_DESIGN"
EXCEL_HEADER_ROW = 1  # Row where headers are located (1-based, as per parse_excel_data documentation)

# Primary key for Excel data parsing (use excel version)
EXCEL_PRIMARY_KEY = PROGRAM_TYPE_DETAIL_KEY[APP_EXCEL]

# Composite key settings
USE_COMPOSITE_KEY = True
COMPOSITE_KEY_SEPARATOR = " | "  # Separator between dept, division, room name
COMPOSITE_KEY_COLUMN_NAME = "COMPOSITE_KEY"  # Name of the synthetic column

# =============================================================================
# REVIT CONFIGURATION
# =============================================================================

# Area schemes to process (leave empty to process all schemes)
# Examples: 
#   ["DGSF Scheme"] - process only DGSF Scheme
#   ["DGSF Scheme", "GFA Scheme"] - process multiple schemes
#   [] - process all schemes found in document
AREA_SCHEMES_TO_PROCESS_PREFIX_KEYWORD = "DGSF Scheme" # any area scheme anme that begin with thos keywords will be processed
# example: "DGSF Scheme" will process "DGSF Scheme", "DGSF Scheme_opt1", "DGSF Scheme_opt3", etc.

# Color scheme names to update from Excel color hierarchy
# Maps hierarchy level to Revit color scheme name
COLOR_SCHEME_NAMES = {
    'department': '#Department Category',
    'division': '#Division',
    'room_name': '#RoomName'
}



# =============================================================================
# REPORT CONFIGURATION
# =============================================================================

# =============================================================================
# NYU HQ WEBAPP API (zero-data architecture)
# =============================================================================
# The NYU HQ website repo holds ZERO data: Postgres is the system of record
# and the webapp's /api/* endpoints are the only gateway. Revit syncs through
# the API -- it READS clean targets (GET /api/targets) and PUBLISHES report +
# geometry (POST /api/report, POST /api/geometry). No repo clone, no JSON
# data files, no GitHub writes from Revit.
#
# Configure via environment variables on the machine running Revit
# (all optional -- sensible production defaults are baked in):
#   NYU_HQ_API_URL        webapp origin (default:
#                         https://enneadtab.com/projects/nyu-hq, the
#                         EnneadTab-Home proxy. Home validates the Bearer
#                         desktop token and adds the identity and proxy
#                         secret NYU-HQ requires. The direct host
#                         nyu-hq.vercel.app answers 404 to requests without
#                         Home's x-proxy-secret, see NYU-HQ middleware.js.)
#   NYU_HQ_SERVICE_TOKEN  headless/CI override only. Interactive Revit
#                         sessions authenticate through the user's
#                         EnneadTab-Home sign-in instead (see home_auth.py):
#                         the first sync opens the browser for a one-time
#                         approval, then the token is cached DPAPI-protected.
#   NYU_HQ_WEBAPP_URL      dashboard URL opened in the browser after a sync
#   NYU_HQ_ACTOR           audit label for the edit log (default: revit-...)
# The service token lives on the user's machine only -- never commit it.
NYU_HQ_API_URL = os.environ.get(
    "NYU_HQ_API_URL", "https://enneadtab.com/projects/nyu-hq").strip()
NYU_HQ_SERVICE_TOKEN = os.environ.get("NYU_HQ_SERVICE_TOKEN", "").strip()
NYU_HQ_WEBAPP_URL = os.environ.get(
    "NYU_HQ_WEBAPP_URL", "https://enneadtab.com/projects/nyu-hq").strip()
NYU_HQ_ACTOR = os.environ.get("NYU_HQ_ACTOR", "").strip()

# Report settings
REPORTS_DIR = "reports"
LATEST_REPORT_FILENAME = "latest_report.html"
REPORT_TITLE = "EnneadTab - Excel Area Requirements vs Revit Actual Areas Report"
PROJECT_NAME = "NYU HQ - Monitor Area System"

# HTML table column headers (for display)
TABLE_COLUMN_HEADERS = {
    "area_detail": "Room Name",
    "department": "Department", 
    "program_type": "Division",
    "target_count": "Target Count",
    "target_dgsf": "Target DGSF",
    "actual_count": "Actual Count",
    "actual_dgsf": "Actual DGSF",
    "count_delta": "Count Delta",
    "dgsf_delta": "DGSF Delta",
    "dgsf_percentage": "DGSF %",
    "status": "Status",
    "match_quality": "Match Quality"
}

# =============================================================================
# AREA MATCHING CONFIGURATION
# =============================================================================

# Matching settings
# NOTE: Matching uses EXACT match on all 3 parameters (case-insensitive)
# Department, Program Type, and Program Type Detail must all match exactly
AREA_TOLERANCE_PERCENTAGE = 5.0

# Alert thresholds for highlighting high differences
COUNT_DELTA_ALERT_THRESHOLD = 10  # Alert if count difference is >= 10
AREA_PERCENTAGE_ALERT_THRESHOLD = 50.0  # Alert if area percentage difference is >= 50%   # 5% tolerance for area fulfillment status
