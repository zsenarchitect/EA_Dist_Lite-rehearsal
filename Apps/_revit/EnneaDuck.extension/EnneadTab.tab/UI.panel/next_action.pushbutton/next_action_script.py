#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Next-Action suggestion surface (ADR 0006, host side).

Reads the on-machine usage-RL checkpoint produced by the
EnneadTab-FederatedArchitectTraining trainer and surfaces the ranked next
actions for the active session, risk-graded, as suggestion chips.

Contract (single source of truth lives in the trainer repo):
- checkpoint: '<checkpoint>/behavior_cloning_latest.npz' + '<...>.json'
  (numpy weights + transition + sidecar vocab; format 'enneadtab_bc_v0').
- risk: LOW (constructive: add wall, place door/window/room, subdivide...) may
  auto-run through per-action approval; HIGH (delete/remove/purge/undo/cancel/
  overwrite/...) requires an explicit confirm. Unknown -> HIGH (conservative).
- SuggestionContext.last_action: read from a local state file the host keeps
  (~/.enneadtab/os/next_action_state.json -> {"last_action": ...}); when absent
  the unigram prior alone drives the ranking.

The button runs in its own command context (off the host's UI thread); the load
is a tiny local npz read. Nothing here uploads anything: inference is local-only
and accept/dismiss stays local telemetry.

IRONPYTHON 2.7: no f-strings, no annotations, no pathlib -- keep it 2.7-clean
(pre-commit EnneadTab-OS python checkers enforce this).
"""
__title__ = "Next\nAction"
__tip__ = True

import json
import os

import numpy as np

CHECKPOINT_FORMAT = "enneadtab_bc_v0"
_DEFAULT_CHECKPOINT = os.path.join(os.path.expanduser("~"), ".enneadtab", "checkpoints", "behavior_cloning_latest.npz")
_DEFAULT_STATE = os.path.join(os.path.expanduser("~"), ".enneadtab", "os", "next_action_state.json")
_TOP_K = 5
_HIGH_RISK_KEYWORDS = (
    "delete", "remove", "purge", "undo", "cancel", "overwrite", "replace",
    "rename", "move", "reassign", "merge", "collapse", "reset", "clear",
    "wipe", "drop", "relocate",
)
_LOW_RISK_KEYWORDS = (
    "wall", "door", "window", "room", "subdivide", "split", "place", "create",
    "add", "insert", "grid", "dimension", "tag", "copy", "duplicate", "align",
    "offset", "join", "level", "floor", "ceiling", "furniture", "electrical",
)


def _risk_grade(action_id):
    a = str(action_id).lower().replace("_", " ").replace("-", " ")
    for key in _HIGH_RISK_KEYWORDS:
        if key in a:
            return "HIGH"
    for key in _LOW_RISK_KEYWORDS:
        if key in a:
            return "LOW"
    return "HIGH"


def load_checkpoint(path):
    """Decode a BC checkpoint (npz + sidecar) with numpy only."""
    if not os.path.isfile(path):
        raise IOError("checkpoint not found: " + str(path))
    data = np.load(path, allow_pickle=False)
    weights = np.asarray(data["weights"], dtype=np.float64)
    transition = np.asarray(data["transition"], dtype=np.float64)
    meta = {}
    sidecar = path[:-4] + ".json"
    if os.path.isfile(sidecar):
        with open(sidecar, "r") as fh:
            meta = json.load(fh)
    if meta.get("format") != CHECKPOINT_FORMAT:
        raise ValueError("unexpected checkpoint format: " + str(meta.get("format")))
    vocab = tuple(meta.get("action_vocab") or [])
    return {"weights": weights, "transition": transition, "vocab": vocab}


def read_last_action(state_path):
    if not os.path.isfile(state_path):
        return None
    try:
        with open(state_path, "r") as fh:
            data = json.load(fh)
    except (IOError, ValueError):
        return None
    last = data.get("last_action")
    return str(last) if last else None


def rank_next_actions(checkpoint, last_action, top_k=None):
    """Rank next actions (unigram prior + bigram transition blend), risk-graded."""
    if top_k is None:
        top_k = _TOP_K
    vocab = checkpoint["vocab"]
    if not vocab:
        return []
    unigram = checkpoint["weights"]
    transition = checkpoint["transition"]
    index = dict((a, i) for i, a in enumerate(vocab))

    scores = [0.0] * len(vocab)
    if last_action in index:
        row = transition[index[last_action]]
        row_sum = float(row.sum())
        if row_sum > 0:
            for j in range(len(vocab)):
                scores[j] = 0.8 * (row[j] / row_sum) + 0.2 * unigram[j]
        else:
            scores = [float(u) for u in unigram]
    else:
        scores = [float(u) for u in unigram]

    ranked = sorted(
        (
            {"action_id": vocab[i], "score": float(scores[i]), "risk": _risk_grade(vocab[i])}
            for i in range(len(vocab))
        ),
        key=lambda d: d["score"],
        reverse=True,
    )
    return ranked[: max(0, top_k)]


def _checkpoint_path():
    env = os.environ.get("ENNEADTAB_TRAINER_CHECKPOINT")
    return os.path.expanduser(env) if env else _DEFAULT_CHECKPOINT


def _state_path():
    return _DEFAULT_STATE


def _main():
    # Heavy imports stay inside the click path (PyRevit command context).
    from pyrevit import forms  # pyright: ignore

    try:
        checkpoint = load_checkpoint(_checkpoint_path())
    except IOError as exc:
        forms.alert(
            "No trained usage checkpoint yet.\n\nRun the trainer "
            "('train --algo behavior_cloning') first.\n\n{0}".format(exc),
            title="Next Action", exitscript=True)
        return 1
    last = read_last_action(_state_path())
    ranked = rank_next_actions(checkpoint, last)
    if not ranked:
        forms.alert("The checkpoint has no learned actions yet.", title="Next Action")
        return 0

    lines = ["Next actions (risk-graded):"]
    for i, item in enumerate(ranked, 1):
        marker = "[LOW]  " if item["risk"] == "LOW" else "[HIGH] "
        lines.append("{0}. {1} {2}  ({3:.3f})".format(i, marker, item["action_id"], item["score"]))
    lines.append("")
    lines.append("[LOW] may auto-run via per-action approval;")
    lines.append("[HIGH] requires an explicit confirm (ADR 0006).")
    forms.alert("\n".join(lines), title="Next Action", exitscript=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
