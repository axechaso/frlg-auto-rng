import importlib.util
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class LocationPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["location-tests", "-platform", "offscreen"])

    def setUp(self):
        from pyside_app.services import AppPaths
        from pyside_app.window import FrlgWindow
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.window = FrlgWindow(paths=AppPaths(user=root, output=root / "runtime"), auto_detect=False)
        self.window.fields["wild_tid"].setText("12345")
        self.window.fields["wild_sid"].setText("54321")
        self.combo = self.window.fields["wild_location"]

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def matches(self, query):
        completer = self.combo.completer()
        completer.setCompletionPrefix(query)
        model = completer.completionModel()
        return [model.index(row, 0).data() for row in range(model.rowCount())]

    def test_chinese_name_sort_and_natural_road_numbers(self):
        from pyside_app.location_picker import sorted_location_items
        from rng.tenlines_utils import load_frlg_encounters
        items = [(self.combo.itemText(i), self.combo.itemData(i)) for i in range(self.combo.count())]
        locations = {loc for loc, cat in load_frlg_encounters() if cat == "Grass"}
        self.assertEqual(items, sorted_location_items(locations))
        roads = [name for _label, name in items if name.startswith("Route ")]
        self.assertEqual(roads, sorted(roads, key=lambda name: int(name.split()[1])))
        names = [label for label, _name in items]
        self.assertLess(names.index("不归之穴"), names.index("常青森林"))
        self.assertLess(names.index("常青森林"), names.index("月见山1F"))

    def test_contains_search_matches_chinese_and_english_but_not_old_room_names(self):
        self.assertEqual(set(self.matches("不归")), {"不归之穴", "不归之穴（有物品的房间）"})
        self.assertEqual(set(self.matches("lost CAVE")), {"不归之穴", "不归之穴（有物品的房间）"})
        self.assertEqual(self.matches("Room 14"), [])
        self.assertEqual(self.matches("不存在的地点"), [])

    def test_native_typing_and_completion_select_the_correct_canonical_data(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.window.select_page("wild")
        self.window.show()
        self.app.processEvents()
        edit = self.combo.lineEdit()
        edit.setFocus()
        edit.selectAll()
        QTest.keyClicks(edit, "Lost Cave Item")
        self.app.processEvents()
        self.assertEqual(self.combo.completer().completionModel().rowCount(), 1)
        # Popup completion grabs real keyboard input. QTest sends directly to
        # its target widget, so navigate the visible popup, not the line edit.
        popup = self.combo.completer().popup()
        self.assertTrue(popup.isVisible())
        QTest.keyClick(popup, Qt.Key.Key_Down)
        QTest.keyClick(popup, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.combo.currentText(), "不归之穴（有物品的房间）")
        self.assertEqual(self.combo.currentData(), "Five Island Lost Cave Item Room")
        self.assertEqual(self.window.collect_inputs().request.location, "Five Island Lost Cave Item Room")
        self.assertGreater(self.window.fields["wild_species"].count(), 0)

    def test_pending_or_unknown_search_rejects_old_selected_location(self):
        from pyside_app.location_picker import selected_location
        previous_count = self.combo.count()
        self.combo.setEditText("不归")
        self.assertIsNone(selected_location(self.combo))
        self.assertEqual(self.window.fields["wild_species"].count(), 0)
        with self.assertRaisesRegex(ValueError, "地点"):
            self.window.collect_inputs()
        self.combo.setEditText("不存在的地点")
        self.combo.lineEdit().editingFinished.emit()
        self.assertEqual(self.combo.count(), previous_count)
        self.assertIsNone(selected_location(self.combo))
        self.assertEqual(self.combo.currentText(), "不存在的地点")

    def test_exact_canonical_english_can_be_committed_without_insert(self):
        count = self.combo.count()
        self.combo.setEditText("five island lost cave item room")
        self.combo.lineEdit().editingFinished.emit()
        self.assertEqual(self.combo.currentText(), "不归之穴（有物品的房间）")
        self.assertEqual(self.combo.currentData(), "Five Island Lost Cave Item Room")
        self.assertEqual(self.combo.count(), count)

    def test_old_room_text_does_not_use_current_or_first_location(self):
        count = self.combo.count()
        self.combo.setEditText("不归之穴 房间14")
        self.combo.lineEdit().editingFinished.emit()
        with self.assertRaisesRegex(ValueError, "地点"):
            self.window.collect_inputs()
        self.assertEqual(self.combo.currentText(), "不归之穴 房间14")
        self.assertEqual(self.combo.count(), count)

    def test_repopulate_preserves_valid_selection_and_updates_completion_model(self):
        self.combo.setCurrentIndex(self.combo.findData("Five Island Lost Cave"))
        self.window.fields["wild_game"].setCurrentIndex(1)
        self.assertEqual(self.combo.currentData(), "Five Island Lost Cave")
        self.assertEqual(len(self.matches("不归")), 2)
        categories = self.window.fields["wild_category"]
        categories.setCurrentIndex(categories.findData("Surfing"))
        self.assertEqual(self.matches("不归"), [])
        self.assertTrue(self.window.collect_inputs().request.location)
        self.window.fields["wild_method"].setCurrentIndex(1)
        self.assertEqual(self.combo.count(), 1)
        self.assertEqual(self.window.collect_inputs().request.category, "Starter")

    def test_invalid_text_invalidates_an_existing_prepared_plan(self):
        sentinel = object()
        self.window.prepared = sentinel
        self.combo.setEditText("不归")
        self.assertIsNone(self.window.prepared)

    def test_sid_location_edit_uses_same_sorted_search_without_touching_text(self):
        from PySide6.QtWidgets import QLineEdit
        from pyside_app.location_picker import configure_location_edit, sorted_location_items
        names = ["Seven Island Tanoby Ruins Monean Chamber", "Five Island Lost Cave Item Room", "Five Island Lost Cave"]
        edit = QLineEdit("旧输入")
        configure_location_edit(edit, names)
        completer = edit.completer()
        self.assertEqual(edit.text(), "旧输入")
        self.assertEqual([completer.model().index(i, 0).data() for i in range(3)], [label for label, _name in sorted_location_items(names)])
        completer.setCompletionPrefix("monean")
        self.assertEqual(completer.completionModel().rowCount(), 1)
        self.assertEqual(completer.pathFromIndex(completer.completionModel().index(0, 0)), "伊莱斯石室")
        configure_location_edit(edit, ["Viridian Forest"])
        self.assertEqual(edit.text(), "旧输入")
        self.assertEqual(edit.completer().model().rowCount(), 1)
        edit.deleteLater()


if __name__ == "__main__":
    unittest.main()
