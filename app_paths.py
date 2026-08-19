"""Runtime paths shared by source and frozen Windows builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_root() -> Path:
    """Return the read-only directory containing bundled application assets."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    return Path(__file__).resolve().parent


def data_root() -> Path:
    """Return the writable per-user directory used by packaged applications."""
    if not getattr(sys, "frozen", False):
        return resource_root()
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "FRLG-Auto-RNG"


RESOURCE_ROOT = resource_root()
DATA_ROOT = data_root()
