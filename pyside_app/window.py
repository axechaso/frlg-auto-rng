"""Functional Qt window, layered on the approved preview layout."""
from __future__ import annotations

import codecs
import html
import json
import re
import uuid
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QSignalBlocker, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QLabel, QMessageBox, QPushButton,
    QSpinBox, QTableWidgetItem, QWidget,
)

from pyside_preview import FrlgPreviewWindow, Card, SEED_MODE_LABELS, sync_toggle_text
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
from automation.frame_parity import resolve_frame_parity
from automation.precalibration import update_from_manifest
from automation.sid_traversal_policy import traversal_availability
from rng.tenlines_utils import (
    get_ability_name, get_personal, get_species_id, get_species_name,
    get_encounter_species_list, load_frlg_encounters,
)
from save_profiles import SaveProfileStore
from tid_records import TidRecordStore
from tid_session import write_json_atomic

from .jobs import Job
from .location_picker import (
    configure_location_combo, refresh_location_search_roles,
    selected_location, sorted_location_items,
)
from .history_controller import HistoryController
from .path_settings import restore_resource_path
from .diagnostics import explain_error, explain_popup_error, parse_integer
from .error_dialog import show_error_dialog
from .profiles import ProfileManager, ProfileWheelFilter
from .services import AppPaths, WildInputs, prepare_wild, prepare_run, display_log_line
from notifications.qq_service import QQNotificationService, QQSettingsStore
from easycon_outcome import easycon_log_has_fatal_error
from audio_observer import LOG_PREFIX
from .qq_notifications import QQNotificationDialog


_CAPTURE_REQUIREMENT_SPECIES = frozenset({97, 101, 143, 150, 175, 243, 244, 245, 249, 250, 386})
_ROAMING_SPECIES = frozenset({243, 244, 245})


def wild_run_requirements(plan, options) -> tuple[str, ...]:
    """Mirror the visible 2.0 setup requirements for a generated wild/static run."""
    request = plan.request
    species = plan.species_id
    is_wild = "Wild" in request.method
    requirements = ["第 0 轮会自动检查文字速度、战斗动画、声音和按键模式。"]

    if options.item_rng_mode and is_wild:
        requirements.append(
            f"队伍预留 {options.party_empty_slots} 个空位；脚本会保存同样数量的携带道具目标。"
        )
    elif species == 175:
        requirements.append("队伍放四只宝可梦：第五位留给波克比蛋，第六位留给 Seed 复核野生。")
    else:
        requirements.append("队伍放五只宝可梦，第六位留空。")

    if (is_wild and request.category in {"Grass", "Surf"}) or species == 175:
        requirements.append("队伍第一位放会使用甜甜香气的宝可梦。")
    if species in _ROAMING_SPECIES:
        requirements.extend(("队首宝可梦低于 50 级。", "队伍第三位放飞翔宝可梦，飞翔位于技能栏第一位。"))
    if (is_wild or species in _CAPTURE_REQUIREMENT_SPECIES) and options.paralysis:
        requirements.append("队伍第一位放麻痹宝可梦，麻痹招式位于技能栏第一位。")
    if (is_wild or species in _CAPTURE_REQUIREMENT_SPECIES) and options.false_swipe:
        requirements.append("队伍第二位放点到为止宝可梦，点到为止位于技能栏第一位。")

    requirements.append("背包第一页第一格放神奇糖果，数量不限。")
    if is_wild or species in _CAPTURE_REQUIREMENT_SPECIES:
        requirements.extend(("背包第一页第二格放血药。", "背包第三页第一格放大师球。"))
        if options.continue_capture_after_shiny:
            requirements.append("背包第三页第二格放出闪后抓捕使用的球种。")
    if species in _ROAMING_SPECIES:
        requirements.append("背包第一页第三格放黄金喷雾。")

    fishing_rods = {
        "OldRod": "破旧钓竿",
        "GoodRod": "好钓竿",
        "SuperRod": "厉害钓竿",
    }
    rod = fishing_rods.get(request.category) if is_wild else None
    requirements.append(
        "重要道具固定顺序：第1项 Teachy TV，第2项自行车；钓鱼时第3项放本次使用的钓竿。"
    )
    if plan.initial_seed.advances > 14400:
        if rod is not None:
            requirements.append(
                f"目标 Advance 超过 14400：TV 从背包使用；第0轮会自动把第3项{rod}登记为快捷键。"
            )
        elif species in _ROAMING_SPECIES:
            requirements.append("目标 Advance 超过 14400：第0轮会自动把第1项 Teachy TV 登记为快捷键；游走路线不使用自行车。")
        elif species == 175:
            requirements.append("目标 Advance 超过 14400：第0轮会自动把第1项 Teachy TV 登记为快捷键；自行车固定在第2项。")
        elif "Safari Zone" in request.location:
            requirements.append("目标 Advance 超过 14400：Teachy TV 固定在第1项并从背包使用。")
        else:
            requirements.append("目标 Advance 超过 14400：第0轮会自动把第1项 Teachy TV 登记为快捷键。")
    elif rod is not None:
        requirements.append(f"第0轮会自动把第3项{rod}登记为快捷键。")
    elif species == 175:
        requirements.append("第0轮会自动把第2项自行车登记为快捷键。")

    requirements.append("确认游戏位于方案要求的存档位置，并保持 NS 主页/游戏启动状态符合脚本要求。")
    return tuple(requirements)


def wild_start_confirmation_html(plan, options, port: str, capture_name: str, warnings=()) -> str:
    """Render a scannable, rich-text run confirmation for QMessageBox."""
    esc = lambda value: html.escape(str(value))
    target = SPECIES_EN_TO_ZH.get(plan.request.pokemon, plan.request.pokemon)
    rom = "日版（日文）" if "_jpn_" in plan.request.game else "美版（英文）"
    seed_mode = "10（日版 mono_h_a）" if options.japanese_starter else str(plan.seed_mode)
    requirements = "".join(f"<li>{esc(item)}</li>" for item in wild_run_requirements(plan, options))
    warning_items = tuple(line for warning in warnings for line in str(warning).splitlines() if line.strip())
    warning_html = "".join(f"<li>{esc(line)}</li>" for line in warning_items)
    if not warning_html:
        warning_html = "<li>EasyCon 1.6.4-a 启动预检已通过。</li>"
    return f"""
<table width="620" cellspacing="0" cellpadding="0">
  <tr><td style="font-size:18px; font-weight:600; color:#102a56; padding-bottom:8px;">即将运行：{esc(target)}</td></tr>
  <tr><td>
    <table width="100%" cellspacing="0" cellpadding="8" style="background-color:#edf3ff; border:1px solid #b8c9f5;">
      <tr><td><b>ROM</b><br>{esc(rom)}</td><td><b>设备</b><br>{esc(port)} / {esc(capture_name)}</td></tr>
      <tr><td><b>目标 Seed</b><br><span style="font-size:17px; color:#3157d5; font-weight:600;">{esc(plan.initial_seed.seed)}</span></td>
          <td><b>目标 Advance</b><br><span style="font-size:17px; color:#3157d5; font-weight:600;">{plan.initial_seed.advances:,}</span></td></tr>
      <tr><td colspan="2"><b>Seed 模式</b>：{esc(seed_mode)}　<span style="color:#53657d;">{esc(plan.initial_seed.settings)}</span></td></tr>
    </table>
  </td></tr>
  <tr><td style="padding-top:10px;">
    <table width="100%" cellspacing="0" cellpadding="9" style="background-color:#fff4d6; border:1px solid #e0ae43;">
      <tr><td><span style="font-size:15px; font-weight:600; color:#9a5200;">⚠ 运行前必须确认</span>
        <ol style="margin-top:6px; margin-bottom:4px;">{requirements}</ol>
      </td></tr>
    </table>
  </td></tr>
  <tr><td style="padding-top:10px;"><b>路线</b>：{esc(plan.route_support.summary)}</td></tr>
  <tr><td style="padding-top:8px; color:#66758a;"><b>预检信息</b><ul style="margin-top:3px; margin-bottom:0;">{warning_html}</ul></td></tr>
</table>
""".strip()


