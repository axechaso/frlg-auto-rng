import unittest

from rng.tenlines import (
    METHOD_1,
    METHOD_4,
    SearcherFilter,
    get_shiny,
    iter_iv_combinations,
    pokerng_next,
    search_bugged_roamer,
)
from rng.tenlines_utils import (
    IVs,
    IVsRange,
    SearchWorkLimitError,
    initial_seed,
    resolve_ability_idx,
    search_target_tiers,
)
from automation.seed_modes import seed_mode_to_settings, settings_to_seed_mode


class TenLinesFixTests(unittest.TestCase):
    def test_exact_iv_total_iterator_is_bounded_and_complete(self):
        values = list(iter_iv_combinations([0] * 6, [2] * 6, iv_total=11))
        self.assertEqual(len(values), 6)
        self.assertTrue(all(sum(item) == 11 for item in values))
        self.assertTrue(all(0 <= value <= 2 for item in values for value in item))

    def test_ability_filter_is_applied(self):
        filter_obj = SearcherFilter(
            iv_min=[0] * 6,
            iv_max=[31] * 6,
            ability=1,
        )
        self.assertTrue(filter_obj.compare_state([31] * 6, 0, 0, 0, 0, ability=1))
        self.assertFalse(filter_obj.compare_state([31] * 6, 0, 0, 0, 0, ability=0))

    def test_duplicate_ability_slots_do_not_filter_pid_bit(self):
        self.assertIsNone(resolve_ability_idx("Static", 25))

    def test_chinese_unrestricted_ability_is_treated_as_any(self):
        self.assertIsNone(resolve_ability_idx("不限", 1))

    def test_initial_seed_settings_are_structured_without_losing_suffix(self):
        results = initial_seed(
            game="fr_nx",
            target_seed="935EFF9E",
            result_count=2,
        )
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertEqual(result.settings.sound, "mono")
            self.assertEqual(result.settings.button_mode, "h")
            self.assertEqual(result.settings.seed_button, "a")
            self.assertIn(result.settings.extra_button, {"blackout_r", "blackout_l"})

    def test_initial_seed_can_filter_one_118_mode_before_result_limit(self):
        results = initial_seed(
            game="fr_nx",
            target_seed="935EFF9E",
            result_count=3,
            settings=seed_mode_to_settings(6),
        )
        self.assertEqual(len(results), 3)
        self.assertTrue(all(settings_to_seed_mode(result.settings) == 6 for result in results))

    def test_initial_seed_does_not_repeat_routes_to_fill_large_request(self):
        results = initial_seed(
            game="fr_nx",
            target_seed="935EFF9E",
            result_count=100000,
            settings=seed_mode_to_settings(6),
        )
        keys = {
            (item.seed, item.advances, item.seed_time, item.settings.extra_button)
            for item in results
        }
        self.assertEqual(len(results), len(keys))

    def test_work_limit_reports_incomplete_instead_of_no_result(self):
        tiers = search_target_tiers(
            max_iv_combinations=0,
            game="fr_nx",
            tid=1,
            sid=2,
            method="Static 1",
            category="Starter",
            location="Starter",
            pokemon="Bulbasaur",
            shiny="Any",
            ivs_range=IVsRange(IVs(31, 31, 31, 31, 31, 31), IVs(31, 31, 31, 31, 31, 31)),
        )
        with self.assertRaisesRegex(SearchWorkLimitError, "搜索尚未完成"):
            next(tiers)

    def test_bugged_roamer_search_recovers_the_exact_forward_state(self):
        start_seed = 0x12345678
        pid_high_state = pokerng_next(start_seed)
        pid_high = pid_high_state >> 16
        pid_low_state = pokerng_next(pid_high_state)
        pid_low = pid_low_state >> 16
        pid = pid_low | (pid_high << 16)
        iv_state = pokerng_next(pid_low_state)
        iv_byte = (iv_state >> 16) & 0xFF
        ivs = (iv_byte & 31, (iv_byte >> 5) & 7, 0, 0, 0, 0)
        tsv = pid_low ^ pid_high
        self.assertEqual(get_shiny(pid, tsv), 2)

        filter_obj = SearcherFilter(
            shiny=2,
            iv_min=list(ivs),
            iv_max=list(ivs),
        )
        results = list(search_bugged_roamer(
            list(ivs), list(ivs), METHOD_1, tsv,
            filter_obj=filter_obj, iv_total=sum(ivs),
        ))
        self.assertTrue(any(
            item["seed"] == start_seed
            and item["pid"] == pid
            and item["ivs"] == ivs
            for item in results
        ))

    def test_bugged_roamer_method4_skips_one_rng_output_before_ivs(self):
        start_seed = 0x8BADF00D
        pid_high_state = pokerng_next(start_seed)
        pid_high = pid_high_state >> 16
        pid_low_state = pokerng_next(pid_high_state)
        pid_low = pid_low_state >> 16
        pid = pid_low | (pid_high << 16)
        skipped_state = pokerng_next(pid_low_state)
        iv_state = pokerng_next(skipped_state)
        iv_byte = (iv_state >> 16) & 0xFF
        ivs = (iv_byte & 31, (iv_byte >> 5) & 7, 0, 0, 0, 0)
        tsv = pid_low ^ pid_high
        filter_obj = SearcherFilter(
            shiny=2,
            iv_min=list(ivs),
            iv_max=list(ivs),
        )
        results = list(search_bugged_roamer(
            list(ivs), list(ivs), METHOD_4, tsv,
            filter_obj=filter_obj, iv_total=sum(ivs),
        ))
        self.assertTrue(any(
            item["seed"] == start_seed
            and item["pid"] == pid
            and item["ivs"] == ivs
            for item in results
        ))

    def test_roaming_tiers_rank_only_the_retained_hp_and_attack(self):
        tiers = search_target_tiers(
            game="fr_nx",
            tid=0x0B71,
            sid=0x84EA,
            method="Static 1",
            category="Roaming",
            location="Roaming",
            pokemon="Raikou",
            shiny="Square",
            ivs_range=IVsRange(
                IVs(10, 4, 0, 0, 0, 0),
                IVs(10, 4, 31, 31, 31, 31),
            ),
        )
        iv_total, results = next(tiers)
        rows = list(results)
        self.assertEqual(iv_total, 14)
        self.assertTrue(rows)
        self.assertTrue(all(row.ivs == IVs(10, 4, 0, 0, 0, 0) for row in rows))


if __name__ == "__main__":
    unittest.main()
