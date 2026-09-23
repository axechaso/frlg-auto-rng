from pathlib import Path
import unittest


class WildRoamerRetryTests(unittest.TestCase):
    def test_bundled_wild_roamer_escape_restarts_instead_of_stopping(self):
        source_dir = Path(__file__).resolve().parents[1] / "local_assets" / "easycon118"
        template_paths = tuple(
            source_dir / filename
            for filename in (
                "NS火叶全自动一键乱数2.0.ecs",
                "NS火叶全自动一键乱数2.0-时间轴.ecs",
            )
        )
        if not all(path.is_file() for path in template_paths):
            self.skipTest("requires the imported 2.0 runtime")
        for template_path in template_paths:
            template = template_path.read_text(encoding="utf-8")
            body = template.split("FUNC 执行RNG启动与目标获取", 1)[1].split(
                "ENDFUNC", 1
            )[0]
            retry = (
                "ELIF $执行目标获取结果 == 2\n"
                "            # 普通野生偶遇游走宝可梦会直接逃跑；本轮没有可反查样本。\n"
                "            PRINT 目标在抓捕前逃跑，本轮作废并自动重启\n"
                "            RETURN 0"
            )
            self.assertIn(retry, body)
            self.assertLess(
                body.index(retry), body.index("目标获取失败: 未知目标获取返回值")
            )


if __name__ == "__main__":
    unittest.main()
