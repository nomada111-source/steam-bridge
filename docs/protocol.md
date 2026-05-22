# HID protocol notes

The new Steam Controller appears to share the Steam Deck's HID input report
format. This file is where we track what's confirmed vs. assumed and how to
tweak the parser if your hardware reports something different.

## Frame header

Each input report begins (modulo a 0- or 1-byte transport framing prefix) with:

```
01 00 09 40  <seq:4>  <buttons_lo:4>  <buttons_hi:4>  <axes...>
```

`src/protocol.py` scans the first 4 bytes for the `01 00 09 40` signature and
re-bases offsets to it, so the parser tolerates either no prefix or a single
prefix byte without configuration.

## Field offsets

Offsets are relative to the start of the matched header (`anchor = 0`):

| offset | size | field                       |
|--------|------|------------------------------|
| 0      | 4    | header `01 00 09 40`         |
| 4      | 4    | sequence counter (u32 LE)    |
| 8      | 4    | buttons[31:0]   (u32 LE)     |
| 12     | 4    | buttons[63:32]  (u32 LE)     |
| 16     | 2    | left pad X      (i16 LE)     |
| 18     | 2    | left pad Y                   |
| 20     | 2    | right pad X                  |
| 22     | 2    | right pad Y                  |
| 24     | 6    | accel XYZ (3 × i16)          |
| 30     | 6    | gyro XYZ                     |
| 36     | 8    | gyro quaternion (some fw)    |
| 44     | 2    | left trigger (i16, 0..32767) |
| 46     | 2    | right trigger                |
| 48     | 2    | left stick X    (i16 LE)     |
| 50     | 2    | left stick Y                 |
| 52     | 2    | right stick X                |
| 54     | 2    | right stick Y                |

## Button bit assignments

The 64-bit button field (bytes 8..15) packs digital inputs. The bits we use
are listed in `Btn` in `src/protocol.py`. The well-known ones (from public
Steam Deck reverse engineering):

| bit | name              |
|-----|-------------------|
| 0   | R2 (analog trigger digital edge)
| 1   | L2
| 2   | R1
| 3   | L1
| 4   | Y
| 5   | B
| 6   | X
| 7   | A
| 8   | DPAD_UP
| 9   | DPAD_RIGHT
| 10  | DPAD_LEFT
| 11  | DPAD_DOWN
| 12  | VIEW (-)
| 13  | STEAM
| 14  | MENU (+)
| 15  | L5  (rear paddle)
| 16  | R5  (rear paddle)
| 17  | LEFT_PAD_CLICK
| 18  | RIGHT_PAD_CLICK
| 19  | LEFT_PAD_TOUCH
| 20  | RIGHT_PAD_TOUCH
| 22  | LEFT_STICK_CLICK
| 26  | RIGHT_STICK_CLICK
| 27  | QUICK_ACCESS ("..." on Deck; may differ on the new pad)

If a button doesn't light up in the **Visualizer** tab when you press it on
hardware, watch the raw hex dump — the byte that changes tells you the
correct bit. Update `Btn` accordingly.

## Output reports (haptics, rumble, LEDs)

Not yet implemented. Output reports use feature report 0x87 with various
sub-commands; rumble in particular needs a per-side amplitude/duration
payload. Future work.

## References

- SDL2: `src/joystick/hidapi/SDL_hidapi_steamdeck.c`
- Linux: `drivers/hid/hid-steam.c`
- Various community write-ups on the Steam Deck HID protocol
