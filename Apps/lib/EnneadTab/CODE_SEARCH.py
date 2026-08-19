# -*- coding: utf-8 -*-
"""Filesystem keyword search + confined read over the EnneadTab-OS Apps/ tree.

Runtime-agnostic (CPython 3 and IronPython 2.7). No Revit/Rhino imports at module
scope. .NET (System.IO) is imported LAZILY inside the junction guard so this module
still imports and runs under plain CPython (dev-box smoke tests + the shared
confinement logic); under CPython 3.8+ os.path.realpath resolves junctions, which is
the fallback when .NET is unavailable.

Both RPC servers (Rhino single-file, Revit pyRevit Routes) import this module so the
corpus definition, ranking, confinement guard, and caps live here ONCE.
"""

import os
import re
import time

# --- caps -------------------------------------------------------------------
MAX_RESULTS_CAP    = 15
SNIPPET_CHARS      = 800
DOC_CHARS          = 200
READ_CHARS_CAP     = 20000
READ_CHARS_DEFAULT = 12000
FILE_SIZE_CAP      = 256 * 1024
MAX_FILES          = 8000
SCORE_MAX_LINES    = 1500
SEARCH_TIME_BUDGET_SEC = 20.0   # wall-clock bound on one scan (addendum D)

# First-party corpus only (addendum B). Skip vendored/dependency trees AND the
# CPython3 _engine (it would surface f-strings / type hints to an IronPython 2.7
# coder). node_modules stays for the junction/defense-in-depth story too.
SKIP_DIRS = set([
    ".git", "__pycache__", ".venv", "node_modules", "DEBUG",
    "dependency", "Lib", "site-packages", "DLLs", "tcl", "pythonwin", "_engine",
])
SKIP_PATH_PARTS = ["DarkSide" + os.sep + "exes"]


def corpus_root():
    """.../Apps/lib/EnneadTab/CODE_SEARCH.py -> .../Apps/"""
    here = os.path.dirname(os.path.abspath(__file__))          # .../Apps/lib/EnneadTab
    return os.path.dirname(os.path.dirname(here))              # up EnneadTab, up lib -> Apps


# --- text reads -------------------------------------------------------------
def _strip_bom(text):
    if text and text[:1] == u"\ufeff":
        return text[1:]
    return text


def _read_text(full):
    # utf-8 with errors='replace': corpus files carry `# -*- coding: utf-8 -*-`; a
    # naive open().read() in IronPython 2.7 raises UnicodeDecodeError and would kill
    # the whole scan. Read binary, decode defensively, strip a leading BOM.
    f = open(full, "rb")
    try:
        raw = f.read(FILE_SIZE_CAP + 1)
    finally:
        f.close()
    return _strip_bom(raw.decode("utf-8", "replace"))


def _read_text_full(full):
    # No size cap here: _safe_resolve already confined the path, and read_file bounds
    # the returned window by max_chars. Corpus files are small (<256 KB) anyway.
    f = open(full, "rb")
    try:
        raw = f.read()
    finally:
        f.close()
    return _strip_bom(raw.decode("utf-8", "replace"))


# --- metadata extractors ----------------------------------------------------
_ASSIGN_RE_CACHE = {}


def _extract(text, name):
    """Return the single-line string literal assigned to `name` (e.g. __title__)."""
    pat = _ASSIGN_RE_CACHE.get(name)
    if pat is None:
        pat = re.compile(
            r"^\s*" + re.escape(name) + r"\s*=\s*[uUrR]?(['\"])(.*?)\1",
            re.MULTILINE,
        )
        _ASSIGN_RE_CACHE[name] = pat
    m = pat.search(text)
    if m:
        return m.group(2).strip()
    return None


def _module_doc(lines):
    """First non-empty line of the module docstring (first ~40 lines)."""
    joined = "\n".join(lines[:40])
    for q in ('"""', "'''"):
        i = joined.find(q)
        if i != -1:
            j = joined.find(q, i + 3)
            if j != -1:
                body = joined[i + 3:j].strip()
                if body:
                    return body.split("\n")[0].strip()
    return None


def _folder_title(rel):
    """Title derived from the .pushbutton / .button folder name."""
    for part in rel.replace("\\", "/").split("/"):
        low = part.lower()
        if low.endswith(".pushbutton") or low.endswith(".button"):
            base = part.rsplit(".", 1)[0]
            return base.replace("_", " ").strip().title()
    return None


