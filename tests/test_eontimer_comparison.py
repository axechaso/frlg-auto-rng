import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from automation.eontimer_core import Countergroup, CustomPhase, GBA_FPS, INT_MAX, Unit, to_milliseconds
from automation.eontimer_comparison import EasyConPlan, read_easycon_plans, render_report, report
from tools.eontimer_comparison import main


ROOT = Path(__file__).resolve().parents[1]
LOG = """[20:00:00.000] Seed绝对时间轴: 请求30000 ms，实际30002 ms，超时2 ms
[20:00:07.000] F1绝对时间轴: 目标7032 ms，实际7033 ms，超时1 ms
[20:00:07.001] F2绝对时间轴计划: 自Seed确认起40500 ms
[20:00:40.000] F2绝对时间轴(静态): 超时1 ms
"""


class EonTimerCoreTests(unittest.TestCase):
    def test_pinned_gba_golden_vectors(self):
        self.assertEqual(GBA_FPS, 59.7275)
        for frames, milliseconds in ((0, 0), (1, 17), (-1, -17), (2, 33), (420, 7032),
                                     (2000, 33485), (16230, 271734), (-2000, -33485)):
            with self.subTest(frames=frames):
                self.assertEqual(to_milliseconds(frames), milliseconds)

    def test_no_old_60_or_120_conversion(self):
        rows = Countergroup(30000, 420, 2000, 3394).settings()
        self.assertEqual([row["duration_ms"] for row in rows], [30000, 7032, 33485])
        self.assertEqual([row["from_start_ms"] for row in rows], [30000, 37032, 70517])

    def test_custom_ms_and_frame_update_add_to_existing_calibration(self):
        self.assertEqual(CustomPhase(Unit.MILLISECONDS, 30000, -5.5).calibrated(30020).calibration_ms, -25.5)
        self.assertEqual(CustomPhase(Unit.ADVANCES, 2000, 7).calibrated(2002).calibration_ms, -26)
        self.assertEqual(CustomPhase(Unit.HEX, 2000, 7).calibrated(1998).calibration_ms, 40)

    def test_final_error_updates_f2_not_f1_and_does_not_guess_total_target(self):
        old = Countergroup(30000, 420, 2000, 3394, 5, 11, 7)
        new = old.calibrated(30020, 3396, candidates=1)
        self.assertEqual((new.seed_calibration_ms, new.f1_calibration_ms, new.f2_calibration_ms), (-15, 11, -26))
        self.assertEqual((old.seed_calibration_ms, old.f1_calibration_ms, old.f2_calibration_ms), (5, 11, 7))
        later = new.calibrated(29990, 3392, candidates=1)
        self.assertEqual((later.seed_calibration_ms, later.f1_calibration_ms, later.f2_calibration_ms), (-5, 11, 7))

    def test_zero_f1_supports_tutorial_two_phase_setup(self):
        rows = Countergroup(30000, 0, 2000, 2000).settings()
        self.assertEqual(rows[1]["duration_ms"], 0)
        self.assertEqual(rows[2]["from_start_ms"], 63485)

    def test_unique_exact_hit_does_not_move_any_phase(self):
        config = Countergroup(30000, 420, 2000, 3394, 5, 11, 7)
        self.assertEqual(config.calibrated(30000, 3394, candidates=1), config)

    def test_multiple_or_invalid_candidates_do_not_update(self):
        config = Countergroup(30000, 420, 2000, 3394)
        for count in (0, 2, 200, True, 1.0, -1):
            with self.subTest(count=count), self.assertRaises(ValueError):
                config.calibrated(30020, 3396, candidates=count)

    def test_invalid_inputs_and_unexecutable_negative_duration(self):
        base = Countergroup(30000, 420, 2000, 3394)
        for field, value in (("seed_ms", -1), ("f1_frames", True), ("f2_frames", 1.5),
                             ("target_advances", INT_MAX + 1), ("seed_calibration_ms", float("nan")),
                             ("f1_calibration_ms", float("inf")), ("f2_calibration_ms", -40000),
                             ("seed_calibration_ms", True), ("seed_ms", INT_MAX + 1)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                replace(base, **{field: value}).validate()
        with self.assertRaises(ValueError):
            CustomPhase("ms", 1).duration_ms()
        for value in (True, 1.5, INT_MAX + 1, 10**500):
            with self.subTest(value=value), self.assertRaises(ValueError):
                to_milliseconds(value)
        with self.assertRaises(ValueError):
            base.calibrated(-1, 3394, candidates=1)
        with self.assertRaises(ValueError):
            base.calibrated(30000, -1, candidates=1)
        with self.assertRaises(ValueError):
            Countergroup(10, 0, 1, 1).calibrated(100, 1, candidates=1)


class EonTimerComparisonTests(unittest.TestCase):
    def test_reads_complete_attempt_and_strips_ansi(self):
        plans = read_easycon_plans("\x1b[90m" + LOG + "\x1b[0m")
        self.assertEqual(plans, [EasyConPlan(30000, 7032, 40500, 1)])

    def test_skips_initial_measurement_and_incomplete_rounds(self):
        initialization = "Seed绝对时间轴: 请求29000 ms\nPRINT 初始检测\n"
        incomplete = "Seed绝对时间轴: 请求31000 ms\nF1绝对时间轴: 目标7000 ms\n"
        self.assertEqual(len(read_easycon_plans(initialization + incomplete + LOG)), 1)

    def test_does_not_join_old_run_or_out_of_order_markers(self):
        for boundary in ("脚本运行完成", "-- 运行终止 --", "-- 开始运行 --", "==>开始执行脚本：other.ecs"):
            text = "Seed绝对时间轴: 请求30000 ms\n" + boundary + "\n" + "\n".join(LOG.splitlines()[1:])
            self.assertEqual(read_easycon_plans(text), [], boundary)
        self.assertEqual(read_easycon_plans("Seed绝对时间轴: 请求30000 ms\nF2绝对时间轴计划: 自Seed确认起40500 ms\nF1绝对时间轴: 目标7032 ms"), [])
        self.assertEqual(read_easycon_plans("Seed绝对时间轴: 请求30000 ms\nF1绝对时间轴: 目标7032 ms\nF1绝对时间轴: 目标7033 ms\nF2绝对时间轴计划: 自Seed确认起40500 ms"), [])

    def test_rejects_f2_deadline_before_f1(self):
        with self.assertRaises(ValueError):
            read_easycon_plans(LOG.replace("40500", "100"))
        for value in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                EasyConPlan(value, 10, 20).validate()

    def test_compares_absolute_anchors_without_double_counting_f1(self):
        payload = report(Countergroup(30000, 420, 2000, 3394), read_easycon_plans(LOG)[0])
        points = payload["comparison"]
        self.assertEqual([item["easycon_from_start_ms"] for item in points], [30000, 37032, 70500])
        self.assertEqual([item["eontimer_minus_easycon_ms"] for item in points], [0, 0, 17])
        self.assertIn("+17", render_report(payload))
        self.assertIn("计划时间轴", render_report(payload))

    def test_legacy_seed_target_label_but_never_guesses_missing_f1_f2(self):
        self.assertEqual(len(read_easycon_plans(LOG.replace("请求30000", "目标30000"))), 1)
        self.assertEqual(read_easycon_plans("下轮Seed等待:30000 ms\nF1等待帧:420 帧\nF2等待帧:2000 帧"), [])


class EonTimerCommandTests(unittest.TestCase):
    def args(self):
        return ["--seed-ms", "30000", "--f1", "420", "--f2", "2000", "--target-advances", "3394"]

    def run_command(self, args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            result = main(args)
        return result, out.getvalue()

    def test_default_only_prints_without_writing_or_connecting(self):
        with mock.patch("pathlib.Path.open", side_effect=AssertionError("unexpected file I/O")):
            code, output = self.run_command(self.args())
        self.assertEqual(code, 0)
        self.assertIn("33485", output)
        self.assertIn("不运行游戏", output)

    def test_read_only_log_and_explicit_new_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, output = root / "original.log", root / "result.json"
            log.write_text(LOG, encoding="utf-8")
            before = log.read_bytes()
            code, _ = self.run_command(self.args() + ["--easycon-log", str(log), "--output", str(output),
                                                       "--hit-seed-ms", "30020", "--hit-advances", "3396", "--candidates", "1"])
            self.assertEqual(code, 0)
            self.assertEqual(log.read_bytes(), before)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["config"]["f2_calibration_ms"], -33)
            self.assertEqual(payload["config"]["seed_calibration_ms"], -20)
            with self.assertRaises(SystemExit):
                self.run_command(self.args() + ["--output", str(log)])
            self.assertEqual(log.read_bytes(), before)

    def test_requires_complete_unique_hit_data_and_explicit_sample_selection(self):
        for extra in (["--hit-seed-ms", "30020"], ["--candidates", "1"], ["--round", "1"],
                      ["--hit-seed-ms", "30020", "--hit-advances", "3396", "--candidates", "2"]):
            with self.subTest(extra=extra), self.assertRaises(SystemExit):
                self.run_command(self.args() + extra)
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "two.log"
            log.write_text(LOG + LOG.replace("30000", "30010"), encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.run_command(self.args() + ["--easycon-log", str(log)])
            code, output = self.run_command(self.args() + ["--easycon-log", str(log), "--round", "2"])
            self.assertEqual(code, 0)
            self.assertIn("-10", output)
            with self.assertRaises(SystemExit):
                self.run_command(self.args() + ["--easycon-log", str(log), "--round", "3"])

    def test_no_production_wiring_or_eon_runner_patch(self):
        for name in ("pyside_preview.py", "pyside_app/migration.py", "pyside_app/workflows.py",
                     "tools/build_easycon164a_compat_runner.ps1"):
            self.assertNotIn("eontimer", (ROOT / name).read_text(encoding="utf-8").lower())
        for name in ("tools/patches/easycon164a-eontimer-test-v1.patch", "tools/eontimer/EonTimerBuiltins.cs",
                     "tools/verify_eontimer_runner.py"):
            self.assertFalse((ROOT / name).exists())


if __name__ == "__main__":
    unittest.main()
