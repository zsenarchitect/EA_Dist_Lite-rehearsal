# Retired EXEs — no longer built or shipped

Batch retired 2026-08-07 (Phase 1 of repo downsizing). For each tool below the **binary was removed**
from `Apps/lib/ExeProducts/`, its build recipe renamed `*.sexyDuck` → `*.sexyDuck.RETIRED` so ExeMaker
no longer compiles it (`ExeMaker.py` builds only files ending `.sexyDuck`), and its `exe_hash.json`
entry deleted. **Source code is intentionally KEPT** under `DarkSide/exes/source code/` for reference —
these are retired, not deleted.

## Retired (recipe present → renamed `.RETIRED`)
| Tool | Source kept at |
|------|----------------|
| Data_Viz | `source code/Data_Viz.py` |
| Scratcher | `source code/Scratcher/` |
| AvdResourceMonitor | `source code/AvdResourceMonitor/` |
| AccAutoRestarter | `source code/AccAutoRestarter/` |
| BCF_Converter | `source code/BCF_Converter/` |
| VizSheetTree | `source code/VizSheetTree.py` |
| RelationshipTree | `source code/RelationshipTree/` |
| FactoryResetAccDesktopConnector | `source code/FactoryResetAccDesktopConnector.py` |
| AccFileOpenner | `source code/AccFileOpenner/` |
| SplashScreen | `source code/SplashScreen.py` |
| IndesignAccOpenner | `source code/IndesignAccOpenner/` |
| ShanghaiRepoAssist | `source code/ShanghaiRepoAssist.py` (source is now a refuse stub; BackupRepo copy deleted 2026-08-18) |

## Retired (orphans — no build recipe existed; binary removed only)
`HealthMetricSender`, `NYU_HQ`, `AboutMe_ComputerInfo`, `AboutMe_ComputerInfo_Silent`.

## Effect on live launch buttons
These tools' launch buttons (`Data_Viz`, `VizSheetTree`, `RelationshipTree`, `NYU_HQ` have live
`try_open_app` sites) will now **silently no-op** on user machines (missing exe → `locate_executable`
returns False, no crash). Intended — these tools are retired.

To un-retire a tool: rename its `.sexyDuck.RETIRED` back to `.sexyDuck`, rebuild via ExeMaker, restore
its `exe_hash.json` entry.

---

# ⛔ PHASE 2 — HARD-STOP HANDOFF: history purge (NOT yet done)

**Phase 1 (this) only stops the exes from being tracked/shipped GOING FORWARD.** It reclaims ~0 from
`.git` — every one of these ~0.70 GB of binaries (plus their historical versions) is still baked into
git history. Reclaiming that space requires a **history rewrite + force-push**, which is deferred.

## Do NOT run this without an explicit coordinated window
- Rewrites SHAs → **breaks every existing clone/worktree** (devs, CI, any concurrent agent session).
- At time of Phase 1 there was an active concurrent worktree (`sen-mcp-assistant-enh`) — a force-push
  would have broken it. Confirm ALL clones are quiesced and ready to re-clone before proceeding.
- End users are unaffected (they consume the EA_Dist ZIP snapshot, not git history) — the risk is to
  developers/CI/agents only.

## The purge (when cleared)
Purge these paths from ALL history, then gc + force-push:
```
Apps/lib/ExeProducts/Data_Viz.exe
Apps/lib/ExeProducts/Scratcher.exe
Apps/lib/ExeProducts/AvdResourceMonitor.exe
Apps/lib/ExeProducts/AccAutoRestarter.exe
Apps/lib/ExeProducts/BCF_Converter.exe
Apps/lib/ExeProducts/VizSheetTree.exe
Apps/lib/ExeProducts/RelationshipTree.exe
Apps/lib/ExeProducts/FactoryResetAccDesktopConnector.exe
Apps/lib/ExeProducts/AccFileOpenner.exe
Apps/lib/ExeProducts/SplashScreen.exe
Apps/lib/ExeProducts/IndesignAccOpenner.exe
Apps/lib/ExeProducts/ShanghaiRepoAssist.exe
Apps/lib/ExeProducts/HealthMetricSender.exe
Apps/lib/ExeProducts/NYU_HQ.exe
Apps/lib/ExeProducts/AboutMe_ComputerInfo.exe
Apps/lib/ExeProducts/AboutMe_ComputerInfo_Silent.exe
```
Recommended: `git filter-repo --invert-paths --path <each>` (or `--paths-from-file`). Back up a mirror
bundle of pre-rewrite refs first. Coordinate re-clone for all devs/CI after force-push.

**Scope note:** this handoff covers ONLY the 16 exes retired in Phase 1. A broader downsizing (other
large tracked exes) was explicitly NOT authorized — remove only what the owner names.
