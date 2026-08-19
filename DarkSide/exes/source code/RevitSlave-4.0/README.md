# RevitSlave4 - Model Pre-Validation

## What's New in V4?

**Key Feature:** Pre-validates models exist via APS API before launching Revit!

### The Problem RevitSlave4 Solves

**RevitSlave3 Behavior:**
```
1. Load cache (may include deleted models)
2. Launch Revit for each model (5-10 min per launch)
3. Try to open model
4. Discover model is deleted
5. Fail, waste 5-10 minutes
6. Move to next model
```

**Impact on SPARC Project (Real Example):**
- 33 models in cache
- 32 deleted ("central model is missing")  
- Time wasted: 32 × 5 min = **2.5+ hours**
- Success rate: 3% (1/33)

**RevitSlave4 Solution:**
```
1. Load cache (33 models)
2. **PRE-VALIDATE via APS API (NEW!):**
   - Check each model exists (1 sec per model)
   - 32 return 404 Not Found → SKIP
   - 1 returns 200 OK → PROCEED
   - Total time: 30-60 seconds
3. Create jobs only for 1 validated model
4. Launch Revit once (for validated model)
5. Open model (should succeed - already validated)
```

**Impact:**
- Time saved: 2.5 hours per run
- Success rate: ~100% (only process verified models)
- Run time: 10-15 minutes (vs 3+ hours)

---

## Installation

RevitSlave4 is a **separate version** from RevitSlave3. Both can coexist.

### Directory Structure:
```
DarkSide/exes/source code/
├── RevitSlave-3.0/  (unchanged - production stable)
└── RevitSlave-4.0/  (new - with pre-validation)
```

### Requirements:
- Python 3.9+ (same as V3)
- APS credentials (same as V3)
- pyRevit installed (same as V3)
- requests library (already installed)

**No new dependencies!** Uses only existing packages.

---

## Usage

### Basic Usage (SPARC Project):
```bash
cd "DarkSide\exes\source code\RevitSlave-4.0"
run_RevitSlave4_Sparc.bat
```

### Advanced Usage:
```bash
# All projects:
run_RevitSlave4.bat

# Specific project:
python RevitSlave4.py --project "2412_SPARC"

# Force cache refresh:
python RevitSlave4.py --force-refresh --project "2412_SPARC"

# Disable validation (fallback to V3):
python RevitSlave4.py --no-validate --project "2412_SPARC"

# Multiple projects:
python RevitSlave4.py --project "2412_SPARC" "2510_OTHER"
```

---

## How Pre-Validation Works

### Technical Details

**API Endpoint Used:**
```
GET https://developer.api.autodesk.com/data/v1/projects/{project_id}/items/{item_id}
```

**Response Codes:**
- `200 OK` → Model exists and accessible → **PROCESS**
- `404 Not Found` → Model deleted/moved → **SKIP**
- `403 Forbidden` → No access permissions → **SKIP**
- `401 Unauthorized` → Token expired → **REFRESH & RETRY**

**Performance:**
- ~1 second per model
- Rate limited to ~100 models/minute
- 33 models = 30-60 seconds total

**Graceful Degradation:**
- If API fails → Falls back to V3 behavior (try opening anyway)
- If >90% validation failures → Disables validation for run
- Never blocks processing due to validation issues

---

## New Component: ModelValidator

**File:** `core/model_validator.py`

