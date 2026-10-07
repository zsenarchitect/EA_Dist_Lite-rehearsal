# -*- coding: utf-8 -*-
__title__ = "LibraryPortability"
__doc__ = """Audit a catalog definition for portability problems (ports EnneadTab-For-Grasshopper PR #72).

Checks one library entry for the things that break when a definition moves to
another machine: absolute paths hiding in the sidecar or in indexed parameter
values, plugin assemblies the entry needs but this machine does not have
installed ("Name|secret" wire format, cross-checked against the Grasshopper
Libraries / yak package folders and the entry's pluginsKnown provenance flag),
and Windows-only assumptions (registry keys, drive-letter paths, Program
Files references).

Key Features:
- Pass / warn / fail verdict per entry with fix hints
- Absolute-path scan over sidecar fields and parameter values
- Missing-plugin detection with yak install hints
- Full report printed to the command line"""
__is_popular__ = False

import os
import sys
import re

import rhinoscriptsyntax as rs # pyright: ignore
import scriptcontext as sc # pyright: ignore

_rhino_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_library_dir = os.path.join(_rhino_folder, "Library")
if _library_dir not in sys.path: sys.path.append(_library_dir)
try:
    import catalog
except ImportError:
    catalog = None

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION

_MISSING_LIB_TEXT = ("The shared library module (Apps/_rhino/Library/catalog.py) is not installed yet. "
                     "This button needs the shared-catalog-lib PR #283 (branch sen/osrhino-shared-catalog-lib) merged first.")

_ABS_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")
_WINDOWS_ONLY_RES = (
    (re.compile(r"\bHKLM\b|\bHKCU\b|\bHKEY_", re.IGNORECASE), "Windows registry reference"),
    (re.compile(r"[A-Za-z]:\\Windows", re.IGNORECASE), "Windows system folder path"),
    (re.compile(r"Program Files", re.IGNORECASE), "Program Files path"),
    (re.compile(r"\.dll\b", re.IGNORECASE), ".dll reference"),
)


