# -*- coding: utf-8 -*-
"""Client for EnneadTab-Bank -- the firm-wide virtual-coin ("quacks") economy.

Replaces the stub that used to keep a `money` integer in the per-user settings
file. There is no local ledger any more: the Bank owns an append-only ledger and
derives every balance by folding it, so anything we stored here would be a lie
with a second source of truth.

WHAT THIS TALKS TO
------------------
    POST /bank/api/events       emit a measurement; the SERVER decides its value
    GET  /bank/api/wallet       balance (banked / pool / spendable)
    GET  /bank/api/leaderboard  anonymized firm board + this caller's own rank

Proxied by EnneadTab-Home at enneadtab.com/bank/*.

THE TWO RULES THAT SHAPE THIS FILE
----------------------------------
1. **Clients never send coin amounts.** We send `metrics` (counts, measurements)
   and the Bank's server-side rules engine derives the value. A client that
   posts its own numbers is a client that can be edited into printing money.
2. **Nothing here may block a sync.** `report_event` does NOT hit the network --
   it appends to a local outbox. `flush_outbox` does the POSTing, and is called
   from startup where latency is free. The envelope's 48h `occurred_at` window
   is exactly what makes that deferral legal, and `_prune` enforces it so we
   never POST an event the server would reject as too old.

   Same reasoning for reads: `get_wallet`/`get_leaderboard` cache their last
   good response, and the sync-time card reads the CACHE (`cached_only=True`).
   A stale balance is fine; a 10-second HTTP GET in front of a sync is not.

AUTH
----
`Authorization: Bearer <AUTH.get_token()>`. That token comes from
enneadtab.com/api/desktop-auth and is the same `base64url(payload).sig` shape
the Bank's desktop credential verifies (lib/ingest/credentials.ts: "Format
mirrors EnneadTab-Home lib/desktop-token.ts"). The desktop path is the only
credential that can BOTH write events and read a wallet -- the service key is
rejected on every read route -- which is why no shared firm secret ships to
workstations.

`get_token()` returns None when the user has never signed in, and never blocks.
That None is the natural "leave the coin lines off the card" signal; it is not
an error and is not reported as one.

IronPython 2.7 SAFE. No f-strings, no type hints, no pathlib. Loaded inside both
Revit and Rhino.
"""

import json
import random
import time

try:
    from EnneadTab import (AUTH, DATA_FILE, ENVIRONMENT, ERROR_HANDLE, TIME,
                           USER, WEB_GUARD)
except Exception:  # pragma: no cover - bare-import fallback for older loaders
    import AUTH  # pyright: ignore
    import DATA_FILE  # pyright: ignore
    import ENVIRONMENT  # pyright: ignore
    import ERROR_HANDLE  # pyright: ignore
    import TIME  # pyright: ignore
    import USER  # pyright: ignore
    import WEB_GUARD  # pyright: ignore


BANK_BASE_URL = "https://enneadtab.com/bank"
EVENTS_URL = BANK_BASE_URL + "/api/events"
WALLET_URL = BANK_BASE_URL + "/api/wallet"
LEADERBOARD_URL = BANK_BASE_URL + "/api/leaderboard"

ENVELOPE_VERSION = 1

# The server rejects occurred_at older than 48h. Prune below that with an hour of
# headroom so an event cannot expire between prune and POST.
MAX_EVENT_AGE_SECONDS = 47 * 60 * 60

# Outbox bound. A machine that is offline for a week must not grow an unbounded
# file, and everything past the age limit is unsendable anyway.
MAX_OUTBOX_ITEMS = 300

# How much of the outbox one startup flush may drain.
#
# This has to exceed a heavy user's DAILY volume, not be a polite small number.
# LOG.log emits one event per button click; at ~40 clicks/day against a 25-event
# flush, 15 events/day would age out at the 47h mark having never been sent, and
# the loss would be completely invisible. Draining the whole outbox is the only
# setting that cannot silently lose runs.
FLUSH_MAX_ITEMS = MAX_OUTBOX_ITEMS

# ...but bounded in wall-clock too. 300 POSTs that each hit the 8s timeout is 40
# minutes of a daemon thread grinding on a dead network. Stopping early is free:
# whatever is left stays queued and is still well inside the server's 48h window
# on the next launch.
FLUSH_MAX_SECONDS = 90

# Per call. Short on purpose: this runs on desktops with flaky VPN, and every
# caller treats failure as "skip", never as "retry harder".
HTTP_TIMEOUT = 8

