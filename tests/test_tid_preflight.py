import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from automation import tid_rng137 as backend
from pyside_app.diagnostics import explain_popup_error


class TidPreflightTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(backend, "verify_easycon170_files"))
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.ezcon = self.root / "ezcon.exe"
        self.ezcon.write_bytes(b"preflight fixture")
        self.project = self.root / "project" / "main.ecs"
        self.project.parent.mkdir()
        self.project.write_text("RETURN 0\n", encoding="utf-8")
        (self.project.parent / "ImgLabel").mkdir()
        self.stack.enter_context(patch.object(
            backend, "_sha256_file", return_value=backend.EXPECTED_EZCON_SHA256,
        ))
        self.stack.enter_context(patch.object(backend, "inspect_label_corpus", return_value={
            "count": backend.EXPECTED_TID_LABEL_COUNT,
            "methods": backend.EXPECTED_TID_LABEL_METHODS,
            "sha256": backend.EXPECTED_TID_LABEL_SHA256,
        }))
        self.stack.enter_context(patch.object(
            backend, "validate_project_overrides",
            return_value=SimpleNamespace(recognized=False),
        ))

    def version(self, returncode=0, stdout=None, stderr=""):
        if stdout is None:
            stdout = backend.EXPECTED_EZCON_VERSION if returncode == 0 else ""
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def check(self, formatted, version=None):
        with patch.object(backend.subprocess, "run", side_effect=[
            self.version() if version is None else version, formatted,
        ]) as run:
            result = backend.validate_tid_runtime(self.ezcon, self.project)
        return result, run

    def test_dll_initialization_failure_is_not_reported_as_a_syntax_error(self):
        for code in (-1073741502, 3221225794):
            with self.subTest(returncode=code):
                result, _ = self.check(subprocess.CompletedProcess([], code, "", ""))
                self.assertFalse(result.ok)
                error = "\n".join(result.errors)
                self.assertIn(str(code), error)
                self.assertIn("0xC0000142", error)
                self.assertIn("DLL 初始化失败", error)
                self.assertIn("本次未完成脚本语法检查", error)
                self.assertIn(str(self.project), error)
                self.assertIn("进程没有提供标准输出或错误输出", error)
                self.assertEqual(explain_popup_error(error).key, "runtime_dll_init")

    def test_empty_output_retains_unknown_failure_code_without_guessing_dll(self):
        result, _ = self.check(subprocess.CompletedProcess([], 7, "", ""))
        self.assertFalse(result.ok)
        error = "\n".join(result.errors)
        self.assertIn("退出码 7（0x00000007）", error)
        self.assertIn(str(self.project), error)
        self.assertIn("没有提供标准输出或错误输出", error)
        self.assertNotIn("DLL 初始化失败", error)

    def test_syntax_diagnostics_keep_both_output_streams(self):
        result, _ = self.check(subprocess.CompletedProcess(
            [], 1, "第8行: 找不到变量 $不存在", "EasyCon 编译失败",
        ))
        self.assertFalse(result.ok)
        error = "\n".join(result.errors)
        self.assertIn("ECS 语法预检失败", error)
        self.assertIn("第8行: 找不到变量 $不存在", error)
        self.assertIn("EasyCon 编译失败", error)
        self.assertNotIn("DLL 初始化失败", error)

    def test_whitespace_stderr_does_not_hide_stdout_diagnostics(self):
        result, _ = self.check(subprocess.CompletedProcess([], 1, "真实语法错误", " \n "))
        self.assertFalse(result.ok)
        self.assertIn("真实语法错误", "\n".join(result.errors))

    def test_version_startup_failure_blocks_format_and_retains_exit_code(self):
        result, run = self.check(
            subprocess.CompletedProcess([], 0, "", ""),
            version=self.version(-1073741502),
        )
        self.assertFalse(result.ok)
        self.assertEqual(run.call_count, 1)
        self.assertIn("版本检查进程启动失败", "\n".join(result.errors))
        self.assertIn("0xC0000142", "\n".join(result.errors))

    def test_unsupported_version_still_blocks_format(self):
        result, run = self.check(
            subprocess.CompletedProcess([], 0, "", ""),
            version=self.version(stdout="1.70"),
        )
        self.assertFalse(result.ok)
        self.assertEqual(run.call_count, 1)
        self.assertIn("只支持 EasyCon", "\n".join(result.errors))

    def test_success_requires_both_commands_and_uses_no_console_on_windows(self):
        result, run = self.check(subprocess.CompletedProcess([], 0, "", ""))
        self.assertTrue(result.ok)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(run.call_args.kwargs["cwd"], str(self.project.parent))

    def test_old_blank_error_does_not_claim_to_identify_a_dll_failure(self):
        error = "EasyCon 1.6.4-a TID ECS 语法预检失败: "
        self.assertEqual(explain_popup_error(error).key, "unknown")

    def test_popup_recognizes_signed_and_unsigned_exit_codes(self):
        for code in ("-1073741502", "3221225794"):
            with self.subTest(returncode=code):
                self.assertEqual(
                    explain_popup_error("EasyCon 预检失败，退出码 " + code).key,
                    "runtime_dll_init",
                )


if __name__ == "__main__":
    unittest.main()
