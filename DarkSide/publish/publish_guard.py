"""Pre-publish safety guard for the EnneadTab distribution publish.

WHY THIS EXISTS
---------------
`________publish.py` force-pushes to the distribution repos on EVERY publish, with
no fetch and no ancestry check (see `_sync_repositories`, the comment
"Skip pulling latest changes - we will override everything"). That makes whichever
clone runs the publish become truth: a clone that is behind SILENTLY DESTROYS every
published commit made since it last synced -- on repos the whole firm installs from.

On 2026-08-06 this was live: this machine's `EA_Dist_Lite` clone sat 16 days and two
commits behind origin. A manual publish from here would have force-pushed that
regression to the fleet.

This module is the guard that must pass BEFORE any publish is allowed to proceed.
It is deliberately:

  * side-effect free at import  -- no EnneadTab import, no tkinter, no shared-root
    probing, so it can run anywhere (CI runner, dev box, a machine with no L: drive)
  * read-only                   -- it fetches, it never pushes, resets, or commits
  * loud                        -- every check returns a Problem; nothing warns-and-continues

It is the intended source of truth for discovery + target verification. `________publish.py`
should IMPORT `discover_dist_repos` and `verify_publish_preconditions` rather than
re-implementing them, so the two can never drift apart.

USAGE
    python publish_guard.py --report            # human report, exit 1 if unsafe
    python publish_guard.py --report --json     # machine-readable
    python publish_guard.py --self-test         # prove the guard can REJECT (see below)

ON --self-test (rule #22)
    A detector nobody has watched FAIL is not a verified detector -- "only ever
    returns green" and "working correctly" look identical. `--self-test` runs the
    predicates against known-bad fixtures and asserts each one is rejected. Run it
    after any edit to this file.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

# ---------------------------------------------------------------------------
# The expected publish targets, by directory basename.
#
# NOTE THE TWO DIFFERENT GITHUB ORGS -- this is not a typo and it is the single
# most commonly-gotten-wrong fact about this pipeline:
#     EA_Dist       -> Ennead-Architects-LLP   (PUBLIC; end users pull main.zip from it)
#     EA_Dist_Lite  -> EnneadTab-EcoSystem
# A count-based check (`len(found) >= 2`) is NOT sufficient: a stray `EA_Dist_Backup`
# directory satisfies both `startswith("EA_Dist")` and the count while the real
# target is missing. Always verify the resolved REMOTE URL.
# ---------------------------------------------------------------------------
EXPECTED_TARGETS = {
    "EA_Dist": "github.com/Ennead-Architects-LLP/EA_Dist",
    "EA_Dist_Lite": "github.com/EnneadTab-EcoSystem/EA_Dist_Lite",
}

PUBLISH_BRANCH = "main"

# Wiki ingest (the handbook channel since EI PDF upload retired) authenticates
# with WIKI_API_KEY. Source order: process env, DarkSide/.env, then Vercel
# `ennead-projects/ennead-tab-wiki` production. A missing key used to skip
# ingest and still exit 0.
WIKI_VERCEL_SCOPE = "ennead-projects"
WIKI_VERCEL_PROJECT = "ennead-tab-wiki"

# ---------------------------------------------------------------------------
# Rehearsal mode.
#
# The checks above are strict on purpose, which makes them hostile to a
# REHEARSAL: pointing the dist clones at throwaway forks trips WRONG_REMOTE,
# exactly as it should. But rehearsing a publish end-to-end against forks is the
# only way to exercise the real code path at zero blast radius, and "verified"
# has repeatedly not meant "exercised".
#
# So there is one narrow, explicit door. It is an env var read per run, never a
# committed constant and never a file that can be left lying around:
#
#   ENNEADTAB_PUBLISH_REHEARSAL_TARGETS='{"EA_Dist":"github.com/me/EA_Dist-rehearsal",
#                                         "EA_Dist_Lite":"github.com/me/EA_Dist_Lite-rehearsal"}'
#
# Design constraints this shape satisfies:
#   * ABSENT IS SAFE. Unset -> behaviour is identical to having no rehearsal code
#     at all, and the self-test proves that rather than assuming it.
#   * LOUD. Every report and every gate invocation prints a banner. A rehearsal
#     that looks like a production run is worse than no rehearsal.
#   * NARROW. It substitutes the target map only. It cannot disable a check,
#     skip a target, or loosen a predicate.
#   * PER-RUN. An env var dies with the shell. Editing the constant instead would
#     mean "remember to revert it" -- the same forget-the-flag shape that was
#     rejected when _kill_stray_git's CI guard was made unconditional.
# ---------------------------------------------------------------------------
REHEARSAL_ENV_VAR = "ENNEADTAB_PUBLISH_REHEARSAL_TARGETS"


class RehearsalConfigError(RuntimeError):
    """The rehearsal override was set but unusable. Never silently ignored."""


def rehearsal_targets():
    """Parse the rehearsal override into a target map, or return None if unset.

    Raises RehearsalConfigError on a malformed value rather than falling back to
    production targets. A typo'd override that silently published to the real
    distribution would be the worst possible failure of this feature.
    """
    raw = os.environ.get(REHEARSAL_ENV_VAR)
    if not raw or not raw.strip():
        return None

    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise RehearsalConfigError(
            "{} is set but is not valid JSON ({}). Refusing to fall back to the "
            "production targets.".format(REHEARSAL_ENV_VAR, exc))

    if not isinstance(parsed, dict) or not parsed:
        raise RehearsalConfigError(
            "{} must be a non-empty JSON object mapping target name -> remote.".format(
                REHEARSAL_ENV_VAR))

    unknown = sorted(set(parsed) - set(EXPECTED_TARGETS))
    if unknown:
        raise RehearsalConfigError(
            "{} names unknown target(s): {}. Valid names: {}.".format(
                REHEARSAL_ENV_VAR, ", ".join(unknown), ", ".join(sorted(EXPECTED_TARGETS))))

    missing = sorted(set(EXPECTED_TARGETS) - set(parsed))
    if missing:
        raise RehearsalConfigError(
            "{} omits target(s): {}. A partial override would rehearse some targets "
            "while pointing the rest at PRODUCTION.".format(
                REHEARSAL_ENV_VAR, ", ".join(missing)))

    resolved = {name: normalize_remote(url) for name, url in parsed.items()}

    collisions = sorted(n for n in resolved if resolved[n] == EXPECTED_TARGETS[n])
    if collisions:
        raise RehearsalConfigError(
            "{} points {} at the PRODUCTION remote. That is not a rehearsal.".format(
                REHEARSAL_ENV_VAR, ", ".join(collisions)))

    return resolved


def active_targets():
    """The target map this run must verify against."""
    return rehearsal_targets() or EXPECTED_TARGETS


def is_rehearsal():
    return rehearsal_targets() is not None


def rehearsal_banner(targets):
    return "\n".join([
        "*" * 78,
        "*** REHEARSAL MODE -- publish targets are OVERRIDDEN.",
        "*** This is NOT the production distribution. Nothing published here",
        "*** reaches the fleet.",
        "***   " + "\n***   ".join(
            "{} -> {}".format(name, targets[name]) for name in sorted(targets)),
        "*" * 78,
    ])


class Problem(object):
    """A single reason the publish must not proceed."""

    def __init__(self, code, target, detail):
        self.code = code
        self.target = target
        self.detail = detail

    def __str__(self):
        where = " [{}]".format(self.target) if self.target else ""
        return "{}{}: {}".format(self.code, where, self.detail)

    def as_dict(self):
        return {"code": self.code, "target": self.target, "detail": self.detail}


def _git(repo, *args, **kwargs):
    """Run a git command in `repo`. Returns (returncode, stdout, stderr)."""
    timeout = kwargs.pop("timeout", 120)
    proc = subprocess.run(
        ["git"] + list(args),
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def normalize_remote(url):
    """Reduce a git remote URL to `host/owner/repo` for comparison.

    Handles https, ssh (git@host:owner/repo), trailing .git, and trailing slashes.
    """
    if not url:
        return ""
    u = url.strip()
    for prefix in ("https://", "http://", "ssh://"):
        if u.startswith(prefix):
            u = u[len(prefix):]
            break
    else:
        if u.startswith("git@"):
            u = u[len("git@"):].replace(":", "/", 1)
    if "@" in u.split("/")[0]:
        # strip creds like user:token@host
        u = u.split("@", 1)[1]
    if u.endswith(".git"):
        u = u[: -len(".git")]
    return u.rstrip("/")


def discover_dist_repos(os_repo_folder):
    """Find distribution repos as siblings of the OS repo folder.

    Mirrors the discovery rule in `________publish.py` (`_dist_repo_folders`):
    scan the PARENT directory for entries starting with "EA_Dist". Lite sorts first.

    This is the function `________publish.py` should call, so the rule lives in
    exactly one place.
    """
    parent = os.path.dirname(os.path.abspath(os_repo_folder))
    found = []
    try:
        for name in sorted(os.listdir(parent)):
            full = os.path.join(parent, name)
            if name.startswith("EA_Dist") and os.path.isdir(full):
                found.append(full)
    except OSError as exc:
        raise RuntimeError("Cannot scan {} for dist repos: {}".format(parent, exc))
    found.sort(key=lambda p: 0 if "lite" in os.path.basename(p).lower() else 1)
    return found


def inspect_target(path, fetch=True):
    """Gather the publish-safety facts for one dist repo clone. Read-only."""
    name = os.path.basename(path.rstrip("\\/"))
    info = {
        "name": name,
        "path": path,
        "remote": None,
        "remote_normalized": None,
        "head": None,
        "origin_head": None,
        "behind": None,
        "ahead": None,
        "is_ancestor_of_origin": None,
        "dirty": None,
        "fetch_ok": None,
    }

    rc, out, _ = _git(path, "remote", "get-url", "origin")
    if rc == 0:
        info["remote"] = out
        info["remote_normalized"] = normalize_remote(out)

    if fetch:
        # gc.auto=0 is load-bearing. A fetch on EA_Dist otherwise triggers
        # `git gc --auto` -> pack-objects across ~11 GB, which exceeds this
        # timeout and can drop the publisher box below the 5 GB free-disk gate
        # (post-#124 rehearsal: fetch timed out at 300s, retries then died on
        # 3.3 GB free). ls-remote is used for push-landing; this fetch still
        # has to run so a stale clone is rejected before the force-push.
        rc, _, err = _git(
            path, "-c", "gc.auto=0", "fetch", "origin", PUBLISH_BRANCH,
            timeout=900,
        )
        info["fetch_ok"] = rc == 0
        if rc != 0:
            info["fetch_error"] = err

    rc, out, _ = _git(path, "rev-parse", "HEAD")
    if rc == 0:
        info["head"] = out
    rc, out, _ = _git(path, "rev-parse", "origin/{}".format(PUBLISH_BRANCH))
    if rc == 0:
        info["origin_head"] = out

    if info["head"] and info["origin_head"]:
        rc, out, _ = _git(
            path, "rev-list", "--left-right", "--count",
            "origin/{}...HEAD".format(PUBLISH_BRANCH),
        )
        if rc == 0 and "\t" in out:
            behind, ahead = out.split("\t")[:2]
            info["behind"] = int(behind)
            info["ahead"] = int(ahead)
        rc, _, _ = _git(
            path, "merge-base", "--is-ancestor", "HEAD",
            "origin/{}".format(PUBLISH_BRANCH),
        )
        info["is_ancestor_of_origin"] = rc == 0

    rc, out, _ = _git(path, "status", "--porcelain")
    if rc == 0:
        info["dirty"] = bool(out.strip())

    return info


def evaluate_target(info, targets=None):
    """Turn one target's facts into Problems. Predicates written from FAILURE modes.

    `targets` defaults to the PRODUCTION map, not to active_targets(), so a caller
    that forgets to thread it through fails closed against production rather than
    silently inheriting a rehearsal override from the environment.
    """
    problems = []
    name = info["name"]
    targets = EXPECTED_TARGETS if targets is None else targets

    expected = targets.get(name)
    if expected is None:
        problems.append(Problem(
            "UNEXPECTED_TARGET", name,
            "directory matches the EA_Dist* discovery rule but is not a known publish "
            "target. Publishing here would push the distribution to the wrong repo.",
        ))
        return problems

    if not info["remote_normalized"]:
        problems.append(Problem(
            "NO_REMOTE", name, "no origin remote resolved; cannot verify the push target."))
    elif info["remote_normalized"] != expected:
        problems.append(Problem(
            "WRONG_REMOTE", name,
            "origin resolves to {} but this target must be {}. A count-based check "
            "would have passed this.".format(info["remote_normalized"], expected),
        ))

    if info["fetch_ok"] is False:
        problems.append(Problem(
            "FETCH_FAILED", name,
            "could not fetch origin/{}: {}. Sync state is unknown, so a force-push "
            "would be unsafe.".format(PUBLISH_BRANCH, info.get("fetch_error", "")),
        ))

    if info["behind"]:
        problems.append(Problem(
            "STALE_CLONE", name,
            "clone is {} commit(s) BEHIND origin/{}. The publisher force-pushes without "
            "pulling, so publishing from here would DESTROY those published commits."
            .format(info["behind"], PUBLISH_BRANCH),
        ))

    if info["dirty"]:
        problems.append(Problem(
            "DIRTY_TREE", name,
            "working tree has uncommitted changes; they would be swept into the "
            "published distribution.",
        ))

    return problems


def check_ruiwriter_yaml(importer=None):
    """RuiWriter imports yaml at module load. Missing pyyaml used to skip RUI
    updates and still exit 0, so the fleet got a dist whose Rhino toolbar was
    never regenerated. Presence of the import is the predicate."""
    importer = importer or __import__
    try:
        importer("yaml")
    except ImportError:
        return [Problem(
            "MISSING_PYYAML",
            None,
            "pyyaml is not importable. RuiWriter cannot update RUI files, so a "
            "publish from this box would skip the Rhino toolbar and still exit 0. "
            "Install it on the publisher interpreter: pip install pyyaml.",
        )]
    return []


def check_wiki_requests(importer=None):
    """wiki_ingest_client POSTs with requests. Missing it used to mark
    ATTEMPTED AND FAILED then still print [OK] Publish completed successfully
    (post-#122 rehearsal). Presence of the import is the predicate."""
    importer = importer or __import__
    try:
        importer("requests")
    except ImportError:
        return [Problem(
            "MISSING_REQUESTS",
            None,
            "requests is not importable. Wiki ingest cannot POST tool data, so a "
            "publish from this box would ship the fleet and leave the wiki stale "
            "while still exiting 0. Install it on the publisher interpreter: "
            "pip install requests.",
        )]
    return []


def load_darkside_dotenv(os_repo_folder, environ=None):
    """Load DarkSide/.env into environ with setdefault (never override)."""
    environ = os.environ if environ is None else environ
    env_file = os.path.join(os.path.abspath(os_repo_folder), "DarkSide", ".env")
    if not os.path.isfile(env_file):
        return
    with open(env_file, "r") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and (
                    (value[0] == '"' and value[-1] == '"') or
                    (value[0] == "'" and value[-1] == "'")):
                value = value[1:-1]
            environ.setdefault(key.strip(), value)


def _find_vercel_executable():
    appdata = os.environ.get("APPDATA", "")
    npm_cmd = os.path.join(appdata, "npm", "vercel.cmd")
    if os.path.isfile(npm_cmd):
        return npm_cmd
    for name in ("vercel.cmd", "vercel"):
        found = shutil.which(name)
        if found and not found.lower().endswith(".ps1"):
            return found
    return None


def _parse_dotenv_value(path, name):
    if not os.path.isfile(path):
        return ""
    with open(path, "r") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() != name:
                continue
            value = value.strip()
            if len(value) >= 2 and (
                    (value[0] == '"' and value[-1] == '"') or
                    (value[0] == "'" and value[-1] == "'")):
                value = value[1:-1]
            return value
    return ""


def vercel_env_get(name, environment="production", cwd=None, runner=None):
    """Read one production env var from Vercel. Never log the value.

    CLI 50 has no `env get`. Pull production into a throwaway dir (the dump
    contains every secret), parse `name`, shred. Empty string on any failure.
    """
    if runner is not None:
        return (runner(name, environment, cwd) or "").strip()
    vercel = _find_vercel_executable()
    if not vercel:
        return ""
    work = tempfile.mkdtemp(prefix="enneadtab-wiki-env-")
    pulled = os.path.join(work, ".env.production.pull")
    try:
        link = subprocess.run(
            [vercel, "link", "--yes",
             "--scope", WIKI_VERCEL_SCOPE,
             "--project", WIKI_VERCEL_PROJECT],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if link.returncode != 0:
            return ""
        pull = subprocess.run(
            [vercel, "env", "pull", pulled,
             "--environment", environment, "--yes",
             "--scope", WIKI_VERCEL_SCOPE],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if pull.returncode != 0:
            return ""
        return _parse_dotenv_value(pulled, name)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    finally:
        shutil.rmtree(work, ignore_errors=True)


def persist_wiki_key_to_dotenv(os_repo_folder, key):
    """Write WIKI_API_KEY into DarkSide/.env if that file does not already have it."""
    if not key:
        return
    env_file = os.path.join(os.path.abspath(os_repo_folder), "DarkSide", ".env")
    if os.path.isfile(env_file):
        with open(env_file, "r") as handle:
            for line in handle:
                if line.strip().startswith("WIKI_API_KEY="):
                    return
        with open(env_file, "a") as handle:
            handle.write("\nWIKI_API_KEY={}\n".format(key))
        return
    env_dir = os.path.dirname(env_file)
    if not os.path.isdir(env_dir):
        return
    with open(env_file, "w") as handle:
        handle.write("WIKI_API_KEY={}\n".format(key))


def resolve_wiki_api_key(os_repo_folder, environ=None, vercel_fetch=None,
                         persist=False):
    """Return WIKI_API_KEY from env, DarkSide/.env, or Vercel. May set environ.

    persist=True writes the pulled key into DarkSide/.env (gitignored) so the
    next run does not need the Vercel CLI. The guard leaves persist=False.
    """
    environ = os.environ if environ is None else environ
    key = (environ.get("WIKI_API_KEY") or "").strip()
    if key:
        return key
    load_darkside_dotenv(os_repo_folder, environ=environ)
    key = (environ.get("WIKI_API_KEY") or "").strip()
    if key:
        return key
    fetch = vercel_fetch if vercel_fetch is not None else (
        lambda n, environment="production", cwd=None: vercel_env_get(
            n, environment=environment)
    )
    print("    WIKI_API_KEY not in env or DarkSide/.env; "
          "pulling from Vercel {}/{} ...".format(
              WIKI_VERCEL_SCOPE, WIKI_VERCEL_PROJECT))
    pulled = (fetch("WIKI_API_KEY") or "").strip()
    if not pulled:
        return ""
    environ["WIKI_API_KEY"] = pulled
    if persist:
        persist_wiki_key_to_dotenv(os_repo_folder, pulled)
    print("    WIKI_API_KEY pulled from Vercel (value not logged)")
    return pulled


def check_wiki_api_key(os_repo_folder, environ=None, vercel_fetch=None):
    """Missing wiki key used to skip ingest and still exit 0. Wiki is the handbook."""
    # 2026-08-12: in a rehearsal the wiki ingest is skipped outright (see
    # _generate_wiki_website's rehearsal gate), so this precondition guards a step
    # that will not run -- and satisfying it pulls the PRODUCTION key from Vercel.
    #
    # CI run 31612329379 proved the two halves are separate. The publisher-side
    # gate stopped the production wiki being written (its /api/ingest/last did not
    # move), yet the log still showed "pulling from Vercel ennead-projects/
    # ennead-tab-wiki" four minutes earlier -- from HERE, via publish_guard
    # --report. Fetching a credential the run is forbidden to use is itself the
    # leak, so the gate has to cover every caller, not just the writer.
    if is_rehearsal():
        return []
    key = resolve_wiki_api_key(
        os_repo_folder, environ=environ, vercel_fetch=vercel_fetch)
    if key:
        return []
    return [Problem(
        "MISSING_WIKI_API_KEY",
        None,
        "WIKI_API_KEY is not in the environment or DarkSide/.env, and Vercel "
        "env get from {}/{} production returned empty. Wiki ingest would skip "
        "and the handbook channel would go stale. Set the env var, put it in "
        "DarkSide/.env, or `vercel env get WIKI_API_KEY production --scope {} "
        "--project {}`.".format(
            WIKI_VERCEL_SCOPE, WIKI_VERCEL_PROJECT,
            WIKI_VERCEL_SCOPE, WIKI_VERCEL_PROJECT),
    )]


# ---------------------------------------------------------------------------
# Production assertion.
#
# The rehearsal override is checked by ABSENCE everywhere else, and absence is
# the weakest predicate there is -- it cannot tell "this run is aimed at the
# production distribution" from "this run is aimed at nothing in particular".
# run-ci-publish.ps1's first production dispatch (run 31633491120) failed on
# exactly that asymmetry: the wrapper knew how to refuse a missing rehearsal
# override and had no way at all to affirm a production one.
#
# So -Production does not SKIP the rehearsal check, it INVERTS it and then adds
# the positive half: the override must be absent AND the dist repos actually
# discovered on disk must be, name for name, the production remotes. A skipped
# check is how this class of bug starts.
# ---------------------------------------------------------------------------
def production_assertion_problems(discovered_remotes):
    """Prove this run targets PRODUCTION. Returns [] only when it provably does.

    `discovered_remotes` maps target name -> normalized remote as found on disk
    (see normalize_remote). Pure, so the self-test can drive it with fixtures
    instead of only ever watching it pass against the one real machine.
    """
    try:
        override = rehearsal_targets()
    except RehearsalConfigError as exc:
        # Malformed is NOT "absent". Treating an unparseable override as unset
        # is the fall-back-to-production shape rehearsal_targets() refuses.
        return [Problem(
            "PRODUCTION_REHEARSAL_SET", None,
            "{} is set but unusable ({}). A production publish requires it "
            "ABSENT, not merely unreadable.".format(REHEARSAL_ENV_VAR, exc))]

    if override is not None:
        return [Problem(
            "PRODUCTION_REHEARSAL_SET", None,
            "{} is set ({}). A production publish with a rehearsal override "
            "would ship to the forks and still report success -- the fleet "
            "goes stale behind a green check.".format(
                REHEARSAL_ENV_VAR,
                ", ".join("{} -> {}".format(n, override[n]) for n in sorted(override))))]

    problems = []
    for name in sorted(EXPECTED_TARGETS):
        expected = EXPECTED_TARGETS[name]
        actual = discovered_remotes.get(name)
        if name not in discovered_remotes:
            problems.append(Problem(
                "PRODUCTION_TARGET_MISSING", name,
                "not discovered as a sibling of the publish tree. Publishing "
                "would ship a PARTIAL distribution; expected {}.".format(expected)))
        elif not actual:
            # The folder IS there. Saying "not discovered" would send the next
            # operator hunting for a directory they are looking straight at.
            problems.append(Problem(
                "PRODUCTION_TARGET_NO_REMOTE", name,
                "is present but has no origin remote, so nothing can prove it is "
                "{}. A tree with no remote cannot be published to.".format(expected)))
        elif actual != expected:
            problems.append(Problem(
                "PRODUCTION_TARGET_MISMATCH", name,
                "resolves to {} but production is {}. A force-push goes where "
                "origin points, not where the caller intended.".format(actual, expected)))

    for name in sorted(discovered_remotes):
        if name not in EXPECTED_TARGETS:
            problems.append(Problem(
                "PRODUCTION_UNEXPECTED_TARGET", name,
                "is a dist sibling that is not a production target ({}). The "
                "publisher force-pushes every EA_Dist* sibling it finds.".format(
                    discovered_remotes[name] or "<no remote>")))

    return problems


def assert_production(os_repo_folder):
    """--assert-production: affirm the publish tree is aimed at production.

    Read-only. Fetches nothing -- only the configured remote matters here, and
    sync/dirty state is --report's job.
    """
    print("=" * 78)
    print("PRODUCTION ASSERTION -- read-only. Nothing is pushed, reset, or committed.")
    print("=" * 78)
    print("OS repo: {}".format(os_repo_folder))

    discovered = {}
    try:
        found = discover_dist_repos(os_repo_folder)
    except RuntimeError as exc:
        print("\nPRODUCTION ASSERTION FAILED:\n\n  * DISCOVERY_FAILED: {}".format(exc))
        return 1

    for path in found:
        info = inspect_target(path, fetch=False)
        discovered[info["name"]] = info["remote_normalized"]

    for name in sorted(discovered):
        print("  {:<14} -> {}".format(name, discovered[name] or "<no remote>"))

    problems = production_assertion_problems(discovered)
    print("-" * 78)
    if problems:
        print("PRODUCTION ASSERTION FAILED -- {} problem(s):\n".format(len(problems)))
        for problem in problems:
            print("  * {}".format(problem))
        print("\nThis tree must NOT be used for a production publish.")
        return 1

    print("PRODUCTION CONFIRMED -- {} is absent and every dist sibling resolves "
          "to its production remote.".format(REHEARSAL_ENV_VAR))
    return 0


def verify_publish_preconditions(os_repo_folder, fetch=True):
    """The gate. Returns (problems, target_infos). Empty problems == safe to publish."""
    problems = []
    infos = []

    # Resolve the target map FIRST. A malformed override is a hard stop, never a
    # quiet fall-back to production -- it is reported as a Problem so it travels
    # through the caller's normal abort path.
    try:
        targets = active_targets()
    except RehearsalConfigError as exc:
        return [Problem("REHEARSAL_CONFIG_INVALID", None, str(exc))], []

    problems.extend(check_ruiwriter_yaml())
    problems.extend(check_wiki_requests())
    problems.extend(check_wiki_api_key(os_repo_folder))

    if targets is not EXPECTED_TARGETS:
        print(rehearsal_banner(targets))

    try:
        found = discover_dist_repos(os_repo_folder)
    except RuntimeError as exc:
        problems.append(Problem("DISCOVERY_FAILED", None, str(exc)))
        return problems, []

    found_names = {os.path.basename(p.rstrip("\\/")) for p in found}
    for expected_name in targets:
        if expected_name not in found_names:
            problems.append(Problem(
                "MISSING_TARGET", expected_name,
                "not found as a sibling of {}. The publisher treats empty/partial "
                "discovery as non-fatal, so this would publish a PARTIAL distribution "
                "and still report success.".format(os_repo_folder),
            ))

    for path in found:
        info = inspect_target(path, fetch=fetch)
        infos.append(info)
        problems.extend(evaluate_target(info, targets))

    return problems, infos


# ---------------------------------------------------------------------------
# Self-test: prove the predicates can REJECT. A guard that has only ever been
# seen to pass is indistinguishable from a guard that cannot fail.
# ---------------------------------------------------------------------------
def _self_test():
    cases = [
        ("stale clone is rejected",
         {"name": "EA_Dist_Lite", "remote_normalized": EXPECTED_TARGETS["EA_Dist_Lite"],
          "behind": 2, "ahead": 0, "dirty": False, "fetch_ok": True}, "STALE_CLONE"),
        ("wrong org on EA_Dist is rejected",
         {"name": "EA_Dist", "remote_normalized": "github.com/EnneadTab-EcoSystem/EA_Dist",
          "behind": 0, "ahead": 0, "dirty": False, "fetch_ok": True}, "WRONG_REMOTE"),
        ("EA_Dist_Backup is rejected as an unexpected target",
         {"name": "EA_Dist_Backup", "remote_normalized": "github.com/zsenarchitect/EA_Dist_Backup",
          "behind": 0, "ahead": 0, "dirty": False, "fetch_ok": True}, "UNEXPECTED_TARGET"),
        ("dirty tree is rejected",
         {"name": "EA_Dist", "remote_normalized": EXPECTED_TARGETS["EA_Dist"],
          "behind": 0, "ahead": 0, "dirty": True, "fetch_ok": True}, "DIRTY_TREE"),
        ("failed fetch is rejected",
         {"name": "EA_Dist", "remote_normalized": EXPECTED_TARGETS["EA_Dist"],
          "behind": None, "ahead": None, "dirty": False, "fetch_ok": False,
          "fetch_error": "network down"}, "FETCH_FAILED"),
        ("missing remote is rejected",
         {"name": "EA_Dist", "remote_normalized": None,
          "behind": 0, "ahead": 0, "dirty": False, "fetch_ok": True}, "NO_REMOTE"),
    ]

    rejected = 0
    failures = []
    for label, info, expected_code in cases:
        codes = [p.code for p in evaluate_target(info)]
        if expected_code in codes:
            rejected += 1
            print("  PASS  {} -> {}".format(label, expected_code))
        else:
            failures.append(label)
            print("  FAIL  {} -> expected {}, got {}".format(label, expected_code, codes or "NOTHING"))

    # A good clone must be ACCEPTED, or the guard is just a constant `reject`.
    good = {"name": "EA_Dist", "remote_normalized": EXPECTED_TARGETS["EA_Dist"],
            "behind": 0, "ahead": 0, "dirty": False, "fetch_ok": True}
    good_problems = evaluate_target(good)
    if good_problems:
        failures.append("a healthy clone was wrongly rejected")
        print("  FAIL  healthy clone accepted -> got {}".format([p.code for p in good_problems]))
    else:
        print("  PASS  healthy clone is accepted")

    print("\nrejected {}/{} known-bad fixtures".format(rejected, len(cases)))

    # --- rehearsal-override fixtures ---------------------------------------
    # Two things must hold, and the SECOND is the one worth testing: the override
    # must be provably INERT when unset. A feature that only ever gets exercised
    # in its "on" state is how an accidental production publish happens.
    print("\nrehearsal override:")
    saved = os.environ.get(REHEARSAL_ENV_VAR)
    try:
        os.environ.pop(REHEARSAL_ENV_VAR, None)
        if active_targets() is EXPECTED_TARGETS and not is_rehearsal():
            print("  PASS  unset -> production targets, byte-identical behaviour")
        else:
            failures.append("override unset did not resolve to production targets")
            print("  FAIL  unset -> did NOT resolve to production targets")

        fork = {"EA_Dist": "github.com/tester/EA_Dist-rehearsal",
                "EA_Dist_Lite": "github.com/tester/EA_Dist_Lite-rehearsal"}
        os.environ[REHEARSAL_ENV_VAR] = json.dumps(fork)
        targets = active_targets()

        prod_info = {"name": "EA_Dist", "remote_normalized": EXPECTED_TARGETS["EA_Dist"],
                     "behind": 0, "ahead": 0, "dirty": False, "fetch_ok": True}
        prod_codes = [p.code for p in evaluate_target(prod_info, targets)]
        if "WRONG_REMOTE" in prod_codes:
            print("  PASS  set -> the PRODUCTION remote is now rejected")
        else:
            failures.append("with an override set, the production remote was not rejected")
            print("  FAIL  set -> production remote accepted, got {}".format(prod_codes or "NOTHING"))

        fork_info = dict(prod_info, remote_normalized=fork["EA_Dist"])
        fork_codes = [p.code for p in evaluate_target(fork_info, targets)]
        if not fork_codes:
            print("  PASS  set -> the rehearsal remote is accepted")
        else:
            failures.append("rehearsal remote was rejected under its own override")
            print("  FAIL  set -> rehearsal remote rejected: {}".format(fork_codes))

        # Malformed / partial / production-pointing overrides must RAISE, never
        # quietly degrade to publishing at production.
        bad_cases = [
            ("not JSON", "{nope"),
            ("empty object", "{}"),
            ("unknown target name", json.dumps({"EA_Dist_Typo": "github.com/t/x"})),
            ("partial override", json.dumps({"EA_Dist": "github.com/t/x"})),
            ("points at production",
             json.dumps({"EA_Dist": "https://github.com/Ennead-Architects-LLP/EA_Dist.git",
                         "EA_Dist_Lite": "github.com/t/y"})),
        ]
        for label, value in bad_cases:
            os.environ[REHEARSAL_ENV_VAR] = value
            try:
                active_targets()
            except RehearsalConfigError:
                print("  PASS  rejected bad override ({})".format(label))
            else:
                failures.append("bad override accepted: {}".format(label))
                print("  FAIL  accepted bad override ({})".format(label))
    finally:
        if saved is None:
            os.environ.pop(REHEARSAL_ENV_VAR, None)
        else:
            os.environ[REHEARSAL_ENV_VAR] = saved

    # --- production assertion -------------------------------------------------
    # The mirror image of the block above. That one proves the override is inert
    # when unset; this one proves that "unset" alone is NOT accepted as evidence
    # of a production run -- the remotes on disk have to say so too.
    print("\nproduction assertion:")
    prod_pair = {"EA_Dist": EXPECTED_TARGETS["EA_Dist"],
                 "EA_Dist_Lite": EXPECTED_TARGETS["EA_Dist_Lite"]}
    saved_prod = os.environ.get(REHEARSAL_ENV_VAR)
    try:
        os.environ.pop(REHEARSAL_ENV_VAR, None)
        prod_cases = [
            ("rehearsal override set is rejected",
             json.dumps({"EA_Dist": "github.com/tester/EA_Dist-rehearsal",
                         "EA_Dist_Lite": "github.com/tester/EA_Dist_Lite-rehearsal"}),
             prod_pair, "PRODUCTION_REHEARSAL_SET"),
            ("malformed override is rejected, not read as absent",
             "{nope", prod_pair, "PRODUCTION_REHEARSAL_SET"),
            ("a missing dist sibling is rejected",
             None, {"EA_Dist": EXPECTED_TARGETS["EA_Dist"]}, "PRODUCTION_TARGET_MISSING"),
            ("a sibling with no remote is rejected AS SUCH, not as missing",
             None, dict(prod_pair, EA_Dist=None), "PRODUCTION_TARGET_NO_REMOTE"),
            ("the rehearsal tree is rejected",
             None, {"EA_Dist": "github.com/zsenarchitect/EA_Dist-rehearsal",
                    "EA_Dist_Lite": "github.com/zsenarchitect/EA_Dist_Lite-rehearsal"},
             "PRODUCTION_TARGET_MISMATCH"),
            ("an extra dist sibling is rejected",
             None, dict(prod_pair, EA_Dist_Backup="github.com/zsenarchitect/EA_Dist_Backup"),
             "PRODUCTION_UNEXPECTED_TARGET"),
        ]
        prod_rejected = 0
        for label, override, remotes, expected_code in prod_cases:
            if override is None:
                os.environ.pop(REHEARSAL_ENV_VAR, None)
            else:
                os.environ[REHEARSAL_ENV_VAR] = override
            codes = [p.code for p in production_assertion_problems(remotes)]
            if expected_code in codes:
                prod_rejected += 1
                print("  PASS  {} -> {}".format(label, expected_code))
            else:
                failures.append("production assertion accepted: {}".format(label))
                print("  FAIL  {} -> expected {}, got {}".format(
                    label, expected_code, codes or "NOTHING"))

        # And it must ACCEPT the real thing, or -Production could never publish.
        os.environ.pop(REHEARSAL_ENV_VAR, None)
        real = production_assertion_problems(prod_pair)
        if not real:
            print("  PASS  override absent + production remotes is accepted")
        else:
            failures.append("the real production configuration was rejected")
            print("  FAIL  production config rejected -> {}".format(
                [p.code for p in real]))
        print("\nrejected {}/{} known-bad production fixtures".format(
            prod_rejected, len(prod_cases)))
    finally:
        if saved_prod is None:
            os.environ.pop(REHEARSAL_ENV_VAR, None)
        else:
            os.environ[REHEARSAL_ENV_VAR] = saved_prod

    # --- RuiWriter yaml -------------------------------------------------------
    print("\npyyaml:")
    def _yaml_missing(_name):
        raise ImportError("No module named 'yaml'")
    missing_yaml = check_ruiwriter_yaml(importer=_yaml_missing)
    if missing_yaml and missing_yaml[0].code == "MISSING_PYYAML":
        print("  PASS  missing import -> MISSING_PYYAML")
    else:
        failures.append("missing pyyaml was not rejected")
        print("  FAIL  missing import -> got {}".format(
            [p.code for p in missing_yaml] or "NOTHING"))
    present_yaml = check_ruiwriter_yaml(importer=lambda _name: None)
    if not present_yaml:
        print("  PASS  importable yaml is accepted")
    else:
        failures.append("importable yaml was wrongly rejected")
        print("  FAIL  present import -> got {}".format(
            [p.code for p in present_yaml]))

    # --- wiki ingest requests -------------------------------------------------
    print("\nrequests:")
    def _requests_missing(_name):
        raise ImportError("No module named 'requests'")
    missing_requests = check_wiki_requests(importer=_requests_missing)
    if missing_requests and missing_requests[0].code == "MISSING_REQUESTS":
        print("  PASS  missing import -> MISSING_REQUESTS")
    else:
        failures.append("missing requests was not rejected")
        print("  FAIL  missing import -> got {}".format(
            [p.code for p in missing_requests] or "NOTHING"))
    present_requests = check_wiki_requests(importer=lambda _name: None)
    if not present_requests:
        print("  PASS  importable requests is accepted")
    else:
        failures.append("importable requests was wrongly rejected")
        print("  FAIL  present import -> got {}".format(
            [p.code for p in present_requests]))

    # --- wiki API key ---------------------------------------------------------
    print("\nwiki api key:")
    missing_wiki = check_wiki_api_key(
        os.path.join("C:\\", "no-such-publisher-repo"),
        environ={},
        vercel_fetch=lambda *_args, **_kwargs: "",
    )
    if missing_wiki and missing_wiki[0].code == "MISSING_WIKI_API_KEY":
        print("  PASS  missing key -> MISSING_WIKI_API_KEY")
    else:
        failures.append("missing WIKI_API_KEY was not rejected")
        print("  FAIL  missing key -> got {}".format(
            [p.code for p in missing_wiki] or "NOTHING"))
    from_env = check_wiki_api_key(
        os.path.join("C:\\", "no-such-publisher-repo"),
        environ={"WIKI_API_KEY": "from-env"},
        vercel_fetch=lambda *_args, **_kwargs: "",
    )
    if not from_env:
        print("  PASS  env var is accepted")
    else:
        failures.append("present WIKI_API_KEY was wrongly rejected")
        print("  FAIL  env var -> got {}".format([p.code for p in from_env]))
    from_vercel = check_wiki_api_key(
        os.path.join("C:\\", "no-such-publisher-repo"),
        environ={},
        vercel_fetch=lambda *_args, **_kwargs: "from-vercel",
    )
    if not from_vercel:
        print("  PASS  Vercel pull is accepted")
    else:
        failures.append("Vercel-pulled WIKI_API_KEY was wrongly rejected")
        print("  FAIL  vercel pull -> got {}".format(
            [p.code for p in from_vercel]))

    if failures:
        print("\nSELF-TEST FAILED: {}".format("; ".join(failures)))
        return 1
    print("\nSELF-TEST PASSED")
    return 0


def _default_os_repo():
    # publish_guard.py lives in <repo>/DarkSide/publish/
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--report", action="store_true",
                        help="inspect the real clones and report publish safety")
    parser.add_argument("--self-test", action="store_true",
                        help="prove the predicates reject known-bad fixtures")
    parser.add_argument("--assert-production", action="store_true",
                        help="exit 0 only if this tree provably targets the "
                             "PRODUCTION distribution (rehearsal override absent "
                             "AND every dist sibling on its production remote)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip the fetch (sync state will be reported as unknown)")
    parser.add_argument("--os-repo", default=None, help="path to the EnneadTab-OS clone")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    if args.assert_production:
        return assert_production(args.os_repo or _default_os_repo())

    if not args.report:
        parser.print_help()
        return 2

    os_repo = args.os_repo or _default_os_repo()

    # Resolved separately from the gate only so the report can LABEL each target.
    # A broken override still fails inside the gate below; this must not swallow it.
    try:
        display_targets = active_targets()
        rehearsing = display_targets is not EXPECTED_TARGETS
    except RehearsalConfigError:
        display_targets = EXPECTED_TARGETS
        rehearsing = False

    problems, infos = verify_publish_preconditions(os_repo, fetch=not args.no_fetch)

    if args.json:
        print(json.dumps({
            "os_repo": os_repo,
            "rehearsal": rehearsing,
            "safe_to_publish": (not problems) and not rehearsing,
            "rehearsal_targets_ok": (not problems) and rehearsing,
            "problems": [p.as_dict() for p in problems],
            "targets": infos,
        }, indent=2))
        return 1 if problems else 0

    print("=" * 78)
    print("PUBLISH GUARD -- read-only. Nothing is pushed, reset, or committed.")
    print("=" * 78)
    print("OS repo: {}".format(os_repo))
    print("Scanned for EA_Dist* siblings in: {}\n".format(os.path.dirname(os_repo)))

    if not infos:
        print("  (no distribution repositories discovered)")
    for info in infos:
        print("  {}".format(info["name"]))
        print("    path      : {}".format(info["path"]))
        print("    remote    : {}".format(info["remote"] or "<none>"))
        print("    expected  : {}".format(display_targets.get(info["name"], "<not a known target>")))
        print("    HEAD      : {}".format((info["head"] or "?")[:12]))
        print("    origin/{}: {}".format(PUBLISH_BRANCH, (info["origin_head"] or "?")[:12]))
        print("    behind/ahead: {}/{}".format(info["behind"], info["ahead"]))
        print("    dirty     : {}".format(info["dirty"]))
        print("")

    print("-" * 78)
    if problems:
        print("UNSAFE TO PUBLISH -- {} problem(s):\n".format(len(problems)))
        for p in problems:
            print("  * {}".format(p))
        print("\nNo publish should run until these are resolved.")
        return 1

    if rehearsing:
        # Deliberately NOT the same sentence as the production path. A rehearsal
        # that reports identically to a real run is the false-signal class this
        # guard exists to prevent -- someone would screenshot it as proof the
        # production distribution was verified.
        print("REHEARSAL TARGETS OK -- all overridden targets present, remotes verified, "
              "clones current, trees clean.")
        print("This says NOTHING about the production distribution.")
        return 0

    print("SAFE TO PUBLISH -- all expected targets present, remotes verified, "
          "clones current, trees clean.")
    return 0


def main_never_silent(argv=None):
    """Run main(), but guarantee a refusal is never output-free.

    On 2026-08-21 production run 32511676656 refused with literally this, and nothing
    else:

        publish_guard --report:
        CI PUBLISH REFUSED: publish_guard exited 1

    No banner, no problem list, no traceback. The banner is printed UNCONDITIONALLY on
    the report path, so zero output proves the process died BEFORE it -- inside
    verify_publish_preconditions -- and the traceback went to a stderr the caller
    discarded. PR #195 fixed the caller. This fixes the other half, at the source: an
    exception here now explains itself on STDOUT regardless of how any caller, now or
    later, handles streams. A guard whose entire job is to say WHY a publish was refused
    must never exit without saying it.

    The fleet went stale behind that silence -- PR #192 merged, its publish refused,
    nobody could tell why, and the condition then cleared on its own. A self-clearing
    failure with no diagnostic is unfindable after the fact, which is what makes the
    reporting fix urgent rather than cosmetic.

    NOTE: this does NOT explain the 2026-08-21 refusal. That root cause is still UNKNOWN
    and senzhang-todo #4661 stays open on it. This only guarantees the next occurrence
    arrives with evidence attached.

    SystemExit passes through untouched -- argparse uses it for --help and for usage
    errors, and those are not crashes.
    """
    try:
        return main(argv)
    except SystemExit:
        raise
    except BaseException as exc:
        # STDOUT on purpose: stderr is the stream that was thrown away.
        print("=" * 78)
        print("PUBLISH GUARD CRASHED before it could report -- {}: {}".format(
            type(exc).__name__, exc))
        print("This is a guard failure, NOT a verdict on the distribution. Nothing was "
              "verified, so nothing may be assumed safe to publish.")
        print("=" * 78)
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        return 1


if __name__ == "__main__":
    sys.exit(main_never_silent())
