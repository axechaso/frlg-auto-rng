import tempfile
import unittest
from pathlib import Path
from unittest import mock

import rng.tenlines as tenlines
import tenlines_seed_updater as updater


def sample_tables():
    fr = updater.NxSeedTable(
        raw_times=(100, 116),
        modes={
            "mono_h_a": (0x0010, None),
            "stereo_h_a": (0x1234, 0x5678),
            "mono_h_start": (0xABCD, 0x0000),
        },
    )
    lg = updater.NxSeedTable(
        raw_times=(200, 216),
        modes={
            "mono_h_a": (0x0020, 0x0030),
            "stereo_h_a": (0x2234, 0x6678),
            "mono_h_start": (0xBBCD, None),
            "stereo_r_a": (0xCAFE, 0xBEEF),
        },
    )
    return fr, lg


class SeedTableBinaryTests(unittest.TestCase):
    def test_mode_three_uses_help_start_and_never_lr_a(self):
        _, lg = sample_tables()
        self.assertEqual(updater.CANONICAL_NX_ENGLISH_MODES[3], "stereo_h_start")
        self.assertEqual(updater.canonical_seed_modes(lg)[3], (None, None))
        with_start = updater.NxSeedTable(
            raw_times=lg.raw_times,
            modes={**lg.modes, "stereo_h_start": (0x0000, 0x1234)},
        )
        self.assertEqual(updater.canonical_seed_modes(with_start)[3], (0, 0x1234))
        for index in (0, 1, 2, 4, 5, 6, 7, 8, 9):
            self.assertEqual(updater.canonical_seed_modes(lg)[index],
                             updater.canonical_seed_modes(with_start)[index])

    def test_legacy_mode_three_migration_is_idempotent_and_preserves_correct_tables(self):
        old = ('#   3 = stereo_r_a\n# mode 3 = stereo_r_a\n'
               '$Seed_HEX_叶绿_m3 = ["CAFE","BEEF"]\n'
               '$Seed_HEX_叶绿_m4 = ["1234",""]\n')
        upgraded = updater.upgrade_legacy_mode3_table(old, "叶绿")
        self.assertIn('#   3 = stereo_h_start', upgraded)
        self.assertIn('$Seed_HEX_叶绿_m3 = ["",""]', upgraded)
        self.assertIn('$Seed_HEX_叶绿_m4 = ["1234",""]', upgraded)
        self.assertEqual(updater.upgrade_legacy_mode3_table(upgraded, "叶绿"), upgraded)
        correct = old.replace("stereo_r_a", "stereo_h_start")
        self.assertEqual(updater.upgrade_legacy_mode3_table(correct, "叶绿"), correct)

    def test_binary_round_trip_preserves_blank_entries(self):
        fr, _ = sample_tables()
        encoded = updater.encode_nx_seed_binary(fr)
        self.assertEqual(updater.decode_nx_seed_binary(encoded), fr)
        with self.assertRaisesRegex(updater.SeedTableUpdateError, "过短"):
            updater.decode_nx_seed_binary(b"\x01")

    def test_easycon_render_uses_canonical_modes_and_blackout_offset(self):
        fr, _ = sample_tables()
        text = updater.render_easycon_seed_table(
            "fr",
            fr,
            source_sha256="a" * 64,
            generated_at="2026-08-25 12:00:00 +0800",
        )
        self.assertIn("RETURN 1", text)
        self.assertIn('$Seed_HEX_火红_m3 = ["",""]', text)
        self.assertIn('$Seed_HEX_火红_m4 = ["FFEC",""]', text)
        self.assertIn('$Seed_HEX_火红_m5 = ["FFEC",""]', text)
        self.assertIn("$Seed_Raw_火红 = [100,116]", text)


