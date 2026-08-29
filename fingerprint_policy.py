"""Shared policy for audited-file fingerprint mismatches.

Normal operation remains strict.  The GUI's advanced mode may explicitly
downgrade only hash/fingerprint mismatches to visible warnings; missing files,
invalid manifests, unsupported versions and syntax errors are unaffected.
"""

from __future__ import annotations

from collections.abc import MutableSequence


FINGERPRINT_WARNING_PREFIX = "高级模式指纹警告："


def record_fingerprint_mismatch(
    message: str,
    *,
    warning_only: bool,
    errors: MutableSequence[str] | None = None,
    warnings: MutableSequence[str] | None = None,
    exception_type: type[Exception] = ValueError,
) -> None:
    """Record or raise one fingerprint mismatch according to the policy."""
    if warning_only:
        if warnings is not None:
            warnings.append(FINGERPRINT_WARNING_PREFIX + message)
        return
    if errors is not None:
        errors.append(message)
        return
    raise exception_type(message)
