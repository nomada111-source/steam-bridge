"""Rumble passthrough.

When a game vibrates the virtual Xbox pad we expose, vgamepad fires a
notification callback with `large_motor` (low-frequency / left side) and
`small_motor` (high-frequency / right side) values, each 0..255.

We forward those values to the real Steam Controller via a haptic output
report. The exact wire format for the new Steam Controller's rumble
command is still being finalised in upstream SDL (see PR #15558). The
implementation here uses Valve's well-known
`ID_TRIGGER_HAPTIC_PULSE` (0x8F) report — which works on the Steam Deck
and the original Steam Controller — as a best-effort starting point.

If the bytes turn out wrong for a given firmware, rumble simply does
nothing — the input/output bridging stays unaffected.
"""

from __future__ import annotations

import threading
import time
from typing import Iterable

import hid

from .hid_device import DeviceInfo


# Steam Deck/Controller "trigger haptic pulse" report ID.
ID_TRIGGER_HAPTIC_PULSE = 0x8F

# Sides for the pulse command.
SIDE_LEFT = 0x00
SIDE_RIGHT = 0x01


def _haptic_payload(side: int, amplitude: int, period_us: int = 1500, count: int = 1) -> bytes:
    """Build a 64-byte feature-report payload that triggers a haptic pulse.

    Layout (Valve common haptic command):
        report_id (0x00)
        ID_TRIGGER_HAPTIC_PULSE (0x8F)
        length-in-bytes (0x07)
        side (0=left, 1=right)
        period_us_low, period_us_high
        period_us_low, period_us_high   (off-period — same as on for a buzz)
        count_low, count_high
        ... zero-padded to 64 bytes
    """
    amplitude = max(0, min(255, amplitude))
    period_us = max(0, min(0xFFFF, period_us))
    count = max(0, min(0xFFFF, count))
    body = [
        0x00, ID_TRIGGER_HAPTIC_PULSE, 0x07,
        side & 0xFF,
        period_us & 0xFF, (period_us >> 8) & 0xFF,
        period_us & 0xFF, (period_us >> 8) & 0xFF,
        count & 0xFF, (count >> 8) & 0xFF,
    ]
    return bytes(body + [0x00] * (65 - len(body)))


class RumbleForwarder:
    """Sends haptic feature reports to a Valve controller in response to
    XInput vibration values from games.

    The forwarder is rate-limited (~50 Hz) so a game that updates rumble
    every frame doesn't drown the controller's HID endpoint.
    """

    MIN_INTERVAL = 0.020   # seconds — at most 50 sends/sec

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._devices: list[DeviceInfo] = []
        self._last_send = 0.0
        self._last_low = -1
        self._last_high = -1
        self._enabled = True

    def set_devices(self, devices: Iterable[DeviceInfo]) -> None:
        """Update the candidate output endpoints. We try them all on each
        rumble send and the first that accepts is enough."""
        with self._lock:
            self._devices = list(devices)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def feed(self, large_motor: int, small_motor: int) -> None:
        """Receive a vibration update (0..255 each). Called from the
        vgamepad notification thread."""
        if not self._enabled:
            return
        if (large_motor, small_motor) == (self._last_low, self._last_high):
            return
        now = time.monotonic()
        if now - self._last_send < self.MIN_INTERVAL:
            return
        self._last_low = large_motor
        self._last_high = small_motor
        self._last_send = now
        self._dispatch(large_motor, small_motor)

    def _dispatch(self, low: int, high: int) -> None:
        with self._lock:
            devices = list(self._devices)
        if not devices:
            return
        left_payload = _haptic_payload(SIDE_LEFT, low)
        right_payload = _haptic_payload(SIDE_RIGHT, high)
        for info in devices:
            dev = hid.device()
            try:
                dev.open_path(info.path)
            except Exception:
                continue
            try:
                if low > 0:
                    dev.send_feature_report(left_payload)
                if high > 0:
                    dev.send_feature_report(right_payload)
                # One successful send is enough — stop after the first
                # interface that accepted the report.
                break
            except Exception:
                pass
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
