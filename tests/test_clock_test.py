from dataclasses import replace
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from automation.clock_test import ASSETS, DLL_NAME, MARKER, adapt_main, adapt_f2, asset_manifest, validate_driver
from automation.clock_test_report import ClockTestReport
from automation.eontimer_test import validate_test_project
from tests.test_fixed_timeline_test import INIT, FIXED_TEMPLATE, make_config, marker


def clock_marker(kind, **fields):
    return "CLOCKTEST|" + "|".join(f"{key}={value}" for key, value in dict(V=1, TYPE=kind, **fields, END=1).items())


def clock_init(driver=0):
    return clock_marker("INIT", DRIVER=driver, SEED=65907, F1=3499, F2=61948, FREQ_KHZ=10000, FREQ_REMAINDER=0)


def clock_stage(stage, *, attempt=1, driver=0, status=2, error=150):
    target = (65907, 3499, 61948)[stage]
    return clock_marker("STAGE", ATTEMPT=attempt, DRIVER=driver, STAGE=stage, STATUS=status, TARGET_MS=target,
                        ELAPSED_US=target * 1000 + error if status == 2 else 0,
                        ERROR_US=error if status == 2 else 0, WALL_ELAPSED_MS=target if status == 2 else 0)


class ClockReportTests(unittest.TestCase):
    def report(self, driver="easycon", capture="Capture", labels="a" * 64):
        report = ClockTestReport("new", make_config(), driver, capture_name=capture, labels_sha256=labels)
        report.consume(INIT)
        report.consume(marker("ATTEMPT", ATTEMPT=1))
        report.consume(clock_init(int(driver == "eontimer")))
        self.assertFalse(report.error)
        return report

    def test_measured_waits_are_separate_from_unique_reverse(self):
        report = self.report()
        for stage in range(3):
            report.consume("\x1b[90m[12:00:00.000] \x1b[0m" + clock_stage(stage))
        report.consume(marker("ROUND", ATTEMPT=1, CANDIDATES=1, TRUTH=1, HIT_SEED=65823, HIT_ADV=8022,
                              USED_SEED=65907, USED_F1=3499, USED_F2=61948, APPLIED=1))
        self.assertFalse(report.error)
        self.assertEqual(report.rows[0]["seed_error_ms"], 17)
        self.assertEqual(report.rows[0]["adv_error"], 1)
        self.assertEqual(report.statistics()["F1"]["mean_error_us"], 150)
        self.assertFalse(report.payload()["calibration_enabled"])
        self.assertIn("不是单片机/游戏收到按键", report.render())

    def test_shiny_without_reverse_retains_three_waits_but_no_invented_zero_iv_error(self):
        report = self.report("eontimer")
        for stage in range(3):
            report.consume(clock_stage(stage, driver=1, error=22))
        report.finished = True
        self.assertFalse(report.rows)
        self.assertEqual(len(report.clock_rows), 3)
        self.assertIn("1 轮尚无反查记录", report.render())
        self.assertEqual(report.payload()["measurement_kind"], "qpc_at_wait_return_not_electrical_keypress")

    def test_partial_stages_never_enter_statistics(self):
        report = self.report()
        report.consume(clock_stage(0))
        report.consume(clock_stage(1, status=1))
        report.consume(clock_stage(2, status=1))
        self.assertFalse(report.error)
        self.assertEqual(report.statistics()["F2"]["count"], 0)
        self.assertIsNone(report.clock_rows[-1]["deadline_error_us"])

    def test_wall_time_discontinuity_is_not_concealed_as_invalid_qpc(self):
        report = self.report()
        text = clock_stage(0, error=-17000)
        report.consume(text)
        self.assertFalse(report.error)
        self.assertEqual(report.clock_rows[0]["wall_minus_qpc_us"], 17000)
        eon = self.report("eontimer")
        eon.consume(clock_stage(0, driver=1, error=-2))
        self.assertTrue(eon.error)

    def test_bad_versions_duplicates_order_config_and_measurements_rejected(self):
        invalid = [clock_stage(1), clock_stage(0, attempt=2), clock_stage(0, driver=1),
                   clock_stage(0).replace("STATUS=2", "STATUS=9"),
                   clock_stage(0).replace("ERROR_US=150", "ERROR_US=151"),
                   clock_stage(0).replace("TARGET_MS=65907", "TARGET_MS=65908"),
                   clock_stage(0) + "|END=1", clock_stage(0).replace("V=1", "V=2"),
                   clock_stage(0, status=0).replace("ELAPSED_US=0", "ELAPSED_US=1"), clock_init()]
        for text in invalid:
            with self.subTest(text=text):
                report = self.report()
                report.consume(text)
                self.assertTrue(report.error)
        report = self.report()
        report.consume(clock_stage(0))
        report.consume(clock_stage(0))
        self.assertTrue(report.error)

    def test_every_protocol_truncation_is_ignored_or_invalid_not_valid_sample(self):
        line = clock_stage(0)
        for length in range(len(line)):
            report = self.report()
            report.consume(line[:length])
            self.assertFalse(report.clock_rows)

    def test_pairing_requires_same_source_goal_capture_and_labels_not_same_driver(self):
        a = self.report()
        b = self.report("eontimer")
        self.assertEqual(a.comparison_key(), b.comparison_key())
        self.assertNotEqual(a.comparison_key(), self.report(capture="Other").comparison_key())
        self.assertNotEqual(a.comparison_key(), self.report(labels="b" * 64).comparison_key())
        changed = ClockTestReport("new", replace(make_config(), seed_ms=65908), "eontimer")
        self.assertNotEqual(a.comparison_key(), changed.comparison_key())


