# -*- coding: utf-8 -*-
"""The card shown while the user waits for a sync (Revit) or a save (Rhino).

A sync-to-central is dead time: the UI thread is frozen, the user is blocked,
and until now EnneadTab said nothing. This is the one recurring moment where we
already have their attention and cost them nothing to take it.

Shared verbatim by Revit and Rhino -- both hosts call `show_session_card` and
`on_sync_finished`, so there is no per-framework copy to drift, the same
construction that keeps RECAP.py honest.

WHY THIS RENDERS OUT OF PROCESS
-------------------------------
Nothing running inside Revit can draw during a sync. We hand a payload to
NOTIFICATION.messenger, which writes a JSON file into the host inbox and wakes
NotificationHost.exe -- a separate process, unaffected by the frozen UI thread.
Both steps are a local file write and a non-blocking `os.startfile`. Same
reasoning, same shape, as ARCADE.start_wait_watch.

WHY THERE IS NO "DISMISS"
-------------------------
Today's NotificationHost has no dismiss channel; a card leaves when its own
timer expires. So instead of pretending, the card's lifetime is sized to the
wait: `CARD_STAY_SECONDS` is pinned to ARCADE.WAIT_THRESHOLD_SECONDS. A normal
sync finishes and the card has already gone; a sync that outlives it is exactly
the case where the arcade watcher fires and takes over. Attention returns to
Revit either way, and `on_sync_finished` does the work that genuinely belongs at
the end -- reporting to the Bank -- rather than faking a window close. Early
dismissal needs a host-side control message; that ships with the dedicated
desktop app.

THE POSITIVITY RULE
-------------------
Only successful, flattering facts are eligible. This is enforced at the SOURCE,
not in the copy: SESSION_STATS.get_warnings_cleared returns None on an increase,
and every candidate here is a count of work done. There is deliberately no
"below average" or "you have not used X lately" path to accidentally reach, the
same way recap_claims has no "you might be #1" path. A guaranteed-available
fallback tier means the list is never empty, so there is always something
positive to say.

Nothing here fabricates. A metric that came back None is dropped from the card,
never rendered as 0, and the coin/rank lines vanish entirely when the Bank is
unreachable rather than showing a stale-looking zero.

IronPython 2.7 SAFE. No f-strings, no type hints, no pathlib.
"""

import time

try:
    from EnneadTab import (ARCADE, CONFIG, ERROR_HANDLE, LEADER_BOARD,
                           NOTIFICATION, SESSION_STATS)
except Exception:  # pragma: no cover - bare-import fallback for older loaders
    import ARCADE  # pyright: ignore
    import CONFIG  # pyright: ignore
    import ERROR_HANDLE  # pyright: ignore
    import LEADER_BOARD  # pyright: ignore
    import NOTIFICATION  # pyright: ignore
    import SESSION_STATS  # pyright: ignore


SETTING_KEY = "checkbox_sync_summary_card"

# Pinned to the arcade's threshold on purpose -- see the module docstring. If one
# moves, move both: a card that outlives the arcade hand-off stacks two surfaces
# on top of each other.
CARD_STAY_SECONDS = ARCADE.WAIT_THRESHOLD_SECONDS

# Below this the card is not worth the interruption. A 5-second sync 20 seconds
# into a session has nothing interesting to report, and firing anyway is how a
# welcome surface becomes noise the user mutes forever.
MIN_SESSION_SECONDS = 5 * 60

# The recommendation is chosen at startup and read from the store here, so the
# sync path never walks the knowledge database.
KEY_RECOMMENDATION = "EA_SYNC_CARD_RECOMMENDATION"
KEY_LAST_SHOWN = "EA_SYNC_CARD_LAST_SHOWN"

# One card per this window. Someone syncing every two minutes gets the card
# occasionally, not every time.
MIN_SECONDS_BETWEEN_CARDS = 45 * 60

BANK_URL = "https://enneadtab.com/bank"


def is_enabled():
    """Per-user opt-out. Defaults on, like the weekly recap digest."""
    return CONFIG.get_setting(SETTING_KEY, True)


# --------------------------------------------------------------- copy helpers

