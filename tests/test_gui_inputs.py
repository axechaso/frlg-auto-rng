import unittest

from run_auto_rng_gui import iv_ranges_for_preset, parse_iv_ranges


class GuiIvInputTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
