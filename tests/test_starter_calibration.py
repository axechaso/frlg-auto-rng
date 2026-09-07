"""Hardware-free replay of the actual starter ECS and generation hooks."""

import json
from pathlib import Path
import re
import unittest

from automation.seed_common_regions import ASSET, upgrade_entry, upgrade_library
from automation.starter_calibration import ASSET as STARTER_ASSET
from automation.starter_calibration import upgrade_starter_calibration
from tests.test_seed_common_regions import CommonReplay


def function(text, name):
    return re.search(rf"(?ms)^FUNC {name}[^\n]*\n.*?^ENDFUNC", text)[0]


def strict_replay():
    replay = CommonReplay()
    replay.call("共同区设置严格模式", 1)
    return replay


def selected(replay):
    slot = replay.call("共同区选择本轮配对")
    return None if slot < 0 else [replay.v["C_本Seed"][slot], replay.v["C_本ADV"][slot]]


def entry_fixture(timeline=False):
    # Only anchors needed by the installer, not an alternative ECS runtime.
    return """$other = 1
CALL 投票重置Seed校准
        $反查细分成功 = 执行识图反查直到候选唯一()
        IF $反查细分成功 == 1 and $调试日志输出 == 1
            CALL 保留流程
        ENDIF
        $校准成功 = 执行自动校准与等待更新()
FUNC 执行识图反查直到候选唯一(): INT
        $有效最大消耗帧 = $最大消耗帧
            IF $扩窗层数上限 <= 0 or $当前扩窗层 >= $扩窗层数上限
                BREAK
            ENDIF
        IF $反查扫描成功 == 0
            RETURN 0
        ENDIF
ENDFUNC
FUNC 重置本轮候选状态
    $other = 0
ENDFUNC
FUNC 处理匹配候选
    $当前候选帧原始 = $当前消耗帧 - $目标消耗帧
    # 路径一致性选择：现有诊断
    $当前候选距离 = 0
    # NPC离群过滤：现有规则
    $当前候选离群 = 0
    IF $最佳候选有效 == 0
        CALL 记录当前候选为最佳候选
    ENDIF
ENDFUNC
FUNC 执行自动校准与等待更新(): INT
    $投票忽略 = 投票记真值解($本轮真值解, $消耗帧本轮偏离中心)
    RETURN 1
ENDFUNC
FUNC 执行RNG启动与目标获取(): INT
""" + ("    $F2时间轴截止 = TIME()\n" if timeline else "") + """    # 普通帧轴菜单奇偶方案：原顺序
        X
        WAIT 500
        B
        WAIT 500
    $first = 执行目标获取($遭遇地点, $F2等待MS, $TV等待MS, $钓鱼最长时间)
    $second = 执行目标获取($遭遇地点, $F2等待MS, $TV等待MS, $钓鱼最长时间)
ENDFUNC
"""


