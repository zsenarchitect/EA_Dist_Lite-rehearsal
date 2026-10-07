# HARD-STOP HANDOFF — 2026-08-13

Written at a hard stop at the end of a long session. Read §0 before doing anything.

This supersedes `DarkSide/publish/HANDOFF-2026-08-12-cicd-cutover.md`, which is kept only as the
historical record of *why* the `-Production` design took the shape it did. Its "what is left" list
is now stale — this file is the current one.

Ledger: senzhang-todo **#3269** (cutover), **#4014** (AppStore on-demand), plus #3984 #3990 #3991
#4007 #4011.

---

## 0. BLOCKING CONDITIONS — read before acting

**Nothing is mid-flight. No subagent is running. No tree is half-written.** The three subagents
this session used (`sec5b-note`, `appstore-sketch`, `petduck-3990`) all completed and are idle.

Two things are STAGED BUT NOT MERGED. Check them first:

```bash
gh pr view 149 --repo EnneadTab-EcoSystem/EnneadTab-OS      # docs: AppStore design + prototype
gh pr view 21  --repo EnneadTab-EcoSystem/EnneadTab-PetDuck # fix: release upload ordering
```

Two worktrees are live and hold those branches. Do not delete them until the PRs merge:

```
~/github/ennead-llp/.wt-os-appstore-plan        docs/appstore-on-demand-plan
~/github/ennead-llp/.wt-petduck-release-order   fix/release-upload-ordering
```

A third worktree, `EnneadTab-OS/.claude/worktrees/sen-progressbar-host-surface`, belongs to a
CONCURRENT SESSION. Never `git clean -fd` at the EnneadTab-OS root — it would delete that tree.
Use pathspec-scoped cleans only.

---

## 1. DONE, AND HOW IT WAS VERIFIED

Not a feature list. Each line is what was actually observed.

