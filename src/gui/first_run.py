"""First-launch wizard. Walks the user through ViGEmBus install, controller
pairing, an interface scan, and confirms the bridge end-to-end."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class FirstRunWizard(QDialog):
    """Shown the very first time the app launches (no settings.json yet).

    Each step is a small explainer + a button to validate. The user can Skip
    any step and finish the wizard.
    """

    def __init__(self, app, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to SteamPad Bridge")
        self.resize(560, 380)
        self.setModal(True)
        self._app = app

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        title = QLabel("Welcome — let's get the bridge running.")
        f = QFont(title.font()); f.setPointSize(13); f.setBold(True); title.setFont(f)
        layout.addWidget(title)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self._add_step_vigem()
        self._add_step_pairing()
        self._add_step_scan()
        self._add_step_done()

        # Nav row.
        nav = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self._back)
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self._next)
        nav.addStretch(1)
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)
        layout.addLayout(nav)
        self._update_nav()

    # ---- steps ----

    def _add_step_vigem(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(8)
        l.addWidget(QLabel("<b>Step 1 — Install ViGEmBus driver</b>"))
        l.addWidget(_wrap(
            "SteamPad Bridge presents the Steam Controller to Windows as an Xbox 360 "
            "controller. That requires the open-source ViGEmBus kernel driver. "
            "If you've never installed it, get the latest <code>.msi</code> from:"
        ))
        link = QLabel('<a href="https://github.com/nefarius/ViGEmBus/releases">'
                      'github.com/nefarius/ViGEmBus/releases</a>')
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        l.addWidget(link)
        l.addWidget(_wrap(
            "After installing, reboot if it asks. Already installed? Just click Next."
        ))
        l.addStretch(1)
        self.stack.addWidget(w)

    def _add_step_pairing(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(8)
        l.addWidget(QLabel("<b>Step 2 — Connect your Steam Controller</b>"))
        l.addWidget(_wrap(
            "Pair it over Bluetooth, or plug in the Valve wireless dongle. "
            "<b>Important:</b> quit Steam fully first (system tray → right-click → Exit). "
            "Steam grabs the controller exclusively while running."
        ))
        self.detect_btn = QPushButton("Detect controller")
        self.detect_btn.clicked.connect(self._detect_controller)
        self.detect_status = QLabel("")
        self.detect_status.setWordWrap(True)
        l.addWidget(self.detect_btn)
        l.addWidget(self.detect_status)
        l.addStretch(1)
        self.stack.addWidget(w)

    def _add_step_scan(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(8)
        l.addWidget(QLabel("<b>Step 3 — Pick the right HID interface</b>"))
        l.addWidget(_wrap(
            "The new Steam Controller exposes several HID interfaces; only one streams "
            "gamepad input. Wiggle a stick on the controller, then click Scan — the "
            "bridge will find the right one and remember it for next time."
        ))
        self.scan_btn = QPushButton("Scan now (wiggle a stick)")
        self.scan_btn.clicked.connect(self._scan)
        self.scan_status = QLabel("")
        self.scan_status.setWordWrap(True)
        l.addWidget(self.scan_btn)
        l.addWidget(self.scan_status)
        l.addStretch(1)
        self.stack.addWidget(w)

    def _add_step_done(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(8)
        l.addWidget(QLabel("<b>You're set.</b>"))
        l.addWidget(_wrap(
            "Click <b>Start Bridge</b> on the top bar after closing this dialog. "
            "Press buttons on the controller and watch the Visualizer tab to confirm "
            "everything's working. The default profile maps to a standard Xbox layout — "
            "tweak it on the Mapping tab any time."
        ))
        l.addWidget(_wrap(
            "More tips and per-game profile setup are in the Settings tab."
        ))
        l.addStretch(1)
        self.stack.addWidget(w)

    # ---- nav ----

    def _back(self) -> None:
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))
        self._update_nav()

    def _next(self) -> None:
        last = self.stack.count() - 1
        cur = self.stack.currentIndex()
        if cur == last:
            self.accept()
        else:
            self.stack.setCurrentIndex(cur + 1)
            self._update_nav()

    def _update_nav(self) -> None:
        cur = self.stack.currentIndex()
        self.back_btn.setEnabled(cur > 0)
        if cur == self.stack.count() - 1:
            self.next_btn.setText("Finish")
        else:
            self.next_btn.setText("Next")

    # ---- actions ----

    def _detect_controller(self) -> None:
        devices = self._app.list_devices()
        if not devices:
            self.detect_status.setText(
                "❌  No Valve HID devices found. Confirm Steam is not running "
                "and the controller/dongle is connected."
            )
            return
        first = devices[0]
        self.detect_status.setText(f"✅  Found: {first.label}  ({len(devices)} HID collections)")

    def _scan(self) -> None:
        import hid
        import time
        from .. import settings

        devices = [
            d for d in self._app.list_devices()
            if not (d.usage_page == 0x0001 and d.usage == 0x0006)
        ]
        if not devices:
            self.scan_status.setText("❌  No interfaces to scan. Run Step 2 first.")
            return

        self.scan_status.setText("Scanning… wiggle a stick now.")
        self.scan_btn.setEnabled(False)
        try:
            best_idx = -1
            best_n = 0
            for i, d in enumerate(devices):
                try:
                    dev = hid.device()
                    dev.open_path(d.path)
                    dev.set_nonblocking(True)
                    for cmd in ([0x81], [0x87, 0x03, 0x09, 0x00, 0x00]):
                        buf = bytes([0x00] + cmd + [0x00] * (64 - len(cmd)))
                        try: dev.send_feature_report(buf)
                        except Exception: pass
                    end = time.monotonic() + 0.6
                    n = 0
                    while time.monotonic() < end:
                        chunk = dev.read(128, 50)
                        if chunk:
                            n += 1
                    dev.close()
                    if n > best_n:
                        best_n = n
                        best_idx = i
                except Exception:
                    pass
            if best_idx >= 0 and best_n > 0:
                best_dev = devices[best_idx]
                settings.set_("last_good_device_path",
                              best_dev.path.decode("ascii", errors="replace"))
                self.scan_status.setText(
                    f"✅  Streaming interface found: {best_dev.label} ({best_n} frames). Saved."
                )
            else:
                self.scan_status.setText(
                    "❌  No interface streamed input. Press a button to wake the "
                    "controller and retry."
                )
        finally:
            self.scan_btn.setEnabled(True)


def _wrap(text: str) -> QLabel:
    l = QLabel(text)
    l.setWordWrap(True)
    l.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    l.setOpenExternalLinks(True)
    return l
