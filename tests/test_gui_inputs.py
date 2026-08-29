import unittest
from types import SimpleNamespace

from assets.game_text import ABILITY_ZH_TO_EN
from automation.easycon118 import parse_easycon_video_devices
from run_auto_rng_gui import (
    ADVANCED_TAB_LABEL,
    AutoRngApp,
    MODE_TAB_ORDER,
    RUN_LOG_TAB_LABEL,
    SEED_STARTUP_FIXED_USER_HOME,
    SEED_STARTUP_HOME_BUFFER,
    SEED_STARTUP_SCHEME_CODES,
    _install_autocomplete_combo,
    build_egg_config_payload,
    build_egg_full_config_payload,
    build_egg_parent_config_payload,
    clean_terminal_log,
    describe_sid_log_failure,
    filter_autocomplete_choices,
    format_video_device_choice,
    iv_ranges_for_preset,
    parse_egg_config_payload,
    parse_egg_full_config_payload,
    parse_egg_parent_config_payload,
    parse_egg_species,
    parse_iv_ranges,
    parse_sid_effort_values,
    parse_sid_species,
    parse_tid_fixed_delays,
    parse_tid_calibration_result,
    preferred_detected_port,
    preferred_detected_video,
)
from save_profiles import SaveProfile


class GuiIvInputTests(unittest.TestCase):
    def test_save_profile_applies_to_all_relevant_pages(self):
        class FakeVariable:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        variable_names = (
            "sid_game_var",
            "sid_nx_var",
            "sid_tid_var",
            "game_var",
            "nx_var",
            "tid_var",
            "sid_var",
            "tid_game_var",
            "tid_nx_var",
            "tid_target_var",
            "tid_sid_var",
            "tid_language_var",
        )
        app = SimpleNamespace(
            **{name: FakeVariable() for name in variable_names},
            _updating=False,
            _on_game_change=lambda: None,
            _refresh_save_profile_selector=lambda _profile_id: None,
            invalidate_plan=lambda: None,
        )
        profile = SaveProfile.create("叶绿档", "叶绿", 123, 456, 2, language="日文")
        AutoRngApp._apply_save_profile(app, profile, persist=False)

        self.assertEqual(app.sid_game_var.get(), "叶绿")
        self.assertEqual(app.sid_nx_var.get(), "Switch 2")
        self.assertEqual(app.sid_tid_var.get(), "123")
        self.assertEqual(app.game_var.get(), "叶绿")
        self.assertEqual(app.nx_var.get(), "Switch 2")
        self.assertEqual(app.tid_var.get(), "123")
        self.assertEqual(app.sid_var.get(), "456")
        self.assertEqual(app.tid_game_var.get(), "叶绿")
        self.assertEqual(app.tid_nx_var.get(), "Switch 2")
        self.assertEqual(app.tid_target_var.get(), "123")
        self.assertEqual(app.tid_sid_var.get(), "456")
        self.assertEqual(app.tid_language_var.get(), "日文")

    def test_seed_choices_only_apply_when_advanced_mode_is_enabled(self):
        class FakeVariable:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class FakeCombo:
            def __init__(self):
                self.configured = {}

            def configure(self, **kwargs):
                self.configured.update(kwargs)

        app = SimpleNamespace(
            mode_var=FakeVariable("normal"),
            advanced_mode_var=FakeVariable(False),
            seed_calibration_scheme_var=FakeVariable("方案1：实验锁定与毫秒细调"),
            seed_startup_scheme_var=FakeVariable(SEED_STARTUP_FIXED_USER_HOME),
            seed_calibration_scheme_combo=FakeCombo(),
            seed_startup_scheme_combo=FakeCombo(),
            _seed_options_are_advanced=lambda: app.advanced_mode_var.get(),
        )
        AutoRngApp._update_seed_scheme_controls(app)
        self.assertEqual(
            app.seed_calibration_scheme_var.get(),
            "方案0：原始12轮绝对落点众数",
        )
        self.assertEqual(app.seed_startup_scheme_var.get(), SEED_STARTUP_HOME_BUFFER)
        self.assertEqual(app.seed_calibration_scheme_combo.configured["state"], "disabled")

        app.mode_var.set("egg")
        app.advanced_mode_var.set(True)
        app.seed_calibration_scheme_var.set("方案1：实验锁定与毫秒细调")
        app.seed_startup_scheme_var.set(SEED_STARTUP_FIXED_USER_HOME)
        AutoRngApp._update_seed_scheme_controls(app)
        self.assertEqual(app.seed_calibration_scheme_combo.configured["state"], "readonly")
        self.assertEqual(len(app.seed_calibration_scheme_combo.configured["values"]), 3)
        self.assertEqual(app.seed_startup_scheme_var.get(), SEED_STARTUP_FIXED_USER_HOME)

    def test_tid_fixed_delay_log_requires_and_returns_all_four_values(self):
        log = (
            "\x1b[90mOP脚本固定延迟：30550\x1b[0m\n"
            "F1脚本固定延迟: 22050\n"
            "F2脚本固定延迟：4250\n"
            "F3脚本固定延迟：14900\n"
        )
        self.assertEqual(
            parse_tid_fixed_delays(log),
            {"OP": 30550, "F1": 22050, "F2": 4250, "F3": 14900},
        )
        with self.assertRaisesRegex(ValueError, "F3"):
            parse_tid_fixed_delays(log.replace("F3脚本固定延迟：14900\n", ""))

    def test_sid_terminal_log_is_cleaned_and_failure_is_explained(self):
        raw = (
            "\x1b[90m[18:25:45] \x1b[0m性格识别失败，最高匹配度:60\n"
            "System.OperationCanceledException: The operation was canceled.\n"
        )
        cleaned = clean_terminal_log(raw)
        self.assertNotIn("\x1b", cleaned)
        self.assertIn("性格识别失败", cleaned)
        explanation = describe_sid_log_failure(cleaned)
        self.assertIn("没有生成任何 SID 观测", explanation)
        self.assertIn("停止/取消请求", explanation)

    def test_tid_calibration_keeps_recovered_op_correction_with_measured_delays(self):
        log = (
            "OP修正增加50ms：当前修正=50ms，实际固定WAIT=30600ms\n"
            "\x1b[90m[18:00:00] OP修正增加50ms：当前修正=100ms，实际固定WAIT=30650ms\x1b[0m\n"
            "OP脚本固定延迟：30700\nF1脚本固定延迟：22050\n"
            "F2脚本固定延迟：4250\nF3脚本固定延迟：14900\n"
        )
        result = parse_tid_calibration_result(log, 0)
        self.assertEqual(result, {"OP": 30700, "F1": 22050, "F2": 4250, "F3": 14900, "OP_CORRECTION": 100})
        with self.assertRaisesRegex(ValueError, "F3"):
            parse_tid_calibration_result(log.replace("F3脚本固定延迟：14900\n", ""), 0)

    def test_tid_r3_calibration_uses_normalized_value_without_double_model_offset(self):
        log = (
            "OP机型补偿(ms)：-750；OP修正(ms)：0\n"
            "OP实测耗时(ms)：29850；下列OP回填值已还原机型差\n"
            "OP脚本固定延迟：30600\nF1脚本固定延迟：22050\n"
            "F2脚本固定延迟：4250\nF3脚本固定延迟：14900\n"
        )
        result = parse_tid_calibration_result(log, 0)
        self.assertEqual(result["OP"], 30600)
        self.assertEqual(result["OP_CORRECTION"], 0)

    def test_tid_old_calibration_preserves_existing_op_correction(self):
        log = "OP脚本固定延迟：30600\nF1脚本固定延迟：22050\nF2脚本固定延迟：4250\nF3脚本固定延迟：14900\n"
        self.assertEqual(parse_tid_calibration_result(log, -50)["OP_CORRECTION"], -50)

    def test_unrestricted_ability_maps_to_ten_lines_any(self):
        self.assertEqual(ABILITY_ZH_TO_EN["不限"], "Any")

    def test_egg_config_payload_round_trips_requested_fields(self):
        payload = build_egg_config_payload(
            "叶绿",
            2,
            143,
            "50",
            [31, 20, 15, 0, 28, 7],
            [10, 11, 12, 13, 14, 15],
        )
        self.assertEqual(
            payload,
            {
                "version": 1,
                "game": "叶绿",
                "nx_model": 2,
                "egg_species_id": 143,
                "compatibility": 50,
                "parent_a_ivs": [31, 20, 15, 0, 28, 7],
                "parent_b_ivs": [10, 11, 12, 13, 14, 15],
                "start_from_prepared_254": False,
            },
        )
        self.assertEqual(parse_egg_config_payload(payload), payload)

        prepared = dict(payload, start_from_prepared_254=True)
        self.assertTrue(parse_egg_config_payload(prepared)["start_from_prepared_254"])

        legacy = dict(payload)
        legacy.pop("start_from_prepared_254")
        self.assertFalse(parse_egg_config_payload(legacy)["start_from_prepared_254"])

    def test_egg_config_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "相性"):
            build_egg_config_payload("火红", 1, 25, 30, [31] * 6, [31] * 6)
        with self.assertRaisesRegex(ValueError, "亲本A攻击"):
            build_egg_config_payload("火红", 1, 25, 70, [31, 32, 31, 31, 31, 31], [31] * 6)
        with self.assertRaisesRegex(ValueError, "版本"):
            parse_egg_config_payload({"version": 2})
        with self.assertRaisesRegex(ValueError, "布尔值"):
            parse_egg_config_payload(
                {
                    "version": 1,
                    "game": "火红",
                    "nx_model": 1,
                    "egg_species_id": 25,
                    "compatibility": 70,
                    "parent_a_ivs": [31] * 6,
                    "parent_b_ivs": [31] * 6,
                    "start_from_prepared_254": 1,
                }
            )

    def test_egg_parent_config_round_trips_genders_and_ivs(self):
        payload = build_egg_parent_config_payload(
            46,
            50,
            "雌",
            [31, 0, 30, 29, 28, 27],
            "无性别",
            [1, 2, 3, 4, 5, 6],
        )
        self.assertEqual(payload["kind"], "egg_parent")
        self.assertEqual(payload["egg_species_id"], 46)
        self.assertEqual(payload["parent_a_gender"], "雌")
        self.assertEqual(payload["parent_b_gender"], "无性别")
        self.assertEqual(parse_egg_parent_config_payload(payload), payload)

    def test_egg_parent_config_loads_legacy_whole_page_file(self):
        legacy = build_egg_config_payload(
            "火红", 1, 46, 70, [31] * 6, [30] * 6, True
        )
        parent = parse_egg_parent_config_payload(legacy)
        self.assertEqual(parent["kind"], "egg_parent")
        self.assertEqual(parent["egg_species_id"], 46)
        self.assertEqual(parent["parent_a_gender"], "雌")
        self.assertEqual(parent["parent_b_gender"], "雄")
        self.assertNotIn("game", parent)
        self.assertNotIn("start_from_prepared_254", parent)

    def test_egg_full_config_round_trips_all_runtime_inputs(self):
        payload = build_egg_full_config_payload(
            "叶绿",
            2,
            3,
            "0xedde",
            1115,
            3405,
            46,
            50,
            "雌",
            [31, 30, 29, 28, 27, 26],
            "雄",
            [1, 2, 3, 4, 5, 6],
            True,
            True,
            1,
        )
        self.assertEqual(payload["kind"], "egg_full")
        self.assertEqual(payload["target_seed"], "EDDE")
        self.assertEqual(payload["seed_mode"], 3)
        self.assertEqual(payload["held_advances"], 1115)
        self.assertEqual(payload["pickup_advances"], 3405)
        self.assertTrue(payload["start_from_prepared_254"])
        self.assertTrue(payload["home_buffer_adaptive_threshold"])
        self.assertEqual(payload["seed_startup_scheme"], 1)
        self.assertEqual(parse_egg_full_config_payload(payload), payload)

        legacy = dict(payload)
        legacy.pop("seed_startup_scheme")
        self.assertEqual(
            parse_egg_full_config_payload(legacy)["seed_startup_scheme"], 0
        )
        self.assertEqual(SEED_STARTUP_SCHEME_CODES[SEED_STARTUP_HOME_BUFFER], 0)
        self.assertEqual(SEED_STARTUP_SCHEME_CODES[SEED_STARTUP_FIXED_USER_HOME], 1)

    def test_egg_full_config_rejects_wrong_kind_and_invalid_game_mode(self):
        parent = build_egg_parent_config_payload(
            46, 50, "雌", [31] * 6, "雄", [31] * 6
        )
        with self.assertRaisesRegex(ValueError, "不是孵蛋全部配置"):
            parse_egg_full_config_payload(parent)
        with self.assertRaisesRegex(ValueError, "0-9"):
            build_egg_full_config_payload(
                "火红",
                1,
                10,
                "EDDE",
                1115,
                3405,
                46,
                50,
                "雌",
                [31] * 6,
                "雄",
                [31] * 6,
            )
        with self.assertRaisesRegex(ValueError, "Seed启动方案"):
            build_egg_full_config_payload(
                "火红", 1, 0, "EDDE", 1115, 3405, 46, 50,
                "雌", [31] * 6, "雄", [31] * 6, False, False, 2,
            )

    def test_seed_mode_choices_keep_mode_three_for_both_games(self):
        class FakeVariable:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class FakeCombo:
            def __init__(self):
                self.values = ()

            def configure(self, *, values):
                self.values = tuple(values)

        for game in ("火红", "叶绿"):
            app = SimpleNamespace(
                game_var=FakeVariable(game),
                seed_mode_var=FakeVariable("自动选择"),
                egg_seed_mode_var=FakeVariable("请选择"),
                seed_mode_combo=FakeCombo(),
                egg_seed_mode_combo=FakeCombo(),
                _updating=False,
            )
            AutoRngApp._populate_seed_modes(app)
            self.assertIn("3: stereo_h_start_none", app.seed_mode_combo.values)
            self.assertIn("3: stereo_h_start_none", app.egg_seed_mode_combo.values)

    def test_autocomplete_filters_chinese_english_and_location_fragments(self):
        species = ("皮卡丘 (Pikachu)", "雷丘 (Raichu)", "皮皮 (Clefairy)")
        locations = ("2号道路 (Route 2)", "常青森林 (Viridian Forest)")
        self.assertEqual(
            filter_autocomplete_choices(species, "皮卡"),
            ("皮卡丘 (Pikachu)",),
        )
        self.assertEqual(
            filter_autocomplete_choices(species, "pika"),
            ("皮卡丘 (Pikachu)",),
        )
        self.assertEqual(
            filter_autocomplete_choices(locations, "route"),
            ("2号道路 (Route 2)",),
        )
        self.assertEqual(
            filter_autocomplete_choices(locations, "森林"),
            ("常青森林 (Viridian Forest)",),
        )

    def test_autocomplete_puts_prefix_matches_before_contains_matches(self):
        choices = ("X Route 2", "Route 1", "Route 3")
        self.assertEqual(
            filter_autocomplete_choices(choices, "route"),
            ("Route 1", "Route 3", "X Route 2"),
        )
        self.assertEqual(filter_autocomplete_choices(choices, ""), choices)

    def test_autocomplete_selection_commits_value_before_restoring_choices(self):
        class FakeTk:
            def __init__(self):
                self.calls = []

            def call(self, *args):
                self.calls.append(args)

        class FakeCombo:
            def __init__(self):
                self.value = ""
                self.values = ()
                self.bindings = {}
                self.tk = FakeTk()

            def __str__(self):
                return ".species"

            def bind(self, event, callback, add=None):
                self.bindings[event] = (callback, add)

            def get(self):
                return self.value

            def configure(self, *, values):
                self.values = tuple(values)

            def set(self, value):
                self.value = value

        class FakeVariable:
            def __init__(self):
                self.value = "旧值"

            def set(self, value):
                self.value = value

        choices = ("皮卡丘 (Pikachu)", "雷丘 (Raichu)")
        combo = FakeCombo()
        variable = FakeVariable()
        _install_autocomplete_combo(combo, choices, variable)

        combo.value = "pika"
        combo.bindings["<KeyRelease>"][0](SimpleNamespace(keysym="a"))
        self.assertEqual(combo.values, ("皮卡丘 (Pikachu)",))
        self.assertEqual(
            combo.tk.calls,
            [("ttk::combobox::Post", ".species")],
        )
        self.assertEqual(combo.bindings["<KeyRelease>"][1], "+")

        combo.value = "皮卡丘 (Pikachu)"
        combo.bindings["<<ComboboxSelected>>"][0](SimpleNamespace())
        self.assertEqual(variable.value, "皮卡丘 (Pikachu)")
        self.assertEqual(combo.value, "皮卡丘 (Pikachu)")
        self.assertEqual(combo.values, choices)
        self.assertNotIn("<FocusOut>", combo.bindings)

    def test_requested_tab_order(self):
        self.assertEqual(
            MODE_TAB_ORDER,
            ("SID 查找", "TID 乱数", "野生 / 静态", "孵蛋（测试）"),
        )
        self.assertEqual(ADVANCED_TAB_LABEL, "脚本测试（高级）")
        self.assertEqual(RUN_LOG_TAB_LABEL, "运行日志")

    def test_running_log_path_follows_active_mode(self):
        app = SimpleNamespace(
            running_mode="egg",
            script_test_log_path=None,
            sid_log_path=None,
            tid_flow_log_path=None,
            tid_log_path=None,
            egg_log_path="egg.log",
            easycon_log_path="normal.log",
        )
        self.assertEqual(AutoRngApp._current_running_log_path(app), "egg.log")
        app.running_mode = "easycon"
        self.assertEqual(AutoRngApp._current_running_log_path(app), "normal.log")

    def test_manual_ranges_are_parsed_in_stat_order(self):
        minimums, maximums = parse_iv_ranges(
            ["1", "2", "3", "4", "5", "6"],
            ["11", "12", "13", "14", "15", "16"],
        )
        self.assertEqual(minimums, (1, 2, 3, 4, 5, 6))
        self.assertEqual(maximums, (11, 12, 13, 14, 15, 16))

    def test_ten_lines_presets_match_exact_iv_ranges(self):
        expected = {
            "不限": ((0, 31),) * 6,
            "6V": ((31, 31),) * 6,
            "0A": (
                (31, 31), (0, 0), (31, 31),
                (31, 31), (31, 31), (31, 31),
            ),
            "0S": (
                (31, 31), (31, 31), (31, 31),
                (31, 31), (31, 31), (0, 0),
            ),
            "0A0S": (
                (31, 31), (0, 0), (31, 31),
                (31, 31), (31, 31), (0, 0),
            ),
        }
        for preset, ranges in expected.items():
            with self.subTest(preset=preset):
                self.assertEqual(iv_ranges_for_preset(preset), ranges)

    def test_invalid_values_report_the_affected_stat(self):
        cases = (
            (["", "0", "0", "0", "0", "0"], ["31"] * 6, "HP"),
            (["0"] * 6, ["31", "x", "31", "31", "31", "31"], "攻击"),
            (["0", "0", "-1", "0", "0", "0"], ["31"] * 6, "防御"),
            (["0"] * 6, ["31", "31", "31", "32", "31", "31"], "特攻"),
            (["0", "0", "0", "0", "20", "0"], ["31", "31", "31", "31", "10", "31"], "特防"),
        )
        for minimums, maximums, stat in cases:
            with self.subTest(stat=stat):
                with self.assertRaisesRegex(ValueError, stat):
                    parse_iv_ranges(minimums, maximums)

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(ValueError):
            iv_ranges_for_preset("5V")

    def test_detected_port_keeps_valid_selection_or_uses_lowest_number(self):
        self.assertEqual(preferred_detected_port({"COM12", "COM4"}, "COM12"), "COM12")
        self.assertEqual(preferred_detected_port({"COM12", "COM4"}, "COM22"), "COM4")
        self.assertIsNone(preferred_detected_port(set(), "COM22"))

    def test_detected_video_lists_names_and_keeps_valid_index(self):
        output = "[0] Hagibis\n[3] OBS Virtual Camera\n[7]\n"
        devices = parse_easycon_video_devices(output)
        self.assertEqual(devices, {0: "Hagibis", 3: "OBS Virtual Camera", 7: "未命名设备"})
        self.assertEqual(format_video_device_choice(3, devices[3]), "[3] OBS Virtual Camera")
        self.assertEqual(
            preferred_detected_video(devices, "[3] 旧设备名"),
            "[3] OBS Virtual Camera",
        )
        self.assertEqual(preferred_detected_video(devices, "5"), "[0] Hagibis")
        self.assertIsNone(preferred_detected_video({}, "0"))

    def test_sid_effort_values_require_six_valid_stats(self):
        self.assertEqual(
            parse_sid_effort_values(("0", "4", "8", "12", "16", "20"), 1),
            (0, 4, 8, 12, 16, 20),
        )
        with self.assertRaisesRegex(ValueError, "第2位.*六项"):
            parse_sid_effort_values(("0", "0"), 2)
        with self.assertRaisesRegex(ValueError, "总和"):
            parse_sid_effort_values(("255", "255", "255", "0", "0", "0"), 3)
        with self.assertRaisesRegex(ValueError, "第4位攻击"):
            parse_sid_effort_values(("0", "x", "0", "0", "0", "0"), 4)

    def test_sid_species_accepts_chinese_english_display_and_dex(self):
        self.assertEqual(parse_sid_species("皮卡丘", 1), 25)
        self.assertEqual(parse_sid_species("Pikachu", 1), 25)
        self.assertEqual(parse_sid_species("皮卡丘 (Pikachu)", 1), 25)
        self.assertEqual(parse_sid_species("25", 1), 25)
        self.assertEqual(parse_sid_species("大葱鸭", 1), 83)

    def test_egg_species_accepts_typed_chinese_english_display_and_dex(self):
        self.assertEqual(parse_egg_species("派拉斯"), 46)
        self.assertEqual(parse_egg_species("Paras"), 46)
        self.assertEqual(parse_egg_species("派拉斯 (Paras)"), 46)
        self.assertEqual(parse_egg_species("46"), 46)
        self.assertEqual(parse_egg_species("Farfetch’d"), 83)

    def test_egg_species_rejects_blank_and_unknown_names(self):
        with self.assertRaisesRegex(ValueError, "孵蛋蛋种"):
            parse_egg_species("")
        with self.assertRaisesRegex(ValueError, "无法识别孵蛋蛋种"):
            parse_egg_species("不是宝可梦")

    def test_sid_species_rejects_blank_and_unknown_names(self):
        with self.assertRaisesRegex(ValueError, "第2位"):
            parse_sid_species("", 2)
        with self.assertRaisesRegex(ValueError, "无法识别.*第3位"):
            parse_sid_species("不是宝可梦", 3)

    def test_sid_party_rows_follow_selected_shiny_count(self):
        class FakeVariable:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        class FakeWidget:
            def __init__(self):
                self.state = None

            def configure(self, *, state):
                self.state = state

        app = object.__new__(AutoRngApp)
        app.sid_count_var = FakeVariable("2")
        app.sid_party_row_widgets = [
            ((FakeWidget(), "normal"), (FakeWidget(), "readonly"))
            for _ in range(6)
        ]
        app._refresh_sid_party_rows()
        self.assertEqual(
            [[widget.state for widget, _ in row] for row in app.sid_party_row_widgets],
            [
                ["normal", "readonly"],
                ["normal", "readonly"],
                ["disabled", "disabled"],
                ["disabled", "disabled"],
                ["disabled", "disabled"],
                ["disabled", "disabled"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
