import unittest

from automation.sid_reverse118 import SIDReverseRunRequest, configure_sid_reverse_template


class SIDReverse118Tests(unittest.TestCase):
    def test_configures_only_declared_inputs(self):
        template = """$SID反查TID = 1
$SID反查队内闪光数量 = 2
$SID反查每只最多糖果 = 3
$SID反查识图阈值 = 80
$SID反查队伍起始位置 = 1
$SID反查图鉴编号覆盖 = [0,0,0,0,0,0]
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
                source_types=(1, 0, 0, 0, 0, 0),
            ).validate()


if __name__ == "__main__":
    unittest.main()
