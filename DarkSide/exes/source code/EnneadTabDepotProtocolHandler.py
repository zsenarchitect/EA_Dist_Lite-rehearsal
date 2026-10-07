"""Handles enneadtab-depot://install?id=<assetId> activations.

Registered as a custom Windows URI protocol (see
_protocol_handler_registration.py) so EnneadTab-Library's web "1-Click Drag &
Download" button (components/AssetDetailModal.tsx) can hand off from an
ordinary browser to the user's desktop. There is no guarantee any EnneadTab
host app (Revit, Rhino) is even running when this fires -- clicking a web
link is not the same context as clicking a ribbon button -- so this
deliberately does NOT try to inject into a live session. It downloads the
asset and hands off to Windows' own file-type association instead (Revit
already opens .rfa on double-click, Rhino already opens .3dm) -- the same
"let the OS do it" principle used everywhere else a file needs opening.

senzhang-todo #5513. See EnneadTab-Library's CLAUDE.md ("Current state") for
why this exists: the button has been calling this URI since before anything
registered it, and has been silently failing (a false "Launched into App!"
shown regardless of outcome) the whole time.

Windows-only by construction (_Exe_Util reads USERPROFILE at import time,
os.startfile only exists on Windows) -- built into a standalone .exe by this
repo's service-factory pipeline (see the build-exe skill), same convention
as every other flat .py file in this folder (e.g. EnscapeRenamer.py). The
pure functions below (parse_install_uri, resolve_download_url,
local_download_path) have no such dependency and are unit-tested directly.
"""

import os
import sys

try:
    from urllib.parse import parse_qs, quote, unquote, urlparse  # Py3
except ImportError:  # pragma: no cover - this tool only ever runs under CPython 3
    from urllib import quote, unquote  # type: ignore
    from urlparse import parse_qs, urlparse  # type: ignore

LIBRARY_BASE_URL_DEFAULT = "https://enneadtab.com/library"

# Source of truth: EnneadTab-Library lib/asset-upload-limits.ts
# ALLOWED_ASSET_EXTENSIONS. This process hands the downloaded file to
# os.startfile with no confirmation, so it must only ever launch a type
# Library can publish -- never .exe/.bat/.lnk/.ps1 etc., whatever the server
# (or a crafted link pointing at a wrong asset) returns.
ALLOWED_EXTENSIONS = (".rfa", ".rte", ".3dm", ".mat", ".matpkg")


def library_base_url():
    """Overridable via EA_LIBRARY_URL, mirroring EnneadTab-OS's other Library
    clients (LIBRARY_CATALOG.py, senzhang-todo #5449)."""
    return os.environ.get("EA_LIBRARY_URL", LIBRARY_BASE_URL_DEFAULT).rstrip("/")


def parse_install_uri(uri):
    """Parse 'enneadtab-depot://install?id=<assetId>'. Returns {'id': str} or
    None if the URI is not a recognizable install request. The 'version'
    query param some callers may still send is intentionally ignored: this
    always fetches the asset's CURRENT version -- there is no supported way
    to request an older one through this protocol."""
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme != "enneadtab-depot":
        return None
    # netloc holds 'install' for 'enneadtab-depot://install?...'; some shells
    # normalize away the '//' and put it in path instead -- accept both.
    action = parsed.netloc or parsed.path.lstrip("/")
    if action != "install":
        return None
    params = parse_qs(parsed.query)
    asset_id = params.get("id", [None])[0]
    if not asset_id:
        return None
    return {"id": unquote(asset_id)}


def resolve_asset_url(asset_id):
    # The id comes from a link any web page can craft; quote it so it stays one
    # path segment (no '/', '?', '#', '..' steering the request elsewhere).
    return "{0}/api/v1/assets/{1}".format(library_base_url(), quote(asset_id, safe=""))


def _url_path_extension(url_or_path):
    """Lower-cased extension of the URL's PATH only -- a '?sig=Foo.rfa' query
    must neither grant nor hide an extension."""
    return os.path.splitext(urlparse(url_or_path or "").path)[1].lower()


def is_allowed_download(url_or_path):
    """True only if the file's real (last) extension is one Library publishes.
    Exact match: 'evil.exe.rfa ' (trailing space) and 'evil.rfa:x.exe' fail."""
    return _url_path_extension(url_or_path) in ALLOWED_EXTENSIONS


