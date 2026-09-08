"""Restore resource locations after a portable install is moved or updated."""
from __future__ import annotations

import sys
from pathlib import Path


def restore_resource_path(value, default: Path, *, bundled_suffix: str, file: bool = False) -> str:
    default = Path(default)
    if not isinstance(value, str) or not value.strip():
        return str(default)
    saved = Path(value)
    # Settings from an earlier portable package contain absolute paths. A
    # frozen app must use its own bundled copy even if the old one still exists.
    suffix = Path(bundled_suffix).parts
    bundled = tuple(part.casefold() for part in saved.parts[-len(suffix):]) == tuple(
        part.casefold() for part in suffix
    )
    if getattr(sys, "frozen", False) and bundled:
        return str(default)
    saved_exists = saved.is_file() if file else saved.is_dir()
    default_exists = default.is_file() if file else default.is_dir()
    if not saved_exists and default_exists:
        return str(default)
    # Preserve an unavailable custom path when no usable default exists, so
    # the error still identifies the location the user selected.
    return value
