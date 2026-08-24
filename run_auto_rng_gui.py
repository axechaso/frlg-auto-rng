# -*- coding: utf-8 -*-
"""Simple end-to-end GUI: inputs -> best plan -> configured ECS -> ezcon."""

import hashlib
import json
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app_paths import DATA_ROOT, RESOURCE_ROOT

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
    EggRunRequest,
    EasyCon118Options,
    SEED_MODE_CHOICES,
    SearchCancelledError,
    SCRIPT_TEST_BACKEND_COMPAT,
    SCRIPT_TEST_BACKENDS,
    SID_REVERSE_TEMPLATE_NAME,
    SIDReverseRunRequest,
    ScriptTestPreparation,
    TidRngRequest,
    TidStarterFlowPlan,
    TidStarterFlowRequest,
    PLANNER_STATIC_CATEGORIES,
    build_tid_starter_flow_plan,
    build_run_command,
    prepare_compat_runner,
    prepare_script_test_runtime,
    probe_easycon_devices,
    search_best_plan,
    get_static_targets,
    validate_runtime,
    validate_tid_starter_flow_runtime,
    validate_tid_runtime,
    write_configured_egg_project,
    write_configured_project,
    write_configured_tid_project,
    write_sid_reverse_plan,
    write_sid_reverse_project,
    write_tid_starter_flow_bundle,
    write_builtin_egg_surf_menu_probe,
)
from rng.tenlines_utils import (
    get_ability_name,
    get_encounter_species_list,
    get_personal,
    get_species_id,
    get_species_name,
    load_frlg_encounters,
)
from manual_tools import ManualToolsManager, parse_video_device


ROOT = RESOURCE_ROOT
WRITABLE_ROOT = DATA_ROOT
IMPORTED_SOURCE_118 = ROOT / "local_assets" / "easycon118"
DOWNLOADED_SOURCE_118 = Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8"
DEFAULT_SOURCE_118 = IMPORTED_SOURCE_118 if IMPORTED_SOURCE_118.is_dir() else DOWNLOADED_SOURCE_118
DEFAULT_EZCON = DEFAULT_EZCON_PATH
IV_STAT_LABELS = ("HP", "攻击", "防御", "特攻", "特防", "速度")
IV_PRESETS = ("不限", "6V", "0A", "0S", "0A0S")
SID_SOURCE_LABELS = ("定点", "野生")
MODE_TAB_ORDER = ("SID 查找", "TID 乱数", "野生 / 静态", "孵蛋（测试）")
ADVANCED_TAB_LABEL = "脚本测试（高级）"
EGG_START_MODE_FULL = "完整准备（自动走254步并存档）"
EGG_START_MODE_PREPARED = "从已完成254步准备开始"
EGG_START_MODES = (EGG_START_MODE_FULL, EGG_START_MODE_PREPARED)
TID_SID_MODE_TARGET = "目标 SID（自动计算 ADV）"
TID_SID_MODE_FIXED_F3 = "固定 F3 延迟（采用实际 SID）"
TID_SID_MODES = (TID_SID_MODE_TARGET, TID_SID_MODE_FIXED_F3)
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
TID_FIXED_DELAY_PATTERNS = {
    "OP": re.compile(r"OP脚本固定延迟[：:]\s*(\d+)"),
    "F1": re.compile(r"F1脚本固定延迟[：:]\s*(\d+)"),
    "F2": re.compile(r"F2脚本固定延迟[：:]\s*(\d+)"),
    "F3": re.compile(r"F3脚本固定延迟[：:]\s*(\d+)"),
}


def clean_terminal_log(text: str) -> str:
    """Remove terminal color/control sequences before showing a saved log in Tk."""
    cleaned = ANSI_ESCAPE_RE.sub("", text)
    return cleaned.replace("\r\n", "\n").replace("\r", "\n")


def parse_tid_fixed_delays(text: str) -> dict[str, int]:
    """Parse one complete OP/F1/F2/F3 calibration result from an EasyCon log."""
    cleaned = clean_terminal_log(text)
    result: dict[str, int] = {}
    for name, pattern in TID_FIXED_DELAY_PATTERNS.items():
        matches = pattern.findall(cleaned)
        if matches:
            result[name] = int(matches[-1])
    missing = [name for name in TID_FIXED_DELAY_PATTERNS if name not in result]
    if missing:
        raise ValueError("固定延迟日志缺少：" + "/".join(missing))
    return result


def read_display_log_tail(path: Path | None, maximum_chars: int = 20000) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return clean_terminal_log(text)[-maximum_chars:]


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
            raise ValueError(f"{label}个体值必须是 0-31 的整数") from exc
        if not 0 <= minimum <= 31 or not 0 <= maximum <= 31:
            raise ValueError(f"{label}个体值必须在 0-31 之间")
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
            raise ValueError(f"{label}{stat}必须是 0-31 的整数") from exc
        if not 0 <= value <= 31:
            raise ValueError(f"{label}{stat}必须在 0-31 之间")
        result.append(value)
    return tuple(result)  # type: ignore[return-value]


