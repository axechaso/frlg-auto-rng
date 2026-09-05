# -*- coding: utf-8 -*-
"""Simple end-to-end GUI: inputs -> best plan -> configured ECS -> ezcon."""

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import uuid
from dataclasses import asdict, replace
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # File/folder pickers remain available without drag support.
    DND_FILES = None
    TkinterDnD = None

from app_paths import DATA_ROOT, RESOURCE_ROOT, USER_DATA_ROOT
from app_version import APP_VERSION, APP_VERSION_CODE, UPDATER_EXECUTABLE
from app_updater import (
    PreparedUpdate,
    UpdateCancelled,
    UpdateCandidate,
    UpdateCheckResult,
    UpdateError,
    check_for_update,
    is_frozen_build,
    prepare_update,
    write_install_request,
)
from device_label_overrides import (
    LabelIssue,
    LabelOverrideProfile,
    LabelOverrideStore,
    apply_profile_to_projects,
    diagnose_label_log,
)
from save_profiles import SaveProfile, SaveProfileStore
from tid_records import TidRecordContext, TidRecordStore
from tid_session import load_tid_settings, write_json_atomic, progress_context, read_progress, latest_progress
from automation.tid_search import parse_target_tids, progress_supported
from process_control import terminate_process_tree
from automation.tid_rng137 import resolve_tid_template
from automation.precalibration import (
    DEFAULT_STORE_PATH as DEFAULT_PRECALIBRATION_STORE_PATH,
    update_from_manifest as update_precalibration_from_manifest,
)
from automation.tid_calibration import (
    calibrated_tid_request,
    parse_tid_calibration_result,
    parse_tid_fixed_delays,
    validate_tid_plan_runtime,
)

from assets.game_text import (
    ABILITY_EN_TO_ZH,
    ABILITY_ZH_TO_EN,
    CATEGORY_EN_TO_ZH,
    FILTER_GENDER_ZH_TO_EN,
    FILTER_NATURE_ZH_TO_EN,
    FILTER_SHINY_ZH_TO_EN,
    FILTER_TYPE_ZH_TO_EN,
    SPECIES_EN_TO_ZH,
    WILD_CATEGORIES,
    location_to_zh,
)
from automation import (
    AutoSearchRequest,
    DEFAULT_EZCON_PATH,
    DEFAULT_TID_SOURCE_PATH,
    EGG_TEMPLATE_NAME,
    EggRunRequest,
    EasyCon118Options,
    EasyConRuntimeCheck,
    SEED_MODE_CHOICES,
    SearchCancelledError,
    SCRIPT_TEST_BACKEND_COMPAT,
    SCRIPT_TEST_BACKENDS,
    SCRIPT_TEST_ENTRIES,
    SCRIPT_TEST_ENTRY_CHOICES,
    SCRIPT_TEST_ENTRY_CUSTOM,
    SCRIPT_TEST_ENTRY_FORMAL,
    SCRIPT_TEST_ENTRY_TIMELINE,
    SID_REVERSE_TEMPLATE_NAME,
    SIDReverseRunRequest,
    STANDARD_TEMPLATE_NAME,
    ScriptTestPreparation,
    TidRngRequest,
    STARTER_SEED_CALIBRATION_SCHEME,
    TidStarterFlowPlan,
    TidStarterFlowRequest,
    PLANNER_STATIC_CATEGORIES,
    build_tid_starter_flow_plan,
    build_run_command,
    prepare_compat_runner,
    identify_script_test_entry,
    prepare_script_test_runtime,
    probe_easycon_devices,
    search_best_plan,
    get_static_targets,
    validate_runtime,
    validate_generated_project_consistency,
    validate_generated_egg_project_consistency,
    write_configured_egg_project,
    write_configured_project,
    write_configured_tid_project,
    write_sid_reverse_plan,
    write_sid_reverse_project,
    write_tid_starter_flow_bundle,
    resolve_script_test_entry,
)
from rng.tenlines_utils import (
    get_ability_name,
    get_encounter_species_list,
    get_personal,
    get_species_id,
    get_species_name,
    load_frlg_encounters,
)
from rng.tenlines import clear_frlg_seed_cache
from rng.sid_reverse import (
    DEFAULT_TID_SID_SEARCH_ADVANCES,
    SID_ADV_COMPENSATION_BY_LANGUAGE,
    fixed_delay_to_frames,
    find_earliest_shiny_sid,
    parse_pid_hex,
    pid_to_psv,
    sid_min_advances_for_f3,
    sid_candidates_for_psv,
)
from manual_tools import ManualToolsManager, parse_video_device
from tenlines_seed_updater import update_seed_tables as run_seed_table_update
from sid_traversal import (
    DEFAULT_MAX_ADVANCES as SID_TRAVERSAL_DEFAULT_MAX_ADVANCES,
    DEFAULT_START_ADVANCE as SID_TRAVERSAL_DEFAULT_START_ADVANCE,
    DEFAULT_TARGET_MAX_ADVANCES as SID_TRAVERSAL_DEFAULT_TARGET_MAX_ADVANCES,
    NAMED_RIVAL_START_ADVANCE as SID_TRAVERSAL_NAMED_RIVAL_START_ADVANCE,
    progress_path as sid_traversal_progress_path,
    read_progress as read_sid_traversal_progress,
    sid_traversal_start_advance,
    traversal_context,
)


ROOT = RESOURCE_ROOT
WRITABLE_ROOT = DATA_ROOT
IMPORTED_SOURCE_118 = ROOT / "local_assets" / "easycon118"
DOWNLOADED_SOURCE_118 = Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8"
DEFAULT_SOURCE_118 = IMPORTED_SOURCE_118 if IMPORTED_SOURCE_118.is_dir() else DOWNLOADED_SOURCE_118
DEFAULT_EZCON = DEFAULT_EZCON_PATH
IV_STAT_LABELS = ("HP", "攻击", "防御", "特攻", "特防", "速度")
IV_PRESETS = ("不限", "6V", "0A", "0S", "0A0S")
SID_SOURCE_LABELS = ("定点", "野生")
SCRIPT_PACKAGE_UI_NAME = "2.0 自动乱数脚本包"
SCRIPT_FLOW_UI_NAME = "2.0 自动乱数脚本"
MODE_TAB_ORDER = ("SID 查找", "TID 乱数", "野生 / 静态", "孵蛋")
ADVANCED_TAB_LABEL = "脚本测试（高级）"
RUN_LOG_TAB_LABEL = "运行日志"
TID_RECORD_TAB_LABEL = "TID 实测表"
TID_RECORD_PATH = USER_DATA_ROOT / "tid_records.sqlite3"
TID_SETTINGS_PATH = USER_DATA_ROOT / "tid_settings.json"
TID_PROGRESS_DIR = USER_DATA_ROOT / "tid_progress"
SID_TRAVERSAL_PROGRESS_DIR = USER_DATA_ROOT / "sid_traversal_progress"
SID_TRAVERSAL_TARGET_MAX_ADVANCES = SID_TRAVERSAL_DEFAULT_TARGET_MAX_ADVANCES
MANUAL_PROFILE_LABEL = "未选择（手动输入）"
SAVE_PROFILE_PATH = USER_DATA_ROOT / "save_profiles.json"
DEVICE_LABEL_ROOT = USER_DATA_ROOT / "device_label_overrides"
EGG_START_MODE_FULL = "完整准备（自动走 254 步并存档）"
EGG_START_MODE_PREPARED = "从已完成 254 步准备开始"
EGG_START_MODES = (EGG_START_MODE_FULL, EGG_START_MODE_PREPARED)
SEED_STARTUP_HOME_BUFFER = "方案 0：当前 HOME_BUFFER（原样）"
SEED_STARTUP_FIXED_USER_HOME = "方案 1：固定用户界面 HOME"
SEED_STARTUP_SCHEMES = (
    SEED_STARTUP_HOME_BUFFER,
    SEED_STARTUP_FIXED_USER_HOME,
)
SEED_STARTUP_SCHEME_CODES = {
    SEED_STARTUP_HOME_BUFFER: 0,
    SEED_STARTUP_FIXED_USER_HOME: 1,
}
SEED_CALIBRATION_ORIGINAL = "方案 0：原始 12 轮绝对落点众数"
SEED_CALIBRATION_LOCKED_FINE = "方案 1：实验锁定与毫秒细调"
SEED_CALIBRATION_CONTINUATION = "方案 2：命中保持后的方向票接续（仅孵蛋）"
SEED_CALIBRATION_SCHEMES = (
    SEED_CALIBRATION_ORIGINAL,
    SEED_CALIBRATION_LOCKED_FINE,
    SEED_CALIBRATION_CONTINUATION,
)
SEED_CALIBRATION_SCHEME_CODES = {
    SEED_CALIBRATION_ORIGINAL: 0,
    SEED_CALIBRATION_LOCKED_FINE: 1,
    SEED_CALIBRATION_CONTINUATION: 2,
}
OUTPUT_LOG_COMPACT = "精简日志"
OUTPUT_LOG_DEBUG = "完整调试日志"
OUTPUT_LOG_MODES = (OUTPUT_LOG_COMPACT, OUTPUT_LOG_DEBUG)
OUTPUT_LOG_MODE_CODES = {OUTPUT_LOG_COMPACT: 0, OUTPUT_LOG_DEBUG: 1}
FRAME_PARITY_F1_F2 = "方案 0：F1 +1 / F2 -1"
FRAME_PARITY_MENU = "方案 1：菜单调整"
FRAME_PARITY_MODES = (FRAME_PARITY_MENU, FRAME_PARITY_F1_F2)
FRAME_PARITY_MODE_CODES = {FRAME_PARITY_F1_F2: 0, FRAME_PARITY_MENU: 1}
REVERSE_EXPANSION_FALLBACKS = {
    SCRIPT_TEST_ENTRY_FORMAL: (3, (25, 30, 30), (5000, 10000, 30000)),
    SCRIPT_TEST_ENTRY_TIMELINE: (3, (10, 20, 25), (2000, 5000, 10000)),
}
TID_SID_MODE_TARGET = "目标 SID（自动计算 ADV）"
TID_SID_MODE_NO_RANDOM = "不乱数 SID（固定 F3，采用实际 SID）"
# Keep the old symbol and persisted label as compatibility aliases.  New UI
# state uses the explicit wording above so the SID behavior is unambiguous.
TID_SID_MODE_FIXED_F3_LEGACY = "固定 F3 延迟（采用实际 SID）"
TID_SID_MODE_FIXED_F3 = TID_SID_MODE_NO_RANDOM
TID_SID_MODES = (TID_SID_MODE_TARGET, TID_SID_MODE_NO_RANDOM)
DEFAULT_TID_SHINY_PID = "7942EF72"
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def allocate_preview_port() -> int:
    """Reserve a loopback TCP port for the compat runner's MJPEG stream."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _new_runtime_staging_dir(output_dir: Path) -> Path:
    """Create an empty sibling directory for a generated runtime project."""
    output_dir = output_dir.resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        candidate = output_dir.parent / f".{output_dir.name}.pending-{uuid.uuid4().hex}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise OSError(f"无法创建生成暂存目录：{output_dir.parent}")


def _preserve_runtime_logs(previous_dir: Path, staging_dir: Path) -> None:
    """Copy old runtime logs into a new project before the directory swap."""
    if not previous_dir.is_dir():
        return
    for source in previous_dir.iterdir():
        if not source.is_file() or ".log" not in source.name.lower():
            continue
        destination = staging_dir / source.name
        if destination.exists():
            destination = staging_dir / f"previous-{uuid.uuid4().hex}-{source.name}"
        shutil.copy2(source, destination)


def _promote_runtime_project(staging_dir: Path, output_dir: Path) -> Path:
    """Atomically make a validated staging project the active runtime project."""
    staging_dir = staging_dir.resolve()
    output_dir = output_dir.resolve()
    if not (staging_dir / "main.ecs").is_file():
        raise FileNotFoundError(f"生成暂存项目缺少 main.ecs：{staging_dir}")
    _preserve_runtime_logs(output_dir, staging_dir)
    backup_dir: Path | None = None
    if output_dir.exists():
        backup_dir = output_dir.parent / f".{output_dir.name}.previous-{uuid.uuid4().hex}"
        output_dir.rename(backup_dir)
    try:
        staging_dir.rename(output_dir)
    except Exception:
        if backup_dir is not None and backup_dir.is_dir() and not output_dir.exists():
            backup_dir.rename(output_dir)
        raise
    if backup_dir is not None:
        shutil.rmtree(backup_dir, ignore_errors=True)
    return output_dir / "main.ecs"


def _generate_runtime_project_atomically(
    output_dir: Path,
    generate_project,
    verify_project,
    validate_project,
):
    """Generate, verify, preflight, and promote one runtime project safely."""
    staging_dir = _new_runtime_staging_dir(output_dir)
    try:
        staged_main = generate_project(staging_dir)
        verify_project(staged_main)
        check = validate_project(staged_main)
        if not check.ok:
            return None, check
        return _promote_runtime_project(staging_dir, output_dir), check
    finally:
        # Validation failures and exceptions must never leave a stale staging
        # project that a later GUI action could accidentally execute.
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def clean_terminal_log(text: str) -> str:
    """Clean display only; durable logs retain checkpoints for resume/records."""
    cleaned = ANSI_ESCAPE_RE.sub("", text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    # Hide only complete machine checkpoint lines, including EasyCon's optional
    # timestamp. Keep errors, unknown versions and truncated lines visible.
    return re.sub(
        r"(?m)^(?:\[\d{2}:\d{2}:\d{2}(?:\.\d+)?\]\s*)?"
        r"TIDPROGRESS\|V=[123]\|(?:[A-Z0-9_]+=-?[0-9]+\|)+END=1[ \t]*(?:\n|$)",
        "", cleaned,
    )


class HoverTooltip:
    """Small delayed help window used for non-essential UI explanations."""

    def __init__(
        self,
        widget: tk.Widget,
        title: str,
        text: str,
        *,
        delay: int = 350,
        wraplength: int = 380,
    ) -> None:
        self.widget = widget
        self.title = title
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self._after_id = None
        self._hide_after_id = None
        self._window: tk.Toplevel | None = None
        self._pointer_in_trigger = False
        self._pointer_in_popup = False
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def _on_enter(self, _event=None) -> None:
        self._pointer_in_trigger = True
        self._cancel_hide()
        self._schedule_show()

    def _on_leave(self, _event=None) -> None:
        self._pointer_in_trigger = False
        self._cancel_pending()
        # Most help markers are never open. Avoid queuing a geometry check for
        # every marker the pointer crosses while the native window is moving.
        if self._window is not None:
            self._schedule_hide()

    def _schedule_show(self) -> None:
        if self._window is None and self._after_id is None:
            self._after_id = self.widget.after(self.delay, self._show_from_hover)

    def _show_from_hover(self) -> None:
        self._after_id = None
        if self._pointer_in_trigger:
            self.show()

    def _schedule_hide(self) -> None:
        self._cancel_hide()
        self._hide_after_id = self.widget.after(160, self._hide_if_pointer_left)

    def _hide_if_pointer_left(self) -> None:
        self._hide_after_id = None
        if self._pointer_in_trigger or self._pointer_in_popup:
            return
        try:
            x, y = self.widget.winfo_pointerxy()
            left = self.widget.winfo_rootx()
            top = self.widget.winfo_rooty()
            right = left + self.widget.winfo_width()
            bottom = top + self.widget.winfo_height()
            if not (left <= x <= right and top <= y <= bottom) and not self._pointer_in_popup:
                self.hide()
        except tk.TclError:
            self.hide()

    def _cancel_pending(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _cancel_hide(self) -> None:
        if self._hide_after_id is not None:
            try:
                self.widget.after_cancel(self._hide_after_id)
            except tk.TclError:
                pass
            self._hide_after_id = None

    def show(self) -> None:
        self._after_id = None
        if self._window is not None:
            return
        try:
            if not self.widget.winfo_exists():
                return
            window = tk.Toplevel(self.widget)
            self._window = window
            window.overrideredirect(True)
            window.transient(self.widget.winfo_toplevel())
            try:
                window.attributes("-topmost", True)
            except tk.TclError:
                pass
            window.configure(background="#9a9a9a")
            body = tk.Frame(
                window,
                background="#fffdf8",
                borderwidth=1,
                relief="solid",
                padx=7,
                pady=5,
            )
            body.pack(fill="both", expand=True, padx=1, pady=1)
            tk.Label(
                body,
                text=self.title,
                background="#fffdf8",
                foreground="#1f2937",
                font=("Segoe UI", 9, "bold"),
                anchor="w",
                justify="left",
            ).pack(anchor="w", fill="x")
            tk.Label(
                body,
                text=self.text,
                background="#fffdf8",
                foreground="#374151",
                font=("Segoe UI", 9),
                anchor="w",
                justify="left",
                wraplength=self.wraplength,
            ).pack(anchor="w", fill="x", pady=(2, 0))
            window.update_idletasks()
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
            width = window.winfo_reqwidth()
            height = window.winfo_reqheight()
            screen_width = self.widget.winfo_screenwidth()
            screen_height = self.widget.winfo_screenheight()
            if x + width > screen_width - 8:
                x = max(8, screen_width - width - 8)
            if y + height > screen_height - 8:
                y = self.widget.winfo_rooty() - height - 4
            window.geometry(f"+{max(8, x)}+{max(8, y)}")
            window.bind("<Enter>", self._on_popup_enter, add="+")
            window.bind("<Leave>", self._on_popup_leave, add="+")
            window.bind("<ButtonPress>", self.hide, add="+")
            window.deiconify()
            window.lift()
        except tk.TclError:
            self.hide()

    def _on_popup_enter(self, _event=None) -> None:
        self._pointer_in_popup = True
        self._cancel_hide()

    def _on_popup_leave(self, _event=None) -> None:
        self._pointer_in_popup = False
        self._schedule_hide()

    def hide(self, _event=None) -> None:
        self._cancel_pending()
        self._cancel_hide()
        self._pointer_in_trigger = False
        self._pointer_in_popup = False
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None


def read_display_log_tail(path: Path | None, maximum_chars: int = 20000) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return clean_terminal_log(text)[-maximum_chars:]


def read_full_run_log(path: Path | None) -> str:
    """Read the complete worker log used for durable success markers."""
    if path is None or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def describe_sid_log_failure(log_text: str) -> str:
    if not log_text.strip():
        return "没有读到 SID 运行日志；流程可能在日志文件建立前被强制终止。"
    messages = []
    if "SIDREV|OBS|" not in log_text:
        if "性格识别失败" in log_text or "闪光性别识别失败" in log_text:
            messages.append(
                "本次没有生成任何 SID 观测：摘要页的性格或闪光性别标签未可靠命中，"
                "SID/PID 计算尚未开始。请确认脚本到达宝可梦摘要第一页、队伍位置正确，"
                "并核对采集画面与标签包；不要只按约 60 分的错误画面盲目降低阈值。"
            )
        else:
            messages.append("本次没有生成任何 SIDREV|OBS| 观测，SID/PID 计算尚未开始。")
    if "OperationCanceledException" in log_text or "The operation was canceled" in log_text:
        messages.append("EasyCon 收到了停止/取消请求；末尾调用栈是取消结果，不是 SID 算法崩溃。")
    return "\n".join(messages) or "SID 采集未正常完成，请根据下面的日志尾部定位失败阶段。"


def build_worker_command(worker: str, arguments: list[str]) -> list[str]:
    """Build a source or frozen command for one of the GUI worker modes."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker", worker, *arguments]
    worker_scripts = {
        "sid-capture": "run_sid_reverse_capture.py",
        "sid-traversal": "run_sid_traversal.py",
        "tid-flow": "run_tid_starter_flow.py",
        "easycon-log": "run_easycon_logged.py",
    }
    try:
        script_name = worker_scripts[worker]
    except KeyError as exc:
        raise ValueError(f"未知后台工作模式: {worker}") from exc
    return [sys.executable, str(ROOT / script_name), *arguments]


def iv_ranges_for_preset(preset: str) -> tuple[tuple[int, int], ...]:
    """Return the same 6V/0A/0S/0A0S ranges used by Ten Lines."""
    normalized = preset.strip().upper()
    if normalized == "不限":
        return ((0, 31),) * 6
    if normalized not in {"6V", "0A", "0S", "0A0S"}:
        raise ValueError(f"未知个体预设: {preset}")
    ranges = [(31, 31) for _ in IV_STAT_LABELS]
    if normalized in {"0A", "0A0S"}:
        ranges[1] = (0, 0)
    if normalized in {"0S", "0A0S"}:
        ranges[5] = (0, 0)
    return tuple(ranges)


def parse_iv_ranges(
    minimum_values,
    maximum_values,
) -> tuple[tuple[int, int, int, int, int, int], tuple[int, int, int, int, int, int]]:
    if len(minimum_values) != 6 or len(maximum_values) != 6:
        raise ValueError("个体值范围必须包含 HP、攻击、防御、特攻、特防、速度六项")
    minimums = []
    maximums = []
    for label, minimum_text, maximum_text in zip(
        IV_STAT_LABELS, minimum_values, maximum_values
    ):
        try:
            minimum = int(str(minimum_text).strip())
            maximum = int(str(maximum_text).strip())
        except ValueError as exc:
            raise ValueError(f"{label}个体值必须是 0–31 的整数") from exc
        if not 0 <= minimum <= 31 or not 0 <= maximum <= 31:
            raise ValueError(f"{label}个体值必须在 0–31 之间")
        if minimum > maximum:
            raise ValueError(
                f"{label}个体值最低值 {minimum} 不能高于最高值 {maximum}"
            )
        minimums.append(minimum)
        maximums.append(maximum)
    return tuple(minimums), tuple(maximums)  # type: ignore[return-value]


def parse_exact_ivs(values, label: str) -> tuple[int, int, int, int, int, int]:
    if len(values) != 6:
        raise ValueError(f"{label}必须包含六项 IV")
    result = []
    for stat, text in zip(IV_STAT_LABELS, values):
        try:
            value = int(str(text).strip())
        except ValueError as exc:
            raise ValueError(f"{label}{stat}必须是 0–31 的整数") from exc
        if not 0 <= value <= 31:
            raise ValueError(f"{label}{stat}必须在 0–31 之间")
        result.append(value)
    return tuple(result)  # type: ignore[return-value]


EGG_CONFIG_VERSION = 1
EGG_PARENT_CONFIG_KIND = "egg_parent"
EGG_FULL_CONFIG_KIND = "egg_full"


