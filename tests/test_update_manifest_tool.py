import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_version import APP_VERSION
from tools.create_update_manifest import create_manifest, main


class UpdateManifestToolTests(unittest.TestCase):
    def test_manifest_and_sha_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unpacked = root / "release"
            unpacked.mkdir()
            (unpacked / "FRLG-Auto-RNG.exe").write_bytes(b"main")
            (unpacked / "_internal").mkdir()
            (unpacked / "_internal" / "x").write_bytes(b"internal")
            package = root / f"FRLG-Auto-RNG-{APP_VERSION}-windows-x64.zip"
            package.write_bytes(b"zip bytes")
            result = create_manifest(package, unpacked, notes="notes")
            expected_hash = hashlib.sha256(b"zip bytes").hexdigest()
            self.assertEqual(result["sha256"], expected_hash)
            self.assertEqual(result["bytes"], 9)
            self.assertEqual(result["unpacked_bytes"], 12)
            self.assertEqual(
                json.loads((root / "update-manifest.json").read_text(encoding="utf-8")),
                result,
            )
            self.assertEqual(
                (root / f"{package.name}.sha256").read_text(encoding="ascii"),
                f"{expected_hash}  {package.name}\n",
            )

    def test_invalid_package_or_empty_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unpacked = root / "release"
            unpacked.mkdir()
            package = root / "bad.zip"
            package.write_bytes(b"x")
            with self.assertRaises(ValueError):
                create_manifest(package, unpacked)
            package = root / f"FRLG-Auto-RNG-{APP_VERSION}-windows-x64.zip"
            package.write_bytes(b"x")
            with self.assertRaises(ValueError):
                create_manifest(package, root / "empty")

    def test_manifest_cli_reads_release_notes_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unpacked = root / "release"
            unpacked.mkdir()
            (unpacked / "FRLG-Auto-RNG.exe").write_bytes(b"main")
            package = root / f"FRLG-Auto-RNG-{APP_VERSION}-windows-x64.zip"
            package.write_bytes(b"zip")
            notes = root / f"v{APP_VERSION}.md"
            expected = f"# FRLG Auto RNG {APP_VERSION}\n\nPySide6 正式版。\n"
            notes.write_text(expected, encoding="utf-8")

            with patch.object(sys, "stdout", io.StringIO()):
                code = main(
                    [
                        "--package",
                        str(package),
                        "--unpacked-root",
                        str(unpacked),
                        "--notes-file",
                        str(notes),
                    ]
                )

            self.assertEqual(code, 0)
            manifest = json.loads(
                (root / "update-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["notes"], expected)
