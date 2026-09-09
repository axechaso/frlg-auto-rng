import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation import EasyCon118Options, EasyConRuntimeCheck, SearchCancelledError, search_best_plan
from pyside_app.services import (
    AppPaths,
    PreparedWild,
    WildInputs,
    cleanup_generated_plan_directories,
    display_log_line,
    prepare_run,
    prepare_wild,
)
from tests.test_auto_planner import request, target, route


def sample_result(**overrides):
    req = request(min_advances=3000, max_advances=10000, **overrides)
    return search_best_plan(req, target_search=lambda **_: [target("1234", (31,) * 6)],
                            seed_search=lambda *_args, **_kwargs: [route("75D1", 8021)])


class PySideServiceTests(unittest.TestCase):
    def test_generated_plan_cleanup_keeps_three_and_archives_text_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "runtime"
            archive = root / "archive"
            output.mkdir()
            created = []
            for index in range(5):
                directory = output / f"wild-{index:032x}"
                project = directory / "project"
                project.mkdir(parents=True)
                (project / "main.ecs").write_text("script", encoding="utf-8")
                (project / f"run-{index}.log").write_text(f"log {index}", encoding="utf-8")
                (directory / "search-result.json").write_text("{}", encoding="utf-8")
                timestamp = (index + 1) * 1_000_000_000
                os.utime(directory, ns=(timestamp, timestamp))
                created.append(directory)
            unrelated = output / "manual-files"
            unrelated.mkdir()

            removed = cleanup_generated_plan_directories(
                output, archive_root=archive,
            )

            self.assertEqual(set(removed), set(created[:2]))
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {*(path.name for path in created[2:]), unrelated.name},
            )
            for index, directory in enumerate(created[:2]):
                saved = archive / directory.name
                self.assertEqual(
                    (saved / "project" / f"run-{index}.log").read_text(encoding="utf-8"),
                    f"log {index}",
                )
                self.assertTrue((saved / "search-result.json").is_file())
                self.assertFalse((saved / "project" / "main.ecs").exists())

    def test_display_filter_preserves_errors_and_incomplete_checkpoints(self):
        self.assertIsNone(display_log_line("[12:00:00] TIDPROGRESS|V=3|MODE=1|COUNT=4|END=1\r\n"))
        self.assertEqual(display_log_line("TIDPROGRESS|V=3|COUNT=4|"), "TIDPROGRESS|V=3|COUNT=4|")
        self.assertEqual(display_log_line("TIDPROGRESS|V=4|COUNT=4|END=1"), "TIDPROGRESS|V=4|COUNT=4|END=1")
        self.assertEqual(display_log_line("\x1b[31m错误\x1b[0m\n"), "错误")

    def test_search_cancel_does_not_create_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = WildInputs(sample_result().plan.request, EasyCon118Options(), root, root / "ezcon.exe")
            (root / inputs.template_name).touch()
            with patch("pyside_app.services.search_best_plan") as search:
                with self.assertRaises(SearchCancelledError):
                    prepare_wild(inputs, AppPaths(output=root / "runtime"), cancel=lambda: True)
            search.assert_not_called()
            self.assertFalse((root / "runtime").exists())

    def test_generation_uses_existing_services_and_keeps_failed_check(self):
        result = sample_result()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = WildInputs(result.plan.request, EasyCon118Options(), root, root / "ezcon.exe")
            (root / inputs.template_name).touch()
            check = EasyConRuntimeCheck(False, ("missing runtime",), ())
            with patch("pyside_app.services.search_best_plan", return_value=result) as search, \
                 patch("pyside_app.services.write_configured_project", return_value=root / "generated/main.ecs") as generate, \
                 patch("pyside_app.services.validate_generated_project_consistency") as consistency, \
                 patch("pyside_app.services.validate_runtime", return_value=check):
                first = prepare_wild(inputs, AppPaths(user=root, output=root / "runtime"), cancel=lambda: False)
                second = prepare_wild(inputs, AppPaths(user=root, output=root / "runtime"), cancel=lambda: False)
            self.assertEqual(search.call_args.args[0].min_advances, 3000)
            self.assertIs(generate.call_args.args[2], result.plan)
            self.assertIs(consistency.call_args.args[1], result.plan)
            self.assertFalse(first.check.ok)
            self.assertTrue(first.plan_path.is_file())
            self.assertNotEqual(first.plan_path, second.plan_path)
            with self.assertRaises(ValueError):
                prepare_run(first, "COM4", 3, "Capture")

    def test_successful_generation_prunes_old_wild_projects(self):
        result = sample_result()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = WildInputs(result.plan.request, EasyCon118Options(), root, root / "ezcon.exe")
            (root / inputs.template_name).touch()

            def generate(_source, output, *_args, **_kwargs):
                main = Path(output) / "main.ecs"
                main.parent.mkdir(parents=True)
                main.write_text("generated", encoding="utf-8")
                return main

            check = EasyConRuntimeCheck(True, (), ())
            with patch("pyside_app.services.search_best_plan", return_value=result), \
                 patch("pyside_app.services.write_configured_project", side_effect=generate), \
                 patch("pyside_app.services.validate_generated_project_consistency"), \
                 patch("pyside_app.services.validate_runtime", return_value=check):
                for _ in range(5):
                    prepare_wild(
                        inputs,
                        AppPaths(user=root, output=root / "runtime"),
                        cancel=lambda: False,
                    )
            self.assertEqual(len(list((root / "runtime").glob("wild-*"))), 3)

    def test_cancel_after_generation_removes_partial_runtime_directory(self):
        result = sample_result()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = WildInputs(result.plan.request, EasyCon118Options(), root, root / "ezcon.exe")
            (root / inputs.template_name).touch()
            calls = 0

            def cancel():
                nonlocal calls
                calls += 1
                return calls >= 3

            with patch("pyside_app.services.search_best_plan", return_value=result), \
                 patch("pyside_app.services.write_configured_project", return_value=root / "generated/main.ecs"):
                with self.assertRaises(SearchCancelledError):
                    prepare_wild(
                        inputs,
                        AppPaths(user=root, output=root / "runtime"),
                        cancel=cancel,
                    )
            self.assertEqual(list((root / "runtime").glob("wild-*")), [])

    def test_start_rejects_changed_capture_identity_and_tampered_project(self):
        result = sample_result()
        inputs = WildInputs(result.plan.request, EasyCon118Options(), Path("source"), Path("ezcon.exe"), capture_name="Expected")
        prepared = PreparedWild(inputs, result, Path("project/main.ecs"), Path("plan.json"), EasyConRuntimeCheck(True, (), ()))
        with patch("pyside_app.services.probe_easycon_devices", return_value=({"COM4"}, {3: "Changed"}, "")), \
             patch("pyside_app.services.prepare_compat_runner") as runner:
            with self.assertRaisesRegex(ValueError, "采集卡"):
                prepare_run(prepared, "COM4", 3, "Expected")
            runner.assert_not_called()
        with patch("pyside_app.services.probe_easycon_devices", return_value=({"COM4"}, {3: "Expected"}, "")), \
             patch("pyside_app.services.validate_generated_project_consistency", side_effect=ValueError("tampered")), \
             patch("pyside_app.services.prepare_compat_runner") as runner:
            with self.assertRaisesRegex(ValueError, "tampered"):
                prepare_run(prepared, "COM4", 3, "Expected")
            runner.assert_not_called()
