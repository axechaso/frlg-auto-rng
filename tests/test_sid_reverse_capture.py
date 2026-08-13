import json
import tempfile
import unittest
from pathlib import Path

from run_sid_reverse_capture import _parse_dex_overrides, load_sid_reverse_request


class SIDReverseCaptureTests(unittest.TestCase):
    def test_parses_active_dex_numbers_and_pads_unused_slots(self):
        self.assertEqual(
            _parse_dex_overrides("25,148", 2),
            (25, 148, 0, 0, 0, 0),
        )

    def test_rejects_zero_dex_for_active_slot(self):
        with self.assertRaisesRegex(ValueError, "活动队伍槽位"):
            _parse_dex_overrides("25,0", 2)

    def test_loads_gui_plan_request_and_preserves_slot_metadata(self):
        payload = {
            "mode": "sid_reverse_observation",
            "request": {
                "tid": 54321,
                "party_count": 2,
                "start_slot": 1,
                "max_candies": 7,
                "recognition_threshold": 88,
                "dex_overrides": [25, 148, 0, 0, 0, 0],
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
        self.assertEqual(request.source_types[:2], (0, 1))
        self.assertEqual(request.locations[1], "Safari Zone Center")


if __name__ == "__main__":
    unittest.main()
