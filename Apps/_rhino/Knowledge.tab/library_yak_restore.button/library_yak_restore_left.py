__title__ = "LibraryYakRestore"
__doc__ = """Install missing Grasshopper plugins for a library entry via Yak.

Key Features:
- Pick a catalog entry and read its required plugins ("Name|secret" format)
- Detects installed plugins from the Grasshopper Libraries folder and the
  Rhino Yak package folders
- Offers to run `yak install` for each missing package and reports results
- Copies the install commands to the clipboard on request

Ports EnneadTab-For-Grasshopper#74 (missing-plugin package restore via Yak)."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os, sys, subprocess
_rhino_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_library_dir = os.path.join(_rhino_folder, "Library")
if _library_dir not in sys.path: sys.path.append(_library_dir)
try:
    import catalog
except ImportError:
    catalog = None
from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE
_MISSING_LIB_TEXT = ("The shared library module (Apps/_rhino/Library/catalog.py) is not installed yet. "
                     "This button needs the shared-catalog-lib PR #283 merged first.")


def _parse_dependency(raw):
    # Mirrors PluginDependency.Parse (GH PR #74): "DisplayName|secret";
    # secret (yak package id/GUID) is optional; malformed input is kept
    # as missing under its raw text rather than dropped.
    text = (raw or "").strip()
    if not text:
        return None
    if "|" in text:
        name, secret = text.split("|", 1)
        name, secret = name.strip(), secret.strip()
        if not name:
            return (text, None)
        return (name, secret or None)
    return (text, None)


def _install_hint(name, secret):
    # Mirrors MissingPackage.InstallHint: prefer the secret, display names
    # are ambiguous on the package server.
    if secret:
        return "yak install {0}".format(secret)
    return 'yak install "{0}"'.format(name)


def _grasshopper_libraries_dirs():
    appdata = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return [os.path.join(appdata, "Grasshopper", "Libraries")]


def _yak_package_dirs():
    appdata = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return [os.path.join(appdata, "McNeel", "Rhinoceros", "packages", v)
            for v in ("8.0", "7.0")]


def _installed_names():
    # Best-effort installed-plugin detection from the Rhino side: .gha file
    # stems in the Grasshopper Libraries folder plus Yak package folder names.
    found = set()
    for folder in _grasshopper_libraries_dirs():
        try:
            names = os.listdir(folder)
        except (OSError, IOError):
            continue
        for name in names:
            if name.lower().endswith(".gha"):
                found.add(os.path.splitext(name)[0].lower())
            elif name.lower().endswith(".ghpy"):
                found.add(os.path.splitext(name)[0].lower())
    for folder in _yak_package_dirs():
        try:
            names = os.listdir(folder)
        except (OSError, IOError):
            continue
        for name in names:
            if os.path.isdir(os.path.join(folder, name)):
                found.add(name.lower())
                # Yak folders are often "<pkg>-<version>"; also index the bare name.
                base = name.rsplit("-", 1)[0]
                if base:
                    found.add(base.lower())
    return found


def _pick_entry(entries):
    get_string = getattr(rs, "GetString", None)
    if get_string is None:
        return None
    query = get_string("Search catalog entries (blank = list all)")
    if query is None:
        return None
    matches = catalog.search_entries(entries, query=query) if query.strip() else list(entries)
    if not matches:
        rs.MessageBox("No catalog entries matched.", buttons=0, title=__title__)
        return None
    labels = ["{0} -- {1}".format(e.get("title") or "(untitled)",
                                  os.path.basename(e.get("path") or "")) for e in matches]
    picked = rs.ListBox(labels, "Pick a catalog entry to restore plugins for", __title__)
    if picked is None:
        return None
    return matches[labels.index(picked)]


def _try_install_yak(target):
    # Best-effort `yak install`, mirrors PackageRestoreService.TryInstallViaYak
    # (hand-verified only -- needs live Rhino/Windows).
    try:
        proc = subprocess.Popen(
            ["yak", "install", target],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
        message = ((out or "") + (err or "")).strip()
        if not message:
            message = "yak exited with code {0}.".format(proc.returncode)
        return proc.returncode == 0, message
    except Exception as ex:
        return False, str(ex)


def _copy_to_clipboard(text):
    try:
        import clr
        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import Clipboard
        Clipboard.SetText(text)
        return True
    except Exception:
        return False


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_yak_restore():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT); return

    index_path, _ = catalog.find_catalog_paths()
    if not index_path:
        rs.MessageBox("No catalog index found yet.\n"
                      "Refresh the Grasshopper library first, then try again.",
                      buttons=0, title=__title__)
        return
    entries = catalog.iter_entries(catalog.load_index(index_path))
    if not entries:
        rs.MessageBox("The catalog index has no entries.", buttons=0, title=__title__)
        return

    entry = _pick_entry(entries)
    if entry is None:
        return

    requirements = []
    for raw in entry.get("pluginsRequired") or []:
        dep = _parse_dependency(raw)
        if dep:
            requirements.append(dep)
    if not requirements:
        rs.MessageBox('Entry "{0}" declares no required plugins.'.format(
            entry.get("title") or "(untitled)"), buttons=0, title=__title__)
        return

    installed = _installed_names()
    missing, already = [], []
    for name, secret in requirements:
        if name.lower() in installed:
            already.append(name)
        else:
            missing.append((name, secret))

    lines = ['Plugin restore plan: "{0}"'.format(entry.get("title") or "(untitled)"), ""]
    if already:
        lines.append("Already installed ({0}): {1}".format(len(already), ", ".join(already)))
    if not missing:
        rs.MessageBox("\n".join(lines) + "\n\nNothing to install -- all required plugins are present.",
                      buttons=0, title=__title__)
        return
    lines.append("")
    lines.append("Missing ({0}):".format(len(missing)))
    commands = []
    for name, secret in missing:
        cmd = _install_hint(name, secret)
        commands.append(cmd)
        lines.append("  - {0}  ->  {1}".format(name, cmd))

    choice = rs.MessageBox("\n".join(lines) + "\n\nInstall all missing packages now via yak?",
                           buttons=4, title=__title__)
    if choice == 6:  # Yes
        results = []
        for (name, secret), cmd in zip(missing, commands):
            target = secret if secret else name
            ok, message = _try_install_yak(target)
            results.append("{0}: {1} -- {2}".format(
                "OK" if ok else "FAILED", name, message.splitlines()[0] if message else ""))
        rs.MessageBox("Yak install results:\n\n" + "\n".join(results),
                      buttons=0, title=__title__)
        return

    if _copy_to_clipboard("\n".join(commands)):
        rs.MessageBox("Install commands copied to the clipboard:\n\n" + "\n".join(commands),
                      buttons=0, title=__title__)
    else:
        rs.MessageBox("Run these commands yourself:\n\n" + "\n".join(commands),
                      buttons=0, title=__title__)


if __name__ == "__main__":
    library_yak_restore()
