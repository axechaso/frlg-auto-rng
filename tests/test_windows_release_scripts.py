import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsReleaseScriptTests(unittest.TestCase):
    def test_build_script_contains_updater_and_manifest_steps(self):
        source = (ROOT / "tools" / "build_windows_release.ps1").read_text(encoding="utf-8")
        for required in (
            "FRLG-Auto-RNG-Updater",
            "tools.create_update_manifest",
            "--notes-file",
            "--onefile",
            "--version-json-file",
            '"truststore==0.10.4"',
            '"PySide6==6.11.2"',
            '"--collect-all", "PySide6"',
            '"--exclude-module", "tkinter"',
            '"--exclude-module", "tkinterdnd2"',
            '"--hidden-import", "run_pyside6_gui"',
            '"--screenshot"',
            '$ForeignIcuPatterns',
            '"icuuc.dll", "icudt*.dll", "icuin*.dll"',
            'Remove-Item -Force -LiteralPath $ForeignIcu.FullName',
        ):
            self.assertIn(required, source)
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
