import json
import tempfile
import unittest
from pathlib import Path

from app_updater import PreparedUpdate, UpdateManifest, write_install_request
from update_installer import InstallError, InstallRequest, apply_update


class FakeProcess:
    def __init__(self, pid=987):
        self.pid = pid
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


class UpdateInstallerTests(unittest.TestCase):
    def make_request(self, root: Path):
        request_id = "1" * 32
        token = "2" * 32
        install = root / "FRLG-Auto-RNG"
        stage = root / f".frlg-update-stage-{request_id}"
        updates = root / "user" / "updates"
        install.mkdir()
        stage.mkdir()
        (install / "FRLG-Auto-RNG.exe").write_bytes(b"old")
        (stage / "FRLG-Auto-RNG.exe").write_bytes(b"new")
        (stage / "FRLG-Auto-RNG-Updater.exe").write_bytes(b"updater")
        marker = {
            "schema": 1,
            "request_id": request_id,
            "token": token,
            "version": "0.2",
            "version_code": 2026090201,
        }
        (stage / ".frlg-update-stage.json").write_text(
            json.dumps(marker), encoding="utf-8"
        )
        manifest = UpdateManifest(
            1,
            "0.2",
            2026090201,
            "FRLG-Auto-RNG-0.2-windows-x64.zip",
            "a" * 64,
            1,
            1,
            "https://github.com/axechaso/frlg-auto-rng/releases/tag/v0.2",
            "notes",
        )
        prepared = PreparedUpdate(
            request_id, token, install.resolve(), stage.resolve(), root / "x.zip", manifest
        )
        path = write_install_request(prepared, current_pid=123, updates_root=updates)
        return InstallRequest.from_path(path, allowed_updates_root=updates), install, stage

    def test_request_rejects_path_outside_updates_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, _install, _stage = self.make_request(root)
            with self.assertRaises(InstallError):
                InstallRequest.from_path(
                    request.request_path, allowed_updates_root=root / "other"
                )

    def test_successful_swap_launches_new_version_and_removes_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, install, stage = self.make_request(root)
            launched = []
            process = FakeProcess()

            def launch(executable, arguments):
                launched.append((executable, arguments))
                return process

            result = apply_update(
                request,
                wait_pid=lambda _pid, _timeout: True,
                launch=launch,
                wait_health=lambda _path, _token, _version, _timeout: True,
            )
            self.assertEqual(result.status, "installed")
            self.assertFalse(stage.exists())
            self.assertEqual((install / "FRLG-Auto-RNG.exe").read_bytes(), b"new")
            self.assertFalse(request.backup_dir.exists())
            self.assertEqual(launched[0][0], install / "FRLG-Auto-RNG.exe")
            self.assertIn("--update-health-file", launched[0][1])

    def test_launch_failure_rolls_back_old_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, install, _stage = self.make_request(root)

            def launch(_executable, _arguments):
                raise OSError("launch failed")

            result = apply_update(
                request,
                wait_pid=lambda _pid, _timeout: True,
                launch=launch,
                wait_health=lambda *_args: False,
            )
            self.assertEqual(result.status, "rolled_back")
            self.assertEqual((install / "FRLG-Auto-RNG.exe").read_bytes(), b"old")
            self.assertTrue(request.failed_dir.is_dir())

    def test_health_timeout_terminates_new_version_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, install, _stage = self.make_request(root)
            process = FakeProcess()
            result = apply_update(
                request,
                wait_pid=lambda _pid, _timeout: True,
                launch=lambda *_args: process,
                wait_health=lambda *_args: False,
            )
            self.assertEqual(result.status, "rolled_back")
            self.assertTrue(process.terminated)
            self.assertEqual((install / "FRLG-Auto-RNG.exe").read_bytes(), b"old")

    def test_pid_timeout_does_not_change_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, install, stage = self.make_request(root)
            result = apply_update(
                request,
                wait_pid=lambda _pid, _timeout: False,
                launch=lambda *_args: self.fail("must not launch"),
            )
            self.assertEqual(result.status, "failed")
            self.assertTrue(stage.exists())
            self.assertEqual((install / "FRLG-Auto-RNG.exe").read_bytes(), b"old")
