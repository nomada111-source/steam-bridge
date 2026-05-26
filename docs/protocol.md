# HID protocol notes

The new Steam Controller (codename **Triton**, USB VID `0x28DE` / PID `0x1304`)
uses a 54-byte HID input report with report ID `0x42`. It does NOT share the
Steam Deck's `01 00 09 40` layout.

In November 2025 Valve open-sourced the controller driver into SDL. The
authoritative reference is now
[`SDL_hidapi_steam_triton.c`](https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/SDL_hidapi_steam_triton.c)
along with [`controller_constants.h`](https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/steam/controller_constants.h).
SteamPad Bridge's parser is aligned with that source. The original
reverse-engineered map (built from held-frame captures) agreed with SDL on
most face buttons and triggers but was wrong about VIEW/MENU and missing
several digital flags; both are fixed.

The legacy Steam Deck / 2015 Steam Controller path is still supported (see
`DECK_LAYOUT` in `src/protocol.py`) for those older devices.

## Triton report format (PID 0x1304)

```
byte 0      report id (0x42)
byte 1      sequence counter (u8, wraps at 256)
bytes 2-5   ulButtons[31:0] (u32 little-endian, see bit table below)
bytes 6-7   left  trigger analog (i16 LE, 0..32767)
bytes 8-9   right trigger analog (i16 LE, 0..32767)
bytes 10-11 left  stick X (i16 LE, -32768..32767)
bytes 12-13 left  stick Y
bytes 14-15 right stick X
bytes 16-17 right stick Y
bytes 18-53 IMU (gyro/accel), touchpads, and other state — partly decoded
```

## Button bit assignments (verified vs SDL Triton driver)

| SDL bit | Byte / bit | Name                            | Notes |
|--------:|-----------:|----------------------------------|-------|
|       0 |    0x02 b0 | A                               | face |
|       1 |    0x02 b1 | B                               | face |
|       2 |    0x02 b2 | X                               | face |
|       3 |    0x02 b3 | Y                               | face |
|       4 |    0x02 b4 | QUICK_ACCESS (QAM)              | Steam Deck "..." analogue |
|       5 |    0x02 b5 | RIGHT_STICK_CLICK (R3)          | |
|       6 |    0x02 b6 | VIEW                            | small "minus / back" |
|       7 |    0x02 b7 | R4                              | inner-rear right paddle |
|       8 |    0x03 b0 | R5                              | outer-rear right paddle |
|       9 |    0x03 b1 | R1                              | right shoulder |
|      10 |    0x03 b2 | DPAD_DOWN                       | HID only — see lizard-mode note |
|      11 |    0x03 b3 | DPAD_RIGHT                      | HID only |
|      12 |    0x03 b4 | DPAD_LEFT                       | HID only |
|      13 |    0x03 b5 | DPAD_UP                         | HID only |
|      14 |    0x03 b6 | MENU                            | small "plus / start" |
|      15 |    0x03 b7 | LEFT_STICK_CLICK (L3)           | |
|      16 |    0x04 b0 | STEAM                           | |
|      17 |    0x04 b1 | L4                              | inner-rear left paddle |
|      18 |    0x04 b2 | L5                              | outer-rear left paddle |
|      19 |    0x04 b3 | L1                              | left shoulder |
|      20 |    0x04 b4 | RIGHT_STICK_TOUCH (capacitive)  | |
|      21 |    0x04 b5 | RIGHT_PAD_TOUCH (capacitive)    | |
|      22 |    0x04 b6 | RIGHT_PAD_CLICK                 | |
|      23 |    0x04 b7 | R2 (digital, full-pull edge)    | analog at bytes 8-9 |
|      24 |    0x05 b0 | LEFT_STICK_TOUCH (capacitive)   | |
|      25 |    0x05 b1 | LEFT_PAD_TOUCH (capacitive)     | |
|      26 |    0x05 b2 | LEFT_PAD_CLICK                  | |
|      27 |    0x05 b3 | L2 (digital, full-pull edge)    | analog at bytes 6-7 |
|      28 |    0x05 b4 | RIGHT_GRIP_TOUCH (capacitive)   | |
|      29 |    0x05 b5 | LEFT_GRIP_TOUCH (capacitive)    | |

The bit positions are stored at `src/protocol.py:PUCK_BUTTON_BITS` for direct
editing.

## Lizard mode — important

Out of the box, the Steam Controller emits keyboard + mouse events instead
of streaming HID gamepad data — most visibly, the **D-pad fires as keyboard
arrow keys**. SDL calls this state "lizard mode".

To disable it, send a feature report with command `ID_SET_SETTINGS_VALUES`
(`0x87`), setting number `SETTING_LIZARD_MODE` (= 9), value
`LIZARD_MODE_OFF` (= 0). Wire layout:

```
report_id  0x00
type       0x87   ID_SET_SETTINGS_VALUES
length     0x03   (count * 3 bytes follow)
setting    0x09   SETTING_LIZARD_MODE
value_lo   0x00   LIZARD_MODE_OFF (low byte)
value_hi   0x00   (high byte)
... 0-padded to 64 bytes
```

The new controller's firmware **reverts to lizard mode automatically** if
this command isn't re-sent periodically. SDL re-sends it every ~3 seconds;
SteamPad Bridge does the same via `BridgeApp._schedule_keepalive`.

If for any reason the keepalive doesn't take effect (older firmware, an
intervening Steam process holding the control endpoint, etc.), the bridge
also installs a Windows low-level keyboard hook that intercepts arrow keys
and forwards them to the virtual Xbox D-pad. See `src/keyboard_hook.py`.

## Output reports (haptics, rumble, LEDs)

Not yet implemented in this project. SDL's Triton driver shows:

- `ID_TRIGGER_HAPTIC_PULSE` (`0x8F`) — single-pulse haptic on one side
- Rumble uses a richer command payload — see SDL PR #15558 ("Fix Steam
  Controller 2026 (triton) rumble") for the exact bytes

PRs welcome.

## References

- [SDL Triton driver source](https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/SDL_hidapi_steam_triton.c)
- [SDL controller_constants.h](https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/steam/controller_constants.h)
- [SDL PR #15528 — touchpads + grip sense](https://github.com/libsdl-org/SDL/pull/15528)
- [SDL PR #15558 — rumble fix](https://discourse.libsdl.org/t/sdl-fix-steam-controller-2026-triton-rumble-15558/67844)
- [Linux `hid-steam.c`](https://elixir.bootlin.com/linux/latest/source/drivers/hid/hid-steam.c) — older but still useful for the original Steam Controller
- [HID Remapper Steam Controller support](https://www.techpowerup.com/349296/steam-controller-gets-hid-remapper-support-for-3rd-party-compatibility) — alternative project that uses a USB middleman device