**Adapted from:** [acc_sdk](https://github.com/realdanielbyrne/acc_sdk) (MIT License)

**Key Methods:**
```python
validator = ModelValidator(access_token)

# Check single model:
exists, metadata, error = validator.check_item_exists(project_id, item_id)

# Check multiple models:
valid, invalid, api_calls = validator.batch_validate(project_id, items)
```

**Attribution:** Daniel Byrne (realdanielbyrne/acc_sdk)

---

## Configuration

**File:** `config/settings.py`

### ValidationSettings Class (New):

```python
class ValidationSettings:
    ENABLED = True  # Enable/disable pre-validation
    
    SKIP_INVALID_MODELS = True  # Skip or try anyway
    FAIL_ON_API_ERROR = False  # Fallback to V3 if API fails
    
    VALIDATION_TIMEOUT_SECONDS = 10  # Per-model timeout
    RATE_LIMIT_DELAY_SECONDS = 0.6  # Respect API limits
    
    MIN_SUCCESS_RATE = 0.1  # Disable if <10% validate
    SUGGEST_REFRESH_THRESHOLD = 0.5  # Suggest --force-refresh if >50% skipped
```

**To disable validation:**
```bash
python RevitSlave4.py --no-validate
```

Or in `config/settings.py`:
```python
ValidationSettings.ENABLED = False
```

---

## Migration from RevitSlave3

### Option 1: Just Switch Batch Files (Recommended)
```bash
# Old:
run_RevitSlave3_Sparc.bat

# New:
run_RevitSlave4_Sparc.bat
```

**That's it!** Both use the same cache, same database folder.

### Option 2: Test Both Side-by-Side
```bash
# Run V3 (no validation):
cd RevitSlave-3.0
run_RevitSlave3_Sparc.bat

# Run V4 (with validation):
cd RevitSlave-4.0
run_RevitSlave4_Sparc.bat

# Compare results and runtime
```

### Rollback to V3:
```bash
# Instant rollback - just use V3:
cd RevitSlave-3.0
run_RevitSlave3_Sparc.bat
```

**No migration needed!** Both versions use same cache and output formats.

---

## What's Different from V3?

### Changed:
- ✅ Pre-validation step added (Step 2.5)
- ✅ ModelValidator class (new file)
- ✅ ValidationSettings configuration
- ✅ --no-validate flag added
- ✅ Version updated to 4.0.0

### Unchanged:
- ✅ Cache format (same)
- ✅ Job payloads (same)
- ✅ Output format (.sexyDuck same)
- ✅ Database folders (same)
- ✅ Revit entry script (same)
- ✅ Health metrics (same)
- ✅ All V3 features (templates_filters fix, APAC regions, etc.)

**RevitSlave4 = RevitSlave3 + Pre-Validation**

---

## Testing

### Test with SPARC Project:
```bash
cd "DarkSide\exes\source code\RevitSlave-4.0"
run_RevitSlave4_Sparc.bat
```

### Expected Output:
```
[PRE-VALIDATION] Step 2.5: Model Validation (RevitSlave4)
────────────────────────────────────────────────────────────────────────────────
[PRE-VALIDATION] Checking 33 models via APS API...
[1/33] SPARC_A_EA_CUNY_FF&E.rvt... ✓ Active
[2/33] SPARC_P_SE_Building.rvt... ✗ Model not found (deleted or moved)
[3/33] SPARC_S_LE_BUILDING.rvt... ✗ Model not found (deleted or moved)
...
[33/33] DA_2410_SPARC_Site.rvt... ✗ Model not found (deleted or moved)
────────────────────────────────────────────────────────────────────────────────
[VALIDATION COMPLETE]
  Time: 45.3 seconds
  Active models: 1
  Skipped models: 32
  API calls made: 33

Skipped Models:
  - SPARC_P_SE_Building.rvt: Model not found (deleted or moved)
  - SPARC_S_LE_BUILDING.rvt: Model not found (deleted or moved)
  ... and 30 more

[OK] Validation complete: 1 active, 32 skipped

[FACTORY] Step 3: Job Payload Creation
────────────────────────────────────────────────────────────────────────────────
[OK] Created 1 job payloads  ← Only 1 instead of 33!
```

### Expected Runtime:
- Validation: ~1 minute
- Revit launch + processing: ~10 minutes
- **Total: ~11 minutes (vs 3+ hours in V3)**

---

## Monitoring

### Log Files (Same locations as V3):
```
C:\Users\{username}\Documents\EnneadTab Ecosystem\Dump\RevitSlaveDatabase\
├── logs\
│   └── SCRIPT_STARTED_*.txt
├── debug\
│   └── validation_*.txt (new - validation reports)
└── task_output\
    └── 2412_SPARC\
        └── *.sexyDuck (results)
```

### Console Output:
Watch for validation step showing which models are skipped

---

## Troubleshooting

### If validation fails:
```bash
# Disable validation, use V3 behavior:
python RevitSlave4.py --no-validate --project SPARC

# Or just use V3:
cd ..\RevitSlave-3.0
run_RevitSlave3_Sparc.bat
```

### If too many models skipped:
```bash
# Refresh cache with fresh GUIDs:
python RevitSlave4.py --force-refresh --project SPARC
```

### If validation takes too long:
- Check network connection
- Check APS API status: https://health.autodesk.com/
- Use --no-validate flag

---

## Comparison: V3 vs V4

| Feature | RevitSlave3 | RevitSlave4 |
|---------|-------------|-------------|
| **Pre-validation** | ❌ No | ✅ Yes (APS API) |
| **Deleted model handling** | Launch Revit, fail | Skip immediately |
| **SPARC run time** | 3+ hours | ~10 minutes |
| **SPARC success rate** | 3% (1/33) | ~100% (1/1 validated) |
| **API calls** | ~10-20 | ~10-20 + 33 validation |
| **Time saved** | - | 2.5 hours |
| **Templates fix** | ✅ Yes | ✅ Yes (same) |
| **APAC regions** | ✅ Yes | ✅ Yes (same) |
| **Cancellation** | ✅ Yes | ✅ Yes (same) |
| **Risk** | Stable | Low (separate version) |

---

## Attribution

**Model validation logic adapted from:**
- Repository: [acc_sdk](https://github.com/realdanielbyrne/acc_sdk)
- Author: Daniel Byrne (realdanielbyrne)
- License: MIT (allows extraction and modification)
- Method: `AccDataManagementApi.get_item()`
- File: `acc_sdk/data_management.py` lines 903-952

**Research:** See `DEBUG/external_sdks/` for full analysis (2,000+ lines of documentation)

---

## Support

### Issues?
1. Try `--no-validate` flag (falls back to V3 behavior)
2. Or use RevitSlave-3.0 (always available)
3. Check `DEBUG/logs/` for validation reports

### Feature Requests?
See `DEBUG/external_sdks/REVITSLAVE4_ARCHITECTURE_PROPOSAL.md` for future enhancements

---

## Version History

**4.0.0** (November 4, 2025)
- Initial release
- Model pre-validation via APS API
- Based on RevitSlave3 with all recent fixes
- Adapted acc_sdk's get_item() method for validation

**3.0.0** (October-November 2025)
- Parent version (stable, production-tested)

---

**Status:** RevitSlave4 MVP complete  
**Testing:** Ready for SPARC project test  
**Fallback:** RevitSlave3 always available  

**Next:** Run `run_RevitSlave4_Sparc.bat` to test!

