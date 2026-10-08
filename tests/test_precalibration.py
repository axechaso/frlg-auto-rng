import hashlib
import json
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from automation.easycon118 import (
    EGG_HOME_BUFFER_OVERRIDE_MARKER,
    EGG_TEMPLATE_NAME,
    STANDARD_HOME_BUFFER_OVERRIDE_MARKER,
    STANDARD_TEMPLATE_NAME,
    EggRunRequest,
    EasyCon118Options,
    write_configured_egg_project,
    write_configured_project,
    validate_generated_egg_project_consistency,
    validate_generated_project_consistency,
)
from automation.planner import AutoSearchRequest, search_best_plan
from automation.precalibration import (
    PrecalibrationContext,
    PrecalibrationFrameScope,
    build_marker,
    context_key,
    read_record,
    parse_marker,
    update_from_log,
    update_from_manifest,
    update_record,
)
from automation.seed_modes import seed_mode_to_settings
from rng.tenlines_utils import IVs, InitialSeedResult, SearcherResult


SOURCE_118 = Path(__file__).resolve().parents[1] / "local_assets" / "easycon118"


def make_plan(*, static: bool = False, nx_model: int = 1):
    pokemon = "Bulbasaur" if static else "Pikachu"
    request = AutoSearchRequest(
        game=f"fr_{'nx2' if nx_model == 2 else 'nx'}",
        tid=12345,
        sid=54321,
        method="Static 1" if static else "Wild",
        category="Starter" if static else "Grass",
        location="" if static else "Viridian Forest",
        pokemon=pokemon,
        max_advances=5000,
        seed_mode=1,
    )
    target = SearcherResult(
        target_seed="12345678",
        method="Static 1" if static else "Wild 1",
        pokemon=pokemon,
        level=5 if static else 3,
        pid="00000001",
        shiny="Star",
        nature="Timid",
        ability="Overgrow" if static else "Static",
        ivs=IVs(31, 30, 29, 28, 27, 26),
        hidden_type="Electric",
        hidden_power=70,
        gender="M",
    )
    initial = InitialSeedResult(
        seed="9C76",
        advances=1600,
        total_frames=1600,
        total_time="00:00:13",
        seed_time=40490,
        settings=seed_mode_to_settings(1),
    )
    return search_best_plan(
        request,
        target_search=lambda **_: [target],
        seed_search=lambda **_: [initial],
    ).plan


def make_egg_request(**changes):
    values = {
        "game": "fr_nx",
        "seed_mode": 1,
        "target_seed": "75D1",
        "held_advances": 8021,
        "pickup_advances": 10021,
        "species_id": 148,
        "compatibility": 70,
        "parent_a_gender": "雌",
        "parent_a_ivs": (31, 30, 29, 28, 27, 26),
        "parent_b_gender": "雄",
        "parent_b_ivs": (0, 1, 2, 3, 4, 5),
    }
    values.update(changes)
    return EggRunRequest(**values)


