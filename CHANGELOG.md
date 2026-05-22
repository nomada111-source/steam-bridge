# Changelog

All notable changes to SteamPad Bridge.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project tries to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Initial public release

### Added

- HID discovery for any Valve VID `0x28DE` device, with auto-detection of the
  one HID collection on the multi-interface Puck (PID `0x1304`) that actually
  streams gamepad input.
- Parser for the new Steam Controller's 54-byte input report (report id `0x42`).
- Confirmed bit-level mapping for: A, B, X, Y, MENU, QUICK_ACCESS, STEAM,
  L1, R1, L2 (digital + analog), R2 (digital + analog), L5, R5, DPAD_RIGHT.
- Confirmed offsets for both analog sticks (LX, LY, RX, RY as i16 LE).
- Legacy Steam Deck-style report parser kept for compatibility with older
  Valve controllers.
- Virtual Xbox 360 gamepad output via ViGEmBus (`vgamepad`), with a
  `NullGamepad` fallback for systems without the driver so the GUI still
  launches and emits clear status.
- PySide6 GUI with Device / Mapping / Visualizer tabs.
- Live frame counter showing decoded / received / rejected.
- Capture-and-diff tool for reverse-engineering remaining buttons against an
  idle baseline, including a 3-second-delay mode for buttons that emit
  focus-stealing keyboard events.
- Per-machine settings store that remembers the last-known-good HID
  interface so subsequent launches skip the scan step.
- Per-game JSON profiles with default mapping bundled.
- CLI helpers: `python -m src.probe` (HID interface scanner) and
  `python -m src.selftest` (drives a fake controller pattern through
  ViGEmBus to verify the virtual-pad side).
- 40+ unit tests including assertions against real captured frames from
  the new Steam Controller.

### D-pad workaround

The new Steam Controller intermittently emits the D-pad as keyboard arrow
keys regardless of HID mode. To make it work universally, the bridge installs
a Windows low-level keyboard hook (`SetWindowsHookExW` with `WH_KEYBOARD_LL`)
that intercepts arrow-key events, forwards them to the virtual Xbox D-pad,
and suppresses the original event so it can't move window focus.

### Known limitations

- No rumble / haptics output yet.
- Gyro / accelerometer bytes are present in the raw frame but not yet decoded
  or routed.
- LEFT_STICK_CLICK / RIGHT_STICK_CLICK distinct bits are unknown — they may
  not exist as separate signals on the new controller.
- Auto profile switching by foreground process is not implemented.
