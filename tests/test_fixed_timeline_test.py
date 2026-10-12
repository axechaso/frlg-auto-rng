import hashlib
import json
import os
from dataclasses import asdict, replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from automation.easycon118 import EasyCon118Options, EGG_TEMPLATE_NAME
from automation.eontimer_test import adapt_text, apply_test_project, test_options, validate_test_project
from automation.fixed_timeline_test import (
    FixedTimeline, FixedTestReport, find_successful_timeline, read_successful_timeline, request_context,
)
from tests.test_eontimer_test import BARE_TEMPLATE
from tests.test_pyside_services import sample_result

RUN = "a" * 32
END = f"脚本运行完成FRLG_INPUT_SESSION|V=1|RUN={RUN}|SESSION={'b' * 32}|STAGE=wild|STATE=ENDED|END=1"
BODY = ("[11:00:00.000] 第4轮\n"
        "[11:00:00.001] Seed绝对时间轴: 请求65907 ms，实际 65907 ms，超时 0 ms\n"
        "[11:01:00.000] F1绝对时间轴: 目标3499 ms，实际 3499 ms，超时 0 ms\n"
        "[11:01:04.000] F2绝对时间轴计划: 自Seed确认起61948 ms\n"
        "[11:02:00.000] F2绝对时间轴(静态): 超时0 ms\n"
        "[11:02:01.000] 时差检测到出闪: HP栏出现100ms后对话框仍为空白\n"
        "[11:02:02.000] 目标获取流程结束，停止脚本\n")
FIXED_TEMPLATE = ("FOR\n        $本轮流程结果 = 执行RNG启动与目标获取()\nNEXT\n"
                  "FUNC 输出下一轮等待参数\n    RETURN\nENDFUNC\n" + BARE_TEMPLATE)


def make_config(request=None, options=None, **changes):
    plan = sample_result().plan
    request = request or plan.request
    options = options or test_options(EasyCon118Options())
    return replace(FixedTimeline(65907, 3499, 61948, "source.log", RUN, request_context(request, options),
                                 plan.initial_seed.seed, plan.initial_seed.advances, 0), **changes)


def marker(kind, **values):
    return "FIXEDTEST|" + "|".join(f"{key}={value}" for key, value in dict(V=1, TYPE=kind, **values, END=1).items())


INIT = marker("INIT", SEED_TARGET=65806, ADV_TARGET=8021, USED_SEED=65907, USED_F1=3499, USED_F2=61948, LIMIT=5)


class FixedTimelineSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plan = sample_result().plan
        self.options = test_options(EasyCon118Options())
        self.log = self.root / f"easycon-{RUN}.log"
        self.manifest = self.root / "plan.json"
        self.payload = {"template": EGG_TEMPLATE_NAME, "plan": {
            "request": asdict(self.plan.request), "initial_seed": asdict(self.plan.initial_seed),
            "execution": {"seed_mode": 0}}, "easycon118_options": asdict(self.options)}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self, body=BODY, end=END):
        self.log.write_text(body + end + "\n", encoding="utf-8")
        self.manifest.write_text(json.dumps(self.payload), encoding="utf-8")

    def read(self, request=None, options=None):
        return read_successful_timeline(self.log, request or self.plan.request, options or self.options)

    def test_auto_reads_exact_final_deadlines_and_leaves_evidence_unchanged(self):
        before = hashlib.sha256(self.log.read_bytes()).hexdigest()
        result = self.read()
        self.assertEqual((result.seed_ms, result.f1_ms, result.f2_total_ms), (65907, 3499, 61948))
        self.assertEqual(result.source_run_id, RUN)
        result.validate_plan(self.plan, self.options)
        self.assertEqual(before, hashlib.sha256(self.log.read_bytes()).hexdigest())

    def test_ansi_log_is_supported(self):
        self.save(body="\x1b[90m" + BODY.replace("\n", "\x1b[0m\n\x1b[90m"))
        self.assertIsNotNone(self.read())

    def test_partial_or_manually_stopped_logs_are_not_success_sources(self):
        for body, end in ((BODY, "脚本已停止"), (BODY, END.replace("STATE=ENDED", "STATE=STOPPED")),
                          (BODY.replace("目标获取流程结束，停止脚本", "识图失败"), END),
                          (BODY.replace("时差检测到出闪:", "时差检测结果普通:"), END),
                          (BODY.replace("超时0 ms", "超时1 ms"), END),
                          (BODY.replace("实际 3499", "实际 3500"), END),
                          (BODY + "第5轮\n", END), (BODY, END.replace(RUN, "c" * 32))):
            with self.subTest(body=body, end=end):
                self.save(body, end)
                self.assertIsNone(self.read())

    def test_context_route_nx_startup_and_language_are_isolated(self):
        for changes in ({"tid": 1}, {"sid": 1}, {"game": "lg_nx"}, {"pokemon": "Zapdos"},
                        {"location": "Elsewhere"}, {"method": "Static 1"}):
            self.assertIsNone(self.read(request=replace(self.plan.request, **changes)))
        for changes in ({"nx_model": 2}, {"seed_startup_scheme": 1}, {"mystery_gift_enabled": True}):
            self.assertIsNone(self.read(options=replace(self.options, **changes)))

    def test_native_menu_and_fixed_test_sources_are_excluded(self):
        self.payload["easycon118_options"]["frame_parity_scheme"] = 1
        self.save()
        self.assertIsNone(self.read())
        self.payload["easycon118_options"]["frame_parity_scheme"] = 0
        self.payload["eontimer_test"] = {"mode": "fixed"}
        self.save()
        self.assertIsNone(self.read())

    def test_latest_matching_success_is_selected_and_cancellation_is_respected(self):
        entries = [SimpleNamespace(path=self.root / "missing.log"), SimpleNamespace(path=self.log)]
        self.assertEqual(find_successful_timeline(entries, self.plan.request, self.options).source_run_id, RUN)
        self.assertIsNone(find_successful_timeline(entries, self.plan.request, self.options, cancelled=lambda: True))
        with self.assertRaisesRegex(ValueError, "没有找到"):
            find_successful_timeline(entries[:1], self.plan.request, self.options)

    def test_malformed_manifest_or_oversized_log_are_ignored(self):
        self.manifest.write_text("not json", encoding="utf-8")
        self.assertIsNone(self.read())
        self.save()
        with self.log.open("r+b") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
        self.assertIsNone(self.read())