class PrecalibrationStoreTests(unittest.TestCase):
    def test_target_shiny_marker_saves_successful_offsets_without_reverse_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = PrecalibrationContext("fr", 1, 1, "TIMELINE", "STATIC", 0)
            scope = PrecalibrationFrameScope(1, False)
            manifest = root / "plan.json"
            manifest.write_text(json.dumps({"precalibration": {
                "enabled": True, "context": context.to_dict(),
                "frame_scope": scope.to_dict(), "frame_enabled": True,
                "target_shiny_success": {"enabled": True, "species_id": 144},
            }}), encoding="utf-8")
            marker = build_marker(context, seed_index=-7, frame_pre=23,
                                  frame_enabled=True, frame_scope=scope)
            for stage in (0, 1):
                with self.subTest(stage=stage):
                    store = root / f"precalibration-{stage}.json"
                    text = (
                        "[11:41:25.702] 时差检测到出闪\n"
                        f"\x1b[90m[11:41:25.702]\x1b[0m {marker}"
                        f"|EVIDENCE=TARGET_SHINY|TARGET_DEX=144|ROUND=8|SHINY_STAGE={stage}|SHINY_END=1\n"
                        "目标获取流程结束，停止脚本\n脚本运行完成\n"
                    )
                    record = update_from_manifest(store, manifest, text)
                    self.assertEqual(record["seed_ns1"], -7)
                    self.assertEqual(record["frame_ns1"], 23)
                    self.assertEqual(read_record(store, context, frame_scope=scope), record)

    def test_target_shiny_writeback_rejects_other_target_and_disabled_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = PrecalibrationContext("fr", 1, 1, "FORMAL", "STATIC", 0)
            scope = PrecalibrationFrameScope(1, False)
            store = root / "precalibration.json"
            update_record(store, context, {"seed_ns1": -6})
            original = store.read_bytes()
            manifest = root / "plan.json"
            config = {"enabled": True, "context": context.to_dict(),
                      "frame_scope": scope.to_dict(), "frame_enabled": False,
                      "target_shiny_success": {"enabled": True, "species_id": 144}}
            marker = build_marker(context, seed_index=9, frame_pre=-17,
                                  frame_enabled=False, frame_scope=scope)
            marker += "|EVIDENCE=TARGET_SHINY|TARGET_DEX=144|ROUND=8|SHINY_STAGE=0|SHINY_END=1"
            for change in (
                {"target_shiny_success": {"enabled": True, "species_id": 145}},
                {"target_shiny_success": {"enabled": False, "species_id": 144}},
                {"target_shiny_success": None},
                {"frame_enabled": True},
                {"frame_scope": PrecalibrationFrameScope(0, False).to_dict()},
            ):
                with self.subTest(change=change):
                    manifest.write_text(json.dumps({"precalibration": config | change}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        update_from_manifest(store, manifest, marker)
                    self.assertEqual(store.read_bytes(), original)
            manifest.write_text(json.dumps({"precalibration": config}), encoding="utf-8")
            record = update_from_manifest(store, manifest, marker)
            self.assertEqual(record["seed_ns1"], 9)
            self.assertIsNone(record["frame_ns1"])

    def test_target_shiny_evidence_must_be_complete_and_is_not_sid_proof(self):
        context = PrecalibrationContext("fr", 1, 1, "TIMELINE", "STATIC", 0)
        marker = build_marker(context, seed_index=-3, frame_pre=7, frame_enabled=True,
                              frame_scope=PrecalibrationFrameScope(1, False))
        marker += "|EVIDENCE=TARGET_SHINY|TARGET_DEX=144|ROUND=8|SHINY_STAGE=0|SHINY_END=1"
        self.assertIsNotNone(parse_marker(marker))
        for invalid in (
            marker.replace("|TARGET_DEX=144", ""),
            marker.replace("|ROUND=8", ""),
            marker.replace("|SHINY_STAGE=0", ""),
            marker.replace("|SHINY_END=1", ""),
            marker.replace("SHINY_END=1", "SHINY_END=0"),
            marker.replace("TARGET_DEX=144", "TARGET_DEX=0"),
            marker.replace("TARGET_DEX=144", "TARGET_DEX=387"),
            marker.replace("ROUND=8", "ROUND=0"),
            marker.replace("SHINY_STAGE=0", "SHINY_STAGE=2"),
            marker.replace("EVIDENCE=TARGET_SHINY", "EVIDENCE=UNKNOWN"),
            marker.replace("KIND=STATIC", "KIND=STARTER"),
            marker.replace("V=2", "V=1"),
        ):
            with self.subTest(marker=invalid):
                self.assertIsNone(parse_marker(invalid))

    def test_seed_startup_schemes_never_share_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "precalibration.json"
            scheme0 = PrecalibrationContext("fr", 1, 1, "FORMAL", "WILD", 0)
            scheme1 = PrecalibrationContext("fr", 1, 1, "FORMAL", "WILD", 1)
            frame_scope = PrecalibrationFrameScope(1, False)
            update_record(
                path, scheme0, {"seed_ns1": -4, "frame_ns1": 12},
                frame_scope=frame_scope,
            )
            self.assertIsNone(read_record(path, scheme1))
            update_record(
                path, scheme1, {"seed_ns1": 7, "frame_ns1": -8},
                frame_scope=frame_scope,
            )
            self.assertEqual(read_record(path, scheme0, frame_scope=frame_scope)["seed_ns1"], -4)
            self.assertEqual(read_record(path, scheme1, frame_scope=frame_scope)["seed_ns1"], 7)

    def test_legacy_record_is_visible_only_to_startup_scheme_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "precalibration.json"
            legacy_context = {
                "game": "fr",
                "nx_model": 2,
                "seed_mode": 3,
                "entry": "TIMELINE",
                "kind": "STATIC",
            }
            encoded = json.dumps(
                legacy_context,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            legacy_key = hashlib.sha256(encoded).hexdigest()
            path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "records": {
                            legacy_key: {
                                "context": legacy_context,
                                "seed_ns2": 5,
                                "frame_ns2": 33,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            scheme0 = PrecalibrationContext("fr", 2, 3, "TIMELINE", "STATIC", 0)
            scheme1 = PrecalibrationContext("fr", 2, 3, "TIMELINE", "STATIC", 1)
            old = read_record(path, scheme0)
            self.assertEqual(old["seed_ns2"], 5)
            self.assertIsNone(old["frame_ns2"])
            self.assertEqual(old["legacy_frames"]["frame_ns2"], 33)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema"], 1)
            self.assertIsNone(read_record(path, scheme1))

    def test_flow_types_and_nx_fields_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "precalibration.json"
            static = PrecalibrationContext("fr", 1, 1, "FORMAL", "STATIC", 0)
            starter = PrecalibrationContext("fr", 1, 1, "FORMAL", "STARTER", 0)
            nx2 = PrecalibrationContext("fr", 2, 1, "FORMAL", "STARTER", 0)
            scope = PrecalibrationFrameScope(1, False)
            update_record(path, static, {"seed_ns1": 1})
            update_record(path, starter, {"seed_ns1": 2, "frame_ns1": 20}, frame_scope=scope)
            update_record(path, nx2, {"seed_ns2": 3, "frame_ns2": 30}, frame_scope=scope)
            self.assertEqual(read_record(path, static)["seed_ns1"], 1)
            self.assertEqual(read_record(path, starter, frame_scope=scope)["seed_ns1"], 2)
            self.assertEqual(read_record(path, nx2, frame_scope=scope)["seed_ns2"], 3)

    def test_marker_mismatch_and_malformed_store_never_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "precalibration.json"
            context = PrecalibrationContext("fr", 1, 1, "FORMAL", "WILD", 0)
            wrong = PrecalibrationContext("fr", 1, 1, "FORMAL", "WILD", 1)
            marker = build_marker(
                wrong,
                seed_index=4,
                frame_enabled=True,
                frame_pre=25,
            )
            with self.assertRaisesRegex(ValueError, "上下文不一致"):
                update_from_log(path, context, marker)
            self.assertFalse(path.exists())

            path.write_text("{broken", encoding="utf-8")
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "原文件保留"):
                update_from_log(
                    path,
                    context,
                    build_marker(
                        context,
                        seed_index=4,
                        frame_enabled=True,
                        frame_pre=25,
                    ),
                )
            self.assertEqual(path.read_bytes(), original)

    def test_no_success_marker_means_no_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "precalibration.json"
            context = PrecalibrationContext("fr", 1, 1, "FORMAL", "WILD", 0)
            self.assertIsNone(update_from_log(path, context, "普通运行日志"))
            self.assertFalse(path.exists())

    def test_manifest_without_a_success_marker_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "precalibration.json"
            manifest_path = root / "plan.json"
            context = PrecalibrationContext("fr", 1, 1, "FORMAL", "STATIC", 0)
            update_record(store, context, {"seed_ns1": -6})
            original = store.read_bytes()
            manifest_path.write_text(json.dumps({
                "precalibration": {
                    "enabled": True,
                    "context": context.to_dict(),
                    "frame_scope": PrecalibrationFrameScope(1, False).to_dict(),
                },
            }), encoding="utf-8")
            logs = (
                "[11:41:25.702] 时差检测到出闪\n"
                "[11:41:25.702] 目标获取流程结束，停止脚本\n"
                "脚本运行完成FRLG_INPUT_SESSION|V=1|STATE=ENDED|END=1\n",
                "[11:41:25.702] 已识别到出闪，脚本停止\n",
                "普通运行日志\n",
                "",
            )
            for text in logs:
                with self.subTest(log=text):
                    self.assertIsNone(update_from_manifest(store, manifest_path, text))
                    self.assertEqual(store.read_bytes(), original)
            self.assertEqual(list(root.glob("*.bak")), [])

    def test_manifest_rejects_a_present_but_invalid_success_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "precalibration.json"
            manifest_path = root / "plan.json"
            context = PrecalibrationContext("fr", 1, 1, "FORMAL", "STATIC", 0)
            scope = PrecalibrationFrameScope(1, False)
            update_record(store, context, {"seed_ns1": -6})
            original = store.read_bytes()
            manifest_path.write_text(json.dumps({
                "precalibration": {
                    "enabled": True, "context": context.to_dict(),
                    "frame_scope": scope.to_dict(),
                },
            }), encoding="utf-8")
            complete = build_marker(
                context, seed_index=4, frame_enabled=False, frame_scope=scope,
            )
            for text in (
                "PRECALIBRATION_UPDATE",
                "PRECALIBRATION_UPDATE|V=2|GAME=FR",
                complete.replace("|SEED_INDEX=4", "|SEED_INDEX=bad"),
                complete.replace("|GIFT=0", "|GIFT=bad"),
            ):
                with self.subTest(marker=text):
                    with self.assertRaisesRegex(ValueError, "不完整或格式无效"):
                        update_from_manifest(store, manifest_path, text)
                    self.assertEqual(store.read_bytes(), original)
            updated = update_from_manifest(store, manifest_path, complete)
            self.assertEqual(updated["seed_ns1"], 4)
            self.assertIsNone(updated["frame_ns1"])

    def test_frame_scope_isolated_while_seed_values_are_shared(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "precalibration.json"
            context = PrecalibrationContext("fr", 2, 3, "TIMELINE", "STATIC", 0)
            off = PrecalibrationFrameScope(0, False)
            gift = PrecalibrationFrameScope(1, True)
            update_record(path, context, {"seed_ns2": 17, "frame_ns2": -4}, frame_scope=off)
            update_record(path, context, {"frame_ns2": 29}, frame_scope=gift)
            self.assertEqual(read_record(path, context, frame_scope=off)["seed_ns2"], 17)
            self.assertEqual(read_record(path, context, frame_scope=off)["frame_ns2"], -4)
            self.assertEqual(read_record(path, context, frame_scope=gift)["seed_ns2"], 17)
            self.assertEqual(read_record(path, context, frame_scope=gift)["frame_ns2"], 29)
            self.assertIsNone(read_record(path, context)["frame_ns2"])

    def test_schema_one_write_backups_exact_bytes_and_keeps_old_frames_historical(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "precalibration.json"
            context = PrecalibrationContext("fr", 1, 1, "FORMAL", "WILD", 0)
            legacy_record = {
                "context": context.to_dict(), "seed_ns1": 3, "frame_ns1": -7,
            }
            payload = {"schema": 1, "records": {context_key(context): legacy_record}}
            original = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            path.write_bytes(original)
            scope = PrecalibrationFrameScope(1, False)
            update_record(path, context, {"seed_ns1": 4, "frame_ns1": 22}, frame_scope=scope)
            backups = list(path.parent.glob("precalibration.json.schema1-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            migrated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema"], 2)
            stored = migrated["records"][context_key(context)]
            self.assertEqual(stored["legacy_frames"]["frame_ns1"], -7)
            self.assertEqual(stored["frames"]["parity=1;gift=0"]["frame_ns1"], 22)

    def test_legacy_marker_updates_seed_but_never_scoped_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "precalibration.json"
            context = PrecalibrationContext("fr", 1, 1, "FORMAL", "WILD", 0)
            marker = build_marker(
                context, seed_index=8, frame_enabled=True, frame_pre=99,
            )
            updated = update_from_log(path, context, marker)
            self.assertEqual(updated["seed_ns1"], 8)
            self.assertIsNone(updated["frame_ns1"])
            stored = json.loads(path.read_text(encoding="utf-8"))["records"][context_key(context)]
            self.assertEqual(stored["frames"], {})

@unittest.skipUnless(SOURCE_118.is_dir(), "requires materialized EasyCon assets")
class PrecalibrationGenerationTests(unittest.TestCase):
    def test_regular_success_marker_matches_each_generated_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for template_name in (STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME):
                for static in (False, True):
                    for nx_model in (1, 2):
                        with self.subTest(template=template_name, static=static, nx=nx_model):
                            output = root / f"{template_name}-{static}-{nx_model}"
                            store = output / "precalibration.json"
                            plan = make_plan(static=static, nx_model=nx_model)
                            options = EasyCon118Options(nx_model=nx_model, update_precalibration=True)
                            main = write_configured_project(
                                SOURCE_118, output, plan, options,
                                template_name=template_name, precalibration_store_path=store,
                            )
                            validate_generated_project_consistency(
                                main, plan, options, template_name=template_name,
                            )
                            manifest_path = main.parent / "plan.json"
                            config = json.loads(manifest_path.read_text(encoding="utf-8"))["precalibration"]
                            text = main.read_text(encoding="utf-8")
                            self.assertTrue(config["target_shiny_success"]["enabled"])
                            self.assertEqual(config["target_shiny_success"]["species_id"], plan.species_id)
                            self.assertIn("CALL 清空最近出闪检测\n        CALL 开始反查识图轮次", text)
                            self.assertIn("IF $本轮流程结果 == -1\n            $预校准目标出闪写回结果 = 记录目标出闪预校准(0)", text)
                            self.assertIn("IF $反查细分成功 == -2\n            $预校准目标出闪写回结果 = 记录目标出闪预校准(1)", text)
                            helper = text.split("FUNC 记录目标出闪预校准($来源: INT): INT", 1)[1].split("\nENDFUNC", 1)[0]
                            for unsafe in ("WAIT ", "@", "CAPTURE", "CALL 打开", "CALL 抓捕"):
                                self.assertNotIn(unsafe, helper)
                            self.assertIn("$Seed累计修正索引", helper)
                            self.assertIn("$消耗帧实际执行修正量", helper)
                            self.assertNotIn("$命中差索引", helper)
                            self.assertNotIn("$本轮消耗帧误差", helper)
                            self.assertIn(f"读取最近出闪检测图鉴编号() != {plan.species_id}", helper)
                            self.assertIn("|EVIDENCE=TARGET_SHINY|", helper)
                            block = text.split("FUNC 执行自动校准与等待更新(): INT", 1)[1].split("\nENDFUNC", 1)[0]
                            hit_condition = (
                                "IF $道具乱数模式 == 0 and $命中差索引 == 0 and "
                                "$本轮消耗帧误差 == 0 and $本轮物种命中 == 1"
                            )
                            self.assertLess(block.index(hit_condition), block.index("PRECALIBRATION_UPDATE"))
                            marker_lines = [line for line in block.splitlines() if "PRECALIBRATION_UPDATE" in line]
                            self.assertEqual(len(marker_lines), 1)
                            marker_line = marker_lines[0]
                            head = marker_line.split('"', 2)[1]
                            enabled = re.search(r'"\|FRAME_ENABLED=([01])"', marker_line).group(1)
                            # Exercise the actual generated context/fields, with
                            # deterministic simulated runtime correction values.
                            marker = f"{head}4|FRAME_PRE=-17|FRAME_ENABLED={enabled}"
                            parsed = parse_marker(marker)
                            self.assertIsNotNone(parsed)
                            updated = update_from_manifest(store, manifest_path, f"\x1b[90m[11:41:25.702]\x1b[0m {marker}\n")
                            seed_field = f"seed_ns{nx_model}"
                            frame_field = f"frame_ns{nx_model}"
                            self.assertEqual(updated[seed_field], 4)
                            expected_frame = -17 if config["frame_enabled"] else None
                            self.assertEqual(updated[frame_field], expected_frame)
                            persisted = read_record(store, config["context"], frame_scope=config["frame_scope"])
                            self.assertEqual(persisted[seed_field], 4)
                            self.assertEqual(persisted[frame_field], expected_frame)

    def test_identity_verification_item_mode_and_disabled_writeback_keep_old_terminals(self):
        from automation.target_verification import TargetVerificationSpec, validate_injected_target_verification
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = make_plan(static=True)
            spec = TargetVerificationSpec("offline", "attempt", plan.initial_seed.seed,
                                          plan.initial_seed.advances, plan.species_id,
                                          plan.target.method, plan.target.pid)
            for name, options, verification in (
                ("disabled", EasyCon118Options(update_precalibration=False), None),
                ("starter-proof", EasyCon118Options(update_precalibration=True,
                                                   precalibration_context_kind="STARTER"), None),
                ("sid-proof", EasyCon118Options(update_precalibration=True), spec),
                ("items", EasyCon118Options(update_precalibration=True, item_rng_mode=True), None),
            ):
                with self.subTest(name=name):
                    selected = make_plan() if name == "items" else plan
                    main = write_configured_project(
                        SOURCE_118, root / name, selected, options,
                        precalibration_store_path=root / "unused.json", target_verification=verification,
                    )
                    text = main.read_text(encoding="utf-8")
                    self.assertNotIn("GUI_TARGET_SHINY_PRECALIBRATION", text)
                    self.assertNotIn("CALL 记录目标出闪预校准", text)
                    if verification:
                        validate_injected_target_verification(text, verification)
                    manifest = json.loads((main.parent / "plan.json").read_text(encoding="utf-8"))
                    self.assertFalse(manifest["precalibration"]["target_shiny_success"]["enabled"])

    def test_formal_static_loads_seed_but_disables_frame_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "precalibration.json"
            context = PrecalibrationContext("fr", 1, 1, "FORMAL", "STATIC", 0)
            update_record(
                store, context, {"seed_ns1": -6, "frame_ns1": 91},
                frame_scope=PrecalibrationFrameScope(1, False),
            )
            main = write_configured_project(
                SOURCE_118,
                root / "project",
                make_plan(static=True),
                EasyCon118Options(nx_model=1, update_precalibration=True),
                template_name=STANDARD_TEMPLATE_NAME,
                precalibration_store_path=store,
            )
            text = main.read_text(encoding="utf-8")
            manifest = json.loads((main.parent / "plan.json").read_text(encoding="utf-8"))
            self.assertIn("$Seed预校准索引_NS1 = -6", text)
            self.assertIn("$消耗帧预校准修正_NS1 = 0", text)
            self.assertIn("|ENTRY=FORMAL|KIND=STATIC|PARITY=1|GIFT=0|SEED_INDEX=", text)
            self.assertIn('"|FRAME_ENABLED=0"', text)
            self.assertIn(STANDARD_HOME_BUFFER_OVERRIDE_MARKER, text)
            self.assertNotIn(EGG_HOME_BUFFER_OVERRIDE_MARKER, text)
            self.assertEqual(
                manifest["runtime_overrides"]["home_buffer_controller"],
                "FORMAL",
            )
            self.assertFalse(manifest["precalibration"]["frame_enabled"])
            self.assertEqual(manifest["precalibration"]["loaded"]["frame_ns1"], 91)

    def test_timeline_static_loads_its_own_seed_and_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "precalibration.json"
            context = PrecalibrationContext("fr", 1, 1, "TIMELINE", "STATIC", 1)
            update_record(
                store, context, {"seed_ns1": 8, "frame_ns1": -17},
                frame_scope=PrecalibrationFrameScope(1, False),
            )
            main = write_configured_project(
                SOURCE_118,
                root / "project",
                make_plan(static=True),
                EasyCon118Options(
                    nx_model=1,
                    seed_startup_scheme=1,
                    update_precalibration=True,
                ),
                template_name=EGG_TEMPLATE_NAME,
                precalibration_store_path=store,
            )
            text = main.read_text(encoding="utf-8")
            manifest = json.loads((main.parent / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["template"], EGG_TEMPLATE_NAME)
            self.assertIn("$Seed预校准索引_NS1 = 8", text)
            self.assertIn("$消耗帧预校准修正_NS1 = -17", text)
            self.assertIn("|STARTUP=1|ENTRY=TIMELINE|KIND=STATIC|", text)
            self.assertIn(EGG_HOME_BUFFER_OVERRIDE_MARKER, text)
            self.assertNotIn(STANDARD_HOME_BUFFER_OVERRIDE_MARKER, text)
            self.assertEqual(
                manifest["runtime_overrides"]["home_buffer_controller"],
                "TIMELINE",
            )
            self.assertTrue(manifest["precalibration"]["frame_enabled"])

    def test_formal_and_timeline_projects_match_their_selected_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = make_plan(static=True)
            for template_name in (STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME):
                with self.subTest(template_name=template_name):
                    main = write_configured_project(
                        SOURCE_118,
                        root / template_name,
                        plan,
                        EasyCon118Options(nx_model=1),
                        template_name=template_name,
                    )
                    validate_generated_project_consistency(
                        main,
                        plan,
                        EasyCon118Options(nx_model=1),
                        template_name=template_name,
                    )

    def test_togepi_static_generation_clears_stale_name_and_writes_dex(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = make_plan(static=True)
            plan = replace(
                plan,
                request=replace(plan.request, pokemon="Togepi"),
                target=replace(plan.target, pokemon="Togepi"),
            )
            main = write_configured_project(
                SOURCE_118,
                root / "project",
                plan,
                EasyCon118Options(nx_model=1),
                template_name=EGG_TEMPLATE_NAME,
            )
            text = main.read_text(encoding="utf-8")
            self.assertIn('$目标宝可梦名称 = ""', text)
            self.assertIn("$目标全国图鉴编号 = 175", text)
            self.assertNotIn('$目标宝可梦名称 = "哈克龙"', text)

    def test_egg_loads_dynamic_held_pickup_and_manifest_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "precalibration.json"
            context = PrecalibrationContext("fr", 1, 1, "TIMELINE", "EGG", 1)
            frame_scope = PrecalibrationFrameScope(1, False)
            update_record(
                store,
                context,
                {"seed_ns1": 9, "held_pre": -12, "pickup_pre": 21},
                frame_scope=frame_scope,
            )
            main = write_configured_egg_project(
                SOURCE_118,
                root / "project",
                make_egg_request(
                    seed_startup_scheme=1,
                    update_precalibration=True,
                ),
                template_name=EGG_TEMPLATE_NAME,
                precalibration_store_path=store,
            )
            text = main.read_text(encoding="utf-8")
            manifest_path = main.parent / "plan.json"
            self.assertIn("$Seed预校准索引_NS1 = 9", text)
            self.assertIn("$孵蛋Held动态预校准帧 = -12", text)
            self.assertIn("$孵蛋Pickup动态预校准帧 = 21", text)
            self.assertIn("|ENTRY=TIMELINE|KIND=EGG|PARITY=1|GIFT=0|SEED_INDEX=", text)
            marker = build_marker(
                context,
                seed_index=10,
                frame_enabled=True,
                frame_scope=frame_scope,
                held_pre=-13,
                pickup_pre=22,
            )
            updated = update_from_manifest(store, manifest_path, marker)
            self.assertEqual(updated["seed_ns1"], 10)
            self.assertEqual(updated["held_pre"], -13)
            self.assertEqual(updated["pickup_pre"], 22)

    def test_egg_formal_and_timeline_projects_match_selected_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = make_egg_request(record_shiny_video=True)
            for template_name in (STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME):
                with self.subTest(template_name=template_name):
                    main = write_configured_egg_project(
                        SOURCE_118,
                        root / template_name,
                        request,
                        template_name=template_name,
                    )
                    validate_generated_egg_project_consistency(
                        main,
                        request,
                        template_name=template_name,
                    )
                    text = main.read_text(encoding="utf-8")
                    self.assertIn("$出闪录像 = 1", text)

                    tampered = text.replace("$出闪录像 = 1", "$出闪录像 = 0", 1)
                    main.write_text(tampered, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "出闪录像"):
                        validate_generated_egg_project_consistency(
                            main,
                            request,
                            template_name=template_name,
                        )


if __name__ == "__main__":
    unittest.main()
