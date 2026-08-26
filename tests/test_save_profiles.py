import json
import tempfile
import unittest
from pathlib import Path

from save_profiles import SaveProfile, SaveProfileStore


class SaveProfileTests(unittest.TestCase):
    def test_profile_validates_frlg_identity(self):
        profile = SaveProfile.create("主存档", "火红", "00001", "65535", "2")
        self.assertEqual(profile.game, "火红")
        self.assertEqual(profile.tid, 1)
        self.assertEqual(profile.sid, 65535)
        self.assertEqual(profile.switch_name, "Switch 2")

        invalid = (
            (("", "火红", 1, 2, 1), "名称"),
            (("A", "红宝石", 1, 2, 1), "版本"),
            (("A", "火红", -1, 2, 1), "TID"),
            (("A", "火红", 1, 65536, 1), "SID"),
            (("A", "火红", 1, 2, 3), "主机"),
        )
        for arguments, message in invalid:
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ValueError, message):
                    SaveProfile.create(*arguments)

    def test_store_round_trips_selection_edit_duplicate_and_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "save_profiles.json"
            store = SaveProfileStore(path)
            first = store.add("主存档", "火红", 12345, 54321, 1)
            second = store.duplicate(first.profile_id)
            self.assertEqual(second.name, "主存档 副本")
            updated = store.update(
                second.profile_id, "叶绿存档", "叶绿", 7, 8, 2
            )
            self.assertEqual(updated.switch_name, "Switch 2")
            store.select(first.profile_id)

            reloaded = SaveProfileStore(path)
            reloaded.load()
            self.assertEqual(
                [profile.name for profile in reloaded.profiles],
                ["主存档", "叶绿存档"],
            )
            self.assertEqual(reloaded.selected_profile_id, first.profile_id)
            reloaded.delete(first.profile_id)
            self.assertIsNone(reloaded.selected_profile_id)

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(payload["profiles"][0]["name"], "叶绿存档")

    def test_store_rejects_duplicate_names_and_invalid_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "save_profiles.json"
            store = SaveProfileStore(path)
            store.add("主存档", "火红", 1, 2, 1)
            with self.assertRaisesRegex(ValueError, "已经存在"):
                store.add("主存档", "叶绿", 3, 4, 2)

            path.write_text("{bad json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "无法读取"):
                SaveProfileStore(path).load()

            path.write_text(
                json.dumps({"version": 1, "profiles": [{"name": "缺少ID"}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "ID"):
                SaveProfileStore(path).load()

    def test_failed_write_rolls_back_memory_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SaveProfileStore(Path(temp_dir) / "save_profiles.json")

            def fail_write():
                raise OSError("disk full")

            store._write = fail_write
            with self.assertRaisesRegex(OSError, "disk full"):
                store.add("主存档", "火红", 1, 2, 1)
            self.assertEqual(store.profiles, [])
            self.assertIsNone(store.selected_profile_id)


if __name__ == "__main__":
    unittest.main()
