# RETIRED — do NOT build an exe here

This is the Princeton-special variant of the Keynote Exporter, now superseded by the
standalone product **EnneadTab-KeynoteExporter** (https://enneadtab.com/keynote-exporter).

- **Source kept for reference only.** Do **NOT** rebuild or ship an `.exe` from this folder.
- The legacy bundled binary `Apps/lib/ExeProducts/KeynoteExporterPrincetonSpecial.exe` was
  **cut** from the repo — large binaries in `Apps/lib/ExeProducts/` were 500-ing git pushes
  (see the root `CLAUDE.md` "Repository size / legacy EXE bloat" section).
- The ExeMaker build metadata was **disabled**:
  `DarkSide/exes/maker data/KeynoteExporterPrincetonSpecial.sexyDuck` →
  `…/KeynoteExporterPrincetonSpecial.sexyDuck.RETIRED`, so `ExeMaker.py` (which scans for
  `*.sexyDuck`) no longer picks it up.

The historical `.exe` blob still lives in git history; purging it is the pending
"downsizing" action tracked in the root `CLAUDE.md`.