class FixedTimelineConfigTests(unittest.TestCase):
    def test_service_generation_rebuild_and_start_keep_fixed_snapshot(self):
        from automation import EasyConRuntimeCheck
        from pyside_app.services import AppPaths, WildInputs, prepare_wild, prepare_run, rebuild_wild_with_override
        result = sample_result()
        options, config = test_options(EasyCon118Options()), make_config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / EGG_TEMPLATE_NAME).write_text("untouched mother", encoding="utf-8")
            inputs = WildInputs(result.plan.request, options, root, root / "ezcon.exe", EGG_TEMPLATE_NAME,
                                True, "Capture", True, config)
            paths = AppPaths(user=root, output=root / "runtime")

            def generate(_source, output, *_args, **_kwargs):
                output = Path(output)
                output.mkdir(parents=True)
                main = output / "main.ecs"
                main.write_text(FIXED_TEMPLATE, encoding="utf-8")
                (output / "plan.json").write_text(json.dumps({
                    "template": EGG_TEMPLATE_NAME, "precalibration": {"enabled": False}}), encoding="utf-8")
                return main

            with patch("pyside_app.services.search_best_plan", return_value=result) as search, \
                 patch("pyside_app.services.write_configured_project", side_effect=generate), \
                 patch("pyside_app.services.validate_generated_project_consistency"), \
                 patch("pyside_app.services.validate_runtime", return_value=EasyConRuntimeCheck(True, (), ())), \
                 patch("pyside_app.services.probe_easycon_devices", return_value=({"COM4"}, {3: "Capture"}, "")), \
                 patch("pyside_app.services.prepare_compat_runner", return_value=root / "runner.exe"), \
                 patch("pyside_app.services.build_run_command", return_value=["unused-runner"]):
                prepared = prepare_wild(inputs, paths, cancel=lambda: False)
                self.assertTrue(prepared.check.ok)
                rebuilt = rebuild_wild_with_override(prepared, paths)
                self.assertIs(rebuilt.inputs.fixed_timeline, config)
                validate_test_project(rebuilt.project, expected=True, fixed=config)
                self.assertTrue(prepare_run(rebuilt, "COM4", 3, "Capture", paths).check.ok)
                search.assert_called_once()
            self.assertEqual((root / EGG_TEMPLATE_NAME).read_text(encoding="utf-8"), "untouched mother")
            self.assertFalse((root / "precalibration.json").exists())

    def test_config_binds_target_and_does_not_allow_search_to_change_it(self):
        plan = sample_result().plan
        options = test_options(EasyCon118Options())
        config = make_config()
        config.validate_plan(plan, options)
        config.validate_request(replace(plan.request, direct_mode=True, direct_seed=config.initial_seed,
                                         direct_advances=config.advances), options)
        with self.assertRaisesRegex(ValueError, "指定"):
            config.validate_request(replace(plan.request, direct_mode=True, direct_seed="FFFF", direct_advances=1), options)
        with self.assertRaisesRegex(ValueError, "换了目标"):
            config.validate_plan(replace(plan, initial_seed=replace(plan.initial_seed, advances=1)), options)
        with self.assertRaisesRegex(ValueError, "Seed 模式"):
            config.validate_request(replace(plan.request, seed_mode=1), options)
        for changes in ({"repeat_limit": 0}, {"repeat_limit": 21}, {"f1_ms": 61948},
                        {"seed_ms": 0}, {"seed_ms": True}, {"source_run_id": "wrong"}, {"advances": 14400}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(config, **changes).validate()

    def test_japanese_execution_mode_ten_binds_logical_mode_zero(self):
        plan = sample_result().plan
        plan = replace(plan, request=replace(plan.request, game="fr_jpn_nx", method="Static 1",
                                             category="Starter", location="Starter", pokemon="Squirtle"))
        options = test_options(EasyCon118Options(japanese_starter=True))
        config = make_config(plan.request, options, seed_mode=10)
        config.validate_plan(plan, options)
        config.validate_request(replace(plan.request, seed_mode=0), options)

    def test_adapter_only_changes_disposable_project_and_adds_bounded_loop_guard(self):
        text = adapt_text(FIXED_TEMPLATE, make_config())
        self.assertIn("$EON固定测试模式 = 1", text)
        self.assertIn("$EON固定F2总MS = 61948", text)
        self.assertIn("IF EON开始固定轮() == 0\n            RETURN", text)
        self.assertIn("FUNC 游戏操作\n    A\n    WAIT 3000\n    X\nENDFUNC", text)
        with self.assertRaisesRegex(ValueError, "轮次入口"):
            adapt_text(BARE_TEMPLATE, make_config())

    def test_generation_start_manifest_rejects_mode_mix_but_only_warns_on_fingerprint(self):
        plan = sample_result().plan
        config = make_config()
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "main.ecs"
            project.write_text(FIXED_TEMPLATE, encoding="utf-8")
            manifest = project.parent / "plan.json"
            manifest.write_text(json.dumps({"template": EGG_TEMPLATE_NAME, "precalibration": {"enabled": False}}), encoding="utf-8")
            apply_test_project(project, plan, test_options(EasyCon118Options()), advanced=True, fixed=config)
            validate_test_project(project, expected=True, fixed=config)
            with self.assertRaisesRegex(ValueError, "混入"):
                validate_test_project(project, expected=True)
            with self.assertRaisesRegex(ValueError, "配置不一致"):
                validate_test_project(project, expected=True, fixed=replace(config, repeat_limit=6), fingerprint_warning_only=True)
            project.write_bytes(project.read_bytes() + b"# user edit\n")
            warnings = validate_test_project(project, expected=True, fixed=config, fingerprint_warning_only=True)
            self.assertEqual(len(warnings), 1)
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["eontimer_test"]["calibration"], "disabled")


