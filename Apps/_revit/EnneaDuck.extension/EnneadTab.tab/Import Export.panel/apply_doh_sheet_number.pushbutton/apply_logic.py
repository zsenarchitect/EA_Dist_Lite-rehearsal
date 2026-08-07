# -*- coding: utf-8 -*-
"""Pure (Revit-free) logic for the Apply DOH SheetNum button.
Dual-safe for IronPython 2.7 and CPython 3.x: no f-strings, no type hints,
no reliance on dict/set iteration order."""
from collections import namedtuple

SheetRow = namedtuple(
    "SheetRow",
    ["sheet_id", "live", "internal", "doh", "is_placeholder", "is_changable",
     "owner"],
)

MODE_INTERNAL = "INTERNAL"
MODE_DOH = "DOH"
MODE_IDENTICAL = "IDENTICAL"
MODE_DRIFT = "DRIFT"
MODE_MIXED = "MIXED"
MODE_EMPTY = "EMPTY"

SOURCE_INTERNAL = "internal"
SOURCE_DOH = "doh"

TEMP_PREFIX = "__APPLY_TMP__"


def is_empty(value):
    return value is None or value == ""


def _source_value(row, source):
    return row.internal if source == SOURCE_INTERNAL else row.doh


def classify(row):
    """Return 'P','Q','G','N' for a row whose internal AND doh are non-empty."""
    if is_empty(row.internal) or is_empty(row.doh):
        raise ValueError("classify() requires both stores populated")
    li = row.live == row.internal
    ld = row.live == row.doh
    if li and ld:
        return "G"
    if li:
        return "P"
    if ld:
        return "Q"
    return "N"


def infer_mode(rows):
    classifiable = [r for r in rows
                    if not is_empty(r.internal) and not is_empty(r.doh)]
    if not classifiable:
        return MODE_EMPTY
    classes = set(classify(r) for r in classifiable)
    if classes == set(["G"]):
        return MODE_IDENTICAL
    if "N" in classes:
        return MODE_DRIFT
    has_p = "P" in classes
    has_q = "Q" in classes
    if has_p and has_q:
        return MODE_MIXED
    if has_q:
        return MODE_DOH
    return MODE_INTERNAL


def find_incomplete(rows):
    return [r.sheet_id for r in rows
            if not r.is_placeholder and (is_empty(r.internal) or is_empty(r.doh))]


def find_duplicates(rows, source):
    buckets = {}
    for r in rows:
        v = _source_value(r, source)
        if is_empty(v):
            continue
        buckets.setdefault(v, []).append(r.sheet_id)
    out = {}
    for v, ids in buckets.items():
        if len(ids) > 1:
            out[v] = ids
    return out


def duplicate_detail(rows, source):
    """For every duplicated value in `source`, name the sheets that carry it,
    identified by their live SheetNumber -- the unique handle you see in Revit's
    Sheet browser. (Two sheets can share a stored DOH value because Revit only
    enforces uniqueness on the live number, not on the custom parameter.)
    Returns a sorted list of strings, one per duplicated value; empty if none."""
    dups = find_duplicates(rows, source)
    id_to_live = {}
    for r in rows:
        id_to_live[r.sheet_id] = r.live
    lines = []
    for v in sorted(dups.keys()):
        handles = []
        for sid in dups[v]:
            live = id_to_live.get(sid)
            handles.append(live if not is_empty(live) else ("id " + str(sid)))
        lines.append("  " + v + "  ->  " + ", ".join(sorted(handles)))
    return lines


def find_collisions(rows, source, reserved_numbers):
    reserved = set(reserved_numbers)
    hits = []
    for r in rows:
        if r.is_placeholder:
            continue
        v = _source_value(r, source)
        if is_empty(v):
            continue
        if v in reserved:
            hits.append((r.sheet_id, v))
    return hits


def find_non_changable(rows):
    return [r.sheet_id for r in rows if not r.is_changable]


def _handle(r):
    """The sheet's user-facing handle: its live SheetNumber, or a fallback id."""
    return r.live if not is_empty(r.live) else ("id " + str(r.sheet_id))


def blank_target_detail(rows, source):
    """Name the non-placeholder sheets that CAN'T receive the scheme being
    applied because their target store is empty. Surgical counterpart to the
    strict full-model completeness check: applying DOH only needs a DOH value
    (a missing Internal doesn't stop a DOH apply), so this looks at one store."""
    handles = sorted(_handle(r) for r in rows
                     if not r.is_placeholder and is_empty(_source_value(r, source)))
    return ["  " + h for h in handles]


