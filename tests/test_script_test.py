import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automation import script_test
from automation import easycon118


class DirectScriptTestTests(unittest.TestCase):
    def _project(self, root: Path, *, with_label: bool = True) -> Path:
        main = root / "main.ecs"
        main.write_text(
            "$分数 = @火红BAG\nPRINT $分数\n# @注释标签不应被加载\n",
            encoding="utf-8",
        )
        lib_dir = root / "lib"
        lib_dir.mkdir()
        (lib_dir / "extra.ecs").write_text(
            "$箭头 = @三代菜单栏\n",
            encoding="utf-8",
        )
        if with_label:
            label_dir = root / "ImgLabel"
            label_dir.mkdir()
            (label_dir / "火红BAG.IL").write_bytes(b"bag")
            (label_dir / "三代菜单栏.IL").write_bytes(b"cursor")
        return main

    def test_inspects_main_and_sibling_lib_label_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            main = self._project(Path(temporary))
            self.assertEqual(
                script_test.inspect_script_label_references(main),
                ("三代菜单栏", "火红BAG"),
            )

    def test_resolves_and_identifies_formal_and_timeline_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            formal = source / script_test.STANDARD_TEMPLATE_NAME
            timeline = source / script_test.EGG_TEMPLATE_NAME
            formal.write_text("PRINT 1\n", encoding="utf-8")
            timeline.write_text("PRINT 2\n", encoding="utf-8")

            self.assertEqual(
                script_test.resolve_script_test_entry(
                    source,
                    script_test.SCRIPT_TEST_ENTRY_FORMAL,
                ),
                formal.resolve(),
            )
            self.assertEqual(
                script_test.resolve_script_test_entry(
                    source,
                    script_test.SCRIPT_TEST_ENTRY_TIMELINE,
                ),
                timeline.resolve(),
            )
            self.assertEqual(
                script_test.identify_script_test_entry(source, formal),
                script_test.SCRIPT_TEST_ENTRY_FORMAL,
            )
            self.assertEqual(
                script_test.identify_script_test_entry(source, timeline),
                script_test.SCRIPT_TEST_ENTRY_TIMELINE,
            )
            self.assertEqual(
                script_test.identify_script_test_entry(source, source / "probe.ecs"),
                script_test.SCRIPT_TEST_ENTRY_CUSTOM,
            )

    def test_standard_entry_resolution_reports_missing_and_custom_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            with self.assertRaisesRegex(FileNotFoundError, "正式版脚本"):
                script_test.resolve_script_test_entry(
                    source,
                    script_test.SCRIPT_TEST_ENTRY_FORMAL,
                )
            with self.assertRaisesRegex(ValueError, "自选 ECS"):
                script_test.resolve_script_test_entry(
                    source,
                    script_test.SCRIPT_TEST_ENTRY_CUSTOM,
                )
            with self.assertRaisesRegex(ValueError, "未知"):
                script_test.resolve_script_test_entry(source, "不存在的入口")


    def test_extension_labels_fall_back_to_bundled_local_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            broken_extensions = root / "assets"
            broken_extensions.mkdir()
            fallback_labels = root / "local_assets" / "ImgLabel"
            fallback_labels.mkdir(parents=True)
            output_labels = root / "output" / "ImgLabel"
            output_labels.mkdir(parents=True)
            for name in easycon118.EASYCON118_EXTENSION_LABEL_NAMES:
                (fallback_labels / name).write_bytes(name.encode("utf-8"))

            with mock.patch.object(
                easycon118,
                "EASYCON118_EXTENSION_LABEL_DIR",
                broken_extensions,
            ), mock.patch.object(
                easycon118,
                "EASYCON118_LOCAL_LABEL_DIR",
                fallback_labels,
            ):
                easycon118.copy_easycon118_extension_labels(output_labels)

            self.assertEqual(
                sorted(path.name for path in output_labels.iterdir()),
                sorted(easycon118.EASYCON118_EXTENSION_LABEL_NAMES),
            )


if __name__ == "__main__":
    unittest.main()
