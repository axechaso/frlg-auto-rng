import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from app_updater import (
    PreparedUpdate,
    UpdateCandidate,
    UpdateCancelled,
    UpdateError,
    UpdateManifest,
    candidate_from_release,
    download_package,
    parse_manifest,
    required_free_space,
    safe_extract,
    validate_zip,
    write_install_request,
)


def manifest_payload(**overrides):
    value = {
        "schema": 1,
        "version": "0.2",
        "version_code": 2026090201,
        "package": "FRLG-Auto-RNG-0.2-windows-x64.zip",
        "sha256": "a" * 64,
        "bytes": 123,
        "unpacked_bytes": 456,
        "release_url": "https://github.com/axechaso/frlg-auto-rng/releases/tag/v0.2",
        "notes": "更新说明",
    }
    value.update(overrides)
    return value


def make_manifest(**overrides):
    return parse_manifest(json.dumps(manifest_payload(**overrides)).encode())


def make_release(manifest):
    base = "https://github.com/axechaso/frlg-auto-rng/releases/download/v0.2/"
    names = (
        manifest.package,
        f"{manifest.package}.sha256",
        "update-manifest.json",
    )
    return {
        "draft": False,
        "prerelease": False,
        "tag_name": "v0.2",
        "html_url": manifest.release_url,
        "published_at": "2026-09-02T12:00:00Z",
        "assets": [
            {
                "name": name,
                "size": manifest.bytes if name == manifest.package else 100,
                "browser_download_url": base + name,
            }
            for name in names
        ],
    }


