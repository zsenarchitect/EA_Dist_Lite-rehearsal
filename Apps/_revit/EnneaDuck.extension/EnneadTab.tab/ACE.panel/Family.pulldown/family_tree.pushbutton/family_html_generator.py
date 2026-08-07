#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Family HTML Generator Module
Generates interactive D3.js HTML visualization for family tree with parameter details.
Loads styles and scripts from external files for better maintainability.
"""

import json
import codecs
import os


class FamilyTreeHTMLGenerator:
    """Generates interactive HTML visualization for family tree."""
    
    def __init__(self, tree_data):
        """Initialize with tree data.
        
        Args:
            tree_data: Dictionary with nodes and links
        """
        self.tree_data = tree_data
        self.script_dir = os.path.dirname(__file__)
    
    def generate_html(self, output_path):
        """Generate complete HTML file with embedded data.
        
        Args:
            output_path: Path to save HTML file
        """
        html_content = self._get_html_template()
        
        # Write to file with UTF-8 encoding to support Unicode characters
        with codecs.open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _load_css(self):
        """Load CSS from external file.
        
        Returns:
            str: CSS content
        """
        css_path = os.path.join(self.script_dir, 'family_tree_styles.css')
        try:
            with codecs.open(css_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return "/* CSS file not found */"
    
    def _load_js(self):
        """Load JavaScript from external file.
        
        Returns:
            str: JavaScript content
        """
        js_path = os.path.join(self.script_dir, 'family_tree_script.js')
        try:
            with codecs.open(js_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return "/* JavaScript file not found */"
    
    def _get_html_template(self):
        """Return HTML template with D3.js visualization.
        
        Returns:
            str: Complete HTML content
        """
        # Load external CSS and JS
        css_content = self._load_css()
        js_content = self._load_js()
        
        # Embed data as JSON
        data_json = json.dumps(self.tree_data)
        root_family = self.tree_data.get("rootFamily", "Family")
        
        # Generate clean HTML template with injected CSS and JS
        html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Family Tree - {root_family}</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
{css_content}
    </style>
</head>
<body>
    <div class="container">
        <div class="graph-container">
            <div class="controls">
                <h3>Family Tree Controls</h3>
                <div class="control-group">
                    <button onclick="resetZoom()">Reset View</button>
                    <button onclick="toggleLabels()">Toggle Labels</button>
                    <button onclick="zoomToExtent()">Zoom to Extent</button>
                    <button onclick="toggleAssociationLabels()" id="assocBtn">Show Associations</button>
                    <button onclick="toggleAnimation()" id="animBtn" class="active">Flowing Animation</button>
                    <button onclick="toggleLegend()" id="legendBtn">Category Legend</button>
                    <button onclick="exportData()">Export Data</button>
                </div>
                <div class="search-box">
                    <input type="text" id="searchInput" placeholder="Search families..." onkeyup="searchFamilies()">
                </div>
                <div class="category-legend" id="categoryLegend">
                    <div class="legend-title">Category Colors</div>
                    <div id="legendContent"></div>
                </div>
            </div>
            <div class="instruction-banner" id="instructionBanner">
                💡 Top-level family info shown. Click any node to explore nested families and their parameters →
            </div>
        </div>
        <div class="detail-panel" id="detailPanel">
            <div class="panel-header">
                <button class="panel-close" onclick="closePanel()">&times;</button>
                <h2 id="panelTitle">Family Name</h2>
                <div class="category" id="panelCategory">Category</div>
                <div class="type-count" id="panelTypeCount">Types</div>
                <div class="unit-info" id="panelUnits">Units</div>
                <div class="ownership-info" id="panelOwnership">Ownership</div>
                <div id="familyTypeBadge" class="family-type-badge"></div>
            </div>
            <div class="panel-content" id="panelContent">
                <!-- Content populated by JavaScript -->
            </div>
        </div>
    </div>
    
    <script>
        // Inject family tree data
        const treeData = {data_json};
        
        // Load main visualization script
        {js_content}
    </script>
</body>
</html>""".format(
            root_family=root_family,
            css_content=css_content,
            data_json=data_json,
            js_content=js_content
        )
        
        return html


if __name__ == "__main__":
    pass
