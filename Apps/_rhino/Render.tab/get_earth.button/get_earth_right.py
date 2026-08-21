# -*- coding: utf-8 -*-
__title__ = "GetEarthSettings"
__doc__ = """Diagnose and configure GetEarth.

Run this first when GetEarth misbehaves. It answers the four questions that
actually explain a failure:

- Can this machine reach the EarthModel service?
- Am I signed in to EnneadTab?
- What is cached locally, and how big has it got?
- Which contract version is this client speaking?

Also sets the default site size and purges the local cache.

This diagnostic SHIPS on purpose. DarkSide/ is stripped at publish, so the test
harness, the stub server and every developer driver are gone on a designer's
machine. Without this, a failing GetEarth button has nothing to run at all.
"""

import os

import rhinoscriptsyntax as rs  # pyright: ignore

from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION, DATA_FILE
from EnneadTab import AUTH
from EnneadTab import EARTH_MODEL
from EnneadTab.AI import _common


STICKY_SIZE = "GET_EARTH_SIZE_M"
DEFAULT_SIZE_M = 500.0
HEALTH_TIMEOUT_MS = 15000


def _health_url():
    return "{}/api/health".format(EARTH_MODEL.get_base_url().rstrip("/"))


def _describe_cache():
    """(file_count, total_bytes, path). Never raises; a missing dir is 0/0."""
    try:
        folder = EARTH_MODEL.cache_dir()
    except Exception as e:
        return (None, None, "unavailable ({})".format(e))
    if not folder or not os.path.isdir(folder):
        return (0, 0, folder or "unavailable")
    count = 0
    total = 0
    for name in os.listdir(folder):
        full = os.path.join(folder, name)
        if os.path.isfile(full):
            count += 1
            try:
                total += os.path.getsize(full)
            except OSError:
                pass
    return (count, total, folder)


def _mb(num_bytes):
    if not num_bytes:
        return "0 MB"
    return "{:.1f} MB".format(num_bytes / (1024.0 * 1024.0))


def _probe_service(token):
    """Ask /api/health. Returns a human-readable line.

    Deliberately reports THREE distinguishable outcomes, because they have
    different fixes and collapsing them is what makes a diagnostic useless:
    unreachable (network/VPN/outage), reachable-but-refused (auth), and
    reachable-and-answering (service is fine, look elsewhere).
    """
    try:
        data = _common.get_json(_health_url(), token=token,
                                timeout_ms=HEALTH_TIMEOUT_MS)
    except _common.AIRequestError as e:
        status = getattr(e, "status_code", None)
        if status in (401, 403):
            return ("REACHABLE, but it refused this machine "
                    "(HTTP {}). That is a sign-in problem, not an "
                    "outage.".format(status))
        return "UNREACHABLE ({}).".format(e)
    except Exception as e:
        return "UNREACHABLE ({}).".format(e)

    if not isinstance(data, dict):
        return "Answered, but not with the health record we expected."

    server_version = data.get("contract_version")
    formats = data.get("formats") or []
    sources = data.get("sources") or {}

    lines = ["UP. Contract v{}, formats {}.".format(
        server_version, ", ".join([str(f) for f in formats]) or "none")]

    # A source that is configured but not implemented is the normal state while
    # the backend is being built. Saying so stops it reading as a fault.
    for name in sorted(sources.keys()):
        entry = sources.get(name) or {}
        if not isinstance(entry, dict):
            continue
        lines.append("  source '{}': configured={} implemented={}".format(
            name, entry.get("configured"), entry.get("implemented")))

    if server_version and str(server_version) != str(EARTH_MODEL.CONTRACT_VERSION):
        lines.append(
            "  MISMATCH: this button speaks v{}, the service speaks v{}. "
            "Update EnneadTab.".format(
                EARTH_MODEL.CONTRACT_VERSION, server_version))

    return "\n".join(lines)


@ERROR_HANDLE.try_catch_error()
def run_diagnostic():
    token = AUTH.get_token()
    if token:
        auth_line = "SIGNED IN."
    else:
        auth_line = ("NOT SIGNED IN. Run any EnneadTab AI command once to "
                     "sign in, then retry.")

    service_line = _probe_service(token)
    count, total, folder = _describe_cache()
    if count is None:
        cache_line = "Cache: {}".format(folder)
    else:
        cache_line = "Cache: {} file(s), {}\n  {}".format(
            count, _mb(total), folder)

    report = (
        "GetEarth diagnostic\n"
        "-------------------\n"
        "Service : {}\n"
        "{}\n\n"
        "Auth    : {}\n\n"
        "{}\n\n"
        "Client contract: v{}\n"
        "Endpoint: {}"
    ).format(
        EARTH_MODEL.get_base_url(),
        service_line,
        auth_line,
        cache_line,
        EARTH_MODEL.CONTRACT_VERSION,
        EARTH_MODEL.model_endpoint(),
    )

    # Printed as well as shown: the messenger is transient, and a designer
    # pasting this into a chat is the whole point of a shipped diagnostic.
    print(report)
    NOTIFICATION.messenger(main_text=report)


@ERROR_HANDLE.try_catch_error()
def set_default_size():
    current = DATA_FILE.get_sticky(STICKY_SIZE, DEFAULT_SIZE_M)
    value = rs.RealBox(
        message="Default site size in METRES, used next time GetEarth runs.",
        default_number=float(current),
        title="GetEarth - default size",
        minimum=1.0)
    if not value:
        return
    DATA_FILE.set_sticky(STICKY_SIZE, float(value))
    NOTIFICATION.messenger(
        main_text="Default site size is now {:.0f} m.".format(float(value)))


@ERROR_HANDLE.try_catch_error()
def purge_cache():
    count, total, folder = _describe_cache()
    if not count:
        NOTIFICATION.messenger(main_text="Nothing cached. Nothing to purge.")
        return

    if not rs.MessageBox(
            "Delete {} cached site model(s), {}?\n\n{}\n\n"
            "Anything you delete will be downloaded again on next use, "
            "which costs another server-side build.".format(
                count, _mb(total), folder),
            4 | 32,
            "GetEarth - purge cache") == 6:
        return

    removed = 0
    failed = 0
    for name in os.listdir(folder):
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            continue
        try:
            os.remove(full)
            removed += 1
        except OSError as e:
            # Never silent to the operator, even when graceful to the designer.
            failed += 1
            print("GetEarth: could not delete {}: {}".format(full, e))

    if failed:
        NOTIFICATION.messenger(
            main_text=("Purged {} file(s); {} could not be deleted "
                       "(likely open elsewhere). See the command line."
                       ).format(removed, failed))
    else:
        NOTIFICATION.messenger(
            main_text="Purged {} cached site model(s).".format(removed))


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def get_earth_settings():
    options = [
        "Diagnostic - is the service up and am I signed in",
        "Default size - set the size GetEarth starts with",
        "Purge cache - delete downloaded site models",
    ]
    picked = rs.ListBox(options,
                        message="GetEarth",
                        title="GetEarth settings",
                        default=options[0])
    if not picked:
        return
    if picked == options[0]:
        run_diagnostic()
    elif picked == options[1]:
        set_default_size()
    elif picked == options[2]:
        purge_cache()


if __name__ == "__main__":
    get_earth_settings()
