# How to Prevent PyRevit Cache Issues

## Problem Overview

PyRevit caches information about installed Revit versions, including build numbers and installation paths. When Revit is updated (especially in-place updates that change the build number but keep the same version year), PyRevit's cache can become stale, leading to:

- Incorrect build detection (e.g., showing February 2025 build instead of September 2025 build)
- `pyrevit run` command failures
- RevitSlave unable to launch correct Revit versions
- Attachment issues with pyRevit extensions

## Root Cause

PyRevit stores cached data in multiple locations:
- `%APPDATA%\pyRevit\` - User-level cache files
- `%PROGRAMDATA%\pyRevit\Cache\` - System-level cache (if using admin installer)
- Internal cache used by `pyrevit revits --installed` command

Simply updating the `pyrevit-hosts.json` file is **NOT enough** because PyRevit has already cached the wrong installation data separately.

## Solution 1: Manual Cache Clearing (When Needed)

### When to Clear Cache Manually

Clear the cache whenever you:
1. Update Revit to a new build
2. Install or uninstall a Revit version
3. Experience pyrevit detection issues
4. See "incorrect build" errors in RevitSlave logs

### How to Clear Cache

**Option A: Using PyRevit CLI (Recommended)**

```powershell
# Close all Revit instances first!

# Clear all caches for all Revit versions
pyrevit caches clear --all

# Or clear for specific version
pyrevit caches clear 2025
```

**Option B: Using the Standalone Script**

```powershell
# Navigate to the RevitSlave src directory
cd "C:\Users\<YourUsername>\github\ennead-llp\EnneadTab-OS\DarkSide\exes\source code\RevitSlave\src"

# Run the step0 cache cleanup module
python step0_cache_cleanup.py

# Or force clear even if Revit is running (not recommended)
python step0_cache_cleanup.py --force
```

**Option C: Build and Run the Executable**

The `step0_cache_cleanup.py` script can be compiled into a standalone `.exe` for easier distribution to users who don't have Python installed.

### After Clearing Cache

1. Verify Revit is closed
2. Run: `pyrevit revits --installed` to force re-detection
3. Start Revit
4. PyRevit will rebuild its cache with correct information

## Solution 2: Automated Prevention (Built into RevitSlave)

RevitSlave now **automatically clears the pyRevit cache** at startup before detecting Revit installations. This ensures:

- Fresh detection every time RevitSlave runs
- No stale build information
- Reliable Revit version detection

### Implementation Details

The cache clearing is integrated into `step1_config.py`:

```python
# In milestone_step1_setup()
print_section("PYREVIT CACHE CLEANUP")
_clear_pyrevit_cache()  # <-- Automatic cache clear

print_section("REVIT DETECTION AND PYREVIT ATTACHMENT")
installed_versions = _detect_installed_revit_versions()
```

This means **you don't need to manually clear cache before running RevitSlave** - it's done automatically.

## Solution 3: Best Practices for the Future

### For Developers

1. **Always clear cache after Revit updates**
   ```powershell
   pyrevit caches clear --all
   ```

2. **Use the automated cache clearing in all batch scripts**
   - Import and call `clear_pyrevit_cache()` from `step0_cache_cleanup` module at the start of any script that uses pyrevit
   ```python
   from src.step0_cache_cleanup import clear_pyrevit_cache
   clear_pyrevit_cache(force=True, verbose=False)
   ```
   
3. **Check actual build numbers, not just versions**
   ```powershell
   # Don't just check "2025" - verify the build!
   pyrevit revits --installed
   ```

4. **When in doubt, clear and re-detect**
   ```powershell
   pyrevit caches clear --all
   pyrevit revits killall
   pyrevit revits --installed
   ```

### For Users

1. **After Revit updates**: 
   - Close Revit
   - Run `ClearPyRevitCache.exe` (or the Python script)
   - Restart Revit

2. **If pyRevit buttons are missing or not working**:
   - Clear cache using the methods above
   - Re-attach pyRevit: `pyrevit attach master default --installed`
   - Restart Revit

3. **If RevitSlave fails to launch**:
   - Check the logs for "wrong build" messages
   - RevitSlave should auto-clear cache, but you can manually run the cleaner if needed
   - Report the issue if auto-clearing didn't work

## Technical Details

### What Gets Cached?

PyRevit caches:
- Revit installation paths
- Build numbers and dates
- Assembly versions
- addin manifest locations
- Extension attachment information

### Cache File Locations

```
%APPDATA%\pyRevit\
├── 2024\
│   ├── *.cache
│   └── *.tmp
├── 2025\
│   ├── *.cache
│   └── *.tmp
└── pyRevit_config.ini

%PROGRAMDATA%\pyRevit\Cache\
└── [Various cache files]
```

### How Cache Clearing Works

The `pyrevit caches clear --all` command:
1. Closes all pyRevit-related processes
2. Deletes cache files for all Revit versions
3. Clears temporary files
4. Forces fresh detection on next Revit launch

## Troubleshooting

### "pyrevit command not found"

PyRevit CLI is not in your PATH. Either:
- Reinstall pyRevit with CLI support
- Use the Python script instead: `python ClearPyRevitCache.py`

### "Access Denied" errors

- Make sure Revit is fully closed
- Run as Administrator if needed
- Check that no Revit processes are running in Task Manager

### Cache clear succeeded but still seeing wrong build

1. Check if Revit was truly updated:
   ```powershell
   # Check actual Revit executable version
   Get-Item "C:\Program Files\Autodesk\Revit 2025\Revit.exe" | Select-Object VersionInfo
   ```

2. Force pyRevit to re-scan:
   ```powershell
   pyrevit revits killall
   pyrevit revits --installed
   ```

3. Try clearing Windows file cache:
   - Restart your computer (this clears Windows' own file caches)

### RevitSlave still fails after cache clear

1. Check the `step1_config.py` logs to see if cache clear actually ran
2. Verify the detected versions match your installed Revit
3. Try manual cache clear before running RevitSlave
4. Report the issue with full logs

## Quick Reference Commands

```powershell
# Clear all pyRevit cache
pyrevit caches clear --all

# Force re-detection
pyrevit revits --installed

# Re-attach to all installed
pyrevit attach master default --installed

# Check current pyRevit version
pyrevit --version

# Kill all Revit processes
pyrevit revits killall

# Full reset sequence
pyrevit caches clear --all
pyrevit revits killall  
pyrevit attach master default --installed
pyrevit revits --installed
```

## Related Files

- `DarkSide/exes/source code/RevitSlave/src/step0_cache_cleanup.py` - Cache cleanup module (Step 0)
- `DarkSide/exes/source code/RevitSlave/src/step1_config.py` - RevitSlave config with auto-clear (Step 1)
- This documentation: `HOW-TO-PREVENT-PYREVIT-CACHE-ISSUES.md`

## Version History

- **2025-10-07**: Created automated cache clearing solution
  - Added `step0_cache_cleanup.py` module (follows RevitSlave naming convention)
  - Integrated cache clearing into RevitSlave startup as Step 0
  - Documented prevention strategies
  - Supports verbose mode for detailed output vs. silent mode for automated use

---

**Remember**: When in doubt, clear the cache! It's a quick, safe operation that prevents hours of debugging.

