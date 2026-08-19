"""
HTML tree visualizer for KeynoteExporter.

Builds a hierarchy as:
Division (category) -> Section (group) -> Entry rows (KEYNOTE #)

Outputs an interactive collapsible HTML file and opens in the default browser.
"""

from typing import Dict, List, Any, Tuple
import os
import html
import webbrowser


def build_hierarchy(keynote_items: List[Any]) -> Dict[str, Dict[str, List[Tuple[str, str]]]]:
    """
    Build hierarchy mapping from a list of KeynoteData-like objects.

    Expected string fields on each item:
    - "DIVISION #", "DIVISION NAME"
    - "SECTION #", "SECTION NAME"
    - "KEYNOTE #", "KEYNOTE DESCRIPTION"

    Returns a nested dict: { division_label: { section_label: [(keynote_no, desc), ...] } }
    """
    tree: Dict[str, Dict[str, List[Tuple[str, str]]]] = {}

    for item in keynote_items:
        # Accessors are provided by KeynoteData
        div_no = item.get_string_field("DIVISION #").strip()
        div_name = item.get_string_field("DIVISION NAME").strip()
        sec_no = item.get_string_field("SECTION #").strip()
        sec_name = item.get_string_field("SECTION NAME").strip()
        key_no = item.get_string_field("KEYNOTE #").strip()
        key_desc = item.get_string_field("KEYNOTE DESCRIPTION").strip()

        if not div_no and not div_name:
            # Skip rows with no division info at all
            continue

        division_label = f"{div_no} - {div_name}".strip(" -")
        section_label = f"{sec_no} - {sec_name}".strip(" -") if (sec_no or sec_name) else "(Unsectioned)"

        if division_label not in tree:
            tree[division_label] = {}
        if section_label not in tree[division_label]:
            tree[division_label][section_label] = []

        if key_no or key_desc:
            tree[division_label][section_label].append((key_no, key_desc))

    return tree


