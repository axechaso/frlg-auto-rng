import io
from dataclasses import asdict
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from automation.sid_reverse118 import SIDReverseRunRequest
from run_sid_reverse_capture import (
    _find_unique_pid,
    _parse_dex_overrides,
    _parse_initial_levels,
    _run_easycon,
    _safe_print,
    _write_slot_project,
    load_sid_reverse_request,
    main,
)


class SIDReverseCaptureTests(unittest.TestCase):
    UNIQUE_OBSERVATION = (
        "SIDREV|OBS|MON=1|SOURCE=STATIC|LOCATION=|"
        "EVHP=0|EVATK=0|EVDEF=0|EVSPA=0|EVSPD=0|EVSPE=0|"
        "DEX=1|NATURE=0|LEVEL=100|HP=231|ATK=134|DEF=134|"
        "SPA=135|SPD=166|SPE=126\n"
    )

    def test_console_output_falls_back_when_active_code_page_is_ascii(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="ascii")
        _safe_print("SID反查中文", file=stream)
        stream.flush()
        self.assertEqual(raw.getvalue().splitlines(), [b"SID????"])

    def test_parses_active_dex_numbers_and_pads_unused_slots(self):
        self.assertEqual(
            _parse_dex_overrides("25,148", 2),
            (25, 148, 0, 0, 0, 0),
        )

    def test_rejects_zero_dex_for_active_slot(self):
        with self.assertRaisesRegex(ValueError, "活动队伍槽位"):
            _parse_dex_overrides("25,0", 2)

    def test_parses_initial_levels_and_pads_unused_slots(self):
        self.assertEqual(
            _parse_initial_levels("46,55", 2),
            (46, 55, 1, 1, 1, 1),
        )

    def test_loads_gui_plan_request_and_preserves_slot_metadata(self):
        payload = {
            "mode": "sid_reverse_observation",
            "request": {
                "tid": 54321,
                "party_count": 2,
                "game": "lg_nx",
                "nx_model": 2,
                "start_slot": 1,
                "max_candies": 7,
                "recognition_threshold": 88,
                "home_buffer_adaptive_threshold": True,
                "dex_overrides": [25, 148, 0, 0, 0, 0],
                "initial_levels": [46, 55, 1, 1, 1, 1],
                "source_types": [0, 1, 0, 0, 0, 0],
                "locations": ["", "Safari Zone Center", "", "", "", ""],
                "effort_values": [[0, 0, 0, 0, 0, 0]] * 6,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            request = load_sid_reverse_request(path)
        self.assertEqual(request.tid, 54321)
        self.assertEqual(request.dex_overrides[:2], (25, 148))
        self.assertEqual(request.game, "lg_nx")
        self.assertEqual(request.nx_model, 2)
        self.assertTrue(request.home_buffer_adaptive_threshold)
        self.assertEqual(request.initial_levels[:2], (46, 55))
        self.assertEqual(request.source_types[:2], (0, 1))
        self.assertEqual(request.locations[1], "Safari Zone Center")

    @patch("run_sid_reverse_capture.write_sid_reverse_project")
    def test_slot_project_uses_separate_plan_file(self, write_project):
        write_project.return_value = Path("output/main.ecs")
        request = SIDReverseRunRequest(
            tid=17500,
            party_count=2,
            dex_overrides=(18, 143, 0, 0, 0, 0),
            initial_levels=(46, 30, 1, 1, 1, 1),
        )
        result = _write_slot_project(Path("source"), Path("output"), request, 2)
        self.assertEqual(result, Path("output/main.ecs"))
        slot_request = write_project.call_args.args[2]
        self.assertEqual(slot_request.party_count, 1)
        self.assertEqual(slot_request.start_slot, 2)
        self.assertEqual(write_project.call_args.kwargs["copy_assets"], False)
        self.assertEqual(
            write_project.call_args.kwargs["plan_filename"],
            "slot-2-plan.json",
        )

    def test_finds_unique_pid_from_current_slot_observations(self):
        result = _find_unique_pid(
            self.UNIQUE_OBSERVATION,
            pokemon_index=1,
            game="fr_nx",
        )
        self.assertEqual(result, (0x02B0100B, 1))

    @patch("run_sid_reverse_capture.subprocess.Popen")
    def test_easycon_is_terminated_as_soon_as_pid_is_unique(self, popen):
        class FakeProcess:
            def __init__(self, lines):
                self.stdout = iter(lines)
                self.terminated = False

            def terminate(self):
                self.terminated = True

            def wait(self):
                return 1 if self.terminated else 0

        process = FakeProcess(
            [
                "SIDREV|META|TID=17500|COUNT=1\n",
                self.UNIQUE_OBSERVATION,
                "SIDREV|CANDY_LABEL|MON=1|SCORE=97\n",
            ]
        )
        popen.return_value = process

        code, output, stopped = _run_easycon(
            ["runner"],
            Path("output"),
            pokemon_index=1,
            game="fr_nx",
        )

        self.assertEqual(code, 1)
        self.assertTrue(stopped)
        self.assertTrue(process.terminated)
        self.assertIn("SIDREV|PID_UNIQUE|MON=1|PID=02B0100B|OBS=1", output)
        self.assertNotIn("SIDREV|CANDY_LABEL", output)

    @patch("run_sid_reverse_capture.subprocess.Popen")
    def test_easycon_output_is_streamed_before_a_cancel_interrupt(self, popen):
        class InterruptingOutput:
            def __init__(self):
                self.read_count = 0

            def __iter__(self):
                return self

            def __next__(self):
                self.read_count += 1
                if self.read_count == 1:
                    return "SIDREV|ATTEMPT_BEGIN|MON=1|ATTEMPT=1\n"
                raise KeyboardInterrupt

        class FakeProcess:
            def __init__(self):
                self.stdout = InterruptingOutput()
                self.terminated = False

            def terminate(self):
                self.terminated = True

        process = FakeProcess()
        popen.return_value = process
        streamed = []

        with self.assertRaises(KeyboardInterrupt):
            _run_easycon(
                ["runner"],
                Path("output"),
                pokemon_index=1,
                game="fr_nx",
                output_callback=streamed.append,
            )

        self.assertTrue(process.terminated)
        self.assertEqual(
            streamed,
            ["SIDREV|ATTEMPT_BEGIN|MON=1|ATTEMPT=1\n"],
        )

    def test_main_collects_every_requested_slot_before_building_report(self):
        payload = {
            "mode": "sid_reverse_observation",
            "request": {
                "tid": 17500,
                "party_count": 2,
                "game": "fr_nx",
                "start_slot": 1,
                "max_candies": 2,
                "recognition_threshold": 85,
                "dex_overrides": [18, 143, 0, 0, 0, 0],
                "initial_levels": [46, 30, 1, 1, 1, 1],
                "source_types": [1, 0, 0, 0, 0, 0],
                "locations": ["Route 2", "", "", "", "", ""],
                "effort_values": [[0, 0, 0, 0, 0, 0]] * 6,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            request_path.write_text(json.dumps(payload), encoding="utf-8")
            output = root / "output"
            report_path = output / "report.txt"
            slot_paths = [output / "slot-1.ecs", output / "slot-2.ecs"]
            with (
                patch(
                    "run_sid_reverse_capture.probe_easycon_devices",
                    return_value=({"COM4"}, {0}, "devices"),
                ),
                patch(
                    "run_sid_reverse_capture.prepare_compat_runner",
                    return_value=root / "runner.exe",
                ),
                patch("run_sid_reverse_capture.write_sid_reverse_plan"),
                patch(
                    "run_sid_reverse_capture._write_slot_project",
                    side_effect=slot_paths,
                ) as write_slot,
                patch(
                    "run_sid_reverse_capture.validate_runtime",
                    return_value=SimpleNamespace(ok=True, errors=()),
                ),
                patch(
                    "run_sid_reverse_capture.build_run_command",
                    return_value=["runner"],
                ) as build_run_command,
                patch(
                    "run_sid_reverse_capture._run_easycon",
                    side_effect=[
                        (1, "slot 1 complete\n", True),
                        (0, "slot 2 complete\n", False),
                    ],
                ) as run_easycon,
                patch("run_sid_reverse_capture.build_report", return_value="report"),
            ):
                result = main(
                    [
                        "--request-json",
                        str(request_path),
                        "--game",
                        "fr_nx",
                        "--source",
                        str(root),
                        "--ezcon",
                        str(root / "ezcon.exe"),
                        "--output",
                        str(output),
                        "--port",
                        "COM4",
                        "--video",
                        "0",
                        "--report-path",
                        str(report_path),
                    ]
                )
        self.assertEqual(result, 0)
        self.assertEqual(write_slot.call_count, 2)
        self.assertEqual(run_easycon.call_count, 2)
        for call in build_run_command.call_args_list:
            self.assertEqual(call.kwargs["preview_port"], 0)

    def test_main_passes_one_preview_port_to_every_slot(self):
        request = SIDReverseRunRequest(
            tid=17500, party_count=2,
            dex_overrides=(18, 143, 0, 0, 0, 0),
            initial_levels=(46, 30, 1, 1, 1, 1),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            save_payload = {"request": asdict(request)}
            request_path.write_text(json.dumps(save_payload), encoding="utf-8")
            with (
                patch("run_sid_reverse_capture.probe_easycon_devices", return_value=({"COM4"}, {3}, "devices")),
                patch("run_sid_reverse_capture.prepare_compat_runner", return_value=root / "runner.exe"),
                patch("run_sid_reverse_capture.write_sid_reverse_plan"),
                patch("run_sid_reverse_capture._write_slot_project", return_value=root / "main.ecs"),
                patch("run_sid_reverse_capture.validate_runtime", return_value=SimpleNamespace(ok=True, errors=())),
                patch("run_sid_reverse_capture.build_run_command", return_value=["runner"]) as build,
                patch("run_sid_reverse_capture._run_easycon", return_value=(1, "unique\n", True)),
                patch("run_sid_reverse_capture.build_report", return_value="report"),
            ):
                code = main(["--request-json", str(request_path), "--game", "fr_nx",
                             "--source", str(root), "--ezcon", str(root / "ezcon.exe"),
                             "--output", str(root), "--port", "COM4", "--video", "3",
                             "--preview-port", "43123"])
        self.assertEqual(code, 0)
        self.assertEqual(build.call_count, 2)
        self.assertEqual([call.kwargs["preview_port"] for call in build.call_args_list], [43123, 43123])


if __name__ == "__main__":
    unittest.main()
