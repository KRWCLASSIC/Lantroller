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
import shutil
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

def _file_exists(path: str) -> bool:
    try:
        return path and os.path.exists(path)
    except Exception:
        return False

def resolve_python_invocation(script_path: str):
    """Return (exe, args_list) choosing a robust Python runtime.

    Prefers 'py -3' on Windows, then sys.executable if it exists,
    then 'python3' or 'python' from PATH.
    args_list always includes the executable/program name as argv[0].
    """
    # 1) Prefer 'py' launcher if present
    py_launcher = shutil.which('py')
    if py_launcher:
        return (py_launcher, [py_launcher, '-3', script_path])

    # 2) sys.executable if it exists
    if _file_exists(sys.executable):
        return (sys.executable, [sys.executable, script_path])

    # 3) PATH fallbacks
    for name in ('python3', 'python'):
        found = shutil.which(name)
        if found:
            return (found, [found, script_path])

    # 4) Last resort: try direct call, will likely fail
    return ('python', ['python', script_path])

def quote_arg(arg: str) -> str:
    if not arg:
        return '""'
    if ' ' in arg or '"' in arg or '\\' in arg:
        # naive safe quoting for Task Scheduler command line
        return '"' + arg.replace('"', '\\"') + '"'
    return arg

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
        exe, base_args = resolve_python_invocation(script_path)
        # preserve any original CLI args beyond the script path
        extra_args = sys.argv[1:]
        argv = base_args + extra_args
        if os.name == 'nt' and os.path.splitext(exe)[1].lower() == '.exe':
            os.execv(exe, argv)
        else:
            # Use PATH lookup for non-absolute executables like 'py' or 'python'
            os.execvp(exe, argv)
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
    def _restart():
        time.sleep(1)
        exe, base_args = resolve_python_invocation(os.path.realpath(sys.argv[0]))
        argv = base_args + sys.argv[1:]
        try:
            if os.name == 'nt' and os.path.splitext(exe)[1].lower() == '.exe':
                os.execv(exe, argv)
            else:
                os.execvp(exe, argv)
        except Exception as e:
            print(f"[ERROR] Restart failed: {e}")
    threading.Thread(target=_restart).start()
    return jsonify({"status": "Restarting server..."})

def install_startup():
    """Install app to run on logon with highest privileges via Scheduled Task.

    Attempts to create a Windows Scheduled Task with RunLevel=Highest.
    If elevation is declined, falls back to a Startup folder .bat.
    """
    script_path = os.path.realpath(sys.argv[0])
    task_name = "Lantroller"

    # Prepare elevated call to schtasks with robust Python invocation
    exe, base_args = resolve_python_invocation(script_path)
    cmd_line = ' '.join(quote_arg(a) for a in base_args)
    schtasks_args = f'/Create /TN {quote_arg(task_name)} /TR {quote_arg(cmd_line)} /SC ONLOGON /RL HIGHEST /F'

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
    exe, base_args = resolve_python_invocation(script_path)
    bat_line = ' '.join(quote_arg(a) for a in base_args)
    if not os.path.exists(target_path):
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("@echo off\n")
            f.write(f"start \"\" {bat_line}\n")
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
