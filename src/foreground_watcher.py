"""Watch the Windows foreground window and report exe name changes.

Used by BridgeApp to auto-load a per-game profile when the user switches to
a game window. Polls (no event hook) at ~500ms — well below the threshold
of "feels reactive" and cheap enough to not show up on a profiler.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
from pathlib import Path
from typing import Callable


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi


def _foreground_exe_name() -> str | None:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return Path(buf.value).stem.lower()
        return None
    finally:
        kernel32.CloseHandle(h)


class ForegroundWatcher:
    """Background thread that calls `on_change(exe_basename)` whenever the
    foreground exe changes. Stops on `stop()`.

    `exe_basename` is the lowercase filename without extension, e.g.
    "cyberpunk2077" or "factorio". `None` means "couldn't determine".
    """

    def __init__(
        self,
        on_change: Callable[[str | None], None],
        poll_interval: float = 0.5,
    ) -> None:
        self._cb = on_change
        self._interval = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: str | None = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ForegroundWatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                current = _foreground_exe_name()
            except Exception:
                continue
            if current != self._last:
                self._last = current
                try:
                    self._cb(current)
                except Exception:
                    pass
