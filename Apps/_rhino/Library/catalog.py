# -*- coding: utf-8 -*-
"""Shared reader for the EnneadTab Grasshopper definition catalog.

Reads the JSON catalog produced by the EnneadTab for Grasshopper plugin
(``library-index.json``, ``library-settings.json``, and ``*.ennead.json``
sidecars) so Rhino toolbar ports can share one implementation instead of
duplicating catalog parsing, search, and sort logic.

Mirrored formats (EnneadTab-EcoSystem/EnneadTab-For-Grasshopper, main):
  - index JSON ........ LibraryJson.cs:356-380 (camelCase keys, LibraryJson.cs:118-121
                        camelCase naming policy + case-insensitive read)
  - settings JSON ..... LibrarySettings.cs:8-19 (``scanRoots`` array)
  - sidecar JSON ...... LibrarySidecar.cs:8-13 (title/description/tags/category/curated,
                        all optional; curation fields only)
  - sidecar discovery . LibrarySidecarIO.cs:13,20,27 (``<definition>.gh`` + ``".ennead.json"``;
                        LibrarySidecarIO.cs:34-36 TryLoad never throws)
  - search semantics .. LibraryCatalog.cs:11-27,66-133 (whitespace tokens, AND across
                        tokens, case-insensitive substring per token)
  - default paths ..... LibraryIndexRefreshService.cs:21-38
                        (``%LOCALAPPDATA%/EnneadTab/Grasshopper/library-index.json``
                        and ``library-settings.json``)

IronPython 2.7 only: no f-strings, no type hints, no walrus operator, no
pathlib. Import-time dependencies are ``json`` and ``os`` from the stdlib
only -- safe to import anywhere, including modules that never touch Rhino.
"""

import json
import os


try:
    _STRING_TYPES = basestring  # IronPython 2.7 / CPython 2
except NameError:
    _STRING_TYPES = str  # CPython 3


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Suffix appended to a definition path to find its sidecar.
#: Mirrors LibrarySidecarIO.ExtensionSuffix (LibrarySidecarIO.cs:13).
SIDECAR_SUFFIX = ".ennead.json"

#: Default file names under <LocalAppData>/EnneadTab/Grasshopper.
#: Mirrors LibraryIndexRefreshService.DefaultIndexPath/DefaultSettingsPath
#: (LibraryIndexRefreshService.cs:21-38).
INDEX_FILENAME = "library-index.json"
SETTINGS_FILENAME = "library-settings.json"

#: Environment overrides for the default catalog locations (opt-in; the
#: Grasshopper plugin itself has no equivalent, it always uses the defaults).
ENV_INDEX_PATH = "ENNEAD_LIBRARY_INDEX"
ENV_SETTINGS_PATH = "ENNEAD_LIBRARY_SETTINGS"

#: Sort keys accepted by sort_entries().
SORT_KEYS = ("title", "category", "path")

