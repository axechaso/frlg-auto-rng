import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "assets" / "easycon118_extensions" / "egg_surf_menu_probe.ecs"


class EggSurfMenuProbeTests(unittest.TestCase):
    def test_probe_compares_cursor_and_stable_bag_label_without_navigation(self):
        source = PROBE_PATH.read_text(encoding="utf-8")

        self.assertIn("@三代菜单栏", source)
        self.assertIn("@火红BAG", source)
        self.assertIn("SURF_MENU|SAMPLE", source)
        self.assertIn("SURF_MENU|SUMMARY", source)
        probe = source.split("PRINT 【菜单探测】", 1)[1]
        for command in ("DOWN", "UP", "LEFT", "RIGHT", "LS "):
            self.assertNotIn(f"\n    {command}", probe)
        self.assertNotIn("\n    A\n", probe)
        self.assertEqual(probe.count("\n    X\n"), 1)
        self.assertLess(
            probe.index("@火红BAG"),
            probe.index("$测试_BAG命中次数 += 1"),
        )


if __name__ == "__main__":
    unittest.main()