def _iter_strings(obj, prefix=""):
    """Yield (dotted field path, string value) for every string nested in dicts/lists."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = "{}.{}".format(prefix, key) if prefix else str(key)
            for item in _iter_strings(value, path):
                yield item
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            for item in _iter_strings(value, "{}[{}]".format(prefix, i)):
                yield item
    elif isinstance(obj, basestring):
        yield (prefix, obj)


def _parse_plugin_dependency(raw):
    """Mirror PluginDependency.Parse: "DisplayName|secret", secret optional; malformed keeps raw text."""
    text = (raw or "").strip()
    if not text:
        return None
    sep = text.find("|")
    if sep < 0:
        return (text, None)
    name = text[:sep].strip()
    secret = text[sep + 1:].strip() or None
    if not name:
        return (text, None)
    return (name, secret)


def _gh_plugin_search_dirs():
    dirs = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        dirs.append(os.path.join(appdata, "Grasshopper", "Libraries"))
        pkg_root = os.path.join(appdata, "McNeel", "Rhinoceros", "packages")
        if os.path.isdir(pkg_root):
            try:
                for ver in os.listdir(pkg_root):
                    candidate = os.path.join(pkg_root, ver)
                    if os.path.isdir(candidate):
                        dirs.append(candidate)
            except OSError:
                pass
    home = os.path.expanduser("~")
    dirs.append(os.path.join(home, "Library", "Application Support", "Grasshopper", "Libraries"))
    return [d for d in dirs if os.path.isdir(d)]


def _installed_plugin_names():
    names = set()
    for folder in _gh_plugin_search_dirs():
        for root, _dirs, files in os.walk(folder):
            depth = root[len(folder):].count(os.sep)
            if depth > 3:
                _dirs[:] = []
                continue
            for fn in files:
                if fn.lower().endswith((".gha", ".rhp", ".dll")):
                    names.add(os.path.splitext(fn)[0].lower())
            for d in _dirs:
                names.add(d.lower())
    return names


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _is_installed(display_name, installed):
    needle = _norm(display_name)
    return bool(needle) and len(needle) >= 3 and any(needle in have for have in installed)


def _pick_entry(entries):
    labels = []
    for entry in entries:
        title = entry.get("title") or os.path.basename(entry.get("path") or "") or "(untitled)"
        labels.append("{}  --  {}".format(title, entry.get("path") or ""))
    choice = rs.ListBox(labels, "Pick a catalog entry to audit for portability:", "Library Portability")
    if choice is None:
        return None
    for entry, label in zip(entries, labels):
        if label == choice:
            return entry
    return None


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_portability():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT)
        return

    index_path, _settings_path = catalog.find_catalog_paths()
    if not index_path:
        NOTIFICATION.messenger(main_text="Library catalog not found.\nIndex the Grasshopper library first, then run again.")
        return

    entries = [e for e in catalog.iter_entries(catalog.load_index(index_path)) if e.get("path")]
    entries = sorted(entries, key=lambda e: (e.get("title") or "").lower())
    if not entries:
        NOTIFICATION.messenger(main_text="No catalog entries found.")
        return

    entry = _pick_entry(entries)
    if entry is None:
        return

    label = entry.get("title") or os.path.basename(entry.get("path") or "") or "(untitled)"
    sidecar = catalog.load_sidecar(entry)

    fails, warns = [], []

    # 1. Absolute paths in the sidecar.
    for field_path, value in _iter_strings(sidecar):
        if _ABS_PATH_RE.match(value.strip()):
            warns.append(("absolute path in sidecar field '{}'".format(field_path),
                          value.strip(),
                          "Use a path relative to the definition folder so the entry survives a move."))

    # 2. Absolute paths in indexed parameter values.
    for field_path, value in _iter_strings(entry.get("parameters") or []):
        if _ABS_PATH_RE.match(value.strip()):
            warns.append(("absolute path in parameter '{}'".format(field_path),
                          value.strip(),
                          "Parameterize the path or store it relative to the definition."))

    # 3. Windows-only assumptions.
    for field_path, value in _iter_strings(sidecar):
        for pattern, what in _WINDOWS_ONLY_RES:
            if pattern.search(value):
                fails.append(("Windows-only assumption in sidecar field '{}': {}".format(field_path, what),
                              value.strip()[:160],
                              "Replace with a cross-platform equivalent or document the Windows requirement."))

    # 4. Missing plugin assemblies ("Name|secret" wire format).
    installed = _installed_plugin_names()
    for raw in entry.get("pluginsRequired") or []:
        dep = _parse_plugin_dependency(raw)
        if dep is None:
            continue
        name, secret = dep
        if _is_installed(name, installed):
            continue
        hint = "yak install {}".format(secret) if secret else 'yak install "{}"'.format(name)
        fails.append(("missing plugin assembly: {}".format(name),
                      'required by this entry ("{}") but not installed'.format(raw),
                      "Restore it with: {}".format(hint)))
    if not entry.get("pluginsKnown") and entry.get("pluginsRequired"):
        warns.append(("plugin provenance is incomplete for this entry",
                      "pluginsKnown is false",
                      "Re-index the definition so the plugin list is captured, then audit again."))

    verdict = "PASS" if not fails and not warns else ("FAIL" if fails else "WARN")

    lines = ["Portability audit: {} -> {}".format(label, verdict), ""]
    for kind, items in (("FAIL", fails), ("WARN", warns)):
        for title, detail, hint in items:
            lines.append("[{}] {}".format(kind, title))
            lines.append("       {}".format(detail))
            lines.append("       fix: {}".format(hint))
            lines.append("")
    if verdict == "PASS":
        lines.append("No absolute paths, missing plugins, or Windows-only assumptions found.")
    print("\n".join(lines))

    summary = "{} check(s) failed, {} warning(s).".format(len(fails), len(warns))
    if verdict == "PASS":
        NOTIFICATION.messenger(main_text="{}: portable - no problems found.".format(label))
    else:
        shown = [l for l in lines[2:] if l.strip()][:28]
        sub_text = "\n".join(shown)
        if len(lines) - 2 > len(shown):
            sub_text += "\n... see the command line for the full report"
        RHINO_FORMS.notification(
            title="Library Portability: {}".format(verdict),
            main_text="{}: {}".format(label, summary),
            sub_text=sub_text,
            width=700,
            height=450)


if __name__ == "__main__":
    library_portability()
