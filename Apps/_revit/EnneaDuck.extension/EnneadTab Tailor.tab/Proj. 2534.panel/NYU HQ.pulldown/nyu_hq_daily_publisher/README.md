# NYU HQ Daily Publisher

Automated publisher for NYU Long Island HQ Revit models via Autodesk Platform Services (APS) Data Management API.

## Features

- **Batch Publishing**: Publishes multiple models in a single API call for efficiency
- **Dual Authentication**: Supports both 2-legged (client credentials + impersonation) and 3-legged (user authorization) OAuth
- **Link Preservation**: Optional publishing with links intact for coordinated multi-model projects
- **Auto ID Resolution**: Automatically resolves missing item lineage IDs by file name
- **Flexible Scheduling**: Can be triggered manually or via scheduler

## Configuration

Edit `configs/config.json`:

```json
{
  "project_name": "2534_NYUL Long Island HQ",
  "project_id": "b.4456b0ff-5748-4a86-a35f-3a0e1a257a1e",
  "publish_with_links": false,
  "items": [
    {
      "name": "2534_A_EA_NYU HQ_Shell.rvt",
      "id": "urn:adsk.wipprod:dm.lineage:...",
      "enabled": true
    },
    {
      "name": "2534_A_EA_NYU HQ_Site.rvt",
      "id": "urn:adsk.wipprod:dm.lineage:...",
      "enabled": true
    }
  ],
  "impersonate_user_email": "sen.zhang@ennead.com"
}
```

### Configuration Options

#### `publish_with_links` (boolean) - Now with Smart Fallback! 🎯

**NEW BEHAVIOR (v2.1)**: The publisher now uses a **smart fallback strategy**:

1. **Always tries WITH links first** (`C4RPublishWithLinks`)
   - Best for model coordination
   - Preserves links between Shell and Site models
   
2. **Automatically falls back to WITHOUT links** if first attempt fails (`C4RPublishWithoutLinks`)
   - Handles regions/hubs where PublishWithLinks isn't supported
   - Ensures publish succeeds even if links aren't supported
   
3. **Skips fallback only for authentication errors**
   - Auth issues (401/403) need to be fixed, not retried

**What this means**:
- ✅ You get the **best possible outcome** automatically
- ✅ No need to worry about region/hub support
- ✅ Models will coordinate if possible, publish anyway if not
- ✅ Clear logging shows which strategy succeeded

**The `publish_with_links` setting is kept for backward compatibility but the smart fallback runs regardless.**

**Example Log Output**:
```
Attempting publish WITH links (C4RPublishWithLinks)...
✅ Successfully published WITH links - CommandId=abc123
```

Or if fallback is needed:
```
Attempting publish WITH links (C4RPublishWithLinks)...
⚠️  Publish with links failed (HTTP 400): Extension not supported
Retrying WITHOUT links (C4RPublishWithoutLinks) as fallback...
✅ Successfully published WITHOUT links (fallback) - CommandId=def456
```

#### `items` Array

Each item represents a Revit model to publish:

- **`name`**: File name (must match exactly)
- **`id`**: Item lineage URN (auto-resolved if missing)
- **`enabled`**: Whether to include in daily publish

#### `impersonate_user_email`

Required for 2-legged authentication. The email of the user to impersonate when publishing.

## Usage

### Manual Publish

```bash
# Publish all enabled items
python run_publish.py

# Publish specific files
python run_publish.py --files "2534_A_EA_NYU HQ_Shell.rvt" "2534_A_EA_NYU HQ_Site.rvt"

# Batch mode (less verbose, for scheduler)
python run_publish.py --batch
```

### Batch File (Windows)

```cmd
publish_daily.bat
```

### Resolve Missing IDs

If item IDs are missing or outdated:

```bash
python resolve_ids.py
```

This will search the project for files by name and update `config.json` with their lineage IDs.

## How Batch Publishing Works

### Previous Implementation (One-by-One)

```python
for each model:
    publish_resources(project_id, [single_model_id])
    # Result: 2 API calls for Shell + Site
```

