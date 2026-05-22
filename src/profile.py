"""JSON-backed mapping profiles.

A profile describes:
- which physical input (button on the Steam Controller) drives which Xbox
  button or stick axis on the virtual gamepad,
- per-axis dead zones and sensitivity,
- whether the gyro is fed into the right stick (when a button is held, or
  always-on),
- whether the right pad acts as a mouse-style stick (not yet wired through —
  shape exists in the schema for forward compatibility).

A profile is a plain dict that round-trips to JSON without losing precision.
The default profile produces a sensible Xbox-controller layout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .protocol import Btn


PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"


# ----- Default mapping ------------------------------------------------------

# Maps a Steam-Controller button name (string, as used in the GUI) to an
# Xbox-360 virtual gamepad target name. The string keys are used so the
# JSON file is human-readable and editable.
DEFAULT_BUTTON_MAP: dict[str, str] = {
    "A": "A",
    "B": "B",
    "X": "X",
    "Y": "Y",
    "L1": "LB",
    "R1": "RB",
    "L2": "LT",      # analog trigger; mapper treats LT/RT specially
    "R2": "RT",
    "L5": "LB",      # rear paddle defaults — feel free to remap in the GUI
    "R5": "RB",
    "VIEW": "BACK",
    "MENU": "START",
    "STEAM": "GUIDE",
    "QUICK_ACCESS": "GUIDE",
    "LEFT_STICK_CLICK": "LS",
    "RIGHT_STICK_CLICK": "RS",
    "LEFT_PAD_CLICK": "LS",   # touchpad click → left stick click by default
    "RIGHT_PAD_CLICK": "RS",
    "DPAD_UP": "DPAD_UP",
    "DPAD_DOWN": "DPAD_DOWN",
    "DPAD_LEFT": "DPAD_LEFT",
    "DPAD_RIGHT": "DPAD_RIGHT",
}

# Every physical button we recognise. Order matters for the GUI's editor.
ALL_BUTTONS: list[str] = list(DEFAULT_BUTTON_MAP.keys())

# Targets the user can pick in the GUI. Includes "NONE" to disable a button.
ALL_TARGETS: list[str] = [
    "NONE", "A", "B", "X", "Y",
    "LB", "RB", "LT", "RT",
    "BACK", "START", "GUIDE",
    "LS", "RS",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
]


# Bridge between Btn flags and string names used in profiles.
BTN_NAME_TO_FLAG: dict[str, Btn] = {
    "A": Btn.A,
    "B": Btn.B,
    "X": Btn.X,
    "Y": Btn.Y,
    "L1": Btn.L1,
    "R1": Btn.R1,
    "L2": Btn.L2,
    "R2": Btn.R2,
    "L5": Btn.L5,
    "R5": Btn.R5,
    "VIEW": Btn.VIEW,
    "MENU": Btn.MENU,
    "STEAM": Btn.STEAM,
    "QUICK_ACCESS": Btn.QUICK_ACCESS,
    "LEFT_STICK_CLICK": Btn.LEFT_STICK_CLICK,
    "RIGHT_STICK_CLICK": Btn.RIGHT_STICK_CLICK,
    "LEFT_PAD_CLICK": Btn.LEFT_PAD_CLICK,
    "RIGHT_PAD_CLICK": Btn.RIGHT_PAD_CLICK,
    "DPAD_UP": Btn.DPAD_UP,
    "DPAD_DOWN": Btn.DPAD_DOWN,
    "DPAD_LEFT": Btn.DPAD_LEFT,
    "DPAD_RIGHT": Btn.DPAD_RIGHT,
}


# ----- Schema ---------------------------------------------------------------


@dataclass
class StickTune:
    deadzone: float = 0.10        # ignore values below this magnitude
    saturation: float = 0.98      # value at which we clamp to 1.0
    invert_x: bool = False
    invert_y: bool = False
    sensitivity: float = 1.0


@dataclass
class TriggerTune:
    deadzone: float = 0.02
    saturation: float = 0.98


@dataclass
class GyroTune:
    enabled: bool = False
    activate_button: str = "RIGHT_PAD_TOUCH"  # only feed gyro while held
    pitch_to_y: float = 0.0
    yaw_to_x: float = 1.2          # camera-look default: yaw -> right stick X
    roll_to_x: float = 0.0


@dataclass
class Profile:
    name: str = "default"
    description: str = ""
    buttons: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BUTTON_MAP))
    left_stick: StickTune = field(default_factory=StickTune)
    right_stick: StickTune = field(default_factory=StickTune)
    left_pad: StickTune = field(default_factory=lambda: StickTune(deadzone=0.05))
    right_pad: StickTune = field(default_factory=lambda: StickTune(deadzone=0.05))
    left_trigger: TriggerTune = field(default_factory=TriggerTune)
    right_trigger: TriggerTune = field(default_factory=TriggerTune)
    gyro: GyroTune = field(default_factory=GyroTune)

    # Routing of pad-as-stick: which virtual stick (if any) does the pad feed?
    # "NONE" | "LEFT" | "RIGHT"
    left_pad_routes_to: str = "NONE"
    right_pad_routes_to: str = "NONE"

    # ---- (de)serialization ----

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "buttons": dict(self.buttons),
            "left_stick": self.left_stick.__dict__,
            "right_stick": self.right_stick.__dict__,
            "left_pad": self.left_pad.__dict__,
            "right_pad": self.right_pad.__dict__,
            "left_trigger": self.left_trigger.__dict__,
            "right_trigger": self.right_trigger.__dict__,
            "gyro": self.gyro.__dict__,
            "left_pad_routes_to": self.left_pad_routes_to,
            "right_pad_routes_to": self.right_pad_routes_to,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Profile":
        return cls(
            name=d.get("name", "default"),
            description=d.get("description", ""),
            buttons={k: v for k, v in (d.get("buttons") or DEFAULT_BUTTON_MAP).items()},
            left_stick=StickTune(**(d.get("left_stick") or {})),
            right_stick=StickTune(**(d.get("right_stick") or {})),
            left_pad=StickTune(**(d.get("left_pad") or {"deadzone": 0.05})),
            right_pad=StickTune(**(d.get("right_pad") or {"deadzone": 0.05})),
            left_trigger=TriggerTune(**(d.get("left_trigger") or {})),
            right_trigger=TriggerTune(**(d.get("right_trigger") or {})),
            gyro=GyroTune(**(d.get("gyro") or {})),
            left_pad_routes_to=d.get("left_pad_routes_to", "NONE"),
            right_pad_routes_to=d.get("right_pad_routes_to", "NONE"),
        )


# ----- Disk I/O -------------------------------------------------------------


def profiles_dir() -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILES_DIR


def list_profiles() -> list[str]:
    return sorted(p.stem for p in profiles_dir().glob("*.json"))


def load_profile(name: str) -> Profile:
    path = profiles_dir() / f"{name}.json"
    if not path.exists():
        if name == "default":
            p = Profile()
            save_profile(p)
            return p
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as f:
        return Profile.from_dict(json.load(f))


def save_profile(profile: Profile) -> Path:
    path = profiles_dir() / f"{profile.name}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(profile.to_dict(), f, indent=2, sort_keys=False)
    return path


def delete_profile(name: str) -> bool:
    path = profiles_dir() / f"{name}.json"
    if path.exists():
        path.unlink()
        return True
    return False
