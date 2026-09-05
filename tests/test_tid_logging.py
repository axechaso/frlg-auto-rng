"""Exercise generated reports and their consumers, including state isolation."""
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from automation.tid_checkpoint import CHECKPOINT_V3_PREFIX
from automation.tid_rng137 import TidRngRequest
from automation.tid_starter_save import DEFAULT_TID_STARTER_SAVE_SOURCE
from run_auto_rng_gui import clean_terminal_log, read_display_log_tail, read_full_run_log
from run_tid_starter_flow import FlowRunner
from tid_records import TidRecordContext, TidLogParser
from tests import test_tid_search as support


@unittest.skipUnless(DEFAULT_TID_STARTER_SAVE_SOURCE.is_file(), "requires audited TID template")
class TidLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.TidSearchTests.setUpClass()
        cls.support = support.TidSearchTests()

    def machine(self, request):
        m, p, _ = self.support.setup_machine(request)
        m.state.update({"TID脚本版本": "2026-08-28-r3", "name": request.player_name,
                        "select基础次数": 1, "F3总帧": 2700, "CISHU": 6})
        m.output = []
        return m, p

    def observe(self, m, p, tid):
        for i, digit in enumerate(f"{tid:05d}", 1):
            m.state[f"curr{i}"] = int(digit)
        m.call(p + "_去噪")

    def test_round_report_preserves_state_and_records_exact_five_digit_tid(self):
        for language in ("英文", "日文"):
            request = TidRngRequest(language=language, player_name="Alxe" if language == "英文" else "レット゛",
                mode=0, target_tid=0, additional_target_tids=(3, 65535), sid_random=True)
            m, p = self.machine(request)
            self.observe(m, p, 1)
            before = dict(m.state)
            m.call(p + "_打印参数")
            report = "\n".join(m.output) + "\n"
            self.assertIn("目标TID：00000、00003、65535", report)
            self.assertIn("当前TID：00001", report)
            self.assertIn("本参数观察次数：1 / 10", report)
            self.assertIn("当前阶段：F2外层筛查", report)
            self.assertIn("Sound：MONO", report)
            self.assertIn("Button Mode：HELP", report)
            self.assertIn("本轮环形差值：1", report)
            self.assertNotIn("专用回填参数", report)
            for key, value in before.items():
                if not key.startswith("TID日志") and key not in ("adv", "select执行次数"):
                    self.assertEqual(m.state[key], value, key)
            self.assertEqual(m.state["adv"], 2700 + m.state["英文版SID_ADV补偿"])
            self.assertEqual(m.state["select执行次数"], 1 + request.select_correction)
            rows = TidLogParser(TidRecordContext.from_request("火红", request)).feed(report)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].tid, 1)
            self.assertEqual((rows[0].op, rows[0].f1, rows[0].f2),
                             tuple(m.state[a + "总帧"] for a in ("OP", "F1", "F2")))

    def test_rng_report_uses_locked_target_and_clipped_live_ranges(self):
        request = TidRngRequest(sid_random=False, target_tid=3, target_sid=7,
            op_target_frame=0, op_rng_range=20, f1_rng_range=20, f2_rng_range=10)
        m, p = self.machine(request)
        m.state["adv"] = 3256
        self.observe(m, p, 65535)
        m.call(p + "_打印参数")
        report = "\n".join(m.output)
        self.assertIn("目标TID：00003", report)
        self.assertIn("目标SID：00007", report)
        self.assertIn("SID ADV：3256", report)
        self.assertIn("OP当前偏移：0；有效范围：-0 / +20", report)
        self.assertIn("本轮环形差值：-4", report)
        self.assertEqual(m.state["adv"], 3256)

    def test_auto_switch_reports_observation_before_clearing_window(self):
        request = TidRngRequest(mode=0, auto_rng=True, target_tid=33333,
                                additional_target_tids=(0,), sid_random=True)
        m, p = self.machine(request)
        for tid in (65535, 1, 2):
            self.observe(m, p, tid)
            m.call(p + "_检测目标区域")
        report = "\n".join(m.output)
        self.assertIn("第7轮", report)
        self.assertIn("当前TID：00002", report)
        self.assertIn("本参数观察次数：3 / 10", report)
        self.assertLess(report.index("当前TID：00002"), report.index("穷举已自动转为乱数模式"))
        self.assertEqual((m.state["CISHU"], m.state["denoise_try_count"]), (6, 0))
        m.output.clear()
        self.observe(m, p, 65534)
        m.call(p + "_打印参数")
        self.assertIn("当前模式：乱数（穷举自动切换）", "\n".join(m.output))
        self.assertIn("目标TID：00000", m.output)

    def test_backfill_only_runs_inside_confirmed_success_exits(self):
        for language in ("英文", "日文"):
            m, p = self.machine(TidRngRequest(language=language,
                player_name="Alxe" if language == "英文" else "レット゛", mode=0, sid_random=True))
            self.observe(m, p, 54321)
            self.observe(m, p, 54321)
            m.call(p + "_打印参数")
            self.assertNotIn("专用回填参数", "\n".join(m.output))
            blocks = re.findall(r"(?ms)^                IF \$denoise_hit_count >= \$denoise_need_hit\n(.*?)^                ELSE", m.source)
            self.assertEqual(len(blocks), 10)  # Both language bodies remain in the combined source.
            changed = [b for b in blocks if f"CALL {p}_打印回填参数" in b]
            self.assertEqual(len(changed), 5)
            for block in changed:
                body = "\n".join(line for line in block.splitlines() if line.strip() != "BREAK 2")
                m.source += "\nFUNC CONFIRMED\n" + body + "\nENDFUNC\n"
                m.compiled.pop("CONFIRMED", None)
                m.output.clear()
                m.call("CONFIRMED")
                self.assertEqual(sum("专用回填参数" in line for line in m.output), 1)
                m.source = m.source[:m.source.rfind("\nFUNC CONFIRMED")]

    def test_display_hides_checkpoint_but_worker_keeps_progress_and_record_feed(self):
        from unittest.mock import Mock
        request = TidRngRequest(mode=0, auto_rng=True, sid_random=True)
        m, p = self.machine(request)
        state = self.support.state(m, p)
        line = CHECKPOINT_V3_PREFIX + "|".join(f"{k}={v}" for k,v in state.items()) + "|END=1"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            with path.open("w", encoding="utf-8") as log:
                runner = FlowRunner(Path("unused"), port="COM4", video_device=0, log=log, recording=Mock())
                runner.active_stage = 1
                runner.progress = Mock()
                with patch("run_tid_starter_flow.print"):
                    runner.output("\x1b[90m[12:34:56] \x1b[0m" + line)
                    runner.output("当前TID：00001")
                runner.progress.feed.assert_any_call("\x1b[90m[12:34:56] \x1b[0m" + line)
                runner.recording.feed.assert_any_call("\x1b[90m[12:34:56] \x1b[0m" + line + "\n")
            self.assertIn(line, read_full_run_log(path))
            self.assertEqual(read_display_log_tail(path), "当前TID：00001\n")
        malformed = line[:-6]
        self.assertEqual(clean_terminal_log(malformed), malformed)
        self.assertEqual(clean_terminal_log("TIDPROGRESS|DONE=1"), "TIDPROGRESS|DONE=1")
