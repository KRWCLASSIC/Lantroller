# Lantroller

![UI Version](https://img.shields.io/badge/UI%20Version-v8-red)
![Backend Version](https://img.shields.io/badge/Backend%20Version-v9--fix-green)

LAN Remote Administration Tool aimed for trolling.

For now entirely undetected by any antivirus software.

> Why is it undetected? Everything is done via http requests, even Live command execution - this doesn't trigger any antivirus software but makes command execution pretty bad - no "live" output and shell stuff.
> If you happen to run shell/live based tools - run "Restart Server" option.
> Note that scripts will most likely not work at all.
> And last but not least: Output is sent once command finishes execution, so you need to wait for things like `pip install` to finish.

## Features

- mDNS access via `http://controlled.local:5000/ui` (for Android devices there's also [mDNS helper script](https://github.com/KRWCLASSIC/Lantroller/blob/main/lantroller_mdns.py) that will return usable link without mDNS)
- App Killers (Quick shortcuts)
- Power actions
- Semi-live command execution
- Live key down/up simulation
- Touchpad
- Mini keyboard
- Restart Server
- In-app updates for UI and Backend
- Last resort options like stop and self-destruct

## TODO

- Rewrite UI
- Some way for real SSH (paramiko? external ssh executable? idk)
- Lan-less mode (ngrok? unsafe, selfhosted reverse proxies too...)

## Important Note

Please use this tool responsibly and only with explicit consent from the target user. This software is intended for legitimate remote administration and troubleshooting purposes only. Any unauthorized or malicious use is strictly prohibited and may violate local laws and regulations.

## License

This project is licensed under the KRW LICENSE v1. Please see the [LICENSE](LICENSE) file for full details.
