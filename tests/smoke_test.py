"""Quick smoke test for the parser + mapper without any hardware.

Run:  python -m tests.smoke_test

It builds a synthetic HID report, feeds it through the parser, and pushes
the result through the mapper into a fake virtual gamepad. Verifies that
button bits, sticks, triggers, and pad routing all behave correctly.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

# Allow running from project root regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mapper import Mapper
from src.profile import Profile
from src.protocol import Btn, ReportParser
from src.virtual_gamepad import NullGamepad


def build_report(
    *,
    buttons: int = 0,
    left_stick: tuple[int, int] = (0, 0),
    right_stick: tuple[int, int] = (0, 0),
    left_trigger: int = 0,
    right_trigger: int = 0,
    left_pad: tuple[int, int] = (0, 0),
    right_pad: tuple[int, int] = (0, 0),
    seq: int = 1,
) -> bytes:
    """Build a minimal Steam-Deck-style input report."""
    buf = bytearray(64)
    buf[0:4] = b"\x01\x00\x09\x40"
    struct.pack_into("<I", buf, 4, seq)
    struct.pack_into("<I", buf, 8, buttons & 0xFFFFFFFF)
    struct.pack_into("<I", buf, 12, (buttons >> 32) & 0xFFFFFFFF)
    struct.pack_into("<hh", buf, 16, *left_pad)
    struct.pack_into("<hh", buf, 20, *right_pad)
    struct.pack_into("<h", buf, 44, left_trigger)
    struct.pack_into("<h", buf, 46, right_trigger)
    struct.pack_into("<hh", buf, 48, *left_stick)
    struct.pack_into("<hh", buf, 52, *right_stick)
    return bytes(buf)


class CapturingGamepad(NullGamepad):
    """NullGamepad variant that records the last values pushed in."""

    def __init__(self) -> None:
        super().__init__("test")
        self.left = (0.0, 0.0)
        self.right = (0.0, 0.0)
        self.lt = 0.0
        self.rt = 0.0
        self.buttons: dict[str, bool] = {}
        self.dpad = (False, False, False, False)
        self.updates = 0

    def set_left_stick(self, x: float, y: float) -> None:
        self.left = (x, y)

    def set_right_stick(self, x: float, y: float) -> None:
        self.right = (x, y)

    def set_left_trigger(self, v: float) -> None:
        self.lt = v

    def set_right_trigger(self, v: float) -> None:
        self.rt = v

    def set_button(self, name: str, pressed: bool) -> None:
        self.buttons[name] = pressed

    def set_dpad(self, up: bool, down: bool, left: bool, right: bool) -> None:
        self.dpad = (up, down, left, right)

    def update(self) -> None:
        self.updates += 1


def approx(a: float, b: float, eps: float = 1e-3) -> bool:
    return abs(a - b) < eps


def run() -> int:
    parser = ReportParser()
    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            failures.append(msg)
            print(f"  FAIL: {msg}")
        else:
            print(f"  ok:   {msg}")

    # --- 1. Empty report decodes to all-zeros state ---
    print("[1] empty report")
    s = parser.parse(build_report())
    assert s is not None, "parser returned None on a valid empty frame"
    check(s.buttons == 0, "no buttons pressed")
    check(s.left_stick == (0.0, 0.0), "left stick centered")
    check(s.right_stick == (0.0, 0.0), "right stick centered")
    check(approx(s.left_trigger, 0.0), "left trigger 0")
    check(approx(s.right_trigger, 0.0), "right trigger 0")

    # --- 2. Buttons round-trip ---
    print("[2] button decode")
    btns = int(Btn.A | Btn.Y | Btn.STEAM | Btn.DPAD_UP)
    s = parser.parse(build_report(buttons=btns))
    check(s.pressed(Btn.A), "A pressed")
    check(s.pressed(Btn.Y), "Y pressed")
    check(s.pressed(Btn.STEAM), "STEAM pressed")
    check(s.pressed(Btn.DPAD_UP), "DPAD_UP pressed")
    check(not s.pressed(Btn.B), "B not pressed")

    # --- 3. Sticks + triggers scale correctly ---
    print("[3] axis scaling")
    s = parser.parse(build_report(left_stick=(32767, -32767), right_trigger=32767))
    check(approx(s.left_stick[0], 1.0), "left stick X saturates to +1")
    check(approx(s.left_stick[1], -1.0), "left stick Y saturates to -1")
    check(approx(s.right_trigger, 1.0), "right trigger saturates to 1.0")

    # --- 4. Mapper drives the virtual gamepad ---
    print("[4] mapper basic round-trip")
    profile = Profile()
    pad = CapturingGamepad()
    mapper = Mapper(profile, pad)

    s = parser.parse(build_report(buttons=int(Btn.A) | int(Btn.R1), right_trigger=32767))
    mapper.apply(s)
    check(pad.buttons.get("A", False), "A propagated to virtual pad")
    check(pad.buttons.get("RB", False), "R1 -> RB propagated")
    check(approx(pad.rt, 1.0), "trigger propagated")
    check(pad.updates == 1, "update() called once per frame")

    # --- 5. Releasing buttons clears them ---
    print("[5] release clears")
    s2 = parser.parse(build_report(buttons=0))
    mapper.apply(s2)
    check(pad.buttons.get("A") is False, "A released")
    check(pad.buttons.get("RB") is False, "RB released")
    check(approx(pad.rt, 0.0), "trigger released")

    # --- 6. Pad routing: right pad -> right stick ---
    print("[6] right pad routes to right stick")
    profile.right_pad_routes_to = "RIGHT"
    s3 = parser.parse(build_report(
        buttons=int(Btn.RIGHT_PAD_TOUCH),
        right_pad=(16000, 16000),
    ))
    mapper.apply(s3)
    check(abs(pad.right[0]) > 0.3, f"right stick X driven by pad (got {pad.right[0]:.3f})")
    check(abs(pad.right[1]) > 0.3, f"right stick Y driven by pad (got {pad.right[1]:.3f})")

    # --- 7. Header anchoring tolerates a single framing prefix byte ---
    print("[7] header anchored with prefix")
    framed = b"\x00" + build_report(buttons=int(Btn.B))
    s4 = parser.parse(framed)
    assert s4 is not None
    check(s4.pressed(Btn.B), "header found after 1-byte prefix")

    # --- 8. Unknown / garbage frames return None ---
    print("[8] junk frame rejected")
    s5 = parser.parse(b"\xff" * 64)
    check(s5 is None, "unrecognised report rejected")

    # --- 9. Puck (PID 0x1304) idle frame from the real device ---
    print("[9] Puck idle frame decodes with no buttons")
    real_idle = bytes.fromhex(
        "42 a7 00 00 00 00 00 00 00 00 6b 01 7b 04 71 02"
        "ba 04 00 00 00 00 00 00 00 00 00 00 00 00 04 bf"
        "e3 b2 40 00 a9 f4 58 3f 00 00 00 00 fe ff 5c 62"
        "1d f7 e9 06 e1 ae".replace(" ", "")
    )
    sr = parser.parse(real_idle)
    check(sr is not None, "Puck idle frame parsed")
    check(sr.buttons == 0, "idle frame reports no buttons")
    check(sr.seq == 0xA7, "idle frame seq=0xA7")
    check(len(real_idle) == 54, "idle frame is 54 bytes")

    # --- 10. Real Puck captures — A, X, Y, R1, L1, LSCLICK, STEAM ---
    print("[10] real Puck button captures decode correctly")

    def puck_frame(b2: int = 0, b3: int = 0, b4: int = 0) -> bytes:
        f = bytearray(54)
        f[0] = 0x42
        f[1] = 0x10
        f[2] = b2
        f[3] = b3
        f[4] = b4
        return bytes(f)

    def puck_frame2(b2: int = 0, b3: int = 0, b4: int = 0, b5: int = 0,
                    lt_i16: int = 0, rt_i16: int = 0) -> bytes:
        import struct
        f = bytearray(54)
        f[0] = 0x42
        f[1] = 0x10
        f[2] = b2; f[3] = b3; f[4] = b4; f[5] = b5
        struct.pack_into("<h", f, 0x06, lt_i16)
        struct.pack_into("<h", f, 0x08, rt_i16)
        return bytes(f)

    sa = parser.parse(puck_frame2(b2=0x01))
    check(sa.pressed(Btn.A), "byte 0x02 bit 0 -> A")
    sx = parser.parse(puck_frame2(b2=0x04))
    check(sx.pressed(Btn.X), "byte 0x02 bit 2 -> X")
    sy = parser.parse(puck_frame2(b2=0x08))
    check(sy.pressed(Btn.Y), "byte 0x02 bit 3 -> Y")
    sb = parser.parse(puck_frame2(b2=0x02))
    check(sb.pressed(Btn.B), "byte 0x02 bit 1 -> B")
    smn = parser.parse(puck_frame2(b2=0x40))
    check(smn.pressed(Btn.MENU), "byte 0x02 bit 6 -> MENU")
    sqa = parser.parse(puck_frame2(b2=0x10))
    check(sqa.pressed(Btn.QUICK_ACCESS), "byte 0x02 bit 4 -> QUICK_ACCESS")
    sr5 = parser.parse(puck_frame2(b3=0x01))
    check(sr5.pressed(Btn.R5), "byte 0x03 bit 0 -> R5")
    sr1 = parser.parse(puck_frame2(b3=0x02))
    check(sr1.pressed(Btn.R1), "byte 0x03 bit 1 -> R1")
    sdr = parser.parse(puck_frame2(b3=0x08))
    check(sdr.pressed(Btn.DPAD_RIGHT), "byte 0x03 bit 3 -> DPAD_RIGHT")
    sst = parser.parse(puck_frame2(b4=0x01))
    check(sst.pressed(Btn.STEAM), "byte 0x04 bit 0 -> STEAM")
    sl5 = parser.parse(puck_frame2(b4=0x04))
    check(sl5.pressed(Btn.L5), "byte 0x04 bit 2 -> L5")
    sl1 = parser.parse(puck_frame2(b4=0x08))
    check(sl1.pressed(Btn.L1), "byte 0x04 bit 3 -> L1")
    # byte 0x04 bit 4 is "right-stick touched" not RSCLICK — should NOT register
    # as RIGHT_STICK_CLICK to avoid false-clicks during normal stick movement.
    srtouch = parser.parse(puck_frame2(b4=0x10))
    check(not srtouch.pressed(Btn.RIGHT_STICK_CLICK),
          "byte 0x04 bit 4 (right-stick touched) does NOT map to RSCLICK")
    sr2 = parser.parse(puck_frame2(b4=0x80))
    check(sr2.pressed(Btn.R2), "byte 0x04 bit 7 -> R2 digital")
    sl2 = parser.parse(puck_frame2(b5=0x08))
    check(sl2.pressed(Btn.L2), "byte 0x05 bit 3 -> L2 digital")

    # Analog triggers — max value 0x7fff
    sat = parser.parse(puck_frame2(lt_i16=0x7fff))
    check(approx(sat.left_trigger, 1.0), "L2 analog at 0x7fff -> 1.0")
    sat = parser.parse(puck_frame2(rt_i16=0x7fff))
    check(approx(sat.right_trigger, 1.0), "R2 analog at 0x7fff -> 1.0")
    sat = parser.parse(puck_frame2(lt_i16=0))
    check(approx(sat.left_trigger, 0.0), "L2 analog at 0 -> 0.0")

    # --- 11. Analog stick offsets confirmed from real captures ---
    print("[11] Puck stick offsets")
    import struct
    def stick_frame(lx=0, ly=0, rx=0, ry=0) -> bytes:
        f = bytearray(54)
        f[0] = 0x42
        struct.pack_into("<hhhh", f, 0x0a, lx, ly, rx, ry)
        return bytes(f)
    sst = parser.parse(stick_frame(lx=0x7fff))
    check(approx(sst.left_stick[0], 1.0), "LX_RIGHT -> left_stick x=+1")
    sst = parser.parse(stick_frame(ly=0x7fff))
    check(approx(sst.left_stick[1], 1.0), "LY_UP -> left_stick y=+1")
    sst = parser.parse(stick_frame(rx=0x7fff))
    check(approx(sst.right_stick[0], 1.0), "RX_RIGHT -> right_stick x=+1")
    sst = parser.parse(stick_frame(ry=0x7fff))
    check(approx(sst.right_stick[1], 1.0), "RY_UP -> right_stick y=+1")
    sst = parser.parse(stick_frame(lx=-32768))
    check(approx(sst.left_stick[0], -1.0), "LX_LEFT -> left_stick x=-1")

    # Multiple held simultaneously
    sm = parser.parse(puck_frame2(b2=0x09, b4=0x08))  # A+Y + L1
    check(sm.pressed(Btn.A) and sm.pressed(Btn.Y) and sm.pressed(Btn.L1),
          "multiple buttons OR together correctly")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed.")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
