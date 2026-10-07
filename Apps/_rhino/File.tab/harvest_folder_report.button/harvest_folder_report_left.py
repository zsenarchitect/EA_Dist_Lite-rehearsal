__title__ = "HarvestFolderReport"
__doc__ = """Scan a folder of .3dm files and report aggregated model context.

Key Features:
- Resolves a folder + file pattern (e.g. *.3dm), top folder or subfolders
- Lists every matched file before reading anything
- Aggregates layer paths found across all files
- Aggregates attribute user-text keys found across all files
- Prints a copy-paste-ready report to the command line

Rhino-side equivalent of the Rhino 8 Query Directory + Import Content
harvest pattern: batch-read model context without importing anything
into the active document.
"""
__is_popular__ = False

import os
import fnmatch

import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc

from EnneadTab import LOG, ERROR_HANDLE


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def harvest_folder_report():
    folder = rs.BrowseForFolder(
        message="Pick the folder to harvest model context from",
        title=__title__)
    if not folder:
        return

    pattern = rs.GetString("File pattern", "*.3dm")
    if not pattern:
        return

    scope = rs.ListBox(
        ["Top folder only", "Include subfolders"],
        "Search scope:", __title__)
    if not scope:
        return
    recursive = scope == "Include subfolders"

    matched = resolve_files(folder, pattern, recursive)
    if not matched:
        rs.MessageBox(
            "No files matched '{}' in:\n{}".format(pattern, folder),
            0, __title__)
        return

    layers, key_counts, failures = aggregate_context(matched)
    report = build_report(folder, pattern, matched, layers, key_counts, failures)
    print(report)
    rs.MessageBox(
        "Harvested {} file(s): {} layer(s), {} user-text key(s){}.".format(
            len(matched), len(layers), len(key_counts),
            " ({} unreadable)".format(len(failures)) if failures else "")
        + "\nFull report printed to the command line.",
        0, __title__)


def resolve_files(folder, pattern, recursive):
    matched = []
    if recursive:
        walker = os.walk(folder)
    else:
        try:
            names = os.listdir(folder)
        except OSError:
            return []
        walker = [(folder, [], names)]
    for root, _dirs, names in walker:
        for name in sorted(names):
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                matched.append(os.path.join(root, name))
    return matched


def aggregate_context(paths):
    layers = set()
    key_counts = {}
    failures = []
    for path in paths:
        try:
            file3dm = Rhino.FileIO.File3dm.Read(path)
        except Exception:
            file3dm = None
        if file3dm is None:
            failures.append(path)
            continue
        for layer in file3dm.Layers:
            layers.add(layer.FullPath)
        for obj in file3dm.Objects:
            keys = obj.Attributes.GetUserStrings()
            if not keys:
                continue
            for key in keys:
                key_counts[key] = key_counts.get(key, 0) + 1
    return sorted(layers), key_counts, failures


def build_report(folder, pattern, matched, layers, key_counts, failures):
    lines = [
        "=== Harvest report ===",
        "Folder : {}".format(folder),
        "Pattern: {}".format(pattern),
        "Files  : {}".format(len(matched)),
        "",
        "-- Matched files --",
    ]
    lines.extend("  " + p for p in matched)
    lines.append("")
    lines.append("-- Layers across files ({} total) --".format(len(layers)))
    if layers:
        lines.extend("  " + l for l in layers)
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("-- User-text keys across files ({} total) --".format(len(key_counts)))
    if key_counts:
        for key in sorted(key_counts):
            lines.append("  {} ({} object(s))".format(key, key_counts[key]))
    else:
        lines.append("  (none)")
    if failures:
        lines.append("")
        lines.append("-- Unreadable files ({}) --".format(len(failures)))
        lines.extend("  " + p for p in failures)
    return "\n".join(lines)


if __name__ == "__main__":
    harvest_folder_report()
