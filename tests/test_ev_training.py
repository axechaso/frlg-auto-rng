from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import zipfile

from rng.ev_training import (
    EVTrainingContext, EVTrainingLedger, award_defeat_evs, gen3_ev_yield, validate_evs,
)
from rng.sid_reverse_workflow import SIDObservation, analyze_observed_pokemon, parse_sid_reverse_log
from rng.tenlines_utils import IVsObservation, get_personal, iv_calculator
from run_sid_reverse import build_report
from tools.inspect_sid_training_packages import inspect_training_archive


ZERO = (0, 0, 0, 0, 0, 0)
IVS = (31, 31, 31, 0, 31, 31)
EV_KEYS = ("EVHP", "EVATK", "EVDEF", "EVSPA", "EVSPD", "EVSPE")
STATS = ("HP", "ATK", "DEF", "SPA", "SPD", "SPE")


def stat_values(level, effort_values=ZERO):
    base = get_personal(1)["stats"]
    return tuple(((2 * value + iv + ev // 4) * level // 100) +
                 (level + 10 if index == 0 else 5)
                 for index, (value, iv, ev) in enumerate(zip(base, IVS, effort_values)))


def ev_fields(values):
    return "|".join(f"{key}={value}" for key, value in zip(EV_KEYS, values))


def begin(mon=1, session="run1", level=95, evs=ZERO, extra=""):
    return (f"SIDTRAIN|BEGIN|V=1|SESSION={session}|MON={mon}|DEX=1|LEVEL={level}|"
            f"SOURCE=STATIC|LOCATION=|RECIPIENT=PARTICIPANT|MACHO_BRACE=0|POKERUS=0|{ev_fields(evs)}{extra}\n")


def defeat(sequence=1, species=16, mon=1, session="run1", extra=""):
    return (f"SIDTRAIN|DEFEAT|V=1|SESSION={session}|MON={mon}|SEQ={sequence}|FOE={species}|"
            f"RESULT=DEFEATED|XP_CONFIRMED=1|RECIPIENT_CONFIRMED=1{extra}\n")


def observation(level=95, sequence=0, evs=ZERO, mon=1, session="run1", stats=None):
    values = stats or stat_values(level, evs)
    return (f"SIDTRAIN|OBS|V=1|SESSION={session}|MON={mon}|SEQ={sequence}|DEX=1|"
            f"SOURCE=STATIC|LOCATION=|NATURE=0|LEVEL={level}|"
            f"RECALC={'INITIAL' if sequence == 0 else 'LEVEL_UP'}|{ev_fields(evs)}|" +
            "|".join(f"{key}={value}" for key, value in zip(STATS, values)) + "\n")


def training_log():
    lines = ["SIDREV|META|TID=17500\n", begin(), observation()]
    lines.extend(defeat(sequence) for sequence in range(1, 21))
    lines.append(observation(100, 20, (0, 0, 0, 0, 0, 20)))
    return "".join(lines)


class EVTrainingLedgerTests(unittest.TestCase):
    def test_yields_cover_all_386_species_and_known_archive_targets(self):
        for species in range(1, 387):
            self.assertIn(sum(gen3_ev_yield(species)), (1, 2, 3))
        for species, values in {
            10: (1, 0, 0, 0, 0, 0), 13: (0, 0, 0, 0, 0, 1),
            43: (0, 0, 0, 1, 0, 0), 51: (0, 0, 0, 0, 0, 2),
            57: (0, 2, 0, 0, 0, 0), 39: (2, 0, 0, 0, 0, 0),
            386: (0, 1, 0, 1, 0, 1),
        }.items():
            self.assertEqual(gen3_ev_yield(species), values)

    def test_unknown_species_is_rejected_instead_of_awarding_zero(self):
        for species in (0, 387, -1, True, 1.0):
            with self.assertRaises(ValueError):
                gen3_ev_yield(species)

    def test_macho_brace_and_recovered_pokerus_multiply_yield(self):
        self.assertEqual(award_defeat_evs(ZERO, 51, macho_brace=True, had_pokerus=True),
                         (0, 0, 0, 0, 0, 8))

    def test_caps_and_native_stat_order(self):
        self.assertEqual(award_defeat_evs((0, 0, 0, 0, 0, 254), 51), (0, 0, 0, 0, 0, 255))
        self.assertEqual(award_defeat_evs((255, 253, 0, 0, 0, 0), 386),
                         (255, 254, 0, 0, 0, 1))
        self.assertEqual(award_defeat_evs((255, 255, 0, 0, 0, 0), 16),
                         (255, 255, 0, 0, 0, 0))

    def test_ev_vectors_require_integer_values_and_510_cap(self):
        for values in ((0,) * 5, (256, 0, 0, 0, 0, 0), (255, 255, 1, 0, 0, 0),
                       (True, 0, 0, 0, 0, 0)):
            with self.assertRaises(ValueError):
                validate_evs(values)

    def test_exp_share_is_full_yield_not_divided_and_cannot_hold_brace(self):
        ledger = EVTrainingLedger(EVTrainingContext("share", 2, 1, 95, ZERO, recipient="EXP_SHARE"))
        ledger.commit_defeat(51, sequence=1, experience_confirmed=True, recipient_confirmed=True)
        self.assertEqual(ledger.effort_values[-1], 2)
        with self.assertRaisesRegex(ValueError, "simultaneously"):
            EVTrainingLedger(replace(ledger.context, macho_brace=True))

    def test_failed_confirmation_duplicate_and_gap_do_not_mutate_ledger(self):
        ledger = EVTrainingLedger(EVTrainingContext("run", 1, 1, 95, ZERO))
        for xp, recipient, seq, foe in ((False, True, 1, 16), (True, False, 1, 16),
                                         (True, True, 2, 16), (True, True, 1, 999)):
            with self.assertRaises(ValueError):
                ledger.commit_defeat(foe, sequence=seq, experience_confirmed=xp, recipient_confirmed=recipient)
            self.assertEqual(ledger.effort_values, ZERO)
            self.assertEqual(ledger.defeated_species, [])
        ledger.commit_defeat(16, sequence=1, experience_confirmed=True, recipient_confirmed=True)
        with self.assertRaises(ValueError):
            ledger.commit_defeat(16, sequence=1, experience_confirmed=True, recipient_confirmed=True)
        self.assertEqual(ledger.effort_values[-1], 1)

    def test_snapshot_is_immutable_and_no_levelup_is_not_a_stat_refresh(self):
        ledger = EVTrainingLedger(EVTrainingContext("run", 1, 1, 95, ZERO))
        first = ledger.observe(level=95, sequence=0, recalculation="INITIAL")
        ledger.commit_defeat(16, sequence=1, experience_confirmed=True, recipient_confirmed=True)
        for level, seq, trigger in ((95, 1, "LEVEL_UP"), (96, 1, "NONE"), (96, 0, "INITIAL")):
            with self.assertRaises(ValueError):
                ledger.observe(level=level, sequence=seq, recalculation=trigger)
        second = ledger.observe(level=97, sequence=1, recalculation="LEVEL_UP")
        self.assertEqual(first.effort_values, ZERO)
        self.assertEqual(second.effort_values[-1], 1)
        self.assertEqual(ledger.observe(level=97, sequence=1, recalculation="LEVEL_UP"), second)


class EVTrainingProtocolTests(unittest.TestCase):
    def test_verified_variable_evs_recover_the_same_gen3_pid(self):
        tid, observations = parse_sid_reverse_log(training_log())
        self.assertEqual(tid, 17500)
        result = analyze_observed_pokemon(observations)
        self.assertEqual(result.iv_min, IVS)
        self.assertEqual(result.iv_max, IVS)
        self.assertTrue(any(candidate.pid == 45092875 for candidate in result.candidates))
        self.assertEqual(result.training_battles, 20)
        self.assertEqual(result.effort_history[-1], (100, (0, 0, 0, 0, 0, 20)))
        report = build_report(training_log())
        self.assertIn("20次已确认击倒", report)
        self.assertIn("LV100 努力值: 0/0/0/0/0/20", report)

    def test_raw_variable_evs_without_a_journal_remain_rejected(self):
        first = SIDObservation(1, 1, 0, 95, stat_values(95))
        second = SIDObservation(1, 1, 0, 100, stat_values(100, (0, 0, 0, 0, 0, 20)),
                                effort_values=(0, 0, 0, 0, 0, 20))
        with self.assertRaisesRegex(ValueError, "without a confirmed training journal"):
            analyze_observed_pokemon((first, second))

    def test_missing_initial_observation_cannot_start_after_training(self):
        with self.assertRaisesRegex(ValueError, "initial"):
            parse_sid_reverse_log(begin() + defeat() + observation(96, 1, (0, 0, 0, 0, 0, 1)))

    def test_rejects_ambiguous_defeat_missing_receipt_wrong_ev_and_order(self):
        prefix = begin() + observation()
        bad_records = [
            defeat().replace("DEFEATED", "FLED"),
            defeat().replace("XP_CONFIRMED=1", "XP_CONFIRMED=0"),
            defeat().replace("RECIPIENT_CONFIRMED=1", "RECIPIENT_CONFIRMED=0"),
            defeat(2), defeat() + defeat(),
            defeat() + observation(96, 1, ZERO),
            defeat() + observation(95, 1, (0, 0, 0, 0, 0, 1)),
            defeat() + observation(96, 1, (0, 0, 0, 0, 0, 1)).replace("RECALC=LEVEL_UP", "RECALC=NONE"),
        ]
        for record in bad_records:
            with self.subTest(record=record), self.assertRaises(ValueError):
                parse_sid_reverse_log(prefix + record)

    def test_unknown_event_version_duplicate_field_and_session_mismatch(self):
        for text in (begin(extra="|MON=1"), begin().replace("V=1", "V=2"),
                     begin() + observation(session="other"), begin() + begin(),
                     begin() + defeat().replace("DEFEAT|", "ENCOUNTER|"),
                     begin().replace("|POKERUS=0", "")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_sid_reverse_log(text)

    def test_evolution_and_wrong_slot_do_not_change_the_mon_identity(self):
        for record in (observation().replace("DEX=1", "DEX=2"), observation(mon=2),
                       observation().replace("SOURCE=STATIC", "SOURCE=WILD")):
            with self.assertRaises(ValueError):
                parse_sid_reverse_log(begin() + record)

    def test_plain_candy_observations_and_attempt_restart_cannot_mix_with_training(self):
        plain = observation().replace("SIDTRAIN|OBS|V=1|SESSION=run1|", "SIDREV|OBS|")
        for tail in (plain, "SIDREV|ATTEMPT_BEGIN|MON=1|ATTEMPT=2\n"):
            with self.assertRaises(ValueError):
                parse_sid_reverse_log(begin() + observation() + tail)

    def test_non_protocol_archive_counters_cannot_become_effort_evidence(self):
        _, observations = parse_sid_reverse_log("波波: 100\n$Pidgey_count = 100\n")
        self.assertEqual(observations, [])

    def test_each_party_slot_has_an_independent_ledger(self):
        text = (begin() + observation() + begin(2, "run2") + observation(mon=2, session="run2") +
                defeat() + observation(96, 1, (0, 0, 0, 0, 0, 1)))
        _, values = parse_sid_reverse_log(text)
        self.assertEqual([item.pokemon_index for item in values], [1, 2, 1])
        self.assertEqual(values[1].effort_values, ZERO)
        self.assertEqual(values[2].effort_values[-1], 1)

    def test_direct_snapshot_inconsistency_and_backwards_observation_are_rejected(self):
        _, values = parse_sid_reverse_log(training_log())
        second = values[-1]
        for bad in (replace(second, effort_values=ZERO),
                    replace(second, training=replace(second.training, level=99)),
                    replace(second, training=replace(second.training,
                            context=replace(second.training.context, session_id="other")))):
            with self.assertRaises(ValueError):
                analyze_observed_pokemon([values[0], bad])
        with self.assertRaises(ValueError):
            analyze_observed_pokemon(values[::-1])

    def test_impossible_stat_is_not_silently_dropped_from_intersection(self):
        _, values = parse_sid_reverse_log(training_log())
        bad = replace(values[-1], stats=(231, 666, 134, 135, 166, 131))
        with self.assertRaisesRegex(ValueError, "no common IV range"):
            analyze_observed_pokemon([values[0], bad])

    def test_ansi_and_multilevel_gain_are_supported(self):
        text = "\n".join(f"\x1b[90m[12:00:00] {line}\x1b[0m" for line in training_log().splitlines())
        _, observations = parse_sid_reverse_log(text)
        self.assertEqual([item.level for item in observations], [95, 100])

    def test_iv_api_requires_aligned_vectors_and_disallows_ambiguous_constant(self):
        sample = IVsObservation("Bulbasaur", "Hardy", 100, *stat_values(100))
        for values in ([], [ZERO, ZERO], [(0,) * 5], [(255, 255, 1, 0, 0, 0)]):
            with self.assertRaises(ValueError):
                iv_calculator([sample], get_personal(1)["stats"], effort_values_per_observation=values)
        with self.assertRaises(ValueError):
            iv_calculator([sample], get_personal(1)["stats"], (1, 0, 0, 0, 0, 0),
                          effort_values_per_observation=[ZERO])


class TrainingArchiveInspectionTests(unittest.TestCase):
    def test_audit_does_not_extract_execute_or_trust_species_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "training.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("原包/（美版）火红叶绿全能脚本V3.9.txt", "CALL 针对性判断\r\r\n")
                archive.writestr("原包/lib/努力值数据包.ecs", "IF @波波 > 90\n$count_波波 = $count_波波 + 1\nENDIF\n")
                archive.writestr("原包/ImgLabel/波波.IL", b"label")
            report = inspect_training_archive(path)
            self.assertEqual(report["selection_time_counter_increments"], 1)
            self.assertFalse(report["confirmed_defeat_journal_supported"])
            self.assertEqual(report["missing_effort_labels"], [])
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_legacy_chinese_filename_recovery(self):
        from tools.inspect_sid_training_packages import _name
        original = "日版努力值数据包.ecs"
        info = zipfile.ZipInfo(original.encode("gbk").decode("cp437"))
        self.assertEqual(_name(info), original)

    def test_unsafe_or_duplicate_archive_members_are_rejected(self):
        for bad in ("../lib/a.ecs", "C:/a.ecs", "/a.ecs", "..\\a.ecs"):
            from tools.inspect_sid_training_packages import _name
            with self.assertRaises(ValueError):
                _name(zipfile.ZipInfo(bad))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("lib/a.ecs", "RETURN\n")
                with self.assertWarns(UserWarning):
                    archive.writestr("lib/a.ecs", "A\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                inspect_training_archive(path)


if __name__ == "__main__":
    unittest.main()
