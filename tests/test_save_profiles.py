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
        self.assertEqual(profile.language, "英文")
        self.assertEqual(profile.language_name, "美版")
        self.assertFalse(profile.mystery_gift_enabled)

        japanese = SaveProfile.create(
            "日版档", "火红", 1, 2, 1, language="日文"
        )
        self.assertEqual(japanese.language_name, "日版")

        with_gift = SaveProfile.create(
            "已开礼物", "叶绿", 1, 2, 1, mystery_gift_enabled=True
        )
        self.assertTrue(with_gift.mystery_gift_enabled)

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
        with self.assertRaisesRegex(ValueError, "布尔值"):
            SaveProfile.create("错误", "火红", 1, 2, 1, mystery_gift_enabled="false")

    def test_store_round_trips_selection_edit_duplicate_and_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "save_profiles.json"
            store = SaveProfileStore(path)
            first = store.add("主存档", "火红", 12345, 54321, 1,
                              mystery_gift_enabled=True)
            second = store.duplicate(first.profile_id)
            self.assertEqual(second.name, "主存档 副本")
            self.assertTrue(second.mystery_gift_enabled)
            updated = store.update(
                second.profile_id, "叶绿存档", "叶绿", 7, 8, 2,
                mystery_gift_enabled=False,
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
            self.assertEqual(reloaded.get(second.profile_id).language, "英文")
            reloaded.delete(first.profile_id)
            self.assertIsNone(reloaded.selected_profile_id)

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(payload["profiles"][0]["name"], "叶绿存档")

    def test_legacy_profile_without_language_defaults_to_english(self):
        payload = {
            "version": 1,
            "profiles": [
                {
                    "id": "legacy",
                    "name": "旧档",
                    "game": "火红",
                    "tid": 1,
                    "sid": 2,
                    "nx_model": 1,
                }
            ],
            "selected_profile_id": "legacy",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "save_profiles.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            store = SaveProfileStore(path)
            store.load()

        self.assertEqual(store.profiles[0].language, "英文")
        self.assertEqual(store.profiles[0].language_name, "美版")
        self.assertFalse(store.profiles[0].mystery_gift_enabled)

    def test_legacy_invalid_mystery_gift_is_rejected_without_rewriting(self):
        payload = {
            "version": 1,
            "profiles": [{"id": "legacy", "name": "旧档", "game": "火红",
                          "tid": 1, "sid": 2, "nx_model": 1,
                          "mystery_gift_enabled": "false"}],
            "selected_profile_id": "legacy",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "save_profiles.json"
            original = json.dumps(payload, ensure_ascii=False)
            path.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "布尔值"):
                SaveProfileStore(path).load()
            self.assertEqual(path.read_text(encoding="utf-8"), original)

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
