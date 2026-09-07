import importlib.util
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch, Mock

from automation import EasyConRuntimeCheck, SearchCancelledError, TidRngRequest
from pyside_app.services import AppPaths
from pyside_app.workflows import WorkflowInputs, PreparedWorkflow, prepare_workflow, prepare_workflow_run, _snapshot
from tests.test_easycon118_egg import egg_request


class WorkflowTests(unittest.TestCase):
    def test_cancel_prevents_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = WorkflowInputs("egg", egg_request(), root, root / "ezcon.exe")
            with self.assertRaises(SearchCancelledError):
                prepare_workflow(inputs, AppPaths(output=root / "out"), cancel=lambda: True)
            self.assertFalse((root / "out").exists())

    def test_worker_commands_keep_resume_devices_and_private_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "main.ecs"
            project.write_text("# test", encoding="utf-8")
            check = EasyConRuntimeCheck(True, (), ())
            request = TidRngRequest(mode=0, target_tid=12345)
            inputs = WorkflowInputs("tid", request, root, root / "ezcon.exe", capture_name="Capture", extra={"flow": None, "game": "火红", "resume": False})
            prepared = PreparedWorkflow(inputs, root, project, check, _snapshot(project, root), "", ("", "", ""))
            with patch("pyside_app.workflows.probe_easycon_devices", return_value=({"COM4"}, {3: "Capture"}, "")), patch("pyside_app.workflows.check_workflow", return_value=check):
                command = prepare_workflow_run(prepared, AppPaths(user=root), "COM4", 3, "Capture")
                self.assertIn("--fresh-exhaustive", command.arguments)
                self.assertIn("--tid-progress-dir", command.arguments)
                self.assertIn(str(command.stop_path), command.arguments)
                self.assertTrue(command.preview_url.startswith("http://127.0.0.1:"))
                self.assertFalse(command.stop_path.exists())
                project.write_text("changed", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "改变"):
                    prepare_workflow_run(prepared, AppPaths(user=root), "COM4", 3, "Capture")

    def test_changed_device_rejected_before_runtime(self):
        inputs = WorkflowInputs("egg", egg_request(), Path("source"), Path("ezcon.exe"), capture_name="Capture")
        prepared = PreparedWorkflow(inputs, Path("out"), Path("out/main.ecs"), EasyConRuntimeCheck(True, (), ()), {}, "", ())
        with patch("pyside_app.workflows.probe_easycon_devices", return_value=({"COM4"}, {3: "Other"}, "")), patch("pyside_app.workflows.check_workflow") as check:
            with self.assertRaisesRegex(ValueError, "设备"):
                prepare_workflow_run(prepared, AppPaths(), "COM4", 3, "Capture")
            check.assert_not_called()

    def test_sid_slot_reapplies_profile_after_assets_are_copied(self):
        from run_sid_reverse_capture import _write_slot_project
        from automation import SIDReverseRunRequest
        with patch("run_sid_reverse_capture.write_sid_reverse_project", return_value=Path("out/main.ecs")) as generate, \
             patch("device_label_overrides.load_label_override_profile", return_value="profile"), \
             patch("device_label_overrides.apply_profile_to_projects") as apply:
            _write_slot_project(Path("source"), Path("out"), SIDReverseRunRequest(12345, 1), 1, Path("profile"))
            self.assertTrue(generate.call_args.kwargs["copy_assets"])
            apply.assert_called_once_with(Path("out"), "profile")


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is optional")
class RemainingQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["remaining-tests", "-platform", "offscreen"])

    def setUp(self):
        from pyside_app.migration import CompleteWindow
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.w = CompleteWindow(paths=AppPaths(user=self.root, output=self.root / "runtime"), auto_detect=False)
        self.errors = []
        self.w.show_error = self.errors.append

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def configure_egg(self):
        from pyside_app.egg_config import build_egg_full_config_payload
        request = egg_request()
        payload = build_egg_full_config_payload("火红", 1, request.seed_mode, request.target_seed,
            request.held_advances, request.pickup_advances, request.species_id, request.compatibility,
            request.parent_a_gender, request.parent_a_ivs, request.parent_b_gender, request.parent_b_ivs)
        self.w.select_page("egg")
        self.w.apply_egg_config(payload, True)
        self.w.egg_ack.setChecked(True)
        return request

    def test_formal_window_has_no_migration_placeholders(self):
        from PySide6.QtWidgets import QWidget

        stale = []
        for widget in self.w.findChildren(QWidget):
            text = widget.text() if hasattr(widget, "text") else ""
            tooltip = widget.toolTip()
            if any(marker in f"{text}\n{tooltip}" for marker in ("尚未接入", "仍在迁移")):
                stale.append((type(widget).__name__, text, tooltip))
        self.assertEqual(stale, [])

    def test_egg_full_roundtrip_and_acknowledgement(self):
        expected = self.configure_egg()
        actual = self.w.reader.egg()
        self.assertEqual(actual.species_id, 148)
        self.assertEqual(actual.parent_a_ivs, expected.parent_a_ivs)
        self.assertEqual(actual.pickup_advances, expected.pickup_advances)
        payload = self.w.egg_payload(True)
        self.w.apply_egg_config(payload, True)
        self.assertFalse(self.w.egg_ack.isChecked())
        with self.assertRaisesRegex(ValueError, "前置"):
            self.w.reader.egg()
        self.assertEqual(self.w.reader.egg(require_ack=False), actual)

    def test_sid_active_slots_and_effort_values(self):
        w = self.w
        w.select_page("sid")
        w.fields["sid_count"].setValue(1)
        row = w.sid_party_widgets[0]
        row[0].setText("皮卡丘")
        row[1].setText("3")
        row[2].setCurrentIndex(1)
        row[3].setText("常青森林")
        row[4].setValue(252)
        w.sid_ack.setChecked(True)
        request = w.collect_workflow().request
        self.assertEqual(request.dex_overrides, (25, 0, 0, 0, 0, 0))
        self.assertEqual(request.locations[0], "Viridian Forest")
        self.assertEqual(request.effort_values[0][0], 252)

    def test_egg_config_can_inherit_defaults_without_local_script_pack(self):
        self.configure_egg()
        self.w.fields["source"].setText(str(self.root / "missing-script-pack"))
        for key, widget in self.w.fields.items():
            if key.startswith("expansion_"):
                widget.clear()
        self.w.fields["layers"].setValue(3)
        request = self.w.reader.egg()
        self.assertIsNone(request.reverse_expansion_layers)
        self.assertIsNone(self.w.egg_payload(True)["reverse_expansion_seed_tolerances"])
        self.w.fields["expansion_1_seed"].setText("12")
        with self.assertRaises(ValueError):
            self.w.reader.egg()

    def test_tid_exhaustive_additional_targets_and_flow_policy(self):
        w = self.w
        w.select_page("tid")
        w.fields["tid_target"].setText("00123")
        w.fields["tid_mode"].setCurrentIndex(1)
        w.fields["tid_additional_targets"].setText("00456, 00789")
        w.tid_auto_rng_check.setChecked(True)
        request = w.reader.tid()
        self.assertEqual(request.additional_target_tids, (456, 789))
        self.assertTrue(request.auto_rng)
        w.tid_any_check.setChecked(True)
        request = w.reader.tid()
        self.assertEqual(request.additional_target_tids, ())
        self.assertFalse(request.auto_rng)
        self.assertTrue(w.reader.flow(request).accept_any_tid)
        w.tid_state.save()
        values = json.loads((self.root / "tid_settings.json").read_text(encoding="utf-8"))["values"]
        self.assertEqual(values["tid_target_var"], "00123")
        self.assertEqual(values["tid_op_rng_range_var"], w.fields["tid_op_radius"].text())

    def test_profile_switch_edit_and_restart_preserve_tid_target_draft(self):
        w = self.w
        w.select_page("tid")
        w.fields["tid_target"].setText("00123")
        w.fields["tid_sid"].setText("00456")
        first = w.profile_store.add("English", "火红", 31056, 38449, 1)
        w.profile_store.add("Japanese", "叶绿", 7, 8, 2, language="日文")
        w.reload_profiles(apply=True)
        self.assertEqual(w.fields["tid_target"].text(), "00123")
        self.assertEqual(w.fields["tid_sid"].text(), "00456")
        w.profile_selector.setCurrentIndex(w.profile_selector.findData(first.profile_id))
        w.profile_store.update(first.profile_id, "English", "火红", 22222, 33333, 1)
        w.reload_profiles(apply=True)
        request = w.reader.tid()
        self.assertEqual((request.target_tid, request.target_sid), (123, 456))
        self.assertEqual(w.fields["wild_tid"].text(), "22222")
        self.assertEqual(w.fields["wild_sid"].text(), "33333")
        window_class = type(w)
        w.close()
        w.deleteLater()
        self.app.processEvents()
        values = json.loads((self.root / "tid_settings.json").read_text(encoding="utf-8"))["values"]
        self.assertEqual((values["tid_target_var"], values["tid_sid_var"]), ("00123", "00456"))
        self.w = window_class(paths=AppPaths(user=self.root, output=self.root / "runtime"), auto_detect=False)
        self.w.show_error = self.errors.append
        self.w.reload_profiles(apply=True)
        self.assertEqual(self.w.fields["tid_target"].text(), "00123")
        self.assertEqual(self.w.fields["tid_sid"].text(), "00456")
        self.assertEqual(self.w.fields["wild_tid"].text(), "22222")
        self.assertEqual(self.w.fields["wild_sid"].text(), "33333")
        self.assertEqual(self.errors, [])

    def test_calibration_checks_identity_and_only_fills_measured_fields(self):
        from automation.tid_calibration import calibrated_tid_request
        w = self.w
        w.select_page("tid")
        w.tid_calibration_check.setChecked(True)
        request = w.reader.tid()
        path = self.root / "measured.json"
        measurements = {"OP": 30610, "F1": 22060, "F2": 4260, "F3": 14910, "OP_CORRECTION": 3}
        updated = calibrated_tid_request(request, measurements)
        path.write_text(json.dumps({"schema": 1, "initial_request": request.to_dict(), "values": measurements, "request": updated.to_dict()}), encoding="utf-8")
        w.tid_state.pending = {"path": str(path), "request": request.to_dict(), "values": w.tid_state.values()}
        w.tid_state.restore_calibration()
        self.assertEqual(w.fields["tid_op_delay"].text(), "30610")
        self.assertEqual(w.fields["tid_op_correction"].text(), "3")
        self.assertFalse(w.tid_calibration_check.isChecked())
        self.assertIsNone(w.workflow)
        w.tid_state.pending = {"path": str(path), "request": request.to_dict(), "values": w.tid_state.values()}
        w.fields["tid_op_delay"].setText("31000")
        w.tid_state.restore_calibration()
        self.assertEqual(w.fields["tid_op_delay"].text(), "31000")

    def test_script_custom_selection_does_not_replace_user_path(self):
        w = self.w
        w.advanced_check.setChecked(True)
        w.select_page("script_test")
        w.fields["script_entry"].setCurrentText("自选 ECS")
        w.fields["script_path"].setText(str(self.root / "custom.ecs"))
        inputs = w.collect_workflow()
        self.assertEqual(inputs.extra["script"], str(self.root / "custom.ecs"))
        self.assertTrue(w.search_button.isEnabled())
        self.assertFalse(w.start_button.isEnabled())

    def test_controller_combines_direction_and_releases_on_focus_loss(self):
        from pyside_app.manual import ControllerWindow
        from PySide6.QtCore import QEvent
        controller = ControllerWindow(self.w)
        controller.controller = Mock(is_connected=True)
        controller.native = type("Keys", (), {key: key for key in ("TOP", "RIGHT", "TOP_RIGHT", "A")})
        controller.press("TOP")
        controller.press("RIGHT")
        controller.controller.press.assert_called_with("TOP_RIGHT")
        controller.release("RIGHT")
        controller.controller.press.assert_called_with("TOP")
        controller.eventFilter(controller, QEvent(QEvent.Type.WindowDeactivate))
        self.assertEqual(controller.pressed, set())
        controller.controller.release_all.assert_called()
        controller.close()

    def test_stale_workflow_and_additional_inputs_are_locked(self):
        self.configure_egg()
        inputs = self.w.collect_workflow()
        prepared = PreparedWorkflow(inputs, self.root, self.root / "main.ecs", EasyConRuntimeCheck(True, (), ()), {}, "", ("75D1", "8021", "10021"))
        self.w.fields["egg_pickup"].setText("10022")
        self.w.workflow_finished(prepared)
        self.assertIsNone(self.w.workflow)
        self.w.running = True
        self.w.refresh_state()
        self.assertFalse(self.w.egg_parent_widgets[0][1].isEnabled())
        self.assertFalse(self.w.egg_ack.isEnabled())
        self.assertTrue(self.w.nav_buttons["egg"].isEnabled())
        self.assertFalse(self.w.nav_buttons["wild"].isEnabled())
        self.assertTrue(self.w.actions["监视窗口"].isEnabled())
        self.w.running = False
        self.w.refresh_state()
        self.assertTrue(self.w.egg_parent_widgets[0][1].isEnabled())

    def test_corrupt_draft_is_not_partially_applied_or_overwritten(self):
        from pyside_app.tid_state import TidState
        path = self.root / "tid_settings.json"
        original = json.dumps({"schema": 1, "values": {"tid_target_var": "12345", "tid_mode_var": "invalid-mode"}})
        path.write_text(original, encoding="utf-8")
        state = TidState(self.w)
        self.assertTrue(state.blocked)
        self.assertEqual(self.w.fields["tid_target"].text(), "00000")
        state.save()
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        state.poll_timer.stop()

    def test_report_presentations_do_not_claim_unique_sid_from_psv(self):
        from pyside_app.results import sid_report_summary, traversal_report_summary
        title, _, metrics, note = sid_report_summary("结果: PSV已经唯一: 123\n最终SID（窗口内最早ADV）: 00123；ADV: 2000")
        self.assertEqual(title, "候选 SID 00123")
        self.assertEqual(metrics[1], 8)
        self.assertIn("8 个 SID", note)
        self.assertEqual(traversal_report_summary({"status": "paused", "state": {"current_sid_advance": 1901}})[0], "遍历已暂停")

    def test_pending_calibration_rejects_nonmeasurement_changes(self):
        from automation.tid_calibration import calibrated_tid_request
        w = self.w
        w.select_page("tid")
        request = w.reader.tid()
        measurements = {"OP": 30610, "F1": 22060, "F2": 4260, "F3": 14910, "OP_CORRECTION": 3}
        updated = replace(calibrated_tid_request(request, measurements), target_tid=12345)
        path = self.root / "tampered.json"
        path.write_text(json.dumps({"schema": 1, "initial_request": request.to_dict(), "values": measurements, "request": updated.to_dict()}), encoding="utf-8")
        w.tid_state.pending = {"path": str(path), "request": request.to_dict(), "values": w.tid_state.values()}
        with self.assertRaisesRegex(ValueError, "测量项"):
            w.tid_state.restore_calibration()
        self.assertEqual(w.fields["tid_op_delay"].text(), "30600")
        w.tid_state.pending = None

    def test_actual_child_process_completes_and_releases_workflow_inputs(self):
        import sys
        from PySide6.QtCore import QEventLoop, QTimer
        from pyside_app.services import RunCommand
        self.configure_egg()
        inputs = self.w.collect_workflow()
        prepared = PreparedWorkflow(inputs, self.root, self.root / "main.ecs", EasyConRuntimeCheck(True, (), ()), {}, "", ("75D1", 8021, 10021))
        self.w.running_workflow = prepared
        self.w.running_prepared = None
        self.w.run_command = RunCommand(sys.executable, (), self.root / "log.txt", self.root / "stop", "", prepared.check)
        self.w.running = True
        self.w.refresh_state()
        loop = QEventLoop()
        self.w.process.finished.connect(loop.quit)
        QTimer.singleShot(10000, loop.quit)
        self.w.process.start(sys.executable, ["-u", "-c", "print('no hardware child')"])
        loop.exec()
        self.assertFalse(self.w.running)
        self.assertIn("no hardware child", self.w.log_view.toPlainText())
        self.assertTrue(self.w.egg_parent_widgets[0][1].isEnabled())