def _readable_duration(seconds):
    """'2 hr 40 min' / '35 min'. Minutes only below an hour -- nobody cares
    about the seconds they spent in Revit today."""
    try:
        total_minutes = int(seconds // 60)
    except Exception:
        return None
    if total_minutes < 1:
        return None
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours and minutes:
        return "{} hr {} min".format(hours, minutes)
    if hours:
        return "{} hr".format(hours)
    return "{} min".format(minutes)


def _plural(count, singular, plural=None):
    if plural is None:
        plural = singular + "s"
    return "{} {}".format(count, singular if count == 1 else plural)


# --------------------------------------------------------------- candidates

def _candidates(stats, balance, rank):
    """Eligible lines, best first.

    Each entry is (score, text). Only facts that are both AVAILABLE and
    FLATTERING get in -- there is no softening branch, because a claim we would
    have to soften is a claim we should not make.
    """
    out = []

    cleared = stats.get("warnings_cleared")
    if cleared:
        # Highest score: the user fixed something the whole model shares.
        out.append((100, "You cleared {} in this model.".format(
            _plural(cleared, "warning"))))

    views = stats.get("views_touched")
    if views:
        out.append((70, "You worked across {}.".format(_plural(views, "view"))))

    runs = stats.get("tool_runs")
    distinct = stats.get("distinct_tools")
    if runs and distinct and distinct > 1:
        out.append((65, "You ran {}, {} different ones.".format(
            _plural(runs, "EnneadTab tool"), distinct)))
    elif runs:
        out.append((60, "You ran {} this session.".format(
            _plural(runs, "EnneadTab tool"))))

    readable = _readable_duration(stats.get("session_seconds"))
    if readable:
        out.append((40, "You have been in this session for {}.".format(readable)))

    if rank:
        # An exact, computed, firm-wide comparison -- the one honest answer we
        # have to "how do I compare to the office". A tool-usage office average
        # has no source yet, so it is not claimed here at all.
        out.append((90, "You are #{} on the office board.".format(rank)))

    out.sort(key=lambda pair: pair[0], reverse=True)
    return out


def _earned_today(wallet):
    """Quacks credited today, straight from the Bank's own ledger rows.

    Deliberately "today" and not "this session". We cannot know session
    earnings: value is derived server-side, and our events do not even reach the
    Bank until the next startup flush. What the wallet's `recent` rows give us
    IS server-authoritative, so this is the honest version of the number rather
    than a client-side guess dressed up as one.

    Compares the date prefix instead of parsing timestamps -- `created_at` is
    ISO-8601, so the first ten characters are the date, and no strptime format
    can drift out from under us.
    """
    if not isinstance(wallet, dict):
        return None
    rows = wallet.get("recent")
    if not isinstance(rows, list):
        return None
    today = time.strftime("%Y-%m-%d")
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        created = row.get("created_at")
        if not created or str(created)[:10] != today:
            continue
        try:
            delta = int(row.get("delta", 0))
        except Exception:
            continue
        if delta > 0:
            total += delta
    return total if total > 0 else None


def _coin_line(balance, earned):
    """The money line, or None when the Bank told us nothing.

    Never renders a zero balance as a fact: `get_balance` already returns None
    for "no ledger rows at all", and we would rather say nothing than tell
    somebody they have 0 quacks because a token expired.
    """
    if balance is None:
        return None
    if earned:
        return "+{} quacks today. Balance: {}.".format(earned, balance)
    return "Balance: {} quacks.".format(balance)


def _actions(balance):
    """At most two -- the renderer's hard cap.

    Arcade first when it is installed and wanted: on a long sync it is the more
    useful of the two, and the watcher is about to offer it anyway.
    """
    actions = []
    try:
        if not ARCADE.is_hate_arcade():
            exe = ARCADE.get_installed_arcade_exe()
            if exe:
                actions.append({
                    "id": "sync_card_arcade",
                    "label": "Play arcade",
                    "type": "open_path",
                    "payload": exe,
                })
    except Exception:
        pass

    # Only offered when the Bank actually answered. Linking somebody to a wallet
    # page that cannot show them a balance is worse than not linking at all.
    if balance is not None and len(actions) < 2:
        actions.append({
            "id": "sync_card_bank",
            "label": "My bank",
            "type": "open_url",
            "payload": BANK_URL,
        })
    return actions


# --------------------------------------------------------------- recommendation

@ERROR_HANDLE.try_catch_error(is_pass=True)
def refresh_recommendation():
    """Pick a popular tool this user has not run, and stash it. Startup only.

    Deliberately NOT done at sync time: this reads the knowledge database, and
    the sync path is allowed exactly zero avoidable file walks.
    """
    try:
        from EnneadTab import DATA_FILE, DOCUMENTATION, ENVIRONMENT, LOG
    except Exception:
        return None

    try:
        if ENVIRONMENT.IS_REVIT_ENVIRONMENT:
            knowledge = DOCUMENTATION.get_revit_knowledge()
        else:
            knowledge = DOCUMENTATION.get_rhino_knowledge()
    except Exception:
        return None
    if not isinstance(knowledge, dict) or not knowledge:
        return None

    try:
        log_data = DATA_FILE.get_data(LOG.LOG_FILE_NAME)
    except Exception:
        log_data = {}
    used = set()
    if isinstance(log_data, dict):
        for record in log_data.values():
            if isinstance(record, dict) and record.get("function_name"):
                used.add(record.get("function_name"))

    for entry in knowledge.values():
        if not isinstance(entry, dict):
            continue
        if not entry.get("is_popular"):
            continue
        alias = entry.get("alias")
        if alias and alias not in used and alias != "Alias not set":
            SESSION_STATS.store_set(KEY_RECOMMENDATION, alias)
            return alias
    return None


def _recommendation_line():
    alias = SESSION_STATS.store_get(KEY_RECOMMENDATION)
    if not alias:
        return None
    return "Not tried yet: {}.".format(alias)


# --------------------------------------------------------------- the card

def build_card(doc=None):
    """The renderer-agnostic payload, or None when there is nothing worth saying.

    Returned as a structured dict rather than a finished string so the dedicated
    desktop app can lay the same facts out differently without the copy being
    rewritten. `render_text` is the only place that squeezes it into the
    single-`main_text` budget today's NotificationHost gives us.
    """
    stats = SESSION_STATS.snapshot(doc) or {}

    session_seconds = stats.get("session_seconds")
    if session_seconds is not None and session_seconds < MIN_SESSION_SECONDS:
        return None

    # Cache-only, and read once each: this runs microseconds before the UI
    # thread freezes, so neither a network round trip nor a redundant file read
    # is acceptable here.
    wallet = LEADER_BOARD.get_wallet(cached_only=True)
    board = LEADER_BOARD.get_leaderboard(cached_only=True)
    balance = LEADER_BOARD.balance_from_wallet(wallet)
    rank = LEADER_BOARD.rank_from_leaderboard(board)

    lines = _candidates(stats, balance, rank)
    if not lines:
        return None

    return {
        "stats": stats,
        "lines": [text for _score, text in lines],
        "coin_line": _coin_line(balance, _earned_today(wallet)),
        "recommendation": _recommendation_line(),
        "actions": _actions(balance),
    }


def render_text(card, max_lines=3):
    """Squeeze the card down to one `main_text` block.

    Headline plus the best few facts. The cap exists because a toast that needs
    scrolling is a toast nobody reads.
    """
    parts = ["While you sync..."]
    parts.extend(card.get("lines", [])[:max_lines])
    if card.get("coin_line"):
        parts.append(card["coin_line"])
    if card.get("recommendation"):
        parts.append(card["recommendation"])
    return "\n".join(parts)


def _should_show_now():
    last = SESSION_STATS.store_get(KEY_LAST_SHOWN)
    if last is None:
        return True
    try:
        return (time.time() - float(last)) >= MIN_SECONDS_BETWEEN_CARDS
    except Exception:
        return True


@ERROR_HANDLE.try_catch_error(is_pass=True)
def show_session_card(doc_title=None, doc=None):
    """Show the card. Call LAST in the sync-start path, right before ARCADE.

    `is_pass` rather than `is_silent`: this runs on every sync on every machine
    in the office, and `is_silent` still sends an error email. A card that fails
    to appear is a nicety not delivered, not an incident worth mailing the firm
    about on every sync -- the same call RECAP.show_pending_digest makes.
    """
    if not is_enabled():
        return False
    if not _should_show_now():
        return False

    card = build_card(doc)
    if not card:
        return False

    SESSION_STATS.store_set(KEY_LAST_SHOWN, time.time())

    kwargs = {
        "main_text": render_text(card),
        "level": "info",
        "animation_stay_duration": CARD_STAY_SECONDS,
    }
    if card.get("actions"):
        kwargs["actions"] = card["actions"]

    NOTIFICATION.messenger(**kwargs)
    return True


@ERROR_HANDLE.try_catch_error(is_pass=True)
def on_sync_finished(doc=None, doc_title=None):
    """End-of-wait bookkeeping. Call from doc-synced / after a Rhino save.

    Named for what it does. It does NOT close the card -- today's host has no
    dismiss channel and the card is already sized to expire on its own (see the
    module docstring). What genuinely belongs here is telling the Bank what
    happened, which is queued locally and posted at the next startup so this
    never adds latency to a sync.
    """
    cleared = SESSION_STATS.get_warnings_cleared(doc)
    if cleared:
        LEADER_BOARD.report_warnings_cleared(cleared, doc_title)
    return True


def peek():
    """Diagnostic: what the card would say right now. Shows nothing."""
    card = build_card()
    return {
        "enabled": is_enabled(),
        "due": _should_show_now(),
        "card": card,
        "text": render_text(card) if card else None,
    }


def unit_test():
    SESSION_STATS.mark_session_start()
    SESSION_STATS.note_view("1")
    SESSION_STATS.note_view("2")
    print("SYNC_SUMMARY peek: {}".format(peek()))


if __name__ == "__main__":
    unit_test()
