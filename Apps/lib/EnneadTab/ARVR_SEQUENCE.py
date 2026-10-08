# -*- coding: utf-8 -*-
"""Exploded-axon / construction-sequence manifest for EnneadTab-ARVR.

The web viewers can pull a model apart (EXPLODE) and reveal it step by step
(BUILD). The steps come from an optional sidecar manifest per room
(EnneadTab-ARVR lib/sequence.ts):

    {"version": 1, "source": "rhino-layers",
     "groups": [{"name": "Level 1", "match": ["Level 1", "Site::Level 1"]}, ...],
     "explode": {"distance": 1.0}}

Groups run bottom to top (explode order) and first to last (build order). A
group's `match` names are compared, case-insensitively and exactly, with the
model's mesh and ancestor node names. Which node names a given exporter writes
is not controlled here; with no usable match the viewer falls back to the
model's own top-level parts, so a manifest never makes things worse.

Pure Python 2.7 / 3.
"""

MAX_GROUPS = 100
MAX_NAME = 80
MAX_MATCHES = 200


def leaf_name(layer_path):
    """'Building::Level 2' -> 'Level 2' (Rhino separates parent and child layers with '::')."""
    return layer_path.split("::")[-1].strip()


def order_by_elevation(layers):
    """Sort [(layer_name, center_z)] bottom to top; ties keep the given order. Returns names."""
    indexed = [(z, i, name) for i, (name, z) in enumerate(layers)]
    indexed.sort(key=lambda t: (t[0], t[1]))
    return [name for _, _, name in indexed]


def build_manifest(ordered_layers, explode_distance=1.0, source="rhino-layers"):
    """Manifest dict from layer names already in the wanted order. Raises ValueError on bad input."""
    if not ordered_layers:
        raise ValueError("Pick at least one layer.")
    if len(ordered_layers) > MAX_GROUPS:
        raise ValueError("At most {} layers per sequence.".format(MAX_GROUPS))
    if not (0 < explode_distance <= 10):
        raise ValueError("Explode distance must be between 0 and 10.")
    groups = []
    for full in ordered_layers:
        leaf = leaf_name(full)
        name = leaf[:MAX_NAME]
        if not name:
            raise ValueError("Layer '{}' has an empty name.".format(full))
        match = [leaf]
        if full.strip() != leaf:
            match.append(full.strip())
        groups.append({"name": name, "match": [m[:MAX_NAME] for m in match][:MAX_MATCHES]})
    return {
        "version": 1,
        "source": source,
        "groups": groups,
        "explode": {"distance": float(explode_distance)},
    }


def build_revit_level_manifest(level_pairs, explode_distance=1.0):
    """Revit Levels -> manifest, mirroring build_manifest for Rhino layers.

    level_pairs: [(level_name, elevation)] for the levels the user picked, in any
    order. Revit has no layers; Levels are the build axis. They are ordered bottom
    to top by elevation (explode order) automatically, exactly like Rhino layers.
    A Revit level name carries no '::' path, so each group matches its own name.
    Raises ValueError on bad input.
    """
    ordered = order_by_elevation(level_pairs)
    return build_manifest(ordered, explode_distance=explode_distance, source="revit-levels")


def build_revit_phase_manifest(phase_names_in_order, explode_distance=1.0):
    """Revit Phases -> manifest. phase_names_in_order: names oldest build phase -> newest.

    Phases are the alternative build axis. Revit exposes no elevation for a phase, so
    the caller supplies the already-ordered names (oldest construction -> newest); this
    does not reorder them. Raises ValueError on bad input.
    """
    return build_manifest(list(phase_names_in_order), explode_distance=explode_distance, source="revit-phases")
