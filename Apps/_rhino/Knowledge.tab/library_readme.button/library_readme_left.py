# -*- coding: utf-8 -*-
__title__ = "LibraryReadme"
__doc__ = """Show a library definition's version-agnostic README.md docs.

Pick a catalog entry to read the <definition>.gh.README.md sidecar sitting next
to the definition file — usage notes, input explanations, and known
limitations, exactly as the Grasshopper library explorer renders them
(EnneadTab-For-Grasshopper PR #30). The docs live outside the .gh file, so
updating the definition never wipes them; files over 256 KiB are not loaded.

Reads the shared Grasshopper definition catalog through
Apps/_rhino/Library/catalog.py to resolve each entry's definition path."""
__is_popular__ = False

import os
import sys

import rhinoscriptsyntax as rs
import scriptcontext as sc

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION


# Shared definition-catalog reader, added by the sibling PR
# `sen/osrhino-shared-catalog-lib` as Apps/_rhino/Library/catalog.py.
# A toolbar script runs with its own .button folder on sys.path, not the
# _rhino root, so anchor the Library package to this file's location first
# (the same sys.path.append-then-import shape .button scripts already use
# for sibling-folder modules; the lib PR's README documents
# `from Library import catalog`).
_BUTTON_DIR = os.path.dirname(os.path.abspath(__file__))
_RHINO_DIR = os.path.normpath(os.path.join(_BUTTON_DIR, os.pardir, os.pardir))
if _RHINO_DIR not in sys.path:
    sys.path.append(_RHINO_DIR)

try:
    from Library import catalog as _catalog
    _CATALOG_IMPORT_ERROR = None
except ImportError as _import_error:
    _catalog = None
    _CATALOG_IMPORT_ERROR = str(_import_error)


def _utext(value):
    """Coerce to unicode for report building (IronPython 2.7)."""
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    if isinstance(value, bool):
        return u"True" if value else u"False"
    if isinstance(value, float):
        if value.is_integer():
            return unicode(int(value))
        return unicode(repr(value))
    if isinstance(value, (int, long)):
        return unicode(value)
    try:
        return unicode(value)
    except Exception:
        pass
    try:
        return str(value).decode("utf-8", "replace")
    except Exception:
        return u"?"


def _load_catalog():
    """Returns (entries, raw_index, error_message)."""
    if _catalog is None:
        return (None, None,
                u"The shared library catalog reader is not available.\n\n{0}\n\n"
                u"Merge the shared-catalog lib PR first, then retry.".format(
                    _utext(_CATALOG_IMPORT_ERROR)))
    try:
        index_path, _settings_path = _catalog.find_catalog_paths()
    except Exception as err:
        return (None, None,
                u"Could not resolve the catalog location: {0}".format(_utext(err)))
    if not index_path:
        return (None, None,
                u"No Grasshopper library index was found.\n\n"
                u"Expected %LOCALAPPDATA%\\EnneadTab\\Grasshopper\\library-index.json "
                u"(written by the EnneadTab for Grasshopper plugin's Refresh), or set "
                u"ENNEAD_LIBRARY_INDEX to point at one.")
    index = _catalog.load_index(index_path)
    entries = _catalog.iter_entries(index)
    if not entries:
        return (None, None,
                u"The library index at\n{0}\ncontains no entries. Run Refresh in the "
                u"Grasshopper library explorer first.".format(_utext(index_path)))
    entries = _catalog.sort_entries(entries, key="title", direction="asc")
    return (entries, index, None)


def _entry_display_title(entry):
    title = entry.get("title")
    if title:
        return _utext(title)
    return _utext(entry.get("id")) or u"(untitled)"


def _build_labels(entries, suffix_fn=None):
    titles = [_entry_display_title(entry) for entry in entries]
    counts = {}
    for title in titles:
        counts[title] = counts.get(title, 0) + 1
    labels = []
    for entry, title in zip(entries, titles):
        label = title
        if counts[title] > 1:
            label = u"{0} [{1}]".format(title, _utext(entry.get("id")) or u"?")
        if suffix_fn is not None:
            suffix = suffix_fn(entry)
            if suffix:
                label = u"{0} ({1})".format(label, suffix)
        labels.append(label)
    return labels


def _pick_entry(entries, labels, message, dialog_title):
    picked_label = RHINO_FORMS.select_from_list(
        labels,
        title=dialog_title,
        message=message,
        button_names=["Show"],
        width=650,
        height=550,
        multi_select=False)
    if not picked_label:
        return None
    for entry, label in zip(entries, labels):
        if label == picked_label:
            return entry
    return None


def _show_report(title, text):
    rs.MessageBox(message=text, buttons=0, title=title)


# --- Definition READMEs (ports GH PR #30) -----------------------------------
# Version-agnostic docs: <definition>.gh.README.md lives next to the
# definition, so updating the .gh never wipes its docs. Loaded live from
# disk (never indexed), mirroring LibraryReadmeIO.

_README_SUFFIX = u".README.md"
_MAX_README_BYTES = 256 * 1024


def _readme_path(definition_path):
    return _utext(definition_path) + _README_SUFFIX


def _try_load_readme(definition_path):
    """Raw README.md markdown, or None when missing, unreadable, oversized,
    or not valid UTF-8 (mirrors LibraryReadmeIO.TryLoad's never-throw
    contract so docs can never break the button)."""
    path = _utext(definition_path)
    if not path:
        return None
    readme_path = _readme_path(path)
    try:
        if not os.path.isfile(readme_path):
            return None
        if os.path.getsize(readme_path) > _MAX_README_BYTES:
            return None
        with open(readme_path, "rb") as handle:
            data = handle.read()
        return data.decode("utf-8")
    except Exception:
        return None


def _format_readme(entry):
    definition_path = _utext(entry.get("path"))
    readme_path = _readme_path(definition_path)
    file_name = os.path.basename(readme_path) or _README_SUFFIX.lstrip(u".")
    lines = [u"Definition: {0}".format(_entry_display_title(entry)),
             u"Id: {0}".format(_utext(entry.get("id"))),
             u"",
             u"Documentation ({0}):".format(file_name)]
    markdown = _try_load_readme(definition_path)
    if markdown is None or not markdown.strip():
        lines.append(u"  (none \u2014 add a README.md sidecar next to the definition "
                     u"to document usage, inputs, and known limitations)")
    else:
        for readme_line in markdown.splitlines():
            lines.append(u"  " + readme_line.rstrip())
    return u"\n".join(lines)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_readme():
    entries, _raw_index, error = _load_catalog()
    if error is not None:
        NOTIFICATION.messenger(main_text=error, title=__title__,
                               level="warning", sticky=True)
        return
    labels = _build_labels(entries)
    entry = _pick_entry(entries,
                        labels,
                        "Pick a definition to read its README.md docs.",
                        "Library README")
    if entry is None:
        return
    report = _format_readme(entry)
    _show_report(u"README \u2014 {0}".format(_entry_display_title(entry)),
                 report)


if __name__ == "__main__":
    library_readme()
