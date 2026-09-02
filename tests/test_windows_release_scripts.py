import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsReleaseScriptTests(unittest.TestCase):
    def test_build_script_contains_updater_and_manifest_steps(self):
        source = (ROOT / "tools" / "build_windows_release.ps1").read_text(encoding="utf-8")
        self.assertIn("FRLG-Auto-RNG-Updater", source)
        self.assertIn("tools.create_update_manifest", source)
        self.assertIn("--onefile", source)
        self.assertIn("--version-json-file", source)

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
        ):
            self.assertIn(required, source)
        self.assertNotIn("Remove-Item", source)
        self.assertNotIn("$BuildRoot\\*", source)
        self.assertNotIn("Authorization: token", source)
