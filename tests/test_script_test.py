import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automation import script_test


class DirectScriptTestTests(unittest.TestCase):
    def _project(self, root: Path, *, with_label: bool = True) -> Path:
        main = root / "main.ecs"
        main.write_text(
            "$分数 = @火红BAG\nPRINT $分数\n# @注释标签不应被加载\n",
            encoding="utf-8",
        )
        lib_dir = root / "lib"
        lib_dir.mkdir()
        (lib_dir / "extra.ecs").write_text(
            "$箭头 = @三代菜单栏\n",
            encoding="utf-8",
        )
        if with_label:
            label_dir = root / "ImgLabel"
            label_dir.mkdir()
            (label_dir / "火红BAG.IL").write_bytes(b"bag")
            (label_dir / "三代菜单栏.IL").write_bytes(b"cursor")
        return main

    def test_inspects_main_and_sibling_lib_label_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            main = self._project(Path(temporary))
            self.assertEqual(
                script_test.inspect_script_label_references(main),
                ("三代菜单栏", "火红BAG"),
            )

    def test_original_backend_uses_pinned_raw_cli_and_formats_in_place(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main = self._project(root)
            ezcon = root / "ezcon.exe"
            ezcon.write_bytes(b"pinned-ezcon")
            expected_hash = hashlib.sha256(ezcon.read_bytes()).hexdigest()
            version = subprocess.CompletedProcess(
                [],
                0,
                stdout=script_test.EXPECTED_EZCON_VERSION + "\n",
                stderr="",
            )
            formatted = subprocess.CompletedProcess([], 0, stdout="formatted", stderr="")
            with mock.patch.object(script_test, "EXPECTED_EZCON_SHA256", expected_hash), mock.patch.object(
                script_test, "EXPECTED_TESSDATA_SHA256", {}
            ), mock.patch.object(
                script_test.subprocess,
                "run",
                side_effect=(version, formatted),
            ) as run:
                preparation = script_test.prepare_script_test_runtime(
                    ezcon,
                    main,
                    script_test.SCRIPT_TEST_BACKEND_ORIGINAL,
                )

            self.assertTrue(preparation.check.ok, preparation.check.errors)
            self.assertEqual(preparation.runner_path, ezcon.resolve())
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[1].args[0][1], "format")
            self.assertEqual(
                main.read_text(encoding="utf-8"),
                "$分数 = @火红BAG\nPRINT $分数\n# @注释标签不应被加载\n",
            )

    def test_missing_direct_label_blocks_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main = self._project(root, with_label=False)
            ezcon = root / "ezcon.exe"
            ezcon.write_bytes(b"pinned-ezcon")
            expected_hash = hashlib.sha256(ezcon.read_bytes()).hexdigest()
            completed = subprocess.CompletedProcess(
                [],
                0,
                stdout=script_test.EXPECTED_EZCON_VERSION + "\n",
                stderr="",
            )
            with mock.patch.object(script_test, "EXPECTED_EZCON_SHA256", expected_hash), mock.patch.object(
                script_test, "EXPECTED_TESSDATA_SHA256", {}
            ), mock.patch.object(
                script_test.subprocess,
                "run",
                side_effect=(completed, completed),
            ):
                preparation = script_test.prepare_script_test_runtime(
                    ezcon,
                    main,
                    script_test.SCRIPT_TEST_BACKEND_ORIGINAL,
                )

            self.assertFalse(preparation.check.ok)
            self.assertIn("缺少 ImgLabel", "\n".join(preparation.check.errors))

    def test_compat_backend_resolves_the_same_runner_as_formal_tool(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main = self._project(root)
            ezcon = root / "ezcon.exe"
            runner = root / "compat.exe"
            ezcon.write_bytes(b"pinned-ezcon")
            runner.write_bytes(b"runner")
            expected_hash = hashlib.sha256(ezcon.read_bytes()).hexdigest()
            completed = subprocess.CompletedProcess(
                [],
                0,
                stdout=script_test.EXPECTED_EZCON_VERSION + "\n",
                stderr="",
            )
            with mock.patch.object(script_test, "EXPECTED_EZCON_SHA256", expected_hash), mock.patch.object(
                script_test, "EXPECTED_TESSDATA_SHA256", {}
            ), mock.patch.object(
                script_test.subprocess,
                "run",
                side_effect=(completed, completed),
            ), mock.patch.object(
                script_test,
                "prepare_compat_runner",
                return_value=runner,
            ) as prepare_runner:
                preparation = script_test.prepare_script_test_runtime(
                    ezcon,
                    main,
                    script_test.SCRIPT_TEST_BACKEND_COMPAT,
                )

            self.assertTrue(preparation.check.ok, preparation.check.errors)
            self.assertEqual(preparation.runner_path, runner)
            prepare_runner.assert_called_once_with(ezcon.resolve())

    def test_missing_ocr_model_blocks_raw_and_compat_comparison(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main = self._project(root)
            ezcon = root / "ezcon.exe"
            ezcon.write_bytes(b"pinned-ezcon")
            expected_hash = hashlib.sha256(ezcon.read_bytes()).hexdigest()
            completed = subprocess.CompletedProcess(
                [],
                0,
                stdout=script_test.EXPECTED_EZCON_VERSION + "\n",
                stderr="",
            )
            with mock.patch.object(script_test, "EXPECTED_EZCON_SHA256", expected_hash), mock.patch.object(
                script_test,
                "EXPECTED_TESSDATA_SHA256",
                {"frlg_battle.traineddata": "0" * 64},
            ), mock.patch.object(
                script_test.subprocess,
                "run",
                side_effect=(completed, completed),
            ):
                preparation = script_test.prepare_script_test_runtime(
                    ezcon,
                    main,
                    script_test.SCRIPT_TEST_BACKEND_ORIGINAL,
                )

            self.assertFalse(preparation.check.ok)
            self.assertIn("Tessdata 缺少", "\n".join(preparation.check.errors))

    def test_builtin_surf_probe_copies_only_required_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source_labels = source / "ImgLabel"
            source_labels.mkdir(parents=True)
            for label in script_test.BUILTIN_EGG_SURF_MENU_LABELS:
                (source_labels / f"{label}.IL").write_bytes(label.encode("utf-8"))
            output = root / "output"

            main = script_test.write_builtin_egg_surf_menu_probe(source, output)

            self.assertTrue(main.is_file())
            self.assertIn("SURF_MENU|SURF_SUMMARY", main.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(path.name for path in (output / "ImgLabel").iterdir()),
                ["冲浪.IL"],
            )
            manifest = json.loads(
                (output / "script-test.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["kind"], "builtin_egg_surf_menu_probe")


if __name__ == "__main__":
    unittest.main()
