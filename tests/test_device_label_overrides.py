import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

import automation.easycon118 as easycon118
from device_label_overrides import (
    PROJECT_OVERRIDE_FILENAME,
    LabelOverrideStore,
    OverrideValidation,
    apply_profile_to_projects,
    capture_device_identity,
    diagnose_label_log,
    inspect_label_directory,
    load_label_override_profile,
    validate_project_overrides,
)


def write_label(path: Path, *, method: int = 5, image: bytes = b"base-image-012345") -> None:
    color = np.frombuffer(hashlib.sha256(image).digest(), dtype=np.uint8)[:3]
    pixels = np.empty((40, 30, 4 if method == 14 else 3), dtype=np.uint8)
    pixels[:, :, :3] = color
    if method == 14:
        pixels[:, :, 3] = 255
    ok, encoded = cv2.imencode(".png", pixels)
    if not ok:
        raise RuntimeError("failed to create label fixture")
    payload = {
        "searchMethod": method,
        "ImgBase64": base64.b64encode(encoded.tobytes()).decode("ascii"),
        "RangeX": 0,
        "RangeY": 0,
        "RangeWidth": 1920,
        "RangeHeight": 1080,
        "TargetX": 10,
        "TargetY": 20,
        "TargetWidth": 30,
        "TargetHeight": 40,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class DeviceLabelOverrideTests(unittest.TestCase):
    def test_capture_profile_uses_device_name_not_volatile_index(self):
        self.assertEqual(capture_device_identity("[3] USB Video"), "USB Video")
        with self.assertRaisesRegex(ValueError, "检测并选择采集卡"):
            capture_device_identity("3")

    def test_audited_base_then_registered_override_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base" / "ImgLabel"
            write_label(base / "HOME_BUFFER正确退出.IL")
            write_label(base / "正确退出.IL", method=3)
            original = (base / "HOME_BUFFER正确退出.IL").read_bytes()
            base_hash = str(inspect_label_directory(base)["sha256"])

            replacement = root / "replacement" / "HOME_BUFFER正确退出.IL"
            write_label(replacement, image=b"device-image-abcdef")
            store = LabelOverrideStore(root / "profiles")
            verification = {"schema": "frlg-label-verification/v1", "same_image": {"passed": True}}
            imported = store.import_paths(
                "[7] USB Capture", (replacement,), (base,),
                provenance={"HOME_BUFFER正确退出.IL": {
                    "incident_id": "incident-1", "verification": verification,
                    "operation": "label_editor", "source": "in_app_label_editor",
                }},
            )
            metadata = store.load_manifest(imported.profile)["files"]["HOME_BUFFER正确退出.IL"]
            self.assertEqual(metadata["incident_id"], "incident-1")
            self.assertEqual(metadata["source"], "in_app_label_editor")
            self.assertEqual(metadata["original_sha256"], hashlib.sha256(original).hexdigest())
            profile = load_label_override_profile(imported.profile.directory)

            project = root / "project"
            shutil.copytree(base, project / "ImgLabel")
            (project / "plan.json").write_text("{}", encoding="utf-8")
            applied = apply_profile_to_projects(project, profile)

            self.assertEqual(len(applied), 1)
            self.assertEqual(
                (base / "HOME_BUFFER正确退出.IL").read_bytes(), original,
                "device overrides must never modify the audited source corpus",
            )
            self.assertTrue((project / PROJECT_OVERRIDE_FILENAME).is_file())
            project_override = json.loads((project / PROJECT_OVERRIDE_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(project_override["files"][0]["incident_id"], "incident-1")
            plan = json.loads((project / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(
                plan["device_label_overrides"]["base_corpus"]["sha256"],
                base_hash,
            )
            check = validate_project_overrides(project / "ImgLabel", base_hash)
            self.assertTrue(check.recognized)
            self.assertTrue(check.ok, check.errors)
            self.assertIn("原始标签包指纹仍已验证", "\n".join(check.warnings))

            # Re-validating the same worker plan is idempotent.
            repeated = apply_profile_to_projects(project, profile)
            self.assertEqual(repeated[0].effective_sha256, applied[0].effective_sha256)

            # Project generators refresh ImgLabel but can leave the old sidecar.
            shutil.rmtree(project / "ImgLabel")
            shutil.copytree(base, project / "ImgLabel")
            refreshed = apply_profile_to_projects(project, profile)
            self.assertEqual(refreshed[0].base_sha256, base_hash)

            # A post-application modification is still a hard validation error.
            write_label(
                project / "ImgLabel" / "正确退出.IL",
                method=3,
                image=b"tampered-image-1234",
            )
            tampered = validate_project_overrides(project / "ImgLabel", base_hash)
            self.assertFalse(tampered.ok)
            self.assertIn("再次修改", "\n".join(tampered.errors))

    def test_override_history_restores_one_label_and_clear_is_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base" / "ImgLabel"
            write_label(base / "known.IL", image=b"base")
            store = LabelOverrideStore(root / "profiles")
            first = root / "revision-one" / "known.IL"
            second = root / "revision-two" / "known.IL"
            write_label(first, image=b"first")
            write_label(second, image=b"second")
            imported = store.import_paths("[2] USB Card", (first,), (base,))
            first_bytes = (imported.profile.label_dir / "known.IL").read_bytes()
            store.import_paths("[2] USB Card", (second,), (base,))
            second_bytes = (imported.profile.label_dir / "known.IL").read_bytes()
            self.assertNotEqual(first_bytes, second_bytes)

            self.assertEqual(store.restore_previous("[2] USB Card", "known.IL"), "已恢复上一版设备标签")
            self.assertEqual((imported.profile.label_dir / "known.IL").read_bytes(), first_bytes)

    def test_interrupted_override_transaction_recovers_before_next_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base" / "ImgLabel"
            write_label(base / "known.IL", image=b"base")
            replacement = root / "replacement" / "known.IL"
            write_label(replacement, image=b"first")
            store = LabelOverrideStore(root / "profiles")
            result = store.import_paths("[2] USB Card", (replacement,), (base,))
            profile = result.profile
            before_label = (profile.label_dir / "known.IL").read_bytes()
            before_manifest = profile.manifest_path.read_bytes()
            transaction = store.root / ".transactions" / profile.key / "pending-recovery"
            (transaction / "before").mkdir(parents=True)
            (transaction / "after").mkdir()
            (transaction / "before" / "known.IL").write_bytes(before_label)
            (transaction / "before" / "manifest.json").write_bytes(before_manifest)
            write_label(root / "replacement-next.IL", image=b"interrupted")
            (profile.label_dir / "known.IL").write_bytes((root / "replacement-next.IL").read_bytes())
            (transaction / "transaction.json").write_text(json.dumps({
                "schema": "frlg-label-override-transaction/v1",
                "transaction_id": "pending-recovery",
                "profile_key": profile.key,
                "status": "prepared",
                "labels": ["known.IL"],
                "before_files": {"known.IL": True},
                "before_manifest_exists": True,
            }), encoding="utf-8")

            listed = store.list_overrides("[2] USB Card")

            self.assertEqual(len(listed), 1)
            self.assertEqual((profile.label_dir / "known.IL").read_bytes(), before_label)
            self.assertEqual(json.loads(profile.manifest_path.read_text(encoding="utf-8"))["files"]["known.IL"]["sha256"], listed[0]["sha256"])

            store.clear("[2] USB Card")
            self.assertEqual(store.list_overrides("[2] USB Card"), ())
            self.assertFalse((profile.label_dir / "known.IL").exists())
            self.assertEqual(store.restore_previous("[2] USB Card", "known.IL"), "已恢复上一版设备标签")
            self.assertEqual((profile.label_dir / "known.IL").read_bytes(), before_label)

    def test_unknown_label_and_method_change_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base" / "ImgLabel"
            write_label(base / "known.IL", method=5)
            store = LabelOverrideStore(root / "profiles")

            unknown = root / "unknown.IL"
            write_label(unknown)
            with self.assertRaisesRegex(ValueError, "没有同名目标"):
                store.import_paths("[0] Card", (unknown,), (base,))

            changed_method = root / "known.IL"
            write_label(changed_method, method=3)
            with self.assertRaisesRegex(ValueError, "searchMethod"):
                store.import_paths("[0] Card", (changed_method,), (base,))

    def test_base_fingerprint_mismatch_never_becomes_a_device_override_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            labels = root / "project" / "ImgLabel"
            write_label(labels / "known.IL")
            (root / "project" / PROJECT_OVERRIDE_FILENAME).write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "profile_key": "fake",
                        "capture_device": "Card",
                        "base_corpus": inspect_label_directory(labels),
                        "effective_corpus": inspect_label_directory(labels),
                        "files": [],
                    }
                ),
                encoding="utf-8",
            )
            check = validate_project_overrides(labels, "expected-audited-hash")
            self.assertFalse(check.ok)
            self.assertIn("原始标签包指纹不一致", "\n".join(check.errors))
            advanced = validate_project_overrides(
                labels,
                "expected-audited-hash",
                fingerprint_warning_only=True,
            )
            self.assertTrue(advanced.ok, advanced.errors)
            self.assertIn("高级模式指纹警告", "\n".join(advanced.warnings))

    def test_easycon_preflight_accepts_valid_override_without_advanced_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ezcon = root / "ezcon.exe"
            ezcon.write_bytes(b"audited-ezcon")
            project = root / "project"
            (project / "lib").mkdir(parents=True)
            (project / "ImgLabel").mkdir()
            main = project / "main.ecs"
            main.write_text("PRINT test\n", encoding="utf-8")
            corpus = {
                "count": easycon118.EXPECTED_LABEL_COUNT,
                "methods": easycon118.EXPECTED_LABEL_METHODS,
                "sha256": "effective-device-corpus",
            }
            version = subprocess.CompletedProcess(
                [], 0, stdout=easycon118.EXPECTED_EZCON_VERSION, stderr=""
            )
            formatted = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            registered = OverrideValidation(
                True,
                True,
                easycon118.EXPECTED_LABEL_SHA256,
                (),
                ("已应用设备标签覆盖",),
            )
            with (
                mock.patch.object(
                    easycon118,
                    "EXPECTED_EZCON_SHA256",
                    hashlib.sha256(ezcon.read_bytes()).hexdigest(),
                ),
                mock.patch.object(easycon118, "EXPECTED_TESSDATA_SHA256", {}),
                mock.patch.object(easycon118, "inspect_label_corpus", return_value=corpus),
                mock.patch.object(
                    easycon118,
                    "validate_project_overrides",
                    return_value=registered,
                ),
                mock.patch.object(
                    easycon118.subprocess,
                    "run",
                    side_effect=(version, formatted),
                ),
            ):
                check = easycon118.validate_runtime(ezcon, main)

            self.assertTrue(check.ok, check.errors)
            self.assertIn("已应用设备标签覆盖", check.warnings)


class LabelLogDiagnosisTests(unittest.TestCase):
    def test_repeated_home_buffer_near_miss_names_the_exact_ns1_label(self):
        failure = (
            "HOME_BUFFER_LABEL|NX=1|BUFFER=94|NORMAL=63|ERROR=57|THRESHOLD=95\n"
        )
        issues = diagnose_label_log(failure * 3)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].labels, ("HOME_BUFFER正确退出.IL",))
        self.assertEqual(issues[0].occurrences, 3)

        recovered = diagnose_label_log(
            failure * 3
            + "HOME_BUFFER_LABEL|NX=1|BUFFER=96|NORMAL=61|ERROR=47|THRESHOLD=95\n"
        )
        self.assertEqual(recovered, ())

    def test_far_below_threshold_is_reported_only_after_repetition(self):
        failure = "孵蛋池塘冲浪检测|尝试=1|冲浪=73\n"
        self.assertEqual(diagnose_label_log(failure), ())
        issues = diagnose_label_log(failure * 3)
        self.assertEqual(issues[0].labels, ("冲浪.IL",))
        self.assertEqual(issues[0].occurrences, 3)

    def test_sid_strict_threshold_and_generic_groups(self):
        failure = "SIDREV|CANDY_LABEL|SCORE=94|THRESHOLD=94\n"
        issues = diagnose_label_log(failure)
        self.assertEqual(issues[0].labels, ("神奇糖果.IL",))
        self.assertEqual(issues[0].threshold, 95)
        self.assertEqual(
            diagnose_label_log(failure + "SIDREV|CANDY_LABEL|SCORE=95|THRESHOLD=94\n"),
            (),
        )
        generic = diagnose_label_log("SPE识图失败")
        self.assertEqual(generic[0].context, "能力值/速度")

    def test_battle_labels_use_their_independent_script_thresholds(self):
        line = "孵蛋池塘战斗检测|尝试=1|野生出现=92|抓捕就绪=94\n"
        issues = diagnose_label_log(line)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].labels, ("抓捕就绪.IL",))
        self.assertEqual(issues[0].threshold, 96)


if __name__ == "__main__":
    unittest.main()
