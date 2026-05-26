# SteamPad Bridge

Use the **new Valve Steam Controller** (Nov 2025, codename **Triton**, PID `0x1304`) on *any* Windows game — including non-Steam games — without launching Steam.

The bridge reads the controller's HID input directly (Bluetooth or the Valve "Puck" 2.4 GHz dongle), then emits a virtual Xbox 360 gamepad through the [ViGEmBus](https://github.com/nefarius/ViGEmBus) kernel driver. Any game that accepts an Xbox controller will see it as one.

PySide6 GUI with per-button remapping, per-game profiles, system-tray operation, rumble passthrough, gyro routing, auto-switching by foreground process, and a one-time setup wizard.

---

## Why does this exist?

Valve's Steam Input only intercepts games launched **through Steam**. For everything else — Epic, GOG, Battle.net, standalone launchers, emulators — the controller is invisible unless it presents as a standard XInput device. SteamPad Bridge makes the new Steam Controller present as a standard Xbox 360 pad to the whole OS.

In November 2025 Valve open-sourced the Triton driver in SDL ([`SDL_hidapi_steam_triton.c`](https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/SDL_hidapi_steam_triton.c)). SteamPad Bridge's parser is aligned with that authoritative reference.

---

## What works

| Input / feature | Status |
|---|---|
| A, B, X, Y face buttons | ✓ |
| MENU, VIEW, STEAM, QUICK_ACCESS system buttons | ✓ |
| L1, R1 shoulders | ✓ |
| L2, R2 analog triggers (0–32767) + digital edges | ✓ |
| L4, R4 inner-rear paddles | ✓ |
| L5, R5 outer-rear paddles | ✓ |
| D-pad (HID + Windows keyboard-hook fallback) | ✓ |
| Left + right sticks (full X/Y range) | ✓ |
| Left + right stick clicks (L3 / R3) | ✓ |
| Capacitive stick / pad / grip touch flags | ✓ |
| Battery percentage (best-effort, firmware-dependent) | ✓ |
| Rumble passthrough (game → controller) | ✓ |
| Gyro → right-stick aim (configurable) | ✓ |
| Auto-switch profile by foreground process name | ✓ |
| Start with Windows + minimize to tray | ✓ |
| Headless / CLI mode (`--no-gui`) | ✓ |
| System-tray icon + close-to-tray | ✓ |
| First-launch setup wizard | ✓ |
| LEDs / advanced haptic patterns | not yet |

---

## Requirements

- Windows 10 / 11
- Python **3.10+** (only if running from source — the prebuilt `.exe` has its own)
- [ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases) — install the latest `ViGEmBus_x.x.x.x_x64.msi`, reboot if it asks
- A Valve Steam Controller (any model, VID `0x28DE`), paired over Bluetooth or via the Valve wireless dongle
- **Steam must NOT be running** while the bridge is active — Steam grabs the HID endpoint exclusively

---

## Setup

### Option A — prebuilt single-file `.exe` (recommended for end users)

1. Install the [ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases) (one-time).
2. Download `SteamPadBridge.exe` from the [latest release](../../releases/latest).
3. Drop it in any folder, double-click to run.
4. Follow the first-launch wizard — it takes ~30 seconds.

No Python install required. The exe creates a `profiles/` subfolder next to itself on first run.

### Option B — run from source

```powershell
git clone https://github.com/nomada111-source/steampad-bridge.git
cd steampad-bridge
.\setup.bat       # creates .venv and installs deps
.\run.bat         # launches the GUI
```

### Option C — build your own .exe

```powershell
.\setup.bat
.\build.bat        # produces dist\SteamPadBridge.exe (~45 MB)
```

Uses PyInstaller with the spec file in `SteamPadBridge.spec`. Committed for reproducibility.

---

## Run

If you downloaded the prebuilt .exe, just double-click `SteamPadBridge.exe`.

From source:

```powershell
.\run.bat
```

### CLI options

| Flag | Purpose |
|---|---|
| `--minimized` | Start hidden, tray-only. Used by auto-start. |
| `--no-gui` | Headless mode — bridge runs until Ctrl-C. |
| `--profile NAME` | Load a specific profile on startup. |
| `--device-index N` | Pre-pick an interface by index. |

Example: `python -m src --no-gui --profile cyberpunk`

---

## Per-game profiles

Save your mapping with a name that matches a game's executable (without `.exe`):

```
profiles/
  default.json
  cyberpunk2077.json
  hades.json
```

