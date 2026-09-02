"""PyInstaller entry point for the standalone Windows updater."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app_paths import USER_DATA_ROOT
from update_installer import InstallError, InstallRequest, apply_update


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--request")
    try:
        arguments, unknown = parser.parse_known_args(argv)
    except SystemExit:
        return 2
    if unknown or not arguments.request:
        return 2
    request_path = Path(arguments.request)
    try:
        request = InstallRequest.from_path(
            request_path,
            allowed_updates_root=USER_DATA_ROOT / "updates",
        )
        os.chdir(USER_DATA_ROOT / "updates")
        result = apply_update(request)
    except (InstallError, OSError, ValueError):
        return 1
    return 0 if result.status == "installed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
