"""Windows low-level keyboard hook for capturing the new Steam Controller's
D-pad output.

Background: the new Steam Controller (PID 0x1304) emits its D-pad as keyboard
arrow events most of the time, even after we send the disable-lizard-mode
HID feature reports. The D-pad bits *do* exist in the HID frame format
(observed once during early captures), but the controller firmware seems
to revert to keyboard mode unpredictably.

Workaround: register a global low-level keyboard hook. When the user
presses an arrow key while the bridge is running, we:
  1. Forward it to the virtual Xbox gamepad's D-pad.
  2. Suppress the original keyboard event so Windows doesn't shift focus
     (which is why pressing D-pad keys was closing GUI windows).

The hook runs on its own thread with a Windows message pump.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
import time
from typing import Callable

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28

ARROW_NAMES = {VK_LEFT: "LEFT", VK_RIGHT: "RIGHT", VK_UP: "UP", VK_DOWN: "DOWN"}


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


_LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    ctypes.c_long,                    # return type
    ctypes.c_int,                     # nCode
    ctypes.wintypes.WPARAM,           # wParam
    ctypes.wintypes.LPARAM,           # lParam
)


class ArrowKeyHook:
    """Intercept arrow-key presses and forward them to a callback.

    Usage:
        hook = ArrowKeyHook(on_arrow=lambda name, pressed: ...)
        hook.start()
        ...
        hook.stop()

    The callback is invoked from the hook thread for every arrow key
    down/up event. Be careful to do minimal work in the callback.

    `suppress=True` (default) returns 1 from the hook, telling Windows to
    drop the event so other apps don't see it.
    """

    def __init__(
        self,
        on_arrow: Callable[[str, bool], None],
        suppress: bool = True,
    ) -> None:
        self._on_arrow = on_arrow
        self._suppress = suppress
        self._thread: threading.Thread | None = None
        self._hook_id: int = 0
        self._stop = threading.Event()
        # The CFUNCTYPE wrapper MUST be kept alive as long as the hook is
        # installed, otherwise Windows will call into freed memory.
        self._hook_proc = _LowLevelKeyboardProc(self._proc)

    # ---- public API ----

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.is_running():
            return True
        self._stop.clear()
        ready = threading.Event()
        ok_box: list[bool] = [False]

        def run() -> None:
            self._hook_id = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL,
                self._hook_proc,
                kernel32.GetModuleHandleW(None),
                0,
            )
            ok_box[0] = bool(self._hook_id)
            ready.set()
            if not self._hook_id:
                return
            # Message pump — hook needs an active message queue to fire.
            msg = ctypes.wintypes.MSG()
            while not self._stop.is_set():
                # PeekMessage with PM_REMOVE so we can periodically check _stop.
                got = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
                if got:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.005)
            try:
                user32.UnhookWindowsHookEx(self._hook_id)
            except Exception:
                pass
            self._hook_id = 0

        self._thread = threading.Thread(target=run, name="ArrowKeyHook", daemon=True)
        self._thread.start()
        ready.wait(timeout=1.0)
        return ok_box[0]

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.0)
        self._thread = None

    # ---- internal ----

    def _proc(self, nCode: int, wParam: int, lParam: int) -> int:
        if nCode == 0:
            try:
                kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT))[0]
                vk = int(kb.vkCode)
                if vk in ARROW_NAMES:
                    pressed = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    released = wParam in (WM_KEYUP, WM_SYSKEYUP)
                    if pressed or released:
                        try:
                            self._on_arrow(ARROW_NAMES[vk], pressed)
                        except Exception:
                            pass
                        if self._suppress:
                            return 1
            except Exception:
                pass
        return user32.CallNextHookEx(None, nCode, wParam, lParam)
