# Color Scheme Excel Templates

Two formats are accepted by the `Excel2ColorScheme` button in
`EnneadTab > ACE > ColorScheme`. Pick the matching mode in the
dialog's first prompt.

## Single Channel

Use when you exported a single Revit color scheme via `ColorScheme2Excel`
(ACE panel > ColorScheme pulldown > ColorScheme2Excel), edited the colors,
and want to push the result back into the same scheme.

There is no sample file for single-channel mode — the correct workflow is:
1. Run `ColorScheme2Excel` to export the target scheme to Excel.
2. Edit the colors in that exported file.
3. Come back to `Excel2ColorScheme > Single Channel` and Browse to that file.

Single-channel Excel layout (as exported by ColorScheme2Excel):

| A: Parameter Value | B: Color |
|--------------------|----------|
| Lobby              | (filled cell) |
| Imaging            | (filled cell) |

One scheme per Excel. The `Color` cell's **fill color** is what the tool
reads — typed RGB / hex values are a fallback only.

## Dual Channel — `Sample ColorScheme (Dual Channel).xlsx`

Use when you have the office-standard color template, which carries
Department and Program palettes side-by-side in one worksheet.

The sample file is the real Ennead healthcare office template.
It contains two sheets: **HEALTHCARE** and **CANCER CENTER**, each in the
standard 6-column dual-pair layout:

| A: Department | B: Abbr. | C: Color | D: Program | E: Abbr. | F: Color |
|---------------|----------|----------|------------|----------|----------|
| Lobby         | LBY      | (filled) | Outpatient | OUT      | (filled) |
| Imaging       | IMG      | (filled) | Inpatient  | IN       | (filled) |

The parser reads fixed columns A/D for names and C/F for colors. No
column header override is needed for this format.

The dialog picks two color schemes — one for Department, one for Program —
and applies both in a single Revit transaction.

## Avoid in color cells

- Conditional Formatting fills (the tool sees the underlying cell color, not the CF result)
- Theme colors (resolution is unreliable across Office versions)
- Typed RGB without an actual fill (fallback only — fragile)

Use Excel's plain "Fill Color" picker.
