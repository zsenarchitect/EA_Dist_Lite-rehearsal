// Upload
function uploadFile() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];
    if (!file) {
        alert("Please select a file");
        return;
    }
    
    const formData = new FormData();
    formData.append('file', file);
    
    fetch('/upload', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.location.href = '/editor/' + data.filename;
        } else {
            alert(data.error);
        }
    })
    .catch(error => console.error('Error:', error));
}

// Editor
if (typeof currentFilename !== 'undefined') {
    loadDocument();
}

function loadDocument() {
    fetch('/api/view/' + currentFilename)
    .then(response => response.json())
    .then(data => {
        const container = document.getElementById('doc-container');
        if (data.html) {
            container.innerHTML = '<div class="paper">' + data.html + '</div>';
        } else {
            container.innerHTML = '<p>Error loading document.</p>';
        }
    });
}

function sendMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;
    
    // Add user message
    addMessage(message, 'user');
    input.value = '';
    
    // Send to API
    fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message: message,
            filename: currentFilename
        })
    })
    .then(response => response.json())
    .then(data => {
        addMessage(data.response, 'ai');
        
        if (data.edits && data.edits.length > 0) {
            // Apply edits
            applyEdits(data.edits);
        }
    })
    .catch(error => {
        addMessage("Error communicating with server.", 'ai');
        console.error(error);
    });
}

function addMessage(text, type) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message ' + type;
    div.innerHTML = text.replace(/\n/g, '<br>');
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function applyEdits(edits) {
    addMessage("Applying changes to document...", 'ai');
    
    fetch('/api/save_edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            filename: currentFilename,
            edits: edits
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            addMessage("Document updated! Reloading view...", 'ai');
            loadDocument();
        } else {
            addMessage("Failed to apply edits: " + data.error, 'ai');
        }
    })
    .catch(error => console.error(error));
}

// Allow Enter to send
document.addEventListener('DOMContentLoaded', function() {
    const input = document.getElementById('chat-input');
    if (input) {
        input.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }
});
