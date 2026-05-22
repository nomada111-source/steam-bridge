# Contributing to SteamPad Bridge

Thanks for considering a contribution. This is a tool that reverse-engineers a
non-public HID protocol, so contributions of test data are as valuable as code.

## Quick start

```powershell
git clone https://github.com/nomada111-source/steampad-bridge.git
cd steampad-bridge
.\setup.bat
python -m tests.smoke_test
.\run.bat
```

Tests must pass before a PR is merged. The smoke test asserts against real
captured HID frames — those assertions catch regressions when the protocol
mappings are edited.

## Most useful contributions

1. **More device captures.** If you have hardware behaviour that differs from
   the reference (a different controller revision, a paired Steam Frame, etc.),
   run the GUI's **Capture now** flow for each button and paste the output in
   an issue. We update `PUCK_BUTTON_BITS` (`src/protocol.py`) accordingly.
2. **Identify unmapped inputs.** LSCLICK/RSCLICK distinct bits, stick-click
   pressure, capacitive-touch indicators — anything not yet locked down. The
   "byte-level diff" output from the capture tool makes this a short job.
3. **Output reports.** Rumble (haptics) and LED control. Valve devices accept
   feature reports via report id `0x87` followed by setting/sub-command bytes.
   Steam Deck rumble uses a per-side amplitude+duration payload; the new
   controller's wire format here is unverified.
4. **Gyro / accelerometer decode.** Raw IMU bytes sit mixed with stick data
   in bytes 0x0a–0x1f; tease them out and route to virtual right-stick or to
   a configurable mouse-style output.
5. **Auto profile switching.** Watch the foreground process and load a
   matching profile from `profiles/<exe-name>.json`.

## Style

- Standard library + the three deps listed in `requirements.txt`. Don't add
  more without a good reason — this is a small tool, not a framework.
- Type hints on public surfaces. No mypy gate yet but the existing code uses
  them.
- Match existing comment style: explain *why*, not what.
- New parser bit mappings go in `PUCK_BUTTON_BITS` with a comment citing the
  capture that confirmed it.

## Testing your changes

```powershell
python -m tests.smoke_test
```

There are 40+ checks including:

- All currently-mapped Puck buttons decode their bit correctly.
- Analog triggers normalize 0..0x7fff → 0.0..1.0.
- Stick offsets translate correctly to ControllerState.
- The byte 0x04 bit 4 "right-stick touched" indicator does NOT register as
  RSCLICK (regression guard).
- Real captured idle frame from the reference hardware parses cleanly.

If you add a new mapping, add a corresponding `check(...)` line so it's locked
in.

## Filing an issue

Please include:

- Your controller's PID (visible in the Device tab dropdown).
- The output of `python -m src.probe --verbose` (with a button pressed during
  the scan).
- The status log from the GUI (right-click the log → copy).
- For wrong/missing button mappings: the full `capture_<button>.txt` file
  written by the **Capture now** flow.
