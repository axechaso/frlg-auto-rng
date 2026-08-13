import unittest
from pathlib import Path

from automation.sid_reverse118 import SIDReverseRunRequest, configure_sid_reverse_template


class SIDReverse118Tests(unittest.TestCase):
    def test_template_uses_effort_aware_ranges_and_shiny_gender_label(self):
        root = Path(__file__).resolve().parents[1]
        template = (
            root
            / "assets"
            / "easycon118_extensions"
            / "NS火叶SID反查-采集测试.ecs"
        ).read_text(encoding="utf-8")
        self.assertIn("$SID反查闪公匹配 = @闪公图标", template)
        self.assertIn("SID反查识别闪光性别", template)
        self.assertNotIn("$SID反查当前等级 = 识别LV", template)
        self.assertIn(
            "$SID反查当前等级 = $SID反查当前初始等级 + $观测序号",
            template,
        )
        self.assertIn("识别候选范围能力值($能力项, $最小值, $最大值", template)
        for stat in ("HP", "ATK", "DEF", "SPA", "SPD", "SPE"):
            self.assertIn(f"$SID反查当前努力{stat}", template)
            self.assertIn(f"$SID反查{stat}最小", template)
            self.assertIn(f"$SID反查{stat}最大", template)
        self.assertIn(
            "计算非HP能力值($SID反查种族DEF, $SID反查当前努力DEF",
            template,
        )
        self.assertIn("SIDREV|LEGAL|MON=", template)

    def test_configures_only_declared_inputs(self):
        template = """$SID反查TID = 1
$SID反查队内闪光数量 = 2
$SID反查每只最多糖果 = 3
$SID反查识图阈值 = 80
$SID反查队伍起始位置 = 1
$SID反查图鉴编号覆盖 = [0,0,0,0,0,0]
$SID反查初始等级 = [1,1,1,1,1,1]
$SID反查种族HP覆盖 = [0,0,0,0,0,0]
$SID反查种族ATK覆盖 = [0,0,0,0,0,0]
$SID反查种族DEF覆盖 = [0,0,0,0,0,0]
$SID反查种族SPA覆盖 = [0,0,0,0,0,0]
$SID反查种族SPD覆盖 = [0,0,0,0,0,0]
$SID反查种族SPE覆盖 = [0,0,0,0,0,0]
$SID反查性别阈值覆盖 = [127,127,127,127,127,127]
$SID反查来源类型 = [0,0,0,0,0,0]
$SID反查相遇地点 = ["","","","","",""]
$SID反查努力HP = [0,0,0,0,0,0]
$SID反查努力ATK = [0,0,0,0,0,0]
$SID反查努力DEF = [0,0,0,0,0,0]
$SID反查努力SPA = [0,0,0,0,0,0]
$SID反查努力SPD = [0,0,0,0,0,0]
$SID反查努力SPE = [0,0,0,0,0,0]
"""
        request = SIDReverseRunRequest(
            tid=54321,
            party_count=1,
            start_slot=4,
            max_candies=7,
            recognition_threshold=86,
            dex_overrides=(0, 0, 0, 148, 0, 0),
            initial_levels=(1, 1, 1, 55, 1, 1),
            source_types=(0, 0, 0, 1, 0, 0),
            locations=("", "", "", "Safari Zone Center", "", ""),
            effort_values=(
                (0, 0, 0, 0, 0, 0),
                (0, 0, 0, 0, 0, 0),
                (0, 0, 0, 0, 0, 0),
                (252, 0, 0, 0, 0, 252),
                (0, 0, 0, 0, 0, 0),
                (0, 0, 0, 0, 0, 0),
            ),
        )
        configured = configure_sid_reverse_template(template, request)
        self.assertIn("$SID反查TID = 54321", configured)
        self.assertIn("$SID反查队伍起始位置 = 4", configured)
        self.assertIn("$SID反查图鉴编号覆盖 = [0,0,0,148,0,0]", configured)
        self.assertIn("$SID反查初始等级 = [1,1,1,55,1,1]", configured)
        self.assertIn("$SID反查种族HP覆盖 = [0,0,0,61,0,0]", configured)
        self.assertIn("$SID反查性别阈值覆盖 = [127,127,127,127,127,127]", configured)
        self.assertIn('$SID反查相遇地点 = ["","","","Safari Zone Center","",""]', configured)
        self.assertIn("$SID反查努力HP = [0,0,0,252,0,0]", configured)

    def test_rejects_party_range_past_slot_six(self):
        with self.assertRaisesRegex(ValueError, "第六个"):
            SIDReverseRunRequest(tid=1, party_count=2, start_slot=6).validate()

    def test_rejects_wild_slot_without_location(self):
        with self.assertRaisesRegex(ValueError, "相遇地点"):
            SIDReverseRunRequest(
                tid=1,
                party_count=1,
                dex_overrides=(25, 0, 0, 0, 0, 0),
                source_types=(1, 0, 0, 0, 0, 0),
            ).validate()

    def test_rejects_missing_species_for_active_slot(self):
        with self.assertRaisesRegex(ValueError, "图鉴编号"):
            SIDReverseRunRequest(tid=1, party_count=1).validate()

    def test_rejects_missing_initial_level_for_active_slot(self):
        with self.assertRaisesRegex(ValueError, "初始等级"):
            SIDReverseRunRequest(
                tid=1,
                party_count=1,
                dex_overrides=(18, 0, 0, 0, 0, 0),
                initial_levels=(0, 1, 1, 1, 1, 1),
            ).validate()

    def test_injects_complete_gen3_pidgeot_data(self):
        template = """$SID反查TID = 1
$SID反查队内闪光数量 = 1
$SID反查每只最多糖果 = 0
$SID反查识图阈值 = 85
$SID反查队伍起始位置 = 1
$SID反查图鉴编号覆盖 = [0,0,0,0,0,0]
$SID反查初始等级 = [1,1,1,1,1,1]
$SID反查种族HP覆盖 = [0,0,0,0,0,0]
$SID反查种族ATK覆盖 = [0,0,0,0,0,0]
$SID反查种族DEF覆盖 = [0,0,0,0,0,0]
$SID反查种族SPA覆盖 = [0,0,0,0,0,0]
$SID反查种族SPD覆盖 = [0,0,0,0,0,0]
$SID反查种族SPE覆盖 = [0,0,0,0,0,0]
$SID反查性别阈值覆盖 = [127,127,127,127,127,127]
$SID反查来源类型 = [0,0,0,0,0,0]
$SID反查相遇地点 = ["","","","","",""]
$SID反查努力HP = [0,0,0,0,0,0]
$SID反查努力ATK = [0,0,0,0,0,0]
$SID反查努力DEF = [0,0,0,0,0,0]
$SID反查努力SPA = [0,0,0,0,0,0]
$SID反查努力SPD = [0,0,0,0,0,0]
$SID反查努力SPE = [0,0,0,0,0,0]
"""
        configured = configure_sid_reverse_template(
            template,
            SIDReverseRunRequest(
                tid=17500,
                party_count=1,
                dex_overrides=(18, 0, 0, 0, 0, 0),
                initial_levels=(46, 1, 1, 1, 1, 1),
            ),
        )
        self.assertIn("$SID反查种族HP覆盖 = [83,0,0,0,0,0]", configured)
        self.assertIn("$SID反查种族SPE覆盖 = [91,0,0,0,0,0]", configured)
        self.assertIn("$SID反查性别阈值覆盖 = [127,127,127,127,127,127]", configured)


if __name__ == "__main__":
    unittest.main()
