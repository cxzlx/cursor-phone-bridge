"""Phone voice/text over LAN → paste into Cursor / Codex / ChatGPT."""

from __future__ import annotations

import ctypes
import html
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

PORT = 8765
MUTEX_NAME = "Local\\CursorPhoneBridge_SingleInstance"
ERROR_ALREADY_EXISTS = 183
APP_TITLE = "Phone to Cursor"

SELF_TITLES = (APP_TITLE, "PhoneToCursor", "Phone to Cursor", "手机传 Cursor")

PRESETS: dict[str, dict] = {
    "Cursor": {
        "label": "Cursor",
        "keywords": ["Cursor"],
        "send_key": "enter",
        "focus_hotkey": "none",  # 项目窗口里 Ctrl+L 容易跑偏，默认不按
        "exe_names": ["Cursor.exe"],
        "app_ids": ["Anysphere.Cursor"],
        "lnk_names": ["Cursor.lnk"],
    },
    "Codex": {
        "label": "Codex",
        "keywords": ["Codex"],
        "send_key": "enter",
        "focus_hotkey": "none",
        "exe_names": ["Codex.exe"],
        "app_ids": [],
        "app_name_hints": ["Codex", "ChatGPT"],
        "lnk_names": ["Codex.lnk", "ChatGPT.lnk"],
    },
    "ChatGPT": {
        "label": "ChatGPT",
        "keywords": ["ChatGPT"],
        "send_key": "enter",
        "focus_hotkey": "none",
        "exe_names": ["ChatGPT.exe"],
        "app_ids": [],
        "app_name_hints": ["ChatGPT", "Codex"],
        "lnk_names": ["ChatGPT.lnk", "Codex.lnk"],
    },
    "custom": {"label": "Custom", "keywords": [], "send_key": "enter", "focus_hotkey": "none"},
}

SEND_KEY_OPTIONS = {
    "enter": "Enter",
    "ctrl_enter": "Ctrl+Enter",
    "none": "Do not auto-send",
}

FOCUS_HOTKEY_OPTIONS = {
    "ctrl_l": "Ctrl+L (Cursor chat)",
    "ctrl_i": "Ctrl+I (Cursor Composer)",
    "none": "No focus hotkey",
}

_mutex = None
_ui_root = None
paste_queue: queue.Queue = queue.Queue()
last_status = "Waiting for phone…"
_start_apps_cache: dict[str, str] | None = None

# 运行时目标配置（GUI / 配置文件可改）
runtime_cfg: dict = {
    "target": "Cursor",
    "custom_keyword": "",
    "send_key": "enter",
    "focus_hotkey": "none",
    "auto_send_default": True,
    "auto_launch": False,
    "launch_paths": {
        "Cursor": "",
        "Codex": "",
        "ChatGPT": "",
        "custom": "",
    },
}


def _default_launch_paths() -> dict[str, str]:
    return {"Cursor": "", "Codex": "", "ChatGPT": "", "custom": ""}


def normalize_launch_paths(raw) -> dict[str, str]:
    paths = _default_launch_paths()
    if isinstance(raw, dict):
        for key in paths:
            paths[key] = str(raw.get(key) or "").strip()
    return paths


def current_launch_path() -> str:
    tid = runtime_cfg.get("target", "Cursor")
    paths = runtime_cfg.get("launch_paths") or {}
    if isinstance(paths, dict):
        return str(paths.get(tid) or "").strip()
    return ""


def set_current_launch_path(path: str) -> None:
    tid = runtime_cfg.get("target", "Cursor")
    paths = runtime_cfg.setdefault("launch_paths", _default_launch_paths())
    if not isinstance(paths, dict):
        paths = _default_launch_paths()
        runtime_cfg["launch_paths"] = paths
    paths[tid] = (path or "").strip()


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_path() -> Path:
    return app_dir() / "phone_bridge_config.json"


def load_config() -> dict:
    path = config_path()
    data = {
        "target": "Cursor",
        "custom_keyword": "",
        "send_key": "enter",
        "focus_hotkey": "none",
        "auto_send_default": True,
        "auto_launch": False,
        "launch_paths": _default_launch_paths(),
    }
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception:  # noqa: BLE001
            pass
    if data.get("target") not in PRESETS:
        data["target"] = "Cursor"
    if data.get("send_key") not in SEND_KEY_OPTIONS:
        data["send_key"] = "enter"
    if data.get("focus_hotkey") not in FOCUS_HOTKEY_OPTIONS:
        # 跟随预设默认
        tid = data["target"]
        data["focus_hotkey"] = PRESETS.get(tid, {}).get("focus_hotkey", "none")
        if data["focus_hotkey"] not in FOCUS_HOTKEY_OPTIONS:
            data["focus_hotkey"] = "none"
    data["custom_keyword"] = str(data.get("custom_keyword") or "")
    data["auto_send_default"] = bool(data.get("auto_send_default", True))
    # 项目文件夹模式下 Ctrl+L 常把焦点带偏，统一默认关闭（用户可手动再开）
    if data.get("focus_hotkey") == "ctrl_l":
        data["focus_hotkey"] = "none"
    data["auto_launch"] = bool(data.get("auto_launch", False))
    paths = normalize_launch_paths(data.get("launch_paths"))
    old = str(data.get("launch_path") or "").strip()
    if old and not paths.get(data["target"]):
        paths[data["target"]] = old
    data["launch_paths"] = paths
    return data


