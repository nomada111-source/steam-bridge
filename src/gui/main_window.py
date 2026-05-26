"""Main window: clean top bar (device, Start/Stop, profile, battery, status)
plus three tabs (Mapping / Visualizer / Settings), system-tray icon with
minimize-to-tray on close.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QMainWindow,
    QMenu,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..app import BridgeApp
from .. import settings
from .bridge_bar import BridgeBar
from .mapping_editor import MappingEditor
from .settings_panel import SettingsPanel
from .visualizer import Visualizer


APP_TITLE = "SteamPad Bridge"


def _make_tray_icon() -> QIcon:
    """Generate a small icon programmatically so we don't need a bundled
    asset (the PyInstaller spec stays simple)."""
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#2d6cdf"))
    p.setPen(QColor("#4f8ff0"))
    p.drawRoundedRect(2, 8, 28, 18, 6, 6)
    p.setBrush(QColor("#ffffff"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(8, 14, 6, 6)
    p.drawEllipse(18, 14, 6, 6)
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, app: BridgeApp, start_hidden: bool = False) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(QSize(960, 640))
        self.setWindowIcon(_make_tray_icon())
        self._app = app
        self._force_quit = False

        # Layout: top bar + tabs.
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self.bridge_bar = BridgeBar(app)
        central_layout.addWidget(self.bridge_bar)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.mapping_editor = MappingEditor(app)
        self.visualizer = Visualizer(app)
        self.settings_panel = SettingsPanel(app)
        self.tabs.addTab(self.mapping_editor, "Mapping")
        self.tabs.addTab(self.visualizer, "Visualizer")
        self.tabs.addTab(self.settings_panel, "Settings")
        central_layout.addWidget(self.tabs, 1)

        self.setCentralWidget(central)

        # Refresh mapping editor when a new profile is loaded from the bar.
        self.bridge_bar.profile_changed.connect(
            lambda _name: self.mapping_editor.load_from_profile()
        )

        # System tray.
        self._tray = self._build_tray()

        # File menu.
        self._build_menu()

        # Apply a subtle stylesheet for a polished look.
        self.setStyleSheet(_QSS)

        if start_hidden:
            pass
        else:
            self.show()

    def _build_tray(self) -> QSystemTrayIcon | None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(self.windowIcon(), self)
        tray.setToolTip(APP_TITLE)
        menu = QMenu()

        show_act = QAction("Show", self)
        show_act.triggered.connect(self._restore_from_tray)
        menu.addAction(show_act)

        start_act = QAction("Start Bridge", self)
        start_act.triggered.connect(self.bridge_bar._on_start)
        menu.addAction(start_act)

        stop_act = QAction("Stop", self)
        stop_act.triggered.connect(self.bridge_bar._on_stop)
        menu.addAction(stop_act)

        menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self._quit)
        menu.addAction(quit_act)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("&File")
        a_hide = QAction("Minimize to tray", self)
        a_hide.triggered.connect(self.hide)
        m.addAction(a_hide)
        m.addSeparator()
        a_quit = QAction("Quit", self)
        a_quit.triggered.connect(self._quit)
        m.addAction(a_quit)

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible():
                self.hide()
            else:
                self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._force_quit = True
        self.close()

    def closeEvent(self, ev) -> None:  # noqa: N802 (Qt naming)
        if (not self._force_quit
                and self._tray is not None
                and bool(settings.get("close_to_tray", True))):
            self.hide()
            if not bool(settings.get("tray_hint_shown", False)):
                self._tray.showMessage(
                    APP_TITLE,
                    "Still running in the tray. Right-click the icon to quit.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3500,
                )
                settings.set_("tray_hint_shown", True)
            ev.ignore()
            return
        self._app.shutdown()
        if self._tray is not None:
            self._tray.hide()
        super().closeEvent(ev)


# Subtle theme touches; Qt's platform style on Win11 is mostly fine on its own.
_QSS = """
QWidget { font-size: 12px; }
QGroupBox {
    border: 1px solid #333;
    border-radius: 5px;
    margin-top: 8px;
    padding-top: 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: #bbb;
}
QTabBar::tab { padding: 6px 14px; }
QPushButton { padding: 5px 10px; }
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox { padding: 3px 6px; }
"""
