"""Virtual Xbox 360 gamepad backed by ViGEmBus.

Wraps `vgamepad`'s VX360Gamepad with a small typed surface so the mapper can
push axes/buttons/triggers as floats in [-1, 1] / [0, 1] without knowing
ViGEm specifics.

If `vgamepad` or the ViGEmBus driver are not installed, this module degrades
to a no-op `NullGamepad` so the GUI still launches and the user gets a clear
error in the status panel.
"""

from __future__ import annotations

from typing import Protocol


class VirtualGamepad(Protocol):
    def set_left_stick(self, x: float, y: float) -> None: ...
    def set_right_stick(self, x: float, y: float) -> None: ...
    def set_left_trigger(self, v: float) -> None: ...
    def set_right_trigger(self, v: float) -> None: ...
    def set_button(self, name: str, pressed: bool) -> None: ...
    def set_dpad(self, up: bool, down: bool, left: bool, right: bool) -> None: ...
    def update(self) -> None: ...
    def reset(self) -> None: ...
    def close(self) -> None: ...
    @property
    def available(self) -> bool: ...
    @property
    def status(self) -> str: ...


# XInput button mapping. Names match the labels we use elsewhere in the app.
_BUTTON_NAMES = {
    "A", "B", "X", "Y",
    "LB", "RB",
    "BACK", "START",
    "LS", "RS",          # left/right stick click
    "GUIDE",             # Xbox guide / Steam button
}


class NullGamepad:
    """Fallback when ViGEmBus is unavailable. All ops are no-ops."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def set_left_stick(self, x: float, y: float) -> None: pass
    def set_right_stick(self, x: float, y: float) -> None: pass
    def set_left_trigger(self, v: float) -> None: pass
    def set_right_trigger(self, v: float) -> None: pass
    def set_button(self, name: str, pressed: bool) -> None: pass
    def set_dpad(self, up: bool, down: bool, left: bool, right: bool) -> None: pass
    def update(self) -> None: pass
    def reset(self) -> None: pass
    def close(self) -> None: pass

    @property
    def available(self) -> bool: return False

    @property
    def status(self) -> str: return self._reason


class ViGEmX360Gamepad:
    """Concrete VirtualGamepad backed by vgamepad's VX360Gamepad."""

    def __init__(self) -> None:
        import vgamepad as vg

        self._vg = vg
        self._pad = vg.VX360Gamepad()
        self._buttons_state: dict[str, bool] = {}
        self._dpad_state: tuple[bool, bool, bool, bool] = (False, False, False, False)
        self._lx = self._ly = self._rx = self._ry = 0
        self._lt = self._rt = 0

        # Map our button names to vgamepad's enum.
        bm = vg.XUSB_BUTTON
        self._button_enum = {
            "A": bm.XUSB_GAMEPAD_A,
            "B": bm.XUSB_GAMEPAD_B,
            "X": bm.XUSB_GAMEPAD_X,
            "Y": bm.XUSB_GAMEPAD_Y,
            "LB": bm.XUSB_GAMEPAD_LEFT_SHOULDER,
            "RB": bm.XUSB_GAMEPAD_RIGHT_SHOULDER,
            "BACK": bm.XUSB_GAMEPAD_BACK,
            "START": bm.XUSB_GAMEPAD_START,
            "LS": bm.XUSB_GAMEPAD_LEFT_THUMB,
            "RS": bm.XUSB_GAMEPAD_RIGHT_THUMB,
            "GUIDE": bm.XUSB_GAMEPAD_GUIDE,
            "DPAD_UP": bm.XUSB_GAMEPAD_DPAD_UP,
            "DPAD_DOWN": bm.XUSB_GAMEPAD_DPAD_DOWN,
            "DPAD_LEFT": bm.XUSB_GAMEPAD_DPAD_LEFT,
            "DPAD_RIGHT": bm.XUSB_GAMEPAD_DPAD_RIGHT,
        }

    # ---- VirtualGamepad surface ----

    def set_left_stick(self, x: float, y: float) -> None:
        self._lx = _to_i16(x)
        self._ly = _to_i16(y)
        self._pad.left_joystick(x_value=self._lx, y_value=self._ly)

    def set_right_stick(self, x: float, y: float) -> None:
        self._rx = _to_i16(x)
        self._ry = _to_i16(y)
        self._pad.right_joystick(x_value=self._rx, y_value=self._ry)

    def set_left_trigger(self, v: float) -> None:
        self._lt = _to_u8(v)
        self._pad.left_trigger(value=self._lt)

    def set_right_trigger(self, v: float) -> None:
        self._rt = _to_u8(v)
        self._pad.right_trigger(value=self._rt)

    def set_button(self, name: str, pressed: bool) -> None:
        flag = self._button_enum.get(name.upper())
        if flag is None:
            return
        prev = self._buttons_state.get(name, False)
        if pressed == prev:
            return
        if pressed:
            self._pad.press_button(button=flag)
        else:
            self._pad.release_button(button=flag)
        self._buttons_state[name] = pressed

    def set_dpad(self, up: bool, down: bool, left: bool, right: bool) -> None:
        target = (up, down, left, right)
        if target == self._dpad_state:
            return
        for name, want in zip(("DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"), target):
            self.set_button(name, want)
        self._dpad_state = target

    def update(self) -> None:
        self._pad.update()

    def reset(self) -> None:
        self._pad.reset()
        self._buttons_state.clear()
        self._dpad_state = (False, False, False, False)
        self._lx = self._ly = self._rx = self._ry = 0
        self._lt = self._rt = 0
        self._pad.update()

    def close(self) -> None:
        try:
            self.reset()
        except Exception:
            pass

    @property
    def available(self) -> bool:
        return True

    @property
    def status(self) -> str:
        return "ViGEmBus connected, virtual Xbox 360 gamepad active"


def create_gamepad() -> VirtualGamepad:
    """Try to create a ViGEmBus-backed pad. On failure, return a NullGamepad
    so callers can still wire up signals without crashing."""
    try:
        return ViGEmX360Gamepad()
    except ImportError as e:
        return NullGamepad(f"vgamepad not installed: {e}")
    except Exception as e:  # ViGEmBus missing / not loaded
        return NullGamepad(f"ViGEmBus unavailable: {e}")


# ----- helpers --------------------------------------------------------------


def _to_i16(v: float) -> int:
    if v >= 1.0:
        return 32767
    if v <= -1.0:
        return -32768
    return int(round(v * 32767))


def _to_u8(v: float) -> int:
    if v >= 1.0:
        return 255
    if v <= 0.0:
        return 0
    return int(round(v * 255))
