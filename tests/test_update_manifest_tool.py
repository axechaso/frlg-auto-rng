import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app_version import APP_VERSION
from tools.create_update_manifest import create_gitee_release_assets, create_manifest, main


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

    def test_gitee_release_assets_are_sequential_verified_parts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unpacked = root / "release"
            unpacked.mkdir()
            (unpacked / "FRLG-Auto-RNG.exe").write_bytes(b"main")
            package = root / f"FRLG-Auto-RNG-{APP_VERSION}-windows-x64.zip"
            package.write_bytes(b"0123456789")
            manifest = create_manifest(package, unpacked, notes="notes")

            gitee = create_gitee_release_assets(
                package, manifest, root / "gitee-release-assets", part_size=4,
            )

            self.assertEqual(gitee["source"], "gitee-split")
            self.assertEqual(gitee["repository"], "dazzling-night-scales/frlg-auto-rng")
            self.assertEqual(
                [part["name"] for part in gitee["parts"]],
                [f"{package.name}.001", f"{package.name}.002", f"{package.name}.003"],
            )
            rebuilt = b"".join(
                (root / "gitee-release-assets" / part["name"]).read_bytes()
                for part in gitee["parts"]
            )
            self.assertEqual(rebuilt, package.read_bytes())
            self.assertEqual(
                json.loads(
                    (root / "gitee-release-assets" / "gitee-update-manifest.json").read_text(
                        encoding="utf-8"
                    )
                ),
                gitee,
            )

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

    def test_cli_builds_identical_incremental_assets_for_both_sources(self):
        from packed_updates import MANIFEST_NAME, asset_names, verify_release_assets

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unpacked = root / "release"
            contents = {"FRLG-Auto-RNG.exe": b"main", "FRLG-Auto-RNG-Updater.exe": b"updater", "_internal/data": b"data"}
            package = root / f"FRLG-Auto-RNG-{APP_VERSION}-windows-x64.zip"
            with zipfile.ZipFile(package, "w") as archive:
                for name, value in contents.items():
                    path = unpacked / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(value)
                    archive.writestr(name, value)
            incremental = root / "incremental"
            gitee = root / "gitee"
            with patch.object(sys, "stdout", io.StringIO()):
                self.assertEqual(main([
                    "--package", str(package), "--unpacked-root", str(unpacked),
                    "--gitee-assets-dir", str(gitee), "--incremental-assets-dir", str(incremental),
                ]), 0)
            manifest = json.loads((root / "update-manifest.json").read_text(encoding="utf-8"))
            metadata = verify_release_assets(package, manifest, incremental)
            for name in asset_names(metadata):
                self.assertEqual((gitee / name).read_bytes(), (incremental / name).read_bytes())
            self.assertEqual(metadata.schema, 2)
            self.assertNotIn("incremental-manifest.json", [path.name for path in gitee.iterdir()])

    def test_repack_tool_preserves_old_assets_and_outputs_exact_compact_names(self):
        from incremental_update import create_assets
        from packed_updates import asset_names, verify_release_assets
        from tools.pack_incremental_release import main as repack
        from tools.verify_incremental_release import main as verify

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unpacked = root / "release"
            contents = {"FRLG-Auto-RNG.exe": b"main", "FRLG-Auto-RNG-Updater.exe": b"updater", "_internal/data": b"data"}
            package = root / f"FRLG-Auto-RNG-{APP_VERSION}-windows-x64.zip"
            with zipfile.ZipFile(package, "w") as archive:
                for name, value in contents.items():
                    path = unpacked / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(value)
                    archive.writestr(name, value)
            manifest = create_manifest(package, unpacked)
            old = root / "old"
            create_assets(unpacked, manifest, old)
            old_values = {path.name: path.read_bytes() for path in old.iterdir()}
            output, gitee = root / "packed", root / "gitee"
            with patch.object(sys, "stdout", io.StringIO()):
                self.assertEqual(repack([
                    "--package", str(package), "--manifest", str(root / "update-manifest.json"),
                    "--assets-dir", str(old), "--output-dir", str(output), "--gitee-output-dir", str(gitee),
                ]), 0)
            metadata = verify_release_assets(package, manifest, output)
            self.assertEqual({path.name: path.read_bytes() for path in old.iterdir()}, old_values)
            self.assertEqual({path.name for path in output.iterdir()}, set(asset_names(metadata)))
            for name in asset_names(metadata):
                self.assertEqual((output / name).read_bytes(), (gitee / name).read_bytes())
            with patch.object(sys, "argv", ["verify", "--package", str(package), "--manifest", str(root / "update-manifest.json"), "--assets-dir", str(output)]), patch.object(sys, "stdout", io.StringIO()) as stdout:
                verify()
                self.assertEqual(json.loads(stdout.getvalue()), list(asset_names(metadata)))