def resolve_download_url(asset_json):
    """asset_json is the parsed JSON body of GET /api/v1/assets/{id} -- the
    full DigitalAsset object itself, not a list wrapper. Returns the absolute
    URL to download, or None if the asset has no published file yet.

    downloadUrl is a path relative to Library's OWN host, not an
    EnneadTab-Depot asset key -- verified against Library's actual route
    source 2026-09-05 (senzhang-todo #5447/#5449); resolve it exactly the way
    LIBRARY_CATALOG.py's resolve_media_url does, not as a Depot key."""
    version_history = asset_json.get("versionHistory") or []
    if not version_history:
        return None
    download_url = version_history[0].get("downloadUrl")
    if not download_url:
        return None
    if download_url.startswith("http://") or download_url.startswith("https://"):
        return download_url
    if not download_url.startswith("/"):
        download_url = "/" + download_url
    return library_base_url() + download_url


def safe_file_stem(name):
    """Enneadtab-Library asset names are free text -- keep the saved file
    filesystem-safe without inventing a naming scheme Library does not
    publish."""
    cleaned = "".join(c if c not in '\\/:*?"<>|' else "_" for c in (name or "")).strip()
    return cleaned or "library_download"


def local_download_path(dump_folder, asset_json, download_url):
    """Where to save the downloaded file before handing it to the OS. Keeps
    the extension from download_url so Windows' file-type association
    actually recognizes what it is (a .rfa stays a .rfa)."""
    name = asset_json.get("name") or asset_json.get("id")
    ext = _url_path_extension(download_url)
    folder = os.path.join(dump_folder, "LibraryProtocolDownloads")
    return os.path.join(folder, safe_file_stem(name) + ext)


def _fail(message):
    """Best-effort user-visible failure -- this process has no console (it
    was launched by the OS via protocol activation), so silence here means
    the user sees nothing at all beyond the web button's own (already
    misleading) success message. A native message box is the one UI surface
    guaranteed to exist with no other setup."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "EnneadTab-Library", 0x10)  # MB_ICONERROR
    except Exception:
        pass


def main(argv):
    request = parse_install_uri(argv[1] if len(argv) > 1 else None)
    if not request:
        _fail("This link is not a recognized EnneadTab-Library install request.")
        return 1

    # Deferred imports: _Exe_Util has Windows-only side effects at import time
    # (reads USERPROFILE, creates folders on disk) and requests is a real
    # network dependency -- neither should run just to import/unit-test the
    # pure functions above.
    import _Exe_Util
    import requests

    try:
        response = requests.get(resolve_asset_url(request["id"]), timeout=15)
        if response.status_code == 404:
            _fail("This EnneadTab-Library asset could not be found. It may have been removed.")
            return 1
        response.raise_for_status()
        asset_json = response.json()

        download_url = resolve_download_url(asset_json)
        if not download_url:
            _fail("'{0}' has no downloadable file published yet.".format(asset_json.get("name", request["id"])))
            return 1

        if not is_allowed_download(download_url):
            _fail("'{0}' is not a file type EnneadTab-Library installs, so it was not opened.".format(
                asset_json.get("name", request["id"])))
            return 1

        dest_path = local_download_path(_Exe_Util.DUMP_FOLDER, asset_json, download_url)
        dest_folder = os.path.dirname(dest_path)
        if not os.path.exists(dest_folder):
            os.makedirs(dest_folder)

        file_response = requests.get(download_url, timeout=60)
        file_response.raise_for_status()
        tmp_path = dest_path + ".part"
        with open(tmp_path, "wb") as f:
            f.write(file_response.content)
        if os.path.exists(dest_path):
            os.remove(dest_path)  # Windows rename refuses to overwrite
        os.rename(tmp_path, dest_path)

        # Re-check the path actually about to be launched, not just the URL we
        # decided on earlier -- the last line of defense before os.startfile.
        if not is_allowed_download(dest_path):
            os.remove(dest_path)
            _fail("Refused to open an unexpected file type.")
            return 1

        # Hand off to Windows' own file-type association -- Revit already
        # opens .rfa on double-click, Rhino already opens .3dm. This process
        # never touches a live Revit/Rhino session directly.
        os.startfile(dest_path)
        return 0
    except Exception as e:
        _fail("Could not download this EnneadTab-Library asset.\n\n{0}".format(e))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
