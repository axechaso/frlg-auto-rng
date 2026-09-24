import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from label_verification import verify_label


class LabelVerificationTests(unittest.TestCase):
    def test_offline_check_uses_native_command_and_preserves_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = root / "runner.exe"
            label = root / "label.IL"
            frame = root / "frame.png"
            runner.touch()
            label.touch()
            frame.touch()
            record = {
                "frame_index": 0, "raw_score": 95.01, "integer_score": 96,
                "operator": ">", "threshold": 95, "passed": True,
                "position": {"x": 10, "y": 20}, "elapsed_ms": 1.2,
            }
            completed = mock.Mock(returncode=0, stdout=json.dumps(record) + "\n", stderr="")
            with mock.patch("label_verification.subprocess.run", return_value=completed) as run:
                result = verify_label(runner, label, frame=frame, operator=">", threshold=95)

            self.assertEqual(result, (record,))
            command = run.call_args.args[0]
            self.assertEqual(command[1], "verify-label")
            self.assertIn("--frame", command)
            self.assertIn("--operator", command)
            self.assertEqual(command[command.index("--threshold") + 1], "95")

    def test_dynamic_check_saves_all_fresh_frames_to_requested_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = root / "runner.exe"
            label = root / "label.IL"
            frames = root / "fresh"
            runner.touch()
            label.touch()
            records = [
                {"frame_index": i, "raw_score": 96.0, "integer_score": 96,
                 "operator": ">", "threshold": 95, "passed": True,
                 "position": {"x": i, "y": i}, "elapsed_ms": 1.0,
                 "saved_frame": str(frames / f"frame-{i + 1:03}.png")}
                for i in range(3)
            ]
            completed = mock.Mock(
                returncode=0,
                stdout="\n".join(json.dumps(item) for item in records),
                stderr="",
            )
            with mock.patch("label_verification.subprocess.run", return_value=completed) as run:
                result = verify_label(
                    runner, label, frames=3, interval_ms=250,
                    save_frames_directory=frames,
                )

            self.assertEqual(len(result), 3)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--frames") + 1], "3")
            self.assertEqual(command[command.index("--save-frames-dir") + 1], str(frames.resolve()))


if __name__ == "__main__":
    unittest.main()