def workflow_start_confirmation_html(prepared, port: str, capture_name: str, warnings=()) -> str:
    """Render the same rich start confirmation for the non-planner workflows.

    Wild/static runs historically used :func:`wild_start_confirmation_html`,
    while the egg, SID and TID pages still showed a plain ``QMessageBox``
    string.  Keep the data specific to each workflow, but share the visual
    contract: title, ROM/device card, two prominent result cards and a
    highlighted pre-run checklist.
    """
    esc = lambda value: html.escape(str(value))
    inputs = prepared.inputs
    request = inputs.request
    mode = inputs.mode
    game = getattr(request, "game", "") or ""
    rom = "日版（日文）" if "_jpn_" in game else "美版（英文）"
    if mode == "tid" and getattr(request, "language", "英文") == "日文":
        rom = "日版（日文）"
    mode_names = {
        "egg": "孵蛋",
        "sid": "SID 采集",
        "tid": "TID → 御三家" if inputs.extra.get("flow") else "TID / SID 建档",
        "sid_traversal": "SID 遍历",
        "script_test": "脚本测试",
    }
    title = mode_names.get(mode, mode)

    if mode == "egg":
        target = f"孵蛋 · {get_species_name(request.species_id)}"
        seed_label, seed_value = "目标 Seed", getattr(request, "normalized_seed", request.target_seed)
        advance_label = "目标 Advance"
        advance_value = f"Held {request.held_advances:,} / Pickup {request.pickup_advances:,}"
        mode_prefix = "自动选择 → " if inputs.extra.get("seed_mode_auto") else ""
        seed_mode = f"{mode_prefix}{request.seed_mode} · 启动方案 {request.seed_startup_scheme}"
        checklist = (
            "队伍与亲本资料按方案填写，蛋生成与领取位置保持不变。",
            "背包第一页第一格放神奇糖果，数量不限。",
            "重要道具第1项放 Teachy TV、第2项放自行车；前置设置检查会自动登记第2项自行车。",
            "确认游戏位于方案要求的存档位置，并保持 NS 主页/游戏启动状态符合脚本要求。",
        )
    elif mode == "sid":
        target = "SID 逐只采集"
        seed_label, seed_value = "目标 TID", f"{request.tid:05d}"
        advance_label, advance_value = "队伍数量", str(request.party_count)
        seed_mode = f"Switch {request.nx_model} · 起始位置 {request.start_slot}"
        checklist = (
            f"队伍从第 {request.start_slot} 位开始，连续准备 {request.party_count} 只目标个体。",
            "背包第一页第一格放神奇糖果，数量不限。",
            "确认游戏位于方案要求的存档位置，并保持 NS 主页/游戏启动状态符合脚本要求。",
        )
    elif mode == "tid":
        target = title
        seed_label, seed_value = "目标 TID", f"{request.target_tid:05d}"
        sid_value = "运行后确定" if request.sid_random else f"{request.target_sid:05d}"
        advance_label, advance_value = "目标 SID", sid_value
        seed_mode = f"{request.language} · Switch {request.nx_model} · {'穷举' if request.mode == 0 else '乱数'}"
        checklist = (
            "确认主角名称、目标 TID/SID 与游戏版本填写正确。",
            "本流程会新建 / 覆盖游戏存档并在阶段之间关闭游戏。",
            "确认游戏位于方案要求的存档位置，并保持 NS 主页/游戏启动状态符合脚本要求。",
        )
        flow = inputs.extra.get("flow")
        if flow is not None and getattr(flow, "any_tid_sixv_sid", False):
            checklist = (
                "先穷举并去噪确认一个任意 TID 与对应参数。",
                "随后再次新建游戏，按锁定参数乱数出 6V 闪 SID；首次穷举的游戏进度不会保留。",
                "最后通过御三家验证候选 SID，成功后工具会预填一个新建存档草稿。",
                "确认游戏位于方案要求的存档位置，并保持 NS 主页/游戏启动状态符合脚本要求。",
            )
    elif mode == "sid_traversal":
        target = "SID 遍历"
        seed_label, seed_value = "目标 TID", f"{request.tid:05d}"
        advance_label, advance_value = "SID 起点 / 上限", f"{inputs.extra.get('start_advance') or '自动'} / {inputs.extra.get('max_advances', '—'):,}"
        seed_mode = f"Switch {request.nx_model} · {'已取名劲敌' if inputs.extra.get('named_rival') else '未取名劲敌'}"
        checklist = (
            "确认 TID 填写正确，并确认劲敌取名状态与存档一致。",
            "只有明确识别到闪光目标后才会结束遍历并输出 SID。",
            "确认游戏位于方案要求的存档位置，并保持 NS 主页/游戏启动状态符合脚本要求。",
        )
    else:
        target = "脚本测试"
        seed_label, seed_value = "执行脚本", Path(inputs.extra.get("script", "")).name or "未选择"
        advance_label, advance_value = "后端", inputs.extra.get("backend", "—")
        seed_mode = "仅执行所选 ECS，不替换参数"
        checklist = (
            "确认所选 ECS 脚本、串口与采集卡均为本次测试目标。",
            "脚本测试不会替换自选脚本中的用户参数。",
        )

    details = [line for line in str(getattr(prepared, "details", "")).splitlines()
               if line.strip() and not line.startswith("工程：")]
    detail_html = "".join(f"<li>{esc(line)}</li>" for line in details[:6])
    warning_items = tuple(line for warning in warnings for line in str(warning).splitlines() if line.strip())
    if not warning_items:
        warning_items = tuple(getattr(prepared.check, "warnings", ()))
    warning_html = "".join(f"<li>{esc(line)}</li>" for line in warning_items if line.strip())
    if not warning_html:
        warning_html = "<li>EasyCon 1.6.4-a 启动预检已通过。</li>"
    requirements = "".join(f"<li>{esc(item)}</li>" for item in checklist)
    if detail_html:
        requirements += f"<li><b>方案</b><ul>{detail_html}</ul></li>"
    return f"""
<table width="620" cellspacing="0" cellpadding="0">
  <tr><td style="font-size:18px; font-weight:600; color:#102a56; padding-bottom:8px;">即将运行：{esc(target)}</td></tr>
  <tr><td>
    <table width="100%" cellspacing="0" cellpadding="8" style="background-color:#edf3ff; border:1px solid #b8c9f5;">
      <tr><td><b>ROM</b><br>{esc(rom)}</td><td><b>设备</b><br>{esc(port)} / {esc(capture_name)}</td></tr>
      <tr><td><b>{esc(seed_label)}</b><br><span style="font-size:17px; color:#3157d5; font-weight:600;">{esc(seed_value)}</span></td>
          <td><b>{esc(advance_label)}</b><br><span style="font-size:17px; color:#3157d5; font-weight:600;">{esc(advance_value)}</span></td></tr>
      <tr><td colspan="2"><b>运行模式</b>：{esc(title)}　<span style="color:#53657d;">{esc(seed_mode)}</span></td></tr>
    </table>
  </td></tr>
  <tr><td style="padding-top:10px;">
    <table width="100%" cellspacing="0" cellpadding="9" style="background-color:#fff4d6; border:1px solid #e0ae43;">
      <tr><td><span style="font-size:15px; font-weight:600; color:#9a5200;">⚠ 运行前必须确认</span>
        <ol style="margin-top:6px; margin-bottom:4px;">{requirements}</ol>
      </td></tr>
    </table>
  </td></tr>
  <tr><td style="padding-top:8px; color:#66758a;"><b>预检信息</b><ul style="margin-top:3px; margin-bottom:0;">{warning_html}</ul></td></tr>
</table>
""".strip()