def save_config(cfg: dict | None = None) -> None:
    data = cfg if cfg is not None else runtime_cfg
    path = config_path()
    path.write_text(
        json.dumps(
            {
                "target": data.get("target", "Cursor"),
                "custom_keyword": data.get("custom_keyword", ""),
                "send_key": data.get("send_key", "enter"),
                "focus_hotkey": data.get("focus_hotkey", "none"),
                "auto_send_default": bool(data.get("auto_send_default", True)),
                "auto_launch": bool(data.get("auto_launch", False)),
                "launch_paths": normalize_launch_paths(data.get("launch_paths")),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def apply_config(cfg: dict) -> None:
    runtime_cfg.update(cfg)
    runtime_cfg["launch_paths"] = normalize_launch_paths(runtime_cfg.get("launch_paths"))


def target_label() -> str:
    tid = runtime_cfg.get("target", "Cursor")
    if tid == "custom":
        kw = (runtime_cfg.get("custom_keyword") or "").strip() or "Custom"
        return kw
    return PRESETS.get(tid, PRESETS["Cursor"])["label"]


def match_keywords() -> list[str]:
    tid = runtime_cfg.get("target", "Cursor")
    if tid == "custom":
        kw = (runtime_cfg.get("custom_keyword") or "").strip()
        return [kw] if kw else []
    return list(PRESETS.get(tid, PRESETS["Cursor"])["keywords"])


def acquire_single_instance() -> bool:
    global _mutex
    kernel32 = ctypes.windll.kernel32
    _mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def phone_url() -> str:
    return f"http://{local_ip()}:{PORT}/"


# --- Win32 输入 / 剪贴板（避免 Tk 抢焦点） ---
ULONG_PTR = ctypes.c_size_t
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
VK_CONTROL = 0x11
VK_RETURN = 0x0D


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", INPUTUNION)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def set_clipboard_ui(text: str) -> None:
    """界面「复制地址」用；发送到目标应用请用 set_clipboard_text。"""
    if _ui_root is None:
        raise RuntimeError("UI not ready")
    _ui_root.clipboard_clear()
    _ui_root.clipboard_append(text)
    _ui_root.update_idletasks()


def set_clipboard_text(text: str) -> None:
    """Win32 Unicode 剪贴板，不触碰 Tk，避免抢焦点。"""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    data = text.encode("utf-16-le") + b"\x00\x00"
    for _ in range(8):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Cannot open clipboard")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise RuntimeError("GlobalAlloc failed")
        locked = kernel32.GlobalLock(handle)
        if not locked:
            kernel32.GlobalFree(handle)
            raise RuntimeError("GlobalLock failed")
        ctypes.memmove(locked, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise RuntimeError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()


def _send_inputs(inputs: list[INPUT]) -> None:
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    user32 = ctypes.windll.user32
    user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint
    sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent != n:
        raise RuntimeError(f"SendInput 失败 ({sent}/{n})")


def _key_input(vk: int, key_up: bool = False) -> INPUT:
    flags = KEYEVENTF_KEYUP if key_up else 0
    return INPUT(
        type=INPUT_KEYBOARD,
        union=INPUTUNION(ki=KEYBDINPUT(vk, 0, flags, 0, 0)),
    )


def send_ctrl_key(vk_code: int) -> None:
    _send_inputs(
        [
            _key_input(VK_CONTROL, False),
            _key_input(vk_code, False),
            _key_input(vk_code, True),
            _key_input(VK_CONTROL, True),
        ]
    )


def send_ctrl_v() -> None:
    send_ctrl_key(0x56)  # V


def send_enter() -> None:
    _send_inputs([_key_input(VK_RETURN, False), _key_input(VK_RETURN, True)])


def send_ctrl_enter() -> None:
    send_ctrl_key(VK_RETURN)


def send_submit(send_key: str) -> None:
    if send_key == "ctrl_enter":
        send_ctrl_enter()
    elif send_key == "enter":
        send_enter()


def send_focus_hotkey(hotkey: str) -> None:
    if hotkey == "ctrl_l":
        send_ctrl_key(0x4C)  # L
    elif hotkey == "ctrl_i":
        send_ctrl_key(0x49)  # I


def _abs_mouse(x: int, y: int) -> tuple[int, int]:
    user32 = ctypes.windll.user32
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    ax = int(x * 65535 / max(w - 1, 1))
    ay = int(y * 65535 / max(h - 1, 1))
    return ax, ay


def click_screen(x: int, y: int) -> None:
    ax, ay = _abs_mouse(x, y)
    move = INPUT(
        type=INPUT_MOUSE,
        union=INPUTUNION(
            mi=MOUSEINPUT(ax, ay, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, 0)
        ),
    )
    down = INPUT(
        type=INPUT_MOUSE,
        union=INPUTUNION(mi=MOUSEINPUT(ax, ay, 0, MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE, 0, 0)),
    )
    up = INPUT(
        type=INPUT_MOUSE,
        union=INPUTUNION(mi=MOUSEINPUT(ax, ay, 0, MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE, 0, 0)),
    )
    _send_inputs([move, down, up])


def click_chat_areas(hwnd: int) -> None:
    """点击 Cursor 常见聊天输入区域（底部中央 / 右下角 Agent）。"""
    user32 = ctypes.windll.user32
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return
    width = max(rect.right - rect.left, 1)
    height = max(rect.bottom - rect.top, 1)
    points = [
        (rect.left + int(width * 0.72), rect.top + int(height * 0.90)),  # 右侧 Agent 底部
        (rect.left + int(width * 0.55), rect.top + int(height * 0.92)),  # 中下
        (rect.left + int(width * 0.85), rect.top + int(height * 0.88)),  # 更靠右下
    ]
    for x, y in points:
        click_screen(x, y)
        time.sleep(0.18)


def _is_self_title(title: str) -> bool:
    return any(s in title for s in SELF_TITLES)


def _enum_target_hwnd(keywords: list[str]) -> int:
    if not keywords:
        return 0
    user32 = ctypes.windll.user32
    found = ctypes.c_size_t(0)
    keys = [k for k in keywords if k]

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_size_t)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""
        if _is_self_title(title):
            return True
        for key in keys:
            if key in title:
                found.value = hwnd
                return False
        return True

    user32.EnumWindows(callback, 0)
    return int(found.value)


def focus_target(keywords: list[str]) -> bool:
    hwnd = _enum_target_hwnd(keywords)
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    # 允许跨进程抢前台
    try:
        user32.AllowSetForegroundWindow(-1)
    except Exception:  # noqa: BLE001
        pass
    foreground = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    tgt_thread = user32.GetWindowThreadProcessId(hwnd, None)
    attached_fg = False
    attached_tgt = False
    if fg_thread and fg_thread != current_thread:
        attached_fg = bool(user32.AttachThreadInput(current_thread, fg_thread, True))
    if tgt_thread and tgt_thread != current_thread:
        attached_tgt = bool(user32.AttachThreadInput(current_thread, tgt_thread, True))
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        else:
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
        time.sleep(0.15)
    finally:
        if attached_tgt:
            user32.AttachThreadInput(current_thread, tgt_thread, False)
        if attached_fg:
            user32.AttachThreadInput(current_thread, fg_thread, False)
    return user32.GetForegroundWindow() == hwnd or user32.IsWindow(hwnd)


def paste_into_target(text: str, do_send: bool) -> str:
    """简单流程：写剪贴板 → 聚焦窗口 →（可选快捷键）→ 粘贴一次 → 发送。"""
    text = (text or "").strip()
    if not text:
        return "Empty content"
    keywords = match_keywords()
    label = target_label()
    if not keywords:
        return "Set a custom window title keyword first"
    try:
        set_clipboard_text(text)
    except Exception as exc:  # noqa: BLE001
        return f"Clipboard write failed: {exc}"
    if not focus_target(keywords):
        return f"Window not found for {label}. Open the app and focus the input."
    time.sleep(0.08)
    hotkey = runtime_cfg.get("focus_hotkey") or "none"
    if hotkey and hotkey != "none":
        send_focus_hotkey(hotkey)
        time.sleep(0.2)
    send_ctrl_v()
    send_key = runtime_cfg.get("send_key", "enter")
    if do_send and send_key != "none":
        time.sleep(0.12)
        send_submit(send_key)
        return f"Pasted and sent to {label}"
    return f"Pasted to {label}"


def _iter_start_menu_roots() -> list[Path]:
    roots = []
    appdata = os.environ.get("APPDATA")
    program_data = os.environ.get("ProgramData")
    if appdata:
        roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if program_data:
        roots.append(Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return roots


def _find_start_menu_lnk(names: list[str]) -> Path | None:
    lowered = {n.lower() for n in names}
    for root in _iter_start_menu_roots():
        if not root.exists():
            continue
        try:
            for path in root.rglob("*.lnk"):
                if path.name.lower() in lowered:
                    return path
        except OSError:
            continue
    return None


def _load_start_apps() -> dict[str, str]:
    """返回 {显示名: AppID}。"""
    global _start_apps_cache
    if _start_apps_cache is not None:
        return _start_apps_cache
    mapping: dict[str, str] = {}
    try:
        raw = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-StartApps | ConvertTo-Json -Compress",
            ],
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        data = json.loads(raw or "[]")
        if isinstance(data, dict):
            data = [data]
        for item in data or []:
            name = str(item.get("Name") or "")
            app_id = str(item.get("AppID") or "")
            if name and app_id:
                mapping[name] = app_id
    except Exception:  # noqa: BLE001
        mapping = {}
    _start_apps_cache = mapping
    return mapping


def _find_app_id(hints: list[str], explicit: list[str] | None = None) -> str | None:
    for app_id in explicit or []:
        if app_id:
            return app_id
    apps = _load_start_apps()
    for hint in hints:
        for name, app_id in apps.items():
            if hint.lower() in name.lower():
                return app_id
    return None


def _candidate_exe_paths(exe_names: list[str]) -> list[Path]:
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("ProgramFiles", "")
    pf86 = os.environ.get("ProgramFiles(x86)", "")
    home = Path.home()
    bases = [
        Path(local) / "Programs" / "cursor",
        Path(local) / "Programs" / "Cursor",
        Path(pf) / "Cursor",
        Path("D:/cursor"),
        Path("C:/cursor"),
        home / "AppData" / "Local" / "Programs" / "cursor",
        Path(local) / "Programs" / "Codex",
        Path(local) / "Programs" / "ChatGPT",
        Path(local) / "OpenAI Codex",
        Path(pf) / "ChatGPT",
        Path(pf86) / "ChatGPT",
    ]
    out: list[Path] = []
    for base in bases:
        for name in exe_names:
            out.append(base / name)
    for name in exe_names:
        which = shutil.which(name) or shutil.which(Path(name).stem)
        if which:
            out.append(Path(which))
    return out


def resolve_launch_target() -> tuple[str, str] | None:
    """返回 (kind, value)。kind: path | appid | lnk"""
    override = current_launch_path()
    if override:
        p = Path(override)
        if p.exists():
            return ("path", str(p))
        if "!" in override:
            return ("appid", override)
        return None

    tid = runtime_cfg.get("target", "Cursor")
    preset = PRESETS.get(tid, {})
    for exe in _candidate_exe_paths(list(preset.get("exe_names") or [])):
        if exe.exists():
            return ("path", str(exe))

    lnk = _find_start_menu_lnk(list(preset.get("lnk_names") or []))
    if lnk is not None:
        return ("lnk", str(lnk))

    app_id = _find_app_id(
        list(preset.get("app_name_hints") or [preset.get("label", "")]),
        list(preset.get("app_ids") or []),
    )
    if app_id:
        return ("appid", app_id)
    return None


def launch_target_app() -> tuple[bool, str]:
    resolved = resolve_launch_target()
    label = target_label()
    if not resolved:
        return False, f"Cannot find launch path for {label}. Configure .exe on desktop."
    kind, value = resolved
    try:
        if kind == "path":
            os.startfile(value)  # type: ignore[attr-defined]
        elif kind == "lnk":
            os.startfile(value)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(
                ["explorer.exe", f"shell:AppsFolder\\{value}"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return True, f"Launching {label}…"
    except Exception as exc:  # noqa: BLE001
        return False, f"Failed to launch {label}: {exc}"


def update_target_from_form(qs: dict) -> None:
    """根据手机/请求参数更新目标配置并落盘。"""
    target = (qs.get("target") or [""])[0].strip()
    if target in PRESETS:
        runtime_cfg["target"] = target
    keyword = (qs.get("keyword") or [None])[0]
    if keyword is not None:
        runtime_cfg["custom_keyword"] = keyword.strip()
    send_key = (qs.get("send_key") or [""])[0].strip()
    if send_key in SEND_KEY_OPTIONS:
        runtime_cfg["send_key"] = send_key
    focus_hotkey = (qs.get("focus_hotkey") or [""])[0].strip()
    if focus_hotkey in FOCUS_HOTKEY_OPTIONS:
        runtime_cfg["focus_hotkey"] = focus_hotkey
    auto_default = (qs.get("auto_default") or [None])[0]
    if auto_default is not None:
        runtime_cfg["auto_send_default"] = auto_default != "0"
    auto_launch = (qs.get("auto_launch") or [None])[0]
    if auto_launch is not None:
        runtime_cfg["auto_launch"] = auto_launch != "0"
    try:
        save_config()
    except Exception:  # noqa: BLE001
        pass


def page_html() -> str:
    cur = runtime_cfg.get("target", "Cursor")
    keyword = html.escape(runtime_cfg.get("custom_keyword", ""), quote=True)
    send_key = runtime_cfg.get("send_key", "enter")
    auto_checked = "checked" if runtime_cfg.get("auto_send_default", True) else ""
    launch_checked = "checked" if runtime_cfg.get("auto_launch", False) else ""
    options = []
    for tid in ("Cursor", "Codex", "ChatGPT", "custom"):
        sel = " selected" if tid == cur else ""
        options.append(f'<option value="{tid}"{sel}>{PRESETS[tid]["label"]}</option>')
    options_html = "\n".join(options)
    send_opts = []
    for sk, label in SEND_KEY_OPTIONS.items():
        sel = " selected" if sk == send_key else ""
        send_opts.append(f'<option value="{sk}"{sel}>{label}</option>')
    send_opts_html = "\n".join(send_opts)
    custom_display = "block" if cur == "custom" else "none"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"/>
<title>Phone to PC</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; font-family:system-ui,sans-serif; background:#0f1419; color:#e8eef5;
         min-height:100vh; display:flex; flex-direction:column; }}
  header {{ padding:18px 16px 8px; background:#0b3d36; }}
  h1 {{ margin:0; font-size:1.25rem; }}
  p {{ margin:6px 0 0; color:#9db5a8; font-size:.9rem; }}
  main {{ flex:1; padding:16px; display:flex; flex-direction:column; gap:12px; }}
  textarea {{ width:100%; min-height:36vh; box-sizing:border-box; border-radius:14px;
             border:1px solid #2a3646; background:#1a222c; color:#e8eef5;
             font-size:1.05rem; padding:14px; resize:vertical; }}
  .field {{ display:flex; flex-direction:column; gap:6px; }}
  .field span {{ font-size:.85rem; color:#8b9bb0; }}
  select, .field input {{ width:100%; box-sizing:border-box; border-radius:12px;
             border:1px solid #2a3646; background:#1a222c; color:#e8eef5;
             font-size:1rem; padding:12px; }}
  .opts label {{ display:flex; align-items:center; gap:10px; font-size:.95rem; color:#c9d4e0; }}
  .opts input {{ width:18px; height:18px; }}
  .row {{ display:flex; gap:10px; }}
  button {{ flex:1; border:0; border-radius:12px; padding:14px 12px; font-size:1.05rem; font-weight:700; }}
  .send {{ background:#2dd4a8; color:#041510; }}
  .clear {{ background:#2a3646; color:#e8eef5; }}
  .hint {{ color:#8b9bb0; font-size:.85rem; line-height:1.4; }}
  #status {{ min-height:1.2em; color:#2dd4a8; font-size:.95rem; }}
  #status.err {{ color:#ff8b7a; }}
  #kwWrap {{ display:{custom_display}; }}
</style>
</head>
<body>
<header>
  <h1 id="title">Send to PC</h1>
  <p>Pick target app, then type or dictate and send</p>
</header>
<main>
  <div class="field">
    <span>Target app</span>
    <select id="target" onchange="onTargetChange()">{options_html}</select>
  </div>
  <div class="field" id="kwWrap">
    <span>Window title keyword</span>
    <input id="keyword" value="{keyword}" placeholder="e.g. Codex / WeChat" onchange="saveCfg()"/>
  </div>
  <div class="field">
    <span>Send key after paste</span>
    <select id="sendKey" onchange="saveCfg()">{send_opts_html}</select>
  </div>
  <textarea id="t" placeholder="Tap here, use voice input…" autofocus></textarea>
  <div class="opts">
    <label><input id="autoEnter" type="checkbox" {auto_checked} onchange="saveCfg()"/> Auto send key after paste</label>
  </div>
  <div class="row">
    <button class="clear" type="button" onclick="clearT()">Clear</button>
    <button class="send" type="button" id="sendBtn" onclick="sendT()">Send</button>
  </div>
  <div id="status"></div>
  <div class="hint">提示：Open the target app and focus the input first for best results.</div>
</main>
<script>
function labelOf(){{
  const t=document.getElementById('target');
  const opt=t.options[t.selectedIndex];
  if(t.value==='custom'){{
    const kw=(document.getElementById('keyword').value||'').trim();
    return kw||'Custom';
  }}
  return opt?opt.text:'Target';
}}
function refreshUI(){{
  const lab=labelOf();
  document.getElementById('title').textContent='To '+lab;
  document.getElementById('sendBtn').textContent='Send to '+lab;
  document.getElementById('kwWrap').style.display=
    document.getElementById('target').value==='custom'?'block':'none';
}}
function formBody(extra){{
  const p=new URLSearchParams();
  p.set('target', document.getElementById('target').value);
  p.set('keyword', document.getElementById('keyword').value||'');
  p.set('send_key', document.getElementById('sendKey').value);
  p.set('auto_default', document.getElementById('autoEnter').checked?'1':'0');
  if(extra) Object.keys(extra).forEach(k=>p.set(k, extra[k]));
  return p.toString();
}}
async function saveCfg(){{
  refreshUI();
  try{{
    await fetch('/config',{{method:'POST',
      headers:{{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'}},
      body:formBody()}});
  }}catch(e){{}}
}}
function onTargetChange(){{ refreshUI(); saveCfg(); }}
async function sendT(){{
  const el=document.getElementById('t');
  const st=document.getElementById('status');
  const text=el.value.trim();
  if(!text){{ st.className='err'; st.textContent='Enter some text first'; return; }}
  if(document.getElementById('target').value==='custom' && !(document.getElementById('keyword').value||'').trim()){{
    st.className='err'; st.textContent='Custom target needs a window title keyword'; return;
  }}
  const autoEnter=document.getElementById('autoEnter').checked ? '1':'0';
  st.className=''; st.textContent='Sending…';
  try{{
    const r=await fetch('/send',{{method:'POST',
      headers:{{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'}},
      body:formBody({{text:text, enter:autoEnter}})}});
    const j=await r.json();
    st.className=j.ok?'':'err';
    st.textContent=j.message||(j.ok?'OK':'Failed');
    if(j.ok) el.value='';
  }}catch(e){{ st.className='err'; st.textContent='Send failed: '+e; }}
}}
function clearT(){{ document.getElementById('t').value=''; document.getElementById('status').textContent=''; }}
refreshUI();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def _json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        raw = page_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        global last_status
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        qs = parse_qs(body)

        if self.path == "/config":
            update_target_from_form(qs)
            self._json(
                200,
                {
                    "ok": True,
                    "target": runtime_cfg.get("target"),
                    "label": target_label(),
                    "send_key": runtime_cfg.get("send_key"),
                },
            )
            return

        if self.path != "/send":
            self.send_error(404)
            return

        update_target_from_form(qs)
        text = (qs.get("text") or [""])[0].strip()
        do_send = (qs.get("enter") or ["1"])[0] != "0"
        if not text:
            self._json(400, {"ok": False, "message": "Empty content"})
            return

        done = threading.Event()
        result: dict = {}

        def job() -> None:
            global last_status
            try:
                msg = paste_into_target(text, do_send)
                result["ok"] = msg.startswith("Pasted")
                result["message"] = msg
                last_status = msg
            except Exception as exc:  # noqa: BLE001
                result["ok"] = False
                result["message"] = f"Failed: {exc}"
                last_status = result["message"]
            finally:
                done.set()

        paste_queue.put(job)
        if not done.wait(timeout=8):
            last_status = "Timed out, try again"
            self._json(504, {"ok": False, "message": last_status})
            return
        self._json(200, result)


def start_server() -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def run_gui(start_in_tray: bool = False) -> None:
    global last_status, _ui_root
    import customtkinter as ctk
    from tkinter import filedialog
    from PIL import Image, ImageDraw

    import startup

    apply_config(load_config())

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("green")

    app = ctk.CTk()
    _ui_root = app
    app.title(APP_TITLE)
    app.geometry("560x740")
    app.minsize(520, 700)
    app.configure(fg_color="#0f1419")

    state = {
        "tray": None,
        "quitting": False,
        "hide_from_unmap": False,
        "httpd": None,
    }

    url = phone_url()
    state["httpd"] = start_server()
    last_status = f"Server running: {url}"

    ctk.CTkLabel(app, text="Phone to PC", font=ctk.CTkFont(size=22, weight="bold")).pack(
        anchor="w", padx=20, pady=(18, 4)
    )
    ctk.CTkLabel(
        app, text="Open this URL on your phone (same Wi‑Fi), then send", text_color="#8b9bb0"
    ).pack(anchor="w", padx=20)

    url_box = ctk.CTkEntry(app, height=40)
    url_box.pack(fill="x", padx=20, pady=12)
    url_box.insert(0, url)
    url_box.configure(state="readonly")

    row = ctk.CTkFrame(app, fg_color="transparent")
    row.pack(fill="x", padx=20)

    def copy_url() -> None:
        try:
            set_clipboard_ui(url)
            status_var.set("URL copied to clipboard")
        except Exception as exc:  # noqa: BLE001
            status_var.set(f"Copy failed: {exc}")

    ctk.CTkButton(row, text="Copy URL", width=110, command=copy_url).pack(side="left")
    ctk.CTkButton(
        row, text="Preview locally", width=110, command=lambda: webbrowser.open(f"http://127.0.0.1:{PORT}/")
    ).pack(side="left", padx=8)
    ctk.CTkButton(
        row, text="Hide to tray", width=110, fg_color="#2a3646", command=lambda: hide_to_tray()
    ).pack(side="left", padx=8)

    target_frame = ctk.CTkFrame(app, fg_color="#1a222c", corner_radius=12)
    target_frame.pack(fill="x", padx=20, pady=(16, 0))

    ctk.CTkLabel(target_frame, text="Target app", font=ctk.CTkFont(size=14, weight="bold")).pack(
        anchor="w", padx=14, pady=(12, 4)
    )

    preset_names = [PRESETS[k]["label"] for k in ("Cursor", "Codex", "ChatGPT", "custom")]
    id_by_label = {PRESETS[k]["label"]: k for k in PRESETS}
    current_id = runtime_cfg.get("target", "Cursor")
    target_var = ctk.StringVar(value=PRESETS.get(current_id, PRESETS["Cursor"])["label"])
    send_label_by_key = SEND_KEY_OPTIONS
    key_by_label = {v: k for k, v in SEND_KEY_OPTIONS.items()}
    send_var = ctk.StringVar(
        value=send_label_by_key.get(runtime_cfg.get("send_key", "enter"), "Enter")
    )
    focus_by_label = {v: k for k, v in FOCUS_HOTKEY_OPTIONS.items()}
    focus_var = ctk.StringVar(
        value=FOCUS_HOTKEY_OPTIONS.get(
            runtime_cfg.get("focus_hotkey", "none"), FOCUS_HOTKEY_OPTIONS["none"]
        )
    )
    keyword_var = ctk.StringVar(value=runtime_cfg.get("custom_keyword", ""))
    launch_var = ctk.StringVar(value=current_launch_path())
    auto_var = ctk.BooleanVar(value=bool(runtime_cfg.get("auto_send_default", True)))
    auto_launch_var = ctk.BooleanVar(value=bool(runtime_cfg.get("auto_launch", False)))
    autostart_var = ctk.BooleanVar(value=startup.is_autostart_enabled())

    def persist() -> None:
        runtime_cfg["target"] = id_by_label.get(target_var.get(), "Cursor")
        runtime_cfg["custom_keyword"] = keyword_var.get().strip()
        runtime_cfg["send_key"] = key_by_label.get(send_var.get(), "enter")
        runtime_cfg["focus_hotkey"] = focus_by_label.get(focus_var.get(), "none")
        runtime_cfg["auto_send_default"] = bool(auto_var.get())
        runtime_cfg["auto_launch"] = bool(auto_launch_var.get())
        set_current_launch_path(launch_var.get())
        save_config()
        path_hint = current_launch_path() or "No exe configured (auto-detect)"
        status_var.set(
            f"Target {target_label()} · {SEND_KEY_OPTIONS[runtime_cfg['send_key']]} · {path_hint}"
        )

    def on_target_change(_choice: str | None = None) -> None:
        # 先保存当前目标的路径，再切到新目标
        set_current_launch_path(launch_var.get())
        tid = id_by_label.get(target_var.get(), "Cursor")
        runtime_cfg["target"] = tid
        is_custom = tid == "custom"
        keyword_entry.configure(state="normal" if is_custom else "disabled")
        if not is_custom and not keyword_var.get().strip():
            keyword_var.set("")
        launch_var.set(current_launch_path())
        if tid != "custom":
            sk = PRESETS[tid]["send_key"]
            send_var.set(SEND_KEY_OPTIONS[sk])
            fk = PRESETS[tid].get("focus_hotkey", "none")
            focus_var.set(FOCUS_HOTKEY_OPTIONS.get(fk, FOCUS_HOTKEY_OPTIONS["none"]))
        persist()

    ctk.CTkOptionMenu(
        target_frame,
        values=preset_names,
        variable=target_var,
        command=on_target_change,
        width=200,
    ).pack(anchor="w", padx=14, pady=4)

    ctk.CTkLabel(target_frame, text="Window title keyword (custom target)", text_color="#8b9bb0").pack(
        anchor="w", padx=14, pady=(8, 2)
    )
    keyword_entry = ctk.CTkEntry(
        target_frame, textvariable=keyword_var, height=34, placeholder_text="e.g. Codex / ChatGPT"
    )
    keyword_entry.pack(fill="x", padx=14, pady=4)
    if current_id != "custom":
        keyword_entry.configure(state="disabled")

    def on_keyword_focus_out(_event=None) -> None:
        if id_by_label.get(target_var.get()) == "custom":
            persist()

    keyword_entry.bind("<FocusOut>", on_keyword_focus_out)
    keyword_entry.bind("<Return>", on_keyword_focus_out)

    ctk.CTkLabel(
        target_frame,
        text="Target .exe path (optional)",
        text_color="#8b9bb0",
    ).pack(anchor="w", padx=14, pady=(8, 2))
    path_row = ctk.CTkFrame(target_frame, fg_color="transparent")
    path_row.pack(fill="x", padx=14, pady=4)
    launch_entry = ctk.CTkEntry(
        path_row,
        textvariable=launch_var,
        height=34,
        placeholder_text=r"e.g. D:\cursor\Cursor.exe",
    )
    launch_entry.pack(side="left", fill="x", expand=True)

    def browse_exe() -> None:
        picked = filedialog.askopenfilename(
            title="Select target .exe",
            filetypes=[("Executables", "*.exe"), ("All files", "*.*")],
        )
        if picked:
            launch_var.set(picked)
            persist()

    ctk.CTkButton(path_row, text="Browse", width=72, command=browse_exe).pack(side="left", padx=(8, 0))
    launch_entry.bind("<FocusOut>", lambda _e: persist())
    launch_entry.bind("<Return>", lambda _e: persist())

    ctk.CTkLabel(target_frame, text="Send key after paste", text_color="#8b9bb0").pack(
        anchor="w", padx=14, pady=(8, 2)
    )
    ctk.CTkOptionMenu(
        target_frame,
        values=list(SEND_KEY_OPTIONS.values()),
        variable=send_var,
        command=lambda _c: persist(),
        width=220,
    ).pack(anchor="w", padx=14, pady=4)

    ctk.CTkLabel(target_frame, text="Focus input before paste", text_color="#8b9bb0").pack(
        anchor="w", padx=14, pady=(8, 2)
    )
    ctk.CTkOptionMenu(
        target_frame,
        values=list(FOCUS_HOTKEY_OPTIONS.values()),
        variable=focus_var,
        command=lambda _c: persist(),
        width=260,
    ).pack(anchor="w", padx=14, pady=4)

    ctk.CTkCheckBox(
        target_frame,
        text="Phone page: auto-send checked by default",
        variable=auto_var,
        command=persist,
    ).pack(anchor="w", padx=14, pady=(8, 4))
    ctk.CTkCheckBox(
        target_frame,
        text="Auto-launch target if closed (off by default)",
        variable=auto_launch_var,
        command=persist,
    ).pack(anchor="w", padx=14, pady=4)

    def on_autostart() -> None:
        try:
            startup.set_autostart(bool(autostart_var.get()))
            status_var.set("Autostart enabled" if autostart_var.get() else "Autostart disabled")
        except Exception as exc:  # noqa: BLE001
            autostart_var.set(startup.is_autostart_enabled())
            status_var.set(f"Autostart failed: {exc}")

    ctk.CTkCheckBox(
        target_frame,
        text="Autostart (minimize to tray)",
        variable=autostart_var,
        command=on_autostart,
    ).pack(anchor="w", padx=14, pady=(4, 14))

    status_var = ctk.StringVar(value=last_status)
    ctk.CTkLabel(app, textvariable=status_var, text_color="#2dd4a8", wraplength=500).pack(
        anchor="w", padx=20, pady=8
    )
    ctk.CTkLabel(
        app,
        text=(
            "Steps:\n"
            "1. Pick target (Cursor / Codex / …)\n"
            "2. Same Wi‑Fi, open URL on phone\n"
            "3. Open target app and focus input\n"
            "4. Send from phone; close hides to tray"
        ),
        justify="left",
        text_color="#8b9bb0",
    ).pack(anchor="w", padx=20, pady=(4, 0))

    def make_tray_image():
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((4, 4, 60, 60), fill=(15, 111, 91, 255))
        draw.rectangle((20, 18, 44, 46), fill=(45, 212, 168, 255))
        return img

    def show_from_tray() -> None:
        app.deiconify()
        app.lift()
        app.focus_force()
        try:
            app.state("normal")
        except Exception:  # noqa: BLE001
            pass

    def hide_to_tray() -> None:
        state["hide_from_unmap"] = True
        try:
            app.withdraw()
        finally:
            app.after(200, lambda: state.__setitem__("hide_from_unmap", False))
        if state["tray"] is not None:
            try:
                state["tray"].title = f"{APP_TITLE} · {target_label()}"
            except Exception:  # noqa: BLE001
                pass

    def quit_app() -> None:
        if state["quitting"]:
            return
        state["quitting"] = True
        try:
            set_current_launch_path(launch_var.get())
            save_config()
        except Exception:  # noqa: BLE001
            pass
        tray = state["tray"]
        state["tray"] = None
        if tray is not None:
            try:
                tray.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            if state["httpd"] is not None:
                state["httpd"].shutdown()
        except Exception:  # noqa: BLE001
            pass
        app.destroy()

    def setup_tray() -> None:
        try:
            import pystray
            from pystray import MenuItem as Item
        except ImportError:
            status_var.set("Tray unavailable; close will exit")
            return

        menu = pystray.Menu(
            Item("Open window", lambda *_: app.after(0, show_from_tray), default=True),
            Item("Quit", lambda *_: app.after(0, quit_app)),
        )
        icon = pystray.Icon("phone_to_cursor", make_tray_image(), APP_TITLE, menu)
        state["tray"] = icon
        threading.Thread(target=icon.run, daemon=True).start()

    def on_close() -> None:
        if state["quitting"]:
            return
        if state["tray"] is None:
            quit_app()
            return
        hide_to_tray()

    def on_unmap(event) -> None:
        if event.widget is not app or state["quitting"] or state["hide_from_unmap"]:
            return
        if state["tray"] is None:
            return
        if str(app.state()) == "iconic":
            app.after(30, hide_to_tray)

    def pump() -> None:
        try:
            while True:
                job = paste_queue.get_nowait()
                job()
        except queue.Empty:
            pass
        status_var.set(last_status)
        app.after(80, pump)

    app.protocol("WM_DELETE_WINDOW", on_close)
    app.bind("<Unmap>", on_unmap)
    app.after(80, pump)
    app.after(200, setup_tray)
    if start_in_tray:
        app.after(300, hide_to_tray)
    app.mainloop()


def main() -> None:
    if not acquire_single_instance():
        ctypes.windll.user32.MessageBoxW(0, f"{APP_TITLE} is already running", "Notice", 0x40)
        sys.exit(0)
    run_gui(start_in_tray="--tray" in sys.argv)


if __name__ == "__main__":
    main()
