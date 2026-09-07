import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app_updater import (
    UpdateCandidate,
    UpdateManifest,
    prepare_update,
    write_install_request,
)
from tools.verify_windows_upgrade import persistent_user_snapshot
from update_installer import InstallRequest, apply_update


class BytesResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class FakeProcess:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


class PySideReleaseUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.install = self.root / "FRLG-Auto-RNG"
        self.install.mkdir()
        (self.install / "FRLG-Auto-RNG.exe").write_bytes(b"tk-0.2.2")
        (self.install / "FRLG-Auto-RNG-Updater.exe").write_bytes(b"old-updater")
        (self.install / "_internal").mkdir()
        (self.install / "_internal" / "legacy.bin").write_bytes(b"legacy")
        self.user = self.root / "LocalAppData" / "FRLG-Auto-RNG"
        fixtures = {
            "pyside6_settings.json": b'{"source":"saved"}',
            "startup_notice.json": b'{"hidden":true}',
            "tid_progress/task.json": b'{"round":27}',
            "seed_tables/current/fr_nx.bin": b"seed-table",
            "device_label_overrides/capture/manifest.json": b'{"labels":2}',
        }
        for relative, content in fixtures.items():
            path = self.user / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.before = persistent_user_snapshot(self.user)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("FRLG-Auto-RNG.exe", b"pyside6-0.9")
            archive.writestr("FRLG-Auto-RNG-Updater.exe", b"new-updater")
            archive.writestr("_internal/qt.conf", b"[Paths]")
        self.package = buffer.getvalue()
        self.manifest = UpdateManifest(
            schema=1,
            version="0.9",
            version_code=2026090701,
            package="FRLG-Auto-RNG-0.9-windows-x64.zip",
            sha256=hashlib.sha256(self.package).hexdigest(),
            bytes=len(self.package),
            unpacked_bytes=len(b"pyside6-0.9") + len(b"new-updater") + len(b"[Paths]"),
            release_url="https://github.com/axechaso/frlg-auto-rng/releases/tag/v0.9",
            notes="PySide6 正式版。",
        )
        self.candidate = UpdateCandidate(
            manifest=self.manifest,
            package_url=(
                "https://github.com/axechaso/frlg-auto-rng/releases/download/v0.9/"
                + self.manifest.package
            ),
            published_at="2026-09-07T12:00:00Z",
            tag_name="v0.9",
        )

    def tearDown(self):
        self.temp.cleanup()

    def prepare_request(self):
        prepared = prepare_update(
            self.candidate,
            install_dir=self.install,
            updates_root=self.user / "updates",
            opener=lambda *_args, **_kwargs: BytesResponse(self.package),
            probe=lambda _stage, manifest: self.assertEqual(
                (manifest.version, manifest.version_code), ("0.9", 2026090701)
            ),
        )
        request_path = write_install_request(
            prepared,
            current_pid=123,
            updates_root=self.user / "updates",
        )
        return InstallRequest.from_path(
            request_path,
            allowed_updates_root=self.user / "updates",
        )

    def test_0_2_2_install_is_replaced_by_0_9_without_touching_user_data(self):
        request = self.prepare_request()
        result = apply_update(
            request,
            wait_pid=lambda _pid, _timeout: True,
            launch=lambda _executable, _arguments: FakeProcess(),
            wait_health=lambda _path, _token, version, _timeout: version == 2026090701,
        )

        self.assertEqual(result.status, "installed")
        self.assertEqual(
            (self.install / "FRLG-Auto-RNG.exe").read_bytes(), b"pyside6-0.9"
        )
        self.assertEqual(persistent_user_snapshot(self.user), self.before)
        self.assertFalse(request.backup_dir.exists())

    def test_failed_0_9_health_check_restores_0_2_2_and_user_data(self):
        request = self.prepare_request()
        process = FakeProcess()
        result = apply_update(
            request,
            wait_pid=lambda _pid, _timeout: True,
            launch=lambda _executable, _arguments: process,
            wait_health=lambda *_args: False,
        )

        self.assertEqual(result.status, "rolled_back")
        self.assertTrue(process.terminated)
        self.assertEqual(
            (self.install / "FRLG-Auto-RNG.exe").read_bytes(), b"tk-0.2.2"
        )
        self.assertEqual(persistent_user_snapshot(self.user), self.before)


if __name__ == "__main__":
    unittest.main()
