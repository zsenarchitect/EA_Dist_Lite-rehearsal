"""
PyInstaller hook for win32com modules
=====================================

This hook ensures that all win32com modules and their dependencies
are properly collected when building executables.

Author: EnneadTab Team
"""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import os

# Collect all win32com submodules
hiddenimports = collect_submodules('win32com')

# Also collect pythoncom and pywintypes submodules
hiddenimports += collect_submodules('pythoncom')
hiddenimports += collect_submodules('pywintypes')

# Add specific win32 modules that are commonly used
win32_modules = [
    'win32api', 'win32con', 'win32file', 'win32security', 'win32service',
    'win32serviceutil', 'win32ts', 'win32evtlog', 'win32evtlogutil',
    'win32clipboard', 'win32net', 'win32netcon', 'win32pdh', 'win32pipe',
    'win32process', 'win32profile', 'win32ras', 'win32reg', 'win32rcparser',
    'win32timezone', 'win32trace', 'win32wnet'
]

for module in win32_modules:
    try:
        hiddenimports += collect_submodules(module)
    except ImportError:
        # Some modules might not be available on all systems
        pass

# Collect data files for win32com (COM servers, etc.)
datas = collect_data_files('win32com', include_py_files=False)

# Also collect pythoncom and pywintypes data files
datas += collect_data_files('pythoncom', include_py_files=False)
datas += collect_data_files('pywintypes', include_py_files=False)
