import os
import sys
import tempfile
import random
import string
import requests
import subprocess
import threading
import time
from flask import Flask, send_file, request, jsonify
import socket

try:
    from zeroconf import Zeroconf, ServiceInfo
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "zeroconf"])
    from zeroconf import Zeroconf, ServiceInfo

# ===== CONFIG =====
PYTHON_UPDATE_URL = "https://raw.githubusercontent.com/YourUser/YourRepo/main/server.py"
HTML_UPDATE_URL = "https://raw.githubusercontent.com/YourUser/YourRepo/main/ui.html"
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
    startup_dir = os.path.join(os.getenv("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    target_path = os.path.join(startup_dir, os.path.basename(sys.argv[0]).replace(".py", ".pyw"))
    if not os.path.exists(target_path):
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(f'@echo off\nstart "" "{sys.executable}" "{os.path.realpath(sys.argv[0])}"\n')
        print(f"[INFO] Installed to startup: {target_path}")
    else:
        print("[INFO] Already installed in startup")

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
