# -*- coding: utf-8 -*-
"""Pre-publish IronPython 2.7 compile gate (senzhang-todo TODO-7728).

Compiles every shipping IronPython file with a real IronPython 2.7 interpreter and
refuses the publish when an Apps/_revit or Apps/_rhino file will not compile.

WHY IT EXISTS AGAIN. The legacy RepoPublisher ran this gate
(_validate_shipping_python_syntax). The 2026-08-18 move to the stage pipeline
(PR #176) never ported it: stage_01 kept locating ipy.exe and then did nothing with
it, so from 2026-08-18 the fleet shipped with only the diff-scoped static lint
(tools/check_ironpython.py --diff) in front of it. The dead copy was deleted in
PR #382; this is the port.

WHY IronPython AND NOT CPython. The shipped code runs under IronPython 2.7. CPython 3
false-rejects valid Py2 idioms (print statement, `except X, e`) and false-accepts the
exact Py3-only syntax (f-strings, annotations) this gate exists to catch.

SCOPE IS NOT DECIDED HERE. tools/check_ironpython.py already owns "is this file
IronPython" (is_ironpython_target) and tools/.ironpython_lint_allowlist owns "which
known violators are grandfathered". This module consumes both answers. Two mechanisms
answering the same question and disagreeing is how the legacy gate aborted on 19 files
on its first real run (2026-08-07).

THREE OUTCOMES PER FILE
  HARD     Apps/_revit, Apps/_rhino, not allowlisted -> blocks the publish.
  SOFT     everything else in scope (Apps/lib/EnneadTab...) -> warned, not blocking;
           that tree ships genuine CPython-only helpers.
  ALLOWED  allowlisted -> compiled anyway and listed loudly, never blocking.

WHAT IT NEVER DOES
  * Fall back to CPython when no IronPython is found. It skips and says so, and the
    stage is reported DEGRADED, so the skip shows in the publish summary and on GitHub.
  * Pass a run that compiled zero files. The tree has ~950; zero means the scope broke.
"""

import importlib.util
import os
import subprocess
import tempfile

from .stage_base import PublishStageError
from .stages.stage_04_stage_dist import path_excluded_from_target

HARD_PREFIXES = ("Apps/_revit/", "Apps/_rhino/")
GATE_TIMEOUT_SECONDS = 900

# Py2-safe: IronPython runs this. It compiles exactly the paths it is handed, one per
# line in a list file (thousands of paths would blow the ~32 KB Windows argv limit).
# Ported unchanged from the legacy gate, including the rstrip-then-newline fix: Py2
# compile() needs source ending in a newline, and a whitespace-only last line without
# one raises a bogus "unindent does not match" (two shipping files hit it 2026-08-07).
WALKER_SRC = (
    "import sys\n"
    "lf = open(sys.argv[1], 'rb')\n"
    "paths = lf.read().split('\\n')\n"
    "lf.close()\n"
    "for p in paths:\n"
    "    p = p.strip()\n"
    "    if not p:\n"
    "        continue\n"
    "    try:\n"
    "        f = open(p, 'rb')\n"
    "        src = f.read()\n"
    "        f.close()\n"
    "    except Exception, e:\n"
    "        sys.stdout.write('UNREADABLE\\t' + p + '\\t' + str(e) + '\\n')\n"
    "        continue\n"
    "    if src[:3] == '\\xef\\xbb\\xbf':\n"
    "        src = src[3:]\n"
    "    src = src.replace('\\r\\n', '\\n').replace('\\r', '\\n')\n"
    "    src = src.rstrip() + '\\n'\n"
    "    try:\n"
    "        compile(src, p, 'exec')\n"
    "    except SyntaxError, e:\n"
    "        sys.stdout.write('SYNTAXERR\\t' + p + '\\t' + str(e) + '\\n')\n"
    "    except Exception, e:\n"
    "        sys.stdout.write('UNREADABLE\\t' + p + '\\t' + str(e) + '\\n')\n"
)


def _load_checker(repo_root):
    checker_path = os.path.join(repo_root, "tools", "check_ironpython.py")
    spec = importlib.util.spec_from_file_location("_ennead_ironpython_scope", checker_path)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    return checker