OUTBOX_FILE = "bank_outbox"
CACHE_FILE = "bank_cache"

# Which documents have already produced an open_model charge today. Durable on
# purpose -- see report_model_opened.
OPEN_CHARGED_FILE = "bank_open_charged"

# Reads are cached this long. The card wants "roughly current", not live.
CACHE_TTL_SECONDS = 30 * 60


# --------------------------------------------------------------- event id

# Monotonic within this process. See _new_event_id for why a timestamp and a
# random suffix are not enough on their own.
_EVENT_SEQUENCE = 0


def _new_event_id():
    """Globally-unique idempotency key.

    `event.event_id` is the Bank's TEXT primary key and dedupe is `ON CONFLICT
    DO NOTHING`, so a collision is not a retry -- it SILENTLY DISCARDS a real
    event. Uniqueness must hold across the whole firm, hence the user + app
    prefix. Built from time+random rather than `uuid` for the same reason
    NOTIFICATION._write_inbox_item is: it is the pattern already proven on every
    runtime this file loads in.

    The in-process counter is what makes it actually unique rather than merely
    unlikely to collide. Timestamp-plus-random alone is a birthday problem inside
    a single millisecond: ~500 events minted in one tick collide roughly a fifth
    of the time against a 900k random space. Real clicks are seconds apart so it
    almost never bit in practice, but "almost never" is the wrong guarantee for a
    primary key, and the counter costs nothing.

    Not locked: IronPython's GIL makes the increment atomic enough here, and a
    lost update would still be salvaged by the timestamp and random suffix.
    """
    global _EVENT_SEQUENCE
    _EVENT_SEQUENCE += 1
    try:
        user_name = USER.USER_NAME
    except Exception:
        user_name = "unknown"
    try:
        app_name = ENVIRONMENT.get_app_name()
    except Exception:
        app_name = "EnneadTab"
    return "{}:{}:{}:{}:{}".format(
        app_name,
        user_name,
        int(time.time() * 1000),
        _EVENT_SEQUENCE,
        random.randint(100000, 999999),
    )


def _source_app():
    try:
        return "EnneadTab-{}".format(ENVIRONMENT.get_app_name())
    except Exception:
        return "EnneadTab"


# --------------------------------------------------------------- transport

def _auth_headers():
    """Bearer headers, or None when the user has not signed in."""
    try:
        token = AUTH.get_token()
    except Exception:
        return None
    if not token:
        return None
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer {}".format(token),
    }


def _request(method, url, headers, body=None):
    """One HTTP call across three runtimes.

    Returns (status_code, decoded_json_or_None), or (None, None) when no HTTP
    library was usable. Mirrors LOG.send_usage_to_infrawatch's fallback order --
    Revit ships urllib3, Rhino's IronPython has urllib2, CPython tools have
    urllib.request -- because that is the only combination proven to work on
    all three here.
    """
    for attempt in (_via_urllib3, _via_urllib2, _via_urllib_request):
        status, payload, usable = attempt(method, url, headers, body)
        if usable:
            return status, payload
    ERROR_HANDLE.print_note("No HTTP library available for Bank call")
    return None, None


def _decode(raw):
    try:
        if raw is None:
            return None
        if not isinstance(raw, str):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception:
        return None


def _via_urllib3(method, url, headers, body):
    try:
        import urllib3
    except ImportError:
        return None, None, False
    try:
        http = urllib3.PoolManager()
        # redirect=False is load-bearing, not tidiness. Home's middleware answers
        # a gated API path with a 302 to an SSO login page; followed, that lands
        # on a 200 with an HTML body, and this client used to score that as a
        # delivered event and delete it. See WEB_GUARD.
        kwargs = {"headers": headers, "timeout": float(HTTP_TIMEOUT),
                  "redirect": False}
        if body is not None:
            kwargs["body"] = json.dumps(body).encode("utf-8")
        response = http.request(method, url, **kwargs)
        return response.status, _decode(response.data), True
    except Exception as e:
        ERROR_HANDLE.print_note("Bank call error (urllib3): {}".format(e))
        return None, None, True


