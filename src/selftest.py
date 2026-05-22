"""Smoke-test the ViGEmBus side of the pipeline without needing a controller.

Creates a virtual Xbox 360 gamepad and waggles the sticks + presses A so you
can confirm the virtual pad shows up in Windows Game Controllers / a game.

Usage:
    python -m src.selftest
    python -m src.selftest --duration 5
"""

from __future__ import annotations

import argparse
import math
import time

from .virtual_gamepad import create_gamepad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=4.0,
                    help="seconds to run the self-test pattern (default 4)")
    args = ap.parse_args(argv)

    pad = create_gamepad()
    print(f"Gamepad status: {pad.status}")
    if not pad.available:
        print("ViGEmBus is not available — install the driver from")
        print("  https://github.com/nefarius/ViGEmBus/releases")
        return 2

    print("Open Windows 'Game Controllers' (joy.cpl) — you should see a new")
    print("'Xbox 360 Controller' that responds to the pattern below.")
    print()
    print(f"Running pattern for {args.duration:.1f}s...")

    start = time.monotonic()
    last_a = False
    while True:
        t = time.monotonic() - start
        if t >= args.duration:
            break
        # Circular left stick, opposite-phase right stick, ramped triggers.
        pad.set_left_stick(math.cos(t * 2.0), math.sin(t * 2.0))
        pad.set_right_stick(-math.cos(t * 2.0), -math.sin(t * 2.0))
        pad.set_left_trigger(0.5 + 0.5 * math.sin(t * 3.0))
        pad.set_right_trigger(0.5 + 0.5 * math.cos(t * 3.0))
        a = (int(t) % 2) == 0
        if a != last_a:
            pad.set_button("A", a)
            last_a = a
        pad.update()
        time.sleep(0.016)

    pad.reset()
    pad.close()
    print("Done. If you saw a controller wiggle in joy.cpl, the virtual gamepad side works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
