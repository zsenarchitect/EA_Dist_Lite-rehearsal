__title__ = "Model Snapshot"
__doc__ = """Snapshot model geometry into local versioned stores with branch/commit vocabulary.

Snapshot mode: capture the objects on chosen layers into a versioned store - a .3dm export plus a JSON manifest recording a fingerprint per object - on a named branch, with a commit message.
Diff mode: pick any past commit and compare it against the current document; added, removed, and modified objects are listed.

Manifests and exports live in <chosen folder>/model_snapshots/<branch>/.

Rhino-side companion to the GH library's model snapshot workflow (feature 18).
"""
__is_popular__ = False

import hashlib
import json
import math
import os
import time

import rhinoscriptsyntax as rs
import scriptcontext as sc

from EnneadTab import ERROR_HANDLE, LOG
from EnneadTab.RHINO import ENVIRONMENT, RHINO_FORMS

FOLDER_STICKY = "model_snapshot_folder"
BRANCH_STICKY = "model_snapshot_branch"
SNAPSHOT_MODE = "Snapshot current state (new commit)"
DIFF_MODE = "Diff against a past commit"


def _snapshots_root():
    folder = sc.sticky.get(FOLDER_STICKY)
    if not folder or not os.path.isdir(folder):
        folder = ENVIRONMENT.DOCUMENT_FOLDER
        if not folder or not os.path.isdir(folder):
            folder = rs.BrowseForFolder(title="Pick the folder that will hold model snapshots")
            if not folder:
                return None
    sc.sticky[FOLDER_STICKY] = folder
    root = os.path.join(folder, "model_snapshots")
    if not os.path.exists(root):
        os.makedirs(root)
    return root


def _layer_full_path(layer):
    try:
        return rs.LayerName(layer, fullpath=True) or layer
    except Exception:
        return layer


def _fingerprint(obj_id):
    try:
        obj_type = rs.ObjectType(obj_id)
        bbox = rs.BoundingBox(obj_id)
        if not bbox:
            return "{}|no-bbox".format(obj_type)
        p0 = bbox[0]
        p6 = bbox[6]
        diag = math.sqrt(
            (p0.X - p6.X) ** 2 + (p0.Y - p6.Y) ** 2 + (p0.Z - p6.Z) ** 2)
        return "{}|{:.3f}".format(obj_type, diag)
    except Exception:
        return "unreadable"


def _collect_objects(layers):
    records = []
    for layer in layers:
        try:
            ids = rs.ObjectsByLayer(layer, select=False) or []
        except Exception:
            ids = []
        for obj_id in ids:
            records.append({
                "id": str(obj_id),
                "layer": _layer_full_path(layer),
                "hash": _fingerprint(obj_id),
            })
    return records


def _commit_id(manifest):
    payload = json.dumps(manifest, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _snapshot_mode(root):
    branch = rs.StringBox(
        "Branch name:",
        sc.sticky.get(BRANCH_STICKY, "main"),
        title=__title__)
    if not branch:
        return
    branch = branch.strip()
    message = rs.StringBox("Commit message:", title=__title__)
    if message is None:
        return

    selected = rs.SelectedObjects() or []
    if selected:
        layers = sorted(set(rs.ObjectLayer(o) for o in selected if rs.ObjectLayer(o)))
    else:
        all_layers = rs.LayerNames() or []
        layers = RHINO_FORMS.select_from_list(
            all_layers,
            title=__title__,
            message="Pick the layers to snapshot:",
            default=all_layers,
            multi_select=True)
        if not layers:
            return

    records = _collect_objects(layers)
    manifest = {
        "branch": branch,
        "message": message,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "layers": layers,
        "objects": records,
    }
    commit = _commit_id(manifest)
    manifest["commit"] = commit

    branch_dir = os.path.join(root, branch)
    if not os.path.exists(branch_dir):
        os.makedirs(branch_dir)

    export_path = None
    if records:
        export_path = os.path.join(branch_dir, "snap_{}.3dm".format(commit))
        rs.SelectObjects([r["id"] for r in records if rs.IsObject(r["id"])])
        try:
            rs.Command('-_Export "{}" _Enter'.format(export_path), False)
        finally:
            rs.UnselectAllObjects()

    manifest_path = os.path.join(branch_dir, "snap_{}.json".format(commit))
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    sc.sticky[BRANCH_STICKY] = branch
    rs.MessageBox(
        "Commit {} on branch '{}'.\n{} object(s) on {} layer(s).\n{}".format(
            commit, branch, len(records), len(layers),
            "Export: {}".format(export_path) if export_path else "No objects exported."),
        buttons=0,
        title=__title__)


def _list_manifests(root):
    found = []
    for branch in sorted(os.listdir(root)):
        branch_dir = os.path.join(root, branch)
        if not os.path.isdir(branch_dir):
            continue
        for name in sorted(os.listdir(branch_dir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(branch_dir, name)
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                found.append((branch, data.get("commit", name), data, path))
            except Exception:
                continue
    return found


def _diff_mode(root):
    manifests = _list_manifests(root)
    if not manifests:
        rs.MessageBox("No snapshots found yet.", buttons=0, title=__title__)
        return

    options = [
        "{} | {} | {} | {}".format(branch, commit, data.get("timestamp", "?"), data.get("message", ""))
        for branch, commit, data, _ in manifests
    ]
    choice = RHINO_FORMS.select_from_list(
        options,
        title=__title__,
        message="Pick the commit to diff against the current document:")
    if choice is None:
        return
    _, commit, manifest, _ = manifests[options.index(choice)]

    old = {o["id"]: o for o in manifest.get("objects", [])}
    current = {r["id"]: r for r in _collect_objects(manifest.get("layers", []))}

    added = sorted(set(current) - set(old))
    removed = sorted(set(old) - set(current))
    modified = sorted(i for i in set(current) & set(old) if current[i]["hash"] != old[i]["hash"])

    lines = ["Diff vs commit {} ({}):".format(commit, manifest.get("message", "")),
             "  added: {}".format(len(added)),
             "  removed: {}".format(len(removed)),
             "  modified: {}".format(len(modified))]
    for label, ids, lookup in (("ADDED", added, current), ("REMOVED", removed, old), ("MODIFIED", modified, current)):
        for i in ids[:25]:
            lines.append("  [{}] {} ({})".format(label, i, lookup[i].get("layer", "?")))
        if len(ids) > 25:
            lines.append("  ... and {} more {}".format(len(ids) - 25, label.lower()))
    report = "\n".join(lines)
    print(report)
    rs.MessageBox(report, buttons=0, title=__title__)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def model_snapshot():
    root = _snapshots_root()
    if not root:
        return
    mode = RHINO_FORMS.select_from_list(
        [SNAPSHOT_MODE, DIFF_MODE],
        title=__title__,
        message="What do you want to do?")
    if mode == SNAPSHOT_MODE:
        _snapshot_mode(root)
    elif mode == DIFF_MODE:
        _diff_mode(root)


if __name__ == "__main__":
    model_snapshot()
