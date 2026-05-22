"""Coordinator. Owns the HID reader, the parser, the mapper, and the gamepad.

The GUI talks to this via a thin signal-callback interface (no Qt deps here)
so the bridge can also be driven from a CLI or tests.
"""

from __future__ import annotations

import threading
from typing import Callable

from .hid_device import (
    DeviceInfo,
    HidReader,
    enumerate_valve_devices,
    pick_input_interface,
    wake_all_valve_interfaces,
)
from .keyboard_hook import ArrowKeyHook
from .mapper import Mapper
from .profile import Profile, load_profile, save_profile
from .protocol import ControllerState, ReportParser
from .virtual_gamepad import VirtualGamepad, create_gamepad


StateCallback = Callable[[ControllerState], None]
StatusCallback = Callable[[str], None]


class BridgeApp:
    def __init__(self) -> None:
        self._reader: HidReader | None = None
        self._parser = ReportParser()
        self._gamepad: VirtualGamepad = create_gamepad()
        self._profile: Profile = load_profile("default")
        self._mapper = Mapper(self._profile, self._gamepad)
        self._state_cbs: list[StateCallback] = []
        self._status_cbs: list[StatusCallback] = []
        self._last_state: ControllerState | None = None
        self._lock = threading.Lock()
        # Keyboard-arrow → virtual D-pad fallback (for the case where the
        # Steam Controller reverts to emitting D-pad as keyboard keys).
        self._arrow_hook: ArrowKeyHook | None = None
        self._dpad_kbd_enabled: bool = True
        # Track the current keyboard-driven d-pad state so the gamepad
        # always sees a consistent up/down/left/right tuple.
        self._kbd_dpad = {"UP": False, "DOWN": False, "LEFT": False, "RIGHT": False}
        # Counters for diagnostics: total HID frames seen, frames the parser
        # accepted as input frames, frames it rejected (wrong header etc).
        self.frames_total: int = 0
        self.frames_decoded: int = 0
        self.frames_rejected: int = 0
        # Latest raw frame regardless of whether the parser accepted it —
        # exposed so the Visualizer can show *something* when decode fails.
        self.last_raw_frame: bytes | None = None
        # Rolling buffer of the most recent raw frames (for offline analysis
        # when the report format is unknown). User can press buttons and then
        # snapshot the buffer via the GUI's "Dump frames" button.
        from collections import deque
        self._recent_frames: deque[bytes] = deque(maxlen=120)
        # First N frames after Start — typically the idle state, useful as
        # a baseline to diff against button-down captures.
        self.baseline_frames: list[bytes] = []

    # ---- subscriptions ----

    def on_state(self, cb: StateCallback) -> None:
        self._state_cbs.append(cb)

    def on_status(self, cb: StatusCallback) -> None:
        self._status_cbs.append(cb)

    def _emit_status(self, msg: str) -> None:
        for cb in list(self._status_cbs):
            try:
                cb(msg)
            except Exception:
                pass

    # ---- properties ----

    @property
    def profile(self) -> Profile:
        return self._profile

    @property
    def gamepad(self) -> VirtualGamepad:
        return self._gamepad

    @property
    def last_state(self) -> ControllerState | None:
        return self._last_state

    def is_running(self) -> bool:
        return self._reader is not None and self._reader.is_running()

    # ---- device handling ----

    def list_devices(self) -> list[DeviceInfo]:
        return enumerate_valve_devices()

    def autopick_device(self) -> DeviceInfo | None:
        return pick_input_interface(self.list_devices())

    def start(self, device: DeviceInfo) -> None:
        self.stop()
        self.frames_total = 0
        self.frames_decoded = 0
        self.frames_rejected = 0
        self._recent_frames.clear()
        self.baseline_frames.clear()
        # Broadcast the disable-lizard / enable-raw-input commands to every
        # Valve interface BEFORE opening the data endpoint. The control and
        # data endpoints are different HID collections on the new Puck.
        try:
            stats = wake_all_valve_interfaces()
            self._emit_status(
                f"Wake: opened {stats['opened']} interface(s), "
                f"sent {stats['commands_sent']} commands, {stats['errors']} errors."
            )
        except Exception as e:
            self._emit_status(f"Wake-broadcast failed: {e}")
        self._emit_status(f"Opening {device.label}...")
        self._reader = HidReader(
            device,
            on_report=self._on_report,
            on_error=self._on_error,
        )
        self._reader.start()
        # Start the arrow-key hook so the D-pad works even when the
        # controller reverts to keyboard-arrow output. The hook also
        # suppresses the OS keyboard event so it doesn't move window focus.
        if self._dpad_kbd_enabled:
            self._start_arrow_hook()
        self._emit_status(f"Bridging: {device.label}. {self._gamepad.status}.")

    def set_dpad_keyboard_capture(self, enabled: bool) -> None:
        """Toggle the keyboard-arrow → virtual D-pad fallback. When the
        bridge is already running, takes effect immediately."""
        self._dpad_kbd_enabled = enabled
        if not enabled:
            self._stop_arrow_hook()
        elif self.is_running():
            self._start_arrow_hook()

    def _start_arrow_hook(self) -> None:
        if self._arrow_hook is not None:
            return
        self._arrow_hook = ArrowKeyHook(on_arrow=self._on_arrow_key, suppress=True)
        if self._arrow_hook.start():
            self._emit_status(
                "D-pad fallback: capturing keyboard arrows → virtual D-pad."
            )
        else:
            self._emit_status("D-pad fallback: failed to install keyboard hook.")
            self._arrow_hook = None

    def _stop_arrow_hook(self) -> None:
        if self._arrow_hook is None:
            return
        self._arrow_hook.stop()
        self._arrow_hook = None
        # Release any pressed d-pad direction on shutdown.
        for k in self._kbd_dpad:
            self._kbd_dpad[k] = False
        try:
            self._gamepad.set_dpad(False, False, False, False)
            self._gamepad.update()
        except Exception:
            pass

    def _on_arrow_key(self, name: str, pressed: bool) -> None:
        """Hook callback (runs on the keyboard-hook thread)."""
        if name not in self._kbd_dpad:
            return
        if self._kbd_dpad[name] == pressed:
            return
        self._kbd_dpad[name] = pressed
        try:
            self._gamepad.set_dpad(
                up=self._kbd_dpad["UP"],
                down=self._kbd_dpad["DOWN"],
                left=self._kbd_dpad["LEFT"],
                right=self._kbd_dpad["RIGHT"],
            )
            self._gamepad.update()
        except Exception as e:
            self._emit_status(f"D-pad keyboard forward error: {e}")

    def stop(self) -> None:
        if self._reader is not None:
            self._reader.stop()
            self._reader = None
        self._stop_arrow_hook()
        try:
            self._gamepad.reset()
        except Exception:
            pass
        self._emit_status("Bridge stopped.")

    def shutdown(self) -> None:
        self.stop()
        try:
            self._gamepad.close()
        except Exception:
            pass

    # ---- profile handling ----

    def load_profile(self, name: str) -> Profile:
        prof = load_profile(name)
        self.set_profile(prof)
        return prof

    def save_current_profile(self) -> None:
        save_profile(self._profile)

    def set_profile(self, profile: Profile) -> None:
        with self._lock:
            self._profile = profile
            self._mapper.set_profile(profile)
        self._emit_status(f"Loaded profile: {profile.name}")

    # ---- callbacks from HidReader ----

    @property
    def recent_frames(self) -> list[bytes]:
        return list(self._recent_frames)

    def _on_report(self, data: bytes) -> None:
        self.frames_total += 1
        self.last_raw_frame = data
        self._recent_frames.append(data)
        if len(self.baseline_frames) < 12:
            self.baseline_frames.append(data)
        state = self._parser.parse(data)
        if state is None:
            self.frames_rejected += 1
            return
        self.frames_decoded += 1
        self._last_state = state
        with self._lock:
            try:
                self._mapper.apply(state)
            except Exception as e:
                self._emit_status(f"Mapper error: {e}")
        for cb in list(self._state_cbs):
            try:
                cb(state)
            except Exception:
                pass

    def _on_error(self, err: BaseException) -> None:
        self._emit_status(f"HID error: {err}")
