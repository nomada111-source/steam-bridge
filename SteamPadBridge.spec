# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SteamPad Bridge.

Build:
    pyinstaller SteamPadBridge.spec

Produces:
    dist/SteamPadBridge.exe     — single-file Windows GUI executable

Bundles:
    - All Python source under src/
    - PySide6 (Qt6) GUI runtime
    - hidapi native lib (ships with the cython-hidapi wheel)
    - vgamepad + its bundled ViGEmClient.dll
"""

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


# vgamepad ships ViGEmClient.dll inside its package; pull it in explicitly so
# the frozen exe doesn't try to load it from a venv path that doesn't exist
# on the end user's machine.
vgamepad_datas = collect_data_files("vgamepad", include_py_files=False)
vgamepad_binaries = collect_dynamic_libs("vgamepad")


a = Analysis(
    ["pyinstaller_entry.py"],
    pathex=[],
    binaries=vgamepad_binaries,
    datas=vgamepad_datas,
    hiddenimports=[
        # PyInstaller's static analysis can miss GUI submodules that are
        # only imported via from-string lookups inside Qt; list them so the
        # frozen bundle definitely contains them.
        "src.gui.main_window",
        "src.gui.bridge_bar",
        "src.gui.mapping_editor",
        "src.gui.visualizer",
        "src.gui.settings_panel",
        "src.gui.first_run",
        "src.app",
        "src.protocol",
        "src.mapper",
        "src.profile",
        "src.hid_device",
        "src.virtual_gamepad",
        "src.keyboard_hook",
        "src.settings",
        "src.autostart",
        "src.foreground_watcher",
        "src.rumble",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim Qt modules SteamPad Bridge never imports. PyInstaller's
        # static analyser usually skips unused PySide6 modules already, but
        # an explicit excludes list shaves another few MB off the bundle
        # and guards against transitive pulls.
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQuickWidgets",
        "PySide6.QtNetwork",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtLocation",
        "PySide6.QtPositioning",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialBus",
        "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio",
        "PySide6.QtStateMachine",
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "PySide6.QtTextToSpeech",
        "PySide6.QtWebSockets",
        "PySide6.QtXml",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "tkinter",
        "unittest",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SteamPadBridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # GUI app — no stray cmd window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