def skip_reason(absolute, rel, checker):
    """Why a file in IronPython scope is still not compiled here, or None.

    * Never shipped: stage_04 excludes it from every dist (e.g. DuckMaker.extension),
      so the fleet never loads it. Same function stage_04 uses, so the two cannot drift.
    * `#! python3` shebang: the file declares it runs on CPython 3 (pyRevit / Rhino 8
      honor this), and tools/check_ironpython.py skips it for exactly that reason
      (PY3_SHEBANG_RE). Compiling it with IronPython would be the wrong oracle. The
      first rehearsal of this gate (2026-10-07) refused four such files before this
      skip existed, none of them actually broken.
    """
    if path_excluded_from_target(rel, is_lite=False):
        return "not shipped"
    shebang_re = getattr(checker, "PY3_SHEBANG_RE", None)
    if shebang_re is not None:
        try:
            with open(absolute, "rb") as fh:
                first = fh.readline().decode("ascii", errors="replace")
        except OSError:
            return None  # let the walker report it as unreadable
        if shebang_re.match(first):
            return "python3 shebang"
    return None


def file_plan(repo_root, checker=None, skipped=None):
    """Return (hard, soft, allowed) absolute paths under <repo_root>/Apps.

    is_ironpython_target() takes a REPO-RELATIVE, forward-slashed path, so the base
    must be repo_root, never the process cwd: a wrong base classifies everything out
    of scope and the gate checks nothing (run_gate refuses an empty plan for that).

    load_allowlist() returns (entries, errors). The legacy gate tested `rel in
    allowlist` against that whole tuple, which is never true, so after the allowlist
    gained its reason/date format every grandfathered file would have been HARD.
    Unpack it.

    Files skip_reason() rejects are left out; pass a list as `skipped` to collect
    (path, reason) for them.
    """
    if checker is None:
        checker = _load_checker(repo_root)
    entries, _errors = checker.load_allowlist()
    allowlisted = set(entries)

    hard, soft, allowed = [], [], []
    apps_root = os.path.join(repo_root, "Apps")
    for dirpath, dirnames, filenames in os.walk(apps_root):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git", ".venv")]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            absolute = os.path.join(dirpath, filename)
            rel = os.path.relpath(absolute, repo_root).replace("\\", "/")
            if not checker.is_ironpython_target(rel):
                continue
            reason = skip_reason(absolute, rel, checker)
            if reason:
                if skipped is not None:
                    skipped.append((absolute, reason))
                continue
            if rel in allowlisted:
                allowed.append(absolute)
            elif rel.startswith(HARD_PREFIXES):
                hard.append(absolute)
            else:
                soft.append(absolute)
    return hard, soft, allowed


def classify_output(stdout, hard_paths, allowed_paths):
    """Sort the walker's SYNTAXERR / UNREADABLE lines into buckets.

    Returns a dict of lists of (path, message): hard, soft, allowed, unreadable.
    Anything not known as hard or allowed counts as soft, so an unexpected path can
    only ever warn, never block on a misclassification.
    """
    def _norm(path):
        return os.path.normcase(os.path.abspath(path))

    hard_set = set(_norm(p) for p in hard_paths)
    allowed_set = set(_norm(p) for p in allowed_paths)
    out = {"hard": [], "soft": [], "allowed": [], "unreadable": []}
    for line in (stdout or "").splitlines():
        if line.startswith("SYNTAXERR\t"):
            parts = line.split("\t", 2)[1:]
            path = parts[0] if parts else "?"
            entry = (path, parts[1] if len(parts) > 1 else "")
            key = _norm(path)
            if key in allowed_set:
                out["allowed"].append(entry)
            elif key in hard_set:
                out["hard"].append(entry)
            else:
                out["soft"].append(entry)
        elif line.startswith("UNREADABLE\t"):
            parts = line.split("\t", 2)[1:]
            out["unreadable"].append((parts[0] if parts else "?",
                                      parts[1] if len(parts) > 1 else ""))
    return out


