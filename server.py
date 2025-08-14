from flask import Flask, send_file, request, jsonify, Response, stream_with_context, redirect
from logging.handlers import RotatingFileHandler
import pydirectinput
import subprocess
import threading
import tempfile
import requests
import argparse
import logging
import random
import string
import shutil
import socket
import locale
import time
import sys
import os

try:
    from zeroconf import Zeroconf, ServiceInfo
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "zeroconf"])
    from zeroconf import Zeroconf, ServiceInfo

# ===== CONFIG =====
PYTHON_UPDATE_URL = "https://raw.githubusercontent.com/KRWCLASSIC/Lantroller/refs/heads/main/server.py"
HTML_UPDATE_URL = "https://raw.githubusercontent.com/KRWCLASSIC/Lantroller/refs/heads/main/ui.html"
BACKEND_VERSION = "v8"
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

# Parse command line arguments
parser = argparse.ArgumentParser(description="Lantroller Backend Server")
parser.add_argument("--dev", action="store_true", help="Run in development mode")
parser.add_argument("--port", type=int, default=PORT, help=f"Port to run the server on (default: {PORT})")
args = parser.parse_args()

# Apply parsed arguments
if args.dev:
    HOSTNAME = "dev.local"
    logger.info("Running in development mode: hostname set to dev.local")
if args.port != PORT:
    PORT = args.port
    logger.info(f"Using custom port: {PORT}")

def _has_internet() -> bool:
    """Return True if the host appears to have Internet connectivity.

    Uses a fast DNS socket probe and falls back to an HTTP HEAD against
    our existing update endpoint.
    """
    try:
        # Fast, low-overhead connectivity probe (no TLS): DNS to Google
        socket.create_connection(("8.8.8.8", 53), timeout=2).close()
        return True
    except Exception:
        pass
    try:
        # Fallback: check reachability of the UI update host
        r = requests.head(HTML_UPDATE_URL, timeout=3)
        return r.status_code < 500
    except Exception:
        return False

def wait_for_internet():
    """Block until Internet is available.

    Logs periodic status so users can see why startup is paused.
    """
    if _has_internet():
        return
    logger.info("Waiting for Internet connectivity before starting services…")
    delay_seconds = 1.0
    max_delay = 5.0
    while not _has_internet():
        time.sleep(delay_seconds)
        delay_seconds = min(max_delay, delay_seconds + 0.5)
    logger.info("Internet connectivity detected. Continuing startup.")

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

def fetch_ui():
    global temp_html_path
    try:
        r = requests.get(HTML_UPDATE_URL, timeout=5)
        r.raise_for_status()
        
        # Read ui.html content from the response
        ui_html_content = r.text

        # Replace BACKEND_VERSION in ui_html_content
        ui_html_content = ui_html_content.replace("const BACKEND_VERSION = 'local';", f"const BACKEND_VERSION = '{BACKEND_VERSION}';")

        temp_name = "ui_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6)) + ".html"
        temp_html_path = os.path.join(tempfile.gettempdir(), temp_name)
        with open(temp_html_path, "w", encoding="utf-8") as f:
            f.write(ui_html_content)
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

def _kill_processes_windows(process_names, use_wildcard=False):
    results = {}
    creation = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    for name in process_names:
        try:
            # /T kills child processes, /F forces termination
            cmd = ["taskkill", "/IM", name, "/F", "/T"]
            if use_wildcard:
                # taskkill /IM supports wildcards directly
                pass
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creation,
                text=True,
                shell=False,
            )
            results[name] = {"returncode": completed.returncode, "output": completed.stdout}
        except Exception as e:
            results[name] = {"returncode": -1, "output": str(e)}
    return results

def kill_named_process_groups(group: str):
    group = (group or '').lower()
    browser_map = {
        "chrome": ["chrome.exe"],
        "edge": ["msedge.exe"],
        "opera": ["opera.exe"],
        "operagx": ["opera.exe"],
        "firefox": ["firefox.exe"],
        "brave": ["brave.exe"],
        "vivaldi": ["vivaldi.exe"],
        "chromium": ["chromium.exe"],
    }
    if group == "discord":
        results = _kill_processes_windows(["discord*"], use_wildcard=True)
        logger.info("Kill Discord requested")
        return {"killed": results}
    if group == "roblox":
        results = _kill_processes_windows(["roblox*"], use_wildcard=True)
        logger.info("Kill Roblox requested")
        return {"killed": results}
    if group == "steam":
        results = _kill_processes_windows(["steam*"], use_wildcard=True)
        logger.info("Kill Steam requested")
        return {"killed": results}
    if group == "all-browsers" or group == "all":
        names = sorted({n for arr in browser_map.values() for n in arr})
        results = _kill_processes_windows(names)
        logger.info("Kill all browsers requested")
        return {"killed": results}
    return {"error": f"Unknown group '{group}'"}, 400

