"""Functional Qt window, layered on the approved preview layout."""
from __future__ import annotations

import codecs
import json
import re
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QLabel, QMessageBox, QPushButton,
    QSpinBox, QTableWidgetItem,
)

from pyside_preview import FrlgPreviewWindow, Card
from app_paths import RESOURCE_ROOT
from assets.game_text import (
    ABILITY_EN_TO_ZH, CATEGORY_EN_TO_ZH, SPECIES_EN_TO_ZH, WILD_CATEGORIES,
    FILTER_SHINY_ZH_TO_EN, FILTER_NATURE_ZH_TO_EN, FILTER_GENDER_ZH_TO_EN,
    FILTER_TYPE_ZH_TO_EN, location_to_zh,
)
from automation import (
    AutoSearchRequest, EasyCon118Options, EGG_TEMPLATE_NAME, STANDARD_TEMPLATE_NAME,
    PLANNER_STATIC_CATEGORIES, get_static_targets, probe_easycon_devices,
)
from automation.precalibration import update_from_manifest
from rng.tenlines_utils import (
    get_ability_name, get_personal, get_species_id, get_species_name,
    get_encounter_species_list, load_frlg_encounters,
)
from save_profiles import SaveProfileStore
from tid_records import TidRecordStore
from tid_session import write_json_atomic

from .jobs import Job
from .diagnostics import explain_error, parse_integer
from .profiles import ProfileManager
from .services import AppPaths, WildInputs, prepare_wild, prepare_run, display_log_line


