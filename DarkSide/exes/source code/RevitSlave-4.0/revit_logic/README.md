# RevitSlave4 Revit Logic

This folder contains all scripts that run **INSIDE Revit** using IronPython 2.7.

## 🎯 Purpose

These scripts are executed by pyRevit CLI and run within the Revit process. They bridge the gap between the orchestrator (CPython 3.x) and Revit (IronPython 2.7).

## 📁 Structure

```
revit_logic/
├── entry_script.py          # Main entry point (runs inside Revit)
├── health_metric/           # Health metric checks (standalone)
│   ├── __init__.py         # HealthMetric main class
│   ├── project_checks.py   # Project info checks
│   ├── linked_files_checks.py
│   ├── elements_checks.py
│   ├── views_checks.py
│   ├── templates_checks.py
│   ├── cad_checks.py
│   ├── families_checks.py
│   ├── graphical_checks.py
│   ├── groups_checks.py
│   ├── reference_checks.py
│   ├── materials_checks.py
│   ├── warnings_checks.py
│   ├── file_checks.py
│   └── regions_checks.py
└── README.md               # This file
```

## 🔄 Process Flow

### 1. Orchestrator (CPython) Side
```python
# core/job_executor.py
cmd = [
    'pyrevit', 'run',
    'revit_logic/entry_script.py',    # This script!
    'assets/empty_doc_2025.rvt',       # Version-specific empty doc
    '--revit=2025',                    # Revit version
    '--purge',
    '--import=KingDuck.lib'
]
subprocess.Popen(cmd)
```

### 2. Entry Script (IronPython) Side
```python
# revit_logic/entry_script.py
def main():
    # 1. Load job payload
    job = load_json('current_job_payload.json')
    
    # 2. Open cloud model using GUIDs
    doc = open_cloud_model(
        model_guid=job['model_guid'],
        project_guid=job['project_guid']
    )
    
    # 3. Run health metrics
    from health_metric import HealthMetric
    metric = HealthMetric(doc)
    report = metric.check()
    
    # 4. Write results
    write_results('results/result_{job_id}.json', report)
    
    # 5. Update status
    write_status('completed')
```

## 📊 HealthMetric Integration

### Pattern from remote_revit_server

The entry script follows the proven pattern from `remote_revit_server_script.py`:

```python
def run_health_metrics(doc, job_payload):
    """
    Run HealthMetric with automatic fallback to mock data
    """
    try:
        from health_metric import HealthMetric
        metric = HealthMetric(doc)
        report = metric.check()
        return report, None
    except Exception as ex:
        # Automatic fallback - never crash the job
        return mock_data, error_message
```

### Why This Pattern?

- **Resilient**: Falls back to mock data if HealthMetric fails
- **Non-blocking**: Job completes even if health checks crash
- **Standalone**: No EnneadTab dependencies (faster, cleaner)
- **Proven**: Used successfully in remote_revit_server

## 🎨 Key Features

### 1. Cloud Model Opening via GUIDs ✅
```python
cloud_path = ModelPathUtils.ConvertCloudGUIDsToCloudPath(
    project_guid,  # From job payload
    model_guid     # From job payload
)

doc = app.OpenDocumentFile(cloud_path, open_options)
```

**No file paths needed!** - Pure GUID-based opening

### 2. Status Tracking ✅
```python
_write_status("opening", "Opening cloud model...")
_write_status("analyzing", "Running health metrics...")
_write_status("completed", "Job finished")
```

Enables real-time monitoring by orchestrator.

### 3. Heartbeat Updates ✅
```python
_write_heartbeat("Downloading model...", progress=30)
_write_heartbeat("Running health checks...", progress=80)
```

Enhanced monitoring with progress tracking.

### 4. Comprehensive Error Handling ✅
```python
try:
    doc = open_cloud_model(job_payload)
    report = run_health_metrics(doc, job_payload)
    write_results(job_payload, report)
except Exception as e:
    _write_status("failed", str(e), traceback.format_exc())
    raise  # Re-raise so pyrevit knows script failed
```

All errors captured and logged for debugging.

## 📝 Job Payload Structure

The entry script expects this payload structure:

