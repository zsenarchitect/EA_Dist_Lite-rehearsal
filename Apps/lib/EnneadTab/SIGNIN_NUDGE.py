# -*- coding: utf-8 -*-
"""Day-based sign-in onboarding nudge for the EnneadTab economy.

WHY THIS EXISTS
---------------
The economy earns and spends against the SSO desktop token, never the machine
username (USERPROFILE is NOT the company account -- contractors, shared machines,
and CannonDesign staff all break that guess). To converge the firm onto SSO we
nudge sign-in early, but WITHOUT ever blocking a tool.

THE RULE (owner decision 2026-08-12)
------------------------------------
- Ask at most ONCE per return-day. If the user defers today (maybe they are
  heads-down on a deadline), we do not ask again until the next day they return
  and launch a tool.
- The budget is 10 distinct return-days ([Not today]). Days the user is away
  never burn the budget -- the counter only moves on a day the user actually
  returns and defers.
- After the budget is spent, the daily prompt drops the [Not today] option but is
  STILL shown at most once per day and STILL runs the tool on close. It never
  blocks work; it just keeps asking, kindly, one day at a time.
- Signing in stops the prompt. A later token expiry re-prompts (missing auth
  proof) but does NOT re-impose the 10-day budget -- re-auth is a one-click
  refresh, not a fresh onboarding.

The decision core (`_decide` / `_apply_defer`) is PURE and unit-tested. The IO and
identity wrappers sit on top so the host UIs (WPF in Revit, Eto in Rhino) only
have to supply a prompt callback.

IronPython 2.7 SAFE. No f-strings, no type hints, no pathlib. Loaded inside both
Revit and Rhino.
"""

import os
import json
import time

# 10 distinct return-days of deferral, then the prompt can no longer be deferred
# (but still never blocks a tool).
DEFER_LIMIT_DAYS = 10

STATE_FILE = "signin_nudge.sexyDuck"


def _empty_state():
    return {"deferred_days": 0, "last_defer_day": None, "first_seen": None}


# --------------------------------------------------------------- pure core

def _spent(state):
    """True once the deferral budget of return-days is used up."""
    try:
        return int(state.get("deferred_days", 0)) >= DEFER_LIMIT_DAYS
    except Exception:
        return False


def _decide(signed_in, today, state):
    """Pure decision. Returns (should_prompt, can_defer).

    should_prompt is True unless the user is already signed in OR we already
    asked/deferred today. The spent budget does NOT silence the prompt -- it only
    removes the [Not today] option (can_defer).
    """
    if signed_in:
        return (False, False)
    can_defer = not _spent(state)
    if state.get("last_defer_day") == today:
        # Already asked once today -- stay quiet until the next return-day.
        return (False, can_defer)
    return (True, can_defer)


def _apply_defer(state, today):
    """Pure. Return the new state after a defer/close on `today`.

    Counts a NEW return-day only (idempotent within a day), and only increments
    the budget while it remains -- so a day past the limit still records
    last_defer_day (to suppress same-day re-asks) without overflowing the count.
    """
    new = dict(state)
    if new.get("first_seen") is None:
        new["first_seen"] = time.time()
    if new.get("last_defer_day") != today:
        current = new.get("deferred_days", 0)
        try:
            current = int(current)
        except Exception:
            current = 0
        if current < DEFER_LIMIT_DAYS:
            current = current + 1
        new["deferred_days"] = current
        new["last_defer_day"] = today
    return new


# --------------------------------------------------------------- io + identity

def _today():
    """Local calendar day as 'YYYY-MM-DD'."""
    return time.strftime("%Y-%m-%d", time.localtime())


def _get_state_path():
    """Per Windows profile, next to the AUTH token cache. Never shared."""
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        folder = os.path.join(appdata, "EnneadTab")
    else:
        folder = os.path.join(os.path.expanduser("~"), ".enneadtab")
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return os.path.join(folder, STATE_FILE)