def _kind(rel):
    low = "/" + rel.replace("\\", "/").lower()
    if ".pushbutton" in low or ".button" in low:
        return "pushbutton"
    if "/lib/enneadtab/" in low:
        return "lib"
    return "tool"


# --- corpus iteration -------------------------------------------------------
def _scope_dirs(root, scope):
    scope = (scope or "all").lower()
    tokens = [t.strip() for t in scope.split(",") if t.strip()]
    # exact-token match for "all" (a substring test false-triggers on "install", etc.)
    if not tokens or "all" in tokens:
        return [root]
    mapping = {
        "revit":    os.path.join(root, "_revit"),
        "rhino":    os.path.join(root, "_rhino"),
        "cad":      os.path.join(root, "_cad"),
        "indesign": os.path.join(root, "_indesign"),
        "lib":      os.path.join(root, "lib", "EnneadTab"),   # addendum B: lib == lib/EnneadTab
    }
    dirs = []
    for tok in tokens:
        d = mapping.get(tok)
        if d and os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    return dirs


def _iter_py(dirs, root):
    seen = 0
    for base in dirs:
        for dirpath, dirnames, filenames in os.walk(base):
            # prune skip dirs in place so os.walk never descends into them
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            if any(sp in dirpath for sp in SKIP_PATH_PARTS):
                continue
            for fn in filenames:
                if not fn.lower().endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(full) > FILE_SIZE_CAP:
                        continue
                except OSError:
                    continue
                seen += 1
                if seen > MAX_FILES:
                    return
                yield full, os.path.relpath(full, root).replace(os.sep, "/")


# --- public: search ---------------------------------------------------------
def search(query, scope="all", max_results=8):
    root = corpus_root()
    terms = [t for t in (query or "").lower().split() if t]
    if not terms:
        return {"query": query, "scope": scope, "result_count": 0, "results": []}
    try:
        cap = min(int(max_results or 8), MAX_RESULTS_CAP)
    except (TypeError, ValueError):
        cap = 8
    if cap < 1:
        cap = 1

    started = time.time()
    hits = []
    for full, rel in _iter_py(_scope_dirs(root, scope), root):
        if time.time() - started > SEARCH_TIME_BUDGET_SEC:
            break
        try:
            text = _read_text(full)
        except Exception:
            continue
        all_lines = text.split("\n")
        lines = all_lines[:SCORE_MAX_LINES]
        low_rel = rel.lower()

        title = _extract(text, "__title__") or _folder_title(rel)
        doc = _extract(text, "__doc__") or _module_doc(lines)
        title_low = (title or "").lower()
        head = "\n".join(lines[:40]).lower()

        score = 0
        for t in terms:
            if t in title_low:
                score += 5
            if t in head:
                score += 3
            if t in low_rel:
                score += 2

        body_hits = 0
        def_bonus = 0
        best_i = 0
        best_s = -1
        for i, ln in enumerate(lines):
            low = ln.lower()
            matched = [t for t in terms if t in low]
            s = 0
            if low.lstrip().startswith("def ") and matched:
                def_bonus += 3
                s += 3
            if matched:
                body_hits += 1
                s += 1
            if s > best_s:
                best_s = s
                best_i = i
        score += min(def_bonus, 12)
        score += min(body_hits, 10)
        if score <= 0:
            continue

        lo = max(0, best_i - 7)
        hi = min(len(lines), best_i + 8)
        snippet = "\n".join(lines[lo:hi])[:SNIPPET_CHARS]
        hits.append({
            "path": rel,
            "kind": _kind(rel),
            "title": (title or "")[:DOC_CHARS],
            "doc": (doc or "")[:DOC_CHARS],
            "score": score,
            "total_lines": len(all_lines),
            "snippet": snippet,
        })

    # score desc; tie-break shorter path; then lib before app dirs (helpers first)
    hits.sort(key=lambda h: (-h["score"], len(h["path"]),
                             0 if "/lib/enneadtab/" in ("/" + h["path"].lower()) else 1))
    return {"query": query, "scope": scope,
            "result_count": min(len(hits), cap), "results": hits[:cap]}