class ClockAdapterTests(unittest.TestCase):
    def test_missing_fixed_unknown_driver_or_injected_main_rejected(self):
        for driver, fixed in ((None, make_config()), ("other", make_config()), ("easycon", None)):
            with self.assertRaises(ValueError):
                validate_driver(driver, fixed)
        with self.assertRaisesRegex(ValueError, "已注入"):
            adapt_main(MARKER)
        with self.assertRaisesRegex(ValueError, "未知流程"):
            adapt_main("unknown")

    def test_f2_changes_only_wait_and_propagates_error_before_button(self):
        text = ("$静态目标时间轴模式 = 0\n"
                "FUNC 静态目标等待F2($普通等待MS: INT): INT\n"
                "    IF $静态目标时间轴模式 == 0\n        WAIT $普通等待MS\n        RETURN 0\n    ENDIF\n"
                "    $静态目标时间轴当前 = TIME()\n    WAIT 100\n"
                "    $静态目标时间轴超时 = $静态目标时间轴当前 - $静态目标时间轴截止\n"
                "    PRINT F2绝对时间轴(静态): 超时 & $静态目标时间轴超时\n    RETURN $静态目标时间轴超时\nENDFUNC\n"
                "FUNC 捕捉(): INT\n    $静态目标时间轴超时 = 静态目标等待F2(0)\n    A\n    RETURN 1\nENDFUNC")
        adapted = adapt_f2(text, wild=False)
        self.assertIn("WAIT $普通等待MS", adapted)
        self.assertIn("        WAIT 100", adapted)
        self.assertIn("CT_Mark(2, TIME())", adapted)
        self.assertIn("IF $静态目标时间轴超时 < 0\n        RETURN -1\n    ENDIF\n    A", adapted)

    def test_distributed_asset_is_small_x64_and_bound_to_manifest(self):
        import hashlib
        manifest = asset_manifest()
        self.assertLess((ASSETS / DLL_NAME).stat().st_size, 200000)
        self.assertEqual(manifest["dll_sha256"], hashlib.sha256((ASSETS / DLL_NAME).read_bytes()).hexdigest())
        source = ASSETS.parents[1] / "tools/clock_test/clock_test.cpp"
        self.assertEqual(manifest["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(manifest["abi"], 1)

    def test_plain_project_with_clock_library_rejected_even_without_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "main.ecs"
            path.write_text("ordinary", encoding="utf-8")
            (path.parent / "plan.json").write_text("{}", encoding="utf-8")
            (path.parent / "lib").mkdir()
            (path.parent / "lib/98_clock_test.ecs").write_text(MARKER, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "混入"):
                validate_test_project(path, expected=False)

    def test_services_generate_rebuild_and_start_keep_driver_and_validate_semantics(self):
        from automation import EasyCon118Options, EasyConRuntimeCheck, EGG_TEMPLATE_NAME
        from automation.eontimer_test import test_options
        from pyside_app.services import AppPaths, WildInputs, prepare_wild, rebuild_wild_with_override, prepare_run
        from tests.test_pyside_services import sample_result
        result = sample_result()
        fixed = make_config()
        main = (FIXED_TEMPLATE + "\nFUNC 执行RNG启动与目标获取(): INT\n"
                "    $time_start = TIME()\n"
                "    $Seed时间轴结果 = 执行时间轴等待到($time_start, $SeedMS)\n"
                "    $Seed时间轴结果 = 执行时间轴等待到($time_start, $SeedMS)\n"
                "    $time_OP = TIME()\n"
                "    $F1时间轴结果 = 执行时间轴等待到($time_OP, $F1时间轴目标MS)\n"
                "    $F2时间轴设置结果 = 设置静态目标时间轴($F2时间轴模式, $F2时间轴截止, $时间轴精确尾段MS)\n"
                "    RETURN 1\nENDFUNC\n")
        def f2(prefix):
            return (f"FUNC {prefix}目标等待F2($普通等待MS: INT): INT\n"
                    f"    ${prefix}目标时间轴当前 = TIME()\n"
                    f"    ${prefix}目标时间轴超时 = ${prefix}目标时间轴当前 - ${prefix}目标时间轴截止\n"
                    f"    RETURN ${prefix}目标时间轴超时\nENDFUNC\n"
                    f"FUNC {prefix}目标(): INT\n    ${prefix}目标时间轴超时 = {prefix}目标等待F2(0)\n    RETURN 1\nENDFUNC\n")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / EGG_TEMPLATE_NAME).write_text("mother-unchanged", encoding="utf-8")
            inputs = WildInputs(result.plan.request, test_options(EasyCon118Options()), root, root / "ezcon.exe",
                                EGG_TEMPLATE_NAME, True, "Capture", True, fixed, "eontimer")
            paths = AppPaths(user=root, output=root / "output")
            def generate(_source, output, *_args, **_kwargs):
                output.mkdir(parents=True)
                (output / "lib").mkdir()
                (output / "ImgLabel").mkdir()
                (output / "ImgLabel/test.IL").write_bytes(b"label-fixture")
                (output / "main.ecs").write_text(main, encoding="utf-8")
                (output / "lib/16_获取_静态目标.ecs").write_text(f2("静态"), encoding="utf-8")
                (output / "lib/17_获取_野生目标.ecs").write_text(f2("野生"), encoding="utf-8")
                (output / "plan.json").write_text(json.dumps({"template": EGG_TEMPLATE_NAME, "precalibration": {"enabled": False}}), encoding="utf-8")
                return output / "main.ecs"
            with patch("pyside_app.services.search_best_plan", return_value=result), \
                 patch("pyside_app.services.write_configured_project", side_effect=generate), \
                 patch("pyside_app.services.validate_generated_project_consistency"), \
                 patch("pyside_app.services.validate_runtime", return_value=EasyConRuntimeCheck(True, (), ())), \
                 patch("pyside_app.services.probe_easycon_devices", return_value=({"COM4"}, {3: "Capture"}, "")), \
                 patch("pyside_app.services.prepare_compat_runner", return_value=root / "runner.exe") as runner, \
                 patch("pyside_app.services.build_run_command", return_value=["unused"]):
                prepared = prepare_wild(inputs, paths, cancel=lambda: False)
                self.assertTrue(prepared.check.ok, prepared.check.errors)
                rebuilt = rebuild_wild_with_override(prepared, paths)
                self.assertIs(rebuilt.inputs, inputs)
                validate_test_project(rebuilt.project, expected=True, fixed=fixed, clock_driver="eontimer")
                command = prepare_run(rebuilt, "COM4", 3, "Capture", paths)
                self.assertTrue(command.check.ok)
                runner.assert_called_once()
                library = rebuilt.project.parent / "lib/98_clock_test.ecs"
                original = library.read_text(encoding="utf-8")
                library.write_text(original + "# user comment\n", encoding="utf-8")
                warnings = validate_test_project(rebuilt.project, expected=True, fixed=fixed, clock_driver="eontimer", fingerprint_warning_only=True)
                self.assertTrue(warnings)
                library.write_text(original.replace("CT_Init(1, 1,", "CT_Init(1, 0,"), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "初始化参数"):
                    prepare_run(rebuilt, "COM4", 3, "Capture", paths)
                self.assertEqual(runner.call_count, 1)
            self.assertEqual((root / EGG_TEMPLATE_NAME).read_text(encoding="utf-8"), "mother-unchanged")


@unittest.skipUnless(sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8, "Windows x64 native clock only")
class NativeClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dll = ctypes.CDLL(str(ASSETS / DLL_NAME))
        for name, count in (("CT_Init", 5), ("CT_Round", 1), ("CT_Info", 1), ("CT_Origin", 2),
                            ("CT_Step", 1), ("CT_Mark", 2), ("CT_Get", 2), ("CT_Close", 0)):
            function = getattr(cls.dll, name)
            function.argtypes = [ctypes.c_int] * count
            function.restype = ctypes.c_int

    def tearDown(self):
        self.dll.CT_Close()

    def test_invalid_init_rounds_and_stage_order_fail_closed(self):
        d = self.dll
        for values in ((2, 0, 10, 10, 20), (1, 2, 10, 10, 20), (1, 0, 10, 20, 20), (1, 0, -1, 10, 20)):
            self.assertLess(d.CT_Init(*values), 0)
            self.assertEqual(d.CT_Info(6), 0)
        self.assertEqual(d.CT_Init(1, 1, 25, 35, 100), 1)
        self.assertEqual(d.CT_Round(0), 1)
        self.assertEqual(d.CT_Origin(0, 100), 100)
        self.assertLess(d.CT_Step(0), 0)
        self.assertLess(d.CT_Round(2), 0)
        self.assertEqual(d.CT_Round(1), 1)
        self.assertLess(d.CT_Origin(1, 100), 0)
        self.assertEqual(d.CT_Origin(0, 100), 100)
        self.assertLess(d.CT_Origin(0, 100), 0)
        self.assertLess(d.CT_Mark(2, 100), 0)

    def test_qpc_independent_of_supplied_wall_time_and_f1_f2_share_origin(self):
        d = self.dll
        self.assertEqual(d.CT_Init(1, 0, 25, 35, 100), 1)
        d.CT_Round(1)
        d.CT_Origin(0, 500)
        time.sleep(.005)
        self.assertEqual(d.CT_Mark(0, 499), 1) # simulated wall clock change, not a system change
        self.assertGreater(d.CT_Get(0, 2), 0)
        self.assertEqual(d.CT_Get(0, 4), -1)
        self.assertEqual(d.CT_Origin(1, 501), 501)
        self.assertEqual(d.CT_Get(1, 5), d.CT_Get(2, 5))
        self.assertLess(d.CT_Step(1), 0) # native A is never secretly a B wait

    def test_precision_steps_yield_and_use_absolute_deadline(self):
        d = self.dll
        self.assertEqual(d.CT_Init(1, 1, 30, 35, 100), 1)
        d.CT_Round(1)
        d.CT_Origin(0, 0)
        calls = 0
        begin = time.perf_counter()
        result = d.CT_Step(0)
        while result == 0:
            calls += 1
            self.assertLess(time.perf_counter() - begin, 1)
            result = d.CT_Step(0)
        self.assertEqual(result, 1)
        self.assertGreaterEqual(calls, 1)
        self.assertEqual(d.CT_Mark(0, 30), 1)
        self.assertGreaterEqual(d.CT_Get(0, 3), -1)
        self.assertGreaterEqual(d.CT_Get(0, 2), 29999)
        self.assertLess(d.CT_Mark(0, 30), 0)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ClockQtTests(unittest.TestCase):
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

    def tearDown(self):
        self.window.running = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def enable(self):
        w = self.window
        w.advanced_check.setChecked(True)
        w.eontimer_mode.setCurrentIndex(2)
        with patch.object(w, "launch_job", return_value=False):
            w.eontimer_test_check.setChecked(True)
        inputs = w.collect_inputs(require_fixed=False)
        w.eontimer_controller.fixed = make_config(inputs.request, inputs.options)

    def test_mode_off_by_default_fixed_required_driver_changes_invalidate_and_lock(self):
        w = self.window
        self.assertFalse(w.eontimer_test_check.isChecked())
        self.enable()
        a = w.collect_inputs()
        self.assertEqual(a.clock_driver, "easycon")
        self.assertFalse(a.options.update_precalibration)
        w.prepared = object()
        w.eontimer_clock_driver.setCurrentIndex(1)
        b = w.collect_inputs()
        self.assertEqual(b.clock_driver, "eontimer")
        self.assertEqual(a.fixed_timeline, b.fixed_timeline)
        self.assertNotEqual(a.fingerprint(), b.fingerprint())
        self.assertIsNone(w.prepared)
        self.assertNotIn("clock_driver", w.settings_payload())
        w.running = True
        w.refresh_state()
        self.assertFalse(w.eontimer_clock_driver.isEnabled())

    def test_live_report_export_and_same_session_pair_are_separate_from_normal_precal(self):
        from automation import EasyConRuntimeCheck
        from pyside_app.services import RunCommand
        self.enable()
        controller = self.window.eontimer_controller
        manifest = self.root / "plan.json"
        manifest.write_text(json.dumps({"eontimer_test": {"clock_test": {"labels_sha256": "a" * 64}}}), encoding="utf-8")
        (self.root / "ImgLabel").mkdir()
        (self.root / "ImgLabel/sample.IL").write_bytes(b"label-fixture")
        (self.root / DLL_NAME).write_bytes((ASSETS / DLL_NAME).read_bytes())
        for driver, number in (("easycon", 0), ("eontimer", 1)):
            inputs = SimpleNamespace(eontimer_test=True, fixed_timeline=make_config(), clock_driver=driver, capture_name="Capture")
            command = RunCommand("unused", (), self.root / f"run-{number}.log", self.root / "stop", "", EasyConRuntimeCheck(True, (), ()), f"run-{number}")
            controller.begin(command, SimpleNamespace(inputs=inputs, project=self.root / "main.ecs"))
            controller.consume(INIT)
            controller.consume(marker("ATTEMPT", ATTEMPT=1))
            controller.consume(clock_init(number))
            for stage in range(3):
                controller.consume(clock_stage(stage, driver=number))
            controller.finish()
            report = json.loads(command.log_path.with_suffix(".clock-timing.json").read_text(encoding="utf-8"))
            self.assertFalse(report["calibration_enabled"])
            self.assertEqual(report["driver"], driver)
        self.assertEqual(controller.report.reference["run_id"], "run-0")
        self.assertIn("同参数另一组", controller.report.render())
        self.assertFalse((self.root / "precalibration.json").exists())
