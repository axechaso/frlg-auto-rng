"""Generate SID-traversal evidence acceptance projects, with no console input."""

import argparse
from itertools import product
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation import EasyCon118Options, EGG_TEMPLATE_NAME, write_configured_project
from automation.planner import AutoSearchRequest, RunPlan
from automation.support import get_route_support
from automation.target_verification import TargetVerificationSpec
from automation.sid_observation import validate_injected_pid_observation
from automation.easycon118 import validate_generated_project_consistency
from rng.sid_reverse import sid_at_advance
from rng.tenlines_utils import IVs, InitialSeedResult, SearcherResult
from automation.seed_modes import seed_mode_to_settings


def generate_matrix(source: Path, destination: Path) -> list[Path]:
    source, destination = source.resolve(), destination.resolve()
    result = []
    for template, model, kind in product(('NS火叶全自动一键乱数2.0.ecs', EGG_TEMPLATE_NAME), (1, 2),
                                         ('wild', 'static', 'starter-en', 'starter-jp')):
        game = ('fr_jpn_nx' if kind.endswith('-jp') else 'fr_nx') + ('2' if model == 2 else '')
        pokemon = 'Pikachu' if kind == 'wild' else 'Snorlax' if kind == 'static' else 'Squirtle'
        species = 25 if kind == 'wild' else 143 if kind == 'static' else 7
        category = 'Grass' if kind == 'wild' else 'Stationary' if kind == 'static' else 'Starter'
        location = 'Viridian Forest' if kind == 'wild' else category
        method = 'Wild 1' if kind == 'wild' else 'Static 1'
        sid = sid_at_advance(12345, 1901)
        pid = ((12345 ^ sid) >> 3) << 3
        request = AutoSearchRequest(game=game, tid=12345, sid=sid, method=method, category=category,
                                   location=location, pokemon=pokemon, min_advances=0, max_advances=3000)
        target = SearcherResult(target_seed='0000EDDE', method=method, pokemon=pokemon,
                                level=3 if kind == 'wild' else 30 if kind == 'static' else 5,
                                pid=f'{pid:08X}', shiny='Star', nature='Timid', ability='Any',
                                ivs=IVs(31, 31, 31, 31, 31, 31), hidden_type='Dark', hidden_power=70, gender='M')
        initial = InitialSeedResult(seed='EDDE', advances=2000, total_frames=2000, total_time='00:00:00',
                                    seed_time=40000, settings=seed_mode_to_settings(0))
        route = get_route_support(method, category, location, pokemon=pokemon, game=game)
        plan = RunPlan(request, target, initial, 186, route)
        options = EasyCon118Options(nx_model=model, japanese_starter=kind.endswith('-jp'),
                                    record_shiny_video=True, update_precalibration=False)
        spec = TargetVerificationSpec('offline-matrix', 'attempt-matrix', 'EDDE', 2000, species, method, f'{pid:08X}')
        directory = destination / f"{'formal' if template == 'NS火叶全自动一键乱数2.0.ecs' else 'timeline'}-ns{model}-{kind}"
        main = write_configured_project(source, directory, plan, options, template_name=template,
                                        precalibration_store_path=destination / 'unused-precalibration.json',
                                        target_verification=spec)
        validate_injected_pid_observation(main.read_text(encoding='utf-8'), spec, tid=request.tid, sid=sid)
        validate_generated_project_consistency(main, plan, options, template_name=template)
        result.append(main)
    if len(result) != 16 or len(set(result)) != 16:
        raise AssertionError('The acceptance matrix must contain 16 independent projects.')
    (destination / 'matrix.json').write_text(json.dumps({'count': len(result), 'hardware_access': False,
        'files': [str(p.relative_to(destination)) for p in result]}, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--source', type=Path, default=Path('local_assets/easycon118'))
    args = parser.parse_args()
    paths = generate_matrix(args.source, args.destination)
    print(f'Generated {len(paths)} complete SID evidence projects. No hardware run.')


if __name__ == '__main__':
    main()