def _via_urllib2(method, url, headers, body):
    # Py2-only; the bare import raising on CPython 3 is the correct skip signal.
    try:
        import urllib2
    except ImportError:
        return None, None, False
    try:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib2.Request(url, data=data, headers=headers)
        # urllib2 infers POST from a non-None body; anything else needs telling.
        if method != "POST":
            request.get_method = lambda: method
        response = WEB_GUARD.urlopen_no_redirect(request, HTTP_TIMEOUT)
        return response.getcode(), _decode(response.read()), True
    except Exception as e:
        # An HTTPError is a real, useful answer (401/429/...), not a transport
        # failure -- read its body rather than throwing the status away.
        code = getattr(e, "code", None)
        if code is not None:
            try:
                return code, _decode(e.read()), True
            except Exception:
                return code, None, True
        ERROR_HANDLE.print_note("Bank call error (urllib2): {}".format(e))
        return None, None, True


def _via_urllib_request(method, url, headers, body):
    try:
        import urllib.request
        import urllib.error
    except ImportError:
        return None, None, False
    try:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url, data=data, headers=headers, method=method)
        response = WEB_GUARD.urlopen_no_redirect(request, HTTP_TIMEOUT)
        return response.getcode(), _decode(response.read()), True
    except Exception as e:
        code = getattr(e, "code", None)
        if code is not None:
            try:
                return code, _decode(e.read()), True
            except Exception:
                return code, None, True
        ERROR_HANDLE.print_note("Bank call error (urllib.request): {}".format(e))
        return None, None, True


# --------------------------------------------------------------- outbox

def _read_outbox():
    try:
        data = DATA_FILE.get_data(OUTBOX_FILE)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("events")
    return items if isinstance(items, list) else []


def _write_outbox(items):
    try:
        DATA_FILE.set_data({"events": items}, OUTBOX_FILE)
        return True
    except Exception:
        return False


def _prune(items):
    """Drop what the server would reject anyway, then bound the file.

    Age first, then cap -- capping first could keep a full page of events that
    are all too old to send and evict fresh ones behind them.
    """
    cutoff = time.time() - MAX_EVENT_AGE_SECONDS
    fresh = []
    for item in items:
        try:
            if float(item.get("_queued_at", 0)) >= cutoff:
                fresh.append(item)
        except Exception:
            continue
    if len(fresh) > MAX_OUTBOX_ITEMS:
        fresh = fresh[-MAX_OUTBOX_ITEMS:]
    return fresh


@ERROR_HANDLE.try_catch_error(is_pass=True)
def report_event(event_type, action, metrics=None, result="success", subject=None):
    """Queue one event for the Bank. Local write only -- never touches the net.

    `is_pass` rather than `is_silent`: this is called from sync hooks on every
    machine in the office, and `is_silent` still emails an error report. A coin
    that does not get awarded is a nicety missed, not an incident worth mailing
    the whole firm about on every sync.

    Args:
        event_type (str): e.g. "tool_run", "sync_event", "model_metric".
        action (str): the specific action. Stored byte-verbatim by the server --
            it is NOT trimmed or case-folded, so it must match the rule's
            allow-list exactly to score.
        metrics (dict, optional): flat map of finite numbers ONLY. Never coin
            amounts.
        result (str): "success" or "error". Anything else is rejected as a 400.
        subject (str, optional): what the action acted on (doc name, tool, ...).
    """
    if result not in ("success", "error"):
        result = "success"

    envelope = {
        "version": ENVELOPE_VERSION,
        "event_id": _new_event_id(),
        "source_app": _source_app(),
        "event_type": event_type,
        "action": action,
        "result": result,
        "occurred_at": TIME.get_utc_timestamp_iso(),
    }
    if subject is not None:
        envelope["subject"] = str(subject)

    clean = _clean_metrics(metrics)
    if clean:
        envelope["metrics"] = clean

    # Local bookkeeping, stripped before POST. The server ignores unknown keys,
    # so this would not be rejected -- but the ledger is firm-wide and legally
    # discoverable, and our queue mechanics have no business being in it.
    envelope["_queued_at"] = time.time()

    items = _prune(_read_outbox())
    items.append(envelope)
    return _write_outbox(items)


def _clean_metrics(metrics):
    """Keep only finite numbers -- the server 400s the whole event otherwise."""
    if not isinstance(metrics, dict):
        return {}
    clean = {}
    for key, value in metrics.items():
        if isinstance(value, bool):
            # bool is an int subclass in Python; a True would post as 1 and read
            # as a measurement. Refuse it rather than silently coerce.
            continue
        try:
            number = float(value)
        except Exception:
            continue
        if number != number or number in (float("inf"), float("-inf")):
            continue
        clean[key] = value
    return clean


