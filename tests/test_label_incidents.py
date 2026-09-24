import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from label_incidents import LabelIncidentStore, validate_incident


def incident_payload(incident_id="fault-1"):
    return {
        "schema": "frlg-label-incident/v1",
        "incident_id": incident_id,
        "run_id": "run-1",
        "workflow": "wild",
        "stage_id": "capture.wait_ready",
        "stage_instance_id": "capture.wait_ready:1",
        "failure_kind": "stage_timeout",
        "labels": [{"name": "抓捕就绪.IL", "score": 92, "operator": ">", "threshold": 95}],
        "capture_device": {"name": "USB Capture", "index": 0, "backend": "DSHOW"},
        "screenshot": {"match": "match-frame.png", "stop": "stop-frame.png", "errors": []},
    }


class LabelIncidentTests(unittest.TestCase):
    def test_completed_bundle_is_atomic_discoverable_and_resolvable(self):
        ok, encoded = cv2.imencode(".png", np.zeros((1080, 1920, 3), dtype=np.uint8))
        self.assertTrue(ok)
        image = encoded.tobytes()
        with tempfile.TemporaryDirectory() as directory:
            store = LabelIncidentStore(Path(directory) / "incidents")
            bundle = store.write_completed(
                incident_payload(),
                assets={"match-frame.png": image, "stop-frame.png": image, "log-tail.txt": b"fault"},
            )

            record = store.read("fault-1")
            self.assertEqual(record["bundle_path"], str(bundle))
            self.assertTrue(record["complete"])
            self.assertEqual(len(store.list(include_resolved=False)), 1)
            self.assertEqual((bundle / "match-frame.png").read_bytes(), image)
            store.set_status("fault-1", "applied", note="same target rebuilt")
            store.set_status("fault-1", "loaded", note="next run started")
            store.set_status("fault-1", "resolved", note="run completed")
            self.assertEqual(store.list(include_resolved=False), ())

    def test_incident_rejects_invalid_state_and_duplicate_id(self):
        malformed = incident_payload()
        malformed["failure_kind"] = "low_score"
        with self.assertRaisesRegex(ValueError, "未知故障类型"):
            validate_incident(malformed)
        with tempfile.TemporaryDirectory() as directory:
            store = LabelIncidentStore(directory)
            store.write_completed(incident_payload(), append_event=False)
            with self.assertRaisesRegex(FileExistsError, "重复"):
                store.write_completed(incident_payload(), append_event=False)


if __name__ == "__main__":
    unittest.main()
