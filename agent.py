import os
import time
import socketio

SERVER = os.getenv("CONTROL_SERVER", "https://your-app.onrender.com")
AGENT_ID = os.getenv("AGENT_ID", "agent-demo")

sio = socketio.Client()

@sio.event
def connect():
    print("Connected to server")
    sio.emit("register", {"agent_id": AGENT_ID})

@sio.on("server_message")
def on_server_message(data):
    print("Server:", data)

@sio.on("command")
def on_command(data):
    cmd = data.get("cmd")
    print(f"[Agent {AGENT_ID}] Received command:", cmd)
    # ở đây demo: chỉ log lại
    sio.emit("agent_log", {"agent_id": AGENT_ID, "message": f"Executed: {cmd}"})
    # nếu muốn thực thi thật thì bạn tự thay bằng subprocess như code cũ

@sio.event
def disconnect():
    print("Disconnected from server")

if __name__ == "__main__":
    while True:
        try:
            sio.connect(SERVER, transports=["websocket"])
            sio.wait()
        except Exception as e:
            print("Connection error:", e)
            time.sleep(5)
