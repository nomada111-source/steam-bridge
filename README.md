# SteamPad Bridge

Use the **new Valve Steam Controller** (Nov 2025, PID `0x1304`) on *any* Windows game — including non-Steam games — without launching Steam.

The bridge reads the controller's HID input directly (Bluetooth or the Valve "Puck" 2.4 GHz dongle), then emits a virtual Xbox 360 gamepad through the [ViGEmBus](https://github.com/nefarius/ViGEmBus) kernel driver. Any game that supports an Xbox controller will see it as one.

A PySide6 GUI handles device discovery, live input visualization, per-button remapping, per-game profiles, and the capture/diff tooling used to reverse-engineer the new controller's HID report format.

---

## Why does this exist?

Valve's Steam Input only intercepts games launched **through Steam**. For everything else — Epic, GOG, Battle.net, standalone launchers, emulators — the controller is invisible unless it presents as a standard XInput device. SteamPad Bridge makes the new Steam Controller present as a standard Xbox 360 pad to the whole OS.

---

## Status

The new Steam Controller's HID report format isn't publicly documented. This project reverse-engineered it using a built-in capture/diff tool. As of this release the following are confirmed working:

| Input | Status |
|---|---|
| A, B, X, Y face buttons | ✓ |
| L1, R1 shoulders | ✓ |
| L2, R2 analog triggers (0–32767) | ✓ |
| L2, R2 digital (full-pull edge) | ✓ |
| L5, R5 rear paddles | ✓ |
| Left stick (X/Y, full range) | ✓ |
| Right stick (X/Y, full range) | ✓ |
| D-pad (via keyboard-arrow intercept fallback) | ✓ |
| STEAM, MENU, QUICK_ACCESS | ✓ |
| Rumble / haptics | ✗ not yet |
| Gyro / accelerometer (output) | ✗ raw frames decoded but not wired to virtual pad yet |
| Touchpad clicks (if present) | ? |

The new controller does **not** have a separate VIEW/back/minus button — only STEAM and MENU. Stick-click bits aren't yet identified; they may not exist as separate signals on this controller.

---

## Requirements

- Windows 10 / 11
- Python **3.10+** (tested with 3.14)
- [ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases) — install the latest `ViGEmBus_x.x.x.x_x64.msi`, reboot if it asks
- A Valve Steam Controller (any model, VID `0x28DE`), paired over Bluetooth or via the Valve wireless dongle
- **Steam must NOT be running** while the bridge is active — Steam grabs the HID endpoint exclusively

---

## Setup

### Option A — prebuilt single-file `.exe` (recommended for end users)

1. Install the [ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases) (one-time).
2. Download `SteamPadBridge.exe` from the [latest release](../../releases/latest).
3. Drop it in any folder, double-click to run.

That's it — no Python install required. The exe creates a `profiles/` subfolder next to itself on first run to store mappings.

### Option B — run from source (for hacking on the code)

```powershell
git clone https://github.com/nomada111-source/steampad-bridge.git
cd steampad-bridge
.\setup.bat
```

`setup.bat` creates a `.venv\` and installs `hidapi`, `vgamepad`, and `PySide6`.

Manual install:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
```

### Option C — build your own .exe

```powershell
.\setup.bat        # one-time, sets up .venv
.\build.bat        # produces dist\SteamPadBridge.exe (~45 MB)
```

Uses PyInstaller with the spec file in `SteamPadBridge.spec` (commit-tracked, so the build is reproducible).

---

## Run

If you downloaded the prebuilt .exe, just double-click `SteamPadBridge.exe`.

From source:

```powershell
.\run.bat
```

Or:

```powershell
.\.venv\Scripts\activate
python -m src
```

The GUI opens with three tabs:

- **Device** — pick HID interface (auto-detected after first successful scan), Start/Stop bridge, save/load profiles, run captures.
- **Mapping** — per-button remapping, stick deadzone/saturation/sensitivity, trigger thresholds, gyro tuning.
- **Visualizer** — live stick/pad dots, trigger bars, button grid lights, raw HID hex dump.

### Typical first-run flow

1. Exit Steam (system tray → right-click → Exit).
2. Pair the controller (Bluetooth) or plug in the Puck dongle.
3. `.\run.bat`.
4. On the **Device** tab, click **Start Bridge**. If no interface is remembered yet, the GUI will automatically scan the controller's 9 HID collections to find the one that streams gamepad input and persist the choice.
5. Check the green **Frames** counter — it should rise as you press buttons.
6. Launch any game. It will see an Xbox 360 controller.

---

## Helper scripts

```powershell
# Confirm the ViGEmBus side works without needing the controller.
# Watch joy.cpl ("Game Controllers") to see the virtual pad wiggle.
python -m src.selftest

# Probe every HID interface the controller exposes and report which one
# streams gamepad input. Wiggle a stick / press buttons while it runs.
python -m src.probe --verbose

# Parser + mapper unit tests (40+ checks, including assertions against real
# captured frames from the new Steam Controller).
python -m tests.smoke_test
```

