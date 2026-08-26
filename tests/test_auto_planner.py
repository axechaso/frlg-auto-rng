import unittest
from pathlib import Path

from automation.easycon118 import (
    EasyCon118Options,
    EXPECTED_SCRIPT_SHA256,
    SUPPORTED_RUNTIME_SCRIPT_SHA256S,
    configure_template_text,
    inspect_label_corpus,
    inspect_script_corpus,
    is_supported_script_input_sha256,
    is_supported_runtime_script_sha256,
    plan_to_user_values,
)
from automation.planner import (
    AutoSearchRequest,
    NoMatchingTargetError,
    NoReachablePlanError,
    SearchCancelledError,
    search_best_plan,
)
from automation.seed_modes import seed_mode_to_settings, settings_to_seed_mode
from automation.support import RouteSupportLevel, get_route_support
from automation.static_targets import (
    PLANNER_STATIC_CATEGORIES,
    STATIC_TARGETS_BY_GAME,
    is_supported_static_target,
)
from rng.tenlines_utils import IVs, InitialSeedResult, SearcherResult, calibration


def target(seed: str, ivs: tuple[int, ...], pid: str = "00000001") -> SearcherResult:
    return SearcherResult(
        target_seed=seed,
        method="Wild 1",
        pokemon="Pikachu",
        level=3,
        pid=pid,
        shiny="Star",
        nature="Timid",
        ability="Static",
        ivs=IVs(*ivs),
        hidden_type="Electric",
        hidden_power=70,
        gender="M",
    )


def route(seed: str, advances: int, mode: int = 0, seed_time: int = 40000):
    return InitialSeedResult(
        seed=seed,
        advances=advances,
        total_frames=advances,
        total_time="00:00:00",
        seed_time=seed_time,
        settings=seed_mode_to_settings(mode),
    )


def request(**overrides) -> AutoSearchRequest:
    values = {
        "game": "fr_nx",
        "tid": 12345,
        "sid": 54321,
        "method": "Wild",
        "category": "Grass",
        "location": "Viridian Forest",
        "pokemon": "Pikachu",
        "max_advances": 1000,
    }
    values.update(overrides)
    return AutoSearchRequest(**values)


class PlannerSelectionTests(unittest.TestCase):
    def run_plan(self, targets, routes, **request_overrides):
        return search_best_plan(
            request(**request_overrides),
            target_search=lambda **_: targets,
            seed_search=lambda target_seed, **_: routes.get(target_seed, []),
        )

    def test_higher_iv_total_wins_before_lower_advance(self):
        high = target("00000001", (30, 30, 30, 30, 30, 30))
        low = target("00000002", (30, 30, 30, 30, 30, 29))
        result = self.run_plan(
            [low, high],
            {
                high.target_seed: [route("1111", 500)],
                low.target_seed: [route("2222", 10)],
            },
        )
        self.assertEqual(result.plan.target.target_seed, high.target_seed)
        self.assertEqual(result.plan.iv_total, 180)
        self.assertEqual(result.plan.initial_seed.advances, 500)

    def test_equal_iv_total_uses_smallest_advance(self):
        first = target("00000001", (31, 31, 31, 31, 31, 25))
        second = target("00000002", (30, 30, 30, 30, 30, 30))
        result = self.run_plan(
            [first, second],
            {
                first.target_seed: [route("1111", 400)],
                second.target_seed: [route("2222", 50)],
            },
        )
        self.assertEqual(result.plan.target.target_seed, second.target_seed)
        self.assertEqual(result.plan.initial_seed.advances, 50)

    def test_unreachable_high_iv_falls_back_to_next_iv_tier(self):
        high = target("00000001", (31, 31, 31, 31, 31, 31))
        lower = target("00000002", (30, 30, 30, 30, 30, 30))
        result = self.run_plan(
            [high, lower],
            {
                high.target_seed: [route("1111", 1001)],
                lower.target_seed: [route("2222", 999)],
            },
        )
        self.assertEqual(result.plan.target.target_seed, lower.target_seed)

    def test_seed_mode_is_a_hard_route_filter(self):
        item = target("00000001", (31, 31, 31, 31, 31, 31))
        result = self.run_plan(
            [item],
            {item.target_seed: [route("1111", 10, mode=0), route("2222", 20, mode=6)]},
            seed_mode=6,
        )
        self.assertEqual(result.plan.initial_seed.seed, "2222")
        self.assertEqual(result.plan.seed_mode, 6)

    def test_no_target_and_no_route_have_distinct_errors(self):
        with self.assertRaises(NoMatchingTargetError):
            self.run_plan([], {})
        item = target("00000001", (31, 31, 31, 31, 31, 31))
        with self.assertRaises(NoReachablePlanError):
            self.run_plan([item], {item.target_seed: []})

    def test_tiered_search_can_be_cancelled(self):
        with self.assertRaises(SearchCancelledError):
            search_best_plan(
                request(),
                target_tier_search=lambda **_: iter(()),
                cancel_check=lambda: True,
            )

    def test_cancel_during_seed_lookup_cannot_return_a_plan(self):
        cancelled = False

        def seed_search(**_):
            nonlocal cancelled
            cancelled = True
            return [route("1111", 10)]

        with self.assertRaises(SearchCancelledError):
            search_best_plan(
                request(),
                target_search=lambda **_: [target("00000001", (31,) * 6)],
                seed_search=seed_search,
                cancel_check=lambda: cancelled,
            )

    def test_rng_config_uses_16_bit_seed_and_explicit_seed_time(self):
        item = target("12345678", (31, 31, 31, 31, 31, 31))
        result = self.run_plan([item], {item.target_seed: [route("9E2E", 500, seed_time=37798)]})
        config = result.plan.to_rng_config()
        self.assertEqual(config.target.seed_hex, 0x9E2E)
        self.assertEqual(config.target.seed_time, 37798)
        self.assertEqual(config.target.advances, 500)
        self.assertEqual(config.target.method, "Wild 1")


