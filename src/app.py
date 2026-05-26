"""Coordinator. Owns the HID reader, the parser, the mapper, and the gamepad.

The GUI talks to this via a thin signal-callback interface (no Qt deps here)
so the bridge can also be driven from a CLI or tests.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Callable

from .foreground_watcher import ForegroundWatcher
from .hid_device import (
    DeviceInfo,
    HidReader,
    enumerate_valve_devices,
    pick_input_interface,
    send_lizard_off_to,
    wake_all_valve_interfaces,
)
from .keyboard_hook import ArrowKeyHook
from .mapper import Mapper
from .profile import Profile, list_profiles, load_profile, save_profile
from .protocol import ControllerState, ReportParser
from .rumble import RumbleForwarder
from .virtual_gamepad import VirtualGamepad, create_gamepad


StateCallback = Callable[[ControllerState], None]
StatusCallback = Callable[[str], None]
ProfileCallback = Callable[[Profile], None]


class BridgeApp:
    """Owns the long-lived bridge state. UI talks to it through callbacks."""

    KEEPALIVE_INTERVAL = 3.0   # seconds — re-send lizard-off (matches SDL)

    def __init__(self) -> None:
        self._reader: HidReader | None = None
        self._parser = ReportParser()
        self._gamepad: VirtualGamepad = create_gamepad()
        self._profile: Profile = load_profile("default")
        self._mapper = Mapper(self._profile, self._gamepad)
        self._state_cbs: list[StateCallback] = []
        self._status_cbs: list[StatusCallback] = []
        self._profile_cbs: list[ProfileCallback] = []
        self._last_state: ControllerState | None = None
        self._lock = threading.Lock()

        # D-pad keyboard fallback (safety net for firmware that drops back
        # to lizard mode despite our keepalive).
        self._arrow_hook: ArrowKeyHook | None = None
        self._dpad_kbd_enabled: bool = True
        self._kbd_dpad = {"UP": False, "DOWN": False, "LEFT": False, "RIGHT": False}

        # Keepalive: SDL's Triton driver re-sends SETTING_LIZARD_MODE=OFF
        # every ~3 seconds because firmware reverts otherwise. We do the same.
        self._keepalive_timer: threading.Timer | None = None

        # Frame counters for diagnostics.
        self.frames_total: int = 0
        self.frames_decoded: int = 0
        self.frames_rejected: int = 0
        self.last_raw_frame: bytes | None = None
        # Short rolling buffer for the live Visualizer.
        self._recent_frames: deque[bytes] = deque(maxlen=64)

        # Rumble passthrough — game vibrates virtual pad → we forward to
        # the real controller.
        self._rumble = RumbleForwarder()
        self._gamepad.register_rumble(self._on_rumble)

        # Auto-profile-switch: poll foreground process, load
        # profiles/<exe>.json when the active window changes.
        self._foreground: ForegroundWatcher | None = None
        self._auto_profile_enabled: bool = False

    # ---- subscriptions ----

    def on_state(self, cb: StateCallback) -> None:
        self._state_cbs.append(cb)

    def on_status(self, cb: StatusCallback) -> None:
        self._status_cbs.append(cb)

    def on_profile_change(self, cb: ProfileCallback) -> None:
        self._profile_cbs.append(cb)

    def _emit_status(self, msg: str) -> None:
        for cb in list(self._status_cbs):
            try:
                cb(msg)
            except Exception:
                pass

    def _emit_profile(self) -> None:
        for cb in list(self._profile_cbs):
            try:
                cb(self._profile)
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

    @property
    def recent_frames(self) -> list[bytes]:
        return list(self._recent_frames)

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
        # Broadcast disable-lizard / enable-raw-input to every Valve interface
        # BEFORE opening the data endpoint. The control and data endpoints are
        # different HID collections on the new Puck.
        try:
            stats = wake_all_valve_interfaces()
            self._emit_status(
                f"Wake: opened {stats['opened']} interface(s), "
                f"{stats['commands_sent']} commands sent, {stats['errors']} errors."
            )
        except Exception as e:
            self._emit_status(f"Wake-broadcast failed: {e}")
        self._emit_status(f"Opening {device.label}…")
        self._reader = HidReader(
            device,
            on_report=self._on_report,
            on_error=self._on_error,
        )
        self._reader.start()
        # Make the rumble forwarder aware of every Valve interface (one will
        # accept haptic reports — we don't know which in advance).
        self._rumble.set_devices(self.list_devices())
        # Arrow-key safety net for the D-pad.
        if self._dpad_kbd_enabled:
            self._start_arrow_hook()
        # 3-second keepalive for SETTING_LIZARD_MODE=OFF.
        self._start_keepalive()
        # Foreground process watcher (if enabled).
        if self._auto_profile_enabled:
            self._start_foreground_watcher()
        self._emit_status(f"Bridging: {device.label}. {self._gamepad.status}.")

    def stop(self) -> None:
        if self._reader is not None:
            self._reader.stop()
            self._reader = None
        self._stop_arrow_hook()
        self._stop_keepalive()
        self._stop_foreground_watcher()
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

    # ---- d-pad keyboard fallback ----

    def set_dpad_keyboard_capture(self, enabled: bool) -> None:
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
            self._emit_status("D-pad fallback active: keyboard arrows → virtual D-pad.")
        else:
            self._emit_status("D-pad fallback: keyboard hook failed to install.")
            self._arrow_hook = None

    def _stop_arrow_hook(self) -> None:
        if self._arrow_hook is None:
            return
        self._arrow_hook.stop()
        self._arrow_hook = None
        for k in self._kbd_dpad:
            self._kbd_dpad[k] = False
        try:
            self._gamepad.set_dpad(False, False, False, False)
            self._gamepad.update()
        except Exception:
            pass

    def _on_arrow_key(self, name: str, pressed: bool) -> None:
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

    # ---- lizard-mode keepalive ----

    def _start_keepalive(self) -> None:
        self._stop_keepalive()
        self._schedule_keepalive()

    def _schedule_keepalive(self) -> None:
        if not self.is_running():
            return
        self._keepalive_timer = threading.Timer(self.KEEPALIVE_INTERVAL, self._keepalive_tick)
        self._keepalive_timer.daemon = True
        self._keepalive_timer.start()

    def _keepalive_tick(self) -> None:
        if not self.is_running():
            return
        try:
            send_lizard_off_to(enumerate_valve_devices())
        except Exception as e:
            self._emit_status(f"Keepalive error: {e}")
        finally:
            self._schedule_keepalive()

    def _stop_keepalive(self) -> None:
        t = self._keepalive_timer
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass
        self._keepalive_timer = None

    # ---- rumble passthrough ----

    def set_rumble_enabled(self, enabled: bool) -> None:
        self._rumble.set_enabled(enabled)

    def _on_rumble(self, large_motor: int, small_motor: int) -> None:
        # Called from vgamepad's notification thread. RumbleForwarder is
        # internally thread-safe and rate-limited.
        self._rumble.feed(large_motor, small_motor)

    # ---- foreground watcher / auto profile ----

    def set_auto_profile(self, enabled: bool) -> None:
        self._auto_profile_enabled = enabled
        if enabled and self.is_running():
            self._start_foreground_watcher()
        elif not enabled:
            self._stop_foreground_watcher()

    def _start_foreground_watcher(self) -> None:
        if self._foreground is not None:
            return
        self._foreground = ForegroundWatcher(on_change=self._on_foreground_change)
        self._foreground.start()
        self._emit_status("Auto profile: watching foreground process.")

    def _stop_foreground_watcher(self) -> None:
        if self._foreground is None:
            return
        self._foreground.stop()
        self._foreground = None

    def _on_foreground_change(self, exe_name: str | None) -> None:
        if not exe_name:
            return
        # Only switch if a profile with that exact name exists.
        if exe_name in list_profiles():
            try:
                self.load_profile(exe_name)
                self._emit_status(f"Auto-loaded profile '{exe_name}' for foreground process.")
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
        self._emit_profile()

    # ---- callbacks from HidReader ----

    def _on_report(self, data: bytes) -> None:
        self.frames_total += 1
        self.last_raw_frame = data
        self._recent_frames.append(data)
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
