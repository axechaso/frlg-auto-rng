import unittest

from automation.target_verification import (
    MARKER,
    TargetVerificationSpec,
    inject_target_verification,
    parse_target_verification,
    validate_injected_target_verification,
    _event_line,
)


class TargetVerificationTests(unittest.TestCase):
    def setUp(self):
        self.spec = TargetVerificationSpec(
            run_id="run-1",
            attempt_id="attempt-1",
            target_seed="1234ABCD",
            target_advances=1901,
            species_id=1,
            method="Static1",
            pid_hex="89ABCDEF",
        )
        self.template = '''$脚本版本 = "2.0"
    IF $道具乱数模式 == 0 and @出闪 >= $识图阈值
        PRINT ""
        PRINT 已识别到出闪，脚本停止
        RETURN 0
    ENDIF
    IF $道具乱数模式 == 0 and @出闪 >= $识图阈值
        PRINT 已识别到出闪，脚本停止
        RETURN 0
    ENDIF
        $本轮流程结果 = 执行RNG启动与目标获取()
    IF $道具乱数模式 == 0 and $命中差索引 == 0 and $本轮消耗帧误差 == 0 and $本轮物种命中 == 1
        PRINT 已命中目标，脚本停止
    ENDIF
    IF $命中差索引 == 0 and $本轮消耗帧误差 == 0 and $本轮物种命中 == 0
        PRINT 未命中目标
    ENDIF
    $循环计数 += 1
'''

    def test_injection_is_idempotent_and_keeps_star_observation_separate(self):
        injected = inject_target_verification(self.template, self.spec)
        self.assertEqual(inject_target_verification(injected, self.spec), injected)
        self.assertEqual(injected.count(MARKER), 1)
        self.assertEqual(injected.count("$SID遍历本轮出闪 = 0"), 2)
        self.assertEqual(injected.count("EVENT=TARGET"), 2)
        self.assertIn("EVENT=NON_TARGET_SHINY", injected)
        self.assertIn("EVENT=INCOMPLETE", injected)
        validate_injected_target_verification(injected, self.spec)

    def test_injection_rejects_missing_or_duplicate_anchors(self):
        with self.assertRaisesRegex(ValueError, "英/日"):
            inject_target_verification(self.template.replace("RETURN 0", "RETURN 1", 1), self.spec)
        with self.assertRaisesRegex(ValueError, "锚点"):
            inject_target_verification(self.template + self.template.split("    $循环计数 += 1")[0], self.spec)

    def test_upstream_shiny_minus_two_is_adapted_without_changing_evidence_rules(self):
        latest = self.template.replace("        RETURN 0\n", "        RETURN -2\n")
        injected = inject_target_verification(latest, self.spec)
        validate_injected_target_verification(injected, self.spec)
        self.assertEqual(inject_target_verification(injected, self.spec), injected)
        self.assertEqual(injected.count("$SID遍历本轮出闪 = 1"), 2)
        self.assertNotIn("RETURN -2", injected)
        with self.assertRaisesRegex(ValueError, "英/日"):
            inject_target_verification(
                self.template.replace("        RETURN 0\n", "        RETURN -2\n", 1), self.spec
            )

    def test_only_one_complete_current_attempt_event_is_accepted(self):
        event = (
            "SIDTRAVERSAL|V=1|RUN=run-1|ATTEMPT=attempt-1|ROUND=4|EVENT=TARGET|"
            "SEED_MATCH=1|ADV_MATCH=1|SPECIES_MATCH=1|SHINY=1|END=1"
        )
        proof = parse_target_verification(event, run_id="run-1", attempt_id="attempt-1")
        self.assertTrue(proof["complete"])
        self.assertTrue(proof["shiny"])
        self.assertIsNone(parse_target_verification(event[:-1], run_id="run-1", attempt_id="attempt-1"))
        self.assertIsNone(parse_target_verification(event, run_id="run-1", attempt_id="other"))
        self.assertIsNone(parse_target_verification(event + "\n" + event, run_id="run-1", attempt_id="attempt-1"))
        self.assertIsNone(parse_target_verification(event.replace("SHINY=1", "SHINY=true"), run_id="run-1", attempt_id="attempt-1"))

    def test_generated_print_terminates_with_a_separate_string_operand(self):
        for shiny in ("0", "1"):
            self.assertTrue(_event_line(self.spec, "TARGET", shiny=shiny).endswith(shiny + ' & "|END=1"'))

    def test_real_cli_prefix_is_accepted_but_quoted_or_malformed_events_are_not(self):
        event = "SIDTRAVERSAL|V=1|RUN=run-1|ATTEMPT=attempt-1|ROUND=4|EVENT=TARGET|SEED_MATCH=1|ADV_MATCH=1|SPECIES_MATCH=1|SHINY=1|END=1"
        wrapped = "\ufeff\x1b[32m[01:23:45.678] " + event + "\x1b[0m"
        self.assertIsNotNone(parse_target_verification(wrapped, run_id="run-1", attempt_id="attempt-1"))
        for invalid in ("引用：" + event, event + '"', "[99:23:45.678] " + event, "\n\ufeff" + event, wrapped + "\n" + event):
            self.assertIsNone(parse_target_verification(invalid, run_id="run-1", attempt_id="attempt-1"))

    def test_old_injection_requires_regeneration_and_corrupt_new_events_are_rejected(self):
        injected = inject_target_verification(self.template, self.spec)
        with self.assertRaisesRegex(ValueError, "重新生成"):
            inject_target_verification(injected.replace(MARKER, "# SIDTRAVERSAL_TARGET_VERIFICATION_V1"), self.spec)
        with self.assertRaises(ValueError):
            validate_injected_target_verification(injected.replace('|END=1"', '|END=1""', 1), self.spec)

    def test_unrelated_round_updates_are_not_evidence_exit_anchors(self):
        source = 'FUNC unrelated\n    $循环计数 += 1\nENDFUNC\n' + self.template + 'ENDFUNC\nFUNC other\n    $循环计数 += 1\nENDFUNC\n'
        injected = inject_target_verification(source,self.spec)
        self.assertIn('FUNC unrelated\n    $循环计数 += 1\nENDFUNC',injected)
        self.assertIn('FUNC other\n    $循环计数 += 1\nENDFUNC',injected)
        validate_injected_target_verification(injected,self.spec)


if __name__ == "__main__":
    unittest.main()
