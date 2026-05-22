"""Entry point: `python -m src` launches the GUI."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .app import BridgeApp
from .gui.main_window import MainWindow


def main() -> int:
    qt = QApplication(sys.argv)
    qt.setApplicationName("SteamPad Bridge")
    bridge = BridgeApp()
    win = MainWindow(bridge)
    win.show()
    return qt.exec()


if __name__ == "__main__":
    raise SystemExit(main())
