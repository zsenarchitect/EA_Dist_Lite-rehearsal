# Family Tree Interactive Visualization

## Overview
Interactive HTML-based family tree visualization tool for Revit families with comprehensive parameter analysis and association mapping.

## Architecture

### Module Structure
```
family_tree.pushbutton/
├── family_tree_script.py           # Main entry point & orchestration
├── family_data_extractor.py        # Data collection module
├── family_html_generator.py        # HTML/D3.js visualization generator
└── icon.png                        # Tool icon
```

### Module Responsibilities

#### `family_tree_script.py` (Main Orchestrator)
- Entry point for pyRevit button
- Coordinates data extraction and HTML generation
- Handles document cleanup
- Minimal logic, delegates to specialized modules

#### `family_data_extractor.py` (Data Collection)
**Key Class**: `FamilyDataExtractor`

**Responsibilities**:
- Recursively traverse family hierarchy
- Extract ALL parameters (built-in, shared, project)
- Capture parameter metadata:
  - Type vs Instance
  - Storage type (String, Integer, Double, ElementId, Boolean)
  - Read-only status
  - Formulas
  - Values across all family types
- Detect parameter associations using `GetAssociatedFamilyParameter()`
- Track opened documents for cleanup
- Build structured data (nodes and links)

**Key Methods**:
- `extract_family_tree()` - Main entry point
- `_extract_family_node()` - Process single family recursively
- `_extract_all_parameters()` - Get comprehensive parameter list
- `_extract_parameter_associations()` - Map parent-to-nested relationships
- `cleanup_documents()` - Close all opened families

#### `family_html_generator.py` (Visualization)
**Key Class**: `FamilyTreeHTMLGenerator`

**Responsibilities**:
- Generate interactive D3.js visualization
- Embed family tree data as JSON
- Create responsive UI with:
  - Force-directed graph layout
  - Clickable nodes
  - Detail panel for parameters
  - Interactive controls
  - Search functionality
  - Export capabilities

**Key Methods**:
- `generate_html()` - Main entry point, writes HTML file
- `_get_html_template()` - Returns complete HTML with embedded JavaScript

## Features

### Interactive Graph
- **D3.js v7**: Force-directed layout with physics simulation
- **Color-Coded**: Categories have distinct colors
- **Node Sizing**: Based on parameter count
- **Link Thickness**: Indicates parameter association count
- **Drag & Drop**: Move nodes freely
- **Zoom & Pan**: Navigate large family hierarchies

### Parameter Details
When clicking a family node, displays:
- Family name, category, and type count
- Comprehensive parameter table:
  - Parameter name
  - Type/Instance badge
  - Storage type
  - Read-only indicator
  - Values for ALL family types (not just current)
  - Formula display
  - Association badges
- Parameter associations section:
  - Shows which parameters link to nested families
  - Format: `ParentParam → [NestedFamily].NestedParam`

### Controls
- **Reset View**: Return to default zoom/position
- **Toggle Labels**: Show/hide family names
- **Zoom to Extent**: Fit all families in view
- **Show Associations**: Display parameter count on links
- **Export Data**: Save complete tree as JSON
- **Search**: Filter families by name

## Data Flow

```
1. User clicks "Family Tree" button in Revit
   ↓
2. family_tree_script.py orchestrates:
   ↓
3. FamilyDataExtractor collects:
   - Family hierarchy
   - All parameters
   - Parameter associations
   - Values across types
   ↓
4. FamilyTreeHTMLGenerator creates:
   - HTML file with embedded data
   - D3.js interactive visualization
   ↓
5. HTML opens in browser automatically
   ↓
6. All opened documents are closed
```

## Data Structure

### Tree Data
```python
{
  "rootFamily": "Door Family",
  "nodes": [
    {
      "id": "node_0",
      "name": "Door Family",
      "category": "Doors",
      "isEditable": true,
      "depth": 0,
      "typeCount": 3,
      "parameters": [...]
    }
  ],
  "links": [
    {
      "source": "node_0",
      "target": "node_1",
      "parameterCount": 2,
      "associatedParameters": ["Width", "Height"]
    }
  ]
}
```

### Parameter Structure
```python
{
  "name": "Width",
  "isInstance": false,
  "isReadOnly": false,
  "storageType": "Double",
  "builtInParameter": "FAMILY_WIDTH_PARAM",  # or None
  "formula": "Height / 2",  # or None
  "values": {
    "Type 1": "3.000",
    "Type 2": "4.000",
    "Type 3": "5.000"
  },
  "associations": [
    {
      "targetNodeId": "node_1",
      "targetFamilyName": "Panel",
      "targetParameter": "Width"
    }
  ]
}
```

## Key Revit API Methods Used

- `FamilyManager.Parameters` - Get family parameters
- `FamilyManager.Types` - Get all family types
- `FamilyManager.CurrentType` - Set active type to read values
- `FamilyManager.Get(param)` - Get parameter value for current type
- `FamilyManager.GetAssociatedFamilyParameter(instance, param)` - Get parameter associations
- `FilteredElementCollector(doc).OfClass(DB.Family)` - Get nested families
- `FilteredElementCollector(doc).OfClass(DB.FamilyInstance)` - Get family instances
- `Parameter.StorageType` - Get storage type
- `Parameter.Formula` - Get formula if exists
- `FamilyParameter.IsInstance` - Check type vs instance
- `Family.EditFamily()` - Open nested family document

## Extension Points

### Adding New Parameter Properties
Modify `_extract_all_parameters()` in `family_data_extractor.py`:
```python
param_info = {
    "name": param_name,
    # ... existing properties ...
    "newProperty": extract_new_property(param)  # Add here
}
```

### Customizing Visualization
Modify HTML template in `family_html_generator.py`:
- Change colors: Update `categoryColors` dictionary
- Modify layout: Adjust D3 force simulation parameters
- Add new controls: Add buttons and JavaScript handlers

### Extending Data Collection
Add new methods to `FamilyDataExtractor`:
```python
def extract_custom_data(self, family_doc):
    # Custom extraction logic
    return custom_data
```

Then call from `_extract_family_node()`.

## Error Handling

- Wrapped in `ERROR_HANDLE.try_catch_error()` decorator
- Non-editable families are skipped gracefully
- Document cleanup occurs even on errors
- Circular reference detection (depth limit: 20 levels)

## Performance Considerations

- Large families (100+ nested) may take 30-60 seconds to process
- All family documents are opened recursively (memory intensive)
- HTML file size grows with parameter count
- D3.js handles up to ~500 nodes efficiently

## Testing Checklist

- [ ] Single family (no nesting)
- [ ] Deeply nested (5+ levels)
- [ ] Multiple family types (3+ types)
- [ ] Formula parameters
- [ ] Parameter associations
- [ ] Built-in parameters
- [ ] System families (non-editable)
- [ ] Large families (50+ parameters)
- [ ] Circular references (should error gracefully)
- [ ] Document cleanup on error

## Maintenance Notes

- **D3.js Version**: v7 (CDN link, no local copy)
- **Python Version**: IronPython 2.7 (Revit compatibility)
- **Browser Compatibility**: Modern browsers (Chrome, Firefox, Edge)
- **No External Dependencies**: Self-contained HTML files

## Version History

- **v2.0** (2025-10-29): Complete modular rewrite with interactive HTML
- **v1.0** (Previous): Simple markdown output to pyRevit console

## Author Notes

This tool provides deep insight into family structure and parameter relationships. It's particularly useful for:
- Understanding complex nested families
- Debugging parameter associations
- Documenting family architecture
- Training new team members
- Quality control and family standards enforcement

