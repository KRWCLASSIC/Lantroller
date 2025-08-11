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
import logging
from logging.handlers import RotatingFileHandler

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
LOG_PATH = os.path.join(tempfile.gettempdir(), "lantroller.log")

# Configure rotating file logging in temp
logger = logging.getLogger("lantroller")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    _handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(_handler)

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

def launch_windowless_with_python_and_exit(extra_args=None):
    """Launch the script in a windowless way on Windows (pythonw or CREATE_NO_WINDOW) and exit.

    On non-Windows platforms, falls back to in-PATH python relaunch.
    """
    if extra_args is None:
        extra_args = []
    script_path = os.path.realpath(sys.argv[0])
    if os.name == 'nt':
        try:
            pythonw_exe, argv = resolve_pythonw_invocation(script_path)
            cmd = argv + list(extra_args)
            creation = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            subprocess.Popen(cmd, creationflags=creation, close_fds=True)
        except Exception:
            # Fallback to PATH python but request no window
            python_cmd = shutil.which('python') or 'python'
            cmd = [python_cmd, script_path] + list(extra_args)
            creation = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            subprocess.Popen(cmd, creationflags=creation, close_fds=True)
        finally:
            os._exit(0)
    else:
        launch_with_path_python_and_exit(extra_args)

def fetch_ui():
    global temp_html_path
    try:
        r = requests.get(HTML_UPDATE_URL, timeout=5)
        r.raise_for_status()
        temp_name = "ui_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6)) + ".html"
        temp_html_path = os.path.join(tempfile.gettempdir(), temp_name)
        with open(temp_html_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        logger.info(f"UI fetched to {temp_html_path}")
    except Exception as e:
        logger.error(f"Failed to fetch UI: {e}")

def update_self():
    try:
        r = requests.get(PYTHON_UPDATE_URL, timeout=5)
        r.raise_for_status()
        script_path = os.path.realpath(sys.argv[0])
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        logger.info("Backend updated, restarting...")
        # Relaunch windowless (pythonw/NO_WINDOW on Windows)
        launch_windowless_with_python_and_exit(sys.argv[1:])
    except Exception as e:
        logger.error(f"Update failed: {e}")
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
        logger.info(f"Action exec: {cmd}")
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
            logger.info(f"Live exec: {cmd}")
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

@app.get("/logs")
def get_logs():
    """Return the last N lines of the log file as text/plain.
    Query param: tail (int) default 500
    """
    tail = request.args.get('tail', default=500, type=int)
    tail = max(1, min(tail or 500, 5000))
    try:
        if not os.path.exists(LOG_PATH):
            return Response("<no logs yet>\n", mimetype="text/plain")
        with open(LOG_PATH, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        text = ''.join(lines[-tail:])
        return Response(text, mimetype="text/plain")
    except Exception as e:
        return Response(f"Error reading logs: {e}\n", mimetype="text/plain", status=500)

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
            launch_windowless_with_python_and_exit(sys.argv[1:])
        except Exception as e:
            logger.error(f"Restart failed: {e}")
    threading.Thread(target=_restart).start()
    return jsonify({"status": "Restarting server..."})

@app.route("/stop")
def stop():
    logger.info("Stop requested via /stop")
    def _stop():
        time.sleep(0.2)
        os._exit(0)
    threading.Thread(target=_stop).start()
    return jsonify({"status": "Stopping server..."})

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
        logger.info(f"Requested creation of elevated scheduled task '{task_name}'.")
        logger.info("If you accepted the UAC prompt, the task will run with highest privileges on logon.")

        # Try to start the task immediately so it activates without reboot/logon
        try:
            time.sleep(0.5)
            schtasks_run_args = f'/Run /TN {quote_arg(task_name)}'
            rc_run = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "schtasks.exe",
                schtasks_run_args,
                None,
                1,
            )
            if rc_run <= 32:
                logger.warning(f"Could not start scheduled task now (code {rc_run}). It will run on next logon.")
            else:
                logger.info("Scheduled task started successfully.")
        except Exception as e:
            logger.warning(f"Failed to start scheduled task immediately: {e}")
        return
    except Exception as e:
        logger.warning(f"Could not create elevated scheduled task (maybe UAC declined): {e}")
        logger.warning("Falling back to per-user Startup shortcut (not elevated).")

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
    logger.info(f"Installed non-elevated startup launcher: {vbs_path}")

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
    logger.info(f"mDNS registered as {HOSTNAME}:{PORT}")

if __name__ == "__main__":
    if "--install" in sys.argv:
        install_startup()
        sys.exit(0)
    fetch_ui()
    threading.Thread(target=register_mdns, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
