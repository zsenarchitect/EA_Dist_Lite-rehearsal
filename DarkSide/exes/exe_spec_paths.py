# -*- coding: utf-8 -*-
"""Pure path logic for .sexyDuck specs (no tkinter / EnneadTab imports, so it is testable anywhere).

A spec path may be:
  - repo-relative (preferred, TODO-1215):  DarkSide\\exes\\source code\\X\\X.py
  - legacy absolute, embedding the repo marker:  C:\\Users\\x\\github\\EnneadTab-OS\\DarkSide\\...
  - a PyInstaller --add-data pair "src;dest" where only src is a path
  - anything else (returned unchanged)
"""

MARKER = "EnneadTab-OS"


def _is_absolute(path):
    return (len(path) > 1 and path[1] == ":") or path.startswith("\\") or path.startswith("/")


def _repath_one(path, root):
    idx = path.rfind(MARKER)
    if idx != -1:
        return root + path[idx + len(MARKER):]
    if not path or _is_absolute(path):
        return path
    return root + "\\" + path.replace("/", "\\")


def repath_to_root(path, root):
    """Resolve a spec path against root. Handles 'src;dest' add-data pairs."""
    if ";" in path:
        src, dest = path.split(";", 1)
        return _repath_one(src, root) + ";" + dest
    return _repath_one(path, root)


def to_repo_relative(path):
    """Inverse used by the converter: strip everything up to and including the repo marker.

    Returns the path unchanged if it has no marker (already relative or foreign).
    """
    def one(p):
        idx = p.rfind(MARKER)
        if idx == -1:
            return p
        tail = p[idx + len(MARKER):]
        return tail.lstrip("\\/")
    if ";" in path:
        src, dest = path.split(";", 1)
        return one(src) + ";" + dest
    return one(path)


# auto-py-to-exe JSON optionDest -> PyInstaller CLI flag.
#
# Verified 2026-10-06 against the argparse definitions in PyInstaller 6.22.3
# (PyInstaller/building/makespec.py + build_main.py + log.py). Several dests
# do NOT mechanically map to their flag: some use underscores where the flag
# uses dashes, and a few are renamed outright. ExeMaker._json_to_command()'s
# old generic fallback emitted "--{optionDest}" verbatim, which silently
# produced invalid flags (e.g. --clean_build, --uac_admin,
# --disable_windowed_traceback) for any spec that set one of these options
# truthy. TODO-3969 audit.
_OPTION_FLAG_OVERRIDES = {
    # dest matches PyInstaller's spec-file argument, not its CLI flag
    "pathex": "--paths",
    "icon_file": "--icon",
    "datas": "--add-data",
    # dest differs from the CLI flag beyond underscore/dash spelling
    "clean_build": "--clean",
    "hiddenimports": "--hidden-import",
    "hookspath": "--additional-hooks-dir",
    "excludes": "--exclude-module",
    "binaries": "--add-binary",
    "bundle_identifier": "--osx-bundle-identifier",
    "entitlements_file": "--osx-entitlements-file",
    "loglevel": "--log-level",
    "python_options": "--python-option",
    "target_arch": "--target-architecture",
    "resources": "--resource",
    # legacy auto-py-to-exe naming (dashes); newer configs use collect_submodules
    "collect-submodules": "--collect-submodules",
}


def cli_flag_for(option_dest):
    """Return the PyInstaller CLI flag for an auto-py-to-exe JSON optionDest.

    Falls back to "--" + dest with underscores converted to dashes, which is
    PyInstaller's own dest-derivation convention for the regular options.
    Dests that pre-date the convention (or were renamed outright) are covered
    by _OPTION_FLAG_OVERRIDES above.
    """
    if option_dest in _OPTION_FLAG_OVERRIDES:
        return _OPTION_FLAG_OVERRIDES[option_dest]
    return "--" + option_dest.replace("_", "-")
