"""HID discovery and read loop for Valve controllers.

The new Steam Controller, like the Steam Deck and the original Steam Controller,
uses Valve's vendor ID 0x28DE. We enumerate all HID interfaces from that vendor,
let the user pick one, and stream raw reports off it.

The protocol decode lives in protocol.py; this module is pure transport.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Iterable

import hid

VALVE_VID = 0x28DE

# Known Valve PIDs. Anything else from 0x28DE is treated as a candidate —
# the new Steam Controller's PID may not be in this list yet.
KNOWN_PIDS: dict[int, str] = {
    0x1102: "Steam Controller (wired)",
    0x1142: "Steam Controller (wireless dongle)",
    0x1205: "Steam Deck Controls",
    0x11FF: "Steam Deck Controls (rev)",
    # New Steam Controller (Nov 2025) — confirmed enumerating as
    # "Steam Controller Puck" via the bundled wireless receiver.
    0x1304: "Steam Controller (Puck wireless receiver)",
}


@dataclass(frozen=True)
class DeviceInfo:
    path: bytes
    vendor_id: int
    product_id: int
    serial_number: str
    manufacturer: str
    product: str
    interface_number: int
    usage_page: int
    usage: int

    @property
    def label(self) -> str:
        name = KNOWN_PIDS.get(self.product_id) or self.product or "Valve device"
        suffix = f" [iface {self.interface_number}" if self.interface_number >= 0 else " ["
        # Try to surface the HID collection number from the path (Windows-only)
        # so the user can tell the otherwise-identical interfaces apart.
        try:
            path_s = self.path.decode("ascii", errors="ignore")
            if "&Col" in path_s:
                col = path_s.split("&Col", 1)[1][:2]
                suffix += f" col {col}"
        except Exception:
            pass
        usage = f" usage 0x{self.usage_page:04X}:0x{self.usage:04X}"
        return f"{name} (PID 0x{self.product_id:04X}){suffix}{usage}]"


def enumerate_valve_devices() -> list[DeviceInfo]:
    """Return every HID interface exposed by any Valve device."""
    out: list[DeviceInfo] = []
    for d in hid.enumerate(VALVE_VID, 0):
        out.append(
            DeviceInfo(
                path=d["path"],
                vendor_id=d["vendor_id"],
                product_id=d["product_id"],
                serial_number=d.get("serial_number") or "",
                manufacturer=d.get("manufacturer_string") or "",
                product=d.get("product_string") or "",
                interface_number=d.get("interface_number", -1),
                usage_page=d.get("usage_page", 0),
                usage=d.get("usage", 0),
            )
        )
    return out


def pick_input_interface(devices: Iterable[DeviceInfo]) -> DeviceInfo | None:
    """Pick the most likely input interface from a list of HID endpoints.

    Heuristics (refined against PID 0x1304 / Steam Controller Puck):

    - usage_page 0xFF00 + usage 0x0001 is Valve's vendor input collection
      and is where the gamepad HID frames stream.
    - usage_page 0xFF00 + usage 0x0002 is the *control* endpoint — accepts
      feature reports but does NOT stream input. Penalise it.
    - usage_page 0x0001 + usage 0x0005 is "Generic Desktop / Gamepad" and
      is a reasonable fallback on older Valve hardware.
    - usage_page 0x0001 + usage 0x0006 is "Keyboard" — Windows blocks raw
      reads on those, never pick one.
    - Break ties by lower interface_number, which empirically maps to the
      first gamepad collection on multi-pad receivers (Steam Frame).
    """
    devs = list(devices)
    if not devs:
        return None

    def score(d: DeviceInfo) -> tuple[int, int]:
        s = 0
        if d.usage_page == 0xFF00 and d.usage == 0x0001:
            s += 100
        elif d.usage_page == 0xFF00 and d.usage == 0x0002:
            s -= 50          # control endpoint, never streams input
        elif d.usage_page == 0xFF00:
            s += 60          # other vendor-defined collections
        if d.usage_page == 0x0001 and d.usage == 0x0005:
            s += 40
        if d.usage_page == 0x0001 and d.usage == 0x0006:
            s -= 100         # keyboard — Windows blocks raw read
        # Break ties by *lowest* interface_number — on the Puck, iface 4 is
        # the gamepad while higher ifaces are extra VR-controller channels.
        return (s, -d.interface_number)

    return max(devs, key=score)


# Valve HID command IDs (verified against SDL's open-source Triton driver,
# src/joystick/hidapi/steam/controller_constants.h):
#   0x81  ID_CLEAR_DIGITAL_MAPPINGS     — wipe keyboard/mouse bindings
#   0x85  ID_SET_DEFAULT_DIGITAL_MAPPINGS — restore them
#   0x87  ID_SET_SETTINGS_VALUES        — change a controller setting
#   0x8E  ID_LOAD_DEFAULT_SETTINGS      — reset settings to firmware defaults
#
# SETTING_LIZARD_MODE = 9 in the ControllerSettings enum. Sending a
# SET_SETTINGS_VALUES request with (setting=9, value=0) drops the
# controller out of lizard mode (keyboard/mouse emulation) and into raw
# HID gamepad streaming — including the D-pad bits, which otherwise only
# fire as keyboard arrow keys.
SETTING_LIZARD_MODE = 9
LIZARD_MODE_OFF = 0


def _settings_command(*pairs: tuple[int, int]) -> bytes:
    """Build a feature-report payload for ID_SET_SETTINGS_VALUES (0x87).

    Wire format:
        report_id (0x00)
        ID_SET_SETTINGS_VALUES (0x87)
        length-in-bytes (= count * 3)
        for each setting:
            setting_num (u8)
            setting_value_lo (u8)
            setting_value_hi (u8)
        ... zero-padded to feature-report size (64 bytes).
    """
    body = [0x87, len(pairs) * 3]
    for setting, value in pairs:
        body += [setting & 0xFF, value & 0xFF, (value >> 8) & 0xFF]
    buf = [0x00] + body
    return bytes(buf + [0x00] * (65 - len(buf)))


def _disable_lizard_payload() -> bytes:
    return _settings_command((SETTING_LIZARD_MODE, LIZARD_MODE_OFF))


def wake_all_valve_interfaces(devices: Iterable[DeviceInfo] | None = None) -> dict[str, int]:
    """Broadcast the disable-lizard / enable-raw-input commands to every
    Valve HID interface on the system.

    Why broadcast: on multi-collection controllers (like the new Steam
    Controller Puck) the *control* endpoint that accepts SET_SETTINGS
    commands is a different HID collection from the *data* endpoint that
    streams input. We don't know in advance which is which, so we send the
    commands to every interface we can open and let the controller ignore
    irrelevant ones.

    Returns a dict {"opened": N, "commands_sent": M, "errors": E} for
    diagnostic display.
    """
    if devices is None:
        devices = enumerate_valve_devices()

    def pad64(cmd: list[int]) -> bytes:
        buf = [0x00] + cmd
        return bytes(buf + [0x00] * (65 - len(buf)))

    # Legacy single-byte commands (still useful for the original Steam
    # Controller and as a hint to older firmware revisions).
    legacy_commands = (
        [0x81],                          # CLEAR_DIGITAL_MAPPINGS
    )

    stats = {"opened": 0, "commands_sent": 0, "errors": 0}
    lizard_payload = _disable_lizard_payload()
    for info in devices:
        dev = hid.device()
        try:
            dev.open_path(info.path)
            stats["opened"] += 1
        except Exception:
            stats["errors"] += 1
            continue
        try:
            for cmd in legacy_commands:
                try:
                    dev.send_feature_report(pad64(cmd))
                    stats["commands_sent"] += 1
                except Exception:
                    pass
            # Modern lizard-off via SETTING_LIZARD_MODE — the only command
            # SDL's Triton driver uses, and the one the new Steam Controller
            # actually responds to.
            try:
                dev.send_feature_report(lizard_payload)
                stats["commands_sent"] += 1
            except Exception:
                pass
        finally:
            try:
                dev.close()
            except Exception:
                pass
    return stats


def send_lizard_off_to(devices: Iterable[DeviceInfo]) -> int:
    """Send the SET_SETTINGS_VALUES(LIZARD_MODE_OFF) feature report to every
    interface in `devices`. Returns the number of interfaces the command
    was accepted on.

    BridgeApp's keepalive timer calls this every ~3 seconds because SDL's
    Triton reference driver does the same — firmware otherwise reverts to
    lizard mode after a brief idle.
    """
    payload = _disable_lizard_payload()
    accepted = 0
    for info in devices:
        dev = hid.device()
        try:
            dev.open_path(info.path)
        except Exception:
            continue
        try:
            dev.send_feature_report(payload)
            accepted += 1
        except Exception:
            pass
        finally:
            try:
                dev.close()
            except Exception:
                pass
    return accepted


class HidReader:
    """Background thread that reads raw HID reports and dispatches them.

    Usage:
        reader = HidReader(device_info, on_report=callback)
        reader.start()
        ...
        reader.stop()
    """

    def __init__(
        self,
        info: DeviceInfo,
        on_report: Callable[[bytes], None],
        on_error: Callable[[BaseException], None] | None = None,
        read_size: int = 128,
        poll_timeout_ms: int = 100,
    ) -> None:
        self._info = info
        self._on_report = on_report
        self._on_error = on_error
        self._read_size = read_size
        self._poll_timeout_ms = poll_timeout_ms
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._device: hid.device | None = None

    @property
    def info(self) -> DeviceInfo:
        return self._info

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="HidReader", daemon=True)
        self._thread.start()

    def stop(self, join_timeout: float = 1.0) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(join_timeout)
        self._thread = None

    def _run(self) -> None:
        try:
            self._device = hid.device()
            self._device.open_path(self._info.path)
            self._device.set_nonblocking(True)
            try:
                self._enable_input_reports(self._device)
            except Exception:
                # Best-effort; many devices stream input by default.
                pass

            while not self._stop.is_set():
                data = self._device.read(self._read_size, self._poll_timeout_ms)
                if data:
                    try:
                        self._on_report(bytes(data))
                    except Exception as cb_err:  # don't kill the loop on a bad mapping
                        if self._on_error:
                            self._on_error(cb_err)
        except BaseException as err:
            if self._on_error:
                self._on_error(err)
        finally:
            try:
                if self._device is not None:
                    self._device.close()
            except Exception:
                pass
            self._device = None

    @staticmethod
    def _enable_input_reports(dev: hid.device) -> None:
        """Put the Valve controller into raw-gamepad-HID mode.

        Without this, the controller falls back to "lizard mode" — emitting
        keyboard + mouse events instead of HID gamepad reports. This affects:
          - original Steam Controller (wired and dongle)
          - Steam Deck (when running its built-in input through HID to host)
          - new Steam Controller (Nov 2025) — confirmed needed.

        Sequence used (all standard Valve HID command IDs):
          0x81 — CLEAR_DIGITAL_MAPPINGS (disables keyboard/mouse mappings)
          0x87 0x03 0x08 0x07 0x00 — SET_SETTINGS: enable raw input
          0x87 0x03 0x32 0x00 0x00 — SET_SETTINGS: never idle-disconnect

        All are sent as 64-byte feature reports with leading report-id byte 0.
        Errors are swallowed: some interfaces don't accept feature reports at
        all (e.g. the bare keyboard collection), and that's fine — we just
        want one of the right ones to accept the commands.
        """
        def pad64(cmd: list[int]) -> bytes:
            buf = [0x00] + cmd
            return bytes(buf + [0x00] * (65 - len(buf)))

        commands: list[list[int]] = [
            [0x81],                              # clear digital mappings
            [0x87, 0x03, 0x08, 0x07, 0x00],      # set raw-input setting
            [0x87, 0x03, 0x32, 0x00, 0x00],      # disable idle timeout
            [0x85],                              # default-mouse (ignored if already off)
        ]
        for cmd in commands:
            try:
                dev.send_feature_report(pad64(cmd))
            except Exception:
                pass
