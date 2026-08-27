import csv
from dataclasses import asdict, replace
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from automation.tid_rng137 import TidRngRequest
from run_auto_rng_gui import AutoRngApp
from run_easycon_logged import run_logged
from run_tid_starter_flow import FlowRunner
from tid_records import (
    TidLogParser, TidRecordContext, TidRecordStore, TidRecordingSession, recording_session,
)


def context(game="火红", nx_model=1):
    return TidRecordContext.from_request(game, TidRngRequest(nx_model=nx_model))


def observation(tid="12345", op=3693, f1=2693, f2=2105, *, newline=True):
    return (
        f"\x1b[90m[20:10:00.100] \x1b[0m当前TID：{tid}\x1b[0m\n"
        "当前TID命中次数：9（本参数观察窗口）\n"
        f"【OP】{op}【F1】{f1}【F2】{f2}\n"
        "select执行次数：2；HOME_BUFFER(ms)：1200" + ("\n" if newline else "")
    )


class TidRecordTests(unittest.TestCase):
    def test_context_whitelists_tid_settings_and_requires_game_and_model(self):
        data = asdict(context("叶绿", 2))
        self.assertEqual((data["game"], data["nx_model"]), ("叶绿", 2))
        self.assertFalse(any("sid" in name.lower() or "f3" in name.lower() for name in data))
        with self.assertRaises(ValueError):
            context("未知游戏")
        with self.assertRaises(ValueError):
            context(nx_model=3)

    def test_chunked_colored_log_keeps_leading_zero_and_ignores_window_count(self):
        parser = TidLogParser(context())
        rows = []
        for character in observation("00001"):
            rows.extend(parser.feed(character))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].tid, rows[0].op, rows[0].f1, rows[0].f2, rows[0].select_count), (1, 3693, 2693, 2105, 2))
        self.assertEqual(parser.feed("", final=True), [])

    def test_final_partial_line_is_only_recorded_at_end(self):
        parser = TidLogParser(context())
        self.assertEqual(parser.feed(observation(newline=False)), [])
        self.assertEqual(len(parser.feed("", final=True)), 1)
        self.assertEqual(parser.feed("", final=True), [])

    def test_incomplete_invalid_target_and_sid_lines_do_not_make_rows(self):
        parser = TidLogParser(context())
        noise = "目标TID：12345\nTIDFLOW|ID|TID=12345\nSID ADV：199\n目标SID：8832\n"
        self.assertEqual(parser.feed(noise), [])
        self.assertEqual(parser.feed(observation("99999")), [])
        self.assertEqual(parser.feed(observation("12-134")), [])
        self.assertEqual(parser.feed("当前TID：12345\n【OP】1【F1】2【F2】3\n当前TID：bad\nselect执行次数：2\n"), [])
        self.assertEqual(parser.feed("当前TID：12345\nID识别不完整\n【OP】1【F1】2【F2】3\nselect执行次数：2\n"), [])

    def test_legacy_separate_select_line_is_supported(self):
        parser = TidLogParser(context())
        text = observation().replace("；HOME_BUFFER(ms)：1200", "")
        self.assertEqual(len(parser.feed(text)), 1)

    def test_flow_records_only_id_stage_and_resets_op_recovery_for_next_attempt(self):
        parser = TidLogParser(context(), flow=True)
        self.assertEqual(parser.feed(observation()), [])
        parser.feed("========== 第1阶段：TID/SID ==========\n")
        parser.feed("OP修正增加50ms：当前修正=100ms，实际固定WAIT=30650ms\n")
        row = parser.feed(observation())[0]
        self.assertEqual(row.context.op_correction, 100)
        parser.feed("========== 第2阶段：研究所 ==========\n")
        self.assertEqual(parser.feed(observation()), [])
        parser.feed("========== 第3阶段：御三家 ==========\n")
        self.assertEqual(parser.feed(observation()), [])
        parser.feed("========== 第1阶段：TID/SID ==========\n")
        self.assertEqual(parser.feed(observation())[0].context.op_correction, 0)

    def test_store_counts_actual_observations_and_deduplicates_retry_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TidRecordStore(Path(temp) / "tid.sqlite3")
            rows = TidLogParser(context()).feed(observation() * 2 + observation("54321"))
            entries = list(enumerate(rows, 1))
            store.append("run", entries, Path("test.log"))
            store.append("run", entries, Path("test.log"))
            self.assertEqual({r["tid"]: r["occurrences"] for r in store.rows()}, {12345: 2, 54321: 1})
            self.assertEqual(len(TidRecordStore(store.path).rows()), 2)

    def test_fire_red_leaf_green_and_switch_models_never_merge(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TidRecordStore(Path(temp) / "tid.sqlite3")
            for game in ("火红", "叶绿"):
                for nx in (1, 2):
                    row = TidLogParser(context(game, nx)).feed(observation())[0]
                    store.append(f"{game}-{nx}", [(1, row)], Path("test.log"))
            self.assertEqual(len(store.rows()), 4)
            self.assertEqual(len(store.rows(game="叶绿")), 2)
            self.assertEqual(len(store.rows(nx_model=1)), 2)
            rows = store.rows(game="叶绿", nx_model=2, tid=12345)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["occurrences"], 1)
            self.assertEqual(store.rows(game="叶绿", nx_model=2, tid=42), [])

    def test_different_frames_and_op_corrections_remain_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TidRecordStore(Path(temp) / "tid.sqlite3")
            parser = TidLogParser(context())
            rows = parser.feed(observation() + observation(op=3694))
            parser.feed("OP修正增加50ms：当前修正=50ms，实际固定WAIT=30600ms\n")
            rows.extend(parser.feed(observation()))
            store.append("run", list(enumerate(rows)), Path("test.log"))
            self.assertEqual(len(store.rows()), 3)

    def test_r3_ns2_offset_never_merges_with_older_ns2_records(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TidRecordStore(Path(temp) / "tid.sqlite3")
            parser = TidLogParser(context("火红", 2))
            rows = parser.feed(observation())
            self.assertNotIn("op_model_offset", rows[0].parameters())
            parser.feed("OP机型补偿(ms)：-750；OP修正(ms)：0\n")
            rows.extend(parser.feed(observation()))
            store.append("run", list(enumerate(rows)), Path("test.log"))
            records = store.rows(game="火红", nx_model=2)
            self.assertEqual({row["op_model_offset"] for row in records}, {0, -750})
            self.assertTrue(all(row["occurrences"] == 1 for row in records))
            path = Path(temp) / "table.csv"
            store.export_csv(path)
            exported = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
            self.assertEqual({row["OP机型补偿ms"] for row in exported}, {"0", "-750"})

    def test_r3_ns1_zero_offset_keeps_old_records_compatible(self):
        parser = TidLogParser(context())
        old = parser.feed(observation())[0]
        parser.feed("OP机型补偿(ms)：0；OP修正(ms)：0\n")
        new = parser.feed(observation())[0]
        self.assertEqual(old.parameters(), new.parameters())

    def test_model_offset_is_reset_when_flow_enters_new_id_attempt(self):
        parser = TidLogParser(context(nx_model=2), flow=True)
        parser.feed("========== 第1阶段：TID/SID ==========\nOP机型补偿(ms)：-750；OP修正(ms)：0\n")
        self.assertEqual(parser.feed(observation())[0].op_model_offset, -750)
        parser.feed("========== 第2阶段：研究所 ==========\nOP机型补偿(ms)：-123\n")
        parser.feed("========== 第1阶段：TID/SID ==========\n")
        self.assertEqual(parser.feed(observation())[0].op_model_offset, 0)

    def test_csv_is_filtered_utf8_and_contains_no_sid_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = TidRecordStore(root / "tid.sqlite3")
            for nx in (1, 2):
                parser = TidLogParser(replace(context("叶绿", nx), player_name="=test"))
                store.append(str(nx), [(1, parser.feed(observation("00001"))[0])], root / "run.log")
            path = root / "tid.csv"
            self.assertEqual(store.export_csv(path, game="叶绿", nx_model=2), 1)
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            data = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
            self.assertEqual(data[0]["TID"], "00001")
            self.assertEqual(data[0]["Switch机型"], "2")
            self.assertEqual(data[0]["主角名称"], "'=test")
            self.assertNotIn("SID", path.read_text(encoding="utf-8-sig"))

    def test_database_failure_retries_without_stopping_or_double_counting(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TidRecordStore(Path(temp) / "tid.sqlite3")
            warnings = []
            session = TidRecordingSession(context(), store, Path("run.log"), warning=warnings.append)
            with patch("tid_records.time.monotonic", return_value=10):
                with patch.object(store, "append", side_effect=sqlite3.OperationalError("locked")) as append:
                    session.feed(observation())
                    session.feed("more log output\n")
                    append.assert_called_once()
                self.assertEqual(len(session.pending), 1)
                self.assertEqual(len(warnings), 1)
                session.feed("", final=True)
                session.feed("", final=True)
            self.assertEqual(session.pending, [])
            self.assertEqual(store.rows()[0]["occurrences"], 1)

    def test_pending_records_retry_after_backoff_and_include_later_observations(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TidRecordStore(Path(temp) / "tid.sqlite3")
            session = TidRecordingSession(context(), store, Path("run.log"))
            with patch("tid_records.time.monotonic", return_value=10), patch.object(store, "append", side_effect=sqlite3.OperationalError("locked")):
                session.feed(observation())
            with patch("tid_records.time.monotonic", return_value=10.5):
                session.feed(observation("54321"))
                self.assertEqual(len(session.pending), 2)
            with patch("tid_records.time.monotonic", return_value=11):
                session.feed("")
            self.assertEqual(session.pending, [])
            self.assertEqual({row["tid"]: row["occurrences"] for row in store.rows()}, {12345: 1, 54321: 1})

    def test_log_worker_records_without_gui_and_flushes_last_line(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context("叶绿", 2).save(root / "context.json")
            text = observation(newline=False)
            code = "import sys; sys.stdout.write(" + repr(text) + "); sys.stdout.flush()"
            with patch("run_easycon_logged._write_console"):
                result = run_logged([sys.executable, "-X", "utf8", "-c", code], root, root / "run.log",
                                    tid_context=root / "context.json", tid_records=root / "tid.sqlite3")
            self.assertEqual(result, 0)
            rows = TidRecordStore(root / "tid.sqlite3").rows()
            self.assertEqual((rows[0]["game"], rows[0]["nx_model"]), ("叶绿", 2))

    def test_flow_worker_passes_output_to_tid_recording(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context().save(root / "context.json")
            with recording_session(root / "context.json", root / "tid.sqlite3", root / "run.log", flow=True) as recording:
                runner = FlowRunner(Path("runner.exe"), port="COM4", video_device=0, log=io.StringIO(), recording=recording)
                with patch("run_tid_starter_flow.print"):
                    runner.output("========== 第1阶段：TID/SID ==========")
                    runner.output(observation())
                    runner.output("========== 第3阶段：御三家 ==========")
                    runner.output(observation())
            self.assertEqual(TidRecordStore(root / "tid.sqlite3").rows()[0]["occurrences"], 1)

    def test_gui_filters_pass_both_game_and_model(self):
        variable = lambda value: SimpleNamespace(get=lambda: value)
        app = SimpleNamespace(tid_record_game_var=variable("叶绿"), tid_record_nx_var=variable("Switch 2"), tid_record_filter_var=variable("00001"))
        self.assertEqual(AutoRngApp._tid_record_filters(app), {"game": "叶绿", "nx_model": 2, "tid": 1})
        app.tid_record_filter_var = variable("65536")
        with self.assertRaises(ValueError):
            AutoRngApp._tid_record_filters(app)

    def test_gui_context_snapshot_does_not_include_sid_or_follow_later_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = SimpleNamespace(tid_game_var=SimpleNamespace(get=lambda: "叶绿"), tid_request=TidRngRequest(nx_model=2))
            args = AutoRngApp._tid_record_arguments(app, root / "run.log")
            data = json.loads(Path(args[1]).read_text(encoding="utf-8"))
            self.assertEqual((data["game"], data["nx_model"]), ("叶绿", 2))
            self.assertFalse(any("sid" in key.lower() for key in data))
            app.tid_request = TidRngRequest(nx_model=1)
            self.assertEqual(json.loads(Path(args[1]).read_text(encoding="utf-8"))["nx_model"], 2)


if __name__ == "__main__":
    unittest.main()
