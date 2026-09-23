"""Restore resource locations after a portable install is moved or updated."""
from __future__ import annotations

import sys
from pathlib import Path


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
