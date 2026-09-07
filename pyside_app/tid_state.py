"""Qt drafts and calibration recovery using the existing TID disk contracts."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QObject, QSignalBlocker, QTimer
from PySide6.QtWidgets import QAbstractButton, QComboBox

from automation.tid_rng137 import resolve_tid_template
from automation.tid_calibration import calibrated_tid_request, tid_request_from_dict
from automation.tid_search import progress_supported
from automation.tid_checkpoint import _exhaustive_start
from automation.tid_starter_flow import parse_successful_sid_advance_correction
from rng.starter_sid_verification import sid_advance_scan_offsets
from tid_session import load_tid_settings, write_json_atomic, progress_context, read_progress, latest_progress


class TidState(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.path = window.paths.user / "tid_settings.json"
        self.blocked = False
        self.pending = None
        self.refill = None
        self.unknown = {}
        self.widgets = {key + "_var": widget for key, widget in window.fields.items() if key.startswith("tid_")}
        aliases = {"tid_pid": "tid_shiny_pid", "tid_button": "tid_button_mode", "tid_close": "tid_close_delay",
            "tid_home": "tid_home_buffer", "tid_sid_correction": "tid_sid_adv_correction", "tid_select": "tid_select_correction",
            "tid_hits": "tid_denoise_hit", "tid_window": "tid_denoise_window"}
        for axis in ("op", "f1", "f2"):
            aliases[f"tid_{axis}_radius"] = f"tid_{axis}_rng_range"
            aliases[f"tid_{axis}_range"] = f"tid_{axis}_max_range"
        for qt, tk in aliases.items():
            self.widgets[tk + "_var"] = self.widgets.pop(qt + "_var")
        for qt, tk in {"starter_species": "tid_starter", "starter_min": "tid_starter_min_adv",
            "starter_max": "tid_starter_max_adv", "starter_retry": "tid_sid_retry_radius",
            "starter_sound": "tid_starter_sound", "starter_button": "tid_starter_button_mode",
            "starter_seed_button": "tid_starter_seed_button", "wild_tid": "tid"}.items():
            self.widgets[tk + "_var"] = window.fields[qt]
        checks = {"tid_calibration": window.tid_calibration_check, "tid_manual_delay": window.tid_manual_delay,
            "tid_starter_flow": window.tid_flow_check, "tid_any_tid": window.tid_any_check,
            "tid_any_tid_denoise": window.tid_denoise_check, "tid_auto_rng": window.tid_auto_rng_check,
            "tid_resume": window.tid_resume_check, "home_buffer_adaptive": window.home_buffer_check}
        checks.update(zip(("tid_same_id", "tid_sequential_id", "tid_65535", "tid_single_digit"), window.tid_special_checks))
        self.widgets.update({key + "_var": widget for key, widget in checks.items()})
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(500)
        self.save_timer.timeout.connect(self.save)
        try:
            saved = load_tid_settings(self.path)
            values = saved.get("values", {})
            # Validate every known field before changing any widget.
            for key, value in values.items():
                widget = self.widgets.get(key)
                if widget is not None:
                    if type(value) is not type(self.value(widget)):
                        raise ValueError(f"TID 参数 {key} 类型无效")
                    if isinstance(widget, QComboBox) and widget.findText(value) < 0:
                        raise ValueError(f"TID 参数 {key} 选项无效：{value}")
            blockers = [QSignalBlocker(widget) for widget in self.widgets.values()]
            window.updating = True
            try:
                for key, value in values.items():
                    if key in self.widgets:
                        self.set_value(self.widgets[key], value)
                    else:
                        self.unknown[key] = value
            finally:
                del blockers
                window.updating = False
            self.pending = saved.get("pending_calibration")
            window._refresh_tid_controls()
            self.restore_refill(saved.get("qt_progress_refill"))
            self.restore_calibration()
        except (ValueError, OSError, TypeError, KeyError) as exc:
            self.blocked = True
            window.tid_progress_status.setText(f"{exc}；原参数文件保留，自动保存已暂停。")
        for widget in self.widgets.values():
            signal = widget.toggled if isinstance(widget, QAbstractButton) else widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.textChanged
            signal.connect(self.schedule)
        window._bind("刷新进度", lambda: self.refresh_progress(fill_starts=True))
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1500)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start()
        if not self.blocked:
            self.refresh_progress()

    @staticmethod
    def value(widget):
        if isinstance(widget, QAbstractButton):
            return widget.isChecked()
        return widget.currentText() if isinstance(widget, QComboBox) else widget.text()

    @staticmethod
    def set_value(widget, value):
        if isinstance(widget, QAbstractButton):
            widget.setChecked(value)
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(value)
        else:
            widget.setText(value)

    def values(self):
        return {**self.unknown, **{key: self.value(widget) for key, widget in self.widgets.items()}}

    def schedule(self, *_):
        if not self.w.updating and not self.blocked:
            sender = self.sender()
            if sender in [self.w.fields[f"tid_{axis}_start"] for axis in ("op", "f1", "f2")] or (
                sender is self.w.tid_resume_check and not sender.isChecked()
            ):
                self.refill = None
            self.save_timer.start()

    def save(self, *, refresh=True):
        self.save_timer.stop()
        if self.blocked:
            return
        try:
            values = self.values()
            if self.refill:
                # Recheck edits before persisting the display/origin association.
                try:
                    self.w.reader.tid()
                except (ValueError, TypeError):
                    self.refill = None
            if self.refill:
                for axis, value in self.refill["original_starts"].items():
                    values[f"tid_{axis}_start_var"] = value
            payload = {"schema": 1, "values": values, "pending_calibration": self.pending}
            if self.refill:
                payload["qt_progress_refill"] = self.refill
            write_json_atomic(self.path, payload)
            if refresh:
                self.refresh_progress()
        except OSError as exc:
            self.w.tid_progress_status.setText(f"TID 参数保存失败：{exc}")

    def before_start(self, prepared, command):
        if prepared.inputs.mode == "tid" and prepared.inputs.request.calibration_check:
            self.pending = {"path": str(command.log_path.with_suffix(".calibration.json")),
                "request": prepared.inputs.request.to_dict(), "values": self.values()}
            self.save()

    def apply_successful_sid_correction(self, log_path: Path, exit_code: int) -> int | None:
        """Persist a retry correction only after the runner confirms a shiny starter."""
        if exit_code != 0:
            return None
        try:
            correction = parse_successful_sid_advance_correction(
                log_path.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            return None
        if correction is None:
            return None
        self.w.updating = True
        try:
            self.w.fields["tid_sid_correction"].setText(str(correction))
        finally:
            self.w.updating = False
        self.refill = None
        self.w.invalidate()
        self.save()
        return correction

    def poll(self):
        if self.blocked:
            return
        try:
            self.restore_calibration()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.pending = None
            self.w.set_status(f"固定延迟结果未回填：{exc}；原始结果保留。")
            self.save()
        if self.w.running and self.w.input_mode == "tid":
            self.refresh_progress()

    def restore_calibration(self):
        if not self.pending:
            return
        if not isinstance(self.pending, dict) or self.pending.get("values") != self.values():
            self.pending = None
            return
        path = Path(self.pending.get("path", ""))
        if not path.is_file():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        initial = tid_request_from_dict(self.pending["request"])
        if payload.get("schema") != 1 or payload.get("initial_request") != initial.to_dict():
            raise ValueError("固定延迟结果与启动配置不一致")
        updated = calibrated_tid_request(initial, payload["values"])
        if payload.get("request") != updated.to_dict():
            raise ValueError("固定延迟结果包含测量项以外的变化")
        self.w.updating = True
        try:
            for axis in ("op", "f1", "f2", "f3"):
                self.w.fields[f"tid_{axis}_delay"].setText(str(getattr(updated, f"{axis}_fixed_delay")))
            self.w.fields["tid_op_correction"].setText(str(updated.op_correction))
            self.w.tid_calibration_check.setChecked(False)
        finally:
            self.w.updating = False
        self.pending = None
        self.w.invalidate()
        self.save()
        self.w.set_status("固定延迟与 OP 修正已回填；运行器按实测参数继续。")

    def _context(self, request):
        request = replace(request, calibration_check=False)
        flow = self.w.reader.flow(request)
        if flow:
            request = flow.to_flow_tid_request()
        template = resolve_tid_template(self.w.fields["tid_source"].text(), request.language)
        flow_payload = {**asdict(flow), "tid_request": flow.tid_request.to_dict()} if flow else None
        context = progress_context(request, self.w.fields["tid_game"].currentText(),
            hashlib.sha256(template.read_bytes()).hexdigest(), flow_payload)
        return request, flow, context

    def effective_request(self, request):
        """The visible checkpoint position does not redefine its search origin."""
        binding = self.refill
        if not binding:
            return request
        if self.w.tid_resume_check.isChecked() and all(
            self.w.fields[f"tid_{axis}_start"].text() == text
            for axis, text in binding["displayed_starts"].items()
        ):
            candidate = replace(request, **{
                f"{axis}_start": int(value) for axis, value in binding["original_starts"].items()})
            try:
                if self._context(candidate)[2] == binding["context"]:
                    return candidate
            except (OSError, ValueError, KeyError, TypeError):
                pass
        self.refill = None
        return request

    def restore_refill(self, binding):
        # The shared draft retains original starts so the unchanged Tk entry
        # addresses the same checkpoint. Only Qt restores this display layer.
        if not isinstance(binding, dict) or binding.get("schema") != 1:
            return
        for key in ("original_starts", "displayed_starts"):
            values = binding.get(key)
            if not isinstance(values, dict) or set(values) != {"op", "f1", "f2"}:
                return
            if any(not isinstance(value, str) or not value.isascii() or not value.isdecimal() for value in values.values()):
                return
        if not self.w.tid_resume_check.isChecked() or any(
            self.w.fields[f"tid_{axis}_start"].text() != value for axis, value in binding["original_starts"].items()
        ):
            return
        try:
            if self._context(self.w.reader.tid())[2] != binding.get("context"):
                return
        except (OSError, ValueError, KeyError, TypeError):
            return
        self.refill = binding
        for axis, text in binding["displayed_starts"].items():
            widget = self.w.fields[f"tid_{axis}_start"]
            with QSignalBlocker(widget):
                widget.setText(text)

    def _fill_progress_starts(self, saved, request, context):
        if self.w.running or self.w.job is not None:
            return "运行中或后台任务处理中，仅刷新进度；停止后可回填穷举起点。"
        if saved["status"] == "completed":
            return "已完成的检查点不回填穷举起点。"
        if request.mode != 0:
            return "当前是手动乱数进度，不回填穷举起点。"
        state = saved["state"]
        starts = {
            axis.lower(): str(state[axis + "_CENTER"] if state.get("SWITCHED") else
                _exhaustive_start(request, axis) + state[axis])
            for axis in ("OP", "F1", "F2")
        }
        originals = self.refill["original_starts"] if self.refill else {
            axis: self.w.fields[f"tid_{axis}_start"].text() for axis in starts}
        for axis, text in starts.items():
            with QSignalBlocker(self.w.fields[f"tid_{axis}_start"]):
                self.w.fields[f"tid_{axis}_start"].setText(text)
        self.refill = {"schema": 1, "context": context, "original_starts": originals,
            "displayed_starts": starts} if self.w.tid_resume_check.isChecked() else None
        self.w.invalidate()
        self.save(refresh=False)
        return "已回填 OP / F1 / F2 穷举起点；续跑仍恢复原检查点。" if self.refill else "已回填穷举起点；当前未勾选续跑，将按回填起点开始新搜索。"

    def refresh_progress(self, *, fill_starts=False):
        if self.blocked:
            return
        try:
            request = replace(self.effective_request(self.w.reader.tid()), calibration_check=False)
            if not progress_supported(request):
                self.w.tid_progress_status.setText("参数自动保存；乱数半径全为 0，重复同一参数点，无需恢复搜索位置。")
                return
            request, flow, context = self._context(request)
            directory = self.w.paths.user / "tid_progress"
            saved = read_progress(directory, context)
            if flow and not flow.deferred_identity:
                contexts = [progress_context(replace(request, sid_advance_correction=request.sid_advance_correction + offset),
                    context["game"], context["template_sha256"], context["flow_request"]) for offset in sid_advance_scan_offsets(flow.sid_retry_radius)]
                latest = latest_progress(directory, contexts)
                if latest:
                    saved = latest[1]
            if not saved or saved.get("state") is None:
                text = "参数自动保存；当前游戏、机型、参数及脚本版本没有检查点，将从所填起点开始。"
            else:
                state = saved["state"]
                status = "已命中完成，下次重新开始" if saved["status"] == "completed" else "存在同参数进度"
                if state.get("MODE", 0) == 1:
                    ranges = "；".join(
                        f"{axis} [-{state.get(axis + '_NEG', state[axis + '_RANGE'])}, +{state[axis + '_RANGE']}]"
                        for axis in ("OP", "F1", "F2"))
                    text = (
                        f"{status}：{'穷举转乱数' if state['SWITCHED'] else '乱数'}，目标 TID {state['TARGET']:05d}\n"
                        f"中心 OP/F1/F2：{state['OP_CENTER']}/{state['F1_CENTER']}/{state['F2_CENTER']}\n"
                        f"实际偏移范围：{ranges}\n"
                        f"当前壳层 ±{state['RADIUS']}，累计 {state['COUNT']} 次。")
                else:
                    text = f"{status}：穷举层级 {state['STAGE']}，OP/F1/F2 偏移 {state['OP']}/{state['F1']}/{state['F2']}，累计 {state['COUNT']} 次。"
                if request.auto_rng and "COMPLETED_REGIONS" in state:
                    text += f" 已完成局部区域 {state['COMPLETED_REGIONS']} 个。"
                if fill_starts:
                    text += "\n" + self._fill_progress_starts(saved, request, context)
            self.w.tid_progress_status.setText(text)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.w.tid_progress_status.setText(f"参数自动保存；暂不能匹配进度：{exc}")
