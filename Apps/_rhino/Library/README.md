# Library — shared Grasshopper catalog reader for Rhino ports

One shared Python package that reads the EnneadTab Grasshopper definition
catalog, so the ~24 upcoming Rhino toolbar ports reuse it instead of
duplicating parsing, search, and sort logic.

## What it reads

The catalog is produced by the EnneadTab for Grasshopper plugin
(`EnneadTab-EcoSystem/EnneadTab-For-Grasshopper`, branch `main`) and mirrored
here exactly:

| File | Format source |
|---|---|
| `library-index.json` | `LibraryIndexDocument` + `LibraryJson` (`LibraryIndexDocument.cs`, `LibraryJson.cs:356-380`): `lastIndexedAt`, `scanRoots[]`, `entries[]`. Entry rows use camelCase keys (`LibraryJson.cs:118-121` sets the camelCase naming policy and case-insensitive reads): `id`, `title`, `description`, `tags[]`, `category`, `sourcePath`, `scanRoot`, `fileHash`, `pluginsRequired[]`, `pluginsKnown`, `conventionOk`, `conventionNotes`, `parameters[]`, `indexedAt`, `curated` |
| `library-settings.json` | `LibrarySettings` (`LibrarySettings.cs:8-19`, `LibraryJson.cs:382-384`): `scanRoots[]` only, so scan roots survive across sessions independently of the index |
| `<definition>.gh.ennead.json` | `LibrarySidecar` (`LibrarySidecar.cs:8-13`): optional curation overrides — `title`, `description`, `tags[]`, `category`, `curated`, all optional. The sidecar sits next to the definition (`LibrarySidecarIO.cs:13,20,27`); missing/unreadable/malformed sidecars are ignored, never fatal (`LibrarySidecarIO.cs:34-36`) |

Entry ids are stable per scan root (`LibraryEntryIds.cs`); search token
semantics (whitespace-split, AND across tokens, case-insensitive substring
per token) mirror `LibraryCatalog.cs:11-27,66-133`.

## Path resolution

`find_catalog_paths()` mirrors the plugin's default store locations
(`LibraryIndexRefreshService.cs:21-38`):

- index: `%LOCALAPPDATA%\EnneadTab\Grasshopper\library-index.json`
- settings: `%LOCALAPPDATA%\EnneadTab\Grasshopper\library-settings.json`

On non-Windows platforms `%LOCALAPPDATA%` maps to `~/.local/share`
(honoring `XDG_DATA_HOME`), matching .NET's `LocalApplicationData`
behavior. Set `ENNEAD_LIBRARY_INDEX` / `ENNEAD_LIBRARY_SETTINGS` to
override either path (opt-in; the plugin itself always uses the defaults).
Returns `(None, None)` with no exception when nothing is found.

## Interface (`catalog.py`)

```python
from Library import catalog  # or: from Library.catalog import ...

index_path, settings_path = catalog.find_catalog_paths()
index = catalog.load_index(index_path)        # {} on missing/corrupt, never raises
settings = catalog.load_settings(settings_path)

entries = catalog.iter_entries(index)         # normalized dicts: id, title, path
                                              # (= GH sourcePath), tags (list),
                                              # category, sidecar ({} until loaded),
                                              # plus description, scanRoot,
                                              # conventionOk, curated, ...

catalog.load_sidecar(entry)                   # loads <path>.ennead.json -> dict,
                                              # {} when absent; caches on entry

hits = catalog.search_entries(entries, query="facade panel",
                              facets={"tag": ["curated"], "category": ["Facade"]})
ordered = catalog.sort_entries(hits, key="title", direction="desc")
warnings = catalog.validate_sidecar(entry["sidecar"])
```

- `search_entries(entries, query=None, facets=None)` — query tokens are
  AND-matched as case-insensitive substrings over title, description,
  category, path, scan root, tags, and parameter names. Facets
  `{"tag": [...], "category": [...]}` use case-insensitive exact matching
  (OR within a facet, AND across facets), mirroring
  `LibraryCatalog.cs:91-101`.
- `sort_entries(entries, key="title", direction="asc")` — keys `title`,
  `category`, `path`; case-insensitive primary sort with deterministic `id`
  tie-break (ascending regardless of direction).
- `validate_sidecar(sidecar)` — warns about unknown or mistyped sidecar
  fields. New on the Rhino side: the Grasshopper indexer silently drops
  unknown fields, so hand-edited sidecars fail quietly; this surfaces them.

## Dependency note

- **IronPython 2.7 only**: no f-strings, no type hints, no walrus operator,
  no pathlib. Keep it that way — `tools/check_ironpython.py` lints every new
  file under `Apps/_rhino/`.
- **Stdlib `json` + `os` only at import time** — no Rhino/GH dependencies, so
  the logic stays testable without Rhino and never crashes an import chain.
- **No I/O surprises**: `load_index`/`load_settings`/`load_sidecar` never
  raise; corrupt or missing files degrade to empty data.
- Tests live in `tests/` (`test_catalog.py` + `sample_index.json`, a small
  fixture in the exact GH camelCase schema). Run with
  `python -m unittest discover` from this directory.