class FrlgWindow(FrlgPreviewWindow):
    def __init__(self, *, paths=None, auto_detect=True):
        self.live_ready = False
        super().__init__()
        self.paths = paths or AppPaths()
        self.qq_service = QQNotificationService(self, store=QQSettingsStore(self.paths.user / "qq-notifications.json"))
        self.qq_dialog = None
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
        configure_location_combo(self.fields["wild_location"])
        self.devices_checked = False
        self.run_input_states = None
        self.preferred_frame_parity_scheme = 1
        self.manual_profile_draft = None
        self._settings_values = {}
        self._settings_invalid = False
        self.record_rows = []
        self.record_store_signature = None
        self.all_history_rows = []
        self.history_rows = []
        self.history_controller = HistoryController(self)
        self.profile_store = SaveProfileStore(self.paths.user / "save_profiles.json")
        self.profiles_available = True
        self.record_store = TidRecordStore(self.paths.user / "tid_records.sqlite3")
        self.profile_selector = self.profile_dialog.findChild(QComboBox)
        self.profile_mystery_gift = self.profile_dialog.findChild(QCheckBox, "profileMysteryGift")
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
        self.actions = {}
        self._bind("重新检测", self.detect_devices)
        self._bind("选择脚本包", lambda: self.choose_path("source"))
        self._bind("选择 ezcon.exe", lambda: self.choose_path("ezcon", file=True))
        self._bind("管理存档", self.manage_profiles)
        self._bind("查询 / 刷新", self.refresh_records)
        self._bind("导出 CSV", self.export_records)
        self._bind("刷新历史日志", lambda: self.history_controller.refresh(force=True))
        self._bind("打开日志文件", lambda: self.open_history_log(directory=False))
        self._bind("打开所在文件夹", lambda: self.open_history_log(directory=True))
        self._bind_button(self.search_button, self.search)
        self._bind_button(self.cancel_button, self.cancel)
        self._bind_button(self.start_button, self.request_start)
        self._bind_button(self.stop_button, self.stop_run)
        self.qq_notification_button.clicked.connect(self.show_qq_notifications)
        self.profile_selector.currentIndexChanged.connect(self.select_profile)
        self.profile_mystery_gift.toggled.connect(self._profile_gift_changed)
        self.profile_wheel_filter = ProfileWheelFilter(self)
        self.profile_wheel_filter.stepped.connect(self._wheel_select_profile)
        for widget in (self.profile_chip, *self.profile_chip.findChildren(QWidget), self.profile_selector):
            widget.installEventFilter(self.profile_wheel_filter)
        self.records_table.itemSelectionChanged.connect(self.record_details)
        self.history_table.selectionModel().selectionChanged.connect(self.history_log_details)
        self.fields["history_workflow"].currentIndexChanged.connect(self.filter_history_logs)
        self.fields["history_search"].textChanged.connect(self.filter_history_logs)
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
        self.manual_profile_draft = self._capture_manual_profile_draft()
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
        self.fields["parity"].currentIndexChanged.connect(self._remember_frame_parity_preference)
        self.fields["wild_game"].currentIndexChanged.connect(self._populate_locations)
        self.fields["wild_nx"].currentIndexChanged.connect(self._populate_species)
        self.fields["profile_language"].currentIndexChanged.connect(self._populate_categories)
        self.fields["wild_category"].currentIndexChanged.connect(self._populate_locations)
        self.fields["wild_location"].currentIndexChanged.connect(self._populate_species)
        self.fields["wild_location"].editTextChanged.connect(self._populate_species)
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
        self._run_id = ""
        self._run_terminal_handled = False
        self._manual_stop_requested = False
        self._run_notification_sent = False
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
            "界面初版 · 不执行真实脚本": "PySide6 · 正式服务",
            "设备与运行服务尚未接入": "使用正式 EasyCon 服务",
            "尚未检测采集卡，未读取任何设备标签覆盖。": "生成时自动使用已保存的设备标签覆盖；可在日志页诊断、导入或清除覆盖。",
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
                widget.setToolTip("按采集设备名称读取已保存的覆盖，仅应用到生成工程；可在日志页诊断、导入或清除覆盖。")
        self.profile_chip.setToolTip("选择或管理与正式工具共用的存档；手动修改字段不会覆盖已保存的存档。")
        self.log_view.setPlainText("尚无运行输出。点击开始运行后在这里查看日志。")
        self.result_panel.setPlainText("尚无方案。搜索完成后显示真实结果与正式预检详情。")
        self.log_view.setToolTip("原始运行日志保存在生成工程中；显示区隐藏完整的已知机器检查点，保留错误和未知记录。")
        self.traversal_check.setToolTip("唯一 PID 的非闪个体可排除 TSV；目标或非目标闪光可反查 TSV。停止后保留证据和进度，同参数下次继续。")
        for key in ("source", "ezcon", "port", "video"):
            self.fields[key].setToolTip("选择正式脚本包或本次运行设备；启动前会重新核对设备与运行时。")
        for key in ("wild_seed_mode", "wild_direct_seed", "wild_direct_adv"):
            self.fields[key].setToolTip(
                "指定 Seed / 帧数时可自动遍历当前版本的 Seed 表，"
                "优先选择启动等待时间最短的可达模式；也可手动强制指定模式。"
            )

    def _connect_inputs(self):
        self.input_keys = [k for k in self.fields if k.startswith("wild_") or k.startswith("expansion_")]
        self.input_keys += ["profile_game", "profile_language", "source", "ezcon", "port", "video",
                            "seed_calibration", "seed_startup", "script_entry", "parity", "layers", "output_log",
                            "togepi_reverse_mode", "togepi_reverse_adv", "egg_reverse_mode", "egg_reverse_seed", "egg_reverse_min_adv", "egg_reverse_max_adv"]
        for key in self.input_keys:
            widget = self.fields[key]
            signal = widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.valueChanged if isinstance(widget, QSpinBox) else widget.textChanged
            signal.connect(self.invalidate)
        self.fields["wild_location"].editTextChanged.connect(self.invalidate)
        for pair in self.iv_ranges:
            for widget in pair:
                widget.valueChanged.connect(self.invalidate)
        for widget in (*self.capture_checks, self.home_buffer_check, self.precalibration_check,
                       self.advanced_check, self.item_check, self.dunsparce_three_segment_check):
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
            if combo.property("locationSearch"):
                refresh_location_search_roles(combo)

    def game_code(self, *, include_profile_language=True):
        family = "fr" if self.fields["wild_game"].currentIndex() == 0 else "lg"
        language = "_jpn" if include_profile_language and self.fields["profile_language"].currentIndex() == 1 else ""
        console = "_nx2" if self.fields["wild_nx"].currentIndex() else "_nx"
        return family + language + console

    def _refresh_wild_type(self):
        if not getattr(self, "live_ready", False):
            return super()._refresh_wild_type()
        self._populate_categories()
        self._refresh_wild_controls()
        self.invalidate()

    def _refresh_wild_controls(self):
        super()._refresh_wild_controls()
        wild = self.fields["wild_method"].currentIndex() == 0
        item = self.item_check.isChecked()
        traversal = self.traversal_check.isChecked()
        direct = self.fields["wild_search_mode"].currentIndex() == 1
        try:
            availability = traversal_availability(
                method="All Wild Methods" if wild else "Static 1",
                category=self.fields["wild_category"].currentData() or "",
                location=selected_location(self.fields["wild_location"]) or "",
                game=self.game_code(),
                pokemon=self.fields["wild_species"].currentData() or "",
                direct_mode=direct,
                item_mode=item,
            )
        except (ValueError, KeyError, AttributeError):
            availability = None
        available = bool(availability and availability.supported)
        reason = availability.reason if availability else "当前条件尚未就绪。"
        busy = getattr(self, "running", False) or getattr(self, "job", None) is not None
        self.traversal_check.setEnabled((available or traversal) and not item and not busy)
        self.traversal_status.setText(reason)
        self.traversal_status.setToolTip(reason)
        self.fields["wild_traversal_max"].setEnabled(traversal and not busy)
        self.fields["wild_traversal_start"].setEnabled(
            traversal and self.advanced_check.isChecked() and not busy
        )

    def _populate_categories(self):
        japanese = self.fields["profile_language"].currentIndex() == 1
        if japanese and self.fields["wild_method"].currentIndex() != 1:
            with QSignalBlocker(self.fields["wild_method"]):
                self.fields["wild_method"].setCurrentIndex(1)
        wild = self.fields["wild_method"].currentIndex() == 0
        categories = WILD_CATEGORIES if wild else PLANNER_STATIC_CATEGORIES
        if japanese:
            categories = ("Starter",)
            self.fields["wild_method"].setToolTip("日版当前只支持静态御三家；使用日版 mono_h_a Seed 表与专用识图。")
        else:
            self.fields["wild_method"].setToolTip("")
        seed_modes = self.fields["wild_seed_mode"]
        seed_mode_items = ("自动选择", SEED_MODE_LABELS[0]) if japanese else ("自动选择", *SEED_MODE_LABELS)
        if tuple(seed_modes.itemText(i) for i in range(seed_modes.count())) != seed_mode_items:
            with QSignalBlocker(seed_modes):
                seed_modes.clear()
                seed_modes.addItems(seed_mode_items)
                seed_modes.setCurrentIndex(0)
        self._fill(self.fields["wild_category"], [(CATEGORY_EN_TO_ZH.get(x, x), x) for x in categories], "Grass")
        self._populate_locations()

    def _populate_locations(self):
        category = self.fields["wild_category"].currentData()
        if self.fields["wild_method"].currentIndex() == 0:
            locations = {loc for loc, cat in load_frlg_encounters(self.game_code()) if cat == category}
            items = sorted_location_items(locations)
        else:
            items = [(CATEGORY_EN_TO_ZH.get(category, category), category)] if category else []
        self._fill(self.fields["wild_location"], items, "Viridian Forest")
        self.fields["wild_location"].setEnabled(bool(items))
        self._populate_species()

    def _populate_species(self):
        category = self.fields["wild_category"].currentData()
        location = selected_location(self.fields["wild_location"])
        if not category or not location:
            names = []
        elif self.fields["wild_method"].currentIndex() == 0:
            names = [get_species_name(s) for s in get_encounter_species_list(location, category, self.game_code())]
        else:
            names = get_static_targets(self.game_code(), category)
        self._fill(self.fields["wild_species"], [(SPECIES_EN_TO_ZH.get(n, n), n) for n in dict.fromkeys(names)], "Pikachu")
        self.fields["wild_species"].setEnabled(bool(names))
        self._populate_abilities()
        self._refresh_wild_controls()

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
            pairs += [
                ("togepi_reverse_adv", "波克比野生反查帧半宽"),
                ("egg_reverse_seed", "孵蛋野生Seed容差"),
                ("egg_reverse_min_adv", "孵蛋野生最小消耗帧"),
                ("egg_reverse_max_adv", "孵蛋野生最大消耗帧"),
            ]
            # The latest mother initializes these globals to 0, then derives
            # [Held, Pickup + 4000] at runtime. They are not useful manual
            # defaults: preserve the visible advanced bounds/user config.
            dynamic_egg_window = all(line in text for line in (
                "    $孵蛋野生最小消耗帧 = $孵蛋生成目标帧",
                "    $孵蛋野生最大消耗帧 = $孵蛋领取目标帧 + 4000",
            ))
            for key, name in pairs:
                if dynamic_egg_window and key in {"egg_reverse_min_adv", "egg_reverse_max_adv"}:
                    continue
                if key == "togepi_reverse_adv" and self.fields["togepi_reverse_mode"].currentIndex() == 1:
                    continue  # Do not overwrite an explicit manual preference.
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
        location = selected_location(f["wild_location"])
        if location is None:
            raise ValueError("地点：请输入名称后从匹配列表中选择当前遭遇方式下的地点，不能使用未完成的搜索文字。")
        request = AutoSearchRequest(
            game=self.game_code(), tid=integer("wild_tid", "当前 TID"), sid=integer("wild_sid", "当前 SID"),
            method="All Wild Methods" if f["wild_method"].currentIndex() == 0 else "Static 1",
            category=f["wild_category"].currentData() or "", location=location,
            pokemon=f["wild_species"].currentData() or "", min_advances=integer("wild_min", "最小消耗帧") if not direct else 0, max_advances=integer("wild_max", "最大消耗帧") if not direct else 0,
            iv_min=tuple(pair[0].value() for pair in self.iv_ranges), iv_max=tuple(pair[1].value() for pair in self.iv_ranges),
            shiny=FILTER_SHINY_ZH_TO_EN[f["wild_shiny"].currentText()], nature=FILTER_NATURE_ZH_TO_EN[f["wild_nature"].currentText()],
            gender=FILTER_GENDER_ZH_TO_EN[f["wild_gender"].currentText()], hidden_type=FILTER_TYPE_ZH_TO_EN[f["wild_hidden"].currentText()],
            ability=f["wild_ability"].currentData() or "Any", seed_mode=seed_index - 1 if seed_index > 0 else None,
            direct_mode=direct, direct_seed=f["wild_direct_seed"].text().strip() if direct else "", direct_advances=integer("wild_direct_adv", "指定消耗帧") if direct else None,
            dunsparce_three_segment=self.dunsparce_three_segment_check.isChecked(),
        )
        advanced = self.advanced_check.isChecked()
        options = EasyCon118Options(
            nx_model=f["wild_nx"].currentIndex() + 1,
            japanese_starter="_jpn_" in request.game,
            continue_capture_after_shiny=self.capture_checks[0].isChecked(), paralysis=self.capture_checks[1].isChecked(), false_swipe=self.capture_checks[2].isChecked(),
            record_shiny_video=self.capture_checks[3].isChecked(), stop_on_non_target_shiny=self.capture_checks[4].isChecked(),
            home_buffer_adaptive_threshold=self.home_buffer_check.isChecked(), update_precalibration=self.precalibration_check.isChecked(),
            seed_calibration_scheme=f["seed_calibration"].currentIndex() if advanced else 0,
            seed_startup_scheme=f["seed_startup"].currentIndex() if advanced else 0,
            item_rng_mode=self.item_check.isChecked(), party_empty_slots=f["wild_slots"].value(),
            debug_log_output=f["output_log"].currentIndex(),
            frame_parity_scheme=resolve_frame_parity(
                requested=self.preferred_frame_parity_scheme if advanced else 1,
                mystery_gift_enabled=self.profile_mystery_gift.isChecked(),
                is_egg=False,
            ).effective,
            mystery_gift_enabled=self.profile_mystery_gift.isChecked(),
            reverse_expansion_layers=f["layers"].value() if advanced else None,
            reverse_expansion_seed_tolerances=tuple(integer(f"expansion_{i}_seed", f"第 {i} 层 Seed 容差") for i in range(1, 4)) if advanced else None,
            reverse_expansion_frame_half_widths=tuple(integer(f"expansion_{i}_adv", f"第 {i} 层帧半宽") for i in range(1, 4)) if advanced else None,
            togepi_seed_reverse_frame_half_width=integer("togepi_reverse_adv", "波克比 Seed 反查帧半宽")
                if advanced and f["togepi_reverse_mode"].currentIndex() == 1 else None,
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
        if hasattr(self, "page_guides"):
            self.page_guides.page_changed(key)
        if hasattr(self, "history_controller") and key != "history_logs":
            self.history_controller.leave()
        super().select_page(key)
        if getattr(self, "live_ready", False):
            if key == "tid_records":
                self.refresh_records()
            elif key == "history_logs":
                self.refresh_history_logs()
            self.refresh_state()
            if hasattr(self, "accessories"):
                self.accessories.update_input_visibility()

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
        history_actions = {"刷新历史日志", "打开日志文件", "打开所在文件夹"}
        for title, button in self.actions.items():
            button.setEnabled(not busy or title in history_actions)
        self.actions["管理存档"].setEnabled(not busy and self.profiles_available)
        self.search_button.setEnabled(wild and not busy)
        self.cancel_button.setEnabled(self.job is not None and not self.running)
        valid = bool(wild and self.prepared and self.prepared.project and self.prepared.check.ok)
        self.start_button.setEnabled(valid and not busy and bool(self.fields["port"].currentData()) and self.fields["video"].currentData() is not None)
        self.stop_button.setEnabled(self.running)
        self.footer_status.setText(self.status_text)
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
            rare_form = " · 三节形态" if plan.request.dunsparce_three_segment else ""
            self.summary_note.setText(f"IV {ivs.hp} / {ivs.attack} / {ivs.defense} / {ivs.sp_attack} / {ivs.sp_defense} / {ivs.speed}\n{nature} · {ABILITY_EN_TO_ZH.get(plan.target.ability, plan.target.ability)} · {gender}{rare_form}")
            if plan.request.direct_mode:
                self.metric_values[2].setText("—")
                display_mode = "10（日版）" if self.prepared.inputs.options.japanese_starter else str(plan.seed_mode)
                self.summary_note.setText(
                    "指定模式未计算个体与闪光结果；"
                    f"Seed 模式 {display_mode}，启动等待 {plan.initial_seed.seed_time:,} ms。"
                )
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
                widgets = [
                    widget for key, widget in self.fields.items()
                    if key not in {"history_workflow", "history_search"}
                ] + [self.profile_selector, self.advanced_check, self.home_buffer_check,
                    self.precalibration_check, self.label_supervision_check, self.item_check,
                    self.dunsparce_three_segment_check, *self.capture_checks,
                    *(widget for pair in self.iv_ranges for widget in pair),
                    *(button for key, button in self.nav_buttons.items()
                      if key not in ("wild", "logs", "history_logs", "tid_records"))]
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
        if hasattr(self, "accessories") and not self.running and not self.job:
            if self.accessories.repair_prompts.preflight(text):
                self.set_status(text)
                self.result_panel.setPlainText(text)
                return
        explanation = explain_popup_error(text)
        self.set_status(explanation.summary)
        self.result_panel.setPlainText(explanation.message + "\n\n原始错误：\n" + text)
        show_error_dialog(self, "操作未完成", text)

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
        rom_language = "日版（日文）" if "_jpn_" in plan.request.game else "美版（英文）"
        display_mode = "10（日版 mono_h_a）" if prepared.inputs.options.japanese_starter else str(plan.seed_mode)
        text = [f"目标：{SPECIES_EN_TO_ZH.get(plan.request.pokemon, plan.request.pokemon)}",
                f"ROM：{rom_language}",
                f"初始 Seed：{plan.initial_seed.seed}；Advance：{plan.initial_seed.advances}；Seed 模式：{display_mode}",
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
            plan = prepared.result.plan
            prompt = wild_start_confirmation_html(
                plan,
                prepared.inputs.options,
                port,
                self.devices[1][video],
                command.check.warnings,
            )
            if not self._confirm_wild_start(prompt):
                self.set_status("预检通过，等待开始运行。")
                return
            self.begin_accepted_run(command, prepared_wild=prepared)
        supervision = self.label_supervision_check.isChecked()
        accessories = getattr(self, "accessories", None)
        preview_video = accessories.preview_video_requested() if accessories else False
        self.launch_job(lambda _cancel, _status: prepare_run(
            prepared, port, video, self.devices[1][video], self.paths,
            label_supervision=supervision, preview_video=preview_video,
        ), ready, "正在重新核对设备、脚本与正式运行器……")

    def _confirm_wild_start(self, prompt: str) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("开始运行")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setTextFormat(Qt.TextFormat.RichText)
        dialog.setText(prompt)
        dialog.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.Yes)
        dialog.setEscapeButton(QMessageBox.StandardButton.No)
        yes_button = dialog.button(QMessageBox.StandardButton.Yes)
        no_button = dialog.button(QMessageBox.StandardButton.No)
        if yes_button is not None:
            yes_button.setText("开始运行")
        if no_button is not None:
            no_button.setText("返回检查")
        label = dialog.findChild(QLabel, "qt_msgbox_label")
        if label is not None:
            label.setMinimumWidth(620)
            label.setWordWrap(True)
        return dialog.exec() == QMessageBox.StandardButton.Yes

    def _begin_run_notification(self):
        """Start a new notification event for each accepted run."""
        # This ID deduplicates desktop notifications; RunCommand.run_id binds
        # the worker, reports and any script input-state session.
        self._run_id = uuid.uuid4().hex
        self._manual_stop_requested = False
        self._run_notification_sent = False
        self._run_terminal_handled = False

    def begin_accepted_run(
        self,
        command,
        *,
        prepared_wild=None,
        prepared_workflow=None,
    ):
        self.run_command = command
        self.running_prepared = prepared_wild
        self.running_workflow = prepared_workflow
        self._begin_run_notification()
        self.decoder.reset()
        self.pending_output = ""
        self.pending_visible = False
        self.log_view.clear()
        self.running = True
        self.refresh_state()
        self.select_page("logs")
        if prepared_workflow is not None and prepared_workflow.inputs.mode == "script_test":
            script_path = prepared_workflow.inputs.extra.get("script", "")
            backend = prepared_workflow.inputs.extra.get("backend", "未知后端")
        elif prepared_workflow is not None:
            script_path = str(prepared_workflow.project)
            backend = prepared_workflow.inputs.extra.get("backend", "兼容运行器")
        else:
            script_path = str(prepared_wild.project)
            backend = "EasyCon 1.6.4-a 兼容运行器"
        startup = f"正在启动脚本：{script_path}\n所选后端：{backend}\n"
        self.set_status("正在启动；日志页已就绪。")
        self._append_log(startup)
        self.process.setWorkingDirectory(str(RESOURCE_ROOT))
        try:
            if hasattr(self, "accessories"):
                self.accessories.prepare_run(command)
            if prepared_workflow is not None:
                self.before_workflow_start(prepared_workflow, command)
        except (OSError, RuntimeError, ValueError) as exc:
            self._finish_start_failure(f"运行准备失败：{exc}")
            return
        self.process.start(command.program, list(command.arguments))

    def _process_started(self):
        self.runtime_issues.clear()
        self.running = True
        self.set_status("正在运行；完整日志持续写入工程目录。")

    def apply_script_action_view(self, view):
        if view is None:
            return
        values = self.script_action_values
        searching = view.phase == "searching"
        uncertain = (
            view.phase in {"unsupported", "disconnected", "error", "stale", "unknown"}
            or view.connection in {"unknown", "disconnected", "error"}
        )
        if searching:
            current = "计算中，无按键输出"
            direction = "计算中"
        elif uncertain:
            current = view.message or "当前按键状态未知"
            direction = "方向与摇杆未知"
        else:
            current = " + ".join(view.snapshot["buttons"]) or "当前无按键输出"
            direction = (
                f"十字 {view.snapshot['hat']} · "
                f"左摇杆 {view.snapshot['left_stick'][0]}, {view.snapshot['left_stick'][1]} · "
                f"右摇杆 {view.snapshot['right_stick'][0]}, {view.snapshot['right_stick'][1]}"
            )
        recent = "—"
        if view.recent_action and view.recent_action_at:
            import time
            if time.monotonic() - view.recent_action_at <= 1.0:
                recent = f"{view.recent_action_time} · {view.recent_action}"
        phase_names = {
            "starting": "切换阶段", "searching": "计算中", "running": "运行中",
            "stopping": "正在停止", "ended": "已结束", "failed": "失败",
            "unsupported": "不支持回显", "disconnected": "连接中断",
            "error": "状态无效", "stale": "状态未知", "unknown": "状态未知",
            "idle": "等待运行",
        }
        stage = view.stage_id.replace("_", " ") if view.stage_id else "脚本"
        phase = phase_names.get(view.phase, view.phase)
        if view.source == "mock":
            phase += " · 模拟状态"
        values["buttons"].setText(current)
        values["direction"].setText(direction)
        values["recent"].setText(recent)
        values["phase"].setText(f"{stage} · {phase}")
        values["phase"].setToolTip(view.message)

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
        self._remove_pending_log_line()
        for line in pieces:
            if hasattr(self, "accessories") and self.accessories.consume_input_session_marker(line):
                continue
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

    def _remove_pending_log_line(self):
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

    def append_observation_log(self, line):
        """Render a side observation without feeding stdout/checkpoint parsers."""
        line = " ".join(str(line).split())
        if not line.startswith(LOG_PREFIX):
            raise ValueError("观察日志缺少来源标记")
        bar = self.log_view.verticalScrollBar()
        following, old = bar.value() >= bar.maximum() - 2, bar.value()
        self._remove_pending_log_line()
        self.log_view.appendPlainText(line)
        if self.pending_output:
            self.log_view.appendPlainText(self.pending_output.rstrip("\r"))
            self.pending_visible = True
        bar.setValue(bar.maximum() if following else old)

    def _read_output(self):
        self._append_log(self.decoder.decode(bytes(self.process.readAllStandardOutput())))

    def _process_finished(self, code, _status):
        if self._run_terminal_handled:
            return
        self._run_terminal_handled = True
        self._read_output()
        self._append_log(self.decoder.decode(b"", final=True), final=True)
        self.running = False
        flow_text = "\n".join(line for line in self.log_view.toPlainText().splitlines() if not line.startswith(LOG_PREFIX))
        fatal_output = easycon_log_has_fatal_error(flow_text)
        prepared = getattr(self, "running_prepared", None)
        if code == 0 and not fatal_output and prepared and prepared.inputs.options.update_precalibration and self.run_command:
            try:
                record = update_from_manifest(self.paths.user / "precalibration.json", prepared.project.parent / "plan.json",
                                              self.run_command.log_path.read_text(encoding="utf-8", errors="replace"))
                self._append_log("\n预校准已更新。\n" if record else "\n没有完整命中记录，预校准未更新。\n")
            except (OSError, ValueError, TypeError) as exc:
                self._append_log(f"\n预校准更新失败，原记录保留：{exc}\n")
        from label_incidents import REPAIR_REQUIRED_EXIT_CODE
        if code == REPAIR_REQUIRED_EXIT_CODE:
            self._append_log("\n[标签故障保护] 手柄输入已锁定，本次运行以安全停止码结束。请在设备标签卡片查看截图并修复标签。\n")
            self.set_status("标签故障保护已停止运行；请打开设备标签卡片处理故障事件。")
        elif fatal_output:
            self._append_log("\n[运行失败] EasyCon 报告了未处理异常；即使退出码为 0，也不会判定为完成。\n")
            self.set_status("运行失败：EasyCon 报告了未处理异常，请查看完整日志。")
        elif self.runtime_issues:
            for explanation in self.runtime_issues.values():
                self._append_log("\n[本次运行问题] " + explanation.message + "\n")
            issue = next(iter(self.runtime_issues.values()))
            self.set_status(f"运行已结束（退出码 {code}）：{issue.summary}")
        else:
            self.set_status(f"运行进程已结束（退出码 {code}）；请查看日志中的实际结果。")
        self._notify_run_finished(code, fatal_output=fatal_output)
        self.history_controller.invalidate()
        if self.current_page == "history_logs":
            self.refresh_history_logs()
        if self.current_page == "tid_records" and not self.closing:
            QTimer.singleShot(0, self.refresh_records)
        if self.closing:
            self.close()

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            message = f"运行进程无法启动：{self.process.errorString()}"
            self._finish_start_failure(message)

    def _finish_start_failure(self, message):
        if self._run_terminal_handled:
            return
        self._run_terminal_handled = True
        self.running = False
        self._append_log(f"\n[启动失败] {message}\n")
        if self.run_command is not None:
            try:
                self.run_command.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.run_command.log_path.open("a", encoding="utf-8", newline="") as stream:
                    stream.write(f"\n[启动失败] {message}\n")
            except OSError as exc:
                self._append_log(f"[日志写入失败] {exc}\n")
        if hasattr(self, "accessories"):
            self.accessories.run_finished("启动失败", phase="failed")
        self.set_status(message)
        self.refresh_state()
        self._notify_run_finished(1, fatal_output=True)
        if self.closing:
            self.close()

    def stop_run(self):
        if self.running and self.run_command:
            self._manual_stop_requested = True
            self.run_command.stop_path.write_text("stop\n", encoding="utf-8")
            self.set_status("已请求停止，正在等待运行器结束……")

    def show_qq_notifications(self):
        if self.qq_dialog is None:
            self.qq_dialog = QQNotificationDialog(self.qq_service, self)
            self.qq_dialog.closed.connect(lambda: None)
        self.qq_dialog.show()
        self.qq_dialog.raise_()
        self.qq_dialog.activateWindow()

    def _notify_run_finished(self, code, *, fatal_output=False):
        if self._run_notification_sent:
            return
        self._run_notification_sent = True
        if self._manual_stop_requested:
            outcome = "已停止"
        else:
            outcome = "已完成" if code == 0 and not fatal_output else "失败"
        detail = self.log_view.toPlainText().strip()
        if len(detail) > 800:
            detail = detail[-800:]
        frame = self.accessories.latest_frame() if hasattr(self, "accessories") else None
        self.qq_service.notify_task(
            self._run_id or uuid.uuid4().hex,
            "FRLG 乱数任务",
            outcome,
            target=self.summary_name.text() if self.summary_name.text() != "暂无方案" else "当前方案",
            detail=detail,
            frame=frame,
        )

    def _load_settings(self):
        path = self.paths.user / "pyside6_settings.json"
        if not path.exists():
            return
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(values, dict):
                self._settings_invalid = True
                self.settings_load_error = "设置文件顶层必须是 JSON 对象"
                return
            for key, default, suffix in (
                ("source", self.paths.source, "_internal/local_assets/easycon118"),
                ("ezcon", self.paths.ezcon, "_internal/easycon/publish/ezcon.exe"),
            ):
                self.fields[key].setText(restore_resource_path(
                    values.get(key), default, bundled_suffix=suffix, file=key == "ezcon",
                ))
            update_source = values.get("update_source", "auto")
            source_index = self.fields["update_source"].findData(update_source)
            self.fields["update_source"].setCurrentIndex(max(0, source_index))
            self.label_supervision_check.setChecked(values.get("label_supervision") is True)
            togepi_mode = values.get("togepi_reverse_mode", 0)
            if type(togepi_mode) is int and togepi_mode in (0, 1):
                self.fields["togepi_reverse_mode"].setCurrentIndex(togepi_mode)
            else:
                self._settings_invalid = True
                self.settings_load_error = "设置字段 togepi_reverse_mode 必须是 0 或 1"
            togepi_width = values.get("togepi_reverse_half_width", "5000")
            if isinstance(togepi_width, str):
                self.fields["togepi_reverse_adv"].setText(togepi_width)
            else:
                self._settings_invalid = True
                self.settings_load_error = "设置字段 togepi_reverse_half_width 必须是文本"
            for key, widget in (
                ("update_precalibration", self.precalibration_check),
                ("record_shiny_video", self.record_shiny_video_check),
                ("label_repair_prompt", self.label_repair_prompt_check),
            ):
                value = values.get(key, True)
                if type(value) is not bool:
                    self._settings_invalid = True
                    self.settings_load_error = f"设置字段 {key} 必须是布尔值"
                    continue
                with QSignalBlocker(widget):
                    widget.setChecked(value)
                sync_toggle_text(widget)
            parity = values.get("preferred_frame_parity_scheme", 1)
            if type(parity) is not int or parity not in (0, 1):
                self._settings_invalid = True
                self.settings_load_error = "设置字段 preferred_frame_parity_scheme 必须是 0 或 1"
            else:
                self.preferred_frame_parity_scheme = parity
                combo = self.fields["parity"]
                with QSignalBlocker(combo):
                    combo.setCurrentIndex(combo.findData(parity))
            if self._settings_invalid:
                self.status_text = f"设置文件有无效字段，已保留原文件：{self.settings_load_error}"
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            self._settings_invalid = True
            self.settings_load_error = str(exc)
            self.status_text = f"设置文件读取失败，已保留原文件：{exc}"

    def settings_payload(self):
        return {
            **{key: self.fields[key].text() for key in ("source", "ezcon")},
            "update_source": self.fields["update_source"].currentData() or "auto",
            "label_supervision": self.label_supervision_check.isChecked(),
            "update_precalibration": self.precalibration_check.isChecked(),
            "record_shiny_video": self.record_shiny_video_check.isChecked(),
            "label_repair_prompt": self.label_repair_prompt_check.isChecked(),
            "preferred_frame_parity_scheme": self.preferred_frame_parity_scheme,
            "togepi_reverse_mode": self.fields["togepi_reverse_mode"].currentIndex(),
            "togepi_reverse_half_width": self.fields["togepi_reverse_adv"].text(),
        }

    def closeEvent(self, event):
        if hasattr(self, "record_poll_timer"):
            self.record_poll_timer.stop()
        if self.job or self.running:
            self.closing = True
            self.cancel()
            self.stop_run()
            event.ignore()
            return
        self.qq_service.shutdown()
        if not self.history_controller.shutdown():
            event.ignore()
            return
        if not self._settings_invalid:
            try:
                write_json_atomic(
                    self.paths.user / "pyside6_settings.json",
                    self.settings_payload(),
                )
            except (OSError, ValueError) as exc:
                if not self.closing:
                    show_error_dialog(self, "设置未保存", str(exc))
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

    def _capture_manual_profile_draft(self):
        combo_keys = (
            "wild_game", "profile_game", "egg_game", "sid_game", "tid_game",
            "wild_nx", "egg_nx", "sid_nx", "tid_nx", "tid_language",
        )
        return {
            **{key: self.fields[key].currentText() for key in combo_keys},
            "profile_language": self.fields["profile_language"].currentIndex(),
            "wild_tid": self.fields["wild_tid"].text(),
            "wild_sid": self.fields["wild_sid"].text(),
            "sid_tid": self.fields["sid_tid"].text(),
            "mystery_gift_enabled": self.profile_mystery_gift.isChecked(),
        }

    def _restore_manual_profile_draft(self):
        draft = self.manual_profile_draft
        if not draft:
            return
        self.updating = True
        for key in (
            "wild_game", "profile_game", "egg_game", "sid_game", "tid_game",
            "wild_nx", "egg_nx", "sid_nx", "tid_nx", "tid_language",
        ):
            widget = self.fields[key]
            with QSignalBlocker(widget):
                widget.setCurrentText(draft[key])
        for key in ("wild_tid", "wild_sid", "sid_tid"):
            with QSignalBlocker(self.fields[key]):
                self.fields[key].setText(draft[key])
        with QSignalBlocker(self.fields["profile_language"]):
            self.fields["profile_language"].setCurrentIndex(draft["profile_language"])
        with QSignalBlocker(self.profile_mystery_gift):
            self.profile_mystery_gift.setChecked(draft["mystery_gift_enabled"])
        self.updating = False
        self._populate_categories()
        self._refresh_common_settings()
        self.invalidate()

    def _remember_frame_parity_preference(self, *_):
        combo = self.fields["parity"]
        if combo.isEnabled() and combo.currentData() in (0, 1):
            self.preferred_frame_parity_scheme = int(combo.currentData())

    def _refresh_common_settings(self):
        super()._refresh_common_settings()
        if not hasattr(self, "profile_mystery_gift"):
            return
        advanced = self.advanced_check.isChecked()
        applies = self.input_mode in {"wild", "egg"} or (
            self.input_mode == "tid" and getattr(self, "tid_flow_check", None)
            and self.tid_flow_check.isChecked()
        )
        requested = self.preferred_frame_parity_scheme if advanced else 1
        gift_enabled = (
            self.profile_mystery_gift.isChecked()
            if self.input_mode in {"wild", "egg"}
            else False
        )
        policy = resolve_frame_parity(
            requested=requested,
            mystery_gift_enabled=gift_enabled,
            is_egg=self.input_mode == "egg",
        )
        combo = self.fields["parity"]
        with QSignalBlocker(combo):
            combo.setCurrentIndex(combo.findData(policy.effective))
        combo.setEnabled(advanced and applies and not policy.forced)
        if policy.forced:
            combo.setToolTip(f"{policy.reason}；有效帧奇偶方案固定为 1，原偏好 {policy.requested} 已保留。")
        else:
            combo.setToolTip("选择遭遇帧奇偶调整方案；此设置不改变 SID ADV 奇偶。")

    def _profile_gift_changed(self, *_):
        if self.updating:
            return
        self._refresh_common_settings()
        self.invalidate()
        if hasattr(self, "profile_selector"):
            self._profile_summary()

    def _wheel_select_profile(self, steps):
        if not steps or self.job or self.running or self.closing or not self.profiles_available:
            return
        ids = [profile.profile_id for profile in self.profile_store.profiles]
        if not ids:
            return
        current = self.profile_selector.currentData()
        if current is None:
            target_index = 0 if steps > 0 else len(ids) - 1
        else:
            try:
                target_index = ids.index(current) + steps
            except ValueError:
                target_index = 0 if steps > 0 else len(ids) - 1
        target_index = max(0, min(len(ids) - 1, target_index))
        target_id = ids[target_index]
        if target_id == current:
            return
        self.select_profile_id(target_id, source="wheel")

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
        with QSignalBlocker(self.profile_mystery_gift):
            self.profile_mystery_gift.setChecked(profile.mystery_gift_enabled)
        self.updating = False
        if self.live_ready:
            self._populate_categories()
            self._refresh_tid_controls()
            self._refresh_common_settings()
            self.invalidate()

    def select_profile_id(self, profile_id, *, source="selector"):
        previous_id = self.profile_store.selected_profile_id
        if profile_id == previous_id:
            with QSignalBlocker(self.profile_selector):
                self.profile_selector.setCurrentIndex(
                    self.profile_selector.findData(previous_id)
                )
            self._profile_summary()
            return True
        if self.job or self.running or self.closing:
            with QSignalBlocker(self.profile_selector):
                self.profile_selector.setCurrentIndex(self.profile_selector.findData(previous_id))
            return False
        selected_profile = self.profile_store.get(profile_id)
        if profile_id is not None and selected_profile is None:
            with QSignalBlocker(self.profile_selector):
                self.profile_selector.setCurrentIndex(
                    self.profile_selector.findData(previous_id)
                )
            self.show_error("要切换的存档不存在")
            return False
        if selected_profile is not None:
            for key, value in (
                ("wild_game", selected_profile.game),
                ("profile_game", selected_profile.game),
                ("egg_game", selected_profile.game),
                ("wild_nx", selected_profile.switch_name),
                ("egg_nx", selected_profile.switch_name),
                ("sid_game", selected_profile.game),
                ("sid_nx", selected_profile.switch_name),
                ("tid_game", selected_profile.game),
                ("tid_nx", selected_profile.switch_name),
                ("tid_language", selected_profile.language),
            ):
                if self.fields[key].findText(value) < 0:
                    with QSignalBlocker(self.profile_selector):
                        self.profile_selector.setCurrentIndex(
                            self.profile_selector.findData(previous_id)
                        )
                    self.show_error(f"存档字段无法应用到当前表单：{value}")
                    return False
        before_draft = self._capture_manual_profile_draft()
        old_manual_draft = self.manual_profile_draft
        if previous_id is None and profile_id is not None:
            self.manual_profile_draft = before_draft
        try:
            profile = self.profile_store.select(profile_id)
            if profile is not None:
                self.apply_profile(profile)
            else:
                self._restore_manual_profile_draft()
            with QSignalBlocker(self.profile_selector):
                self.profile_selector.setCurrentIndex(
                    self.profile_selector.findData(profile_id)
                )
            self._profile_summary()
            return True
        except (OSError, ValueError) as exc:
            rollback_error = None
            try:
                self.profile_store.select(previous_id)
                self.manual_profile_draft = (
                    before_draft if previous_id is None else old_manual_draft
                )
                if previous_id is not None:
                    self.apply_profile(self.profile_store.get(previous_id))
                else:
                    self._restore_manual_profile_draft()
            except (OSError, ValueError) as rollback_exc:
                rollback_error = rollback_exc
            with QSignalBlocker(self.profile_selector):
                self.profile_selector.setCurrentIndex(
                    self.profile_selector.findData(previous_id)
                )
            detail = f"切换存档失败：{exc}"
            if rollback_error is not None:
                detail += f"；恢复原选择也失败：{rollback_error}"
            self.show_error(detail)
            return False

    def select_profile(self, *_):
        return self.select_profile_id(
            self.profile_selector.currentData(), source="selector",
        )

    def _profile_summary(self):
        profile = self.profile_store.get(self.profile_selector.currentData())
        tid, sid = self.fields["wild_tid"].text(), self.fields["wild_sid"].text()
        matching = (profile and tid == str(profile.tid) and sid == str(profile.sid)
                    and self.fields["wild_game"].currentText() == profile.game
                    and self.fields["wild_nx"].currentIndex() + 1 == profile.nx_model
                    and bool(self.fields["profile_language"].currentIndex()) == (profile.language == "日文")
                    and self.profile_mystery_gift.isChecked() == profile.mystery_gift_enabled)
        name = f"{profile.name} · " if matching else ""
        game = self.fields["wild_game"].currentText()
        language = "日版" if self.fields["profile_language"].currentIndex() == 1 else "美版"
        version = f"{game}（{language}）"
        text = f"{name}{version} · {tid} / {sid}" if tid and sid else f"未选择 · {version} · 手动输入"
        label = self.profile_chip.findChild(QLabel, "chipValue")
        label.setWordWrap(False)
        label.setText(label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, self.profile_chip.width() - 24))
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

    def refresh_history_logs(self, *_):
        if hasattr(self, "history_controller"):
            self.history_controller.refresh()

    def filter_history_logs(self, *_):
        if hasattr(self, "history_controller"):
            self.history_controller.schedule_filter()

    def _selected_history_log(self):
        index = self.history_table.currentIndex().row()
        return self.history_rows[index] if 0 <= index < len(self.history_rows) else None

    def history_log_details(self, *_):
        self.history_controller.preview()

    def open_history_log(self, *, directory: bool):
        entry = self._selected_history_log()
        if entry is None:
            self.show_error("请先选择一份历史日志")
            return
        target = entry.path.parent if directory else entry.path
        if not target.exists():
            self.show_error(f"日志已经不存在：{target}")
            self.refresh_history_logs()
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self.show_error(f"无法打开：{target}")
