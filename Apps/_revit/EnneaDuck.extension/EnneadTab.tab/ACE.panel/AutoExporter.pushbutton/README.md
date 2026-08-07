# AutoExporter

Automated export orchestrator for Revit cloud models. Processes multiple export configurations sequentially.

## Overview

AutoExporter is a flexible orchestration system that:
- Auto-discovers all export configurations in the `configs/` folder
- Processes each config sequentially
- Opens Revit, exports files (PDF/DWG/JPG), sends notifications, and closes Revit
- Continues processing even if individual jobs fail
- Provides comprehensive logging and status tracking

## File Structure

```
AutoExporter.pushbutton/
├── configs/                              # Configuration files directory
│   └── AutoExportConfig_*.json          # Export config files (auto-discovered)
├── orchestrator.py                       # Main orchestrator (runs outside Revit - CPython)
├── run_orchestrator.bat                  # Batch launcher for task scheduler (ONLY bat file)
├── revit_auto_export_script.py           # Revit entry point (runs inside Revit - IronPython)
├── revit_export_logic.py                 # Export operations (runs inside Revit - IronPython)
├── revit_post_export_logic.py            # Post-export tasks (runs inside Revit - IronPython)
├── config_loader.py                      # Configuration loader (Python 2/3 compatible)
├── heartbeat/                            # Heartbeat logs (both orchestrator and Revit)
│   ├── orchestrator_heartbeat_*.log     # Orchestrator-level progress tracking
│   └── heartbeat_*.log                  # Revit script execution progress
├── orchestrator_logs/                    # Orchestrator execution logs (runtime)
├── current_job_payload.json             # Runtime: Current job info
└── current_job_status.json              # Runtime: Job status tracking
```

## Configuration

Each config file in `configs/` must follow this structure:

```json
{
  "project": {
    "project_name": "Project Name",
    "pim_parameter_name": "PIM_Number"
  },
  "models": {
    "Model Name": {
      "model_guid": "xxx-xxx-xxx",
      "project_guid": "xxx-xxx-xxx",
      "region": "US",
      "revit_version": "2026"
    }
  },
  "export": {
    "output_base_path": "C:\\path\\to\\export",
    "sheet_filter_parameter": "Sheet_$Issue_AutoPublish",
    "dwg_setting_name": "Export Setting Name",
    "pdf_color_parameter": "Print_In_Color",
    "subfolders": ["PDF", "DWG", "JPG"],
    "date_format": "%Y-%m-%d",
    "pdf_options": { ... },
    "jpg_options": { ... }
  },
  "email": {
    "recipients": ["email@example.com"],
    "subject_template": "Export Completed - {date}",
    "body_template": "...",
    "enable_notifications": true
  },
  "paths": {
    "lib_paths": ["C:\\path\\to\\lib"]
  },
  "heartbeat": {
    "enabled": true,
    "folder_name": "heartbeat",
    "date_format": "%Y%m%d"
  },
  "orchestrator": {
    "timeout_minutes": 30
  }
}
```

### Template Variables

Config files support template variables that are automatically replaced:
- `{username}` - Windows username
- `{userprofile}` - User profile path
- `{computername}` - Computer name

Example: `"C:\\Users\\{username}\\Documents\\Export"`

## Usage

### Manual Run

Double-click `run_orchestrator.bat` to start processing all configs.

Optional flags (pass after the batch file name):

- `--sparc` – only process configs that target SPARC (filters by filename/project metadata)

Example: `run_orchestrator.bat --sparc`

### Task Scheduler

1. Open Windows Task Scheduler
2. Create a new task
3. Set the action to run: `C:\path\to\AutoExporter.pushbutton\run_orchestrator.bat`
4. Configure schedule (e.g., daily at 2 AM)

### Monitoring

The orchestrator creates detailed logs in `orchestrator_logs/` with:
- Config discovery and validation results
- Job execution progress
- Export counts and status
- Error messages and stack traces
- Summary report with all job results

Each Revit script execution also creates heartbeat logs in `heartbeat/` with step-by-step progress:

**Two Types of Heartbeat Logs:**

1. **`orchestrator_heartbeat_YYYYMMDD.log`** - Written by orchestrator (CPython)
   - Tracks job launch, process monitoring, timeout tracking
   - Shows WHEN Revit process started and idle time
   - Critical for debugging jobs that timeout before Revit script runs
   - Includes periodic "still waiting" updates with idle time vs total time

2. **`heartbeat_YYYYMMDD.log`** - Written by Revit script (IronPython)
   - Tracks detailed progress INSIDE Revit
   - Shows model opening stages, export progress, email sending
   - Only appears AFTER Revit launches and script begins execution
   - If missing, job failed before Revit script could start

