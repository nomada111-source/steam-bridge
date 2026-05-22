"""Top-level window: tabs for Device, Mapping, Visualizer."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget

from ..app import BridgeApp
from .device_panel import DevicePanel
from .mapping_editor import MappingEditor
from .visualizer import Visualizer


class MainWindow(QMainWindow):
    def __init__(self, app: BridgeApp) -> None:
        super().__init__()
        self.setWindowTitle("SteamPad Bridge")
        self.resize(QSize(900, 720))
        self._app = app

        tabs = QTabWidget()
        self.device_panel = DevicePanel(app)
        self.mapping_editor = MappingEditor(app)
        self.visualizer = Visualizer(app)

        tabs.addTab(self.device_panel, "Device")
        tabs.addTab(self.mapping_editor, "Mapping")
        tabs.addTab(self.visualizer, "Visualizer")
        self.setCentralWidget(tabs)

        # When the user loads a profile from the Device tab, refresh the
        # Mapping tab's widgets.
        self.device_panel.profile_changed.connect(lambda _: self.mapping_editor.load_from_profile())

        # File menu
        menu = self.menuBar().addMenu("&File")
        quit_act = QAction("Quit", self)
        quit_act.setShortcut(QKeySequence.StandardKey.Quit)
        quit_act.triggered.connect(self.close)
        menu.addAction(quit_act)

    def closeEvent(self, ev) -> None:  # noqa: N802 (Qt naming)
        self._app.shutdown()
        super().closeEvent(ev)
