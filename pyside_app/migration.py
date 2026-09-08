"""Functional adapters for the remaining approved Qt pages."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QComboBox, QCompleter, QFileDialog, QLabel, QMessageBox, QSpinBox, QStyledItemDelegate

from app_paths import RESOURCE_ROOT
from assets.game_text import SPECIES_EN_TO_ZH
from automation import STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME, resolve_script_test_entry
from automation.precalibration import update_from_manifest
from rng.tenlines_utils import get_species_name
from rng.sid_reverse import find_earliest_shiny_sid, parse_pid_hex, sid_min_advances_for_f3, DEFAULT_TID_SID_SEARCH_ADVANCES
from sid_traversal import DEFAULT_TARGET_MAX_ADVANCES, sid_traversal_start_advance
from tid_session import write_json_atomic
from pyside_preview import APP_STYLE, CompletionPopup
from .window import FrlgWindow
from .forms import FormReader, species_id
from .workflows import WorkflowInputs, prepare_workflow, prepare_workflow_run
from .egg_config import build_egg_parent_config_payload, build_egg_full_config_payload, parse_egg_parent_config_payload, parse_egg_full_config_payload


class CompleteWindow(FrlgWindow):
    def __init__(self, **kwargs):
        self.migration_ready = False
        super().__init__(**kwargs)
        self.workflow = None
        self.running_workflow = None
        self.workflow_summary = None
        self.named_rival = None
        parents = self.egg_parents.layout()
        self.egg_parent_widgets = []
        for row in range(2):
            grid = parents.itemAt(row).layout()
            self.egg_parent_widgets.append([grid.itemAtPosition(0, col).layout().itemAt(1).widget() for col in range(7)])
        self.script_verbose = next(check for check in self.findChildren(QCheckBox) if check.text() == "输出 EasyCon 详细日志")
        for title, handler in (("保存亲本配置", lambda: self.save_egg(False)), ("载入亲本配置", lambda: self.load_egg(False)),
                ("保存全部配置", lambda: self.save_egg(True)), ("载入全部配置", lambda: self.load_egg(True)),
                ("6V 闪 SID", self.calculate_shiny_sid), ("选择脚本", self.choose_script),
                ("检查程序更新", lambda: self.app_update.check(force=True))):
            self._bind(title, handler)
        for key in ("sid_source", "tid_source"):
            entry = self.fields[key]
            card = entry.parentWidget().parentWidget()
            from PySide6.QtWidgets import QPushButton
            button = next(b for b in card.findChildren(QPushButton) if b.text() == "选择")
            self._bind_button(button, lambda _checked=False, key=key: self.choose_path(key))
            self.actions[key] = button
        self.reader = FormReader(self)
        for key, widget in self.fields.items():
            if key not in self.input_keys:
                signal = widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.valueChanged if isinstance(widget, QSpinBox) else widget.textChanged
                signal.connect(self.invalidate)
        for widget in self.extra_checks():
            widget.toggled.connect(self.invalidate)
        for row in self.egg_parent_widgets + self.sid_party_widgets:
            for widget in row:
                signal = widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.valueChanged if isinstance(widget, QSpinBox) else widget.textChanged
                signal.connect(self.invalidate)
        choices = [f"{SPECIES_EN_TO_ZH.get(get_species_name(i), get_species_name(i))}" for i in range(1, 387)]
        for edit in (self.fields["egg_species"], *(row[0] for row in self.sid_party_widgets)):
            completer = QCompleter(choices, edit)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setMaxVisibleItems(8)
            popup = CompletionPopup()
            completer.setPopup(popup)
            popup.setObjectName("comboPopupList")
            # A completer popup is a separate window and does not inherit the
            # main window's stylesheet. Share the existing dropdown appearance.
            popup.setStyleSheet(APP_STYLE)
            popup.setItemDelegate(QStyledItemDelegate(popup))
            popup.setUniformItemSizes(True)
            popup.setMouseTracking(True)
            popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            popup.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            popup.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            edit.setCompleter(completer)
        self.fields["script_entry"].currentIndexChanged.connect(self.sync_script)
        self.fields["source"].editingFinished.connect(self.sync_script)
        self.fields["script_path"].setPlaceholderText("选择 ECS 文件")
        for key, widget in self.fields.items():
            if key.startswith("expansion_"):
                widget.setPlaceholderText("沿用所选脚本的默认值")
        self.migration_ready = True
        self._connected_text()
        self._refresh_wild_controls()
        self.refresh_state()
        from .tid_state import TidState
        from .accessories import Accessories
        from .app_update import AppUpdateController
        self.tid_state = TidState(self)
        self.app_update = AppUpdateController(self)
        self.accessories = Accessories(self)
        self.refresh_state()

    def extra_checks(self):
        return (self.egg_ack, self.sid_ack, self.traversal_check, self.tid_flow_check, self.tid_any_check,
            self.tid_denoise_check, self.tid_manual_delay, self.tid_calibration_check, self.tid_auto_rng_check,
            self.tid_resume_check, self.script_verbose, *self.tid_special_checks)

    def current_template(self):
        return EGG_TEMPLATE_NAME if self.fields["script_entry"].currentIndex() == 1 else STANDARD_TEMPLATE_NAME

    def collect_workflow(self):
        mode = self.input_mode
        f, r = self.fields, self.reader
        source = Path(f["source"].text()).resolve()
        extra = {}
        if mode == "egg":
            request = r.egg()
        elif mode == "sid":
            request = r.sid()
            source = Path(f["sid_source"].text()).resolve()
        elif mode == "tid":
            request = r.tid()
            source = Path(f["tid_source"].text()).resolve()
            extra = {"flow": r.flow(request), "starter_source": Path(f["source"].text()).resolve(),
                     "game": r.text("tid_game"), "resume": self.tid_resume_check.isChecked()}
        elif mode == "script_test":
            if not self.advanced_check.isChecked():
                raise ValueError("请开启高级模式")
            self.sync_script()
            request = None
            extra = {"script": f["script_path"].text(), "backend": r.text("script_backend"), "verbose": self.script_verbose.isChecked()}
        elif mode == "wild" and self.traversal_check.isChecked():
            if self.named_rival is None:
                raise ValueError("请先确认 SID 遍历的劲敌取名状态")
            base = self.collect_inputs()
            request = base.request
            if request.direct_mode or "Wild" not in request.method:
                raise ValueError("SID 遍历需要野生筛选搜索模式")
            if request.min_advances > DEFAULT_TARGET_MAX_ADVANCES:
                raise ValueError(f"SID 遍历目标最低 ADV 不能大于 {DEFAULT_TARGET_MAX_ADVANCES}")
            options = replace(base.options, continue_capture_after_shiny=False, item_rng_mode=False, party_empty_slots=1)
            start_text = f["wild_traversal_start"].text().strip()
            start = r.integer("wild_traversal_start") if self.advanced_check.isChecked() and start_text else None
            sid_traversal_start_advance(self.named_rival, start)
            mode = "sid_traversal"
            extra = {"options": options, "named_rival": self.named_rival, "start_advance": start,
                "max_advances": f["wild_traversal_max"].value(), "progress_dir": self.paths.user / "sid_traversal_progress"}
        else:
            raise ValueError("当前不是独立工作流")
        video = f["video"].currentData()
        return WorkflowInputs(mode, request, source, Path(f["ezcon"].text()).resolve(),
            self.advanced_check.isChecked(), self.current_template(), self.devices[1].get(video, ""), extra)

    def is_workflow_mode(self):
        return self.input_mode != "wild" or self.traversal_check.isChecked()

    def invalidate(self, *_):
        if getattr(self, "migration_ready", False) and not self.updating:
            self.workflow = None
            self.workflow_summary = None
        super().invalidate()

    def _refresh_wild_controls(self):
        super()._refresh_wild_controls()
        if getattr(self, "migration_ready", False):
            self.traversal_check.setEnabled(self.fields["wild_method"].currentIndex() == 0 and not self.item_check.isChecked() and not self.running)
            if self.traversal_check.isChecked():
                self.capture_checks[0].setChecked(False)
            self.capture_checks[0].setEnabled(not self.traversal_check.isChecked() and not self.running)

    def refresh_state(self, *_):
        super().refresh_state()
        if not getattr(self, "migration_ready", False):
            return
        busy = self.running or self.job is not None
        if "监视窗口" in self.actions:
            self.actions["监视窗口"].setEnabled(self.job is None)
        self.traversal_check.setEnabled(not busy and self.fields["wild_method"].currentIndex() == 0 and not self.item_check.isChecked())
        self.footer_status.setText(self.status_text)
        if self.is_workflow_mode():
            self.search_button.setEnabled(not busy)
            prepared = self.workflow
            valid = bool(prepared and prepared.check.ok)
            self.start_button.setEnabled(valid and not busy and bool(self.fields["port"].currentData()) and self.fields["video"].currentData() is not None)
            self.summary_badge.setText("预检通过" if valid else "暂无已通过预检的计划")
            self.summary_context.setText("填写条件后生成方案")
            if prepared:
                names = {"egg": "孵蛋方案", "sid": "SID 采集方案", "tid": "建档方案", "script_test": "脚本测试", "sid_traversal": "SID 遍历方案"}
                self.summary_name.setText(names[prepared.inputs.mode])
                request = prepared.inputs.request
                if prepared.inputs.mode == "sid":
                    self.summary_context.setText(f"TID {request.tid:05d} · {request.party_count} 只闪光")
                elif prepared.inputs.mode == "egg":
                    self.summary_context.setText(f"{SPECIES_EN_TO_ZH.get(get_species_name(request.species_id), str(request.species_id))} · 相性 {request.compatibility}")
                elif prepared.inputs.mode == "tid":
                    self.summary_context.setText(f"{request.language} · Switch {request.nx_model} · {'穷举' if request.mode == 0 else '乱数'}")
                elif prepared.inputs.mode == "script_test":
                    self.summary_context.setText(prepared.project.name)
                else:
                    self.summary_context.setText(f"TID {request.tid:05d} · SID 候选逐一验证")
                for label, value in zip(self.metric_values, prepared.metrics):
                    label.setText(str(value))
                self.summary_note.setText("查看详情中的运行要求与预检结果。")
            else:
                self.summary_name.setText("暂无方案")
                self.summary_note.setText("填写参数后生成或预检。")
            self.ready_values[2].setText("预检通过" if valid else "运行前预检")
            labels = self.overview.findChildren(QLabel, "metricLabel")
            if self.traversal_check.isChecked() and self.input_mode == "wild":
                for label, text in zip(labels, ("候选 SID", "建档 ADV", "状态")):
                    label.setText(text)
            self.ready_dots[2].setStyleSheet(f"color: {'#22a785' if valid else '#b6c0cf'};")
            if self.workflow_summary:
                title, context, metrics, note = self.workflow_summary
                self.summary_name.setText(title)
                self.summary_context.setText(context)
                for label, value in zip(self.metric_values, metrics):
                    label.setText(str(value))
                self.summary_note.setText(note)
        self.summary_note.setMinimumHeight(max(28, self.summary_note.heightForWidth(max(180, self.summary_note.width()))))
        if hasattr(self, "app_update"):
            self.app_update.refresh()

    def _lock_run_inputs(self):
        super()._lock_run_inputs()
        if getattr(self, "migration_ready", False) and self.running:
            for widget in (*self.extra_checks(), *(widget for row in self.egg_parent_widgets + self.sid_party_widgets for widget in row)):
                if widget not in self.run_input_states:
                    self.run_input_states[widget] = widget.isEnabled()
                widget.setEnabled(False)
            for key, button in self.nav_buttons.items():
                if key not in ("logs", "tid_records"):
                    if button not in self.run_input_states:
                        self.run_input_states[button] = button.isEnabled()
                    button.setEnabled(key == self.input_mode)

    def _refresh_common_settings(self):
        super()._refresh_common_settings()
        if getattr(self, "migration_ready", False):
            if self.input_mode in ("wild", "egg") or self.input_mode == "tid" and self.tid_flow_check.isChecked():
                self.advanced_scope.setText("Seed 校准与启动在主窗口顶部；以下参数用于本次脚本生成。")

    def _connected_text(self):
        replacements = {
            "PySide6 · 野生 / 静态已接入": "PySide6 · 正式服务",
            "游戏和主机与野生 / 静态页共用；蛋种目录与名称校验尚未接入。": "游戏和主机与野生 / 静态页共用；支持中文名、英文名和编号。",
            "入口未解析；预检与运行服务尚未接入。": "选定入口后预检；开始运行前再次核对脚本与设备。",
            "仅用于穷举：局部搜完一轮未命中后返回穷举。搜索与切换尚未接入。": "仅用于穷举：局部搜完一轮未命中后返回穷举。",
            "延迟和 OP 修正使用 ms；测量与自动回填服务尚未接入。": "延迟和 OP 修正使用 ms；检测结果校验后自动回填。",
        }
        for label in self.findChildren(QLabel):
            if label.text() in replacements:
                label.setText(replacements[label.text()])
            elif label.text().startswith("断点读取尚未接入"):
                label.setObjectName("traversalProgress")
                label.setText("生成时匹配当前参数的遍历断点；停止后保留当前候选。")
            elif label.text().startswith("尚未接入记录详情"):
                label.setObjectName("liveRecordDetails")
                label.setText("选择一条实测记录查看详情；出现次数不保证再次命中。")
        from PySide6.QtWidgets import QWidget
        for widget in self.findChildren(QWidget):
            if widget.property("helpKey") != "update":
                tooltip = re.sub(r"(?:本预览|此预览|当前预览|预览)[^。<]*。?", "", widget.toolTip())
                tooltip = tooltip.replace("路径选择与校验尚未接入。", "")
                tooltip = tooltip.replace("预检与运行尚未接入。", "开始前会执行预检，并使用所选后端运行。")
                tooltip = tooltip.replace("反查服务尚未接入", "反查由正式服务执行")
                tooltip = tooltip.replace("断点与运行服务尚未接入", "断点与运行由正式服务处理")
                tooltip = tooltip.replace("延迟和 OP 修正使用 ms；测量与自动回填服务尚未接入。", "延迟和 OP 修正使用 ms；检测结果校验后自动回填。")
                widget.setToolTip(tooltip)
        self.traversal_check.setToolTip("按原有 SID 遍历运行器处理；停止后保留当前候选，同参数下次继续。")

    def search(self):
        if not getattr(self, "migration_ready", False) or not self.is_workflow_mode():
            return super().search()
        if self.job or self.running:
            return
        try:
            if self.input_mode == "wild":
                answer = QMessageBox.question(self, "SID 遍历", f"请核对当前 TID {self.fields['wild_tid'].text()}。\n此存档创建时是否给劲敌取了名字？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
                if answer == QMessageBox.StandardButton.Cancel:
                    return
                self.named_rival = answer == QMessageBox.StandardButton.Yes
            inputs = self.collect_workflow()
        except (ValueError, KeyError, OSError) as exc:
            self.show_error(str(exc))
            return
        self.workflow = None
        self.workflow_summary = None
        self.prepared = None
        self.launch_job(lambda cancel, status: prepare_workflow(inputs, self.paths, cancel=cancel, progress=status),
                        self.workflow_finished, "正在准备方案……")

    def workflow_finished(self, prepared):
        if self.collect_workflow().fingerprint() != prepared.inputs.fingerprint():
            self.set_status("生成期间条件发生变化，请重新生成。")
            return
        self.workflow = prepared
        self.result_panel.setPlainText(prepared.details)
        if prepared.inputs.mode == "sid_traversal":
            label = self.findChild(QLabel, "traversalProgress")
            if label:
                label.setText(prepared.details.split("\n工程：")[0])
        self.set_status("方案已生成，预检通过。" if prepared.check.ok else "预检未通过，请查看详情。")

    def request_start(self):
        if hasattr(self, "accessories") and not self.running and self.job is None:
            try:
                if not self.accessories.release_for_run():
                    self.set_status("正在释放采集卡……")
                    QTimer.singleShot(100, self.request_start)
                    return
            except ValueError as exc:
                self.show_error(str(exc))
                return
        if not getattr(self, "migration_ready", False) or not self.is_workflow_mode():
            self.running_workflow = None
            return super().request_start()
        if not self.workflow or self.job or self.running:
            return
        prepared = self.workflow
        try:
            if prepared.inputs.fingerprint() != self.collect_workflow().fingerprint():
                raise ValueError("条件已变化，请重新生成")
            port, video = self.fields["port"].currentData(), self.fields["video"].currentData()
            if not port or video is None:
                raise ValueError("请先选择串口与采集卡")
        except ValueError as exc:
            self.show_error(str(exc))
            return
        def ready(command):
            if self.workflow is not prepared or self.collect_workflow().fingerprint() != prepared.inputs.fingerprint():
                self.set_status("启动检查期间条件已变化，请重新生成。")
                return
            prompt = prepared.details + f"\n\n设备：{port} / {prepared.inputs.capture_name}\n"
            if prepared.inputs.mode in ("tid", "sid_traversal"):
                prompt += "本流程会新建 / 覆盖游戏存档并关闭游戏。请核对资料和当前游戏位置。"
            else:
                prompt += "请确认游戏位置与前置条件符合当前脚本要求。"
            if QMessageBox.question(self, "开始运行", prompt) != QMessageBox.StandardButton.Yes:
                self.set_status("预检通过，等待开始运行。")
                return
            self.running_workflow = prepared
            self.running_prepared = None
            self.run_command = command
            self.decoder.reset()
            self.pending_output = ""
            self.pending_visible = False
            self.log_view.clear()
            self.running = True
            self.process.setWorkingDirectory(str(RESOURCE_ROOT))
            self.before_workflow_start(prepared, command)
            self.refresh_state()
            self.process.start(command.program, list(command.arguments))
        self.launch_job(lambda cancel, status: prepare_workflow_run(prepared, self.paths, port, video, prepared.inputs.capture_name),
                        ready, "正在重新核对设备与工程……")

    def before_workflow_start(self, prepared, command):
        self.tid_state.before_start(prepared, command)

    def _process_started(self):
        super()._process_started()
        if hasattr(self, "accessories"):
            self.accessories.run_started()

    def _process_finished(self, code, status):
        prepared = self.running_workflow
        super()._process_finished(code, status)
        if prepared and self.run_command:
            if prepared.inputs.mode == "egg" and code == 0 and prepared.inputs.request.update_precalibration:
                try:
                    update_from_manifest(self.paths.user / "precalibration.json", prepared.directory / "plan.json",
                                         self.run_command.log_path.read_text(encoding="utf-8", errors="replace"))
                except (OSError, ValueError) as exc:
                    self._append_log(f"\n预校准未更新：{exc}\n")
            suffix = ".report.txt" if prepared.inputs.mode == "sid" else ".report.json"
            report = self.run_command.log_path.with_suffix(suffix)
            if report.is_file():
                report_text = report.read_text(encoding="utf-8", errors="replace")
                self.result_panel.setPlainText(report_text)
                self._append_log(f"\n报告：{report}\n")
                if code == 0 and prepared.inputs.mode == "sid":
                    from .results import sid_report_summary
                    self.workflow_summary = sid_report_summary(report_text)
                elif prepared.inputs.mode == "sid_traversal":
                    from .results import traversal_report_summary
                    self.workflow_summary = traversal_report_summary(json.loads(report_text))
            if prepared.inputs.mode in ("tid", "sid"):
                self.workflow = None  # Workers may regenerate stages after calibration.
            flow = prepared.inputs.extra.get("flow") if prepared.inputs.mode == "tid" else None
            if flow is not None and not flow.deferred_identity:
                correction = self.tid_state.apply_successful_sid_correction(
                    self.run_command.log_path, code
                )
                if correction is not None:
                    self._append_log(
                        f"\n[SID ADV自动校准] 已将确认闪光时的修正 {correction:+d} "
                        "保存为下次重试基准。\n"
                    )
                    self.set_status(
                        f"御三家已确认闪光；SID ADV 修正 {correction:+d} 已自动保存。"
                    )
        self.refresh_state()
        if hasattr(self, "accessories"):
            self.accessories.run_finished()
            self.tid_state.poll()

    def closeEvent(self, event):
        if hasattr(self, "app_update"):
            self.app_update.close()
        if hasattr(self, "tid_state"):
            self.tid_state.save()
        if hasattr(self, "accessories") and not self.accessories.close():
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        super().closeEvent(event)
        if event.isAccepted():
            if hasattr(self, "tid_state"):
                self.tid_state.poll_timer.stop()
            if hasattr(self, "accessories"):
                self.accessories.timer.stop()
            try:
                write_json_atomic(self.paths.user / "pyside6_settings.json", {key: self.fields[key].text() for key in ("source", "ezcon", "sid_source", "tid_source")})
            except OSError:
                pass  # Base close already reports settings write failures.

    def _load_settings(self):
        super()._load_settings()
        try:
            values = json.loads((self.paths.user / "pyside6_settings.json").read_text(encoding="utf-8"))
            for key in ("sid_source", "tid_source"):
                if isinstance(values.get(key), str):
                    self.fields[key].setText(values[key])
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def sync_script(self, *_):
        if self.input_mode != "script_test":
            return
        selection = self.fields["script_entry"].currentText()
        if not selection:
            return  # The shared selector emits once while rebuilding its options.
        if selection != "自选 ECS":
            path = resolve_script_test_entry(self.fields["source"].text(), selection, require_exists=False)
            self.fields["script_path"].setText(str(path))
        self.fields["script_path"].setReadOnly(selection != "自选 ECS")

    def choose_script(self):
        path = QFileDialog.getOpenFileName(self, "选择 ECS 脚本", self.fields["script_path"].text(), "EasyCon (*.ecs)")[0]
        if path:
            self.fields["script_entry"].setCurrentText("自选 ECS")
            self.fields["script_path"].setText(path)

    def calculate_shiny_sid(self):
        try:
            r = self.reader
            tid = r.integer("tid_target")
            pid = parse_pid_hex(r.text("tid_pid"))
            minimum = sid_min_advances_for_f3(r.integer("tid_f3_delay"), language=r.text("tid_language"),
                                             sid_advance_correction=r.integer("tid_sid_correction"))
            snapshot = (r.text("tid_target"), r.text("tid_pid"), r.text("tid_language"), r.text("tid_f3_delay"), r.text("tid_sid_correction"))
        except ValueError as exc:
            self.show_error(str(exc))
            return
        def finish(hit):
            current = tuple(self.reader.text(key) for key in ("tid_target", "tid_pid", "tid_language", "tid_f3_delay", "tid_sid_correction"))
            if current != snapshot:
                self.set_status("计算期间参数改变，未覆盖新输入。")
            elif hit is None:
                self.show_error("搜索范围内没有找到该 PID 对应的闪光 SID")
            else:
                self.fields["tid_sid"].setText(f"{hit.sid:05d}")
                self.set_status(f"已回填 SID {hit.sid:05d}，最低可执行 ADV {hit.advance}。请重新生成。")
        self.launch_job(lambda cancel, status: find_earliest_shiny_sid(tid, pid, min_advances=minimum, max_advances=DEFAULT_TID_SID_SEARCH_ADVANCES), finish, "正在计算 6V 闪 SID……")

    def egg_payload(self, full):
        a, b = self.egg_parent_widgets
        parent = dict(species_id=species_id(self.fields["egg_species"].text()), compatibility=self.reader.selected_integer("egg_compatibility"),
            parent_a_gender=a[0].currentText(), parent_b_gender=b[0].currentText(),
            parent_a_ivs=[s.value() for s in a[1:]], parent_b_ivs=[s.value() for s in b[1:]])
        if not full:
            return build_egg_parent_config_payload(**parent)
        request = self.reader.egg(require_ack=False)
        return build_egg_full_config_payload(game=self.fields["egg_game"].currentText(), nx_model=request.nx_model,
            seed_mode=request.seed_mode, target_seed=request.target_seed, held_advances=request.held_advances,
            pickup_advances=request.pickup_advances, start_from_prepared_254=request.start_from_prepared_254,
            home_buffer_adaptive_threshold=request.home_buffer_adaptive_threshold, seed_startup_scheme=request.seed_startup_scheme,
            seed_calibration_scheme=request.seed_calibration_scheme, debug_log_output=request.debug_log_output,
            **parent, **self.reader.expansion())

    def save_egg(self, full):
        try:
            payload = self.egg_payload(full)
            path = QFileDialog.getSaveFileName(self, "保存孵蛋配置", "egg-full.json" if full else "egg-parent.json", "JSON (*.json)")[0]
            if path:
                write_json_atomic(Path(path), payload)
                self.set_status("孵蛋配置已保存。")
        except (OSError, ValueError, TypeError) as exc:
            self.show_error(str(exc))

    def load_egg(self, full):
        path = QFileDialog.getOpenFileName(self, "载入孵蛋配置", "", "JSON (*.json)")[0]
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            config = (parse_egg_full_config_payload if full else parse_egg_parent_config_payload)(payload)
            self.apply_egg_config(config, full)
        except (OSError, ValueError, TypeError) as exc:
            self.show_error(str(exc))

    def apply_egg_config(self, config, full):
        # Parse and validate the entire file before changing any fields.
        config = (parse_egg_full_config_payload if full else parse_egg_parent_config_payload)(config)
        self.fields["egg_species"].setText(SPECIES_EN_TO_ZH.get(get_species_name(config["egg_species_id"]), str(config["egg_species_id"])))
        compatibility_index = self.fields["egg_compatibility"].findData(config["compatibility"])
        if compatibility_index < 0:
            raise ValueError("双亲相性只能填写 20、50 或 70")
        self.fields["egg_compatibility"].setCurrentIndex(compatibility_index)
        for letter, widgets in zip(("a", "b"), self.egg_parent_widgets):
            widgets[0].setCurrentText(config[f"parent_{letter}_gender"])
            for widget, value in zip(widgets[1:], config[f"parent_{letter}_ivs"]):
                widget.setValue(value)
        if full:
            self.fields["egg_game"].setCurrentText(config["game"])
            self.fields["egg_nx"].setCurrentIndex(config["nx_model"] - 1)
            self.advanced_check.setChecked(True)
            for key, source in (("egg_seed", "target_seed"), ("egg_held", "held_advances"), ("egg_pickup", "pickup_advances")):
                self.fields[key].setText(str(config[source]))
            self.fields["egg_seed_mode"].setCurrentIndex(config["seed_mode"] + 1)
            self.fields["egg_start"].setCurrentIndex(int(config["start_from_prepared_254"]))
            self.home_buffer_check.setChecked(config["home_buffer_adaptive_threshold"])
            for key, source in (("seed_startup", "seed_startup_scheme"), ("seed_calibration", "seed_calibration_scheme"), ("output_log", "debug_log_output")):
                self.fields[key].setCurrentIndex(config[source])
            if config["reverse_expansion_layers"] is not None:
                self.fields["layers"].setValue(config["reverse_expansion_layers"])
                for axis, source in (("seed", "reverse_expansion_seed_tolerances"), ("adv", "reverse_expansion_frame_half_widths")):
                    for i, value in enumerate(config[source], 1):
                        self.fields[f"expansion_{i}_{axis}"].setText(str(value))
            else:
                self._read_expansion_defaults()
        self.egg_ack.setChecked(False)
        self.invalidate()
        self.set_status("配置已载入，请重新确认本次孵蛋前置条件。")
