import unittest

from run_auto_rng_gui import (
    AutoRngApp,
    MODE_TAB_ORDER,
    iv_ranges_for_preset,
    parse_iv_ranges,
    parse_sid_effort_values,
    parse_sid_species,
    preferred_detected_port,
)


class GuiIvInputTests(unittest.TestCase):
    def test_requested_tab_order(self):
        self.assertEqual(
            MODE_TAB_ORDER,
            ("SID 查找", "TID 乱数", "野生 / 静态", "孵蛋（测试）"),
        )

    def test_manual_ranges_are_parsed_in_stat_order(self):
        minimums, maximums = parse_iv_ranges(
            ["1", "2", "3", "4", "5", "6"],
            ["11", "12", "13", "14", "15", "16"],
        )
        self.assertEqual(minimums, (1, 2, 3, 4, 5, 6))
        self.assertEqual(maximums, (11, 12, 13, 14, 15, 16))

    def test_ten_lines_presets_match_exact_iv_ranges(self):
        expected = {
            "不限": ((0, 31),) * 6,
            "6V": ((31, 31),) * 6,
            "0A": (
                (31, 31), (0, 0), (31, 31),
                (31, 31), (31, 31), (31, 31),
            ),
            "0S": (
                (31, 31), (31, 31), (31, 31),
                (31, 31), (31, 31), (0, 0),
            ),
            "0A0S": (
                (31, 31), (0, 0), (31, 31),
                (31, 31), (31, 31), (0, 0),
            ),
        }
        for preset, ranges in expected.items():
            with self.subTest(preset=preset):
                self.assertEqual(iv_ranges_for_preset(preset), ranges)

    def test_invalid_values_report_the_affected_stat(self):
        cases = (
            (["", "0", "0", "0", "0", "0"], ["31"] * 6, "HP"),
            (["0"] * 6, ["31", "x", "31", "31", "31", "31"], "攻击"),
            (["0", "0", "-1", "0", "0", "0"], ["31"] * 6, "防御"),
            (["0"] * 6, ["31", "31", "31", "32", "31", "31"], "特攻"),
            (["0", "0", "0", "0", "20", "0"], ["31", "31", "31", "31", "10", "31"], "特防"),
        )
        for minimums, maximums, stat in cases:
            with self.subTest(stat=stat):
                with self.assertRaisesRegex(ValueError, stat):
                    parse_iv_ranges(minimums, maximums)

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(ValueError):
            iv_ranges_for_preset("5V")

    def test_detected_port_keeps_valid_selection_or_uses_lowest_number(self):
        self.assertEqual(preferred_detected_port({"COM12", "COM4"}, "COM12"), "COM12")
        self.assertEqual(preferred_detected_port({"COM12", "COM4"}, "COM22"), "COM4")
        self.assertIsNone(preferred_detected_port(set(), "COM22"))

    def test_sid_effort_values_require_six_valid_stats(self):
        self.assertEqual(
            parse_sid_effort_values(("0", "4", "8", "12", "16", "20"), 1),
            (0, 4, 8, 12, 16, 20),
        )
        with self.assertRaisesRegex(ValueError, "第2位.*六项"):
            parse_sid_effort_values(("0", "0"), 2)
        with self.assertRaisesRegex(ValueError, "总和"):
            parse_sid_effort_values(("255", "255", "255", "0", "0", "0"), 3)
        with self.assertRaisesRegex(ValueError, "第4位攻击"):
            parse_sid_effort_values(("0", "x", "0", "0", "0", "0"), 4)

    def test_sid_species_accepts_chinese_english_display_and_dex(self):
        self.assertEqual(parse_sid_species("皮卡丘", 1), 25)
        self.assertEqual(parse_sid_species("Pikachu", 1), 25)
        self.assertEqual(parse_sid_species("皮卡丘 (Pikachu)", 1), 25)
        self.assertEqual(parse_sid_species("25", 1), 25)
        self.assertEqual(parse_sid_species("大葱鸭", 1), 83)

    def test_sid_species_rejects_blank_and_unknown_names(self):
        with self.assertRaisesRegex(ValueError, "第2位"):
            parse_sid_species("", 2)
        with self.assertRaisesRegex(ValueError, "无法识别.*第3位"):
            parse_sid_species("不是宝可梦", 3)

    def test_sid_party_rows_follow_selected_shiny_count(self):
        class FakeVariable:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        class FakeWidget:
            def __init__(self):
                self.state = None

            def configure(self, *, state):
                self.state = state

        app = object.__new__(AutoRngApp)
        app.sid_count_var = FakeVariable("2")
        app.sid_party_row_widgets = [
            ((FakeWidget(), "normal"), (FakeWidget(), "readonly"))
            for _ in range(6)
        ]
        app._refresh_sid_party_rows()
        self.assertEqual(
            [[widget.state for widget, _ in row] for row in app.sid_party_row_widgets],
            [
                ["normal", "readonly"],
                ["normal", "readonly"],
                ["disabled", "disabled"],
                ["disabled", "disabled"],
                ["disabled", "disabled"],
                ["disabled", "disabled"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
