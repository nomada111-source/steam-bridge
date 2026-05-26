"""Decode raw HID reports from Valve controllers into ControllerState.

The new Steam Controller, like the Steam Deck, uses Valve's "Deck-style" HID
input report. Layout (after report-id byte):

  offset  size  field
  0       1     report id  (0x01 most commonly)
  1       1     reserved (0x00)
  2       2     report type (little-endian, e.g. 0x09 0x40)
  4       4     sequence counter (uint32 LE)
  8       4     buttons (uint32 LE)  -- low 32 bits
  12      4     more buttons / pad-touch state (uint32 LE)
  16      2     left pad X  (int16 LE, signed)
  18      2     left pad Y
  20      2     right pad X
  22      2     right pad Y
  24      2     accelerometer X
  26      2     accelerometer Y
  28      2     accelerometer Z
  30      2     gyro X
  32      2     gyro Y
  34      2     gyro Z
  36      2     gyro quat W   (some firmwares)
  38      2     gyro quat X
  40      2     gyro quat Y
  42      2     gyro quat Z
  44      2     left trigger  (int16 LE, 0..32767)
  46      2     right trigger
  48      2     left stick X  (int16 LE, signed)
  50      2     left stick Y
  52      2     right stick X
  54      2     right stick Y

This is the published Steam Deck layout. The new Steam Controller is widely
expected to reuse it because both share Valve's HID stack. If a particular
field is off on real hardware, edit the offsets in `DECK_LAYOUT` below or use
the GUI's raw-bytes visualizer to figure out which byte changed.

Sources cross-referenced for this layout:
- SDL2 src/joystick/hidapi/SDL_hidapi_steamdeck.c
- linux drivers/hid/hid-steam.c
- libusb steamdeck reverse-engineering notes
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntFlag


class Btn(IntFlag):
    """Button bitmask. Bits are positions within the 64-bit button field
    (bytes 8..15 of the input report, little-endian).
    """

    R2 = 1 << 0
    L2 = 1 << 1
    R1 = 1 << 2
    L1 = 1 << 3
    Y = 1 << 4
    B = 1 << 5
    X = 1 << 6
    A = 1 << 7
    DPAD_UP = 1 << 8
    DPAD_RIGHT = 1 << 9
    DPAD_LEFT = 1 << 10
    DPAD_DOWN = 1 << 11
    VIEW = 1 << 12          # "Select" / View / -
    STEAM = 1 << 13         # Steam button
    MENU = 1 << 14          # "Start" / Menu / +
    L5 = 1 << 15            # rear paddle L
    R5 = 1 << 16            # rear paddle R
    LEFT_PAD_CLICK = 1 << 17
    RIGHT_PAD_CLICK = 1 << 18
    LEFT_PAD_TOUCH = 1 << 19
    RIGHT_PAD_TOUCH = 1 << 20
    LEFT_STICK_CLICK = 1 << 22
    RIGHT_STICK_CLICK = 1 << 26
    QUICK_ACCESS = 1 << 27  # Steam Deck "..." button; reused as second Steam btn

    # New Steam Controller (Triton, PID 0x1304) extras — these don't exist on
    # the original 2015 Steam Controller. Picked bits beyond the legacy range
    # so we never alias an existing flag.
    L4 = 1 << 32             # inner-rear paddle left  (SDL TRITON_HBUTTON_L4)
    R4 = 1 << 33             # inner-rear paddle right (SDL TRITON_HBUTTON_R4)
    LEFT_STICK_TOUCH = 1 << 34   # capacitive touch on the left stick top
    RIGHT_STICK_TOUCH = 1 << 35  # capacitive touch on the right stick top
    LEFT_GRIP_TOUCH = 1 << 36    # capacitive touch on the left grip
    RIGHT_GRIP_TOUCH = 1 << 37   # capacitive touch on the right grip


@dataclass
class ControllerState:
    """Decoded controller snapshot. All sticks/pads in [-1.0, 1.0],
    triggers in [0.0, 1.0]."""

    seq: int = 0
    buttons: int = 0
    left_stick: tuple[float, float] = (0.0, 0.0)
    right_stick: tuple[float, float] = (0.0, 0.0)
    left_pad: tuple[float, float] = (0.0, 0.0)
    right_pad: tuple[float, float] = (0.0, 0.0)
    left_pad_pressure: float = 0.0
    right_pad_pressure: float = 0.0
    left_trigger: float = 0.0
    right_trigger: float = 0.0
    accel: tuple[float, float, float] = (0.0, 0.0, 0.0)
    gyro: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # Battery percent, 0..100. -1 means "unknown / not decoded".
    battery_percent: int = -1
    raw: bytes = field(default_factory=bytes, repr=False)

    def pressed(self, button: Btn) -> bool:
        return bool(self.buttons & int(button))


# ----- Layout description ---------------------------------------------------


@dataclass(frozen=True)
class DeckLayout:
    """Byte offsets into the HID payload (after the leading report-id byte).

    All offsets are relative to the START of the payload that
    `ReportParser.parse` receives — that includes the report-id byte at
    offset 0.
    """

    report_id: int = 0x01
    header_offset: int = 2
    header_value: int = 0x4009  # bytes 0x09 0x40 LE
    seq_offset: int = 4
    buttons_lo_offset: int = 8
    buttons_hi_offset: int = 12
    left_pad_x: int = 16
    left_pad_y: int = 18
    right_pad_x: int = 20
    right_pad_y: int = 22
    accel_x: int = 24
    accel_y: int = 26
    accel_z: int = 28
    gyro_x: int = 30
    gyro_y: int = 32
    gyro_z: int = 34
    left_trigger: int = 44
    right_trigger: int = 46
    left_stick_x: int = 48
    left_stick_y: int = 50
    right_stick_x: int = 52
    right_stick_y: int = 54
    payload_min_size: int = 56


DECK_LAYOUT = DeckLayout()

# Some Valve transports prepend an additional byte (e.g. the dongle wraps the
# report in a transport frame). The parser scans for the header signature
# `0x01 0x00 0x09 0x40` and re-bases offsets to that anchor, so we tolerate
# 0 or 1 leading framing bytes automatically.
HEADER_SIGNATURE = bytes([0x01, 0x00, 0x09, 0x40])


# ----- New Steam Controller "Puck" format (PID 0x1304) ----------------------
#
# Confirmed empirically: input frames are 54 bytes long, start with report-id
# byte 0x42 ('B'), followed by a u8 sequence counter at offset 1. Bytes 2..9
# read all-zero at rest and almost certainly hold the digital button mask.
# Sticks / triggers / IMU live later in the frame; exact offsets to be
# determined from button-down captures. For now we decode what we know and
# pass the raw bytes through so the GUI can show them.
PUCK_REPORT_ID = 0x42
PUCK_FRAME_LEN = 54


@dataclass(frozen=True)
class PuckLayout:
    """Layout for the new Steam Controller Puck input report (PID 0x1304).

    Aligned with Valve's open-source SDL Triton driver
    (`SDL_hidapi_steam_triton.c`) plus held-frame captures.
    Offsets are relative to the start of the 54-byte frame (byte 0 is the
    0x42 report id).
    """
    report_id_offset: int = 0
    seq_offset: int = 1                # u8 counter

    # Digital buttons occupy bytes 0x02..0x05. Parsed via PUCK_BUTTON_BITS.

    # Analog triggers: i16 little-endian, 0..32767. Confirmed via captures:
    # L2 squeeze fills 0x06..0x07 with 0x7fff; R2 squeeze fills 0x08..0x09.
    left_trigger_offset: int = 0x06
    right_trigger_offset: int = 0x08

    # Analog sticks: i16 little-endian. Confirmed via stick captures.
    left_stick_x: int = 0x0a
    left_stick_y: int = 0x0c
    right_stick_x: int = 0x0e
    right_stick_y: int = 0x10

    # IMU (accelerometer + gyroscope): each axis i16 LE. SDL's
    # `TritonMTUIMU_t` structure follows the sticks. Best-effort offsets
    # — verifiable in the live Visualizer (the values change continuously
    # as you tilt the controller, distinguishable from sticks which sit
    # at zero at rest).
    accel_x: int = 0x12
    accel_y: int = 0x14
    accel_z: int = 0x16
    gyro_x: int = 0x18
    gyro_y: int = 0x1a
    gyro_z: int = 0x1c

    # Touchpad position + pressure (i16 LE / u16 LE). Touchpad position is
    # only meaningful when LEFT_PAD_TOUCH / RIGHT_PAD_TOUCH is set.
    left_pad_x: int = 0x1e
    left_pad_y: int = 0x20
    left_pad_pressure: int = 0x22
    right_pad_x: int = 0x24
    right_pad_y: int = 0x26
    right_pad_pressure: int = 0x28

    # Battery: single u8 in the trailing block, 0..100 percent. The exact
    # byte position is firmware-revision-dependent; we scan a small window
    # at the end of the frame for a plausible 0..100 value (see parser).
    battery_search_start: int = 0x30
    battery_search_end: int = 0x36


PUCK_LAYOUT = PuckLayout()


# ----- Parser ---------------------------------------------------------------


def _i16(buf: bytes, off: int) -> int:
    if off + 2 > len(buf):
        return 0
    return struct.unpack_from("<h", buf, off)[0]


def _u32(buf: bytes, off: int) -> int:
    if off + 4 > len(buf):
        return 0
    return struct.unpack_from("<I", buf, off)[0]


def _norm_axis(v: int, full_scale: int = 32767) -> float:
    """Clamp + normalize a signed int16 into [-1.0, 1.0]."""
    if v >= full_scale:
        return 1.0
    if v <= -full_scale:
        return -1.0
    return v / float(full_scale)


def _norm_trigger(v: int) -> float:
    """Triggers report 0..32767 (or sometimes -32768..32767 on noise).
    Clamp to [0, 1]."""
    if v <= 0:
        return 0.0
    if v >= 32767:
        return 1.0
    return v / 32767.0


class ReportParser:
    """Stateless decoder. Pass the bytes you got from `hid.read()` and you
    get back a `ControllerState`, or None if the report wasn't a recognised
    input frame (some reports are battery/feature responses).

    Supports two report formats:
      - Steam Deck-style (header `01 00 09 40`, 64-byte payload)
      - New Steam Controller Puck (PID 0x1304): 54 bytes, report id 0x42
    """

    def __init__(
        self,
        deck_layout: DeckLayout = DECK_LAYOUT,
        puck_layout: PuckLayout = PUCK_LAYOUT,
    ) -> None:
        self.deck_layout = deck_layout
        self.puck_layout = puck_layout

    def parse(self, data: bytes) -> ControllerState | None:
        if not data:
            return None

        # Try Puck (new Steam Controller) format first: 54-byte frames with
        # report id 0x42 at offset 0.
        if data[0] == PUCK_REPORT_ID and len(data) >= PUCK_FRAME_LEN:
            return self._parse_puck(data)

        # Fall back to Steam Deck format with `01 00 09 40` signature.
        return self._parse_deck(data)

    # ---- Deck (legacy) -----------------------------------------------------

    def _parse_deck(self, data: bytes) -> ControllerState | None:
        anchor = -1
        for start in range(0, min(4, len(data))):
            if data[start : start + len(HEADER_SIGNATURE)] == HEADER_SIGNATURE:
                anchor = start
                break
        if anchor < 0:
            return None

        buf = data[anchor:]
        L = self.deck_layout
        if len(buf) < L.payload_min_size:
            return None

        buttons_lo = _u32(buf, L.buttons_lo_offset)
        buttons_hi = _u32(buf, L.buttons_hi_offset)
        buttons = buttons_lo | (buttons_hi << 32)

        return ControllerState(
            seq=_u32(buf, L.seq_offset),
            buttons=buttons,
            left_stick=(
                _norm_axis(_i16(buf, L.left_stick_x)),
                _norm_axis(_i16(buf, L.left_stick_y)),
            ),
            right_stick=(
                _norm_axis(_i16(buf, L.right_stick_x)),
                _norm_axis(_i16(buf, L.right_stick_y)),
            ),
            left_pad=(
                _norm_axis(_i16(buf, L.left_pad_x)),
                _norm_axis(_i16(buf, L.left_pad_y)),
            ),
            right_pad=(
                _norm_axis(_i16(buf, L.right_pad_x)),
                _norm_axis(_i16(buf, L.right_pad_y)),
            ),
            left_trigger=_norm_trigger(_i16(buf, L.left_trigger)),
            right_trigger=_norm_trigger(_i16(buf, L.right_trigger)),
            accel=(
                _norm_axis(_i16(buf, L.accel_x)),
                _norm_axis(_i16(buf, L.accel_y)),
                _norm_axis(_i16(buf, L.accel_z)),
            ),
            gyro=(
                _norm_axis(_i16(buf, L.gyro_x)),
                _norm_axis(_i16(buf, L.gyro_y)),
                _norm_axis(_i16(buf, L.gyro_z)),
            ),
            raw=buf,
        )

    # ---- Puck (new Steam Controller) --------------------------------------

    def _parse_puck(self, data: bytes) -> ControllerState | None:
        L = self.puck_layout
        # Buttons: walk the bit→Btn translation table.
        buttons = 0
        for (byte_off, bit), btn in PUCK_BUTTON_BITS.items():
            if byte_off < len(data) and data[byte_off] & (1 << bit):
                buttons |= int(btn)

        def axis(off: int) -> float:
            return _norm_axis(_i16(data, off)) if off >= 0 else 0.0

        def u16_pressure(off: int) -> float:
            if off + 2 > len(data):
                return 0.0
            v = struct.unpack_from("<H", data, off)[0]
            return v / 65535.0

        # Best-effort battery scan: look for the first byte in the trailing
        # range that's a plausible 0..100 value. Firmware tends to put
        # battery percent here directly. -1 = unknown.
        battery = -1
        for off in range(L.battery_search_start, min(L.battery_search_end, len(data))):
            b = data[off]
            if 0 <= b <= 100:
                battery = b
                break

        return ControllerState(
            seq=data[L.seq_offset] if L.seq_offset < len(data) else 0,
            buttons=buttons,
            left_stick=(axis(L.left_stick_x), axis(L.left_stick_y)),
            right_stick=(axis(L.right_stick_x), axis(L.right_stick_y)),
            left_pad=(axis(L.left_pad_x), axis(L.left_pad_y)),
            right_pad=(axis(L.right_pad_x), axis(L.right_pad_y)),
            left_pad_pressure=u16_pressure(L.left_pad_pressure),
            right_pad_pressure=u16_pressure(L.right_pad_pressure),
            left_trigger=_norm_trigger(_i16(data, L.left_trigger_offset)),
            right_trigger=_norm_trigger(_i16(data, L.right_trigger_offset)),
            accel=(axis(L.accel_x), axis(L.accel_y), axis(L.accel_z)),
            gyro=(axis(L.gyro_x), axis(L.gyro_y), axis(L.gyro_z)),
            battery_percent=battery,
            raw=data,
        )


# Mapping of (byte_offset, bit_index) → Btn flag for the new Steam Controller
# (codename Triton, PID 0x1304). This map is now grounded in Valve's
# open-source SDL driver (`SDL_hidapi_steam_triton.c`), cross-checked against
# the project's own held-button captures.
#
# In SDL the button field is a 32-bit `ulButtons` little-endian, where bit N
# corresponds to byte (N // 8) + buttons_offset, bit (N % 8). Translating:
#
#   byte 0x02 (SDL bits 0..7)
#     bit 0 = A                    TRITON_LBUTTON_A          (capture_a)
#     bit 1 = B                    TRITON_LBUTTON_B
#     bit 2 = X                    TRITON_LBUTTON_X          (capture_x)
#     bit 3 = Y                    TRITON_LBUTTON_Y          (capture_y)
#     bit 4 = QUICK_ACCESS         TRITON_HBUTTON_QAM        (capture_quick_access)
#     bit 5 = RIGHT_STICK_CLICK    TRITON_LBUTTON_R3
#     bit 6 = VIEW                 TRITON_LBUTTON_VIEW       (the "minus/back" small btn —
#                                                              user reported the controller
#                                                              has no such button, but SDL
#                                                              wires it here. May map to a
#                                                              different physical key on
#                                                              this revision.)
#     bit 7 = R4                   TRITON_HBUTTON_R4 (inner-rear right paddle)
#
#   byte 0x03 (SDL bits 8..15) — RIGHT side, D-pad
#     bit 0 = R5                   TRITON_LBUTTON_R5         (capture_r5)
#     bit 1 = R1                   TRITON_LBUTTON_R          (capture_r1)
#     bit 2 = DPAD_DOWN            TRITON_LBUTTON_DPAD_DOWN  ← HID-mode only
#     bit 3 = DPAD_RIGHT           TRITON_LBUTTON_DPAD_RIGHT (capture_dpad_right)
#     bit 4 = DPAD_LEFT            TRITON_LBUTTON_DPAD_LEFT  ← HID-mode only
#     bit 5 = DPAD_UP              TRITON_LBUTTON_DPAD_UP    ← HID-mode only
#     bit 6 = MENU                 TRITON_LBUTTON_MENU       (the "plus/start" small btn —
#                                                              what the user previously
#                                                              labeled MENU was actually
#                                                              VIEW at byte 0x02 bit 6.)
#     bit 7 = LEFT_STICK_CLICK     TRITON_LBUTTON_L3
#
#   byte 0x04 (SDL bits 16..23) — LEFT side, touchpad/trigger flags
#     bit 0 = STEAM                TRITON_LBUTTON_STEAM      (capture_steam, transient)
#     bit 1 = L4                   TRITON_HBUTTON_L4 (inner-rear left paddle)
#     bit 2 = L5                   TRITON_LBUTTON_L5         (capture_l5)
#     bit 3 = L1                   TRITON_LBUTTON_L          (capture_l1)
#     bit 4 = RIGHT_STICK_TOUCH    TRITON_RIGHT_JOYSTICK_TOUCH
#     bit 5 = RIGHT_PAD_TOUCH      TRITON_RIGHT_TOUCHPAD_TOUCH
#     bit 6 = RIGHT_PAD_CLICK      TRITON_RIGHT_TOUCHPAD_CLICK
#     bit 7 = R2 digital           TRITON_RIGHT_TRIGGER_CLICK (capture_r2)
#
#   byte 0x05 (SDL bits 24..31) — leftover touchpad/trigger/grip flags
#     bit 0 = LEFT_STICK_TOUCH     TRITON_LEFT_JOYSTICK_TOUCH
#     bit 1 = LEFT_PAD_TOUCH       TRITON_LEFT_TOUCHPAD_TOUCH
#     bit 2 = LEFT_PAD_CLICK       TRITON_LEFT_TOUCHPAD_CLICK
#     bit 3 = L2 digital           TRITON_LEFT_TRIGGER_CLICK (capture_l2)
#     bit 4 = RIGHT_GRIP_TOUCH     TRITON_RIGHT_GRIP_TOUCH
#     bit 5 = LEFT_GRIP_TOUCH      TRITON_LEFT_GRIP_TOUCH
#
# Notes:
# - The D-pad bits in byte 0x03 only stream when the controller is in raw
#   HID gamepad mode (lizard mode off). We re-send the SET_SETTINGS_VALUES
#   (SETTING_LIZARD_MODE=OFF) command every 3 seconds from BridgeApp to keep
#   them flowing — see hid_device.send_lizard_off_to and app.BridgeApp's
#   keepalive timer. A keyboard-hook fallback (keyboard_hook.py) handles the
#   case where lizard mode stubbornly stays on.
# - byte 0x02 bit 6 (VIEW) and byte 0x03 bit 6 (MENU) are *both* defined by
#   SDL, but the physical layout on this controller revision exposes only
#   one such button between the sticks. Our default profile maps the one the
#   user can reach to Xbox START — either label works in practice.
PUCK_BUTTON_BITS: dict[tuple[int, int], Btn] = {
    # byte 0x02 — face buttons + low-bit specials
    (0x02, 0): Btn.A,
    (0x02, 1): Btn.B,
    (0x02, 2): Btn.X,
    (0x02, 3): Btn.Y,
    (0x02, 4): Btn.QUICK_ACCESS,
    (0x02, 5): Btn.RIGHT_STICK_CLICK,
    (0x02, 6): Btn.VIEW,
    (0x02, 7): Btn.R4,

    # byte 0x03 — right side + D-pad + system
    (0x03, 0): Btn.R5,
    (0x03, 1): Btn.R1,
    (0x03, 2): Btn.DPAD_DOWN,
    (0x03, 3): Btn.DPAD_RIGHT,
    (0x03, 4): Btn.DPAD_LEFT,
    (0x03, 5): Btn.DPAD_UP,
    (0x03, 6): Btn.MENU,
    (0x03, 7): Btn.LEFT_STICK_CLICK,

    # byte 0x04 — STEAM + left paddles + right touchpad + R2 digital
    (0x04, 0): Btn.STEAM,
    (0x04, 1): Btn.L4,
    (0x04, 2): Btn.L5,
    (0x04, 3): Btn.L1,
    (0x04, 4): Btn.RIGHT_STICK_TOUCH,
    (0x04, 5): Btn.RIGHT_PAD_TOUCH,
    (0x04, 6): Btn.RIGHT_PAD_CLICK,
    (0x04, 7): Btn.R2,

    # byte 0x05 — left touchpad + L2 digital + grip touches
    (0x05, 0): Btn.LEFT_STICK_TOUCH,
    (0x05, 1): Btn.LEFT_PAD_TOUCH,
    (0x05, 2): Btn.LEFT_PAD_CLICK,
    (0x05, 3): Btn.L2,
    (0x05, 4): Btn.RIGHT_GRIP_TOUCH,
    (0x05, 5): Btn.LEFT_GRIP_TOUCH,
}