---

## Architecture

```
src/
  __main__.py          entry point — launches the Qt GUI
  app.py               BridgeApp coordinator (no Qt deps, callable from CLI too)
  hid_device.py        Valve HID discovery + background read loop + wake commands
  protocol.py          input report parsers (Steam Deck legacy + new Puck PID 0x1304)
  virtual_gamepad.py   ViGEmBus / vgamepad wrapper with a Null fallback
  mapper.py            ControllerState → virtual pad per profile
  profile.py           JSON profile load/save
  keyboard_hook.py     Windows low-level keyboard hook for D-pad fallback
  settings.py          per-machine kv store (remembers the working HID interface)
  probe.py             CLI: scan HID interfaces to find the streaming one
  selftest.py          CLI: drive a fake controller pattern through ViGEmBus
  gui/
    main_window.py
    device_panel.py    device picker, start/stop, status, capture tools
    mapping_editor.py  per-button remap + tuning
    visualizer.py      live input view with raw hex dump
profiles/
  default.json
docs/
  protocol.md          HID report format notes (Deck-style + new Puck format)
tests/
  smoke_test.py
```

---

## How the new controller was decoded

The new Steam Controller doesn't share the Steam Deck's input report format. It uses a 54-byte frame with report id `0x42`. Mapping out which byte/bit was which button was done with the built-in capture tool:

1. Bridge starts → first 12 frames captured as **idle baseline**.
2. User types a label (e.g. `A`), holds the corresponding button on the controller, clicks **Capture now**.
3. The tool snapshots the rolling buffer (most recent ~30 frames) and diffs each byte against the baseline.
4. Cleanly-disjoint bytes are flagged `BUTTON?`; a bit-level analysis identifies the specific bit that changed.

For buttons that emit keyboard events (like the D-pad, which Windows reads as arrow keys), the **Capture in 3s** countdown mode bypasses the focus-theft problem — you hold the button on the controller and the snapshot fires automatically.

All findings, with confidence levels and unresolved questions, are documented in [`docs/protocol.md`](docs/protocol.md) and as comments above `PUCK_BUTTON_BITS` in [`src/protocol.py`](src/protocol.py).

---

## D-pad keyboard fallback

The new Steam Controller usually emits the D-pad as keyboard arrow keys regardless of whether the HID lizard-mode is disabled. When **Capture D-pad from keyboard arrows** is checked in the Device tab (default on), the bridge installs a Windows low-level keyboard hook (`SetWindowsHookExW`) that:

1. Intercepts arrow-key presses.
2. Forwards them to the virtual Xbox D-pad.
3. **Suppresses** the OS keyboard event so it can't move window focus or escape into other apps.

The hook only runs while the bridge is active. Uncheck the option if you need arrow keys for other apps while bridging.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "No Valve HID devices found" | Controller not paired or dongle unplugged | Re-pair BT / replug dongle, hit **Refresh** |
| Frames counter stays at 0 | Wrong HID interface picked | Click **Scan interfaces** while pressing buttons; it auto-selects and remembers |
| Frames counter rising but 0 decoded | Wrong report format for this controller | Use **Capture now** / paste me your captures via an Issue; the parser is data-driven |
| Pressing A closes Windows / types letters | Controller is in "lizard mode" (keyboard emulation) | Click **Wake / Disable Lizard**, then try again |
| Bridge says "ViGEmBus unavailable" | Driver not installed | Install ViGEmBus, reboot |
| Steam-related errors | Steam is running and has the HID endpoint exclusive | Right-click Steam tray icon → Exit |
| D-pad moves window focus | Keyboard hook not enabled or failed to install | Check **Capture D-pad from keyboard arrows**; may require admin |

---

## Contributing

Patches welcome. Particularly useful:

- **Confirm or refine the button/bit map** on your hardware. Use the capture tool and paste the output in an issue.
- **Identify stick-click bits**, if they exist on your controller — none were found on the reference hardware.
- **Rumble / haptics output reports** — the Steam Deck protocol uses output report ID 0x8F with a per-side amplitude payload; the new controller likely uses similar but unverified.
- **Gyro / accelerometer**: raw IMU bytes are in the report (around offsets 0x0c–0x1f mixed with stick data — see notes in `docs/protocol.md`), but not yet decoded or routed to the virtual gamepad.
- **Auto-profile-switch** by foreground process name.

Run `python -m tests.smoke_test` before opening a PR — there are real captured frames in the test fixtures that the parser must keep decoding correctly.

---

## License

MIT — see [`LICENSE`](LICENSE).

This project is not affiliated with or endorsed by Valve. "Steam", "Steam Controller", "Steam Deck", and "Steam Frame" are trademarks of Valve Corporation.
