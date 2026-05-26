# Changelog

All notable changes to SteamPad Bridge.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project tries to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — SDL-aligned protocol + UI overhaul

### Big news

Valve open-sourced the new Steam Controller's driver into SDL in November
2025 (codename **Triton**). The bridge is now aligned with SDL's
authoritative bit map and command set, which fixes several long-standing
issues.

### Added

- **SDL-aligned button map.** All 30 Triton buttons in `PUCK_BUTTON_BITS`,
  including all four D-pad directions in their actual HID positions, real
  MENU and VIEW, real L3/R3 stick clicks, L4/R4 inner-rear paddles, all
  capacitive touch flags (stick, pad, grip).
- **Lizard-mode keepalive.** Re-sends `SET_SETTINGS_VALUES(LIZARD_MODE=OFF)`
  every 3 seconds while bridging — matches SDL's reference driver. The
  D-pad now reliably emits via HID instead of leaking as arrow keys.
- **Rumble passthrough.** When a game vibrates the virtual Xbox pad, the
  bridge forwards it to the controller via haptic feature reports.
- **Auto-switch profile** by foreground process name. Save
  `profiles/<exe>.json`, enable in Settings, the profile loads when you
  Alt-Tab into the game.
- **System-tray icon** + minimize-to-tray on close.
- **Start with Windows** option (HKCU Run key, no admin needed). Launches
  minimized to tray.
- **First-launch wizard** that walks new users through ViGEmBus, pairing,
  and interface scan.
- **Headless / CLI mode**: `python -m src --no-gui [--profile NAME]` for
  power users.
- **Battery percentage** indicator in the top bar (firmware-dependent).
- **Gyro → right-stick aim** is now wired through (was already in the
  profile schema; the parser now populates the IMU bytes).
- **Cleaner GUI**: bridge bar at the top with device + Start/Stop +
  profile + battery + status; three tabs (Mapping / Visualizer /
  Settings). Removed the reverse-engineering capture/diff tooling — no
  longer needed.

### Changed

- The Windows arrow-key keyboard hook is now a *safety net* rather than
  the primary D-pad path — the keepalive normally keeps HID D-pad alive
  on its own.
- `byte 0x02 bit 6` was relabeled VIEW (per SDL). Existing profiles using
  the old "MENU" label still work because the mapper translates flags by
  semantic name.

### Removed

- Capture-now / Capture-in-3s / Dump-frames / Wake-button UI controls.
  The protocol is fully mapped now; these tools served their purpose.
- Old `device_panel.py`. Replaced by the smaller `bridge_bar.py`.

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
