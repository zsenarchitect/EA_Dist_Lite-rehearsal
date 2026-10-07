__title__ = "ValidateLayerPatterns"
__doc__ = """Validate Elefront-style layer patterns (with :: full paths and * wildcards) against the document's layer table.

Reports per-pattern match counts and, for patterns that match nothing, suggests the closest real layer names — catching renamed layers before a definition fails silently.
"""
__is_popular__ = False

import difflib
import re

import rhinoscriptsyntax as rs

from EnneadTab import ERROR_HANDLE, LOG


def _pattern_to_regex(pattern):
    return re.compile("^" + re.escape(pattern).replace(r"\*", ".*") + "$",
                      re.IGNORECASE)


def _matches(pattern, layer_path):
    pattern = pattern.strip()
    if not pattern:
        return False
    if "*" in pattern:
        return bool(_pattern_to_regex(pattern).match(layer_path))
    if "::" in pattern:
        return pattern.lower() == layer_path.lower()
    # Bare name: the layer itself, or any nested layer ending in ::name.
    return (pattern.lower() == layer_path.lower()
            or layer_path.lower().endswith("::" + pattern.lower()))


def _collect_patterns():
    patterns = []
    while True:
        entry = rs.GetString(
            "Layer pattern (* wildcards, :: paths). Press Enter with empty input when done"
            + (" [{0} so far]".format(len(patterns)) if patterns else ""))
        if entry is None:  # user cancelled
            return None
        entry = entry.strip()
        if not entry:
            break
        if entry not in patterns:
            patterns.append(entry)
    return patterns


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def validate_layer_patterns():
    layers = rs.LayerNames() or []
    if not layers:
        rs.MessageBox("The document contains no layers.", 0, __title__)
        return

    patterns = _collect_patterns()
    if patterns is None:
        print("Validation cancelled.")
        return
    if not patterns:
        rs.MessageBox("No patterns entered.", 0, __title__)
        return

    print("=== Layer pattern validation: {0} pattern(s), {1} layer(s) ===".format(
        len(patterns), len(layers)))
    unmatched = 0
    for pattern in patterns:
        matched = [layer for layer in layers if _matches(pattern, layer)]
        if matched:
            preview = ", ".join(sorted(matched)[:3])
            if len(matched) > 3:
                preview += " (+{0} more)".format(len(matched) - 3)
            print("  '{0}': matches {1} layer(s): {2}".format(pattern, len(matched), preview))
        else:
            unmatched += 1
            probe = pattern.replace("*", "")
            suggestions = difflib.get_close_matches(probe, layers, n=3, cutoff=0.6)
            if suggestions:
                print("  '{0}': NO MATCH - did you mean: {1}?".format(
                    pattern, ", ".join("'{0}'".format(s) for s in suggestions)))
            else:
                print("  '{0}': NO MATCH in the document's layer table.".format(pattern))

    rs.MessageBox(
        "{0} of {1} pattern(s) matched at least one layer.\nSee the command history for details.".format(
            len(patterns) - unmatched, len(patterns)),
        0,
        __title__)


if __name__ == "__main__":
    validate_layer_patterns()
