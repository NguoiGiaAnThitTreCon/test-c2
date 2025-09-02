import os
import time
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")  # dùng ENV trên Render
socketio = SocketIO(app, cors_allowed_origins="*")

ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")

# Lưu agent_id -> sid
connected_agents = {}
logs = []


# ----------------- AUTH -----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASS:
            session["logged_in"] = True
            flash("Login successful", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid password", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("logged_in"):
            return f(*args, **kwargs)
        return redirect(url_for("login"))
    return decorated


# ----------------- DASHBOARD -----------------
@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html")


# ----------------- API -----------------
@app.route("/send", methods=["POST"])
@login_required
def send_command():
    payload = request.json
    agent = payload.get("agent")
    cmd = payload.get("cmd")
    if not cmd:
        return jsonify({"status": "error", "message": "Empty command"}), 400

    if agent == "all":
        for sid in connected_agents.values():
            socketio.emit("command", {"cmd": cmd}, to=sid)
        logs.append(f"[SERVER] broadcast command: {cmd}")
        return jsonify({"status": "success", "message": "Sent to all agents"})
    else:
        sid = connected_agents.get(agent)
        if not sid:
            return jsonify({"status": "error", "message": "Agent not connected"}), 404
        socketio.emit("command", {"cmd": cmd}, to=sid)
        logs.append(f"[SERVER] sent command to {agent}: {cmd}")
        return jsonify({"status": "success", "message": f"Sent to {agent}"})


@app.route("/logs")
@login_required
def get_logs():
    return jsonify([{
        "timestamp": time.strftime("%H:%M:%S"),
        "type": "info",
        "message": m
    } for m in reversed(logs[-100:])])


# ----------------- SOCKET.IO -----------------
@socketio.on("connect")
def handle_connect():
    print("New socket connected:", request.sid)


@socketio.on("register")
def handle_register(data):
    agent_id = data.get("agent_id", f"agent-{request.sid}")
    connected_agents[agent_id] = request.sid
    logs.append(f"[SYSTEM] Agent {agent_id} registered")
    emit("server_message", {"msg": f"Welcome, {agent_id}"})
    print(f"Agent {agent_id} registered with sid {request.sid}")


@socketio.on("agent_log")
def handle_agent_log(data):
    msg = data.get("message", "")
    agent_id = data.get("agent_id", request.sid)
    logs.append(f"[{agent_id}] {msg}")
    print(f"Log from {agent_id}: {msg}")


@socketio.on("disconnect")
def handle_disconnect():
    # Tìm agent_id theo sid
    to_remove = [aid for aid, sid in connected_agents.items() if sid == request.sid]
    for aid in to_remove:
        connected_agents.pop(aid, None)
        logs.append(f"[SYSTEM] Agent {aid} disconnected")
        print(f"Agent {aid} disconnected")


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