# --- public: read -----------------------------------------------------------
def read_file(rel_path, max_chars=None, start_line=None, end_line=None):
    root = corpus_root()
    full = _safe_resolve(root, rel_path)              # raises ValueError on escape
    text = _read_text_full(full)
    all_lines = text.split("\n")
    total_lines = len(all_lines)

    try:
        s = max(1, int(start_line or 1))
    except (TypeError, ValueError):
        s = 1
    try:
        e = int(end_line) if end_line else total_lines
    except (TypeError, ValueError):
        e = total_lines
    if e < s:
        e = total_lines

    window = "\n".join(all_lines[s - 1:e])
    try:
        cap = min(int(max_chars or READ_CHARS_DEFAULT), READ_CHARS_CAP)
    except (TypeError, ValueError):
        cap = READ_CHARS_DEFAULT
    if cap < 1:
        cap = READ_CHARS_DEFAULT

    truncated = len(window) > cap
    content = window[:cap]
    result = {
        "path": rel_path.replace("\\", "/"),
        "total_lines": total_lines,
        "total_chars": len(text),
        "returned_chars": len(content),
        "start_line": s,
        "end_line": e,
        "truncated": truncated,
        "content": content,
    }
    if truncated:
        result["note"] = ("Truncated - narrow with start_line/end_line "
                          "or a tighter search.")
    return result


# --- confinement ------------------------------------------------------------
def _has_reparse_point(path):
    """True if `path` is a junction/symlink (a .NET reparse point).

    .NET is imported LAZILY so this module still imports under CPython. Returns None
    when .NET is unavailable (CPython) so the caller falls back to realpath. Fails
    CLOSED: any GetAttributes error is treated as suspicious (reject).
    """
    try:
        from System.IO import File, FileAttributes  # pyright: ignore
    except Exception:
        return None
    try:
        attrs = File.GetAttributes(path)
        return int(attrs & FileAttributes.ReparsePoint) != 0
    except Exception:
        return True


def _safe_resolve(root, rel_path):
    # CONFINEMENT -- reject traversal, absolute paths, drive letters, junctions,
    # vendored dirs. No content is ever exec'd; files are returned as DATA only.
    if not rel_path or "\x00" in rel_path:
        raise ValueError("empty or null path")
    # 1) reject absolute / drive-letter input: os.path.join(root, "C:/x") silently
    #    DISCARDS root on Windows -- the classic bypass.
    if os.path.isabs(rel_path) or (len(rel_path) > 1 and rel_path[1] == ":"):
        raise ValueError("absolute path not allowed")

    rel = rel_path.replace("\\", "/")
    # 2) component-level skip-dir defense on the READ path too (addendum C).
    for comp in rel.split("/"):
        if comp and comp != "." and comp != ".." and comp in SKIP_DIRS:
            raise ValueError("path component not allowed: {}".format(comp))

    root_abs = os.path.abspath(root)
    target = os.path.abspath(os.path.join(root_abs, rel_path))
    # 3) lexical containment (abspath collapses .. even on IronPython 2.7).
    if target != root_abs and not target.startswith(root_abs + os.sep):
        raise ValueError("path escapes corpus root")

    # 4) junction / symlink defense. os.path.realpath == abspath on IronPython 2.7
    #    (no reparse resolution before CPython 3.8), so a junction inside Apps/ could
    #    reach an out-of-tree .py. Reject if ANY component from root..target is a
    #    reparse point, via .NET. If .NET is unavailable (CPython) fall back to
    #    realpath, which DOES resolve junctions on 3.8+.
    reparse_checked = False
    cur = root_abs
    rel_from_root = os.path.relpath(target, root_abs).replace("\\", "/")
    for part in rel_from_root.split("/"):
        if not part or part == ".":
            continue
        cur = os.path.join(cur, part)
        rp = _has_reparse_point(cur)
        if rp is True:
            raise ValueError("path traverses a junction/symlink")
        if rp is not None:
            reparse_checked = True
    if not reparse_checked:
        real = os.path.realpath(target)
        root_real = os.path.realpath(root_abs)
        if real != root_real and not real.startswith(root_real + os.sep):
            raise ValueError("path escapes corpus root")

    # 5) .py-only allowlist (case-insensitive) -- also a mild exfiltration guard.
    if not target.lower().endswith(".py"):
        raise ValueError("only .py reference files may be read")
    if not os.path.isfile(target):
        raise ValueError("not a file")
    return target
