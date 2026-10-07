import json
from contextlib import ExitStack
from dataclasses import asdict, replace
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation.sid_observation import (
    EXTENSION_PATH, MARKER, inject_pid_observation, parse_pid_observations,
    validate_injected_pid_observation,
)
from automation.target_verification import TargetVerificationSpec, inject_target_verification
from pyside_app.results import traversal_report_summary
from rng.sid_reverse import pid_to_psv, sid_at_advance, sid_candidates_for_psv
from sid_traversal import SIDTraversalSession, progress_path, read_progress
from tests.test_sid_traversal import make_context
from tests.test_auto_planner import request as make_request, route as make_route, target as make_target


def wire(pid, shiny=False, *, round=0, run="run-1", attempt="attempt-1", species=54,
         count=1, minimum=None, maximum=None, page=98, threshold=95):
    minimum = (96 if shiny else 60) if minimum is None else minimum
    maximum = (97 if shiny else 62) if maximum is None else maximum
    return (f"SIDTRAVERSAL_OBS|V=1|RUN={run}|ATTEMPT={attempt}|ROUND={round}"
            f"|SPECIES={species}|PIDHI={pid >> 16}|PIDLO={pid & 65535}|UNIQUE_PID=1"
            f"|CANDIDATES={count}|SHINY={int(shiny)}|STAR_MIN={minimum}|STAR_MAX={maximum}"
            f"|PAGE_MIN={page}|THRESHOLD={threshold}|END=1")


def observations(pid, shiny=False, **kwargs):
    return parse_pid_observations(wire(pid, shiny, **kwargs), run_id="run-1", attempt_id="attempt-1")


def minimal_template():
    shiny = '    IF $道具乱数模式 == 0 and @出闪 >= $识图阈值\n        PRINT 已识别到出闪，脚本停止\n        RETURN 0\n    ENDIF\n'
    return ('$脚本版本 = "2.0"\n'
            'FUNC 读取并输出识图结果(): INT\n' + shiny.replace('        PRINT 已识别', '        PRINT ""\n        PRINT 已识别') + '    RETURN 1\nENDFUNC\n'
            'FUNC 读取并输出日版御三家识图结果(): INT\n' + shiny + '    RETURN 1\nENDFUNC\n'
            'FUNC 重置本轮候选状态\n    $本轮候选命中计数 = 0\nENDFUNC\n'
            'FUNC 处理匹配候选\n    IF $匹配 != 1\n        RETURN\n    ENDIF\n    $本轮候选命中计数 += 1\n    CALL 记录当前候选为最佳候选\nENDFUNC\n'
            'FUNC 执行自动校准与等待更新(): INT\n'
            '    IF $道具乱数模式 == 0 and $命中差索引 == 0 and $本轮消耗帧误差 == 0 and $本轮物种命中 == 1\n        RETURN 0\n    ENDIF\n'
            '    IF $命中差索引 == 0 and $本轮消耗帧误差 == 0 and $本轮物种命中 == 0\n        PRINT 非目标\n    ENDIF\n'
            '    $循环计数 += 1\n    RETURN 1\nENDFUNC\n'
            '$普通闪光策略结果 = 设置普通闪光策略($目标全国图鉴编号, $普通闪光停止策略, $出闪录像, $出闪录像长按MS)\n'
            'FOR\n        $本轮流程结果 = 执行RNG启动与目标获取()\n'
            '        $反查细分成功 = 执行识图反查直到候选唯一()\nNEXT\n')


