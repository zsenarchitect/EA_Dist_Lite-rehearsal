# -*- coding: utf-8 -*-
"""Client for BimRunner's desktop-publish path -- push Revit sheets to an
existing model's pinup wall (app/model/[id]/pinup) without building any new
service. BimRunner already has the DB, the upload endpoint, and the wall UI;
this is a thin caller, same shape as EARTH_MODEL.py / AI_RENDER.py.

Architecture (2026-09-04, decided with the user after the original
"new EnneadTab-Web-Revit service" framing was replaced; base URL corrected
2026-09-14 after live verify):
  * BimRunner is reached at enneadtab.com/bim-data (Home soft-public proxy).
    Do NOT use ennead-bimdata.com as the default -- that host 308-redirects
    and HttpWebRequest drops Authorization across the hop (silent 401).
  * Auth: BimRunner's write endpoint accepts EITHER its own static API_KEY
    (the automated extractor's credential, not available to a desktop
    session) OR a Home-issued desktop token (AUTH.get_token()), which
    BimRunner independently verifies against a secret it shares with Home
    (HOME_DESKTOP_TOKEN_SECRET == Home's DESKTOP_TOKEN_SECRET). This client
    always sends the desktop token -- it never has and never should hold
    BimRunner's static key.
  * Model auto-detection: the current document's cloud ModelGUID/ProjectGUID
    (Document.GetWorksharingCentralModelPath()) is resolved against
    BimRunner's existing GET /api/data/models?modelGuid=...&latestOnly=true
    endpoint to find the CURRENT winning job_id -- never a cached one, so a
    publish never targets a job_id that has already lost that week's dedupe
    race. This read is unauthenticated (BimRunner's read endpoints carry no
    auth by house convention), so no token is needed for this half.
  * Sheet identity across republishes is the Revit Element.UniqueId, never
    sheet_number/name -- those can be renumbered. The upload endpoint
    upserts (soft-delete old + insert new) on (job_id, source_element_unique_id).

Transport is EnneadTab.AI._common, same as EARTH_MODEL.py / AI_RENDER.py:
.NET HttpWebRequest inside Revit because urllib2's SSL is broken there.

IronPython 2.7 (loads inside Revit): no f-strings, no type hints, no
pathlib. Fully-qualified sibling imports only -- a bare `import _common`
resolves in an editor and raises "No module named" at runtime under the
package path.
"""

import os

from EnneadTab.AI import _common


# --- Contract ---------------------------------------------------------------

# Overridable per machine so a dev can point at a local stub without a code
# change -- same escape hatch EARTH_MODEL_URL_ENV_VAR gives EARTH_MODEL.py.
WEB_REVIT_URL_ENV_VAR = "EA_BIMRUNNER_URL"
# Must be the Home-proxied origin (includes /bim-data). Legacy apex
# ennead-bimdata.com 308-redirects and strips Authorization on follow.
WEB_REVIT_URL_DEFAULT = "https://enneadtab.com/bim-data"

# Matches the upload route's own `export const maxDuration = 60` (Vercel).
DEFAULT_TIMEOUT_MS = 60000


class WebRevitError(Exception):
    """Raised for a protocol-level failure. The caller decides how to show
    this to the user -- this module stays Revit/UI-free, matching the other
    AI._common-based clients (EARTH_MODEL.py, AI_RENDER.py)."""

    def __init__(self, message, status_code=None):
        Exception.__init__(self, message)
        self.status_code = status_code


def get_base_url():
    override = os.environ.get(WEB_REVIT_URL_ENV_VAR)
    if override:
        return override.rstrip("/")
    return WEB_REVIT_URL_DEFAULT


# --- Model resolution --------------------------------------------------------