def _render_tree_to_html(tree: Dict[str, Dict[str, List[Tuple[str, str]]]], keynote_items: List[Any]) -> str:
    """Render the tree dictionary into a collapsible HTML string with dark theme and rich node details."""
    def esc(text: str) -> str:
        return html.escape(text, quote=True)

    # Notes suffix char from config (for Copy button and tooltip)
    try:
        from .keynote_config import KeynoteConfig
        notes_suffix = KeynoteConfig().get_notes_format_suffix()
    except Exception:
        notes_suffix = "\u200a"
    # Handle both single-character markers (whitespace) and multi-character prefixes (e.g. "NOTE:")
    if isinstance(notes_suffix, str) and len(notes_suffix) == 1:
        cp = ord(notes_suffix)
    elif isinstance(notes_suffix, str) and len(notes_suffix) > 1:
        # Use the first codepoint as a representative for the copy button; still avoids crashes.
        cp = ord(notes_suffix[0])
    else:
        cp = ord("\u200b")
    notes_codepoint_hex = format(cp, "04X")

    # Build lookup for full keynote data
    keynote_lookup = {}
    for item in keynote_items:
        key_no = item.get_string_field("KEYNOTE #").strip()
        if key_no:
            keynote_lookup[key_no] = item
    
    # Detect problematic duplicates (not normal hierarchy duplicates)
    keynote_counts = {}
    section_counts = {}
    duplicate_keynotes = []
    duplicate_sections = []
    
    for item in keynote_items:
        # Check keynote codes (always problematic if duplicate)
        key_no = item.get_string_field("KEYNOTE #").strip()
        if key_no:
            if key_no in keynote_counts:
                keynote_counts[key_no].append(item)
                if key_no not in duplicate_keynotes:
                    duplicate_keynotes.append(key_no)
            else:
                keynote_counts[key_no] = [item]
        
        # Check section codes (only problematic if different names)
        sec_no = item.get_string_field("SECTION #").strip()
        sec_name = item.get_string_field("SECTION NAME").strip()
        if sec_no:
            if sec_no in section_counts:
                section_counts[sec_no].append((item, sec_name))
                # Check if this section has different names
                existing_names = [name for _, name in section_counts[sec_no]]
                if len(set(existing_names)) > 1 and sec_no not in duplicate_sections:
                    duplicate_sections.append(sec_no)
            else:
                section_counts[sec_no] = [(item, sec_name)]
    
    # Note: Division duplicates are NORMAL and ACCEPTABLE - multiple entries can belong to same division

    html_parts: List[str] = []
    html_parts.append("""
<!DOCTYPE html>
<html>
<head>
<meta charset=\"utf-8\" />
        <title>EnneadTab Keynote Viewer</title>
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<style>
:root { --fg:#1a202c; --muted:#718096; --brand:#4a5568; --pill:#f7fafc; --bg:#ffffff; --line:#e2e8f0; --success:#38a169; --warning:#d69e2e; --danger:#e53e3e; --category:#3182ce; --group:#805ad5; }
body { font-family: Segoe UI, Arial, sans-serif; margin: 0; color: var(--fg); background: var(--bg); }
.header { background: linear-gradient(135deg, var(--category)10, var(--group)10); border-bottom: 2px solid var(--line); padding: 20px; margin-bottom: 0; }
.header h1 { margin: 0 0 8px 0; color: var(--category); font-size: 28px; font-weight: 700; }
.header p { margin: 0; color: var(--muted); font-size: 14px; }
.toolbar { display:flex; gap:8px; align-items:center; margin: 16px 20px; position: sticky; top: 0; z-index: 100; background: var(--bg); padding: 12px 16px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); transition: all 0.3s ease; }
.toolbar.sticky { box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-bottom: 1px solid var(--line); }
.toolbar input[type="search"] { flex:1; padding:8px 10px; border:1px solid var(--line); border-radius:8px; background: var(--pill); color: var(--fg); }
.btn { padding:6px 10px; border:1px solid var(--line); border-radius:8px; background: var(--pill); cursor:pointer; color: var(--fg); }
.btn:hover { background: var(--line); }
details { margin: 6px 0; border-left: 2px solid var(--pill); padding-left: 8px; }
summary { list-style: none; cursor: pointer; position: relative; }
summary::-webkit-details-marker { display:none; }
summary::before { content: '▶'; color: var(--brand); margin-right: 6px; transition: all 0.2s; font-size: 12px; }
details[open] > summary::before { content: '▼'; transform: none; }
.title { display:inline-flex; align-items:center; gap:8px; }
.badge { font-size:12px; background: var(--line); border:1px solid var(--line); padding:2px 6px; border-radius:999px; color: var(--fg); }
.key { color: var(--brand); font-weight:600; }
.desc { color: var(--muted); }
/* Category level (Division) styling */
.category-level { background: linear-gradient(135deg, var(--category)15, var(--category)08); border: 1px solid var(--category)40; border-radius: 8px; padding: 12px; margin: 6px 0; }
.category-level summary { font-weight: 600; color: var(--category); }
/* Group level (Section) styling */
.group-level { background: linear-gradient(135deg, var(--group)15, var(--group)08); border: 1px solid var(--group)40; border-radius: 6px; padding: 10px; margin: 4px 0; }
.group-level summary { font-weight: 500; color: var(--group); }
/* Entry level styling */
.node-item { background: var(--pill); border: 1px solid var(--line); border-radius: 6px; padding: 8px; margin: 4px 0; }
.node-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.node-details { font-size: 12px; color: var(--muted); margin-top: 4px; }
.meta-row { display:flex; flex-wrap:wrap; gap:6px; }
.pill { display:inline-flex; align-items:center; gap:6px; background: #f7fafc; border:1px solid var(--line); color: var(--fg); padding: 3px 8px; border-radius: 999px; font-size: 11px; line-height: 1; }
.pill .label { color: var(--muted); font-weight: 600; }
.pill .value { color: var(--fg); }
.scope-badge { font-size: 11px; padding: 4px 8px; border-radius: 999px; margin-right: 6px; margin-bottom: 6px; display: inline-flex; align-items:center; gap:6px; }
.scope-int { background: #f0fff4; color: #2f855a; border: 1px solid #9ae6b4; }
.scope-ext { background: #fffbeb; color: #b7791f; border: 1px solid #f6e05e; }
.scope-none { background: var(--line); color: var(--muted); }
ul { margin: 6px 0 10px 18px; }
li { margin: 2px 0; }
.hidden { display:none; }
/* Search highlighting */
.search-highlight { background: #fef5e7; color: #b7791f; padding: 1px 2px; border-radius: 2px; font-weight: 600; }
/* Do not highlight inside pills/badges to keep layout intact */
.pill .search-highlight, .scope-badge .search-highlight { background: transparent; color: inherit; font-weight: inherit; padding: 0; }
.search-match { background: #f7fafc; border-left: 3px solid var(--brand); padding-left: 4px; }
/* Context menu styling */
.context-menu { position: fixed; background: var(--pill); border: 1px solid var(--line); border-radius: 6px; padding: 4px 0; box-shadow: 0 4px 12px rgba(0,0,0,0.3); z-index: 1000; min-width: 160px; }
.context-menu-item { padding: 8px 12px; cursor: pointer; color: var(--fg); border-bottom: 1px solid var(--line); }
.context-menu-item:last-child { border-bottom: none; }
.context-menu-item:hover { background: var(--line); }
.context-menu-item.disabled { color: var(--muted); cursor: not-allowed; }
.context-menu-item.disabled:hover { background: transparent; }
/* Duplicate code styling */
.duplicate-code { background: #fef2f2 !important; border: 2px solid #f56565 !important; }
.duplicate-code .key { color: #c53030 !important; font-weight: 700 !important; }
</style>
<script src="keynote_viewer.js"></script>
</head>
<body>
<div class="header">
  <h1>EnneadTab Keynote Viewer</h1>
  <p>Interactive keynote hierarchy visualization with advanced search and navigation</p>
</div>
<div class="toolbar">
  <input id="search" type="search" placeholder="Search by keynote number or description…" oninput="filterTree()" />
  <button class="btn" onclick="toggleAll(true)">Expand all</button>
  <button class="btn" onclick="toggleAll(false)">Collapse all</button>
  <button class="btn" onclick="document.getElementById('search').value=''; filterTree();">Clear</button>
  <button id="copy-notes-char-btn" class="btn" onclick="copyNotesChar()" data-notes-suffix-codepoint="%s" title="Copy invisible character (U+%s) for Revit schedule filter so you can filter NOTES from other data types.">Copy NOTES char (U+%s)</button>
</div>
<div style="margin: 0 20px 20px 20px;">
  <p>Division → Section → Entries. Use search to filter; expand/collapse controls affect the whole tree. <span title="Use this char in Revit schedule filter to show only NOTES.">Use &quot;Copy NOTES char&quot; to paste the invisible character into Revit schedule filters.</span></p>
""" % (notes_codepoint_hex, notes_codepoint_hex, notes_codepoint_hex))

    # Add duplicate warnings section only if problematic duplicates exist
    all_duplicates = duplicate_keynotes + duplicate_sections
    if all_duplicates:
        html_parts.append(f"""
  <div style="background: #fef2f2; border: 2px solid #f56565; border-radius: 8px; padding: 16px; margin: 16px 0; color: #742a2a;">
    <h3 style="margin: 0 0 12px 0; color: #c53030; font-size: 18px;">⚠️ PROBLEMATIC DUPLICATES DETECTED</h3>
    <p style="margin: 0 0 12px 0; font-weight: 600;">The following codes have conflicts and will cause warnings in Revit:</p>
    <p style="margin: 0 0 12px 0; font-size: 14px; color: #742a2a;"><em>Note: Division duplicates are normal - multiple entries can belong to the same division.</em></p>
""")
        
        if duplicate_sections:
            html_parts.append("    <h4 style=\"margin: 12px 0 8px 0; color: #c53030;\">🟡 Section Codes with Different Names:</h4>")
            html_parts.append("    <ul style=\"margin: 0 0 12px 0; padding-left: 20px;\">")
            for code in duplicate_sections:
                items_with_names = section_counts[code]
                names = [name for _, name in items_with_names]
                unique_names = list(set(names))
                html_parts.append(f"      <li><strong>{esc(code)}</strong> - {len(items_with_names)} occurrences")
                html_parts.append(f"<br/>        <em>Different names: {', '.join([esc(name) for name in unique_names if name])}</em>")
                html_parts.append("</li>")
            html_parts.append("    </ul>")
        
        if duplicate_keynotes:
            html_parts.append("    <h4 style=\"margin: 12px 0 8px 0; color: #c53030;\">🔵 Duplicate Keynote Codes:</h4>")
            html_parts.append("    <ul style=\"margin: 0 0 12px 0; padding-left: 20px;\">")
            for code in duplicate_keynotes:
                items = keynote_counts[code]
                descriptions = [item.get_string_field("KEYNOTE DESCRIPTION").strip() for item in items]
                unique_descriptions = list(set(descriptions))
                html_parts.append(f"      <li><strong>{esc(code)}</strong> - {len(items)} occurrences")
                if len(unique_descriptions) > 1:
                    html_parts.append(f"<br/>        <em>Different descriptions: {', '.join([esc(desc) for desc in unique_descriptions if desc])}</em>")
                html_parts.append("</li>")
            html_parts.append("    </ul>")
        
        html_parts.append("""
    <p style="margin: 12px 0 0 0; font-size: 14px; color: #742a2a;">
      <strong>Action Required:</strong> Review and resolve these conflicts before importing into Revit to avoid import warnings.
    </p>
  </div>
""")

    # Divisions (Category level) - sort by division number naturally
    def natural_sort_key(division_label):
        # Extract the division number from the label (e.g., "3 - DIVISION 03 - CONCRETE" -> 3)
        import re
        match = re.match(r'^(\d+)', division_label)
        return int(match.group(1)) if match else 999  # Put non-numeric at end
    
    for division_label, sections in sorted(tree.items(), key=lambda x: natural_sort_key(x[0])):
        total_entries = sum(len(v) for v in sections.values())
        html_parts.append(
            f"<details open data-division class=\"category-level\">\n  <summary><span class=\"title\"><strong>{esc(division_label)}</strong><span class=\"badge\">{total_entries}</span></span></summary>"
        )

        # Sections (Group level)
        for section_label, entries in sorted(sections.items(), key=lambda x: x[0]):
            html_parts.append(
                f"  <details data-section class=\"group-level\">\n    <summary><span class=\"title\">{esc(section_label)}<span class=\"badge\">{len(entries)}</span></span></summary>"
            )

            if entries:
                html_parts.append("    <ul>")
                for key_no, key_desc in sorted(entries, key=lambda x: (x[0], x[1])):
                    key_text = esc(key_no) if key_no else "(no number)"
                    desc_text = esc(key_desc) if key_desc else ""
                    
                    # Get section and division numbers for this entry
                    keynote_data = keynote_lookup.get(key_no, None)
                    sec_no = keynote_data.get_string_field("SECTION #").strip() if keynote_data else ""
                    div_no = keynote_data.get_string_field("DIVISION #").strip() if keynote_data else ""
                    
                    # Check if this is a problematic duplicate (not normal hierarchy duplicates)
                    is_duplicate_keynote = key_no in duplicate_keynotes if key_no else False
                    is_duplicate_section = sec_no in duplicate_sections if sec_no else False
                    is_any_duplicate = is_duplicate_keynote or is_duplicate_section
                    
                    duplicate_class = "duplicate-code" if is_any_duplicate else ""
                    duplicate_badges = []
                    if is_duplicate_keynote:
                        duplicate_badges.append('<span style="background: #3182ce; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 4px;">KEYNOTE</span>')
                    if is_duplicate_section:
                        duplicate_badges.append('<span style="background: #d69e2e; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 4px;">SECTION</span>')
                    duplicate_badge = ''.join(duplicate_badges)
                    if keynote_data:
                        # Get scope information
                        int_scope = keynote_data.get_interior_scope_fields()
                        ext_scope = keynote_data.get_exterior_scope_fields()
                        int_active = [k for k, v in int_scope.items() if v]
                        ext_active = [k for k, v in ext_scope.items() if v]
                        
                        # Get other fields that might have data
                        bldg_id = esc(keynote_data.get_string_field("BldgId"))
                        format_field = esc(keynote_data.get_string_field("FORMAT"))
                        cat_no = esc(keynote_data.get_string_field("CAT. NO."))
                        color = esc(keynote_data.get_string_field("COLOR"))
                        finish = esc(keynote_data.get_string_field("FINISH"))
                        size = esc(keynote_data.get_string_field("SIZE"))
                        source = esc(keynote_data.get_string_field("SOURCE"))
                        product = esc(keynote_data.get_string_field("PRODUCT"))
                        contact = esc(keynote_data.get_string_field("CONTACT"))
                        remarks = esc(keynote_data.get_string_field("REMARKS"))
                        
                        # Only show fields that have data, render as compact pills
                        pills = []
                        if bldg_id: pills.append(f"<span class=\"pill\"><span class=\"label\">Bldg:</span><span class=\"value\">{bldg_id}</span></span>")
                        if format_field: pills.append(f"<span class=\"pill\"><span class=\"label\">Format:</span><span class=\"value\">{format_field}</span></span>")
                        if cat_no: pills.append(f"<span class=\"pill\"><span class=\"label\">Cat#:</span><span class=\"value\">{cat_no}</span></span>")
                        if color: pills.append(f"<span class=\"pill\"><span class=\"label\">Color:</span><span class=\"value\">{color}</span></span>")
                        if finish: pills.append(f"<span class=\"pill\"><span class=\"label\">Finish:</span><span class=\"value\">{finish}</span></span>")
                        if size: pills.append(f"<span class=\"pill\"><span class=\"label\">Size:</span><span class=\"value\">{size}</span></span>")
                        if source: pills.append(f"<span class=\"pill\"><span class=\"label\">Source:</span><span class=\"value\">{source}</span></span>")
                        if product: pills.append(f"<span class=\"pill\"><span class=\"label\">Product:</span><span class=\"value\">{product}</span></span>")
                        if contact: pills.append(f"<span class=\"pill\"><span class=\"label\">Contact:</span><span class=\"value\">{contact}</span></span>")
                        if remarks: pills.append(f"<span class=\"pill\"><span class=\"label\">Remarks:</span><span class=\"value\">{remarks}</span></span>")
                        
                        details_html = f"<div class=\"meta-row\">{''.join(pills)}</div>" if pills else "<div><em>No additional details available</em></div>"
                        
                        html_parts.append(f"""      <li class="node-item {duplicate_class}">
        <div class="node-header">
          <span class="key">{key_text}</span>{duplicate_badge}
          <span class="desc">{desc_text}</span>
        </div>
        <div class="node-details">{details_html}</div>
        <div class="meta-row" style="margin-top: 6px;">
          <span class="scope-badge scope-int"><span class="label">Interior</span>: {', '.join(int_active) if int_active else 'None'}</span>
          <span class="scope-badge scope-ext"><span class="label">Exterior</span>: {', '.join(ext_active) if ext_active else 'None'}</span>
        </div>
      </li>""")
                    else:
                        html_parts.append(f"      <li class=\"node-item {duplicate_class}\"><span class=\"key\">{key_text}</span>{duplicate_badge} — <span class=\"desc\">{desc_text}</span></li>")
                html_parts.append("    </ul>")
            else:
                html_parts.append("    <p><em>No entries</em></p>")

            html_parts.append("  </details>")

        html_parts.append("</details>")

    html_parts.append("""
</body>
</html>
""")
    return "\n".join(html_parts)


def generate_html_tree(tree: Dict[str, Dict[str, List[Tuple[str, str]]]], keynote_items: List[Any], output_path: str, open_in_browser: bool = True) -> str:
    """
    Write the HTML tree to disk and optionally open it in the default browser.

    Returns the written file path.
    """
    import shutil
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    html_text = _render_tree_to_html(tree, keynote_items)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    
    # Copy the JavaScript file to the output directory
    js_source = os.path.join(os.path.dirname(__file__), "keynote_viewer.js")
    js_dest = os.path.join(os.path.dirname(output_path), "keynote_viewer.js")
    if os.path.exists(js_source):
        shutil.copy2(js_source, js_dest)

    if open_in_browser:
        webbrowser.open(f"file:///{output_path}")

    return output_path


