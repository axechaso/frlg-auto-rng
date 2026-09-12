import unittest
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from tools.stage_release_assets import stage_assets


ROOT = Path(__file__).resolve().parents[1]


class WindowsReleaseScriptTests(unittest.TestCase):
    def test_build_script_contains_updater_and_manifest_steps(self):
        source = (ROOT / "tools" / "build_windows_release.ps1").read_text(encoding="utf-8")
        for required in (
            "FRLG-Auto-RNG-Updater",
            "tools.create_update_manifest",
            "tools.stage_release_assets $LocalAssets $StagedAssets",
            "tools.verify_frozen_workers --exe $frozenMain",
            "--notes-file",
            "--onefile",
            "--version-json-file",
            '"truststore==0.10.4"',
            '"PySide6==6.11.2"',
            '"--exclude-module", "tkinter"',
            '"--exclude-module", "tkinterdnd2"',
            '"--hidden-import", "run_pyside6_gui"',
            '"--screenshot"',
            '$ForeignIcuPatterns',
            '"icuuc.dll", "icudt*.dll", "icuin*.dll"',
            'Remove-Item -Force -LiteralPath $ForeignIcu.FullName',
        ):
            self.assertIn(required, source)
        self.assertNotIn('"--collect-all", "PySide6"', source)
        self.assertGreaterEqual(source.count('"--collect-submodules", "truststore"'), 2)
        for removed in (
            "$TkinterBinary",
            "$TclBinary",
            "$TkBinary",
            "_tcl_data",
            "_tk_data",
            "hook-tkinterdnd2.py",
        ):
            self.assertNotIn(removed, source)

    def test_formal_requirements_pin_pyside6(self):
        requirements = (ROOT / "requirements-auto.txt").read_text(encoding="utf-8")
        self.assertIn("PySide6==6.11.2", requirements)

    def test_publisher_requires_preflight_and_draft_verification(self):
        source = (ROOT / "tools" / "publish_windows_release.ps1").read_text(encoding="utf-8")
        for required in (
            "git diff --quiet",
            "git ls-remote origin refs/heads/main",
            "gh api user --jq .login",
            "gh run list",
            "--draft",
            "gh release upload $Tag $Package $Manifest $ShaFile",
            "make_latest=true",
            "草稿 Release 已保留",
            "--notes-file $NotesFile",
        ):
            self.assertIn(required, source)
        self.assertNotIn("Remove-Item", source)
        self.assertNotIn("$BuildRoot\\*", source)
        self.assertNotIn("Authorization: token", source)

    def test_staging_copies_only_audited_ocr_models_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            models = source / "easycon118/Tessdata"
            models.mkdir(parents=True)
            (models / "required.traineddata").write_bytes(b"model")
            (models / "experimental.traineddata").write_bytes(b"experiment")
            (source / "tid.ecs").write_bytes(b"tid")
            expected = {"required.traineddata": hashlib.sha256(b"model").hexdigest()}
            with patch("tools.stage_release_assets.EXPECTED_TESSDATA_SHA256", expected):
                staged = stage_assets(source, root / "staged")
                self.assertEqual((staged / "tid.ecs").read_bytes(), b"tid")
                self.assertEqual(list((staged / "easycon118/Tessdata").iterdir()),
                                 [staged / "easycon118/Tessdata/required.traineddata"])
                self.assertEqual((models / "experimental.traineddata").read_bytes(), b"experiment")
                with self.assertRaises(FileExistsError):
                    stage_assets(source, staged)
                with self.assertRaises(ValueError):
                    stage_assets(source, source / "nested")
                (models / "required.traineddata").write_bytes(b"modified")
                with self.assertRaisesRegex(ValueError, "fingerprint"):
                    stage_assets(source, root / "bad")
                self.assertFalse((root / "bad").exists())