def build_egg_config_payload(
    game: str,
    nx_model,
    species_id,
    compatibility,
    parent_a_ivs,
    parent_b_ivs,
    start_from_prepared_254=False,
) -> dict:
    """Validate the egg-page settings and return a portable JSON payload."""
    game = str(game).strip()
    if game not in {"火红", "叶绿"}:
        raise ValueError("游戏版本只能是火红或叶绿")
    try:
        nx_model = int(nx_model)
    except (TypeError, ValueError) as exc:
        raise ValueError("机型必须是 Switch 1 或 Switch 2") from exc
    if nx_model not in {1, 2}:
        raise ValueError("机型必须是 Switch 1 或 Switch 2")
    try:
        species_id = int(species_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("蛋种全国图鉴编号必须是整数") from exc
    if not 1 <= species_id <= 386:
        raise ValueError("蛋种全国图鉴编号必须在 1-386 之间")
    try:
        compatibility = int(compatibility)
    except (TypeError, ValueError) as exc:
        raise ValueError("双亲相性只能填写 20、50 或 70") from exc
    if compatibility not in {20, 50, 70}:
        raise ValueError("双亲相性只能填写 20、50 或 70")
    for values, label in ((parent_a_ivs, "亲本A"), (parent_b_ivs, "亲本B")):
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{label}必须包含六项 IV")
        try:
            len(values)
        except TypeError as exc:
            raise ValueError(f"{label}必须包含六项 IV") from exc
    parent_a_ivs = parse_exact_ivs(parent_a_ivs, "亲本A")
    parent_b_ivs = parse_exact_ivs(parent_b_ivs, "亲本B")
    if not isinstance(start_from_prepared_254, bool):
        raise ValueError("254 步启动模式必须是布尔值")
    return {
        "version": EGG_CONFIG_VERSION,
        "game": game,
        "nx_model": nx_model,
        "egg_species_id": species_id,
        "compatibility": compatibility,
        "parent_a_ivs": list(parent_a_ivs),
        "parent_b_ivs": list(parent_b_ivs),
        "start_from_prepared_254": start_from_prepared_254,
    }


def parse_egg_config_payload(payload) -> dict:
    """Validate a saved egg JSON object and return its canonical values."""
    if not isinstance(payload, dict):
        raise ValueError("配置文件顶层必须是 JSON 对象")
    try:
        version = int(payload.get("version", EGG_CONFIG_VERSION))
    except (TypeError, ValueError) as exc:
        raise ValueError("配置文件版本无效") from exc
    if version != EGG_CONFIG_VERSION:
        raise ValueError(f"不支持的孵蛋配置版本: {version}")
    return build_egg_config_payload(
        payload.get("game"),
        payload.get("nx_model"),
        payload.get("egg_species_id"),
        payload.get("compatibility"),
        payload.get("parent_a_ivs"),
        payload.get("parent_b_ivs"),
        payload.get("start_from_prepared_254", False),
    )


def build_egg_parent_config_payload(
    species_id,
    compatibility,
    parent_a_gender,
    parent_a_ivs,
    parent_b_gender,
    parent_b_ivs,
) -> dict:
    """Build a portable parent-only egg configuration."""
    try:
        species_id = int(species_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("蛋种全国图鉴编号必须是整数") from exc
    if not 1 <= species_id <= 386:
        raise ValueError("蛋种全国图鉴编号必须在 1-386 之间")
    try:
        compatibility = int(compatibility)
    except (TypeError, ValueError) as exc:
        raise ValueError("双亲相性只能填写 20、50 或 70") from exc
    if compatibility not in {20, 50, 70}:
        raise ValueError("双亲相性只能填写 20、50 或 70")
    parent_a_gender = str(parent_a_gender).strip()
    parent_b_gender = str(parent_b_gender).strip()
    if parent_a_gender not in {"雌", "无性别"}:
        raise ValueError("孵蛋亲本 A 必须是雌或无性别")
    if parent_b_gender not in {"雄", "无性别"}:
        raise ValueError("孵蛋亲本 B 必须是雄或无性别")
    if parent_a_gender == parent_b_gender == "无性别":
        raise ValueError("两只亲本不能同时填写无性别")
    for values, label in ((parent_a_ivs, "亲本A"), (parent_b_ivs, "亲本B")):
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{label}必须包含六项 IV")
        try:
            len(values)
        except TypeError as exc:
            raise ValueError(f"{label}必须包含六项 IV") from exc
    parent_a_ivs = parse_exact_ivs(parent_a_ivs, "亲本A")
    parent_b_ivs = parse_exact_ivs(parent_b_ivs, "亲本B")
    return {
        "kind": EGG_PARENT_CONFIG_KIND,
        "version": EGG_CONFIG_VERSION,
        "egg_species_id": species_id,
        "compatibility": compatibility,
        "parent_a_gender": parent_a_gender,
        "parent_a_ivs": list(parent_a_ivs),
        "parent_b_gender": parent_b_gender,
        "parent_b_ivs": list(parent_b_ivs),
    }


def parse_egg_parent_config_payload(payload) -> dict:
    """Read a parent configuration, including legacy whole-page version 1 files."""
    if not isinstance(payload, dict):
        raise ValueError("配置文件顶层必须是 JSON 对象")
    kind = payload.get("kind")
    if kind is None:
        legacy = parse_egg_config_payload(payload)
        return build_egg_parent_config_payload(
            legacy["egg_species_id"],
            legacy["compatibility"],
            payload.get("parent_a_gender", "雌"),
            legacy["parent_a_ivs"],
            payload.get("parent_b_gender", "雄"),
            legacy["parent_b_ivs"],
        )
    if kind != EGG_PARENT_CONFIG_KIND:
        raise ValueError("所选文件不是孵蛋亲本配置")
    try:
        version = int(payload.get("version", EGG_CONFIG_VERSION))
    except (TypeError, ValueError) as exc:
        raise ValueError("配置文件版本无效") from exc
    if version != EGG_CONFIG_VERSION:
        raise ValueError(f"不支持的孵蛋亲本配置版本: {version}")
    return build_egg_parent_config_payload(
        payload.get("egg_species_id"),
        payload.get("compatibility"),
        payload.get("parent_a_gender"),
        payload.get("parent_a_ivs"),
        payload.get("parent_b_gender"),
        payload.get("parent_b_ivs"),
    )


def build_egg_full_config_payload(
    game,
    nx_model,
    seed_mode,
    target_seed,
    held_advances,
    pickup_advances,
    species_id,
    compatibility,
    parent_a_gender,
    parent_a_ivs,
    parent_b_gender,
    parent_b_ivs,
    start_from_prepared_254=False,
    home_buffer_adaptive_threshold=False,
    seed_startup_scheme=0,
    seed_calibration_scheme=2,
    debug_log_output=1,
    reverse_expansion_layers=None,
    reverse_expansion_seed_tolerances=None,
    reverse_expansion_frame_half_widths=None,
) -> dict:
    """Validate and build a complete egg-page configuration."""
    parent = build_egg_parent_config_payload(
        species_id,
        compatibility,
        parent_a_gender,
        parent_a_ivs,
        parent_b_gender,
        parent_b_ivs,
    )
    game = str(game).strip()
    if game not in {"火红", "叶绿"}:
        raise ValueError("游戏版本只能是火红或叶绿")
    try:
        nx_model = int(nx_model)
    except (TypeError, ValueError) as exc:
        raise ValueError("机型必须是 Switch 1 或 Switch 2") from exc
    if nx_model not in {1, 2}:
        raise ValueError("机型必须是 Switch 1 或 Switch 2")
    try:
        seed_mode = int(seed_mode)
    except (TypeError, ValueError) as exc:
        raise ValueError("孵蛋 Seed 模式必须在 0-9 之间") from exc
    try:
        held_advances = int(held_advances)
        pickup_advances = int(pickup_advances)
    except (TypeError, ValueError) as exc:
        raise ValueError("Held/生成帧和 Pickup/领取帧必须是整数") from exc
    if not isinstance(start_from_prepared_254, bool):
        raise ValueError("254 步启动模式必须是布尔值")
    if not isinstance(home_buffer_adaptive_threshold, bool):
        raise ValueError("HOME_BUFFER 稳定低分自适应开关必须是布尔值")
    try:
        seed_startup_scheme = int(seed_startup_scheme)
    except (TypeError, ValueError) as exc:
        raise ValueError("Seed 启动方案只能是 0 或 1") from exc
    if seed_startup_scheme not in {0, 1}:
        raise ValueError("Seed 启动方案只能是 0（当前 HOME_BUFFER）或 1（固定用户界面 HOME）")
    try:
        seed_calibration_scheme = int(seed_calibration_scheme)
    except (TypeError, ValueError) as exc:
        raise ValueError("Seed 校准方案只能是 0、1 或 2") from exc
    if seed_calibration_scheme not in {0, 1, 2}:
        raise ValueError("Seed 校准方案只能是 0（原始 12 轮众数）、1（实验锁定细调）或 2（命中保持后的方向票接续）")
    try:
        debug_log_output = int(debug_log_output)
    except (TypeError, ValueError) as exc:
        raise ValueError("脚本输出日志模式只能是 0（精简）或 1（完整调试）") from exc
    if debug_log_output not in {0, 1}:
        raise ValueError("脚本输出日志模式只能是 0（精简）或 1（完整调试）")
    if reverse_expansion_layers is not None:
        try:
            reverse_expansion_layers = int(reverse_expansion_layers)
            reverse_expansion_seed_tolerances = tuple(
                int(value) for value in reverse_expansion_seed_tolerances
            )
            reverse_expansion_frame_half_widths = tuple(
                int(value) for value in reverse_expansion_frame_half_widths
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("反查扩窗配置必须包含整数层数、三层 Seed 容差和三层帧半宽") from exc
    game_code = ("fr" if game == "火红" else "lg") + ("_nx2" if nx_model == 2 else "_nx")
    request = EggRunRequest(
        game=game_code,
        seed_mode=seed_mode,
        target_seed=str(target_seed),
        held_advances=held_advances,
        pickup_advances=pickup_advances,
        species_id=parent["egg_species_id"],
        compatibility=parent["compatibility"],
        parent_a_gender=parent["parent_a_gender"],
        parent_a_ivs=tuple(parent["parent_a_ivs"]),
        parent_b_gender=parent["parent_b_gender"],
        parent_b_ivs=tuple(parent["parent_b_ivs"]),
        start_from_prepared_254=start_from_prepared_254,
        home_buffer_adaptive_threshold=home_buffer_adaptive_threshold,
        seed_startup_scheme=seed_startup_scheme,
        seed_calibration_scheme=seed_calibration_scheme,
        debug_log_output=debug_log_output,
        reverse_expansion_layers=reverse_expansion_layers,
        reverse_expansion_seed_tolerances=(
            None
            if reverse_expansion_seed_tolerances is None
            else tuple(reverse_expansion_seed_tolerances)
        ),
        reverse_expansion_frame_half_widths=(
            None
            if reverse_expansion_frame_half_widths is None
            else tuple(reverse_expansion_frame_half_widths)
        ),
    )
    request.validate()
    return {
        "kind": EGG_FULL_CONFIG_KIND,
        "version": EGG_CONFIG_VERSION,
        "game": game,
        "nx_model": nx_model,
        "seed_mode": seed_mode,
        "target_seed": request.normalized_seed,
        "held_advances": held_advances,
        "pickup_advances": pickup_advances,
        "egg_species_id": parent["egg_species_id"],
        "compatibility": parent["compatibility"],
        "parent_a_gender": parent["parent_a_gender"],
        "parent_a_ivs": parent["parent_a_ivs"],
        "parent_b_gender": parent["parent_b_gender"],
        "parent_b_ivs": parent["parent_b_ivs"],
        "start_from_prepared_254": start_from_prepared_254,
        "home_buffer_adaptive_threshold": home_buffer_adaptive_threshold,
        "seed_startup_scheme": seed_startup_scheme,
        "seed_calibration_scheme": seed_calibration_scheme,
        "debug_log_output": request.debug_log_output,
        "reverse_expansion_layers": request.reverse_expansion_layers,
        "reverse_expansion_seed_tolerances": (
            None
            if request.reverse_expansion_seed_tolerances is None
            else list(request.reverse_expansion_seed_tolerances)
        ),
        "reverse_expansion_frame_half_widths": (
            None
            if request.reverse_expansion_frame_half_widths is None
            else list(request.reverse_expansion_frame_half_widths)
        ),
    }


def parse_egg_full_config_payload(payload) -> dict:
    """Validate a saved complete egg-page configuration."""
    if not isinstance(payload, dict):
        raise ValueError("配置文件顶层必须是 JSON 对象")
    if payload.get("kind") != EGG_FULL_CONFIG_KIND:
        raise ValueError("所选文件不是孵蛋全部配置")
    try:
        version = int(payload.get("version", EGG_CONFIG_VERSION))
    except (TypeError, ValueError) as exc:
        raise ValueError("配置文件版本无效") from exc
    if version != EGG_CONFIG_VERSION:
        raise ValueError(f"不支持的孵蛋全部配置版本: {version}")
    return build_egg_full_config_payload(
        payload.get("game"),
        payload.get("nx_model"),
        payload.get("seed_mode"),
        payload.get("target_seed"),
        payload.get("held_advances"),
        payload.get("pickup_advances"),
        payload.get("egg_species_id"),
        payload.get("compatibility"),
        payload.get("parent_a_gender"),
        payload.get("parent_a_ivs"),
        payload.get("parent_b_gender"),
        payload.get("parent_b_ivs"),
        payload.get("start_from_prepared_254", False),
        payload.get("home_buffer_adaptive_threshold", False),
        payload.get("seed_startup_scheme", 0),
        payload.get("seed_calibration_scheme", 2),
        payload.get("debug_log_output", 1),
        payload.get("reverse_expansion_layers"),
        payload.get("reverse_expansion_seed_tolerances"),
        payload.get("reverse_expansion_frame_half_widths"),
    )


def parse_sid_effort_values(values, slot: int) -> tuple[int, int, int, int, int, int]:
    parts = (
        [part.strip() for part in values.split(",")]
        if isinstance(values, str)
        else [str(part).strip() for part in values]
    )
    if len(parts) != 6:
        raise ValueError(f"队伍第{slot}位努力值必须包含六项能力")
    parsed = []
    for stat, part in zip(IV_STAT_LABELS, parts):
        try:
            value = int(part)
        except ValueError as exc:
            raise ValueError(f"队伍第{slot}位{stat}努力值必须是整数") from exc
        if not 0 <= value <= 255:
            raise ValueError(f"队伍第{slot}位{stat}努力值必须在0-255之间")
        parsed.append(value)
    if sum(parsed) > 510:
        raise ValueError(f"队伍第{slot}位六项努力值总和不能超过510")
    return tuple(parsed)  # type: ignore[return-value]


def _normalize_species_name(value: str) -> str:
    return " ".join(value.strip().casefold().replace("’", "'").split())


def filter_autocomplete_choices(choices, query: str) -> tuple[str, ...]:
    """Filter choices while keeping prefix matches ahead of contains matches."""
    normalized_query = " ".join(query.strip().casefold().split())
    values = tuple(str(choice) for choice in choices)
    if not normalized_query:
        return values

    prefix_matches = []
    contains_matches = []
    for choice in values:
        normalized_choice = " ".join(choice.casefold().split())
        if normalized_choice.startswith(normalized_query):
            prefix_matches.append(choice)
        elif normalized_query in normalized_choice:
            contains_matches.append(choice)
    return tuple(prefix_matches + contains_matches)


_AUTOCOMPLETE_IGNORED_KEYS = frozenset(
    {
        "Up",
        "Down",
        "Left",
        "Right",
        "Home",
        "End",
        "Prior",
        "Next",
        "Return",
        "Escape",
        "Tab",
        "Shift_L",
        "Shift_R",
        "Control_L",
        "Control_R",
        "Alt_L",
        "Alt_R",
        "Caps_Lock",
    }
)


def _install_autocomplete_combo(combo: ttk.Combobox, choices, variable=None) -> None:
    all_choices = tuple(choices)

    def update_matches(event) -> None:
        if event.keysym in _AUTOCOMPLETE_IGNORED_KEYS:
            return
        query = combo.get()
        matches = filter_autocomplete_choices(all_choices, query)
        combo.configure(values=matches)
        if not query.strip() or not matches:
            return
        try:
            combo.tk.call("ttk::combobox::Post", str(combo))
        except tk.TclError:
            pass

    def commit_selection(_event) -> None:
        selected = combo.get()
        if variable is not None:
            variable.set(selected)
        combo.configure(values=all_choices)
        combo.set(selected)

    combo.bind("<KeyRelease>", update_matches, add="+")
    combo.bind("<<ComboboxSelected>>", commit_selection, add="+")


@lru_cache(maxsize=1)
def species_input_catalog() -> tuple[tuple[str, ...], dict[str, int]]:
    """Return Gen 1-3 display choices and normalized input aliases."""
    chinese_by_english = {
        _normalize_species_name(english): chinese
        for english, chinese in SPECIES_EN_TO_ZH.items()
    }
    choices = []
    aliases: dict[str, int] = {}
    for species_id in range(1, 387):
        english = get_species_name(species_id)
        chinese = chinese_by_english.get(_normalize_species_name(english), "")
        display = f"{chinese} ({english})" if chinese else english
        choices.append(display)
        for alias in (str(species_id), english, chinese, display):
            if alias:
                aliases[_normalize_species_name(alias)] = species_id
    return tuple(choices), aliases


def parse_sid_species(value: str, slot: int) -> int:
    normalized = _normalize_species_name(value)
    if not normalized:
        raise ValueError(f"队伍第{slot}位必须填写宝可梦名称或全国图鉴编号")
    _, aliases = species_input_catalog()
    species_id = aliases.get(normalized)
    if species_id is None:
        raise ValueError(
            f"无法识别队伍第{slot}位宝可梦“{value.strip()}”，"
            "请填写中文名、英文名或1-386的全国图鉴编号"
        )
    return species_id


def parse_egg_species(value: str) -> int:
    """Resolve an egg species from Chinese, English, display text or dex ID."""
    normalized = _normalize_species_name(value)
    if not normalized:
        raise ValueError("必须填写孵蛋蛋种名称或全国图鉴编号")
    _, aliases = species_input_catalog()
    species_id = aliases.get(normalized)
    if species_id is None:
        raise ValueError(
            f"无法识别孵蛋蛋种“{value.strip()}”，"
            "请填写中文名、英文名或1-386的全国图鉴编号"
        )
    return species_id


def preferred_detected_port(ports, current: str = "") -> str | None:
    """Keep a connected selection, otherwise choose the lowest COM number."""
    normalized = {str(port).strip().upper() for port in ports if str(port).strip()}
    selected = current.strip().upper()
    if selected in normalized:
        return selected

    def sort_key(port: str):
        suffix = port[3:] if port.startswith("COM") else ""
        return (0, int(suffix)) if suffix.isdigit() else (1, port)

    return min(normalized, key=sort_key) if normalized else None


def format_video_device_choice(index: int, name: str) -> str:
    """Build the user-facing capture-device dropdown label."""
    return f"[{index}] {name.strip() or '未命名设备'}"


def preferred_detected_video(
    devices: dict[int, str],
    current: str = "",
) -> str | None:
    """Keep the selected EasyCon index, otherwise choose the lowest index."""
    if not devices:
        return None
    try:
        current_index = parse_video_device(current)
    except ValueError:
        current_index = -1
    selected_index = current_index if current_index in devices else min(devices)
    return format_video_device_choice(selected_index, devices[selected_index])


class AutoRngApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"火红/叶绿全自动乱数 {APP_VERSION}")
        self.root.geometry("1100x880")
        self.root.minsize(900, 620)
        self.plan_result = None
        self.egg_request: EggRunRequest | None = None
        self.tid_request: TidRngRequest | None = None
        self.tid_flow_plan: TidStarterFlowPlan | None = None
        self.sid_request: SIDReverseRunRequest | None = None
        self.sid_traversal_request: AutoSearchRequest | None = None
        self.sid_traversal_options: EasyCon118Options | None = None
        self.sid_traversal_named_rival = False
        self.sid_traversal_context: dict | None = None
        self.sid_traversal_plan_path: Path | None = None
        self.project_main: Path | None = None
        self.runtime_check = None
        self.script_test_preparation: ScriptTestPreparation | None = None
        self.process: subprocess.Popen | None = None
        self.search_cancel: threading.Event | None = None
        self.running_mode: str | None = None
        self.sid_report_path: Path | None = None
        self.sid_log_path: Path | None = None
        self.sid_traversal_log_path: Path | None = None
        self.sid_traversal_report_path: Path | None = None
        self.tid_flow_log_path: Path | None = None
        self.tid_log_path: Path | None = None
        self.egg_log_path: Path | None = None
        self.script_test_log_path: Path | None = None
        self.easycon_log_path: Path | None = None
        self.running_log_snapshot = ""
        self.busy = False
        self._updating = False
        self._page_scrollregion_job = None
        self._page_canvas_width = None
        self._tooltips: list[HoverTooltip] = []
        ttk.Style(self.root).configure(
            "Help.TLabel",
            foreground="#1d4ed8",
            font=("Segoe UI", 9, "bold"),
        )
        self.manual_tools: ManualToolsManager | None = None
        self.preview_url: str | None = None
        self.tid_calibration_result_path: Path | None = None
        self.tid_calibration_snapshot = None
        self.tid_calibration_input_fingerprint = None
        self.tid_calibration_applied = False
        self.running_tid_exhaustive = False
        self.close_when_stopped = False
        self._closing_for_update = False
        self._app_update_checking = False
        self._app_update_manual_check = False
        self._app_update_cancel: threading.Event | None = None
        self._app_update_candidate: UpdateCandidate | None = None
        # Device probing runs asynchronously during startup.  Generation
        # captures the selected capture device in its input fingerprint, so a
        # late startup callback must not race a search and invalidate its
        # result halfway through.
        self._device_check_in_progress = True
        self.stop_request_path: Path | None = None
        self.profile_store = SaveProfileStore(SAVE_PROFILE_PATH)
        self.label_override_store = LabelOverrideStore(DEVICE_LABEL_ROOT)
        self.label_issues: tuple[LabelIssue, ...] = ()
        self.tid_record_store = TidRecordStore(TID_RECORD_PATH)
        self.profile_load_error: str | None = None
        try:
            self.profile_store.load()
        except ValueError as exc:
            self.profile_load_error = str(exc)
        self.all_locations = self._load_locations()
        self.category_map = {}
        self.location_map = {}
        self.pokemon_map = {}

        self._build_ui()
        self.manual_tools = ManualToolsManager(
            self.root,
            port_provider=self.port_var.get,
            video_provider=self.video_var.get,
            process_running=self._process_running,
            preview_url_provider=lambda: self.preview_url,
        )
        self._populate_seed_modes()
        self._populate_categories()
        self._populate_egg_pokemon()
        self._install_invalidation()
        self._refresh_save_profile_selector()
        selected_profile = self.profile_store.get(
            self.profile_store.selected_profile_id
        )
        if selected_profile is not None:
            self._apply_save_profile(selected_profile, persist=False)
        self._install_tid_persistence()
        if self.profile_load_error:
            self.root.after(
                0,
                lambda: messagebox.showwarning(
                    "存档信息读取失败",
                    self.profile_load_error
                    + "\n\n现有文件不会被静默采用；请在“管理存档”中确认后再保存。",
                    parent=self.root,
                ),
            )
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(250, lambda: self.check_devices(initial=True))
        if is_frozen_build():
            self.root.after(1800, lambda: self.check_app_update(force=False))

    @staticmethod
    def _load_locations() -> dict[str, list[str]]:
        result: dict[str, set[str]] = {}
        for game in ("fr_nx", "lg_nx"):
            for location, category in load_frlg_encounters(game):
                result.setdefault(category, set()).add(location)
        return {category: sorted(locations) for category, locations in result.items()}

    def _build_tid_records_tab(self):
        filters = ttk.Frame(self.tid_records_tab)
        filters.pack(fill="x", pady=(0, 8))
        self.tid_record_game_var = tk.StringVar(value="全部")
        self.tid_record_nx_var = tk.StringVar(value="全部")
        self.tid_record_filter_var = tk.StringVar(value="")
        for label, variable, choices in (
            ("游戏", self.tid_record_game_var, ("全部", "火红", "叶绿")),
            ("机型", self.tid_record_nx_var, ("全部", "Switch 1", "Switch 2")),
        ):
            ttk.Label(filters, text=label).pack(side="left", padx=(0, 4))
            combo = ttk.Combobox(filters, textvariable=variable, values=choices, state="readonly", width=11)
            combo.pack(side="left", padx=(0, 12))
            combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_tid_records())
        ttk.Label(filters, text="TID").pack(side="left")
        entry = ttk.Entry(filters, textvariable=self.tid_record_filter_var, width=10)
        entry.pack(side="left", padx=4)
        entry.bind("<Return>", lambda _event: self.refresh_tid_records())
        ttk.Button(filters, text="查询 / 刷新", command=self.refresh_tid_records).pack(side="left", padx=4)
        ttk.Button(filters, text="导出 CSV", command=self.export_tid_records).pack(side="left", padx=4)
        self._help_marker(
            self.tid_records_tab,
            "TID 实测表",
            "自动记录 TID 页运行得到的有效结果；不同游戏、机型和参数分别统计。"
            "这里只记录 TID，不记录 SID 或 SID ADV。",
            label="?",
        ).pack(anchor="w")
        frame = ttk.Frame(self.tid_records_tab)
        frame.pack(fill="both", expand=True, pady=6)
        columns = ("tid", "game", "nx_model", "language", "OP", "F1", "F2", "occurrences", "player_name", "op_correction", "last_seen")
        labels = ("TID", "游戏", "机型", "语言", "OP", "F1", "F2", "出现次数", "主角名称", "OP 修正（ms）", "最近记录时间")
        self.tid_record_tree = ttk.Treeview(frame, columns=columns, show="headings", height=18, selectmode="browse")
        for column, label in zip(columns, labels):
            self.tid_record_tree.heading(column, text=label)
            self.tid_record_tree.column(column, width=160 if column == "last_seen" else 85, minwidth=65, anchor="center")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.tid_record_tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.tid_record_tree.xview)
        self.tid_record_tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tid_record_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tid_record_rows = {}
        self.tid_record_status_var = tk.StringVar(value=f"记录自动保存到：{TID_RECORD_PATH}")
        ttk.Label(self.tid_records_tab, textvariable=self.tid_record_status_var).pack(anchor="w")
        self.tid_record_details_var = tk.StringVar(value="选择一条记录查看固定延迟、按键及主角设置。次数表示观测次数，不保证再次命中。")
        ttk.Label(self.tid_records_tab, textvariable=self.tid_record_details_var, wraplength=950, justify="left").pack(anchor="w", pady=8)
        self.tid_record_tree.bind("<<TreeviewSelect>>", self._show_tid_record_details)

    def _tid_record_filters(self):
        text = self.tid_record_filter_var.get().strip()
        if text and (not text.isascii() or not text.isdigit() or not 0 <= int(text) <= 65535):
            raise ValueError("TID 必须为 0–65535，留空查询全部")
        return {
            "game": None if self.tid_record_game_var.get() == "全部" else self.tid_record_game_var.get(),
            "nx_model": None if self.tid_record_nx_var.get() == "全部" else int(self.tid_record_nx_var.get()[-1]),
            "tid": int(text) if text else None,
        }

    def refresh_tid_records(self):
        try:
            rows = self.tid_record_store.rows(**self._tid_record_filters())
        except Exception as exc:
            self.tid_record_status_var.set(f"TID 实测表读取失败：{exc}")
            return
        selected = self.tid_record_tree.selection()
        self.tid_record_tree.delete(*self.tid_record_tree.get_children())
        self.tid_record_rows = {}
        for row in rows:
            identity = {k: v for k, v in row.items() if k not in ("occurrences", "last_seen")}
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            self.tid_record_rows[key] = row
            values = [f"{row['tid']:05d}", row["game"], f"Switch {row['nx_model']}", row["language"], row["OP"], row["F1"], row["F2"], row["occurrences"], row["player_name"], row["op_correction"], row["last_seen"]]
            self.tid_record_tree.insert("", "end", iid=key, values=values)
        if selected and selected[0] in self.tid_record_rows:
            self.tid_record_tree.selection_set(selected[0])
            self._show_tid_record_details()
        else:
            self.tid_record_details_var.set("选择一条记录查看固定延迟、按键及主角设置。次数表示观测次数，不保证再次命中。")
        self.tid_record_status_var.set(f"显示 {len(rows)} 项参数记录（最多 1000 项）；导出包含全部筛选结果。保存位置：{TID_RECORD_PATH}")

    def _show_tid_record_details(self, _event=None):
        selected = self.tid_record_tree.selection()
        if not selected or selected[0] not in self.tid_record_rows:
            return
        row = self.tid_record_rows[selected[0]]
        self.tid_record_details_var.set(
            f"{row['game']} / Switch {row['nx_model']} / {row['language']} / TID {row['tid']:05d}\n"
            f"主角：{row['player_name']}（{'男性' if row['gender'] == 0 else '女性'}）；"
            f"OP/F1/F2 固定延迟：{row['op_fixed_delay']}/{row['f1_fixed_delay']}/{row['f2_fixed_delay']} ms；OP 修正：{row['op_correction']} ms\n"
            f"OP机型补偿：{row['op_model_offset']} ms；"
            f"SELECT 执行/额外补偿：{row['select_count']}/{row['select_correction']}；HOME_BUFFER：{row['home_buffer_delay']} ms；"
            f"Sound：{('MONO','STEREO')[row['sound']]}；Button：{('HELP','LR','L=A')[row['button_mode']]}；"
            f"Seed 键：{('A','START','L')[row['seed_button']]}；取名进入键：{('A','B')[row['name_entry_button']]}"
        )

    def export_tid_records(self):
        try:
            filters = self._tid_record_filters()
            path = filedialog.asksaveasfilename(parent=self.root, title="导出 TID 实测表", initialfile="TID 实测表.csv", defaultextension=".csv", filetypes=[("CSV 表格", "*.csv")])
            if path:
                count = self.tid_record_store.export_csv(Path(path), **filters)
                self.tid_record_status_var.set(f"已导出 {count} 项记录：{path}")
        except Exception as exc:
            messagebox.showerror("TID 实测表导出失败", str(exc), parent=self.root)

    def _tid_record_arguments(self, log_path):
        context = TidRecordContext.from_request(self.tid_game_var.get(), self.tid_request)
        path = Path(log_path).with_suffix(".tid-context.json")
        context.save(path)
        return ["--tid-context", str(path), "--tid-records", str(TID_RECORD_PATH)]

    def _build_ui(self):
        page = ttk.Frame(self.root)
        page.pack(fill="both", expand=True)

        self.page_canvas = tk.Canvas(page, highlightthickness=0)
        page_scrollbar = ttk.Scrollbar(
            page, orient="vertical", command=self.page_canvas.yview
        )
        self.page_canvas.configure(yscrollcommand=page_scrollbar.set)
        page_scrollbar.pack(side="right", fill="y")
        self.page_canvas.pack(side="left", fill="both", expand=True)

        container = ttk.Frame(self.page_canvas, padding=12)
        self.page_window = self.page_canvas.create_window(
            (0, 0), window=container, anchor="nw"
        )
        container.bind("<Configure>", self._schedule_page_scrollregion_update)
        self.page_canvas.bind("<Configure>", self._resize_page_content)
        self.root.bind("<MouseWheel>", self._on_page_mousewheel, add="+")

        profile_frame = ttk.LabelFrame(container, text="存档信息", padding=8)
        profile_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(profile_frame, text="当前存档").pack(side="left")
        self.save_profile_var = tk.StringVar(value=MANUAL_PROFILE_LABEL)
        self.save_profile_combo = ttk.Combobox(
            profile_frame,
            textvariable=self.save_profile_var,
            values=(MANUAL_PROFILE_LABEL,),
            width=50,
            state="readonly",
        )
        self.save_profile_combo.pack(side="left", padx=(6, 8))
        self.save_profile_combo.bind(
            "<<ComboboxSelected>>", self._on_save_profile_selected
        )
        self._add_tooltip(
            self.save_profile_combo,
            "当前存档",
            "选择存档会同步各页面的游戏、主机、TID 和 SID；手动输入模式不会自动覆盖现有参数。",
        )
        ttk.Button(
            profile_frame,
            text="管理存档",
            command=self.open_save_profile_manager,
        ).pack(side="left")
        self.save_profile_summary_var = tk.StringVar(
            value="手动输入模式"
        )
        ttk.Label(
            profile_frame,
            textvariable=self.save_profile_summary_var,
        ).pack(side="left", padx=(12, 0))

        self.mode_var = tk.StringVar(value="sid")
        self.mode_notebook = ttk.Notebook(container)
        sid_tab = ttk.Frame(self.mode_notebook, padding=6)
        tid_tab = ttk.Frame(self.mode_notebook, padding=6)
        normal_tab = ttk.Frame(self.mode_notebook, padding=6)
        egg_tab = ttk.Frame(self.mode_notebook, padding=6)
        self.script_test_tab = ttk.Frame(self.mode_notebook, padding=6)
        self.run_log_tab = ttk.Frame(self.mode_notebook, padding=6)
        self.tid_records_tab = ttk.Frame(self.mode_notebook, padding=6)
        for tab, label in zip(
            (sid_tab, tid_tab, normal_tab, egg_tab), MODE_TAB_ORDER
        ):
            self.mode_notebook.add(tab, text=label)
        self.tab_modes = {
            str(sid_tab): "sid",
            str(tid_tab): "tid",
            str(normal_tab): "normal",
            str(egg_tab): "egg",
            str(self.script_test_tab): "script_test",
            str(self.run_log_tab): "log",
            str(self.tid_records_tab): "tid_records",
        }
        self.mode_notebook.insert(2, self.tid_records_tab, text=TID_RECORD_TAB_LABEL)
        self.mode_notebook.add(self.script_test_tab, text=ADVANCED_TAB_LABEL)
        self.mode_notebook.hide(self.script_test_tab)
        self.mode_notebook.add(self.run_log_tab, text=RUN_LOG_TAB_LABEL)
        self.mode_notebook.pack(fill="x")
        self._build_tid_records_tab()

        log_frame = ttk.LabelFrame(
            self.run_log_tab,
            text="当前/最近一次运行输出",
            padding=8,
        )
        log_frame.pack(fill="both", expand=True)
        self.run_log_text = tk.Text(
            log_frame,
            height=28,
            wrap="none",
            state="disabled",
        )
        log_y_scrollbar = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.run_log_text.yview,
        )
        log_x_scrollbar = ttk.Scrollbar(
            log_frame,
            orient="horizontal",
            command=self.run_log_text.xview,
        )
        self.run_log_text.configure(
            yscrollcommand=log_y_scrollbar.set,
            xscrollcommand=log_x_scrollbar.set,
        )
        self.run_log_text.grid(row=0, column=0, sticky="nsew")
        log_y_scrollbar.grid(row=0, column=1, sticky="ns")
        log_x_scrollbar.grid(row=1, column=0, sticky="ew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.set_run_log("尚未开始运行。点击“开始运行”后会自动切换到本页。")

        label_tools = ttk.LabelFrame(
            self.run_log_tab,
            text="设备标签诊断与覆盖",
            padding=8,
        )
        label_tools.pack(fill="x", pady=(8, 0))
        self.label_profile_status_var = tk.StringVar(
            value="检测并选择采集卡后，可为该设备导入同名 .IL 标签。"
        )
        ttk.Label(
            label_tools,
            textvariable=self.label_profile_status_var,
            wraplength=1000,
        ).grid(row=0, column=0, columnspan=5, sticky="w", padx=3, pady=(0, 5))
        self._help_marker(
            label_tools,
            "设备标签覆盖",
            "覆盖按采集设备名称独立保存，只应用到生成工程，不会修改原始标签包。",
        ).grid(row=0, column=5, sticky="e", padx=3, pady=(0, 5))
        self.label_issue_tree = ttk.Treeview(
            label_tools,
            columns=("label", "score", "threshold", "count", "context"),
            show="headings",
            height=5,
        )
        for column, heading, width in (
            ("label", "疑似标签", 330),
            ("score", "最高分", 70),
            ("threshold", "门槛", 65),
            ("count", "连续次数", 75),
            ("context", "出错阶段与原因", 480),
        ):
            self.label_issue_tree.heading(column, text=heading)
            self.label_issue_tree.column(column, width=width, anchor="w")
        self.label_issue_tree.grid(
            row=1, column=0, columnspan=6, sticky="ew", padx=3, pady=3
        )
        self.label_drop_target = ttk.Label(
            label_tools,
            text="拖放 .IL 文件或文件夹" if DND_FILES is not None else "请使用下方按钮选择 .IL 文件或文件夹",
            anchor="center",
            relief="groove",
            padding=7,
        )
        self._add_tooltip(
            self.label_drop_target,
            "导入设备标签",
            "可以拖入多个 .IL 文件或包含标签的文件夹；也可以使用下方的多文件/文件夹选择按钮。",
        )
        self.label_drop_target.grid(
            row=2, column=0, columnspan=6, sticky="ew", padx=3, pady=(5, 6)
        )
        if DND_FILES is not None and hasattr(self.label_drop_target, "drop_target_register"):
            self.label_drop_target.drop_target_register(DND_FILES)
            self.label_drop_target.dnd_bind("<<Drop>>", self._on_label_drop)
        self.label_import_files_button = ttk.Button(
            label_tools,
            text="选择标签文件（可多选）",
            command=self.choose_device_label_files,
        )
        self.label_import_files_button.grid(row=3, column=0, padx=3, pady=3, sticky="w")
        self.label_import_folder_button = ttk.Button(
            label_tools,
            text="选择标签文件夹",
            command=self.choose_device_label_folder,
        )
        self.label_import_folder_button.grid(row=3, column=1, padx=3, pady=3, sticky="w")
        self.label_clear_button = ttk.Button(
            label_tools,
            text="清除当前设备覆盖",
            command=self.clear_device_label_overrides,
        )
        self.label_clear_button.grid(row=3, column=2, padx=3, pady=3, sticky="w")
        ttk.Button(
            label_tools,
            text="清空诊断列表",
            command=lambda: self._show_label_issues(()),
        ).grid(row=3, column=3, padx=3, pady=3, sticky="w")
        label_tools.columnconfigure(5, weight=1)

        sid_identity = ttk.LabelFrame(sid_tab, text="1. SID 查找条件", padding=10)
        sid_identity.pack(fill="x")
        self.sid_game_var = tk.StringVar(value="火红")
        self.sid_nx_var = tk.StringVar(value="Switch 1")
        self.sid_tid_var = tk.StringVar(value="12345")
        self.sid_count_var = tk.StringVar(value="2")
        self.sid_candies_var = tk.StringVar(value="5")
        self.sid_threshold_var = tk.StringVar(value="85")
        self.sid_ack_var = tk.BooleanVar(value=False)
        self._labeled_combo(
            sid_identity, "游戏", self.sid_game_var, ("火红", "叶绿"), 0, 0
        )
        self._labeled_combo(
            sid_identity,
            "主机",
            self.sid_nx_var,
            ("Switch 1", "Switch 2"),
            0,
            2,
        )
        self._labeled_entry(sid_identity, "当前 TID", self.sid_tid_var, 0, 4, width=12)
        self._labeled_combo(
            sid_identity,
            "队内闪光数量",
            self.sid_count_var,
            tuple(str(value) for value in range(1, 7)),
            0,
            6,
            width=8,
        )
        self._labeled_entry(
            sid_identity, "每只最多糖果", self.sid_candies_var, 1, 0, width=8
        )
        self._labeled_entry(
            sid_identity, "识图阈值", self.sid_threshold_var, 1, 2, width=8
        )
        self._help_marker(
            sid_identity,
            "SID 反查范围",
            "支持第三世代 Method 1/2/4。闪光公式只能确定 8 个真实 SID 候选；"
            "建档链前 10000 ADV 有命中时再选最早值。",
            label="?",
        ).grid(row=1, column=4, columnspan=4, sticky="w", padx=4, pady=4)
        ttk.Checkbutton(
            sid_identity,
            text="已确认队伍顺序、宝可梦、初始等级、来源、努力值准确，且背包第一页第一格是神奇糖果",
            variable=self.sid_ack_var,
        ).grid(row=2, column=0, columnspan=8, sticky="w", padx=4, pady=(5, 0))

        sid_party = ttk.LabelFrame(sid_tab, text="2. 队伍闪光宝可梦信息", padding=8)
        sid_party.pack(fill="x", pady=(8, 0))
        sid_party_headers = (
            "槽位",
            "宝可梦（名称/编号）",
            "初始等级",
            "来源",
            "Ten Lines 相遇地点（野生必填）",
            *IV_STAT_LABELS,
        )
        for column, label in enumerate(sid_party_headers):
            ttk.Label(sid_party, text=label).grid(row=0, column=column, padx=4, pady=3)
        sid_party.columnconfigure(4, weight=1)
        self.sid_species_vars = tuple(tk.StringVar(value="") for _ in range(6))
        self.sid_initial_level_vars = tuple(tk.StringVar(value="") for _ in range(6))
        self.sid_source_type_vars = tuple(tk.StringVar(value="定点") for _ in range(6))
        self.sid_location_vars = tuple(tk.StringVar(value="") for _ in range(6))
        self.sid_effort_vars = tuple(
            tuple(tk.StringVar(value="0") for _ in IV_STAT_LABELS)
            for _ in range(6)
        )
        sid_species_choices, _ = species_input_catalog()
        self.sid_party_row_widgets = []
        self.sid_location_map = {}
        for locations in self.all_locations.values():
            for location in locations:
                self.sid_location_map[f"{location_to_zh(location)} ({location})"] = location
        location_choices = tuple(sorted(self.sid_location_map))
        for index in range(6):
            row = index + 1
            row_widgets = []
            slot_label = ttk.Label(sid_party, text=str(index + 1))
            slot_label.grid(row=row, column=0, padx=4, pady=2)
            row_widgets.append((slot_label, "normal"))
            species_combo = ttk.Combobox(
                sid_party,
                textvariable=self.sid_species_vars[index],
                values=sid_species_choices,
                width=22,
            )
            species_combo.grid(row=row, column=1, padx=4, pady=2)
            _install_autocomplete_combo(
                species_combo,
                sid_species_choices,
                self.sid_species_vars[index],
            )
            row_widgets.append((species_combo, "normal"))
            level_spinbox = ttk.Spinbox(
                sid_party,
                from_=1,
                to=100,
                width=6,
                justify="center",
                textvariable=self.sid_initial_level_vars[index],
            )
            level_spinbox.grid(row=row, column=2, padx=3, pady=2)
            row_widgets.append((level_spinbox, "normal"))
            source_combo = ttk.Combobox(
                sid_party,
                textvariable=self.sid_source_type_vars[index],
                values=SID_SOURCE_LABELS,
                width=8,
                state="readonly",
            )
            source_combo.grid(row=row, column=3, padx=4, pady=2)
            row_widgets.append((source_combo, "readonly"))
            location_combo = ttk.Combobox(
                sid_party,
                textvariable=self.sid_location_vars[index],
                values=location_choices,
                width=30,
            )
            location_combo.grid(row=row, column=4, sticky="we", padx=4, pady=2)
            _install_autocomplete_combo(
                location_combo,
                location_choices,
                self.sid_location_vars[index],
            )
            row_widgets.append((location_combo, "normal"))
            for stat_index, variable in enumerate(self.sid_effort_vars[index], 5):
                effort_spinbox = ttk.Spinbox(
                    sid_party,
                    from_=0,
                    to=255,
                    width=5,
                    justify="center",
                    textvariable=variable,
                )
                effort_spinbox.grid(row=row, column=stat_index, padx=3, pady=2)
                row_widgets.append((effort_spinbox, "normal"))
            self.sid_party_row_widgets.append(tuple(row_widgets))
        self._help_marker(
            sid_party,
            "队伍输入规则",
            "只处理队伍前 N 位；活动槽位可输入中文名、英文名或全国图鉴编号。"
            "孵蛋来源与非 Method 1/2/4 个体暂不支持。",
            label="?",
        ).grid(
            row=7,
            column=0,
            columnspan=len(sid_party_headers),
            sticky="w",
            padx=4,
            pady=(5, 0),
        )
        self.sid_count_var.trace_add("write", self._refresh_sid_party_rows)
        self._refresh_sid_party_rows()

        sid_source = ttk.LabelFrame(sid_tab, text="3. SID 查找脚本", padding=8)
        sid_source.pack(fill="x", pady=(8, 0))
        # 优先使用安装器生成的已审计本地快照。下载目录可能仍是旧版
        # SID 模板或缺少闪光雄性标签，不能因为文件“存在”就绕过导入结果。
        self.sid_source_var = tk.StringVar(value=str(DEFAULT_SOURCE_118))
        self._labeled_entry(
            sid_source, SCRIPT_PACKAGE_UI_NAME, self.sid_source_var, 0, 0, width=70, span=5
        )
        ttk.Button(sid_source, text="选择", command=self.choose_sid_source).grid(
            row=0, column=6, padx=4
        )

        identity = ttk.LabelFrame(normal_tab, text="1. 乱数条件", padding=10)
        identity.pack(fill="x")
        self.game_var = tk.StringVar(value="火红")
        self.nx_var = tk.StringVar(value="Switch 1")
        self.tid_var = tk.StringVar(value="58888")
        self.sid_var = tk.StringVar(value="12232")
        self.method_var = tk.StringVar(value="野生")
        self.category_var = tk.StringVar()
        self.location_var = tk.StringVar()
        self.pokemon_var = tk.StringVar()

        self.game_combo = self._labeled_combo(identity, "游戏", self.game_var, ("火红", "叶绿"), 0, 0)
        self.nx_combo = self._labeled_combo(identity, "主机", self.nx_var, ("Switch 1", "Switch 2"), 0, 2)
        self._labeled_entry(identity, "TID", self.tid_var, 0, 4)
        self._labeled_entry(identity, "SID", self.sid_var, 0, 6)
        self.method_combo = self._labeled_combo(
            identity, "类型", self.method_var, ("野生", "静态"), 1, 0
        )
        self.category_combo = self._labeled_combo(identity, "遭遇方式", self.category_var, (), 1, 2)
        self.location_combo = self._labeled_combo(identity, "地点", self.location_var, (), 1, 4, width=24)
        self.pokemon_combo = self._labeled_combo(identity, "宝可梦", self.pokemon_var, (), 1, 6, width=24)
        self.method_combo.bind("<<ComboboxSelected>>", lambda _: self._on_method_change())
        self.game_combo.bind("<<ComboboxSelected>>", lambda _: self._on_game_change())
        self.nx_combo.bind("<<ComboboxSelected>>", lambda _: self._on_game_change())
        self.category_combo.bind("<<ComboboxSelected>>", lambda _: self._populate_locations())
        self.location_combo.bind("<<ComboboxSelected>>", lambda _: self._populate_pokemon())
        self.pokemon_combo.bind("<<ComboboxSelected>>", lambda _: self._populate_abilities())

        filters = ttk.LabelFrame(normal_tab, text="2. 筛选与最大 Advance", padding=10)
        filters.pack(fill="x", pady=(10, 0))
        self.iv_min_vars = tuple(tk.StringVar(value="0") for _ in IV_STAT_LABELS)
        self.iv_max_vars = tuple(tk.StringVar(value="31") for _ in IV_STAT_LABELS)
        self.search_mode_var = tk.StringVar(value="筛选搜索")
        self.direct_seed_var = tk.StringVar(value="0000")
        self.direct_adv_var = tk.StringVar(value="3000")
        self.min_adv_var = tk.StringVar(value="3000")
        self.max_adv_var = tk.StringVar(value="100000")
        self.shiny_var = tk.StringVar(value="星形/方形闪光")
        self.nature_var = tk.StringVar(value="不限")
        self.gender_var = tk.StringVar(value="不限")
        self.ability_var = tk.StringVar(value="不限")
        self.hidden_type_var = tk.StringVar(value="不限")
        self.seed_mode_var = tk.StringVar(value="自动选择")
        self.auto_capture_var = tk.BooleanVar(value=False)
        self.paralysis_var = tk.BooleanVar(value=False)
        self.false_swipe_var = tk.BooleanVar(value=False)
        self.item_rng_mode_var = tk.BooleanVar(value=False)
        self.party_empty_slots_var = tk.StringVar(value="1")
        self.sid_traversal_var = tk.BooleanVar(value=False)
        self.sid_traversal_max_adv_var = tk.StringVar(
            value=str(SID_TRAVERSAL_DEFAULT_MAX_ADVANCES)
        )
        self.sid_traversal_start_adv_var = tk.StringVar(value="")

        iv_frame = ttk.LabelFrame(filters, text="个体值范围", padding=(8, 5))
        iv_frame.grid(row=0, column=0, columnspan=8, sticky="we", padx=4, pady=(0, 6))
        ttk.Label(iv_frame, text="能力").grid(row=0, column=0, padx=(2, 8), pady=2)
        ttk.Label(iv_frame, text="最低").grid(row=1, column=0, padx=(2, 8), pady=2)
        ttk.Label(iv_frame, text="最高").grid(row=2, column=0, padx=(2, 8), pady=2)
        ttk.Label(iv_frame, text="单项重置").grid(row=3, column=0, padx=(2, 8), pady=2)
        self.iv_spinboxes = []
        for index, label in enumerate(IV_STAT_LABELS, 1):
            ttk.Label(iv_frame, text=label).grid(row=0, column=index, padx=5, pady=2)
            minimum = ttk.Spinbox(
                iv_frame,
                from_=0,
                to=31,
                width=5,
                justify="center",
                textvariable=self.iv_min_vars[index - 1],
            )
            maximum = ttk.Spinbox(
                iv_frame,
                from_=0,
                to=31,
                width=5,
                justify="center",
                textvariable=self.iv_max_vars[index - 1],
            )
            minimum.grid(row=1, column=index, padx=5, pady=2)
            maximum.grid(row=2, column=index, padx=5, pady=2)
            ttk.Button(
                iv_frame,
                text="0–31",
                width=5,
                command=lambda stat_index=index - 1: self.reset_iv_stat(stat_index),
            ).grid(row=3, column=index, padx=5, pady=2)
            self.iv_spinboxes.append((minimum, maximum))
            iv_frame.columnconfigure(index, weight=1)

        preset_frame = ttk.Frame(iv_frame)
        preset_frame.grid(row=0, column=7, rowspan=4, sticky="w", padx=(16, 2))
        ttk.Label(preset_frame, text="Ten Lines 预设").pack(anchor="w", pady=(0, 3))
        preset_buttons = ttk.Frame(preset_frame)
        preset_buttons.pack(anchor="w")
        for preset in IV_PRESETS:
            ttk.Button(
                preset_buttons,
                text=preset,
                width=6,
                command=lambda value=preset: self.apply_iv_preset(value),
            ).pack(side="left", padx=(0, 4))

        self._labeled_combo(filters, "运行模式", self.search_mode_var, ("筛选搜索", "指定 Seed/帧数"), 1, 0)
        self._labeled_entry(filters, "最小 Advance", self.min_adv_var, 1, 2, width=12)
        self._labeled_entry(filters, "最大 Advance", self.max_adv_var, 1, 4, width=12)
        self._labeled_combo(
            filters, "闪光", self.shiny_var,
            ("不限", *[value for value in FILTER_SHINY_ZH_TO_EN if value != "不限"]), 2, 0,
        )
        self._labeled_combo(
            filters, "性格", self.nature_var,
            ("不限", *[value for value in FILTER_NATURE_ZH_TO_EN if value != "不限"]), 2, 2, width=12,
        )
        self._labeled_combo(
            filters, "性别", self.gender_var,
            ("不限", *[value for value in FILTER_GENDER_ZH_TO_EN if value != "不限"]), 2, 4,
        )
        self.ability_combo = self._labeled_combo(filters, "特性", self.ability_var, ("不限",), 2, 6, width=14)
        self._labeled_combo(
            filters, "觉醒力量", self.hidden_type_var,
            ("不限", *[value for value in FILTER_TYPE_ZH_TO_EN if value != "不限"]), 3, 0,
        )
        self.seed_mode_combo = self._labeled_combo(
            filters, "Seed 模式", self.seed_mode_var,
            ("自动选择", *SEED_MODE_CHOICES), 3, 2, width=36, span=3,
        )
        direct_frame = ttk.Frame(filters)
        direct_frame.grid(row=4, column=0, columnspan=8, sticky="w", padx=4, pady=(3, 0))
        self._labeled_entry(direct_frame, "指定初始 Seed", self.direct_seed_var, 0, 0, width=10)
        self._labeled_entry(direct_frame, "指定消耗帧", self.direct_adv_var, 0, 2, width=12)
        self._help_marker(
            direct_frame,
            "指定 Seed / 帧数",
            "指定模式会跳过筛选搜索，Seed 模式必须手动选择。",
        ).grid(
            row=0, column=4, columnspan=4, sticky="w", padx=4
        )
        self.search_mode_combo = filters.grid_slaves(row=1, column=1)[0]
        self.search_mode_combo.bind("<<ComboboxSelected>>", lambda _: self._update_search_mode_controls())
        self._direct_entries = direct_frame.winfo_children()
        capture_options = ttk.Frame(filters)
        capture_options.grid(row=5, column=0, columnspan=8, sticky="w", padx=6, pady=(2, 0))
        ttk.Checkbutton(capture_options, text="出闪后自动抓捕", variable=self.auto_capture_var).pack(side="left")
        ttk.Checkbutton(capture_options, text="麻痹", variable=self.paralysis_var).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(capture_options, text="点到为止", variable=self.false_swipe_var).pack(side="left", padx=(12, 0))
        self.item_rng_mode_check = ttk.Checkbutton(
            capture_options,
            text="道具乱数模式",
            variable=self.item_rng_mode_var,
            command=self._update_item_rng_controls,
        )
        self.item_rng_mode_check.pack(side="left", padx=(12, 0))
        ttk.Label(capture_options, text="队伍空位").pack(side="left", padx=(8, 2))
        self.party_empty_slots_spin = ttk.Spinbox(
            capture_options,
            from_=1,
            to=5,
            width=4,
            justify="center",
            textvariable=self.party_empty_slots_var,
        )
        self.party_empty_slots_spin.pack(side="left")
        self._help_marker(
            capture_options,
            "出闪后处理",
            "未勾选自动抓捕时，脚本会在识别到闪光后停止，交给用户处理。",
        ).pack(side="left", padx=(14, 0))
        self._help_marker(
            capture_options,
            "道具乱数模式",
            "仅野生目标可用。开启后，物种正确且“无道具”标签不匹配时计为一次命中；"
            "脚本按队伍空位数保存对应次数的携带道具目标，支持 1–5 个空位。",
        ).pack(side="left", padx=(6, 0))
        traversal_options = ttk.Frame(filters)
        traversal_options.grid(
            row=6, column=0, columnspan=8, sticky="w", padx=6, pady=(2, 0)
        )
        self.sid_traversal_check = ttk.Checkbutton(
            traversal_options,
            text="SID 遍历模式",
            variable=self.sid_traversal_var,
            command=self._update_item_rng_controls,
        )
        self.sid_traversal_check.pack(side="left")
        ttk.Label(traversal_options, text="遍历上限").pack(side="left", padx=(8, 2))
        self.sid_traversal_max_adv_spin = ttk.Spinbox(
            traversal_options,
            from_=0,
            to=65535,
            width=7,
            justify="center",
            textvariable=self.sid_traversal_max_adv_var,
        )
        self.sid_traversal_max_adv_spin.pack(side="left")
        self._help_marker(
            traversal_options,
            "SID 遍历模式",
            "仅野生目标可用。生成前会确认当前 TID 是否正确，并询问是否给劲敌取名；"
            "未取名从 ADV 1901 开始且只走奇数 ADV，取名从 ADV 1900 开始且只走偶数 ADV，"
            "每次推进 2 帧。每个 SID 候选都会先搜索低帧闪光目标；"
            "明确未出闪才推进并保存下一起点，中途停止会保留当前候选，下一次从断点继续。",
        ).pack(side="left", padx=(8, 0))
        self.sid_traversal_start_label = ttk.Label(
            traversal_options, text="高级起点"
        )
        self.sid_traversal_start_label.pack(side="left", padx=(10, 2))
        self.sid_traversal_start_adv_entry = ttk.Entry(
            traversal_options,
            textvariable=self.sid_traversal_start_adv_var,
            width=7,
        )
        self.sid_traversal_start_adv_entry.pack(side="left")
        self._help_marker(
            traversal_options,
            "自定义 SID 起点",
            "仅高级模式可用。留空使用 1901（未给劲敌取名）或 1900（给劲敌取名）；"
            "填写后必须与劲敌取名对应的奇偶一致，并作为新的任务起点使用独立断点，"
            "不会覆盖其它起点的进度。",
        ).pack(side="left", padx=(6, 0))
        self.sid_traversal_progress_var = tk.StringVar(
            value="尚无 SID 遍历断点；生成后会显示保存的起点。"
        )
        ttk.Label(
            traversal_options,
            textvariable=self.sid_traversal_progress_var,
            wraplength=760,
            justify="left",
        ).pack(side="left", padx=(10, 0))
        self._update_item_rng_controls()

        egg_identity = ttk.LabelFrame(egg_tab, text="1. 孵蛋运行条件", padding=10)
        egg_identity.pack(fill="x")
        self.egg_seed_mode_var = tk.StringVar(value="请选择")
        self.egg_pokemon_var = tk.StringVar()
        self.egg_start_mode_var = tk.StringVar(value=EGG_START_MODE_FULL)
        self.egg_pokemon_map = {}
        self.egg_game_combo = self._labeled_combo(
            egg_identity, "游戏", self.game_var, ("火红", "叶绿"), 0, 0
        )
        self.egg_nx_combo = self._labeled_combo(
            egg_identity, "主机", self.nx_var, ("Switch 1", "Switch 2"), 0, 2
        )
        self.egg_seed_mode_combo = self._labeled_combo(
            egg_identity, "Seed 模式", self.egg_seed_mode_var,
            ("请选择", *SEED_MODE_CHOICES), 0, 4, width=36,
        )
        self.egg_pokemon_combo = self._labeled_combo(
            egg_identity,
            "蛋种（名称/编号）",
            self.egg_pokemon_var,
            (),
            1,
            0,
            width=24,
            span=3,
        )
        egg_species_choices, _ = species_input_catalog()
        self.egg_pokemon_combo.configure(state="normal", values=egg_species_choices)
        _install_autocomplete_combo(
            self.egg_pokemon_combo,
            egg_species_choices,
            self.egg_pokemon_var,
        )
        self._help_marker(
            egg_identity,
            "孵蛋 Seed 模式",
            "必须与 Ten Lines Egg 页搜索时使用的游戏设置一致。",
        ).grid(row=1, column=4, columnspan=3, sticky="w", padx=4, pady=4)
        self._labeled_combo(
            egg_identity,
            "启动准备",
            self.egg_start_mode_var,
            EGG_START_MODES,
            2,
            0,
            width=34,
            span=3,
        )
        self._help_marker(
            egg_identity,
            "从 254 步基础档开始",
            "第二项要求当前存档已经完成 254 步准备；仍会执行所选 Seed 启动方案与全部校准流程。",
        ).grid(row=2, column=4, columnspan=3, sticky="w", padx=4, pady=4)
        self.egg_game_combo.bind("<<ComboboxSelected>>", lambda _: self._on_game_change())
        self.egg_nx_combo.bind("<<ComboboxSelected>>", lambda _: self._on_game_change())

        egg = ttk.LabelFrame(
            egg_tab,
            text="2. 孵蛋目标",
            padding=8,
        )
        egg.pack(fill="x", pady=(10, 0))
        self.egg_seed_var = tk.StringVar(value="75D1")
        self.egg_held_var = tk.StringVar(value="8021")
        self.egg_pickup_var = tk.StringVar(value="10021")
        self.egg_compatibility_var = tk.StringVar(value="70")
        self.egg_parent_a_gender_var = tk.StringVar(value="雌")
        self.egg_parent_b_gender_var = tk.StringVar(value="雄")
        self.egg_parent_a_iv_vars = tuple(tk.StringVar(value="31") for _ in IV_STAT_LABELS)
        self.egg_parent_b_iv_vars = tuple(tk.StringVar(value="31") for _ in IV_STAT_LABELS)
        self.egg_ack_var = tk.BooleanVar(value=False)
        self._labeled_entry(egg, "目标 Seed", self.egg_seed_var, 0, 0, width=10)
        self._labeled_entry(egg, "Held/生成帧", self.egg_held_var, 0, 2, width=12)
        self._labeled_entry(egg, "Pickup/领取帧", self.egg_pickup_var, 0, 4, width=12)
        self._labeled_combo(
            egg, "双亲相性", self.egg_compatibility_var, ("20", "50", "70"), 0, 6, width=8
        )
        ttk.Label(egg, text="亲本").grid(row=1, column=0, sticky="e", padx=(4, 2), pady=3)
        ttk.Label(egg, text="性别").grid(row=1, column=1, padx=3, pady=3)
        for index, stat in enumerate(IV_STAT_LABELS, 2):
            ttk.Label(egg, text=stat).grid(row=1, column=index, padx=3, pady=3)
        ttk.Label(egg, text="A").grid(row=2, column=0, sticky="e", padx=3, pady=3)
        self._egg_parent_row(
            egg, 2, self.egg_parent_a_gender_var, ("雌", "无性别"), self.egg_parent_a_iv_vars
        )
        ttk.Label(egg, text="B").grid(row=3, column=0, sticky="e", padx=3, pady=3)
        self._egg_parent_row(
            egg, 3, self.egg_parent_b_gender_var, ("雄", "无性别"), self.egg_parent_b_iv_vars
        )
        ttk.Checkbutton(
            egg,
            text="我已确认孵蛋前置条件，允许启动流程",
            variable=self.egg_ack_var,
        ).grid(row=4, column=0, columnspan=7, sticky="w", padx=6, pady=(5, 0))
        self._help_marker(
            egg,
            "孵蛋运行确认",
            "该流程尚未完成本机整轮实机验收。启动前请确认 254 步基础档、队伍空位、"
            "甜甜香气宝可梦和 Ten Lines 目标参数均正确。",
        ).grid(row=4, column=7, sticky="e", padx=6, pady=(5, 0))
        egg_config_actions = ttk.Frame(egg)
        egg_config_actions.grid(row=5, column=0, columnspan=8, sticky="w", padx=6, pady=(7, 0))
        ttk.Button(
            egg_config_actions,
            text="保存亲本配置",
            command=self.save_egg_parent_config,
        ).pack(side="left")
        ttk.Button(
            egg_config_actions,
            text="载入亲本配置",
            command=self.load_egg_parent_config,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            egg_config_actions,
            text="保存全部配置",
            command=self.save_egg_full_config,
        ).pack(side="left", padx=(16, 0))
        ttk.Button(
            egg_config_actions,
            text="载入全部配置",
            command=self.load_egg_full_config,
        ).pack(side="left", padx=(8, 0))
        self._help_marker(
            egg_config_actions,
            "目标数据来源",
            "目标 Seed、Held / 生成帧和 Pickup / 领取帧需要先从 Ten Lines Egg 页取得。",
        ).pack(side="left", padx=(14, 0))

        tid_identity = ttk.LabelFrame(tid_tab, text="1. TID / SID 基本条件", padding=8)
        tid_identity.pack(fill="x")
        self.tid_language_var = tk.StringVar(value="英文")
        self.tid_game_var = tk.StringVar(value="火红")
        self.tid_mode_var = tk.StringVar(value="乱数模式")
        self.tid_nx_var = tk.StringVar(value="Switch 1")
        self.tid_gender_var = tk.StringVar(value="女性")
        self.tid_target_var = tk.StringVar(value="0")
        self.tid_sid_var = tk.StringVar(value="38449")
        self.tid_shiny_pid_var = tk.StringVar(value=DEFAULT_TID_SHINY_PID)
        self.tid_name_var = tk.StringVar(value="Alxe")
        self.tid_sid_mode_var = tk.StringVar(value=TID_SID_MODE_TARGET)
        self.tid_calibration_var = tk.BooleanVar(value=False)
        self.tid_language_combo = self._labeled_combo(
            tid_identity, "ROM 语言", self.tid_language_var, ("英文", "日文"), 0, 0
        )
        self.tid_mode_combo = self._labeled_combo(
            tid_identity, "运行模式", self.tid_mode_var,
            ("乱数模式", "穷举模式"), 0, 2,
        )
        self._labeled_combo(
            tid_identity, "主机", self.tid_nx_var,
            ("Switch 1", "Switch 2"), 0, 4,
        )
        self._labeled_combo(
            tid_identity, "主角性别", self.tid_gender_var,
            ("男性", "女性"), 0, 6,
        )
        self.tid_target_entry = self._labeled_entry(tid_identity, "目标 TID", self.tid_target_var, 1, 0, width=12)
        self.tid_sid_entry = self._labeled_entry(
            tid_identity, "目标 SID", self.tid_sid_var, 1, 2, width=12
        )
        self._labeled_entry(tid_identity, "主角名称", self.tid_name_var, 1, 4, width=18)
        self.tid_sid_mode_combo = self._labeled_combo(
            tid_identity, "SID 处理", self.tid_sid_mode_var,
            TID_SID_MODES, 1, 6,
        )
        self._help_marker(
            tid_identity,
            "SID 处理",
            "目标 SID 模式会按目标 SID 自动计算最低可用 ADV；不乱数 SID 模式固定 F3，"
            "由实际生成链决定 SID。目标 SID 搜索上限为 1,000,000 ADV；连续御三家流程在"
            "后一种模式下会取得实际 SID 后再动态生成目标。",
        ).grid(row=3, column=4, columnspan=2, sticky="e", padx=4, pady=(0, 3))
        self.tid_calibration_check = ttk.Checkbutton(
            tid_identity,
            text="先检测固定延迟，完成后自动运行计划",
            variable=self.tid_calibration_var,
        )
        self.tid_calibration_check.grid(
            row=2, column=2, columnspan=4, sticky="w", padx=4, pady=4
        )
        self._add_tooltip(
            self.tid_calibration_check,
            "固定延迟检测",
            "先测量 OP、F1、F2、F3 和实际 OP 修正；测量完整后自动回填、重新生成并预检计划，"
            "通过后继续运行，不会再次弹出确认。",
        )
        self.tid_game_combo = self._labeled_combo(
            tid_identity, "游戏版本", self.tid_game_var, ("火红", "叶绿"), 2, 0
        )
        self.tid_shiny_pid_entry = self._labeled_entry(
            tid_identity,
            "6V闪 PID",
            self.tid_shiny_pid_var,
            2,
            6,
            width=12,
        )
        self.tid_shiny_sid_button = ttk.Button(
            tid_identity,
            text="6V 闪 SID",
            command=self.calculate_tid_shiny_sid,
        )
        self.tid_shiny_sid_button.grid(
            row=3,
            column=6,
            columnspan=2,
            sticky="w",
            padx=4,
            pady=(0, 3),
        )
        self._add_tooltip(
            self.tid_shiny_pid_entry,
            "6V闪 SID",
            "按当前 TID 和指定 PID 计算闪光 PSV，搜索至少从 F3 固定延迟换算帧起，"
            "并计入当前语言脚本的 SID 前置补偿和 SID ADV 修正；在 1,000,000 ADV 上限内"
            "选择最早可执行的合法 SID。普通模式固定使用 7942EF72；开启高级模式后可编辑 PID。",
        )
        self._add_tooltip(
            self.tid_shiny_sid_button,
            "6V 闪 SID",
            "只计算并回填目标 SID，不启动游戏。搜索起点不能早于 F3 固定延迟对应帧，"
            "并会计入当前语言的 SID 前置补偿和 SID ADV 修正；结果按最低可执行 ADV，"
            "而不是 SID 数值大小。",
        )
        ttk.Label(
            tid_identity,
            text="脚本会新建存档并自动退出游戏两次；请先确认当前存档与主页状态。",
            foreground="#9a3412",
        ).grid(row=4, column=0, columnspan=8, sticky="w", padx=4, pady=(3, 0))
        self.tid_language_combo.bind(
            "<<ComboboxSelected>>", lambda _: self._apply_tid_language_defaults()
        )
        self.tid_mode_combo.bind(
            "<<ComboboxSelected>>", lambda _: self._update_tid_flow_controls()
        )
        self.tid_sid_mode_combo.bind(
            "<<ComboboxSelected>>", lambda _: self._update_tid_flow_controls()
        )

        tid_frames = ttk.LabelFrame(
            tid_tab, text="2. 乱数中心 / 穷举范围", padding=8
        )
        tid_frames.pack(fill="x", pady=(8, 0))
        self.tid_op_target_var = tk.StringVar(value="3693")
        self.tid_f1_target_var = tk.StringVar(value="2693")
        self.tid_f2_target_var = tk.StringVar(value="2105")
        self.tid_op_rng_range_var = tk.StringVar(value="0")
        self.tid_f1_rng_range_var = tk.StringVar(value="0")
        self.tid_f2_rng_range_var = tk.StringVar(value="0")
        self.tid_op_start_var = tk.StringVar(value="0")
        self.tid_f1_start_var = tk.StringVar(value="0")
        self.tid_f2_start_var = tk.StringVar(value="0")
        self.tid_op_max_range_var = tk.StringVar(value="600")
        self.tid_f1_max_range_var = tk.StringVar(value="30")
        self.tid_f2_max_range_var = tk.StringVar(value="300")
        ttk.Label(tid_frames, text="参数").grid(row=0, column=0, padx=5, pady=2)
        for column, label in enumerate(("OP", "F1", "F2"), 1):
            ttk.Label(tid_frames, text=label).grid(row=0, column=column, padx=18, pady=2)
            tid_frames.columnconfigure(column, weight=1)
        self._help_marker(
            tid_frames,
            "帧数单位",
            "帧数为 RNG advance，沿用 TID 脚本的 120.00144 advance/s 换算；WAIT 和固定延迟使用毫秒。",
        ).grid(row=0, column=4, padx=5, pady=2)
        frame_rows = (
            ("乱数中心帧", (self.tid_op_target_var, self.tid_f1_target_var, self.tid_f2_target_var)),
            ("乱数搜索半径", (self.tid_op_rng_range_var, self.tid_f1_rng_range_var, self.tid_f2_rng_range_var)),
            ("穷举起点", (self.tid_op_start_var, self.tid_f1_start_var, self.tid_f2_start_var)),
            ("穷举最大范围", (self.tid_op_max_range_var, self.tid_f1_max_range_var, self.tid_f2_max_range_var)),
        )
        for row, (label, variables) in enumerate(frame_rows, 1):
            ttk.Label(tid_frames, text=label).grid(row=row, column=0, sticky="e", padx=5, pady=3)
            for column, variable in enumerate(variables, 1):
                ttk.Entry(tid_frames, textvariable=variable, width=12).grid(
                    row=row, column=column, padx=8, pady=3
                )

        self.tid_additional_targets_var = tk.StringVar(value="")
        self.tid_auto_rng_var = tk.BooleanVar(value=False)
        self.tid_near_distance_var = tk.StringVar(value="100")
        self.tid_near_hits_var = tk.StringVar(value="3")
        self.tid_auto_op_range_var = tk.StringVar(value="20")
        self.tid_auto_f1_range_var = tk.StringVar(value="20")
        self.tid_auto_f2_range_var = tk.StringVar(value="10")
        ttk.Label(tid_frames, text="穷举额外目标TID").grid(row=5, column=0, sticky="e", padx=5)
        ttk.Entry(tid_frames, textvariable=self.tid_additional_targets_var).grid(
            row=5, column=1, columnspan=3, sticky="ew", padx=8, pady=3)
        self._help_marker(tid_frames, "多个目标", "主目标始终保留；额外目标用空格或逗号分隔，最多31个，例如 00000, 33333, 65535。仅穷举使用；切换乱数后锁定已确认的区域目标。").grid(row=5, column=4)
        ttk.Checkbutton(tid_frames, text="接近目标区间后自动转乱数", variable=self.tid_auto_rng_var).grid(
            row=6, column=0, columnspan=4, sticky="w", padx=5, pady=4)
        ttk.Label(tid_frames, text="接近距离 / 次数").grid(row=7, column=0, sticky="e", padx=5)
        ttk.Entry(tid_frames, textvariable=self.tid_near_distance_var, width=12).grid(row=7, column=1, padx=8, pady=3)
        ttk.Entry(tid_frames, textvariable=self.tid_near_hits_var, width=12).grid(row=7, column=2, padx=8, pady=3)
        self._help_marker(tid_frames, "目标区间确认", "同一参数窗口按目标分别统计，默认±100内3次后切换。局部范围完整搜索一遍后返回原穷举位置；最近16个完成区域随进度保存。同一目标在已搜区域内不反复切入。距离不是帧补偿。").grid(row=7, column=4)
        ttk.Label(tid_frames, text="自动切换后半径").grid(row=8, column=0, sticky="e", padx=5)
        for column, variable in enumerate((self.tid_auto_op_range_var, self.tid_auto_f1_range_var, self.tid_auto_f2_range_var), 1):
            ttk.Entry(tid_frames, textvariable=variable, width=12).grid(row=8, column=column, padx=8, pady=3)
        ttk.Label(tid_frames, text="越过下限时只裁剪负向范围，保留正向范围；负半径归零，按步长2向下取偶数。", foreground="#475569").grid(
            row=9, column=0, columnspan=5, sticky="w", padx=5, pady=3)

        tid_settings = ttk.LabelFrame(tid_tab, text="3. 游戏设置与固定延迟", padding=8)
        tid_settings.pack(fill="x", pady=(8, 0))
        self.tid_sound_var = tk.StringVar(value="MONO")
        self.tid_button_mode_var = tk.StringVar(value="HELP")
        self.tid_seed_button_var = tk.StringVar(value="A")
        self.tid_name_entry_var = tk.StringVar(value="A")
        self.tid_op_delay_var = tk.StringVar(value="30600")
        self.tid_f1_delay_var = tk.StringVar(value="22050")
        self.tid_f2_delay_var = tk.StringVar(value="4250")
        self.tid_f3_delay_var = tk.StringVar(value="14900")
        self.tid_close_delay_var = tk.StringVar(value="1500")
        self.tid_home_buffer_var = tk.StringVar(value="1200")
        self.tid_op_correction_var = tk.StringVar(value="0")
        self.tid_sid_adv_correction_var = tk.StringVar(value="0")
        self.tid_select_correction_var = tk.StringVar(value="0")
        self.tid_manual_delay_var = tk.BooleanVar(value=False)
        self._labeled_combo(tid_settings, "Sound", self.tid_sound_var, ("MONO", "STEREO"), 0, 0)
        self._labeled_combo(
            tid_settings, "Button Mode", self.tid_button_mode_var,
            ("HELP", "LR", "L=A"), 0, 2,
        )
        self._labeled_combo(
            tid_settings, "Seed Button", self.tid_seed_button_var,
            ("A", "START", "L(L=A)"), 0, 4,
        )
        self._labeled_combo(
            tid_settings, "取名进入键", self.tid_name_entry_var, ("A", "B"), 0, 6
        )
        tid_op_delay_entry = self._labeled_entry(
            tid_settings, "OP 固定延迟", self.tid_op_delay_var, 1, 0, width=12
        )
        tid_f1_delay_entry = self._labeled_entry(
            tid_settings, "F1 固定延迟", self.tid_f1_delay_var, 1, 2, width=12
        )
        tid_f2_delay_entry = self._labeled_entry(
            tid_settings, "F2 固定延迟", self.tid_f2_delay_var, 1, 4, width=12
        )
        tid_f3_delay_entry = self._labeled_entry(
            tid_settings, "F3 固定延迟", self.tid_f3_delay_var, 1, 6, width=12
        )
        self.tid_delay_entries = (
            tid_op_delay_entry,
            tid_f1_delay_entry,
            tid_f2_delay_entry,
            tid_f3_delay_entry,
        )
        self._labeled_entry(tid_settings, "关闭游戏延迟", self.tid_close_delay_var, 2, 0, width=12)
        self._labeled_entry(tid_settings, "HOME_BUFFER", self.tid_home_buffer_var, 2, 2, width=12)
        self._labeled_entry(tid_settings, "OP 修正", self.tid_op_correction_var, 2, 4, width=12)
        self._labeled_entry(tid_settings, "SID ADV 修正", self.tid_sid_adv_correction_var, 2, 6, width=12)
        self._labeled_entry(tid_settings, "select 补偿", self.tid_select_correction_var, 3, 0, width=12)
        self.tid_manual_delay_check = ttk.Checkbutton(
            tid_settings,
            text="手动编辑固定延迟",
            variable=self.tid_manual_delay_var,
            command=self._update_tid_delay_controls,
        )
        self.tid_manual_delay_check.grid(
            row=3, column=2, columnspan=5, sticky="w", padx=4, pady=4
        )
        self._help_marker(
            tid_settings,
            "固定延迟编辑",
            "默认关闭；固定延迟检查完成后会自动回填 OP、F1、F2、F3。",
        ).grid(row=3, column=7, sticky="w", padx=4, pady=4)

        tid_starter = ttk.LabelFrame(tid_tab, text="4. 御三家连续乱数", padding=8)
        tid_starter.pack(fill="x", pady=(8, 0))
        self.tid_starter_flow_var = tk.BooleanVar(value=True)
        self.tid_any_tid_var = tk.BooleanVar(value=False)
        self.tid_any_tid_denoise_var = tk.BooleanVar(value=True)
        self.tid_starter_var = tk.StringVar(value="妙蛙种子")
        self.tid_starter_min_adv_var = tk.StringVar(value="1500")
        self.tid_starter_max_adv_var = tk.StringVar(value="10000")
        self.tid_sid_retry_radius_var = tk.StringVar(value="20")
        self.tid_starter_sound_var = tk.StringVar(value="MONO")
        self.tid_starter_button_mode_var = tk.StringVar(value="HELP")
        self.tid_starter_seed_button_var = tk.StringVar(value="A")
        ttk.Checkbutton(
            tid_starter,
            text="TID 阶段完成后继续御三家",
            variable=self.tid_starter_flow_var,
        ).grid(row=0, column=0, columnspan=7, sticky="w", padx=4, pady=4)
        self._help_marker(
            tid_starter,
            "连续御三家流程",
            "穷举模式会使用实际 TID 与 SID ADV；游戏版本沿用上方 TID / SID 基本条件。",
        ).grid(row=0, column=7, sticky="w", padx=4, pady=4)
        self._help_marker(
            tid_starter,
            "御三家游戏版本",
            "游戏版本使用上方 TID / SID 基本条件中的选择。",
            label="?",
        ).grid(row=1, column=0, columnspan=2, sticky="e", padx=4)
        self.tid_starter_combo = self._labeled_combo(
            tid_starter,
            "御三家",
            self.tid_starter_var,
            ("妙蛙种子", "小火龙", "杰尼龟"),
            1,
            2,
        )
        self.tid_starter_min_adv_entry = self._labeled_entry(
            tid_starter, "最低 ADV", self.tid_starter_min_adv_var, 1, 4, width=12
        )
        self.tid_starter_max_adv_entry = self._labeled_entry(
            tid_starter, "最高 ADV", self.tid_starter_max_adv_var, 1, 6, width=12
        )
        starter_settings_label = ttk.Label(
            tid_starter,
            text="御三家游戏设置",
            style="Help.TLabel",
            cursor="question_arrow",
        )
        starter_settings_label.grid(
            row=2, column=0, columnspan=2, sticky="e", padx=4, pady=4
        )
        self._add_tooltip(
            starter_settings_label,
            "御三家游戏设置",
            "这些设置独立于上方 TID 阶段的 Sound、Button Mode 和 Seed Button。",
        )
        self.tid_starter_sound_combo = self._labeled_combo(
            tid_starter, "Sound", self.tid_starter_sound_var,
            ("MONO", "STEREO"), 2, 2,
        )
        self.tid_starter_button_mode_combo = self._labeled_combo(
            tid_starter, "Button Mode", self.tid_starter_button_mode_var,
            ("HELP", "LR", "L=A"), 2, 4,
        )
        self.tid_starter_seed_button_combo = self._labeled_combo(
            tid_starter, "Seed Button", self.tid_starter_seed_button_var,
            ("A", "START", "L(L=A)"), 2, 6,
        )
        self.tid_sid_retry_radius_entry = self._labeled_entry(
            tid_starter, "SID ADV 重试半径", self.tid_sid_retry_radius_var, 3, 0, width=12
        )
        self.tid_any_tid_check = ttk.Checkbutton(
            tid_starter,
            text="取得任意 TID 后继续",
            variable=self.tid_any_tid_var,
            command=self._update_tid_flow_controls,
        )
        self.tid_any_tid_check.grid(row=3, column=2, columnspan=5, sticky="w", padx=4, pady=4)
        self._help_marker(
            tid_starter,
            "任意 TID 接续",
            "开启后忽略目标 TID 与特殊号码条件，首次满足完整性要求的 TID 可接续御三家流程。",
        ).grid(row=3, column=7, sticky="w", padx=4, pady=4)
        self.tid_any_tid_denoise_check = ttk.Checkbutton(
            tid_starter,
            text="任意 TID 仍需去噪确认",
            variable=self.tid_any_tid_denoise_var,
        )
        self.tid_any_tid_denoise_check.grid(row=4, column=2, columnspan=5, sticky="w", padx=4, pady=4)
        self._help_marker(
            tid_starter,
            "任意 TID 去噪",
            "默认开启。关闭后，首个完整识别且数值合法的 TID 会直接接续；缺位或非法识别仍不会放行。",
        ).grid(row=4, column=7, sticky="w", padx=4, pady=4)
        self.tid_starter_flow_controls = (
            self.tid_starter_combo,
            self.tid_starter_min_adv_entry,
            self.tid_starter_max_adv_entry,
            self.tid_sid_retry_radius_entry,
            self.tid_starter_sound_combo,
            self.tid_starter_button_mode_combo,
            self.tid_starter_seed_button_combo,
        )

        tid_filters = ttk.LabelFrame(tid_tab, text="5. 穷举判定与高级范围", padding=8)
        tid_filters.pack(fill="x", pady=(8, 0))
        self.tid_same_id_var = tk.BooleanVar(value=False)
        self.tid_sequential_id_var = tk.BooleanVar(value=False)
        self.tid_65535_var = tk.BooleanVar(value=True)
        self.tid_single_digit_var = tk.BooleanVar(value=False)
        special = ttk.Frame(tid_filters)
        special.grid(row=0, column=0, columnspan=8, sticky="w", padx=4, pady=2)
        self.tid_same_id_check = ttk.Checkbutton(
            special, text="豹子号", variable=self.tid_same_id_var
        )
        self.tid_same_id_check.pack(side="left")
        self.tid_sequential_id_check = ttk.Checkbutton(
            special, text="升/降连号", variable=self.tid_sequential_id_var
        )
        self.tid_sequential_id_check.pack(side="left", padx=10)
        self.tid_65535_check = ttk.Checkbutton(
            special, text="65535", variable=self.tid_65535_var
        )
        self.tid_65535_check.pack(side="left")
        self.tid_single_digit_check = ttk.Checkbutton(
            special, text="个位数 TID", variable=self.tid_single_digit_var
        )
        self.tid_single_digit_check.pack(side="left", padx=10)
        self.tid_special_checks = (
            self.tid_same_id_check,
            self.tid_sequential_id_check,
            self.tid_65535_check,
            self.tid_single_digit_check,
        )
        self.tid_f2_candidate_var = tk.StringVar(value="2000")
        self.tid_f1_candidate_var = tk.StringVar(value="100")
        self.tid_denoise_hit_var = tk.StringVar(value="2")
        self.tid_denoise_window_var = tk.StringVar(value="10")
        self.tid_threshold_var = tk.StringVar(value="95")
        self._labeled_entry(tid_filters, "F2 候选阈值", self.tid_f2_candidate_var, 1, 0, width=12)
        self._labeled_entry(tid_filters, "F1 候选阈值", self.tid_f1_candidate_var, 1, 2, width=12)
        self._labeled_entry(tid_filters, "去噪命中数", self.tid_denoise_hit_var, 1, 4, width=12)
        self._labeled_entry(tid_filters, "去噪窗口", self.tid_denoise_window_var, 1, 6, width=12)
        self._labeled_entry(tid_filters, "识图阈值", self.tid_threshold_var, 2, 0, width=12)

        tid_source = ttk.LabelFrame(tid_tab, text="6. TID 1.3.7 脚本包", padding=8)
        tid_source.pack(fill="x", pady=(8, 0))
        self.tid_source_var = tk.StringVar(value=str(DEFAULT_TID_SOURCE_PATH))
        self._labeled_entry(tid_source, "脚本包", self.tid_source_var, 0, 0, width=70, span=5)
        ttk.Button(tid_source, text="选择", command=self.choose_tid_source).grid(
            row=0, column=6, padx=4
        )

        tid_resume = ttk.LabelFrame(tid_tab, text="7. 参数保存与搜索续跑", padding=8)
        tid_resume.pack(fill="x", pady=(8, 0))
        self.tid_resume_var = tk.BooleanVar(value=True)
        tid_resume_toggle = ttk.Frame(tid_resume)
        tid_resume_toggle.pack(anchor="w", fill="x")
        ttk.Checkbutton(
            tid_resume_toggle, text="继续同参数的上次搜索进度（穷举 / 非零半径乱数）",
            variable=self.tid_resume_var,
        ).pack(side="left")
        self._help_marker(
            tid_resume_toggle,
            "搜索续跑",
            "默认开启，TID 参数会自动保存。取消勾选后，本次从所填起点开始；"
            "打开工具不会自动运行游戏。续跑会重试停止时的当前点并重新去噪，"
            "已命中完成的进度不会继续。",
        ).pack(side="left", padx=(6, 0))
        self.tid_progress_status_var = tk.StringVar(value="尚无本次参数的搜索进度。")
        ttk.Label(tid_resume, textvariable=self.tid_progress_status_var, wraplength=950,
                  justify="left").pack(anchor="w")
        ttk.Button(tid_resume, text="刷新进度", command=self._refresh_tid_progress).pack(anchor="w", pady=4)

        script_test = ttk.LabelFrame(
            self.script_test_tab,
            text="直接运行 ECS 测试脚本",
            padding=10,
        )
        script_test.pack(fill="x")
        self.script_test_path_var = tk.StringVar(value="")
        self.script_test_entry_var = tk.StringVar(value=SCRIPT_TEST_ENTRY_FORMAL)
        self.script_test_entry_status_var = tk.StringVar(value="")
        self.script_test_backend_var = tk.StringVar(value=SCRIPT_TEST_BACKEND_COMPAT)
        self.script_test_verbose_var = tk.BooleanVar(value=False)
        self._labeled_entry(
            script_test,
            "ECS 文件",
            self.script_test_path_var,
            0,
            0,
            width=78,
            span=5,
        )
        ttk.Button(
            script_test,
            text="选择脚本",
            command=self.choose_script_test,
        ).grid(row=0, column=6, padx=4)
        self._labeled_combo(
            script_test,
            "运行后端",
            self.script_test_backend_var,
            SCRIPT_TEST_BACKENDS,
            1,
            0,
            width=42,
            span=3,
        )
        ttk.Checkbutton(
            script_test,
            text="输出 EasyCon 详细日志",
            variable=self.script_test_verbose_var,
        ).grid(row=1, column=5, columnspan=2, sticky="w", padx=4, pady=4)
        self._help_marker(
            script_test,
            "高级脚本测试",
            "所选 ECS 会原地直接执行，不经过方案搜索、参数替换或正式 main.ecs 生成。"
            "兼容后端等同正式工具；原始 CLI 用于 A/B 对照。",
            label="?",
        ).grid(row=2, column=0, sticky="w", padx=4, pady=(8, 4))
        self._help_marker(
            script_test,
            "危险操作",
            "测试脚本拥有完整手柄控制权限。开始前请人工核对脚本内容、游戏位置和存档状态；"
            "同目录的 lib 与 ImgLabel 会被 EasyCon 使用。",
            label="?",
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 0))
        ttk.Label(
            script_test,
            text="运行前必须核对脚本内容、游戏位置和存档状态。",
            foreground="#9a3412",
        ).grid(row=3, column=2, columnspan=5, sticky="w", padx=4, pady=(4, 0))
        ttk.Label(
            script_test,
            textvariable=self.script_test_entry_status_var,
            wraplength=980,
            justify="left",
        ).grid(row=4, column=0, columnspan=7, sticky="w", padx=4, pady=(5, 0))

        runtime = ttk.LabelFrame(container, text="EasyCon 1.6.4-a 与设备", padding=10)
        runtime.pack(fill="x", pady=(0, 10), before=self.mode_notebook)
        self.source_var = tk.StringVar(value=str(DEFAULT_SOURCE_118))
        self.ezcon_var = tk.StringVar(value=str(DEFAULT_EZCON))
        self.port_var = tk.StringVar(value="COM22")
        self.video_var = tk.StringVar(value="0")
        self.source_entry = self._labeled_entry(runtime, SCRIPT_PACKAGE_UI_NAME, self.source_var, 0, 0, width=68, span=5)
        self._add_tooltip(
            self.source_entry,
            "2.0 自动乱数脚本包路径",
            "野生/静态、孵蛋和高级页的正式版/时间轴版入口都从此目录读取。",
        )
        ttk.Button(runtime, text="选择", command=self.choose_source).grid(row=0, column=6, padx=4)
        self.ezcon_entry = self._labeled_entry(runtime, "ezcon.exe", self.ezcon_var, 1, 0, width=68, span=5)
        ttk.Button(runtime, text="选择", command=self.choose_ezcon).grid(row=1, column=6, padx=4)
        ttk.Label(runtime, text="串口").grid(row=2, column=0, sticky="e", padx=4, pady=4)
        self.port_combo = ttk.Combobox(
            runtime,
            textvariable=self.port_var,
            values=(self.port_var.get(),),
            width=12,
            state="readonly",
        )
        self.port_combo.grid(row=2, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(runtime, text="采集卡").grid(row=2, column=2, sticky="e", padx=4, pady=4)
        self.video_combo = ttk.Combobox(
            runtime,
            textvariable=self.video_var,
            values=(self.video_var.get(),),
            width=34,
            state="readonly",
        )
        self.video_combo.grid(
            row=2, column=3, columnspan=3, sticky="w", padx=4, pady=4
        )
        self.video_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._on_capture_device_changed()
        )
        self.device_button = ttk.Button(runtime, text="检测端口/采集卡", command=self.check_devices)
        self.device_button.grid(row=2, column=6, padx=8)
        manual_tools = ttk.Frame(runtime)
        manual_tools.grid(row=3, column=0, columnspan=7, sticky="w", padx=4, pady=(6, 0))
        self.virtual_controller_button = ttk.Button(
            manual_tools,
            text="虚拟手柄",
            command=self.open_virtual_controller,
        )
        self.virtual_controller_button.pack(side="left")
        self._add_tooltip(
            self.virtual_controller_button,
            "虚拟手柄与状态浮窗",
            "连接当前串口并打开键盘虚拟手柄，同时显示采用 EasyCon 原版 VPad 图片的 100×100 置顶状态浮窗。"
            "绿色表示正在发送的按键；浮窗左键唤出控制窗口，右键拖动，中键隐藏。"
            "自动脚本运行期间为避免串口冲突，虚拟手柄不可开启。",
        )
        self.monitor_button = ttk.Button(
            manual_tools,
            text="监视窗口",
            command=self.open_monitor,
        )
        self.monitor_button.pack(side="left", padx=(8, 0))
        self.advanced_mode_var = tk.BooleanVar(value=False)
        self.advanced_mode_check = ttk.Checkbutton(
            manual_tools,
            text="高级模式",
            variable=self.advanced_mode_var,
            command=self._toggle_advanced_mode,
        )
        self.advanced_mode_check.pack(side="left", padx=(18, 0))
        self._add_tooltip(
            self.advanced_mode_check,
            "高级模式",
            "显示直接脚本测试页，并允许修改 Seed 方案、反查扩窗和奇偶调整。开启后，"
            "已登记脚本、标签、EasyCon、OCR 与兼容运行器的指纹不一致只警告；"
            "文件缺失、语法错误和参数非法等硬错误仍会阻止运行。",
        )
        self.home_buffer_adaptive_var = tk.BooleanVar(value=False)
        self.home_buffer_adaptive_check = ttk.Checkbutton(
            manual_tools,
            text="HOME_BUFFER 稳定低分自适应",
            variable=self.home_buffer_adaptive_var,
        )
        self.home_buffer_adaptive_check.pack(side="left", padx=(14, 0))
        self._add_tooltip(
            self.home_buffer_adaptive_check,
            "HOME_BUFFER 稳定低分自适应",
            "作用于 2.0 自动乱数脚本、TID 和 SID，默认关闭。只有同一状态连续稳定命中时才会采用低于 95 的分数。",
        )
        self.seed_update_button = ttk.Button(
            manual_tools,
            text="检查/更新 Seed 表",
            command=self.update_seed_tables,
        )
        self.seed_update_button.pack(side="left", padx=(14, 0))

        seed_options = ttk.Frame(runtime)
        seed_options.grid(row=4, column=0, columnspan=7, sticky="w", padx=4, pady=(2, 0))
        self.seed_calibration_scheme_var = tk.StringVar(value=SEED_CALIBRATION_ORIGINAL)
        ttk.Label(seed_options, text="Seed 校准").pack(side="left", padx=(0, 4))
        self.seed_calibration_scheme_combo = ttk.Combobox(
            seed_options,
            textvariable=self.seed_calibration_scheme_var,
            values=SEED_CALIBRATION_SCHEMES,
            width=35,
            state="disabled",
        )
        self.seed_calibration_scheme_combo.pack(side="left")
        ttk.Label(seed_options, text="Seed 启动").pack(side="left", padx=(10, 4))
        self.seed_startup_scheme_var = tk.StringVar(value=SEED_STARTUP_HOME_BUFFER)
        self.seed_startup_scheme_combo = ttk.Combobox(
            seed_options,
            textvariable=self.seed_startup_scheme_var,
            values=SEED_STARTUP_SCHEMES,
            width=29,
            state="disabled",
        )
        self.seed_startup_scheme_combo.pack(side="left")
        self.script_entry_options = ttk.Frame(seed_options)
        ttk.Label(self.script_entry_options, text="2.0 脚本入口").pack(
            side="left", padx=(0, 4)
        )
        self.script_test_entry_combo = ttk.Combobox(
            self.script_entry_options,
            textvariable=self.script_test_entry_var,
            values=SCRIPT_TEST_ENTRY_CHOICES,
            width=15,
            state="readonly",
        )
        self.script_test_entry_combo.pack(side="left")
        self.script_test_entry_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._on_script_test_entry_change(),
        )
        self._help_marker(
            self.script_entry_options,
            "2.0 脚本入口",
            "正式版脚本使用 NS火叶全自动一键乱数2.0.ecs；时间轴版脚本使用"
            " NS火叶全自动一键乱数2.0-时间轴.ecs。"
            "自选 ECS 保留高级页的任意脚本测试能力。切换模板会自动更新 ECS 文件路径。",
        ).pack(side="left", padx=(6, 0))
        self.seed_scheme_help_marker = self._help_marker(
            seed_options,
            "Seed 高级方案",
            "仅高级模式可修改。关闭高级模式时，野生、静态和御三家固定方案 0；"
            "孵蛋固定方案 2；Seed 启动均恢复方案 0。",
            label="?",
        )
        self.seed_scheme_help_marker.pack(side="left", padx=(6, 0))
        # The selector is an advanced-only control. Start hidden so the
        # initial layout does not briefly expand and then reflow on startup.
        self.script_entry_options.pack_forget()

        runtime_output_options = ttk.Frame(runtime)
        runtime_output_options.grid(
            row=5,
            column=0,
            columnspan=7,
            sticky="w",
            padx=4,
            pady=(3, 0),
        )
        self.output_log_mode_var = tk.StringVar(value=OUTPUT_LOG_DEBUG)
        ttk.Label(runtime_output_options, text="脚本输出日志").pack(
            side="left", padx=(0, 4)
        )
        self.output_log_mode_combo = ttk.Combobox(
            runtime_output_options,
            textvariable=self.output_log_mode_var,
            values=OUTPUT_LOG_MODES,
            width=16,
            state="readonly",
        )
        self.output_log_mode_combo.pack(side="left")
        self._help_marker(
            runtime_output_options,
            "脚本输出日志",
            "精简日志保留运行状态、误差、修正和命中结果；完整调试日志还会输出识图分数、"
            "候选与校准细节。这里只控制生成的 2.0 自动乱数脚本（含孵蛋和御三家阶段），"
            "不会改变执行时序，也不等同于脚本测试页的 EasyCon 详细日志。",
        ).pack(side="left", padx=(6, 0))

        self.advanced_reverse_options = ttk.LabelFrame(
            runtime,
            text="高级反查设置",
            padding=(8, 5),
        )
        self.advanced_reverse_options.grid(
            row=6,
            column=0,
            columnspan=7,
            sticky="w",
            padx=4,
            pady=(4, 0),
        )
        self.frame_parity_scheme_var = tk.StringVar(value=FRAME_PARITY_MENU)
        ttk.Label(self.advanced_reverse_options, text="奇偶调整").grid(
            row=0, column=0, sticky="e", padx=(2, 4), pady=3
        )
        self.frame_parity_scheme_combo = ttk.Combobox(
            self.advanced_reverse_options,
            textvariable=self.frame_parity_scheme_var,
            values=FRAME_PARITY_MODES,
            width=24,
            state="readonly",
        )
        self.frame_parity_scheme_combo.grid(
            row=0, column=1, columnspan=2, sticky="w", padx=(0, 12), pady=3
        )
        ttk.Label(self.advanced_reverse_options, text="扩窗层数").grid(
            row=0, column=3, sticky="e", padx=(2, 4), pady=3
        )
        self.reverse_expansion_layers_var = tk.StringVar(value="3")
        self.reverse_expansion_layers_spin = ttk.Spinbox(
            self.advanced_reverse_options,
            from_=0,
            to=3,
            width=5,
            justify="center",
            textvariable=self.reverse_expansion_layers_var,
        )
        self.reverse_expansion_layers_spin.grid(
            row=0, column=4, sticky="w", padx=(0, 8), pady=3
        )
        self._help_marker(
            self.advanced_reverse_options,
            "反查扩窗与奇偶调整",
            "扩窗只在反查无结果时按层启用；每层填写相对目标中心的 Seed 容差和消耗帧半宽，"
            "0 层表示关闭。窗口越大，反查耗时越长。孵蛋的预校准反查同样使用扩窗设置，"
            "但孵蛋奇偶调整固定使用菜单方案，下面的奇偶选择会被忽略。",
        ).grid(row=0, column=5, sticky="w", padx=(2, 0), pady=3)
        ttk.Label(self.advanced_reverse_options, text="层").grid(
            row=1, column=0, padx=3, pady=(3, 1)
        )
        ttk.Label(self.advanced_reverse_options, text="Seed 容差（±）").grid(
            row=1, column=1, padx=3, pady=(3, 1)
        )
        ttk.Label(self.advanced_reverse_options, text="消耗帧半宽（±）").grid(
            row=1, column=2, padx=3, pady=(3, 1)
        )
        self.reverse_expansion_seed_vars = []
        self.reverse_expansion_frame_vars = []
        self.reverse_expansion_entries = []
        initial_expansion = REVERSE_EXPANSION_FALLBACKS[SCRIPT_TEST_ENTRY_FORMAL]
        for index, (seed_value, frame_value) in enumerate(
            zip(initial_expansion[1], initial_expansion[2]), 1
        ):
            ttk.Label(self.advanced_reverse_options, text=f"第 {index} 层").grid(
                row=index + 1, column=0, padx=3, pady=2
            )
            seed_var = tk.StringVar(value=str(seed_value))
            frame_var = tk.StringVar(value=str(frame_value))
            seed_entry = ttk.Spinbox(
                self.advanced_reverse_options,
                from_=0,
                to=99999,
                width=10,
                justify="center",
                textvariable=seed_var,
            )
            frame_entry = ttk.Spinbox(
                self.advanced_reverse_options,
                from_=0,
                to=999999999,
                width=14,
                justify="center",
                textvariable=frame_var,
            )
            seed_entry.grid(row=index + 1, column=1, padx=3, pady=2)
            frame_entry.grid(row=index + 1, column=2, padx=3, pady=2)
            self.reverse_expansion_seed_vars.append(seed_var)
            self.reverse_expansion_frame_vars.append(frame_var)
            self.reverse_expansion_entries.extend((seed_entry, frame_entry))
        self._reverse_defaults_template = SCRIPT_TEST_ENTRY_FORMAL
        self.advanced_reverse_options.grid_remove()

        precalibration_options = ttk.Frame(runtime)
        precalibration_options.grid(
            row=7,
            column=0,
            columnspan=7,
            sticky="w",
            padx=4,
            pady=(2, 0),
        )
        self.update_precalibration_var = tk.BooleanVar(value=False)
        self.update_precalibration_check = ttk.Checkbutton(
            precalibration_options,
            text="命中后更新预校准",
            variable=self.update_precalibration_var,
        )
        self.update_precalibration_check.pack(side="left")
        self._help_marker(
            precalibration_options,
            "自动更新预校准",
            "默认关闭。完整命中目标后保存本次 Seed 与可用的帧修正；记录按游戏、"
            "Switch 机型、Seed 模式、Seed 启动方案、正式版/时间轴版入口和流程类型隔离。"
            "正式版普通定点只复用 Seed；时间轴版定点及野生、孵蛋、御三家可复用帧修正。"
            "TID 与 SID 阶段不使用这些记录。",
        ).pack(side="left", padx=(6, 0))

        app_update_options = ttk.Frame(runtime)
        app_update_options.grid(
            row=8,
            column=0,
            columnspan=7,
            sticky="w",
            padx=4,
            pady=(5, 0),
        )
        ttk.Label(app_update_options, text=f"程序版本 {APP_VERSION}").pack(side="left")
        self.app_update_button = ttk.Button(
            app_update_options,
            text="检查程序更新",
            command=lambda: self.check_app_update(force=True),
        )
        self.app_update_button.pack(side="left", padx=(10, 0))
        self.app_update_status_var = tk.StringVar(
            value=(
                "尚未检查程序更新。"
                if is_frozen_build()
                else "源码模式不使用程序自更新。"
            )
        )
        ttk.Label(
            app_update_options,
            textvariable=self.app_update_status_var,
            wraplength=690,
        ).pack(side="left", padx=(10, 0))
        self._help_marker(
            app_update_options,
            "整包程序更新",
            "绿色版每天最多自动检查一次稳定版。发现新版后会先询问，完整下载 ZIP 并校验"
            "大小和 SHA-256，再退出程序完成目录交换；失败会恢复旧版。用户配置和日志不在"
            f"程序目录中，不会被替换。旧版可直接升级到 {APP_VERSION}。",
        ).pack(side="left", padx=(6, 0))
        if not is_frozen_build():
            self.app_update_button.configure(state="disabled")

        actions = ttk.Frame(container)
        actions.pack(fill="x", pady=10)
        self.search_button = ttk.Button(actions, text="搜索并生成方案", command=self.search_and_generate)
        self.search_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="取消搜索", command=self.cancel_search, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.start_button = ttk.Button(actions, text="开始运行", command=self.start_run, state="disabled")
        self.start_button.pack(side="left", padx=8)
        self.stop_button = ttk.Button(actions, text="停止 EasyCon", command=self.stop_run, state="disabled")
        self.stop_button.pack(side="left")
        self.status_var = tk.StringVar(value="填写条件后先点击“搜索并生成方案”。")
        ttk.Label(actions, textvariable=self.status_var).pack(side="left", padx=16)

        result_frame = ttk.LabelFrame(container, text="方案与预检结果", padding=8)
        result_frame.pack(fill="both", expand=True)
        self.result_text = tk.Text(result_frame, height=10, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=scrollbar.set)
        self.result_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.mode_notebook.bind("<<NotebookTabChanged>>", self._on_mode_tab_change)
        self.tid_starter_flow_var.trace_add("write", self._on_tid_flow_toggle)
        self._update_tid_flow_controls()
        self._update_tid_shiny_pid_controls()
        self._on_mode_tab_change()
        self.source_var.trace_add("write", self._on_script_test_source_change)
        self.script_test_path_var.trace_add("write", self._on_script_test_path_change)
        self._sync_script_test_entry_path()
        self._sync_reverse_expansion_defaults(force=True)

    def _schedule_page_scrollregion_update(self, _event=None):
        if self._page_scrollregion_job is not None:
            return
        try:
            self._page_scrollregion_job = self.root.after_idle(
                self._update_page_scrollregion
            )
        except tk.TclError:
            self._page_scrollregion_job = None

    def _update_page_scrollregion(self, _event=None):
        self._page_scrollregion_job = None
        try:
            bbox = self.page_canvas.bbox("all")
            if bbox is not None:
                self.page_canvas.configure(scrollregion=bbox)
        except tk.TclError:
            pass

    def _resize_page_content(self, event):
        width = int(event.width)
        if self._page_canvas_width != width:
            self._page_canvas_width = width
            self.page_canvas.itemconfigure(self.page_window, width=width)
        self._schedule_page_scrollregion_update()

    def _on_page_mousewheel(self, event):
        # The result box has its own scrollbar; keep the wheel local while the
        # pointer is over it. Everywhere else, scroll the complete form.
        if event.widget in (self.result_text, self.run_log_text):
            return None
        steps = int(-event.delta / 120)
        if steps == 0:
            steps = -1 if event.delta > 0 else 1
        self.page_canvas.yview_scroll(steps * 3, "units")
        return "break"

    @staticmethod
    def _save_profile_display(profile: SaveProfile) -> str:
        return (
            f"{profile.name}  ·  {profile.game} / {profile.language_name}  ·  "
            f"TID {profile.tid:05d} / SID {profile.sid:05d}  ·  {profile.switch_name}"
        )

    def _refresh_save_profile_selector(self, selected_id: str | None = None) -> None:
        if selected_id is None:
            selected_id = self.profile_store.selected_profile_id
        self.profile_display_to_id = {
            self._save_profile_display(profile): profile.profile_id
            for profile in self.profile_store.profiles
        }
        values = (MANUAL_PROFILE_LABEL, *self.profile_display_to_id)
        self.save_profile_combo.configure(values=values)
        selected = self.profile_store.get(selected_id)
        if selected is None:
            self.save_profile_var.set(MANUAL_PROFILE_LABEL)
            self.save_profile_summary_var.set(
                "手动输入模式"
            )
        else:
            self.save_profile_var.set(self._save_profile_display(selected))
            self.save_profile_summary_var.set(
                f"{selected.game}｜{selected.language_name}｜TID {selected.tid:05d}｜SID {selected.sid:05d}｜{selected.switch_name}"
            )

    def _on_save_profile_selected(self, _event=None) -> None:
        selected_id = self.profile_display_to_id.get(self.save_profile_var.get())
        try:
            profile = self.profile_store.select(selected_id)
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法保存当前存档", str(exc), parent=self.root)
            self._refresh_save_profile_selector()
            return
        if profile is None:
            self.save_profile_summary_var.set(
                "手动输入模式"
            )
            return
        self._apply_save_profile(profile, persist=False)

    def _apply_save_profile(
        self,
        profile: SaveProfile,
        *,
        persist: bool = True,
    ) -> None:
        if persist:
            try:
                self.profile_store.select(profile.profile_id)
            except (OSError, ValueError) as exc:
                messagebox.showerror("无法保存当前存档", str(exc), parent=self.root)
                return
        switch_name = profile.switch_name
        self._updating = True
        try:
            language_var = getattr(self, "tid_language_var", None)
            # SID 查找页使用当前存档的 TID；SID 正是该页要反查的目标。
            self.sid_game_var.set(profile.game)
            self.sid_nx_var.set(switch_name)
            self.sid_tid_var.set(str(profile.tid))

            # 野生/静态与孵蛋页共用这两个版本/主机变量。
            self.game_var.set(profile.game)
            self.nx_var.set(switch_name)
            self.tid_var.set(str(profile.tid))
            self.sid_var.set(str(profile.sid))

            # TID 页的目标身份可以直接来自已登记或计划创建的存档。
            self.tid_game_var.set(profile.game)
            self.tid_nx_var.set(switch_name)
            self.tid_target_var.set(str(profile.tid))
            self.tid_sid_var.set(str(profile.sid))
            if language_var is not None:
                language_var.set(profile.language)
            self._on_game_change()
        finally:
            self._updating = False
        self._refresh_save_profile_selector(profile.profile_id)
        self.invalidate_plan()

    def _current_save_profile_defaults(self) -> dict:
        mode = self.mode_var.get()
        if mode == "sid":
            game = self.sid_game_var.get()
            nx_model = 2 if self.sid_nx_var.get() == "Switch 2" else 1
            tid = self.sid_tid_var.get()
            sid = self.sid_var.get()
        elif mode == "tid":
            game = self.tid_game_var.get()
            nx_model = 2 if self.tid_nx_var.get() == "Switch 2" else 1
            tid = self.tid_target_var.get()
            sid = self.tid_sid_var.get()
        else:
            game = self.game_var.get()
            nx_model = 2 if self.nx_var.get() == "Switch 2" else 1
            tid = self.tid_var.get()
            sid = self.sid_var.get()
        language_variable = getattr(self, "tid_language_var", None)
        language = language_variable.get() if language_variable is not None else "英文"
        return {
            "name": "新存档",
            "game": game,
            "tid": tid,
            "sid": sid,
            "nx_model": nx_model,
            "language": language,
        }

    def _show_save_profile_editor(
        self,
        parent,
        title: str,
        initial: dict,
    ) -> dict | None:
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.resizable(False, False)
        dialog.transient(parent)

        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)
        name_var = tk.StringVar(value=str(initial.get("name", "")))
        game_var = tk.StringVar(value=str(initial.get("game", "火红")))
        tid_var = tk.StringVar(value=str(initial.get("tid", "0")))
        sid_var = tk.StringVar(value=str(initial.get("sid", "0")))
        language_var = tk.StringVar(value=str(initial.get("language", "英文")))
        nx_var = tk.StringVar(
            value=f"Switch {int(initial.get('nx_model', 1))}"
        )

        name_entry = self._labeled_entry(body, "存档名称", name_var, 0, 0, width=28)
        self._labeled_combo(body, "游戏版本", game_var, ("火红", "叶绿"), 1, 0, width=26)
        self._labeled_entry(body, "TID", tid_var, 2, 0, width=28)
        self._labeled_entry(body, "SID", sid_var, 3, 0, width=28)
        self._labeled_combo(
            body,
            "ROM语言/地区",
            language_var,
            ("英文（美版）", "日文（日版）"),
            4,
            0,
            width=26,
        )
        language_display_to_code = {
            "英文（美版）": "英文",
            "日文（日版）": "日文",
        }
        language_var.set(
            "日文（日版）" if language_var.get() == "日文" else "英文（美版）"
        )
        self._labeled_combo(
            body,
            "主机",
            nx_var,
            ("Switch 1", "Switch 2"),
            5,
            0,
            width=26,
        )
        self._help_marker(
            body,
            "存档字段",
            "火红/叶绿没有时钟电池参数；主机字段用于选择对应 NX Seed 表。",
            label="?",
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=4, pady=(8, 2))

        result: dict = {}

        def accept() -> None:
            try:
                validated = SaveProfile.create(
                    name_var.get(),
                    game_var.get(),
                    tid_var.get(),
                    sid_var.get(),
                    2 if nx_var.get() == "Switch 2" else 1,
                    language=language_display_to_code[language_var.get()],
                )
            except ValueError as exc:
                messagebox.showerror("存档信息无效", str(exc), parent=dialog)
                return
            result.update(
                name=validated.name,
                game=validated.game,
                tid=validated.tid,
                sid=validated.sid,
                nx_model=validated.nx_model,
                language=validated.language,
            )
            dialog.destroy()

        buttons = ttk.Frame(body)
        buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="保存", command=accept).pack(side="left")
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(
            side="left", padx=(8, 0)
        )
        dialog.bind("<Return>", lambda _event: accept())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        name_entry.focus_set()
        dialog.grab_set()
        parent.wait_window(dialog)
        return result or None

    def open_save_profile_manager(self) -> None:
        manager = tk.Toplevel(self.root)
        manager.title("管理存档信息")
        manager.geometry("940x390")
        manager.minsize(700, 330)
        manager.transient(self.root)

        body = ttk.Frame(manager, padding=12)
        body.pack(fill="both", expand=True)
        tree = ttk.Treeview(
            body,
            columns=("name", "game", "language", "tid", "sid", "switch"),
            show="headings",
            selectmode="browse",
            height=10,
        )
        headings = (
            ("name", "存档名称", 220),
            ("game", "游戏版本", 90),
            ("language", "版本/地区", 110),
            ("tid", "TID", 90),
            ("sid", "SID", 90),
            ("switch", "主机", 100),
        )
        for column, label, width in headings:
            tree.heading(column, text=label)
            tree.column(column, width=width, anchor="center" if column != "name" else "w")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        def selected_profile() -> SaveProfile | None:
            selection = tree.selection()
            return self.profile_store.get(selection[0]) if selection else None

        def refresh_tree(select_id: str | None = None) -> None:
            for item in tree.get_children():
                tree.delete(item)
            for profile in self.profile_store.profiles:
                tree.insert(
                    "",
                    "end",
                    iid=profile.profile_id,
                    values=(
                        profile.name,
                        profile.game,
                        profile.language_name,
                        f"{profile.tid:05d}",
                        f"{profile.sid:05d}",
                        profile.switch_name,
                    ),
                )
            desired = select_id or self.profile_store.selected_profile_id
            if desired and tree.exists(desired):
                tree.selection_set(desired)
                tree.focus(desired)
                tree.see(desired)

        def add_profile() -> None:
            initial = self._current_save_profile_defaults()
            while True:
                values = self._show_save_profile_editor(manager, "新建存档", initial)
                if values is None:
                    return
                try:
                    profile = self.profile_store.add(**values)
                except (OSError, ValueError) as exc:
                    messagebox.showerror("无法新建存档", str(exc), parent=manager)
                    initial = values
                    continue
                self._apply_save_profile(profile, persist=False)
                refresh_tree(profile.profile_id)
                return

        def edit_profile() -> None:
            current = selected_profile()
            if current is None:
                messagebox.showinfo("编辑存档", "请先选择一个存档。", parent=manager)
                return
            initial = current.to_dict()
            while True:
                values = self._show_save_profile_editor(manager, "编辑存档", initial)
                if values is None:
                    return
                try:
                    updated = self.profile_store.update(current.profile_id, **values)
                except (OSError, ValueError) as exc:
                    messagebox.showerror("无法编辑存档", str(exc), parent=manager)
                    initial = values
                    continue
                self._refresh_save_profile_selector()
                if self.profile_store.selected_profile_id == updated.profile_id:
                    self._apply_save_profile(updated, persist=False)
                refresh_tree(updated.profile_id)
                return

        def duplicate_profile() -> None:
            current = selected_profile()
            if current is None:
                messagebox.showinfo("复制存档", "请先选择一个存档。", parent=manager)
                return
            try:
                duplicate = self.profile_store.duplicate(current.profile_id)
            except (OSError, ValueError) as exc:
                messagebox.showerror("无法复制存档", str(exc), parent=manager)
                return
            self._apply_save_profile(duplicate, persist=False)
            refresh_tree(duplicate.profile_id)

        def delete_profile() -> None:
            current = selected_profile()
            if current is None:
                messagebox.showinfo("删除存档", "请先选择一个存档。", parent=manager)
                return
            if not messagebox.askyesno(
                "删除存档",
                f"确定删除“{current.name}”吗？\n不会删除或修改游戏存档本身。",
                parent=manager,
            ):
                return
            try:
                self.profile_store.delete(current.profile_id)
            except (OSError, ValueError) as exc:
                messagebox.showerror("无法删除存档", str(exc), parent=manager)
                return
            self._refresh_save_profile_selector()
            refresh_tree()

        def select_current() -> None:
            current = selected_profile()
            if current is None:
                messagebox.showinfo("设为当前", "请先选择一个存档。", parent=manager)
                return
            self._apply_save_profile(current)
            refresh_tree(current.profile_id)

        controls = ttk.Frame(body)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(controls, text="新建", command=add_profile).pack(side="left")
        ttk.Button(controls, text="编辑", command=edit_profile).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="复制", command=duplicate_profile).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="删除", command=delete_profile).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="设为当前", command=select_current).pack(side="left", padx=(18, 0))
        ttk.Button(controls, text="完成", command=manager.destroy).pack(side="right")
        self._help_marker(
            controls,
            "存档信息边界",
            "选择存档只填写工具参数，不会读取、写入或删除模拟器或游戏存档。",
            label="?",
        ).pack(side="right", padx=(0, 14))
        tree.bind("<Double-1>", lambda _event: edit_profile())
        manager.protocol("WM_DELETE_WINDOW", manager.destroy)
        refresh_tree()

    def _add_tooltip(self, widget, title: str, text: str, **tooltip_options):
        self._tooltips.append(
            HoverTooltip(widget, title, text, **tooltip_options)
        )
        return widget

    def _help_marker(self, parent, title: str, text: str, *, label: str = "?"):
        marker = ttk.Label(
            parent,
            text=label,
            style="Help.TLabel",
            cursor="question_arrow",
            padding=(6, 2),
        )
        return self._add_tooltip(marker, title, text, delay=120)

    @staticmethod
    def _labeled_entry(parent, label, variable, row, column, width=14, span=1):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="e", padx=(4, 2), pady=4)
        entry = ttk.Entry(parent, textvariable=variable, width=width)
        entry.grid(row=row, column=column + 1, columnspan=span, sticky="we", padx=(2, 8), pady=4)
        return entry

    @staticmethod
    def _labeled_combo(parent, label, variable, values, row, column, width=16, span=1):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="e", padx=(4, 2), pady=4)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, width=width, state="readonly")
        combo.grid(row=row, column=column + 1, columnspan=span, sticky="we", padx=(2, 8), pady=4)
        return combo

    @staticmethod
    def _egg_parent_row(parent, row, gender_var, gender_values, iv_vars):
        ttk.Combobox(
            parent, textvariable=gender_var, values=gender_values,
            width=8, state="readonly",
        ).grid(row=row, column=1, padx=3, pady=3)
        for index, variable in enumerate(iv_vars, 2):
            ttk.Spinbox(
                parent, from_=0, to=31, width=5, justify="center", textvariable=variable,
            ).grid(row=row, column=index, padx=3, pady=3)

    def _install_invalidation(self):
        self.tracked_variables = (
            self.mode_var, self.game_var, self.nx_var, self.tid_var, self.sid_var, self.method_var,
            self.category_var, self.location_var, self.pokemon_var,
            *self.iv_min_vars, *self.iv_max_vars,
            self.search_mode_var, self.direct_seed_var, self.direct_adv_var,
            self.min_adv_var, self.max_adv_var, self.shiny_var, self.nature_var,
            self.gender_var, self.ability_var, self.hidden_type_var, self.seed_mode_var,
            self.auto_capture_var, self.paralysis_var, self.false_swipe_var,
            self.item_rng_mode_var, self.party_empty_slots_var,
            self.sid_traversal_var, self.sid_traversal_max_adv_var,
            self.sid_traversal_start_adv_var,
            self.home_buffer_adaptive_var, self.seed_calibration_scheme_var,
            self.seed_startup_scheme_var, self.update_precalibration_var,
            self.output_log_mode_var, self.frame_parity_scheme_var,
            self.reverse_expansion_layers_var,
            *self.reverse_expansion_seed_vars,
            *self.reverse_expansion_frame_vars,
            self.source_var, self.ezcon_var, self.video_var,
            self.egg_seed_var, self.egg_held_var, self.egg_pickup_var,
            self.egg_seed_mode_var, self.egg_pokemon_var, self.egg_compatibility_var,
            self.egg_start_mode_var,
            self.egg_parent_a_gender_var, self.egg_parent_b_gender_var,
            *self.egg_parent_a_iv_vars, *self.egg_parent_b_iv_vars,
            self.egg_ack_var,
            self.tid_language_var, self.tid_mode_var, self.tid_nx_var,
            self.tid_gender_var, self.tid_target_var, self.tid_sid_var,
            self.tid_shiny_pid_var,
            self.tid_name_var, self.tid_sid_mode_var,
            self.tid_calibration_var,
            self.tid_op_target_var, self.tid_f1_target_var, self.tid_f2_target_var,
            self.tid_op_rng_range_var, self.tid_f1_rng_range_var, self.tid_f2_rng_range_var,
            self.tid_additional_targets_var, self.tid_auto_rng_var,
            self.tid_near_distance_var, self.tid_near_hits_var,
            self.tid_auto_op_range_var, self.tid_auto_f1_range_var, self.tid_auto_f2_range_var,
            self.tid_op_start_var, self.tid_f1_start_var, self.tid_f2_start_var,
            self.tid_op_max_range_var, self.tid_f1_max_range_var, self.tid_f2_max_range_var,
            self.tid_sound_var, self.tid_button_mode_var, self.tid_seed_button_var,
            self.tid_name_entry_var, self.tid_op_delay_var, self.tid_f1_delay_var,
            self.tid_f2_delay_var, self.tid_f3_delay_var, self.tid_close_delay_var,
            self.tid_home_buffer_var, self.tid_op_correction_var,
            self.tid_sid_adv_correction_var, self.tid_select_correction_var,
            self.tid_same_id_var, self.tid_sequential_id_var, self.tid_65535_var,
            self.tid_single_digit_var, self.tid_f2_candidate_var,
            self.tid_f1_candidate_var, self.tid_denoise_hit_var,
            self.tid_denoise_window_var, self.tid_threshold_var, self.tid_source_var,
            self.tid_starter_flow_var, self.tid_game_var, self.tid_starter_var,
            self.tid_starter_min_adv_var, self.tid_starter_max_adv_var,
            self.tid_sid_retry_radius_var,
            self.tid_starter_sound_var, self.tid_starter_button_mode_var,
            self.tid_starter_seed_button_var,
            self.tid_any_tid_var,
            self.tid_any_tid_denoise_var,
            self.sid_game_var, self.sid_nx_var, self.sid_tid_var, self.sid_count_var,
            self.sid_candies_var, self.sid_threshold_var, self.sid_ack_var,
            *self.sid_species_vars, *self.sid_initial_level_vars,
            *self.sid_source_type_vars,
            *self.sid_location_vars,
            *(variable for row in self.sid_effort_vars for variable in row),
            self.sid_source_var,
            self.script_test_entry_var, self.script_test_path_var,
            self.script_test_backend_var,
            self.script_test_verbose_var,
        )
        for variable in self.tracked_variables:
            variable.trace_add("write", self.invalidate_plan)
        self._update_search_mode_controls()

    def _refresh_sid_party_rows(self, *_):
        try:
            active_count = int(self.sid_count_var.get())
        except ValueError:
            active_count = 0
        for index, row in enumerate(self.sid_party_row_widgets):
            enabled = index < active_count
            for widget, enabled_state in row:
                widget.configure(state=enabled_state if enabled else "disabled")

    def apply_iv_preset(self, preset):
        ranges = iv_ranges_for_preset(preset)
        self._set_iv_ranges(ranges)

    def reset_iv_stat(self, index):
        if not 0 <= index < len(IV_STAT_LABELS):
            raise IndexError(index)
        ranges = [
            (minimum.get(), maximum.get())
            for minimum, maximum in zip(self.iv_min_vars, self.iv_max_vars)
        ]
        ranges[index] = (0, 31)
        self._set_iv_ranges(ranges)

    def _set_iv_ranges(self, ranges):
        self._updating = True
        try:
            for minimum_var, maximum_var, (minimum, maximum) in zip(
                self.iv_min_vars, self.iv_max_vars, ranges
            ):
                minimum_var.set(str(minimum))
                maximum_var.set(str(maximum))
        finally:
            self._updating = False
        self.invalidate_plan()

    def input_fingerprint(self):
        return tuple(str(variable.get()) for variable in self.tracked_variables)

    def _tid_setting_variables(self):
        return {
            name: variable for name, variable in vars(self).items()
            if (name.startswith("tid_") and name.endswith("_var")
                and not name.startswith("tid_record_") and name != "tid_progress_status_var"
                or name == "home_buffer_adaptive_var")
            and isinstance(variable, (tk.StringVar, tk.BooleanVar))
        }

    def _tid_settings_fingerprint(self):
        return {name: variable.get() for name, variable in self._tid_setting_variables().items()}

    def _install_tid_persistence(self):
        self._tid_save_job = None
        self._tid_pending_job = None
        self._tid_settings_blocked = False
        self._tid_pending_calibration = None
        try:
            saved = load_tid_settings(TID_SETTINGS_PATH)
            variables = self._tid_setting_variables()
            # Check all known types first: no half-applied drafts.
            for name, value in saved.get("values", {}).items():
                if name in variables and type(value) is not type(variables[name].get()):
                    raise ValueError(f"TID 参数“{name}”类型无效，原文件保留")
            self._updating = True
            try:
                for name, value in saved.get("values", {}).items():
                    if name in variables:
                        variables[name].set(value)
            finally:
                self._updating = False
            self._update_tid_flow_controls()
            self._tid_pending_calibration = saved.get("pending_calibration")
            self._restore_pending_tid_calibration()
        except (ValueError, OSError, tk.TclError, KeyError, TypeError) as exc:
            self._tid_settings_blocked = True
            self.tid_progress_status_var.set(str(exc) + "；未覆盖原参数文件。")
        for variable in self._tid_setting_variables().values():
            variable.trace_add("write", self._schedule_tid_settings_save)
        if not self._tid_settings_blocked:
            self._refresh_tid_progress()
            self._tid_pending_job = self.root.after(1000, self._poll_pending_tid_settings)

    def _poll_pending_tid_settings(self):
        self._tid_pending_job = None
        if self._tid_pending_calibration and not self._process_running():
            try:
                self._restore_pending_tid_calibration()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.tid_progress_status_var.set(f"后台固定延迟结果未回填：{exc}")
                self._tid_pending_calibration = None
        if self._tid_pending_calibration:
            self._tid_pending_job = self.root.after(1000, self._poll_pending_tid_settings)

    def _schedule_tid_settings_save(self, *_):
        if self._tid_save_job is not None:
            self.root.after_cancel(self._tid_save_job)
        self._tid_save_job = self.root.after(500, self._save_tid_settings)

    def _save_tid_settings(self):
        if self._tid_save_job is not None:
            self.root.after_cancel(self._tid_save_job)
        self._tid_save_job = None
        if self._tid_settings_blocked:
            return
        try:
            write_json_atomic(TID_SETTINGS_PATH, {
                "schema": 1, "values": self._tid_settings_fingerprint(),
                "pending_calibration": self._tid_pending_calibration,
            })
            self._refresh_tid_progress()
        except OSError as exc:
            self.tid_progress_status_var.set(f"TID 参数保存失败：{exc}")

    def _restore_pending_tid_calibration(self):
        pending = self._tid_pending_calibration
        if not isinstance(pending, dict) or pending.get("values") != self._tid_settings_fingerprint():
            self._tid_pending_calibration = None
            return
        path = Path(pending.get("path", ""))
        if not path.is_file():
            return
        from automation.tid_calibration import tid_request_from_dict
        self.tid_calibration_result_path = path
        self.tid_calibration_snapshot = tid_request_from_dict(pending["request"])
        self.tid_calibration_input_fingerprint = self.input_fingerprint()
        self.tid_calibration_applied = False
        self._poll_tid_calibration_result()

    def _refresh_tid_progress(self):
        try:
            request = replace(self.collect_tid_request(), calibration_check=False)
            if not progress_supported(request):
                self.tid_progress_status_var.set("乱数半径全为0：重复同一个参数点，无需恢复搜索位置；参数仍会自动保存。")
                return
            flow = self.collect_tid_starter_flow_request(request)
            if flow is not None:
                request = flow.to_flow_tid_request()
            template = resolve_tid_template(self.tid_source_var.get(), request.language)
            flow_payload = {**asdict(flow), "tid_request": flow.tid_request.to_dict()} if flow else None
            context = progress_context(request, self.tid_game_var.get(),
                hashlib.sha256(template.read_bytes()).hexdigest(), flow_payload)
            saved = read_progress(TID_PROGRESS_DIR, context)
            if flow is not None and not flow.deferred_identity:
                from rng.starter_sid_verification import sid_advance_scan_offsets
                contexts = [progress_context(
                    replace(request, sid_advance_correction=request.sid_advance_correction + offset),
                    self.tid_game_var.get(), context["template_sha256"], flow_payload,
                ) for offset in sid_advance_scan_offsets(flow.sid_retry_radius)]
                latest = latest_progress(TID_PROGRESS_DIR, contexts)
                if latest is not None:
                    saved = latest[1]
            if not saved or saved.get("state") is None:
                text = "当前游戏、机型、参数及脚本版本没有可续跑的检查点，将从所填起点开始。"
            else:
                state = saved["state"]
                status = "已命中完成；下次重新开始" if saved["status"] == "completed" else "可续跑（若后台仍在运行，须先停止）"
                if state.get("MODE", 0) == 1:
                    text = (f"{status}：{'穷举自动转乱数' if state['SWITCHED'] else '乱数'}，目标TID {state['TARGET']:05d}，"
                            f"中心OP/F1/F2 {state['OP_CENTER']}/{state['F1_CENTER']}/{state['F2_CENTER']}，"
                            "偏移范围OP/F1/F2 " + "/".join(
                                f"[-{state.get(a + '_NEG', state[a + '_RANGE'])},+{state[a + '_RANGE']}]" for a in ("OP", "F1", "F2")) + "，"
                            f"当前壳层 ±{state['RADIUS']}，累计 {state['COUNT']} 次。")
                    if flow is not None and not flow.deferred_identity:
                        correction = saved.get("context", context)["request"]["sid_advance_correction"]
                        text += f" 当前SID ADV修正 {correction:+d}。"
                else:
                    text = (f"{status}：穷举层级 {state['STAGE']}，OP/F1/F2偏移 "
                            f"{state['OP']}/{state['F1']}/{state['F2']}，累计 {state['COUNT']} 次。")
                if "COMPLETED_REGIONS" in state and request.auto_rng:
                    text += f" 已完成局部区域 {state['COMPLETED_REGIONS']} 个（记住最近16个）。"
            self.tid_progress_status_var.set(text)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.tid_progress_status_var.set(f"暂不能匹配搜索进度：{exc}")

    def invalidate_plan(self, *_):
        if self._updating:
            return
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        self.project_main = None
        self.runtime_check = None
        self.start_button.configure(state="disabled")
        if self.process is None or self.process.poll() is not None:
            self.status_var.set("输入已变化，请重新搜索并生成方案。")

    def _populate_categories(self):
        categories = WILD_CATEGORIES if self.method_var.get() == "野生" else PLANNER_STATIC_CATEGORIES
        self.category_map = {
            f"{CATEGORY_EN_TO_ZH.get(category, category)} ({category})": category
            for category in categories
        }
        self._updating = True
        try:
            self.category_combo.configure(values=list(self.category_map))
            preferred = "草丛 (Grass)" if self.method_var.get() == "野生" else None
            self.category_var.set(preferred if preferred in self.category_map else next(iter(self.category_map), ""))
        finally:
            self._updating = False
        self._populate_locations()

    def _populate_locations(self):
        category = self.category_map.get(self.category_var.get(), "")
        if self.method_var.get() == "静态":
            locations = [category] if category else []
        else:
            locations = self.all_locations.get(category, [])
        if self.method_var.get() == "静态":
            self.location_map = {
                f"{CATEGORY_EN_TO_ZH.get(item, item)} ({item})": item
                for item in locations
            }
        else:
            self.location_map = {f"{location_to_zh(item)} ({item})": item for item in locations}
        self._updating = True
        try:
            self.location_combo.configure(values=list(self.location_map))
            preferred = next((key for key, value in self.location_map.items() if value == "Viridian Forest"), None)
            self.location_var.set(preferred or next(iter(self.location_map), ""))
        finally:
            self._updating = False
        self._populate_pokemon()

    def _game_code(self):
        prefix = "fr" if self.game_var.get() == "火红" else "lg"
        return f"{prefix}_nx2" if self.nx_var.get() == "Switch 2" else f"{prefix}_nx"

    def _populate_pokemon(self):
        category = self.category_map.get(self.category_var.get(), "")
        location = self.location_map.get(self.location_var.get(), category)
        if self.method_var.get() == "静态":
            names = get_static_targets(self._game_code(), category)
        elif category and location:
            ids = get_encounter_species_list(location, category, self._game_code())
            names = [get_species_name(species_id) for species_id in ids]
        else:
            names = []
        names = list(dict.fromkeys(names))
        self.pokemon_map = {
            f"{SPECIES_EN_TO_ZH.get(name, name)} ({name})": name
            for name in names
        }
        self._updating = True
        try:
            self.pokemon_combo.configure(values=list(self.pokemon_map))
            preferred = next((key for key, value in self.pokemon_map.items() if value == "Pikachu"), None)
            self.pokemon_var.set(preferred or next(iter(self.pokemon_map), ""))
        finally:
            self._updating = False
        self._populate_abilities()

    def _on_game_change(self):
        self._populate_seed_modes()
        self._populate_pokemon()
        self._populate_egg_pokemon()

    def _on_method_change(self):
        self._populate_categories()
        self._update_item_rng_controls()

    def _update_item_rng_controls(self):
        """Limit wild-only modes and keep item/SID traversal mutually exclusive."""
        is_wild = self.method_var.get() == "野生"
        item_var = getattr(self, "item_rng_mode_var", None)
        traversal_var = getattr(self, "sid_traversal_var", None)
        item_enabled = bool(item_var is not None and item_var.get())
        traversal_enabled = bool(traversal_var is not None and traversal_var.get())
        if not is_wild and (item_enabled or traversal_enabled):
            self._updating = True
            try:
                if item_var is not None:
                    item_var.set(False)
                if traversal_var is not None:
                    traversal_var.set(False)
            finally:
                self._updating = False
        if is_wild and item_enabled and traversal_enabled:
            # A traversal must stop on a shiny marker, while item mode keeps
            # scanning held-item outcomes; accepting both would make the
            # worker unable to classify a candidate safely.
            self._updating = True
            try:
                item_var.set(False)
            finally:
                self._updating = False
        item_enabled = is_wild and bool(item_var is not None and item_var.get())
        traversal_enabled = is_wild and bool(
            traversal_var is not None and traversal_var.get()
        )
        item_check = getattr(self, "item_rng_mode_check", None)
        if item_check is not None:
            item_check.configure(state="normal" if is_wild else "disabled")
        traversal_check = getattr(self, "sid_traversal_check", None)
        if traversal_check is not None:
            traversal_check.configure(
                state="normal" if is_wild and not item_enabled else "disabled"
            )
        party_slots = getattr(self, "party_empty_slots_spin", None)
        if party_slots is not None:
            party_slots.configure(state="normal" if item_enabled else "disabled")
        max_adv = getattr(self, "sid_traversal_max_adv_spin", None)
        if max_adv is not None:
            max_adv.configure(state="normal" if traversal_enabled else "disabled")
        start_entry = getattr(self, "sid_traversal_start_adv_entry", None)
        if start_entry is not None:
            start_entry.configure(
                state=(
                    "normal"
                    if traversal_enabled
                    and bool(
                        getattr(
                            getattr(self, "advanced_mode_var", None),
                            "get",
                            lambda: False,
                        )()
                    )
                    else "disabled"
                )
            )

    def _sid_traversal_start_override(self) -> int | None:
        """Parse the advanced-only manual SID traversal start, if present."""
        text = self.sid_traversal_start_adv_var.get().strip()
        if not text or not self.advanced_mode_var.get():
            return None
        try:
            value = int(text)
        except ValueError as exc:
            raise ValueError("SID 遍历的自定义起点必须是整数") from exc
        if not 0 <= value <= 65535:
            raise ValueError("SID 遍历的自定义起点必须在 0–65535 之间")
        return value

    def _ask_sid_traversal_confirmation(self, request: AutoSearchRequest) -> bool | None:
        """Confirm identity inputs before a destructive SID traversal run."""
        if not messagebox.askyesno(
            "确认 TID",
            f"当前填写的 TID 是 {request.tid:05d}。请确认它与游戏内 TID 完全一致，是否继续？",
        ):
            return None
        override = self._sid_traversal_start_override()
        start_hint = (
            f"当前高级起点为 ADV {override}，会覆盖默认起点；仍必须匹配本次路线的奇偶。"
            if override is not None
            else "选择“是”从 ADV 1900 开始并只遍历偶数；选择“否”从 ADV 1901 开始并只遍历奇数。"
        )
        return messagebox.askyesno(
            "劲敌名称",
            "开始 SID 遍历前，请确认是否给劲敌取名。\n\n"
            + start_hint
            + "\n劲敌名称决定 SID 计算分支和 ADV 奇偶；已填写的高级起点优先。是否给劲敌取名？",
        )

    def _sid_traversal_progress_text(self, context: dict | None) -> str:
        if context is None:
            return "尚无 SID 遍历断点；生成后会显示保存的起点。"
        path = sid_traversal_progress_path(SID_TRAVERSAL_PROGRESS_DIR, context)
        try:
            payload = read_sid_traversal_progress(SID_TRAVERSAL_PROGRESS_DIR, context)
        except ValueError as exc:
            return f"断点读取失败（原文件保留）：{exc}"
        if payload is None:
            return (
                f"无既有断点，将从 ADV {context['start_sid_advance']} 开始；"
                f"断点：{path}"
            )
        state = payload["state"]
        status = payload.get("status", state.get("status"))
        if status == "completed":
            detail = f"已确认出闪 ADV {state.get('hit_sid_advance')} / SID {state.get('hit_sid')}"
        elif status == "exhausted":
            detail = f"已遍历到上限 {context['max_advances']}，未发现闪光"
        elif state.get("current_sid_advance") is not None:
            detail = (
                f"将重试当前 ADV {state['current_sid_advance']} / SID "
                f"{state.get('current_sid')}"
            )
        else:
            detail = f"下次从 ADV {state.get('next_sid_advance')} 继续"
        return f"SID 遍历断点：{detail}；尝试 {state.get('attempt_count', 0)} 次；文件：{path}"

    @staticmethod
    def _sid_traversal_report_text(path: Path | None) -> tuple[str, str | None]:
        """Render the worker report and return its terminal status, if readable."""
        if path is None or not path.is_file():
            return "", None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return f"SID 遍历报告读取失败：{exc}\n报告文件：{path}", None
        if not isinstance(payload, dict):
            return f"SID 遍历报告格式无效\n报告文件：{path}", None
        context = payload.get("context")
        state = payload.get("state")
        status = payload.get("status")
        lines = ["SID 遍历运行报告", f"状态：{status or '未知'}"]
        if isinstance(context, dict):
            lines.append(
                f"起点/上限：ADV {context.get('start_sid_advance', '?')}"
                f"-{context.get('max_advances', '?')}；低帧搜索上限："
                f"{context.get('target_max_advances', '?')}"
            )
        if isinstance(state, dict):
            current = state.get("current_sid_advance")
            if current is not None:
                lines.append(
                    f"当前候选：ADV {current} / SID {state.get('current_sid', '?')}"
                )
            elif state.get("next_sid_advance") is not None:
                lines.append(f"下一起点：ADV {state.get('next_sid_advance')}")
            if state.get("hit_sid") is not None:
                lines.append(
                    f"确认 SID：{state.get('hit_sid')}（ADV {state.get('hit_sid_advance')}）"
                )
            lines.append(f"尝试次数：{state.get('attempt_count', 0)}")
        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            lines.append(f"本次候选数：{len(candidates)}")
        lines.append(f"报告文件：{path}")
        return "\n".join(lines), str(status) if status is not None else None

    def _is_egg_mode(self):
        return self.mode_var.get() == "egg"

    def _is_tid_mode(self):
        return self.mode_var.get() == "tid"

    def _is_sid_mode(self):
        return self.mode_var.get() == "sid"

    def _is_script_test_mode(self):
        return self.mode_var.get() == "script_test"

    def _seed_options_are_advanced(self) -> bool:
        return bool(getattr(self, "advanced_mode_var", None) and self.advanced_mode_var.get())

    def _selected_seed_startup_scheme(self) -> int:
        """Return the GUI-selected startup path, or the audited default."""
        return SEED_STARTUP_SCHEME_CODES[self.seed_startup_scheme_var.get()]

    def _selected_generation_template_name(self) -> str:
        """Return the audited 2.0 entry selected for generated projects."""
        selection = self.script_test_entry_var.get()
        if selection == SCRIPT_TEST_ENTRY_FORMAL:
            return STANDARD_TEMPLATE_NAME
        if selection == SCRIPT_TEST_ENTRY_TIMELINE:
            return EGG_TEMPLATE_NAME
        raise ValueError("自选 ECS 仅用于直接脚本测试；自动生成请选择正式版或时间轴版")

    def _selected_seed_calibration_scheme(self, *, egg: bool) -> int:
        """Return the selected calibration path with page-specific defaults."""
        code = SEED_CALIBRATION_SCHEME_CODES[self.seed_calibration_scheme_var.get()]
        if not egg and code == 2:
            raise ValueError("正式版 Seed 校准只能选择方案 0 或方案 1")
        return code

    def _selected_output_log_mode(self) -> int:
        try:
            return OUTPUT_LOG_MODE_CODES[self.output_log_mode_var.get()]
        except KeyError as exc:
            raise ValueError("请选择有效的脚本输出日志模式") from exc

    def _selected_frame_parity_scheme(self, *, egg: bool) -> int:
        if egg or not self._seed_options_are_advanced():
            return 1
        try:
            return FRAME_PARITY_MODE_CODES[self.frame_parity_scheme_var.get()]
        except KeyError as exc:
            raise ValueError("请选择有效的奇偶调整方案") from exc

    def _selected_reverse_expansion(self):
        """Return explicit advanced overrides, or template-owned defaults."""
        if not self._seed_options_are_advanced():
            return None, None, None
        try:
            layers = int(self.reverse_expansion_layers_var.get())
            seeds = tuple(int(variable.get()) for variable in self.reverse_expansion_seed_vars)
            frames = tuple(int(variable.get()) for variable in self.reverse_expansion_frame_vars)
        except ValueError as exc:
            raise ValueError("反查扩窗层数、Seed 容差和帧半宽必须是整数") from exc
        if not 0 <= layers <= 3:
            raise ValueError("反查扩窗层数必须在 0–3 之间")
        if any(value < 0 for value in seeds):
            raise ValueError("反查扩窗 Seed 容差不能为负数")
        if any(value < 0 for value in frames):
            raise ValueError("反查扩窗帧半宽不能为负数")
        return layers, seeds, frames

    def _read_reverse_expansion_defaults(self, entry: str):
        fallback = REVERSE_EXPANSION_FALLBACKS.get(
            entry,
            REVERSE_EXPANSION_FALLBACKS[SCRIPT_TEST_ENTRY_FORMAL],
        )
        if entry not in {SCRIPT_TEST_ENTRY_FORMAL, SCRIPT_TEST_ENTRY_TIMELINE}:
            return fallback
        template_name = (
            STANDARD_TEMPLATE_NAME
            if entry == SCRIPT_TEST_ENTRY_FORMAL
            else EGG_TEMPLATE_NAME
        )
        path = Path(self.source_var.get()) / template_name
        try:
            text = path.read_text(encoding="utf-8-sig")
            names = ["扩窗层数上限"]
            names.extend(
                item
                for index in range(1, 4)
                for item in (f"扩窗第{index}层Seed容差", f"扩窗第{index}层帧半宽")
            )
            values = []
            for name in names:
                matches = re.findall(
                    rf"(?m)^\s*\${re.escape(name)}\s*=\s*([0-9]+)\s*$",
                    text,
                )
                if len(matches) != 1:
                    return fallback
                values.append(int(matches[0]))
            return values[0], tuple(values[1::2]), tuple(values[2::2])
        except (OSError, UnicodeError):
            return fallback

    def _sync_reverse_expansion_defaults(self, *, force: bool = False) -> None:
        entry = self.script_test_entry_var.get()
        if entry not in {SCRIPT_TEST_ENTRY_FORMAL, SCRIPT_TEST_ENTRY_TIMELINE}:
            return
        defaults = self._read_reverse_expansion_defaults(entry)
        previous = getattr(self, "_reverse_defaults_values", None)
        try:
            current = (
                int(self.reverse_expansion_layers_var.get()),
                tuple(int(variable.get()) for variable in self.reverse_expansion_seed_vars),
                tuple(int(variable.get()) for variable in self.reverse_expansion_frame_vars),
            )
        except ValueError:
            current = None
        if force or previous is None or current == previous:
            updating = self._updating
            self._updating = True
            try:
                self.reverse_expansion_layers_var.set(str(defaults[0]))
                for variable, value in zip(self.reverse_expansion_seed_vars, defaults[1]):
                    variable.set(str(value))
                for variable, value in zip(self.reverse_expansion_frame_vars, defaults[2]):
                    variable.set(str(value))
            finally:
                self._updating = updating
        self._reverse_defaults_values = defaults
        self._reverse_defaults_template = entry

    def _update_advanced_runtime_controls(self) -> None:
        frame = getattr(self, "advanced_reverse_options", None)
        if frame is None:
            return
        mode = self.mode_var.get()
        applies = mode in {"normal", "egg"} or (
            mode == "tid" and self.tid_starter_flow_var.get()
        )
        if self._seed_options_are_advanced() and applies:
            frame.grid()
        else:
            frame.grid_remove()
        process = getattr(self, "process", None)
        editable = not getattr(self, "busy", False) and not (
            process is not None and process.poll() is None
        )
        parity = getattr(self, "frame_parity_scheme_combo", None)
        if parity is not None:
            if mode == "egg":
                updating = self._updating
                self._updating = True
                try:
                    self.frame_parity_scheme_var.set(FRAME_PARITY_MENU)
                finally:
                    self._updating = updating
                parity.configure(state="disabled")
            else:
                parity.configure(state="readonly" if editable else "disabled")
        layer_spin = getattr(self, "reverse_expansion_layers_spin", None)
        if layer_spin is not None:
            layer_spin.configure(state="normal" if editable else "disabled")
        for entry in getattr(self, "reverse_expansion_entries", ()):
            entry.configure(state="normal" if editable else "disabled")

    def _update_seed_scheme_controls(self) -> None:
        """Keep advanced Seed choices valid for the active 2.0 entry."""
        combo = getattr(self, "seed_calibration_scheme_combo", None)
        startup_combo = getattr(self, "seed_startup_scheme_combo", None)
        calibration_var = getattr(self, "seed_calibration_scheme_var", None)
        startup_var = getattr(self, "seed_startup_scheme_var", None)
        if (
            combo is None
            or startup_combo is None
            or calibration_var is None
            or startup_var is None
        ):
            return
        is_egg = self.mode_var.get() == "egg"
        values = SEED_CALIBRATION_SCHEMES if is_egg else SEED_CALIBRATION_SCHEMES[:2]
        combo.configure(values=values)
        advanced = self._seed_options_are_advanced()
        if not advanced:
            desired = SEED_CALIBRATION_CONTINUATION if is_egg else SEED_CALIBRATION_ORIGINAL
            if (
                calibration_var.get() != desired
                or startup_var.get() != SEED_STARTUP_HOME_BUFFER
            ):
                updating = getattr(self, "_updating", False)
                self._updating = True
                try:
                    if calibration_var.get() != desired:
                        calibration_var.set(desired)
                    if startup_var.get() != SEED_STARTUP_HOME_BUFFER:
                        startup_var.set(SEED_STARTUP_HOME_BUFFER)
                finally:
                    self._updating = updating
        elif calibration_var.get() not in values:
            updating = getattr(self, "_updating", False)
            self._updating = True
            try:
                calibration_var.set(values[0])
            finally:
                self._updating = updating
        state = "readonly" if advanced else "disabled"
        combo.configure(state=state)
        startup_combo.configure(state=state)
        entry_combo = getattr(self, "script_test_entry_combo", None)
        entry_var = getattr(self, "script_test_entry_var", None)
        if entry_combo is not None and entry_var is not None:
            entry_choices = (
                SCRIPT_TEST_ENTRY_CHOICES
                if self._is_script_test_mode()
                else (SCRIPT_TEST_ENTRY_FORMAL, SCRIPT_TEST_ENTRY_TIMELINE)
            )
            entry_combo.configure(values=entry_choices)
            if not advanced or entry_var.get() not in entry_choices:
                # Tk variable traces treat setting the same value as a write.
                # Avoid invalidating a freshly generated plan during the
                # busy-state refresh that runs immediately after generation.
                if entry_var.get() != SCRIPT_TEST_ENTRY_FORMAL:
                    updating = getattr(self, "_updating", False)
                    self._updating = True
                    try:
                        entry_var.set(SCRIPT_TEST_ENTRY_FORMAL)
                        self._sync_script_test_entry_path()
                    finally:
                        self._updating = updating
        entry_options = getattr(self, "script_entry_options", None)
        if entry_options is not None:
            if advanced:
                entry_options.pack(
                    side="left",
                    padx=(8, 0),
                    before=getattr(self, "seed_scheme_help_marker", None),
                )
            else:
                entry_options.pack_forget()
        update_advanced = getattr(self, "_update_advanced_runtime_controls", None)
        if callable(update_advanced):
            update_advanced()

    def _toggle_advanced_mode(self):
        if self.busy or self._process_running():
            self._updating = True
            try:
                self.advanced_mode_var.set(not self.advanced_mode_var.get())
            finally:
                self._updating = False
            return
        if self.advanced_mode_var.get():
            self.mode_notebook.insert(
                self.run_log_tab,
                self.script_test_tab,
                text=ADVANCED_TAB_LABEL,
            )
            self.mode_notebook.select(self.script_test_tab)
        else:
            if self._is_script_test_mode():
                normal_tab = next(
                    tab for tab, mode in self.tab_modes.items() if mode == "normal"
                )
                self.mode_notebook.select(normal_tab)
            self.mode_notebook.hide(self.script_test_tab)
        self._update_seed_scheme_controls()
        self._update_tid_shiny_pid_controls()
        self._update_item_rng_controls()
        self._update_advanced_runtime_controls()
        self._schedule_page_scrollregion_update()
        # Advanced mode changes which Seed/entry settings are effective.  The
        # normalization above is protected from Tk traces, so invalidate once
        # here for the actual user action instead of relying on incidental
        # variable writes.
        self.invalidate_plan()

    def _on_mode_tab_change(self, _event=None):
        mode = self.tab_modes.get(self.mode_notebook.select(), "normal")
        if mode == "tid_records":
            self.refresh_tid_records()
            self._schedule_page_scrollregion_update()
            return
        if mode == "log":
            if not self.busy and not self._process_running():
                self.status_var.set("运行日志页会保留当前或最近一次自动流程输出。")
            self._schedule_page_scrollregion_update()
            return
        if self.mode_var.get() != mode:
            self.mode_var.set(mode)
        self._update_seed_scheme_controls()
        self._update_advanced_runtime_controls()
        is_egg = mode == "egg"
        is_tid = mode == "tid"
        is_sid = mode == "sid"
        is_script_test = mode == "script_test"
        self.search_button.configure(
            text=(
                "预检所选脚本" if is_script_test
                else "准备 SID 查找" if is_sid
                else "生成孵蛋脚本" if is_egg
                else (
                    "生成 TID/SID + 御三家计划"
                    if self.tid_starter_flow_var.get()
                    else "生成 TID/SID 脚本"
                ) if is_tid
                else "搜索并生成方案"
            )
        )
        if not self.busy:
            self.status_var.set(
                "选择 ECS 和运行后端后点击“预检所选脚本”。"
                if is_script_test
                else "填写 SID 查找条件后点击“准备 SID 查找”。"
                if is_sid
                else "填写孵蛋参数后点击“生成孵蛋脚本”。"
                if is_egg
                else (
                    "填写 TID/SID 与御三家参数后生成连续流程计划。"
                    if self.tid_starter_flow_var.get()
                    else "填写 TID/SID 参数后点击“生成 TID/SID 脚本”。"
                )
                if is_tid
                else "填写条件后点击“搜索并生成方案”。"
            )
        self._schedule_page_scrollregion_update()

    def _on_tid_flow_toggle(self, *_):
        self._update_tid_flow_controls()
        self._update_advanced_runtime_controls()
        if self._is_tid_mode():
            self._on_mode_tab_change()

    def _update_tid_delay_controls(self):
        state = "normal" if self.tid_manual_delay_var.get() else "disabled"
        for entry in self.tid_delay_entries:
            entry.configure(state=state)

    def _update_tid_shiny_pid_controls(self):
        """Keep the optional shiny-PID input restricted to advanced mode."""
        entry = getattr(self, "tid_shiny_pid_entry", None)
        variable = getattr(self, "tid_shiny_pid_var", None)
        if entry is None or variable is None:
            return
        advanced_var = getattr(self, "advanced_mode_var", None)
        advanced = bool(advanced_var is not None and advanced_var.get())
        if not advanced and variable.get() != DEFAULT_TID_SHINY_PID:
            self._updating = True
            try:
                variable.set(DEFAULT_TID_SHINY_PID)
            finally:
                self._updating = False
        entry.configure(state="normal" if advanced else "disabled")

    def _update_tid_flow_controls(self):
        enabled = self.tid_starter_flow_var.get()
        exhaustive = self.tid_mode_var.get() == "穷举模式"
        any_tid = enabled and exhaustive and self.tid_any_tid_var.get()
        if enabled and exhaustive:
            self._updating = True
            try:
                self.tid_sid_mode_var.set(TID_SID_MODE_FIXED_F3)
            finally:
                self._updating = False
        if self.tid_sid_mode_var.get() == TID_SID_MODE_FIXED_F3_LEGACY:
            self._updating = True
            try:
                self.tid_sid_mode_var.set(TID_SID_MODE_FIXED_F3)
            finally:
                self._updating = False
        fixed_f3 = self.tid_sid_mode_var.get() in {
            TID_SID_MODE_FIXED_F3,
            TID_SID_MODE_FIXED_F3_LEGACY,
            TID_SID_MODE_NO_RANDOM,
        }
        self.tid_mode_combo.configure(state="readonly")
        self.tid_sid_mode_combo.configure(
            state="disabled" if enabled and exhaustive else "readonly"
        )
        self.tid_sid_entry.configure(state="disabled" if fixed_f3 else "normal")
        self.tid_calibration_check.configure(state="normal")
        self.tid_any_tid_check.configure(state="normal" if enabled and exhaustive else "disabled")
        self.tid_any_tid_denoise_check.configure(state="normal" if any_tid else "disabled")
        self.tid_target_entry.configure(state="disabled" if any_tid else "normal")
        for widget in self.tid_special_checks:
            widget.configure(state="normal" if (not enabled or exhaustive) and not any_tid else "disabled")
        for widget in self.tid_starter_flow_controls:
            state = "readonly" if enabled and isinstance(widget, ttk.Combobox) else (
                "normal" if enabled else "disabled"
            )
            widget.configure(state=state)
        if enabled and (exhaustive or fixed_f3):
            self.tid_sid_retry_radius_entry.configure(state="disabled")
        self._update_tid_delay_controls()
        shiny_pid_update = getattr(self, "_update_tid_shiny_pid_controls", None)
        if callable(shiny_pid_update):
            shiny_pid_update()

    def _apply_tid_language_defaults(self):
        japanese = self.tid_language_var.get() == "日文"
        defaults = (
            (self.tid_gender_var, "男性" if japanese else "女性"),
            (self.tid_target_var, "1" if japanese else "0"),
            (self.tid_sid_var, "64506" if japanese else "38449"),
            (self.tid_name_var, "レット゛" if japanese else "Alxe"),
            (self.tid_op_delay_var, "30650" if japanese else "30600"),
            (self.tid_f1_delay_var, "27600" if japanese else "22050"),
            (self.tid_f2_delay_var, "8960" if japanese else "4250"),
            (self.tid_f3_delay_var, "15950" if japanese else "14900"),
            (self.tid_op_target_var, "3689" if japanese else "3693"),
            (self.tid_f1_target_var, "3323" if japanese else "2693"),
            (self.tid_f2_target_var, "2011" if japanese else "2105"),
            (self.tid_op_start_var, "0"),
            (self.tid_f1_start_var, "0"),
            (self.tid_f2_start_var, "0"),
            (self.tid_op_rng_range_var, "10" if japanese else "0"),
            (self.tid_f1_rng_range_var, "10" if japanese else "0"),
            (self.tid_f2_rng_range_var, "10" if japanese else "0"),
            (self.tid_op_max_range_var, "600"),
            (self.tid_f1_max_range_var, "500" if japanese else "30"),
            (self.tid_f2_max_range_var, "10" if japanese else "300"),
        )
        self._updating = True
        try:
            for variable, value in defaults:
                variable.set(value)
            self.tid_same_id_var.set(japanese)
            self.tid_sequential_id_var.set(japanese)
            self.tid_65535_var.set(True)
            self.tid_single_digit_var.set(japanese)
            if (
                self.tid_starter_flow_var.get()
                and self.tid_mode_var.get() != "穷举模式"
            ):
                self.tid_same_id_var.set(False)
                self.tid_sequential_id_var.set(False)
                self.tid_65535_var.set(False)
                self.tid_single_digit_var.set(False)
        finally:
            self._updating = False
        self.invalidate_plan()

    def _populate_seed_modes(self):
        choices = ["自动选择", *SEED_MODE_CHOICES]
        current = self.seed_mode_var.get()
        egg_choices = ["请选择", *[choice for choice in choices if choice != "自动选择"]]
        egg_current = self.egg_seed_mode_var.get()
        self._updating = True
        try:
            self.seed_mode_combo.configure(values=choices)
            if current not in choices:
                self.seed_mode_var.set("自动选择")
            self.egg_seed_mode_combo.configure(values=egg_choices)
            if egg_current not in egg_choices:
                self.egg_seed_mode_var.set("请选择")
        finally:
            self._updating = False

    def _populate_egg_pokemon(self):
        names = [get_species_name(species_id) for species_id in range(1, 387)]
        self.egg_pokemon_map = {
            f"{SPECIES_EN_TO_ZH.get(name, name)} ({name})": name
            for name in names
        }
        current_text = self.egg_pokemon_var.get()
        try:
            current_species_id = parse_egg_species(current_text)
        except ValueError:
            current_species_id = None
        self._updating = True
        try:
            self.egg_pokemon_combo.configure(values=list(self.egg_pokemon_map))
            if current_species_id is None:
                preferred = next(
                    (key for key, value in self.egg_pokemon_map.items() if value == "Pikachu"),
                    None,
                )
                self.egg_pokemon_var.set(preferred or next(iter(self.egg_pokemon_map), ""))
        finally:
            self._updating = False

    def _populate_abilities(self):
        pokemon = self.pokemon_map.get(self.pokemon_var.get())
        abilities = ["不限"]
        if pokemon:
            personal = get_personal(get_species_id(pokemon), self._game_code())
            abilities.extend(
                dict.fromkeys(
                    ABILITY_EN_TO_ZH.get(get_ability_name(ability_id), get_ability_name(ability_id))
                    for ability_id in personal["abilities"] if ability_id
                )
            )
        self._updating = True
        try:
            self.ability_combo.configure(values=abilities)
            self.ability_var.set("不限")
        finally:
            self._updating = False

    def _update_search_mode_controls(self):
        """Enable direct Seed/Advance fields only in the explicit-target mode."""
        direct = self.search_mode_var.get() == "指定 Seed/帧数"
        for widget in getattr(self, "_direct_entries", ()):
            if isinstance(widget, (ttk.Entry, ttk.Spinbox)):
                widget.configure(state="normal" if direct else "disabled")
        if direct:
            self.min_adv_var.set(self.min_adv_var.get() or "3000")

    def collect_request(self):
        category = self.category_map.get(self.category_var.get())
        location = self.location_map.get(self.location_var.get())
        pokemon = self.pokemon_map.get(self.pokemon_var.get())
        if not category or not location or not pokemon:
            raise ValueError("请完整选择遭遇方式、地点和宝可梦")
        seed_mode = (
            None
            if self.seed_mode_var.get() == "自动选择"
            else int(self.seed_mode_var.get().split(":", 1)[0])
        )
        iv_min, iv_max = parse_iv_ranges(
            [variable.get() for variable in self.iv_min_vars],
            [variable.get() for variable in self.iv_max_vars],
        )
        return AutoSearchRequest(
            game=self._game_code(),
            tid=int(self.tid_var.get()),
            sid=int(self.sid_var.get()),
            method="All Wild Methods" if self.method_var.get() == "野生" else "Static 1",
            category=category,
            location=location,
            pokemon=pokemon,
            min_advances=int(self.min_adv_var.get()),
            max_advances=int(self.max_adv_var.get()),
            iv_min=iv_min,
            iv_max=iv_max,
            shiny=FILTER_SHINY_ZH_TO_EN[self.shiny_var.get()],
            nature=FILTER_NATURE_ZH_TO_EN[self.nature_var.get()],
            gender=FILTER_GENDER_ZH_TO_EN[self.gender_var.get()],
            ability=ABILITY_ZH_TO_EN.get(self.ability_var.get(), self.ability_var.get()),
            hidden_type=FILTER_TYPE_ZH_TO_EN[self.hidden_type_var.get()],
            seed_mode=seed_mode,
            direct_mode=self.search_mode_var.get() == "指定 Seed/帧数",
            direct_seed=self.direct_seed_var.get().strip(),
            direct_advances=int(self.direct_adv_var.get()),
        )

    def _egg_parent_config_payload(self) -> dict:
        species_id = parse_egg_species(self.egg_pokemon_var.get())
        return build_egg_parent_config_payload(
            species_id,
            self.egg_compatibility_var.get(),
            self.egg_parent_a_gender_var.get(),
            [variable.get() for variable in self.egg_parent_a_iv_vars],
            self.egg_parent_b_gender_var.get(),
            [variable.get() for variable in self.egg_parent_b_iv_vars],
        )

    def _egg_full_config_payload(self) -> dict:
        if self.egg_seed_mode_var.get() == "请选择":
            raise ValueError("保存全部配置前必须选择孵蛋 Seed 模式")
        species_id = parse_egg_species(self.egg_pokemon_var.get())
        expansion_layers, expansion_seeds, expansion_frames = (
            self._selected_reverse_expansion()
        )
        return build_egg_full_config_payload(
            self.game_var.get(),
            {"Switch 1": 1, "Switch 2": 2}.get(self.nx_var.get()),
            self.egg_seed_mode_var.get().split(":", 1)[0],
            self.egg_seed_var.get(),
            self.egg_held_var.get(),
            self.egg_pickup_var.get(),
            species_id,
            self.egg_compatibility_var.get(),
            self.egg_parent_a_gender_var.get(),
            [variable.get() for variable in self.egg_parent_a_iv_vars],
            self.egg_parent_b_gender_var.get(),
            [variable.get() for variable in self.egg_parent_b_iv_vars],
            self.egg_start_mode_var.get() == EGG_START_MODE_PREPARED,
            self.home_buffer_adaptive_var.get(),
            self._selected_seed_startup_scheme(),
            self._selected_seed_calibration_scheme(egg=True),
            self._selected_output_log_mode(),
            expansion_layers,
            expansion_seeds,
            expansion_frames,
        )

    def _save_egg_json(self, payload: dict, title: str, initialfile: str) -> str | None:
        path = filedialog.asksaveasfilename(
            title=title,
            initialdir=str(ROOT),
            initialfile=initialfile,
            defaultextension=".json",
            filetypes=(("JSON 配置", "*.json"), ("所有文件", "*.*")),
        )
        if not path:
            return None
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def save_egg_parent_config(self):
        try:
            path = self._save_egg_json(
                self._egg_parent_config_payload(),
                "保存孵蛋亲本配置",
                "孵蛋亲本配置.json",
            )
        except (OSError, TypeError, ValueError) as exc:
            messagebox.showerror("保存孵蛋亲本配置失败", str(exc))
            return
        if path:
            self.status_var.set(f"孵蛋亲本配置已保存：{path}")

    def save_egg_full_config(self):
        try:
            path = self._save_egg_json(
                self._egg_full_config_payload(),
                "保存孵蛋全部配置",
                "孵蛋全部配置.json",
            )
        except (OSError, TypeError, ValueError) as exc:
            messagebox.showerror("保存孵蛋全部配置失败", str(exc))
            return
        if path:
            self.status_var.set(f"孵蛋全部配置已保存：{path}")

    def _apply_egg_parent_config(self, config: dict) -> None:
        species_id = config["egg_species_id"]
        display = next(
            (
                key
                for key, value in self.egg_pokemon_map.items()
                if get_species_id(value) == species_id
            ),
            None,
        )
        if display is None:
            raise ValueError(f"无法在当前蛋种列表中找到图鉴编号 {species_id}")
        self._updating = True
        try:
            self.egg_pokemon_var.set(display)
            self.egg_compatibility_var.set(str(config["compatibility"]))
            self.egg_parent_a_gender_var.set(config["parent_a_gender"])
            self.egg_parent_b_gender_var.set(config["parent_b_gender"])
            for variable, value in zip(
                self.egg_parent_a_iv_vars, config["parent_a_ivs"]
            ):
                variable.set(str(value))
            for variable, value in zip(
                self.egg_parent_b_iv_vars, config["parent_b_ivs"]
            ):
                variable.set(str(value))
        finally:
            self._updating = False

    def load_egg_parent_config(self):
        path = filedialog.askopenfilename(
            title="载入孵蛋亲本配置",
            initialdir=str(ROOT),
            filetypes=(("JSON 配置", "*.json"), ("所有文件", "*.*")),
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            config = parse_egg_parent_config_payload(payload)
            self._apply_egg_parent_config(config)
            self.invalidate_plan()
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("载入孵蛋亲本配置失败", str(exc))
            return
        self.status_var.set(f"孵蛋亲本配置已载入：{path}")

    def load_egg_full_config(self):
        path = filedialog.askopenfilename(
            title="载入孵蛋全部配置",
            initialdir=str(ROOT),
            filetypes=(("JSON 配置", "*.json"), ("所有文件", "*.*")),
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            config = parse_egg_full_config_payload(payload)
            game = config["game"]
            nx_model = config["nx_model"]
            self._updating = True
            try:
                self.game_var.set(game)
                self.nx_var.set("Switch 2" if nx_model == 2 else "Switch 1")
            finally:
                self._updating = False
            self._on_game_change()
            seed_mode = next(
                (
                    choice
                    for choice in self.egg_seed_mode_combo.cget("values")
                    if str(choice).startswith(f'{config["seed_mode"]}:')
                ),
                None,
            )
            if seed_mode is None:
                raise ValueError(
                    f'当前游戏不支持孵蛋 Seed 模式 {config["seed_mode"]}'
                )
            self._apply_egg_parent_config(config)
            self._updating = True
            try:
                self.egg_seed_mode_var.set(seed_mode)
                self.egg_seed_var.set(config["target_seed"])
                self.egg_held_var.set(str(config["held_advances"]))
                self.egg_pickup_var.set(str(config["pickup_advances"]))
                self.egg_start_mode_var.set(
                    EGG_START_MODE_PREPARED
                    if config["start_from_prepared_254"]
                    else EGG_START_MODE_FULL
                )
                self.home_buffer_adaptive_var.set(
                    config["home_buffer_adaptive_threshold"]
                )
                self.seed_startup_scheme_var.set(
                    SEED_STARTUP_FIXED_USER_HOME
                    if config["seed_startup_scheme"] == 1
                    else SEED_STARTUP_HOME_BUFFER
                )
                calibration_code = int(config.get("seed_calibration_scheme", 2))
                calibration_labels = {
                    0: SEED_CALIBRATION_ORIGINAL,
                    1: SEED_CALIBRATION_LOCKED_FINE,
                    2: SEED_CALIBRATION_CONTINUATION,
                }
                self.seed_calibration_scheme_var.set(
                    calibration_labels[calibration_code]
                )
                self.output_log_mode_var.set(
                    OUTPUT_LOG_DEBUG
                    if int(config.get("debug_log_output", 1)) == 1
                    else OUTPUT_LOG_COMPACT
                )
                if config.get("reverse_expansion_layers") is not None:
                    self.reverse_expansion_layers_var.set(
                        str(config["reverse_expansion_layers"])
                    )
                    for variable, value in zip(
                        self.reverse_expansion_seed_vars,
                        config["reverse_expansion_seed_tolerances"],
                    ):
                        variable.set(str(value))
                    for variable, value in zip(
                        self.reverse_expansion_frame_vars,
                        config["reverse_expansion_frame_half_widths"],
                    ):
                        variable.set(str(value))
            finally:
                self._updating = False
            self.invalidate_plan()
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("载入孵蛋全部配置失败", str(exc))
            return
        self.status_var.set(f"孵蛋全部配置已载入：{path}")

    # Keep the old method names for callers that used the first GUI version.
    def save_egg_config(self):
        self.save_egg_parent_config()

    def load_egg_config(self):
        self.load_egg_parent_config()

    def collect_egg_request(self) -> EggRunRequest:
        species_id = parse_egg_species(self.egg_pokemon_var.get())
        if self.egg_seed_mode_var.get() == "请选择":
            raise ValueError("请选择与 Ten Lines 结果一致的孵蛋 Seed 模式")
        if not self.egg_ack_var.get():
            raise ValueError("请先勾选孵蛋运行确认")
        expansion_layers, expansion_seeds, expansion_frames = (
            self._selected_reverse_expansion()
        )
        return EggRunRequest(
            game=self._game_code(),
            seed_mode=int(self.egg_seed_mode_var.get().split(":", 1)[0]),
            target_seed=self.egg_seed_var.get(),
            held_advances=int(self.egg_held_var.get()),
            pickup_advances=int(self.egg_pickup_var.get()),
            species_id=species_id,
            compatibility=int(self.egg_compatibility_var.get()),
            parent_a_gender=self.egg_parent_a_gender_var.get(),
            parent_a_ivs=parse_exact_ivs(
                [variable.get() for variable in self.egg_parent_a_iv_vars], "亲本A"
            ),
            parent_b_gender=self.egg_parent_b_gender_var.get(),
            parent_b_ivs=parse_exact_ivs(
                [variable.get() for variable in self.egg_parent_b_iv_vars], "亲本B"
            ),
            start_from_prepared_254=(
                self.egg_start_mode_var.get() == EGG_START_MODE_PREPARED
            ),
            home_buffer_adaptive_threshold=self.home_buffer_adaptive_var.get(),
            seed_startup_scheme=self._selected_seed_startup_scheme(),
            seed_calibration_scheme=self._selected_seed_calibration_scheme(egg=True),
            update_precalibration=self.update_precalibration_var.get(),
            debug_log_output=self._selected_output_log_mode(),
            reverse_expansion_layers=expansion_layers,
            reverse_expansion_seed_tolerances=expansion_seeds,
            reverse_expansion_frame_half_widths=expansion_frames,
        )

    def calculate_tid_shiny_sid(self) -> None:
        """Find and apply the earliest SID that makes the configured PID shiny."""
        if self.busy or self._process_running():
            messagebox.showerror("正在运行", "请先等待当前流程结束，再计算 6V 闪 SID。")
            return
        try:
            tid_text = str(self.tid_target_var.get()).strip()
            if not re.fullmatch(r"[0-9]+", tid_text):
                raise ValueError("TID 必须是十进制整数")
            tid = int(tid_text, 10)
            if not 0 <= tid <= 0xFFFF:
                raise ValueError("TID 必须在 0–65535 之间")
            f3_delay_var = getattr(self, "tid_f3_delay_var", None)
            f3_delay_text = f3_delay_var.get() if f3_delay_var is not None else "0"
            if not re.fullmatch(r"[0-9]+", str(f3_delay_text).strip()):
                raise ValueError("F3 固定延迟必须是非负整数")
            f3_delay_ms = int(str(f3_delay_text).strip(), 10)
            f3_frame_floor = fixed_delay_to_frames(f3_delay_ms)
            language_var = getattr(self, "tid_language_var", None)
            language = (
                str(language_var.get()).strip()
                if language_var is not None
                else "英文"
            )
            sid_correction_var = getattr(self, "tid_sid_adv_correction_var", None)
            sid_correction_text = (
                str(sid_correction_var.get()).strip()
                if sid_correction_var is not None
                else "0"
            )
            if not re.fullmatch(r"[+-]?[0-9]+", sid_correction_text):
                raise ValueError("SID ADV 修正必须是整数")
            sid_correction = int(sid_correction_text, 10)
            f3_min_advances = sid_min_advances_for_f3(
                f3_delay_ms,
                language=language,
                sid_advance_correction=sid_correction,
            )
            sid_prefix = SID_ADV_COMPENSATION_BY_LANGUAGE[language]
            advanced = self._seed_options_are_advanced()
            pid_text = (
                self.tid_shiny_pid_var.get()
                if advanced
                else DEFAULT_TID_SHINY_PID
            )
            pid = parse_pid_hex(pid_text)
            psv = pid_to_psv(pid)
            sid_candidates = sid_candidates_for_psv(tid, psv)
            hit = find_earliest_shiny_sid(
                tid,
                pid,
                min_advances=f3_min_advances,
                max_advances=DEFAULT_TID_SID_SEARCH_ADVANCES,
            )
            if hit is None:
                raise LookupError(
                    f"TID 生成链 ADV {f3_min_advances:,}-"
                    f"{DEFAULT_TID_SID_SEARCH_ADVANCES - 1:,} 中没有找到"
                    "该 PID 对应的闪光 SID"
                )
        except (ValueError, LookupError) as exc:
            messagebox.showerror("6V 闪 SID 计算失败", str(exc), parent=self.root)
            return

        self._updating = True
        try:
            self.tid_shiny_pid_var.set(f"{pid:08X}")
            self.tid_sid_var.set(f"{hit.sid:05d}")
        finally:
            self._updating = False
        self.invalidate_plan()
        self.append_result_note(
            "6V 闪 SID 计算完成："
            f"TID {tid:05d} / PID {pid:08X} / PSV {psv:04d}\n"
            f"合法 SID 候选：{', '.join(f'{sid:05d}' for sid in sid_candidates)}\n"
            f"F3 固定延迟：{f3_delay_ms} ms = {f3_frame_floor} ADV；"
            f"{language}版 SID 前置补偿：{sid_prefix} ADV；SID 修正：{sid_correction:+d}；"
            f"实际最低搜索 ADV：{f3_min_advances}；"
            f"最低 SID ADV：{hit.advance}；目标 SID 已设置为 {hit.sid:05d}。"
        )
        self.status_var.set(
            f"6V 闪 SID 已回填：SID {hit.sid:05d}（ADV {hit.advance}，"
            f"最低可执行 ADV {f3_min_advances}）；请重新生成计划。"
        )

    def collect_tid_request(self) -> TidRngRequest:
        sid_mode = self.tid_sid_mode_var.get()
        any_tid = self.tid_starter_flow_var.get() and self.tid_mode_var.get() == "穷举模式" and self.tid_any_tid_var.get()
        request = TidRngRequest(
            language=self.tid_language_var.get(),
            mode=1 if self.tid_mode_var.get() == "乱数模式" else 0,
            calibration_check=self.tid_calibration_var.get(),
            op_fixed_delay=int(self.tid_op_delay_var.get()),
            f1_fixed_delay=int(self.tid_f1_delay_var.get()),
            f2_fixed_delay=int(self.tid_f2_delay_var.get()),
            f3_fixed_delay=int(self.tid_f3_delay_var.get()),
            close_game_delay=int(self.tid_close_delay_var.get()),
            home_buffer_delay=int(self.tid_home_buffer_var.get()),
            op_correction=int(self.tid_op_correction_var.get()),
            gender=0 if self.tid_gender_var.get() == "男性" else 1,
            nx_model=2 if self.tid_nx_var.get() == "Switch 2" else 1,
            target_tid=0 if any_tid else int(self.tid_target_var.get()),
            target_sid=int(self.tid_sid_var.get()),
            sid_advance_correction=int(self.tid_sid_adv_correction_var.get()),
            op_target_frame=int(self.tid_op_target_var.get()),
            f1_target_frame=int(self.tid_f1_target_var.get()),
            f2_target_frame=int(self.tid_f2_target_var.get()),
            op_start=int(self.tid_op_start_var.get()),
            f1_start=int(self.tid_f1_start_var.get()),
            f2_start=int(self.tid_f2_start_var.get()),
            player_name=self.tid_name_var.get(),
            select_correction=int(self.tid_select_correction_var.get()),
            sound=0 if self.tid_sound_var.get() == "MONO" else 1,
            button_mode={"HELP": 0, "LR": 1, "L=A": 2}[self.tid_button_mode_var.get()],
            seed_button={"A": 0, "START": 1, "L(L=A)": 2}[self.tid_seed_button_var.get()],
            name_entry_button=0 if self.tid_name_entry_var.get() == "A" else 1,
            sid_random=sid_mode
            in {
                TID_SID_MODE_NO_RANDOM,
                TID_SID_MODE_FIXED_F3,
                TID_SID_MODE_FIXED_F3_LEGACY,
            },
            f3_random_range=0,
            op_rng_range=int(self.tid_op_rng_range_var.get()),
            f1_rng_range=int(self.tid_f1_rng_range_var.get()),
            f2_rng_range=int(self.tid_f2_rng_range_var.get()),
            op_max_range=int(self.tid_op_max_range_var.get()),
            f1_max_range=int(self.tid_f1_max_range_var.get()),
            f2_max_range=int(self.tid_f2_max_range_var.get()),
            f2_candidate_range=int(self.tid_f2_candidate_var.get()),
            f1_candidate_range=int(self.tid_f1_candidate_var.get()),
            denoise_need_hit=int(self.tid_denoise_hit_var.get()),
            denoise_try_window=int(self.tid_denoise_window_var.get()),
            same_id=self.tid_same_id_var.get(),
            sequential_id=self.tid_sequential_id_var.get(),
            include_65535=self.tid_65535_var.get(),
            single_digit_id=self.tid_single_digit_var.get(),
            image_threshold=int(self.tid_threshold_var.get()),
            home_buffer_adaptive_threshold=self.home_buffer_adaptive_var.get(),
            additional_target_tids=() if any_tid else parse_target_tids(self.tid_additional_targets_var.get()),
            auto_rng=self.tid_auto_rng_var.get() and not any_tid,
            near_tid_distance=int(self.tid_near_distance_var.get()),
            near_tid_hits=int(self.tid_near_hits_var.get()),
            auto_op_rng_range=int(self.tid_auto_op_range_var.get()),
            auto_f1_rng_range=int(self.tid_auto_f1_range_var.get()),
            auto_f2_rng_range=int(self.tid_auto_f2_range_var.get()),
        )
        template_path = resolve_tid_template(self.tid_source_var.get(), request.language)
        template_text = template_path.read_text(encoding="utf-8-sig")
        from automation.tid_starter_save import is_starter_save_template, split_tid_modules
        if is_starter_save_template(template_text):
            modules = split_tid_modules(template_text)
            template_text = modules[1 if request.language == "英文" else 2]
        request.validate(template_text)
        return request

    def collect_tid_starter_flow_request(
        self,
        tid_request: TidRngRequest,
    ) -> TidStarterFlowRequest | None:
        if not self.tid_starter_flow_var.get():
            return None
        startup_selector = getattr(self, "_selected_seed_startup_scheme", None)
        starter_seed_startup_scheme = (
            startup_selector() if callable(startup_selector) else 0
        )
        template_selector = getattr(self, "_selected_generation_template_name", None)
        starter_template_name = (
            template_selector() if callable(template_selector) else STANDARD_TEMPLATE_NAME
        )
        update_precalibration_var = getattr(self, "update_precalibration_var", None)
        expansion_selector = getattr(self, "_selected_reverse_expansion", None)
        expansion_layers, expansion_seeds, expansion_frames = (
            expansion_selector()
            if callable(expansion_selector)
            else (None, None, None)
        )
        output_selector = getattr(self, "_selected_output_log_mode", None)
        parity_selector = getattr(self, "_selected_frame_parity_scheme", None)
        request = TidStarterFlowRequest(
            tid_request=replace(tid_request, calibration_check=False),
            version=self.tid_game_var.get(),
            starter=self.tid_starter_var.get(),
            starter_min_advances=int(self.tid_starter_min_adv_var.get()),
            starter_max_advances=int(self.tid_starter_max_adv_var.get()),
            sid_retry_radius=int(self.tid_sid_retry_radius_var.get()),
            starter_sound=(
                {"MONO": 0, "STEREO": 1}.get(
                    getattr(self, "tid_starter_sound_var", None).get()
                    if getattr(self, "tid_starter_sound_var", None) is not None
                    else "MONO",
                    0,
                )
            ),
            starter_button_mode=(
                {"HELP": 0, "LR": 1, "L=A": 2}.get(
                    getattr(self, "tid_starter_button_mode_var", None).get()
                    if getattr(self, "tid_starter_button_mode_var", None) is not None
                    else "HELP",
                    0,
                )
            ),
            starter_seed_button=(
                {"A": 0, "START": 1, "L(L=A)": 2}.get(
                    getattr(self, "tid_starter_seed_button_var", None).get()
                    if getattr(self, "tid_starter_seed_button_var", None) is not None
                    else "A",
                    0,
                )
            ),
            accept_any_tid=tid_request.mode == 0 and self.tid_any_tid_var.get(),
            any_tid_require_denoise=self.tid_any_tid_denoise_var.get(),
            starter_seed_startup_scheme=starter_seed_startup_scheme,
            starter_template_name=starter_template_name,
            update_precalibration=(
                bool(update_precalibration_var.get())
                if update_precalibration_var is not None
                else False
            ),
            starter_debug_log_output=(
                output_selector() if callable(output_selector) else 1
            ),
            starter_frame_parity_scheme=(
                parity_selector(egg=False) if callable(parity_selector) else 1
            ),
            starter_reverse_expansion_layers=expansion_layers,
            starter_reverse_expansion_seed_tolerances=expansion_seeds,
            starter_reverse_expansion_frame_half_widths=expansion_frames,
        )
        request.validate()
        return request

    def collect_sid_request(self) -> SIDReverseRunRequest:
        if not self.sid_ack_var.get():
            raise ValueError("请先确认队伍顺序、宝可梦、来源、努力值和神奇糖果位置")
        party_count = int(self.sid_count_var.get())
        dex_overrides = tuple(
            parse_sid_species(variable.get(), index + 1)
            if index < party_count
            else 0
            for index, variable in enumerate(self.sid_species_vars)
        )
        try:
            initial_levels = tuple(
                int(variable.get()) if index < party_count else 1
                for index, variable in enumerate(self.sid_initial_level_vars)
            )
        except ValueError as exc:
            raise ValueError("活动队伍槽位必须填写1-100的初始等级") from exc
        source_types = tuple(
            0 if index >= party_count or variable.get() == "定点" else 1
            for index, variable in enumerate(self.sid_source_type_vars)
        )
        locations = tuple(
            self.sid_location_map.get(variable.get(), variable.get().strip())
            if index < party_count
            else ""
            for index, variable in enumerate(self.sid_location_vars)
        )
        effort_values = tuple(
            parse_sid_effort_values(
                tuple(variable.get() for variable in row), index + 1
            )
            if index < party_count
            else (0, 0, 0, 0, 0, 0)
            for index, row in enumerate(self.sid_effort_vars)
        )
        request = SIDReverseRunRequest(
            tid=int(self.sid_tid_var.get()),
            party_count=party_count,
            game="fr_nx" if self.sid_game_var.get() == "火红" else "lg_nx",
            nx_model=2 if self.sid_nx_var.get() == "Switch 2" else 1,
            max_candies=int(self.sid_candies_var.get()),
            recognition_threshold=int(self.sid_threshold_var.get()),
            home_buffer_adaptive_threshold=self.home_buffer_adaptive_var.get(),
            dex_overrides=dex_overrides,  # type: ignore[arg-type]
            initial_levels=initial_levels,  # type: ignore[arg-type]
            source_types=source_types,  # type: ignore[arg-type]
            locations=locations,  # type: ignore[arg-type]
            effort_values=effort_values,  # type: ignore[arg-type]
        )
        source_path = Path(self.sid_source_var.get())
        template_path = source_path / SID_REVERSE_TEMPLATE_NAME
        if not template_path.is_file():
            raise FileNotFoundError(f"找不到 SID 采集模板：{template_path}")
        request.validate()
        return request

    def set_result(self, text):
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    def append_result_note(self, text: str) -> None:
        if not text:
            return
        self.result_text.configure(state="normal")
        if self.result_text.index("end-1c") != "1.0":
            self.result_text.insert("end", "\n")
        self.result_text.insert("end", text.rstrip("\r\n"))
        self.result_text.configure(state="disabled")

    @staticmethod
    def _precalibration_plan_lines(project_main: Path | None) -> list[str]:
        if project_main is None:
            return []
        manifest_path = project_main.parent / "plan.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return []
        config = manifest.get("precalibration")
        if not isinstance(config, dict):
            return []
        if config.get("enabled") is not True:
            return ["自动更新预校准：关闭"]
        context = config.get("context")
        if not isinstance(context, dict):
            return ["自动更新预校准：已开启，但生成清单缺少上下文"]
        kind_text = {
            "STATIC": "普通定点",
            "WILD": "野生",
            "EGG": "孵蛋",
            "STARTER": "御三家",
        }.get(str(context.get("kind")), str(context.get("kind", "?")))
        entry_text = "正式版" if context.get("entry") == "FORMAL" else "时间轴版"
        lines = [
            "自动更新预校准：开启（"
            f"{kind_text} / {entry_text} / Seed 启动方案 {context.get('seed_startup_scheme', '?')}）"
        ]
        if config.get("frame_enabled") is False:
            lines.append("本流程只复用 Seed 预校准；正式版普通定点不复用帧预校准。")
        loaded = config.get("loaded")
        if isinstance(loaded, dict):
            nx = int(context.get("nx_model", 1))
            seed_value = loaded.get("seed_ns1" if nx == 1 else "seed_ns2")
            if context.get("kind") == "EGG":
                frame_text = (
                    f"Held={loaded.get('held_pre')} / Pickup={loaded.get('pickup_pre')}"
                )
            elif config.get("frame_enabled") is False:
                frame_text = "帧=不加载"
            else:
                frame_text = f"帧={loaded.get('frame_ns1' if nx == 1 else 'frame_ns2')}"
            lines.append(f"已载入同上下文记录：Seed 索引={seed_value} / {frame_text}")
        else:
            lines.append("未找到同上下文历史记录，本次使用模板初值。")
        return lines

    @staticmethod
    def _update_completed_precalibration(
        project_main: Path | None,
        log_path: Path | None,
        exit_code: int,
    ) -> str | None:
        if project_main is None or exit_code != 0:
            return None
        manifest_path = project_main.parent / "plan.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        config = manifest.get("precalibration")
        if not isinstance(config, dict) or config.get("enabled") is not True:
            return None
        full_log = read_full_run_log(log_path)
        try:
            record = update_precalibration_from_manifest(
                DEFAULT_PRECALIBRATION_STORE_PATH,
                manifest_path,
                full_log,
            )
        except (OSError, TypeError, ValueError) as exc:
            return f"预校准更新失败，原记录保留：{exc}"
        if record is None:
            return "预校准未更新：本轮日志没有完整的目标命中标记。"
        context = record["context"]
        nx = int(context["nx_model"])
        seed_value = record.get("seed_ns1" if nx == 1 else "seed_ns2")
        if context["kind"] == "EGG":
            frame_text = (
                f"Held={record.get('held_pre')} / Pickup={record.get('pickup_pre')}"
            )
        else:
            frame_value = record.get("frame_ns1" if nx == 1 else "frame_ns2")
            frame_allowed = not (
                context["entry"] == "FORMAL" and context["kind"] == "STATIC"
            )
            frame_text = (
                f"帧={frame_value}"
                if frame_allowed and frame_value is not None
                else "帧=不适用"
            )
        return (
            "预校准已更新："
            f"{context['kind']} / {context['entry']} / 启动方案{context['seed_startup_scheme']} / "
            f"Seed 索引={seed_value} / {frame_text}"
        )

    def set_run_log(self, text: str) -> None:
        self.run_log_text.configure(state="normal")
        self.run_log_text.delete("1.0", "end")
        self.run_log_text.insert("1.0", text)
        self.run_log_text.see("end")
        self.run_log_text.configure(state="disabled")

    def append_run_log(self, text: str) -> None:
        line = text.rstrip("\r\n")
        if not line:
            return
        self.run_log_text.configure(state="normal")
        if self.run_log_text.index("end-1c") != "1.0":
            self.run_log_text.insert("end", "\n")
        self.run_log_text.insert("end", line)
        self.run_log_text.see("end")
        self.run_log_text.configure(state="disabled")

    def _known_device_label_dirs(self) -> tuple[Path, ...]:
        candidates = [ROOT / "assets" / "easycon118_extensions"]
        for variable_name in ("source_var", "sid_source_var", "tid_source_var"):
            variable = getattr(self, variable_name, None)
            if variable is None:
                continue
            value = variable.get().strip()
            if value:
                candidates.append(Path(value) / "ImgLabel")
        if self.project_main is not None:
            candidates.append(self.project_main.parent / "ImgLabel")
        return tuple(dict.fromkeys(path.resolve() for path in candidates if path.is_dir()))

    def _current_label_profile(self) -> LabelOverrideProfile:
        return self.label_override_store.profile(self.video_var.get())

    def _active_label_profile(self) -> LabelOverrideProfile | None:
        try:
            profile = self._current_label_profile()
            return profile if self.label_override_store.list_overrides(self.video_var.get()) else None
        except ValueError:
            raise

    def _on_capture_device_changed(self) -> None:
        self.refresh_device_label_profile()

    def refresh_device_label_profile(self) -> None:
        try:
            profile = self._current_label_profile()
            overrides = self.label_override_store.list_overrides(self.video_var.get())
        except ValueError as exc:
            self.label_profile_status_var.set(str(exc))
            return
        self.label_profile_status_var.set(
            f"当前采集设备：{profile.capture_device}；设备覆盖标签 {len(overrides)} 个。"
            "导入后须重新生成方案；原始标签包不会被修改，也不需要开启高级模式。"
        )

    def _show_label_issues(self, issues: tuple[LabelIssue, ...]) -> None:
        self.label_issues = issues
        for item in self.label_issue_tree.get_children():
            self.label_issue_tree.delete(item)
        for issue in issues:
            self.label_issue_tree.insert(
                "",
                "end",
                values=(
                    " / ".join(issue.labels),
                    "未输出" if issue.score is None else issue.score,
                    "未输出" if issue.threshold is None else issue.threshold,
                    issue.occurrences,
                    f"{issue.context}：{issue.reason}",
                ),
            )

    def _update_label_diagnostics(self, log_text: str, *, notify: bool = False) -> None:
        issues = diagnose_label_log(log_text)
        self._show_label_issues(issues)
        if not issues:
            return
        exact = [
            issue for issue in issues
            if any(label.lower().endswith(".il") for label in issue.labels)
        ]
        if exact:
            first = exact[0]
            score = (
                f"{first.score}/{first.threshold}"
                if first.score is not None and first.threshold is not None
                else "未输出分数"
            )
            self.label_profile_status_var.set(
                f"检测到 {len(issues)} 组疑似标签问题；最可能是 "
                f"{' / '.join(first.labels)}（{score}，连续{first.occurrences}次）。"
                "可在下方选择或拖入重做后的同名标签。"
            )
        if notify:
            lines = []
            for issue in issues[:8]:
                score = (
                    f"{issue.score}/{issue.threshold}"
                    if issue.score is not None and issue.threshold is not None
                    else "日志未输出组内分数"
                )
                lines.append(
                    f"- {issue.context}: {' / '.join(issue.labels)}，{score}，"
                    f"连续{issue.occurrences}次"
                )
            messagebox.showwarning(
                "可能由标签匹配造成停止或卡住",
                "工具从日志中定位到以下疑似标签：\n\n"
                + "\n".join(lines)
                + "\n\n请只导入在正确画面上重新制作的同名 .IL；"
                  "工具会保存为当前采集设备的覆盖层，不修改原包。",
            )

    def _import_device_label_paths(self, paths: tuple[str, ...]) -> None:
        if self.busy or self._process_running():
            messagebox.showerror("正在运行", "请先停止当前流程，再修改设备标签覆盖。")
            return
        try:
            result = self.label_override_store.import_paths(
                self.video_var.get(),
                paths,
                self._known_device_label_dirs(),
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("标签导入失败", str(exc))
            return
        self.invalidate_plan()
        self.refresh_device_label_profile()
        self.set_result(
            f"已为采集设备 {result.profile.capture_device} 导入 "
            f"{len(result.imported)} 个标签：\n"
            + "\n".join(result.imported)
            + f"\n\n当前设备覆盖共 {result.total} 个；请重新搜索/生成方案后再运行。"
        )
        messagebox.showinfo(
            "设备标签已导入",
            f"已导入 {len(result.imported)} 个同名标签。\n"
            "原始标签包未修改；请重新生成方案，让运行工程应用覆盖层。",
        )

    def choose_device_label_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择当前采集设备重做后的 EasyCon 标签",
            filetypes=(("EasyCon 标签", "*.IL"), ("所有文件", "*.*")),
        )
        if paths:
            self._import_device_label_paths(tuple(paths))

    def choose_device_label_folder(self) -> None:
        path = filedialog.askdirectory(title="选择包含重做标签的文件夹")
        if path:
            self._import_device_label_paths((path,))

    def _on_label_drop(self, event):
        try:
            paths = tuple(self.root.tk.splitlist(event.data))
        except tk.TclError as exc:
            messagebox.showerror("拖入失败", f"无法解析拖入路径：{exc}")
            return "break"
        self._import_device_label_paths(paths)
        return "copy"

    def clear_device_label_overrides(self) -> None:
        if self.busy or self._process_running():
            messagebox.showerror("正在运行", "请先停止当前流程，再清除设备标签覆盖。")
            return
        try:
            profile = self._current_label_profile()
            count = len(self.label_override_store.list_overrides(self.video_var.get()))
        except ValueError as exc:
            messagebox.showerror("无法清除", str(exc))
            return
        if count == 0:
            messagebox.showinfo("没有设备覆盖", "当前采集设备尚未导入自定义标签。")
            return
        if not messagebox.askyesno(
            "清除当前设备覆盖",
            f"删除 {profile.capture_device} 的 {count} 个设备标签覆盖？\n"
            "原始标签包不会受影响。",
        ):
            return
        self.label_override_store.clear(self.video_var.get())
        self.invalidate_plan()
        self.refresh_device_label_profile()
        self.set_result("已清除当前采集设备的标签覆盖；后续生成恢复使用原始标签包。")

    def show_run_log_tab(self) -> None:
        self.mode_notebook.select(self.run_log_tab)
        self.page_canvas.yview_moveto(0.0)
        self._schedule_page_scrollregion_update()

    def set_busy(self, busy, status):
        self.busy = busy
        self.status_var.set(status)
        self.search_button.configure(state="disabled" if busy else "normal")
        self.device_button.configure(state="disabled" if busy else "normal")
        self._refresh_manual_tools_buttons()
        self._refresh_start_button()

    def _process_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _current_running_log_path(self) -> Path | None:
        return {
            "script_test": self.script_test_log_path,
            "sid": self.sid_log_path,
            "sid_traversal": getattr(self, "sid_traversal_log_path", None),
            "tid_flow": self.tid_flow_log_path,
            "tid": self.tid_log_path,
            "egg": self.egg_log_path,
            "easycon": self.easycon_log_path,
        }.get(self.running_mode)

    def _refresh_manual_tools_buttons(self) -> None:
        enabled = not self.busy and not self._process_running()
        monitor_enabled = not self.busy and (enabled or bool(self.preview_url))
        state = "normal" if enabled else "disabled"
        self.virtual_controller_button.configure(state=state)
        self.monitor_button.configure(state="normal" if monitor_enabled else "disabled")
        self.advanced_mode_check.configure(state=state)
        self.home_buffer_adaptive_check.configure(state=state)
        self.update_precalibration_check.configure(state=state)
        self.output_log_mode_combo.configure(
            state="readonly" if enabled else "disabled"
        )
        self._update_seed_scheme_controls()
        self.seed_update_button.configure(state=state)
        update_button = getattr(self, "app_update_button", None)
        if update_button is not None:
            if not is_frozen_build() or getattr(self, "_app_update_checking", False):
                update_button.configure(state="disabled")
            elif getattr(self, "_app_update_cancel", None) is not None:
                update_button.configure(state="normal", text="取消程序更新")
            else:
                update_button.configure(state=state, text="检查程序更新")
        self.port_combo.configure(state="readonly" if enabled else "disabled")
        self.video_combo.configure(state="readonly" if enabled else "disabled")
        for button in (
            self.label_import_files_button,
            self.label_import_folder_button,
            self.label_clear_button,
        ):
            button.configure(state=state)

    @staticmethod
    def _app_update_description(candidate: UpdateCandidate) -> str:
        manifest = candidate.manifest
        size_mib = manifest.bytes / (1024 * 1024)
        notes = manifest.notes.strip() or "本版未提供额外更新说明。"
        return (
            f"当前版本：{APP_VERSION}\n"
            f"新版本：{manifest.version}\n"
            f"发布时间：{candidate.published_at}\n"
            f"下载大小：{size_mib:.1f} MiB\n\n"
            f"{notes}\n\n"
            "将下载完整绿色版、校验后退出并安装。是否下载并安装？"
        )

    def check_app_update(self, *, force: bool = True) -> None:
        cancel_event = getattr(self, "_app_update_cancel", None)
        if cancel_event is not None:
            cancel_event.set()
            self.app_update_status_var.set("正在取消程序更新……")
            self.app_update_button.configure(state="disabled")
            return
        if not is_frozen_build():
            self.app_update_status_var.set("源码模式不使用程序自更新。")
            return
        if getattr(self, "_app_update_checking", False):
            return
        self._app_update_checking = True
        self._app_update_manual_check = force
        self.app_update_status_var.set("正在检查程序更新……")
        self._refresh_manual_tools_buttons()

        def worker() -> None:
            try:
                result = check_for_update(
                    current_version_code=APP_VERSION_CODE,
                    cache_dir=USER_DATA_ROOT / "updates",
                    force=force,
                )
            except Exception as exc:
                self.root.after(
                    0,
                    lambda error=exc: self._finish_app_update_check(error=error),
                )
            else:
                self.root.after(
                    0,
                    lambda value=result: self._finish_app_update_check(result=value),
                )

        threading.Thread(target=worker, daemon=True, name="app-update-check").start()

    def _finish_app_update_check(
        self,
        result: UpdateCheckResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        manual = self._app_update_manual_check
        self._app_update_checking = False
        self._refresh_manual_tools_buttons()
        if error is not None:
            self.app_update_status_var.set(f"程序更新检查失败：{error}")
            if manual:
                messagebox.showerror("程序更新检查失败", str(error), parent=self.root)
            return
        if result is None:
            return
        self.app_update_status_var.set(result.message)
        self._app_update_candidate = result.candidate
        if result.status == "error":
            if manual:
                messagebox.showerror("程序更新检查失败", result.message, parent=self.root)
            return
        if result.status != "available" or result.candidate is None:
            if manual:
                messagebox.showinfo("程序更新", result.message, parent=self.root)
            return
        if self.busy or self._process_running():
            self.app_update_status_var.set(
                f"发现新版本 {result.candidate.manifest.version}；当前任务结束后可手动更新。"
            )
            return
        if messagebox.askyesno(
            "发现程序更新",
            self._app_update_description(result.candidate),
            parent=self.root,
        ):
            self.download_app_update(result.candidate)

    def download_app_update(self, candidate: UpdateCandidate | None = None) -> None:
        candidate = candidate or self._app_update_candidate
        if candidate is None:
            self.check_app_update(force=True)
            return
        if self.busy or self._process_running():
            messagebox.showerror(
                "正在运行",
                "请先等待当前操作结束并停止 EasyCon，再安装程序更新。",
                parent=self.root,
            )
            return
        cancel_event = threading.Event()
        self._app_update_cancel = cancel_event
        self.set_busy(True, "正在下载并验证程序更新……")
        self.app_update_status_var.set("正在下载完整绿色版：0%")
        self._refresh_manual_tools_buttons()
        last_percent = [-1]

        def progress(received: int, total: int) -> None:
            percent = min(100, int(received * 100 / total)) if total else 0
            if percent == last_percent[0]:
                return
            last_percent[0] = percent
            self.root.after(
                0,
                lambda value=percent: self.app_update_status_var.set(
                    f"正在下载完整绿色版：{value}%"
                ),
            )

        def worker() -> None:
            try:
                install_dir = Path(sys.executable).resolve().parent
                prepared = prepare_update(
                    candidate,
                    install_dir=install_dir,
                    updates_root=USER_DATA_ROOT / "updates",
                    progress=progress,
                    cancelled=cancel_event.is_set,
                )
            except Exception as exc:
                self.root.after(
                    0,
                    lambda error=exc: self._finish_app_update_download(error=error),
                )
            else:
                self.root.after(
                    0,
                    lambda value=prepared: self._finish_app_update_download(prepared=value),
                )

        threading.Thread(target=worker, daemon=True, name="app-update-download").start()

    def _finish_app_update_download(
        self,
        prepared: PreparedUpdate | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._app_update_cancel = None
        if error is not None:
            if isinstance(error, UpdateCancelled):
                status = "程序更新已取消；当前版本未改变。"
            else:
                status = f"程序更新准备失败：{error}"
            self.app_update_status_var.set(status)
            self.set_busy(False, status)
            if not isinstance(error, UpdateCancelled):
                messagebox.showerror("程序更新失败", str(error), parent=self.root)
            return
        if prepared is None:
            self.set_busy(False, "程序更新没有生成可安装内容。")
            return
        self.app_update_status_var.set("更新包验证通过，正在启动独立更新器……")
        self.install_prepared_update(prepared)

    def install_prepared_update(self, prepared: PreparedUpdate) -> None:
        if self._process_running():
            self.set_busy(False, "EasyCon 仍在运行，程序更新未安装。")
            messagebox.showerror(
                "无法安装程序更新",
                "EasyCon 仍在运行，请停止后重新检查更新。",
                parent=self.root,
            )
            return
        try:
            request_path = write_install_request(
                prepared,
                current_pid=os.getpid(),
                updates_root=USER_DATA_ROOT / "updates",
            )
            source_updater = prepared.install_dir / UPDATER_EXECUTABLE
            if not source_updater.is_file():
                raise UpdateError(f"当前绿色版缺少独立更新器：{source_updater}")
            copied_updater = request_path.parent / UPDATER_EXECUTABLE
            shutil.copy2(source_updater, copied_updater)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                [str(copied_updater), "--request", str(request_path)],
                cwd=request_path.parent,
                creationflags=flags,
                close_fds=True,
            )
        except (OSError, UpdateError) as exc:
            self.set_busy(False, f"独立更新器启动失败：{exc}")
            self.app_update_status_var.set(f"独立更新器启动失败：{exc}")
            messagebox.showerror("程序更新失败", str(exc), parent=self.root)
            return
        self._closing_for_update = True
        self.app_update_status_var.set("独立更新器已启动，正在退出当前版本……")
        self.status_var.set("正在退出当前版本并安装程序更新……")
        self.root.after(100, self._finish_close)

    def update_seed_tables(self) -> None:
        if self.busy or self._process_running():
            messagebox.showerror("正在运行", "请先等待当前操作结束或停止 EasyCon。")
            return
        if not messagebox.askyesno(
            "检查/更新 Seed 表",
            "将联网读取 Ten Lines 官方火红/叶绿 NX Seed 表，"
            "同时生成 Python 搜索表和 EasyCon 表，并用 1.6.4-a 校验两份主脚本。\n\n"
            "校验全部通过后才会切换，是否继续？",
        ):
            return
        source_directory = Path(self.source_var.get()).resolve()
        ezcon_path = Path(self.ezcon_var.get()).resolve()
        fingerprint_warning_only = self.advanced_mode_var.get()
        self.set_run_log("Seed 表更新日志")
        self.show_run_log_tab()
        self.set_busy(True, "正在检查 Ten Lines 官方 Seed 表……")

        def progress(message: str) -> None:
            self.root.after(0, lambda value=message: self.append_run_log(value))

        def worker() -> None:
            try:
                result = run_seed_table_update(
                    source_directory=source_directory,
                    ezcon_path=ezcon_path,
                    progress=progress,
                    fingerprint_warning_only=fingerprint_warning_only,
                )
            except Exception as exc:
                self.root.after(0, lambda error=exc: self.finish_seed_table_update(error=error))
            else:
                self.root.after(0, lambda value=result: self.finish_seed_table_update(result=value))

        threading.Thread(target=worker, daemon=True).start()

    def finish_seed_table_update(self, result=None, error=None) -> None:
        if error is not None:
            self.append_run_log(f"更新失败：{error}")
            self.set_busy(False, "Seed 表检查/更新失败；现有表未切换。")
            messagebox.showerror("Seed 表更新失败", str(error))
            return
        if result.updated:
            clear_frlg_seed_cache()
            self.invalidate_plan()
        self.set_result(
            result.message
            + f"\n\n生效目录：{result.active_directory}"
            + ("\n现有方案已失效，请重新生成。" if result.updated else "")
        )
        self.set_busy(False, result.message)
        messagebox.showinfo("Seed 表", result.message)

    def _sync_script_test_entry_path(self) -> None:
        """Keep the advanced-page ECS path tied to the selected audited entry."""
        selection = self.script_test_entry_var.get()
        if selection == SCRIPT_TEST_ENTRY_CUSTOM:
            if self.script_test_path_var.get().strip():
                self.script_test_entry_status_var.set(
                    "自选 ECS：请确认脚本、lib 和 ImgLabel 来自同一工程。"
                )
            else:
                self.script_test_entry_status_var.set(
                    "自选 ECS：请填写或选择要直接运行的 .ecs 文件。"
                )
            return
        try:
            path = resolve_script_test_entry(self.source_var.get(), selection)
        except (OSError, ValueError) as exc:
            self._updating = True
            try:
                self.script_test_path_var.set("")
            finally:
                self._updating = False
            self.script_test_entry_status_var.set(f"入口不可用：{exc}")
            return
        self._updating = True
        try:
            self.script_test_path_var.set(str(path))
        finally:
            self._updating = False
        self.script_test_entry_status_var.set(f"当前入口：{path.name}")

    def _on_script_test_entry_change(self, *_event) -> None:
        if self._updating:
            return
        self._sync_script_test_entry_path()
        sync_expansion = getattr(self, "_sync_reverse_expansion_defaults", None)
        if callable(sync_expansion):
            sync_expansion()
        self.invalidate_plan()

    def _on_script_test_source_change(self, *_event) -> None:
        if self._updating or self.script_test_entry_var.get() == SCRIPT_TEST_ENTRY_CUSTOM:
            return
        self._sync_script_test_entry_path()
        sync_expansion = getattr(self, "_sync_reverse_expansion_defaults", None)
        if callable(sync_expansion):
            sync_expansion()

    def _on_script_test_path_change(self, *_event) -> None:
        if self._updating:
            return
        path_text = self.script_test_path_var.get().strip()
        if not path_text:
            if self.script_test_entry_var.get() == SCRIPT_TEST_ENTRY_CUSTOM:
                self.script_test_entry_status_var.set(
                    "自选 ECS：请填写或选择要直接运行的 .ecs 文件。"
                )
            else:
                self.script_test_entry_status_var.set("入口路径为空，请重新选择入口。")
            return
        try:
            identified = identify_script_test_entry(
                self.source_var.get(),
                path_text,
            )
        except (OSError, ValueError):
            identified = SCRIPT_TEST_ENTRY_CUSTOM
        if identified != self.script_test_entry_var.get():
            self._updating = True
            try:
                self.script_test_entry_var.set(identified)
            finally:
                self._updating = False
        if identified == SCRIPT_TEST_ENTRY_CUSTOM:
            self.script_test_entry_status_var.set(
                "自选 ECS：请确认脚本、lib 和 ImgLabel 来自同一工程。"
            )
        else:
            self.script_test_entry_status_var.set(
                f"当前入口：{Path(path_text).name}"
            )

    def open_virtual_controller(self) -> None:
        if self.manual_tools is not None:
            self.manual_tools.open_virtual_controller()

    def open_monitor(self) -> None:
        if self.manual_tools is not None:
            self.manual_tools.open_monitor()

    def _close_manual_tools(self) -> None:
        if self.manual_tools is not None:
            self.manual_tools.close_all()

    def _refresh_start_button(self):
        process_running = self.process is not None and self.process.poll() is None
        normal_can_start = bool(
            self.plan_result and self.plan_result.plan.route_support.can_start
        )
        tid_can_start = self.tid_request is not None
        script_test_can_start = bool(
            self._is_script_test_mode() and self.script_test_preparation
        )
        can_start = bool(
            not self.busy
            and not process_running
            and (
                normal_can_start
                or self.egg_request
                or tid_can_start
                or self.sid_request
                or self.sid_traversal_request
                or script_test_can_start
            )
            and self.project_main
            and self.runtime_check
            and self.runtime_check.ok
        )
        self.start_button.configure(state="normal" if can_start else "disabled")

    def search_and_generate(self):
        if self.busy:
            return
        if self.process is not None and self.process.poll() is None:
            messagebox.showerror("正在运行", "请先停止当前 EasyCon 进程，再生成新方案。")
            return
        if getattr(self, "_device_check_in_progress", False):
            messagebox.showerror(
                "设备检测中",
                "启动时的端口/采集卡检测尚未完成，请等待检测结束后再生成方案。",
            )
            return
        try:
            if self._is_script_test_mode():
                self.generate_script_test_preflight()
                return
            if self._is_sid_mode():
                sid_request = self.collect_sid_request()
                self.generate_sid_project(sid_request)
                return
            if self._is_egg_mode():
                egg_request = self.collect_egg_request()
                self.generate_egg_project(egg_request)
                return
            if self._is_tid_mode():
                tid_request = self.collect_tid_request()
                flow_request = self.collect_tid_starter_flow_request(tid_request)
                self.generate_tid_project(tid_request, flow_request)
                return
            request = self.collect_request()
            if self.method_var.get() == "野生" and self.sid_traversal_var.get():
                if self.item_rng_mode_var.get():
                    raise ValueError("SID 遍历模式不能与道具乱数模式同时开启")
                named_rival = self._ask_sid_traversal_confirmation(request)
                if named_rival is None:
                    return
                self.generate_sid_traversal_plan(
                    replace(request, sid=0),
                    bool(named_rival),
                )
                return
            item_rng_enabled = (
                self.method_var.get() == "野生" and self.item_rng_mode_var.get()
            )
            if item_rng_enabled:
                party_empty_slots = int(self.party_empty_slots_var.get())
                if not 1 <= party_empty_slots <= 5:
                    raise ValueError("队伍空位数量必须在 1–5 之间")
            else:
                party_empty_slots = 1
            template_name = self._selected_generation_template_name()
            expansion_layers, expansion_seeds, expansion_frames = (
                self._selected_reverse_expansion()
            )
        except Exception as exc:
            messagebox.showerror("输入错误", str(exc))
            return
        source_path = Path(self.source_var.get())
        ezcon_path = Path(self.ezcon_var.get())
        easycon_options = EasyCon118Options(
            nx_model=2 if request.game.endswith("nx2") else 1,
            paralysis=self.paralysis_var.get(),
            false_swipe=self.false_swipe_var.get(),
            continue_capture_after_shiny=self.auto_capture_var.get(),
            home_buffer_adaptive_threshold=self.home_buffer_adaptive_var.get(),
            seed_startup_scheme=self._selected_seed_startup_scheme(),
            seed_calibration_scheme=self._selected_seed_calibration_scheme(egg=False),
            item_rng_mode=item_rng_enabled,
            party_empty_slots=party_empty_slots,
            update_precalibration=self.update_precalibration_var.get(),
            debug_log_output=self._selected_output_log_mode(),
            frame_parity_scheme=self._selected_frame_parity_scheme(egg=False),
            reverse_expansion_layers=expansion_layers,
            reverse_expansion_seed_tolerances=expansion_seeds,
            reverse_expansion_frame_half_widths=expansion_frames,
        )
        fingerprint_warning_only = self.advanced_mode_var.get()
        try:
            label_profile = self._active_label_profile()
        except ValueError as exc:
            messagebox.showerror("设备标签配置错误", str(exc))
            return
        input_fingerprint = self.input_fingerprint()
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        self.project_main = None
        self.runtime_check = None
        self.set_busy(True, "正在从最高 IV 总和向下搜索……")
        self.search_cancel = threading.Event()
        self.cancel_button.configure(state="normal")
        self.set_result("搜索进行中。宽 IV 范围会按总和分层，不会先展开全部结果。")
        cancel_event = self.search_cancel

        def worker():
            try:
                result = search_best_plan(request, cancel_check=cancel_event.is_set)
                project_main = None
                check = None
                generation_error = None
                plan_dir = WRITABLE_ROOT / "rng_logs" / "plans"
                plan_dir.mkdir(parents=True, exist_ok=True)
                plan_path = plan_dir / (datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
                plan_path.write_text(
                    json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if cancel_event.is_set():
                    raise SearchCancelledError("操作已由用户取消")
                if result.plan.route_support.can_start:
                    try:
                        output = WRITABLE_ROOT / "runtime" / "easycon118"
                        def generate(staging_dir):
                            staged_main = write_configured_project(
                                source_path,
                                staging_dir,
                                result.plan,
                                easycon_options,
                                template_name=template_name,
                            )
                            if label_profile is not None:
                                apply_profile_to_projects(staging_dir, label_profile)
                            return staged_main

                        project_main, check = _generate_runtime_project_atomically(
                            output,
                            generate,
                            lambda staged_main: validate_generated_project_consistency(
                                staged_main,
                                result.plan,
                                easycon_options,
                                template_name=template_name,
                            ),
                            lambda staged_main: validate_runtime(
                                ezcon_path,
                                staged_main,
                                fingerprint_warning_only=fingerprint_warning_only,
                            ),
                        )
                    except Exception as exc:
                        generation_error = exc
                if cancel_event.is_set():
                    raise SearchCancelledError("操作已由用户取消")
                self.root.after(
                    0,
                    lambda: self.finish_search(
                        result, project_main, check, plan_path, input_fingerprint,
                        generation_error, cancel_event,
                    ),
                )
            except Exception as exc:
                self.root.after(0, lambda error=exc: self.fail_search(error))

        threading.Thread(target=worker, daemon=True).start()

    def generate_sid_traversal_plan(
        self,
        request: AutoSearchRequest,
        named_rival: bool,
    ) -> None:
        """Prepare a resumable wild SID traversal without choosing one SID."""
        source_path = Path(self.source_var.get()).resolve()
        ezcon_path = Path(self.ezcon_var.get()).resolve()
        try:
            max_advances = int(self.sid_traversal_max_adv_var.get())
            start_override = self._sid_traversal_start_override()
            start_advance = sid_traversal_start_advance(named_rival, start_override)
            expansion_layers, expansion_seeds, expansion_frames = (
                self._selected_reverse_expansion()
            )
        except (TypeError, ValueError) as exc:
            messagebox.showerror("SID 遍历输入错误", str(exc))
            return
        if max_advances < start_advance:
            messagebox.showerror(
                "SID 遍历输入错误",
                f"遍历上限必须不小于起点 ADV {start_advance}。",
            )
            return
        if request.min_advances > SID_TRAVERSAL_TARGET_MAX_ADVANCES:
            messagebox.showerror(
                "SID 遍历输入错误",
                "目标闪光搜索的最小 ADV 不能大于低帧搜索上限 "
                f"{SID_TRAVERSAL_TARGET_MAX_ADVANCES}（当前为 {request.min_advances}）。",
            )
            return
        try:
            label_profile = self._active_label_profile()
        except ValueError as exc:
            messagebox.showerror("设备标签配置错误", str(exc))
            return
        options = EasyCon118Options(
            nx_model=2 if request.game.endswith("nx2") else 1,
            paralysis=self.paralysis_var.get(),
            false_swipe=self.false_swipe_var.get(),
            # Traversal must be able to distinguish the shiny-stop marker.
            continue_capture_after_shiny=False,
            home_buffer_adaptive_threshold=self.home_buffer_adaptive_var.get(),
            seed_startup_scheme=self._selected_seed_startup_scheme(),
            seed_calibration_scheme=self._selected_seed_calibration_scheme(egg=False),
            item_rng_mode=False,
            party_empty_slots=1,
            debug_log_output=self._selected_output_log_mode(),
            frame_parity_scheme=self._selected_frame_parity_scheme(egg=False),
            reverse_expansion_layers=expansion_layers,
            reverse_expansion_seed_tolerances=expansion_seeds,
            reverse_expansion_frame_half_widths=expansion_frames,
        )
        input_fingerprint = self.input_fingerprint()
        fingerprint_warning_only = self.advanced_mode_var.get()
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        self.project_main = None
        self.runtime_check = None
        self.set_busy(True, "正在准备 SID 遍历计划并预检 2.0 脚本入口……")
        self.set_result(
            f"TID {request.tid:05d} 已确认；"
            f"将从 ADV {start_advance} 遍历到 {max_advances}；"
            f"每个 SID 的目标搜索范围为 ADV {request.min_advances}-"
            f"{SID_TRAVERSAL_TARGET_MAX_ADVANCES}，正在检查脚本和运行后端。"
        )

        def worker() -> None:
            try:
                corpus = inspect_script_corpus(source_path)
                context = traversal_context(
                    tid=request.tid,
                    named_rival=named_rival,
                    wild_request=asdict(request),
                    easycon_options=asdict(options),
                    source_sha256=corpus["sha256"],
                    max_advances=max_advances,
                    start_advance=start_override,
                    target_max_advances=SID_TRAVERSAL_TARGET_MAX_ADVANCES,
                )
                preparation = prepare_script_test_runtime(
                    ezcon_path,
                    source_path / STANDARD_TEMPLATE_NAME,
                    SCRIPT_TEST_BACKEND_COMPAT,
                    fingerprint_warning_only=fingerprint_warning_only,
                )
                plan_dir = WRITABLE_ROOT / "rng_logs" / "plans"
                plan_dir.mkdir(parents=True, exist_ok=True)
                plan_path = plan_dir / (
                    datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    + "_sid_traversal.json"
                )
                payload = {
                    "mode": "sid_traversal",
                    "version": 1,
                    "source": str(source_path),
                    "request": asdict(request),
                    "easycon_options": asdict(options),
                    "named_rival": bool(named_rival),
                    "start_sid_advance": context["start_sid_advance"],
                    "max_advances": max_advances,
                    "target_max_advances": SID_TRAVERSAL_TARGET_MAX_ADVANCES,
                    "traversal_context": context,
                }
                plan_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                self.root.after(
                    0,
                    lambda: self.finish_sid_traversal_generation(
                        request,
                        options,
                        named_rival,
                        context,
                        plan_path,
                        preparation,
                        input_fingerprint,
                        label_profile,
                    ),
                )
            except Exception as exc:
                self.root.after(0, lambda error=exc: self.fail_search(error))

        threading.Thread(target=worker, daemon=True).start()

    def finish_sid_traversal_generation(
        self,
        request: AutoSearchRequest,
        options: EasyCon118Options,
        named_rival: bool,
        context: dict,
        plan_path: Path,
        preparation,
        input_fingerprint,
        label_profile=None,
    ) -> None:
        del label_profile  # Applied by the worker to each generated candidate.
        if input_fingerprint != self.input_fingerprint():
            self.fail_search(ValueError("生成期间输入发生变化，请按当前 SID 遍历条件重新准备。"))
            return
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.sid_traversal_request = request
        self.sid_traversal_options = options
        self.sid_traversal_named_rival = bool(named_rival)
        self.sid_traversal_context = context
        self.sid_traversal_plan_path = plan_path
        self.script_test_preparation = None
        self.project_main = Path(self.source_var.get()).resolve() / STANDARD_TEMPLATE_NAME
        self.runtime_check = preparation.check
        self.sid_traversal_progress_var.set(self._sid_traversal_progress_text(context))
        lines = [
            "野生 SID 遍历模式：可续跑",
            f"目标宝可梦：{request.pokemon}；遭遇：{request.category} / {request.location}",
            f"TID：{request.tid:05d}（SID 输入不参与遍历）",
            f"劲敌取名：{'是' if named_rival else '否'}；起点 ADV：{context['start_sid_advance']}；"
            f"只遍历{'偶数' if context['sid_advance_parity'] == 0 else '奇数'} ADV（步长 2）",
            f"遍历上限：{context['max_advances']}；低帧目标搜索范围："
            f"ADV {request.min_advances}-{SID_TRAVERSAL_TARGET_MAX_ADVANCES}",
            f"计划文件：{plan_path}",
            f"断点文件：{sid_traversal_progress_path(SID_TRAVERSAL_PROGRESS_DIR, context)}",
            self._sid_traversal_progress_text(context),
        ]
        if preparation.check.ok:
            lines.extend(f"预检提示：{warning}" for warning in preparation.check.warnings)
            lines.append("开始运行后，每个明确未出闪候选都会落盘更新下一起点；停止会保留当前候选。")
            status = "SID 遍历计划已准备，可以开始；已有断点会自动续跑。"
        else:
            lines.extend(f"预检失败：{error}" for error in preparation.check.errors)
            status = "SID 遍历计划已生成，但预检不允许启动。"
        self.set_result("\n".join(lines))
        self.set_busy(False, status)

    def generate_script_test_preflight(self):
        entry = self.script_test_entry_var.get()
        if entry != SCRIPT_TEST_ENTRY_CUSTOM:
            expected = resolve_script_test_entry(self.source_var.get(), entry)
            script_text = self.script_test_path_var.get().strip()
            if not script_text:
                raise ValueError(f"{entry}路径为空，请重新选择入口")
            script_path = Path(script_text)
            if script_path.expanduser().resolve() != expected:
                raise ValueError(
                    f"当前 ECS 文件与{entry}不一致，请重新选择入口或切换为“自选 ECS”"
                )
        else:
            script_text = self.script_test_path_var.get().strip()
            if not script_text:
                raise ValueError("请先选择要直接运行的 .ecs 测试脚本")
            script_path = Path(script_text)
        backend = self.script_test_backend_var.get()
        ezcon_path = Path(self.ezcon_var.get())
        fingerprint_warning_only = self.advanced_mode_var.get()
        input_fingerprint = self.input_fingerprint()
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        self.project_main = None
        self.runtime_check = None
        self.set_busy(True, "正在原地预检所选 ECS 与 1.6.4-a 测试后端……")
        self.set_result(
            "高级测试不会生成或改写 main.ecs；正在检查原文件、直接标签引用和运行后端。"
        )

        def worker():
            try:
                preparation = prepare_script_test_runtime(
                    ezcon_path,
                    script_path,
                    backend,
                    fingerprint_warning_only=fingerprint_warning_only,
                )
                self.root.after(
                    0,
                    lambda: self.finish_script_test_preflight(
                        preparation,
                        input_fingerprint,
                    ),
                )
            except Exception as exc:
                self.root.after(0, lambda error=exc: self.fail_search(error))

        threading.Thread(target=worker, daemon=True).start()

    def finish_script_test_preflight(
        self,
        preparation: ScriptTestPreparation,
        input_fingerprint,
    ):
        if input_fingerprint != self.input_fingerprint():
            self.fail_search(ValueError("预检期间输入发生变化，请按当前选择重新预检。"))
            return
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.script_test_preparation = preparation
        self.project_main = preparation.script_path
        self.runtime_check = preparation.check
        lines = [
            "高级模式：直接 ECS 测试",
            f"2.0 脚本入口：{identify_script_test_entry(self.source_var.get(), preparation.script_path)}",
            f"脚本：{preparation.script_path}",
            f"工作目录：{preparation.project_dir}",
            f"运行后端：{preparation.backend}",
            f"实际执行文件：{preparation.runner_path or '(预检未通过)'}",
            f"直接标签引用：{len(preparation.label_references)} 个",
            "参数处理：无（不会修改、复制或重新生成所选 ECS）",
        ]
        if preparation.label_references:
            lines.append("标签：" + "、".join(preparation.label_references))
        if preparation.check.ok:
            lines.extend(
                f"预检提示：{warning}" for warning in preparation.check.warnings
            )
            status = "所选测试脚本已通过预检，可以直接运行。"
        else:
            lines.extend(
                f"预检失败：{error}" for error in preparation.check.errors
            )
            lines.extend(
                f"预检提示：{warning}" for warning in preparation.check.warnings
            )
            status = "所选测试脚本预检失败，已阻止启动。"
        self.set_result("\n".join(lines))
        self.set_busy(False, status)

    def generate_sid_project(self, request: SIDReverseRunRequest):
        source_path = Path(self.sid_source_var.get())
        ezcon_path = Path(self.ezcon_var.get())
        input_fingerprint = self.input_fingerprint()
        fingerprint_warning_only = self.advanced_mode_var.get()
        label_profile = self._active_label_profile()
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        self.project_main = None
        self.runtime_check = None
        self.set_busy(True, "正在生成 SID 采集脚本并执行 1.6.4-a 预检……")
        self.set_result("正在校验 SID 采集模板、识图标签和 EasyCon 1.6.4-a。")

        def worker():
            try:
                output = WRITABLE_ROOT / "runtime" / "sid_reverse"
                project_main = write_sid_reverse_project(source_path, output, request)
                if label_profile is not None:
                    apply_profile_to_projects(output, label_profile)
                check = validate_runtime(
                    ezcon_path,
                    project_main,
                    fingerprint_warning_only=fingerprint_warning_only,
                )
                self.root.after(
                    0,
                    lambda: self.finish_sid_generation(
                        request, project_main, check, input_fingerprint
                    ),
                )
            except Exception as exc:
                self.root.after(0, lambda error=exc: self.fail_search(error))

        threading.Thread(target=worker, daemon=True).start()

    def finish_sid_generation(
        self, request, project_main, check, input_fingerprint
    ):
        if input_fingerprint != self.input_fingerprint():
            self.fail_search(ValueError("生成期间输入发生变化，请按当前 SID 条件重新准备。"))
            return
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = request
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        self.project_main = project_main
        self.runtime_check = check
        active_slots = range(request.party_count)
        lines = [
            "SID 查找：EasyCon 逐只采集 + Python Method 1/2/4 反查",
            f"游戏：{'火红' if self.sid_game_var.get() == '火红' else '叶绿'}",
            f"主机：Switch {request.nx_model}",
            f"TID：{request.tid:05d}；队内闪光数量：{request.party_count}",
            f"每只最多糖果：{request.max_candies}；识图阈值：{request.recognition_threshold}",
            (
                "SID HOME_BUFFER 稳定低分自适应：开启（稳定 3 次、最低 90 分）"
                if request.home_buffer_adaptive_threshold
                else "SID HOME_BUFFER 稳定低分自适应：关闭（严格 95 分）"
            ),
            "图鉴覆盖：" + ", ".join(str(request.dex_overrides[index]) for index in active_slots),
            "来源：" + ", ".join(
                "野生" if request.source_types[index] else "定点"
                for index in active_slots
            ),
            f"生成脚本：{project_main}",
        ]
        if check.ok:
            lines.extend(f"预检提示：{warning}" for warning in check.warnings)
            lines.append("点击“开始运行”后会逐只采集；PSV 唯一时自动提前停止并生成报告。")
            status = "SID 采集脚本已准备，可以开始查找。"
        else:
            lines.extend(f"预检失败：{error}" for error in check.errors)
            status = "SID 采集脚本已生成，但预检不允许启动。"
        self.set_result("\n".join(lines))
        self.set_busy(False, status)

    def generate_tid_project(
        self,
        request: TidRngRequest,
        flow_request: TidStarterFlowRequest | None = None,
    ):
        source_path = Path(self.tid_source_var.get())
        starter_source_path = Path(self.source_var.get())
        ezcon_path = Path(self.ezcon_var.get())
        input_fingerprint = self.input_fingerprint()
        fingerprint_warning_only = self.advanced_mode_var.get()
        label_profile = self._active_label_profile()
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        self.project_main = None
        self.runtime_check = None
        status = (
            (
                "正在生成延后身份解析的 TID 阶段；御三家目标将在取得实际 TID/SID 后搜索……"
                if flow_request is not None and flow_request.deferred_identity
                else "正在搜索御三家目标并生成 TID/SID 连续流程计划……"
            )
            if flow_request is not None
            else "正在生成 TID/SID 1.3.7 脚本并执行 1.6.4-a 预检……"
        )
        self.set_busy(True, status)
        self.set_result(
            (
                (
                    (
                        (
                            "穷举阶段将输出实际 TID 和 SID ADV；运行时计算实际 SID 后，"
                            if flow_request.tid_request.mode == 0
                            else "不乱数 SID 阶段将输出实际 TID 和 SID ADV；运行时计算实际 SID 后，"
                        )
                        + "再搜索最早可达闪光御三家并生成 2.0 第三阶段。"
                    )
                    if flow_request.deferred_identity
                    else (
                        "正在搜索 ADV "
                        f"{flow_request.starter_min_advances}-"
                        f"{flow_request.starter_max_advances} 内最早可达闪光御三家，"
                        "并生成英文 TID、研究所桥接和 2.0 御三家三个阶段。"
                    )
                )
            )
            if flow_request is not None
            else "正在校验英文/日文模板、328 个标签和 EasyCon 1.6.4-a。"
        )

        def worker():
            try:
                fingerprint_warnings: list[str] = []
                flow_plan = None
                if flow_request is not None:
                    output = WRITABLE_ROOT / "runtime" / "tid_starter_flow"
                    flow_plan = build_tid_starter_flow_plan(flow_request)
                    write_tid_starter_flow_bundle(
                        source_path,
                        output,
                        flow_plan,
                        starter_source_dir=starter_source_path,
                        fingerprint_warning_only=fingerprint_warning_only,
                        fingerprint_warnings=fingerprint_warnings,
                    )
                    project_main = output / "01_id" / "main.ecs"
                else:
                    output = WRITABLE_ROOT / "runtime" / "tid_rng137"
                    project_main = write_configured_tid_project(
                        source_path,
                        output,
                        replace(request, calibration_check=False),
                        fingerprint_warning_only=fingerprint_warning_only,
                        fingerprint_warnings=fingerprint_warnings,
                    )
                if request.calibration_check:
                    write_configured_tid_project(
                        source_path,
                        output / "00_calibration",
                        request,
                        fingerprint_warning_only=fingerprint_warning_only,
                        fingerprint_warnings=fingerprint_warnings,
                    )
                if label_profile is not None:
                    apply_profile_to_projects(output, label_profile)
                check = validate_tid_plan_runtime(
                    ezcon_path, output, is_flow=flow_plan is not None,
                    calibrate_first=request.calibration_check,
                    fingerprint_warning_only=fingerprint_warning_only,
                )
                check = replace(
                    check,
                    warnings=tuple(dict.fromkeys(fingerprint_warnings)) + check.warnings,
                )
                plan_dir = WRITABLE_ROOT / "rng_logs" / "plans"
                plan_dir.mkdir(parents=True, exist_ok=True)
                plan_path = plan_dir / (
                    datetime.now().strftime("%Y%m%d_%H%M%S") + "_tid.json"
                )
                plan_payload = flow_plan.to_dict() if flow_plan is not None else request.to_dict()
                plan_path.write_text(
                    json.dumps(plan_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self.root.after(
                    0,
                    lambda: self.finish_tid_generation(
                        request,
                        flow_plan,
                        project_main,
                        check,
                        plan_path,
                        input_fingerprint,
                    ),
                )
            except Exception as exc:
                self.root.after(0, lambda error=exc: self.fail_search(error))

        threading.Thread(target=worker, daemon=True).start()

    def finish_tid_generation(
        self,
        request,
        flow_plan,
        project_main,
        check,
        plan_path,
        input_fingerprint,
    ):
        if input_fingerprint != self.input_fingerprint():
            self.fail_search(ValueError("生成期间输入发生变化，请按当前 TID/SID 参数重新生成。"))
            return
        self.plan_result = None
        self.egg_request = None
        self.tid_request = request
        self.tid_flow_plan = flow_plan
        self.sid_request = None
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        self.project_main = project_main
        self.runtime_check = check
        mode_name = "乱数模式" if request.mode == 1 else "穷举模式"
        generated_plan = json.loads(
            (project_main.parent / "plan.json").read_text(encoding="utf-8")
        )
        starter_save_template = generated_plan.get("tid_template_family") == "starter_save_164a"
        lines = [
            f"TID/SID 1.3.7：{request.language}版 / {mode_name}",
            f"实际模板：{generated_plan['template']}",
            f"目标 TID/SID：{request.target_tid:05d} / {request.target_sid:05d}",
            f"主角：{'男性' if request.gender == 0 else '女性'} / {request.player_name}",
            f"主机：Switch {request.nx_model}",
            f"中心帧 OP/F1/F2：{request.op_target_frame}/{request.f1_target_frame}/{request.f2_target_frame}",
            f"乱数半径 OP/F1/F2：{request.op_rng_range}/{request.f1_rng_range}/{request.f2_rng_range}",
            f"固定延迟 OP/F1/F2/F3：{request.op_fixed_delay}/{request.f1_fixed_delay}/{request.f2_fixed_delay}/{request.f3_fixed_delay}",
            f"固定延迟检查：{'开启' if request.calibration_check else '关闭'}",
            (
                "TID HOME_BUFFER 稳定低分自适应：开启（稳定 3 次、最低 90 分）"
                if request.home_buffer_adaptive_threshold
                else "TID HOME_BUFFER 稳定低分自适应：关闭（严格 95 分）"
            ),
            f"计划文件：{plan_path}",
            f"生成脚本：{project_main}",
        ]
        if starter_save_template:
            lines.append("已接入同步按键与同语言帧换算更新；首次使用新版建议勾选固定延迟检查。")
        if request.mode == 0:
            lines.append("穷举目标TID：" + ", ".join(f"{tid:05d}" for tid in request.exhaustive_targets))
            if request.auto_rng:
                lines.append(f"自动转乱数：同参数窗口内至少{request.near_tid_hits}次落在同目标±{request.near_tid_distance}内；"
                             f"切换后半径OP/F1/F2={request.auto_op_rng_range}/{request.auto_f1_rng_range}/{request.auto_f2_rng_range}。")
                lines.append("局部范围完整搜索一遍未命中则返回穷举；整窗口选择候选，最近16个完成区域随进度保存。")
        lines.append("越过可执行下限时只裁剪负向范围，保留正向范围；负半径归零，按步长2向下取偶数。")
        if request.calibration_check:
            lines.append("启动后先测量 OP/F1/F2/F3，自动回填实际 OP 修正并关闭检测，再生成、预检和执行正式计划；无需再次点击开始。")
        elif not starter_save_template and request.language == "日文":
            lines.append("兼容修正：已把日版 FOR $InputLen 改为 1.6.4-a 可编译的显式索引循环。")
        if flow_plan is not None:
            if flow_plan.request.tid_request.language == "日文":
                lines.append(
                    "日版御三家临时分支：Seed 模式 10（mono_h_a / HELP / 封面 A），"
                    "使用日版识图标签；识图失败不会默认判为天真。"
                )
            if flow_plan.request.accept_any_tid:
                condition = "通过原版去噪确认" if flow_plan.request.any_tid_require_denoise else "首次完整识别，不等待去噪"
                lines.append(f"TID 接续条件：任意合法 TID，{condition}；目标 TID 和特殊号码均不参与成功判定。")
            lines.extend(
                (
                    f"御三家 Seed 校准方案：固定方案 {STARTER_SEED_CALIBRATION_SCHEME}（当前正式方案）",
                    (
                        "御三家 Seed 启动方案：固定用户界面 HOME（方案 1）"
                        if flow_plan.request.starter_seed_startup_scheme == 1
                        else "御三家 Seed 启动方案：当前 HOME_BUFFER（方案 0）"
                    ),
                    (
                        "御三家脚本入口：正式版"
                        if flow_plan.request.starter_template_name == STANDARD_TEMPLATE_NAME
                        else "御三家脚本入口：时间轴版"
                    ),
                    (
                        "御三家自动更新预校准：开启（独立于普通定点和 TID/SID）"
                        if flow_plan.request.update_precalibration
                        else "御三家自动更新预校准：关闭"
                    ),
                )
            )
            target = flow_plan.starter_target
            if target is None:
                deferred_label = (
                    "穷举动态衔接"
                    if flow_plan.request.tid_request.mode == 0
                    else "不乱数 SID 动态衔接"
                )
                lines.extend(
                    (
                        f"连续流程：{flow_plan.request.version} / {flow_plan.request.starter} / {deferred_label}",
                        f"御三家游戏设置：{flow_plan.request.starter_settings}",
                        (
                            "御三家搜索：取得实际 TID 和 SID ADV 后计算实际 SID，再在 ADV "
                            f"{flow_plan.request.starter_min_advances}-"
                            f"{flow_plan.request.starter_max_advances} 内搜索最早闪光目标"
                        ),
                        "F3：固定延迟；随机F3模式已移除",
                        f"ID 阶段：{project_main}",
                        f"研究所桥接：{project_main.parents[1] / '02_lab_bridge' / 'main.ecs'}",
                        "2.0 御三家：运行时按实际 TID/SID 生成并立即预检",
                    )
                )
            else:
                iv_text = "/".join(str(value) for value in target.ivs)
                retry_preview = ", ".join(
                    f"{value:+d}" for value in flow_plan.sid_retry_corrections[:9]
                )
                lines.extend(
                    (
                        f"连续流程：{flow_plan.request.version} / {target.species_zh} ({target.species_en})",
                        f"御三家游戏设置：{flow_plan.request.starter_settings}",
                        (
                            "御三家搜索：ADV "
                            f"{flow_plan.request.starter_min_advances}-"
                            f"{flow_plan.request.starter_max_advances}；"
                            "Seed 时间直接取 Ten Lines Seed 表"
                        ),
                        f"御三家目标：Seed {target.seed_hex} / {target.seed_time_ms} ms / ADV {target.advances}",
                        f"目标 PID：{target.pid_hex}；IV：{iv_text}",
                        f"TID 链首个目标 SID ADV：{flow_plan.earliest_sid_chain_advance}",
                        f"SID ADV 重试顺序：{retry_preview} ...",
                        f"ID 阶段：{project_main}",
                        f"研究所桥接：{project_main.parents[1] / '02_lab_bridge' / 'main.ecs'}",
                        f"2.0 御三家：{project_main.parents[1] / '03_starter_118' / 'main.ecs'}",
                    )
                )
                lines.extend(
                    self._precalibration_plan_lines(
                        project_main.parents[1] / "03_starter_118" / "main.ecs"
                    )
                )
        if check.ok and flow_plan is None:
            lines.extend(f"预检提示：{warning}" for warning in check.warnings)
            status = "TID/SID 脚本已生成，可以在确认会新建存档后开始。"
        elif check.ok:
            lines.extend(f"预检提示：{warning}" for warning in check.warnings)
            status = (
                (
                    "穷举连续流程前两阶段已通过预检；第三阶段将在取得实际 TID/SID 后生成并预检。"
                    if flow_plan.request.tid_request.mode == 0
                    else "不乱数 SID 连续流程前两阶段已通过预检；第三阶段将在取得实际 TID/SID 后生成并预检。"
                )
                if flow_plan.starter_target is None
                else "连续流程三阶段均已生成并通过预检，可以开始运行。"
            )
        else:
            lines.extend(f"预检失败：{error}" for error in check.errors)
            status = "TID/SID 脚本已生成，但预检不允许启动。"
        self.set_result("\n".join(lines))
        self.set_busy(False, status)

    def generate_egg_project(self, request: EggRunRequest):
        source_path = Path(self.source_var.get())
        ezcon_path = Path(self.ezcon_var.get())
        template_name = self._selected_generation_template_name()
        input_fingerprint = self.input_fingerprint()
        fingerprint_warning_only = self.advanced_mode_var.get()
        label_profile = self._active_label_profile()
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        self.project_main = None
        self.runtime_check = None
        self.set_busy(True, "正在生成孵蛋脚本并执行 EasyCon 1.6.4-a 预检……")
        self.set_result("孵蛋模式使用 Ten Lines 已选出的同 Seed / Held / Pickup，不重复搜索目标。")

        def worker():
            try:
                output = WRITABLE_ROOT / "runtime" / "easycon118"
                def generate(staging_dir):
                    staged_main = write_configured_egg_project(
                        source_path,
                        staging_dir,
                        request,
                        template_name=template_name,
                    )
                    if label_profile is not None:
                        apply_profile_to_projects(staging_dir, label_profile)
                    return staged_main

                project_main, check = _generate_runtime_project_atomically(
                    output,
                    generate,
                    lambda staged_main: validate_generated_egg_project_consistency(
                        staged_main,
                        request,
                        template_name=template_name,
                    ),
                    lambda staged_main: validate_runtime(
                        ezcon_path,
                        staged_main,
                        fingerprint_warning_only=fingerprint_warning_only,
                    ),
                )
                plan_dir = WRITABLE_ROOT / "rng_logs" / "plans"
                plan_dir.mkdir(parents=True, exist_ok=True)
                plan_path = plan_dir / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_egg.json")
                plan_path.write_text(
                    json.dumps(request.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self.root.after(
                    0,
                    lambda: self.finish_egg_generation(
                        request, project_main, check, plan_path, input_fingerprint
                    ),
                )
            except Exception as exc:
                self.root.after(0, lambda error=exc: self.fail_search(error))

        threading.Thread(target=worker, daemon=True).start()

    def finish_egg_generation(
        self, request, project_main, check, plan_path, input_fingerprint
    ):
        if input_fingerprint != self.input_fingerprint():
            self.fail_search(ValueError("生成期间输入发生变化，请按当前孵蛋参数重新生成。"))
            return
        self.plan_result = None
        self.egg_request = request
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        usable_project = project_main if project_main is not None and check and check.ok else None
        self.project_main = usable_project
        self.runtime_check = check
        pokemon = get_species_name(request.species_id)
        selected_template = self._selected_generation_template_name()
        entry_description = (
            "正式版（普通 WAIT）"
            if selected_template == STANDARD_TEMPLATE_NAME
            else "时间轴版"
        )
        lines = [
            f"孵蛋模式：同 Seed {entry_description}",
            (
                "启动准备：从已完成 254 步的基础存档开始"
                if request.start_from_prepared_254
                else "启动准备：完整准备（自动走 254 步、检查设置并存档）"
            ),
            f"蛋种：{SPECIES_EN_TO_ZH.get(pokemon, pokemon)} ({pokemon})",
            f"目标 Seed：{request.normalized_seed}，Seed 模式：{request.seed_mode}",
            (
                "Seed 启动：固定用户界面 HOME（关闭游戏识图保持原样）"
                if request.seed_startup_scheme == 1
                else "Seed 启动：当前 HOME_BUFFER（原样）"
            ),
            f"Seed 校准方案：{request.seed_calibration_scheme}",
            f"Held/生成帧：{request.held_advances}",
            f"Pickup/领取帧：{request.pickup_advances}",
            f"双亲相性：{request.compatibility}",
            f"亲本A：{request.parent_a_gender} {request.parent_a_ivs}",
            f"亲本B：{request.parent_b_gender} {request.parent_b_ivs}",
            f"计划文件：{plan_path}",
            (
                "注意：当前使用正式脚本的普通 WAIT；尚未完成本机实机验收。"
                if selected_template == STANDARD_TEMPLATE_NAME
                else "注意：当前使用时间轴脚本；尚未完成本机实机验收。"
            ),
        ]
        if usable_project is not None:
            lines.insert(-1, f"生成脚本：{usable_project}")
            lines.extend(self._precalibration_plan_lines(usable_project))
        if check and check.ok and usable_project is not None:
            lines.extend(f"预检提示：{warning}" for warning in check.warnings)
            status = "孵蛋脚本已生成，可以在确认存档准备后开始。"
        elif check:
            lines.extend(f"预检失败：{error}" for error in check.errors)
            status = "孵蛋脚本已生成，但预检不允许启动。"
        else:
            status = "孵蛋脚本生成失败，未启用旧运行项目。"
        self.set_result("\n".join(lines))
        self.set_busy(False, status)

    def finish_search(
        self, result, project_main, check, plan_path, input_fingerprint,
        generation_error=None, cancel_event=None,
    ):
        self.search_cancel = None
        self.cancel_button.configure(state="disabled")
        if cancel_event is not None and cancel_event.is_set():
            self.fail_search(SearchCancelledError("操作已由用户取消"))
            return
        if input_fingerprint != self.input_fingerprint():
            self.fail_search(ValueError("搜索期间输入发生变化，请按当前条件重新搜索。"))
            return
        self.plan_result = result
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        usable_project = project_main
        if generation_error is not None or not (check and check.ok):
            usable_project = None
        self.project_main = usable_project
        self.runtime_check = check
        plan = result.plan
        ivs = plan.target.ivs
        direct_mode = plan.request.direct_mode
        lines = [
            (
                f"指定目标：{plan.request.pokemon} / Seed {plan.initial_seed.seed} / "
                f"Advance {plan.initial_seed.advances}"
                if direct_mode
                else f"最优结果：{plan.request.pokemon} / {plan.target.nature} / {plan.target.shiny}"
            ),
            f"IV：{ivs.hp}/{ivs.attack}/{ivs.defense}/{ivs.sp_attack}/{ivs.sp_defense}/{ivs.speed}",
            f"IV 总和：{plan.iv_total}，平均：{plan.iv_average:.2f}",
            f"目标状态 Seed：{plan.target.target_seed}（{plan.target.method}）",
            f"初始 Seed：{plan.initial_seed.seed}",
            f"Advance：{plan.initial_seed.advances}",
            f"Seed 模式：{plan.seed_mode}",
            f"Seed 启动：{self.seed_startup_scheme_var.get()}",
            f"Seed 校准方案：{self.seed_calibration_scheme_var.get()}",
            f"脚本入口：{self.script_test_entry_var.get()}",
            (
                "指定模式：已跳过筛选搜索"
                if direct_mode
                else f"扫描候选：{result.matching_outcomes}，可行路线：{result.feasible_routes}"
            ),
            f"路线状态：{plan.route_support.level.value}",
            f"出闪后处理：{'自动抓捕' if self.auto_capture_var.get() else '停止并交给用户'}",
            (
                f"道具乱数：开启（队伍空位 {self.party_empty_slots_var.get()}）"
                if self.method_var.get() == "野生" and self.item_rng_mode_var.get()
                else "道具乱数：关闭"
            ),
            f"计划文件：{plan_path}",
        ]
        lines.extend(self._precalibration_plan_lines(project_main))
        lines.extend(f"注意：{warning}" for warning in plan.warnings)
        if not plan.route_support.can_start:
            lines.append("此路线仅允许搜索，初版已阻止自动启动。")
        elif generation_error is not None:
            lines.append(f"搜索方案已保存，但 ECS 生成/预检失败：{generation_error}")
        elif check and not check.ok:
            lines.extend(f"预检失败：{error}" for error in check.errors)
        else:
            lines.append(f"生成脚本：{usable_project}")
            if check:
                lines.extend(f"预检提示：{warning}" for warning in check.warnings)
            if plan.request.category.endswith("Rod") and "Safari Zone" in plan.request.location:
                lines.append("启动前确认：所选钓竿已登录到 Y；2.0 脚本实际复用中央钓点路线。")
        self.set_result("\n".join(lines))
        can_start = bool(
            usable_project and check and check.ok
            and generation_error is None and plan.route_support.can_start
        )
        self.set_busy(False, "方案已生成，可以开始。" if can_start else "方案已生成，但当前路线/预检不允许启动。")

    def fail_search(self, error):
        self.search_cancel = None
        self.cancel_button.configure(state="disabled")
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.sid_traversal_request = None
        self.sid_traversal_options = None
        self.sid_traversal_context = None
        self.sid_traversal_plan_path = None
        self.script_test_preparation = None
        self.project_main = None
        self.runtime_check = None
        self.start_button.configure(state="disabled")
        if isinstance(error, SearchCancelledError):
            self.set_result("搜索已取消，未修改现有 EasyCon 运行状态。")
            self.set_busy(False, "搜索已取消。")
        else:
            self.set_result(f"生成失败：{error}")
            self.set_busy(False, "没有生成可运行方案。")

    def cancel_search(self):
        if self.search_cancel is not None:
            self.search_cancel.set()
            self.cancel_button.configure(state="disabled")
            self.status_var.set("正在取消搜索……")

    def check_devices(self, initial=False):
        if self.busy:
            return
        if self.process is not None and self.process.poll() is None:
            if not initial:
                messagebox.showerror("正在运行", "EasyCon 正在运行，停止后才能重新检测设备。")
            return
        self._close_manual_tools()
        ezcon = Path(self.ezcon_var.get())
        if not ezcon.is_file():
            self._device_check_in_progress = False
            if initial:
                self.fail_device_check(FileNotFoundError(f"找不到 {ezcon}"))
            else:
                messagebox.showerror("找不到程序", f"找不到 {ezcon}")
            return
        current_port = self.port_var.get()
        current_video = self.video_var.get()
        self._device_check_in_progress = True
        self.set_busy(True, "正在读取端口和采集设备……")

        def worker():
            try:
                ports, videos, output = probe_easycon_devices(
                    ezcon,
                    include_video_names=True,
                )
                selected_port = preferred_detected_port(ports, current_port)
                selected_video = preferred_detected_video(videos, current_video)
                self.root.after(
                    0,
                    lambda: self.finish_device_check(
                        output,
                        ports,
                        videos,
                        selected_port,
                        selected_video,
                    ),
                )
            except Exception as exc:
                self.root.after(0, lambda error=exc: self.fail_device_check(error))

        threading.Thread(target=worker, daemon=True).start()

    def finish_device_check(
        self,
        output,
        ports,
        videos,
        selected_port,
        selected_video,
    ):
        self._device_check_in_progress = False
        port_choices = sorted(
            ports,
            key=lambda port: (
                0,
                int(port[3:]),
            ) if port.startswith("COM") and port[3:].isdigit() else (1, port),
        )
        video_choices = [
            format_video_device_choice(index, videos[index])
            for index in sorted(videos)
        ]
        self.port_combo.configure(values=port_choices)
        self.video_combo.configure(values=video_choices)
        if selected_port:
            self.port_var.set(selected_port)
        else:
            self.port_var.set("")
        if selected_video:
            self.video_var.set(selected_video)
        else:
            self.video_var.set("")
        self.refresh_device_label_profile()

        selections = []
        if selected_port:
            selections.append(f"串口 {selected_port}")
        if selected_video:
            selections.append(f"采集卡 {selected_video}")
        if selections:
            summary = "；".join(selections)
            output = f"当前选择：{summary}\n\n{output}"
            status = f"设备检测完成：{summary}。"
        else:
            output = "没有检测到可用串口或采集设备。\n\n" + output
            status = "设备检测完成，但没有发现可用设备。"
        self.set_result(output)
        self.set_busy(False, status)

    def fail_device_check(self, error):
        self._device_check_in_progress = False
        self.set_result(f"设备检测失败：{error}")
        self.set_busy(False, "设备检测失败，现有乱数方案未被清除。")

    def start_run(self):
        if not (
            self.plan_result
            or self.egg_request
            or self.tid_request
            or self.sid_request
            or self.sid_traversal_request
            or self.script_test_preparation
        ) or not self.project_main:
            return
        try:
            video_device = parse_video_device(self.video_var.get())
        except ValueError:
            messagebox.showerror("输入错误", "请选择有效的采集卡。")
            return
        if not self.port_var.get().strip():
            messagebox.showerror("输入错误", "串口不能为空。")
            return
        fingerprint_warning_only = self.advanced_mode_var.get()
        self._close_manual_tools()
        try:
            ports, videos, _ = probe_easycon_devices(Path(self.ezcon_var.get()))
        except Exception as exc:
            messagebox.showerror("设备预检失败", str(exc))
            return
        selected_port = self.port_var.get().strip().upper()
        if selected_port not in ports:
            messagebox.showerror(
                "串口未连接",
                f"EasyCon 当前没有列出 {selected_port}。请连接单片机后点击“检测端口/采集卡”。",
            )
            return
        if video_device not in videos:
            messagebox.showerror(
                "采集卡不可用",
                f"EasyCon 当前没有列出采集卡序号 {video_device}。请重新检测并选择正确序号。",
            )
            return
        if self.script_test_preparation is not None:
            preparation = prepare_script_test_runtime(
                Path(self.ezcon_var.get()),
                Path(self.script_test_path_var.get()),
                self.script_test_backend_var.get(),
                fingerprint_warning_only=fingerprint_warning_only,
            )
            self.script_test_preparation = preparation
            self.project_main = preparation.script_path
            check = preparation.check
        elif self.sid_traversal_request is not None:
            preparation = prepare_script_test_runtime(
                Path(self.ezcon_var.get()),
                Path(self.source_var.get()).resolve() / STANDARD_TEMPLATE_NAME,
                SCRIPT_TEST_BACKEND_COMPAT,
                fingerprint_warning_only=fingerprint_warning_only,
            )
            check = preparation.check
        elif self.tid_request is not None:
            is_flow = self.tid_flow_plan is not None
            check = validate_tid_plan_runtime(
                Path(self.ezcon_var.get()),
                self.project_main.parents[1] if is_flow else self.project_main.parent,
                is_flow=is_flow, calibrate_first=self.tid_request.calibration_check,
                fingerprint_warning_only=fingerprint_warning_only,
            )
        else:
            check = validate_runtime(
                Path(self.ezcon_var.get()),
                self.project_main,
                fingerprint_warning_only=fingerprint_warning_only,
            )
        self.runtime_check = check
        if not check.ok:
            messagebox.showerror("预检失败", "\n".join(check.errors))
            self.start_button.configure(state="disabled")
            return
        if self.script_test_preparation is not None:
            confirmation = (
                "将直接执行所选 ECS，不进行参数替换或正式脚本生成。\n"
                f"脚本：{self.script_test_preparation.script_path}\n"
                f"后端：{self.script_test_preparation.backend}\n"
                f"串口 {selected_port} / 采集卡 {video_device} / DSHOW\n"
                "测试脚本拥有完整手柄控制权限；确认已检查脚本内容、游戏位置和存档状态，是否继续？"
            )
        elif self.sid_traversal_request is not None:
            context = self.sid_traversal_context or {}
            progress = self._sid_traversal_progress_text(context)
            confirmation = (
                "将按已保存断点逐个尝试野生闪光目标，直到确认闪光并反推出正确 SID。\n"
                f"TID {self.sid_traversal_request.tid:05d} / "
                f"劲敌取名 {'是' if self.sid_traversal_named_rival else '否'} / "
                f"SID ADV {context.get('start_sid_advance', '?')}-{context.get('max_advances', '?')} / "
                f"仅{'偶数' if context.get('sid_advance_parity') == 0 else '奇数'} ADV，步长 2\n"
                f"目标搜索 ADV {((context.get('wild_request') or {}).get('min_advances', 0))}-"
                f"{context.get('target_max_advances', '?')}\n"
                f"{progress}\n"
                "每个候选会从当前存档重新执行；明确未出闪才推进起点，停止或异常会保留当前候选。"
                "请确认存档、路线、宝可梦和 TID 均正确，是否继续？"
            )
        elif self.sid_request is not None:
            confirmation = (
                "将逐只启动 SID 采集脚本，并在每只结束后由 Python 反查 PID/PSV。\n"
                f"TID {self.sid_request.tid:05d} / "
                f"队伍前 {self.sid_request.party_count} 只闪光宝可梦\n"
                "每只都会从当前存档重新开始；确认队伍顺序、来源、努力值和神奇糖果位置均正确，是否继续？"
            )
        elif self.tid_flow_plan is not None:
            target = self.tid_flow_plan.starter_target
            if target is None:
                deferred_stage = (
                    "穷举 TID"
                    if self.tid_flow_plan.request.tid_request.mode == 0
                    else "不乱数 SID 的 TID 乱数"
                )
                condition = (
                    ("第一阶段取得任意合法 TID 后（忽略目标 TID 及特殊号码；"
                     + ("等待去噪确认" if self.tid_flow_plan.request.any_tid_require_denoise else "首次完整识别即继续，不等待去噪")
                     + "），")
                    if self.tid_flow_plan.request.accept_any_tid
                    else "第一阶段命中启用的 TID 条件后，"
                )
                confirmation = (
                    f"将运行{deferred_stage} → 动态计算实际 SID → 研究所桥接 → 2.0 御三家流程。\n"
                    + condition + "工具读取实际 TID 和 SID ADV，"
                    "计算实际 SID 并搜索最早闪光御三家；第三阶段届时生成并预检。\n"
                    f"{self.tid_flow_plan.request.version} / {self.tid_flow_plan.request.starter} / "
                    f"ADV {self.tid_flow_plan.request.starter_min_advances}-"
                    f"{self.tid_flow_plan.request.starter_max_advances}\n"
                    "第一阶段会新建存档；确认当前存档可以被替代，是否继续？"
                )
            else:
                confirmation = (
                    "将依次运行三个阶段：TID/SID 1.3.7 → 研究所桥接存档 → 2.0 御三家流程。\n"
                    f"目标 TID/SID {self.tid_request.target_tid:05d} / {self.tid_request.target_sid:05d}\n"
                    f"{self.tid_flow_plan.request.version} / {target.species_zh} / "
                    f"Seed {target.seed_hex} / ADV {target.advances}\n"
                    "第一阶段会新建存档；第二阶段会自动走到御三家前并存档；"
                    "第三阶段由 2.0 脚本负责领取、识别和校准。若精确命中但不闪，"
                    "程序会按 SID ADV 重试范围重新执行三段。是否继续？"
                )
        elif self.tid_request is not None:
            confirmation = (
                "将启动 TID/SID 1.3.7 脚本并控制游戏新建存档。\n"
                f"{self.tid_request.language}版 / "
                f"{'乱数模式' if self.tid_request.mode == 1 else '穷举模式'} / "
                f"目标 TID {self.tid_request.target_tid:05d}\n"
                "脚本会自动退出游戏两次；确认当前存档可以被新建流程替代，且主页、名称、性别和固定延迟均正确，是否继续？"
            )
        elif self.egg_request is not None:
            preparation = (
                "本次会跳过 254 步走位、设置检查和存档；请确认当前存档确实是已完成 254 步准备的基础档。"
                if self.egg_request.start_from_prepared_254
                else "本次会自动完成 254 步走位、设置检查并建立基础存档。"
            )
            selected_entry = self._selected_generation_template_name()
            egg_entry = (
                "正式版（普通 WAIT）"
                if selected_entry == STANDARD_TEMPLATE_NAME
                else "时间轴版"
            )
            confirmation = (
                f"将启动 {SCRIPT_FLOW_UI_NAME}的同 Seed 孵蛋{egg_entry}流程。\n"
                f"Seed {self.egg_request.normalized_seed} / Held {self.egg_request.held_advances} / "
                f"Pickup {self.egg_request.pickup_advances}\n"
                f"{preparation}\n"
                "确认已在培育屋内按脚本要求存档、队伍保留两个空位、队首可使用甜甜香气，是否继续？"
            )
        else:
            confirmation = (
                f"将启动 EasyCon CLI 并控制 {self.port_var.get()} / 采集卡 {self.video_var.get()}。\n"
                f"本方案使用 Seed 模式 {self.plan_result.plan.seed_mode}："
                f"{self.plan_result.plan.initial_seed.settings}\n"
                f"请确认游戏设置、存档位置和 NS 主页状态均符合 {SCRIPT_FLOW_UI_NAME}要求，是否继续？"
            )
        if self.tid_request is not None and self.tid_request.calibration_check:
            confirmation = (
                "已开启固定延迟检测：先执行检测，再自动回填四项延迟与实际 OP 修正，"
                "重新生成并预检下述计划，通过后自动继续；不会再次询问。\n\n" + confirmation
            )
        fingerprint_warnings = [
            warning for warning in check.warnings
            if warning.startswith("高级模式指纹警告：")
        ]
        if fingerprint_warnings:
            confirmation = (
                "高级模式已将以下指纹不一致降级为警告：\n"
                + "\n".join(f"- {warning}" for warning in fingerprint_warnings)
                + "\n\n"
                + confirmation
            )
        if not messagebox.askyesno(
            "开始全自动流程",
            confirmation,
        ):
            return
        self.preview_url = None
        self.tid_calibration_result_path = None
        self.tid_calibration_snapshot = None
        self.tid_calibration_applied = False
        preview_url: str | None = None
        if self.script_test_preparation is not None:
            runner_path = self.script_test_preparation.runner_path
            if runner_path is None:
                messagebox.showerror("启动后端检查失败", "测试后端没有可执行文件。")
                return
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_dir = WRITABLE_ROOT / "runtime" / "script_tests" / "logs"
            backend_tag = (
                "compat"
                if self.script_test_preparation.backend == SCRIPT_TEST_BACKEND_COMPAT
                else "original"
            )
            self.script_test_log_path = (
                log_dir / f"script-test-{backend_tag}-{timestamp}.log"
            )
            preview_port = allocate_preview_port() if backend_tag == "compat" else 0
            preview_url = (
                f"http://127.0.0.1:{preview_port}/mjpeg" if preview_port else None
            )
            easycon_command = build_run_command(
                runner_path,
                self.project_main,
                port=selected_port,
                video_device=video_device,
                video_type="DSHOW",
                verbose=self.script_test_verbose_var.get(),
                preview_port=preview_port,
            )
            metadata_path = self.script_test_log_path.with_suffix(".json")
            try:
                metadata_path.parent.mkdir(parents=True, exist_ok=True)
                metadata_path.write_text(
                    json.dumps(
                        {
                            "entry": self.script_test_entry_var.get(),
                            "script": str(self.project_main),
                            "script_sha256": hashlib.sha256(
                                self.project_main.read_bytes()
                            ).hexdigest(),
                            "backend": self.script_test_preparation.backend,
                            "runner": str(runner_path),
                            "port": selected_port,
                            "video_device": video_device,
                            "video_type": "DSHOW",
                            "verbose": self.script_test_verbose_var.get(),
                            "preview_port": preview_port,
                            "command": easycon_command,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError as exc:
                messagebox.showerror("测试日志准备失败", str(exc))
                return
            command = build_worker_command("easycon-log", [
                "--log-path",
                str(self.script_test_log_path),
                "--cwd",
                str(self.project_main.parent),
                "--",
                *easycon_command,
            ])
            command_cwd = ROOT
            self.running_mode = "script_test"
        elif self.sid_traversal_request is not None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            output_dir = WRITABLE_ROOT / "runtime" / "sid_traversal"
            self.sid_traversal_log_path = output_dir / f"sid-traversal-{timestamp}.log"
            self.sid_traversal_report_path = output_dir / f"sid-traversal-{timestamp}.json"
            self.running_log_snapshot = ""
            preview_port = allocate_preview_port()
            preview_url = f"http://127.0.0.1:{preview_port}/mjpeg"
            plan_path = self.sid_traversal_plan_path
            context = self.sid_traversal_context or {}
            if plan_path is None:
                messagebox.showerror("SID 遍历启动失败", "缺少 SID 遍历计划文件，请重新生成。")
                return
            command = build_worker_command("sid-traversal", [
                "--request-json",
                str(plan_path),
                "--source",
                self.source_var.get(),
                "--ezcon",
                self.ezcon_var.get(),
                "--output",
                str(output_dir),
                "--progress-dir",
                str(SID_TRAVERSAL_PROGRESS_DIR),
                "--port",
                selected_port,
                "--video",
                str(video_device),
                "--log-path",
                str(self.sid_traversal_log_path),
                "--report-path",
                str(self.sid_traversal_report_path),
                "--max-advances",
                str(context.get("max_advances", SID_TRAVERSAL_DEFAULT_MAX_ADVANCES)),
                "--target-max-advances",
                str(context.get("target_max_advances", SID_TRAVERSAL_TARGET_MAX_ADVANCES)),
                "--preview-port",
                str(preview_port),
            ])
            if self.sid_traversal_named_rival:
                command.append("--named-rival")
            if context.get("start_sid_advance") is not None:
                command.extend(["--start-advance", str(context["start_sid_advance"])])
            if fingerprint_warning_only:
                command.append("--fingerprint-warnings")
            try:
                label_profile = self._active_label_profile()
            except ValueError as exc:
                self.running_mode = None
                messagebox.showerror("设备标签配置错误", str(exc))
                return
            if label_profile is not None:
                command.extend(["--label-override-profile", str(label_profile.directory)])
            command_cwd = ROOT
            self.running_mode = "sid_traversal"
        elif self.sid_request is not None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = self.project_main.parent
            try:
                write_sid_reverse_plan(
                    self.sid_source_var.get(),
                    output_dir,
                    self.sid_request,
                )
            except (OSError, ValueError) as exc:
                messagebox.showerror("SID 计划写入失败", str(exc))
                return
            self.sid_log_path = output_dir / f"sid-reverse-{timestamp}.log"
            self.sid_report_path = output_dir / f"sid-reverse-{timestamp}.txt"
            self.running_log_snapshot = ""
            preview_port = allocate_preview_port()
            preview_url = f"http://127.0.0.1:{preview_port}/mjpeg"
            command = build_worker_command("sid-capture", [
                "--request-json",
                str(output_dir / "plan.json"),
                "--game",
                "fr_nx" if self.sid_game_var.get() == "火红" else "lg_nx",
                "--source",
                self.sid_source_var.get(),
                "--ezcon",
                self.ezcon_var.get(),
                "--output",
                str(output_dir),
                "--port",
                selected_port,
                "--video",
                str(video_device),
                "--log-path",
                str(self.sid_log_path),
                "--report-path",
                str(self.sid_report_path),
                "--preview-port",
                str(preview_port),
            ])
            if fingerprint_warning_only:
                command.append("--fingerprint-warnings")
            command_cwd = ROOT
            self.running_mode = "sid"
        elif self.tid_request is not None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            is_flow = self.tid_flow_plan is not None
            flow_dir = self.project_main.parents[1] if is_flow else self.project_main.parent
            log_path = flow_dir / f"tid-{'starter' if is_flow else 'run'}-{timestamp}.log"
            if is_flow:
                self.tid_flow_log_path = log_path
            else:
                self.tid_log_path = log_path
            preview_port = allocate_preview_port()
            preview_url = f"http://127.0.0.1:{preview_port}/mjpeg"
            command = build_worker_command("tid-flow", [
                "--flow-dir" if is_flow else "--tid-dir",
                str(flow_dir),
                "--ezcon",
                self.ezcon_var.get(),
                "--port",
                selected_port,
                "--video",
                str(video_device),
                "--log-path",
                str(log_path),
                "--preview-port",
                str(preview_port),
            ])
            if fingerprint_warning_only:
                command.append("--fingerprint-warnings")
            try:
                label_profile = self._active_label_profile()
            except ValueError as exc:
                self.running_mode = None
                messagebox.showerror("设备标签配置错误", str(exc))
                return
            if label_profile is not None:
                command.extend(
                    ["--label-override-profile", str(label_profile.directory)]
                )
            if progress_supported(replace(self.tid_request, calibration_check=False)):
                command.extend(["--tid-progress-dir", str(TID_PROGRESS_DIR),
                                "--tid-game", self.tid_game_var.get()])
                if not self.tid_resume_var.get():
                    command.append("--fresh-exhaustive")
            if self.tid_request.calibration_check:
                self.tid_calibration_result_path = log_path.with_suffix(".calibration.json")
                self.tid_calibration_snapshot = self.tid_request
                self.tid_calibration_input_fingerprint = self.input_fingerprint()
                command.extend(["--calibrate-first", "--calibration-result", str(self.tid_calibration_result_path)])
                self._tid_pending_calibration = {
                    "path": str(self.tid_calibration_result_path),
                    "request": self.tid_request.to_dict(),
                    "values": self._tid_settings_fingerprint(),
                }
            else:
                self._tid_pending_calibration = None
            command_cwd = ROOT
            self.running_mode = "tid_flow" if is_flow else "tid"
        else:
            runner_fingerprint_warnings: list[str] = []
            try:
                runner_path = prepare_compat_runner(
                    Path(self.ezcon_var.get()),
                    fingerprint_warning_only=fingerprint_warning_only,
                    fingerprint_warnings=runner_fingerprint_warnings,
                )
            except (OSError, ValueError, RuntimeError) as exc:
                messagebox.showerror("启动后端检查失败", str(exc))
                return
            if runner_fingerprint_warnings:
                messagebox.showwarning(
                    "高级模式指纹警告",
                    "\n".join(runner_fingerprint_warnings),
                )
            preview_port = allocate_preview_port()
            preview_url = f"http://127.0.0.1:{preview_port}/mjpeg"
            easycon_command = build_run_command(
                runner_path,
                self.project_main,
                port=selected_port,
                video_device=video_device,
                video_type="DSHOW",
                preview_port=preview_port,
            )
            if self.egg_request is not None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.egg_log_path = self.project_main.parent / f"egg-{timestamp}.log"
                command = build_worker_command("easycon-log", [
                    "--log-path",
                    str(self.egg_log_path),
                    "--cwd",
                    str(self.project_main.parent),
                    "--expected-marker",
                    "孵蛋流程完成",
                    "--expected-marker",
                    "孵蛋流程失败",
                    "--expected-marker",
                    "孵蛋流程测试完成",
                    "--expected-marker",
                    "孵蛋流程测试失败",
                    "--",
                    *easycon_command,
                ])
                command_cwd = ROOT
                self.running_mode = "egg"
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.easycon_log_path = (
                    self.project_main.parent / f"easycon-{timestamp}.log"
                )
                command = build_worker_command("easycon-log", [
                    "--log-path",
                    str(self.easycon_log_path),
                    "--cwd",
                    str(self.project_main.parent),
                    "--",
                    *easycon_command,
                ])
                command_cwd = ROOT
                self.running_mode = "easycon"
        if self.running_mode in ("tid", "tid_flow"):
            try:
                arguments = self._tid_record_arguments(self._current_running_log_path())
                if "--" in command:
                    separator = command.index("--")
                    command[separator:separator] = arguments
                else:
                    command.extend(arguments)
            except (OSError, ValueError) as exc:
                self.running_mode = None
                messagebox.showerror("TID 记录准备失败", str(exc))
                return
        log_path = self._current_running_log_path()
        self.stop_request_path = log_path.with_name(log_path.name + "." + uuid.uuid4().hex + ".stop")
        stop_arguments = ["--stop-file", str(self.stop_request_path)]
        if "--" in command:
            command[command.index("--"):command.index("--")] = stop_arguments
        else:
            command.extend(stop_arguments)
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.manual_tools.close_monitor()
        try:
            self.process = subprocess.Popen(command, cwd=str(command_cwd), creationflags=flags)
        except OSError as exc:
            self.running_mode = None
            messagebox.showerror("启动失败", str(exc))
            return
        self.preview_url = preview_url
        self.running_tid_exhaustive = bool(self.tid_request and progress_supported(replace(self.tid_request, calibration_check=False)))
        self.close_when_stopped = False
        self._save_tid_settings()
        self.start_button.configure(state="disabled")
        self.search_button.configure(state="disabled")
        self.device_button.configure(state="disabled")
        self._refresh_manual_tools_buttons()
        self.stop_button.configure(state="normal")
        self.running_log_snapshot = ""
        running_log_path = self._current_running_log_path()
        self.set_run_log(
            "自动流程已启动，正在等待运行输出……"
            + (f"\n日志文件：{running_log_path}" if running_log_path else "")
        )
        self.show_run_log_tab()
        self.status_var.set(
            f"测试脚本正在直接运行；日志将保存到 {self.script_test_log_path}。"
            if self.running_mode == "script_test"
            else f"SID 正在逐只采集；日志实时保存到 {self.sid_log_path}。"
            if self.running_mode == "sid"
            else (
                f"SID 遍历正在运行；日志将保存到 {self.sid_traversal_log_path}。"
                if self.running_mode == "sid_traversal"
                else (
                    "TID/SID → 研究所 → 2.0 御三家流程正在运行；详细日志见新打开的终端。"
                    if self.running_mode == "tid_flow"
                    else (
                        f"TID/SID 正在运行；日志将保存到 {self.tid_log_path}。"
                        if self.running_mode == "tid"
                        else (
                            f"孵蛋流程正在运行；日志将保存到 {self.egg_log_path}。"
                            if self.running_mode == "egg"
                            else f"EasyCon 正在运行；日志将保存到 {self.easycon_log_path}。"
                        )
                    )
                )
            )
        )
        self.root.after(1000, self.poll_process)

    def _poll_tid_calibration_result(self):
        path = self.tid_calibration_result_path
        if path is None or self.tid_calibration_applied or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            initial = self.tid_calibration_snapshot
            if not isinstance(payload, dict) or initial is None or payload.get("schema") != 1 or payload.get("initial_request") != initial.to_dict():
                raise ValueError("固定延迟结果与本次启动的配置不一致")
            updated = calibrated_tid_request(initial, payload["values"])
            if payload.get("request") != updated.to_dict():
                raise ValueError("固定延迟结果包含测量项以外的参数变化")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status_var.set(f"固定延迟结果未回填：{exc}；请查看运行日志。")
            self.tid_calibration_applied = True
            return
        self.tid_calibration_applied = True
        if self.input_fingerprint() != self.tid_calibration_input_fingerprint:
            self.status_var.set("检测已完成，后台按启动时的计划继续；界面输入已修改，未覆盖新输入。")
            return
        self._updating = True
        try:
            for variable, value in (
                (self.tid_op_delay_var, updated.op_fixed_delay),
                (self.tid_f1_delay_var, updated.f1_fixed_delay),
                (self.tid_f2_delay_var, updated.f2_fixed_delay),
                (self.tid_f3_delay_var, updated.f3_fixed_delay),
                (self.tid_op_correction_var, updated.op_correction),
            ):
                variable.set(str(value))
            self.tid_calibration_var.set(False)
        finally:
            self._updating = False
        # The running worker owns its immutable plan. A future start must use
        # a fresh plan for these newly displayed values, never the old files.
        self.invalidate_plan()
        self._tid_pending_calibration = None
        if hasattr(self, "_tid_save_job"):
            self._save_tid_settings()
        self.status_var.set("固定延迟与实际 OP 修正已自动回填；后台正在生成、预检并继续正式计划。")

    def poll_process(self):
        if self.process is None:
            return
        code = self.process.poll()
        self._poll_tid_calibration_result()
        if self.mode_notebook.select() == str(self.tid_records_tab):
            self.refresh_tid_records()
        if code is None:
            log_text = read_display_log_tail(
                self._current_running_log_path(),
                maximum_chars=50000,
            )
            if log_text and log_text != self.running_log_snapshot:
                self.running_log_snapshot = log_text
                self.set_run_log(log_text)
                self._update_label_diagnostics(log_text)
            self.root.after(1000, self.poll_process)
            return
        completed_mode = self.running_mode
        report_path = self.sid_report_path
        sid_traversal_report_path = self.sid_traversal_report_path
        log_path = self.sid_log_path
        tid_flow_log_path = self.tid_flow_log_path
        tid_log_path = self.tid_log_path
        egg_log_path = self.egg_log_path
        script_test_log_path = self.script_test_log_path
        easycon_log_path = self.easycon_log_path
        completed_project_main = self.project_main
        completed_log_path = self._current_running_log_path()
        completed_log_text = read_display_log_tail(
            completed_log_path,
            maximum_chars=50000,
        )
        if completed_log_text:
            self.set_run_log(completed_log_text)
            self._update_label_diagnostics(completed_log_text, notify=True)
        precalibration_update_note = None
        if completed_mode in {"easycon", "egg"}:
            precalibration_update_note = self._update_completed_precalibration(
                completed_project_main,
                completed_log_path,
                code,
            )
        self.process = None
        self.running_mode = None
        self.preview_url = None
        self.stop_button.configure(state="disabled")
        self.search_button.configure(state="normal")
        self.device_button.configure(state="normal")
        self._refresh_manual_tools_buttons()
        self._refresh_start_button()
        if completed_mode == "script_test":
            detail = (
                f"；日志：{script_test_log_path}"
                if script_test_log_path is not None
                else ""
            )
            log_text = ""
            if script_test_log_path is not None and script_test_log_path.is_file():
                log_text = script_test_log_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                self.set_result("直接脚本测试日志：\n\n" + log_text[-20000:])
            self.status_var.set(f"测试脚本已退出，退出码 {code}{detail}")
        elif completed_mode == "sid":
            if code == 0 and report_path is not None and report_path.is_file():
                self.set_result(report_path.read_text(encoding="utf-8"))
                self.status_var.set(f"SID 查找完成，报告已保存：{report_path}")
            else:
                log_text = read_display_log_tail(log_path)
                failure = describe_sid_log_failure(log_text)
                result = "SID 查找未完成。\n\n" + failure
                if log_text:
                    result += "\n\n运行日志尾部：\n\n" + log_text
                self.set_result(result)
                detail = f"；日志：{log_path}" if log_path is not None else ""
                self.status_var.set(f"SID 查找已退出，退出码 {code}{detail}")
        elif completed_mode == "sid_traversal":
            report_text, report_status = self._sid_traversal_report_text(
                sid_traversal_report_path
            )
            if report_text:
                self.set_result(report_text)
            detail = (
                f"；报告：{sid_traversal_report_path}"
                if sid_traversal_report_path is not None
                else ""
            )
            if code == 0 and report_status == "completed":
                self.status_var.set(f"SID 遍历已确认正确 SID{detail}")
            elif code == 0 and report_status == "exhausted":
                self.status_var.set(f"SID 遍历达到上限，未发现闪光{detail}")
            elif report_status == "paused" or code == 130:
                self.status_var.set(f"SID 遍历已暂停，当前起点已保留{detail}")
            else:
                self.status_var.set(f"SID 遍历已退出，退出码 {code}{detail}")
        elif completed_mode == "tid":
            detail = f"；日志：{tid_log_path}" if tid_log_path is not None else ""
            log_text = read_display_log_tail(tid_log_path, maximum_chars=30000)
            if log_text:
                self.set_result("TID/SID 运行日志：\n\n" + log_text)
            self.status_var.set(f"TID/SID 脚本已退出，退出码 {code}{detail}")
        elif completed_mode == "tid_flow":
            detail = f"；日志：{tid_flow_log_path}" if tid_flow_log_path is not None else ""
            if code == 0:
                self.status_var.set(f"TID/SID 到御三家连续流程已完成{detail}")
            else:
                self.status_var.set(f"连续流程已退出，退出码 {code}{detail}")
        elif completed_mode == "egg":
            detail = f"；日志：{egg_log_path}" if egg_log_path is not None else ""
            log_text = ""
            if egg_log_path is not None and egg_log_path.is_file():
                log_text = egg_log_path.read_text(encoding="utf-8", errors="replace")
                self.set_result("孵蛋运行日志：\n\n" + log_text[-16000:])
            if code == 0 and ("孵蛋流程完成" in log_text or "孵蛋流程测试完成" in log_text):
                self.status_var.set(f"孵蛋流程完成{detail}")
            elif "孵蛋流程失败" in log_text or "孵蛋流程测试失败" in log_text:
                self.status_var.set(f"孵蛋流程在检查或执行阶段停止{detail}")
            elif "[EASYCON_DIAGNOSTIC]" in log_text:
                self.status_var.set(f"孵蛋流程被取消或异常提前退出，不能视为正常完成{detail}")
            else:
                self.status_var.set(f"孵蛋流程已退出，退出码 {code}{detail}")
        else:
            detail = f"；日志：{easycon_log_path}" if easycon_log_path is not None else ""
            self.status_var.set(f"EasyCon 已退出，退出码 {code}{detail}")

        if precalibration_update_note:
            self.append_result_note("预校准结果：" + precalibration_update_note)
            self.status_var.set(
                self.status_var.get() + "；" + precalibration_update_note
            )

        self._refresh_tid_progress()
        if self.close_when_stopped:
            self._finish_close()

    def stop_run(self):
        if self.process is None or self.process.poll() is not None:
            return
        if not messagebox.askyesno("停止", "请求停止当前 EasyCon 流程？"):
            return
        self._request_stop()

    def _request_stop(self):
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            if self.stop_request_path is None:
                raise OSError("缺少本次运行的停止通道")
            write_json_atomic(self.stop_request_path, {"stop": True})
        except OSError as exc:
            self.status_var.set(f"停止通知写入失败（{exc}），正在清理本次进程树……")
            self._force_stop_process(process)
            return
        self.stop_button.configure(state="disabled")
        self.status_var.set("已发送停止请求，正在等待 EasyCon 退出……")
        self.root.after(5000, lambda: self.finish_stop_request(process))

    def finish_stop_request(self, expected_process=None):
        process = expected_process if expected_process is not None else self.process
        if process is None or self.process is not process or process.poll() is not None:
            return
        self.status_var.set("停止请求超时，正在终止本次运行器及其 EasyCon 子进程……")
        self._force_stop_process(process)

    def _force_stop_process(self, process):
        def worker():
            try:
                terminate_process_tree(process)
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                self.root.after(0, lambda error=str(exc): failed(error))

        def failed(error):
            if self.process is process and process.poll() is None:
                self.close_when_stopped = False
                self.stop_button.configure(state="normal")
                self.status_var.set(f"本次进程树停止失败：{error}；可以再次点击停止。")

        threading.Thread(target=worker, daemon=True, name="stop-worker-tree").start()

    def choose_source(self):
        path = filedialog.askdirectory(initialdir=self.source_var.get() or str(DEFAULT_SOURCE_118))
        if path:
            self.source_var.set(path)

    def choose_ezcon(self):
        path = filedialog.askopenfilename(
            initialdir=str(Path(self.ezcon_var.get()).parent),
            filetypes=(("EasyCon CLI", "ezcon.exe"), ("Executable", "*.exe")),
        )
        if path:
            self.ezcon_var.set(path)

    def choose_script_test(self):
        current = Path(self.script_test_path_var.get().strip())
        initial_dir = (
            current.parent
            if current.is_file()
            else WRITABLE_ROOT / "runtime" / "script_tests"
        )
        path = filedialog.askopenfilename(
            initialdir=str(initial_dir),
            filetypes=(("EasyCon ECS", "*.ecs"), ("All files", "*.*")),
        )
        if path:
            self.script_test_path_var.set(path)
            self.script_test_entry_status_var.set(
                f"已选择：{Path(path).name}（{self.script_test_entry_var.get()}）"
            )

    def choose_tid_source(self):
        path = filedialog.askdirectory(
            initialdir=self.tid_source_var.get() or str(DEFAULT_TID_SOURCE_PATH)
        )
        if path:
            self.tid_source_var.set(path)

    def choose_sid_source(self):
        path = filedialog.askdirectory(
            initialdir=self.sid_source_var.get() or str(DOWNLOADED_SOURCE_118)
        )
        if path:
            self.sid_source_var.set(path)

    def on_close(self):
        if getattr(self, "_closing_for_update", False):
            self._finish_close()
            return
        if self.busy:
            if self.search_cancel is not None:
                self.cancel_search()
                messagebox.showinfo("正在取消", "已请求取消搜索；请等待状态变为“搜索已取消”后再关闭。")
            else:
                messagebox.showinfo("正在检测", "设备检测尚未结束，请等待完成后再关闭。")
            return
        if self.process is not None and self.process.poll() is None:
            if self.close_when_stopped:
                return
            if self.running_tid_exhaustive:
                stop = messagebox.askyesnocancel("保存搜索进度并关闭",
                    "是否停止当前流程并保存进度后关闭？\n\n"
                    "是：停止后关闭，下次继续当前 TID 搜索点。\n"
                    "否：仅关闭界面，后台继续运行并记录进度。\n取消：返回工具。")
                if stop is None:
                    return
                if stop:
                    self._save_tid_settings()
                    self.close_when_stopped = True
                    self._request_stop()
                    return
            elif not messagebox.askyesno("仍在运行", "EasyCon 仍在运行。关闭界面但保留运行进程？"):
                return
        self._finish_close()

    def _finish_close(self):
        self._poll_tid_calibration_result()
        self._save_tid_settings()
        if self._tid_pending_job is not None:
            self.root.after_cancel(self._tid_pending_job)
            self._tid_pending_job = None
        if self._page_scrollregion_job is not None:
            try:
                self.root.after_cancel(self._page_scrollregion_job)
            except tk.TclError:
                pass
            self._page_scrollregion_job = None
        self._close_manual_tools()
        self.root.destroy()


def main():
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    AutoRngApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
