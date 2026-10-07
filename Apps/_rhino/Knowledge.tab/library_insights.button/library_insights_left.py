# -*- coding: utf-8 -*-
__title__ = "LibraryInsights"
__doc__ = """Show a read-only Insights dashboard for the Grasshopper definition catalog.

Rhino port of the Grasshopper catalog analytics dashboard
(EnneadTab-For-Grasshopper PR #49): entry counts per category and tag,
most-used plugins, sidecar completeness (how many entries have a
*.ennead.json and how many are clean), and -- when a library-usage.json
file is present -- a usage section with the most-opened entries and the
stale-entry cleanup hit-list (no opens in 90 days). Pure report; nothing
is modified."""
__is_popular__ = False

import datetime
import os
import re
import sys
import json

import rhinoscriptsyntax as rs  # pyright: ignore
import scriptcontext as sc  # pyright: ignore

# The shared catalog lib lives at Apps/_rhino/Library. Toolbar scripts do
# not get _rhino on sys.path by themselves, so resolve it from this file.
_rhino_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_library_dir = os.path.join(_rhino_folder, "Library")
if _library_dir not in sys.path:
    sys.path.append(_library_dir)
try:
    import catalog  # pyright: ignore
except ImportError:
    catalog = None

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION

_MISSING_LIB_TEXT = ("The shared library module (Apps/_rhino/Library/catalog.py) is not installed yet. "
                     "This button needs the shared-catalog-lib PR #283 (branch sen/osrhino-shared-catalog-lib) merged first.")

# Mirrors LibraryAnalytics.StaleAfterDays (GH PR #49).
_STALE_AFTER_DAYS = 90
# Mirrors LibraryAnalyticsText.MaxBarWidth (GH PR #49).
_MAX_BAR_WIDTH = 24
_USAGE_FILE_NAME = "library-usage.json"


def _usage_file_candidates(settings_path):
    candidates = []
    folder = os.path.dirname(settings_path) if settings_path else ""
    if folder:
        candidates.append(os.path.join(folder, _USAGE_FILE_NAME))
    # GH default next to the plugin settings; also tolerate the pre-#49
    # array-shaped store location.
    app_data = os.environ.get("APPDATA") or ""
    if app_data:
        candidates.append(os.path.join(app_data, "EnneadTab.Grasshopper", _USAGE_FILE_NAME))
    return candidates


def _parse_last_opened(value):
    # Tolerates the ISO-8601 the C# DateTimeOffset serializes to (with or
    # without fractional seconds / zone offset); returns None when the
    # value is missing or unparseable (never raises).
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1]
    # Drop a trailing zone offset like -04:00 / +0530 (naive local reading).
    rest = text[10:]
    cut = None
    for i, ch in enumerate(rest):
        if ch in ("+", "-"):
            cut = 10 + i
            break
    if cut is not None:
        text = text[:cut]
    # strptime %f takes at most 6 digits; truncate longer fractions.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _load_usage():
    # Returns {entry_key: {"opens": int, "last_opened": datetime|None}}.
    # Tolerates both usage shapes seen in the Grasshopper repo: the GH #49
    # JsonLibraryUsageStore object {"opens": {id: {entryId, openCount,
    # lastOpenedAt}}} and the older GH #31 array [{entryId, opens, ...}].
    _index_path, settings_path = catalog.find_catalog_paths()
    data = None
    for path in _usage_file_candidates(settings_path):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r") as handle:
                data = json.load(handle)
            break
        except Exception:
            data = None
            break
    if data is None:
        return {}

    items = []
    if isinstance(data, dict):
        opens = data.get("opens")
        if isinstance(opens, dict):
            for key, value in opens.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("entryId", key)
                    items.append(item)
        else:
            for key, value in data.items():
                if isinstance(value, dict):
                    item = dict(value)
                    item.setdefault("entryId", key)
                    items.append(item)
    elif isinstance(data, list):
        items = [i for i in data if isinstance(i, dict)]

    usage = {}
    for item in items:
        entry_id = item.get("entryId") or item.get("entry_id") or item.get("id")
        if not entry_id:
            continue
        opens = item.get("openCount", item.get("opens", 0))
        try:
            opens = int(opens)
        except (TypeError, ValueError):
            opens = 0
        usage[str(entry_id)] = {
            "opens": max(0, opens),
            "last_opened": _parse_last_opened(item.get("lastOpenedAt") or item.get("last_opened_at")),
        }
    return usage


def _entry_key(entry):
    # The usage store keys rows by the index row id; fall back to path/title
    # so hand-matched rows still resolve.
    for field in ("id", "path", "title"):
        value = entry.get(field)
        if value:
            return str(value)
    return ""


