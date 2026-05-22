"""Live input visualizer.

Shows two analog sticks as draggable dots in a circle, two trigger bars,
a gyro readout, a button grid that lights up when buttons are pressed, and
a hex dump of the latest raw HID report (useful when tuning the parser).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..app import BridgeApp
from ..profile import ALL_BUTTONS, BTN_NAME_TO_FLAG
from ..protocol import Btn, ControllerState


class StickView(QWidget):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self._x = 0.0
        self._y = 0.0
        self.setMinimumSize(140, 140)

    def set_value(self, x: float, y: float) -> None:
        if (x, y) == (self._x, self._y):
            return
        self._x, self._y = x, y
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h) - 8
        cx, cy = w / 2, h / 2
        r = size / 2

        p.setPen(QPen(QColor("#555"), 1))
        p.setBrush(QBrush(QColor("#1c1c1c")))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(QPen(QColor("#333"), 1))
        p.drawLine(int(cx - r), int(cy), int(cx + r), int(cy))
        p.drawLine(int(cx), int(cy - r), int(cx), int(cy + r))

        # dot
        dx = cx + self._x * r
        dy = cy - self._y * r  # invert: HID Y up is positive in our state
        p.setBrush(QBrush(QColor("#4fa3ff")))
        p.setPen(QPen(QColor("#80c8ff"), 1))
        p.drawEllipse(QPointF(dx, dy), 7, 7)

        p.setPen(QColor("#aaa"))
        f = QFont(p.font()); f.setPointSize(8); p.setFont(f)
        p.drawText(QRectF(0, 0, w, 16), Qt.AlignmentFlag.AlignCenter, self._label)


class Visualizer(QWidget):
    def __init__(self, app: BridgeApp, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._last: ControllerState | None = None

        layout = QVBoxLayout(self)

        # --- sticks + pads ---
        top = QHBoxLayout()
        self.left_stick = StickView("L stick")
        self.right_stick = StickView("R stick")
        self.left_pad = StickView("L pad")
        self.right_pad = StickView("R pad")
        for w in (self.left_stick, self.right_stick, self.left_pad, self.right_pad):
            top.addWidget(w)
        layout.addLayout(top)

        # --- triggers ---
        trig_box = QGroupBox("Triggers")
        trig_l = QHBoxLayout(trig_box)
        self.lt_bar = QProgressBar(); self.lt_bar.setRange(0, 1000); self.lt_bar.setFormat("LT %p%")
        self.rt_bar = QProgressBar(); self.rt_bar.setRange(0, 1000); self.rt_bar.setFormat("RT %p%")
        trig_l.addWidget(self.lt_bar)
        trig_l.addWidget(self.rt_bar)
        layout.addWidget(trig_box)

        # --- gyro ---
        gyro_box = QGroupBox("Gyro / accelerometer")
        gyro_l = QHBoxLayout(gyro_box)
        self.gyro_label = QLabel("gyro: 0.00, 0.00, 0.00    accel: 0.00, 0.00, 0.00")
        gyro_l.addWidget(self.gyro_label)
        layout.addWidget(gyro_box)

        # --- buttons grid ---
        btn_box = QGroupBox("Buttons")
        grid = QGridLayout(btn_box)
        self._btn_labels: dict[str, QLabel] = {}
        all_names = [n for n in ALL_BUTTONS] + ["RIGHT_PAD_TOUCH", "LEFT_PAD_TOUCH"]
        cols = 4
        for i, name in enumerate(all_names):
            lab = QLabel(name)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setStyleSheet(_btn_style(False))
            grid.addWidget(lab, i // cols, i % cols)
            self._btn_labels[name] = lab
        layout.addWidget(btn_box)

        # --- raw report hex dump ---
        raw_box = QGroupBox("Raw HID report (latest)")
        raw_l = QVBoxLayout(raw_box)
        self.raw_view = QPlainTextEdit()
        self.raw_view.setReadOnly(True)
        self.raw_view.setMaximumBlockCount(8)
        f = QFont("Consolas"); f.setStyleHint(QFont.StyleHint.Monospace); f.setPointSize(9)
        self.raw_view.setFont(f)
        raw_l.addWidget(self.raw_view)
        layout.addWidget(raw_box, 1)

        # Pull from app at 60Hz instead of reacting per-event — keeps Qt happy.
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _refresh(self) -> None:
        s = self._app.last_state
        # Show the raw frame regardless of whether decoding worked. This is
        # what lets the user (or us) figure out the report format when the
        # parser is rejecting everything.
        raw = self._app.last_raw_frame
        if raw is not None:
            self.raw_view.setPlainText(_hexdump(raw))

        if s is None or s is self._last:
            return
        self._last = s

        self.left_stick.set_value(*s.left_stick)
        self.right_stick.set_value(*s.right_stick)
        self.left_pad.set_value(*s.left_pad)
        self.right_pad.set_value(*s.right_pad)

        self.lt_bar.setValue(int(s.left_trigger * 1000))
        self.rt_bar.setValue(int(s.right_trigger * 1000))

        self.gyro_label.setText(
            f"gyro: {s.gyro[0]:+.2f}, {s.gyro[1]:+.2f}, {s.gyro[2]:+.2f}    "
            f"accel: {s.accel[0]:+.2f}, {s.accel[1]:+.2f}, {s.accel[2]:+.2f}"
        )

        # Buttons
        for name, lab in self._btn_labels.items():
            flag = BTN_NAME_TO_FLAG.get(name)
            if flag is not None:
                pressed = s.pressed(flag)
            elif name == "RIGHT_PAD_TOUCH":
                pressed = s.pressed(Btn.RIGHT_PAD_TOUCH)
            elif name == "LEFT_PAD_TOUCH":
                pressed = s.pressed(Btn.LEFT_PAD_TOUCH)
            else:
                pressed = False
            lab.setStyleSheet(_btn_style(pressed))


def _btn_style(active: bool) -> str:
    if active:
        return (
            "background-color: #2d6cdf; color: white; padding: 4px 6px;"
            "border: 1px solid #4f8ff0; border-radius: 4px;"
        )
    return (
        "background-color: #222; color: #888; padding: 4px 6px;"
        "border: 1px solid #333; border-radius: 4px;"
    )


def _hexdump(data: bytes, width: int = 16) -> str:
    rows: list[str] = []
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        hex_bytes = " ".join(f"{b:02x}" for b in chunk)
        ascii_bytes = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        rows.append(f"{i:04x}  {hex_bytes:<{width*3}}  {ascii_bytes}")
    return "\n".join(rows)
