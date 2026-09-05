import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PySidePreviewTests(unittest.TestCase):
    def test_preview_is_isolated_from_production_entry(self):
        source = (ROOT / "pyside_preview.py").read_text(encoding="utf-8")
        self.assertIn("class FrlgPreviewWindow(QMainWindow):", source)
        self.assertNotIn("from run_auto_rng_gui import", source)
        self.assertNotIn("EasyConController(", source)
        self.assertEqual(
            (ROOT / "requirements-pyside-preview.txt").read_text(encoding="utf-8").splitlines()[-1],
            "PySide6>=6.7,<7",
        )

    @unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is an optional preview dependency")
    def test_offscreen_preview_renders_a_real_png(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "preview.png"
            env = dict(os.environ)
            env["QT_QPA_PLATFORM"] = "offscreen"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "pyside_preview.py"),
                    "--page",
                    "wild",
                    "--screenshot",
                    str(output),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = output.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            # Qt's Windows offscreen backend intentionally skips the system font
            # database, so its compressed PNG is much smaller than a real window
            # capture.  The header plus a non-trivial payload is enough here; the
            # Windows-backed screenshot is inspected separately during UI QA.
            self.assertGreater(len(data), 20_000)


if __name__ == "__main__":
    unittest.main()
