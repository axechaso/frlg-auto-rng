import unittest

from automation.input_state_protocol import (
    format_input_session_marker,
    parse_input_session_marker,
)
from pyside_app.run_input_state import (
    RunInputStateModel,
    validate_input_response,
    validate_snapshot,
)


def snapshot(buttons=(), *, hat="CENTER", left=(128, 128), right=(128, 128)):
    return {
        "buttons": list(buttons),
        "hat": hat,
        "left_stick": list(left),
        "right_stick": list(right),
    }


def response(seq, current, events=(), *, gap=False, connection="connected", source="device_report"):
    return {
        "protocol": 1,
        "run_id": "run-1",
        "session_id": "session-1",
        "stage_id": "wild",
        "server_ms": 1000,
        "seq": seq,
        "source": source,
        "connection": connection,
        "snapshot": current,
        "events": list(events),
        "history_gap": gap,
    }


class RunInputStateProtocolTests(unittest.TestCase):
    def test_accepts_real_report_shapes_and_rejects_unknown_values(self):
        checked = validate_snapshot(snapshot(["A", "ZL"], hat="DOWN_RIGHT", left=(0, 255)))
        self.assertEqual(checked["buttons"], ("A", "ZL"))
        self.assertEqual(checked["left_stick"], (0, 255))
        for invalid in (
            snapshot(["NOT_A_BUTTON"]),
            snapshot(hat="NORTH"),
            snapshot(left=(True, 128)),
        ):
            with self.assertRaises(ValueError):
                validate_snapshot(invalid)

    def test_response_is_bound_to_run_session_stage_and_monotonic_sequence(self):
        first_event = {"seq": 1, "at_ms": 10, "snapshot": snapshot(["A"])}
        checked = validate_input_response(
            response(1, snapshot(["A"]), [first_event]),
            run_id="run-1", session_id="session-1", stage_id="wild", last_seq=-1,
        )
        self.assertEqual(checked["seq"], 1)
        with self.assertRaisesRegex(ValueError, "会话"):
            validate_input_response(
                {**response(1, snapshot(["A"]), [first_event]), "session_id": "old"},
                run_id="run-1", session_id="session-1", stage_id="wild", last_seq=-1,
            )
        with self.assertRaisesRegex(ValueError, "倒退"):
            validate_input_response(
                response(0, snapshot()),
                run_id="run-1", session_id="session-1", stage_id="wild", last_seq=1,
            )
        with self.assertRaises(ValueError):
            validate_input_response(
                {**response(1, snapshot(["A"]), [first_event]), "protocol": True},
                run_id="run-1", session_id="session-1", stage_id="wild", last_seq=-1,
            )

    def test_latest_snapshot_must_match_last_event(self):
        event = {"seq": 1, "at_ms": 10, "snapshot": snapshot(["A"])}
        with self.assertRaisesRegex(ValueError, "最新事件"):
            validate_input_response(
                response(1, snapshot(), [event]),
                run_id="run-1", session_id="session-1", stage_id="wild", last_seq=-1,
            )

    def test_model_tracks_press_release_and_does_not_invent_gapped_actions(self):
        model = RunInputStateModel()
        model.begin("run-1", "session-1", "wild")
        down = snapshot(["A"])
        model.apply_payload(response(1, down, [{"seq": 1, "at_ms": 10, "snapshot": down}]))
        self.assertEqual(model.view().snapshot["buttons"], ("A",))
        self.assertIn("按下 A", model.view().recent_action)

        up = snapshot()
        model.apply_payload(response(2, up, [{"seq": 2, "at_ms": 20, "snapshot": up}]))
        self.assertEqual(model.view().snapshot["buttons"], ())
        self.assertIn("松开 A", model.view().recent_action)

        latest = snapshot(["B"], hat="TOP_LEFT", left=(4, 241))
        model.apply_payload(response(600, latest, gap=True))
        self.assertEqual(model.view().snapshot["buttons"], ("B",))
        self.assertTrue(model.view().history_gap)
        self.assertEqual(model.view().recent_action, "近期操作记录不完整")

    def test_batched_short_press_keeps_the_release_as_the_latest_action(self):
        model = RunInputStateModel()
        model.begin("run-1", "session-1", "wild")
        pressed = snapshot(["A"])
        neutral = snapshot()
        events = [
            {"seq": 1, "at_ms": 10, "snapshot": pressed},
            {"seq": 2, "at_ms": 20, "snapshot": neutral},
        ]
        model.apply_payload(response(2, neutral, events))
        self.assertEqual(model.view().snapshot["buttons"], ())
        self.assertIn("松开 A", model.view().recent_action)

    def test_stage_markers_neutralize_search_and_drop_old_sessions(self):
        model = RunInputStateModel()
        model.begin("run-1", "session-1", "run")
        searching = format_input_session_marker("run-1", "attempt-2", "sid_candidate", "SEARCHING")
        self.assertTrue(model.set_session(parse_input_session_marker(searching)))
        self.assertEqual(model.view().phase, "searching")
        self.assertEqual(model.view().snapshot["buttons"], ())
        old = response(1, snapshot(["A"]), [{"seq": 1, "at_ms": 10, "snapshot": snapshot(["A"])}])
        with self.assertRaisesRegex(ValueError, "会话"):
            model.apply_payload(old)

        wrong_run = format_input_session_marker("other", "session-2", "wild", "RUNNING")
        self.assertFalse(model.set_session(parse_input_session_marker(wrong_run)))

    def test_failed_session_marker_remains_failed(self):
        model = RunInputStateModel()
        model.begin("run-1", "session-1", "run")
        marker = format_input_session_marker("run-1", "session-2", "tid_stage_2", "FAILED")
        self.assertTrue(model.set_session(parse_input_session_marker(marker)))
        model.end("阶段失败", phase="failed")
        self.assertEqual(model.view().phase, "failed")

    def test_error_connection_clears_confirmed_buttons_without_claiming_release(self):
        model = RunInputStateModel()
        model.begin("run-1", "session-1", "wild")
        down = snapshot(["A"])
        event = {"seq": 1, "at_ms": 10, "snapshot": down}
        model.apply_payload(response(1, down, [event]))
        model.apply_payload(response(1, down, connection="error"))
        self.assertEqual(model.view().connection, "error")
        self.assertEqual(model.view().snapshot["buttons"], ())
        self.assertIn("未知", model.view().message)


if __name__ == "__main__":
    unittest.main()
