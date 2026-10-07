# FlyThrough — Rhino precise camera-path pipeline

**senzhang-todo #452** · Home: **EnneadTab-OS** (`Apps/_rhino/`) · deliberately **repointed off** EnneadTab-RenderPolisher (that repo is AI-from-stills / Veo).

## What it does

1. **Lock camera path** in the live Rhino 3D viewport (or import Named Views).
2. **Export keyframe stills** first for human debug / approval.
3. **Render final** dense frames + image set + optional `flythrough.mp4` (ffmpeg when present).
4. **Monitor logs** under `Dump/FlyThrough/<job_id>/monitor.log` and `job_status.json`, with ambient progress via NotificationHost when available.

## How to run (from Rhino)

1. Open a model and activate a Perspective viewport.
2. Click **Render tab → FlyThrough**, or run alias `FlyThrough` / `EA_FlyThrough` (after EnneadTab startup / get_latest has registered aliases). The toolbar button appears after the next AutoDist / RuiWriter publish; the alias works as soon as the knowledge DB is synced.
3. Choose **Lock keyframe**, move the camera, lock again. Repeat until the path is right.
4. Choose **Export keyframe stills** and review the opened `stills/` folder.
5. Choose **Render final video + image set**. The job folder opens when finished.

### Outputs

```
%USERPROFILE%\Documents\EnneadTab Ecosystem\Dump\FlyThrough\
  active_path.json          # locked path (survives across clicks)
  stills_YYYYMMDD-HHMMSS\   # approval stills job
    monitor.log
    job_status.json
    path.json
    stills\
  final_YYYYMMDD-HHMMSS\    # final render job
    monitor.log
    job_status.json
    path.json
    frames\                 # dense image sequence
    images\                 # evenly spaced image set
    flythrough.mp4          # only if ffmpeg is on PATH
```

## Settings

Use menu item **Configure resolution / fps / duration**. Defaults: 1920×1080, 24 fps, 8 s.

## Extends existing tooling

- Named Views + `ViewCapture` / `Rhino.Display.ViewCapture` (same capture approach as AI Render / batch export).
- Optional import of cameras you already manage with ImportSelectedCamera / BatchRenameCamera / BatchExportRhinoView.
- Progress via `EnneadTab.UI.ProgressBarManager` (Dump/progress_jobs).

## Code map

| Piece | Path |
|-------|------|
| Pipeline (path, sample, stills, final, monitor) | `Apps/lib/EnneadTab/RHINO/RHINO_FLYTHROUGH.py` |
| Thin Rhino button UI | `Apps/_rhino/Render.tab/fly_through.button/fly_through_left.py` |
| Pure math unit tests | `DarkSide/tests/fly_through/test_fly_through_math.py` |