```json
{
  "job_id": "job_20251023_155300_1",
  "hub_name": "Ennead Architects LLP",
  "project_name": "2001.00_UCSC Thimann IIRB",
  "file_name": "EA_UCSC IIRB_A_Building.rvt",
  "model_guid": "44235c04-e313-4da2-ba71-c2657290dc75",
  "project_guid": "74c374d6-157e-46f7-94d6-1372a337b03c",
  "revit_version": 2025,
  "file_size_bytes": 548576256,
  "project_id": "b.ccf84983-...",
  "file_id": "urn:adsk.wipprod:...",
  "timestamp": "2025-10-23T15:53:00"
}
```

**Critical Fields:**
- `model_guid`: Required for cloud opening
- `project_guid`: Required for cloud opening
- `revit_version`: Used to select correct empty doc

## 📤 Result Structure

The entry script writes this result structure:

```json
{
  "job_id": "job_20251023_155300_1",
  "hub_name": "Ennead Architects LLP",
  "project_name": "2001.00_UCSC Thimann IIRB",
  "file_name": "EA_UCSC IIRB_A_Building.rvt",
  "model_guid": "44235c04-e313-4da2-ba71-c2657290dc75",
  "project_guid": "74c374d6-157e-46f7-94d6-1372a337b03c",
  "revit_version": 2025,
  "timestamp": "2025-10-23T15:58:42",
  "health_report": {
    "version": "v2",
    "timestamp": "2025-10-23T15:58:30",
    "document_title": "EA_UCSC IIRB_A_Building",
    "checks": {
      "project_info": {...},
      "linked_files": {...},
      "critical_elements": {...},
      ...
    }
  },
  "health_metric_error": null,
  "status": "completed"
}
```

## 🔐 Dependencies

### IronPython 2.7 (Revit Environment)
- Autodesk.Revit.DB
- Standard Python 2.7 modules (json, os, time, traceback, datetime)

### No External Dependencies
- ❌ NO EnneadTab
- ❌ NO proDUCKtion  
- ❌ NO requests
- ✅ STANDALONE

This ensures fast imports and no version conflicts.

## 🚀 Testing

To test the entry script:

1. **Prepare test payload:**
```json
{
  "job_id": "test_001",
  "model_guid": "...",
  "project_guid": "...",
  "revit_version": 2025,
  ...
}
```

2. **Launch via pyrevit:**
```bash
pyrevit run revit_logic/entry_script.py empty_doc_2025.rvt --revit=2025
```

3. **Check results:**
- `current_job_status.json` - Real-time status
- `heartbeat.json` - Progress updates
- `results/result_test_001.json` - Final results

## 📚 Learn From

This implementation learns from:

1. **remote_revit_server_script.py**
   - HealthMetric integration with fallback
   - Status tracking pattern
   - Error handling strategy

2. **AutoExporter revit_server_entry_script.py**
   - Script structure
   - pyRevit CLI integration
   - Job payload pattern

## 🔧 Maintenance

### Adding New Health Checks

To add a new health check:

1. Create new module in `health_metric/`:
```python
# health_metric/my_new_checks.py
def check_my_feature(doc):
    return {
        "count": 42,
        "status": "OK"
    }
```

2. Import in `health_metric/__init__.py`:
```python
from . import my_new_checks

# In HealthMetric.check():
self.report["checks"]["my_feature"] = my_new_checks.check_my_feature(self.doc)
```

3. No changes needed to entry_script.py!

### Modifying Entry Script

**Keep these principles:**
- ✅ Always write status updates
- ✅ Never import EnneadTab
- ✅ Handle all exceptions gracefully
- ✅ Use GUID-based cloud opening
- ✅ Write structured JSON results

## 🐛 Debugging

### Common Issues

**Issue:** Script doesn't run
- Check: Is pyrevit in PATH?
- Check: Is entry_script.py path correct?
- Check: Does empty doc exist?

**Issue:** Cloud model won't open
- Check: Are GUIDs valid?
- Check: Does user have access to project?
- Check: Is Revit version correct?

**Issue:** HealthMetric fails
- Check: Script will fall back to mock data
- Check: Error logged in status file
- Job will still complete!

## 📄 Related Files

- `../core/job_executor.py` - Launches this script
- `../assets/empty_doc_*.rvt` - Empty docs for version selection
- `../orchestration/orchestrator.py` - Main workflow controller

---

**Last Updated:** October 23, 2025  
**Author:** EnneadTab Development Team  
**Version:** 3.0.0

