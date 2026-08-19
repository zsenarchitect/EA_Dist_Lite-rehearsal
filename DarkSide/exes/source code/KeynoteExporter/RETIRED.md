# RETIRED — do NOT build an exe here

The Keynote Exporter has been extracted into the standalone product
**EnneadTab-KeynoteExporter** (https://enneadtab.com/keynote-exporter). It is no longer
shipped from EnneadTab-OS.

- **Source kept for reference only.** Do **NOT** rebuild or ship an `.exe` from this folder.
- The legacy bundled binary `Apps/lib/ExeProducts/KeynoteExporter.exe` was **cut** from the
  repo — large binaries in `Apps/lib/ExeProducts/` were 500-ing git pushes (see the root
  `CLAUDE.md` "Repository size / legacy EXE bloat" section).
- The ExeMaker build metadata was **disabled**: `DarkSide/exes/maker data/KeynoteExporter.sexyDuck`
  → `…/KeynoteExporter.sexyDuck.RETIRED`, so `ExeMaker.py` (which scans for `*.sexyDuck`) no
  longer picks it up.
- New releases ship from the standalone repo via its own signed installer, mirrored to the
  fleet through `DarkSide/publish/service_factory_products.json` (slug `keynote`).

The historical `.exe` blobs still live in git history; purging them is the pending
"downsizing" action tracked in the root `CLAUDE.md`.
