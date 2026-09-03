"""Application version contract shared by the GUI, updater, and release tools."""

from __future__ import annotations


APP_VERSION = "0.2.1"
APP_VERSION_CODE = 2026090301
UPDATE_SCHEMA = 1
GITHUB_REPOSITORY = "axechaso/frlg-auto-rng"
PACKAGE_PREFIX = "FRLG-Auto-RNG"
MAIN_EXECUTABLE = "FRLG-Auto-RNG.exe"
UPDATER_EXECUTABLE = "FRLG-Auto-RNG-Updater.exe"


def version_payload() -> dict[str, object]:
    return {
        "version": APP_VERSION,
        "version_code": APP_VERSION_CODE,
        "update_schema": UPDATE_SCHEMA,
        "repository": GITHUB_REPOSITORY,
    }