def resolve_job_id(model_guid, project_guid=None):
    """Resolve the CURRENT winning job_id for a cloud model.

    Returns None when BimRunner has never extracted this model -- that is a
    real, expected state (not an error): the caller should tell the user to
    run extraction first, per the "block, tell them to extract" decision.

    Deliberately re-resolved on every publish rather than cached anywhere:
    BimRunner's dedupeWeeklyModelSnapshot() can still retire a job_id later
    the same week, so "today's winner" is only safe to use at the instant it
    is asked for, never stored across a session or reused for a batch that
    spans more than a moment.

    Raises WebRevitError only for a genuine transport/protocol failure
    (BimRunner unreachable, malformed response) -- never for "no data yet",
    which is the None return above.
    """
    url = "{}/api/data/models?modelGuid={}&latestOnly=true&limit=1".format(
        get_base_url(), model_guid)
    if project_guid:
        url += "&projectGuid={}".format(project_guid)

    try:
        data = _common.get_json(url, token=None, timeout_ms=DEFAULT_TIMEOUT_MS)
    except _common.AIRequestError as e:
        raise WebRevitError(
            "Could not reach BimRunner to resolve this model: {}".format(e),
            status_code=getattr(e, "status_code", None))

    if not isinstance(data, dict):
        raise WebRevitError(
            "Unexpected response resolving model: {}".format(type(data).__name__))

    models = data.get("data")
    if not models:
        return None

    return models[0].get("job_id")


# --- Publish ------------------------------------------------------------

def publish_sheet(job_id, pdf_path, source_element_unique_id, category, token,
                  file_name=None):
    """Upload one sheet's PDF to BimRunner's pinup wall (file_type =
    'desktop_publish'). Republish (same job_id + source_element_unique_id)
    upserts server-side -- this function does not need to check for an
    existing entry first, BimRunner's upload route already does that.

    Raises WebRevitError on any failure -- including a 404 meaning the
    job_id vanished between resolve_job_id() and this call (the cascade-
    delete-hazard window this whole resolve-at-publish-time design narrows
    but the caller should still treat as a real, reportable per-sheet
    failure, not retry silently forever).

    The caller is responsible for catching this PER SHEET and continuing to
    the next one -- "resilient batch, not all-or-nothing" is a policy that
    belongs to the button script driving the loop, not to this function.
    """
    if not token:
        raise WebRevitError("No auth token available for publish.")

    if not os.path.exists(pdf_path):
        raise WebRevitError("PDF not found on disk: {}".format(pdf_path))

    f = open(pdf_path, "rb")
    try:
        file_bytes = f.read()
    finally:
        f.close()

    if not file_bytes:
        raise WebRevitError("Exported PDF is empty: {}".format(pdf_path))

    fields = {
        "job_id": job_id,
        "file_type": "desktop_publish",
        "source_element_unique_id": source_element_unique_id,
    }
    if category:
        fields["category"] = category

    files = [
        ("file", file_name or os.path.basename(pdf_path), file_bytes,
         "application/pdf"),
    ]

    url = "{}/api/data/files/upload".format(get_base_url())

    try:
        return _common.post_multipart(url, fields, files, token,
                                      timeout_ms=DEFAULT_TIMEOUT_MS)
    except _common.AIRequestError as e:
        raise WebRevitError(str(e), status_code=getattr(e, "status_code", None))


# --- Sheet classification (client-side heuristic, no server round trip) -----

# Discipline derived from the sheet-number PREFIX, per the "auto-derive
# silently" decision -- no UI review/correction step. This is a fallback
# heuristic (Revit sheet-numbering conventions vary by project template);
# it is not a substitute for a real Discipline parameter if one is later
# confirmed to exist consistently on the firm's sheet templates.
_PREFIX_TO_CATEGORY = {
    "A": "Architectural",
    "S": "Structural",
    "M": "MEP",
    "E": "MEP",
    "P": "MEP",
    "C": "Civil",
    "L": "Landscape",
    "I": "Interiors",
    "FP": "Fire Protection",
    "G": "General",
}


def classify_sheet_number(sheet_number):
    """Best-effort discipline classification from a sheet number's leading
    letters, e.g. "A-101" -> "Architectural", "S101" -> "Structural".
    Returns None when no known prefix matches -- an unclassified sheet is a
    normal, expected outcome, not an error.
    """
    if not sheet_number:
        return None
    letters = ""
    for ch in sheet_number.strip():
        if ch.isalpha():
            letters += ch.upper()
        else:
            break
    if not letters:
        return None
    # Longest-prefix-first so the two-letter FP entry matches before a
    # single-letter entry would (no single-letter entry collides with it
    # today, but this keeps the lookup order-safe if one is added later
    # without needing to touch this function again).
    for length in range(len(letters), 0, -1):
        candidate = letters[:length]
        if candidate in _PREFIX_TO_CATEGORY:
            return _PREFIX_TO_CATEGORY[candidate]
    return None


if __name__ == "__main__":
    pass
