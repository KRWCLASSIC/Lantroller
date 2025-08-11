import os
import sys
import tempfile
import random
import string
import requests
import subprocess
import threading
import time
import ctypes
from flask import Flask, send_file, request, jsonify, Response, stream_with_context
import socket

try:
    from zeroconf import Zeroconf, ServiceInfo
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "zeroconf"])
    from zeroconf import Zeroconf, ServiceInfo

# ===== CONFIG =====
PYTHON_UPDATE_URL = "https://raw.githubusercontent.com/KRWCLASSIC/Lantroller/refs/heads/main/server.py"
HTML_UPDATE_URL = "https://raw.githubusercontent.com/KRWCLASSIC/Lantroller/refs/heads/main/ui.html"
HOSTNAME = "controlled.local"
PORT = 5000
# ==================

app = Flask(__name__)
temp_html_path = None

def fetch_ui():
    global temp_html_path
    try:
        r = requests.get(HTML_UPDATE_URL, timeout=5)
        r.raise_for_status()
        temp_name = "ui_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6)) + ".html"
        temp_html_path = os.path.join(tempfile.gettempdir(), temp_name)
        with open(temp_html_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"[INFO] UI fetched to {temp_html_path}")
    except Exception as e:
        print(f"[ERROR] Failed to fetch UI: {e}")

def update_self():
    try:
        r = requests.get(PYTHON_UPDATE_URL, timeout=5)
        r.raise_for_status()
        script_path = os.path.realpath(sys.argv[0])
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        print("[INFO] Backend updated, restarting...")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        return f"Update failed: {e}"

@app.route("/ui")
def serve_ui():
    if temp_html_path and os.path.exists(temp_html_path):
        return send_file(temp_html_path)
    return "UI not fetched", 500

@app.route("/actions")
def actions():
    cmd = request.args.get("cmd")
    if not cmd:
        return jsonify({"error": "No command provided"}), 400
    try:
        subprocess.Popen(cmd, shell=True)
        return jsonify({"status": f"Executed: {cmd}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/exec")
def exec_stream():
    data = request.get_json(silent=True) or {}
    cmd = data.get("cmd")
    if not cmd:
        return jsonify({"error": "No command provided"}), 400

    def generate():
        try:
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
            )
            for line in iter(process.stdout.readline, ''):
                yield line
            process.stdout.close()
            return_code = process.wait()
            yield f"\n[Process exited with code {return_code}]\n"
        except Exception as e:
            yield f"ERROR: {str(e)}\n"

    return Response(stream_with_context(generate()), mimetype="text/plain")

@app.route("/refetch-ui")
def refetch_ui():
    fetch_ui()
    return jsonify({"status": "UI refetched"})

@app.route("/update")
def update():
    threading.Thread(target=update_self).start()
    return jsonify({"status": "Updating backend..."})

@app.route("/restart")
def restart():
    threading.Thread(target=lambda: (time.sleep(1), os.execv(sys.executable, [sys.executable] + sys.argv))).start()
    return jsonify({"status": "Restarting server..."})

def install_startup():
    """Install app to run on logon with highest privileges via Scheduled Task.

    Attempts to create a Windows Scheduled Task with RunLevel=Highest.
    If elevation is declined, falls back to a Startup folder .bat.
    """
    python_executable = sys.executable
    script_path = os.path.realpath(sys.argv[0])
    task_name = "Lantroller"

    # Prepare elevated call to schtasks
    run_cmd = f'"{python_executable}" "{script_path}"'
    schtasks_args = f'/Create /TN "{task_name}" /TR "{run_cmd}" /SC ONLOGON /RL HIGHEST /F'

    try:
        # Trigger UAC prompt to run schtasks elevated
        # ShellExecuteW returns >32 on success
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "schtasks.exe",
            schtasks_args,
            None,
            1,
        )
        if rc <= 32:
            raise RuntimeError(f"ShellExecuteW failed with code {rc}")
        print(f"[INFO] Requested creation of elevated scheduled task '{task_name}'.")
        print("[INFO] If you accepted the UAC prompt, the task will run with highest privileges on logon.")
        return
    except Exception as e:
        print(f"[WARN] Could not create elevated scheduled task (maybe UAC declined): {e}")
        print("[WARN] Falling back to per-user Startup shortcut (not elevated).")

    # Fallback: non-elevated Startup folder .bat launcher
    startup_dir = os.path.join(os.getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    os.makedirs(startup_dir, exist_ok=True)
    target_path = os.path.join(startup_dir, os.path.basename(sys.argv[0]).replace(".py", ".bat"))
    if not os.path.exists(target_path):
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(f"@echo off\nstart \"\" \"{python_executable}\" \"{script_path}\"\n")
        print(f"[INFO] Installed non-elevated startup launcher: {target_path}")
    else:
        print("[INFO] Non-elevated startup launcher already present")

def register_mdns():
    zeroconf = Zeroconf()
    ip_bytes = socket.inet_aton(socket.gethostbyname(socket.gethostname()))
    info = ServiceInfo(
        "_http._tcp.local.",
        f"{HOSTNAME}._http._tcp.local.",
        addresses=[ip_bytes],
        port=PORT,
        properties={},
        server=f"{HOSTNAME}."
    )
    zeroconf.register_service(info)
    print(f"[INFO] mDNS registered as {HOSTNAME}:{PORT}")

if __name__ == "__main__":
    if "--install" in sys.argv:
        install_startup()
        sys.exit(0)
    fetch_ui()
    threading.Thread(target=register_mdns, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