@ERROR_HANDLE.try_catch_error(is_pass=True)
def flush_outbox(max_items=FLUSH_MAX_ITEMS, max_seconds=FLUSH_MAX_SECONDS):
    """POST queued events. Call from startup, never from a sync hook.

    Returns the number of events the server accepted. A 4xx that is not 429 is
    permanent (bad envelope, no credential) -- the event is DROPPED rather than
    retried forever, because a poison event would otherwise block the queue
    behind it on every launch.

    Stops early on 429/503 (asked to back off), on a transport failure, or once
    `max_seconds` is spent. Every early exit leaves the untried remainder queued,
    so a stop is a pause, never a loss.
    """
    items = _prune(_read_outbox())
    if not items:
        _write_outbox(items)
        return 0

    headers = _auth_headers()
    if headers is None:
        # Not signed in. Keep the queue; the 48h window may still cover it once
        # the user authenticates.
        _write_outbox(items)
        return 0

    sent = 0
    started = time.time()
    # Index-based bookkeeping rather than list.remove(): envelopes are dicts, so
    # remove() compares them field by field against every earlier entry, which is
    # quadratic and was only invisible while the budget was 25.
    done = set()
    for index, envelope in enumerate(items[:max_items]):
        if (time.time() - started) >= max_seconds:
            break

        body = dict(envelope)
        body.pop("_queued_at", None)
        status, payload = _request("POST", EVENTS_URL, headers, body)

        if WEB_GUARD.is_delivered(status, payload):
            # Covers {"deduped": true} too -- a replay IS success.
            #
            # is_delivered, not `status == 200`: a 200 whose body did not parse
            # is an SSO login page, not an acknowledgement. Scoring that as
            # delivered is what silently destroyed every queued event before
            # 2026-08-07. The event must survive a response the Bank did not send.
            done.add(index)
            sent += 1
            continue
        if WEB_GUARD.is_redirect(status):
            # A redirect means the request never reached the Bank -- routing is
            # wrong. Retrying cannot fix it and every event would hit the same
            # wall, so stop and keep the queue intact.
            ERROR_HANDLE.print_note(WEB_GUARD.describe(status))
            break
        if status in (429, 503):
            # Throttled or limiter down. Stop the whole run; hammering is
            # exactly what these codes are asking us not to do.
            break
        if status is not None and 400 <= status < 500:
            done.add(index)
            continue
        # None / 5xx / an unparseable 200: transport or server trouble, or
        # something that is not the Bank answering. Keep it and stop.
        break

    remaining = [x for i, x in enumerate(items) if i not in done]
    _write_outbox(remaining)
    return sent


# --------------------------------------------------------------- reads

def _read_cache():
    try:
        data = DATA_FILE.get_data(CACHE_FILE)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(key, value):
    cache = _read_cache()
    cache[key] = {"fetched_at": time.time(), "value": value}
    try:
        DATA_FILE.set_data(cache, CACHE_FILE)
    except Exception:
        pass


def _cached(key, max_age=None):
    entry = _read_cache().get(key)
    if not isinstance(entry, dict):
        return None
    if max_age is not None:
        try:
            if (time.time() - float(entry.get("fetched_at", 0))) > max_age:
                return None
        except Exception:
            return None
    return entry.get("value")


def _fetch(key, url, cached_only):
    """Cache-first read. Returns the payload dict, or None.

    None means "we do not know" -- every caller must omit the corresponding line
    rather than render a zero. A fabricated balance is worse than a missing one.
    """
    if cached_only:
        return _cached(key)

    headers = _auth_headers()
    if headers is None:
        return _cached(key)

    status, payload = _request("GET", url, headers)
    if status == 200 and isinstance(payload, dict):
        _write_cache(key, payload)
        return payload
    return _cached(key)


def get_wallet(cached_only=False):
    """Balance for the signed-in user, or None.

    Server shape: {hasBankData, banked, pool, spendable, lifetimeEarned,
    season, recent, owned, prefs}. `hasBankData` False distinguishes "no ledger
    rows at all" from a legitimately-earned zero.
    """
    return _fetch("wallet", WALLET_URL, cached_only)


def get_leaderboard(season="current", cached_only=False):
    """Anonymized firm board, or None.

    Server shape: {hasBankData, scope, season, size, top[], cohort[], self,
    selfHandle}. Identities are Duck-XXXX handles; no email or display name ever
    leaves the Bank. `self` carries this caller's own rank and is None when the
    caller has no positive score yet.
    """
    url = LEADERBOARD_URL
    if season == "all":
        url += "?season=all"
    key = "leaderboard_{}".format(season)
    if cached_only:
        return _cached(key)

    headers = _auth_headers()
    if headers is None:
        return _cached(key)

    status, payload = _request("GET", url, headers)
    if status == 200 and isinstance(payload, dict):
        _write_cache(key, payload)
        return payload
    return _cached(key)