def non_changable_detail(rows, relevant_ids=None):
    """Name the sheets owned by others (not editable in this session) AND who
    owns each, so the user knows whom to ask. Owner may be blank if the model
    is not workshared or Revit can't report it -- then say 'unknown user'.

    If `relevant_ids` is given, only sheets in that set are reported: ownership
    only blocks an Apply for sheets it will actually rewrite -- you need no edit
    rights on a sheet whose live number already matches the target and is left
    alone. Pass None (default) to report every owned sheet (overview use)."""
    pairs = []
    for r in rows:
        if r.is_changable:
            continue
        if relevant_ids is not None and r.sheet_id not in relevant_ids:
            continue
        owner = r.owner if not is_empty(r.owner) else "unknown user"
        pairs.append((_handle(r), owner))
    pairs.sort()
    return ["  " + h + "  (owned by " + o + ")" for h, o in pairs]


def collision_detail(rows, source, reserved_numbers):
    """Name sheets whose target value is already reserved by a placeholder."""
    id_to_live = {}
    for r in rows:
        id_to_live[r.sheet_id] = r.live
    lines = []
    for sid, v in find_collisions(rows, source, reserved_numbers):
        h = id_to_live.get(sid)
        h = h if not is_empty(h) else ("id " + str(sid))
        lines.append("  " + h + "  (wants " + v + ", reserved by a placeholder)")
    return sorted(lines)


def drift_detail(rows):
    """Name the sheets whose live SheetNumber matches neither stored scheme
    (class N) -- typically hand-edited or newly added sheets that wandered off
    both the Internal and DOH numbering. Reported by live SheetNumber handle
    (sorted) so the user can find them in the Sheet browser. Rows missing either
    store are not classifiable and are excluded. Empty list if nothing drifted."""
    lines = []
    for r in rows:
        if is_empty(r.internal) or is_empty(r.doh):
            continue
        if classify(r) == "N":
            lines.append("  " + _handle(r))
    return sorted(lines)


def make_temp_tokens(sheet_ids, run_guid):
    tokens = {}
    i = 0
    for sid in sheet_ids:
        tokens[sid] = TEMP_PREFIX + str(run_guid) + "__" + str(i)
        i += 1
    return tokens


def temp_prefix_collision(rows, run_guid):
    prefix = TEMP_PREFIX + str(run_guid) + "__"
    for r in rows:
        if r.live is not None and r.live.startswith(prefix):
            return True
    return False


def plan_apply(rows, target):
    """Plan ONLY the sheets whose live SheetNumber actually changes -- a sheet
    already sitting on its target value is left alone (not rewritten, not
    counted, not prompted about). Placeholders are never written. Returns
    ('noop', []) when nothing changes so the caller can skip the confirm.

    Safe to exclude unchanged sheets from the two-pass write: any collision
    between a changing sheet's target and an unchanged sheet's live number would
    require two sheets to share a target value, which the duplicate gate already
    forbids before Apply runs."""
    finals = []
    for r in rows:
        if r.is_placeholder:
            continue
        v = _source_value(r, target)
        if is_empty(v):
            continue          # nothing to apply -- can't write an empty number
        if r.live != v:
            finals.append((r.sheet_id, v))
    if not finals:
        return ("noop", [])
    return ("apply", finals)


def plan_capture(rows, mode):
    if mode == MODE_DOH:
        return ("refused",
                "Model is in DOH mode; capturing now would overwrite "
                "Sheet Number_Internal with DOH numbers.")
    targets = []
    for r in rows:
        if r.is_placeholder:
            continue
        if is_empty(r.internal):
            targets.append((r.sheet_id, r.live))
        elif not is_empty(r.doh) and classify(r) == "N":
            targets.append((r.sheet_id, r.live))
    return ("capture", targets)


def plan_fill_doh(rows):
    out = []
    for r in rows:
        if is_empty(r.doh) and not is_empty(r.internal):
            out.append((r.sheet_id, r.internal))
    return out


def plan_initialize(rows):
    """Bootstrap: seed BOTH stores from the live SheetNumber, each store only
    where it is EMPTY -- an already-filled store is left untouched (no
    overwrite). Placeholder sheets ARE included (consultant sheets in the index
    need numbering too); the write layer defensively skips any placeholder whose
    param Revit won't expose. Sheets owned by others are excluded here -- a write
    to a non-changable sheet would throw and roll back the whole transaction.
    Because it never overwrites, it needs no mode guard. Returns a 2-tuple of
    (internal_assignments, doh_assignments), each a list of (sheet_id, live)."""
    internal_targets = []
    doh_targets = []
    for r in rows:
        if not r.is_changable:
            continue
        if is_empty(r.live):
            continue
        if is_empty(r.internal):
            internal_targets.append((r.sheet_id, r.live))
        if is_empty(r.doh):
            doh_targets.append((r.sheet_id, r.live))
    return (internal_targets, doh_targets)
