"""Settings tab — toggles for auto-start, auto-profile, D-pad keyboard
capture, rumble, and gyro routing."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..app import BridgeApp


class SettingsPanel(QWidget):
    def __init__(self, app: BridgeApp, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app

        from .. import settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ---- Startup group ----
        startup_box = QGroupBox("Startup")
        startup_layout = QVBoxLayout(startup_box)
        self.autostart_chk = QCheckBox("Start with Windows (launch minimized to tray)")
        self.autostart_chk.setToolTip(
            "Adds an entry to HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run. "
            "No admin needed. Uncheck to remove."
        )
        try:
            from .. import autostart
            self.autostart_chk.setChecked(autostart.is_enabled())
        except Exception:
            self.autostart_chk.setEnabled(False)
            self.autostart_chk.setText("Start with Windows (unavailable on this platform)")
        self.autostart_chk.toggled.connect(self._on_autostart_toggled)
        startup_layout.addWidget(self.autostart_chk)

        self.minimize_chk = QCheckBox("Close button minimizes to tray (don't quit)")
        self.minimize_chk.setChecked(bool(settings.get("close_to_tray", True)))
        self.minimize_chk.toggled.connect(
            lambda v: settings.set_("close_to_tray", bool(v))
        )
        startup_layout.addWidget(self.minimize_chk)
        layout.addWidget(startup_box)

        # ---- Gameplay group ----
        play_box = QGroupBox("Gameplay")
        play_layout = QVBoxLayout(play_box)

        self.rumble_chk = QCheckBox("Forward game rumble to the controller")
        self.rumble_chk.setChecked(bool(settings.get("rumble_enabled", True)))
        self.rumble_chk.toggled.connect(self._on_rumble_toggled)
        play_layout.addWidget(self.rumble_chk)

        self.auto_profile_chk = QCheckBox(
            "Auto-switch profile by foreground game (matches profiles/<exe>.json)"
        )
        self.auto_profile_chk.setChecked(bool(settings.get("auto_profile", False)))
        self.auto_profile_chk.toggled.connect(self._on_auto_profile_toggled)
        play_layout.addWidget(self.auto_profile_chk)

        self.dpad_kbd_chk = QCheckBox(
            "Capture D-pad as keyboard arrows (fallback, also suppresses arrows to other apps)"
        )
        self.dpad_kbd_chk.setChecked(bool(settings.get("dpad_kbd", True)))
        self.dpad_kbd_chk.setToolTip(
            "Safety net for firmware that drops back to lizard mode. "
            "The bridge re-sends the disable-lizard command every 3 seconds, "
            "but this hook catches anything that slips through."
        )
        self.dpad_kbd_chk.toggled.connect(self._on_dpad_kbd_toggled)
        play_layout.addWidget(self.dpad_kbd_chk)

        layout.addWidget(play_box)

        # ---- Tips ----
        tips = QLabel(
            "Tips:\n"
            "• Save a profile named after a game's exe (without .exe) to auto-switch when you Alt-Tab to it.\n"
            "• Make sure Steam is fully quit — it grabs the controller exclusively while running.\n"
            "• Install ViGEmBus driver first: https://github.com/nefarius/ViGEmBus/releases"
        )
        tips.setStyleSheet("color:#888;")
        tips.setWordWrap(True)
        tips.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        tips.setOpenExternalLinks(True)
        layout.addWidget(tips)

        layout.addStretch(1)

        # Apply persisted settings on startup.
        self._apply_initial()

    # ---- slots ----

    def _on_autostart_toggled(self, enabled: bool) -> None:
        try:
            from .. import autostart
            autostart.set_enabled(enabled)
        except Exception:
            pass

    def _on_rumble_toggled(self, enabled: bool) -> None:
        from .. import settings
        settings.set_("rumble_enabled", bool(enabled))
        self._app.set_rumble_enabled(enabled)

    def _on_auto_profile_toggled(self, enabled: bool) -> None:
        from .. import settings
        settings.set_("auto_profile", bool(enabled))
        self._app.set_auto_profile(enabled)

    def _on_dpad_kbd_toggled(self, enabled: bool) -> None:
        from .. import settings
        settings.set_("dpad_kbd", bool(enabled))
        self._app.set_dpad_keyboard_capture(enabled)

    def _apply_initial(self) -> None:
        """Push the persisted settings into the live BridgeApp so they take
        effect even on the very first launch after restoring from disk."""
        self._app.set_rumble_enabled(self.rumble_chk.isChecked())
        self._app.set_auto_profile(self.auto_profile_chk.isChecked())
        self._app.set_dpad_keyboard_capture(self.dpad_kbd_chk.isChecked())