def balance_from_wallet(wallet):
    """Spendable quacks out of an already-fetched wallet, or None.

    Split from `get_balance` so a caller that already holds the payload -- the
    sync card, which also needs `recent` -- does not re-read the cache file just
    to pull one number out of it.

    `hasBankData` False means "no ledger rows at all", which is NOT a zero
    balance; it returns None so the coin line is omitted rather than telling a
    new user they have nothing.
    """
    if not isinstance(wallet, dict):
        return None
    if not wallet.get("hasBankData"):
        return None
    try:
        return int(wallet.get("spendable", 0))
    except Exception:
        return None


def rank_from_leaderboard(board):
    """Firm rank out of an already-fetched leaderboard, or None.

    `self` is None when the caller has no positive score yet -- unranked, not
    last place, so there is nothing to show.
    """
    if not isinstance(board, dict):
        return None
    own = board.get("self")
    if not isinstance(own, dict):
        return None
    try:
        return int(own.get("rank"))
    except Exception:
        return None


def get_balance(cached_only=True):
    """Spendable quacks, or None when unknown.

    Defaults to cached because the sync card is the main caller and must not
    make a network round trip in front of a freeze.
    """
    return balance_from_wallet(get_wallet(cached_only=cached_only))


def get_rank(cached_only=True):
    """This user's firm rank, or None when unranked/unknown."""
    return rank_from_leaderboard(get_leaderboard(cached_only=cached_only))


@ERROR_HANDLE.try_catch_error(is_pass=True)
def refresh(max_items=FLUSH_MAX_ITEMS):
    """Drain the outbox, then warm the read caches. BLOCKS on the network.

    Order matters -- flushing first means the wallet we then cache already
    includes whatever this machine had been sitting on.

    Prefer `refresh_async` from a startup path; call this directly only from a
    context where a minute or two of HTTP is acceptable (MiniBank's explicit
    "Refresh From Bank" button is the one such caller).
    """
    sent = flush_outbox(max_items=max_items)
    get_wallet()
    get_leaderboard()
    return sent


def refresh_async(max_items=FLUSH_MAX_ITEMS):
    """`refresh` on a daemon thread. This is what startup should call.

    A full outbox drain plus two reads is not something to put in front of a user
    opening Revit. Backgrounding it is safe here specifically because nothing in
    `refresh` touches the Revit or Rhino API -- it is files and sockets only, so
    the single-threaded-API rule that makes ASYNC.py unsafe in these hosts does
    not apply. Daemon, so a hung socket cannot keep the process alive at exit,
    and FLUSH_MAX_SECONDS caps how long it can spin even if it does hang.
    """
    try:
        import threading
        thread = threading.Thread(target=refresh, args=(max_items,))
        thread.setDaemon(True)
        thread.start()
        return True
    except Exception:
        # No threading available: skip rather than block the host's startup.
        return False


# --------------------------------------------------------------- convenience

def report_tool_run(tool_name, duration_seconds=None, script_path=None):
    """A tool was used. Emitted from LOG.log, once per instrumented button click.

    `action` is the tool's __title__ (newlines already flattened by LOG.log) --
    the same identity LOG's own record, the InfraWatch usage stream and the Wiki
    knowledge `alias` all key on. One identity across the ecosystem is worth more
    than matching any single rule's allow-list.

    `subject` carries the script's file name because __title__ is display copy
    that a designer can rename at will, while the script is the durable key.
    Sending both means Bank-side rules can later be curated against whichever
    field turns out to be right, without this client having to guess now.

    NOTE: as of EnneadTab-Bank cfa636b, `reward_tool_run_heavy`'s allow-list is
    ["StairMaker", "fix_warnings", "merge_materials", "simplify_blocks"] -- seed
    placeholder data that matches no real __title__ in this repo, so only the
    light rule (+1) can fire. That is a Bank-side data fix, not a client change.

    Args:
        tool_name (str): the tool's recorded name; becomes `action`, byte-verbatim.
        duration_seconds (float, optional): how long the run took, as context.
        script_path (str, optional): full script path; its basename becomes `subject`.
    """
    metrics = {}
    if duration_seconds is not None:
        # Sent as context only. The Bank's anti-gaming guard forbids any reward
        # rule from carrying a positive coefficient on duration -- so this can
        # never be farmed, by construction rather than by our restraint.
        metrics["duration_s"] = duration_seconds

    subject = tool_name
    if script_path:
        try:
            # Normalize separators first rather than trusting os.path.basename:
            # these paths are always Windows-shaped (they come from __file__ in
            # Revit/Rhino), but the tests and any CPython tooling run on POSIX,
            # where basename() would not split on a backslash and would hand the
            # whole path to the ledger. Same reason LOG._is_button_script does it.
            subject = str(script_path).replace("\\", "/").rstrip("/").split("/")[-1]
        except Exception:
            pass
    return report_event("tool_run", tool_name, metrics=metrics, subject=subject)