class FixedTimelineReportTests(unittest.TestCase):
    def report(self):
        report = FixedTestReport("new-run", make_config())
        self.assertTrue(report.consume(INIT))
        self.assertFalse(report.error)
        return report

    def test_unique_errors_are_recorded_but_no_calibration_occurs(self):
        report = self.report()
        report.consume(marker("ATTEMPT", ATTEMPT=1))
        report.consume(marker("ROUND", ATTEMPT=1, CANDIDATES=1, TRUTH=1, HIT_SEED=65823, HIT_ADV=8023,
                              USED_SEED=65907, USED_F1=3499, USED_F2=61948, APPLIED=1))
        self.assertFalse(report.error)
        self.assertEqual((report.rows[0]["seed_error_ms"], report.rows[0]["adv_error"]), (17, 2))
        self.assertFalse(report.payload()["calibration_enabled"])
        self.assertEqual(report.updated, 0)
        self.assertIn("F2 是自 Seed 确认", report.render())

    def test_ambiguous_candidates_are_not_truth_and_missing_shiny_round_is_not_zero_error(self):
        report = self.report()
        report.consume(marker("ATTEMPT", ATTEMPT=1))
        report.consume(marker("ROUND", ATTEMPT=1, CANDIDATES=2, TRUTH=1, HIT_SEED=65806, HIT_ADV=8021,
                              USED_SEED=65907, USED_F1=3499, USED_F2=61948, APPLIED=1))
        report.consume(marker("ATTEMPT", ATTEMPT=2))
        report.finished = True
        self.assertIsNone(report.rows[0]["adv_error"])
        self.assertIn("1 轮尚无反查记录", report.render())

    def test_count_includes_failed_attempts_and_reaches_finite_limit(self):
        report = self.report()
        for number in range(1, 6):
            report.consume(marker("ATTEMPT", ATTEMPT=number))
        report.consume(marker("STOP", ATTEMPTS=5))
        self.assertFalse(report.error)
        self.assertTrue(report.limit_reached)
        self.assertFalse(report.consume(marker("ATTEMPT", ATTEMPT=6)))

    def test_conflicts_duplicate_rounds_and_changed_deadlines_are_refused(self):
        for invalid in (marker("ATTEMPT", ATTEMPT=3), marker("STOP", ATTEMPTS=5),
                        marker("ROUND", ATTEMPT=1, CANDIDATES=1, TRUTH=1, HIT_SEED=65806, HIT_ADV=8021,
                               USED_SEED=65908, USED_F1=3499, USED_F2=61948, APPLIED=1),
                        INIT + "|LIMIT=5", INIT.replace("|END=1", "")):
            report = self.report()
            report.consume(marker("ATTEMPT", ATTEMPT=1))
            report.consume(invalid)
            self.assertTrue(report.error)
        report = FixedTestReport("other", replace(make_config(), seed_ms=65908))
        report.consume(INIT)
        self.assertTrue(report.error)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FixedTimelineQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from pyside_app.migration import CompleteWindow
        from pyside_app.services import AppPaths
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = CompleteWindow(paths=AppPaths(user=self.root, output=self.root / "runtime"), auto_detect=False)
        self.window.app_update.auto_timer.stop()
        self.window.fields["wild_tid"].setText("12345")
        self.window.fields["wild_sid"].setText("54321")
        self.window.advanced_check.setChecked(True)
        self.window.eontimer_mode.setCurrentIndex(1)

    def tearDown(self):
        self.window.running = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def enable_loaded(self):
        inputs = self.window.collect_inputs(require_fixed=False)
        self.window.eontimer_controller.fixed = make_config(inputs.request, inputs.options)
        self.window.eontimer_test_check.setChecked(True)

    def test_default_limit_and_no_silent_fallback_when_source_missing(self):
        w = self.window
        self.assertEqual(w.eontimer_repeat_limit.value(), 5)
        with patch.object(w, "launch_job", return_value=False):
            w.eontimer_test_check.setChecked(True)
        with self.assertRaisesRegex(ValueError, "尚未取得"):
            w.collect_inputs()
        w.eontimer_mode.setCurrentIndex(0)
        self.assertIsNone(w.collect_inputs().fixed_timeline)

    def test_loaded_config_is_immutable_and_all_controls_lock_during_run(self):
        self.enable_loaded()
        w = self.window
        first = w.collect_inputs()
        w.prepared = object()
        w.eontimer_repeat_limit.setValue(3)
        second = w.collect_inputs()
        self.assertIsNone(w.prepared)
        self.assertEqual(first.fixed_timeline.repeat_limit, 5)
        self.assertEqual(second.fixed_timeline.repeat_limit, 3)
        self.assertNotEqual(first.fingerprint(), second.fingerprint())
        self.assertNotIn("fixed_timeline", w.settings_payload())
        w.running = True
        w.refresh_state()
        self.assertFalse(w.eontimer_mode.isEnabled())
        self.assertFalse(w.eontimer_repeat_limit.isEnabled())
        self.assertFalse(w.eontimer_load_button.isEnabled())

    def test_source_is_loaded_automatically_in_background_on_mode_enable(self):
        w = self.window
        inputs = w.collect_inputs(require_fixed=False)
        result = make_config(inputs.request, inputs.options)

        def launch(work, success, _status):
            success(work(lambda: False, lambda _: None))
            return True

        with patch.object(w, "launch_job", side_effect=launch) as job, \
             patch("pyside_app.log_history.discover_logs", return_value=[]), \
             patch("pyside_app.eontimer_test.find_successful_timeline", return_value=result):
            w.eontimer_test_check.setChecked(True)
            job.assert_called_once()
        self.assertEqual(w.collect_inputs().fixed_timeline.seed_ms, 65907)
        self.assertIn("F2 总 61948", w.eontimer_fixed_values.text())

    def test_changed_save_cannot_reuse_previous_fixed_source(self):
        self.enable_loaded()
        self.window.fields["wild_tid"].setText("123")
        with self.assertRaisesRegex(ValueError, "另一目标"):
            self.window.collect_inputs()

    def test_run_report_export_is_separate_and_does_not_pretend_to_calibrate(self):
        from automation import EasyConRuntimeCheck
        from pyside_app.services import RunCommand
        controller = self.window.eontimer_controller
        command = RunCommand("unused", (), self.root / "new.log", self.root / "stop", "", EasyConRuntimeCheck(True, (), ()), "new")
        controller.begin(command, SimpleNamespace(inputs=SimpleNamespace(eontimer_test=True, fixed_timeline=make_config())))
        controller.consume(INIT)
        controller.consume(marker("ATTEMPT", ATTEMPT=1))
        controller.finish()
        payload = json.loads(command.log_path.with_suffix(".fixed-timeline.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["attempts"], 1)
        self.assertFalse(payload["calibration_enabled"])
        self.assertEqual(payload["source"]["source_run_id"], RUN)
        self.assertFalse(command.log_path.with_suffix(".eontimer.json").exists())


if __name__ == "__main__":
    unittest.main()
