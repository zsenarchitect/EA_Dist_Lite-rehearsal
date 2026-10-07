__title__ = "LayerStateSnapshot"
__doc__ = """Snapshot and restore layer visibility states.

Key Features:
- One-click snapshot of every layer's visibility
- One-click restore after model-mutating operations
- Named snapshots kept for the Rhino session"""
__is_popular__ = False

import rhinoscriptsyntax as rs
import scriptcontext as sc

from EnneadTab import LOG, ERROR_HANDLE

STICKY_KEY = "ENNEADTAB_LAYER_SNAPSHOTS"


def get_snapshots():
    snapshots = sc.sticky.get(STICKY_KEY)
    if not isinstance(snapshots, dict):
        snapshots = {}
        sc.sticky[STICKY_KEY] = snapshots
    return snapshots


def take_snapshot(snapshots):
    name = rs.GetString("Snapshot name", "Snapshot {0}".format(len(snapshots) + 1))
    if not name:
        return
    state = {}
    for layer in sc.doc.Layers:
        state[layer.FullPath] = layer.IsVisible
    snapshots[name] = state
    rs.MessageBox(
        "Snapshot '{0}' captured ({1} layers).".format(name, len(state)),
        0,
        __title__)


def restore_snapshot(snapshots):
    names = sorted(snapshots.keys())
    name = rs.ListBox(names, "Pick a snapshot to restore.", __title__)
    if name is None:
        return
    state = snapshots[name]
    changed = 0
    missing = 0
    for path in state:
        index = sc.doc.Layers.FindByFullPath(path, -1)
        if index < 0:
            missing += 1
            continue
        layer = sc.doc.Layers[index]
        if layer.IsVisible != state[path]:
            layer.IsVisible = state[path]
            sc.doc.Layers.Modify(layer, index, True)
            changed += 1
    suffix = ", {0} missing".format(missing) if missing else ""
    rs.MessageBox(
        "Restored '{0}': {1} layer(s) changed{2}.".format(name, changed, suffix),
        0,
        __title__)


def delete_snapshot(snapshots):
    names = sorted(snapshots.keys())
    name = rs.ListBox(names, "Pick a snapshot to delete.", __title__)
    if name is None:
        return
    del snapshots[name]
    rs.MessageBox("Deleted snapshot '{0}'.".format(name), 0, __title__)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def snapshot_layer_state():
    snapshots = get_snapshots()
    actions = ["Take snapshot"]
    if snapshots:
        actions += ["Restore snapshot", "Delete snapshot"]
    action = rs.ListBox(
        actions,
        "Layer visibility snapshots ({0} stored).".format(len(snapshots)),
        __title__)
    if action is None:
        return
    if action == "Take snapshot":
        take_snapshot(snapshots)
    elif action == "Restore snapshot":
        restore_snapshot(snapshots)
    else:
        delete_snapshot(snapshots)


if __name__ == "__main__":
    snapshot_layer_state()
