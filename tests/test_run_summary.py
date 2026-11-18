import unittest

from pyside_app.run_summary import RunSummary


class RunSummaryTests(unittest.TestCase):
    def feed(self, model, text):
        for line in text.splitlines():
            model.consume(line)

    def test_compact_results_preserve_rounds_and_observed_axes(self):
        model = RunSummary()
        self.feed(model, "[12:01:02.123] 第1轮开始\n"
                  "\x1b[32m本轮结果: Seed A1B2（偏差 1），消耗帧 12345（偏差 -2）\x1b[0m\n"
                  "任意脚本调试输出\n第2轮\n"
                  "本轮结果: Seed 1234（偏差 0），消耗帧 12347（偏差 0）\n"
                  "已命中目标，脚本停止")
        first, second = model.rounds.values()
        self.assertEqual((first.seed, first.seed_delta, first.advances, first.frame_delta), ("A1B2", 1, 12345, -2))
        self.assertEqual(second.result, "脚本已确认目标")
        grid, _ = model.bingo()
        self.assertEqual(grid[5][2], "1")
        self.assertEqual(grid[4][4], "＠")

    def test_reported_zero_delta_needs_confirmed_axes(self):
        for evidence, status in (("", "Seed / 帧零偏差待确认"),
                                 ("Seed可信: 0\n消耗帧最终可信: 0\n", "候选待确认")):
            with self.subTest(evidence=evidence):
                model = RunSummary()
                self.feed(model, "第1轮\n" + evidence
                          + "本轮结果: Seed AABB（偏差 0），消耗帧 1000（偏差 0）")
                self.assertEqual(model.current.result, status)
                self.assertEqual(model.bingo()[0][4][4], "＋")

    def test_tv_cycle_with_zero_phase_is_not_an_exact_hit(self):
        model = RunSummary()
        self.feed(model, "第1轮\nSeed可信: 1\n消耗帧最终可信: 1\n"
                  "本轮结果: Seed AABB（偏差 0），消耗帧 1314（偏差 314）\n"
                  "归一化帧偏移: 0 帧")
        self.assertEqual(model.current.result, "存在偏差")
        self.assertEqual(model.bingo()[0][4][4], "＋")

    def test_verbose_results_do_not_confuse_millisecond_and_frame_errors(self):
        model = RunSummary()
        self.feed(model, "第3轮\n【Seed校准】\n命中Seed: AABB\n与目标Seed差: -1个seed\n"
                  "误差: 99 ms\n【消耗帧校准】\n命中消耗帧: 4567 帧\n误差: -312 帧\n"
                  "剩余帧落点(0..周期-1): 2；剩余帧误差 2 帧")
        self.assertEqual(model.current.frame_delta, -312)
        self.assertEqual(model.current.normalized_delta, 2)
        grid, _ = model.bingo()
        self.assertEqual(grid[3][6], "①")

    def test_script_bingo_is_atomic_and_preserves_original_symbols(self):
        model = RunSummary()
        model.consume("【BINGO】")
        rows = ["　０　　．．．．＠．．．．"]
        for offset in (-4, -3, -2, -1, 1, 2, 3, 4):
            label = str(offset).translate(str.maketrans("-+01234", "－＋０１２３４"))
            if offset > 0:
                label = "＋" + label
            cells = "．．．①２ｏｘ．．" if offset == 1 else "．" * 9
            rows.append(label + "　　" + cells)
        self.feed(model, "\n".join(rows[:-1]))
        self.assertIsNone(model.script_grid)
        model.consume(rows[-1])
        grid, source = model.bingo()
        self.assertIn("脚本", source)
        self.assertEqual(grid[4][4], "＠")
        self.assertEqual(grid[5][3:7], ("①", "２", "ｏ", "ｘ"))
        model.consume("TV帧　　．．①．＋．．２．")
        self.assertEqual(model.tv_cells[2], "①")

    def test_incomplete_or_malformed_rows_do_not_replace_a_chart(self):
        model = RunSummary()
        self.feed(model, "第1轮\n本轮结果: Seed FFFF（偏差 1），消耗帧 2（偏差 1）")
        before = model.bingo()[0]
        self.feed(model, "【BINGO】\n－４　　．＠．\n【其他输出】\n＋４　　" + "．" * 9)
        self.assertIsNone(model.script_grid)
        self.assertEqual(model.bingo()[0], before)
        self.assertFalse(model.consume("本轮结果: Seed INVALID（偏差 1），消耗帧 2（偏差 1）"))

    def test_bounded_rounds_and_new_segments_do_not_merge_hits(self):
        model = RunSummary(limit=3)
        for number in range(1, 6):
            self.feed(model, f"第{number}轮\n本轮结果: Seed AABB（偏差 1），消耗帧 2（偏差 1）")
        self.assertEqual(len(model.rounds), 3)
        self.feed(model, "第1轮\n本轮结果: Seed AABB（偏差 -1），消耗帧 2（偏差 -1）")
        self.assertEqual(model.current.segment, 2)
        grid, _ = model.bingo()
        self.assertEqual(grid[5][5], "·")
        self.assertEqual(grid[3][3], "①")

    def test_outside_chart_and_unknown_results_are_not_fabricated_hits(self):
        model = RunSummary()
        self.feed(model, "第1轮\n任意调试\n")
        self.assertEqual(model.current.result, "等待本轮结果")
        self.feed(model, "本轮结果: Seed AABB（偏差 1），消耗帧 2（偏差 1）\n"
                  "第2轮\n本轮结果: Seed AABB（偏差 5），消耗帧 2（偏差 0）")
        grid, _ = model.bingo()
        self.assertEqual(grid[5][5], "1")
        self.assertNotIn("＠", "".join("".join(row) for row in grid))
        self.feed(model, "第3轮\n当前TID: 12345")
        self.assertEqual(model.current.result, "识别到 TID 12345")

    def test_retry_diagnostics_do_not_override_a_later_observed_result(self):
        model = RunSummary()
        self.feed(model, "第1轮\n反查无候选，追加一档扩窗\n")
        self.assertEqual(model.current.result, "等待本轮结果")
        self.feed(model, "本轮结果不唯一\nSeed可信: 1\n消耗帧最终可信: 1\n"
                  "【Seed校准】\n命中Seed: ABCD\n与目标Seed差: 0个seed\n"
                  "【消耗帧校准】\n命中消耗帧: 1000 帧\n误差: 0 帧")
        self.assertEqual(model.current.result, "Seed / 帧命中")


if __name__ == "__main__":
    unittest.main()
