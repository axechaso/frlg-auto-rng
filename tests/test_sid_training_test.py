from pathlib import Path
import json
import re
import tempfile
import unittest
import zipfile

from rng.ev_training import gen3_ev_yield
from tools.build_sid_training_test import (ARCHIVES, FOES, NATURES, STATS,
                                           archive_labels, build_project, data_and_functions,
                                           picker, sha)
from tools.verify_sid_training_test import verify_project

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "assets/sid_training_test/main.ecs.in").read_text(encoding="utf-8")
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aK1cAAAAASUVORK5CYII="


def il():
    return json.dumps({"name": "old", "ImgBase64": PNG, "searchMethod": 5,
                       "RangeX": 0, "RangeY": 147, "RangeWidth": 40, "RangeHeight": 70,
                       "TargetWidth": 1, "TargetHeight": 1}).encode()


class TrainingTestBuilderTests(unittest.TestCase):
    def test_two_english_variants_have_exact_reference_manifests_and_mode_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            common = root / "common"
            common.mkdir()
            originals = ["性格" + s for s in NATURES]
            originals += [f"LV_十位_{i}" for i in range(1, 10)]
            originals += [f"LV_个位_{i}" for i in range(10)] + ["LV_个位_空"]
            originals += [f"{s}_{p}位_{i}" for s in STATS for p in ("百", "十", "个")
                          for i in (range(1, 4) if p == "百" else range(10))]
            originals += [f"{dex:03d}_fixture_闪" for dex in FOES]
            for name in originals:
                (common / (name + ".IL")).write_bytes(il())
            controls = ["三代路闪HP检测", "三代通用菜单启动栏", "三代路闪闪光选项箭头",
                        "三代血量足够", "三代技能池", "获得经验",
                        "想学新技能", "尝试学新技能", "宝可梦进化"]
            sources = {name: (il(), "reference/ImgLabel/" + name + ".IL")
                       for name in controls + list(FOES.values())}
            before = {p.name: p.read_bytes() for p in common.iterdir()}
            for mode in (0, 1):
                output = root / f"en{mode}"
                manifest = build_project("en", mode, sources, common, output)
                text = (output / "main.ecs").read_text(encoding="utf-8")
                self.assertIn("$训练ROM语言 = 0", text)
                self.assertIn(f"$训练经验方式 = {mode}", text)
                self.assertIn(f"$训练队伍位置 = {mode + 1}", text)
                self.assertIn("$训练准备确认 = 0", text)
                self.assertIn("$训练只测试识图 = 1", text)
                self.assertIn("$训练最多战斗 = 1", text)
                self.assertNotIn("@@", text)
                refs = set(re.findall(r"@([\w\u4e00-\u9fff]+)", text))
                self.assertEqual(refs, set(manifest["labels"]))
                self.assertEqual(manifest["label_count"], len(refs))
                self.assertFalse(manifest["hardware_tested"])
                for name, info in manifest["labels"].items():
                    raw = (output / "ImgLabel" / (name + ".IL")).read_bytes()
                    payload = json.loads(raw)
                    self.assertEqual(sha(raw), info["sha256"])
                    self.assertEqual(payload["name"], name)
                    self.assertEqual(payload["ImgBase64"], PNG)
                    self.assertEqual(payload["searchMethod"], 5)
                    self.assertFalse(info["derived_range"])
                    self.assertIsNone(info["image_crop"])
                self.assertEqual(manifest["script_sha256"], sha(text.encode()))
                self.assertEqual(manifest["script_sha256"], sha((output / "main.ecs").read_bytes()))
                self.assertNotIn(b"\r\n", (output / "main.ecs").read_bytes())
                self.assertTrue(verify_project(output)["manifest_verified"])
                with self.assertRaises(FileExistsError):
                    build_project("en", mode, sources, common, output)
            self.assertEqual(before, {p.name: p.read_bytes() for p in common.iterdir()})

    def test_reference_zip_selection_uses_imglabel_not_staging_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixture.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("pkg/new icons/label.IL", b"staging")
                archive.writestr("pkg/ImgLabel/label.IL", b"actual")
            labels = archive_labels(path, sha(path.read_bytes()))
            self.assertEqual(labels["label"], (b"actual", "pkg/ImgLabel/label.IL"))
            with self.assertRaisesRegex(ValueError, "changed"):
                archive_labels(path, "0" * 64)

    def test_zip_traversal_and_ambiguous_label_roots_rejected(self):
        for entries in (("../ImgLabel/x.IL",), ("a/ImgLabel/x.IL", "b/ImgLabel/x.IL")):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "bad.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    for name in entries:
                        archive.writestr(name, il())
                with self.assertRaises(ValueError):
                    archive_labels(path, sha(path.read_bytes()))

    def test_386_ev_vectors_match_bundled_table(self):
        data, funcs = data_and_functions()
        for index, stat in enumerate(STATS):
            match = re.search(rf"\$训练产出{stat} = (\[.*\])", data)
            values = json.loads(match[1])
            self.assertEqual(values, [0] + [gen3_ev_yield(i)[index] for i in range(1, 387)])
        self.assertIn("$dex == 386 and $训练游戏 == 1", funcs)

    def test_pick_highest_and_reject_near_ties(self):
        code = picker("test", [("a", 1), ("b", 2)])
        self.assertLess(code.index("$candidate = @b"), code.index("IF $best <"))
        self.assertIn("$best - $second < $训练区分差值", code)
        self.assertIn("RETURN -2", code)

    def test_multiple_photos_of_same_digit_compete_as_one_value(self):
        code = picker("test", [("digit1a", 1), ("digit1b", 1), ("digit2", 2)])
        self.assertEqual(code.count("IF $score > $best"), 2)
        self.assertLess(code.index("@digit1b"), code.index("IF $score > $best"))

    def test_deferred_language_or_invalid_mode_rejected_before_creating_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for language, mode in (("jp", 0), ("en", 2)):
                output = root / f"{language}{mode}"
                with self.assertRaisesRegex(ValueError, "only English ROM"):
                    build_project(language, mode, {}, root, output)
                self.assertFalse(output.exists())

    def test_no_home_restart_save_or_unbounded_loop(self):
        operations = [line.strip() for line in TEMPLATE.splitlines() if not line.lstrip().startswith("#")]
        self.assertFalse(any(re.match(r"(?:HOME|CAPTURE|ALERT|WHILE)\b", line) for line in operations))
        self.assertNotIn("关闭游戏()", TEMPLATE)
        self.assertIn("$训练最多战斗 > 10", TEMPLATE)
        self.assertIn("FOR $训练检测次数 = 1 TO 200", TEMPLATE)

    def test_original_zero_pp_label_is_a_stop_condition_not_a_readiness_signal(self):
        self.assertIn("IF @TRAIN_空PP >= 80 or @TRAIN_战斗菜单 >= 80", TEMPLATE)
        self.assertNotIn("@TRAIN_技能PP", TEMPLATE)

    def test_commit_only_after_battle_receipts_and_before_after_level_observation(self):
        self.assertLess(TEMPLATE.index("$训练动作结果 = 训练进行战斗()"), TEMPLATE.index("CALL 训练累计击倒EV"))
        section = TEMPLATE[TEMPLATE.index("$训练动作结果 = 训练进行战斗()"):TEMPLATE.index("FUNC 训练返回场景")]
        self.assertLess(section.index("IF $训练动作结果 != 1"), section.index("CALL 训练累计击倒EV"))
        self.assertLess(section.index("训练读取稳定身份()"), section.index("IF $训练等级 > $训练登记等级"))
        self.assertLess(section.index("IF $训练等级 > $训练登记等级"), section.index("训练读取稳定观测()"))
        self.assertEqual(section.count("CALL 训练累计击倒EV"), 1)

    def test_archive_registration_and_precondition_documentation(self):
        self.assertEqual(set(ARCHIVES), {"en"})
        readme = (ROOT / "assets/sid_training_test/使用说明.md").read_text(encoding="utf-8")
        for text in ("队伍只放两只", "第1位不能100级", "没有自动读取持有道具", "不自动保存", "只测试识图", "1–99级"):
            self.assertIn(text, readme)
        self.assertIn("$训练经验方式 == 1 and $训练强制锻炼器 == 1", TEMPLATE)
        self.assertIn("$训练原生顺序 = [0,1,2,5,3,4]", TEMPLATE)


if __name__ == "__main__":
    unittest.main()
