# HANDOFF — EnneadTab-OS publisher CI/CD (#3269)  ·  SUPERSEDED

> **SUPERSEDED 2026-08-13 by `/HANDOFF.md` at the repo root. Do not use this file's "what is
> left" lists — step 5 is DONE (the fleet has been published by CI, run 31713670880) and the
> §5b question is ANSWERED. This document is kept only as the historical record of WHY the
> `-Production` design took the shape it did, which is still load-bearing reasoning.**

Written 2026-08-12 at a hard stop. Everything here is context you should not have to
re-derive.

> **UPDATE 2026-08-12, later the same day — §1 IS RESOLVED. Start at §0 instead.**

---

## 0. CURRENT STATE — start here

**The §1 blocker is fixed and merged** (PR #140, merge commit `1adef6dd522a`). Do not
re-derive it; §1 is kept below only as the record of why the fix took the shape it did.

张老板 chose the switch over a separate wrapper. `run-ci-publish.ps1` now takes
`-Production`, which **inverts** the rehearsal check rather than skipping it: the override
must be *absent*, and `publish_guard.py --assert-production` must then affirmatively prove
every `EA_Dist*` sibling is on its production remote. `publish-production.yml` passes the
flag; `publish-rehearsal.yml` is forbidden to. All of it is mutation-tested.

Two further defects were found and fixed in the same PR, both of the same class — checks
that were structurally incapable of failing:

- `check_publisher_ci_safety.py`'s entire production block sat inside
  `if os.path.isfile(PRODUCTION_WORKFLOW):` with **no `else`**. Deleting that workflow
  removed all five of its predicates and the gate printed `OK`.
- The ratchet runs inside `ironpython-check.yml`, whose PR trigger is a `paths:` allowlist
  that named `publish-rehearsal.yml` and **not** `publish-production.yml`. A PR touching
  only the production workflow never started the job. Adding `pull_request:` there — the
  change that lets a fork PR force-push the fleet — is exactly such a one-file edit, and it
  would have merged green.

**A second blocker to step 5, not in §1, was also cleared:** the production worktree had no
`DarkSide/.env`, so no `WIKI_API_KEY`. Rehearsal never noticed because `check_wiki_api_key`
short-circuits on `is_rehearsal()`; a production run would have fallen through to a Vercel
CLI pull on the critical path. The gitignored key file is now provisioned in that tree
(`git clean -fd` does not remove ignored files, so it survives each reset), and
`publish_guard --report` from there returns `SAFE TO PUBLISH` with no Vercel pull attempted.

### What is left, in order

1. **Step 5 — the watched production dispatch. 张老板 must trigger it**; the permission
   classifier blocks an agent from dispatching a production publish. Verify against the §4
   anchors: refs advanced, **content parity by blob SHA** (not just refs), deletions
   propagated, `dist-*` tags pushed, single attempt, wiki `INGESTED`.
2. **Decide §5b before arming** — after cutover, mirrored installers and
   `Installation/exe_hash.json` stop landing back in the OS repo. Defensible either way;
   discovering it in three months is not.
3. **Step 6 — arm the `push:` trigger** (§2), then watch the first merge-triggered publish.

The fleet is now stale by more than §4 says: `origin/main` advanced by PRs #130, #134, #137
and #140 during this work.

### Traps to add to §7

7. **A mutation that changes more than its target proves nothing about the target.** The
   wrapper predicates were verified by a global `-replace`, which also rewrote the flag
   where it appears in the docstring — so the gate went red for the wrong reason and the
   red light was read as proof. Deleting *only* the real call showed the check still passed.
   The tightened version was ALSO unfalsifiable (the flag appears in a `Write-Host` banner
   and a `Fail` message, both live code). Mutate by deleting exactly the one line the
   predicate names.
8. **`git push` HTTP 500 on this repo is not always "retry until it works".** Four straight
   500s on a 4-file branch; `git -c http.version=HTTP/1.1 push` landed it first try. Logged
   as senzhang-todo #3942.

---

## 1. THE BLOCKER — RESOLVED 2026-08-12 (kept for the reasoning)

The first CI production publish (**run `31633491120`**) **failed**, correctly, with:

```
CI PUBLISH REFUSED: ENNEADTAB_PUBLISH_REHEARSAL_TARGETS is unset.
CI must not fall through to production remotes.
```

`DarkSide/publish/run-ci-publish.ps1` **refuses production by design**. Its docstring line 4
reads *"CI entry for the EnneadTab publisher. Rehearsal remotes only."* and lines 45–48
hard-fail when the rehearsal override is unset:

```powershell
$rehearsal = [Environment]::GetEnvironmentVariable("ENNEADTAB_PUBLISH_REHEARSAL_TARGETS")
if ([string]::IsNullOrWhiteSpace($rehearsal)) {
    Fail "ENNEADTAB_PUBLISH_REHEARSAL_TARGETS is unset. ..."
}
```

**So `publish-production.yml` is structurally incapable of publishing through that wrapper.**
I built the production workflow on top of a script whose first line says it never publishes to
production. The guard did its job; **production was verified byte-identical afterwards.**

### What the fix must NOT be

Do not delete or weaken that check, and do not set a fake rehearsal value to get past it. That
guard is the reason three rehearsals and one misconfigured production dispatch all left the
fleet untouched.

### Shape the fix should take

An **explicit production mode** that replaces the guard rather than removing it:

- add a `-Production` switch to `run-ci-publish.ps1`
- when set: require `ENNEADTAB_PUBLISH_REHEARSAL_TARGETS` to be **absent**, and affirmatively
  assert the resolved targets **are** the production remotes (do not merely skip the check —
  a skipped check is how this class of bug starts)
- when unset: current behaviour, unchanged
- gate assertion: `publish-rehearsal.yml` must never pass `-Production`; `publish-production.yml`
  must always pass it
- mutation-test each new assertion — watch it FAIL, not merely pass

Open question for 张老板: is a switch the right shape, or should production get its own wrapper
script? A switch keeps one guard chain (less drift); a separate script makes the diff between
"rehearse" and "ship" impossible to miss. I lean switch, because the guard chain is the valuable
part and duplicating it invites divergence.

---

## 2. WHERE #3269 STANDS

| Step | State |
|---|---|
| 1 — shared concurrency group across both workflows | ✅ merged `341045957` |
| 2 — `publish-production.yml` created | ✅ merged (dispatch-only, `push:` NOT armed) |
| 3 — CI-safety gate assertions | ✅ merged, all mutation-tested |
| 4 — retire the legacy scheduler | ✅ 张老板 confirmed `EnneadTab_SchedulePublisher` disabled on EANY |
| 4b — production worktree + wiring | ✅ merged `10dc51db2` |
| 4c — `-Production` mode + gate fixes | ✅ merged `1adef6dd5` (PR #140) — see §0 |
| 4d — `WIKI_API_KEY` in the production tree | ✅ provisioned, guard reports SAFE with no Vercel pull |
| **5 — first watched production publish** | ⏸ **ready — 张老板 must dispatch it** |
| 6 — arm the `push:` trigger | ⏸ only after step 5 succeeds, and after §5b is decided |

The `push:` block is written out as a comment in `publish-production.yml`, ready to uncomment:

```yaml
  push:
    branches: [main]
    paths: ['Apps/**', 'Installation/**']
```

**Trigger policy decided by 张老板:** every merge touching `Apps/` or `Installation/`.

---

## 3. VERIFIED FACTS — do not re-derive these

Each was checked empirically today. Several contradict the obvious assumption.

| Fact | How it was proven |
|---|---|
| All 16 self-hosted runners are on **one machine** (`MININT-H00D42F-szhang-1..16`) | org runners API + `$COMPUTERNAME` + the `Machine :` line in CI logs |
| `concurrency` **serialises** publish jobs | two dispatches 8s apart → one `in_progress`, one `pending`, with all 16 runners idle. The second started only after the first finished |
| Sibling dist repos resolve from the **parent directory** | `publish_guard.discover_dist_repos`: `parent = dirname(os_repo_folder)` |
| One tree serves exactly **one destination** | a force-push goes where `origin` points; the rehearsal override only changes what the guard *expects* |
| Guard exit codes are honest | `WRONG_REMOTE` → exit **1**; rehearsal mode → exit **0** |
| The publisher **never pushes the OS repo** | no push targets `os_repo_folder`; on 2026-08-07 `be3ac7e9c` had to be pushed by hand. So no self-trigger loop after arming `push:` |
| **Zero GitHub Actions billing** | every workflow is `runs-on: [self-hosted, windows]`; timing API reports `billable: {WINDOWS: 0}` for all 8 runs today |
| No Git LFS anywhere | 0 LFS-tracked files, no LFS endpoint. So the 5.4 GB repo costs no quota/money — only policy risk and time |
| A force-push does **not** move 5.4 GB | `EA_Dist_Lite` 13.75 s vs `EA_Dist` 547 s on the same connection — object count, not gigabytes |

### Machine layout

```
~/github/rehearsal/EnneadTab-OS        <- vars.ENNEADTAB_PUBLISHER_CLONE
  siblings: EA_Dist, EA_Dist_Lite      -> zsenarchitect/*-rehearsal   (FORKS)

~/github/ennead-llp/EnneadTab-OS-publisher  <- vars.ENNEADTAB_PUBLISHER_CLONE_PRODUCTION
  (detached git worktree, created today)
  siblings: ~/github/ennead-llp/EA_Dist, EA_Dist_Lite  -> PRODUCTION

~/github/ennead-llp/EnneadTab-OS       <- developer checkout. NEVER point the publisher here:
                                          run-ci-publish.ps1 opens with reset --hard + clean -fd
```

The production worktree is synced to `10dc51db2`, clean, `enrolled: True`, venv mirrors the
proven rehearsal one exactly (9 packages, identical `pip freeze`), and the guard from it reports
`SAFE TO PUBLISH`.

---

## 4. ROLLBACK ANCHORS (still current — nothing published since 2026-08-07)

```
EA_Dist       394fa1126c333e0380647525467fdc7ac7d57534   13 refs
EA_Dist_Lite  b40b3a60975d69034acdb31ea3e2e0b04cd8090c   13 refs
```

Rollback per repo: `git reset --hard <dist-tag>` then force-push. `dist-*` tags are pushed each
publish, `keep_last=10`.

**The fleet is stale by 4 commits / 3 files touching `Apps/` + `Installation/` since 2026-08-07.**

---

## 5. WHAT ELSE SHIPPED TODAY (all merged, all verified)

| PR | Commit | What |
|---|---|---|
| OS #117 | `7e150351c` | wiki ingest three-state reporting; a step that never ran can no longer print a green banner |
| OS #132 | `f996ad3a5` | a rehearsal no longer **writes** the production wiki |
| OS #133 | `90eacfaf8` | a rehearsal no longer **pulls** the production wiki key |
| OS #135 | `341045957` | production workflow + shared concurrency group + gate |
| OS #136 | `10dc51db2` | production worktree wiring |
| Wiki #77 | `871bd5c` | `?dryRun=1` on `/api/ingest` — full validation, zero writes |
| Wiki #78 | `82ec4ce` | `--dry-run` reported failure on success and said "committed" |

Also: `WIKI_API_KEY` provisioned in `DarkSide/.env` (gitignored) and verified against the
deployed fingerprint endpoint; 347 revit + 157 rhino tools ingested to the live wiki, confirmed
server-side.

Six publisher gates exist and all pass:
`check_publish_outcome_honesty`, `check_push_landing_predicates`, `check_generated_artifact_commit`,
`check_never_delete_unreplaceable`, `check_publisher_ci_safety`, `check_wiki_ingest_reporting`.

---

## 5b. A BEHAVIOURAL CHANGE THE CUTOVER CAUSES — decide, don't drift into it

The publisher **never pushes the OS repo**, and `run-ci-publish.ps1` opens every run with
`git reset --hard $Sha`. So `_commit_generated_artifacts`' commit is created and then discarded
on the next run.

**Consequence after cutover:** mirrored service-factory installers and
`Installation/exe_hash.json` will **never land back in the OS repo**. Today they do — on
2026-08-07 that commit (`be3ac7e9c`, ~880 MB of installers) was pushed by hand.

- The **fleet is unaffected**: `_sync_repositories` copies the working tree, so EA_Dist still
  ships them.
- The OS repo simply stops tracking new installer versions.
- **This may be desirable** — it removes the ~85 MB-per-release growth in #3785 and sidesteps
  the 99.5 MiB / 100 MiB hard-block ceiling.

Either answer is defensible. What is not defensible is discovering it months later. Decide it
explicitly when arming the trigger.

Related open question from the plan: **should every qualifying merge publish?** 张老板 chose yes
(every merge touching `Apps/` or `Installation/`). The cost is a ~9-minute job and a force-push
per merge; four such PRs merged today would have meant four publishes. A `paths:` filter that is
too *narrow* silently skips a publish that mattered, so prefer slightly too broad — a wasted
publish is cheap, a missed one is invisible.

---

## 6. OPEN TODOS

| # | Item |
|---|---|
| **3901** | fix shipped + verified, but **still OPEN** — the v0.18.0 close-gate rejected the close (`no auto-close targets (no fully-satisfied gates)`) and I would not force it. Outcome is attached as a note (`e7f273a8c`) |
| 3785 | EA_Dist 5.26 GB; `EnneadTab_IndesignRepather_Installer.exe` at **99.5 MiB vs the 100 MiB hard block** — this is a dated fuse, not a nit |
| 3792 | wiki delta-ingest defeated — manifest API unavailable, so every publish full-ingests all 504 tools; 6 icon paths missing on disk |
| 3794 | CLAUDE.md mandates a `.venv` that does not exist in the dev checkout (it DOES exist in the rehearsal + production trees) |
| 3790 | `InfraWatch_Collect` and `ScheduleOpener` have maker configs but no built exe |
| 3791 | 2 tracked `Apps/` files never reach the fleet; no exclusion rule explains it (verified pre-existing) |
| 3919 | `actions/checkout@v4` + `setup-python@v5` still target Node 20, forced onto Node 24 — every workflow breaks at once when that forcing ends |
| 3796 | toolify: `sen-tool-tree-parity` (plugin-hub) |

**Pre-existing, unrelated:** the "Advisory full-tree sweep (non-blocking)" job fails on `main`
too — `check_mcp_tool_drift.py` reports 3 MCP drift findings. Not caused by this work.

---

## 7. TRAPS HIT TODAY — do not repeat

1. **Backticks in `git commit -m "..."` execute.** A message containing `` `git reset --hard` ``
   and `` `git clean -fd` `` ran them via command substitution and destroyed uncommitted work.
   **Always use `git commit -F -` with a quoted heredoc (`<<'MSG'`).**
2. **Mutation-test only AFTER committing.** `git checkout --` to restore a mutation also
   discards uncommitted implementation. Hit twice today.
3. **`$?` after a pipeline is the LAST command's exit code**, not the interesting one.
   `cmd | tail` reports `tail`'s status. Cost a false "GUARD_EXIT=0" on an UNSAFE guard report,
   and a false "pip exit=0" when pip had actually failed.
4. **`grep -c` on an incomplete log returns 0**, identical to a genuinely clean result. Always
   confirm the log is populated (line count + a known marker) before trusting a zero.
5. **Verify presence AND fitness.** I checked the rehearsal clone existed and had a `.venv`,
   never where its siblings pointed. Same shape as the `is_clean: True` bug: presence-shaped
   checks can't answer "is this the right thing".
6. **Don't merge on pending CI.** Did it twice; both happened to pass.

---

## 8. SUGGESTED FIRST MOVES NEXT SESSION

1. Read §1. Decide switch vs separate wrapper with 张老板.
2. Implement, mutation-test each assertion, PR, merge (wait for CI).
3. Dispatch `publish-production.yml` **watched**. Note: 张老板 must trigger it — the permission
   classifier blocks me from dispatching a production publish.
4. Verify against §4 anchors the way 2026-08-07 was verified: refs advanced, **content parity by
   blob SHA** (not just refs), deletions propagated, `dist-*` tags pushed, single attempt, wiki
   `INGESTED`.
5. Only then arm the `push:` trigger (§2), and watch the first merge-triggered publish.