class FrlgWindow(FrlgPreviewWindow):
    def __init__(self, *, paths=None, auto_detect=True):
        self.live_ready = False
        super().__init__()
        self.paths = paths or AppPaths()
        self.setWindowTitle("火红 / 叶绿全自动乱数 · PySide6")
        self.settings_dialog.setWindowTitle("共通设置")
        self.job = None
        self.prepared = None
        self.run_command = None
        self.running = False
        self.closing = False
        self.updating = False
        self.status_text = "请选择目标条件，搜索并生成方案。"
        self.devices = ({}, {})
        self.devices_checked = False
        self.run_input_states = None
        self.record_rows = []
        self.record_store_signature = None
        self.profile_store = SaveProfileStore(self.paths.user / "save_profiles.json")
        self.profiles_available = True
        self.record_store = TidRecordStore(self.paths.user / "tid_records.sqlite3")
        self.profile_selector = self.profile_dialog.findChild(QComboBox)
        self.profile_selector.setEnabled(True)
        self.profile_card = self.profile_selector.parentWidget().parentWidget()
        self.profile_card.findChild(QLabel, "cardSubtitle").setText("选择已有存档，或直接填写当前身份。管理存档与正式工具共用。")
        self.metric_values = self.overview.findChildren(QLabel, "metricValue")
        self.summary_context = next(label for label in self.overview.findChildren(QLabel) if label.text() == "完成左侧条件后生成")
        self.summary_context.setWordWrap(False)
        self.summary_name.setWordWrap(False)
        self.summary_symbol = self.overview.findChild(QLabel, "emptySymbol")
        self.sprite_cache = {}
        self.summary_badge = self.overview.findChild(QLabel, "pendingBadge")
        self.ready_card = next(c for c in self.overview.findChildren(Card)
                               if c.findChild(QLabel, "cardTitle") and c.findChild(QLabel, "cardTitle").text() == "运行准备")
        self.ready_values = [self.ready_card.layout.itemAt(i).layout().itemAt(3).widget() for i in range(3)]
        self.ready_dots = [self.ready_card.layout.itemAt(i).layout().itemAt(0).widget() for i in range(3)]
        self.actions = {}
        self._bind("重新检测", self.detect_devices)
        self._bind("选择脚本包", lambda: self.choose_path("source"))
        self._bind("选择 ezcon.exe", lambda: self.choose_path("ezcon", file=True))
        self._bind("管理存档", self.manage_profiles)
        self._bind("查询 / 刷新", self.refresh_records)
        self._bind("导出 CSV", self.export_records)
        self._bind_button(self.search_button, self.search)
        self._bind_button(self.cancel_button, self.cancel)
        self._bind_button(self.start_button, self.request_start)
        self._bind_button(self.stop_button, self.stop_run)
        self.profile_selector.currentIndexChanged.connect(self.select_profile)
        self.records_table.itemSelectionChanged.connect(self.record_details)
        self.fields["source"].setText(str(self.paths.source))
        self.fields["ezcon"].setText(str(self.paths.ezcon))
        self.fields["sid_source"].setText(str(self.paths.source))
        self.fields["tid_source"].setText(str(self.paths.tid_source))
        self.fields["wild_tid"].clear()
        self.fields["wild_sid"].clear()
        self._fill(self.fields["port"], [])
        self._fill(self.fields["video"], [])
        self.fields["port"].setPlaceholderText("尚未检测")
        self.fields["video"].setPlaceholderText("尚未检测")
        self._load_settings()
        try:
            self.profile_store.load()
            self.reload_profiles(apply=True)
        except (OSError, ValueError) as exc:
            self.profiles_available = False
            self.profile_selector.setEnabled(False)
            self.actions["管理存档"].setEnabled(False)
            self.status_text = f"存档文件读取失败，原文件保留：{exc}"
            self.profile_card.findChild(QLabel, "cardSubtitle").setText(self.status_text)
        self.live_ready = True
        self._populate_categories()
        self._set_live_descriptions()
        self._connect_inputs()
        self.fields["wild_game"].currentIndexChanged.connect(self._populate_locations)
        self.fields["wild_nx"].currentIndexChanged.connect(self._populate_species)
        self.fields["wild_category"].currentIndexChanged.connect(self._populate_locations)
        self.fields["wild_location"].currentIndexChanged.connect(self._populate_species)
        self.fields["wild_species"].currentIndexChanged.connect(self._populate_abilities)
        self.fields["video"].currentIndexChanged.connect(self.refresh_state)
        self.fields["port"].currentIndexChanged.connect(self.refresh_state)
        self.fields["source"].editingFinished.connect(self._read_expansion_defaults)
        self.fields["script_entry"].currentIndexChanged.connect(self._read_expansion_defaults)
        self._read_expansion_defaults()
        self.process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(environment)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.started.connect(self._process_started)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.pending_output = ""
        self.pending_visible = False
        self.runtime_issues = {}
        self.log_view.document().setMaximumBlockCount(4000)
        self.record_poll_timer = QTimer(self)
        self.record_poll_timer.setInterval(1000)
        self.record_poll_timer.timeout.connect(self._poll_record_store)
        self.record_poll_timer.start()
        self.select_page("wild")
        if auto_detect:
            QTimer.singleShot(150, self.detect_devices)

    def _bind(self, title, handler):
        matches = [b for b in self.findChildren(QPushButton) if b.text() == title]
        if len(matches) != 1:
            raise RuntimeError(f"功能入口不唯一：{title}")
        self.actions[title] = matches[0]
        self._bind_button(matches[0], handler)

    @staticmethod
    def _bind_button(button, handler):
        button.setProperty("backendAction", False)
        button.setEnabled(True)
        button.setToolTip("")
        button.clicked.connect(handler)

    def _set_live_descriptions(self):
        replacements = {
            "所有页面共用；设备、文件及更新服务尚未接入。": "共用脚本与设备设置；路径选择和设备检测已接入。",
            "源码模式不使用程序自更新。": "源码模式不使用程序自更新；更新入口仍在迁移。",
            "日志尾读与运行状态尚未接入；这里不展示模拟运行记录。": "显示真实运行输出；完整日志同时写入生成工程目录。",
            "数据库尚未接入，未读取本机记录。正式界面最多显示 1000 项，CSV 导出包含全部筛选结果。": "与正式工具共用实测数据库。最多显示 1000 项，CSV 导出包含全部筛选结果。",
            "界面初版 · 不执行真实脚本": "PySide6 · 野生 / 静态已接入",
            "设备与运行服务尚未接入": "使用正式 EasyCon 服务",
            "尚未检测采集卡，未读取任何设备标签覆盖。": "生成时自动使用正式工具已保存的设备标签覆盖；诊断和导入入口仍在迁移。",
        }
        for label in self.findChildren(QLabel):
            if label.text() in replacements:
                label.setText(replacements[label.text()])
        connected_help = {"iv", "direct", "direct_adv", "seed_hex", "capture", "item", "adaptive", "precalibration", "output_log", "reverse", "parity", "records", "logs", "entry"}
        for widget in self.findChildren(QLabel) + self.findChildren(QPushButton) + list(self.fields.values()) + list(self.capture_checks):
            if widget.property("helpKey") in connected_help or widget in self.capture_checks:
                widget.setToolTip(re.sub(r"(?:本预览|此预览|预览)[^。<]*。?", "", widget.toolTip()))
        for widget in self.findChildren(QLabel) + self.findChildren(QPushButton):
            if widget.property("helpKey") == "profile":
                widget.setToolTip("存档用于填写工具参数，不操作游戏存档。选择和管理与正式工具共用的本机资料。")
            elif widget.property("helpKey") == "source":
                widget.setToolTip("从所选正式 2.0 脚本包生成野生 / 静态工程；原始脚本与标签保持不变。")
            elif widget.property("helpKey") == "labels":
                widget.setToolTip("按采集设备名称读取正式工具已保存的覆盖，仅应用到生成工程。此处的诊断、导入和编辑仍在迁移。")
        self.profile_chip.setToolTip("选择或管理与正式工具共用的存档；手动修改字段不会覆盖已保存的存档。")
        self.log_view.setPlainText("尚无运行输出。点击开始运行后在这里查看日志。")
        self.result_panel.setPlainText("尚无方案。搜索完成后显示真实结果与正式预检详情。")
        self.log_view.setToolTip("原始运行日志保存在生成工程中；显示区隐藏完整的已知机器检查点，保留错误和未知记录。")
        self.traversal_check.setToolTip("SID 遍历运行仍在迁移；本轮已接入普通野生 / 静态与道具乱数。")
        for key in ("source", "ezcon", "port", "video"):
            self.fields[key].setToolTip("选择正式脚本包或本次运行设备；启动前会重新核对设备与运行时。")
        for key in ("wild_seed_mode", "wild_direct_seed", "wild_direct_adv"):
            self.fields[key].setToolTip("与正式工具使用相同的搜索参数。指定 Seed / 帧数时必须明确选择 Seed 模式。")

    def _connect_inputs(self):
        self.input_keys = [k for k in self.fields if k.startswith("wild_") or k.startswith("expansion_")]
        self.input_keys += ["profile_game", "profile_language", "source", "ezcon", "port", "video",
                            "seed_calibration", "seed_startup", "script_entry", "parity", "layers", "output_log"]
        for key in self.input_keys:
            widget = self.fields[key]
            signal = widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.valueChanged if isinstance(widget, QSpinBox) else widget.textChanged
            signal.connect(self.invalidate)
        for pair in self.iv_ranges:
            for widget in pair:
                widget.valueChanged.connect(self.invalidate)
        for widget in (*self.capture_checks, self.home_buffer_check, self.precalibration_check, self.advanced_check, self.item_check):
            widget.toggled.connect(self.invalidate)

    @staticmethod
    def _fill(combo, items, preferred=None):
        old = combo.currentData()
        with QSignalBlocker(combo):
            combo.clear()
            for label, value in items:
                combo.addItem(label, value)
            index = combo.findData(old)
            if index == -1 and preferred is not None:
                index = combo.findData(preferred)
            combo.setCurrentIndex(max(0, index) if combo.count() else -1)

    def game_code(self):
        return ("fr" if self.fields["wild_game"].currentIndex() == 0 else "lg") + ("_nx2" if self.fields["wild_nx"].currentIndex() else "_nx")

    def _refresh_wild_type(self):
        if not getattr(self, "live_ready", False):
            return super()._refresh_wild_type()
        self._populate_categories()
        self._refresh_wild_controls()
        self.invalidate()

    def _refresh_wild_controls(self):
        super()._refresh_wild_controls()
        if getattr(self, "live_ready", False):
            self.traversal_check.setEnabled(False)

    def _populate_categories(self):
        wild = self.fields["wild_method"].currentIndex() == 0
        categories = WILD_CATEGORIES if wild else PLANNER_STATIC_CATEGORIES
        self._fill(self.fields["wild_category"], [(CATEGORY_EN_TO_ZH.get(x, x), x) for x in categories], "Grass")
        self._populate_locations()

    def _populate_locations(self):
        category = self.fields["wild_category"].currentData()
        if self.fields["wild_method"].currentIndex() == 0:
            locations = sorted({loc for loc, cat in load_frlg_encounters(self.game_code()) if cat == category})
            items = [(location_to_zh(loc), loc) for loc in locations]
        else:
            items = [(CATEGORY_EN_TO_ZH.get(category, category), category)] if category else []
        self._fill(self.fields["wild_location"], items, "Viridian Forest")
        self.fields["wild_location"].setEnabled(bool(items))
        self._populate_species()

    def _populate_species(self):
        category = self.fields["wild_category"].currentData()
        location = self.fields["wild_location"].currentData()
        if not category or not location:
            names = []
        elif self.fields["wild_method"].currentIndex() == 0:
            names = [get_species_name(s) for s in get_encounter_species_list(location, category, self.game_code())]
        else:
            names = get_static_targets(self.game_code(), category)
        self._fill(self.fields["wild_species"], [(SPECIES_EN_TO_ZH.get(n, n), n) for n in dict.fromkeys(names)], "Pikachu")
        self.fields["wild_species"].setEnabled(bool(names))
        self._populate_abilities()

    def _populate_abilities(self):
        species = self.fields["wild_species"].currentData()
        abilities = []
        if species:
            abilities = list(dict.fromkeys(get_ability_name(x) for x in get_personal(get_species_id(species), self.game_code())["abilities"] if x))
        self._fill(self.fields["wild_ability"], [("不限", "Any"), *[(ABILITY_EN_TO_ZH.get(x, x), x) for x in abilities]])
        self.fields["wild_ability"].setEnabled(bool(species))

    def _read_expansion_defaults(self):
        template = EGG_TEMPLATE_NAME if self.fields["script_entry"].currentIndex() == 1 else STANDARD_TEMPLATE_NAME
        try:
            text = (Path(self.fields["source"].text()) / template).read_text(encoding="utf-8-sig")
            pairs = [("layers", "扩窗层数上限")]
            pairs += [(f"expansion_{i}_{axis}", f"扩窗第{i}层{name}") for i in range(1, 4) for axis, name in (("seed", "Seed容差"), ("adv", "帧半宽"))]
            for key, name in pairs:
                match = re.search(rf"(?m)^\s*\${re.escape(name)}\s*=\s*(\d+)\s*$", text)
                if match:
                    widget = self.fields[key]
                    widget.setValue(int(match[1])) if isinstance(widget, QSpinBox) else widget.setText(match[1])
        except (OSError, UnicodeError):
            pass  # Missing/corrupt templates are rejected by generation, not replaced.

    def collect_inputs(self):
        f = self.fields
        def integer(key, title):
            return parse_integer(f[key].text(), title)

        seed_index = f["wild_seed_mode"].currentIndex()
        direct = f["wild_search_mode"].currentIndex() == 1
        request = AutoSearchRequest(
            game=self.game_code(), tid=integer("wild_tid", "当前 TID"), sid=integer("wild_sid", "当前 SID"),
            method="All Wild Methods" if f["wild_method"].currentIndex() == 0 else "Static 1",
            category=f["wild_category"].currentData() or "", location=f["wild_location"].currentData() or "",
            pokemon=f["wild_species"].currentData() or "", min_advances=integer("wild_min", "最小消耗帧") if not direct else 0, max_advances=integer("wild_max", "最大消耗帧") if not direct else 0,
            iv_min=tuple(pair[0].value() for pair in self.iv_ranges), iv_max=tuple(pair[1].value() for pair in self.iv_ranges),
            shiny=FILTER_SHINY_ZH_TO_EN[f["wild_shiny"].currentText()], nature=FILTER_NATURE_ZH_TO_EN[f["wild_nature"].currentText()],
            gender=FILTER_GENDER_ZH_TO_EN[f["wild_gender"].currentText()], hidden_type=FILTER_TYPE_ZH_TO_EN[f["wild_hidden"].currentText()],
            ability=f["wild_ability"].currentData() or "Any", seed_mode=seed_index - 1 if seed_index > 0 else None,
            direct_mode=direct, direct_seed=f["wild_direct_seed"].text().strip() if direct else "", direct_advances=integer("wild_direct_adv", "指定消耗帧") if direct else None,
        )
        advanced = self.advanced_check.isChecked()
        options = EasyCon118Options(
            nx_model=f["wild_nx"].currentIndex() + 1,
            continue_capture_after_shiny=self.capture_checks[0].isChecked(), paralysis=self.capture_checks[1].isChecked(), false_swipe=self.capture_checks[2].isChecked(),
            home_buffer_adaptive_threshold=self.home_buffer_check.isChecked(), update_precalibration=self.precalibration_check.isChecked(),
            seed_calibration_scheme=f["seed_calibration"].currentIndex() if advanced else 0,
            seed_startup_scheme=f["seed_startup"].currentIndex() if advanced else 0,
            item_rng_mode=self.item_check.isChecked(), party_empty_slots=f["wild_slots"].value(),
            debug_log_output=f["output_log"].currentIndex(), frame_parity_scheme=1 - f["parity"].currentIndex() if advanced else 1,
            reverse_expansion_layers=f["layers"].value() if advanced else None,
            reverse_expansion_seed_tolerances=tuple(integer(f"expansion_{i}_seed", f"第 {i} 层 Seed 容差") for i in range(1, 4)) if advanced else None,
            reverse_expansion_frame_half_widths=tuple(integer(f"expansion_{i}_adv", f"第 {i} 层帧半宽") for i in range(1, 4)) if advanced else None,
        )
        video = f["video"].currentData()
        capture_name = self.devices[1].get(video, "")
        return WildInputs(request, options, Path(f["source"].text()), Path(f["ezcon"].text()),
                          EGG_TEMPLATE_NAME if f["script_entry"].currentIndex() == 1 else STANDARD_TEMPLATE_NAME,
                          advanced, capture_name)

    def invalidate(self, *_):
        if not self.live_ready or self.updating:
            return
        self.prepared = None
        if not self.running and not self.job:
            self.status_text = "条件已更新，请重新搜索并生成方案。"
        self.refresh_state()

    def select_page(self, key):
        super().select_page(key)
        if getattr(self, "live_ready", False):
            if key == "tid_records":
                self.refresh_records()
            self.refresh_state()

    def _refresh_common_settings(self):
        super()._refresh_common_settings()
        if getattr(self, "live_ready", False):
            if self.input_mode == "wild":
                self.advanced_scope.setText("Seed 校准与启动在主窗口顶部；以下参数将用于野生 / 静态脚本生成。")

    def refresh_state(self, *_):
        if not self.live_ready:
            return
        busy = self.job is not None or self.running
        wild = self.input_mode == "wild"
        for title, button in self.actions.items():
            button.setEnabled(not busy)
        self.actions["管理存档"].setEnabled(not busy and self.profiles_available)
        self.search_button.setEnabled(wild and not busy)
        self.cancel_button.setEnabled(self.job is not None and not self.running)
        valid = bool(wild and self.prepared and self.prepared.project and self.prepared.check.ok)
        self.start_button.setEnabled(valid and not busy and bool(self.fields["port"].currentData()) and self.fields["video"].currentData() is not None)
        self.stop_button.setEnabled(self.running)
        self.traversal_check.setEnabled(False)
        self.footer_status.setText(self.status_text if wild or self.current_page in ("logs", "tid_records") else "本页生成与运行仍在迁移")
        self.summary_badge.setText("已接入正式服务" if wild else "本页生成服务待接入")
        self.summary_context.setText("完成左侧条件后生成")
        self.summary_symbol.clear()
        self.summary_symbol.setText("◎")
        for value in self.metric_values:
            value.setText("—")
        if wild and self.prepared:
            plan = self.prepared.result.plan
            shiny = plan.target.shiny in ("Star", "Square") and not plan.request.direct_mode
            self.summary_name.setText(("闪光" if shiny else "") + SPECIES_EN_TO_ZH.get(plan.request.pokemon, plan.request.pokemon))
            location = location_to_zh(plan.request.location) if "Wild" in plan.request.method else CATEGORY_EN_TO_ZH.get(plan.request.category, plan.request.category)
            self.summary_context.setText(location + (f" · LV {plan.target.level}" if plan.target.level > 0 else " · 静态目标") if not plan.request.direct_mode else "使用指定 Seed 与消耗帧")
            sprite_key = (get_species_id(plan.request.pokemon), shiny)
            if sprite_key not in self.sprite_cache:
                self.sprite_cache[sprite_key] = QPixmap(str(RESOURCE_ROOT / "assets/sprites" / ("shiny" if shiny else "normal") / f"{sprite_key[0]}.png"))
            sprite = self.sprite_cache[sprite_key]
            if not sprite.isNull():
                self.summary_symbol.setPixmap(sprite.scaled(86, 86, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
            for value, text in zip(self.metric_values, (plan.initial_seed.seed, f"{plan.initial_seed.advances:,}", plan.iv_total)):
                value.setText(str(text))
            ivs = plan.target.ivs
            nature = {v: k for k, v in FILTER_NATURE_ZH_TO_EN.items()}.get(plan.target.nature, plan.target.nature)
            gender = {v: k for k, v in FILTER_GENDER_ZH_TO_EN.items()}.get(plan.target.gender, plan.target.gender)
            self.summary_note.setText(f"IV {ivs.hp} / {ivs.attack} / {ivs.defense} / {ivs.sp_attack} / {ivs.sp_defense} / {ivs.speed}\n{nature} · {ABILITY_EN_TO_ZH.get(plan.target.ability, plan.target.ability)} · {gender}")
            if plan.request.direct_mode:
                self.metric_values[2].setText("—")
                self.summary_note.setText("指定模式未计算个体与闪光结果；使用所填 Seed 和消耗帧。")
            self.summary_badge.setText("预检通过" if valid else "查看预检详情")
        elif wild:
            self.summary_name.setText("暂无方案")
            self.summary_note.setText("按当前条件搜索后查看结果。")
        line_count = self.summary_note.text().count("\n") + 1
        self.summary_note.setMinimumHeight(max(self.summary_note.fontMetrics().lineSpacing() * line_count + 6,
                                              self.summary_note.heightForWidth(max(180, self.summary_note.width()))))
        port = self.fields["port"].currentData() or ""
        video = self.fields["video"].currentData()
        missing_port = "未发现串口" if self.devices_checked else "尚未检测"
        missing_video = "未发现采集卡" if self.devices_checked else "尚未检测"
        info = (port or missing_port, self.devices[1].get(video, missing_video), "预检通过" if valid else "运行前预检")
        for label, dot, text, ok in zip(self.ready_values, self.ready_dots, info, (bool(port), video is not None, valid)):
            label.setText(text)
            dot.setStyleSheet(f"color: {'#22a785' if ok else '#b6c0cf'}; font-size: 11px;")
        self.device_chip.findChild(QLabel, "chipValue").setText(f"{self.fields['wild_nx'].currentText()} · {port}" if port else missing_port)
        sidebar = self.findChildren(QLabel, "sideStatusText")
        if len(sidebar) >= 2:
            sidebar[0].setText(f"{port or missing_port} · {self.devices[1].get(video, missing_video)}")
            sidebar[1].setText("正在运行" if self.running else "方案预检通过" if valid else "使用正式 EasyCon 服务")
        self._lock_run_inputs()
        self._profile_summary()

    def _lock_run_inputs(self):
        if self.running:
            if self.run_input_states is None:
                widgets = list(self.fields.values()) + [self.profile_selector, self.advanced_check, self.home_buffer_check,
                    self.precalibration_check, self.item_check, *self.capture_checks,
                    *(widget for pair in self.iv_ranges for widget in pair),
                    *(button for key, button in self.nav_buttons.items() if key not in ("wild", "logs", "tid_records"))]
                self.run_input_states = {widget: widget.isEnabled() for widget in widgets}
            for widget in self.run_input_states:
                widget.setEnabled(False)
        elif self.run_input_states is not None:
            for widget, enabled in self.run_input_states.items():
                widget.setEnabled(enabled)
            self.run_input_states = None

    def launch_job(self, work, success, status, *, allow_while_running=False):
        if self.job is not None or (self.running and not allow_while_running):
            return False
        self.status_text = status
        job = Job(work, self)
        self.job = job
        self._job_result = None
        self._job_error = None
        job.succeeded.connect(lambda result: setattr(self, "_job_result", result))
        job.failed.connect(lambda error: setattr(self, "_job_error", error))
        job.status.connect(self.set_status)
        def finish():
            self.job = None
            if self.closing:
                job.deleteLater()
                self.close()
                return
            if job.cancelled.is_set():
                self.set_status("操作已取消。")
            elif self._job_error:
                self.show_error(self._job_error)
            else:
                try:
                    success(self._job_result)
                except Exception as exc:
                    self.show_error(str(exc))
            job.deleteLater()
            self.refresh_state()
        job.finished.connect(finish)
        self.refresh_state()
        job.start()
        return True

    def set_status(self, text):
        self.status_text = text
        self.refresh_state()

    def show_error(self, text):
        explanation = explain_error(text)
        if explanation is None:
            self.set_status(text)
            self.result_panel.setPlainText(text)
            QMessageBox.warning(self, "操作未完成", text)
            return
        self.set_status(explanation.summary)
        self.result_panel.setPlainText(explanation.message + "\n\n原始错误：\n" + text)
        dialog = QMessageBox(QMessageBox.Icon.Warning, "操作未完成", explanation.message,
                             QMessageBox.StandardButton.Ok, self)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setDetailedText(text)
        dialog.exec()

    def search(self):
        if self.input_mode != "wild" or self.running or self.job:
            return
        try:
            inputs = self.collect_inputs()
            inputs.request.validate()
        except (ValueError, KeyError) as exc:
            self.show_error(f"请检查输入：{exc}")
            return
        self.prepared = None
        self.launch_job(lambda cancel, status: prepare_wild(inputs, self.paths, cancel=cancel, progress=status),
                        self._search_finished, "正在搜索……")

    def _search_finished(self, prepared):
        if prepared.inputs.fingerprint() != self.collect_inputs().fingerprint():
            self.set_status("搜索期间条件已变化，请按当前条件重新搜索。")
            return
        self.prepared = prepared
        plan = prepared.result.plan
        text = [f"目标：{SPECIES_EN_TO_ZH.get(plan.request.pokemon, plan.request.pokemon)}",
                f"初始 Seed：{plan.initial_seed.seed}；Advance：{plan.initial_seed.advances}；Seed 模式：{plan.seed_mode}",
                ("指定模式不计算个体 / 闪光；" if plan.request.direct_mode else f"IV 合计：{plan.iv_total}；") + f"路线：{plan.route_support.summary}",
                f"计划：{prepared.plan_path}", f"脚本：{prepared.project or '未生成'}"]
        text.extend(f"提示：{x}" for x in (*plan.warnings, *prepared.check.warnings))
        text.extend(f"预检未通过：{x}" for x in prepared.check.errors)
        self.result_panel.setPlainText("\n".join(text))
        self.set_status("方案已生成，预检通过。" if prepared.check.ok else "已找到方案；请查看生成 / 预检详情。")

    def cancel(self):
        if self.job:
            self.job.cancelled.set()
            self.set_status("正在取消，请等待当前检查结束……")

    def detect_devices(self):
        ezcon = Path(self.fields["ezcon"].text())
        def finish(result):
            ports, videos, output = result
            old_selection = (self.fields["port"].currentData(), self.fields["video"].currentData(),
                             self.devices[1].get(self.fields["video"].currentData()))
            self.devices = (ports, videos)
            self.devices_checked = True
            self.updating = True
            self._fill(self.fields["port"], [(p, p) for p in sorted(ports, key=lambda p: int(p[3:]))])
            self._fill(self.fields["video"], [(f"{i} · {name}", i) for i, name in sorted(videos.items())])
            self.fields["port"].setEnabled(bool(ports))
            self.fields["video"].setEnabled(bool(videos))
            self.fields["port"].setPlaceholderText("未发现串口")
            self.fields["video"].setPlaceholderText("未发现采集卡")
            self.updating = False
            new_selection = (self.fields["port"].currentData(), self.fields["video"].currentData(),
                             videos.get(self.fields["video"].currentData()))
            if old_selection[0] != new_selection[0] and hasattr(self, "accessories"):
                self.accessories.port_changed()
            if old_selection != new_selection:
                self.invalidate()
            self.result_panel.setPlainText(output)
            self.set_status("设备检测完成。" if ports and videos else "设备检测完成，串口或采集卡尚未就绪。")
        self.launch_job(lambda _cancel, _status: probe_easycon_devices(ezcon, include_video_names=True), finish, "正在检测端口与采集卡……")

    def choose_path(self, key, *, file=False):
        current = self.fields[key].text()
        path = QFileDialog.getOpenFileName(self, "选择 ezcon.exe", current, "EasyCon (ezcon.exe)")[0] if file else QFileDialog.getExistingDirectory(self, "选择脚本包", current)
        if path:
            self.fields[key].setText(path)
            if key == "source":
                self._read_expansion_defaults()

    def request_start(self):
        if not self.prepared or self.running or self.job:
            return
        try:
            if self.collect_inputs().fingerprint() != self.prepared.inputs.fingerprint():
                self.invalidate()
                raise ValueError("条件已变化，请重新生成方案")
            port, video = self.fields["port"].currentData(), self.fields["video"].currentData()
            if not port or video is None:
                raise ValueError("请先选择串口与采集卡")
        except ValueError as exc:
            self.show_error(str(exc))
            return
        prepared = self.prepared
        def ready(command):
            if self.prepared is not prepared or self.collect_inputs().fingerprint() != prepared.inputs.fingerprint():
                self.set_status("启动检查期间条件已变化，请重新生成。")
                return
            warnings = "\n".join(command.check.warnings)
            plan = prepared.result.plan
            prompt = (f"即将运行 {SPECIES_EN_TO_ZH.get(plan.request.pokemon, plan.request.pokemon)} 的已生成方案。\n"
                      f"设备：{port} / {self.devices[1][video]}\n"
                      f"Seed 模式 {plan.seed_mode}：{plan.initial_seed.settings}\n"
                      f"路线：{plan.route_support.summary}\n"
                      "请确认游戏设置、存档位置和 NS 主页状态符合 2.0 脚本要求。")
            if warnings:
                prompt += "\n\n" + warnings
            if QMessageBox.question(self, "开始运行", prompt) != QMessageBox.StandardButton.Yes:
                self.set_status("预检通过，等待开始运行。")
                return
            self.run_command = command
            self.running_prepared = prepared
            self.decoder.reset()
            self.pending_output = ""
            self.pending_visible = False
            self.log_view.clear()
            self.process.setWorkingDirectory(str(RESOURCE_ROOT))
            self.running = True
            self.refresh_state()
            self.process.start(command.program, list(command.arguments))
        self.launch_job(lambda _cancel, _status: prepare_run(prepared, port, video, self.devices[1][video]), ready, "正在重新核对设备、脚本与正式运行器……")

    def _process_started(self):
        self.runtime_issues.clear()
        self.running = True
        self.select_page("logs")
        self.set_status("正在运行；完整日志持续写入工程目录。")

    def _append_log(self, text, *, final=False):
        self.pending_output += text
        pieces = self.pending_output.split("\n")
        self.pending_output = pieces.pop()
        if final and self.pending_output:
            pieces.append(self.pending_output)
            self.pending_output = ""
        bar = self.log_view.verticalScrollBar()
        following = bar.value() >= bar.maximum() - 2
        old = bar.value()
        if self.pending_visible:
            cursor = self.log_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            # BlockUnderCursor can include the preceding paragraph separator;
            # deleting another character then clips the previous complete line.
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            if self.log_view.document().blockCount() > 1:
                cursor.deletePreviousChar()
            self.pending_visible = False
        for line in pieces:
            cleaned = display_log_line(line)
            if cleaned is not None:
                explanation = explain_error(cleaned)
                if explanation and explanation.key not in self.runtime_issues:
                    self.runtime_issues[explanation.key] = explanation
                    self.log_view.appendPlainText("[问题说明] " + explanation.message)
                    self.set_status(explanation.summary)
                self.log_view.appendPlainText(cleaned)
        if self.pending_output:
            self.log_view.appendPlainText(self.pending_output.rstrip("\r"))
            self.pending_visible = True
        bar.setValue(bar.maximum() if following else old)

    def _read_output(self):
        self._append_log(self.decoder.decode(bytes(self.process.readAllStandardOutput())))

    def _process_finished(self, code, _status):
        self._read_output()
        self._append_log(self.decoder.decode(b"", final=True), final=True)
        self.running = False
        prepared = getattr(self, "running_prepared", None)
        if code == 0 and prepared and prepared.inputs.options.update_precalibration and self.run_command:
            try:
                record = update_from_manifest(self.paths.user / "precalibration.json", prepared.project.parent / "plan.json",
                                              self.run_command.log_path.read_text(encoding="utf-8", errors="replace"))
                self._append_log("\n预校准已更新。\n" if record else "\n没有完整命中记录，预校准未更新。\n")
            except (OSError, ValueError, TypeError) as exc:
                self._append_log(f"\n预校准更新失败，原记录保留：{exc}\n")
        if self.runtime_issues:
            for explanation in self.runtime_issues.values():
                self._append_log("\n[本次运行问题] " + explanation.message + "\n")
            issue = next(iter(self.runtime_issues.values()))
            self.set_status(f"运行已结束（退出码 {code}）：{issue.summary}")
        else:
            self.set_status(f"运行进程已结束（退出码 {code}）；请查看日志中的实际结果。")
        if self.current_page == "tid_records" and not self.closing:
            QTimer.singleShot(0, self.refresh_records)
        if self.closing:
            self.close()

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.running = False
            self.show_error(f"运行进程无法启动：{self.process.errorString()}")

    def stop_run(self):
        if self.running and self.run_command:
            self.run_command.stop_path.write_text("stop\n", encoding="utf-8")
            self.set_status("已请求停止，正在等待运行器结束……")

    def _load_settings(self):
        try:
            values = json.loads((self.paths.user / "pyside6_settings.json").read_text(encoding="utf-8"))
            if not isinstance(values, dict):
                return
            for key in ("source", "ezcon"):
                if isinstance(values.get(key), str):
                    self.fields[key].setText(values[key])
        except (OSError, ValueError, TypeError):
            pass

    def closeEvent(self, event):
        if hasattr(self, "record_poll_timer"):
            self.record_poll_timer.stop()
        if self.job or self.running:
            self.closing = True
            self.cancel()
            self.stop_run()
            event.ignore()
            return
        try:
            write_json_atomic(self.paths.user / "pyside6_settings.json", {key: self.fields[key].text() for key in ("source", "ezcon")})
        except (OSError, ValueError) as exc:
            if not self.closing:
                QMessageBox.warning(self, "设置未保存", str(exc))
        super().closeEvent(event)

    def reload_profiles(self, *, apply=False):
        selected = self.profile_store.selected_profile_id
        self._fill(self.profile_selector, [("未选择（手动输入）", None), *[(p.name, p.profile_id) for p in self.profile_store.profiles]], selected)
        index = self.profile_selector.findData(selected)
        with QSignalBlocker(self.profile_selector):
            self.profile_selector.setCurrentIndex(max(0, index))
        if apply:
            profile = self.profile_store.get(selected)
            if profile:
                self.apply_profile(profile)

    def apply_profile(self, profile):
        self.updating = True
        # A save's current identity is separate from the TID page's target IDs.
        values = {"wild_game": profile.game, "profile_game": profile.game, "egg_game": profile.game,
                  "wild_nx": profile.switch_name, "egg_nx": profile.switch_name, "sid_game": profile.game,
                  "sid_nx": profile.switch_name, "sid_tid": str(profile.tid), "wild_tid": str(profile.tid),
                  "wild_sid": str(profile.sid), "tid_game": profile.game, "tid_nx": profile.switch_name,
                  "tid_language": profile.language}
        for key, value in values.items():
            widget = self.fields[key]
            with QSignalBlocker(widget):
                widget.setCurrentText(value) if isinstance(widget, QComboBox) else widget.setText(value)
        with QSignalBlocker(self.fields["profile_language"]):
            self.fields["profile_language"].setCurrentIndex(profile.language == "日文")
        self.updating = False
        if self.live_ready:
            self._populate_categories()
            self._refresh_tid_controls()
            self.invalidate()

    def select_profile(self):
        try:
            profile = self.profile_store.select(self.profile_selector.currentData())
            if profile:
                self.apply_profile(profile)
            self._profile_summary()
        except (OSError, ValueError) as exc:
            self.show_error(str(exc))

    def _profile_summary(self):
        profile = self.profile_store.get(self.profile_selector.currentData())
        tid, sid = self.fields["wild_tid"].text(), self.fields["wild_sid"].text()
        matching = (profile and tid == str(profile.tid) and sid == str(profile.sid)
                    and self.fields["wild_game"].currentText() == profile.game
                    and self.fields["wild_nx"].currentIndex() + 1 == profile.nx_model
                    and bool(self.fields["profile_language"].currentIndex()) == (profile.language == "日文"))
        name = f"{profile.name} · " if matching else ""
        text = f"{name}{tid} / {sid}" if tid and sid else "未选择 · 手动输入"
        label = self.profile_chip.findChild(QLabel, "chipValue")
        label.setWordWrap(False)
        label.setText(label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(140, label.width())))
        self.profile_chip.setToolTip(text + "\n点击选择或管理存档。")

    def manage_profiles(self):
        dialog = ProfileManager(self.profile_store, self)
        dialog.changed.connect(lambda: self.reload_profiles(apply=True))
        dialog.exec()

    def record_filters(self):
        tid = self.fields["record_tid"].text().strip()
        value = int(tid) if tid else None
        if value is not None and not 0 <= value <= 65535:
            raise ValueError("TID 必须在 0–65535 之间")
        return {"tid": value, "game": self.fields["record_game"].currentText() if self.fields["record_game"].currentIndex() else None,
                "nx_model": self.fields["record_nx"].currentIndex() or None}

    def _record_game_settings(self, row):
        labels = []
        for key, field in (("sound", "tid_sound"), ("button_mode", "tid_button"), ("seed_button", "tid_seed_button")):
            value = row.get(key)
            combo = self.fields[field]
            if value is None:
                labels.append("未记录")
            elif type(value) is int and 0 <= value < combo.count():
                labels.append(combo.itemText(value))
            else:
                labels.append(f"未知({value})")
        return tuple(labels)

    def _record_store_signature(self):
        try:
            stat = self.record_store.path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _record_row_identity(row):
        return tuple(row.get(key) for key in (
            "tid", "game", "nx_model", "language", "OP", "F1", "F2", "select_count",
            "player_name", "gender", "sound", "button_mode", "seed_button", "name_entry_button",
            "op_fixed_delay", "f1_fixed_delay", "f2_fixed_delay", "op_correction",
            "op_model_offset", "select_correction", "home_buffer_delay",
        ))

    def _poll_record_store(self):
        if self.current_page != "tid_records" or self.job is not None:
            return
        if self._record_store_signature() != self.record_store_signature:
            self.refresh_records()

    def refresh_records(self):
        try:
            filters = self.record_filters()
        except ValueError as exc:
            self.show_error(str(exc))
            return
        signature = self._record_store_signature()
        selected = None
        index = self.records_table.currentRow()
        if 0 <= index < len(self.record_rows):
            selected = self._record_row_identity(self.record_rows[index])
        def finished(rows):
            self.record_store_signature = signature
            self.record_rows = rows
            self.records_table.setRowCount(len(rows))
            selected_index = None
            for i, row in enumerate(rows):
                values = (f"{row['tid']:05d}", row["game"], f"Switch {row['nx_model']}", row["language"],
                          *self._record_game_settings(row), row["OP"], row["F1"], row["F2"], row["occurrences"],
                          row["player_name"], row["op_correction"], row["last_seen"])
                for j, value in enumerate(values):
                    self.records_table.setItem(i, j, QTableWidgetItem(str(value)))
                if selected is not None and self._record_row_identity(row) == selected:
                    selected_index = i
            if selected_index is not None:
                self.records_table.selectRow(selected_index)
            self.record_details()
            self.set_status(f"已读取 {len(rows)} 项 TID 实测记录；导出包含全部筛选结果。")
        self.launch_job(
            lambda _cancel, _status: self.record_store.rows(**filters),
            finished,
            "正在读取实测记录……",
            allow_while_running=True,
        )

    def record_details(self):
        index = self.records_table.currentRow()
        if not 0 <= index < len(self.record_rows):
            return
        row = self.record_rows[index]
        sound, button_mode, seed_button = self._record_game_settings(row)
        page = self.stack.widget(self.page_indices["tid_records"])
        label = next(l for l in page.findChildren(QLabel) if l.text().startswith("尚未接入记录详情") or l.objectName() == "liveRecordDetails")
        label.setObjectName("liveRecordDetails")
        label.setText(
            f"TID {row['tid']:05d} · {row['game']} · Switch {row['nx_model']} · {row['language']}\n"
            f"OP / F1 / F2：{row['OP']} / {row['F1']} / {row['F2']}　出现 {row['occurrences']} 次\n"
            f"主角：{row['player_name']} · {row.get('gender', '—')}　最近：{row['last_seen']}\n"
            f"OP 修正：{row['op_correction']} ms　固定延迟："
            f"{row.get('op_fixed_delay', '—')} / {row.get('f1_fixed_delay', '—')} / {row.get('f2_fixed_delay', '—')} ms\n"
            f"HOME_BUFFER：{row.get('home_buffer_delay', '—')} ms\n"
            f"声音：{sound}　按键模式：{button_mode}　Seed 启动键：{seed_button}"
        )

    def export_records(self):
        try:
            filters = self.record_filters()
        except ValueError as exc:
            self.show_error(str(exc))
            return
        path = QFileDialog.getSaveFileName(self, "导出全部筛选记录", "tid-records.csv", "CSV (*.csv)")[0]
        if path:
            self.launch_job(lambda _cancel, _status: self.record_store.export_csv(Path(path), **filters),
                            lambda count: self.set_status(f"已导出 {count} 项实测记录。"), "正在导出记录……")
