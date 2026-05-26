"""Windows auto-start support.

Reads / writes a value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
that points at the launch command. HKCU (current user) doesn't need admin.

When running from source, the command is `pythonw.exe -m src`. When frozen
by PyInstaller, it's the .exe path itself. The bridge starts minimized to
tray when auto-launched so it doesn't pop a window in the user's face.
"""

from __future__ import annotations

import sys
from pathlib import Path

import winreg


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "SteamPadBridge"
MINIMIZED_ARG = "--minimized"


def launch_command() -> str:
    """Return a quoted command line that re-launches SteamPad Bridge,
    starting minimized to the system tray."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return f'"{exe}" {MINIMIZED_ARG}'
    # Running from source — call pythonw.exe (no console) with `-m src`.
    pyw = Path(sys.executable).with_name("pythonw.exe")
    if not pyw.exists():
        pyw = Path(sys.executable)
    return f'"{pyw}" -m src {MINIMIZED_ARG}'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, APP_REG_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable() -> None:
    cmd = launch_command()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, APP_REG_NAME, 0, winreg.REG_SZ, cmd)


def disable() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, APP_REG_NAME)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def set_enabled(enabled: bool) -> None:
    if enabled:
        enable()
    else:
        disable()
