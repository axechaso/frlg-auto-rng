import copy
import json
import unittest
import urllib.error
import urllib.parse
import zipfile
from dataclasses import asdict, replace
from unittest.mock import patch

import app_updater as updater
import incremental_update as incremental
import packed_updates as packed
from tests.test_app_updater import BytesResponse, make_gitee_release, make_release
from tests import test_incremental_update as legacy_tests


class RangeResponse(BytesResponse):
    def __init__(self, payload, *, status=206, headers=None):
        super().__init__(payload, headers)
        self.status = status


class PackedUpdatesTests(unittest.TestCase):
    def setUp(self):
        legacy_tests.IncrementalUpdateTests.setUp(self)
        self.legacy_assets = self.assets
        self.legacy_metadata = self.metadata
        self.assets = self.root / "packed"
        self.metadata = packed.pack_assets(self.legacy_assets, self.assets)
        self.requests = []
        self.range_supported = True

    assert_staged = legacy_tests.IncrementalUpdateTests.assert_staged
    prepare = legacy_tests.IncrementalUpdateTests.prepare

    def candidate(self, source="gitee"):
        candidate = legacy_tests.IncrementalUpdateTests.candidate(self, source)
        base = candidate.parts[0].url.rsplit("/", 1)[0] if candidate.parts else candidate.package_url.rsplit("/", 1)[0]
        return replace(candidate, incremental_urls=tuple((archive.name, base + "/" + archive.name) for archive in self.metadata.archives))

    def opener(self, request, **kwargs):
        self.requests.append(request)
        name = urllib.parse.unquote(request.full_url.rsplit("/", 1)[-1])
        self.assertTrue(name.startswith("update-pack-"), "must not download full ZIP, parts or individual blocks")
        value = (self.assets / name).read_bytes()
        header = request.get_header("Range")
        if self.range_supported and header:
            start, end = map(int, header.removeprefix("bytes=").split("-"))
            return RangeResponse(value[start:end + 1], headers={"Content-Range": f"bytes {start}-{end}/{len(value)}"})
        return RangeResponse(value, status=200)

    def test_range_fetches_only_small_changed_blocks(self):
        candidate = self.candidate()
        plan = updater.plan_incremental_update(candidate, install_dir=self.install, updates_root=self.updates)
        self.assertIsInstance(plan, packed.Plan)
        self.assertGreater(plan.archive_download_bytes, plan.download_bytes)
        progress = []
        prepared = self.prepare(incremental_plan=plan, progress=lambda *value: progress.append(value))
        self.assert_staged(prepared.stage_dir)
        self.assertEqual(progress[-1], (plan.download_bytes, plan.download_bytes))
        self.assertTrue(all(request.get_header("Range") for request in self.requests))
        self.assertEqual(list((self.updates / "archives").glob("*.zip")), [])
        runtime = next(file for file in self.metadata.files if file.path == "_internal/runtime.bin")
        runtime_pack = next(item.archive for item in self.metadata.locations if item.bundle == runtime.blocks[0].bundle)
        self.assertFalse(any(request.full_url.endswith(runtime_pack) for request in self.requests))

    def test_no_range_downloads_related_zip_once_and_keeps_verified_cache(self):
        self.range_supported = False
        messages, progress = [], []
        plan = updater.plan_incremental_update(self.candidate(), install_dir=self.install, updates_root=self.updates)
        prepared = self.prepare(status=messages.append, progress=lambda *value: progress.append(value))
        self.assert_staged(prepared.stage_dir)
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(any("服务器不支持" in message for message in messages))
        self.assertEqual(progress[-1], (plan.archive_download_bytes, plan.archive_download_bytes))
        self.assertEqual(len(list((self.updates / "archives").glob("*.zip"))), 1)
        for path in (self.updates / "bundles").glob("*.bin"):
            path.unlink()
        new_plan = updater.plan_incremental_update(self.candidate(), install_dir=self.install, updates_root=self.updates)
        self.assertEqual(new_plan.download_bytes, 0)
        self.assertEqual(new_plan.archive_download_bytes, 0)
        self.assertGreater(new_plan.cache_bytes, 0)
        prepared = self.prepare(opener=lambda *_a, **_k: self.fail("cached ZIP must avoid networking"))
        self.assert_staged(prepared.stage_dir)

    def test_unsupported_range_status_retries_as_normal_get(self):
        for code in (400, 405, 416, 501):
            with self.subTest(code=code):
                calls = []

                def opener(request, **kwargs):
                    calls.append(request)
                    if request.get_header("Range"):
                        raise urllib.error.HTTPError(request.full_url, code, "Range unavailable", {}, None)
                    return self.opener(request, **kwargs)

                self.updates = self.root / f"http-{code}"
                prepared = self.prepare(opener=opener)
                self.assert_staged(prepared.stage_dir)
                self.assertEqual(len(calls), 2)
                self.assertIsNone(calls[1].get_header("Range"))

    def test_bad_partial_range_is_rejected_not_downgraded(self):
        for header in (None, "bytes 0-1/100", "bytes 0-1/*"):
            with self.subTest(header=header):
                calls = []

                def opener(request, **kwargs):
                    calls.append(request)
                    response = self.opener(request, **kwargs)
                    response.headers = {} if header is None else {"Content-Range": header}
                    return response

                self.updates = self.root / f"bad-range-{len(str(header))}"
                with self.assertRaisesRegex(updater.UpdateError, "范围与清单不一致"):
                    self.prepare(opener=opener)
                self.assertEqual(len(calls), 1)
                self.assertEqual(list(self.updates.rglob("*.part")), [])

    def test_tampered_partial_or_full_response_is_never_installed(self):
        for supports_range in (True, False):
            with self.subTest(range=supports_range):
                self.range_supported = supports_range
                self.updates = self.root / f"corrupt-{supports_range}"

                def opener(request, **kwargs):
                    response = self.opener(request, **kwargs)
                    value = bytearray(response.getvalue())
                    value[0] ^= 1
                    response.seek(0)
                    response.write(value)
                    response.seek(0)
                    return response

                with self.assertRaisesRegex(updater.UpdateError, "SHA-256"):
                    self.prepare(opener=opener)
                self.assertEqual(list(self.updates.rglob("*.part")), [])
                self.assertEqual(list(self.updates.rglob("*.zip")), [])
                self.assertEqual((self.install / "FRLG-Auto-RNG.exe").read_bytes(), b"old executable")

    def test_interrupted_range_keeps_completed_blocks_for_retry(self):
        calls = 0

        def interrupted(request, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise urllib.error.URLError("disconnected")
            return self.opener(request, **kwargs)

        with self.assertRaises(updater.UpdateError):
            self.prepare(opener=interrupted)
        first = self.requests[0].get_header("Range")
        self.assertEqual(len(list((self.updates / "bundles").glob("*.bin"))), 1)
        self.requests.clear()
        prepared = self.prepare()
        self.assert_staged(prepared.stage_dir)
        self.assertNotIn(first, [request.get_header("Range") for request in self.requests])

    def test_server_switching_from_partial_to_full_updates_total_correctly(self):
        calls = 0
        progress = []

        def opener(request, **kwargs):
            nonlocal calls
            calls += 1
            self.range_supported = calls == 1
            return self.opener(request, **kwargs)

        prepared = self.prepare(opener=opener, progress=lambda *value: progress.append(value))
        self.assert_staged(prepared.stage_dir)
        self.assertEqual(calls, 2)
        first = self.requests[0].get_header("Range")
        start, end = map(int, first.removeprefix("bytes=").split("-"))
        archive = next(a for a in self.metadata.archives if self.requests[-1].full_url.endswith(a.name))
        expected = end - start + 1 + archive.bytes
        self.assertEqual(progress[-1], (expected, expected))

    def test_corrupted_archive_cache_is_downloaded_again_and_small_zip_stays_small(self):
        self.range_supported = False
        self.prepare()
        path = next((self.updates / "archives").glob("*.zip"))
        value = bytearray(path.read_bytes())
        value[0] ^= 1
        path.write_bytes(value)
        for block in (self.updates / "bundles").glob("*.bin"):
            block.unlink()
        self.requests.clear()
        prepared = self.prepare()
        self.assert_staged(prepared.stage_dir)
        self.assertEqual(len(self.requests), 1)
        self.assertLess(path.stat().st_size, 1024 * 1024)
        archive = next(a for a in self.metadata.archives if a.name == path.name)
        self.assertTrue(incremental.matches(path, archive.bytes, archive.sha256, lambda: None))

    def test_no_changes_do_not_open_any_zip_or_server(self):
        for name, value in self.contents.items():
            (self.install / name).write_bytes(value)
        plan = updater.plan_incremental_update(self.candidate(), install_dir=self.install, updates_root=self.updates)
        self.assertEqual((plan.download_bytes, plan.archive_download_bytes, plan.cache_bytes), (0, 0, 0))
        prepared = self.prepare(opener=lambda *_a, **_k: self.fail("unchanged install must not download anything"))
        for name, value in self.contents.items():
            self.assertEqual((prepared.stage_dir / name).read_bytes(), value)

    def test_cache_disk_check_reserves_whole_archives_not_only_ranges(self):
        from types import SimpleNamespace

        plan = updater.plan_incremental_update(self.candidate(), install_dir=self.install, updates_root=self.updates)
        self.updates.mkdir()
        reserve = self.manifest.unpacked_bytes + 256 * 1024 * 1024
        # Installation and cache share a volume in the fixture. Available space
        # covers range-only transfer, not its advertised safe full-ZIP fallback.
        free = reserve + plan.download_bytes
        with patch.object(updater.shutil, "disk_usage", return_value=SimpleNamespace(free=free)):
            with self.assertRaisesRegex(updater.UpdateError, "缓存盘剩余空间不足"):
                self.prepare(incremental_plan=plan, opener=lambda *_a, **_k: self.fail("must fail before downloading"))

    def test_cancel_during_full_zip_removes_partial_not_install(self):
        self.range_supported = False
        cancelled = [False]

        def progress(received, total):
            if received:
                cancelled[0] = True

        with self.assertRaises(updater.UpdateCancelled):
            self.prepare(progress=progress, cancelled=lambda: cancelled[0])
        self.assertEqual(list(self.updates.rglob("*.part")), [])
        self.assertEqual(list(self.updates.rglob("*.zip")), [])
        self.assertEqual((self.install / "FRLG-Auto-RNG.exe").read_bytes(), b"old executable")

    def test_extra_bytes_and_content_encoding_are_rejected(self):
        for kind in ("extra", "gzip"):
            with self.subTest(kind=kind):
                self.updates = self.root / kind

                def opener(request, **kwargs):
                    response = self.opener(request, **kwargs)
                    if kind == "extra":
                        value = response.getvalue() + b"extra"
                        return RangeResponse(value, headers=response.headers)
                    response.headers["Content-Encoding"] = "gzip"
                    return response

                with self.assertRaises(updater.UpdateError):
                    self.prepare(opener=opener)
                self.assertEqual(list(self.updates.rglob("*.part")), [])

    def test_hash_cached_blocks_work_across_v1_and_v2(self):
        candidate = self.candidate()
        legacy = replace(candidate, incremental=self.legacy_metadata, incremental_urls=tuple(
            (bundle.name, candidate.parts[0].url.rsplit("/", 1)[0] + "/" + bundle.name) for bundle in self.legacy_metadata.bundles
        ))
        prepared = self.prepare(legacy, opener=lambda request, **_k: BytesResponse((self.legacy_assets / request.full_url.rsplit("/", 1)[-1]).read_bytes()))
        self.assert_staged(prepared.stage_dir)
        plan = updater.plan_incremental_update(candidate, install_dir=self.install, updates_root=self.updates)
        self.assertEqual(plan.download_bytes, 0)
        prepared = self.prepare(candidate, opener=lambda *_a, **_k: self.fail("v1 cache must be reusable"))
        self.assert_staged(prepared.stage_dir)

    def test_cache_roundtrip_and_wrong_archive_source_rejected(self):
        for source in ("github", "gitee"):
            candidate = self.candidate(source)
            data = json.loads(json.dumps(updater._candidate_to_json(candidate)))
            self.assertEqual(updater._candidate_from_json(data), candidate)
            name = next(iter(data["incremental_urls"]))
            data["incremental_urls"][name] = "https://example.invalid/" + name
            with self.assertRaises(updater.UpdateError):
                updater._candidate_from_json(data)

    def test_discovery_prefers_new_manifest_and_only_downloads_metadata(self):
        for source in ("github", "gitee"):
            with self.subTest(source=source):
                candidate = self.candidate(source)
                release = make_release(candidate.manifest) if source == "github" else make_gitee_release(candidate.manifest, 1)
                base = dict(candidate.incremental_urls)[self.metadata.archives[0].name].rsplit("/", 1)[0] + "/"
                release["assets"].extend([
                    {"name": packed.MANIFEST_NAME, "browser_download_url": base + packed.MANIFEST_NAME},
                    *({"name": a.name, "size": a.bytes, "browser_download_url": base + a.name} for a in self.metadata.archives),
                ])
                legacy = asdict(candidate.manifest)
                if source == "gitee":
                    legacy.update(source="gitee-split", repository="dazzling-night-scales/frlg-auto-rng", parts=[
                        {"name": part.name, "bytes": part.bytes, "sha256": part.sha256} for part in candidate.parts
                    ])
                responses = [release, legacy, asdict(self.metadata)]
                calls = []

                def opener(request, **kwargs):
                    calls.append(request.full_url)
                    return BytesResponse(json.dumps(responses.pop(0)).encode())

                result = updater.check_for_update(source=source, cache_dir=self.root / source, force=True, current_version_code=1, opener=opener)
                self.assertEqual(result.status, "available", result.message)
                self.assertEqual(result.candidate.incremental, self.metadata)
                self.assertEqual(len(calls), 3)
                self.assertTrue(calls[-1].endswith(packed.MANIFEST_NAME))
                self.assertFalse(any("update-pack-" in url for url in calls))

    def test_missing_new_asset_or_invalid_manifest_never_downgrades(self):
        candidate = self.candidate()
        base = candidate.parts[0].url.rsplit("/", 1)[0] + "/"
        assets = {name: {"name": name, "browser_download_url": base + name} for name in (packed.MANIFEST_NAME, incremental.MANIFEST_NAME)}
        for value, reason in ((asdict(self.metadata), "缺少增量数据包"), ({"schema": 2}, "结构")):
            with self.subTest(reason=reason), self.assertRaisesRegex(updater.UpdateError, reason):
                updater._attach_incremental(candidate, assets, lambda *_a, **_k: BytesResponse(json.dumps(value).encode()))

    def test_old_client_can_ignore_new_name_and_use_whole_package(self):
        # 0.9.5 only looks for incremental-manifest.json. Keep that name absent
        # from new assets and retain the unchanged legacy full-package manifest.
        self.assertNotIn(incremental.MANIFEST_NAME, packed.asset_names(self.metadata))
        candidate = replace(self.candidate(), incremental=None, incremental_urls=())
        self.assertEqual(updater._attach_incremental(candidate, {}, lambda *_a, **_k: self.fail("no incremental metadata")), candidate)
        prepared = self.prepare(candidate, opener=lambda *_a, **_k: BytesResponse(self.package.read_bytes()))
        self.assert_staged(prepared.stage_dir)

    def test_mirror_fallback_requires_identical_packed_metadata_and_manual_stays_put(self):
        def offline_github(request, **kwargs):
            if "github.com" in request.full_url:
                raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
            return self.opener(request, **kwargs)

        with patch.object(updater, "fetch_gitee_candidate", return_value=self.candidate()) as fetch:
            with self.assertRaises(updater.UpdateError):
                self.prepare(self.candidate("github"), opener=offline_github, allow_gitee_fallback=False)
            fetch.assert_not_called()
            prepared = self.prepare(self.candidate("github"), opener=offline_github)
            fetch.assert_called_once()
            self.assert_staged(prepared.stage_dir)
        self.updates = self.root / "mismatch"
        with patch.object(updater, "fetch_gitee_candidate", return_value=replace(self.candidate(), incremental=self.legacy_metadata)):
            with self.assertRaisesRegex(updater.UpdateError, "不一致"):
                self.prepare(self.candidate("github"), opener=offline_github)

    def test_builder_deterministic_small_pack_separate_and_bounded(self):
        other = packed.pack_assets(self.legacy_assets, self.root / "other")
        self.assertEqual(other, self.metadata)
        self.assertEqual(len(self.metadata.archives), 2)
        self.assertEqual(len(packed.asset_names(self.metadata)), 3)
        self.assertEqual(packed.verify_release_assets(self.package, asdict(self.manifest), self.assets), self.metadata)
        self.assertEqual(incremental.parse_manifest(json.loads((self.legacy_assets / incremental.MANIFEST_NAME).read_text(encoding="utf-8"))), self.legacy_metadata)
        for archive in self.metadata.archives:
            self.assertLessEqual(archive.bytes, packed.MAX_ARCHIVE_BYTES)
            with zipfile.ZipFile(self.assets / archive.name) as reader:
                self.assertIsNone(reader.testzip())

    def test_new_build_isolates_labels_from_small_binary_runtime(self):
        path = self.new / "_internal/small-runtime.dll"
        path.write_bytes(b"runtime" * 10000)
        # Rebuild the complete ZIP/manifest for this added file.
        contents = {**self.contents, "_internal/small-runtime.dll": path.read_bytes()}
        with zipfile.ZipFile(self.package, "w") as archive:
            for name, value in contents.items():
                archive.writestr(name, value)
        from tests.test_app_updater import make_manifest
        manifest = make_manifest(
            bytes=self.package.stat().st_size, sha256=incremental.digest_file(self.package),
            unpacked_bytes=sum(map(len, contents.values())),
        )
        assets = self.root / "resources-split"
        metadata = packed.create_assets(self.new, asdict(manifest), assets)
        self.assertEqual(packed.verify_release_assets(self.package, asdict(manifest), assets), metadata)
        files = {file.path: file for file in metadata.files}
        locations = {item.bundle: item.archive for item in metadata.locations}
        script_archive = locations[files["_internal/更新.ecs"].blocks[0].bundle]
        self.assertNotEqual(script_archive, locations[files["_internal/small-runtime.dll"].blocks[0].bundle])
        self.assertNotEqual(script_archive, locations[files["_internal/runtime.bin"].blocks[0].bundle])
        archive = next(a for a in metadata.archives if a.name == script_archive)
        with zipfile.ZipFile(assets / archive.name) as reader:
            for info in reader.infolist():
                self.assertTrue(all(
                    file.path.endswith(tuple(incremental.RESOURCE_SUFFIXES)) for file in metadata.files
                    if any(block.bundle == info.filename for block in file.blocks)
                ))

    def test_parser_rejects_overlapping_missing_or_out_of_bounds_locations(self):
        original = json.loads(json.dumps(asdict(self.metadata)))
        mutations = (
            lambda data: data["locations"].pop(),
            lambda data: data["locations"].__setitem__(0, data["locations"][1].copy()),
            lambda data: data["locations"][0].__setitem__("offset", -1),
            lambda data: data["locations"][0].__setitem__("offset", True),
            lambda data: data["locations"][0].__setitem__("offset", packed.MAX_ARCHIVE_BYTES),
            lambda data: data["locations"][0].__setitem__("archive", "../escape.zip"),
            lambda data: data["archives"][0].__setitem__("bytes", packed.MAX_ARCHIVE_BYTES + 1),
            lambda data: data["archives"][0].__setitem__("name", "../escape.zip"),
            lambda data: data["locations"][1].__setitem__("offset", data["locations"][0]["offset"]),
        )
        for index, mutation in enumerate(mutations):
            data = copy.deepcopy(original)
            mutation(data)
            with self.subTest(index=index), self.assertRaises(incremental.IncrementalError):
                packed.parse_manifest(data)

    def test_verifier_rejects_archive_tampering_and_wrong_offsets(self):
        archive = self.metadata.archives[0]
        path = self.assets / archive.name
        original = path.read_bytes()
        path.write_bytes(original[:-1])
        with self.assertRaisesRegex(incremental.IncrementalError, "摘要不符"):
            packed.verify_release_assets(self.package, asdict(self.manifest), self.assets)
        path.write_bytes(original)
        data = json.loads(json.dumps(asdict(self.metadata)))
        data["locations"][0]["offset"] += 1
        (self.assets / packed.MANIFEST_NAME).write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(incremental.IncrementalError, "成员位置"):
            packed.verify_release_assets(self.package, asdict(self.manifest), self.assets)

    def test_repacking_rejects_overlap_existing_output_and_too_small_cap(self):
        for output in (self.legacy_assets, self.legacy_assets / "nested", self.root):
            with self.subTest(output=output), self.assertRaises(incremental.IncrementalError):
                packed.pack_assets(self.legacy_assets, output)
        with self.assertRaises(FileExistsError):
            packed.pack_assets(self.legacy_assets, self.assets)
        with self.assertRaises(incremental.IncrementalError):
            packed.pack_assets(self.legacy_assets, self.root / "tiny", max_archive_bytes=100)
        self.assertFalse((self.root / "tiny").exists())
        with self.assertRaises(incremental.IncrementalError):
            packed.create_assets(self.new, asdict(self.manifest), self.new / "nested")

    def test_changed_runtime_full_zip_fallback_does_not_fetch_small_pack(self):
        # A large binary edit cannot invalidate the independently grouped scripts.
        for name, value in self.contents.items():
            (self.install / name).write_bytes(value)
        (self.install / "_internal/runtime.bin").write_bytes(b"old runtime")
        self.range_supported = False
        prepared = self.prepare()
        for name, value in self.contents.items():
            self.assertEqual((prepared.stage_dir / name).read_bytes(), value)
        self.assertEqual((self.install / "_internal/runtime.bin").read_bytes(), b"old runtime")
        self.assertEqual(len(self.requests), 1)
        name = self.requests[0].full_url.rsplit("/", 1)[-1]
        self.assertGreater((self.assets / name).stat().st_size, 2 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
