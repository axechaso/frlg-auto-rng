"""Result/order and bounded-work regressions for FRLG computations."""
from collections import Counter
from itertools import product
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rng import tenlines as rng
from rng import tenlines_utils as utils
from automation.planner import AutoSearchRequest, NoMatchingTargetError, NoReachablePlanError, SearchCancelledError, search_best_plan


class ComputeRegressions(unittest.TestCase):
    def test_full_reference_corpus_from_an_independent_directory(self):
        expected = json.loads((ROOT / 'tests/fixtures/frlg-compute-reference.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory(prefix='frlg-compute-') as cwd:
            run = subprocess.run([sys.executable, str(ROOT / 'tests/frlg-compute-cases.py')], cwd=cwd, env={**os.environ, 'PYTHONUTF8': '1'}, capture_output=True, text=True, encoding='utf-8', timeout=90)
        self.assertEqual(run.returncode, 0, run.stderr)
        actual = json.loads(run.stdout)
        self.assertEqual(actual.keys(), expected.keys())
        for name in expected:
            with self.subTest(name=name):
                self.assertEqual(actual[name], expected[name])

    def test_initial_seed_index_exhaustively_matches_rng_distance(self):
        expected = sorted((rng.pokerng_distance(seed, 0), seed) for seed in range(65536))
        rng.sorted_initial_seeds_table = None
        self.assertEqual(rng.build_sorted_initial_seeds(), expected)

    def test_full_plans_match_pinned_results(self):
        for name in ('golbat', 'starter', 'golbat-restricted'):
            with self.subTest(name=name):
                expected = json.loads((ROOT / f'tests/fixtures/frlg-{name}-plan.json').read_text(encoding='utf-8'))
                actual = search_best_plan(AutoSearchRequest(**expected['request'])).to_dict()
                self.assertEqual(actual, expected)

    def test_tier_count_cache_uses_bounded_immutable_keys(self):
        utils._iv_total_counts.cache_clear()
        lower, upper = [0] * 6, [1] * 6
        self.assertEqual(utils._count_iv_combinations(lower, upper, 6), 1)
        upper[:] = [2] * 6
        self.assertEqual(utils._count_iv_combinations(lower, upper, 12), 1)
        for first in range(3):
            for second in range(32):
                utils._count_iv_combinations([0] * 6, [first, second, 1, 1, 1, 1], 1)
        self.assertLessEqual(utils._iv_total_counts.cache_info().currsize, 64)

    def test_tier_counts_and_enumeration_match_exhaustive_cartesian_product(self):
        for lo, hi in (([0] * 6, [2] * 6), ([0, 1, 2, 0, 1, 2], [1, 1, 3, 2, 3, 2]), ([1] * 6, [0] * 6)):
            all_ivs = list(product(*(range(a, b + 1) for a, b in zip(lo, hi))))
            counts = Counter(map(sum, all_ivs))
            for total in range(-1, 20):
                self.assertEqual(utils._count_iv_combinations(lo, hi, total), counts[total])
                self.assertEqual(list(rng.iter_iv_combinations(lo, hi, total)), sorted((v for v in all_ivs if sum(v) == total), reverse=True))
        self.assertEqual(sum(utils._count_iv_combinations([0] * 6, [31] * 6, t) for t in range(187)), 32 ** 6)

    def test_exact_seed_lookup_preserves_duplicates_order_offsets_and_fresh_tables(self):
        # Multiple appearances and wraparound offsets must not collapse to a
        # single time, nor leak across table replacement after an update.
        entries = [{'initial_seed': seed, 'seed_time': time, 'key': 'mono_h_a', 'button_mode': 'h'} for seed, time in ((36, 100), (40, 200), (36, 300), (0, 400))]
        seed_map = {}
        for entry in entries:
            seed_map.setdefault(entry['initial_seed'], []).append(entry)
        table = (seed_map, {'mono_h_a': entries})
        for held in ('none', 'blackout_r', 'blackout_l'):
            whole = rng.get_contiguous_seed_list(table, 'mono_h_a', 'fr_nx', held)
            for seed in (0, 36, 40, 65500, 65535):
                exact = rng.get_contiguous_seed_list(table, 'mono_h_a', 'fr_nx', held, initial_seed=seed)
                self.assertEqual(exact, [r for r in whole if r['initial_seed'] == seed])
        result = rng.get_contiguous_seed_list(table, 'mono_h_a', 'fr_nx', 'none', initial_seed=36)
        result[0]['seed_time'] = -1
        self.assertEqual(rng.get_contiguous_seed_list(table, 'mono_h_a', 'fr_nx', 'none', initial_seed=36)[0]['seed_time'], 100)
        self.assertEqual(rng.get_contiguous_seed_list(({}, {'mono_h_a': []}), 'mono_h_a', 'fr_nx', 'none', initial_seed=36), [])

    def test_rejected_shiny_pids_do_not_walk_the_wild_encounter_loop(self):
        slots = [{'species': 42, 'gender_ratio': 127, 'min_level': 46, 'max_level': 46}] * 12
        calls = []
        for shiny in (None, 2):
            with patch.object(rng, 'pokerngr_next', wraps=rng.pokerngr_next) as advance:
                list(rng.search_wild([30] * 6, [31] * 6, rng.METHOD_1, 38448, slots, filter_obj=rng.SearcherFilter(shiny=shiny)))
                calls.append(advance.call_count)
        self.assertLess(calls[1], calls[0] // 10, f'rejected shiny outcomes must avoid the expensive loop: {calls}')

    def test_static_and_wild_do_not_recompute_hidden_power_per_recovered_state(self):
        slots = [{'species': 42}] * 12
        for search, kwargs in ((rng.search_static, {}), (rng.search_wild, {'encounter_slots': slots})):
            with patch.object(rng, 'get_hidden_power', wraps=rng.get_hidden_power) as hp:
                list(search([30] * 6, [31] * 6, rng.METHOD_1, 38448, **kwargs))
                self.assertLessEqual(hp.call_count, 64, 'hidden power is constant for each IV combination')

    def test_work_limits_and_cancellation_remain_distinct_from_no_result(self):
        request = json.loads((ROOT / 'tests/fixtures/frlg-golbat-plan.json').read_text(encoding='utf-8'))['request']
        with self.assertRaisesRegex(utils.SearchWorkLimitError, '搜索尚未完成'):
            search_best_plan(AutoSearchRequest(**{**request, 'max_iv_combinations': 1}))
        with self.assertRaises(SearchCancelledError):
            search_best_plan(AutoSearchRequest(**request), cancel_check=lambda: True)
        for search, kwargs in ((rng.search_static, {}), (rng.search_wild, {'encounter_slots': []})):
            self.assertEqual(list(search([0] * 6, [31] * 6, rng.METHOD_1, 38448, cancel_check=lambda: True, **kwargs)), [])
        with self.assertRaises(NoMatchingTargetError):
            search_best_plan(AutoSearchRequest(**request), target_search=lambda **kwargs: [])
        fixed_ivs = [30, 28, 31, 31, 31, 30]
        with self.assertRaises(NoReachablePlanError):
            search_best_plan(AutoSearchRequest(**{**request, 'min_advances': 0, 'max_advances': 0, 'iv_min': fixed_ivs, 'iv_max': fixed_ivs}))

    def test_exact_work_boundary_counts_all_methods_even_when_filters_reject(self):
        kwargs = dict(game='fr_nx', tid=0, sid=38448, method='All Wild Methods',
                      category='Grass', location='Cerulean Cave 1F', pokemon='Golbat',
                      shiny='Square', ivs_range=utils.IVsRange(utils.IVs(*([31] * 6)), utils.IVs(*([31] * 6))))
        with self.assertRaises(utils.SearchWorkLimitError):
            list(utils.search_target_tiers(max_iv_combinations=2, **kwargs))
        self.assertEqual(list(utils.search_target_tiers(max_iv_combinations=3, **kwargs)), [])

    def test_cancel_after_search_starts_stops_rejected_iv_combinations(self):
        for search, kwargs in ((rng.search_static, {}), (rng.search_wild, {'encounter_slots': []})):
            with self.subTest(search=search.__name__), \
                 patch.object(rng, 'recover_pokerng_iv', return_value=[]) as recover:
                cancel = lambda: recover.call_count >= 2
                self.assertEqual(list(search([0] * 6, [31] * 6, rng.METHOD_1, 38448,
                                             cancel_check=cancel, **kwargs)), [])
                self.assertEqual(recover.call_count, 2)


if __name__ == '__main__':
    unittest.main()