def _count_by(items):
    counts = {}
    for name in items:
        key = name if name else "(blank)"
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))


def _append_bar_section(lines, heading, counts):
    lines.append(heading)
    if not counts:
        lines.append("  (none)")
    else:
        top = max(1, max(count for _name, count in counts))
        label_width = min(28, max(4, max(len(name) for name, _count in counts)))
        for name, count in counts:
            width = max(1, int(round(float(count) / top * _MAX_BAR_WIDTH)))
            lines.append(u"  {0} {1} {2}".format(
                name.ljust(label_width), u"█" * width, count))
    lines.append("")


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_insights():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT)
        return

    index_path, settings_path = catalog.find_catalog_paths()
    if not index_path:
        NOTIFICATION.messenger(
            main_text="Library catalog not found.\nIndex the Grasshopper library first, then run again.")
        return

    entries = catalog.iter_entries(catalog.load_index(index_path))

    # --- sidecar completeness (mirrors the validate_sidecar idea) ---
    with_sidecar = 0
    sidecar_clean = 0
    sidecar_warned = 0
    for entry in entries:
        sidecar = catalog.load_sidecar(entry)
        if sidecar:
            with_sidecar += 1
            if catalog.validate_sidecar(sidecar):
                sidecar_warned += 1
            else:
                sidecar_clean += 1

    # --- counts (mirrors LibraryAnalytics.Compute) ---
    category_counts = _count_by(
        [(e.get("category") or "").strip() or "Uncategorized" for e in entries])
    tag_counts = _count_by(
        [t for e in entries for t in (e.get("tags") or [])])
    plugin_counts = _count_by(
        [p.strip() for e in entries
         if e.get("pluginsKnown")
         for p in (e.get("pluginsRequired") or []) if p and p.strip()])

    # --- usage + stale (mirrors the StaleEntry computation) ---
    usage = _load_usage()
    total_opens = sum(u["opens"] for u in usage.values())
    now = datetime.datetime.now()
    stale = []
    ranked = []
    if usage:
        keyed = {_entry_key(e): e for e in entries}
        for entry_id, stats in usage.items():
            entry = keyed.get(entry_id)
            title = (entry.get("title") if entry else None) or entry_id
            ranked.append((title, stats["opens"]))
            last = stats["last_opened"]
            if last is None:
                stale.append((title, None))
            elif (now - last).days > _STALE_AFTER_DAYS:
                stale.append((title, (now - last).days))
        ranked.sort(key=lambda r: (-r[1], r[0].lower()))
        stale.sort(key=lambda s: (-1 if s[1] is None else s[1]), reverse=True)

    # --- render (mirrors LibraryAnalyticsText.Format) ---
    lines = []
    lines.append("EnneadTab Library Insights")
    lines.append("==========================")
    lines.append(u"Entries: {0} · Total opens: {1}".format(len(entries), total_opens))
    lines.append("")
    _append_bar_section(lines, "Definitions per category", category_counts[:15])
    _append_bar_section(lines, "Top tags", tag_counts[:15])
    _append_bar_section(lines, "Most-used plugins", plugin_counts[:15])

    lines.append("Sidecar completeness")
    lines.append("  {0}/{1} entries have a *.ennead.json sidecar ({2} clean, {3} with warnings)".format(
        with_sidecar, len(entries), sidecar_clean, sidecar_warned))
    lines.append("")

    if not usage:
        lines.append("Usage")
        lines.append("  (no library-usage.json found -- open definitions from the")
        lines.append("   Grasshopper Library Explorer to start recording usage)")
        lines.append("")
    else:
        lines.append("Most-opened entries")
        for title, opens in ranked[:10]:
            lines.append("  {0} ({1} opens)".format(title, opens))
        lines.append("")
        lines.append("Stale entries (no opens in {0} days) -- cleanup hit-list".format(_STALE_AFTER_DAYS))
        if not stale:
            lines.append("  (none -- everything was opened recently)")
        else:
            for title, days in stale[:20]:
                age = "never opened" if days is None else "last opened {0}d ago".format(days)
                lines.append("  - {0} ({1})".format(title, age))
        if len(stale) > 20:
            lines.append("  ... and {0} more".format(len(stale) - 20))
        lines.append("")

    RHINO_FORMS.notification(
        title="Library Insights",
        main_text="{0} catalog entries".format(len(entries)),
        sub_text="\n".join(lines),
        width=640,
        height=520)


if __name__ == "__main__":
    library_insights()
