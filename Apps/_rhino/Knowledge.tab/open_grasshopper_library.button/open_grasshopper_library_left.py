__title__ = "OpenGrasshopperLibrary"
__doc__ = """Open the EnneadTab Grasshopper Library Explorer window.

Starts Grasshopper when it is not running, locates the EnneadTab Library
Explorer component (reusing an instance already placed on the active
canvas when one exists), and calls its ShowExplorer() entry point. If
the EnneadTab Grasshopper Yak plugin is not installed, install
instructions are shown instead of an error."""
__is_popular__ = True

import time

import clr  # pyright: ignore
import Rhino  # pyright: ignore
import rhinoscriptsyntax as rs  # pyright: ignore
import scriptcontext as sc  # pyright: ignore

from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION
from EnneadTab.RHINO import RHINO_UI

# Verified against EnneadTab-For-Grasshopper (main):
#   src/EnneadTab.Grasshopper.Plugin/Components/EnneadTabLibraryExplorerComponent.cs
# The plugin registers no Rhino commands, so the public ShowExplorer()
# entry point is reached through reflection instead.
PLUGIN_ASSEMBLY_NAME = "EnneadTab.Grasshopper.Plugin"
PLUGIN_TYPE_FULL_NAME = ("EnneadTab.Grasshopper.Plugin.Components."
                         "EnneadTabLibraryExplorerComponent")
YAK_PACKAGE_NAME = "enneadtab-grasshopper"


def _ensure_grasshopper_running():
    """Make sure Grasshopper is loaded; True when its assembly is referenceable."""
    try:
        clr.AddReference("Grasshopper")
        return True
    except Exception:
        pass

    rs.Command("_Grasshopper _Show")

    plugin_object = None
    for _ in range(20):
        plugin_object = Rhino.RhinoApp.GetPlugInObject("Grasshopper")
        if plugin_object is not None:
            break
        time.sleep(0.5)

    if plugin_object is None:
        return False

    try:
        clr.AddReference("Grasshopper")
        return True
    except Exception:
        return False


def _find_explorer_component_type():
    """Scan loaded .NET assemblies for the Library Explorer component type."""
    import System
    for asm in System.AppDomain.CurrentDomain.GetAssemblies():
        try:
            if asm.GetName().Name != PLUGIN_ASSEMBLY_NAME:
                continue
            comp_type = asm.GetType(PLUGIN_TYPE_FULL_NAME)
            if comp_type is not None:
                return comp_type
        except Exception:
            continue
    return None


def _find_canvas_instance(comp_type):
    """Prefer an explorer component already placed on the active GH canvas."""
    try:
        import Grasshopper
        canvas = Grasshopper.Instances.ActiveCanvas
        if canvas is None:
            return None
        doc = canvas.Document
        if doc is None:
            return None
        for obj in doc.Objects:
            try:
                if isinstance(obj, comp_type):
                    return obj
            except Exception:
                continue
    except Exception:
        pass
    return None


def _plugin_files_present():
    """Best-effort check for the Yak plugin files on disk."""
    import os
    app_data = os.environ.get("APPDATA", "")
    if not app_data:
        return False
    folders = [os.path.join(app_data, "Grasshopper", "Libraries"),
               os.path.join(app_data, "McNeel", "Rhinoceros", "packages")]
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for _root, _dirs, files in os.walk(folder):
            for file_name in files:
                lowered = file_name.lower()
                if lowered.startswith("enneadtab.grasshopper"):
                    return True
    return False


def _show_install_instructions():
    main_text = (
        "The EnneadTab Grasshopper plugin is not installed, so the Library "
        "Explorer cannot be opened.\n\n"
        "Install it with one of these options:\n"
        "1. Run the _PackageManager command in Rhino and search for "
        "\"{0}\".\n"
        "2. From a command prompt run: yak install {0}\n\n"
        "Then restart Rhino and run this button again."
    ).format(YAK_PACKAGE_NAME)
    NOTIFICATION.messenger(main_text=main_text,
                           title="Install EnneadTab Grasshopper Plugin")


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def open_grasshopper_library():
    if not _ensure_grasshopper_running():
        NOTIFICATION.messenger(
            main_text="Grasshopper could not be started. "
                      "Please open Grasshopper manually and try again.",
            title="Grasshopper Not Running")
        return

    comp_type = _find_explorer_component_type()
    if comp_type is None:
        _show_install_instructions()
        return

    # Prefer a canvas instance so the component's own bring-to-front
    # deduplication applies; otherwise instantiate transiently.
    instance = _find_canvas_instance(comp_type)
    if instance is None:
        import System
        instance = System.Activator.CreateInstance(comp_type)

    # ShowExplorer() is the public entry point on
    # EnneadTabLibraryExplorerComponent. It marshals the window creation
    # onto the Rhino UI thread itself through RhinoApp.InvokeOnUiThread,
    # and brings an already-open explorer window to the front instead
    # of opening a second one.
    instance.ShowExplorer()


if __name__ == "__main__":
    open_grasshopper_library()
