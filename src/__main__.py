"""Entry point: `python -m src` launches the GUI; flags below adjust behaviour.

    --minimized        Start hidden, only the tray icon visible. Used by
                       auto-start so the bridge doesn't pop a window at login.
    --no-gui           Headless mode: start the bridge and block until killed.
                       Useful for hotkey-launched scripts and services.
    --profile NAME     Load a specific profile on startup.
    --device-index N   Pre-select a HID interface by index (skip the scan).
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from .app import BridgeApp


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="steampad-bridge")
    p.add_argument("--minimized", action="store_true",
                   help="Start hidden in the system tray.")
    p.add_argument("--no-gui", action="store_true",
                   help="Run without the GUI. Bridge keeps running until Ctrl-C / kill.")
    p.add_argument("--profile", type=str, default=None,
                   help="Profile name to load on startup.")
    p.add_argument("--device-index", type=int, default=None,
                   help="Pre-select a HID interface by index (mainly for CI/scripts).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.no_gui:
        return _run_headless(args)
    return _run_gui(args)


# ---- GUI mode --------------------------------------------------------------


def _run_gui(args) -> int:
    from PySide6.QtWidgets import QApplication

    from . import settings
    from .gui.first_run import FirstRunWizard
    from .gui.main_window import MainWindow

    qt = QApplication(sys.argv)
    qt.setApplicationName("SteamPad Bridge")
    qt.setQuitOnLastWindowClosed(False)   # tray keeps us alive

    app = BridgeApp()
    if args.profile:
        try:
            app.load_profile(args.profile)
        except FileNotFoundError:
            print(f"warning: profile '{args.profile}' not found", file=sys.stderr)

    start_hidden = bool(args.minimized)
    win = MainWindow(app, start_hidden=start_hidden)

    # First-run wizard if this is a fresh install (no remembered device).
    if not start_hidden and settings.get("last_good_device_path") is None:
        wiz = FirstRunWizard(app, win)
        wiz.exec()
        settings.set_("first_run_done", True)

    return qt.exec()


# ---- Headless mode ---------------------------------------------------------


def _run_headless(args) -> int:
    app = BridgeApp()
    if args.profile:
        try:
            app.load_profile(args.profile)
        except FileNotFoundError:
            print(f"warning: profile '{args.profile}' not found", file=sys.stderr)

    devices = app.list_devices()
    useful = [d for d in devices if not (d.usage_page == 0x0001 and d.usage == 0x0006)]
    if not useful:
        print("error: no Valve HID devices found", file=sys.stderr)
        return 2

    pick = (useful[args.device_index]
            if args.device_index is not None and 0 <= args.device_index < len(useful)
            else (app.autopick_device() or useful[0]))

    app.on_status(lambda m: print(f"[bridge] {m}"))
    app.start(pick)
    print(f"Bridge running on: {pick.label}. Press Ctrl-C to stop.")

    stop = [False]

    def on_signal(signum, frame):
        print("\nstopping...")
        stop[0] = True

    signal.signal(signal.SIGINT, on_signal)
    try:
        signal.signal(signal.SIGTERM, on_signal)
    except AttributeError:
        pass

    while not stop[0]:
        time.sleep(0.25)

    app.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
