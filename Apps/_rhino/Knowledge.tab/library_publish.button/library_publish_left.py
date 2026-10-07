# -*- coding: utf-8 -*-
__title__ = "LibraryPublish"
__doc__ = """Stage a Grasshopper catalog entry for publishing (ports EnneadTab-For-Grasshopper PR #69).

Picks a library catalog entry (or browses for a .gh/.ghx file), collects the
publish metadata (title, version, description, tags, category), validates the
request the same way the Grasshopper publish dialogs do, writes the versioned
*.ennead.json sidecar, then stages the definition + sidecar (+README if one
sits next to the definition) into a publish/staging folder under the catalog
directory.

Key Features:
- Entry picker over the shared catalog index, or browse for a file
- Next-version suggestion ("1.2.0" -> "1.2.1", "v3" -> "v4", "3beta" -> "4beta")
- Request validation (source file exists, title, dotted-numeric version, no blank tags)
- Sidecar field warnings through catalog.validate_sidecar
- Full staging report printed to the command line"""
__is_popular__ = False

import os
import sys
import json
import re
import shutil

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

_STAGING_DIRNAME = "publish_staging"
_README_NAMES = ("README.md", "readme.md", "ReadMe.md", "README.txt", "readme.txt")
_VERSION_RE = re.compile(r"^[vV]?\d+(\.\d+)*([a-zA-Z][a-zA-Z0-9]*)?$")


def _suggest_next_version(current):
    """Mirror LibraryPublishRequest.SuggestNextVersion ("2"->"3", "1.2.0"->"1.2.1", "v3"->"v4", "3beta"->"4beta")."""
    trimmed = (current or "").strip()
    prefix = ""
    if trimmed[:1].lower() == "v":
        prefix = trimmed[:1]
        trimmed = trimmed[1:]
    chunks = trimmed.split(".")
    last = chunks[-1]
    i = 0
    while i < len(last) and last[i].isdigit():
        i += 1
    digits = last[:i]
    if not digits:
        raise ValueError("Cannot suggest a next version for {0!r} (no numeric component).".format(current))
    chunks[-1] = str(int(digits) + 1) + last[i:]
    return prefix + ".".join(chunks)


def _validate_request(source_path, title, version, tags):
    """Mirror LibraryPublishRequest.Validate: human-readable problems ([] = valid)."""
    errors = []
    if not source_path or not source_path.strip():
        errors.append("Source file is required.")
    elif not os.path.isfile(source_path.strip()):
        errors.append("Source file not found: {}".format(source_path.strip()))
    if not title or not title.strip():
        errors.append("Title is required.")
    if not version or not version.strip():
        errors.append("Version is required.")
    elif not _VERSION_RE.match(version.strip()):
        errors.append('Version "{}" is not a dotted numeric version (e.g. 1, v2, 1.2.0).'.format(version.strip()))
    for tag in tags or []:
        if not tag or not tag.strip():
            errors.append("Tags must not contain blank entries.")
            break
    return errors


