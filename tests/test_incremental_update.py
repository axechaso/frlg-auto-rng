import copy
import hashlib
import json
import random
import shutil
import tempfile
import unittest
import urllib.error
import urllib.parse
import zipfile
import zlib
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import app_updater as updater
import incremental_update as incremental
from tests.test_app_updater import BytesResponse, make_manifest, make_release, make_gitee_release
from update_installer import InstallRequest, apply_update


class IncrementalUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.new = self.root / "new"
        self.new.mkdir()
        self.contents = {
            "FRLG-Auto-RNG.exe": b"new executable",
            "FRLG-Auto-RNG-Updater.exe": b"updater",
            "_internal/runtime.bin": random.Random(11).randbytes(2 * 1024 * 1024),
            "_internal/更新.ecs": b"new script",
            "_internal/new.txt": b"added",
            "_internal/empty.txt": b"",
        }
        for name, content in self.contents.items():
            path = self.new / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.install = self.root / "installed"
        shutil.copytree(self.new, self.install)
        (self.install / "FRLG-Auto-RNG.exe").write_bytes(b"old executable")
        (self.install / "_internal/更新.ecs").write_bytes(b"old script")
        (self.install / "_internal/new.txt").unlink()
        (self.install / "_internal/removed.txt").write_bytes(b"obsolete")
        self.package = self.root / "FRLG-Auto-RNG-0.2-windows-x64.zip"
        with zipfile.ZipFile(self.package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in self.contents.items():
                archive.writestr(name, content)
        self.manifest = make_manifest(
            bytes=self.package.stat().st_size,
            sha256=incremental.digest_file(self.package),
            unpacked_bytes=sum(map(len, self.contents.values())),
        )
        self.assets = self.root / "assets"
        self.metadata = incremental.create_assets(self.new, asdict(self.manifest), self.assets)
        self.updates = self.root / "updates"
        self.urls = []

    def candidate(self, source="gitee"):
        host = "gitee.com/dazzling-night-scales" if source == "gitee" else "github.com/axechaso"
        base = f"https://{host}/frlg-auto-rng/releases/download/v0.2/"
        manifest = replace(self.manifest, release_url=f"https://{host}/frlg-auto-rng/releases/tag/v0.2")
        return updater.UpdateCandidate(
            manifest, None if source == "gitee" else base + manifest.package,
            "2026-10-02T00:00:00Z", "v0.2", source,
            (updater.UpdatePackagePart(manifest.package + ".001", manifest.sha256, manifest.bytes, base + manifest.package + ".001"),) if source == "gitee" else (),
            self.metadata, tuple((bundle.name, base + bundle.name) for bundle in self.metadata.bundles),
        )

    def opener(self, request, **kwargs):
        self.urls.append(request.full_url)
        name = urllib.parse.unquote(urllib.parse.urlsplit(request.full_url).path.rsplit("/", 1)[-1])
        self.assertTrue(name.startswith("update-data-"), "must never request full ZIP/legacy parts")
        return BytesResponse((self.assets / name).read_bytes())

    def prepare(self, candidate=None, **kwargs):
        return updater.prepare_update(
            candidate or self.candidate(), install_dir=self.install, updates_root=self.updates,
            opener=kwargs.pop("opener", self.opener), probe=lambda *_: None, **kwargs,
        )

    def assert_staged(self, stage):
        for name, content in self.contents.items():
            self.assertEqual((stage / name).read_bytes(), content, name)
        self.assertFalse((stage / "_internal/removed.txt").exists())
        self.assertEqual((self.install / "FRLG-Auto-RNG.exe").read_bytes(), b"old executable")

    def test_gitee_only_downloads_changed_small_bundles_and_stages_exact_new_tree(self):
        candidate = self.candidate()
        plan = updater.plan_incremental_update(candidate, install_dir=self.install, updates_root=self.updates)
        self.assertIn("_internal/runtime.bin", plan.reuse)
        self.assertLess(plan.download_bytes, candidate.manifest.bytes // 100)
        reports, progress = [], []
        prepared = self.prepare(incremental_plan=plan, status=reports.append, progress=lambda a, b: progress.append((a, b)))
        self.assert_staged(prepared.stage_dir)
        self.assertEqual(len(self.urls), len(plan.needed))
        self.assertTrue(all("gitee.com" in url for url in self.urls))
        self.assertEqual(progress[-1], (plan.download_bytes, plan.download_bytes))
        self.assertTrue(any("组装" in report for report in reports))
        self.assertFalse(prepared.package_path.exists())

    def test_github_uses_same_incremental_protocol(self):
        prepared = self.prepare(self.candidate("github"))
        self.assert_staged(prepared.stage_dir)
        self.assertTrue(all("github.com" in url for url in self.urls))

    def test_same_size_local_corruption_is_repaired(self):
        runtime = self.install / "_internal/runtime.bin"
        value = bytearray(runtime.read_bytes())
        value[1024] ^= 1
        runtime.write_bytes(value)
        plan = updater.plan_incremental_update(self.candidate(), install_dir=self.install, updates_root=self.updates)
        self.assertNotIn("_internal/runtime.bin", plan.reuse)
        prepared = self.prepare(incremental_plan=plan)
        self.assert_staged(prepared.stage_dir)

    def test_interruption_keeps_verified_bundles_for_retry(self):
        count = 0

        def interrupted(request, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise urllib.error.URLError("connection lost")
            return self.opener(request, **kwargs)

        with self.assertRaises(updater.UpdateError):
            self.prepare(opener=interrupted)
        first_url = self.urls[0]
        self.assertEqual(len(list((self.updates / "bundles").glob("*.bin"))), 1)
        self.assertEqual(list((self.updates / "bundles").glob("*.part")), [])
        self.urls.clear()
        prepared = self.prepare()
        self.assertNotIn(first_url, self.urls)
        self.assert_staged(prepared.stage_dir)

    def test_completed_bundles_are_reused_without_network(self):
        self.prepare()
        plan = updater.plan_incremental_update(self.candidate(), install_dir=self.install, updates_root=self.updates)
        self.assertEqual(plan.download_bytes, 0)
        prepared = self.prepare(opener=lambda *_a, **_k: self.fail("verified bundles must be reused"))
        self.assert_staged(prepared.stage_dir)

    def test_unchanged_install_needs_no_bundle_downloads(self):
        for name, content in self.contents.items():
            (self.install / name).write_bytes(content)
        plan = updater.plan_incremental_update(self.candidate(), install_dir=self.install, updates_root=self.updates)
        self.assertEqual(plan.download_bytes, 0)
        self.assertEqual(plan.needed, ())
        prepared = self.prepare(opener=lambda *_a, **_k: self.fail("unchanged files require no downloads"))
        self.assertFalse((prepared.stage_dir / "_internal/removed.txt").exists())
        self.assertEqual((prepared.stage_dir / "_internal/runtime.bin").read_bytes(), self.contents["_internal/runtime.bin"])

    def test_tampered_cached_bundle_is_downloaded_again(self):
        self.prepare()
        bundle = next((self.updates / "bundles").glob("*.bin"))
        value = bytearray(bundle.read_bytes())
        value[0] ^= 1
        bundle.write_bytes(value)
        self.urls.clear()
        self.prepare()
        self.assertEqual(len(self.urls), 1)
        self.assertTrue(self.urls[0].endswith(bundle.name))

    def test_invalid_download_never_falls_back_to_full_package(self):
        with self.assertRaisesRegex(updater.UpdateError, "SHA-256"):
            self.prepare(opener=lambda *_a, **_k: BytesResponse(b"corrupt"))
        self.assertEqual(list(self.root.glob(".frlg-update-stage-*")), [])
        self.assertEqual(list((self.updates / "bundles").glob("*.part")), [])
        self.assertEqual((self.install / "FRLG-Auto-RNG.exe").read_bytes(), b"old executable")

    def test_local_change_after_plan_rejects_staging(self):
        plan = updater.plan_incremental_update(self.candidate(), install_dir=self.install, updates_root=self.updates)
        (self.install / "_internal/runtime.bin").write_bytes(b"changed after scan")
        with self.assertRaisesRegex(updater.UpdateError, "校验失败"):
            self.prepare(incremental_plan=plan)
        self.assertEqual(list(self.root.glob(".frlg-update-stage-*")), [])

    def test_cancel_staging_removes_stage_and_keeps_download_cache(self):
        self.prepare()
        existing_stages = set(self.root.glob(".frlg-update-stage-*"))
        cancelled = [False]

        def status(text):
            if "组装" in text:
                cancelled[0] = True

        with self.assertRaises(updater.UpdateCancelled):
            self.prepare(cancelled=lambda: cancelled[0], status=status)
        self.assertEqual(set(self.root.glob(".frlg-update-stage-*")), existing_stages)
        self.assertTrue(list((self.updates / "bundles").glob("*.bin")))

    def test_auto_fallback_uses_identical_gitee_bundles_and_manual_does_not(self):
        def opener(request, **kwargs):
            if "github.com" in request.full_url:
                raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
            return self.opener(request, **kwargs)

        with patch.object(updater, "fetch_gitee_candidate", return_value=self.candidate()) as fetch:
            with self.assertRaises(updater.UpdateError):
                self.prepare(self.candidate("github"), opener=opener, allow_gitee_fallback=False)
            fetch.assert_not_called()
            prepared = self.prepare(self.candidate("github"), opener=opener)
            fetch.assert_called_once()
            self.assert_staged(prepared.stage_dir)

    def test_mirror_metadata_mismatch_is_rejected(self):
        mirror = replace(self.candidate(), incremental=None)
        with patch.object(updater, "fetch_gitee_candidate", return_value=mirror):
            with self.assertRaisesRegex(updater.UpdateError, "不一致"):
                self.prepare(self.candidate("github"), opener=lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")))

    def test_candidate_cache_roundtrip_and_wrong_source_urls_rejected(self):
        for source in ("github", "gitee"):
            with self.subTest(source=source):
                candidate = self.candidate(source)
                value = json.loads(json.dumps(updater._candidate_to_json(candidate)))
                self.assertEqual(updater._candidate_from_json(value), candidate)
                name = next(iter(value["incremental_urls"]))
                value["incremental_urls"][name] = f"https://example.invalid/{name}"
                with self.assertRaises(updater.UpdateError):
                    updater._candidate_from_json(value)

    def test_release_discovery_loads_incremental_metadata_without_data_downloads(self):
        for source in ("github", "gitee"):
            candidate = self.candidate(source)
            release = make_release(candidate.manifest) if source == "github" else make_gitee_release(candidate.manifest, 1)
            base = next(iter(dict(candidate.incremental_urls).values())).rsplit("/", 1)[0] + "/"
            release["assets"].extend([
                {"name": incremental.MANIFEST_NAME, "browser_download_url": base + incremental.MANIFEST_NAME},
                *({"name": b.name, "size": b.bytes, "browser_download_url": base + b.name} for b in self.metadata.bundles),
            ])
            legacy = asdict(candidate.manifest)
            if source == "gitee":
                legacy.update(source="gitee-split", repository="dazzling-night-scales/frlg-auto-rng", parts=[
                    {"name": p.name, "bytes": p.bytes, "sha256": p.sha256} for p in candidate.parts
                ])
            responses = [release, legacy, asdict(self.metadata)]
            calls = []

            def opener(request, **kwargs):
                calls.append(request.full_url)
                return BytesResponse(json.dumps(responses.pop(0)).encode())

            result = updater.check_for_update(
                source=source, cache_dir=self.root / (source + "-check"), force=True,
                current_version_code=1, opener=opener,
            )
            self.assertEqual(result.status, "available", result.message)
            self.assertEqual(result.candidate.incremental, self.metadata)
            self.assertEqual(len(calls), 3)
            self.assertFalse(any("update-data-" in url for url in calls))
            cached = updater.check_for_update(
                source=source, cache_dir=self.root / (source + "-check"), current_version_code=1,
                opener=lambda *_a, **_k: self.fail("must reuse metadata cache"),
            )
            self.assertTrue(cached.from_cache)
            self.assertEqual(cached.candidate, result.candidate)

    def test_manifest_rejects_unsafe_paths_and_invalid_bounds(self):
        original = json.loads(json.dumps(asdict(self.metadata)))
        for name in ("../escape", "C:/escape", "_internal/a:stream", "_internal/CON.txt", "/absolute", "_internal/../x", "_internal/end."):
            data = copy.deepcopy(original)
            data["files"][0]["path"] = name
            with self.subTest(path=name), self.assertRaises(incremental.IncrementalError):
                incremental.parse_manifest(data)
        data = copy.deepcopy(original)
        data["files"][0]["blocks"][0]["offset"] = incremental.BUNDLE_BYTES
        with self.assertRaises(incremental.IncrementalError):
            incremental.parse_manifest(data)
        data = copy.deepcopy(original)
        data["files"][1]["path"] = data["files"][0]["path"].upper()
        with self.assertRaises(incremental.IncrementalError):
            incremental.parse_manifest(data)

    def test_bundle_decompression_rejects_oversized_output_and_trailing_content(self):
        for payload, expected_size in ((zlib.compress(b"a" * 200000), 1), (zlib.compress(b"a") + b"trailing", 1)):
            digest = hashlib.sha256(payload).hexdigest()
            bundle = incremental.Bundle(f"update-data-{digest}.bin", len(payload), digest, expected_size)
            path = self.root / bundle.name
            path.write_bytes(payload)
            with self.assertRaisesRegex(incremental.IncrementalError, "解压大小或格式"):
                incremental.unpack_bundle(path, bundle)

    def test_missing_incremental_asset_fails_without_downloading_full_zip(self):
        candidate = self.candidate()
        url = next(iter(dict(candidate.incremental_urls).values())).rsplit("/", 1)[0] + "/" + incremental.MANIFEST_NAME
        assets = {incremental.MANIFEST_NAME: {"name": incremental.MANIFEST_NAME, "browser_download_url": url}}
        calls = []

        def opener(request, **kwargs):
            calls.append(request.full_url)
            return BytesResponse(json.dumps(asdict(self.metadata)).encode())

        with self.assertRaisesRegex(updater.UpdateError, "缺少增量数据包"):
            updater._attach_incremental(candidate, assets, opener)
        self.assertEqual(calls, [url])

    def test_builder_is_deterministic_and_verifier_binds_to_zip_contents(self):
        other = incremental.create_assets(self.new, asdict(self.manifest), self.root / "assets2")
        self.assertEqual(other, self.metadata)
        self.assertEqual(incremental.verify_release_assets(self.package, asdict(self.manifest), self.assets), self.metadata)
        (self.new / "FRLG-Auto-RNG.exe").write_bytes(b"bad executable")  # Same length.
        bad_assets = self.root / "bad-assets"
        incremental.create_assets(self.new, asdict(self.manifest), bad_assets)
        with self.assertRaisesRegex(incremental.IncrementalError, "ZIP 内容不一致"):
            incremental.verify_release_assets(self.package, asdict(self.manifest), bad_assets)

    def test_large_file_is_split_into_bounded_bundles(self):
        # Lower the build target to exercise cross-bundle reconstruction cheaply.
        with patch.object(incremental, "BUNDLE_BYTES", 1024 * 1024):
            metadata = incremental.create_assets(self.new, asdict(self.manifest), self.root / "split")
        runtime = next(file for file in metadata.files if file.path == "_internal/runtime.bin")
        self.assertEqual(len(runtime.blocks), 2)
        rebuilt = b"".join(
            incremental.unpack_bundle(self.root / "split" / block.bundle, next(b for b in metadata.bundles if b.name == block.bundle))[block.offset:block.offset + block.bytes]
            for block in runtime.blocks
        )
        self.assertEqual(rebuilt, self.contents[runtime.path])

    def test_staged_incremental_update_uses_existing_rollback(self):
        prepared = self.prepare()
        request_path = updater.write_install_request(prepared, current_pid=123)
        request = InstallRequest.from_path(request_path, allowed_updates_root=self.updates)
        result = apply_update(
            request, wait_pid=lambda *_: True,
            launch=lambda *_: (_ for _ in ()).throw(OSError("new version cannot start")),
        )
        self.assertEqual(result.status, "rolled_back")
        self.assertEqual((self.install / "FRLG-Auto-RNG.exe").read_bytes(), b"old executable")
        self.assertTrue((self.install / "_internal/removed.txt").exists())


if __name__ == "__main__":
    unittest.main()
