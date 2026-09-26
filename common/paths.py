"""Resource and writable-data paths for source and PyInstaller builds."""
from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def is_frozen() -> bool:
    """Return whether the application is running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def resource_path(relative_path: str | os.PathLike) -> str:
    """Resolve a read-only bundled resource."""
    base = Path(sys._MEIPASS) if is_frozen() else PROJECT_ROOT
    return str((base / Path(relative_path)).resolve())


def user_data_root() -> Path:
    """Return a writable location for settings, images, exports, and caches."""
    if not is_frozen():
        return PROJECT_ROOT
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path(sys.executable).parent
    target = base / "PhenoPod"
    target.mkdir(parents=True, exist_ok=True)
    return target


def writable_path(relative_path: str | os.PathLike) -> str:
    """Resolve a writable application-data path."""
    return str((user_data_root() / Path(relative_path)).resolve())