def _read_json_dict(path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _safe_name(text):
    cleaned = "".join(ch if (ch.isalnum() or ch in ".-_") else "-" for ch in (text or ""))
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or "entry"


def _entry_label(entry):
    title = entry.get("title")
    path = entry.get("path") or ""
    if title:
        return "{}  --  {}".format(title, path)
    return path or "(untitled)"


def _pick_source(entries):
    """Return a source .gh/.ghx path: picked catalog entry or browsed file."""
    browse_label = "[ Browse for a .gh / .ghx file... ]"
    items = [browse_label] + [_entry_label(e) for e in entries]
    choice = rs.ListBox(items, "Pick a catalog entry to stage for publishing:", "EnneadTab Publish")
    if choice is None:
        return None
    if choice == browse_label:
        return rs.OpenFileName("Select a Grasshopper definition",
                               "Grasshopper definition (*.gh;*.ghx)|*.gh;*.ghx||")
    for entry, label in zip(entries, items[1:]):
        if label == choice:
            return entry.get("path")
    return None


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_publish():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT)
        return

    index_path, _settings_path = catalog.find_catalog_paths()
    if not index_path:
        NOTIFICATION.messenger(main_text="Library catalog not found.\nIndex the Grasshopper library first, then run again.")
        return

    entries = [e for e in catalog.iter_entries(catalog.load_index(index_path)) if e.get("path")]
    entries = sorted(entries, key=lambda e: (e.get("title") or "").lower())

    source_path = _pick_source(entries)
    if not source_path:
        return
    if not os.path.isfile(source_path):
        rs.MessageBox("Source file not found:\n{}".format(source_path), 0, "EnneadTab Publish")
        return

    sidecar_path = source_path + catalog.SIDECAR_SUFFIX
    sidecar = _read_json_dict(sidecar_path)
    current_version = sidecar.get("version")

    title = rs.StringBox("Title", sidecar.get("title") or os.path.splitext(os.path.basename(source_path))[0],
                         "EnneadTab Publish")
    if title is None:
        return
    try:
        default_version = _suggest_next_version(current_version) if current_version else "1"
    except ValueError:
        default_version = "1"
    version = rs.StringBox("Version (dotted numeric, e.g. 1, v2, 1.2.0)", default_version, "EnneadTab Publish")
    if version is None:
        return
    description = rs.StringBox("Description", sidecar.get("description") or "", "EnneadTab Publish")
    if description is None:
        return
    tags_raw = rs.StringBox("Tags (comma-separated)", ", ".join(sidecar.get("tags") or []), "EnneadTab Publish")
    if tags_raw is None:
        return
    tags = [t.strip() for t in tags_raw.split(",")]
    category = rs.StringBox("Category", sidecar.get("category") or "", "EnneadTab Publish")
    if category is None:
        return

    errors = _validate_request(source_path, title, version, tags)
    if errors:
        rs.MessageBox("Cannot stage for publishing:\n\n" + "\n".join("- " + e for e in errors), 0, "EnneadTab Publish")
        return
    tags = [t for t in tags if t]

    updated = dict(sidecar)
    updated["title"] = title.strip()
    updated["version"] = version.strip()
    if description.strip():
        updated["description"] = description.strip()
    else:
        updated.pop("description", None)
    if tags:
        updated["tags"] = tags
    else:
        updated.pop("tags", None)
    if category.strip():
        updated["category"] = category.strip()
    else:
        updated.pop("category", None)

    try:
        with open(sidecar_path, "w") as f:
            json.dump(updated, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except (IOError, OSError) as exc:
        rs.MessageBox("Could not write the sidecar:\n{}".format(exc), 0, "EnneadTab Publish")
        return

    sidecar_warnings = catalog.validate_sidecar(updated) or []

    staging_root = os.path.join(os.path.dirname(index_path), _STAGING_DIRNAME)
    dest_dir = os.path.join(staging_root, "{}-v{}".format(_safe_name(title), _safe_name(version)))
    base_dir, n = dest_dir, 0
    while os.path.exists(dest_dir):
        n += 1
        dest_dir = "{}-{}".format(base_dir, n)
    os.makedirs(dest_dir)

    staged = []
    for src in (source_path, sidecar_path):
        dst = os.path.join(dest_dir, os.path.basename(src))
        shutil.copy2(src, dst)
        staged.append(dst)
    src_dir = os.path.dirname(source_path)
    for readme_name in _README_NAMES:
        candidate = os.path.join(src_dir, readme_name)
        if os.path.isfile(candidate):
            dst = os.path.join(dest_dir, readme_name)
            shutil.copy2(candidate, dst)
            staged.append(dst)
            break

    lines = ["Staged {} file(s) for publishing:".format(len(staged))]
    lines.extend("  " + p for p in staged)
    if sidecar_warnings:
        lines.append("")
        lines.append("Sidecar warnings ({}):".format(len(sidecar_warnings)))
        lines.extend("  ! " + w for w in sidecar_warnings)
    lines.append("")
    lines.append("Refresh the library index to pick up the new version.")
    print("\n".join(lines))

    RHINO_FORMS.notification(
        title="EnneadTab Publish",
        main_text="{} v{} staged for publishing.".format(title.strip(), version.strip()),
        sub_text="\n".join(lines[:30]),
        width=700,
        height=450)


if __name__ == "__main__":
    library_publish()
