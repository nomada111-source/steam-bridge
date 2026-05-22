"""CLI probe: opens every Valve HID interface in turn, reads for a moment,
and reports which ones actually deliver input bytes. Lets you find the right
endpoint when the device exposes many.

Usage:
    python -m src.probe
    python -m src.probe --duration 2.0
    python -m src.probe --verbose
"""

from __future__ import annotations

import argparse
import sys
import time

import hid

from .hid_device import VALVE_VID, DeviceInfo, enumerate_valve_devices
from .protocol import ReportParser


def probe(duration: float, verbose: bool) -> int:
    devices = enumerate_valve_devices()
    if not devices:
        print("No Valve HID devices found.")
        return 1

    parser = ReportParser()
    print(f"Found {len(devices)} Valve HID interface(s). Probing each for "
          f"{duration:.1f}s. Press buttons / wiggle sticks on the controller "
          f"while this runs.\n")

    best: tuple[int, DeviceInfo | None] = (-1, None)
    for i, info in enumerate(devices):
        print(f"[{i}] {info.label}")
        sample = open_and_read(info, duration, verbose)
        decoded = sum(1 for s in sample if parser.parse(s) is not None)
        print(f"      frames={len(sample):4d}  decoded={decoded:4d}")
        if sample and verbose:
            print(f"      first: {_hex(sample[0])}")
        score = decoded * 1000 + len(sample)
        if score > best[0]:
            best = (score, info)

    print()
    if best[1] is None or best[0] <= 0:
        print("No interface delivered decodable input. The controller may be")
        print("asleep or paired with Steam exclusively. Try opening Steam once")
        print("(it will do firmware/wake handshake) then close it and re-probe.")
        return 2

    print(f"Best candidate:\n  {best[1].label}")
    return 0


def open_and_read(info: DeviceInfo, duration: float, verbose: bool) -> list[bytes]:
    out: list[bytes] = []
    dev = hid.device()
    try:
        dev.open_path(info.path)
        dev.set_nonblocking(True)
        # Try to wake the controller into raw-input streaming. Same set the
        # real bridge sends — see hid_device.HidReader._enable_input_reports.
        def pad64(cmd: list[int]) -> bytes:
            buf = [0x00] + cmd
            return bytes(buf + [0x00] * (65 - len(buf)))

        for cmd in (
            [0x81],
            [0x87, 0x03, 0x08, 0x07, 0x00],
            [0x87, 0x03, 0x32, 0x00, 0x00],
            [0x85],
        ):
            try:
                dev.send_feature_report(pad64(cmd))
            except Exception:
                pass
        end = time.monotonic() + duration
        while time.monotonic() < end:
            chunk = dev.read(128, 50)
            if chunk:
                out.append(bytes(chunk))
                if verbose and len(out) <= 3:
                    print(f"      raw[{len(out)}]: {_hex(bytes(chunk))}")
    except Exception as e:
        print(f"      ERROR opening: {e}")
    finally:
        try:
            dev.close()
        except Exception:
            pass
    return out


def _hex(b: bytes, n: int = 32) -> str:
    return " ".join(f"{x:02x}" for x in b[:n]) + (" ..." if len(b) > n else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Probe Valve HID interfaces for input streams")
    ap.add_argument("--duration", type=float, default=1.5,
                    help="seconds to read from each interface (default: 1.5)")
    ap.add_argument("--verbose", action="store_true", help="dump first raw frame from each interface")
    args = ap.parse_args(argv)
    return probe(args.duration, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
