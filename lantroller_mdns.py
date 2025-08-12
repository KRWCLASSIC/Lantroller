# This script resolves IP adresses of controlled.local mdns for mobile devices, returns usable link
# Android seems to not support mdns on browsers...

# lantroller_mdns.py
from zeroconf import Zeroconf, ServiceBrowser
import socket
import time

TARGET_NAME = "controlled.local"

class MDNSListener:
    def __init__(self):
        self.ip = None

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            host = info.server.rstrip('.')
            if host.lower() == TARGET_NAME.lower():
                try:
                    self.ip = socket.inet_ntoa(info.addresses[0])
                except Exception:
                    pass

    def remove_service(self, zeroconf, type, name):
        pass  # No removal logic needed

if __name__ == "__main__":
    zeroconf = Zeroconf()
    listener = MDNSListener()

    ServiceBrowser(zeroconf, "_http._tcp.local.", listener)

    print(f"Scanning for {TARGET_NAME}...\n")
    time.sleep(3)  # wait for discovery

    if listener.ip:
        print(f"http://{listener.ip}:5000/ui")
    else:
        print(f"{TARGET_NAME} not found.")

    zeroconf.close()
