# Contributing to SteamPad Bridge

Thanks for considering a contribution.

## Quick start

```powershell
git clone https://github.com/nomada111-source/steampad-bridge.git
cd steampad-bridge
.\setup.bat
python -m tests.smoke_test
.\run.bat
```

Tests must pass before a PR is merged. The smoke test asserts against real
captured HID frames and against SDL's published bit map — those assertions
catch regressions when the protocol mappings are edited.

## High-leverage contributions

1. **Hardware compatibility reports.** Even "everything works" reports help.
   File one through the
   [hardware-compatibility issue template](.github/ISSUE_TEMPLATE/hardware_compatibility.yml).
2. **Confirm or refine button mapping** on revisions other than the reference.
   Reproduce a discrepancy, paste the symptom, and we'll update
   `PUCK_BUTTON_BITS` in `src/protocol.py`.
3. **Rumble pattern improvements.** The current `rumble.py` uses
   `ID_TRIGGER_HAPTIC_PULSE` with conservative parameters. The new
   controller has richer haptic capability — see
   [SDL PR #15558](https://discourse.libsdl.org/t/sdl-fix-steam-controller-2026-triton-rumble-15558/67844)
   for clues on the wire format.
4. **LED control.** SDL has LED report constants; we don't expose them yet.
5. **Auto-profile improvements.** Currently matches `profiles/<exe>.json`
   exactly; could add glob patterns or window-title matching.
6. **Better gyro modes.** Right-stick override is the simplest; "flick stick",
   "ratchet" modes etc. are well-documented in Steam Input docs.

## Style

- Standard library + the deps in `requirements.txt`. Don't add more without
  a strong reason — this is a small tool, not a framework.
- Type hints on public surfaces.
- Match the existing comment style: explain *why*, not what.
- Cite sources (SDL file, Linux driver, capture, etc.) when adding protocol
  knowledge.

## Testing your changes

```powershell
python -m tests.smoke_test
```

50+ checks covering: every confirmed Puck button bit, analog triggers
normalising 0..0x7fff → 0.0..1.0, all four stick axes, the regression guard
that "right-stick TOUCH does NOT register as RSCLICK", and the legacy Steam
Deck format. Add a `check(...)` line for any new bit you map.

```powershell
python -m src.selftest        # confirms the ViGEmBus side without the controller
python -m src.probe --verbose # scans HID interfaces, press a button while it runs
```

## Filing an issue

Use the dedicated templates under **Issues → New** rather than blank issues.
Include your controller's PID (visible in the Controller dropdown), the
status log from the GUI's top bar, and the SteamPad Bridge version number.