def _load():
    path = _get_state_path()
    if not os.path.exists(path):
        return _empty_state()
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_state()
        state = _empty_state()
        state["deferred_days"] = data.get("deferred_days", 0)
        state["last_defer_day"] = data.get("last_defer_day")
        state["first_seen"] = data.get("first_seen")
        return state
    except Exception:
        return _empty_state()


def _save(state):
    path = _get_state_path()
    try:
        with open(path, "w") as f:
            json.dump(state, f)
        return True
    except Exception:
        return False


def is_signed_in():
    """True when a valid SSO token exists. Never raises, never blocks."""
    try:
        import AUTH
        return bool(AUTH.get_token())
    except Exception:
        return False


# --------------------------------------------------------------- public api

def should_prompt():
    """Should the sign-in nudge be shown right now? Never raises."""
    should, _ = _decide(is_signed_in(), _today(), _load())
    return should


def can_defer():
    """Is the [Not today] option still offered?"""
    return not _spent(_load())


def record_defer():
    """The user deferred (or closed the un-deferrable prompt). Stay quiet until
    the next return-day; burn one budget-day while any remain."""
    state = _apply_defer(_load(), _today())
    _save(state)
    return state


def maybe_prompt(prompt_fn):
    """Run one day's nudge. NON-BLOCKING -- never gates the tool.

    `prompt_fn(can_defer)` is the host UI hook (WPF/Revit, Eto/Rhino). It gets
    whether the [Not today] option should be shown, and returns one of:
    'signin' | 'defer' | 'close'. It must return promptly and must never block
    the tool from running afterward.

    Returns the action taken, or None when no prompt was shown (already signed in
    or already asked today).
    """
    should, could_defer = _decide(is_signed_in(), _today(), _load())
    if not should:
        return None
    try:
        action = prompt_fn(could_defer)
    except Exception:
        # A broken UI hook must NEVER block the tool.
        return None
    if action == "signin":
        try:
            import AUTH
            AUTH.request_auth()
        except Exception:
            pass
        return "signin"  # opted in -- do not record a defer
    record_defer()
    return action if action in ("defer", "close") else "close"


# --------------------------------------------------------------- unit test

def unit_test():
    empty = _empty_state()

    # Fresh, signed out, today -> prompt, can defer.
    assert _decide(False, "2026-08-12", empty) == (True, True)

    # Signed in -> never prompt.
    assert _decide(True, "2026-08-12", empty) == (False, False)

    # After deferring today, same day is quiet (but still deferrable).
    s1 = _apply_defer(empty, "2026-08-12")
    assert s1["deferred_days"] == 1 and s1["last_defer_day"] == "2026-08-12"
    assert _decide(False, "2026-08-12", s1) == (False, True)

    # Next return-day asks again.
    assert _decide(False, "2026-08-13", s1) == (True, True)

    # Deferring twice in one day does not double-count.
    s1b = _apply_defer(s1, "2026-08-12")
    assert s1b["deferred_days"] == 1

    # Days away do NOT burn the budget: 3 defers across 3 distinct return-days
    # (with arbitrary gaps) -> exactly 3.
    s = empty
    for day in ("2026-01-01", "2026-03-15", "2026-09-30"):
        s = _apply_defer(s, day)
    assert s["deferred_days"] == 3, s

    # Budget spent: prompt still shows on a new day, but can_defer is False.
    spent = {"deferred_days": DEFER_LIMIT_DAYS, "last_defer_day": "2026-08-11", "first_seen": 1.0}
    assert _decide(False, "2026-08-12", spent) == (True, False)
    # ...and same-day stays quiet.
    assert _decide(False, "2026-08-11", spent) == (False, False)

    # Deferring past the limit records the day but never overflows the count.
    over = _apply_defer(spent, "2026-08-12")
    assert over["deferred_days"] == DEFER_LIMIT_DAYS
    assert over["last_defer_day"] == "2026-08-12"

    # first_seen is stamped on the first defer and preserved after.
    assert s1["first_seen"] is not None
    seen_first = s1["first_seen"]
    s1c = _apply_defer(s1, "2026-08-20")
    assert s1c["first_seen"] == seen_first

    print("SIGNIN_NUDGE unit_test OK")


if __name__ == "__main__":
    unit_test()