class SeedTableStoreTests(unittest.TestCase):
    def test_update_activates_all_four_files_and_second_check_is_noop(self):
        fr, lg = sample_tables()
        fr_data = updater.encode_nx_seed_binary(fr)
        lg_data = updater.encode_nx_seed_binary(lg)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(
                updater,
                "_fetch_bytes",
                side_effect=[fr_data, lg_data, fr_data, lg_data],
            ), mock.patch.object(updater, "_validate_easycon_candidate") as validate:
                first = updater.update_seed_tables(
                    source_directory=root / "source",
                    ezcon_path=root / "ezcon.exe",
                    data_root=root,
                )
                second = updater.update_seed_tables(
                    source_directory=root / "source",
                    ezcon_path=root / "ezcon.exe",
                    data_root=root,
                )
            self.assertTrue(first.updated)
            self.assertFalse(second.updated)
            self.assertEqual(validate.call_count, 1)
            active = root / "seed_tables" / "current"
            manifest = updater.verify_seed_table_directory(active)
            self.assertEqual(manifest["games"]["fr"]["record_count"], 2)
            for filename in (
                updater.FR_BINARY_NAME,
                updater.LG_BINARY_NAME,
                updater.FR_ECS_NAME,
                updater.LG_ECS_NAME,
            ):
                self.assertTrue((active / filename).is_file())

    def test_corrupt_active_file_is_rejected(self):
        fr, lg = sample_tables()
        fr_data = updater.encode_nx_seed_binary(fr)
        lg_data = updater.encode_nx_seed_binary(lg)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(
                updater, "_fetch_bytes", side_effect=[fr_data, lg_data]
            ), mock.patch.object(updater, "_validate_easycon_candidate"):
                result = updater.update_seed_tables(
                    source_directory=root,
                    ezcon_path=root / "ezcon.exe",
                    data_root=root,
                )
            (result.active_directory / updater.FR_BINARY_NAME).write_bytes(b"broken")
            with self.assertRaisesRegex(updater.SeedTableUpdateError, "校验失败"):
                updater.active_seed_table_directory(root)

    def test_easycon_overlay_copies_only_a_valid_active_pair(self):
        fr, lg = sample_tables()
        fr_data = updater.encode_nx_seed_binary(fr)
        lg_data = updater.encode_nx_seed_binary(lg)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(
                updater, "_fetch_bytes", side_effect=[fr_data, lg_data]
            ), mock.patch.object(updater, "_validate_easycon_candidate"):
                result = updater.update_seed_tables(
                    source_directory=root,
                    ezcon_path=root / "ezcon.exe",
                    data_root=root,
                )
            lib = root / "project" / "lib"
            lib.mkdir(parents=True)
            metadata = updater.apply_easycon_seed_table_overrides(lib, root)
            self.assertEqual(
                (lib / updater.FR_ECS_NAME).read_bytes(),
                (result.active_directory / updater.FR_ECS_NAME).read_bytes(),
            )
            self.assertEqual(metadata["source_fingerprint"], result.source_fingerprint)

    def test_tenlines_loader_prefers_active_binary_and_cache_can_be_cleared(self):
        fr, _ = sample_tables()
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / updater.FR_BINARY_NAME
            binary.write_bytes(updater.encode_nx_seed_binary(fr))
            tenlines.clear_frlg_seed_cache()
            with mock.patch.object(tenlines, "active_seed_binary_path", return_value=binary):
                seed_map, contiguous = tenlines.load_frlg_seed_data("fr_nx")
            self.assertIn(0x0010, seed_map)
            self.assertEqual(contiguous["mono_h_a"][0]["seed_time"], 5837)
            tenlines.clear_frlg_seed_cache()

    def test_old_active_cache_is_rerendered_without_mutating_it(self):
        fr, lg = sample_tables()
        lg = updater.NxSeedTable(lg.raw_times, {**lg.modes, "stereo_h_start": (0, 0x1234)})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(updater, "_fetch_bytes", side_effect=[
                updater.encode_nx_seed_binary(fr), updater.encode_nx_seed_binary(lg),
            ]), mock.patch.object(updater, "_validate_easycon_candidate"), \
                 mock.patch.object(updater, "UPDATER_VERSION", "1.0.0"):
                result = updater.update_seed_tables(
                    source_directory=root, ezcon_path=root / "ezcon.exe", data_root=root,
                )
            original = {p.name: p.read_bytes() for p in result.active_directory.iterdir()}
            lib = root / "project" / "lib"
            lib.mkdir(parents=True)
            updater.apply_easycon_seed_table_overrides(lib, root)
            configured = (lib / updater.LG_ECS_NAME).read_text(encoding="utf-8-sig")
            self.assertIn('$Seed_HEX_叶绿_m3 = ["0000","1234"]', configured)
            self.assertEqual(original, {p.name: p.read_bytes() for p in result.active_directory.iterdir()})


if __name__ == "__main__":
    unittest.main()
