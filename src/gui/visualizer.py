"""Live input visualizer.

Sticks/pads as draggable dots, trigger bars, gyro+accel readout, a button
grid that lights up when buttons are pressed, and a small battery line.
The raw-frame hex dump panel was removed in 0.2 — the protocol layout is
now SDL-aligned and no longer needs in-app debugging.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..app import BridgeApp
from ..profile import ALL_BUTTONS, BTN_NAME_TO_FLAG
from ..protocol import Btn, ControllerState


class StickView(QWidget):
    """A circular display for a stick or pad position in [-1, 1]^2."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self._x = 0.0
        self._y = 0.0
        self._active = False
        self.setMinimumSize(120, 120)

    def set_value(self, x: float, y: float, active: bool = True) -> None:
        if (x, y, active) == (self._x, self._y, self._active):
            return
        self._x, self._y, self._active = x, y, active
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h) - 12
        cx, cy = w / 2, h / 2
        r = size / 2

        # Background ring.
        p.setPen(QPen(QColor("#3a3a3a"), 1))
        p.setBrush(QBrush(QColor("#1c1c1c")))
        p.drawEllipse(QPointF(cx, cy), r, r)
        # Crosshair.
        p.setPen(QPen(QColor("#2a2a2a"), 1))
        p.drawLine(int(cx - r), int(cy), int(cx + r), int(cy))
        p.drawLine(int(cx), int(cy - r), int(cx), int(cy + r))

        # Dot.
        dx = cx + self._x * r
        dy = cy - self._y * r
        dot_color = "#4fa3ff" if self._active else "#506070"
        p.setBrush(QBrush(QColor(dot_color)))
        p.setPen(QPen(QColor("#80c8ff"), 1))
        p.drawEllipse(QPointF(dx, dy), 7, 7)

        # Label.
        p.setPen(QColor("#aaa"))
        f = QFont(p.font()); f.setPointSize(8); p.setFont(f)
        p.drawText(0, 0, w, 16, Qt.AlignmentFlag.AlignCenter, self._label)


class Visualizer(QWidget):
    def __init__(self, app: BridgeApp, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._last: ControllerState | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Sticks + pads.
        top = QHBoxLayout()
        top.setSpacing(8)
        self.left_stick = StickView("L stick")
        self.right_stick = StickView("R stick")
        self.left_pad = StickView("L pad")
        self.right_pad = StickView("R pad")
        for w in (self.left_stick, self.right_stick, self.left_pad, self.right_pad):
            top.addWidget(w)
        layout.addLayout(top)

        # Triggers.
        trig_box = QGroupBox("Triggers")
        trig_l = QHBoxLayout(trig_box)
        self.lt_bar = QProgressBar(); self.lt_bar.setRange(0, 1000); self.lt_bar.setFormat("LT %p%")
        self.rt_bar = QProgressBar(); self.rt_bar.setRange(0, 1000); self.rt_bar.setFormat("RT %p%")
        trig_l.addWidget(self.lt_bar)
        trig_l.addWidget(self.rt_bar)
        layout.addWidget(trig_box)

        # IMU.
        imu_box = QGroupBox("Motion (gyro / accelerometer)")
        imu_l = QHBoxLayout(imu_box)
        self.gyro_label = QLabel("gyro: 0.00, 0.00, 0.00")
        self.accel_label = QLabel("accel: 0.00, 0.00, 0.00")
        self.gyro_label.setStyleSheet("color:#bbb; font-family: monospace;")
        self.accel_label.setStyleSheet("color:#bbb; font-family: monospace;")
        imu_l.addWidget(self.gyro_label)
        imu_l.addWidget(self.accel_label)
        layout.addWidget(imu_box)

        # Buttons.
        btn_box = QGroupBox("Buttons")
        grid = QGridLayout(btn_box)
        grid.setSpacing(4)
        self._btn_labels: dict[str, QLabel] = {}
        all_names = [n for n in ALL_BUTTONS]
        cols = 5
        for i, name in enumerate(all_names):
            lab = QLabel(name)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setStyleSheet(_btn_style(False))
            grid.addWidget(lab, i // cols, i % cols)
            self._btn_labels[name] = lab
        layout.addWidget(btn_box, 1)

        # Live refresh at 60Hz.
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _refresh(self) -> None:
        s = self._app.last_state
        if s is None or s is self._last:
            return
        self._last = s

        # Sticks: dim the pad dots when not being touched.
        ls_touch = s.pressed(Btn.LEFT_STICK_TOUCH) or s.left_stick != (0.0, 0.0)
        rs_touch = s.pressed(Btn.RIGHT_STICK_TOUCH) or s.right_stick != (0.0, 0.0)
        lp_touch = s.pressed(Btn.LEFT_PAD_TOUCH)
        rp_touch = s.pressed(Btn.RIGHT_PAD_TOUCH)
        self.left_stick.set_value(*s.left_stick, active=ls_touch)
        self.right_stick.set_value(*s.right_stick, active=rs_touch)
        self.left_pad.set_value(*s.left_pad, active=lp_touch)
        self.right_pad.set_value(*s.right_pad, active=rp_touch)

        self.lt_bar.setValue(int(s.left_trigger * 1000))
        self.rt_bar.setValue(int(s.right_trigger * 1000))

        self.gyro_label.setText(
            f"gyro:  {s.gyro[0]:+.2f}  {s.gyro[1]:+.2f}  {s.gyro[2]:+.2f}"
        )
        self.accel_label.setText(
            f"accel: {s.accel[0]:+.2f}  {s.accel[1]:+.2f}  {s.accel[2]:+.2f}"
        )

        for name, lab in self._btn_labels.items():
            flag = BTN_NAME_TO_FLAG.get(name)
            pressed = bool(flag is not None and s.pressed(flag))
            lab.setStyleSheet(_btn_style(pressed))


def _btn_style(active: bool) -> str:
    if active:
        return (
            "background-color: #2d6cdf; color: white; padding: 3px 5px;"
            "border: 1px solid #4f8ff0; border-radius: 3px; font-size: 11px;"
        )
    return (
        "background-color: #222; color: #888; padding: 3px 5px;"
        "border: 1px solid #333; border-radius: 3px; font-size: 11px;"
    )
