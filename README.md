# Phone to Cursor

**English** | [中文](README_zh.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-blue.svg)]()
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-yellow.svg)]()

A lightweight Windows utility: **mobile browser → same Wi‑Fi LAN → auto‑paste into Cursor, Codex, or ChatGPT**.

Built for voice typing on your phone while coding or chatting on the desktop. No mobile app required—just open a page in the browser.

---

## Features

- **No mobile app install** — start the service on PC, open the LAN URL on your phone
- **Multiple targets** — Cursor, Codex, ChatGPT, or a custom window title keyword
- **Focus + paste** — optional focus hotkeys (Ctrl+L / Ctrl+I), auto Enter / Ctrl+Enter after paste
- **System tray + autostart** — runs in the background
- **Single instance** — avoids port conflicts
- **Persistent config** — saved to `phone_bridge_config.json` next to the executable

---

## Quick start

### Option 1: Download a release (recommended)

1. Download `PhoneToCursor.exe` from [Releases](../../releases)
2. Run it and allow **Private network** access in Windows Firewall
3. Connect phone and PC to the **same Wi‑Fi**
4. Open the URL shown in the app (e.g. `http://192.168.1.10:8765`) on your phone
5. Click the chat input in Cursor (or rely on auto‑focus)
6. Type or dictate on the phone, then tap **Send**

Optional: enable **Auto send after paste**.

### Option 2: Run from source

```powershell
git clone https://github.com/cxzlx/cursor-phone-bridge.git
cd cursor-phone-bridge
python -m pip install -r requirements.txt
python main.py
```

### Build executable

```powershell
python -m PyInstaller --noconfirm phone_bridge.spec
# Output: dist/PhoneToCursor.exe
```

---

## How it works

```
┌─────────────┐     same Wi‑Fi      ┌──────────────────┐    clipboard+keys   ┌─────────┐
│ Mobile web  │ ── HTTP POST ──▶   │  Windows service │ ── paste to target ─▶ │ Cursor  │
│ voice/text  │      :8765         │  (this app)      │                     │ Codex…  │
└─────────────┘                    └──────────────────┘                     └─────────┘
```

---

## Configuration

| Setting | Description |
|---------|-------------|
| Target app | Preset or custom window title keyword |
| Send key | Enter / Ctrl+Enter / none |
| Focus hotkey | Ctrl+L (chat) / Ctrl+I (Composer) / none |
| Launch path | Optional `.exe` or shortcut to start the target app |

Config file: `phone_bridge_config.json` (created on first run).

---

## Security

- Listens on `0.0.0.0:8765` — any device on the **same LAN** can reach it
- **No authentication** — do not leave running on untrusted public Wi‑Fi
- Traffic stays on the local network; no third‑party relay server
- If paste lands in the wrong window, click the target input first

---

## Tech stack

- Python 3.11+
- CustomTkinter (UI)
- stdlib `http.server` (LAN web UI)
- Win32 APIs (window focus, clipboard, key simulation)
- PyInstaller

---

## FAQ

**Phone cannot open the page?**  
Same Wi‑Fi, firewall allowed, antivirus not blocking.

**Wrong window receives paste?**  
Focus the input manually or adjust window title keyword / focus hotkey.

**Conflict with Reminder Doc?**  
No — separate apps, ports, and responsibilities.

---

## License

[MIT](LICENSE)

## Author

[cxzlx](https://github.com/cxzlx)

Issues and PRs welcome.
