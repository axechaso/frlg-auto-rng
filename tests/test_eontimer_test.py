import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from automation.eontimer_core import to_milliseconds
from automation.eontimer_test import (
    MARKER, RUNTIME_PATH, adapt_text, apply_test_project,
    test_options, validate_test_project, validate_test_request,
)
from automation.eontimer_test_report import EonTestReport
from automation.easycon118 import EasyCon118Options, EGG_TEMPLATE_NAME
from tests.test_pyside_services import sample_result


INIT = "EONTEST|V=1|TYPE=INIT|SEED_TARGET=30000|ADV_TARGET=3000|F1_TARGET=210|F2_TARGET=1395|SEED_CAL=0|F2_CAL=0|MULTIPLIER=2|END=1"
BARE_TEMPLATE = ('Seed绝对时间轴: F1绝对时间轴: F2绝对时间轴计划:\n'
                 '$F1阶段脚本固定帧 = 0\n$本轮真值解 = 0\n$本轮候选命中计数 = 0\n'
                 'FUNC 执行自动校准与等待更新(): INT\n    $ok = 重新计算等待参数()\n    RETURN 1\nENDFUNC\n'
                 'FUNC 重新计算等待参数(): INT\n    RETURN 1\nENDFUNC\n'
                 'FUNC 游戏操作\n    A\n    WAIT 3000\n    X\nENDFUNC\n')


def round_marker(round_=1, candidates=1, truth=1, seed_cal=-20, f2_cal=-17, **changes):
    f1 = to_milliseconds(210)
    f2 = f1 + to_milliseconds(1395)
    fields = dict(V=1, TYPE="ROUND", ROUND=round_, CANDIDATES=candidates, TRUTH=truth,
                  UPDATED=int(candidates == 1 and truth == 1), HIT_SEED=30020, HIT_ADV=3002,
                  USED_SEED=30000, USED_F1=f1, USED_F2=f2,
                  BASE_SEED=29990, BASE_F1=3500, BASE_F2=26750,
                  NEXT_SEED=30000 + seed_cal, NEXT_F1=f1, NEXT_F2=f2 + f2_cal,
                  SEED_CAL=seed_cal, F2_CAL=f2_cal, APPLIED=1, END=1)
    fields.update(changes)
    return "EONTEST|" + "|".join(f"{key}={value}" for key, value in fields.items())


class EonTestParserTests(unittest.TestCase):
    def report(self):
        report = EonTestReport("run-1")
        self.assertTrue(report.consume(INIT))
        self.assertFalse(report.error)
        return report

    def test_initial_targets_and_unique_update_are_automatic(self):
        report = self.report()
        self.assertTrue(report.consume("\x1b[90m[14:00:01.000] \x1b[0m" + round_marker()))
        self.assertFalse(report.error)
        self.assertEqual(report.settings.seed_calibration_ms, -20)
        self.assertEqual(report.settings.f2_calibration_ms, -17)
        self.assertEqual(report.updated, 1)
        self.assertEqual(report.payload()["run_id"], "run-1")
        row = report.rows[0]
        self.assertEqual(row["next_minus_easycon_ms"][0], -10)
        self.assertEqual(row["executed_points_ms"][2], 30000 + to_milliseconds(210) + to_milliseconds(1395))
        self.assertIn("并非另一组已执行的实机结果", report.render())
        self.assertIn("不是实测按键时间戳", report.render())
        self.assertEqual(report.payload()["timeline_kind"], "requested_deadlines_not_measured_keypress_timestamps")

    def test_non_unique_and_non_truth_observations_keep_calibration(self):
        for candidates, truth in ((2, 1), (1, 0), (100, 0)):
            report = self.report()
            report.consume(round_marker(candidates=candidates, truth=truth, seed_cal=0, f2_cal=0))
            self.assertFalse(report.error)
            self.assertEqual((report.updated, report.skipped), (0, 1))
            self.assertEqual(report.settings.seed_calibration_ms, 0)

    def test_updates_are_additive_with_normalized_odd_rng_error(self):
        report = self.report()
        report.consume(round_marker())
        report.consume(round_marker(2, seed_cal=-10, f2_cal=-9, HIT_SEED=29990, HIT_ADV=2999,
                                    USED_SEED=29980, USED_F2=to_milliseconds(210) + to_milliseconds(1395) - 17))
        self.assertFalse(report.error)
        self.assertEqual(report.settings.f2_calibration_ms, -9)
        self.assertEqual(report.settings.f1_calibration_ms, 0)
        self.assertEqual(report.updated, 2)

    def test_rejects_stale_duplicate_and_wrong_calibration(self):
        for marker in (round_marker(SEED_CAL=-19), round_marker(F2_CAL=-33),
                       round_marker(USED_SEED=29999), round_marker(candidates=2, UPDATED=1),
                       round_marker(NEXT_F2=1), round_marker(TRUTH=2),
                       round_marker() + "|SEED_CAL=-20", round_marker().replace("|END=1", "")):
            with self.subTest(marker=marker):
                report = self.report()
                report.consume(marker)
                self.assertTrue(report.error)
                self.assertEqual(report.updated, 0)
        report = self.report()
        report.consume(round_marker())
        report.consume(round_marker())
        self.assertIn("轮次重复", report.error)
        self.assertEqual(report.updated, 1)

    def test_no_init_and_finished_results_cannot_mix_runs(self):
        report = EonTestReport()
        report.consume(round_marker())
        self.assertIn("初始化", report.error)
        report = self.report()
        report.finished = True
        self.assertFalse(report.consume(round_marker()))
        self.assertEqual(report.updated, 0)
        self.assertFalse(report.consume("报告：{'message': '" + INIT + "'}"))

    def test_unreachable_next_deadline_is_not_claimed_as_executed(self):
        report = self.report()
        report.consume(round_marker(APPLIED=0))
        self.assertFalse(report.error)
        self.assertTrue(report.finished)
        self.assertIsNone(report.rows[0]["next_eontimer_points_ms"])
        self.assertIn("已停止测试", report.render())