In the **Settings** tab, enable **Auto-switch profile by foreground game**. When you Alt-Tab into a game, the bridge auto-loads the matching profile. Alt-Tab out — back to default.

---

## Architecture

```
src/
  __main__.py           entry point — argparse + GUI or headless launch
  app.py                BridgeApp coordinator (no Qt deps, callable from CLI)
  hid_device.py         Valve HID discovery, wake commands (SETTING_LIZARD_MODE=OFF), keepalive helper
  protocol.py           Triton input report parser (54-byte, ID 0x42) + legacy Steam Deck parser
  virtual_gamepad.py    ViGEmBus / vgamepad wrapper + rumble notification
  mapper.py             ControllerState → virtual pad per profile (sticks, triggers, gyro, dpad)
  profile.py            JSON profile load/save with new Triton button names
  keyboard_hook.py      Windows arrow-key intercept for D-pad fallback
  rumble.py             Forward XInput vibration to the controller via haptic feature reports
  foreground_watcher.py Poll the foreground process for auto-profile switching
  autostart.py          Toggle HKCU Run key entry (start with Windows)
  settings.py           Per-machine kv store
  probe.py              CLI: scan HID interfaces for the streaming one
  selftest.py           CLI: drive a fake controller pattern through ViGEmBus
  gui/
    main_window.py      Tray-aware main window, three tabs, close-to-tray
    bridge_bar.py       Top toolbar: device + Start/Stop + profile + battery + status
    mapping_editor.py   Per-button remap + stick/trigger/gyro tuning
    visualizer.py       Live sticks/buttons/triggers/IMU display
    settings_panel.py   Auto-start, auto-profile, rumble, D-pad fallback toggles
    first_run.py        First-launch wizard
profiles/
  default.json
docs/
  protocol.md           HID report format reference (SDL-aligned)
tests/
  smoke_test.py         50+ parser/mapper unit checks
```

---

## D-pad keepalive + keyboard fallback

The Triton firmware emits the D-pad as keyboard arrow keys unless told otherwise. SDL's reference driver sends a `SET_SETTINGS_VALUES(SETTING_LIZARD_MODE=OFF)` feature report on open and re-sends it every ~3 seconds because the firmware reverts otherwise. SteamPad Bridge does the same.

As a safety net, the bridge also installs a Windows low-level keyboard hook (`SetWindowsHookExW` / `WH_KEYBOARD_LL`) that:

1. Intercepts arrow-key presses while bridging.
2. Forwards them to the virtual Xbox D-pad.
3. **Suppresses** the OS keyboard event so it can't move window focus or escape into other apps.

Toggle it on the **Settings** tab if you need keyboard arrows for other apps while the bridge runs.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "No Valve HID devices found" | Controller not paired or dongle unplugged | Re-pair BT / replug dongle, click the ↻ button |
| Status stays "no HID frames yet" | Wrong HID interface picked | Click **Scan** while wiggling a stick — it auto-selects and remembers |
| Games see no input | ViGEmBus not installed | Install ViGEmBus, reboot |
| Pressing A closes Windows / types letters | Controller is in lizard mode | The keepalive should fix it within 3 s. If not, restart the bridge — and confirm Steam isn't running |
| D-pad presses move window focus | Keyboard hook disabled, lizard keepalive failing | Re-enable D-pad keyboard capture in Settings |
| Rumble doesn't trigger | Controller-side rumble format may differ on your firmware | File a hardware compat issue with your PID + firmware info |

---

## Related projects

- **[ViGEmBus](https://github.com/nefarius/ViGEmBus)** — the kernel driver this whole thing depends on
- **[SDL](https://github.com/libsdl-org/SDL)** — Valve's open-source Triton driver lives here
- **[HID Remapper](https://github.com/jfedor2/hid-remapper)** — alternative, hardware-based approach (a USB dongle that remaps)
- **[python-steamcontroller](https://github.com/ynsta/steamcontroller)** — for the original 2015 Steam Controller

---

## Contributing

PRs welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md). The protocol map is data-driven (one dict in `src/protocol.py`), so adding support for hardware revisions or fixing odd quirks is usually a few lines.

Hardware-compatibility reports are especially valuable — file one through the [issue template](.github/ISSUE_TEMPLATE/hardware_compatibility.yml) if your controller behaves differently from the reference.

---

## License

MIT — see [`LICENSE`](LICENSE).

This project is not affiliated with or endorsed by Valve. "Steam", "Steam Controller", "Steam Deck", and "Steam Frame" are trademarks of Valve Corporation.
