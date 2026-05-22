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
    left_trigger: float = 0.0
    right_trigger: float = 0.0
    accel: tuple[float, float, float] = (0.0, 0.0, 0.0)
    gyro: tuple[float, float, float] = (0.0, 0.0, 0.0)
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

    Confirmed empirically against captured frames. Offsets are relative
    to the start of the 54-byte frame (byte 0 is the 0x42 report id).
    """
    report_id_offset: int = 0
    seq_offset: int = 1                # u8 counter

    # Digital buttons occupy bytes 0x02..0x05 (and some bits leak into
    # higher bytes). Parsed via PUCK_BUTTON_BITS below rather than
    # offset-based, because bits aren't contiguous.

    # Analog triggers: i16 little-endian, 0..32767. Confirmed via captures:
    # L2 squeeze fills 0x06..0x07 with 0x7fff; R2 squeeze fills 0x08..0x09.
    left_trigger_offset: int = 0x06
    right_trigger_offset: int = 0x08

    # Analog sticks: i16 little-endian, -32768..32767. Confirmed via captures
    # LX_RIGHT (0x0a..0x0b = 0x7fff), LY_UP (0x0c..0x0d = 0x7fff),
    # RX_RIGHT (0x0e..0x0f = 0x7fff), RX_UP (0x10..0x11 = 0x7fff).
    left_stick_x: int = 0x0a
    left_stick_y: int = 0x0c
    right_stick_x: int = 0x0e
    right_stick_y: int = 0x10


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

        def _maybe_axis(off: int) -> float:
            return _norm_axis(_i16(data, off)) if off >= 0 else 0.0

        return ControllerState(
            seq=data[L.seq_offset] if L.seq_offset < len(data) else 0,
            buttons=buttons,
            left_stick=(_maybe_axis(L.left_stick_x), _maybe_axis(L.left_stick_y)),
            right_stick=(_maybe_axis(L.right_stick_x), _maybe_axis(L.right_stick_y)),
            left_trigger=_norm_trigger(_i16(data, L.left_trigger_offset)),
            right_trigger=_norm_trigger(_i16(data, L.right_trigger_offset)),
            raw=data,
        )


# Mapping of (byte_offset, bit_index) → Btn flag for the new Steam Controller
# (PID 0x1304) Puck input report. Filled in incrementally from capture sessions
# via the GUI's "Capture now" diff tool.
#
# Confirmed via direct capture (one button held at a time, held-frame inspection):
#
#   byte 0x02 — primary face buttons (XInput-style, low nibble = ABXY)
#     bit 0 = A             (capture_a)
#     bit 1 = B             (inferred from XInput convention; not yet captured solo)
#     bit 2 = X             (capture_x)
#     bit 3 = Y             (capture_y)
#     bit 4 = QUICK_ACCESS  (Deck-style "..." second system button — capture_quick_access)
#     bit 6 = MENU          (start / plus — capture_menu)
#   (the new pad has no separate VIEW/back/minus button — only STEAM and MENU)
#
#   byte 0x03 — right-side digital buttons & part of the D-pad
#     bit 0 = R5 (rear right paddle)   (capture_r5)
#     bit 1 = R1 (right shoulder)      (capture_r1)
#     bit 3 = DPAD_RIGHT               (capture_dpad_right)
#
#   byte 0x04 — left-side digital & system buttons
#     bit 0 = STEAM                     (capture_steam, transient — tentative)
#     bit 2 = L5 (rear left paddle)     (capture_l5)
#     bit 3 = L1 (left shoulder)        (capture_l1)
#     bit 4 = right-stick activity      (fires for BOTH RSCLICK and any stick
#                                        push — see captures rsclick, rx_right,
#                                        rx_up — so this is "stick touched"
#                                        not a clean click. NOT MAPPED to
#                                        RIGHT_STICK_CLICK to avoid false
#                                        positives during normal stick use.)
#     bit 7 = R2 digital (full pull)    (capture_r2 — distinct from R2 analog
#                                        at byte 0x08..0x09)
#
#   byte 0x05
#     bit 0 = left-stick activity       (fires for any LX/LY/click — see
#                                        captures lsclick, lx_right, ly_up.
#                                        Same touched-indicator pattern as
#                                        byte 0x04 bit 4 on the right side.)
#     bit 3 = L2 digital (full pull)   (capture_l2 — distinct from L2 analog
#                                        at byte 0x06..0x07)
#     bit 4..5 appear to be "any-right-side" / "any-left-side" activity
#       indicators; they fire alongside multiple buttons. Not mapped.
#
# Still TBD (need clean captures, d-pad requires delayed-capture mode because
# d-pad keys leak as keyboard arrow events that move window focus):
#   LEFT_STICK_CLICK / RIGHT_STICK_CLICK — distinct from the touch indicators
#       above; may not exist as separate bits on the new pad.
#   DPAD_UP / DOWN / LEFT
#   VIEW (back / minus), QUICK_ACCESS
PUCK_BUTTON_BITS: dict[tuple[int, int], Btn] = {
    (0x02, 0): Btn.A,
    (0x02, 1): Btn.B,
    (0x02, 2): Btn.X,
    (0x02, 3): Btn.Y,
    (0x02, 4): Btn.QUICK_ACCESS,
    (0x02, 6): Btn.MENU,
    (0x03, 0): Btn.R5,
    (0x03, 1): Btn.R1,
    (0x03, 3): Btn.DPAD_RIGHT,
    (0x04, 0): Btn.STEAM,
    (0x04, 2): Btn.L5,
    (0x04, 3): Btn.L1,
    (0x04, 7): Btn.R2,
    (0x05, 3): Btn.L2,
}