class PIDObservationProtocolTests(unittest.TestCase):
    def test_multiple_rounds_accept_normal_and_non_target_shiny(self):
        text = '\ufeff\x1b[90m[12:34:56.789] ' + wire(0xFFFFFFFF, count=3) + '\x1b[0m\n' + wire(0x12345678, True, round=2, species=7)
        result = parse_pid_observations(text, run_id="run-1", attempt_id="attempt-1")
        self.assertEqual([r["pid"] for r in result], ["FFFFFFFF", "12345678"])
        self.assertTrue(result[1]["shiny"])
        self.assertEqual(result[0]["candidate_count"], 3)

    def test_malformed_foreign_duplicate_or_reordered_packets_fail_closed(self):
        good = wire(0x12345678)
        invalid = (good[:-1], good.replace('UNIQUE_PID=1', 'UNIQUE_PID=0'),
                   good.replace('PIDHI=4660', 'PIDHI=65536'), good.replace('SHINY=0', 'SHINY=false'),
                   wire(1, attempt='other'), wire(1, run='other'), wire(1, species=0), wire(1, count=0),
                   good + '\n' + good, wire(1, round=3) + '\n' + wire(2, round=2),
                   good + '"', '[99:34:56.789] ' + good)
        for value in invalid:
            with self.subTest(value=value[-100:]):
                # Invalid timestamp wrapping never qualifies as a protocol line.
                if value.startswith('[99:'):
                    self.assertEqual(parse_pid_observations(value, run_id='run-1', attempt_id='attempt-1'), [])
                else:
                    with self.assertRaises(ValueError):
                        parse_pid_observations(value, run_id='run-1', attempt_id='attempt-1')

    def test_borderline_or_low_page_scores_never_exclude_tsv(self):
        for maximum in (91, 92, 93, 94, 95, 100):
            with self.assertRaisesRegex(ValueError, '闪光状态'):
                observations(1, maximum=maximum)
        for page in (0, 50, 94):
            with self.assertRaisesRegex(ValueError, '置信度'):
                observations(1, page=page)
        with self.assertRaises(ValueError):
            observations(1, True, minimum=94)
        with self.assertRaises(ValueError):
            observations(1, threshold=90)
        self.assertFalse(observations(1, maximum=90)[0]['shiny'])


class PIDObservationInjectionTests(unittest.TestCase):
    def setUp(self):
        self.spec = TargetVerificationSpec('run-1', 'attempt-1', 'EDDE', 2000, 25, 'Wild1', '89ABCDEF')

    def test_all_candidates_are_tracked_before_any_path_choice(self):
        result = inject_pid_observation(inject_target_verification(minimal_template(), self.spec), self.spec, tid=12345, sid=54321)
        self.assertEqual(result.count(MARKER), 1)
        self.assertLess(result.index('CALL SID遍历收集匹配PID'), result.index('CALL 记录当前候选为最佳候选'))
        self.assertEqual(result.count('CALL SID遍历采样闪光状态'), 2)
        self.assertIn('$实际出闪后继续抓捕 = 1\n$普通闪光停止策略 = 0', result)
        self.assertIn('CALL 清空最近出闪检测', result)
        self.assertIn('$SID遍历PID高 != 35243 or $SID遍历PID低 != 52719', result)
        validate_injected_pid_observation(result, self.spec, tid=12345, sid=54321)
        with self.assertRaisesRegex(ValueError, '已经注入'):
            inject_pid_observation(result, self.spec, tid=12345, sid=54321)
        with self.assertRaisesRegex(ValueError, '接线'):
            validate_injected_pid_observation(result.replace('CALL SID遍历收集匹配PID', 'CALL 忽略PID'), self.spec, tid=12345, sid=54321)

    def test_missing_or_duplicated_hook_is_rejected(self):
        source = inject_target_verification(minimal_template(), self.spec)
        for old, new in [('FUNC 重置本轮候选状态', 'FUNC 其他'),
                         ('    $本轮候选命中计数 += 1\n', '    $本轮候选命中计数 += 1\n' * 2),
                         ('        $反查细分成功 = 执行识图反查直到候选唯一()\n', '')]:
            with self.assertRaises(ValueError):
                inject_pid_observation(source.replace(old, new), self.spec, tid=12345, sid=54321)

    def test_shiny_ambiguity_exits_before_calibration_or_restart(self):
        source = EXTENSION_PATH.read_text(encoding='utf-8')
        self.assertNotIn('HOME', source)
        self.assertNotIn('关闭游戏', source)
        self.assertNotIn('本轮真值解', source)
        self.assertIn('$SID遍历PID一致 == 1', source)
        self.assertIn('$SID遍历星标最高 <= $SID遍历证据阈值 - 5', source)
        self.assertIn('RETURN 3', source)


