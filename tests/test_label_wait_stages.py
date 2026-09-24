import json
import re
import unittest
from pathlib import Path

from automation.easycon118 import (
    inspect_script_corpus,
    is_supported_runtime_script_sha256,
    is_supported_script_input_sha256,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = REPO_ROOT / "local_assets" / "easycon118"
SOURCE_CORPUS_SHA256 = "5ab831733be435433f436f078d9ac94fe1b1008aa814231033d9fcfb1b761f03"


class LabelWaitStageMaterializationTests(unittest.TestCase):
    def test_current_source_and_materialized_script_corpora_are_audited(self):
        self.assertTrue(is_supported_script_input_sha256(SOURCE_CORPUS_SHA256))
        scripts = inspect_script_corpus(ASSET_ROOT)
        self.assertTrue(is_supported_runtime_script_sha256(scripts["sha256"]))

        manifest = json.loads(
            (ASSET_ROOT / "asset_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["source_scripts"]["sha256"], SOURCE_CORPUS_SHA256)
        self.assertEqual(manifest["source_scripts"]["bytes"], 2053028)
        self.assertEqual(manifest["scripts"]["sha256"], scripts["sha256"])
        self.assertEqual(manifest["scripts"]["bytes"], scripts["bytes"])

    def test_main_and_ocr_stages_survive_materialization(self):
        main_stages = (
            "main.home_buffer",
            "main.jp.gender",
            "main.jp.nature",
            "main.jp.hp",
            "main.jp.atk",
            "main.jp.def",
            "main.jp.spa",
            "main.jp.spd",
            "main.jp.spe",
        )
        main_files = (
            ASSET_ROOT / "NS火叶全自动一键乱数2.0.ecs",
            ASSET_ROOT / "NS火叶全自动一键乱数2.0-时间轴.ecs",
        )
        for path in main_files:
            text = path.read_text(encoding="utf-8")
            for stage in main_stages:
                with self.subTest(file=path.name, stage=stage):
                    self.assertRegex(text, rf"FRLG_STAGE\|BEGIN\|{re.escape(stage)}\|")
                    self.assertRegex(text, rf"FRLG_STAGE\|END\|{re.escape(stage)}\|")
                    self.assertRegex(text, rf"FRLG_STAGE\|FAIL\|{re.escape(stage)}\|")

        function_name = "FUNC 读取并输出日版御三家识图结果(): INT"
        normalized_bodies = []
        for path in main_files:
            text = path.read_text(encoding="utf-8")
            start = text.index(function_name)
            end = text.index("\nENDFUNC", start) + len("\nENDFUNC")
            normalized_bodies.append(
                "\n".join(
                    line
                    for line in text[start:end].splitlines()
                    if "FRLG_STAGE|" not in line
                )
            )
        self.assertEqual(normalized_bodies[0], normalized_bodies[1])

        expected_by_file = {
            "lib/20_识图_抓捕对象名称识别.ecs": tuple(
                [f"wild.name.char{i:02d}" for i in range(1, 11)]
                + ["wild.unown.form"]
            ),
            "lib/21_识图_数据读取.ecs": tuple(
                f"wild.data.{field}"
                for field in (
                    "gender", "nature", "level", "hp", "atk", "def", "spa", "spd", "spe"
                )
            ),
            "lib/26_识图_候选数字.ecs": ("wild.data.candidate_range",),
        }
        for relative, stages in expected_by_file.items():
            text = (ASSET_ROOT / relative).read_text(encoding="utf-8")
            for stage in stages:
                with self.subTest(file=relative, stage=stage):
                    self.assertRegex(text, rf"FRLG_STAGE\|BEGIN\|{re.escape(stage)}\|")
                    self.assertRegex(text, rf"FRLG_STAGE\|END\|{re.escape(stage)}\|")
                    self.assertRegex(text, rf"FRLG_STAGE\|FAIL\|{re.escape(stage)}\|")


if __name__ == "__main__":
    unittest.main()
