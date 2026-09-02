import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.easycon118 import (
    EGG_TEMPLATE_NAME,
    STANDARD_TEMPLATE_NAME,
    EggRunRequest,
    EasyCon118Options,
    write_configured_egg_project,
    write_configured_project,
)
from automation.planner import AutoSearchRequest, search_best_plan
from automation.precalibration import (
    PrecalibrationContext,
    build_marker,
    read_record,
    update_from_log,
    update_from_manifest,
    update_record,
)
from automation.seed_modes import seed_mode_to_settings
from rng.tenlines_utils import IVs, InitialSeedResult, SearcherResult
from run_auto_rng_gui import AutoRngApp


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
    def test_seed_startup_schemes_never_share_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "precalibration.json"
            scheme0 = PrecalibrationContext("fr", 1, 1, "FORMAL", "WILD", 0)
            scheme1 = PrecalibrationContext("fr", 1, 1, "FORMAL", "WILD", 1)
            update_record(path, scheme0, {"seed_ns1": -4, "frame_ns1": 12})
            self.assertIsNone(read_record(path, scheme1))
            update_record(path, scheme1, {"seed_ns1": 7, "frame_ns1": -8})
            self.assertEqual(read_record(path, scheme0)["seed_ns1"], -4)
            self.assertEqual(read_record(path, scheme1)["seed_ns1"], 7)

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
            self.assertEqual(read_record(path, scheme0)["frame_ns2"], 33)
            self.assertIsNone(read_record(path, scheme1))

    def test_flow_types_and_nx_fields_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "precalibration.json"
            static = PrecalibrationContext("fr", 1, 1, "FORMAL", "STATIC", 0)
            starter = PrecalibrationContext("fr", 1, 1, "FORMAL", "STARTER", 0)
            nx2 = PrecalibrationContext("fr", 2, 1, "FORMAL", "STARTER", 0)
            update_record(path, static, {"seed_ns1": 1})
            update_record(path, starter, {"seed_ns1": 2, "frame_ns1": 20})
            update_record(path, nx2, {"seed_ns2": 3, "frame_ns2": 30})
            self.assertEqual(read_record(path, static)["seed_ns1"], 1)
            self.assertEqual(read_record(path, starter)["seed_ns1"], 2)
            self.assertEqual(read_record(path, nx2)["seed_ns2"], 3)

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

    def test_gui_completion_reads_the_full_log_before_updating(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            main = project / "main.ecs"
            main.write_text("", encoding="utf-8")
            context = PrecalibrationContext("fr", 1, 1, "FORMAL", "WILD", 0)
            (project / "plan.json").write_text(
                json.dumps(
                    {
                        "precalibration": {
                            "enabled": True,
                            "context": context.to_dict(),
                        }
                    }
                ),
                encoding="utf-8",
            )
            log = root / "run.log"
            log.write_text(
                build_marker(
                    context,
                    seed_index=-2,
                    frame_enabled=True,
                    frame_pre=31,
                )
                + "\n"
                + ("tail\n" * 20000),
                encoding="utf-8",
            )
            store = root / "precalibration.json"
            with patch(
                "run_auto_rng_gui.DEFAULT_PRECALIBRATION_STORE_PATH",
                store,
            ):
                note = AutoRngApp._update_completed_precalibration(main, log, 0)
            self.assertIn("预校准已更新", note)
            self.assertEqual(read_record(store, context)["frame_ns1"], 31)

    def test_gui_nonzero_exit_never_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "precalibration.json"
            with patch(
                "run_auto_rng_gui.DEFAULT_PRECALIBRATION_STORE_PATH",
                store,
            ):
                note = AutoRngApp._update_completed_precalibration(
                    root / "main.ecs",
                    root / "run.log",
                    2,
                )
            self.assertIsNone(note)
            self.assertFalse(store.exists())


@unittest.skipUnless(SOURCE_118.is_dir(), "requires materialized EasyCon assets")
class PrecalibrationGenerationTests(unittest.TestCase):
    def test_formal_static_loads_seed_but_disables_frame_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "precalibration.json"
            context = PrecalibrationContext("fr", 1, 1, "FORMAL", "STATIC", 0)
            update_record(store, context, {"seed_ns1": -6, "frame_ns1": 91})
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
            self.assertIn("|ENTRY=FORMAL|KIND=STATIC|SEED_INDEX=", text)
            self.assertIn('"|FRAME_ENABLED=0"', text)
            self.assertFalse(manifest["precalibration"]["frame_enabled"])
            self.assertEqual(manifest["precalibration"]["loaded"]["frame_ns1"], 91)

    def test_timeline_static_loads_its_own_seed_and_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "precalibration.json"
            context = PrecalibrationContext("fr", 1, 1, "TIMELINE", "STATIC", 1)
            update_record(store, context, {"seed_ns1": 8, "frame_ns1": -17})
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
            self.assertTrue(manifest["precalibration"]["frame_enabled"])

    def test_egg_loads_dynamic_held_pickup_and_manifest_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "precalibration.json"
            context = PrecalibrationContext("fr", 1, 1, "TIMELINE", "EGG", 1)
            update_record(
                store,
                context,
                {"seed_ns1": 9, "held_pre": -12, "pickup_pre": 21},
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
            self.assertIn("|ENTRY=TIMELINE|KIND=EGG|SEED_INDEX=", text)
            marker = build_marker(
                context,
                seed_index=10,
                frame_enabled=True,
                held_pre=-13,
                pickup_pre=22,
            )
            updated = update_from_manifest(store, manifest_path, marker)
            self.assertEqual(updated["seed_ns1"], 10)
            self.assertEqual(updated["held_pre"], -13)
            self.assertEqual(updated["pickup_pre"], 22)


if __name__ == "__main__":
    unittest.main()
