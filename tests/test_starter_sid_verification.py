import unittest

from rng.starter_sid_verification import (
    StarterSearchRequest,
    StarterTarget,
    StarterVerificationStatus,
    evaluate_starter_verification,
    find_earliest_shiny_starter,
    sid_advance_scan_offsets,
)


class StarterSIDVerificationTests(unittest.TestCase):
    def test_searches_lowest_reachable_shiny_starter_from_1500(self):
        target = find_earliest_shiny_starter(
            StarterSearchRequest(
                version="火红",
                language="英文",
                starter="妙蛙种子",
                tid=12345,
                sid=8832,
                min_advances=1500,
                max_advances=1600,
            )
        )

        self.assertEqual(target.game_code, "fr_nx")
        self.assertEqual(target.setting_key, "mono_h_a")
        self.assertEqual(target.advances, 1513)
        self.assertEqual(target.initial_seed, 40105)
        self.assertEqual(target.seed_time_ms, 33754)
        self.assertEqual(target.pid, 2271450586)
        self.assertEqual(target.ivs, (21, 25, 13, 18, 11, 25))

    def test_japanese_switch_seed_table_is_supported(self):
        request = StarterSearchRequest(
            version="叶绿",
            language="日文",
            starter="Squirtle",
            tid=1,
            sid=2,
            min_advances=1500,
            max_advances=1500,
        )
        self.assertEqual(request.game_code, "lg_jpn_nx")
        self.assertEqual(request.setting_key, "mono_h_a")

    def test_rejects_setting_missing_from_japanese_switch_data(self):
        with self.assertRaisesRegex(ValueError, "可用设置：mono_h_a"):
            find_earliest_shiny_starter(
                StarterSearchRequest(
                    version="火红",
                    language="日文",
                    starter="小火龙",
                    tid=1,
                    sid=2,
                    sound=1,
                    min_advances=1500,
                    max_advances=1500,
                )
            )

    def test_scan_order_is_symmetric(self):
        self.assertEqual(sid_advance_scan_offsets(3), (0, 1, -1, 2, -2, 3, -3))

    def test_wrong_pid_continues_normal_starter_rng(self):
        target = self._target(pid=0x12345678)
        result = evaluate_starter_verification(
            target,
            0x12345679,
            False,
        )
        self.assertEqual(result.status, StarterVerificationStatus.CONTINUE_STARTER_RNG)
        self.assertFalse(result.target_pid_hit)

    def test_exact_non_shiny_pid_only_proves_sid_miss(self):
        target = self._target(pid=0x12345678)
        result = evaluate_starter_verification(
            target,
            target.pid,
            False,
        )
        self.assertEqual(result.status, StarterVerificationStatus.SID_MISS)

    def test_exact_shiny_pid_finishes_as_sid_hit(self):
        target = self._target(pid=0x12345678, tid=12345, sid=8832)
        result = evaluate_starter_verification(
            target,
            target.pid,
            True,
        )
        self.assertEqual(result.status, StarterVerificationStatus.SID_HIT)

    @staticmethod
    def _target(*, pid: int, tid: int = 1, sid: int = 2) -> StarterTarget:
        return StarterTarget(
            game_code="fr_nx",
            language="英文",
            species_id=1,
            species_zh="妙蛙种子",
            species_en="Bulbasaur",
            tid=tid,
            sid=sid,
            setting_key="mono_h_a",
            initial_seed=0,
            seed_time_ms=0,
            advances=1500,
            pid=pid,
            ivs=(0, 0, 0, 0, 0, 0),
            nature=0,
            gender=0,
            ability=0,
            shiny=1,
        )


if __name__ == "__main__":
    unittest.main()