**Issues:**
- More API calls = more failure points
- Slower execution (sequential)
- Not atomic (one could succeed, other could fail)

### Current Implementation (Batch)

```python
# Collect all enabled model IDs
all_model_ids = [shell_id, site_id]

# Publish in single API call
publish_resources(project_id, all_model_ids)
# Result: 1 API call for Shell + Site
```

**Benefits:**
- ✅ Fewer API calls = better reliability
- ✅ Faster execution
- ✅ Atomic operation (all succeed or all fail together)
- ✅ Better for linked models

## Authentication

### 2-Legged OAuth (Recommended for Automation)

Uses client credentials with user impersonation:

1. Create `configs/credentials.json`:
   ```json
   {
     "client_id": "your_client_id",
     "client_secret": "your_client_secret"
   }
   ```

2. Set impersonation in `config.json`:
   ```json
   {
     "impersonate_user_email": "user@ennead.com"
   }
   ```

Alternatively, set environment variables:
```bash
set APS_CLIENT_ID=your_client_id
set APS_CLIENT_SECRET=your_client_secret
set APS_IMPERSONATE_EMAIL=user@ennead.com
```

### 3-Legged OAuth (Fallback)

For interactive use with user authorization:

```bash
python login_3legged.py
```

This will open a browser for authorization and save the token.

## API Reference

### Endpoint

```
POST https://developer.api.autodesk.com/data/v1/projects/{project_id}/commands
```

### Payload

```json
{
  "jsonapi": {"version": "1.0"},
  "data": {
    "type": "commands",
    "attributes": {
      "extension": {
        "type": "commands:autodesk.bim360:C4RPublishWithoutLinks",
        "version": "1.0.0"
      }
    },
    "relationships": {
      "resources": {
        "data": [
          {"type": "items", "id": "urn:adsk.wipprod:dm.lineage:..."},
          {"type": "items", "id": "urn:adsk.wipprod:dm.lineage:..."}
        ]
      }
    }
  }
}
```

### Extension Types

| Extension Type | Description | Use Case |
|---|---|---|
| `commands:autodesk.bim360:C4RPublishWithoutLinks` | Publish without links | Default, standalone models |
| `commands:autodesk.bim360:C4RPublishWithLinks` | Publish with links preserved | Coordinated multi-model projects |

## Troubleshooting

### "Missing config or id" Error

Run the ID resolver:
```bash
python resolve_ids.py
```

### Authentication Failures

1. Check credentials in `configs/credentials.json` or environment variables
2. Verify impersonation email has access to the project
3. Try 3-legged authentication as fallback

### Publish Fails with HTTP 401

- 2-legged token expired or invalid
- User being impersonated doesn't have publish permissions
- Try 3-legged auth: `python login_3legged.py`

### Models Not Coordinating in ACC

If Shell and Site models should be coordinated but aren't:
1. Set `"publish_with_links": true` in `config.json`
2. Verify models actually have links between them in the source Revit files
3. Re-publish with the new setting

## Daily Scheduling

To integrate with the main EnneadTab scheduler (`DarkSide/publish/_schedule_publish.py`), add this publish script to the scheduler's workflow.

## Files

- `run_publish.py` - Main entry point
- `src/publisher.py` - Publishing logic
- `src/aps_dm.py` - APS Data Management API wrapper
- `src/aps_auth.py` - Authentication (2-legged & 3-legged)
- `src/resolver.py` - ID resolution by file name
- `configs/config.json` - Project and model configuration
- `configs/credentials.json` - OAuth credentials (not in repo)

## Related Documentation

- [Autodesk APS Data Management API](https://aps.autodesk.com/en/docs/data/v2/reference/http/commands-POST/)
- [BIM 360/ACC Commands](https://aps.autodesk.com/en/docs/bim360/v1/overview/field-guide/collaboration/)

## Version History

- **v2.1** (2025-10-30): 🎯 Smart fallback strategy - Always try WITH links first, auto-fallback to WITHOUT links
- **v2.0** (2025-10-30): Implemented batch publishing for efficiency
- **v1.0**: Initial release with one-by-one publishing