class BytesResponse(io.BytesIO):
    def __init__(self, value, headers=None):
        super().__init__(value)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class AppUpdaterTests(unittest.TestCase):
    def test_manifest_contract_and_rejections(self):
        manifest = make_manifest()
        self.assertEqual(manifest.version, "0.2")
        for updates in (
            {"schema": 2},
            {"version_code": True},
            {"package": "../bad.zip"},
            {"sha256": "A" * 64},
            {"bytes": 0},
            {"unpacked_bytes": 0},
            {"release_url": "http://example.invalid"},
        ):
            with self.subTest(updates=updates), self.assertRaises(UpdateError):
                make_manifest(**updates)
        extra = manifest_payload()
        extra["extra"] = True
        with self.assertRaises(UpdateError):
            parse_manifest(json.dumps(extra).encode())

    def test_release_requires_stable_complete_matching_assets(self):
        manifest = make_manifest()
        candidate = candidate_from_release(make_release(manifest), manifest)
        self.assertEqual(candidate.manifest, manifest)
        for mutation in ("draft", "prerelease"):
            release = make_release(manifest)
            release[mutation] = True
            with self.subTest(mutation=mutation), self.assertRaises(UpdateError):
                candidate_from_release(release, manifest)
        release = make_release(manifest)
        release["assets"].pop()
        with self.assertRaises(UpdateError):
            candidate_from_release(release, manifest)
        release = make_release(manifest)
        release["assets"][0]["size"] += 1
        with self.assertRaises(UpdateError):
            candidate_from_release(release, manifest)

    def test_check_uses_cache_etag_and_returns_errors_without_overwriting_cache(self):
        from app_updater import check_for_update

        package_content = b"x" * 123
        manifest = make_manifest(
            sha256=hashlib.sha256(package_content).hexdigest(), bytes=len(package_content)
        )
        release = make_release(manifest)
        responses = [
            BytesResponse(json.dumps(release).encode(), {"ETag": '"abc"'}),
            BytesResponse(json.dumps(manifest_payload(bytes=len(package_content), sha256=manifest.sha256)).encode()),
        ]
        calls = []

        def opener(request, **_kwargs):
            calls.append(request)
            return responses.pop(0)

        with tempfile.TemporaryDirectory() as temporary:
            cache_dir = Path(temporary)
            first = check_for_update(
                cache_dir=cache_dir,
                opener=opener,
                current_version_code=1,
                now=1000,
            )
            self.assertEqual(first.status, "available")
            cached = json.loads((cache_dir / "check-cache.json").read_text(encoding="utf-8"))
            self.assertEqual(cached["etag"], '"abc"')
            second = check_for_update(
                cache_dir=cache_dir,
                opener=lambda *_a, **_k: self.fail("cache"),
                current_version_code=1,
                now=1001,
            )
            self.assertTrue(second.from_cache)
            self.assertEqual(len(calls), 2)
            error = check_for_update(
                cache_dir=cache_dir,
                force=True,
                current_version_code=1,
                opener=lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")),
                now=2000,
            )
            self.assertEqual(error.status, "error")
            self.assertEqual(
                json.loads((cache_dir / "check-cache.json").read_text(encoding="utf-8"))["etag"],
                '"abc"',
            )
    def test_required_space_has_safety_margin(self):
        manifest = make_manifest(bytes=10, unpacked_bytes=100)
        self.assertEqual(required_free_space(manifest), 10 + 100 + 256 * 1024 * 1024)

    def test_download_validates_size_hash_and_cancellation(self):
        content = b"package content"
        manifest = make_manifest(
            bytes=len(content), sha256=hashlib.sha256(content).hexdigest()
        )
        candidate = UpdateCandidate(
            manifest,
            "https://github.com/axechaso/frlg-auto-rng/releases/download/v0.2/"
            + manifest.package,
            "2026-09-02T12:00:00Z",
            "v0.2",
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / manifest.package
            result = download_package(
                candidate,
                destination,
                opener=lambda *_args, **_kwargs: BytesResponse(content),
            )
            self.assertEqual(result.read_bytes(), content)
            destination.unlink()
            with self.assertRaises(UpdateCancelled):
                download_package(
                    candidate,
                    destination,
                    opener=lambda *_args, **_kwargs: BytesResponse(content),
                    cancelled=lambda: True,
                )
            self.assertFalse(destination.exists())
            bad = replace(candidate, manifest=replace(manifest, sha256="0" * 64))
            with self.assertRaises(UpdateError):
                download_package(
                    bad,
                    destination,
                    opener=lambda *_args, **_kwargs: BytesResponse(content),
                )
            self.assertFalse(destination.exists())

    def _write_zip(self, root: Path, entries):
        path = root / "package.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in entries:
                archive.writestr(name, content)
        unpacked = sum(len(content) for _name, content in entries)
        return path, make_manifest(unpacked_bytes=unpacked)

    def test_safe_extract_accepts_release_layout(self):
        entries = [
            ("FRLG-Auto-RNG.exe", b"main"),
            ("FRLG-Auto-RNG-Updater.exe", b"updater"),
            ("_internal/app_version.pyc", b"version"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, manifest = self._write_zip(root, entries)
            stage = root / "stage"
            safe_extract(package, stage, manifest)
            self.assertEqual((stage / "FRLG-Auto-RNG.exe").read_bytes(), b"main")

    def test_zip_rejects_unsafe_and_duplicate_paths(self):
        bad_entries = (
            [("../escape", b"x")],
            [("C:/escape", b"x")],
            [("dir/../escape", b"x")],
            [("A.txt", b"x"), ("a.TXT", b"y")],
        )
        required = [
            ("FRLG-Auto-RNG.exe", b"m"),
            ("FRLG-Auto-RNG-Updater.exe", b"u"),
            ("_internal/x", b"i"),
        ]
        for index, extra in enumerate(bad_entries):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                package, manifest = self._write_zip(root, required + extra)
                with self.assertRaises(UpdateError):
                    validate_zip(package, manifest)

    def test_install_request_uses_constrained_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "app"
            stage = root / (".frlg-update-stage-" + "b" * 32)
            updates = root / "user" / "updates"
            install.mkdir()
            stage.mkdir()
            manifest = make_manifest()
            prepared = PreparedUpdate(
                "b" * 32,
                "c" * 32,
                install,
                stage,
                updates / manifest.package,
                manifest,
            )
            request_path = write_install_request(
                prepared, current_pid=123, updates_root=updates
            )
            value = json.loads(request_path.read_text(encoding="utf-8"))
            self.assertEqual(Path(value["stage_dir"]), stage)
            self.assertEqual(Path(value["backup_dir"]).parent, install.parent)
            self.assertEqual(Path(value["result_path"]).parent, request_path.parent)
