# HANDOFF — rename the dedicated publisher clones to "NO WORK INSIDE" names

**For a session/operator ON THE CICD BOX `MININT-H00D42F`.** Prepared from `EANY-1X8MWP3`, which
cannot reach that box. Goal: rename the two dedicated publish clones to unmistakable names so nobody
`cd`s in and does real work in a tree that gets `git reset --hard` + `git clean -fd` on every publish.

## Why these clones are dangerous to work in

`DarkSide/publish/run-ci-publish.ps1` opens each publish with `git fetch` + `git reset --hard` +
`git clean -fd` on the clone pointed to by the Actions variable. Any uncommitted/unpushed work in
that tree is **destroyed on the next publish, by design.** These are throwaway publish trees, not dev
clones. The rename makes that impossible to forget.

## The two clones (rename the LEAF folder only — keep the parent, it holds the sibling dist repos)

| Clone | Actions variable | From | To |
|---|---|---|---|
| Production | `ENNEADTAB_PUBLISHER_CLONE_PRODUCTION` | `C:\Users\szhang\github\ennead-llp\EnneadTab-OS-publisher` | `C:\Users\szhang\github\ennead-llp\_TEMP_EnneadTab-OS_PUBLISH_NO_WORK_INSIDE` |
| Rehearsal | `ENNEADTAB_PUBLISHER_CLONE` | `C:\Users\szhang\github\rehearsal\EnneadTab-OS` | `C:\Users\szhang\github\rehearsal\_TEMP_EnneadTab-OS_REHEARSAL_NO_WORK_INSIDE` |

(`run-ci-publish.ps1` and `tools/check_publisher_ci_safety.py` key on the variable NAME, not the path,
so the names stay; only the path VALUE + the folder + docs change.)

## Order matters — folder first, variable second, tight (else the next publish `Fail`s "does not exist")

**Precondition:** no publish running — `gh run list --workflow=publish-production.yml --limit 3` and
`gh run list --workflow=publish-rehearsal.yml --limit 3` both idle.

### Step 1 — rename the leaf folders (PowerShell, on `MININT-H00D42F`)
```powershell
Rename-Item 'C:\Users\szhang\github\ennead-llp\EnneadTab-OS-publisher' '_TEMP_EnneadTab-OS_PUBLISH_NO_WORK_INSIDE'
Rename-Item 'C:\Users\szhang\github\rehearsal\EnneadTab-OS'            '_TEMP_EnneadTab-OS_REHEARSAL_NO_WORK_INSIDE'
```
Also, if this fallback file exists and hardcodes the old path, update it:
```
~/.enneadtab/publisher-ci-clone   # holds a clone path per run-ci-publish.ps1:97 — point it at the new prod path
```

### Step 2 — update the two Actions variables (immediately after Step 1)
```bash
gh variable set ENNEADTAB_PUBLISHER_CLONE_PRODUCTION -R EnneadTab-EcoSystem/EnneadTab-OS \
  --body 'C:\Users\szhang\github\ennead-llp\_TEMP_EnneadTab-OS_PUBLISH_NO_WORK_INSIDE'
gh variable set ENNEADTAB_PUBLISHER_CLONE            -R EnneadTab-EcoSystem/EnneadTab-OS \
  --body 'C:\Users\szhang\github\rehearsal\_TEMP_EnneadTab-OS_REHEARSAL_NO_WORK_INSIDE'
# verify:
gh variable list -R EnneadTab-EcoSystem/EnneadTab-OS | grep PUBLISHER_CLONE
```

### Step 3 — update doc path references (in a PR)
Replace the old leaf paths with the new ones in:
- `HANDOFF.md` (line ~171: `.../ennead-llp/EnneadTab-OS-publisher`)
- `DarkSide/publish/HANDOFF-2026-08-12-cicd-cutover.md` (lines ~169, ~172)
- `docs/plans/2026-08-18-exeproducts-history-prune.md` (the `ENNEADTAB_PUBLISHER_CLONE_PRODUCTION` path line)

### Step 4 — verify end-to-end
- Run a **rehearsal** publish (`gh workflow run publish-rehearsal.yml` or the normal trigger) and confirm
  `run-ci-publish.ps1` finds the clone (no "does not exist" Fail) and completes.
- Confirm `tools/check_publisher_ci_safety.py` still passes (it checks the var NAME usage, unaffected).

## Rollback
Rename both folders back to the original leaf names and revert the two variables to the original paths
(above). No data is at stake — these clones are reset every publish anyway.

## Note
If you prefer the exact all-caps form 张老板 sketched (`_TEMP_ENNEADTAB_OS_PUBLISH_NO_WORK_INSIDE`),
use that consistently in Step 1 folder names AND Step 2 variable values — just keep folder and variable
byte-identical.
