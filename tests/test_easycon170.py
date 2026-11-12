import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation import easycon170 as backend
from pyside_app.path_settings import restore_easycon_path


class EasyCon170Tests(unittest.TestCase):
    def test_default_and_explicit_rollback(self):
        for value, expected in (("", True), ("170", True), ("easycon170-pc-extension", True),
                                ("164a", False), ("1.6.4-a", False)):
            with self.subTest(value=value), patch.dict(os.environ, {backend.EASYCON_BACKEND_ENV: value}):
                self.assertEqual(backend.enabled(), expected)
        with patch.dict(os.environ, {backend.EASYCON_BACKEND_ENV: "unknown"}):
            with self.assertRaises(ValueError):
                backend.enabled()

    def test_manifest_pins_compiler_and_all_seven_models(self):
        files = backend.runtime_files()
        self.assertEqual(files["EasyCon.Script.dll"], backend.EASYCON170_SCRIPT_SHA256)
        self.assertEqual(sum(name.endswith(".traineddata") for name in files), 7)
        self.assertFalse(any(name.startswith("EasyCon2.Avalonia") or name.endswith(".pdb") for name in files))

    def test_frozen_build_retains_selected_backend(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(backend, "RESOURCE_ROOT", Path(temp)), \
                patch.object(backend.sys, "frozen", True, create=True), \
                patch.dict(os.environ, {backend.EASYCON_BACKEND_ENV: ""}):
            selection = Path(temp) / "runtime_backend/runtime-selection.json"
            selection.parent.mkdir()
            selection.write_text('{"backend": "164a"}', encoding="utf-8")
            self.assertFalse(backend.enabled())
            selection.write_text('{"backend": "170"}', encoding="utf-8")
            self.assertTrue(backend.enabled())

    def test_video_names_stay_stable_across_170_processes_and_preserve_164_profiles(self):
        from automation.easycon118 import parse_easycon_video_devices
        first = ("[0] OBS Virtual Camera [DSHOW/ABCDEF12] "
                 "(id=temporary:first:DSHOW:revision:0, temporary=True)\n"
                 "[1] USB Video [DSHOW/12345678] (id=DSHOW:device-path, temporary=False)\n")
        second = first.replace("ABCDEF12", "FA987654").replace("temporary:first:", "temporary:second:")
        expected = {0: "OBS Virtual Camera", 1: "USB Video"}
        self.assertEqual(parse_easycon_video_devices(first), expected)
        self.assertEqual(parse_easycon_video_devices(second), expected)
        self.assertEqual(parse_easycon_video_devices("[0] OBS Virtual Camera\n[1] USB Video\n"), expected)
        self.assertEqual(parse_easycon_video_devices("[0] Capture [special label]\n"), {0: "Capture [special label]"})

    def test_compiler_mismatch_and_missing_model_block_even_with_valid_apphost(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = {"EasyCon2.CLI.exe": b"apphost", "EasyCon.Script.dll": b"compiler",
                     "Tessdata/number.traineddata": b"model"}
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
            with patch.object(backend, "runtime_files", return_value=manifest):
                backend.verify_runtime_files(root / "EasyCon2.CLI.exe")
                (root / "EasyCon.Script.dll").write_bytes(b"old compiler")
                with self.assertRaisesRegex(ValueError, "EasyCon.Script.dll"):
                    backend.verify_runtime_files(root / "EasyCon2.CLI.exe")
                warnings = []
                backend.verify_runtime_files(root / "EasyCon2.CLI.exe", warning_only=True, warnings=warnings)
                self.assertEqual(len(warnings), 1)
                (root / "Tessdata/number.traineddata").unlink()
                with self.assertRaisesRegex(FileNotFoundError, "number.traineddata"):
                    backend.verify_runtime_files(root / "EasyCon2.CLI.exe", warning_only=True)

    def test_wrong_version_remains_fatal_in_advanced_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            cli = Path(temp) / "EasyCon2.CLI.exe"
            cli.write_bytes(b"apphost")
            with patch.object(backend, "verify_runtime_files"), patch.object(
                backend.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "1.7.0-old", "")
            ):
                with self.assertRaisesRegex(ValueError, "版本检查失败"):
                    backend.verify_cli(cli, warning_only=True)

    def test_runtime_snapshots_preserve_order_and_are_idempotent(self):
        original = ('FUNC Snapshot\n    RETURN 孵蛋校准_输入上下文([$b, $a], [$text], $arr)\nENDFUNC\n'
                    'FUNC Result\n    RETURN [$x, $y]\nENDFUNC\n')
        adapted, count = backend.adapt_nonconstant_array_literals(original)
        self.assertEqual(count, 2)
        for fragment in ("$EC170输入标量[0] = $b", "$EC170输入标量[1] = $a",
                         '$EC170输入文本 = [""]', "$EC170输入文本[0] = $text",
                         "$EC170输出状态[1] = $y", "RETURN $EC170输出状态"):
            self.assertIn(fragment, adapted)
        self.assertEqual(backend.adapt_nonconstant_array_literals(adapted), (adapted, 0))

    def test_adapter_does_not_evaluate_side_effects_or_rewrite_constant_arrays(self):
        text = "RETURN [1, 2, 3]\n"
        self.assertEqual(backend.adapt_nonconstant_array_literals(text), (text, 0))
        for expression in ("$x + 1", "Call($x)", "$x[0]"):
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError, "无副作用"):
                backend.adapt_nonconstant_array_literals(f"RETURN [{expression}]\n")

    def test_selected_script_copy_retains_resources_and_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            script = source / "custom.ecs"
            original = "$target = 17\nFUNC Result\nRETURN [$target]\nENDFUNC\n"
            script.write_text(original, encoding="utf-8")
            for relative in ("lib/extra.ecs", "ImgLabel/test.IL", "data/table.csv", "native.dll"):
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"resource")
            (source / "unrelated.log").write_bytes(b"huge log")
            result = backend.copy_adapted_script(script, root / "generated")
            self.assertEqual(script.read_text(encoding="utf-8"), original)
            self.assertIn("$target = 17", result.read_text(encoding="utf-8"))
            self.assertIn("$EC170输出状态", result.read_text(encoding="utf-8"))
            self.assertTrue((result.parent / "native.dll").is_file())
            self.assertTrue((result.parent / "ImgLabel/test.IL").is_file())
            self.assertFalse((result.parent / "unrelated.log").exists())
            with self.assertRaises(FileExistsError):
                backend.copy_adapted_script(script, result.parent)

    def test_bingo_function_body_stays_byte_identical(self):
        source = backend.source_path() / "lib/24_显示_BINGO.ecs"
        if not source.is_file():
            self.skipTest("requires audited local assets")
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / source.name
            original = source.read_bytes()
            copied.write_bytes(original)
            backend.adapt_project_tree(temp)
            self.assertEqual(copied.read_bytes(), original)

    def test_saved_known_old_cli_migrates_but_custom_cli_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {backend.EASYCON_BACKEND_ENV: "170"}):
            root = Path(temp)
            default, saved = root / "EasyCon2.CLI.exe", root / "ezcon.exe"
            default.touch()
            saved.write_bytes(b"custom")
            self.assertEqual(restore_easycon_path(str(saved), default), str(saved))
            with patch("pyside_app.path_settings.hashlib.sha256") as digest:
                digest.return_value.hexdigest.return_value = "559b81c234d2548c439926a88f5355ccac0958b8a191c1ecca48b2c7c71c1260"
                self.assertEqual(restore_easycon_path(str(saved), default), str(default))

    def test_workflow_checks_and_freezes_compatible_copy(self):
        from automation import EasyConRuntimeCheck
        from pyside_app.services import AppPaths
        from pyside_app.workflows import WorkflowInputs, prepare_workflow, _check_snapshot
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "custom.ecs"
            script.write_text("FUNC R\nRETURN [$v]\nENDFUNC\n", encoding="utf-8")
            inputs = WorkflowInputs("script_test", None, root, root / "cli.exe",
                                    extra={"script": str(script), "backend": "fixture"})
            with patch("pyside_app.workflows.EASYCON170_TEST", True), patch(
                "pyside_app.workflows.check_workflow", return_value=EasyConRuntimeCheck(True, (), ())
            ) as check:
                prepared = prepare_workflow(inputs, AppPaths(user=root / "user", output=root / "runs"),
                                            cancel=lambda: False)
            self.assertNotEqual(prepared.project, script)
            self.assertEqual(check.call_args.args[1], prepared.project)
            _check_snapshot(prepared)
            script.write_text("PRINT changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "预检后文件已改变"):
                _check_snapshot(prepared)


if __name__ == "__main__":
    unittest.main()