**Activity-Based Monitoring:**
The orchestrator monitors both heartbeat logs and status files. As long as either is being updated (indicating progress), the job continues. Only if BOTH are idle for 30+ minutes does timeout occur.

## Job Flow

For each config file:

1. **Pre-flight checks**: Disk space, pyRevit availability, config validation
2. **Write payload**: Creates `current_job_payload.json` with job info
3. **Launch Revit**: Opens Revit with pyRevit in zero-doc mode
4. **Open model**: Opens cloud model specified in config (detached)
5. **Export files**: Exports PDF/DWG/JPG based on sheet filter parameter
6. **Send email**: Notifies recipients with export summary
7. **Close Revit**: Cleanly closes Revit
8. **Write status**: Updates `current_job_status.json` with results
9. **Cleanup**: Kills lingering processes
10. **Cooldown**: Waits 10 seconds before next job

## Error Handling

- **Config validation**: All configs validated before any processing starts
- **Activity-based timeout**: Jobs timeout only if NO progress for 30 min (configurable)
  - Timeout resets whenever exports happen or heartbeat updates
  - Large jobs can run indefinitely as long as they're making progress
  - Only truly stuck processes (idle for 30+ min) are killed
- **Process cleanup**: Kills lingering Revit.exe/RevitWorker.exe between jobs
- **Continue on failure**: Failed jobs are logged, but processing continues
- **Status tracking**: Each job writes status file for orchestrator monitoring
- **Dual lock system**: Both batch file and orchestrator have lock files (auto-expires after 24hrs)

## Lock System

The AutoExporter uses a dual-lock system to prevent concurrent executions:

1. **Batch Lock** (`run_orchestrator.lock`)
   - Created when batch file starts
   - Prevents multiple batch instances
   - Cleaned up on exit or interruption
   - Auto-expires after 24 hours if stale

2. **Orchestrator Lock** (`orchestrator.lock`)
   - Created by Python orchestrator
   - Additional protection layer
   - Auto-expires after 24 hours if stale

If you see "ALREADY RUNNING" but know nothing is running, either:
- Wait 24 hours for auto-expiry
- Manually delete `run_orchestrator.lock` and `orchestrator.lock`

## Status File Format

`current_job_status.json` contains:

```json
{
  "job_id": "20251022_143052_ProjectName",
  "config": "AutoExportConfig_ProjectName.json",
  "status": "completed",  // or "running", "exporting", "post_export", "failed"
  "updated_at": "2025-10-22 14:30:52",
  "completed_at": "2025-10-22 14:45:23",
  "exports": {
    "pdf": 12,
    "dwg": 12,
    "jpg": 12
  },
  "error": null,  // or error message if failed
  "traceback": null  // or full Python traceback for debugging (only on failure)
}
```

**Note**: The `traceback` field provides complete stack trace information when errors occur, making debugging much easier.

## Adding New Configs

1. Copy an existing config from `configs/`
2. Rename to `AutoExportConfig_NewProject.json`
3. Update all settings for the new project:
   - Project name and model GUIDs
   - Export paths and parameters
   - Email recipients
4. Validate config structure (orchestrator will validate on startup)
5. Run orchestrator - new config will be automatically discovered

## Troubleshooting

**Orchestrator says "already running" but nothing is running:**
- Delete the `orchestrator.lock` file
- Or wait 24 hours for auto-expiry

**Job times out:**
- Check orchestrator heartbeat logs to see where it got stuck
- Review last heartbeat timestamp - if idle for 30+ min, process was truly stuck
- If job is making progress but still timing out, increase `orchestrator.timeout_minutes` in config
- Common causes:
  - Network connectivity issues downloading cloud models
  - Export paths not accessible
  - Model corruption or opening issues
  - Large models taking >30 min to download/open with no progress updates

**Config not discovered:**
- Ensure filename matches `AutoExportConfig_*.json` pattern
- Place in `configs/` folder
- Check JSON syntax is valid

**Email not sent:**
- Check `email.enable_notifications` is true
- Verify recipients list is not empty
- Check EnneadTab email service is configured

## Development

The system uses:
- **CPython 3.9** for orchestrator (runs in .venv)
- **IronPython 2.7** for Revit scripts (runs in pyRevit)
- **Python 2/3 compatible** config_loader for shared code

When modifying:
- `orchestrator.py` - CPython 3 only (runs outside Revit)
- `revit_*.py` files - IronPython 2.7 only (runs inside Revit)
- `config_loader.py` - Must be Python 2/3 compatible (used by both)