@app.route("/localUI")
def local_ui():
    try:
        local_ui = os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "ui.html")
        if os.path.exists(local_ui):
            return send_file(local_ui)
    except Exception:
        pass
    return "Local UI not available", 404

@app.route("/ui")
def serve_ui():
    # Prefer fetched UI from temp path; if missing, redirect to dedicated local endpoint
    if temp_html_path and os.path.exists(temp_html_path):
        return send_file(temp_html_path)
    return redirect("/localUI")

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

@app.post("/logs/clear")
def clear_logs():
    """Truncate the log file to empty."""
    try:
        if os.path.exists(LOG_PATH):
            try:
                with open(LOG_PATH, 'r+', encoding='utf-8') as f:
                    f.truncate(0)
            except Exception:
                # Fallback if r+ fails
                with open(LOG_PATH, 'w', encoding='utf-8'):
                    pass
        return jsonify({"status": "cleared"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ===== Input simulation (Windows) =====
VK_MAP = {
    # Letters
    **{chr(c): c for c in range(0x41, 0x5B)},  # 'A'..'Z' -> 0x41..0x5A
    # Digits
    **{str(d): 0x30 + d for d in range(0, 10)},
    # Common keys
    'ENTER': 0x0D,
    'ESC': 0x1B,
    'SPACE': 0x20,
    'TAB': 0x09,
    'BACKSPACE': 0x08,
    'LEFT': 0x25,
    'UP': 0x26,
    'RIGHT': 0x27,
    'DOWN': 0x28,
    'SHIFT': 0x10,
    'CTRL': 0x11,
    'ALT': 0x12,
    'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73, 'F5': 0x74, 'F6': 0x75,
    'F7': 0x76, 'F8': 0x77, 'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
    'CAPSLOCK': 0x14,
}

def _key_event_windows(vk_code: int, is_down: bool):
    try:
        # pydirectinput works with key names, so we need to map vk_code back to key name
        # This mapping is incomplete and should be expanded if more keys are needed.
        key_name_map = {
            0x0D: 'enter',
            0x1B: 'esc',
            0x20: 'space',
            0x09: 'tab',
            0x08: 'backspace',
            0x25: 'left',
            0x26: 'up',
            0x27: 'right',
            0x28: 'down',
            0x10: 'shift',
            0x11: 'ctrl',
            0x12: 'alt',
            0x70: 'f1', 0x71: 'f2', 0x72: 'f3', 0x73: 'f4', 0x74: 'f5', 0x75: 'f6',
            0x76: 'f7', 0x77: 'f8', 0x78: 'f9', 0x79: 'f10', 0x7A: 'f11', 0x7B: 'f12',
            0x14: 'capslock',
            # Add letters A-Z
            **{v: chr(v).lower() for k, v in VK_MAP.items() if len(k) == 1 and k.isalpha()},
            # Add digits 0-9
            **{v: k for k, v in VK_MAP.items() if len(k) == 1 and k.isdigit()},
        }
        key_to_send = key_name_map.get(vk_code)
        if key_to_send:
            if is_down:
                pydirectinput.keyDown(key_to_send)
            else:
                pydirectinput.keyUp(key_to_send)
            logger.info(f"Sent key event: {key_to_send} { 'down' if is_down else 'up'}")
        else:
            logger.warning(f"No pydirectinput mapping for VK code: {vk_code}")
    except Exception as e:
        logger.error(f"pydirectinput key event failed vk={vk_code} down={is_down}: {e}")

def _mouse_move_by_windows(dx: int, dy: int):
    try:
        pydirectinput.moveRel(int(dx), int(dy), relative=True)
        logger.info(f"Mouse moved by dx={dx}, dy={dy}")
    except Exception as e:
        logger.error(f"pydirectinput mouse move failed dx={dx} dy={dy}: {e}")

def _mouse_button_windows(button: str, is_down: bool):
    try:
        if is_down:
            pydirectinput.mouseDown(button=button)
        else:
            pydirectinput.mouseUp(button=button)
        logger.info(f"Mouse button event: {button} { 'down' if is_down else 'up'}")
    except Exception as e:
        logger.error(f"pydirectinput mouse button failed button={button} down={is_down}: {e}")

def _mouse_wheel_windows(delta: int):
    try:
        # pydirectinput scroll takes positive for up, negative for down
        pydirectinput.scroll(int(delta))
        logger.info(f"Mouse wheel scrolled by {delta}")
    except Exception as e:
        logger.error(f"pydirectinput mouse wheel failed delta={delta}: {e}")

@app.post("/input/key")
def input_key():
    data = request.get_json(silent=True) or {}
    key = (data.get("key") or "").upper()
    event_type = (data.get("event") or "").lower()  # 'down' or 'up'
    if not key or event_type not in ("down", "up"):
        return jsonify({"error": "Provide 'key' and event in {'down','up'}"}), 400
    if os.name != 'nt':
        return jsonify({"error": "Key input only implemented for Windows"}), 400
    vk = VK_MAP.get(key)
    if vk is None:
        return jsonify({"error": f"Unsupported key '{key}'"}), 400
    is_down = event_type == 'down'
    threading.Thread(target=_key_event_windows, args=(vk, is_down), daemon=True).start()
    return jsonify({"status": "ok"})

@app.post("/input/mouse/move")
def input_mouse_move():
    data = request.get_json(silent=True) or {}
    dx = int(data.get("dx") or 0)
    dy = int(data.get("dy") or 0)
    if os.name != 'nt':
        return jsonify({"error": "Mouse move only implemented for Windows"}), 400
    threading.Thread(target=_mouse_move_by_windows, args=(dx, dy), daemon=True).start()
    return jsonify({"status": "ok"})

@app.post("/input/mouse/button")
def input_mouse_button():
    data = request.get_json(silent=True) or {}
    button = (data.get("button") or "").lower()  # left/right/middle
    event_type = (data.get("event") or "").lower()  # down/up
    if button not in ("left", "right", "middle") or event_type not in ("down", "up"):
        return jsonify({"error": "Provide 'button' in {'left','right','middle'} and event in {'down','up'}"}), 400
    if os.name != 'nt':
        return jsonify({"error": "Mouse button only implemented for Windows"}), 400
    is_down = event_type == 'down'
    threading.Thread(target=_mouse_button_windows, args=(button, is_down), daemon=True).start()
    return jsonify({"status": "ok"})

@app.post("/input/mouse/wheel")
def input_mouse_wheel():
    data = request.get_json(silent=True) or {}
    if os.name != 'nt':
        return jsonify({"error": "Mouse wheel only implemented for Windows"}), 400
    # Accept either explicit delta (device units) or logical notches (+/-1 per wheel click)
    delta = data.get("delta")
    notches = data.get("notches")
    direction = (data.get("dir") or "").lower()  # optional: 'up' or 'down'
    try:
        if delta is None:
            if notches is not None:
                delta = int(notches) * 120
            elif direction in ("up", "down"):
                delta = 120 if direction == "up" else -120
            else:
                delta = 120
        delta = int(delta)
        # Clamp to avoid extreme values
        if delta > 120 * 10:
            delta = 120 * 10
        if delta < -120 * 10:
            delta = -120 * 10
    except Exception:
        return jsonify({"error": "Invalid wheel delta/notches"}), 400
    threading.Thread(target=_mouse_wheel_windows, args=(delta,), daemon=True).start()
    return jsonify({"status": "ok", "delta": delta})

@app.route("/kill/discord")
def kill_discord():
    payload, status = kill_named_process_groups("discord"), 200
    # kill_named_process_groups can return (dict, 400)
    if isinstance(payload, tuple):
        payload, status = payload
    return jsonify(payload), status

@app.route("/kill/roblox")
def kill_roblox():
    payload, status = kill_named_process_groups("roblox"), 200
    if isinstance(payload, tuple):
        payload, status = payload
    return jsonify(payload), status

@app.route("/kill/steam")
def kill_steam():
    payload, status = kill_named_process_groups("steam"), 200
    if isinstance(payload, tuple):
        payload, status = payload
    return jsonify(payload), status

@app.route("/kill/browser")
def kill_browser():
    name = request.args.get("name", "").lower()
    # support name=all or all-browsers
    group = "all-browsers" if name in ("all", "all-browsers") else name
    payload, status = kill_named_process_groups(group), 200
    if isinstance(payload, tuple):
        payload, status = payload
    return jsonify(payload), status

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
        # install_startup() is removed, so we exit if --install is passed.
        # The install logic is now expected to be handled by install.bat
        sys.exit(0)
    # Wait for network so we can fetch UI and register services reliably
    wait_for_internet()
    fetch_ui()
    threading.Thread(target=register_mdns, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
