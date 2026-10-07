#!/usr/bin/env python3
"""
EnneadTab InDesign Writer Helper - Web Server
A simple Flask server to provide a web interface for InDesign document management
"""

import os
import sys
import json
import threading
import time
from flask import Flask, render_template, request, jsonify, send_from_directory
import win32com.client
from werkzeug.serving import make_server

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'enneadtab_indesign_helper_2024'

# Global variables
indesign_app = None
current_document = None
server_thread = None
server_instance = None

class InDesignHelper:
    """Helper class to interact with InDesign"""
    
    def __init__(self):
        self.app = None
        self.document = None
        self.connect_to_indesign()
    
    def connect_to_indesign(self):
        """Connect to InDesign application"""
        try:
            self.app = win32com.client.Dispatch("InDesign.Application")
            print("✅ Connected to InDesign")
            return True
        except Exception as e:
            print(f"❌ Failed to connect to InDesign: {e}")
            return False
    
    def get_active_document(self):
        """Get the currently active document"""
        try:
            if self.app and self.app.Documents.Count > 0:
                self.document = self.app.ActiveDocument
                return self.document
            return None
        except Exception as e:
            print(f"❌ Error getting active document: {e}")
            return None
    
    def get_document_info(self):
        """Get basic information about the current document"""
        if not self.document:
            return None
        
        try:
            info = {
                'name': self.document.Name,
                'path': self.document.FilePath,
                'pages_count': self.document.Pages.Count,
                'text_frames_count': len(self.get_text_frames())
            }
            return info
        except Exception as e:
            print(f"❌ Error getting document info: {e}")
            return None
    
    def get_text_frames(self):
        """Get all text frames in the document"""
        if not self.document:
            return []
        
        try:
            text_frames = []
            for page in self.document.Pages:
                for item in page.AllPageItems:
                    if item.Constructor.Name == "TextFrame":
                        text_frames.append({
                            'id': item.id,
                            'name': getattr(item, 'Name', 'Unnamed'),
                            'page': page.Name,
                            'content': item.Contents[:100] + "..." if len(item.Contents) > 100 else item.Contents
                        })
            return text_frames
        except Exception as e:
            print(f"❌ Error getting text frames: {e}")
            return []

    def select_text_frame(self, frame_id):
        """Select a text frame in the active document by its ID.

        Returns (success, message).
        """
        try:
            doc = self.get_active_document()
            if doc is None:
                return False, "No active document found"

            for page in doc.Pages:
                for item in page.AllPageItems:
                    if item.Constructor.Name == "TextFrame" and str(item.id) == str(frame_id):
                        # Replace the current selection with this frame
                        self.app.Select(item)
                        return True, f"Text frame '{getattr(item, 'Name', frame_id)}' selected"

            return False, f"Text frame with id '{frame_id}' not found"
        except Exception as e:
            print(f"❌ Error selecting text frame: {e}")
            return False, str(e)