def report_warnings_cleared(count, doc_name=None):
    """Warnings went down. Matches reward_warnings_cleared.

    The action string must be exactly "fix_warnings" -- the server matches it
    byte-verbatim, so a prettier label here would silently score nothing.
    """
    if not count or count <= 0:
        return False
    return report_event(
        "fix_warnings",
        "fix_warnings",
        metrics={"warnings_cleared": count},
        subject=doc_name,
    )


def report_sync_queue_cut(doc_name=None):
    """Jumped the sync queue. Matches cost_sync_queue_cut."""
    return report_event("sync_event", "sync_queue_cut", subject=doc_name)


def report_sync_queue_waited(doc_name=None):
    """Waited their turn.

    No seeded rule matches this today, so it scores nothing and is recorded for
    when one exists. Deliberately still emitted: the ledger is the evidence a
    future rule would be back-filled from, and an unmatched event is stored
    harmlessly.
    """
    return report_event("sync_event", "sync_queue_wait", subject=doc_name)


def _open_charge_key(doc_name):
    return str(doc_name) if doc_name else "unknown"


def already_charged_for_open_today(doc_name):
    """Has this document already produced an open_model charge today?"""
    try:
        data = DATA_FILE.get_data(OPEN_CHARGED_FILE)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    return data.get(_open_charge_key(doc_name)) == time.strftime("%Y-%m-%d")


def _record_open_charge(doc_name):
    """Stamp today's date against this document, keeping ONLY today's entries.

    Pruning on every write is what stops this file growing forever: yesterday's
    stamps can never block anything, so there is no reason to keep them.
    """
    today = time.strftime("%Y-%m-%d")
    try:
        data = DATA_FILE.get_data(OPEN_CHARGED_FILE)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    fresh = dict((k, v) for k, v in data.items() if v == today)
    fresh[_open_charge_key(doc_name)] = today
    try:
        DATA_FILE.set_data(fresh, OPEN_CHARGED_FILE)
    except Exception:
        pass


def report_model_opened(warning_count, doc_name=None):
    """Opened a model. Matches cost_open_many_warnings.

    ONCE PER DOCUMENT PER DAY, and the guard lives here rather than at the call
    site on purpose.

    This is the only seeded rule with no dailyCap and no cooldownSeconds -- every
    other emitter is safe to fire freely because the server bounds it. Opening is
    passive and repeatable, so without this a user who opened the same
    200-warning model four times would be charged the full cap four times.

    The record is durable (a dump-folder file), NOT the process-scoped store the
    rest of this feature uses: an env var dies with Revit, and "restarted Revit
    twice today" is precisely the case being guarded against.

    Returns False when it declines to charge again.
    """
    if warning_count is None:
        return False
    if already_charged_for_open_today(doc_name):
        return False

    queued = report_event(
        "model_metric",
        "open_model",
        metrics={"warnings": warning_count},
        subject=doc_name,
    )
    if queued:
        _record_open_charge(doc_name)
    return queued


# --------------------------------------------------------------- diagnostics

def peek():
    """What the client currently believes. Never makes a network call."""
    return {
        "signed_in": _auth_headers() is not None,
        "outbox_pending": len(_read_outbox()),
        "balance_cached": get_balance(cached_only=True),
        "rank_cached": get_rank(cached_only=True),
    }


def unit_test():
    print("Bank client state: {}".format(peek()))
    print("Queued a probe event: {}".format(
        report_event("tool_run", "unit_test", metrics={"probe": 1})))
    print("Outbox now holds {} event(s)".format(len(_read_outbox())))


if __name__ == "__main__":
    unit_test()