class StarterCalibrationTests(unittest.TestCase):
    def test_strict_tighter_adv_beats_same_coverage_separate_cluster(self):
        replay = strict_replay()
        for r in range(4):
            replay.submit([(40000 + r, 1500 + r), (40500 + r, 1600 + 2 * r)])
        self.assertEqual(replay.v["C_可用"], 1)
        self.assertEqual(selected(replay), [40003, 1503])

    def test_adv_span_ranks_before_seed_span(self):
        replay = strict_replay()
        for r in range(4):
            replay.submit([(40000 + 20 * r, 1500 + r), (40500 + r, 1600 + 2 * r)])
        self.assertEqual(selected(replay), [40060, 1503])

    def test_seed_span_breaks_equal_adv_span(self):
        replay = strict_replay()
        for r in range(4):
            replay.submit([(40000 + 2 * r, 1500 + r), (40500 + r, 1600 + r)])
        self.assertEqual(selected(replay), [40503, 1603])

    def test_exact_rank_tie_remains_ambiguous(self):
        replay = strict_replay()
        for r in range(4):
            replay.submit([(40000 + r, 1500 + r), (40500 + r, 1600 + r)])
        self.assertEqual(replay.v["C_歧义"], 1)
        self.assertIsNone(selected(replay))

    def test_cold_multiple_candidates_cannot_calibrate(self):
        replay = strict_replay()
        for r in range(2):
            replay.submit([(40000 + r, 1500 + r), (40500 + r, 1600 + r)])
            self.assertIsNone(selected(replay))

    def test_nearby_equal_rank_regions_cannot_choose_arbitrary_lower_seed(self):
        replay = strict_replay()
        for r in range(4):
            replay.submit([(40000 + r, 1500 + r), (40020 + r, 1520 + r)])
        self.assertEqual(replay.v["C_可用"], 0)
        self.assertIsNone(selected(replay))

    def test_complete_single_candidate_is_independent_evidence(self):
        replay = strict_replay()
        replay.submit([(40000, 1500)])
        self.assertEqual(selected(replay), [40000, 1500])

    def test_overflow_then_duplicate_recovers_without_another_vote(self):
        replay = strict_replay()
        for r in range(3):
            replay.submit([(40000 + r, 1500 + r), (41000 + 1000 * r, 1700)])
        replay.submit([(x, x) for x in range(201)])
        self.assertIsNone(selected(replay))
        replay.submit([(40002, 1502), (43000, 1700)])
        self.assertEqual(replay.v["C_轮数"], 3)
        self.assertEqual(selected(replay), [40002, 1502])

    def test_multiple_current_points_inside_region_stay_ambiguous(self):
        replay = strict_replay()
        replay.submit([(40000, 1500)])
        replay.submit([(40020, 1502)])
        replay.submit([(40005, 1500), (40010, 1501)])
        self.assertIsNone(selected(replay))

    def test_real_log_online_and_full_history(self):
        data = json.loads((Path(__file__).parent / "fixtures/starter_common_region_20260907.json").read_text())
        replay = strict_replay()
        online = {}
        for row in data["rounds"]:
            replay.submit(row["points"])
            online[row["round"]] = selected(replay)
        self.assertEqual(replay.v["C_轮数"], 12)
        self.assertEqual(replay.rank(), (-12, 3, 100))
        self.assertEqual(online[6], [70453, 1504])  # B239/1502, not 816B/1507.
        self.assertIsNone(online[3])  # Only two distinct observations then.
        for row in data["rounds"]:
            replay.call("共同区开始扫描")
            for ms, adv in row["points"]:
                replay.call("共同区收集配对", ms, adv, ms)
            self.assertEqual(selected(replay), row["expected"], row["round"])

    def test_window_prediction_undoes_cumulative_correction(self):
        replay = strict_replay()
        self.assertEqual(replay.call("共同区预测ADV", 1502, 7), 1495)
        for r in range(3):
            replay.submit([(40000 + r, 1503 + r)])
        self.assertEqual(replay.call("共同区预测ADV", 1502, 120), 1384)

    def test_main_window_clamps_negative_prediction_and_caps_radius(self):
        replay = CommonReplay(source=STARTER_ASSET.read_text(encoding="utf-8"))
        replay.env["共同区预测ADV"] = lambda target, correction: target - correction
        replay.v.update(御三家严格筛选=1, 目标消耗帧=100, 消耗帧实际执行修正量=1000,
                        最小消耗帧=0, 最大消耗帧=10000)
        replay.call("御三家准备反查窗口")
        self.assertEqual(replay.v["有效最小消耗帧"], 0)
        self.assertEqual(replay.v["有效最大消耗帧"], 500)

    def test_menu_budget_uses_elapsed_ms_and_rejects_overrun(self):
        replay = CommonReplay(source=STARTER_ASSET.read_text(encoding="utf-8"))
        for elapsed, expected in [(0, 4000), (1017, 2983), (4000, 0), (4001, -1), (-1, -1)]:
            self.assertEqual(replay.call("御三家计算菜单剩余等待", 4000, elapsed), expected)

    def test_installer_is_idempotent_and_submits_before_selection(self):
        text = upgrade_entry(entry_fixture())
        self.assertEqual(upgrade_entry(text), text)
        self.assertLess(text.index("共同区提交()"), text.index("$御三家筛选结果 ="))
        self.assertLess(text.index("$御三家筛选结果 ="), text.index("$校准成功 ="))
        self.assertIn("IF $御三家筛选结果 != 1\n                $循环计数 += 1\n                BREAK", text)
        self.assertIn("CALL 投票重置Seed校准\nCALL 共同区重置", text)

    def test_formal_timing_only_and_shared_helpers_match(self):
        formal = upgrade_entry(entry_fixture())
        timeline = upgrade_entry(entry_fixture(True))
        self.assertIn("$御三家菜单耗时MS = TIME() - $御三家菜单起始MS", formal)
        self.assertNotIn("$御三家菜单耗时MS = TIME() - $御三家菜单起始MS", timeline)
        for name in re.findall(r"(?m)^FUNC (御三家\w+)", formal):
            self.assertEqual(function(formal, name), function(timeline, name))

    def test_non_target_seed_one_frame_freeze_is_not_overridden(self):
        text = upgrade_entry(entry_fixture())
        block = function(text, "执行自动校准与等待更新")
        self.assertIn("IF $本轮剩余帧校准允许 == 1\n            $剩余帧本轮可信 = 1", block)

    def test_path_reanchor_preserves_strict_history(self):
        text = upgrade_library("$old = 0\nFUNC 投票重置\n    $old = 0\nENDFUNC\n")
        for strict, expected in [(0, 0), (1, 1)]:
            replay = CommonReplay(source=text)
            replay.call("共同区设置严格模式", strict)
            replay.submit([(40000, 1500)])
            replay.call("投票重置")
            self.assertEqual(replay.v["C_轮数"], expected)
            replay.call("共同区重置")
            self.assertEqual(replay.v["C_轮数"], 0)

    def test_unrelated_script_is_not_upgraded(self):
        self.assertEqual(upgrade_starter_calibration("A\nWAIT 1500\n"), "A\nWAIT 1500\n")


if __name__ == "__main__":
    unittest.main()
