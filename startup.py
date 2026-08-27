"""Windows 开机自启。"""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "PhoneToCursor"


def launch_command(minimized: bool = True) -> str:
    if getattr(sys, "frozen", False):
        target = f'"{Path(sys.executable).resolve()}"'
    else:
        python = sys.executable
        script = str(Path(__file__).resolve().parent / "main.py")
        target = f'"{python}" "{script}"'
    if minimized:
        return f"{target} --tray"
    return target


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    if enabled:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command(True))
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, APP_NAME)
        except FileNotFoundError:
            pass
        except OSError:
            pass
