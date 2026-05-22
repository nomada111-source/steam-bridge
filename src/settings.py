"""Tiny key/value store for app-level preferences (last-good device, etc).

Stored as JSON in `profiles/_settings.json`. Separate from per-game profiles
so it survives switching profiles around.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .profile import profiles_dir


def _path() -> Path:
    return profiles_dir() / "_settings.json"


def load() -> dict[str, Any]:
    p = _path()
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(data: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set_(key: str, value: Any) -> None:
    data = load()
    data[key] = value
    save(data)