class CompatibilityTests(unittest.TestCase):
    IMPORTED_LABEL_DIR = (
        Path(__file__).resolve().parents[1]
        / "local_assets"
        / "easycon118"
        / "ImgLabel"
    )
    DOWNLOADED_LABEL_DIR = (
        Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8" / "ImgLabel"
    )
    LABEL_DIR = (
        IMPORTED_LABEL_DIR
        if IMPORTED_LABEL_DIR.is_dir()
        else DOWNLOADED_LABEL_DIR
    )

    def test_all_118_seed_modes_round_trip(self):
        for mode in range(10):
            self.assertEqual(settings_to_seed_mode(seed_mode_to_settings(mode)), mode)

    def test_fire_red_rejects_seed_mode_missing_from_118_table(self):
        with self.assertRaisesRegex(ValueError, "模式 3"):
            request(game="fr_nx", seed_mode=3).validate()

    def test_leaf_green_accepts_seed_mode_three(self):
        request(game="lg_nx", seed_mode=3).validate()

    def test_static_whitelist_accepts_national_dex_input(self):
        AutoSearchRequest(
            game="fr_nx",
            tid=1,
            sid=2,
            method="Static 1",
            category="Starter",
            location="Starter",
            pokemon="1",
            max_advances=1000,
        ).validate()

    def test_roaming_is_blocked_until_bugged_iv_ranking_is_implemented(self):
        with self.assertRaisesRegex(ValueError, "截断 IV"):
            AutoSearchRequest(
                game="fr_nx",
                tid=1,
                sid=2,
                method="Static 1",
                category="Roaming",
                location="Roaming",
                pokemon="Raikou",
                max_advances=1000,
            ).validate()

    def test_safari_support_matrix_is_conservative(self):
        west_rod = get_route_support("Wild", "SuperRod", "Safari Zone West")
        east_grass = get_route_support("Wild", "Grass", "Safari Zone East")
        surf = get_route_support("Wild", "Surfing", "Safari Zone Center")
        self.assertEqual(west_rod.level, RouteSupportLevel.BASELINE_118)
        self.assertTrue(west_rod.can_start)
        self.assertTrue(east_grass.can_start)
        self.assertFalse(surf.can_start)

    def test_minimum_advance_is_applied_before_route_selection(self):
        item = target("00000001", (31,) * 6)
        result = search_best_plan(
            request(min_advances=3000, max_advances=5000),
            target_search=lambda **_: [item],
            seed_search=lambda **_: [route("1111", 2500), route("2222", 3500)],
        )
        self.assertEqual(result.plan.initial_seed.seed, "2222")

    def test_direct_seed_mode_skips_target_search(self):
        request_value = request(
            seed_mode=0,
            direct_mode=True,
            direct_seed="11C7",
            direct_advances=4321,
        )
        result = search_best_plan(
            request_value,
            target_search=lambda **_: (_ for _ in ()).throw(AssertionError("search called")),
        )
        self.assertEqual(result.plan.initial_seed.seed, "11C7")
        self.assertEqual(result.plan.initial_seed.advances, 4321)

    def test_direct_seed_mode_requires_explicit_seed_mode(self):
        with self.assertRaisesRegex(ValueError, "必须选择 Seed 模式"):
            request(direct_mode=True, direct_seed="9E2E", direct_advances=1).validate()

    def test_118_static_whitelist_has_version_specific_thirty_targets(self):
        for game in ("fr", "lg"):
            self.assertEqual(sum(map(len, STATIC_TARGETS_BY_GAME[game].values())), 30)
        self.assertTrue(is_supported_static_target("fr_nx", "GameCorner", "Scyther"))
        self.assertFalse(is_supported_static_target("fr_nx", "GameCorner", "Pinsir"))
        self.assertTrue(is_supported_static_target("lg_nx", "GameCorner", "Pinsir"))
        self.assertFalse(is_supported_static_target("lg_nx", "GameCorner", "Scyther"))
        self.assertEqual(len(PLANNER_STATIC_CATEGORIES), 7)
        self.assertNotIn("Roaming", PLANNER_STATIC_CATEGORIES)

    def test_rock_smash_is_search_only_even_outside_safari(self):
        support = get_route_support("Wild", "RockSmash", "Route 10")
        self.assertEqual(support.level, RouteSupportLevel.UNSUPPORTED)
        self.assertFalse(support.can_start)

    def test_118_template_replaces_only_user_values(self):
        item = target("12345678", (31, 31, 31, 31, 31, 31))
        result = search_best_plan(
            request(seed_mode=6, max_advances=200000),
            target_search=lambda **_: [item],
            seed_search=lambda **_: [route("9C76", 100020, mode=6)],
        )
        names = (
            "游戏版本文本", "Seed模式", "NX机型", "目标Seed", "目标消耗帧",
            "目标全国图鉴编号", "静态或野生", "宝可梦遭遇方法",
            "宝可梦遭遇地点", "麻痹", "点到为止", "出闪后继续抓捕",
        )
        template = "\n".join(f'${name} = "old"' for name in names)
        template += "\n# ============================进阶设置\n$内部参数 = 1"
        configured = configure_template_text(
            template,
            result.plan,
            EasyCon118Options(nx_model=1),
        )
        self.assertIn('$Seed模式 = 6', configured)
        self.assertIn('$目标Seed = "9C76"', configured)
        self.assertIn('$目标消耗帧 = 100020', configured)
        self.assertIn('$静态或野生 = "野生"', configured)

        values = plan_to_user_values(result.plan)
        self.assertEqual(values["目标全国图鉴编号"], 25)

    def test_118_template_requires_marker_and_matching_nx_model(self):
        item = target("12345678", (31,) * 6)
        result = search_best_plan(
            request(seed_mode=6, max_advances=200000),
            target_search=lambda **_: [item],
            seed_search=lambda **_: [route("9C76", 100020, mode=6)],
        )
        with self.assertRaisesRegex(ValueError, "分界标记"):
            configure_template_text("$游戏版本文本 = \"火红\"", result.plan)
        with self.assertRaisesRegex(ValueError, "NX 机型 1"):
            plan_to_user_values(result.plan, EasyCon118Options(nx_model=2))

    @unittest.skipUnless(LABEL_DIR.is_dir(), "local 1.1.8 label package is not present")
    def test_real_118_label_manifest(self):
        manifest = inspect_label_corpus(self.LABEL_DIR)
        self.assertEqual(manifest["count"], 1150)
        self.assertEqual(manifest["methods"], {1: 17, 3: 1, 5: 777, 11: 1, 14: 354})
        self.assertEqual(
            manifest["sha256"],
            "00d2fbfa9a3638f3cea64553e94b777ed8c5c63f813125617b50aaeed7c9d10e",
        )

    @unittest.skipUnless(LABEL_DIR.is_dir(), "local 1.1.8 package is not present")
    def test_real_118_script_manifest(self):
        manifest = inspect_script_corpus(self.LABEL_DIR.parent)
        self.assertEqual(manifest["count"], 33)
        self.assertIn(
            manifest["sha256"],
            (EXPECTED_SCRIPT_SHA256, *SUPPORTED_RUNTIME_SCRIPT_SHA256S),
        )
        self.assertEqual(
            manifest["templates"],
            [
                "NS火叶全自动一键乱数1.1.8.ecs",
                "NS火叶全自动一键乱数1.1.8-TV时间轴测试.ecs",
            ],
        )

    def test_controlled_egg_window_variant_is_an_audited_runtime_input(self):
        self.assertTrue(
            is_supported_runtime_script_sha256(
                "4843f4044e69dc4bc0eb2f3506490651589e531fe2d3b2bad905a6b977c3eec0"
            )
        )
        self.assertFalse(is_supported_runtime_script_sha256("not-a-script-hash"))

    def test_latest_egg_no_egg_escape_corpus_is_audited(self):
        self.assertTrue(
            is_supported_script_input_sha256(
                "92f5870f09c28b55a583a9ea5ddf4d23a55af4e847220c0aade35d7e66bb52f5"
            )
        )
        self.assertTrue(
            is_supported_runtime_script_sha256(
                "b7d3cf56cc3018522548514a279a950176b136c938dcceda90f60b9b133d2d57"
            )
        )

    def test_real_search_plan_calibration_round_trip(self):
        real_request = AutoSearchRequest(
            game="fr_nx",
            tid=58888,
            sid=12232,
            method="Static",
            category="Starter",
            location="Starter",
            pokemon="Bulbasaur",
            max_advances=100000,
            iv_min=(29, 31, 27, 29, 29, 30),
            iv_max=(29, 31, 27, 29, 29, 30),
            shiny="Star/Square",
        )
        plan = search_best_plan(real_request).plan
        rows = calibration(
            game=real_request.game,
            tid=real_request.tid,
            sid=real_request.sid,
            method=plan.target.method,
            category=real_request.category,
            location=real_request.location,
            pokemon=real_request.pokemon,
            seed=plan.initial_seed.seed,
            advances=plan.initial_seed.advances,
            settings=plan.initial_seed.settings,
            seed_bias=0,
            advances_bias=0,
        )
        self.assertTrue(any(
            f"{row.pid:08X}" == plan.target.pid and row.ivs == plan.target.ivs
            for row in rows
        ))


if __name__ == "__main__":
    unittest.main()
