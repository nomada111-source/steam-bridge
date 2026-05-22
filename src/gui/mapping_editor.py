"""Per-button remap editor + stick / trigger / gyro tuning."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..app import BridgeApp
from ..profile import ALL_BUTTONS, ALL_TARGETS, StickTune, TriggerTune


class MappingEditor(QWidget):
    profile_dirty = Signal()

    def __init__(self, app: BridgeApp, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._button_combos: dict[str, QComboBox] = {}
        self._stick_widgets: dict[str, dict[str, QWidget]] = {}
        self._trigger_widgets: dict[str, dict[str, QWidget]] = {}
        self._gyro_widgets: dict[str, QWidget] = {}
        self._loading = False

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)

        layout.addWidget(self._build_button_map())
        layout.addWidget(self._build_stick_section("Left stick", "left_stick"))
        layout.addWidget(self._build_stick_section("Right stick", "right_stick"))
        layout.addWidget(self._build_stick_section("Left pad", "left_pad"))
        layout.addWidget(self._build_stick_section("Right pad", "right_pad"))
        layout.addWidget(self._build_trigger_section("Left trigger", "left_trigger"))
        layout.addWidget(self._build_trigger_section("Right trigger", "right_trigger"))
        layout.addWidget(self._build_gyro_section())
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.addWidget(scroll, 1)

        apply_btn = QPushButton("Apply to live bridge")
        apply_btn.clicked.connect(self.apply_changes)
        outer.addWidget(apply_btn)

        self.load_from_profile()

    # ---- builders ----

    def _build_button_map(self) -> QGroupBox:
        box = QGroupBox("Button mapping")
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        for name in ALL_BUTTONS:
            combo = QComboBox()
            combo.addItems(ALL_TARGETS)
            combo.currentTextChanged.connect(self._mark_dirty)
            self._button_combos[name] = combo
            form.addRow(QLabel(name), combo)
        return box

    def _build_stick_section(self, title: str, field: str) -> QGroupBox:
        box = QGroupBox(title)
        form = QFormLayout(box)
        dz = QDoubleSpinBox(); dz.setRange(0.0, 0.95); dz.setSingleStep(0.01); dz.setDecimals(3)
        sat = QDoubleSpinBox(); sat.setRange(0.05, 1.0); sat.setSingleStep(0.01); sat.setDecimals(3)
        sens = QDoubleSpinBox(); sens.setRange(0.1, 4.0); sens.setSingleStep(0.05); sens.setDecimals(2)
        inv_x = QCheckBox("Invert X")
        inv_y = QCheckBox("Invert Y")
        for w in (dz, sat, sens):
            w.valueChanged.connect(self._mark_dirty)
        inv_x.toggled.connect(self._mark_dirty)
        inv_y.toggled.connect(self._mark_dirty)
        form.addRow("Dead zone", dz)
        form.addRow("Saturation", sat)
        form.addRow("Sensitivity", sens)
        form.addRow(inv_x)
        form.addRow(inv_y)
        self._stick_widgets[field] = {
            "deadzone": dz, "saturation": sat, "sensitivity": sens,
            "invert_x": inv_x, "invert_y": inv_y,
        }
        return box

    def _build_trigger_section(self, title: str, field: str) -> QGroupBox:
        box = QGroupBox(title)
        form = QFormLayout(box)
        dz = QDoubleSpinBox(); dz.setRange(0.0, 0.95); dz.setSingleStep(0.01); dz.setDecimals(3)
        sat = QDoubleSpinBox(); sat.setRange(0.05, 1.0); sat.setSingleStep(0.01); sat.setDecimals(3)
        dz.valueChanged.connect(self._mark_dirty)
        sat.valueChanged.connect(self._mark_dirty)
        form.addRow("Dead zone", dz)
        form.addRow("Saturation", sat)
        self._trigger_widgets[field] = {"deadzone": dz, "saturation": sat}
        return box

    def _build_gyro_section(self) -> QGroupBox:
        box = QGroupBox("Gyro")
        form = QFormLayout(box)
        en = QCheckBox("Enabled")
        btn = QComboBox()
        btn.addItems(["ALWAYS", "RIGHT_PAD_TOUCH", "LEFT_PAD_TOUCH", "L2", "R2", "L5", "R5"])
        yaw = QDoubleSpinBox(); yaw.setRange(-5.0, 5.0); yaw.setDecimals(2); yaw.setSingleStep(0.1)
        pitch = QDoubleSpinBox(); pitch.setRange(-5.0, 5.0); pitch.setDecimals(2); pitch.setSingleStep(0.1)
        roll = QDoubleSpinBox(); roll.setRange(-5.0, 5.0); roll.setDecimals(2); roll.setSingleStep(0.1)
        for w in (yaw, pitch, roll):
            w.valueChanged.connect(self._mark_dirty)
        en.toggled.connect(self._mark_dirty)
        btn.currentTextChanged.connect(self._mark_dirty)
        form.addRow(en)
        form.addRow("Activate while", btn)
        form.addRow("Yaw → stick X", yaw)
        form.addRow("Pitch → stick Y", pitch)
        form.addRow("Roll → stick X", roll)
        self._gyro_widgets = {
            "enabled": en, "activate_button": btn,
            "yaw_to_x": yaw, "pitch_to_y": pitch, "roll_to_x": roll,
        }
        return box

    # ---- profile <-> widgets ----

    def load_from_profile(self) -> None:
        self._loading = True
        try:
            p = self._app.profile
            for name, combo in self._button_combos.items():
                target = p.buttons.get(name, "NONE")
                idx = combo.findText(target)
                combo.setCurrentIndex(idx if idx >= 0 else 0)

            for field, widgets in self._stick_widgets.items():
                tune: StickTune = getattr(p, field)
                widgets["deadzone"].setValue(tune.deadzone)
                widgets["saturation"].setValue(tune.saturation)
                widgets["sensitivity"].setValue(tune.sensitivity)
                widgets["invert_x"].setChecked(tune.invert_x)
                widgets["invert_y"].setChecked(tune.invert_y)

            for field, widgets in self._trigger_widgets.items():
                tune: TriggerTune = getattr(p, field)
                widgets["deadzone"].setValue(tune.deadzone)
                widgets["saturation"].setValue(tune.saturation)

            g = p.gyro
            self._gyro_widgets["enabled"].setChecked(g.enabled)
            idx = self._gyro_widgets["activate_button"].findText(g.activate_button)
            if idx >= 0:
                self._gyro_widgets["activate_button"].setCurrentIndex(idx)
            self._gyro_widgets["yaw_to_x"].setValue(g.yaw_to_x)
            self._gyro_widgets["pitch_to_y"].setValue(g.pitch_to_y)
            self._gyro_widgets["roll_to_x"].setValue(g.roll_to_x)
        finally:
            self._loading = False

    def apply_changes(self) -> None:
        p = self._app.profile
        for name, combo in self._button_combos.items():
            p.buttons[name] = combo.currentText()

        for field, widgets in self._stick_widgets.items():
            tune: StickTune = getattr(p, field)
            tune.deadzone = widgets["deadzone"].value()
            tune.saturation = widgets["saturation"].value()
            tune.sensitivity = widgets["sensitivity"].value()
            tune.invert_x = widgets["invert_x"].isChecked()
            tune.invert_y = widgets["invert_y"].isChecked()

        for field, widgets in self._trigger_widgets.items():
            tune: TriggerTune = getattr(p, field)
            tune.deadzone = widgets["deadzone"].value()
            tune.saturation = widgets["saturation"].value()

        g = p.gyro
        g.enabled = self._gyro_widgets["enabled"].isChecked()
        g.activate_button = self._gyro_widgets["activate_button"].currentText()
        g.yaw_to_x = self._gyro_widgets["yaw_to_x"].value()
        g.pitch_to_y = self._gyro_widgets["pitch_to_y"].value()
        g.roll_to_x = self._gyro_widgets["roll_to_x"].value()

        # Reseat the profile in the mapper so the live bridge picks it up.
        self._app.set_profile(p)

    def _mark_dirty(self, *args) -> None:
        if not self._loading:
            self.profile_dirty.emit()
