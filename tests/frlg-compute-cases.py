"""Deterministic FRLG compute corpus; can run against the pinned original."""
import argparse
from dataclasses import asdict
import hashlib
from itertools import product
import json
from pathlib import Path
import random
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, default=ROOT)
parser.add_argument('--output', type=Path)
parser.add_argument('--benchmark', action='store_true')
args = parser.parse_args()
sys.path.insert(0, str(args.source_root.resolve()))
from rng import tenlines as rng
from rng import tenlines_utils as utils
from automation.planner import select_seed_mode_for_seed
from automation.seed_modes import seed_mode_to_settings


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def corpus():
    records = {}

    def save(name, fn):
        try:
            value = fn()
        except ValueError as error:
            value = {'error': type(error).__name__, 'message': str(error)}
        records[name] = {'count': len(value) if isinstance(value, list) else None, 'sha256': digest(value)}

    randomizer = random.Random(731)
    iv_samples = [[randomizer.randrange(32) for _ in range(6)] for _ in range(512)]
    for method in (rng.METHOD_1, rng.METHOD_2, rng.METHOD_4):
        save(f'recover/{method}', lambda: [rng.recover_pokerng_iv(*ivs, method) for ivs in iv_samples])
        for ratio in (0, 31, 127, 254, 255):
            baseline = list(rng.search_static([30] * 6, [31] * 6, method, 38448, gender_ratio=ratio))
            target = baseline[0]
            tsv = (target['pid'] >> 16) ^ (target['pid'] & 65535)
            filters = [None, rng.SearcherFilter(shiny=255, gender=255)]
            filters += [rng.SearcherFilter(shiny=s) for s in (0, 1, 2, 3)]
            filters += [rng.SearcherFilter(natures={target['nature']}, ability=target['ability'], gender=target['gender'], hp_type=target['hidden_type'])]
            for index, filt in enumerate(filters):
                save(f'static/{method}/{ratio}/{index}', lambda: list(rng.search_static([30] * 6, [31] * 6, method, tsv, gender_ratio=ratio, filter_obj=filt)))
        # Mixed species/gender ratios catch unsafe hoisting of slot-dependent filters.
        slots = [{'species': 1 + i, 'form': i % 2, 'gender_ratio': (0, 254, 255, 127)[i % 4], 'min_level': 5 + i, 'max_level': 9 + i} for i in range(12)]
        for encounter in range(6):
            baseline = list(rng.search_wild([30] * 6, [31] * 6, method, 38448, slots, encounter_type=encounter))
            target = baseline[0]
            tsv = (target['pid'] >> 16) ^ (target['pid'] & 65535)
            filters = [None, rng.SearcherFilter(shiny=255, gender=255)]
            filters += [rng.SearcherFilter(shiny=s) for s in (0, 1, 2, 3)]
            filters += [rng.SearcherFilter(natures={target['nature']}, ability=target['ability'], gender=target['gender'], hp_type=target['hidden_type'], slots=[target['encounter_slot']])]
            for index, filt in enumerate(filters):
                save(f'wild/{method}/{encounter}/{index}', lambda: list(rng.search_wild([30] * 6, [31] * 6, method, tsv, slots, encounter_type=encounter, filter_obj=filt)))
        save(f'static-bugged/{method}', lambda: list(rng.search_static([30] * 6, [31] * 6, method, 38448, bugged_roamer=True)))

    for method in (rng.METHOD_1, rng.METHOD_4):
        save(f'roamer/{method}', lambda: list(rng.search_bugged_roamer([28, 6, 0, 0, 0, 0], [31, 7, 0, 0, 0, 0], method, 38448, filter_obj=rng.SearcherFilter(shiny=2))))
    save('hidden-power/all-low-bits', lambda: [rng.get_hidden_power(ivs) for ivs in product(range(4), repeat=6)])
    save('initial-index/all-65536', rng.build_sorted_initial_seeds)
    save('iv-tiers/enumeration', lambda: [list(rng.iter_iv_combinations([0, 1, 0, 1, 0, 1], [2] * 6, total)) for total in range(14)])
    save('iv-tiers/counts', lambda: [utils._count_iv_combinations([0] * 6, [31] * 6, total) for total in range(187)])
    for game in ('fr_nx', 'lg_nx', 'fr_nx2', 'lg_nx2', 'fr_jpn_nx', 'lg_jpn_nx', 'fr_jpn_nx2', 'lg_jpn_nx2'):
        for offset in (0, 37, -8192):
            for mode in (None, 0, 4, 6):
                save(f'initial/{game}/{offset}/{mode}', lambda: [asdict(r) for r in utils.initial_seed(game=game, target_seed='95594272', offset=offset, result_count=8, settings=seed_mode_to_settings(mode) if mode is not None else None)])
        for seed in ('0000', '7422', 'BFBD', 'FFFF'):
            for mode in (None, 0, 4, 6):
                save(f'exact-seed/{game}/{seed}/{mode}', lambda: asdict(select_seed_mode_for_seed(game, seed, mode)))
    return records


def benchmark():
    rows = {}

    def measure(name, fn, repeat=1):
        started = perf_counter()
        for _ in range(repeat):
            value = fn()
        rows[name] = {'seconds_per_call': (perf_counter() - started) / repeat, 'repeat': repeat, 'sha256': digest(value)}

    rng.sorted_initial_seeds_table = None
    measure('initial-index/cold', rng.build_sorted_initial_seeds)
    measure('initial-seed/warm', lambda: [asdict(r) for r in utils.initial_seed(game='fr_nx', target_seed='95594272', result_count=10)], 100)
    measure('exact-seed/warm', lambda: asdict(select_seed_mode_for_seed('fr_nx', '7422')), 100)
    measure('iv-tier-counts', lambda: [utils._count_iv_combinations([0] * 6, [31] * 6, t) for t in range(187)], 3)
    measure('iv-enumeration', lambda: list(rng.iter_iv_combinations([0] * 6, [31] * 6, 178)), 3)
    for method in ('Static 1', 'All Wild Methods'):
        for shiny, lower in (('Star/Square', 27), ('Any', 29)):
            measure(f'target-reverse/{method}/{shiny}', lambda: [asdict(r) for r in utils.search_targets(game='fr_nx', tid=0, sid=38448, method=method, category='Grass' if 'Wild' in method else 'Starter', location='Cerulean Cave 1F' if 'Wild' in method else '', pokemon='Golbat' if 'Wild' in method else 'Bulbasaur', shiny=shiny, ivs_range=utils.IVsRange(utils.IVs(*([lower] * 6)), utils.IVs(*([31] * 6))))])
    obs = utils.IVsObservation(nature='Hardy', level=50, hp=120, attack=70, defense=69, sp_attack=85, sp_defense=85, speed=65)
    measure('iv-from-stats', lambda: asdict(utils.iv_calculator([obs], (45, 49, 49, 65, 65, 45))), 1000)
    return rows


if __name__ == '__main__':
    result = benchmark() if args.benchmark else corpus()
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(encoded, encoding='utf-8')
        print(f'Wrote {len(result)} cases to {args.output}', flush=True)
    else:
        print(encoded, flush=True)
