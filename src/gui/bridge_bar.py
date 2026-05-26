"""Top toolbar of the main window — device picker, Start/Stop, profile,
battery, status line. The capture/diff tooling lived here in the old
device_panel; now that the protocol is fully mapped we don't need any of
that."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..app import BridgeApp
from ..hid_device import DeviceInfo


class BridgeBar(QWidget):
    """Top bar above the tab area. Stays in sync with BridgeApp state."""

    profile_changed = Signal(str)

    def __init__(self, app: BridgeApp, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._devices: list[DeviceInfo] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        # Row 1: device + start/stop + scan + battery
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        row1.addWidget(QLabel("Controller:"))
        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row1.addWidget(self.device_combo, 1)

        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setToolTip("Re-enumerate Valve HID devices")
        self.refresh_btn.setFixedWidth(28)
        self.refresh_btn.clicked.connect(self.refresh_devices)
        row1.addWidget(self.refresh_btn)

        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setToolTip(
            "Probe every Valve HID collection for input streams and select "
            "the one that streams gamepad data. Wiggle a stick while it runs."
        )
        self.scan_btn.clicked.connect(self._on_scan)
        row1.addWidget(self.scan_btn)

        self.start_btn = QPushButton("Start Bridge")
        self.start_btn.setStyleSheet(_PRIMARY_BTN_QSS)
        self.start_btn.clicked.connect(self._on_start)
        row1.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        row1.addWidget(self.stop_btn)

        sep1 = QFrame(); sep1.setFrameShape(QFrame.Shape.VLine); sep1.setStyleSheet("color:#444;")
        row1.addWidget(sep1)

        self.battery_label = QLabel("🔋 —")
        self.battery_label.setToolTip("Controller battery (when reported by the firmware)")
        self.battery_label.setMinimumWidth(60)
        row1.addWidget(self.battery_label)

        root.addLayout(row1)

        # Row 2: profile selector + frame indicator
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row2.addWidget(self.profile_combo, 1)
        self.load_profile_btn = QPushButton("Load")
        self.save_profile_btn = QPushButton("Save")
        self.load_profile_btn.clicked.connect(self._on_load_profile)
        self.save_profile_btn.clicked.connect(self._on_save_profile)
        row2.addWidget(self.load_profile_btn)
        row2.addWidget(self.save_profile_btn)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.VLine); sep2.setStyleSheet("color:#444;")
        row2.addWidget(sep2)

        self.status_label = QLabel("Idle")
        self.status_label.setStyleSheet("color:#888;")
        self.status_label.setMinimumWidth(280)
        row2.addWidget(self.status_label)
        root.addLayout(row2)

        # Subscribe to app state.
        self._app.on_status(self._on_app_status)
        self._app.on_profile_change(self._on_app_profile_changed)

        # Initial population.
        self.refresh_devices()
        self.refresh_profiles()
        self._set_status(self._app.gamepad.status)

        # Live frame-rate + battery indicator (1Hz).
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()
        self._last_frames_total = 0

    # ---- subscriptions ----

    def _on_app_status(self, msg: str) -> None:
        self._set_status(msg)

    def _on_app_profile_changed(self, profile) -> None:
        self.refresh_profiles()
        self.profile_combo.setCurrentText(profile.name)

    def _set_status(self, msg: str) -> None:
        self.status_label.setText(msg)
        self.status_label.setToolTip(msg)

    # ---- public ----

    def refresh_devices(self) -> None:
        from .. import settings

        all_devices = self._app.list_devices()
        useful = [
            d for d in all_devices
            if not (d.usage_page == 0x0001 and d.usage == 0x0006)
        ]
        self._devices = useful or all_devices
        self.device_combo.clear()
        if not self._devices:
            self.device_combo.addItem("(no Valve HID devices found)")
            self.device_combo.setEnabled(False)
            self.start_btn.setEnabled(False)
            return
        self.device_combo.setEnabled(True)
        self.start_btn.setEnabled(True)

        saved_path = settings.get("last_good_device_path")
        autopick = self._app.autopick_device()
        autopick_idx = 0
        for i, d in enumerate(self._devices):
            self.device_combo.addItem(d.label, userData=i)
            if saved_path and _path_str(d.path) == saved_path:
                autopick_idx = i
                saved_path = None
            elif autopick is not None and d.path == autopick.path and saved_path is None:
                autopick_idx = i
        self.device_combo.setCurrentIndex(autopick_idx)

    def refresh_profiles(self) -> None:
        from ..profile import list_profiles
        names = list_profiles()
        if "default" not in names:
            names = ["default"] + names
        active = self._app.profile.name
        self.profile_combo.clear()
        self.profile_combo.addItems(names)
        self.profile_combo.setCurrentText(active if active in names else "default")

    # ---- slots ----

    def _on_start(self) -> None:
        from .. import settings
        if not settings.get("last_good_device_path"):
            self._set_status("First launch — running a quick interface scan…")
            self._on_scan()
        idx = self.device_combo.currentData()
        if idx is None or not isinstance(idx, int):
            return
        device = self._devices[idx]
        self._app.start(device)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.refresh_btn.setEnabled(False)
        self.device_combo.setEnabled(False)
        self.scan_btn.setEnabled(False)

    def _on_stop(self) -> None:
        self._app.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.refresh_btn.setEnabled(True)
        self.device_combo.setEnabled(True)
        self.scan_btn.setEnabled(True)
        self.battery_label.setText("🔋 —")

    def _on_scan(self) -> None:
        """Open each candidate Valve HID interface briefly and pick the one
        that streams input. The first time it succeeds we save the choice."""
        import hid
        import time
        from .. import settings

        self._set_status("Scanning interfaces — wiggle a stick on the controller…")
        results: list[tuple[int, int]] = []
        for i, d in enumerate(self._devices):
            try:
                dev = hid.device()
                dev.open_path(d.path)
                dev.set_nonblocking(True)
                # Send the disable-lizard command while we're in there.
                for cmd in ([0x81], [0x87, 0x03, 0x09, 0x00, 0x00]):
                    buf = bytes([0x00] + cmd + [0x00] * (64 - len(cmd)))
                    try: dev.send_feature_report(buf)
                    except Exception: pass
                end = time.monotonic() + 0.8
                n = 0
                while time.monotonic() < end:
                    chunk = dev.read(128, 50)
                    if chunk:
                        n += 1
                dev.close()
                results.append((n, i))
            except Exception:
                pass
        if results:
            n, idx = max(results, key=lambda r: r[0])
            if n > 0:
                best_dev = self._devices[idx]
                settings.set_("last_good_device_path", _path_str(best_dev.path))
                self.device_combo.setCurrentIndex(idx)
                self._set_status(f"Scan: selected {best_dev.label} ({n} frames received).")
                return
        self._set_status(
            "Scan: no interface streamed input. Try waking the controller "
            "(press a button) and scan again."
        )

    def _on_load_profile(self) -> None:
        name = self.profile_combo.currentText().strip()
        if not name:
            return
        try:
            self._app.load_profile(name)
            self.profile_changed.emit(name)
        except FileNotFoundError:
            self._set_status(f"No such profile: {name}")

    def _on_save_profile(self) -> None:
        name = self.profile_combo.currentText().strip()
        if not name:
            return
        prof = self._app.profile
        prof.name = name
        self._app.save_current_profile()
        self.refresh_profiles()
        self._set_status(f"Saved profile: {name}")

    # ---- ticker ----

    def _tick(self) -> None:
        if not self._app.is_running():
            return
        # Frame rate (frames decoded per second).
        total = self._app.frames_total
        rate = total - self._last_frames_total
        self._last_frames_total = total
        decoded = self._app.frames_decoded
        rejected = self._app.frames_rejected
        if total == 0:
            self._set_status("Bridging — no HID frames yet. Press a button on the controller.")
        elif decoded == 0:
            self._set_status(f"Bridging — {total} frames received, parser rejecting all. Try Scan again.")
        else:
            self._set_status(f"Bridging — {rate} fps  ·  {decoded} decoded  ·  {rejected} rejected")

        # Battery.
        s = self._app.last_state
        if s is not None and s.battery_percent >= 0:
            pct = s.battery_percent
            icon = "🔋" if pct > 20 else "🪫"
            self.battery_label.setText(f"{icon} {pct}%")


def _path_str(p: bytes) -> str:
    try:
        return p.decode("ascii", errors="replace")
    except Exception:
        return str(p)


_PRIMARY_BTN_QSS = """
QPushButton {
    background-color: #2d6cdf;
    color: white;
    font-weight: bold;
    padding: 6px 12px;
    border: 1px solid #4f8ff0;
    border-radius: 4px;
}
QPushButton:hover { background-color: #3a7af0; }
QPushButton:disabled { background-color: #335; color: #888; border-color: #445; }
"""
