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

    def test_resolves_and_identifies_formal_and_timeline_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            formal = source / script_test.STANDARD_TEMPLATE_NAME
            timeline = source / script_test.EGG_TEMPLATE_NAME
            formal.write_text("PRINT 1\n", encoding="utf-8")
            timeline.write_text("PRINT 2\n", encoding="utf-8")

            self.assertEqual(
                script_test.resolve_script_test_entry(
                    source,
                    script_test.SCRIPT_TEST_ENTRY_FORMAL,
                ),
                formal.resolve(),
            )
            self.assertEqual(
                script_test.resolve_script_test_entry(
                    source,
                    script_test.SCRIPT_TEST_ENTRY_TIMELINE,
                ),
                timeline.resolve(),
            )
            self.assertEqual(
                script_test.identify_script_test_entry(source, formal),
                script_test.SCRIPT_TEST_ENTRY_FORMAL,
            )
            self.assertEqual(
                script_test.identify_script_test_entry(source, timeline),
                script_test.SCRIPT_TEST_ENTRY_TIMELINE,
            )
            self.assertEqual(
                script_test.identify_script_test_entry(source, source / "probe.ecs"),
                script_test.SCRIPT_TEST_ENTRY_CUSTOM,
            )

    def test_standard_entry_resolution_reports_missing_and_custom_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            with self.assertRaisesRegex(FileNotFoundError, "正式版脚本"):
                script_test.resolve_script_test_entry(
                    source,
                    script_test.SCRIPT_TEST_ENTRY_FORMAL,
                )
            with self.assertRaisesRegex(ValueError, "自选 ECS"):
                script_test.resolve_script_test_entry(
                    source,
                    script_test.SCRIPT_TEST_ENTRY_CUSTOM,
                )
            with self.assertRaisesRegex(ValueError, "未知"):
                script_test.resolve_script_test_entry(source, "不存在的入口")

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
            prepare_runner.assert_called_once_with(
                ezcon.resolve(),
                fingerprint_warning_only=False,
                fingerprint_warnings=mock.ANY,
            )

    def test_advanced_mode_warns_for_hash_mismatches_but_keeps_hard_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main = self._project(root)
            ezcon = root / "ezcon.exe"
            ezcon.write_bytes(b"locally-modified-ezcon")
            tessdata = root / "Tessdata"
            tessdata.mkdir()
            model_name = "FRLG_EN_ALL.traineddata"
            (tessdata / model_name).write_bytes(b"locally-modified-model")
            completed = subprocess.CompletedProcess(
                [], 0, stdout=script_test.EXPECTED_EZCON_VERSION + "\n", stderr=""
            )
            with mock.patch.object(
                script_test, "EXPECTED_EZCON_SHA256", "0" * 64
            ), mock.patch.object(
                script_test, "EXPECTED_TESSDATA_SHA256", {model_name: "1" * 64}
            ), mock.patch.object(
                script_test.subprocess, "run", side_effect=(completed, completed)
            ):
                preparation = script_test.prepare_script_test_runtime(
                    ezcon,
                    main,
                    script_test.SCRIPT_TEST_BACKEND_ORIGINAL,
                    fingerprint_warning_only=True,
                )

            self.assertTrue(preparation.check.ok, preparation.check.errors)
            warning_text = "\n".join(preparation.check.warnings)
            self.assertIn("高级模式指纹警告", warning_text)
            self.assertIn("ezcon.exe 指纹不一致", warning_text)
            self.assertIn(f"Tessdata/{model_name} 指纹不一致", warning_text)

            (tessdata / model_name).unlink()
            with mock.patch.object(
                script_test, "EXPECTED_EZCON_SHA256", "0" * 64
            ), mock.patch.object(
                script_test, "EXPECTED_TESSDATA_SHA256", {model_name: "1" * 64}
            ), mock.patch.object(
                script_test.subprocess, "run", side_effect=(completed, completed)
            ):
                missing = script_test.prepare_script_test_runtime(
                    ezcon,
                    main,
                    script_test.SCRIPT_TEST_BACKEND_ORIGINAL,
                    fingerprint_warning_only=True,
                )
            self.assertFalse(missing.check.ok)
            self.assertIn("Tessdata 缺少", "\n".join(missing.check.errors))

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
