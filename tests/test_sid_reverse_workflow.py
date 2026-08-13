import unittest

from rng.sid_reverse_workflow import (
    SIDObservation,
    analyze_observed_pokemon,
    parse_sid_reverse_log,
    resolve_wild_location,
)
from rng.tenlines import METHOD_2


class SIDReverseWorkflowTests(unittest.TestCase):
    def test_parse_structured_easycon_log(self):
        text = """
        [12:00:00] SIDREV|META|TID=12345|COUNT=2
        [12:00:01] SIDREV|OBS|MON=1|SOURCE=WILD|LOCATION=Route 1|EVHP=252|EVATK=252|EVDEF=0|EVSPA=0|EVSPD=0|EVSPE=0|DEX=16|NATURE=0|GENDER=0|LEVEL=100|HP=294|ATK=197|DEF=116|SPA=106|SPD=106|SPE=148
        """
        tid, observations = parse_sid_reverse_log(text)
        self.assertEqual(tid, 12345)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].stats, (294, 197, 116, 106, 106, 148))
        self.assertEqual(observations[0].source_type, "WILD")
        self.assertEqual(observations[0].location, "Route 1")
        self.assertEqual(observations[0].effort_values, (252, 252, 0, 0, 0, 0))

    def test_parse_strips_easycon_ansi_reset_after_last_stat(self):
        text = (
            "\x1b[90m[12:00:01]\x1b[0m "
            "SIDREV|OBS|MON=1|DEX=18|NATURE=13|GENDER=0|LEVEL=47|"
            "HP=136|ATK=123|DEF=85|SPA=74|SPD=74|SPE=146\x1b[0m"
        )
        _, observations = parse_sid_reverse_log(text)
        self.assertEqual(observations[0].stats, (136, 123, 85, 74, 74, 146))
        self.assertEqual(observations[0].gender, 0)

    def test_rejects_explicit_failed_gender_marker(self):
        text = (
            "SIDREV|OBS|MON=1|DEX=18|NATURE=13|GENDER=-1|LEVEL=47|"
            "HP=136|ATK=123|DEF=85|SPA=74|SPD=74|SPE=146"
        )
        with self.assertRaisesRegex(ValueError, "gender"):
            parse_sid_reverse_log(text)

    def test_ocr_name_normalization_handles_punctuation(self):
        text = "SIDREV|OBS|MON=1|DEX=0|NAME=MR. MIME-|NATURE=0|LEVEL=50|HP=1|ATK=1|DEF=1|SPA=1|SPD=1|SPE=1"
        _, observations = parse_sid_reverse_log(text)
        self.assertEqual(observations[0].species_id, 122)

    def test_level_100_observation_recovers_pokefinder_vector(self):
        observation = SIDObservation(
            pokemon_index=1,
            species_id=1,
            nature=0,
            level=100,
            stats=(231, 134, 134, 135, 166, 126),
            gender=None,
        )
        result = analyze_observed_pokemon((observation,))
        self.assertEqual(result.iv_min, (31, 31, 31, 0, 31, 31))
        self.assertEqual(result.iv_max, result.iv_min)
        self.assertTrue(
            any(
                item.method == METHOD_2 and item.pid == 45092875
                for item in result.candidates
            )
        )

    def test_effort_values_are_applied_to_gen3_stat_formula(self):
        observation = SIDObservation(
            pokemon_index=1,
            species_id=1,
            nature=0,
            level=100,
            stats=(294, 197, 134, 135, 166, 126),
            effort_values=(252, 252, 0, 0, 0, 0),
        )
        result = analyze_observed_pokemon((observation,))
        self.assertEqual(result.iv_min, (31, 31, 31, 0, 31, 31))
        self.assertEqual(result.iv_max, result.iv_min)

    def test_wild_source_validates_tenlines_location_and_species(self):
        self.assertEqual(
            resolve_wild_location("狩猎地带（入口）", "fr_nx"),
            "Safari Zone Center",
        )
        observation = SIDObservation(
            pokemon_index=1,
            species_id=1,
            nature=0,
            level=100,
            stats=(231, 134, 134, 135, 166, 126),
            source_type="WILD",
            location="Route 1",
        )
        with self.assertRaisesRegex(ValueError, "not present"):
            analyze_observed_pokemon((observation,), game="fr_nx")


if __name__ == "__main__":
    unittest.main()
