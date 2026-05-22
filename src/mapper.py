"""Apply a Profile to a ControllerState and drive a VirtualGamepad."""

from __future__ import annotations

import math
from typing import Callable

from .profile import (
    BTN_NAME_TO_FLAG,
    GyroTune,
    Profile,
    StickTune,
    TriggerTune,
)
from .protocol import Btn, ControllerState
from .virtual_gamepad import VirtualGamepad


# Names of "virtual buttons" that aren't simple bitflags but synthesized from
# state. Used so the GUI can list them in the editor.
SYNTHETIC_BUTTONS = ("RIGHT_PAD_TOUCH", "LEFT_PAD_TOUCH")


def _apply_stick(x: float, y: float, t: StickTune) -> tuple[float, float]:
    if t.invert_x:
        x = -x
    if t.invert_y:
        y = -y
    mag = math.hypot(x, y)
    if mag <= t.deadzone:
        return (0.0, 0.0)
    # Rescale so values just past the dead zone start at 0 (radial dead zone).
    scaled = (mag - t.deadzone) / max(1e-6, (t.saturation - t.deadzone))
    scaled = min(1.0, max(0.0, scaled)) * t.sensitivity
    nx = x / mag
    ny = y / mag
    fx = max(-1.0, min(1.0, nx * scaled))
    fy = max(-1.0, min(1.0, ny * scaled))
    return (fx, fy)


def _apply_trigger(v: float, t: TriggerTune) -> float:
    if v <= t.deadzone:
        return 0.0
    if v >= t.saturation:
        return 1.0
    return (v - t.deadzone) / max(1e-6, (t.saturation - t.deadzone))


def _btn_pressed(state: ControllerState, name: str) -> bool:
    # Synthesized buttons (pad touches) — checked first.
    if name == "RIGHT_PAD_TOUCH":
        return state.pressed(Btn.RIGHT_PAD_TOUCH)
    if name == "LEFT_PAD_TOUCH":
        return state.pressed(Btn.LEFT_PAD_TOUCH)
    flag = BTN_NAME_TO_FLAG.get(name)
    if flag is None:
        return False
    return state.pressed(flag)


class Mapper:
    """Stateful mapper. Holds the active profile and a virtual gamepad
    instance. Call `apply(state)` for every decoded input frame."""

    def __init__(self, profile: Profile, gamepad: VirtualGamepad) -> None:
        self._profile = profile
        self._gamepad = gamepad
        # Cache of (name, pressed) so we only call set_button when state changes.
        self._button_cache: dict[str, bool] = {}

    # ---- properties ----

    @property
    def profile(self) -> Profile:
        return self._profile

    def set_profile(self, profile: Profile) -> None:
        self._profile = profile
        # Reset any held buttons to avoid stuck input across profile swaps.
        self._gamepad.reset()
        self._button_cache.clear()

    # ---- main loop hook ----

    def apply(self, state: ControllerState) -> None:
        p = self._profile

        # 1. Sticks
        lx, ly = _apply_stick(state.left_stick[0], state.left_stick[1], p.left_stick)
        rx, ry = _apply_stick(state.right_stick[0], state.right_stick[1], p.right_stick)

        # Optional: pad-as-stick. If the user routes the right pad to RIGHT,
        # the pad value overrides the right stick whenever the pad is touched.
        if p.right_pad_routes_to == "RIGHT" and state.pressed(Btn.RIGHT_PAD_TOUCH):
            rx, ry = _apply_stick(state.right_pad[0], state.right_pad[1], p.right_pad)
        elif p.right_pad_routes_to == "LEFT" and state.pressed(Btn.RIGHT_PAD_TOUCH):
            lx, ly = _apply_stick(state.right_pad[0], state.right_pad[1], p.right_pad)

        if p.left_pad_routes_to == "LEFT" and state.pressed(Btn.LEFT_PAD_TOUCH):
            lx, ly = _apply_stick(state.left_pad[0], state.left_pad[1], p.left_pad)
        elif p.left_pad_routes_to == "RIGHT" and state.pressed(Btn.LEFT_PAD_TOUCH):
            rx, ry = _apply_stick(state.left_pad[0], state.left_pad[1], p.left_pad)

        # 2. Gyro -> right stick (additive)
        if p.gyro.enabled and self._gyro_active(state, p.gyro):
            gx, gy, gz = state.gyro
            add_x = gx * p.gyro.roll_to_x + gy * p.gyro.yaw_to_x
            add_y = gz * p.gyro.pitch_to_y
            rx = max(-1.0, min(1.0, rx + add_x))
            ry = max(-1.0, min(1.0, ry + add_y))

        self._gamepad.set_left_stick(lx, ly)
        self._gamepad.set_right_stick(rx, ry)

        # 3. Triggers (analog from hardware triggers, but also virtual-from-button)
        lt_val = _apply_trigger(state.left_trigger, p.left_trigger)
        rt_val = _apply_trigger(state.right_trigger, p.right_trigger)

        # 4. Buttons
        # Aggregate by target first so multiple physical buttons mapped to the
        # same virtual button OR together (otherwise a released source would
        # clobber a still-held one).
        targets_pressed: dict[str, bool] = {}
        dpad_target: dict[str, bool] = {
            "DPAD_UP": False, "DPAD_DOWN": False,
            "DPAD_LEFT": False, "DPAD_RIGHT": False,
        }

        for phys, target in p.buttons.items():
            if not target or target == "NONE":
                continue
            pressed = _btn_pressed(state, phys)

            if target == "LT":
                if pressed:
                    lt_val = 1.0
                continue
            if target == "RT":
                if pressed:
                    rt_val = 1.0
                continue
            if target in dpad_target:
                dpad_target[target] = dpad_target[target] or pressed
                continue

            targets_pressed[target] = targets_pressed.get(target, False) or pressed

        # Push to the gamepad, including releases for targets that used to be
        # pressed but aren't in this frame.
        all_targets = set(self._button_cache) | set(targets_pressed)
        for target in all_targets:
            pressed = targets_pressed.get(target, False)
            if self._button_cache.get(target) != pressed:
                self._gamepad.set_button(target, pressed)
                self._button_cache[target] = pressed

        self._gamepad.set_left_trigger(lt_val)
        self._gamepad.set_right_trigger(rt_val)
        self._gamepad.set_dpad(
            up=dpad_target["DPAD_UP"],
            down=dpad_target["DPAD_DOWN"],
            left=dpad_target["DPAD_LEFT"],
            right=dpad_target["DPAD_RIGHT"],
        )

        self._gamepad.update()

    # ---- helpers ----

    @staticmethod
    def _gyro_active(state: ControllerState, g: GyroTune) -> bool:
        if not g.activate_button or g.activate_button == "ALWAYS":
            return True
        return _btn_pressed(state, g.activate_button)


# Type used by the GUI to listen for live state.
StateListener = Callable[[ControllerState], None]
