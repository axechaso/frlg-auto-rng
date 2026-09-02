import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.create_update_manifest import create_manifest


class UpdateManifestToolTests(unittest.TestCase):
    def test_manifest_and_sha_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unpacked = root / "release"
            unpacked.mkdir()
            (unpacked / "FRLG-Auto-RNG.exe").write_bytes(b"main")
            (unpacked / "_internal").mkdir()
            (unpacked / "_internal" / "x").write_bytes(b"internal")
            package = root / "FRLG-Auto-RNG-0.2-windows-x64.zip"
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
            package = root / "FRLG-Auto-RNG-0.2-windows-x64.zip"
            package.write_bytes(b"x")
            with self.assertRaises(ValueError):
                create_manifest(package, root / "empty")
