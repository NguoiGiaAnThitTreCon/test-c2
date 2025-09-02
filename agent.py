import os
import time
import socketio

# URL server WebSocket trên Render
SERVER = os.getenv("CONTROL_SERVER", "https://tenapp.onrender.com")

# Agent ID mặc định = tên máy trong Codespaces (hoặc env AGENT_ID nếu có)
AGENT_ID = os.getenv("AGENT_ID", os.uname().nodename)

sio = socketio.Client()


@sio.event
def connect():
    print(f"[{AGENT_ID}] Connected to server {SERVER}")
    sio.emit("register", {"agent_id": AGENT_ID})


@sio.on("server_message")
def on_server_message(data):
    print(f"[{AGENT_ID}] Server:", data)


@sio.on("command")
def on_command(data):
    cmd = data.get("cmd")
    print(f"[{AGENT_ID}] Received command: {cmd}")
    # Demo: chỉ báo về server là đã nhận (bạn có thể thay bằng subprocess để chạy lệnh thật)
    sio.emit("agent_log", {"agent_id": AGENT_ID, "message": f"Executed: {cmd}"})


@sio.event
def disconnect():
    print(f"[{AGENT_ID}] Disconnected from server")


if __name__ == "__main__":
    while True:
        try:
            sio.connect(SERVER, transports=["websocket"])
            sio.wait()
        except Exception as e:
            print(f"[{AGENT_ID}] Connection error: {e}, retrying in 5s")
            time.sleep(5)
