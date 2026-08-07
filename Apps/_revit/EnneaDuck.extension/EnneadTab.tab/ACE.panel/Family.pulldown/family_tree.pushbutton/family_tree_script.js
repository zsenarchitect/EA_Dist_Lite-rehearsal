// Family Tree D3.js Visualization Script
// This script will have treeData injected as a global variable

(function() {
    'use strict';
    
    // Graph setup
    const width = window.innerWidth;
    const height = window.innerHeight;
    
    // Comprehensive color map for Revit family categories
    // Organized by discipline with aesthetically pleasing, distinct colors
    const categoryColors = {
        // Architectural - Openings (Warm Reds/Oranges)
        "Doors": "#ff6b6b",              // Coral Red
        "Windows": "#4ecdc4",             // Turquoise Blue
        "Curtain Panels": "#5fcdff",      // Sky Blue
        "Curtain Wall Mullions": "#3d9bd4", // Ocean Blue
        
        // Architectural - Furniture & Equipment (Blues/Purples)
        "Furniture": "#845EC2",           // Royal Purple
        "Furniture Systems": "#9B59B6",   // Amethyst
        "Casework": "#6C5CE7",            // Lavender Blue
        "Specialty Equipment": "#feca57", // Sunset Yellow
        "Generic Models": "#96ceb4",      // Sage Green
        
        // MEP - Plumbing (Aqua/Cyan)
        "Plumbing Fixtures": "#48dbfb",   // Bright Cyan
        "Pipe Fittings": "#00b8d4",       // Deep Cyan
        "Pipes": "#0097a7",               // Teal
        "Sprinklers": "#26c6da",          // Light Cyan
        
        // MEP - Electrical (Yellows/Golds)
        "Electrical Fixtures": "#ffd93d", // Golden Yellow
        "Electrical Equipment": "#ffb142", // Amber
        "Lighting Fixtures": "#ff9ff3",   // Pink Light
        "Light Fixtures": "#ff79c6",      // Hot Pink
        "Cable Trays": "#f39c12",         // Orange Gold
        "Conduits": "#e67e22",            // Carrot Orange
        
        // MEP - HVAC (Greens)
        "Mechanical Equipment": "#00d2d3", // Mint Turquoise
        "Air Terminals": "#2ecc71",        // Emerald Green
        "Ducts": "#27ae60",                // Nephritis Green
        "Duct Fittings": "#16a085",        // Green Sea
        "Flex Ducts": "#1abc9c",           // Turquoise Green
        
        // Structural (Grays/Steel)
        "Structural Columns": "#95a5a6",   // Concrete Gray
        "Structural Framing": "#7f8c8d",   // Asbestos Gray
        "Structural Foundations": "#555555", // Dark Gray
        
        // Site (Earth Tones)
        "Site": "#a0522d",                 // Sienna Brown
        "Planting": "#3cb371",             // Medium Sea Green
        "Parking": "#708090",              // Slate Gray
        "Entourage": "#dda15e",            // Earth Brown
        
        // Communication & Technology (Cyans/Blues)
        "Communication Devices": "#00bcd4", // Cyan
        "Data Devices": "#0288d1",          // Blue
        "Fire Alarm Devices": "#e74c3c",    // Alizarin Red
        "Nurse Call Devices": "#ff6b9d",    // Bubblegum Pink
        "Security Devices": "#c0392b",      // Pomegranate Red
        "Telephone Devices": "#3498db",     // Peter River Blue
        
        // Annotations & Details (Purples)
        "Detail Items": "#9b59b6",         // Amethyst
        "Generic Annotations": "#b19cd9",  // Light Purple
        "Profiles": "#d8b5ff",             // Lavender
        "Signage": "#8e44ad",              // Wisteria Purple
        
        // Misc Categories (Greens/Teals)
        "Mass": "#1dd1a1",                 // Bright Teal
        "Columns": "#a29bfe",              // Periwinkle
        "Railings": "#fd79a8",             // Carnation Pink
        "Stairs": "#fdcb6e",               // Warm Yellow
        "Ramps": "#fab1a0",                // Light Salmon
        
        // Default fallback
        "Unknown": "#00ff9d"               // Neon Green
    };
    
    // Track unknown categories for alerting
    const unknownCategories = new Set();
    
    // Smart color getter with category matching
    const getColor = (category) => {
        // Direct match first
        if (categoryColors[category]) {
            return categoryColors[category];
        }
        
        // Try partial matching for variations
        for (const [key, color] of Object.entries(categoryColors)) {
            if (category && category.includes(key)) {
                return color;
            }
        }
        
        // Unknown category - use hot pink and track it
        if (!unknownCategories.has(category)) {
            unknownCategories.add(category);
            console.warn("⚠️ UNKNOWN CATEGORY DETECTED: '" + category + "' - Using hot pink. Please alert Sen Zhang!");
        }
        
        // Return hot pink for unknown categories
        return "#ff1493";  // Hot Pink / Deep Pink
    };
    
    // Create SVG
    const svg = d3.select(".graph-container").append("svg")
        .attr("width", width)
        .attr("height", height);
    
    const g = svg.append("g");
    
    // Zoom behavior
    const zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on("zoom", (event) => {
            g.attr("transform", event.transform);
        });
    svg.call(zoom);
    
    // Arrow marker
    svg.append("defs").append("marker")
        .attr("id", "arrow")
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 25)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("fill", "#4a4a4a");
    
    // Create force simulation
    const simulation = d3.forceSimulation(treeData.nodes)
        .force("link", d3.forceLink(treeData.links)
            .id(d => d.id)
            .distance(d => 150))
        .force("charge", d3.forceManyBody().strength(-500))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("collision", d3.forceCollide().radius(40));
    
    // Draw links
    const link = g.append("g")
        .selectAll("line")
        .data(treeData.links)
        .join("line")
        .attr("class", d => d.parameterCount > 0 ? "link has-associations" : "link")
        .attr("stroke-width", d => Math.max(2, Math.min(d.parameterCount / 2, 5)))
        .attr("marker-end", "url(#arrow)");
    
    // Link labels (associations count)
    const linkLabels = g.append("g")
        .selectAll("text")
        .data(treeData.links.filter(d => d.parameterCount > 0))
        .join("text")
        .attr("class", "link-label")
        .style("display", "none")
        .text(d => d.parameterCount);
    
    // Draw nodes
    const node = g.append("g")
        .selectAll(".node")
        .data(treeData.nodes)
        .join("g")
        .attr("class", d => d.isShared ? "node shared-family" : "node")
        .call(d3.drag()
            .on("start", dragstarted)
            .on("drag", dragged)
            .on("end", dragended))
        .on("click", (event, d) => showDetail(d));
    
    node.append("circle")
        .attr("r", d => Math.max(8, Math.min(d.parameters.length / 2, 15)))
        .style("fill", d => getColor(d.category));
    
    const labels = node.append("text")
        .text(d => d.name)
        .attr("x", 12)
        .attr("y", 4);
    
    // Tooltips
    node.on("mouseover", function(event, d) {
        const tooltip = d3.select("body").append("div")
            .attr("class", "tooltip")
            .style("opacity", 0);
        
        tooltip.transition().duration(200).style("opacity", 1);
        
        const familyType = d.isShared ? 
            '<span style="color: #50fa7b; font-weight: bold;">Shared Family</span>' : 
            '<span style="color: #6272a4; font-weight: bold;">Standard Family</span>';
        
        let purgeInfo = '';
        if (d.isPurgeable) {
            purgeInfo = '<br><span style="color: #ff5555; font-weight: bold;">⚠️ PURGEABLE (0 instances)</span>';
        } else if (d.instanceCount !== undefined && d.instanceCount > 0) {
            purgeInfo = `<br>Instances: ${d.instanceCount}`;
        }
        
        let unitInfo = '';
        if (d.units && d.units.lengthUnitDisplay) {
            unitInfo = `<br>📏 Units: ${d.units.lengthUnitDisplay}`;
        }
        
        let ownershipInfo = '';
        if (d.ownership) {
            if (d.ownership.creator) {
                ownershipInfo += `<br>👤 Created by: ${d.ownership.creator}`;
            }
            if (d.ownership.lastEditedBy && d.ownership.lastEditedBy !== d.ownership.creator) {
                ownershipInfo += `<br>✏️ Last edited by: ${d.ownership.lastEditedBy}`;
            }
        }
        
        tooltip.html(`
            <strong>${d.name}</strong><br>
            Category: ${d.category}<br>
            ${familyType}${purgeInfo}${unitInfo}${ownershipInfo}<br>
            Parameters: ${d.parameters.length}<br>
            Types: ${d.typeCount}
        `)
        .style("left", (event.pageX + 10) + "px")
        .style("top", (event.pageY - 28) + "px");
    })
    .on("mouseout", () => d3.selectAll(".tooltip").remove());
    
    // Update positions on simulation tick
    simulation.on("tick", () => {
        link
            .attr("x1", d => d.source.x)
            .attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x)
            .attr("y2", d => d.target.y);
        
        linkLabels
            .attr("x", d => (d.source.x + d.target.x) / 2)
            .attr("y", d => (d.source.y + d.target.y) / 2);
        
        node.attr("transform", d => `translate(${d.x},${d.y})`);
    });
    
    // Auto-show root family on page load and populate legend
    setTimeout(() => {
        // Find the root family (top-level, depth = 0)
        const rootNode = treeData.nodes.find(n => n.depth === 0);
        if (rootNode) {
            showDetail(rootNode);
            
            // Highlight the root node
            node.classed("selected", d => d.id === rootNode.id);
            
            // Keep the instruction banner visible on auto-load
            const banner = document.getElementById("instructionBanner");
            if (banner) {
                banner.classList.remove("hidden");
            }
        }
        
        // Populate legend by default (make it visible on load)
        populateLegend();
        document.getElementById("legendBtn").classList.add("active");
        
        // Check for unknown categories and alert
        if (unknownCategories.size > 0) {
            const unknownList = Array.from(unknownCategories).join(", ");
            const alertMsg = "⚠️ ALERT: Unknown categories detected!\n\n" +
                           "The following categories are using HOT PINK color:\n" +
                           unknownList + "\n\n" +
                           "Please notify Sen Zhang to add these categories to the color map.";
            alert(alertMsg);
        }
    }, 100);
    
    // Drag functions
    function dragstarted(event) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        event.subject.fx = event.subject.x;
        event.subject.fy = event.subject.y;
    }
    
    function dragged(event) {
        event.subject.fx = event.x;
        event.subject.fy = event.y;
    }
    
    function dragended(event) {
        if (!event.active) simulation.alphaTarget(0);
        event.subject.fx = null;
        event.subject.fy = null;
    }
    
    // Control functions
    window.resetZoom = function() {
        svg.transition().duration(750).call(zoom.transform, d3.zoomIdentity);
    };
    
    let labelsVisible = true;
    window.toggleLabels = function() {
        labelsVisible = !labelsVisible;
        labels.style("display", labelsVisible ? null : "none");
    };
    
    window.zoomToExtent = function() {
        const bounds = g.node().getBBox();
        const fullWidth = window.innerWidth;
        const fullHeight = window.innerHeight;
        const width = bounds.width;
        const height = bounds.height;
        const midX = bounds.x + width/2;
        const midY = bounds.y + height/2;
        
        const scale = 0.8 / Math.max(width / fullWidth, height / fullHeight);
        const translate = [fullWidth/2 - scale * midX, fullHeight/2 - scale * midY];
        
        svg.transition().duration(750)
            .call(zoom.transform, d3.zoomIdentity.translate(translate[0], translate[1]).scale(scale));
    };
    
    let associationLabelsVisible = false;
    window.toggleAssociationLabels = function() {
        associationLabelsVisible = !associationLabelsVisible;
        linkLabels.style("display", associationLabelsVisible ? null : "none");
        document.getElementById("assocBtn").classList.toggle("active");
    };
    
    window.exportData = function() {
        const dataStr = JSON.stringify(treeData, null, 2);
        const dataBlob = new Blob([dataStr], {type: 'application/json'});
        const url = URL.createObjectURL(dataBlob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'family_tree_data.json';
        link.click();
    };
    
    window.searchFamilies = function() {
        const searchTerm = document.getElementById("searchInput").value.toLowerCase();
        node.style("opacity", d => {
            if (!searchTerm) return 1;
            return d.name.toLowerCase().includes(searchTerm) ? 1 : 0.2;
        });
    };
    
    let animationEnabled = true;
    window.toggleAnimation = function() {
        animationEnabled = !animationEnabled;
        const svg = d3.select(".graph-container svg");
        
        if (animationEnabled) {
            svg.classed("no-animation", false);
            document.getElementById("animBtn").classList.add("active");
        } else {
            svg.classed("no-animation", true);
            document.getElementById("animBtn").classList.remove("active");
        }
    };
    
    function populateLegend() {
        // Build legend content with categories present in current tree
        const categoriesInTree = new Set(treeData.nodes.map(n => n.category));
        const legendItems = [];
        
        // Sort categories alphabetically
        const sortedCategories = Array.from(categoriesInTree).sort();
        
        for (const category of sortedCategories) {
            const color = getColor(category);
            const isUnknown = unknownCategories.has(category);
            const warningIcon = isUnknown ? ' ⚠️' : '';
            
            legendItems.push(`
                <div class="legend-item ${isUnknown ? 'legend-item-unknown' : ''}">
                    <span class="legend-color" style="background: ${color};"></span>
                    <span class="legend-label">${category}${warningIcon}</span>
                </div>
            `);
        }
        
        // Add alert at bottom if there are unknown categories
        if (unknownCategories.size > 0) {
            legendItems.push(`
                <div class="legend-alert">
                    ⚠️ Categories marked with ⚠️ are unknown and shown in HOT PINK.<br>
                    Please notify Sen Zhang to add these to the color map.
                </div>
            `);
        }
        
        document.getElementById("legendContent").innerHTML = legendItems.join("");
    }
    
    window.toggleLegend = function() {
        const legend = document.getElementById("categoryLegend");
        const btn = document.getElementById("legendBtn");
        
        if (legend.style.display === "none") {
            legend.style.display = "block";
            btn.classList.add("active");
        } else {
            legend.style.display = "none";
            btn.classList.remove("active");
        }
    };
    
    // Detail panel functions
    let selectedNode = null;
    
    function showDetail(nodeData) {
        selectedNode = nodeData;
        
        // Hide instruction banner on first click
        const banner = document.getElementById("instructionBanner");
        if (banner) {
            banner.classList.add("hidden");
        }
        
        // Update node selection
        node.classed("selected", d => d.id === nodeData.id);
        
        // Show panel with slide animation
        const panel = document.getElementById("detailPanel");
        if (panel) {
            panel.classList.add("visible");
        }
        
        // Update header
        document.getElementById("panelTitle").textContent = nodeData.name;
        document.getElementById("panelCategory").textContent = "Category: " + nodeData.category;
        
        // Build type count and instance info
        let typeInfo = "Family Types: " + nodeData.typeCount;
        if (nodeData.instanceCount !== undefined) {
            typeInfo += " | Instances: " + nodeData.instanceCount;
            if (nodeData.isPurgeable) {
                typeInfo += " (PURGEABLE ⚠️)";
            }
        }
        document.getElementById("panelTypeCount").textContent = typeInfo;
        
        // Display unit information
        let unitInfo = "";
        if (nodeData.units && nodeData.units.lengthUnitDisplay) {
            unitInfo = "📏 Length Units: " + nodeData.units.lengthUnitDisplay;
            if (nodeData.units.accuracy && nodeData.units.accuracy !== "N/A") {
                unitInfo += " (Accuracy: " + nodeData.units.accuracy + ")";
            }
        }
        document.getElementById("panelUnits").textContent = unitInfo;
        
        // Display ownership information (creator and last editor)
        let ownershipInfo = "";
        if (nodeData.ownership) {
            let ownershipParts = [];
            if (nodeData.ownership.creator) {
                ownershipParts.push("👤 Created by: " + nodeData.ownership.creator);
            }
            if (nodeData.ownership.lastEditedBy) {
                ownershipParts.push("✏️ Last edited by: " + nodeData.ownership.lastEditedBy);
            }
            ownershipInfo = ownershipParts.join("  |  ");
        }
        document.getElementById("panelOwnership").textContent = ownershipInfo;
        
        // Update family type badge (Shared vs Standard)
        const familyTypeBadge = document.getElementById("familyTypeBadge");
        if (nodeData.isShared) {
            familyTypeBadge.textContent = "Shared Family";
            familyTypeBadge.className = "family-type-badge badge-shared";
        } else {
            familyTypeBadge.textContent = "Standard Family";
            familyTypeBadge.className = "family-type-badge badge-standard";
        }
        
        // Build preview images section for all types
        let content = '';
        if (nodeData.previewImages && Object.keys(nodeData.previewImages).length > 0) {
            content += '<div class="preview-section">';
            
            // If multiple types, add selector dropdown
            if (Object.keys(nodeData.previewImages).length > 1) {
                content += `
                    <div class="preview-type-selector">
                        <label for="typeSelector-${nodeData.id}">Family Type:</label>
                        <select id="typeSelector-${nodeData.id}" onchange="changePreviewType('${nodeData.id}')">
                `;
                
                for (const typeName of Object.keys(nodeData.previewImages)) {
                    content += `<option value="${typeName}">${typeName}</option>`;
                }
                
                content += `
                        </select>
                    </div>
                `;
            }
            
            // Add preview images (hidden by default except first)
            let isFirst = true;
            for (const [typeName, imageData] of Object.entries(nodeData.previewImages)) {
                const displayStyle = isFirst ? 'block' : 'none';
                content += `
                    <div class="preview-type-container" id="preview-${nodeData.id}-${typeName}" style="display: ${displayStyle};">
                        <div class="preview-type-label">${typeName}</div>
                        <img src="${imageData}" class="preview-image" alt="${typeName} Preview">
                    </div>
                `;
                isFirst = false;
            }
            
            content += '</div>';
        } else {
            content += `
                <div class="preview-section">
                    <div class="no-preview">No preview images available</div>
                </div>
            `;
        }
        
        // Build subcategories section
        if (nodeData.subcategories && nodeData.subcategories.length > 0) {
            content += '<div class="section"><div class="section-title">Object Styles / Subcategories</div>';
            nodeData.subcategories.forEach(subcat => {
                content += `
                    <div class="param-item" style="padding: 8px 12px;">
                        <span style="color: #8be9fd;">●</span> ${subcat}
                    </div>
                `;
            });
            content += '</div>';
        }
        
        // Build parameters content grouped by parameter group
        content += `
            <div class="section">
                <div class="section-title-with-controls">
                    <span class="section-title">Parameters</span>
                    <div class="group-controls">
                        <button class="group-control-btn" onclick="expandAllGroups('${nodeData.id}')">Expand All</button>
                        <button class="group-control-btn" onclick="collapseAllGroups('${nodeData.id}')">Collapse All</button>
                    </div>
                </div>
        `;
        
        if (nodeData.parameters.length === 0) {
            content += '<p style="color: #aaa; font-size: 12px;">No parameters found</p>';
        } else {
            // Group parameters by their parameter group
            const paramsByGroup = {};
            nodeData.parameters.forEach(param => {
                const group = param.parameterGroup || 'General';
                if (!paramsByGroup[group]) {
                    paramsByGroup[group] = [];
                }
                paramsByGroup[group].push(param);
            });
            
            // Sort groups alphabetically, but put common groups first
            const priorityGroups = ['Dimensions', 'Identity Data', 'Graphics', 'Materials and Finishes', 'Construction'];
            const sortedGroups = Object.keys(paramsByGroup).sort((a, b) => {
                const aPriority = priorityGroups.indexOf(a);
                const bPriority = priorityGroups.indexOf(b);
                
                if (aPriority !== -1 && bPriority !== -1) return aPriority - bPriority;
                if (aPriority !== -1) return -1;
                if (bPriority !== -1) return 1;
                return a.localeCompare(b);
            });
            
            // Build each parameter group section
            sortedGroups.forEach((groupName, index) => {
                const params = paramsByGroup[groupName];
                const groupId = `param-group-${nodeData.id}-${index}`;
                
                content += `
                    <div class="param-group">
                        <div class="param-group-header" onclick="toggleParamGroup('${groupId}')">
                            <span class="param-group-icon" id="icon-${groupId}">▼</span>
                            <span class="param-group-name">${groupName}</span>
                            <span class="param-group-count">(${params.length})</span>
                        </div>
                        <div class="param-group-content" id="${groupId}">
                `;
                
                params.forEach(param => {
                    content += buildParameterItem(param);
                });
                
                content += `
                        </div>
                    </div>
                `;
            });
        }
        
        content += '</div>';
        
        // Build associations section
        const associations = nodeData.parameters.filter(p => p.associations && p.associations.length > 0);
        if (associations.length > 0) {
            content += '<div class="section"><div class="section-title">Parameter Associations</div>';
            associations.forEach(param => {
                param.associations.forEach(assoc => {
                    content += `
                        <div class="association-item">
                            <strong>${param.name}</strong>
                            <span class="association-arrow">→</span>
                            <span>${assoc.targetFamilyName}</span>.<strong>${assoc.targetParameter}</strong>
                        </div>
                    `;
                });
            });
            content += '</div>';
        }
        
        document.getElementById("panelContent").innerHTML = content;
    }
    
    function buildParameterItem(param) {
        let badges = '';
        
        // Add parameter type badge (User-Created vs Built-In)
        if (param.builtInParameter) {
            badges += '<span class="badge badge-builtin">Built-In</span>';
        } else {
            badges += '<span class="badge badge-user-created">User-Created</span>';
        }
        
        // Add instance/type badge
        badges += param.isInstance ? '<span class="badge badge-instance">Instance</span>' : '<span class="badge badge-type">Type</span>';
        if (param.isReadOnly) badges += '<span class="badge badge-readonly">Read-Only</span>';
        if (param.isMaterial) badges += '<span class="badge badge-material">🎨 Material</span>';
        if (param.associations && param.associations.length > 0) badges += '<span class="badge badge-associated">Associated</span>';
        
        // Add usage badges (only show "Unused" for user-created parameters)
        if (param.usedIn && param.usedIn.length > 0) {
            param.usedIn.forEach(usage => {
                if (usage === "Formula") {
                    badges += '<span class="badge badge-formula">In Formula</span>';
                } else if (usage === "Label") {
                    badges += '<span class="badge badge-label">In Label</span>';
                } else if (usage === "Unused" && !param.builtInParameter) {
                    // Only show "Unused" warning for user-created parameters
                    badges += '<span class="badge badge-unused">⚠️ Unused</span>';
                }
            });
        }
        
        let values = '';
        if (param.values) {
            values = '<div class="param-values">';
            for (let [typeName, value] of Object.entries(param.values)) {
                values += `
                    <div class="value-item">
                        <span class="value-type">${typeName}:</span>
                        <span class="value-val">${value}</span>
                    </div>
                `;
            }
            values += '</div>';
        }
        
        let formula = '';
        if (param.formula) {
            formula = `<div class="param-formula"><strong>Formula:</strong> ${param.formula}</div>`;
        }
        
        // Add visual indicator for unused parameters (only for user-created params)
        const isUnused = param.usedIn && param.usedIn.includes("Unused") && !param.builtInParameter;
        const itemClass = isUnused ? 'param-item param-item-unused' : 'param-item';
        
        return `
            <div class="${itemClass}">
                <div class="param-header">
                    <div class="param-name">${param.name}</div>
                    <div class="param-badges">${badges}</div>
                </div>
                <div class="param-detail">
                    <span class="label">Group:</span> ${param.parameterGroup || 'General'}<br>
                    <span class="label">Storage Type:</span> ${param.storageType}
                    ${param.builtInParameter ? '<br><span class="label">Built-In:</span> ' + param.builtInParameter : ''}
                    ${param.usedIn && param.usedIn.length > 0 ? '<br><span class="label">Used In:</span> ' + param.usedIn.join(', ') : ''}
                </div>
                ${values}
                ${formula}
            </div>
        `;
    }
    
    window.closePanel = function() {
        // Instead of hiding the panel, return to root family
        const rootNode = treeData.nodes.find(n => n.depth === 0);
        if (rootNode) {
            showDetail(rootNode);
            node.classed("selected", d => d.id === rootNode.id);
            
            // Show instruction banner again
            const banner = document.getElementById("instructionBanner");
            if (banner) {
                banner.classList.remove("hidden");
            }
        } else {
            // Fallback: hide panel if no root found
            document.getElementById("detailPanel").classList.remove("visible");
            node.classed("selected", false);
            selectedNode = null;
        }
    };
    
    window.toggleParamGroup = function(groupId) {
        const content = document.getElementById(groupId);
        const icon = document.getElementById('icon-' + groupId);
        
        if (content.style.display === 'none') {
            content.style.display = 'block';
            icon.textContent = '▼';
        } else {
            content.style.display = 'none';
            icon.textContent = '▶';
        }
    };
    
    window.expandAllGroups = function(nodeId) {
        const panel = document.getElementById('panelContent');
        const groups = panel.querySelectorAll('.param-group-content');
        const icons = panel.querySelectorAll('.param-group-icon');
        
        groups.forEach(group => {
            group.style.display = 'block';
        });
        
        icons.forEach(icon => {
            icon.textContent = '▼';
        });
    };
    
    window.collapseAllGroups = function(nodeId) {
        const panel = document.getElementById('panelContent');
        const groups = panel.querySelectorAll('.param-group-content');
        const icons = panel.querySelectorAll('.param-group-icon');
        
        groups.forEach(group => {
            group.style.display = 'none';
        });
        
        icons.forEach(icon => {
            icon.textContent = '▶';
        });
    };
    
    window.changePreviewType = function(nodeId) {
        const selector = document.getElementById('typeSelector-' + nodeId);
        const selectedType = selector.value;
        
        // Hide all preview containers for this node
        const allPreviews = document.querySelectorAll('[id^="preview-' + nodeId + '-"]');
        allPreviews.forEach(preview => {
            preview.style.display = 'none';
        });
        
        // Show selected type's preview
        const selectedPreview = document.getElementById('preview-' + nodeId + '-' + selectedType);
        if (selectedPreview) {
            selectedPreview.style.display = 'block';
        }
    };
    
})();

