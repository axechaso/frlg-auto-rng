import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "assets" / "easycon118_extensions" / "egg_surf_menu_probe.ecs"


class EggSurfMenuProbeTests(unittest.TestCase):
    def test_probe_waits_for_surf_label_before_single_x_without_navigation(self):
        source = PROBE_PATH.read_text(encoding="utf-8")

        self.assertIn("$测试_冲浪阈值 = 95", source)
        self.assertIn("@冲浪", source)
        self.assertNotIn("@三代菜单栏", source)
        self.assertNotIn("@火红BAG", source)
        self.assertIn("SURF_MENU|SURF_SAMPLE", source)
        self.assertIn("SURF_MENU|SURF_SUMMARY", source)
        probe = source.split("PRINT 【冲浪探测】", 1)[1]
        for command in ("DOWN", "UP", "LEFT", "RIGHT", "LS "):
            self.assertNotIn(f"\n    {command}", probe)
        self.assertNotIn("\n    A\n", probe)
        self.assertEqual(probe.count("\nX\n"), 1)
        self.assertLess(
            probe.index("@冲浪"),
            probe.index("\nX\n"),
        )


if __name__ == "__main__":
    unittest.main()
