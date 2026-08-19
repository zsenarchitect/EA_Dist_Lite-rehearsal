#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = "Visualize sheet and view relationships from saved data using an interactive web interface."
__title__ = "Visualize Sheet Tree"


import webbrowser
from flask import Flask, render_template_string

import threading
import time
from werkzeug.serving import make_server

import _Exe_Util


class ServerThread(threading.Thread):
    def __init__(self, app, port=5000):
        threading.Thread.__init__(self)
        self.server = make_server('127.0.0.1', port, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()

def create_visualization():
    """Create and run the visualization server."""
    try:
        data = _Exe_Util.get_data("sheet_tree_data")
        if not data:
            print("No data found in sheet_tree_data")
            return 

        # Process data to create a graph structure
        nodes = []
        links = []
        node_map = {}  # Map view names to indices

        # First create all nodes
        for view_name, view_data in data.items():
            if isinstance(view_data, dict):
                node_map[view_name] = len(nodes)
                nodes.append({
                    "id": len(nodes),
                    "name": view_name,
                    "type": view_data.get("type", "Unknown"),
                    "sheet": view_data.get("sheet", "Unplaced"),
                    "detail": view_data.get("detail", "-")  # Add detail number
                })

        # Then create links from references
        for view_name, view_data in data.items():
            if isinstance(view_data, dict) and "references" in view_data:
                source_idx = node_map.get(view_name)
                if source_idx is not None:
                    for ref in view_data["references"]:
                        # Skip references to self or non-existent views
                        if ref["name"] == view_name:
                            continue
                        target_idx = node_map.get(ref["name"])
                        # Skip self-referential connections
                        if target_idx is not None and target_idx != source_idx:
                            links.append({
                                "source": source_idx,
                                "target": target_idx,
                                "type": ref.get("type", "Unknown")
                            })

        # Create the visualization data
        graph_data = {
            "nodes": nodes,
            "links": links
        }

        # HTML template
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>View Reference Diagram</title>
            <script src="https://d3js.org/d3.v7.min.js"></script>
            <style>
                body { 
                    font-family: Arial, sans-serif; 
                    margin: 0;
                    overflow: hidden;
                    background-color: #1a1a1a;
                    color: #ffffff;
                }
                .container {
                    width: 100vw;
                    height: 100vh;
                    background-color: #1a1a1a;
                }
                .node {
                    cursor: pointer;
                }
                .node circle {
                    stroke-width: 2px;
                    stroke: #ffffff;
                }
                .node text {
                    font: 10px sans-serif;
                    pointer-events: none;
                    fill: #ffffff;
                }
                .link {
                    fill: none;
                    stroke: #4a4a4a;
                    stroke-opacity: 0.8;
                    stroke-width: 2px;
                }
                .link-path {
                    fill: none;
                    stroke: #4a4a4a;
                    stroke-opacity: 0.3;
                    stroke-width: 2px;
                }
                .link-dot {
                    fill: #4a4a4a;
                    r: 3;
                }
                @keyframes flow {
                    0% {
                        stroke-dashoffset: 1000;
                    }
                    100% {
                        stroke-dashoffset: 0;
                    }
                }
                .flow-path {
                    fill: none;
                    stroke: #4a4a4a;
                    stroke-width: 2px;
                    stroke-dasharray: 10, 5;
                    animation: flow 20s linear infinite;
                }
                .glow {
                    filter: drop-shadow(0 0 3px #4a4a4a);
                }
                .controls {
                    position: fixed;
                    top: 20px;
                    left: 20px;
                    background: #2d2d2d;
                    padding: 10px;
                    border-radius: 4px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                    display: flex;
                    gap: 10px;
                    border: 1px solid #4a4a4a;
                }
                .controls button {
                    padding: 8px 12px;
                    border: none;
                    border-radius: 4px;
                    background: #3d3d3d;
                    color: white;
                    cursor: pointer;
                    transition: all 0.3s;
                    border: 1px solid #4a4a4a;
                    position: relative;
                }
                .controls button.active {
                    background: #4d4d4d;
                    border-color: #00ff9d;
                }
                .tooltip {
                    position: absolute;
                    padding: 8px;
                    background: rgba(0, 0, 0, 0.9);
                    color: white;
                    border-radius: 4px;
                    font-size: 12px;
                    pointer-events: none;
                    border: 1px solid #4a4a4a;
                    z-index: 1000;
                }
                .button-tooltip {
                    position: absolute;
                    padding: 8px;
                    background: rgba(0, 0, 0, 0.9);
                    color: white;
                    border-radius: 4px;
                    font-size: 12px;
                    pointer-events: none;
                    border: 1px solid #4a4a4a;
                    z-index: 1000;
                    white-space: nowrap;
                }
                .legend {
                    position: fixed;
                    bottom: 20px;
                    right: 20px;
                    background: #2d2d2d;
                    padding: 15px;
                    border-radius: 4px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                    border: 1px solid #4a4a4a;
                }
                .legend-item {
                    display: flex;
                    align-items: center;
                    margin: 5px 0;
                    color: #ffffff;
                }
                .legend-color {
                    width: 12px;
                    height: 12px;
                    margin-right: 8px;
                    border-radius: 50%;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="controls">
                    <button onclick="resetZoom()">Reset View</button>
                    <button onclick="toggleLabels()">Toggle Labels</button>
                    <button onclick="toggleSheetInfo()">Toggle Sheet Info</button>
                    <button onclick="zoomToExtent()">Zoom to Extent</button>
                    <button onclick="toggleSortByConnections()" 
                            onmouseover="showButtonTooltip(event, 'Sort nodes by number of outgoing connections. Most connected nodes will be at the top.')"
                            onmouseout="hideButtonTooltip()">Sort by Connections</button>
                    <button onclick="toggleSortByRank()"
                            onmouseover="showButtonTooltip(event, 'Sort nodes by their hierarchical rank. Parent nodes will be at the top.')"
                            onmouseout="hideButtonTooltip()">Sort by Rank</button>
                </div>
            </div>
            <script>
                const data = {{ data | tojson | safe }};
                const width = window.innerWidth;
                const height = window.innerHeight;

                // Color scale for different view types
                const color = d3.scaleOrdinal()
                    .domain(["FloorPlan", "Section", "Elevation", "Detail", "Schedule", "ThreeD"])
                    .range(["#00ff9d", "#00b8ff", "#ffb800", "#ff00f7", "#ff6b00", "#00fff7"]);

                const svg = d3.select(".container").append("svg")
                    .attr("width", width)
                    .attr("height", height);

                // Add zoom behavior
                const g = svg.append("g");
                const zoom = d3.zoom()
                    .scaleExtent([0.1, 4])
                    .on("zoom", (event) => {
                        g.attr("transform", event.transform);
                    });
                svg.call(zoom);

                // Define arrow marker with improved design
                svg.append("defs").append("marker")
                    .attr("id", "arrow")
                    .attr("viewBox", "0 -5 10 10")
                    .attr("refX", 25)
                    .attr("refY", 0)
                    .attr("markerWidth", 8)
                    .attr("markerHeight", 8)
                    .attr("orient", "auto")
                    .append("path")
                    .attr("class", "arrow")
                    .attr("d", "M0,-5L10,0L0,5Z")
                    .style("fill", "#4a4a4a");

                // Calculate node ranks based on outgoing connections
                function calculateNodeRanks() {
                    const outDegree = new Map();
                    data.nodes.forEach(node => outDegree.set(node.id, 0));
                    
                    // Count outgoing connections
                    data.links.forEach(link => {
                        outDegree.set(link.source.id, (outDegree.get(link.source.id) || 0) + 1);
                    });
                    
                    // Sort nodes by outgoing connections
                    const sortedNodes = [...data.nodes].sort((a, b) => 
                        (outDegree.get(b.id) || 0) - (outDegree.get(a.id) || 0)
                    );
                    
                    // Assign ranks (levels)
                    const ranks = new Map();
                    sortedNodes.forEach((node, index) => {
                        ranks.set(node.id, index);
                    });
                    
                    return { outDegree, ranks };
                }

                // Apply hierarchical layout
                function applyHierarchicalLayout() {
                    const { outDegree, ranks } = calculateNodeRanks();
                    const maxRank = Math.max(...ranks.values());
                    const levelHeight = height / (maxRank + 2);
                    const horizontalSpacing = width / (data.nodes.length + 1);
                    
                    // Position nodes by rank
                    data.nodes.forEach((node, i) => {
                        const rank = ranks.get(node.id);
                        node.x = horizontalSpacing * (i + 1);
                        node.y = levelHeight * (rank + 1);
                        node.fx = node.x;
                        node.fy = node.y;
                    });
                    
                    // Update simulation
                    simulation.alpha(1).restart();
                }

                // Sort by connections button handler
                function sortByConnections() {
                    applyHierarchicalLayout();
                }

                // Create force simulation with adjusted parameters
                const simulation = d3.forceSimulation(data.nodes)
                    .force("link", d3.forceLink(data.links)
                        .id(d => d.id)
                        .distance(150))
                    .force("charge", d3.forceManyBody().strength(-400))
                    .force("center", d3.forceCenter(width / 2, height / 2))
                    .force("collision", d3.forceCollide().radius(60))
                    .force("y", d3.forceY().strength(0.1));  // Add slight vertical alignment force

                // Draw links with animated paths
                const linkGroup = g.append("g")
                    .attr("class", "links");

                // Background path for glow effect
                const linkBg = linkGroup
                    .selectAll("path.bg")
                    .data(data.links)
                    .join("path")
                    .attr("class", "link-path")
                    .attr("stroke-width", "4px");

                // Animated flow path
                const linkFlow = linkGroup
                    .selectAll("path.flow")
                    .data(data.links)
                    .join("path")
                    .attr("class", "flow-path glow");

                // Moving dot
                const linkDot = linkGroup
                    .selectAll("circle.dot")
                    .data(data.links)
                    .join("circle")
                    .attr("class", "link-dot glow");

                // Draw nodes
                const node = g.append("g")
                    .selectAll(".node")
                    .data(data.nodes)
                    .join("g")
                    .attr("class", "node")
                    .call(d3.drag()
                        .on("start", dragstarted)
                        .on("drag", dragged)
                        .on("end", dragended));

                node.append("circle")
                    .attr("r", 8)
                    .style("fill", d => color(d.type))
                    .style("stroke", "#fff")
                    .style("stroke-width", "2px");

                const labels = node.append("text")
                    .text(d => d.name)
                    .attr("x", 12)
                    .attr("y", 3);

                // Add tooltips
                node.on("mouseover", function(event, d) {
                    const tooltip = d3.select("body").append("div")
                        .attr("class", "tooltip")
                        .style("opacity", 0);

                    tooltip.transition()
                        .duration(200)
                        .style("opacity", .9);

                    let content = `
                        <strong>${d.name}</strong><br>
                        Type: ${d.type}<br>
                        Sheet: ${d.sheet}${d.detail ? `<br>Detail: ${d.detail}` : ''}
                    `;
                    
                    tooltip.html(content)
                        .style("left", (event.pageX + 10) + "px")
                        .style("top", (event.pageY - 28) + "px");
                })
                .on("mouseout", function() {
                    d3.selectAll(".tooltip").remove();
                });

                // Add legend
                const legend = d3.select("body")
                    .append("div")
                    .attr("class", "legend");

                const viewTypes = ["FloorPlan", "Section", "Elevation", "Detail", "Schedule", "ThreeD"];
                
                legend.selectAll(".legend-item")
                    .data(viewTypes)
                    .join("div")
                    .attr("class", "legend-item")
                    .html(d => `
                        <div class="legend-color" style="background: ${color(d)}"></div>
                        <span>${d}</span>
                    `);

                // Add rank labels
                const rankLabels = g.append("g")
                    .attr("class", "rank-labels")
                    .style("display", "none");  // Initially hidden

                rankLabels.selectAll("text")
                    .data(d3.range(6))  // Show levels 0-5
                    .join("text")
                    .attr("x", 10)
                    .attr("y", d => (d + 1) * (height / 6))
                    .style("fill", "#4a4a4a")
                    .style("font-size", "12px")
                    .text(d => `Level ${d}`);

                // Update force simulation with improved link paths
                simulation.on("tick", () => {
                    // Calculate curved paths
                    const paths = data.links.map(link => {
                        const dx = link.target.x - link.source.x;
                        const dy = link.target.y - link.source.y;
                        const dr = Math.sqrt(dx * dx + dy * dy);
                        const angle = Math.atan2(dy, dx);
                        const offset = 20;
                        
                        const cp1x = link.source.x + (dr/2) * Math.cos(angle) + offset * Math.cos(angle - Math.PI/2);
                        const cp1y = link.source.y + (dr/2) * Math.sin(angle) + offset * Math.sin(angle - Math.PI/2);
                        const cp2x = link.target.x - (dr/2) * Math.cos(angle) + offset * Math.cos(angle - Math.PI/2);
                        const cp2y = link.target.y - (dr/2) * Math.sin(angle) + offset * Math.sin(angle - Math.PI/2);
                        
                        return `M${link.source.x},${link.source.y} 
                                C${cp1x},${cp1y} 
                                 ${cp2x},${cp2y} 
                                 ${link.target.x},${link.target.y}`;
                    });

                    // Update background paths
                    linkBg.attr("d", (d, i) => paths[i]);

                    // Update flow paths
                    linkFlow.attr("d", (d, i) => paths[i]);

                    // Animate dots along paths
                    linkDot.each((d, i) => {
                        const path = paths[i];
                        const pathLength = d3.select(linkFlow.nodes()[i]).node().getTotalLength();
                        const progress = (Date.now() % 3000) / 3000; // 3 second cycle
                        const point = d3.select(linkFlow.nodes()[i])
                            .node()
                            .getPointAtLength(progress * pathLength);
                        
                        d3.select(linkDot.nodes()[i])
                            .attr("cx", point.x)
                            .attr("cy", point.y);
                    });

                    node.attr("transform", d => `translate(${d.x},${d.y})`);
                });

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

                // Reset zoom
                function resetZoom() {
                    svg.transition()
                        .duration(750)
                        .call(zoom.transform, d3.zoomIdentity);
                }

                // Toggle labels
                let labelsVisible = true;
                function toggleLabels() {
                    labelsVisible = !labelsVisible;
                    labels.style("display", labelsVisible ? null : "none");
                }

                // Toggle sheet info
                let showSheetInfo = false;
                function toggleSheetInfo() {
                    showSheetInfo = !showSheetInfo;
                    labels.text(d => {
                        if (!showSheetInfo) return d.name;
                        // Only show detail if it's not the default dash
                        const detailInfo = (d.detail && d.detail !== '-') ? `${d.detail}/` : '';
                        return `[${detailInfo}${d.sheet}]${d.name}`;
                    });
                }

                // Zoom to extent
                function zoomToExtent() {
                    const bounds = g.node().getBBox();
                    const fullWidth = window.innerWidth;
                    const fullHeight = window.innerHeight;
                    const width = bounds.width;
                    const height = bounds.height;
                    const midX = bounds.x + width/2;
                    const midY = bounds.y + height/2;
                    
                    const scale = 0.9 / Math.max(width / fullWidth, height / fullHeight);
                    const translate = [fullWidth/2 - scale * midX, fullHeight/2 - scale * midY];
                    
                    svg.transition()
                        .duration(750)
                        .call(zoom.transform, d3.zoomIdentity
                            .translate(translate[0], translate[1])
                            .scale(scale));
                }

                // Browser close detection
                let isActive = true;
                let pingInterval;
                let lastPingTime = Date.now();
                const TIMEOUT = 30 * 60 * 1000; // 30 minutes in milliseconds

                function startPinging() {
                    if (pingInterval) clearInterval(pingInterval);
                    pingInterval = setInterval(async () => {
                        if (!isActive) return;
                        try {
                            const response = await fetch('/ping');
                            const result = await response.text();
                            if (result === 'shutdown') {
                                isActive = false;
                                clearInterval(pingInterval);
                                window.close();
                            }
                            lastPingTime = Date.now();
                        } catch (e) {
                            isActive = false;
                            clearInterval(pingInterval);
                        }
                    }, 1000);

                    // Check for timeout
                    setInterval(() => {
                        if (Date.now() - lastPingTime > TIMEOUT) {
                            isActive = false;
                            clearInterval(pingInterval);
                            fetch('/close').catch(() => {});
                            window.close();
                        }
                    }, 1000);
                }

                // Start pinging when page loads
                startPinging();

                // Handle page close/refresh
                window.addEventListener('beforeunload', async () => {
                    isActive = false;
                    clearInterval(pingInterval);
                    try {
                        await fetch('/close');
                    } catch (e) {
                        // Ignore errors during page close
                    }
                });

                // Button tooltip functions
                function showButtonTooltip(event, text) {
                    const tooltip = d3.select("body")
                        .append("div")
                        .attr("class", "button-tooltip")
                        .style("opacity", 0);

                    tooltip.html(text)
                        .style("left", (event.pageX + 10) + "px")
                        .style("top", (event.pageY - 28) + "px");

                    tooltip.transition()
                        .duration(200)
                        .style("opacity", 1);
                }

                function hideButtonTooltip() {
                    d3.selectAll(".button-tooltip").remove();
                }

                // Sort toggle states
                let isSortedByConnections = false;
                let isSortedByRank = false;

                // Toggle sort by connections
                function toggleSortByConnections() {
                    isSortedByConnections = !isSortedByConnections;
                    isSortedByRank = false;
                    updateSortButtons();
                    rankLabels.style("display", "none");  // Hide labels
                    if (isSortedByConnections) {
                        applyHierarchicalLayout();
                    } else {
                        resetLayout();
                    }
                }

                // Toggle sort by rank
                function toggleSortByRank() {
                    isSortedByRank = !isSortedByRank;
                    isSortedByConnections = false;
                    updateSortButtons();
                    rankLabels.style("display", isSortedByRank ? null : "none");  // Show/hide labels
                    if (isSortedByRank) {
                        applyRankLayout();
                    } else {
                        resetLayout();
                    }
                }

                // Update sort button states
                function updateSortButtons() {
                    d3.selectAll(".controls button")
                        .classed("active", function() {
                            const text = d3.select(this).text();
                            return (text === "Sort by Connections" && isSortedByConnections) ||
                                   (text === "Sort by Rank" && isSortedByRank);
                        });
                }

                // Reset layout to force-directed
                function resetLayout() {
                    data.nodes.forEach(node => {
                        node.fx = null;
                        node.fy = null;
                    });
                    rankLabels.style("display", "none");  // Hide labels
                    simulation.alpha(1).restart();
                }

                // Apply rank-based layout
                function applyRankLayout() {
                    const ranks = new Map();
                    data.nodes.forEach(node => {
                        ranks.set(node.id, 0);
                    });
                    
                    // Calculate ranks based on incoming connections
                    data.links.forEach(link => {
                        ranks.set(link.target.id, ranks.get(link.target.id) + 1);
                    });
                    
                    const maxRank = Math.max(...ranks.values());
                    const levelHeight = height / (maxRank + 2);
                    const horizontalSpacing = width / (data.nodes.length + 1);
                    
                    data.nodes.forEach((node, i) => {
                        const rank = ranks.get(node.id);
                        node.x = horizontalSpacing * (i + 1);
                        node.y = levelHeight * (rank + 1);
                        node.fx = node.x;
                        node.fy = node.y;
                    });
                    
                    simulation.alpha(1).restart();
                }

                // Fix dot animation by using requestAnimationFrame
                function animateDots() {
                    linkDot.each((d, i) => {
                        const pathLength = d3.select(linkFlow.nodes()[i]).node().getTotalLength();
                        const progress = (Date.now() % 3000) / 3000;
                        const point = d3.select(linkFlow.nodes()[i])
                            .node()
                            .getPointAtLength(progress * pathLength);
                        
                        d3.select(linkDot.nodes()[i])
                            .attr("cx", point.x)
                            .attr("cy", point.y);
                    });
                    requestAnimationFrame(animateDots);
                }

                // Start dot animation
                animateDots();
            </script>
        </body>
        </html>
        """

        # Create Flask app
        app = Flask(__name__)
        server = None
        is_running = True  # Flag to track if server should keep running
        start_time = time.time()  # Track start time
        timeout = 30 * 60  # 30 minutes in seconds
        
        @app.route('/')
        def index():
            try:
                return render_template_string(html_template, data=graph_data)
            except Exception as e:
                print(f"Error rendering template: {str(e)}")
                return f"Error rendering visualization: {str(e)}", 500

        @app.route('/ping')
        def ping():
            nonlocal is_running
            if not is_running:
                return 'shutdown', 200
            return 'pong', 200

        @app.route('/close')
        def close():
            nonlocal is_running
            is_running = False
            if server:
                threading.Thread(target=server.shutdown).start()
            return 'closed', 200

        # Start server in a separate thread
        port = 5000
        server = ServerThread(app, port)
        server.start()
        
        # Open browser
        webbrowser.open(f"http://localhost:{port}")
        
        # Monitor connection and server status
        try:
            while is_running:
                time.sleep(1)
                if not server.is_alive():
                    break
                # Check for timeout
                if time.time() - start_time > timeout:
                    print("Visualization timeout reached (30 minutes). Shutting down...")
                    is_running = False
                    break
        except KeyboardInterrupt:
            is_running = False
        finally:
            if server:
                server.shutdown()
                server.join()
            print("Visualization server closed.")

    except Exception as e:
        print(f"Critical error in visualization: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    try:
        create_visualization()
    except FileNotFoundError as e:
        print(f"Error: {e}")
    except ImportError:
        print("Error: Flask is not installed. Please install it using: pip install flask") 