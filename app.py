import eventlet
eventlet.monkey_patch()  # <-- MUST be first

import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from config import Config

# Initialize app
app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions (but don't import models yet)
db = SQLAlchemy()
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    profile_picture = db.Column(db.String(120), default='default.png')
    status = db.Column(db.String(20), default='offline')
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    body = db.Column(db.Text, nullable=True)
    audio_file = db.Column(db.String(120), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    
    sender = db.relationship('User', foreign_keys=[sender_id])
    recipient = db.relationship('User', foreign_keys=[recipient_id])

# Initialize extensions with app
db.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Initialize database
def init_database():
    with app.app_context():
        db.create_all()
        print("Database tables created successfully")

# Routes
@app.route('/')
@login_required
def index():
    users = User.query.filter(User.id != current_user.id).all()
    return render_template('index.html', users=users)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            user.status = 'online'
            db.session.commit()
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Check if user exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists')
            return redirect(url_for('register'))
        
        existing_email = User.query.filter_by(email=email).first()
        if existing_email:
            flash('Email already exists')
            return redirect(url_for('register'))
        
        # Create new user with hashed password
        hashed_password = generate_password_hash(password)
        user = User(username=username, email=email, password_hash=hashed_password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful. Please login.')
        return redirect(url_for('login'))
    
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    current_user.status = 'offline'
    current_user.last_seen = datetime.utcnow()
    db.session.commit()
    logout_user()
    return redirect(url_for('login'))


@app.route('/chat/<int:user_id>')
@login_required
def chat(user_id):
    recipient = User.query.get_or_404(user_id)
    
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.recipient_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.recipient_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()
    
    for message in messages:
        if message.recipient_id == current_user.id and not message.is_read:
            message.is_read = True
    db.session.commit()
    
    return render_template('chat.html', recipient=recipient, messages=messages)


@app.route('/upload_audio', methods=['POST'])
@login_required
def upload_audio():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file'}), 400
    
    audio_file = request.files['audio']
    recipient_id = request.form.get('recipient_id')
    
    if audio_file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if audio_file and allowed_file(audio_file.filename):
        filename = str(uuid.uuid4()) + '.webm'
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        audio_file.save(filepath)
        
        message = Message(
            sender_id=current_user.id,
            recipient_id=recipient_id,
            audio_file=filename
        )
        db.session.add(message)
        db.session.commit()
        
        socketio.emit('new_message', {
            'id': message.id,
            'sender_id': current_user.id,
            'sender_name': current_user.username,
            'recipient_id': int(recipient_id),
            'audio_file': filename,
            'timestamp': message.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }, room=f'user_{recipient_id}')
        
        return jsonify({'success': True, 'filename': filename})
    
    return jsonify({'error': 'Invalid file type'}), 400


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ['webm', 'wav', 'mp3', 'ogg']


# SocketIO Events
@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        join_room(f'user_{current_user.id}')
        current_user.status = 'online'
        db.session.commit()
        emit('user_status', {
            'user_id': current_user.id,
            'status': 'online'
        }, broadcast=True)


@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        current_user.status = 'offline'
        current_user.last_seen = datetime.utcnow()
        db.session.commit()
        emit('user_status', {
            'user_id': current_user.id,
            'status': 'offline',
            'last_seen': current_user.last_seen.strftime('%Y-%m-%d %H:%M:%S')
        }, broadcast=True)


@socketio.on('send_message')
def handle_send_message(data):
    recipient_id = data['recipient_id']
    message_body = data['message']
    
    message = Message(
        sender_id=current_user.id,
        recipient_id=recipient_id,
        body=message_body
    )
    db.session.add(message)
    db.session.commit()
    
    emit('new_message', {
        'id': message.id,
        'sender_id': current_user.id,
        'sender_name': current_user.username,
        'recipient_id': int(recipient_id),
        'body': message_body,
        'timestamp': message.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    }, room=f'user_{recipient_id}')
    
    emit('new_message', {
        'id': message.id,
        'sender_id': current_user.id,
        'sender_name': current_user.username,
        'recipient_id': int(recipient_id),
        'body': message_body,
        'timestamp': message.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    })


@socketio.on('typing')
def handle_typing(data):
    recipient_id = data['recipient_id']
    emit('user_typing', {
        'user_id': current_user.id,
        'username': current_user.username
    }, room=f'user_{recipient_id}')


@socketio.on('stop_typing')
def handle_stop_typing(data):
    recipient_id = data['recipient_id']
    emit('user_stop_typing', {
        'user_id': current_user.id
    }, room=f'user_{recipient_id}')


# Profile routes
@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')


@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    username = request.form.get('username')
    email = request.form.get('email')
    status = request.form.get('status')
    
    if username != current_user.username:
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already taken')
            return redirect(url_for('profile'))
    
    if email != current_user.email:
        existing_email = User.query.filter_by(email=email).first()
        if existing_email:
            flash('Email already taken')
            return redirect(url_for('profile'))
    
    if 'profile_picture' in request.files:
        file = request.files['profile_picture']
        if file and file.filename != '' and allowed_image_file(file.filename):
            if current_user.profile_picture and current_user.profile_picture != 'default.png':
                old_filepath = os.path.join(app.config['PROFILE_PICTURE_FOLDER'], current_user.profile_picture)
                if os.path.exists(old_filepath):
                    os.remove(old_filepath)
            
            filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
            filepath = os.path.join(app.config['PROFILE_PICTURE_FOLDER'], filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            file.save(filepath)
            current_user.profile_picture = filename
    
    current_user.username = username
    current_user.email = email
    current_user.status = status
    db.session.commit()
    
    flash('Profile updated successfully')
    return redirect(url_for('profile'))


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not current_user.check_password(current_password):
            flash('Current password is incorrect')
            return redirect(url_for('profile'))
        
        if new_password != confirm_password:
            flash('New passwords do not match')
            return redirect(url_for('profile'))
        
        current_user.set_password(new_password)
        db.session.commit()
        
        flash('Password changed successfully')
        return redirect(url_for('profile'))
    
    return render_template('change_password.html')


@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    Message.query.filter_by(sender_id=current_user.id).delete()
    Message.query.filter_by(recipient_id=current_user.id).delete()
    
    if current_user.profile_picture and current_user.profile_picture != 'default.png':
        filepath = os.path.join(app.config['PROFILE_PICTURE_FOLDER'], current_user.profile_picture)
        if os.path.exists(filepath):
            os.remove(filepath)
    
    db.session.delete(current_user)
    db.session.commit()
    
    logout_user()
    flash('Your account has been deleted')
    return redirect(url_for('login'))


@app.route('/uploads/profile_pictures/<filename>')
@login_required
def uploaded_profile_picture(filename):
    return send_from_directory(app.config['PROFILE_PICTURE_FOLDER'], filename)


def allowed_image_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ['png', 'jpg', 'jpeg', 'gif']


if __name__ == '__main__':
    # Initialize database
    init_database()
    
    # Ensure directories exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['PROFILE_PICTURE_FOLDER'], exist_ok=True)
    
    # Run the application
    socketio.run(app, debug=True, host='0.0.0.0', port=10000)