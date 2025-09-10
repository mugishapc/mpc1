// Global variables
let mediaRecorder;
let audioChunks = [];
let isRecording = false;
let typingTimer;

// Initialize when document is ready
document.addEventListener('DOMContentLoaded', function() {
    initializeSocketIO();
    initializeVoiceRecording();
    initializeTypingIndicator();
});

// Socket.IO initialization and event handlers
function initializeSocketIO() {
    const socket = io();
    
    // Handle connection
    socket.on('connect', function() {
        console.log('Connected to server');
    });
    
    // Handle new messages
    socket.on('new_message', function(data) {
        addMessageToChat(data);
        scrollToBottom();
    });
    
    // Handle typing indicators
    socket.on('user_typing', function(data) {
        showTypingIndicator(data.username);
    });
    
    socket.on('user_stop_typing', function(data) {
        hideTypingIndicator();
    });
    
    // Handle user status updates
    socket.on('user_status', function(data) {
        updateUserStatus(data.user_id, data.status, data.last_seen);
    });
    
    // Store socket globally for other functions to use
    window.socket = socket;
}

// Voice recording functionality
function initializeVoiceRecording() {
    const recordButton = document.getElementById('record-button');
    if (recordButton) {
        recordButton.addEventListener('click', toggleRecording);
    }
}

function toggleRecording() {
    if (isRecording) {
        stopRecording();
    } else {
        startRecording();
    }
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks = [];
        mediaRecorder = new MediaRecorder(stream);
        
        mediaRecorder.ondataavailable = event => {
            audioChunks.push(event.data);
        };
        
        mediaRecorder.onstop = sendAudioMessage;
        
        mediaRecorder.start();
        isRecording = true;
        
        // Update UI
        const recordButton = document.getElementById('record-button');
        if (recordButton) {
            recordButton.textContent = '⏹️';
            recordButton.classList.add('recording');
        }
    } catch (error) {
        console.error('Error accessing microphone:', error);
        alert('Could not access your microphone. Please check permissions.');
    }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
        isRecording = false;
        
        // Update UI
        const recordButton = document.getElementById('record-button');
        if (recordButton) {
            recordButton.textContent = '🎤';
            recordButton.classList.remove('recording');
        }
    }
}

function sendAudioMessage() {
    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
    const recipientId = document.getElementById('recipient-id')?.value;
    
    if (!recipientId) {
        console.error('No recipient ID found');
        return;
    }
    
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');
    formData.append('recipient_id', recipientId);
    
    fetch('/upload_audio', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            console.log('Audio sent successfully');
        } else {
            console.error('Error sending audio:', data.error);
            alert('Failed to send audio message');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to send audio message');
    });
}

// Typing indicator functionality
function initializeTypingIndicator() {
    const messageInput = document.getElementById('message-text');
    if (messageInput) {
        let typing = false;
        
        messageInput.addEventListener('input', function() {
            const recipientId = document.getElementById('recipient-id')?.value;
            
            if (!typing && recipientId) {
                typing = true;
                window.socket.emit('typing', { recipient_id: recipientId });
            }
            
            clearTimeout(typingTimer);
            typingTimer = setTimeout(function() {
                typing = false;
                window.socket.emit('stop_typing', { recipient_id: recipientId });
            }, 1000);
        });
    }
}

// Message handling functions
function addMessageToChat(data) {
    const messagesContainer = document.getElementById('messages-container');
    if (!messagesContainer) return;
    
    const messageDiv = document.createElement('div');
    const isSent = data.sender_id == window.currentUserId;
    messageDiv.className = `message ${isSent ? 'sent' : 'received'}`;
    
    let messageContent = '';
    if (data.body) {
        messageContent = `
            <div class="message-content">
                <p>${escapeHtml(data.body)}</p>
                <span class="message-time">${formatTime(data.timestamp)}</span>
            </div>
        `;
    } else if (data.audio_file) {
        messageContent = `
            <div class="message-content">
                <div class="audio-message">
                    <audio controls>
                        <source src="/static/uploads/audio/${data.audio_file}" type="audio/webm">
                        Your browser does not support the audio element.
                    </audio>
                </div>
                <span class="message-time">${formatTime(data.timestamp)}</span>
            </div>
        `;
    }
    
    messageDiv.innerHTML = messageContent;
    messagesContainer.appendChild(messageDiv);
}

function scrollToBottom() {
    const messagesContainer = document.getElementById('messages-container');
    if (messagesContainer) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

// UI update functions
function showTypingIndicator(username) {
    const typingIndicator = document.getElementById('typing-indicator');
    if (typingIndicator) {
        typingIndicator.querySelector('span').textContent = `${username} is typing...`;
        typingIndicator.style.display = 'block';
        scrollToBottom();
    }
}

function hideTypingIndicator() {
    const typingIndicator = document.getElementById('typing-indicator');
    if (typingIndicator) {
        typingIndicator.style.display = 'none';
    }
}

function updateUserStatus(userId, status, lastSeen) {
    // Update in users list
    const userItem = document.querySelector(`.user-item[data-user-id="${userId}"]`);
    if (userItem) {
        if (status === 'online') {
            userItem.classList.add('online');
            userItem.classList.remove('offline');
            const lastSeenElement = userItem.querySelector('.last-seen');
            if (lastSeenElement) lastSeenElement.remove();
        } else {
            userItem.classList.remove('online');
            userItem.classList.add('offline');
            if (lastSeen) {
                let lastSeenElement = userItem.querySelector('.last-seen');
                if (!lastSeenElement) {
                    lastSeenElement = document.createElement('span');
                    lastSeenElement.className = 'last-seen';
                    userItem.appendChild(lastSeenElement);
                }
                lastSeenElement.textContent = `Last seen: ${formatDateTime(lastSeen)}`;
            }
        }
    }
    
    // Update in chat header if currently chatting with this user
    const recipientStatus = document.querySelector('.recipient-status');
    const recipientId = document.getElementById('recipient-id')?.value;
    if (recipientStatus && recipientId && parseInt(recipientId) === userId) {
        recipientStatus.textContent = status === 'online' ? 'Online' : 'Offline';
        recipientStatus.className = `recipient-status ${status}`;
    }
}

// Utility functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(timestamp) {
    if (!timestamp) return new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
}

function formatDateTime(timestamp) {
    if (!timestamp) return '';
    
    const date = new Date(timestamp);
    return date.toLocaleString([], {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute:'2-digit'});
}

// Handle message form submission
document.addEventListener('DOMContentLoaded', function() {
    const messageForm = document.getElementById('message-form');
    if (messageForm) {
        messageForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const messageInput = document.getElementById('message-text');
            const message = messageInput.value.trim();
            const recipientId = document.getElementById('recipient-id')?.value;
            
            if (message && recipientId) {
                window.socket.emit('send_message', {
                    recipient_id: recipientId,
                    message: message
                });
                
                messageInput.value = '';
                window.socket.emit('stop_typing', { recipient_id: recipientId });
            }
        });
    }
    
    // Scroll to bottom on page load
    scrollToBottom();
});