# Initialize InDesign helper
indesign_helper = InDesignHelper()

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/api/status')
def api_status():
    """API endpoint to get application status"""
    try:
        doc_info = indesign_helper.get_document_info()
        return jsonify({
            'status': 'success',
            'indesign_connected': indesign_helper.app is not None,
            'document_active': doc_info is not None,
            'document_info': doc_info
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/document/info')
def api_document_info():
    """API endpoint to get document information"""
    try:
        doc_info = indesign_helper.get_document_info()
        if doc_info:
            return jsonify({
                'status': 'success',
                'data': doc_info
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'No active document found'
            }), 404
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/document/text-frames')
def api_text_frames():
    """API endpoint to get all text frames"""
    try:
        text_frames = indesign_helper.get_text_frames()
        return jsonify({
            'status': 'success',
            'data': text_frames
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/document/select-frame', methods=['POST'])
def api_select_frame():
    """API endpoint to select a text frame in the active document"""
    try:
        data = request.get_json(silent=True) or {}
        frame_id = data.get('frame_id')
        if frame_id is None:
            return jsonify({
                'status': 'error',
                'message': 'Missing frame_id in request body'
            }), 400
        success, message = indesign_helper.select_text_frame(frame_id)
        if success:
            return jsonify({
                'status': 'success',
                'message': message
            })
        return jsonify({
            'status': 'error',
            'message': message
        }), 404
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/refresh')
def api_refresh():
    """API endpoint to refresh document connection"""
    try:
        indesign_helper.connect_to_indesign()
        doc = indesign_helper.get_active_document()
        return jsonify({
            'status': 'success',
            'message': 'Document connection refreshed',
            'document_active': doc is not None
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

def create_templates():
    """Create the templates directory and HTML files"""
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    
    # Create index.html template
    index_html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EnneadTab InDesign Writer Helper</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
            color: white;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .header p {
            font-size: 1.2em;
            opacity: 0.9;
        }
        
        .card {
            background: white;
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            transition: transform 0.3s ease;
        }
        
        .card:hover {
            transform: translateY(-5px);
        }
        
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 10px;
        }
        
        .status-connected { background-color: #4CAF50; }
        .status-disconnected { background-color: #f44336; }
        
        .btn {
            background: linear-gradient(45deg, #667eea, #764ba2);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 16px;
            transition: all 0.3s ease;
            margin: 5px;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .text-frames-list {
            max-height: 400px;
            overflow-y: auto;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 10px;
        }
        
        .text-frame-item {
            padding: 10px;
            border-bottom: 1px solid #eee;
            cursor: pointer;
            transition: background-color 0.2s ease;
        }
        
        .text-frame-item:hover {
            background-color: #f5f5f5;
        }
        
        .text-frame-item:last-child {
            border-bottom: none;
        }
        
        .loading {
            text-align: center;
            padding: 20px;
            color: #666;
        }
        
        .error {
            color: #f44336;
            padding: 10px;
            background-color: #ffebee;
            border-radius: 5px;
            margin: 10px 0;
        }
        
        .success {
            color: #4CAF50;
            padding: 10px;
            background-color: #e8f5e8;
            border-radius: 5px;
            margin: 10px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🦆 EnneadTab InDesign Writer Helper</h1>
            <p>Manage your InDesign documents with ease</p>
        </div>
        
        <div class="card">
            <h2>📊 Connection Status</h2>
            <div id="status-container">
                <div class="loading">Checking connection...</div>
            </div>
            <button class="btn" onclick="refreshConnection()">🔄 Refresh Connection</button>
        </div>
        
        <div class="card" id="document-info" style="display: none;">
            <h2>📄 Document Information</h2>
            <div id="document-details"></div>
        </div>
        
        <div class="card" id="text-frames-section" style="display: none;">
            <h2>📝 Text Frames</h2>
            <button class="btn" onclick="loadTextFrames()">📋 Load Text Frames</button>
            <div id="text-frames-container"></div>
        </div>
    </div>

    <script>
        // Global variables
        let isConnected = false;
        let hasDocument = false;
        
        // Initialize the application
        document.addEventListener('DOMContentLoaded', function() {
            checkStatus();
            // Refresh status every 30 seconds
            setInterval(checkStatus, 30000);
        });
        
        async function checkStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                
                if (data.status === 'success') {
                    updateStatusDisplay(data);
                } else {
                    showError('Failed to check status: ' + data.message);
                }
            } catch (error) {
                showError('Network error: ' + error.message);
            }
        }
        
        function updateStatusDisplay(data) {
            const container = document.getElementById('status-container');
            isConnected = data.indesign_connected;
            hasDocument = data.document_active;
            
            let statusHtml = `
                <div>
                    <span class="status-indicator ${data.indesign_connected ? 'status-connected' : 'status-disconnected'}"></span>
                    InDesign: ${data.indesign_connected ? 'Connected' : 'Disconnected'}
                </div>
                <div>
                    <span class="status-indicator ${data.document_active ? 'status-connected' : 'status-disconnected'}"></span>
                    Document: ${data.document_active ? 'Active' : 'No Document'}
                </div>
            `;
            
            if (data.document_info) {
                statusHtml += `
                    <div style="margin-top: 15px; padding: 15px; background-color: #f8f9fa; border-radius: 8px;">
                        <strong>Document Details:</strong><br>
                        Name: ${data.document_info.name}<br>
                        Pages: ${data.document_info.pages_count}<br>
                        Text Frames: ${data.document_info.text_frames_count}
                    </div>
                `;
            }
            
            container.innerHTML = statusHtml;
            
            // Show/hide sections based on status
            document.getElementById('document-info').style.display = data.document_active ? 'block' : 'none';
            document.getElementById('text-frames-section').style.display = data.document_active ? 'block' : 'none';
            
            if (data.document_active) {
                loadDocumentInfo();
            }
        }
        
        async function refreshConnection() {
            try {
                const response = await fetch('/api/refresh');
                const data = await response.json();
                
                if (data.status === 'success') {
                    showSuccess('Connection refreshed successfully');
                    checkStatus();
                } else {
                    showError('Failed to refresh connection: ' + data.message);
                }
            } catch (error) {
                showError('Network error: ' + error.message);
            }
        }
        
        async function loadDocumentInfo() {
            try {
                const response = await fetch('/api/document/info');
                const data = await response.json();
                
                if (data.status === 'success') {
                    const container = document.getElementById('document-details');
                    container.innerHTML = `
                        <div style="padding: 15px; background-color: #f8f9fa; border-radius: 8px;">
                            <strong>Name:</strong> ${data.data.name}<br>
                            <strong>Path:</strong> ${data.data.path}<br>
                            <strong>Pages:</strong> ${data.data.pages_count}<br>
                            <strong>Text Frames:</strong> ${data.data.text_frames_count}
                        </div>
                    `;
                }
            } catch (error) {
                showError('Failed to load document info: ' + error.message);
            }
        }
        
        async function loadTextFrames() {
            try {
                const container = document.getElementById('text-frames-container');
                container.innerHTML = '<div class="loading">Loading text frames...</div>';
                
                const response = await fetch('/api/document/text-frames');
                const data = await response.json();
                
                if (data.status === 'success') {
                    if (data.data.length === 0) {
                        container.innerHTML = '<div class="loading">No text frames found in the document.</div>';
                    } else {
                        let framesHtml = '<div class="text-frames-list">';
                        data.data.forEach(frame => {
                            framesHtml += `
                                <div class="text-frame-item" onclick="selectTextFrame('${frame.id}')">
                                    <strong>${frame.name}</strong> (Page: ${frame.page})<br>
                                    <small>${frame.content}</small>
                                </div>
                            `;
                        });
                        framesHtml += '</div>';
                        container.innerHTML = framesHtml;
                    }
                } else {
                    showError('Failed to load text frames: ' + data.message);
                }
            } catch (error) {
                showError('Failed to load text frames: ' + error.message);
            }
        }
        
        async function selectTextFrame(frameId) {
            try {
                const response = await fetch('/api/document/select-frame', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ frame_id: frameId })
                });
                const data = await response.json();
                if (data.status === 'success') {
                    showSuccess('Text frame selected: ' + frameId);
                } else {
                    showError('Failed to select text frame: ' + data.message);
                }
            } catch (error) {
                showError('Failed to select text frame: ' + error.message);
            }
        }
        
        function showError(message) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'error';
            errorDiv.textContent = message;
            document.querySelector('.container').insertBefore(errorDiv, document.querySelector('.card'));
            
            setTimeout(() => {
                errorDiv.remove();
            }, 5000);
        }
        
        function showSuccess(message) {
            const successDiv = document.createElement('div');
            successDiv.className = 'success';
            successDiv.textContent = message;
            document.querySelector('.container').insertBefore(successDiv, document.querySelector('.card'));
            
            setTimeout(() => {
                successDiv.remove();
            }, 3000);
        }
    </script>
</body>
</html>'''
    
    with open(os.path.join(templates_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index_html)

def start_server():
    """Start the Flask server"""
    global server_instance
    
    # Create templates if they don't exist
    create_templates()
    
    print("🚀 Starting InDesign Writer Helper server...")
    print("🌐 Server will be available at: http://localhost:8081")
    print("💡 Keep this window open while using the application")
    print("🛑 Press Ctrl+C to stop the server")
    print()
    
    try:
        # Run the Flask app
        app.run(host='0.0.0.0', port=8081, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Server error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    try:
        exit_code = start_server()
        sys.exit(exit_code)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