class EonTestAdapterTests(unittest.TestCase):
    def test_temporary_options_never_modify_user_options(self):
        old = EasyCon118Options(update_precalibration=True, frame_parity_scheme=1, debug_log_output=0)
        options = test_options(old)
        self.assertTrue(old.update_precalibration)
        self.assertFalse(options.update_precalibration)
        self.assertEqual(options.frame_parity_scheme, 0)
        self.assertEqual(options.precalibration_seed_ns1, 0)
        self.assertEqual(options.precalibration_frame_ns2, 0)
        self.assertEqual(options.debug_log_output, 1)

    def test_unsupported_routes_are_explicit_not_fallbacks(self):
        result = sample_result()
        for req, options, advanced in (
            (result.plan.request, EasyCon118Options(), False),
            (result.plan.request, EasyCon118Options(item_rng_mode=True), True),
            (result.plan.request, EasyCon118Options(mystery_gift_enabled=True), True),
            (replace(result.plan.request, category="Roaming"), EasyCon118Options(), True),
            (replace(result.plan.request, pokemon="Togepi"), EasyCon118Options(), True),
            (replace(result.plan.request, location="Safari Zone"), EasyCon118Options(), True),
        ):
            with self.subTest(req=req), self.assertRaises(ValueError):
                validate_test_request(req, options, advanced=advanced)

    def test_adapter_renames_only_two_functions_and_preserves_game_operations(self):
        text = BARE_TEMPLATE
        adapted = adapt_text(text)
        self.assertIn('FUNC 游戏操作\n    A\n    WAIT 3000\n    X\nENDFUNC', adapted)
        self.assertIn("FUNC EON伊机控自动校准()", adapted)
        self.assertIn("$ok = EON伊机控等待参数()", adapted)
        self.assertEqual(adapted.count(MARKER), 1)
        with self.assertRaises(ValueError):
            adapt_text(adapted)
        with self.assertRaises(ValueError):
            adapt_text(text.replace('    $ok = 重新计算等待参数()', '    RETURN 1'))

    def test_project_identity_and_advanced_fingerprint_warning_policy(self):
        result = sample_result()
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "main.ecs"
            project.write_text(BARE_TEMPLATE, encoding="utf-8")
            manifest = project.parent / "plan.json"
            manifest.write_text(json.dumps({"template": EGG_TEMPLATE_NAME, "precalibration": {"enabled": False}}), encoding="utf-8")
            apply_test_project(project, result.plan, test_options(EasyCon118Options()), advanced=True)
            validate_test_project(project, expected=True)
            with self.assertRaises(ValueError):
                validate_test_project(project, expected=False)
            original = project.read_bytes()
            project.write_bytes(original + b"# altered\n")
            with self.assertRaises(ValueError):
                validate_test_project(project, expected=True)
            warnings = validate_test_project(project, expected=True, fingerprint_warning_only=True)
            self.assertEqual(len(warnings), 1)
            self.assertIn("高级模式指纹警告", warnings[0])
            project.write_bytes(original.replace(MARKER.encode(), b"# missing marker"))
            with self.assertRaisesRegex(ValueError, "测试标记"):
                validate_test_project(project, expected=True, fingerprint_warning_only=True)
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["eontimer_test"]["script_sha256"], hashlib.sha256(original).hexdigest())

    def test_tv_target_is_rejected_before_project_write(self):
        result = sample_result()
        plan = replace(result.plan, initial_seed=replace(result.plan.initial_seed, advances=14400))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "main.ecs"
            path.write_text("preserved", encoding="utf-8")
            with self.assertRaises(ValueError):
                apply_test_project(path, plan, EasyCon118Options(), advanced=True)
            self.assertEqual(path.read_text(encoding="utf-8"), "preserved")

    def test_service_generation_repair_and_start_keep_test_identity(self):
        from automation import EasyConRuntimeCheck
        from pyside_app.services import (
            AppPaths, WildInputs, prepare_wild, prepare_run, rebuild_wild_with_override,
        )
        result = sample_result()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / EGG_TEMPLATE_NAME).write_text("mother unchanged", encoding="utf-8")
            inputs = WildInputs(result.plan.request, test_options(EasyCon118Options()),
                                root, root / "ezcon.exe", EGG_TEMPLATE_NAME, True,
                                "Capture", True)
            paths = AppPaths(user=root, output=root / "runtime")

            def generate(_source, output, *_args, **_kwargs):
                output = Path(output)
                output.mkdir(parents=True)
                main = output / "main.ecs"
                main.write_text(BARE_TEMPLATE, encoding="utf-8")
                (output / "plan.json").write_text(json.dumps({
                    "template": EGG_TEMPLATE_NAME, "precalibration": {"enabled": False},
                }), encoding="utf-8")
                return main

            with patch("pyside_app.services.search_best_plan", return_value=result) as search, \
                 patch("pyside_app.services.write_configured_project", side_effect=generate), \
                 patch("pyside_app.services.validate_generated_project_consistency"), \
                 patch("pyside_app.services.validate_runtime", return_value=EasyConRuntimeCheck(True, (), ())), \
                 patch("pyside_app.services.probe_easycon_devices", return_value=({"COM4"}, {3: "Capture"}, "")), \
                 patch("pyside_app.services.prepare_compat_runner", return_value=root / "runner.exe") as runner, \
                 patch("pyside_app.services.build_run_command", return_value=["unused-runner"]):
                prepared = prepare_wild(inputs, paths, cancel=lambda: False)
                self.assertTrue(prepared.check.ok)
                validate_test_project(prepared.project, expected=True)
                rebuilt = rebuild_wild_with_override(prepared, paths)
                self.assertIs(rebuilt.inputs, inputs)
                self.assertIs(rebuilt.result.plan, result.plan)
                self.assertNotEqual(rebuilt.project, prepared.project)
                validate_test_project(rebuilt.project, expected=True)
                search.assert_called_once()
                command = prepare_run(rebuilt, "COM4", 3, "Capture", paths)
                self.assertTrue(command.check.ok)
                runner.assert_called_once()
                rebuilt.project.write_bytes(rebuilt.project.read_bytes() + b"# tampered\n")
                modified = prepare_run(rebuilt, "COM4", 3, "Capture", paths)
                self.assertIn("高级模式指纹警告", "\n".join(modified.check.warnings))
                self.assertEqual(runner.call_count, 2)
                rebuilt.project.write_bytes(rebuilt.project.read_bytes().replace(MARKER.encode(), b"# missing marker"))
                with self.assertRaisesRegex(ValueError, "测试标记"):
                    prepare_run(rebuilt, "COM4", 3, "Capture", paths)
                self.assertEqual(runner.call_count, 2)
            self.assertEqual((root / EGG_TEMPLATE_NAME).read_text(encoding="utf-8"), "mother unchanged")


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class EonTestQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from pyside_app.services import AppPaths
        from pyside_app.migration import CompleteWindow
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = CompleteWindow(paths=AppPaths(user=self.root, output=self.root / "runtime"), auto_detect=False)
        self.window.app_update.auto_timer.stop()

    def tearDown(self):
        self.window.running = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def begin(self, enabled=True, run_id="run-1"):
        from pyside_app.services import RunCommand
        from automation import EasyConRuntimeCheck
        command = RunCommand("unused", (), self.root / f"{run_id}.log", self.root / f"{run_id}.stop", "", EasyConRuntimeCheck(True, (), ()), run_id)
        prepared = SimpleNamespace(inputs=SimpleNamespace(eontimer_test=enabled))
        self.window.eontimer_controller.begin(command, prepared)
        return command

    def test_default_off_advanced_only_and_temporary_preference(self):
        w = self.window
        self.assertFalse(w.eontimer_test_check.isChecked())
        self.assertFalse(w.eontimer_test_check.isEnabled())
        w.advanced_check.setChecked(True)
        self.assertTrue(w.eontimer_test_check.isEnabled())
        w.eontimer_test_check.setChecked(True)
        self.assertNotIn("eontimer_test", w.settings_payload())
        w.advanced_check.setChecked(False)
        self.assertFalse(w.eontimer_test_check.isChecked())

    def test_collect_inputs_autofills_test_config_and_protects_normal_precalibration(self):
        w = self.window
        w.fields["wild_tid"].setText("12345")
        w.fields["wild_sid"].setText("54321")
        normal = w.collect_inputs()
        w.advanced_check.setChecked(True)
        w.eontimer_test_check.setChecked(True)
        w.precalibration_check.setChecked(True)
        test = w.collect_inputs()
        self.assertTrue(test.eontimer_test)
        self.assertEqual(test.template_name, EGG_TEMPLATE_NAME)
        self.assertFalse(test.options.update_precalibration)
        self.assertTrue(w.precalibration_check.isChecked())
        self.assertFalse(normal.eontimer_test)
        w.eontimer_test_check.setChecked(False)
        self.assertTrue(w.collect_inputs().options.update_precalibration)

    def test_other_workflows_are_not_silently_changed(self):
        w = self.window
        w.advanced_check.setChecked(True)
        w.eontimer_test_check.setChecked(True)
        w.input_mode = "egg"
        with self.assertRaisesRegex(ValueError, "仅用于"):
            w.collect_workflow()

    def test_no_tv_search_limit_and_running_mode_lock(self):
        w = self.window
        w.fields["wild_tid"].setText("12345")
        w.fields["wild_sid"].setText("54321")
        w.fields["wild_min"].setText("1000")
        w.fields["wild_max"].setText("30000")
        w.advanced_check.setChecked(True)
        w.eontimer_test_check.setChecked(True)
        self.assertEqual(w.collect_inputs().request.max_advances, 14399)
        self.assertEqual(w.fields["wild_max"].text(), "30000")
        w.running = True
        w.refresh_state()
        self.assertFalse(w.eontimer_test_check.isEnabled())
        w.running = False
        w.fields["wild_min"].setText("14400")
        with self.assertRaisesRegex(ValueError, "TV"):
            w.collect_inputs()

    def test_mode_change_invalidates_prepared_plan(self):
        w = self.window
        w.advanced_check.setChecked(True)
        w.prepared = object()
        w.eontimer_test_check.setChecked(True)
        self.assertIsNone(w.prepared)

    def test_live_partial_lines_reopen_and_finish_export_are_automatic(self):
        from PySide6.QtTest import QTest
        w = self.window
        command = self.begin()
        w.pending_output = ""
        w.pending_visible = False
        w.runtime_issues = {}
        w._append_log(INIT + "\n" + round_marker()[:50])
        self.assertEqual(w.eontimer_controller.report.updated, 0)
        w._append_log(round_marker()[50:] + "\n")
        self.assertEqual(w.eontimer_controller.report.updated, 1)
        w.eontimer_controller.show()
        w.eontimer_controller.dialog.hide()
        w.eontimer_controller.show()
        self.assertEqual(w.eontimer_controller.report.updated, 1)
        QTest.qWait(170)
        self.assertIn("已更新 1 轮", w.eontimer_controller.view.toPlainText())
        w.eontimer_controller.finish()
        payload = json.loads(command.log_path.with_suffix(".eontimer.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["updated_rounds"], 1)
        self.assertEqual(payload["run_id"], "run-1")

    def test_normal_run_ignores_test_markers_and_new_test_resets_state(self):
        self.begin(False)
        self.window.eontimer_controller.consume(INIT)
        self.assertIsNone(self.window.eontimer_controller.report.initial)
        self.begin()
        self.window.eontimer_controller.consume(INIT)
        self.window.eontimer_controller.consume(round_marker())
        self.begin(True, "run-2")
        self.assertEqual(self.window.eontimer_controller.report.updated, 0)
        self.assertEqual(self.window.eontimer_controller.report.run_id, "run-2")

    def test_status_refreshes_automatically_without_opening_report(self):
        from PySide6.QtTest import QTest
        self.begin()
        controller = self.window.eontimer_controller
        controller.consume(INIT)
        controller.consume(round_marker())
        self.assertIsNone(controller.dialog)
        QTest.qWait(500)
        self.assertIn("已更新 1 轮", self.window.eontimer_test_status.text())
        self.assertFalse(controller.timer.isActive())

    def test_export_never_overwrites_existing_evidence(self):
        command = self.begin()
        path = command.log_path.with_suffix(".eontimer.json")
        path.write_text("existing", encoding="utf-8")
        self.window.eontimer_controller.consume(INIT)
        self.window.eontimer_controller.finish()
        self.assertEqual(path.read_text(encoding="utf-8"), "existing")
        self.assertIn("未保存", self.window.eontimer_controller.export_note)


if __name__ == "__main__":
    unittest.main()