class TSVEvidenceProgressTests(unittest.TestCase):
    def test_one_non_shiny_observation_excludes_all_eight_sids_and_survives_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = make_context()
            sid = sid_at_advance(context['tid'], 1901)
            tsv = (context['tid'] ^ sid) >> 3
            pid = (tsv << 3) | 7
            with SIDTraversalSession(tmp, context) as session:
                session.begin_candidate(1901)
                session.record_pid_observations(observations(pid), log='candidate.log')
                for variant in sid_candidates_for_psv(context['tid'], tsv):
                    self.assertTrue(session.candidate_tsv_excluded(variant))
                session.skip_excluded_candidate()
                self.assertEqual(session.state['evidence_skipped_count'], 1)
                self.assertEqual(session.state['skipped_count'], 0)
                self.assertEqual(session.state['tested_non_shiny_count'], 0)
            with SIDTraversalSession(tmp, context) as resumed:
                self.assertEqual(resumed.next_sid_advance, 1903)
                self.assertEqual(resumed.state['excluded_tsvs'], [tsv])
                self.assertEqual(len(resumed.state['pid_observations']), 1)

    def test_non_target_shiny_resolves_tsv_not_fake_unique_full_sid(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = make_context()
            sid = sid_at_advance(context['tid'], 1903)
            tsv = (context['tid'] ^ sid) >> 3
            with SIDTraversalSession(tmp, context) as session:
                session.begin_candidate(1901)
                session.record_pid_observations(observations(tsv << 3, True, species=54), log='non-target.log')
                result = session.resolve_confirmed_tsv()
                self.assertTrue(session.completed)
                self.assertEqual(result['tsv'], tsv)
                self.assertEqual(len(result['sid_candidates']), 8)
                self.assertFalse(result['uniquely_determined'])
                for item in result['sid_advance_candidates']:
                    self.assertEqual(item['sid_advance'] % 2, 1)
                    self.assertEqual((context['tid'] ^ item['sid']) >> 3, tsv)
                self.assertEqual(result['sid_advance'], 1903)
            self.assertEqual(read_progress(tmp, context)['state']['confirmed_tsv'], tsv)

    def test_conflicting_batch_changes_no_existing_constraints(self):
        with tempfile.TemporaryDirectory() as tmp:
            with SIDTraversalSession(tmp, make_context()) as session:
                session.begin_candidate(1901)
                batch = observations(0x12345678) + observations(0x12345678, True, round=1)
                with self.assertRaisesRegex(ValueError, '冲突'):
                    session.record_pid_observations(batch, log='conflict.log')
                self.assertEqual(session.state['pid_observations'], [])
                self.assertEqual(session.next_sid_advance, 1901)

    def test_duplicate_evidence_is_idempotent_but_conflicts_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            with SIDTraversalSession(tmp, make_context()) as session:
                session.begin_candidate(1901)
                value = observations(0x12345678)
                session.record_pid_observations(value, log='one.log')
                session.record_pid_observations(value, log='two.log')
                self.assertEqual(len(session.state['pid_observations']), 1)
                with self.assertRaises(ValueError):
                    session.record_pid_observations(observations(1), log='two.log')

    def test_old_checkpoint_retains_cursor_and_corrupt_constraints_are_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = make_context()
            with SIDTraversalSession(tmp, context) as session:
                session.begin_candidate(1901)
            path = progress_path(tmp, context)
            value = json.loads(path.read_text(encoding='utf-8'))
            for key in ('pid_observations', 'excluded_tsvs', 'confirmed_tsv', 'evidence_skipped_count'):
                value['state'].pop(key)
            path.write_text(json.dumps(value), encoding='utf-8')
            with SIDTraversalSession(tmp, context) as session:
                self.assertEqual(session.next_sid_advance, 1901)
                self.assertFalse(session.candidate_tsv_excluded(1))
            value['state']['excluded_tsvs'] = [5]
            path.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '证据不一致'):
                read_progress(tmp, context)

    def test_window_skips_do_not_exclude_any_tsv(self):
        with tempfile.TemporaryDirectory() as tmp:
            with SIDTraversalSession(tmp, make_context()) as session:
                session.begin_candidate(1901)
                session.skip_candidate('no-target')
                self.assertEqual(session.state['excluded_tsvs'], [])
                self.assertEqual(session.state['evidence_skipped_count'], 0)

    def test_resolved_tsv_outside_window_still_finishes_without_console_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = make_context(max_advances=1901)
            current = (context['tid'] ^ sid_at_advance(context['tid'], 1901)) >> 3
            tsv = (current + 1) % 8192
            with SIDTraversalSession(tmp, context) as session:
                session.begin_candidate(1901)
                session.record_pid_observations(observations(tsv << 3, True), log='shiny.log')
                result = session.resolve_confirmed_tsv()
                self.assertIsNone(result['sid'])
                self.assertIsNone(result['sid_advance'])
                summary = traversal_report_summary(dict(result, status='completed'))
                self.assertIn('TSV', summary[0])
                self.assertIn('8 个 SID', summary[3])
                self.assertIn('无可采用值', summary[3])


