import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import package_entry


class PackageEntryTests(unittest.TestCase):
    def test_version_json(self):
        output = io.StringIO()
        with patch.object(sys, "stdout", output):
            self.assertEqual(package_entry.main(["--version-json"]), 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "version": "0.2",
                "version_code": 2026090201,
                "update_schema": 1,
                "repository": "axechaso/frlg-auto-rng",
            },
        )

    def test_version_json_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "version.json"
            self.assertEqual(
                package_entry.main(["--version-json-file", str(path)]), 0
            )
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], "0.2")

    def test_health_marker_is_written_before_gui(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "health.json"
            gui = SimpleNamespace(main=lambda: None)
            with patch.dict(sys.modules, {"run_auto_rng_gui": gui}):
                code = package_entry.main(
                    [
                        "--update-health-file",
                        str(path),
                        "--update-health-token",
                        "a" * 32,
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"token": "a" * 32, "version_code": 2026090201},
            )

    def test_invalid_internal_arguments_are_rejected(self):
        self.assertEqual(package_entry.main(["--version-json-file"]), 2)
        self.assertEqual(
            package_entry.main(
                ["--update-health-file", "x", "--update-health-token", "bad"]
            ),
            2,
        )
