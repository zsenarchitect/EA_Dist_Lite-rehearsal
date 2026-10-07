# -*- coding: utf-8 -*-
__title__ = "LibraryPublishers"
__doc__ = """List named publishers harvested from catalog sidecars and rename one everywhere.

Catalog entries can expose contract parameters as named publishers (the
sidecar "publishers" map: publisher name -> contract parameter name, borrowed
from Telepathy by EnneadTab-For-Grasshopper PR #47). Pick a publisher, enter
a new name, and the rename propagates across every sidecar that references
it, the version-agnostic markdown docs (<definition>.gh.ennead.md), and any
saved contract presets (contract-presets.json) -- one rename, everywhere
consistent.

Additive-only: sidecar files keep every existing field; only the publisher
key is renamed. Depends on PR #283 (shared catalog lib); degrades gracefully
if unmerged."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os, sys, json, re
_rhino_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_library_dir = os.path.join(_rhino_folder, "Library")
if _library_dir not in sys.path: sys.path.append(_library_dir)
try:
    import catalog
except ImportError:
    catalog = None
from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE
_MISSING_LIB_TEXT = ("The shared library module (Apps/_rhino/Library/catalog.py) is not installed yet. "
                     "This button needs the shared-catalog-lib PR #283 (branch sen/osrhino-shared-catalog-lib) merged first.")


# Mirrors PublisherRename.NamePattern (EnneadTab-For-Grasshopper PR #47):
# start with a letter/underscore, then letters/digits/underscore/dot, so
# markdown references can be matched with unambiguous boundaries.
_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")

# Whole-name markdown rename, mirroring PublisherRename.RenameInMarkdown:
# never renames substrings (FacadeHeightMax is left alone when renaming
# FacadeHeight).
_MARKDOWN_BOUNDARY = r"(?<![A-Za-z0-9_.]){0}(?![A-Za-z0-9_.])"

# contract-presets.json lives next to the settings file, mirroring the
# Grasshopper plugin (PublisherRenameDialog / ContractPresetStore, PR #47).
_PRESETS_FILENAME = "contract-presets.json"

# Version-agnostic markdown docs convention, mirroring
# PublisherRenameDialog.DocsPathFor (PR #47).
_DOCS_SUFFIX = ".ennead.md"


def _utext(value):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    try:
        return unicode(value)
    except Exception:
        pass
    try:
        return str(value).decode("utf-8", "replace")
    except Exception:
        return u"?"


def _ci_get(mapping, name):
    """Case-insensitive dict read (the GH index/sidecar JSON is camelCase)."""
    if not isinstance(mapping, dict):
        return None
    wanted = name.lower()
    for key in mapping:
        try:
            if key.lower() == wanted:
                return mapping[key]
        except AttributeError:
            continue
    return None


def _read_json_object(path):
    """Read a JSON object file; {} on missing/corrupt (never raises)."""
    try:
        if not path or not os.path.isfile(path):
            return {}
        with open(path, "rb") as handle:
            data = json.loads(handle.read().decode("utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json_object(path, data):
    """Write a JSON object file (UTF-8). Additive-only callers must pass the
    full object they read; this function never drops keys."""
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        text = json.dumps(data, indent=2, ensure_ascii=True)
    if isinstance(text, unicode):
        payload = text.encode("utf-8")
    else:
        payload = text
    with open(path, "wb") as handle:
        handle.write(payload)


def _entry_title(entry):
    title = _utext(entry.get("title"))
    return title if title else (_utext(entry.get("id")) or u"(untitled)")


def _harvest_publishers(entries):
    """Returns a list of (publisher_name, entry, param_name) triples."""
    found = []
    for entry in entries:
        sidecar = catalog.load_sidecar(entry) or {}
        publishers = _ci_get(sidecar, "publishers")
        if not isinstance(publishers, dict):
            continue
        for name in publishers:
            if not name:
                continue
            param = publishers[name]
            found.append((_utext(name), entry, _utext(param)))
    return found


def _distinct_names(occurrences):
    """Group occurrences by publisher name (case-sensitive, like the GH side)."""
    groups = {}
    order = []
    for name, entry, param in occurrences:
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append((entry, param))
    return [(name, groups[name]) for name in sorted(order)]


def _rename_markdown_refs(text, old_name, new_name):
    pattern = _MARKDOWN_BOUNDARY.format(re.escape(old_name))
    matches = re.findall(pattern, text)
    if not matches:
        return text, 0
    return re.sub(pattern, new_name, text), len(matches)


def _rename_sidecar_key(sidecar_path, old_name, new_name):
    """Rename one publisher key in a sidecar file, keeping every other field.

    Returns (ok, skipped_reason)."""
    data = _read_json_object(sidecar_path)
    if not data:
        return False, u"sidecar unreadable"
    publishers = _ci_get(data, "publishers")
    if not isinstance(publishers, dict):
        return False, u"no publishers map"
    # Exact (Ordinal) key lookup, mirroring the GH rename.
    old_key = None
    for key in publishers:
        if key == old_name:
            old_key = key
            break
    if old_key is None:
        return False, u"publisher not present"
    for key in publishers:
        if key != old_key and _utext(key).lower() == new_name.lower():
            return False, u"a publisher named '{0}' already exists".format(new_name)
    # Rebuild the publishers map with the key renamed (best-effort order;
    # IronPython 2.7 dicts do not guarantee file order round-trips).
    renamed = {}
    for key in publishers:
        renamed[new_name if key == old_key else key] = publishers[key]
    # Write back through the original casing of the "publishers" key.
    for key in list(data.keys()):
        try:
            if key.lower() == "publishers":
                data[key] = renamed
                break
        except AttributeError:
            continue
    else:
        data["publishers"] = renamed
    try:
        _write_json_object(sidecar_path, data)
    except Exception as err:
        return False, _utext(err)
    return True, u""


def _rename_presets(presets_path, affected_entry_ids, old_name, new_name):
    """Rename the publisher value-key in presets of the affected entries.

    Mirrors ContractPreset.RenameValueKey + ContractPresetStore.ReplaceForEntry
    (PR #47). Returns (presets_updated, skipped_reason)."""
    if not presets_path or not os.path.isfile(presets_path):
        return 0, u"no contract-presets.json found -- skipped"
    data = _read_json_object(presets_path)
    presets = _ci_get(data, "presets")
    if not isinstance(presets, list):
        return 0, u"contract-presets.json has no presets list -- skipped"
    updated = 0
    for preset in presets:
        if not isinstance(preset, dict):
            continue
        entry_id = _utext(_ci_get(preset, "entryId"))
        if entry_id not in affected_entry_ids:
            continue
        values = _ci_get(preset, "values")
        if not isinstance(values, dict):
            continue
        old_key = None
        for key in values:
            if key == old_name:
                old_key = key
                break
        if old_key is None:
            continue
        if new_name in values:
            continue  # collision: leave this preset untouched
        renamed_values = {}
        for key in values:
            renamed_values[new_name if key == old_key else key] = values[key]
        for key in list(preset.keys()):
            try:
                if key.lower() == "values":
                    preset[key] = renamed_values
                    break
            except AttributeError:
                continue
        else:
            preset["values"] = renamed_values
        updated += 1
    if updated:
        try:
            _write_json_object(presets_path, data)
        except Exception as err:
            return 0, _utext(err)
    return updated, u""


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_publishers():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT); return

    index_path, settings_path = catalog.find_catalog_paths()
    if not index_path:
        rs.MessageBox(u"No Grasshopper library index was found.\n\n"
                      u"Expected %LOCALAPPDATA%\\EnneadTab\\Grasshopper\\library-index.json "
                      u"(written by the EnneadTab for Grasshopper plugin's Refresh), or set "
                      u"ENNEAD_LIBRARY_INDEX to point at one.")
        return
    entries = catalog.iter_entries(catalog.load_index(index_path))
    if not entries:
        rs.MessageBox(u"The library index contains no entries.")
        return

    occurrences = _harvest_publishers(entries)
    if not occurrences:
        rs.MessageBox(u"No named publishers found in any catalog sidecar.\n\n"
                      u"Add a \"publishers\" map (publisher name -> contract parameter name) "
                      u"to a sidecar (*.ennead.json) first -- see "
                      u"EnneadTab-For-Grasshopper PR #47.")
        return

    grouped = _distinct_names(occurrences)
    labels = []
    for name, group in grouped:
        params = sorted(set(_utext(param) for _entry, param in group if param))
        param_text = u", ".join(params) if params else u"?"
        titles = sorted(set(_entry_title(entry) for entry, _param in group))
        shown = u", ".join(titles[:3])
        if len(titles) > 3:
            shown += u", ..."
        labels.append(u"{0}  ->  {1}  ({2} sidecar(s): {3})".format(
            name, param_text, len(group), shown))

    picked = RHINO_FORMS.select_from_list(
        labels,
        title=u"Library Publishers",
        message=u"Pick a named publisher to rename. The rename propagates to every "
                u"sidecar, markdown doc, and saved preset that references it.",
        button_names=[u"Rename"],
        width=700,
        height=500,
        multi_select=False)
    if not picked:
        return
    old_name, group = grouped[labels.index(picked)]

    new_name = rs.GetString(u"New name for publisher '{0}'".format(old_name))
    if new_name is None:
        return
    new_name = new_name.strip()
    if not new_name:
        rs.MessageBox(u"Rename cancelled: the new name is empty.")
        return
    if new_name == old_name:
        rs.MessageBox(u"No change: the new name is identical.")
        return
    if not _NAME_PATTERN.match(new_name):
        rs.MessageBox(u"Invalid publisher name.\n\nNames must start with a letter or "
                      u"underscore and contain only letters, digits, underscores, "
                      u"and dots (mirrors EnneadTab-For-Grasshopper PR #47).")
        return

    presets_path = None
    if settings_path:
        presets_path = os.path.join(os.path.dirname(settings_path), _PRESETS_FILENAME)

    sidecars_ok = 0
    sidecars_skipped = []
    markdown_replacements = 0
    affected_entry_ids = set()
    for entry, _param in group:
        definition_path = _utext(entry.get("path"))
        if not definition_path:
            sidecars_skipped.append((_entry_title(entry), u"entry has no definition path"))
            continue
        sidecar_path = definition_path + catalog.SIDECAR_SUFFIX
        ok, reason = _rename_sidecar_key(sidecar_path, old_name, new_name)
        if not ok:
            sidecars_skipped.append((_entry_title(entry), reason))
            continue
        sidecars_ok += 1
        affected_entry_ids.add(_utext(entry.get("id")))
        # Markdown docs: <definition>.gh.ennead.md, whole-name references only.
        docs_path = definition_path + _DOCS_SUFFIX
        try:
            if os.path.isfile(docs_path):
                with open(docs_path, "rb") as handle:
                    docs_text = handle.read().decode("utf-8-sig")
                updated_text, count = _rename_markdown_refs(docs_text, old_name, new_name)
                if count:
                    if isinstance(updated_text, unicode):
                        payload = updated_text.encode("utf-8")
                    else:
                        payload = updated_text
                    with open(docs_path, "wb") as handle:
                        handle.write(payload)
                    markdown_replacements += count
        except Exception as err:
            sidecars_skipped.append((_entry_title(entry), u"docs update failed: {0}".format(_utext(err))))

    presets_updated, presets_note = _rename_presets(
        presets_path, affected_entry_ids, old_name, new_name)

    lines = [u"Renamed publisher '{0}' -> '{1}'.".format(old_name, new_name),
             u"",
             u"Sidecars updated: {0}".format(sidecars_ok),
             u"Markdown references renamed: {0}".format(markdown_replacements),
             u"Presets updated: {0}".format(presets_updated)]
    if presets_note and not presets_updated:
        lines.append(u"Presets: {0}".format(presets_note))
    if sidecars_skipped:
        lines.append(u"")
        lines.append(u"Skipped:")
        for title, reason in sidecars_skipped[:8]:
            lines.append(u"  - {0}: {1}".format(title, reason))
        if len(sidecars_skipped) > 8:
            lines.append(u"  ... and {0} more".format(len(sidecars_skipped) - 8))
    rs.MessageBox(u"\n".join(lines), title=u"Library Publishers")


library_publishers()
