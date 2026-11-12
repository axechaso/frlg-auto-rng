"""Restore resource locations after a portable install is moved or updated."""
from __future__ import annotations

import sys
import hashlib
from pathlib import Path


def restore_easycon_path(value, default: Path) -> str:
    """Migrate known old CLIs when this installation selects the 170 runtime."""
    from automation.easycon170 import EASYCON170_CLI_SHA256, enabled
    default = Path(default)
    if not enabled() or default.name != "EasyCon2.CLI.exe":
        return restore_resource_path(
            value, default, bundled_suffix="_internal/easycon/publish/ezcon.exe", file=True,
        )
    restored = restore_resource_path(
        value, default,
        bundled_suffix="_internal/runtime_backend/easycon170-pc-extension/EasyCon2.CLI.exe",
        file=True,
    )
    previous = Path(restored)
    if previous == default or not previous.is_file():
        return restored
    # Identical apphost names/paths are insufficient to distinguish runtimes.
    # Preserve unknown custom paths for an explicit preflight error.
    known_old = {
        "559b81c234d2548c439926a88f5355ccac0958b8a191c1ecca48b2c7c71c1260",
        "979d8b58eb5c50085d3ef4c94f9622aef2fc0106160b70b1f3cd5a5d435ece88",
        "f6e540e08e8cf61ce8e0e1a0e04bcb901a4b8ee0f3d4fd0d6cb800e1b0030ea5",
    }
    try:
        digest = hashlib.sha256(previous.read_bytes()).hexdigest()
    except OSError:
        return restored
    return str(default) if digest in known_old and digest != EASYCON170_CLI_SHA256 else restored


def _label_count(path: Path) -> int | None:
    try:
        return sum(1 for item in (path / "ImgLabel").iterdir()
                   if item.is_file() and item.suffix.casefold() == ".il")
    except OSError:
        return None


def restore_resource_path(
    value,
    default: Path,
    *,
    bundled_suffix: str,
    file: bool = False,
    required_file: str | None = None,
    legacy_label_counts: tuple[int, ...] = (),
) -> str:
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
    if required_file and not file:
        saved_exists = saved_exists and (saved / required_file).is_file()
        default_exists = default_exists and (default / required_file).is_file()
    saved_label_count = (
        _label_count(saved) if legacy_label_counts and not file and saved_exists else None
    )
    default_label_count = (
        _label_count(default) if legacy_label_counts and not file and default_exists else None
    )
    if (not file and saved_exists and default_exists and saved != default
            and legacy_label_counts and saved_label_count in legacy_label_counts
            and default_label_count is not None
            and default_label_count not in legacy_label_counts):
        # Old TID builds persisted their reduced 119/328/329-label cache as a
        # custom absolute path.  It may still exist after an update, but it is
        # not a valid current mother corpus.  Prefer this installation's full
        # bundled corpus while leaving genuinely custom/unknown paths visible.
        return str(default)
    if not saved_exists and default_exists:
        return str(default)
    # Preserve an unavailable custom path when no usable default exists, so
    # the error still identifies the location the user selected.
    return value