#: Sidecar fields the Grasshopper indexer understands, with expected types.
#: Mirrors the LibrarySidecar record (LibrarySidecar.cs:8-13).
_SIDECAR_FIELDS = {
    "title": "string",
    "description": "string",
    "tags": "list of strings",
    "category": "string",
    "curated": "boolean",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_ci(mapping, name):
    """Case-insensitive dict lookup.

    Mirrors System.Text.Json ``PropertyNameCaseInsensitive = true``
    (LibraryJson.cs:121): the real index files use camelCase keys, but reads
    tolerate any casing.
    """
    if name in mapping:
        return mapping[name]
    lowered = name.lower()
    for key in mapping:
        if isinstance(key, _STRING_TYPES) and key.lower() == lowered:
            return mapping[key]
    return None


def _as_text(value):
    """Coerce to text, returning "" for None/uncoercible values."""
    if value is None:
        return ""
    if isinstance(value, _STRING_TYPES):
        return value
    try:
        return str(value)
    except Exception:
        return ""


def _as_str_list(value):
    """Coerce to a list of non-empty strings ([] for None)."""
    if value is None:
        return []
    if isinstance(value, _STRING_TYPES):
        return [value] if value else []
    try:
        iterator = iter(value)
    except TypeError:
        text = _as_text(value)
        return [text] if text else []
    result = []
    for item in iterator:
        text = _as_text(item)
        if text:
            result.append(text)
    return result


def _read_json_file(path):
    """Read and parse a JSON file; return None on any failure (never raises).

    Mirrors JsonLibraryIndexStore.LoadOrEmpty / LibrarySidecarIO.TryLoad:
    missing, unreadable, or malformed files degrade to "no data" instead of
    throwing.
    """
    if not path or not isinstance(path, _STRING_TYPES):
        return None
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as handle:
            text = handle.read().decode("utf-8-sig")
        return json.loads(text)
    except Exception:
        return None


def _default_catalog_dir():
    """Default catalog directory, mirroring the Grasshopper plugin's stores.

    LibraryIndexRefreshService.cs:21-38 builds the defaults from
    ``Environment.SpecialFolder.LocalApplicationData`` joined with
    ``EnneadTab/Grasshopper``. On Windows that is ``%LOCALAPPDATA%``; on other
    platforms .NET maps it to ``~/.local/share`` (honoring XDG_DATA_HOME).
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = local_app_data
    else:
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            base = xdg_data_home
        else:
            base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "EnneadTab", "Grasshopper")


# ---------------------------------------------------------------------------
# Path resolution / loading
# ---------------------------------------------------------------------------

def find_catalog_paths():
    """Resolve the default catalog locations.

    Returns ``(index_path, settings_path)`` mirroring the Grasshopper
    plugin's default store resolution (LibraryIndexRefreshService.cs:21-38).
    ``ENNEAD_LIBRARY_INDEX`` / ``ENNEAD_LIBRARY_SETTINGS`` override the
    defaults when set. Either element is ``None`` when that file does not
    exist; returns ``(None, None)`` with no exception when nothing is found.
    """
    try:
        catalog_dir = _default_catalog_dir()
        index_path = os.environ.get(ENV_INDEX_PATH) or os.path.join(
            catalog_dir, INDEX_FILENAME)
        settings_path = os.environ.get(ENV_SETTINGS_PATH) or os.path.join(
            catalog_dir, SETTINGS_FILENAME)
    except Exception:
        return (None, None)
    try:
        if not os.path.isfile(index_path):
            index_path = None
    except Exception:
        index_path = None
    try:
        if not os.path.isfile(settings_path):
            settings_path = None
    except Exception:
        settings_path = None
    return (index_path, settings_path)


def load_index(path):
    """Load a library index JSON file; ``{}`` on missing/corrupt, never raises.

    The file shape mirrors LibraryIndexDocument/LibraryJson.cs:356-380:
    ``{"lastIndexedAt": ..., "scanRoots": [...], "entries": [...]}``.
    """
    data = _read_json_file(path)
    if not isinstance(data, dict):
        return {}
    return data


def load_settings(path):
    """Load a library settings JSON file; ``{}`` on missing/corrupt, never raises.

    The file shape mirrors LibrarySettings/LibraryJson.cs:382-384:
    ``{"scanRoots": [...]}``.
    """
    data = _read_json_file(path)
    if not isinstance(data, dict):
        return {}
    return data


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------

def _normalize_entry(raw):
    """Normalize one raw index row into the shared entry dict.

    Field mapping mirrors the LibraryEntryDto (LibraryJson.cs:363-379);
    ``path`` is the GH ``sourcePath``. Every entry carries ``sidecar`` (``{}``
    until :func:`load_sidecar` fills it from the adjacent ``*.ennead.json``).
    """
    params = _get_ci(raw, "parameters")
    if not isinstance(params, (list, tuple)):
        params = []
    return {
        "id": _as_text(_get_ci(raw, "id")),
        "title": _as_text(_get_ci(raw, "title")),
        "description": _as_text(_get_ci(raw, "description")),
        "path": _as_text(_get_ci(raw, "sourcePath")) or _as_text(_get_ci(raw, "path")),
        "tags": _as_str_list(_get_ci(raw, "tags")),
        "category": _as_text(_get_ci(raw, "category")),
        "scanRoot": _as_text(_get_ci(raw, "scanRoot")),
        "fileHash": _as_text(_get_ci(raw, "fileHash")),
        "pluginsRequired": _as_str_list(_get_ci(raw, "pluginsRequired")),
        "pluginsKnown": bool(_get_ci(raw, "pluginsKnown")),
        "conventionOk": bool(_get_ci(raw, "conventionOk")),
        "conventionNotes": _as_text(_get_ci(raw, "conventionNotes")),
        "parameters": list(params),
        "indexedAt": _as_text(_get_ci(raw, "indexedAt")),
        "curated": bool(_get_ci(raw, "curated")),
        "sidecar": {},
    }


def iter_entries(index):
    """Return the normalized entry dicts from a loaded index document.

    Each entry has at least ``id``, ``title``, ``path``, ``tags`` (list),
    ``category``, and ``sidecar`` (``{}`` until :func:`load_sidecar` runs).
    Non-dict rows are skipped; an empty/missing index yields ``[]``.
    """
    if not isinstance(index, dict):
        return []
    raw_entries = _get_ci(index, "entries")
    if not isinstance(raw_entries, (list, tuple)):
        return []
    entries = []
    for raw in raw_entries:
        if isinstance(raw, dict):
            entries.append(_normalize_entry(raw))
    return entries


def load_sidecar(entry):
    """Load the adjacent ``*.ennead.json`` sidecar for an entry.

    The sidecar path is ``entry["path"] + ".ennead.json"``, mirroring
    LibrarySidecarIO.GetSidecarPath (LibrarySidecarIO.cs:20,27). Returns the
    sidecar dict (``{}`` when missing, unreadable, or malformed -- never
    raises, mirroring LibrarySidecarIO.TryLoad at LibrarySidecarIO.cs:34-36)
    and caches it on ``entry["sidecar"]``.
    """
    if not isinstance(entry, dict):
        return {}
    path = _as_text(entry.get("path"))
    if not path:
        return {}
    data = _read_json_file(path + SIDECAR_SUFFIX)
    if not isinstance(data, dict):
        return {}
    entry["sidecar"] = data
    return data


# ---------------------------------------------------------------------------
# Search / sort
# ---------------------------------------------------------------------------

def _facet_values(facets, name):
    """Lowercased wanted values for one facet key ([] means no constraint)."""
    if not isinstance(facets, dict):
        return []
    value = facets.get(name)
    if value is None:
        return []
    if isinstance(value, _STRING_TYPES):
        value = [value]
    try:
        iterator = iter(value)
    except TypeError:
        iterator = [value]
    wanted = []
    for item in iterator:
        text = _as_text(item).strip().lower()
        if text and text not in wanted:
            wanted.append(text)
    return wanted


def _matches_facets(entry, tag_wants, category_wants):
    # Facet lists are OR-within / AND-across. Tag and category use exact
    # case-insensitive matching, mirroring LibraryCatalog.cs:91-101.
    if tag_wants:
        tags = [t.lower() for t in _as_str_list(entry.get("tags"))]
        if not any(want in tags for want in tag_wants):
            return False
    if category_wants:
        if _as_text(entry.get("category")).strip().lower() not in category_wants:
            return False
    return True


def _entry_search_blob(entry):
    # One lowercased blob of the substring-searchable fields. Mirrors the
    # per-token field set of LibraryCatalog.MatchesKeywordToken
    # (LibraryCatalog.cs:125-133): title, description, category, source path,
    # scan root, tags, and parameter names.
    parts = [
        _as_text(entry.get("title")),
        _as_text(entry.get("description")),
        _as_text(entry.get("category")),
        _as_text(entry.get("path")),
        _as_text(entry.get("scanRoot")),
    ]
    parts.extend(_as_str_list(entry.get("tags")))
    params = entry.get("parameters")
    if isinstance(params, (list, tuple)):
        for param in params:
            if isinstance(param, dict):
                parts.append(_as_text(_get_ci(param, "name")))
    return "\n".join(parts).lower()


def _matches_tokens(entry, tokens):
    # Every token must appear in at least one field (AND across tokens),
    # mirroring LibraryCatalog.cs:122.
    blob = _entry_search_blob(entry)
    for token in tokens:
        if token not in blob:
            return False
    return True


def search_entries(entries, query=None, facets=None):
    """Filter entries by free-text query and/or facets.

    ``query``: whitespace-separated tokens; every token must match as a
    case-insensitive substring of at least one searchable field
    (title, description, category, path, scan root, tags, parameter names).
    Mirrors LibraryCatalog.Search token semantics (LibraryCatalog.cs:11-27,
    66-133).

    ``facets``: dict like ``{"tag": [...], "category": [...]}``. Each facet
    list is OR-within (case-insensitive exact match, mirroring
    LibraryCatalog.cs:91-101) and facets AND together. Unknown facet keys are
    ignored. ``None``/empty query and facets mean "no constraint".
    """
    tokens = []
    if query:
        for token in _as_text(query).split():
            lowered = token.lower()
            if lowered:
                tokens.append(lowered)
    tag_wants = _facet_values(facets, "tag")
    category_wants = _facet_values(facets, "category")
    matches = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if not _matches_facets(entry, tag_wants, category_wants):
            continue
        if tokens and not _matches_tokens(entry, tokens):
            continue
        matches.append(entry)
    return matches


def sort_entries(entries, key="title", direction="asc"):
    """Sort entries by ``key`` (``"title"``, ``"category"``, or ``"path"``).

    Primary sort is case-insensitive; ties break deterministically on ``id``
    (ascending, regardless of direction). ``direction`` is ``"asc"`` or
    ``"desc"``. Raises ``ValueError`` on an unknown key or direction.
    """
    if key not in SORT_KEYS:
        raise ValueError(
            "sort key must be one of {0}; got {1!r}".format(
                ", ".join(SORT_KEYS), key))
    if direction not in ("asc", "desc"):
        raise ValueError(
            "direction must be 'asc' or 'desc'; got {0!r}".format(direction))
    clean = [e for e in (entries or []) if isinstance(e, dict)]
    by_id = sorted(clean, key=lambda e: _as_text(e.get("id")))
    return sorted(
        by_id,
        key=lambda e: _as_text(e.get(key)).lower(),
        reverse=(direction == "desc"))


# ---------------------------------------------------------------------------
# Sidecar validation
# ---------------------------------------------------------------------------

def _check_sidecar_field(key, field_kind, value):
    if value is None:
        return None
    if field_kind in ("string",):
        if not isinstance(value, _STRING_TYPES):
            return "sidecar field {0!r} should be a string, got {1}".format(
                key, type(value).__name__)
        return None
    if field_kind == "list of strings":
        if isinstance(value, _STRING_TYPES) or not isinstance(value, (list, tuple)):
            return "sidecar field {0!r} should be a list of strings, got {1}".format(
                key, type(value).__name__)
        bad = [item for item in value if not isinstance(item, _STRING_TYPES)]
        if bad:
            return "sidecar field {0!r} should contain only strings; {1} item(s) are not strings".format(
                key, len(bad))
        return None
    if field_kind == "boolean":
        # NB: check bool before int -- in Python bool is a subclass of int.
        if not isinstance(value, bool):
            return "sidecar field {0!r} should be true/false, got {1}".format(
                key, type(value).__name__)
        return None
    return None


def validate_sidecar(sidecar):
    """Warn about unknown or mistyped sidecar fields.

    The Grasshopper indexer silently ignores unknown sidecar fields
    (System.Text.Json drops them on read), so hand-edited ``*.ennead.json``
    files fail quietly. This ports the sidecar-field-warning idea to the
    Rhino side: returns a list of human-readable warning strings; ``[]``
    means the sidecar is clean. Known fields and types mirror the
    LibrarySidecar record (LibrarySidecar.cs:8-13): ``title``/``description``/
    ``category`` are strings, ``tags`` is a list of strings, ``curated`` is a
    boolean; all are optional. Field names are matched case-insensitively,
    mirroring LibraryJson.cs:121.
    """
    if sidecar is None:
        return []
    if not isinstance(sidecar, dict):
        return ["sidecar should be a JSON object, got {0}".format(
            type(sidecar).__name__)]
    warnings = []
    known_fields = ", ".join(sorted(_SIDECAR_FIELDS))
    for key, value in sidecar.items():
        lowered = key.lower() if isinstance(key, _STRING_TYPES) else ""
        field_kind = _SIDECAR_FIELDS.get(lowered)
        if field_kind is None:
            warnings.append(
                "unknown sidecar field {0!r}; the Grasshopper indexer only reads: {1}".format(
                    key, known_fields))
            continue
        warning = _check_sidecar_field(key, field_kind, value)
        if warning:
            warnings.append(warning)
    return warnings