class SIDObservationWorkerTests(unittest.TestCase):
    def run_worker(self, tmp, events, *, stop=False, failed=False, seed_exclusion=False):
        import run_sid_traversal as worker
        from automation import EasyCon118Options
        from automation.planner import RunPlan
        from automation.sid_traversal_policy import validate_traversal_request
        from automation.support import get_route_support
        from sid_traversal import traversal_context
        root = Path(tmp)
        request = make_request(max_advances=3000)
        options = EasyCon118Options(frame_parity_scheme=1, mystery_gift_enabled=False)
        availability = validate_traversal_request(request, options, worker.STANDARD_TEMPLATE_NAME)
        context = traversal_context(tid=request.tid, named_rival=False,
            wild_request=asdict(request), easycon_options=asdict(options), source_sha256='0' * 64,
            max_advances=1905, target_max_advances=3000, template_name=worker.STANDARD_TEMPLATE_NAME,
            encounter_kind=availability.encounter_kind, route_key=availability.route_key,
            save_context={'mystery_gift_enabled': False}, effective_frame_parity_scheme=1)
        payload = dict(source=str(root.resolve()), max_advances=1905, target_max_advances=3000,
            named_rival=False, start_sid_advance=1901, template_name=worker.STANDARD_TEMPLATE_NAME,
            save_context={'mystery_gift_enabled': False}, effective_frame_parity_scheme=1,
            verification_protocol=1, script_fingerprint='sha256:' + '0' * 64,
            traversal_context=context, precalibration_store_path=str(root / 'unused.json'))
        if seed_exclusion:
            sid = sid_at_advance(request.tid, 1901)
            pid = ((request.tid ^ sid) >> 3) << 3
            with SIDTraversalSession(root / 'progress', context) as session:
                session.record_pid_observations(observations(pid), log='old.log')
        spec_holder, searches, runs = [], [], []

        def search(req, **kwargs):
            searches.append(req.sid)
            pid = ((req.tid ^ req.sid) >> 3) << 3
            target = replace(make_target('0000EDDE', (31,) * 6), pid=f'{pid:08X}')
            return SimpleNamespace(plan=RunPlan(req, target, make_route('EDDE', 2000), 186,
                get_route_support(req.method, req.category, req.location, pokemon=req.pokemon, game=req.game)))

        def generate(source, directory, plan, options, **kwargs):
            spec_holder.append(kwargs['target_verification'])
            directory.mkdir(parents=True, exist_ok=True)
            main = directory / 'main.ecs'
            main.write_text('# Offline worker stub; no keys or capture\n', encoding='utf-8')
            return main

        def run(command, cwd, log, markers, **kwargs):
            spec = spec_holder[-1]
            idx = len(runs)
            runs.append(spec)
            event = events[idx] if idx < len(events) else 'shiny'
            tsv = (request.tid ^ searches[-1]) >> 3
            if event == 'shiny-other':
                tsv = (request.tid ^ sid_at_advance(request.tid, 1905)) >> 3
            packet = wire(tsv << 3, event.startswith('shiny'), run=spec.run_id, attempt=spec.attempt_id)
            if event == 'invalid':
                packet = packet.replace('|UNIQUE_PID=1', '|UNIQUE_PID=0')
            elif event == 'conflict':
                packet += '\n' + wire(tsv << 3, True, round=1, run=spec.run_id, attempt=spec.attempt_id)
            elif event == 'target-only':
                packet = (f'SIDTRAVERSAL|V=1|RUN={spec.run_id}|ATTEMPT={spec.attempt_id}|ROUND=1|EVENT=TARGET'
                          '|SEED_MATCH=1|ADV_MATCH=1|SPECIES_MATCH=1|SHINY=0|END=1')
            log.write_text(packet, encoding='utf-8')
            if stop:
                (root / 'stop').write_text('stop', encoding='utf-8')
                return 130
            return 1 if failed else 0

        with ExitStack() as stack:
            for name, side_effect in (('_load_plan', lambda p: (request, options, payload)),
                                      ('inspect_script_corpus', lambda p: {'sha256': '0' * 64}),
                                      ('prepare_compat_runner', lambda *a, **k: root / 'never-run.exe'),
                                      ('search_best_plan', search), ('write_configured_project', generate),
                                      ('validate_runtime', lambda *a, **k: SimpleNamespace(ok=True)),
                                      ('build_run_command', lambda *a, **k: ['never-run']), ('run_logged', run),
                                      ('_emit_session', lambda *a, **k: None), ('_append_log', lambda *a, **k: None)):
                stack.enter_context(patch.object(worker, name, side_effect=side_effect))
            code = worker.run_traversal(plan_path=root / 'plan.json', source_dir=root,
                ezcon_path=root / 'ezcon.exe', output_dir=root / 'out', progress_dir=root / 'progress',
                port='OFFLINE', video=0, log_path=root / 'worker.log', report_path=root / 'report.json',
                stop_file=root / 'stop', run_id='run-1')
        return code, json.loads((root / 'report.json').read_text(encoding='utf-8')), searches, runs

    def test_unique_calibration_non_shiny_advances_without_target_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report, searches, runs = self.run_worker(tmp, ['normal', 'shiny'])
            self.assertEqual(code, 0)
            self.assertEqual(len(runs), 2)
            self.assertEqual(report['status'], 'completed')
            self.assertEqual(report['evidence_skipped_count'], 1)
            self.assertEqual(report['candidates'][0]['status'], 'tsv-excluded')

    def test_non_target_shiny_is_success_not_missing_target_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report, searches, runs = self.run_worker(tmp, ['shiny-other'])
            self.assertEqual(code, 0)
            self.assertEqual(len(runs), 1)
            self.assertEqual(report['status'], 'completed')
            self.assertEqual(report['sid_advance'], 1905)
            self.assertEqual(len(report['sid_candidates']), 8)
            self.assertFalse(report['uniquely_determined'])

    def test_previously_excluded_tsv_skips_search_and_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, report, searches, runs = self.run_worker(tmp, ['shiny'], seed_exclusion=True)
            self.assertEqual(code, 0)
            self.assertEqual(len(searches), 1)
            self.assertEqual(len(runs), 1)
            self.assertEqual(report['candidates'][0]['status'], 'tsv-excluded')

    def test_stop_and_runner_failure_preserve_evidence_but_not_advance(self):
        for stop, failed, expected in ((True, False, 130), (False, True, 1)):
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as tmp:
                code, report, _, _ = self.run_worker(tmp, ['normal'], stop=stop, failed=failed)
                self.assertEqual(code, expected)
                self.assertEqual(report['status'], 'paused')
                self.assertEqual(report['next_sid_advance'], 1901)
                self.assertEqual(len(report['excluded_tsvs']), 1)

    def test_malformed_conflicting_or_target_only_evidence_never_advances(self):
        for event in ('invalid', 'conflict', 'target-only'):
            with self.subTest(event=event), tempfile.TemporaryDirectory() as tmp:
                code, report, _, runs = self.run_worker(tmp, [event])
                self.assertEqual(code, 1)
                self.assertEqual(report['status'], 'paused')
                self.assertEqual(report['next_sid_advance'], 1901)
                self.assertEqual(report['excluded_tsvs'], [])


if __name__ == '__main__':
    unittest.main()