**The fleet is published by CI for the first time (#3269 step 5).** Run `31713670880`, green in
~50 min, dispatched from `d3c514f8`. Verified independently of the log: `EA_Dist`
`394fa1126c33 → 99d48916222b` and `EA_Dist_Lite` `b40b3a60975d → d60e188ad62d`; **content parity by
tree SHA** (`5e5c90da498d` / `01eb8976b903` identical local and remote — a matching ref with a
different tree is the false success this checks for); both trees clean; both `dist-*` rollback tags
created and pushed. From the log: `CI PRODUCTION publish`, `PRODUCTION CONFIRMED`, `SAFE TO
PUBLISH`, `PUBLISH_EXIT=0`, wiki `INGESTED`, and **no** "pulling from Vercel".

**`-Production` mode shipped** (PR #140 → `1adef6dd522a`). Inverts the rehearsal check rather than
skipping it. Every predicate mutation-tested to FAIL, not merely pass.

**Two gates that could not fail, fixed** (same PR): the production block sat inside
`if os.path.isfile(...)` with no `else`, so deleting `publish-production.yml` disarmed five
predicates and printed OK; and `ironpython-check.yml`'s `paths:` allowlist named the rehearsal
workflow but not the production one, so a PR touching only `publish-production.yml` never ran the
ratchet at all.

**#3990 fixed and verified at the URLs, not by exit code.** PetDuck's feed advertised 0.1.16 while
the asset 404'd — a broken auto-update for every installed client. Repaired by uploading the
already-signed artifact (identity checked first: 81,984,976 bytes, sha512 matching the live feed
byte-for-byte, Authenticode Valid + timestamped). After:
`.../updates/EnneadTab-PetDuck-Setup-0.1.16.exe` → 200 with `Content-Length: 81984976`;
`/pet-duck/download` → 200; `latest.yml` unchanged, so no client sees a checksum change.

**§5b answered: let the installers stop landing in the OS repo.** Needs no code — it is what the
cutover already does. Do NOT "implement" it by deleting `_commit_generated_artifacts` — but the
reason originally given here was wrong, and worth correcting because it would send the next reader
looking in the wrong file (senzhang-todo #4659).

The old reason was "that commit is what stops retry attempts 2 and 3 failing the dirty-tree check
*within* a run." There are no retry attempts on the live path. The retry loop
(`max_retries = 3`) lives only in the **shadowed** `publish()` at `________publish.py:3947`;
`__main__` at `:4222-4224` binds the *later* `publish()` at `:4181`, which runs the 7-stage
pipeline, and `PipelineRunner.run` breaks on the first `PublishStageError` — no retries at all.
`_commit_generated_artifacts` itself is called from exactly one place in the publisher,
`:3867`, inside that same shadowed code.

The advice still stands, for a different reason: `tools/check_generated_artifact_commit.py:72`
drives that method as its fixture, so deleting it breaks a gate that pins a real invariant
(a publish records its own output and nothing else). Keep it as gate surface, not as retry
protection.

**Publisher gate coverage — what a green ratchet does and does not prove** (senzhang-todo #4656).
`HANDOFF-2026-08-12-cicd-cutover.md` claimed "six publisher gates exist and all pass". That doc was
retired in `3364c31e8` as superseded by this one; the claim is recorded here because it was true and
misleading, which is worse than false, and the shape recurs.

All six passed — when run by hand. Only **two** were executed by anything; the other four appeared in
prose and in no workflow, hook, or pre-commit config, and a detector that never executes is
indistinguishable from one that passes. Two further corrections:

- **The orphan count was four; it is really six.** `tools/check_ironpython_diff.py` and
  `tools/check_syntax_gate_predicates.py` have zero references repo-wide — not even prose. (Trap:
  `ironpython-check.yml` has a *job* named `ironpython-diff` that does not run
  `check_ironpython_diff.py`.) Sharpest: `check_syntax_gate_predicates.py` is the artifact written
  for "a gate that had never once executed", and has itself never executed. senzhang-todo #4704.
- **Passing says less than it looks.** Four of the six drive `RepoPublisher`, constructed exactly
  once repo-wide — inside the *shadowed* `publish()` at `________publish.py:3947`. They certify the
  legacy publisher, not the seven-stage pipeline that ships.

What that cost: `check_push_landing_predicates` enforces "a timeout is absence of evidence, not
evidence of absence" — on the dead copy. The live `stage_05_git_push.py` violated exactly that,
reporting any unreadable remote as *"origin/main does not equal local HEAD"* **after** the
force-push had landed. Fixed 2026-08-22, with `tools/check_live_push_landing.py` as the live twin.

State now: three of the four orphans are wired into `publisher-ratchets` with their scope stated at
the step. `check_push_landing_predicates` stays unwired on purpose — it calls the real `publish()`
guarded only by a monkeypatch (#4706). Retargeting the legacy gates at the pipeline is #4775
(corrects a miscitation to #4707 shipped in an earlier commit here and in
`ironpython-check.yml` -- #4707 is the venv-mismatch item documented below, unrelated).

**Which publish path is live** — worth stating plainly, because two of the three obvious places to
patch are dead:

- **LIVE:** `publish()` at `________publish.py:4181` → `PublishContext` + `PipelineRunner` → the
  seven stages in `DarkSide/publish/pipeline/stages/`. `stage_04_stage_dist.py` is the sync path.
- **SHADOWED:** `publish()` at `:3947` and `RepoPublisher.publish()` at `:3816`, including the
  ~2700-line legacy sync. Python keeps the later binding, so nothing calls these.
- **DO NOT DELETE `RepoPublisher` anyway.** Five gates construct it via
  `RepoPublisher.__new__(...)` and drive its methods as behavioural fixtures. It is dead as a
  publish path and live as a test surface.

**The two publisher clones run different Python interpreters** (#4707) — a standing hazard
under every publisher change, not something a single fix resolves:

| clone | interpreter | source |
|---|---|---|
| rehearsal (`~/github/rehearsal/EnneadTab-OS_NO_WORK_INSIDE`) | 3.11.9 | `C:\hostedtoolcache\windows\Python\3.11.9\x64` |
| production (`~/github/ennead-llp/EnneadTab-OS_NO_WORK_INSIDE`) | 3.13.14 | **Microsoft Store** install (`PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0`) |

`run-ci-publish.ps1` resolves `$clone\.venv\Scripts\python.exe` and runs `________publish.py`
with it — so *that* interpreter, not whichever one a developer happens to test with, decides
what stdlib APIs are legal anywhere under `DarkSide/publish/**`. **"Verified on rehearsal" is
therefore not "verified on production"** for anything version- or packaging-sensitive: a
rehearsal green is evidence about 3.11.9 on a standard install; every production publish runs
on a different, Store-packaged 3.13.14, which carries its own filesystem redirection and
app-execution-alias behaviour — exactly the class of thing that bites on path handling, which
this codebase already has a documented incident about (the 2026-08-18 clone-rename outage).

Not stated anywhere else in this repo's docs as of 2026-08-22 — confirmed by grepping
`DarkSide/`, `docs/`, every `HANDOFF*.md`, the workflows, and `run-ci-publish.ps1`; it is
observable only by reading the clones directly. No fix shipped here. Repinning either
publisher clone's venv is an out-of-repo, live-infrastructure change (reinstalling a
production Python), not a code change — deliberately out of scope for a documentation pass.
The open question, for whoever picks this up: pin both clones to the same interpreter, or
accept the drift and make the CI-safety ratchet assert the *documented* production version
matches what's actually installed, so a future interpreter upgrade on either box is a loud
diff instead of a silent one.

---

## 2. UNFINISHED — broken or unproven before polish

**#3269 step 6: `push:` is NOT armed.** Verified still commented out on main (0 active trigger
lines). Everything blocking it is now clear. Before arming, know that #3984 is real: `fetch-depth: 0`
spent **27 of that publish's 50 minutes** doing a full `--unshallow` of the 2.26 GB repo (66,595
objects) before the publish step started. Once armed, every qualifying merge pays that, and the
shared `enneadtab-publisher-clone` concurrency group serialises runs.

**AppStore on-demand rewrite (#4014): step 2 not started.** Decision is made (fully on-demand);
design and prototype are preserved in `docs/plans/2026-08-13-appstore-on-demand/` via PR #149. Step
2 refactors `________publish.py` — the file that force-pushes to ~50 machines and ran its first CI
production publish hours ago. Deliberately left for a fresh session.

**Unproven in the prototype, from its own §6:** the tkinter GUI was NEVER executed; PyInstaller
resolution of the split sibling imports inside the frozen exe is unproven (three `datas` entries,
not one); installed-version detection is **n=1** — only PetDuck was installed on the test machine,
so "every product registers an uninstall entry the same way" is one observation, not a rule.

**#4011** — `_mirror_service_factory_installers()` has no download size cap. Reproduced: a
non-closing stream wrote a **23.5 GB `.part`**. Fix belongs in step 2, since that is the code
being moved.

**CARRIED OVER, STILL OPEN — the MCP dead-tool check.** A hard-stop handoff from 2026-08-07 lived
at this path before this file replaced it; its full text is preserved verbatim at
`docs/plans/2026-08-07-mcp-dead-tool-check-handoff.md` and is byte-identical to the original. Read
it before touching `tools/check_mcp_tool_drift.py`. Its blocking condition is the same class of
defect this whole session was about: promoting that check to blocking as currently wired would
create **a gate that can never fail**, because the CI sweep job checks out only this repo and the
check SKIPS any host whose sibling client repo is absent — so in CI both hosts are skipped, it
exits 0 having verified nothing, and a vacuous green reads as coverage. The prerequisite is a CI
change (check out the sibling repos), not a Python change.

This is also the job that has been red on `main` and on every PR this session: the advisory sweep
fails on `check_mcp_tool_drift.py` with 3 findings (`GET /documents` unexposed; two dead
`*-reference-code` client tools). `continue-on-error: true`, so it does not block merges. Confirmed
pre-existing and unrelated to the cutover — verified from the run log, not assumed.

---

## 3. HYPOTHESES THAT TURNED OUT WRONG — the section that saves the next session

**Do not chase these. They were recorded confidently and were wrong.**

1. **#3990's first root cause was wrong.** I filed it as "the roster points at a GitHub release
   asset that does not exist; check the EnneadTab-PetDuck releases." The roster carries no URL at
   all, and the mirror never touches GitHub — it downloads from
   `enneadtab.com/<slug>/updates/latest.yml` over plain `urllib` with no token. Corrected on the
   item. The real cause: release run `31710086433` failed at a single multi-file
   `gh release upload` with HTTP 404 on the 82 MB `.exe` POST, while `.blockmap` and `latest.yml`
   both landed.
2. **`#4005` (concurrent `npm ci`) was NOT the cause of #3990**, despite being same-day and
   plausible — I handed it to the investigating agent as a strong lead and it rejected it on
   evidence: `npm ci`, build, sign and signature-verify all passed.
3. **"§5b sidesteps the 100 MiB ceiling" is FALSE.** I repeated it from the old handoff without
   checking. The same 99.51 MiB installer is *also* in EA_Dist, which is force-pushed every
   publish, so the ceiling lives on the fleet-facing push. **#3785 stays a live dated fuse** — only
   step 6 of #4014 defuses it. Do not close it early.
4. **A `git hash-object` comparison gave a false answer twice.** Used to decide whether working-tree
   files carried real work, it flagged `NOTIFICATION.py` as local work (it was a CRLF difference) and
   MISSED the one file that actually differed. `git diff --quiet <rev> -- <path>` applies git's own
   normalization and was correct. Never use raw-byte hashing for that question.
5. **Content that looks like it REVERTS a documented fix may just be an older checkout target.**
   `toast_window.py` appeared to revert a `QTimer.singleShot` fix; it matched `7cc850cc5` exactly —
   origin had simply advanced. Check whether content matches SOME commit before concluding anyone
   reverted anything.
6. **A mutation test that changes more than its target proves nothing.** Twice, a predicate "verified"
   by a global `-replace` was actually unfalsifiable — the flag also appeared in a docstring, then in
   a banner and an error string. Only single-line deletion exposed it. See
   `feedback_mutation_must_be_minimal.md`.

---

## 4. ROLLOUT ORDER AND WHAT IS IRREVERSIBLE

**Irreversible:** any production publish force-pushes both dist repos to ~50 machines. Rollback is
`git reset --hard <dist-tag>` then force-push, per repo. Current anchors:

```
EA_Dist       dist-20260813-113847 -> 394fa1126c33...
EA_Dist_Lite  dist-20260813-113407 -> 32d2dce8446c...
```

Note the Lite anchor is NOT the 2026-08-07 one: a docs commit landed directly in that dist repo at
11:13 on 08-13, moving the real last-known-good head. **Never verify a rollback tag against a
remembered SHA** — derive it as the publish commit's parent.

**Order for #4014, do not reorder:** publisher refactor onto the shared feed module → roster copy
into `Apps/lib/` → AppStore rewrite + rebuild + **test with the network off** → propagate →
**only then** delete the mirrored binaries. Never bundle the last two: until every machine has the
new AppStore, an old one lists installers that no longer exist.

**A production dispatch cannot be done by an agent** — the permission classifier blocks it. 张森
triggers it.

---

## 5. LOCAL ENVIRONMENT STATE

- `~/github/ennead-llp/EnneadTab-OS_NO_WORK_INSIDE` is the PRODUCTION publish worktree (renamed
  2026-08-19 from `EnneadTab-OS-publisher`; see `DarkSide/publish/HANDOFF-2026-08-18-rename-publisher-clones.md`).
  It now contains
  a **gitignored `DarkSide/.env` holding `WIKI_API_KEY`**, placed this session. It is required:
  `check_wiki_api_key` short-circuits in rehearsal, so no rehearsal ever exercised it, and without
  it a production run falls through to a Vercel CLI pull on the critical path. `git clean -fd` does
  not remove ignored files, so it survives each run's reset. **Do not delete it.**
- The 0.1.16 PetDuck installer still sits in the runner workspace at
  `C:\Users\szhang\actions-runner\1\_work\EnneadTab-PetDuck\...\release\`. It is now also on the
  GitHub release, so it is no longer load-bearing; `actions/checkout` will wipe it.
- `git push` on EnneadTab-OS 500s repeatedly over HTTP/2. `git -c http.version=HTTP/1.1 push` lands
  it first try — used for every push this session. Logged as **#3942**; CLAUDE.md's "just retry"
  guidance is incomplete.
- No scratch databases, no pulled secrets beyond the `.env` above, no test fixtures anywhere near
  production.
