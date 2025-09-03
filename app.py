from flask import Flask, render_template, request, jsonify
import uuid
import time
import threading
import json
from datetime import datetime

app = Flask(__name__)

# Lưu trữ các lệnh và kết quả
commands = {}
agents = {}
results = {}

class CommandStatus:
    PENDING = "pending"
    RUNNING = "running" 
    COMPLETED = "completed"
    FAILED = "failed"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/agents')
def get_agents():
    """Lấy danh sách agents đã kết nối"""
    current_time = time.time()
    active_agents = {}
    
    # Chỉ hiển thị agents còn hoạt động (ping trong vòng 30 giây)
    for agent_id, agent_info in agents.items():
        if current_time - agent_info['last_seen'] < 30:
            active_agents[agent_id] = agent_info
    
    return jsonify(active_agents)

@app.route('/api/agent/register', methods=['POST'])
def register_agent():
    """Agent đăng ký với server"""
    data = request.get_json()
    agent_id = data.get('agent_id', str(uuid.uuid4()))
    
    agents[agent_id] = {
        'id': agent_id,
        'hostname': data.get('hostname', 'unknown'),
        'platform': data.get('platform', 'unknown'),
        'last_seen': time.time(),
        'registered_at': datetime.now().isoformat()
    }
    
    return jsonify({'status': 'registered', 'agent_id': agent_id})

@app.route('/api/agent/<agent_id>/ping', methods=['POST'])
def agent_ping(agent_id):
    """Agent ping để duy trì kết nối"""
    if agent_id in agents:
        agents[agent_id]['last_seen'] = time.time()
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'not_found'}), 404

@app.route('/api/agent/<agent_id>/poll', methods=['GET'])
def poll_commands(agent_id):
    """Agent poll để lấy lệnh mới"""
    pending_commands = []
    
    for cmd_id, cmd_data in commands.items():
        if (cmd_data['agent_id'] == agent_id and 
            cmd_data['status'] == CommandStatus.PENDING):
            pending_commands.append({
                'command_id': cmd_id,
                'command': cmd_data['command'],
                'type': cmd_data['type']
            })
    
    return jsonify(pending_commands)

@app.route('/api/agent/<agent_id>/result', methods=['POST'])
def submit_result(agent_id):
    """Agent gửi kết quả về server"""
    data = request.get_json()
    command_id = data.get('command_id')
    
    if command_id in commands:
        commands[command_id]['status'] = data.get('status', CommandStatus.COMPLETED)
        commands[command_id]['output'] = data.get('output', '')
        commands[command_id]['error'] = data.get('error', '')
        commands[command_id]['completed_at'] = datetime.now().isoformat()
        
        return jsonify({'status': 'received'})
    
    return jsonify({'status': 'command_not_found'}), 404

@app.route('/api/command', methods=['POST'])
def send_command():
    """Gửi lệnh cho agent"""
    data = request.get_json()
    command = data.get('command', '').strip()
    agent_id = data.get('agent_id')
    command_type = data.get('type', 'execute')  # execute hoặc kill_all
    
    if not command and command_type != 'kill_all':
        return jsonify({'error': 'Command không được để trống'}), 400
    
    if not agent_id:
        return jsonify({'error': 'Agent ID không được để trống'}), 400
    
    command_id = str(uuid.uuid4())
    commands[command_id] = {
        'id': command_id,
        'agent_id': agent_id,
        'command': command,
        'type': command_type,
        'status': CommandStatus.PENDING,
        'created_at': datetime.now().isoformat(),
        'output': '',
        'error': ''
    }
    
    return jsonify({
        'status': 'sent', 
        'command_id': command_id,
        'message': f'Lệnh đã được gửi cho agent {agent_id}'
    })

@app.route('/api/commands')
def get_commands():
    """Lấy lịch sử các lệnh"""
    return jsonify(list(commands.values()))

@app.route('/api/command/<command_id>')
def get_command_result(command_id):
    """Lấy kết quả của một lệnh cụ thể"""
    if command_id in commands:
        return jsonify(commands[command_id])
    return jsonify({'error': 'Command not found'}), 404

@app.route('/api/clear', methods=['POST'])
def clear_history():
    """Xóa lịch sử lệnh"""
    global commands
    commands = {}
    return jsonify({'status': 'cleared'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)