def run_gate(repo_root, ipy_exe, checker=None, timeout=GATE_TIMEOUT_SECONDS):
    """Run the gate.

    Returns None when it ran and passed, or a non-empty reason string when it could
    not run (the caller reports that as DEGRADED). Raises PublishStageError when a
    HARD file fails to compile, or when the scope resolved to zero files.
    """
    print("Validating Python syntax of shipping trees under IronPython 2.7...")
    skipped = []
    try:
        hard_paths, soft_paths, allowed_paths = file_plan(repo_root, checker, skipped)
    except Exception as exc:
        return ("IronPython compile gate SKIPPED: could not compute its scope ({}: {}). "
                "Shipping trees were NOT compile-checked.".format(type(exc).__name__, exc))

    to_check = hard_paths + soft_paths + allowed_paths
    print("    Scope: {} hard (_revit/_rhino), {} soft, {} grandfathered -- "
          "{} file(s); {} skipped ({} python3 shebang, {} not shipped).".format(
              len(hard_paths), len(soft_paths), len(allowed_paths), len(to_check),
              len(skipped), sum(1 for _, r in skipped if r == "python3 shebang"),
              sum(1 for _, r in skipped if r == "not shipped")))
    if not to_check:
        raise PublishStageError(
            "IronPython compile gate resolved ZERO files. The tree has ~950, so the "
            "scope is broken; refusing to publish an unchecked tree behind a pass.")

    if not ipy_exe:
        return ("IronPython compile gate SKIPPED: no IronPython 2.7 interpreter found "
                "(set ENNEADTAB_IRONPYTHON_EXE). Shipping trees were NOT compile-checked; "
                "only the diff-scoped static lint ran.")

    fd_w, walker_path = tempfile.mkstemp(prefix="ennead_syntax_gate_", suffix=".py")
    fd_l, list_path = tempfile.mkstemp(prefix="ennead_syntax_gate_", suffix=".txt")
    try:
        with os.fdopen(fd_w, "w") as fh:
            fh.write(WALKER_SRC)
        with os.fdopen(fd_l, "w", encoding="utf-8") as fh:
            fh.write("\n".join(to_check))
        try:
            # errors="replace": a non-ASCII path or message in IronPython's output must
            # not crash the decode and silently turn the gate into a skip.
            # ipy_exe may be a command list (tests pass [python, fake_ipy.py]).
            cmd = list(ipy_exe) if isinstance(ipy_exe, (list, tuple)) else [ipy_exe]
            result = subprocess.run(cmd + [walker_path, list_path],
                                    capture_output=True, text=True, errors="replace",
                                    timeout=timeout)
        except subprocess.TimeoutExpired:
            return ("IronPython compile gate SKIPPED: timed out after {}s. Shipping trees "
                    "were NOT fully compile-checked.".format(timeout))
        except Exception as exc:
            return ("IronPython compile gate SKIPPED: could not run {} ({}: {}).".format(
                ipy_exe, type(exc).__name__, exc))
    finally:
        for tmp in (walker_path, list_path):
            try:
                os.remove(tmp)
            except OSError:
                pass

    if result.returncode != 0 and not (result.stdout or "").strip():
        # The walker reports per-file problems on stdout and exits 0. A non-zero exit
        # with nothing on stdout means the walker itself died, so nothing was checked.
        return ("IronPython compile gate SKIPPED: the walker exited {} without a "
                "report. stderr: {}".format(result.returncode,
                                            (result.stderr or "").strip()[:300]))

    found = classify_output(result.stdout, hard_paths, allowed_paths)

    if found["unreadable"]:
        print("    WARNING: {} file(s) could not be opened for checking; they ship "
              "unchecked:".format(len(found["unreadable"])))
        for path, msg in found["unreadable"][:10]:
            print("      - {}  ({})".format(path, msg))
    if found["allowed"]:
        print("    WARNING: {} grandfathered file(s) do not compile under IronPython 2.7 "
              "(allowlisted, not blocking -- remove the allowlist line once fixed):".format(
                  len(found["allowed"])))
        for path, msg in found["allowed"]:
            print("      ~ {}\n          {}".format(path, msg))
    if found["soft"]:
        print("    WARNING: {} non-_revit/_rhino file(s) do not compile under IronPython "
              "2.7 (not blocking -- may be CPython-only helpers):".format(len(found["soft"])))
        for path, msg in found["soft"]:
            print("      ? {}\n          {}".format(path, msg))
    if found["hard"]:
        print("    COMPILE GATE FAILED -- {} _revit/_rhino file(s) will NOT compile under "
              "IronPython 2.7:".format(len(found["hard"])))
        for path, msg in found["hard"]:
            print("      x {}\n          {}".format(path, msg))
        raise PublishStageError(
            "IronPython compile gate blocked the publish: {} _revit/_rhino file(s) fail "
            "to compile under IronPython 2.7. Fix them, or grandfather them in "
            "tools/.ironpython_lint_allowlist, then republish.".format(len(found["hard"])))

    print("[OK] IronPython compile gate passed: {} file(s) compiled, {} hard with zero "
          "errors.".format(len(to_check), len(hard_paths)))
    return None