EGG_CONFIG_VERSION = 1


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
        raise ValueError("254步启动模式必须是布尔值")
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
        self.root.title("火红/叶绿全自动乱数 - 初步实现")
        self.root.geometry("1100x880")
        self.root.minsize(900, 620)
        self.plan_result = None
        self.egg_request: EggRunRequest | None = None
        self.tid_request: TidRngRequest | None = None
        self.tid_flow_plan: TidStarterFlowPlan | None = None
        self.sid_request: SIDReverseRunRequest | None = None
        self.project_main: Path | None = None
        self.runtime_check = None
        self.script_test_preparation: ScriptTestPreparation | None = None
        self.process: subprocess.Popen | None = None
        self.search_cancel: threading.Event | None = None
        self.running_mode: str | None = None
        self.sid_report_path: Path | None = None
        self.sid_log_path: Path | None = None
        self.tid_flow_log_path: Path | None = None
        self.tid_log_path: Path | None = None
        self.egg_log_path: Path | None = None
        self.script_test_log_path: Path | None = None
        self.running_log_snapshot = ""
        self.busy = False
        self._updating = False
        self.manual_tools: ManualToolsManager | None = None
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
        )
        self._populate_seed_modes()
        self._populate_categories()
        self._populate_egg_pokemon()
        self._install_invalidation()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(250, lambda: self.check_devices(initial=True))

    @staticmethod
    def _load_locations() -> dict[str, list[str]]:
        result: dict[str, set[str]] = {}
        for game in ("fr_nx", "lg_nx"):
            for location, category in load_frlg_encounters(game):
                result.setdefault(category, set()).add(location)
        return {category: sorted(locations) for category, locations in result.items()}

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
        container.bind("<Configure>", self._update_page_scrollregion)
        self.page_canvas.bind("<Configure>", self._resize_page_content)
        self.root.bind("<MouseWheel>", self._on_page_mousewheel, add="+")

        self.mode_var = tk.StringVar(value="sid")
        self.mode_notebook = ttk.Notebook(container)
        sid_tab = ttk.Frame(self.mode_notebook, padding=6)
        tid_tab = ttk.Frame(self.mode_notebook, padding=6)
        normal_tab = ttk.Frame(self.mode_notebook, padding=6)
        egg_tab = ttk.Frame(self.mode_notebook, padding=6)
        self.script_test_tab = ttk.Frame(self.mode_notebook, padding=6)
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
        }
        self.mode_notebook.add(self.script_test_tab, text=ADVANCED_TAB_LABEL)
        self.mode_notebook.hide(self.script_test_tab)
        self.mode_notebook.pack(fill="x")

        sid_identity = ttk.LabelFrame(sid_tab, text="1. SID 查找条件", padding=10)
        sid_identity.pack(fill="x")
        self.sid_game_var = tk.StringVar(value="火红")
        self.sid_tid_var = tk.StringVar(value="12345")
        self.sid_count_var = tk.StringVar(value="2")
        self.sid_candies_var = tk.StringVar(value="5")
        self.sid_threshold_var = tk.StringVar(value="85")
        self.sid_ack_var = tk.BooleanVar(value=False)
        self._labeled_combo(
            sid_identity, "游戏", self.sid_game_var, ("火红", "叶绿"), 0, 0
        )
        self._labeled_entry(sid_identity, "当前 TID", self.sid_tid_var, 0, 2, width=12)
        self._labeled_combo(
            sid_identity,
            "队内闪光数量",
            self.sid_count_var,
            tuple(str(value) for value in range(1, 7)),
            0,
            4,
            width=8,
        )
        self._labeled_entry(
            sid_identity, "每只最多糖果", self.sid_candies_var, 0, 6, width=8
        )
        self._labeled_entry(
            sid_identity, "识图阈值", self.sid_threshold_var, 1, 0, width=8
        )
        ttk.Label(
            sid_identity,
            text="支持第三世代 Method 1/2/4；闪光公式只能确定 8 个真实 SID 候选，建档链前10000 ADV有命中时再选最早值。",
        ).grid(row=1, column=2, columnspan=6, sticky="w", padx=4, pady=4)
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
        ttk.Label(
            sid_party,
            text="只处理队伍前 N 位；活动槽位可输入中文名、英文名或全国图鉴编号。孵蛋来源与非 Method 1/2/4 个体暂不支持。",
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

        sid_source = ttk.LabelFrame(sid_tab, text="3. SID 采集脚本包", padding=8)
        sid_source.pack(fill="x", pady=(8, 0))
        # 优先使用安装器生成的已审计本地快照。下载目录可能仍是旧版
        # SID 模板或缺少闪光雄性标签，不能因为文件“存在”就绕过导入结果。
        self.sid_source_var = tk.StringVar(value=str(DEFAULT_SOURCE_118))
        self._labeled_entry(
            sid_source, "1.1.8 包", self.sid_source_var, 0, 0, width=70, span=5
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
                text="0-31",
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
        ttk.Label(direct_frame, text="指定模式会跳过筛选搜索，Seed 模式必须手动选择。").grid(
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
        ttk.Label(capture_options, text="未勾自动抓捕时，脚本会在出闪后停给用户处理。").pack(side="left", padx=(18, 0))

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
        ttk.Label(
            egg_identity,
            text="Seed 模式必须与 Ten Lines Egg 页使用的游戏设置一致。",
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
        ttk.Label(
            egg_identity,
            text="第二项要求当前存档已经完成254步准备；仍会执行HOME_BUFFER与全部校准流程。",
        ).grid(row=2, column=4, columnspan=3, sticky="w", padx=4, pady=4)
        self.egg_game_combo.bind("<<ComboboxSelected>>", lambda _: self._on_game_change())
        self.egg_nx_combo.bind("<<ComboboxSelected>>", lambda _: self._on_game_change())

        egg = ttk.LabelFrame(
            egg_tab,
            text="2. 孵蛋测试目标（先从 Ten Lines Egg 页取得 Seed / Held / Pickup）",
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
            text="允许生成并运行实验性的同 Seed 孵蛋时间轴（尚未完成本机实机验收）",
            variable=self.egg_ack_var,
        ).grid(row=4, column=0, columnspan=8, sticky="w", padx=6, pady=(5, 0))
        egg_config_actions = ttk.Frame(egg)
        egg_config_actions.grid(row=5, column=0, columnspan=8, sticky="w", padx=6, pady=(7, 0))
        ttk.Button(
            egg_config_actions,
            text="保存孵蛋配置",
            command=self.save_egg_config,
        ).pack(side="left")
        ttk.Button(
            egg_config_actions,
            text="载入孵蛋配置",
            command=self.load_egg_config,
        ).pack(side="left", padx=(8, 0))

        tid_identity = ttk.LabelFrame(tid_tab, text="1. TID / SID 基本条件", padding=8)
        tid_identity.pack(fill="x")
        self.tid_language_var = tk.StringVar(value="英文")
        self.tid_mode_var = tk.StringVar(value="乱数模式")
        self.tid_nx_var = tk.StringVar(value="Switch 1")
        self.tid_gender_var = tk.StringVar(value="女性")
        self.tid_target_var = tk.StringVar(value="0")
        self.tid_sid_var = tk.StringVar(value="38449")
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
        self._labeled_entry(tid_identity, "目标 TID", self.tid_target_var, 1, 0, width=12)
        self.tid_sid_entry = self._labeled_entry(
            tid_identity, "目标 SID", self.tid_sid_var, 1, 2, width=12
        )
        self._labeled_entry(tid_identity, "主角名称", self.tid_name_var, 1, 4, width=18)
        self.tid_sid_mode_combo = self._labeled_combo(
            tid_identity, "SID 处理", self.tid_sid_mode_var,
            TID_SID_MODES, 1, 6,
        )
        self.tid_calibration_check = ttk.Checkbutton(
            tid_identity,
            text="固定延迟检查（名称或性别变化后先运行一次）",
            variable=self.tid_calibration_var,
        )
        self.tid_calibration_check.grid(
            row=2, column=2, columnspan=4, sticky="w", padx=4, pady=4
        )
        ttk.Label(
            tid_identity,
            text="脚本会新建存档并自动退出游戏两次；请先确认当前存档与主页状态。",
        ).grid(row=3, column=0, columnspan=8, sticky="w", padx=4, pady=(3, 0))
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
            tid_tab, text="2. 乱数中心 / 穷举范围（脚本帧为游戏帧）", padding=8
        )
        tid_frames.pack(fill="x", pady=(8, 0))
        self.tid_op_target_var = tk.StringVar(value="3693")
        self.tid_f1_target_var = tk.StringVar(value="2693")
        self.tid_f2_target_var = tk.StringVar(value="2105")
        self.tid_op_rng_range_var = tk.StringVar(value="0")
        self.tid_f1_rng_range_var = tk.StringVar(value="0")
        self.tid_f2_rng_range_var = tk.StringVar(value="0")
        self.tid_op_start_var = tk.StringVar(value="3902")
        self.tid_f1_start_var = tk.StringVar(value="2649")
        self.tid_f2_start_var = tk.StringVar(value="2183")
        self.tid_op_max_range_var = tk.StringVar(value="600")
        self.tid_f1_max_range_var = tk.StringVar(value="30")
        self.tid_f2_max_range_var = tk.StringVar(value="300")
        ttk.Label(tid_frames, text="参数").grid(row=0, column=0, padx=5, pady=2)
        for column, label in enumerate(("OP", "F1", "F2"), 1):
            ttk.Label(tid_frames, text=label).grid(row=0, column=column, padx=18, pady=2)
            tid_frames.columnconfigure(column, weight=1)
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

        tid_settings = ttk.LabelFrame(tid_tab, text="3. 游戏设置与固定延迟", padding=8)
        tid_settings.pack(fill="x", pady=(8, 0))
        self.tid_sound_var = tk.StringVar(value="MONO")
        self.tid_button_mode_var = tk.StringVar(value="HELP")
        self.tid_seed_button_var = tk.StringVar(value="A")
        self.tid_name_entry_var = tk.StringVar(value="A")
        self.tid_op_delay_var = tk.StringVar(value="30550")
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
        ttk.Checkbutton(
            tid_settings,
            text="手动编辑固定延迟（默认关闭；固定延迟检查完成后自动回填）",
            variable=self.tid_manual_delay_var,
            command=self._update_tid_delay_controls,
        ).grid(row=3, column=2, columnspan=6, sticky="w", padx=4, pady=4)

        tid_starter = ttk.LabelFrame(tid_tab, text="4. 御三家连续乱数", padding=8)
        tid_starter.pack(fill="x", pady=(8, 0))
        self.tid_starter_flow_var = tk.BooleanVar(value=True)
        self.tid_game_var = tk.StringVar(value="火红")
        self.tid_starter_var = tk.StringVar(value="妙蛙种子")
        self.tid_starter_min_adv_var = tk.StringVar(value="1500")
        self.tid_starter_max_adv_var = tk.StringVar(value="10000")
        self.tid_sid_retry_radius_var = tk.StringVar(value="20")
        ttk.Checkbutton(
            tid_starter,
            text="TID 阶段完成后继续御三家；穷举模式使用实际 TID 与 SID ADV",
            variable=self.tid_starter_flow_var,
        ).grid(row=0, column=0, columnspan=8, sticky="w", padx=4, pady=4)
        self.tid_game_combo = self._labeled_combo(
            tid_starter, "游戏版本", self.tid_game_var, ("火红", "叶绿"), 1, 0
        )
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
        self.tid_sid_retry_radius_entry = self._labeled_entry(
            tid_starter, "SID ADV 重试半径", self.tid_sid_retry_radius_var, 2, 0, width=12
        )
        self.tid_starter_flow_controls = (
            self.tid_game_combo,
            self.tid_starter_combo,
            self.tid_starter_min_adv_entry,
            self.tid_starter_max_adv_entry,
            self.tid_sid_retry_radius_entry,
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

        script_test = ttk.LabelFrame(
            self.script_test_tab,
            text="直接运行 ECS 测试脚本",
            padding=10,
        )
        script_test.pack(fill="x")
        self.script_test_path_var = tk.StringVar(value="")
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
            text="输出 EasyCon 详细日志（--verbose）",
            variable=self.script_test_verbose_var,
        ).grid(row=1, column=5, columnspan=2, sticky="w", padx=4, pady=4)
        ttk.Button(
            script_test,
            text="准备内置冲浪结束测试",
            command=self.prepare_builtin_surf_menu_probe,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=4, pady=(8, 4))
        ttk.Label(
            script_test,
            text=(
                "所选 ECS 会原地直接执行，不经过方案搜索、参数替换或正式 main.ecs 生成。"
                "兼容后端等同正式工具；原始 CLI 用于 A/B 对照。"
            ),
        ).grid(row=2, column=2, columnspan=5, sticky="w", padx=4, pady=(8, 4))
        ttk.Label(
            script_test,
            text=(
                "警告：测试脚本拥有完整手柄控制权限。开始前请人工核对脚本内容、游戏位置和存档状态；"
                "同目录的 lib 与 ImgLabel 会被 EasyCon 使用。"
            ),
            foreground="#9a3412",
        ).grid(row=3, column=0, columnspan=7, sticky="w", padx=4, pady=(4, 0))

        runtime = ttk.LabelFrame(container, text="EasyCon 共通设置与工具", padding=10)
        runtime.pack(fill="x", pady=(0, 10), before=self.mode_notebook)
        self.source_var = tk.StringVar(value=str(DEFAULT_SOURCE_118))
        self.ezcon_var = tk.StringVar(value=str(DEFAULT_EZCON))
        self.port_var = tk.StringVar(value="COM22")
        self.video_var = tk.StringVar(value="0")
        self.source_entry = self._labeled_entry(runtime, "1.1.8 包（普通/孵蛋）", self.source_var, 0, 0, width=68, span=5)
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
        self.monitor_button = ttk.Button(
            manual_tools,
            text="监视窗口",
            command=self.open_monitor,
        )
        self.monitor_button.pack(side="left", padx=(8, 0))
        self.advanced_mode_var = tk.BooleanVar(value=False)
        self.advanced_mode_check = ttk.Checkbutton(
            manual_tools,
            text="高级模式（显示直接脚本测试页）",
            variable=self.advanced_mode_var,
            command=self._toggle_advanced_mode,
        )
        self.advanced_mode_check.pack(side="left", padx=(18, 0))
        self.home_buffer_adaptive_var = tk.BooleanVar(value=False)
        self.home_buffer_adaptive_check = ttk.Checkbutton(
            manual_tools,
            text="HOME_BUFFER 稳定低分自适应（1.1.8 + TID，默认关闭）",
            variable=self.home_buffer_adaptive_var,
        )
        self.home_buffer_adaptive_check.pack(side="left", padx=(14, 0))

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
        self._on_mode_tab_change()

    def _update_page_scrollregion(self, _event=None):
        self.page_canvas.configure(scrollregion=self.page_canvas.bbox("all"))

    def _resize_page_content(self, event):
        self.page_canvas.itemconfigure(self.page_window, width=event.width)
        self.root.after_idle(self._update_page_scrollregion)

    def _on_page_mousewheel(self, event):
        # The result box has its own scrollbar; keep the wheel local while the
        # pointer is over it. Everywhere else, scroll the complete form.
        if event.widget is self.result_text:
            return None
        steps = int(-event.delta / 120)
        if steps == 0:
            steps = -1 if event.delta > 0 else 1
        self.page_canvas.yview_scroll(steps * 3, "units")
        return "break"

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
            self.home_buffer_adaptive_var,
            self.source_var, self.ezcon_var,
            self.egg_seed_var, self.egg_held_var, self.egg_pickup_var,
            self.egg_seed_mode_var, self.egg_pokemon_var, self.egg_compatibility_var,
            self.egg_start_mode_var,
            self.egg_parent_a_gender_var, self.egg_parent_b_gender_var,
            *self.egg_parent_a_iv_vars, *self.egg_parent_b_iv_vars,
            self.egg_ack_var,
            self.tid_language_var, self.tid_mode_var, self.tid_nx_var,
            self.tid_gender_var, self.tid_target_var, self.tid_sid_var,
            self.tid_name_var, self.tid_sid_mode_var,
            self.tid_calibration_var,
            self.tid_op_target_var, self.tid_f1_target_var, self.tid_f2_target_var,
            self.tid_op_rng_range_var, self.tid_f1_rng_range_var, self.tid_f2_rng_range_var,
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
            self.sid_game_var, self.sid_tid_var, self.sid_count_var,
            self.sid_candies_var, self.sid_threshold_var, self.sid_ack_var,
            *self.sid_species_vars, *self.sid_initial_level_vars,
            *self.sid_source_type_vars,
            *self.sid_location_vars,
            *(variable for row in self.sid_effort_vars for variable in row),
            self.sid_source_var,
            self.script_test_path_var, self.script_test_backend_var,
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

    def invalidate_plan(self, *_):
        if self._updating:
            return
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
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

    def _is_egg_mode(self):
        return self.mode_var.get() == "egg"

    def _is_tid_mode(self):
        return self.mode_var.get() == "tid"

    def _is_sid_mode(self):
        return self.mode_var.get() == "sid"

    def _is_script_test_mode(self):
        return self.mode_var.get() == "script_test"

    def _toggle_advanced_mode(self):
        if self.busy or self._process_running():
            self._updating = True
            try:
                self.advanced_mode_var.set(not self.advanced_mode_var.get())
            finally:
                self._updating = False
            return
        if self.advanced_mode_var.get():
            self.mode_notebook.add(self.script_test_tab, text=ADVANCED_TAB_LABEL)
            self.mode_notebook.select(self.script_test_tab)
        else:
            if self._is_script_test_mode():
                normal_tab = next(
                    tab for tab, mode in self.tab_modes.items() if mode == "normal"
                )
                self.mode_notebook.select(normal_tab)
            self.mode_notebook.hide(self.script_test_tab)
        self.root.after_idle(self._update_page_scrollregion)

    def _on_mode_tab_change(self, _event=None):
        mode = self.tab_modes.get(self.mode_notebook.select(), "normal")
        if self.mode_var.get() != mode:
            self.mode_var.set(mode)
        is_egg = mode == "egg"
        is_tid = mode == "tid"
        is_sid = mode == "sid"
        is_script_test = mode == "script_test"
        self.search_button.configure(
            text=(
                "预检所选脚本" if is_script_test
                else "准备 SID 查找" if is_sid
                else "生成孵蛋测试脚本" if is_egg
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
                else "填写孵蛋参数后点击“生成孵蛋测试脚本”。"
                if is_egg
                else (
                    "填写 TID/SID 与御三家参数后生成连续流程计划。"
                    if self.tid_starter_flow_var.get()
                    else "填写 TID/SID 参数后点击“生成 TID/SID 脚本”。"
                )
                if is_tid
                else "填写条件后点击“搜索并生成方案”。"
            )
        self.root.after_idle(self._update_page_scrollregion)

    def _on_tid_flow_toggle(self, *_):
        self._update_tid_flow_controls()
        if self._is_tid_mode():
            self._on_mode_tab_change()

    def _update_tid_delay_controls(self):
        state = "normal" if self.tid_manual_delay_var.get() else "disabled"
        for entry in self.tid_delay_entries:
            entry.configure(state=state)

    def _update_tid_flow_controls(self):
        enabled = self.tid_starter_flow_var.get()
        exhaustive = self.tid_mode_var.get() == "穷举模式"
        if enabled:
            self._updating = True
            try:
                self.tid_calibration_var.set(False)
                self.tid_sid_mode_var.set(
                    TID_SID_MODE_FIXED_F3 if exhaustive else TID_SID_MODE_TARGET
                )
            finally:
                self._updating = False
        fixed_f3 = self.tid_sid_mode_var.get() == TID_SID_MODE_FIXED_F3
        self.tid_mode_combo.configure(state="readonly")
        self.tid_sid_mode_combo.configure(state="disabled" if enabled else "readonly")
        self.tid_sid_entry.configure(state="disabled" if fixed_f3 else "normal")
        self.tid_calibration_check.configure(state="disabled" if enabled else "normal")
        for widget in self.tid_special_checks:
            widget.configure(state="normal" if not enabled or exhaustive else "disabled")
        for widget in self.tid_starter_flow_controls:
            state = "readonly" if enabled and isinstance(widget, ttk.Combobox) else (
                "normal" if enabled else "disabled"
            )
            widget.configure(state=state)
        if enabled and exhaustive:
            self.tid_sid_retry_radius_entry.configure(state="disabled")
        self._update_tid_delay_controls()

    def _apply_tid_language_defaults(self):
        japanese = self.tid_language_var.get() == "日文"
        defaults = (
            (self.tid_gender_var, "男性" if japanese else "女性"),
            (self.tid_target_var, "1" if japanese else "0"),
            (self.tid_sid_var, "64506" if japanese else "38449"),
            (self.tid_name_var, "レット゛" if japanese else "Alxe"),
            (self.tid_op_delay_var, "30650" if japanese else "30550"),
            (self.tid_f1_delay_var, "27600" if japanese else "22050"),
            (self.tid_f2_delay_var, "8960" if japanese else "4250"),
            (self.tid_f3_delay_var, "15950" if japanese else "14900"),
            (self.tid_op_target_var, "3689" if japanese else "3693"),
            (self.tid_f1_target_var, "3323" if japanese else "2693"),
            (self.tid_f2_target_var, "2011" if japanese else "2105"),
            (self.tid_op_start_var, "0" if japanese else "3902"),
            (self.tid_f1_start_var, "0" if japanese else "2649"),
            (self.tid_f2_start_var, "0" if japanese else "2183"),
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
        if self.game_var.get() == "火红":
            choices = [choice for choice in choices if not choice.startswith("3:")]
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

    def _egg_config_payload(self) -> dict:
        species_id = parse_egg_species(self.egg_pokemon_var.get())
        return build_egg_config_payload(
            self.game_var.get(),
            {"Switch 1": 1, "Switch 2": 2}.get(self.nx_var.get()),
            species_id,
            self.egg_compatibility_var.get(),
            [variable.get() for variable in self.egg_parent_a_iv_vars],
            [variable.get() for variable in self.egg_parent_b_iv_vars],
            self.egg_start_mode_var.get() == EGG_START_MODE_PREPARED,
        )

    def save_egg_config(self):
        try:
            payload = self._egg_config_payload()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("保存孵蛋配置失败", str(exc))
            return
        path = filedialog.asksaveasfilename(
            title="保存孵蛋配置",
            initialdir=str(ROOT),
            initialfile="孵蛋配置.json",
            defaultextension=".json",
            filetypes=(("JSON 配置", "*.json"), ("所有文件", "*.*")),
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            messagebox.showerror("保存孵蛋配置失败", str(exc))
            return
        self.status_var.set(f"孵蛋配置已保存：{path}")

    def load_egg_config(self):
        path = filedialog.askopenfilename(
            title="载入孵蛋配置",
            initialdir=str(ROOT),
            filetypes=(("JSON 配置", "*.json"), ("所有文件", "*.*")),
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            config = parse_egg_config_payload(payload)
            game = config["game"]
            nx_model = config["nx_model"]
            species_id = config["egg_species_id"]
            self._updating = True
            try:
                self.game_var.set(game)
                self.nx_var.set("Switch 2" if nx_model == 2 else "Switch 1")
            finally:
                self._updating = False
            self._on_game_change()
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
                self.egg_start_mode_var.set(
                    EGG_START_MODE_PREPARED
                    if config["start_from_prepared_254"]
                    else EGG_START_MODE_FULL
                )
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
            self.invalidate_plan()
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("载入孵蛋配置失败", str(exc))
            return
        self.status_var.set(f"孵蛋配置已载入：{path}")

    def collect_egg_request(self) -> EggRunRequest:
        species_id = parse_egg_species(self.egg_pokemon_var.get())
        if self.egg_seed_mode_var.get() == "请选择":
            raise ValueError("孵蛋测试必须选择与 Ten Lines 结果一致的 Seed 模式")
        if not self.egg_ack_var.get():
            raise ValueError("请先确认允许运行尚未完成实机验收的孵蛋测试时间轴")
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
        )

    def collect_tid_request(self) -> TidRngRequest:
        sid_mode = self.tid_sid_mode_var.get()
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
            target_tid=int(self.tid_target_var.get()),
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
            sid_random=sid_mode == TID_SID_MODE_FIXED_F3,
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
        )
        source_path = Path(self.tid_source_var.get())
        template_path = source_path / {
            "英文": "【TID+SID乱数&穷举】英文版-火红叶绿1.3.7.txt",
            "日文": "【TID+SID乱数&穷举】日文版-火红叶绿1.3.7.txt",
        }[request.language]
        if not template_path.is_file():
            raise FileNotFoundError(f"找不到 TID 1.3.7 模板：{template_path}")
        request.validate(template_path.read_text(encoding="utf-8"))
        return request

    def collect_tid_starter_flow_request(
        self,
        tid_request: TidRngRequest,
    ) -> TidStarterFlowRequest | None:
        if not self.tid_starter_flow_var.get():
            return None
        request = TidStarterFlowRequest(
            tid_request=tid_request,
            version=self.tid_game_var.get(),
            starter=self.tid_starter_var.get(),
            starter_min_advances=int(self.tid_starter_min_adv_var.get()),
            starter_max_advances=int(self.tid_starter_max_adv_var.get()),
            sid_retry_radius=int(self.tid_sid_retry_radius_var.get()),
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
            max_candies=int(self.sid_candies_var.get()),
            recognition_threshold=int(self.sid_threshold_var.get()),
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

    def set_busy(self, busy, status):
        self.busy = busy
        self.status_var.set(status)
        self.search_button.configure(state="disabled" if busy else "normal")
        self.device_button.configure(state="disabled" if busy else "normal")
        self._refresh_manual_tools_buttons()
        self._refresh_start_button()

    def _process_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _refresh_manual_tools_buttons(self) -> None:
        enabled = not self.busy and not self._process_running()
        state = "normal" if enabled else "disabled"
        self.virtual_controller_button.configure(state=state)
        self.monitor_button.configure(state=state)
        self.advanced_mode_check.configure(state=state)
        self.home_buffer_adaptive_check.configure(state=state)
        self.port_combo.configure(state="readonly" if enabled else "disabled")
        self.video_combo.configure(state="readonly" if enabled else "disabled")

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
        )
        input_fingerprint = self.input_fingerprint()
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
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
                        project_main = write_configured_project(
                            source_path,
                            output,
                            result.plan,
                            easycon_options,
                        )
                        check = validate_runtime(ezcon_path, project_main)
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

    def generate_script_test_preflight(self):
        script_text = self.script_test_path_var.get().strip()
        if not script_text:
            raise ValueError("请先选择要直接运行的 .ecs 测试脚本")
        script_path = Path(script_text)
        backend = self.script_test_backend_var.get()
        ezcon_path = Path(self.ezcon_var.get())
        input_fingerprint = self.input_fingerprint()
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
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
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.script_test_preparation = None
        self.project_main = None
        self.runtime_check = None
        self.set_busy(True, "正在生成 SID 采集脚本并执行 1.6.4-a 预检……")
        self.set_result("正在校验 SID 采集模板、识图标签和 EasyCon 1.6.4-a。")

        def worker():
            try:
                output = WRITABLE_ROOT / "runtime" / "sid_reverse"
                project_main = write_sid_reverse_project(source_path, output, request)
                check = validate_runtime(ezcon_path, project_main)
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
        self.script_test_preparation = None
        self.project_main = project_main
        self.runtime_check = check
        active_slots = range(request.party_count)
        lines = [
            "SID 查找：EasyCon 逐只采集 + Python Method 1/2/4 反查",
            f"游戏：{'火红' if self.sid_game_var.get() == '火红' else '叶绿'}",
            f"TID：{request.tid:05d}；队内闪光数量：{request.party_count}",
            f"每只最多糖果：{request.max_candies}；识图阈值：{request.recognition_threshold}",
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
        ezcon_path = Path(self.ezcon_var.get())
        input_fingerprint = self.input_fingerprint()
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.script_test_preparation = None
        self.project_main = None
        self.runtime_check = None
        status = (
            (
                "正在生成穷举TID阶段；御三家目标将在取得实际TID/SID后搜索……"
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
                    "穷举阶段将输出实际TID和SID ADV；运行时计算实际SID后，"
                    "再搜索最早可达闪光御三家并生成1.1.8第三阶段。"
                    if flow_request.deferred_identity
                    else (
                        "正在搜索 ADV "
                        f"{flow_request.starter_min_advances}-"
                        f"{flow_request.starter_max_advances} 内最早可达闪光御三家，"
                        "并生成英文TID、研究所桥接和1.1.8御三家三个阶段。"
                    )
                )
            )
            if flow_request is not None
            else "正在校验英文/日文模板、328 个标签和 EasyCon 1.6.4-a。"
        )

        def worker():
            try:
                flow_plan = None
                if flow_request is not None:
                    output = WRITABLE_ROOT / "runtime" / "tid_starter_flow"
                    flow_plan = build_tid_starter_flow_plan(flow_request)
                    write_tid_starter_flow_bundle(
                        source_path,
                        output,
                        flow_plan,
                        starter_source_dir=Path(self.source_var.get()),
                    )
                    project_main = output / "01_id" / "main.ecs"
                else:
                    output = WRITABLE_ROOT / "runtime" / "tid_rng137"
                    project_main = write_configured_tid_project(source_path, output, request)
                if flow_plan is not None:
                    bridge_main = output / "02_lab_bridge" / "main.ecs"
                    check = validate_tid_starter_flow_runtime(
                        ezcon_path,
                        project_main,
                        bridge_main,
                        (
                            None
                            if flow_plan.request.deferred_identity
                            else output / "03_starter_118" / "main.ecs"
                        ),
                    )
                else:
                    check = validate_tid_runtime(ezcon_path, project_main)
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
        self.script_test_preparation = None
        self.project_main = project_main
        self.runtime_check = check
        mode_name = "乱数模式" if request.mode == 1 else "穷举模式"
        lines = [
            f"TID/SID 1.3.7：{request.language}版 / {mode_name}",
            f"目标 TID/SID：{request.target_tid:05d} / {request.target_sid:05d}",
            f"主角：{'男性' if request.gender == 0 else '女性'} / {request.player_name}",
            f"主机：Switch {request.nx_model}",
            f"中心帧 OP/F1/F2：{request.op_target_frame}/{request.f1_target_frame}/{request.f2_target_frame}",
            f"乱数半径 OP/F1/F2：{request.op_rng_range}/{request.f1_rng_range}/{request.f2_rng_range}",
            f"固定延迟 OP/F1/F2/F3：{request.op_fixed_delay}/{request.f1_fixed_delay}/{request.f2_fixed_delay}/{request.f3_fixed_delay}",
            f"固定延迟检查：{'开启' if request.calibration_check else '关闭'}",
            (
                "TID HOME_BUFFER稳定低分自适应：开启（稳定3次、最低90分）"
                if request.home_buffer_adaptive_threshold
                else "TID HOME_BUFFER稳定低分自适应：关闭（严格95分）"
            ),
            f"计划文件：{plan_path}",
            f"生成脚本：{project_main}",
        ]
        if request.language == "日文":
            lines.append("兼容修正：已把日版 FOR $InputLen 改为 1.6.4-a 可编译的显式索引循环。")
        if flow_plan is not None:
            target = flow_plan.starter_target
            if target is None:
                lines.extend(
                    (
                        f"连续流程：{flow_plan.request.version} / {flow_plan.request.starter} / 穷举动态衔接",
                        (
                            "御三家搜索：取得实际TID和SID ADV后计算实际SID，再在 ADV "
                            f"{flow_plan.request.starter_min_advances}-"
                            f"{flow_plan.request.starter_max_advances} 内搜索最早闪光目标"
                        ),
                        "F3：固定延迟；随机F3模式已移除",
                        f"ID 阶段：{project_main}",
                        f"研究所桥接：{project_main.parents[1] / '02_lab_bridge' / 'main.ecs'}",
                        "1.1.8 御三家：运行时按实际TID/SID生成并立即预检",
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
                        f"1.1.8 御三家：{project_main.parents[1] / '03_starter_118' / 'main.ecs'}",
                    )
                )
        if check.ok and flow_plan is None:
            lines.extend(f"预检提示：{warning}" for warning in check.warnings)
            status = "TID/SID 脚本已生成，可以在确认会新建存档后开始。"
        elif check.ok:
            lines.extend(f"预检提示：{warning}" for warning in check.warnings)
            status = (
                "穷举连续流程前两阶段已通过预检；第三阶段将在取得实际TID/SID后生成并预检。"
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
        input_fingerprint = self.input_fingerprint()
        self.plan_result = None
        self.egg_request = None
        self.tid_request = None
        self.tid_flow_plan = None
        self.sid_request = None
        self.script_test_preparation = None
        self.project_main = None
        self.runtime_check = None
        self.set_busy(True, "正在生成孵蛋测试脚本并执行 1.6.4a 预检……")
        self.set_result("孵蛋模式使用 Ten Lines 已选出的同 Seed / Held / Pickup，不重复搜索目标。")

        def worker():
            try:
                output = WRITABLE_ROOT / "runtime" / "easycon118"
                project_main = write_configured_egg_project(source_path, output, request)
                check = validate_runtime(ezcon_path, project_main)
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
        self.script_test_preparation = None
        self.project_main = project_main
        self.runtime_check = check
        pokemon = get_species_name(request.species_id)
        lines = [
            "孵蛋模式：同 Seed 时间轴测试版（实验性）",
            (
                "启动准备：从已完成254步的基础存档开始"
                if request.start_from_prepared_254
                else "启动准备：完整准备（自动走254步、检查设置并存档）"
            ),
            f"蛋种：{SPECIES_EN_TO_ZH.get(pokemon, pokemon)} ({pokemon})",
            f"目标 Seed：{request.normalized_seed}，Seed 模式：{request.seed_mode}",
            f"Held/生成帧：{request.held_advances}",
            f"Pickup/领取帧：{request.pickup_advances}",
            f"双亲相性：{request.compatibility}",
            f"亲本A：{request.parent_a_gender} {request.parent_a_ivs}",
            f"亲本B：{request.parent_b_gender} {request.parent_b_ivs}",
            f"计划文件：{plan_path}",
            f"生成脚本：{project_main}",
            "注意：该入口来自 1.1.8 的 TV 时间轴测试脚本，尚未完成本机实机验收。",
        ]
        if check.ok:
            lines.extend(f"预检提示：{warning}" for warning in check.warnings)
            status = "孵蛋测试脚本已生成，可以在确认存档准备后开始。"
        else:
            lines.extend(f"预检失败：{error}" for error in check.errors)
            status = "孵蛋脚本已生成，但预检不允许启动。"
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
        self.script_test_preparation = None
        self.project_main = project_main
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
            (
                "指定模式：已跳过筛选搜索"
                if direct_mode
                else f"扫描候选：{result.matching_outcomes}，可行路线：{result.feasible_routes}"
            ),
            f"路线状态：{plan.route_support.level.value}",
            f"出闪后处理：{'自动抓捕' if self.auto_capture_var.get() else '停止并交给用户'}",
            f"计划文件：{plan_path}",
        ]
        lines.extend(f"注意：{warning}" for warning in plan.warnings)
        if not plan.route_support.can_start:
            lines.append("此路线仅允许搜索，初版已阻止自动启动。")
        elif generation_error is not None:
            lines.append(f"搜索方案已保存，但 ECS 生成/预检失败：{generation_error}")
        elif check and not check.ok:
            lines.extend(f"预检失败：{error}" for error in check.errors)
        else:
            lines.append(f"生成脚本：{project_main}")
            if check:
                lines.extend(f"预检提示：{warning}" for warning in check.warnings)
            if plan.request.category.endswith("Rod") and "Safari Zone" in plan.request.location:
                lines.append("启动前确认：所选钓竿已登录到 Y；1.1.8 实际复用中央钓点路线。")
        self.set_result("\n".join(lines))
        can_start = bool(
            project_main and check and check.ok
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
            if initial:
                self.fail_device_check(FileNotFoundError(f"找不到 {ezcon}"))
            else:
                messagebox.showerror("找不到程序", f"找不到 {ezcon}")
            return
        current_port = self.port_var.get()
        current_video = self.video_var.get()
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
        self.set_result(f"设备检测失败：{error}")
        self.set_busy(False, "设备检测失败，现有乱数方案未被清除。")

    def start_run(self):
        if not (
            self.plan_result
            or self.egg_request
            or self.tid_request
            or self.sid_request
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
            )
            self.script_test_preparation = preparation
            self.project_main = preparation.script_path
            check = preparation.check
        elif self.tid_flow_plan is not None:
            flow_dir = self.project_main.parents[1]
            check = validate_tid_starter_flow_runtime(
                Path(self.ezcon_var.get()),
                self.project_main,
                flow_dir / "02_lab_bridge" / "main.ecs",
                (
                    None
                    if self.tid_flow_plan.request.deferred_identity
                    else flow_dir / "03_starter_118" / "main.ecs"
                ),
            )
        elif self.tid_request is not None:
            check = validate_tid_runtime(Path(self.ezcon_var.get()), self.project_main)
        else:
            check = validate_runtime(Path(self.ezcon_var.get()), self.project_main)
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
                confirmation = (
                    "将运行穷举TID → 动态计算实际SID → 研究所桥接 → 1.1.8御三家流程。\n"
                    "第一阶段命中启用的TID条件后，工具读取实际TID和SID ADV，"
                    "计算实际SID并搜索最早闪光御三家；第三阶段届时生成并预检。\n"
                    f"{self.tid_flow_plan.request.version} / {self.tid_flow_plan.request.starter} / "
                    f"ADV {self.tid_flow_plan.request.starter_min_advances}-"
                    f"{self.tid_flow_plan.request.starter_max_advances}\n"
                    "第一阶段会新建存档；确认当前存档可以被替代，是否继续？"
                )
            else:
                confirmation = (
                    "将依次运行三个阶段：TID/SID 1.3.7 → 研究所桥接存档 → 现有1.1.8御三家流程。\n"
                    f"目标 TID/SID {self.tid_request.target_tid:05d} / {self.tid_request.target_sid:05d}\n"
                    f"{self.tid_flow_plan.request.version} / {target.species_zh} / "
                    f"Seed {target.seed_hex} / ADV {target.advances}\n"
                    "第一阶段会新建存档；第二阶段会自动走到御三家前并存档；"
                    "第三阶段由1.1.8负责领取、识别和校准。若精确命中但不闪，"
                    "程序会按SID ADV重试范围重新执行三段。是否继续？"
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
                "本次会跳过254步走位、设置检查和存档；请确认当前存档确实是已完成254步准备的基础档。"
                if self.egg_request.start_from_prepared_254
                else "本次会自动完成254步走位、设置检查并建立基础存档。"
            )
            confirmation = (
                "将启动 1.1.8 的实验性同 Seed 孵蛋时间轴。\n"
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
                "请确认游戏设置、存档位置和 NS 主页状态均符合 1.1.8 要求，是否继续？"
            )
        if not messagebox.askyesno(
            "开始全自动流程",
            confirmation,
        ):
            return
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
            easycon_command = build_run_command(
                runner_path,
                self.project_main,
                port=selected_port,
                video_device=video_device,
                video_type="DSHOW",
                verbose=self.script_test_verbose_var.get(),
            )
            metadata_path = self.script_test_log_path.with_suffix(".json")
            try:
                metadata_path.parent.mkdir(parents=True, exist_ok=True)
                metadata_path.write_text(
                    json.dumps(
                        {
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
                messagebox.showerror("SID计划写入失败", str(exc))
                return
            self.sid_log_path = output_dir / f"sid-reverse-{timestamp}.log"
            self.sid_report_path = output_dir / f"sid-reverse-{timestamp}.txt"
            self.running_log_snapshot = ""
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
            ])
            command_cwd = ROOT
            self.running_mode = "sid"
        elif self.tid_flow_plan is not None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            flow_dir = self.project_main.parents[1]
            self.tid_flow_log_path = flow_dir / f"tid-starter-{timestamp}.log"
            command = build_worker_command("tid-flow", [
                "--flow-dir",
                str(flow_dir),
                "--ezcon",
                self.ezcon_var.get(),
                "--port",
                selected_port,
                "--video",
                str(video_device),
                "--log-path",
                str(self.tid_flow_log_path),
            ])
            command_cwd = ROOT
            self.running_mode = "tid_flow"
        else:
            try:
                runner_path = prepare_compat_runner(Path(self.ezcon_var.get()))
            except (OSError, ValueError, RuntimeError) as exc:
                messagebox.showerror("启动后端检查失败", str(exc))
                return
            easycon_command = build_run_command(
                runner_path,
                self.project_main,
                port=selected_port,
                video_device=video_device,
                video_type="DSHOW",
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
                    "孵蛋流程测试完成",
                    "--expected-marker",
                    "孵蛋流程测试失败",
                    "--",
                    *easycon_command,
                ])
                command_cwd = ROOT
                self.running_mode = "egg"
            elif self.tid_request is not None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.tid_log_path = self.project_main.parent / f"tid-{timestamp}.log"
                command = build_worker_command("easycon-log", [
                    "--log-path",
                    str(self.tid_log_path),
                    "--cwd",
                    str(self.project_main.parent),
                    "--",
                    *easycon_command,
                ])
                command_cwd = ROOT
                self.running_mode = "tid"
            else:
                command = easycon_command
                command_cwd = self.project_main.parent
                self.running_mode = "easycon"
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            self.process = subprocess.Popen(command, cwd=str(command_cwd), creationflags=flags)
        except OSError as exc:
            self.running_mode = None
            messagebox.showerror("启动失败", str(exc))
            return
        self.start_button.configure(state="disabled")
        self.search_button.configure(state="disabled")
        self.device_button.configure(state="disabled")
        self._refresh_manual_tools_buttons()
        self.stop_button.configure(state="normal")
        self.status_var.set(
            f"测试脚本正在直接运行；日志将保存到 {self.script_test_log_path}。"
            if self.running_mode == "script_test"
            else f"SID 正在逐只采集；日志实时保存到 {self.sid_log_path}。"
            if self.running_mode == "sid"
            else (
                "TID/SID → 研究所 → 1.1.8 御三家流程正在运行；详细日志见新打开的终端。"
                if self.running_mode == "tid_flow"
                else (
                    f"TID/SID 正在运行；日志将保存到 {self.tid_log_path}。"
                    if self.running_mode == "tid"
                    else (
                        f"孵蛋流程正在运行；日志将保存到 {self.egg_log_path}。"
                        if self.running_mode == "egg"
                        else "EasyCon 正在运行；详细日志见新打开的终端。"
                    )
                )
            )
        )
        self.root.after(1000, self.poll_process)

    def poll_process(self):
        if self.process is None:
            return
        code = self.process.poll()
        if code is None:
            if self.running_mode == "sid":
                log_text = read_display_log_tail(self.sid_log_path)
                if log_text and log_text != self.running_log_snapshot:
                    self.running_log_snapshot = log_text
                    self.set_result("SID 采集日志（运行中）：\n\n" + log_text)
            self.root.after(1000, self.poll_process)
            return
        completed_mode = self.running_mode
        report_path = self.sid_report_path
        log_path = self.sid_log_path
        tid_flow_log_path = self.tid_flow_log_path
        tid_log_path = self.tid_log_path
        completed_tid_request = self.tid_request
        egg_log_path = self.egg_log_path
        script_test_log_path = self.script_test_log_path
        self.process = None
        self.running_mode = None
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
        elif completed_mode == "tid":
            detail = f"；日志：{tid_log_path}" if tid_log_path is not None else ""
            log_text = read_display_log_tail(tid_log_path, maximum_chars=30000)
            if log_text:
                self.set_result("TID/SID运行日志：\n\n" + log_text)
            if completed_tid_request is not None and completed_tid_request.calibration_check:
                try:
                    delays = parse_tid_fixed_delays(log_text)
                except ValueError as exc:
                    self.status_var.set(
                        f"固定延迟检查未得到完整四项结果：{exc}{detail}"
                    )
                else:
                    self._updating = True
                    try:
                        self.tid_op_delay_var.set(str(delays["OP"]))
                        self.tid_f1_delay_var.set(str(delays["F1"]))
                        self.tid_f2_delay_var.set(str(delays["F2"]))
                        self.tid_f3_delay_var.set(str(delays["F3"]))
                        self.tid_calibration_var.set(False)
                    finally:
                        self._updating = False
                    self.invalidate_plan()
                    self.set_result(
                        "固定延迟检查完成，已自动回填：\n"
                        f"OP {delays['OP']} / F1 {delays['F1']} / "
                        f"F2 {delays['F2']} / F3 {delays['F3']}\n\n"
                        "固定延迟检查已自动关闭，请重新生成正式TID/御三家方案。\n\n"
                        + log_text
                    )
                    self.status_var.set(
                        "固定延迟已自动更新；请重新生成正式TID/御三家方案。"
                    )
            else:
                self.status_var.set(f"TID/SID脚本已退出，退出码 {code}{detail}")
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
            if code == 0 and "孵蛋流程测试完成" in log_text:
                self.status_var.set(f"孵蛋流程测试完成{detail}")
            elif "孵蛋流程测试失败" in log_text:
                self.status_var.set(f"孵蛋流程在检查或执行阶段停止{detail}")
            elif "[EASYCON_DIAGNOSTIC]" in log_text:
                self.status_var.set(f"孵蛋流程被取消或异常提前退出，不能视为正常完成{detail}")
            else:
                self.status_var.set(f"孵蛋流程已退出，退出码 {code}{detail}")
        else:
            self.status_var.set(f"EasyCon 已退出，退出码 {code}。")

    def stop_run(self):
        if self.process is None or self.process.poll() is not None:
            return
        if not messagebox.askyesno("停止", "请求停止当前 EasyCon 流程？"):
            return
        try:
            self.process.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, AttributeError):
            self.process.terminate()
        self.stop_button.configure(state="disabled")
        self.status_var.set("已发送停止请求，正在等待 EasyCon 退出……")
        self.root.after(5000, self.finish_stop_request)

    def finish_stop_request(self):
        if self.process is None or self.process.poll() is not None:
            return
        if messagebox.askyesno(
            "停止超时",
            "EasyCon 在 5 秒内没有退出。是否强制终止该进程？",
        ):
            self.process.terminate()
            self.status_var.set("已强制终止 EasyCon；请重新检测串口后再运行。")
        else:
            self.stop_button.configure(state="normal")
            self.status_var.set("EasyCon 仍在运行。")

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

    def prepare_builtin_surf_menu_probe(self):
        if self.busy or self._process_running():
            messagebox.showerror("正在运行", "请先等待当前操作结束或停止 EasyCon。")
            return
        try:
            output_dir = (
                WRITABLE_ROOT
                / "runtime"
                / "script_tests"
                / "egg_surf_menu_probe"
            )
            main_path = write_builtin_egg_surf_menu_probe(
                Path(self.source_var.get()),
                output_dir,
            )
            self.script_test_path_var.set(str(main_path))
            self.generate_script_test_preflight()
        except Exception as exc:
            messagebox.showerror("内置测试准备失败", str(exc))

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
        if self.busy:
            if self.search_cancel is not None:
                self.cancel_search()
                messagebox.showinfo("正在取消", "已请求取消搜索；请等待状态变为“搜索已取消”后再关闭。")
            else:
                messagebox.showinfo("正在检测", "设备检测尚未结束，请等待完成后再关闭。")
            return
        if self.process is not None and self.process.poll() is None:
            if not messagebox.askyesno("仍在运行", "EasyCon 仍在运行。关闭界面但保留运行进程？"):
                return
        self._close_manual_tools()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    AutoRngApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
