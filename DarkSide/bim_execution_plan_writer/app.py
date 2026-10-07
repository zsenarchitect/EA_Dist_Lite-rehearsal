import os
import json
import urllib.request
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
from werkzeug.utils import secure_filename
from utils.docx_handler import convert_to_html, save_docx
from utils.gemini_handler import get_gemini_response

# ErrorDump ingest (TODO-6442, child of epic TODO-6438). Public endpoint, no
# API key needed -- see Apps/lib/EnneadTab/ERROR_HANDLE.py:send_error_to_error_dump
# for the canonical Python client this mirrors.
ERROR_DUMP_INGEST_URL = 'https://enneadtab.com/error-dump/api/ingest'

app = Flask(__name__)

# Vercel and other serverless platforms usually only allow writing to /tmp
if os.environ.get('VERCEL'):
    app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
else:
    app.config['UPLOAD_FOLDER'] = 'uploads'

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.route('/')
def index():
    # Handle case where directory might be empty or not exist in /tmp after restart
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    files = os.listdir(app.config['UPLOAD_FOLDER'])
    return render_template('index.html', files=files)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and file.filename.endswith('.docx'):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({'success': True, 'filename': filename})
    return jsonify({'error': 'Invalid file type. Only .docx allowed'}), 400

@app.route('/editor/<filename>')
def editor(filename):
    return render_template('editor.html', filename=filename)

@app.route('/api/view/<filename>')
def view_document(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    
    html_content = convert_to_html(filepath)
    return jsonify({'html': html_content})

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    message = data.get('message')
    filename = data.get('filename')
    history = data.get('history', [])
    
    if not message or not filename:
        return jsonify({'error': 'Missing message or filename'}), 400
        
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    response_text, suggested_edits = get_gemini_response(message, history, filepath)
    
    return jsonify({'response': response_text, 'edits': suggested_edits})

@app.route('/api/save_edit', methods=['POST'])
def save_edit():
    data = request.json
    filename = data.get('filename')
    edits = data.get('edits') # Expecting list of operations
    
    if not filename or not edits:
        return jsonify({'error': 'Missing filename or edits'}), 400
        
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        save_docx(filepath, edits)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/api/client_error', methods=['POST'])
def client_error():
    """Relay a browser-side JS error to ErrorDump.

    main.js cannot POST to the ErrorDump ingest host directly: verified
    2026-09-22 that its OPTIONS preflight response carries no
    Access-Control-Allow-Origin header, so a real browser blocks the
    cross-origin fetch before it ever leaves. Relaying same-origin through
    this route (server-to-server, no CORS involved) is the only version that
    actually reports.

    Never surfaces the relay's own failure to the caller -- the browser
    already console.error'd the original error, so a relay outage would just
    add a second, less useful failure on top of the first.
    """
    data = request.get_json(silent=True) or {}
    error_message = str(data.get('error_message') or '(no message)')[:5000]
    stack_trace = data.get('stack_trace')
    payload = {
        'source_app': 'EnneadTab-OS',
        'error_message': error_message,
        'stack_trace': str(stack_trace)[:10000] if stack_trace else None,
        'function_name': data.get('function_name'),
        'environment': 'browser',
        'context': {
            'app': 'bim_execution_plan_writer',
            'url': data.get('url'),
            'user_agent': request.headers.get('User-Agent'),
        },
    }
    try:
        req = urllib.request.Request(
            ERROR_DUMP_INGEST_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        # Never let ErrorDump's own outage break the app; print so it is at
        # least visible in server logs rather than vanishing silently.
        print('client_error relay to ErrorDump failed: {}'.format(e))
    return jsonify({'ok': True})

if __name__ == '__main__':
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
