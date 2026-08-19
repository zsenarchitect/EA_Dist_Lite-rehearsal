"""
RevitSlave4 Revit Logic Package
================================

This package contains all scripts that run INSIDE Revit (IronPython 2.7).

Structure:
- entry_script.py: Main entry point launched by pyRevit CLI
- health_metric/: Modular HealthMetric package (standalone, no EnneadTab deps)

DO NOT import this package in CPython code - it's IronPython only!
"""

__version__ = "3.0.0"

