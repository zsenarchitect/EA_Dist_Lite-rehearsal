# -*- coding: utf-8 -*-
__title__ = "LibraryPackageRestore"
__doc__ = """Show the Yak install commands for a catalog entry's missing plugins (ports EnneadTab-For-Grasshopper PR #74).

Reads the entry's required plugin packages ("DisplayName|secret" wire format,
same as the Grasshopper plugin), compares them against the plugins installed
on this machine, and emits the `yak install <name>` commands needed to restore
the missing ones.

Read-only helper: it never runs installs itself. Copy the commands to the
clipboard or open the Rhino PackageManager from the prompt.

Key Features:
- Missing vs already-installed plugin report per entry
- Install hints prefer the secret GUID (unambiguous on the package server)
- Copyable command list (clipboard + command line)
- One-click open of the Rhino PackageManager"""
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


def _install_hint(name, secret):
    # Mirrors MissingPackage.InstallHint: prefer the secret GUID, it is unambiguous.
    if secret:
        return "yak install {}".format(secret)
    return 'yak install "{}"'.format(name)


def _copy_to_clipboard(text):
    try:
        import System.Windows.Forms as WinForms
        WinForms.Clipboard.SetText(text)
        return True
    except Exception:
        return False


def _pick_entry(entries):
    labels = []
    for entry in entries:
        title = entry.get("title") or os.path.basename(entry.get("path") or "") or "(untitled)"
        labels.append("{}  --  {}".format(title, entry.get("path") or ""))
    choice = rs.ListBox(labels, "Pick a catalog entry to plan the plugin restore for:", "Library Package Restore")
    if choice is None:
        return None
    for entry, label in zip(entries, labels):
        if label == choice:
            return entry
    return None


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_package_restore():
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
    requirements = entry.get("pluginsRequired") or []
    if not requirements:
        NOTIFICATION.messenger(main_text="{} records no required plugins - nothing to restore.".format(label))
        return

    installed = _installed_plugin_names()
    missing, ok = [], []
    for raw in requirements:
        dep = _parse_plugin_dependency(raw)
        if dep is None:
            continue
        name, secret = dep
        if _is_installed(name, installed):
            ok.append(name)
        else:
            missing.append((name, secret, raw))

    commands = [_install_hint(name, secret) for name, secret, _raw in missing]

    lines = ["Plugin restore plan: {}".format(label), ""]
    if ok:
        lines.append("Already installed ({}):".format(len(ok)))
        lines.extend("  [ok] {}".format(name) for name in ok)
        lines.append("")
    if missing:
        lines.append("Missing ({}):".format(len(missing)))
        for (name, _secret, raw), command in zip(missing, commands):
            lines.append("  [missing] {}  (from {!r})".format(name, raw))
            lines.append("            {}".format(command))
        lines.append("")
        lines.append("This button never installs anything itself - run the commands above")
        lines.append("in a terminal, or open the Rhino PackageManager and install by hand.")
    else:
        lines.append("All required plugins are installed - nothing to restore.")
    print("\n".join(lines))

    if not missing:
        NOTIFICATION.messenger(main_text="{}: all required plugins are installed.".format(label))
        return

    sub_text = "\n".join(lines[:30])
    RHINO_FORMS.notification(
        title="Library Package Restore",
        main_text="{} plugin(s) missing for {}.".format(len(missing), label),
        sub_text=sub_text,
        width=700,
        height=450)

    if rs.MessageBox("Copy the {} yak install command(s) to the clipboard?".format(len(commands)),
                      4, "Library Package Restore") == 6:
        if _copy_to_clipboard("\n".join(commands)):
            NOTIFICATION.messenger(main_text="Install commands copied to the clipboard.")
        else:
            rs.MessageBox("Could not reach the clipboard - copy the commands from the command line instead.",
                          0, "Library Package Restore")

    if rs.MessageBox("Open the Rhino PackageManager now to install them by hand?",
                      4, "Library Package Restore") == 6:
        rs.Command("_PackageManager", False)


if __name__ == "__main__":
    library_package_restore()
