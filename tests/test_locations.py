import json
import unittest
from collections import Counter
from pathlib import Path

from assets.game_text import (
    LOCATION_EN_TO_ZH, location_to_en, location_to_zh,
)
from rng.sid_reverse_workflow import resolve_wild_location
from rng.tenlines_utils import FRLG_MAP_TO_LOCATION, get_encounter, load_frlg_encounters


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = json.loads((ROOT / "tests/fixtures/tenlines-frlg-locations.json").read_text(encoding="utf-8"))


class LocationCatalogTests(unittest.TestCase):
    def test_all_105_names_match_pinned_ten_lines_resources(self):
        expected = {en: zh for _location_id, en, zh in REFERENCE["locations"]}
        self.assertEqual(len(expected), 105)
        self.assertEqual(LOCATION_EN_TO_ZH, expected)
        self.assertEqual(len(set(expected.values())), 105)
        for en, zh in expected.items():
            with self.subTest(location=en):
                self.assertEqual(location_to_en(zh), en)
                self.assertEqual(location_to_en("  " + en.lower() + "  "), en)
                self.assertEqual(location_to_zh(en), zh)

    def test_every_raw_encounter_map_has_a_canonical_name(self):
        raw = json.loads((ROOT / "rng/resources/EncounterTables/Gen3/frlg/wild_encounters.json").read_text())
        for entry in raw:
            with self.subTest(map=entry["map"]):
                self.assertIn(entry["map"], FRLG_MAP_TO_LOCATION)
                self.assertIn(FRLG_MAP_TO_LOCATION[entry["map"]], LOCATION_EN_TO_ZH)

    def test_both_versions_expose_all_canonical_names_without_extra_rooms(self):
        for game in ("fr_nx", "lg_nx", "fr_nx2", "lg_nx2"):
            with self.subTest(game=game):
                catalog = load_frlg_encounters(game)
                self.assertEqual({loc for loc, _cat in catalog}, set(LOCATION_EN_TO_ZH))
                self.assertEqual(len(catalog), 296)
                self.assertFalse(any("Lost Cave Room" in loc for loc, _cat in catalog))

    def test_grouped_maps_keep_one_complete_slot_table_not_concatenated_slots(self):
        expected = {"Grass": 12, "Surfing": 5, "OldRod": 2, "GoodRod": 3, "SuperRod": 5, "RockSmash": 5}
        for game in ("fr_nx", "lg_nx"):
            for (loc, category), data in load_frlg_encounters(game).items():
                with self.subTest(game=game, location=loc, category=category):
                    self.assertEqual(len(data["slots"]), expected[category])
            self.assertEqual(
                Counter(cat for _loc, cat in load_frlg_encounters(game)),
                {"Grass": 86, "Surfing": 49, "OldRod": 49, "GoodRod": 49, "SuperRod": 49, "RockSmash": 14},
            )

    def test_grouped_raw_maps_have_identical_slots_even_when_rates_differ(self):
        raw = json.loads((ROOT / "rng/resources/EncounterTables/Gen3/frlg/wild_encounters.json").read_text())
        for version in ("FireRed", "LeafGreen"):
            groups = {}
            duplicates = 0
            for entry in raw:
                base = entry.get("base_label", "")
                if version not in base:
                    continue
                if entry["map"] == "MAP_SIX_ISLAND_ALTERING_CAVE" and base != f"sSixIslandAlteringCave_{version}":
                    continue
                for kind in ("land_mons", "water_mons", "fishing_mons", "rock_smash_mons"):
                    section = entry.get(kind)
                    if not section or not section.get("encounter_rate", 0):
                        continue
                    key = FRLG_MAP_TO_LOCATION[entry["map"]], kind
                    if key in groups:
                        duplicates += 1
                        with self.subTest(version=version, group=key, source=base):
                            self.assertEqual(section["mons"], groups[key])
                    else:
                        groups[key] = section["mons"]
            self.assertEqual(duplicates, 21)

    def test_lost_cave_ordinary_and_item_rooms_keep_different_encounters(self):
        for game in ("fr_nx", "lg_nx"):
            ordinary = get_encounter("不归之穴", "Grass", game)
            items = get_encounter("不归之穴（有物品的房间）", "Grass", game)
            self.assertNotEqual(ordinary["slots"], items["slots"])

    def test_old_room_names_are_rejected_not_remapped(self):
        for room in range(1, 15):
            for old in (f"不归之穴 房间{room}", f"Five Island Lost Cave Room {room}"):
                with self.subTest(old=old):
                    self.assertEqual(location_to_en(old), old)
                    self.assertIsNone(get_encounter(old, "Grass"))
                    with self.assertRaisesRegex(ValueError, "unknown TenLines"):
                        resolve_wild_location(old, "fr_nx")

    def test_seven_chambers_are_distinct_and_general_ruins_do_not_mean_unown(self):
        chambers = [en for en in LOCATION_EN_TO_ZH if en.endswith(" Chamber")]
        self.assertEqual(len(chambers), 7)
        for name in chambers:
            self.assertEqual(resolve_wild_location(location_to_zh(name), "fr_nx"), name)
            self.assertEqual({slot["species"] for slot in get_encounter(name, "Grass")["slots"]}, {201})
        self.assertIsNone(get_encounter("Seven Island Tanoby Ruins", "Grass"))
        self.assertIsNotNone(get_encounter("Seven Island Tanoby Ruins", "Surfing"))

    def test_altering_cave_keeps_default_zubat_not_concatenated_alternatives(self):
        for game in ("fr_nx", "lg_nx"):
            self.assertEqual({slot["species"] for slot in get_encounter("Six Island Altering Cave", "Grass", game)["slots"]}, {41})

    def test_unknown_names_are_not_guessed(self):
        self.assertEqual(location_to_en("不存在的地点"), "不存在的地点")
        self.assertIsNone(get_encounter("不存在的地点", "Grass"))
        with self.assertRaisesRegex(ValueError, "unknown TenLines"):
            resolve_wild_location("不存在的地点", "fr_nx")


if __name__ == "__main__":
    unittest.main()
