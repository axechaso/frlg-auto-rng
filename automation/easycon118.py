"""Generate and launch a configured 1.1.8 project on pinned EasyCon 1.6.4a."""

import json
import hashlib
import re
import shutil
import struct
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from assets.game_text import CATEGORY_EN_TO_ZH, location_to_zh
from app_paths import RESOURCE_ROOT

from .planner import RunPlan


EXPECTED_LABEL_COUNT = 1150
EXPECTED_LABEL_METHODS = {1: 17, 3: 1, 5: 777, 11: 1, 14: 354}
EXPECTED_LABEL_SHA256 = "00d2fbfa9a3638f3cea64553e94b777ed8c5c63f813125617b50aaeed7c9d10e"
EASYCON_BACKEND_NAME = "EasyCon 1.6.4a"
EXPECTED_EZCON_VERSION = "1.6.4-a+9c86137c7e63bff842175470895727a5fa9bab52"
EXPECTED_EZCON_SHA256 = "559b81c234d2548c439926a88f5355ccac0958b8a191c1ecca48b2c7c71c1260"
EXPECTED_COMPAT_SOURCE_COMMIT = "9c86137c7e63bff842175470895727a5fa9bab52"
EXPECTED_COMPAT_PATCH_ID = "cli-latest-frame-ceiling-ocr-onedir-v4"
EXPECTED_TESSDATA_SHA256 = {
    "frlg_battle.traineddata": "7abcaef4936727b33717656b38fd5b5027823e1cafec21abb06cc8ef1f7ff758",
    "FRLG_EN_ALL.traineddata": "3272f23a6f259518813025d89be77d706574ccdf163132ccf6f5be15ca19cfa0",
}
EXPECTED_COMPAT_OCR_NATIVE_SHA256 = {
    "x64/leptonica-1.82.0.dll": "dfcb3e6ed0b16bc55bfdbcf53543cfe42a354b87c3e35bd3a95eebf005d73e76",
    "x64/tesseract50.dll": "de4d04ec75095374d98f5dd7a60d14d7e2e0f76589db693eccf7ae658be8cb2b",
}
DEFAULT_EZCON_PATH = (
    Path.home()
    / "Downloads"
    / "伊机控-EasyCon-v1.6.4alpha测试版-260518"
    / "publish"
    / "ezcon.exe"
)
if getattr(sys, "frozen", False):
    DEFAULT_EZCON_PATH = RESOURCE_ROOT / "easycon" / "publish" / "ezcon.exe"
DEFAULT_COMPAT_RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / "runtime_backend"
    / "easycon164a-cli-gui-rounding-selfcontained"
    / "EasyCon2.CLI-ocr-v4.exe"
)
STANDARD_TEMPLATE_NAME = "NS火叶全自动一键乱数1.1.8.ecs"
EGG_TEMPLATE_NAME = "NS火叶全自动一键乱数1.1.8-TV时间轴测试.ecs"
EXPECTED_TEMPLATE_NAMES = (STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME)
EXPECTED_SCRIPT_FILE_COUNT = 33
# The legacy package is still accepted by the importer, then upgraded in the
# ignored local cache.  Generators only run against the materialized corpus so
# direct EasyCon execution and GUI-generated execution use the same fixes.
LEGACY_SCRIPT_SHA256 = "7d5e13e4391d5bcc9045044544f409919a6f95c602e2ad0308313470ce23e625"
# Previously audited corpora and the latest download package are accepted as
# upgrade inputs. Keep them separate from the current fingerprint so existing
# installations can be upgraded in place without accepting arbitrary changes.
PREVIOUS_SCRIPT_SHA256S = (
    "aea14e79615bfda89e1f7428014adc2dcc848005bd7ebad0bd170eac67703aef",
    "fe0ae41be3fe035cbefec9afd525b968a070c8781a73595e1ae16b4cd1e2e839",
    "43c3944bad75a1cb424203237b6aad51b351aa5c9bb81bfc6aa2c93ce96932cf",
    # Download package with the egg candy navigation fix; importing it
    # materializes the remaining 1.6.4-a runtime fixes below.
    "cc11e48441fa58c06ea06d307bc868821477483f4a696e02e81779247891ff4f",
    # Current 1.1.8 download package after the latest egg-flow timing edits.
    "cd263d5e94021df1fdfe68ae3da385f20c478d2f901fddd159f0922b263489f8",
    # Raw 1.1.8 package with the audited egg wild reverse window raised to
    # 6500 advances.
    "407e3fde784c631e871c48f201759e29487cc3e3a10b301aac051cbede9f3385",
    # Download package after adding cross-level IV-range intersection and
    # preserving the current screen on terminal egg lookup failures.
    "bf3601815339f253ca0ee0b354fdfb2c26c07a8840f01e7cc375843a14e353b7",
    # Download package after adding Held/Pickup fixed pre-calibration and
    # cross-round multi-candidate trajectory selection.
    "48cdfb839a81333e6115c72adc3ea40bf8642b091fbf55d7b49dac76cba4556f",
)
EXPECTED_SCRIPT_SHA256 = "1700ba02cc60fdfd9857f14a2a8384c5736c06908a92e468d1dfd721a9be4865"
# Previously materialized 1.6.4-a corpora remain accepted as audited
# compatibility inputs. This is not a general bypass for modified ECS files.
SUPPORTED_RUNTIME_SCRIPT_SHA256S = (
    # Materialized corpus before the opt-in HOME_BUFFER stable-low-score
    # classifier was added to both 1.1.8 entry scripts.
    "da32012466a7349113ff166cf158c39dd721fc6e33c8d84355b9747cd7888f86",
    "1ea3bd0ba820e3cb3b1b8616f24e7e8d23b87767b23c49c77cc0a187c2037f73",
    "30fea007607c06d69efdefe256c4b4a639d865854ca94da8afe309eaf0272451",
    "4843f4044e69dc4bc0eb2f3506490651589e531fe2d3b2bad905a6b977c3eec0",
    # Importer materialization adds one controlled trailing newline to the
    # timeline entry while applying the reviewed 1.6.4-a fixes.
    "316c6aa9b6f05adeef0d7f306032b7ae553779d6a86848ae301aa981fd9a8188",
)


def is_supported_runtime_script_sha256(sha256: str) -> bool:
    """Return whether a script corpus is an audited generator/runtime input."""
    return sha256 in {
        EXPECTED_SCRIPT_SHA256,
        *SUPPORTED_RUNTIME_SCRIPT_SHA256S,
    }


def is_supported_script_input_sha256(sha256: str) -> bool:
    """Return whether an imported source corpus is an audited upgrade input."""
    return sha256 in {
        LEGACY_SCRIPT_SHA256,
        *PREVIOUS_SCRIPT_SHA256S,
        EXPECTED_SCRIPT_SHA256,
        *SUPPORTED_RUNTIME_SCRIPT_SHA256S,
    }
EASYCON118_EXTENSION_LABEL_DIR = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "easycon118_extensions"
)
EASYCON118_EXTENSION_LABEL_NAMES = ("闪公图标.IL", "冲浪.IL")
EGG_SETTINGS_OVERRIDE_PATH = (
    EASYCON118_EXTENSION_LABEL_DIR
    / "egg_settings_retry.ecs"
)
EGG_RESTART_OVERRIDE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "easycon118_extensions"
    / "egg_restart_original_flow.ecs"
)
EGG_HOME_BUFFER_OVERRIDE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "easycon118_extensions"
    / "egg_home_buffer_refine.ecs"
)
HOME_BUFFER_ADAPTIVE_CLASSIFIER_PATH = (
    EASYCON118_EXTENSION_LABEL_DIR / "home_buffer_adaptive_classifier.ecs"
)
STANDARD_HOME_BUFFER_OVERRIDE_PATH = (
    EASYCON118_EXTENSION_LABEL_DIR / "home_buffer_standard_adaptive.ecs"
)
EGG_PARTY_SLOT_MAIN_OVERRIDE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "easycon118_extensions"
    / "egg_party_slot_main.ecs"
)
EGG_PARTY_SLOT_CANDY_OVERRIDE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "easycon118_extensions"
    / "egg_party_slot_candy.ecs"
)
EGG_SURF_BATTLE_OVERRIDE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "easycon118_extensions"
    / "egg_surf_battle_retry.ecs"
)
EGG_SEED_CONTROLLER_OVERRIDE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "easycon118_extensions"
    / "egg_seed_controller_main.ecs"
)
EGG_HATCH_EXIT_OVERRIDE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "easycon118_extensions"
    / "egg_hatch_exit_retry.ecs"
)
TOGEPI_HATCH_CYCLE_OVERRIDE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "easycon118_extensions"
    / "togepi_hatch_cycle.ecs"
)
PARTY_SUMMARY_NAVIGATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "easycon118_extensions"
    / "party_summary_up_navigation.ecs"
)
OCR_NAME_LIBRARY_NAME = "19_OCR_GEN3战斗场景名称.ecs"
OCR_RUNTIME_FALLBACK_MARKER = "# GUI 运行时覆盖：OCR 不可用时直接回到单字识别"
OCR_NAME_ORIGINAL_FUNCTION = "FUNC OCR识别抓捕对象名称(): STRING"
OCR_NAME_NEXT_FUNCTION = "FUNC OCR最小3"
WILD_PID_RETRY_LIMIT_MARKER = "# GUI 运行时覆盖：野生 PID 尝试上限"
WILD_PID_RETRY_LIMIT_IMPORTED = "$野生PID尝试上限 = 1000"
WILD_PID_RETRY_LIMIT_RUNTIME = "$野生PID尝试上限 = 200"
OCR_RUNTIME_FALLBACK_FUNCTION = """\
# GUI 运行时覆盖：OCR 不可用时直接回到单字识别
FUNC OCR识别抓捕对象名称(): STRING

    $name = OCR(310, 141, 360, 53, "frlg_battle")
    IF $name == "OCR NOT SUPPORT"
        PRINT ""
        PRINT 【OCR名称识别】
        PRINT "OCR原文:" & $name
        PRINT OCR运行时不可用，跳过名称后处理
        RETURN ""
    ENDIF
    IF $name == "OCR ARGS ERR!"
        PRINT ""
        PRINT 【OCR名称识别】
        PRINT "OCR原文:" & $name
        PRINT OCR区域参数无效，跳过名称后处理
        RETURN ""
    ENDIF

    $fixedName = OCR名称V2后处理($name)

    PRINT ""
    PRINT 【OCR名称识别】
    PRINT "OCR原文:" & $name
    PRINT "后处理:" & $fixedName

    RETURN $fixedName
ENDFUNC
"""
EGG_SETTINGS_LIBRARY_NAME = "27_孵蛋测试流程.ecs"
EGG_SETTINGS_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：游戏设置 OCR 使用有限重试"
EGG_SETTINGS_NEXT_FUNCTION = "FUNC 孵蛋测试_执行前置准备"
EGG_RESTART_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：按 1.1.8 原版顺序关闭游戏，优先处理退出状态"
EGG_RESTART_ORIGINAL_FUNCTION = "FUNC 孵蛋测试_关闭游戏"
EGG_RESTART_NEXT_FUNCTION = "FUNC 孵蛋测试_软重启并跳过回忆"
EGG_RESTART_GLOBALS = """\
$孵蛋库_重启识别尝试 = 0
$孵蛋库_已请求主页 = 0
"""
EGG_HOME_BUFFER_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：按当前 NX 机型二分查找 HOME_BUFFER 窗口"
EGG_HOME_BUFFER_ORIGINAL_FUNCTION = "FUNC HOME_BUFFER"
EGG_HOME_BUFFER_NEXT_FUNCTION = "FUNC 各阶段脚本固定延迟转帧数"
HOME_BUFFER_ADAPTIVE_CLASSIFIER_MARKER = "# 1.6.4-a HOME_BUFFER 稳定低分自适应"
STANDARD_HOME_BUFFER_OVERRIDE_MARKER = "# 1.6.4-a 正式版 HOME_BUFFER"
HOME_BUFFER_ADAPTIVE_SWITCH = "HOME_BUFFER稳定低分自适应"
EGG_PARTY_SLOT_MAIN_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：按目标身份选择队伍末位或固定槽位"
EGG_PARTY_SLOT_MAIN_ORIGINAL_FUNCTION = "FUNC 孵蛋流程_选择队伍槽"
EGG_PARTY_SLOT_MAIN_NEXT_SECTION = "# -------------------- 野生Seed验证"
EGG_PARTY_SLOT_MAIN_EGG_FUNCTION = "FUNC 孵蛋流程_执行蛋个体反查(): INT"
EGG_PARTY_SLOT_MAIN_EGG_NEXT_SECTION = "# -------------------- 总控与重试"
EGG_REVERSE_LOOKUP_POLICY_MARKER = "# GUI 孵蛋反查覆盖：Normal 优先，方法候选不跨算法累加"
EGG_REVERSE_LOOKUP_WINDOW_MARKER = "# GUI 孵蛋反查覆盖：固定帧窗，不再扩展"
EGG_REVERSE_LOOKUP_METHOD_COMMENT = "# FRLG常用Split优先；Split有候选时不再混入其他方法，避免扩大歧义。"
EGG_PARTY_SLOT_CANDY_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：神奇糖果按目标身份选择队伍末位或固定槽位"
EGG_PARTY_SLOT_CANDY_ORIGINAL_FUNCTION = "FUNC 孵蛋测试_使用神奇糖果指定槽"
EGG_SURF_BATTLE_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：识别冲浪结束后再打开菜单，并在名称 OCR 前确认已进入野生战斗"
EGG_SURF_BATTLE_ORIGINAL_FUNCTION = "FUNC 孵蛋测试_前往池塘并甜甜香气抓捕"
EGG_SURF_BATTLE_NEXT_FUNCTION = "FUNC 孵蛋测试_执行骑车孵化"
EGG_SEED_CONTROLLER_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：复用正式版 Seed 锁定与相邻毫秒细调控制器"
EGG_SEED_CONTROLLER_ORIGINAL_FUNCTION = "FUNC 孵蛋流程_按观测Seed校正等待"
EGG_SEED_CONTROLLER_NEXT_SECTION = "# -------------------- 蛋个体反查"
EGG_HATCH_EXIT_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：孵化骑车前可靠退出能力页、队伍菜单和主菜单"
EGG_HATCH_EXIT_ORIGINAL_FUNCTION = "FUNC 孵蛋测试_执行骑车孵化"
EGG_HATCH_EXIT_NEXT_FUNCTION = "FUNC 孵蛋测试_使用神奇糖果指定槽"
TOGEPI_HATCH_CYCLE_OVERRIDE_MARKER = "# 1.6.4-a 共享孵化执行：定点波克比按孵化周期骑车，不再读取蛋孵化标签。"
TOGEPI_HATCH_CYCLE_ORIGINAL_FUNCTION = "FUNC 获取波克比"
TOGEPI_HATCH_CYCLE_NEXT_FUNCTION = "FUNC 获取游走"
PARTY_SUMMARY_NAVIGATION_MARKER = "# 1.6.4-a 共享反查导航：队伍页按上移次数选择目标。"
PARTY_SUMMARY_NAVIGATION_ANCHOR = "FUNC 打开能力值识图页面"
PARTY_SUMMARY_ORIGINAL_UP_BLOCK = """\
            ELSE
                UP
                500
                UP
                500
            ENDIF
"""
PARTY_SUMMARY_INVALID_CALL_BLOCK = """\
            ELSE
                CALL 反查_队伍页按上移次数选择目标(2)
            ENDIF
"""
PARTY_SUMMARY_SHARED_UP_BLOCK = """\
            ELSE
                $反查队伍槽选择结果 = 反查_队伍页按上移次数选择目标(2)
            ENDIF
"""
EGG_PREPARED_254_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：可从已完成254步的基础存档开始"
EGG_TRANSIENT_RETRY_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：瞬时动作失败重启后继续下一轮"
EGG_TERMINAL_STOP_OVERRIDE_MARKER = "# GUI 孵蛋终止策略：无精确结果时保留当前游戏画面"
EGG_POND_SETTLE_ORIGINAL = """\
    LS RESET
    WAIT 500
    DOWN
    $孵蛋库_已到池塘 = 1
"""
EGG_POND_SETTLE_FIXED = """\
    LS RESET
    WAIT 500
    DOWN
    WAIT 500
    $孵蛋库_已到池塘 = 1
"""
EGG_PREPARED_254_GLOBAL = "$孵蛋从已完成254步开始"
EGG_PREPARED_254_GLOBAL_ANCHOR = "$孵蛋同Seed模式 = 1"
EGG_PARTY_SLOT_CANDY_NEXT_SECTION = "# ============================================================\n# Seed启动与同Seed两次命中"
EGG_HOME_BUFFER_GLOBALS = """\
$孵蛋HOME_BUFFER尝试 = 0
$孵蛋HOME_BUFFER短边界 = 0
$孵蛋HOME_BUFFER长边界 = 0
$孵蛋HOME_BUFFER已有短边界 = 0
$孵蛋HOME_BUFFER已有长边界 = 0
$孵蛋HOME_BUFFER下一延迟 = 0
$孵蛋HOME_BUFFER选中正确 = 0
$孵蛋HOME_BUFFER选中普通 = 0
$孵蛋HOME_BUFFER选中错误 = 0
$孵蛋HOME_BUFFER失败 = 0
"""
HOME_BUFFER_ADAPTIVE_GLOBALS = """\
# HOME_BUFFER 稳定低分自适应默认关闭；开启后只接受连续3次相同且唯一最高的90-94分标签。
$HOME_BUFFER稳定低分自适应 = 0
$HOME_BUFFER自适应最低阈值 = 90
$HOME_BUFFER有效识图阈值 = 95
$HOME_BUFFER自适应稳定要求 = 3
$HOME_BUFFER自适应采样 = 0
$HOME_BUFFER选中正确 = 0
$HOME_BUFFER选中普通 = 0
$HOME_BUFFER选中错误 = 0
$HOME_BUFFER自适应候选状态 = 0
$HOME_BUFFER自适应候选分数 = 0
$HOME_BUFFER自适应首次状态 = 0
$HOME_BUFFER自适应首次分数 = 0
$HOME_BUFFER识别状态 = 0
"""
EGG_SETTINGS_GLOBALS = """\
$孵蛋库_设置识别尝试 = 0
$孵蛋库_设置分数1 = -1
$孵蛋库_设置分数2 = -1
$孵蛋库_设置分数3 = -1
$孵蛋库_设置候选分数 = -1
$孵蛋库_设置最佳分数 = -1
$孵蛋库_设置状态 = -1
"""
EGG_TRANSIENT_RETRY_REPLACEMENTS = (
    (
        """\
    ELIF $孵蛋测试结果 != 1
        PRINT 孵蛋生成、领取或Seed复核野生抓捕失败
        CALL 孵蛋流程_重开下一轮
        RETURN 0
    ENDIF
""",
        f"""\
    {EGG_TRANSIENT_RETRY_OVERRIDE_MARKER}
    ELIF $孵蛋测试结果 != 1
        PRINT 孵蛋生成、领取或Seed复核野生抓捕失败，关闭游戏并继续下一轮
        CALL 孵蛋流程_重开下一轮
        RETURN 2
    ENDIF
""",
    ),
    (
        """\
    PRINT 领取后野生Seed反查失败
    CALL 孵蛋流程_重开下一轮
    RETURN 0
""",
        """\
    PRINT 领取后野生Seed反查失败，关闭游戏并重新预校准
    $孵蛋流程Seed已预校准 = 0
    CALL 孵蛋流程_重开下一轮
    RETURN 2
""",
    ),
    (
        """\
    IF $孵蛋流程孵化结果 != 1
        RETURN 0
    ENDIF
""",
        """\
    IF $孵蛋流程孵化结果 != 1
        PRINT 孵化动作失败，关闭游戏并继续下一轮
        CALL 孵蛋流程_重开下一轮
        RETURN 2
    ENDIF
""",
    ),
)
EGG_TERMINAL_STOP_REPLACEMENTS = (
    (
        """\
    ELIF $孵蛋流程蛋反查结果 == 2
        PRINT 蛋个体在自动扩窗后仍无结果，停止以检查亲本或目标数据
        CALL 孵蛋流程_重开下一轮
        RETURN 0
""",
        f"""\
    {EGG_TERMINAL_STOP_OVERRIDE_MARKER}
    ELIF $孵蛋流程蛋反查结果 == 2
        PRINT 蛋个体在自动扩窗后仍无结果，停止以检查亲本或目标数据
        PRINT 停止前保留当前游戏画面，不关闭或重启游戏
        RETURN 0
""",
    ),
    (
        """\
    ELIF $孵蛋流程蛋反查结果 != 1
        PRINT 蛋个体反查失败，请检查双亲、相性、目标帧或识图配置
        CALL 孵蛋流程_重开下一轮
        RETURN 0
""",
        """\
    ELIF $孵蛋流程蛋反查结果 != 1
        PRINT 蛋个体反查失败，请检查双亲、相性、目标帧或识图配置
        PRINT 停止前保留当前游戏画面，不关闭或重启游戏
        RETURN 0
""",
    ),
)


@dataclass(frozen=True)
class EasyCon118Options:
    nx_model: int | None = None
    paralysis: bool = False
    false_swipe: bool = False
    continue_capture_after_shiny: bool = False
    home_buffer_adaptive_threshold: bool = False


@dataclass(frozen=True)
class EggRunRequest:
    """User-provided Ten Lines Egg result for the experimental same-seed flow."""

    game: str
    seed_mode: int
    target_seed: str
    held_advances: int
    pickup_advances: int
    species_id: int
    compatibility: int
    parent_a_gender: str
    parent_a_ivs: tuple[int, int, int, int, int, int]
    parent_b_gender: str
    parent_b_ivs: tuple[int, int, int, int, int, int]
    start_from_prepared_254: bool = False
    home_buffer_adaptive_threshold: bool = False

    @property
    def nx_model(self) -> int:
        return 2 if self.game.endswith("nx2") else 1

    @property
    def normalized_seed(self) -> str:
        value = self.target_seed.strip().upper()
        if value.startswith("0X"):
            value = value[2:]
        return value.zfill(4)

    def validate(self) -> None:
        if self.game not in {"fr_nx", "fr_nx2", "lg_nx", "lg_nx2"}:
            raise ValueError(f"孵蛋测试只支持火红/叶绿 Switch 1/2，当前为 {self.game!r}")
        if not 0 <= self.seed_mode <= 9:
            raise ValueError("孵蛋 Seed 模式必须在 0-9 之间")
        if self.game.startswith("fr") and self.seed_mode == 3:
            raise ValueError("火红 NX Seed 表不包含模式 3 (stereo_r_a)")
        raw_seed = self.target_seed.strip().upper()
        if raw_seed.startswith("0X"):
            raw_seed = raw_seed[2:]
        seed = self.normalized_seed
        if not raw_seed or len(raw_seed) > 4 or not re.fullmatch(r"[0-9A-F]{4}", seed):
            raise ValueError("孵蛋目标 Seed 必须是 0000-FFFF 的十六进制数")
        if self.held_advances <= 0:
            raise ValueError("Held/生成目标帧必须大于 0")
        if self.pickup_advances - self.held_advances < 1800:
            raise ValueError("Pickup/领取目标帧必须至少比 Held/生成目标帧晚 1800 帧")
        if not 1 <= self.species_id <= 386:
            raise ValueError("孵蛋蛋种全国图鉴编号必须在 1-386 之间")
        if self.compatibility not in {20, 50, 70}:
            raise ValueError("孵蛋双亲相性只能填写 20、50 或 70")
        if self.parent_a_gender not in {"雌", "无性别"}:
            raise ValueError("孵蛋亲本 A 必须是雌或无性别")
        if self.parent_b_gender not in {"雄", "无性别"}:
            raise ValueError("孵蛋亲本 B 必须是雄或无性别")
        if self.parent_a_gender == self.parent_b_gender == "无性别":
            raise ValueError("两只亲本不能同时填写无性别")
        if not isinstance(self.start_from_prepared_254, bool):
            raise ValueError("孵蛋254步启动模式必须是布尔值")
        if not isinstance(self.home_buffer_adaptive_threshold, bool):
            raise ValueError("HOME_BUFFER稳定低分自适应开关必须是布尔值")
        for label, ivs in (("A", self.parent_a_ivs), ("B", self.parent_b_ivs)):
            if len(ivs) != 6 or any(not 0 <= iv <= 31 for iv in ivs):
                raise ValueError(f"亲本 {label} 的六项 IV 必须均在 0-31 之间")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        result = asdict(self)
        result["target_seed"] = self.normalized_seed
        result["nx_model"] = self.nx_model
        result["mode"] = "egg_same_seed_experimental"
        return result


@dataclass(frozen=True)
class EasyConRuntimeCheck:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def parse_easycon_video_devices(output: str) -> dict[int, str]:
    """Parse ``ezcon video --list`` into index-to-name mappings."""
    devices: dict[int, str] = {}
    for match in re.finditer(r"(?m)^\s*\[(\d+)\]\s*(.*?)\s*$", output):
        index = int(match.group(1))
        devices[index] = match.group(2).strip() or "未命名设备"
    return devices


def probe_easycon_devices(
    ezcon_path: str | Path,
    *,
    include_video_names: bool = False,
):
    """Return currently enumerated ports, videos and raw EasyCon output.

    Existing CLI callers receive a set of video indexes.  The GUI opts into a
    mapping so its dropdown can show both the EasyCon index and device name.
    """
    ezcon_path = Path(ezcon_path).resolve()
    run_options = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    port = subprocess.run([str(ezcon_path), "port", "--list"], timeout=15, **run_options)
    video = subprocess.run([str(ezcon_path), "video", "--list"], timeout=20, **run_options)
    if port.returncode != 0 or video.returncode != 0:
        details = "\n".join(filter(None, (port.stderr, video.stderr)))
        raise RuntimeError(f"设备检测命令失败：{details or '未知错误'}")
    ports = {item.upper() for item in re.findall(r"\bCOM\d+\b", port.stdout, re.IGNORECASE)}
    video_devices = parse_easycon_video_devices(video.stdout)
    videos = video_devices if include_video_names else set(video_devices)
    output = "端口：\n" + port.stdout + "\n采集设备：\n" + video.stdout
    if not ports:
        output += "\n未检测到 EasyCon 单片机串口。"
    if not videos:
        output += "\n未检测到采集设备。"
    return ports, videos, output


def inspect_label_corpus(label_dir: str | Path) -> dict[str, Any]:
    """Return a deterministic fingerprint of a 1.1.8 ``ImgLabel`` folder."""
    label_dir = Path(label_dir)
    files = sorted(
        (path for path in label_dir.iterdir() if path.is_file() and path.suffix == ".IL"),
        key=lambda path: path.name,
    )
    digest = hashlib.sha256()
    method_counts: dict[int, int] = {}
    total_bytes = 0
    for path in files:
        name = path.name.encode("utf-8")
        data = path.read_bytes()
        digest.update(struct.pack(">I", len(name)))
        digest.update(name)
        digest.update(struct.pack(">Q", len(data)))
        digest.update(data)
        total_bytes += len(data)
        payload = json.loads(data.decode("utf-8-sig"))
        method = int(payload.get("searchMethod", 5))
        method_counts[method] = method_counts.get(method, 0) + 1
    return {
        "count": len(files),
        "bytes": total_bytes,
        "methods": method_counts,
        "sha256": digest.hexdigest(),
    }


def copy_easycon118_extension_labels(label_dir: str | Path) -> None:
    """Install the audited repository labels into an ImgLabel directory.

    The bundled text files may carry a source-control newline. EasyCon's
    audited corpus uses the original one-line IL form, so normalize only the
    trailing line ending while copying.
    """
    label_dir = Path(label_dir)
    if not label_dir.is_dir():
        raise FileNotFoundError(f"1.1.8 包缺少 ImgLabel 目录: {label_dir}")
    for name in EASYCON118_EXTENSION_LABEL_NAMES:
        source = EASYCON118_EXTENSION_LABEL_DIR / name
        if not source.is_file():
            raise FileNotFoundError(f"仓库缺少 EasyCon 扩展标签: {name}")
        (label_dir / name).write_bytes(source.read_bytes().rstrip(b"\r\n"))


def inspect_script_corpus(source_dir: str | Path) -> dict[str, Any]:
    """Fingerprint both official 1.1.8 entry scripts and every file under ``lib``."""
    source_dir = Path(source_dir)
    templates = [source_dir / name for name in EXPECTED_TEMPLATE_NAMES]
    missing_templates = [path.name for path in templates if not path.is_file()]
    if missing_templates:
        raise FileNotFoundError(
            f"1.1.8 包缺少正式/孵蛋入口: {', '.join(missing_templates)}"
        )
    lib_dir = source_dir / "lib"
    if not lib_dir.is_dir():
        raise FileNotFoundError(f"1.1.8 包缺少 lib 目录: {lib_dir}")
    files = [(path.name, path) for path in templates]
    files.extend(
        (path.relative_to(source_dir).as_posix(), path)
        for path in sorted(item for item in lib_dir.rglob("*") if item.is_file())
    )
    digest = hashlib.sha256()
    total_bytes = 0
    for relative_name, path in files:
        name = relative_name.encode("utf-8")
        data = path.read_bytes()
        digest.update(struct.pack(">I", len(name)))
        digest.update(name)
        digest.update(struct.pack(">Q", len(data)))
        digest.update(data)
        total_bytes += len(data)
    return {
        "count": len(files),
        "bytes": total_bytes,
        "sha256": digest.hexdigest(),
        "template": STANDARD_TEMPLATE_NAME,
        "templates": [path.name for path in templates],
    }


def _is_wild(plan: RunPlan) -> bool:
    key = (plan.request.method or plan.target.method).lower()
    return "wild" in key


def _game_text(game: str) -> str:
    if game.startswith("fr"):
        return "火红"
    if game.startswith("lg"):
        return "叶绿"
    raise ValueError(f"1.1.8 只支持火红/叶绿，当前游戏为 {game!r}")


def plan_to_user_values(
    plan: RunPlan,
    options: EasyCon118Options | None = None,
) -> dict[str, Any]:
    """Map a generated plan to the editable variables at the top of 1.1.8."""
    options = options or EasyCon118Options()
    nx_model = options.nx_model
    if nx_model is None:
        nx_model = 2 if plan.request.game.endswith("nx2") else 1
    if nx_model not in (1, 2):
        raise ValueError("NX 机型必须是 1 (Switch1) 或 2 (Switch2)")
    expected_nx_model = 2 if plan.request.game.endswith("nx2") else 1
    if nx_model != expected_nx_model:
        raise ValueError(
            f"搜索游戏 {plan.request.game} 必须使用 NX 机型 {expected_nx_model}，"
            f"不能写入 {nx_model}"
        )

    is_wild = _is_wild(plan)
    category_zh = CATEGORY_EN_TO_ZH.get(plan.request.category, plan.request.category)
    location_zh = location_to_zh(plan.request.location)
    return {
        "游戏版本文本": _game_text(plan.request.game),
        "Seed模式": plan.seed_mode,
        "NX机型": nx_model,
        "目标Seed": plan.initial_seed.seed.upper(),
        "目标消耗帧": plan.initial_seed.advances,
        "目标全国图鉴编号": plan.species_id,
        "静态或野生": "野生" if is_wild else "静态",
        "宝可梦遭遇方法": category_zh if is_wild else "草丛",
        "宝可梦遭遇地点": location_zh if is_wild else "",
        "麻痹": int(options.paralysis),
        "点到为止": int(options.false_swipe),
        "出闪后继续抓捕": int(options.continue_capture_after_shiny),
    }


def egg_request_to_user_values(request: EggRunRequest) -> dict[str, Any]:
    """Map a Ten Lines Egg result to the experimental same-seed ECS fields."""
    request.validate()
    values: dict[str, Any] = {
        "游戏版本文本": _game_text(request.game),
        "Seed模式": request.seed_mode,
        "NX机型": request.nx_model,
        "目标Seed": request.normalized_seed,
        "目标消耗帧": request.held_advances,
        "目标宝可梦名称": "",
        "目标全国图鉴编号": request.species_id,
        "静态或野生": "孵蛋",
        "孵蛋同Seed模式": 1,
        "孵蛋领取目标帧": request.pickup_advances,
        "孵蛋双亲相性": request.compatibility,
        "孵蛋亲本A性别": request.parent_a_gender,
        "孵蛋亲本B性别": request.parent_b_gender,
    }
    for parent, ivs in (("A", request.parent_a_ivs), ("B", request.parent_b_ivs)):
        for stat, value in zip(("HP", "ATK", "DEF", "SPA", "SPD", "SPE"), ivs):
            values[f"孵蛋双亲{parent}_{stat}"] = value
    return values


def _ecs_literal(value: Any) -> str:
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def configure_template_text(
    template_text: str,
    plan: RunPlan,
    options: EasyCon118Options | None = None,
    *,
    allow_experimental: bool = False,
) -> str:
    """Replace only the declared 1.1.8 user-input assignments."""
    if not plan.route_support.can_start and not allow_experimental:
        raise ValueError(
            "该路线只允许搜索/生成计划，不能生成可启动的 1.1.8 正式脚本: "
            + plan.route_support.summary
        )

    return _configure_user_values(template_text, plan_to_user_values(plan, options))


def _configure_user_values(template_text: str, values: dict[str, Any]) -> str:
    marker = "# ============================进阶设置"
    user_section, separator, remainder = template_text.partition(marker)
    if not separator:
        raise ValueError("1.1.8 模板缺少进阶设置分界标记，拒绝在未知版本中替换参数")
    configured = user_section
    for name, value in values.items():
        pattern = re.compile(rf"(?m)^\s*\${re.escape(name)}\s*=\s*[^\r\n]*$")
        configured, count = pattern.subn(f"${name} = {_ecs_literal(value)}", configured)
        if count != 1:
            raise ValueError(f"1.1.8 模板字段 ${name} 应出现 1 次，实际为 {count} 次")
    return configured + (separator + remainder if separator else "")


def configure_egg_template_text(template_text: str, request: EggRunRequest) -> str:
    """Configure the 1.6.4a-only experimental same-seed egg entry."""
    configured = _configure_user_values(template_text, egg_request_to_user_values(request))
    configured = _apply_egg_summary_fix_text(configured)
    return _apply_egg_reverse_lookup_policy_text(configured)


def _apply_egg_summary_fix_text(template_text: str) -> str:
    """Keep function calls out of PRINT and remove a stray quote in the egg summary."""
    inline_species = (
        "    PRINT 孵蛋蛋种: & 目标中文名称($游戏版本, $孵蛋蛋种族全国图鉴编号)"
        " & \"（全国图鉴 \" & $孵蛋蛋种族全国图鉴编号 & \"）\""
    )
    fixed_species = (
        "    $孵蛋蛋种名称文本 = 目标中文名称($游戏版本, $孵蛋蛋种族全国图鉴编号)\n"
        "    PRINT 孵蛋蛋种: & $孵蛋蛋种名称文本 & \"（全国图鉴 \""
        " & $孵蛋蛋种族全国图鉴编号 & \"）\""
    )
    bad_parents = (
        "    PRINT 亲本: A \" & $孵蛋亲本A性别 & \"，B \""
        " & $孵蛋亲本B性别 & \"，相性 \" & $孵蛋双亲相性"
    )
    fixed_parents = (
        "    PRINT 亲本: A & $孵蛋亲本A性别 & \"，B \""
        " & $孵蛋亲本B性别 & \"，相性 \" & $孵蛋双亲相性"
    )
    if fixed_species not in template_text:
        if template_text.count(inline_species) != 1:
            raise ValueError("孵蛋模板缺少唯一的蛋种摘要，拒绝应用日志修正")
        template_text = template_text.replace(inline_species, fixed_species, 1)
    if fixed_parents not in template_text:
        if template_text.count(bad_parents) != 1:
            raise ValueError("孵蛋模板缺少唯一的亲本摘要，拒绝应用日志修正")
        template_text = template_text.replace(bad_parents, fixed_parents, 1)
    return template_text


def _egg_prepared_254_override_text(enabled: bool) -> str:
    value = 1 if enabled else 0
    return f"""\
{EGG_PREPARED_254_OVERRIDE_MARKER}
{EGG_PREPARED_254_GLOBAL} = {value}
"""


def _apply_egg_prepared_254_runtime_override_text(
    template_text: str,
    enabled: bool,
) -> str:
    """Optionally skip only the one-time walk/settings/save preparation."""
    override = _egg_prepared_254_override_text(enabled).rstrip()
    if EGG_PREPARED_254_OVERRIDE_MARKER in template_text:
        assignment = re.compile(
            rf"(?m)^\s*{re.escape(EGG_PREPARED_254_GLOBAL)}\s*=\s*[01]\s*$"
        )
        template_text, count = assignment.subn(
            f"{EGG_PREPARED_254_GLOBAL} = {1 if enabled else 0}",
            template_text,
        )
        if count != 1:
            raise ValueError("孵蛋模板的254步启动模式字段不唯一，拒绝生成运行副本")
        return template_text

    if template_text.count(EGG_PREPARED_254_GLOBAL_ANCHOR) != 1:
        raise ValueError("孵蛋模板缺少唯一的同Seed模式字段，拒绝添加254步启动模式")
    template_text = template_text.replace(
        EGG_PREPARED_254_GLOBAL_ANCHOR,
        EGG_PREPARED_254_GLOBAL_ANCHOR + "\n" + override,
        1,
    )

    original = """\
    $孵蛋前置结果 = 孵蛋测试_执行前置准备($Seed模式, $游戏设置识图阈值)
    IF $孵蛋前置结果 != 1
        RETURN 0
    ENDIF
    CALL 孵蛋流程_重开下一轮
"""
    replacement = """\
    IF $孵蛋从已完成254步开始 == 1
        PRINT 【孵蛋准备】使用已有254步基础存档，跳过走位、设置检查和存档
    ELSE
        $孵蛋前置结果 = 孵蛋测试_执行前置准备($Seed模式, $游戏设置识图阈值)
        IF $孵蛋前置结果 != 1
            RETURN 0
        ENDIF
    ENDIF
    CALL 孵蛋流程_重开下一轮
"""
    if template_text.count(original) != 1:
        raise ValueError("孵蛋模板缺少唯一的前置准备调用，拒绝添加254步启动模式")
    return template_text.replace(original, replacement, 1)


def _apply_ocr_runtime_fallback_text(library_text: str) -> str:
    """Do not feed EasyCon OCR sentinel strings into Pokémon-name correction."""
    if OCR_RUNTIME_FALLBACK_MARKER in library_text:
        return library_text
    if library_text.count(OCR_NAME_ORIGINAL_FUNCTION) != 1:
        raise ValueError("OCR 名称库缺少唯一的识别函数，拒绝应用不可用兜底")
    if library_text.count(OCR_NAME_NEXT_FUNCTION) != 1:
        raise ValueError("OCR 名称库缺少唯一的后继函数，拒绝应用不可用兜底")
    start = library_text.index(OCR_NAME_ORIGINAL_FUNCTION)
    end = library_text.index(OCR_NAME_NEXT_FUNCTION, start)
    replacement = OCR_RUNTIME_FALLBACK_FUNCTION.rstrip() + "\n\n"
    return library_text[:start] + replacement + library_text[end:]


def apply_ocr_runtime_fallback(library_path: str | Path) -> str:
    """Patch a copied runtime library and return the audited overlay hash."""
    library_path = Path(library_path)
    configured = _apply_ocr_runtime_fallback_text(
        library_path.read_text(encoding="utf-8")
    )
    library_path.write_text(configured, encoding="utf-8")
    return hashlib.sha256(OCR_RUNTIME_FALLBACK_FUNCTION.encode("utf-8")).hexdigest()


def _apply_wild_pid_retry_limit_text(template_text: str) -> str:
    """Set the reviewed runtime Wild PID retry cap without altering its algorithms."""
    if WILD_PID_RETRY_LIMIT_MARKER in template_text:
        return template_text
    imported_count = template_text.count(WILD_PID_RETRY_LIMIT_IMPORTED)
    if imported_count != 1:
        raise ValueError("1.1.8 模板的野生 PID 尝试上限不唯一，拒绝生成运行副本")
    return template_text.replace(
        WILD_PID_RETRY_LIMIT_IMPORTED,
        WILD_PID_RETRY_LIMIT_MARKER + "\n" + WILD_PID_RETRY_LIMIT_RUNTIME,
        1,
    )


def apply_wild_pid_retry_limit(main_path: str | Path) -> str:
    """Apply the configured Wild PID retry cap and return the overlay hash."""
    main_path = Path(main_path)
    configured = _apply_wild_pid_retry_limit_text(main_path.read_text(encoding="utf-8"))
    main_path.write_text(configured, encoding="utf-8")
    return hashlib.sha256(
        (WILD_PID_RETRY_LIMIT_MARKER + "\n" + WILD_PID_RETRY_LIMIT_RUNTIME).encode(
            "utf-8"
        )
    ).hexdigest()


def _apply_egg_party_slot_main_runtime_override_text(
    template_text: str,
    override_text: str,
) -> str:
    """Select just-caught wild Pokémon by party tail and the egg by slot five."""
    if EGG_PARTY_SLOT_MAIN_OVERRIDE_MARKER in template_text:
        start = template_text.index(EGG_PARTY_SLOT_MAIN_OVERRIDE_MARKER)
    else:
        if template_text.count(EGG_PARTY_SLOT_MAIN_ORIGINAL_FUNCTION) != 1:
            raise ValueError("孵蛋模板缺少唯一的队伍槽选择函数，拒绝应用末位导航修正")
        start = template_text.index(EGG_PARTY_SLOT_MAIN_ORIGINAL_FUNCTION)
    if template_text.count(EGG_PARTY_SLOT_MAIN_NEXT_SECTION) != 1:
        raise ValueError("孵蛋模板缺少野生Seed验证分区，拒绝应用末位导航修正")
    end = template_text.index(EGG_PARTY_SLOT_MAIN_NEXT_SECTION, start)
    replacement = override_text.rstrip() + "\n\n"
    template_text = template_text[:start] + replacement + template_text[end:]

    call_replacements = (
        (
            "$孵蛋流程开页结果 = 孵蛋流程_打开指定槽能力页($队伍位置)",
            "$孵蛋流程开页结果 = 孵蛋流程_打开指定槽能力页($队伍位置, 1)",
            "野生能力页末位选择",
        ),
        (
            "$神奇糖果结果 = 孵蛋测试_使用神奇糖果指定槽($队伍位置)",
            "$神奇糖果结果 = 孵蛋测试_使用神奇糖果指定槽($队伍位置, 1)",
            "野生神奇糖果末位选择",
        ),
        (
            "$孵蛋流程开页结果 = 孵蛋流程_打开指定槽能力页(5)",
            "$孵蛋流程开页结果 = 孵蛋流程_打开指定槽能力页(5, 0)",
            "蛋能力页第五槽选择",
        ),
        (
            "$神奇糖果结果 = 孵蛋测试_使用神奇糖果指定槽(5)",
            "$神奇糖果结果 = 孵蛋测试_使用神奇糖果指定槽(5, 0)",
            "蛋神奇糖果第五槽选择",
        ),
    )
    for original, fixed, description in call_replacements:
        if fixed in template_text:
            continue
        if template_text.count(original) != 1:
            raise ValueError(f"孵蛋模板缺少唯一的{description}调用，拒绝应用末位导航修正")
        template_text = template_text.replace(original, fixed, 1)

    egg_start = template_text.index(EGG_PARTY_SLOT_MAIN_EGG_FUNCTION)
    if template_text.count(EGG_PARTY_SLOT_MAIN_EGG_NEXT_SECTION) == 1:
        egg_end = template_text.index(EGG_PARTY_SLOT_MAIN_EGG_NEXT_SECTION, egg_start)
    else:
        # Minimal unit fixtures may stop after the egg function; the real
        # 1.1.8 template is still checked against the explicit next section.
        egg_end = template_text.index("ENDFUNC", egg_start)
    egg_section = template_text[egg_start:egg_end]
    if "$孵蛋流程开页结果 = 孵蛋流程_喂糖后打开蛋能力页()" not in egg_section:
        for indent in ("        ", "    "):
            generic_candy_navigation = (
                f"{indent}$刚使用神奇糖果 = 1\n"
                f"{indent}CALL 打开能力值识图页面"
            )
            if egg_section.count(generic_candy_navigation) != 1:
                continue
            egg_candy_navigation = (
                f"{indent}$刚使用神奇糖果 = 1\n"
                f"{indent}$孵蛋流程开页结果 = 孵蛋流程_喂糖后打开蛋能力页()\n"
                f"{indent}IF $孵蛋流程开页结果 != 1\n"
                f"{indent}    RETURN 0\n"
                f"{indent}ENDIF"
            )
            egg_section = egg_section.replace(
                generic_candy_navigation,
                egg_candy_navigation,
                1,
            )
            break
        else:
            raise ValueError("孵蛋个体反查缺少唯一的通用喂糖后导航调用，拒绝应用第五槽修正")
        template_text = template_text[:egg_start] + egg_section + template_text[egg_end:]
    return template_text


def _apply_egg_reverse_lookup_window_text(template_text: str) -> str:
    """Keep egg candidate scans inside the configured frame tolerance."""
    if EGG_REVERSE_LOOKUP_WINDOW_MARKER in template_text:
        return template_text

    egg_start = template_text.find(EGG_PARTY_SLOT_MAIN_EGG_FUNCTION)
    if egg_start < 0:
        return template_text
    egg_end = template_text.find(EGG_PARTY_SLOT_MAIN_EGG_NEXT_SECTION, egg_start)
    if egg_end < 0:
        raise ValueError("孵蛋模板缺少总控与重试分区，拒绝应用固定帧窗修正")
    egg_section = template_text[egg_start:egg_end]
    original = """        FOR $孵蛋流程蛋扩窗层 = 0 TO 2
            IF $孵蛋流程蛋扩窗层 == 0
                $孵蛋流程蛋帧半宽 = $孵蛋个体反查帧容差
            ELIF $孵蛋流程蛋扩窗层 == 1
                $孵蛋流程蛋帧半宽 = 5000
            ELSE
                $孵蛋流程蛋帧半宽 = 10000
            ENDIF
"""
    fixed = """        # GUI 孵蛋反查覆盖：固定帧窗，不再扩展
        FOR $孵蛋流程蛋扩窗层 = 0 TO 0
            $孵蛋流程蛋帧半宽 = $孵蛋个体反查帧容差
"""
    if original not in egg_section:
        # Minimal unit fixtures may omit the full scan loop. The real template
        # is still guarded by the exact replacement above.
        return template_text
    egg_section = egg_section.replace(original, fixed, 1)
    expansion_log = "            PRINT 孵蛋蛋个体反查第 & $孵蛋流程蛋扩窗层 & \" 层无结果，自动扩窗\""
    fixed_log = "            PRINT 孵蛋蛋个体反查固定帧窗无结果"
    if egg_section.count(expansion_log) != 1:
        raise ValueError("孵蛋模板缺少唯一的扩窗日志，拒绝应用固定帧窗修正")
    egg_section = egg_section.replace(expansion_log, fixed_log, 1)
    return template_text[:egg_start] + egg_section + template_text[egg_end:]


def _apply_egg_reverse_lookup_policy_text(template_text: str) -> str:
    """Prefer Normal, then Split, without combining candidates across methods."""
    if EGG_REVERSE_LOOKUP_POLICY_MARKER in template_text:
        return _apply_egg_reverse_lookup_window_text(template_text)

    # This limit belongs to the egg reverse lookup only. The separate generic
    # wild reverse candy limit remains unchanged.
    template_text = template_text.replace(
        "$孵蛋蛋反查最多糖果 = 8",
        "$孵蛋蛋反查最多糖果 = 20",
        1,
    )

    egg_start = template_text.find("FUNC 孵蛋流程_执行蛋个体反查(): INT")
    if egg_start < 0:
        return template_text
    egg_end = template_text.find(EGG_PARTY_SLOT_MAIN_EGG_NEXT_SECTION, egg_start)
    if egg_end < 0:
        raise ValueError("孵蛋模板缺少总控与重试分区，拒绝应用反查方法优先级修正")
    method_start = template_text.find(EGG_REVERSE_LOOKUP_METHOD_COMMENT, egg_start, egg_end)
    if method_start < 0:
        raise ValueError("孵蛋模板缺少候选方法扫描分区，拒绝应用Normal优先修正")
    method_end = template_text.find(
        "            IF $孵蛋流程候选总数 > 0",
        method_start,
        egg_end,
    )
    if method_end < 0:
        raise ValueError("孵蛋模板缺少候选方法扫描结束标记，拒绝应用Normal优先修正")

    replacement = """# GUI 孵蛋反查覆盖：Normal 优先，方法候选不跨算法累加
            # Normal 无候选时再尝试 Split；仅在两者均无结果时保留兼容回退方法。
            FOR $孵蛋流程方法顺序 = 0 TO 3
                IF $孵蛋流程方法顺序 == 0
                    $孵蛋流程扫描方法 = 11
                ELIF $孵蛋流程方法顺序 == 1
                    $孵蛋流程扫描方法 = 12
                ELIF $孵蛋流程方法顺序 == 2
                    $孵蛋流程扫描方法 = 13
                ELSE
                    $孵蛋流程扫描方法 = 14
                ENDIF
                $孵蛋流程蛋扫描结果 = 孵蛋反查_执行HEX($孵蛋Seed关系模式, $目标Seed, $目标Seed, $孵蛋流程Held最小帧, $孵蛋流程Held最大帧, $孵蛋流程Pickup最小帧, $孵蛋流程Pickup最大帧, $孵蛋HeldOffset, $孵蛋PickupOffset, $孵蛋流程扫描方法, $孵蛋双亲相性, 256)
                IF $孵蛋流程蛋扫描结果 < 0
                    PRINT 孵蛋蛋个体反查参数无效
                    RETURN 0
                ENDIF
                $孵蛋流程当前方法候选数 = 孵蛋反查_取总命中数()
                IF $孵蛋流程当前方法候选数 > 0
                    PRINT 孵蛋方法 & $孵蛋流程扫描方法 & " 候选: " & $孵蛋流程当前方法候选数
                    $孵蛋流程候选总数 = $孵蛋流程当前方法候选数
                    IF $孵蛋流程当前方法候选数 == 1
                        $孵蛋流程实际Held帧 = 孵蛋反查_取结果Held帧(0)
                        $孵蛋流程实际Pickup帧 = 孵蛋反查_取结果Pickup帧(0)
                        $孵蛋流程实际方法 = $孵蛋流程扫描方法
                    ENDIF
                    BREAK
                ENDIF
            NEXT
"""
    configured = template_text[:method_start] + replacement + template_text[method_end:]
    return _apply_egg_reverse_lookup_window_text(configured)


def _apply_egg_party_slot_candy_runtime_override_text(
    library_text: str,
    override_text: str,
) -> str:
    """Use the same party-tail rule when feeding candy during reverse lookup."""
    if EGG_PARTY_SLOT_CANDY_OVERRIDE_MARKER in library_text:
        start = library_text.index(EGG_PARTY_SLOT_CANDY_OVERRIDE_MARKER)
    else:
        if library_text.count(EGG_PARTY_SLOT_CANDY_ORIGINAL_FUNCTION) != 1:
            raise ValueError("孵蛋流程库缺少唯一的神奇糖果函数，拒绝应用末位导航修正")
        start = library_text.index(EGG_PARTY_SLOT_CANDY_ORIGINAL_FUNCTION)
    if library_text.count(EGG_PARTY_SLOT_CANDY_NEXT_SECTION) != 1:
        raise ValueError("孵蛋流程库缺少Seed启动分区，拒绝应用末位导航修正")
    end = library_text.index(EGG_PARTY_SLOT_CANDY_NEXT_SECTION, start)
    replacement = override_text.rstrip() + "\n\n"
    return library_text[:start] + replacement + library_text[end:]


def _apply_egg_surf_battle_runtime_override_text(
    library_text: str,
    override_text: str,
) -> str:
    """Gate egg-route name OCR on a verified wild-battle screen."""
    if EGG_SURF_BATTLE_OVERRIDE_MARKER in library_text:
        start = library_text.index(EGG_SURF_BATTLE_OVERRIDE_MARKER)
    else:
        if library_text.count(EGG_SURF_BATTLE_ORIGINAL_FUNCTION) != 1:
            raise ValueError("孵蛋流程库缺少唯一的池塘抓捕函数，拒绝应用冲浪修正")
        start = library_text.index(EGG_SURF_BATTLE_ORIGINAL_FUNCTION)
    if library_text.count(EGG_SURF_BATTLE_NEXT_FUNCTION) != 1:
        raise ValueError("孵蛋流程库缺少池塘抓捕后继函数，拒绝应用冲浪修正")
    end = library_text.index(EGG_SURF_BATTLE_NEXT_FUNCTION, start)
    replacement = override_text.rstrip() + "\n\n"
    return library_text[:start] + replacement + library_text[end:]


def _apply_egg_seed_controller_runtime_override_text(
    template_text: str,
    override_text: str,
) -> str:
    """Reuse the formal Seed lock/fine-tune controller in the egg entry."""
    if EGG_SEED_CONTROLLER_OVERRIDE_MARKER in template_text:
        start = template_text.index(EGG_SEED_CONTROLLER_OVERRIDE_MARKER)
    else:
        if template_text.count(EGG_SEED_CONTROLLER_ORIGINAL_FUNCTION) != 1:
            raise ValueError("孵蛋模板缺少唯一的Seed校正函数，拒绝应用控制器修正")
        start = template_text.index(EGG_SEED_CONTROLLER_ORIGINAL_FUNCTION)
    if template_text.count(EGG_SEED_CONTROLLER_NEXT_SECTION) != 1:
        raise ValueError("孵蛋模板缺少蛋个体反查分区，拒绝应用Seed控制器修正")
    end = template_text.index(EGG_SEED_CONTROLLER_NEXT_SECTION, start)
    replacement = override_text.rstrip() + "\n\n"
    return template_text[:start] + replacement + template_text[end:]


def _apply_egg_transient_retry_runtime_override_text(template_text: str) -> str:
    """Keep transient egg-route failures inside the existing retry loop."""
    if EGG_TRANSIENT_RETRY_OVERRIDE_MARKER in template_text:
        return template_text
    configured = template_text
    for original, replacement in EGG_TRANSIENT_RETRY_REPLACEMENTS:
        if configured.count(original) != 1:
            raise ValueError("孵蛋模板缺少唯一的瞬时失败分支，拒绝应用自动重试修正")
        configured = configured.replace(original, replacement, 1)
    return configured


def _apply_egg_terminal_stop_policy_text(template_text: str) -> str:
    """Stop terminal egg lookup failures without closing or restarting the game."""
    if EGG_TERMINAL_STOP_OVERRIDE_MARKER in template_text:
        return template_text
    configured = template_text
    for original, replacement in EGG_TERMINAL_STOP_REPLACEMENTS:
        if configured.count(original) != 1:
            raise ValueError("孵蛋模板缺少唯一的终止分支，拒绝应用保留画面策略")
        configured = configured.replace(original, replacement, 1)
    return configured


def _apply_egg_pond_settle_delay_text(library_text: str) -> str:
    """Let the final pond-facing input settle before the surf sequence starts."""
    if EGG_POND_SETTLE_FIXED in library_text:
        return library_text
    if library_text.count(EGG_POND_SETTLE_ORIGINAL) != 1:
        raise ValueError("孵蛋流程库缺少唯一的池塘到位等待位置，拒绝应用稳定延迟")
    return library_text.replace(
        EGG_POND_SETTLE_ORIGINAL,
        EGG_POND_SETTLE_FIXED,
        1,
    )


def _apply_egg_hatch_exit_runtime_override_text(
    library_text: str,
    override_text: str,
) -> str:
    """Reliably leave summary/menu layers before starting the bicycle loop."""
    if EGG_HATCH_EXIT_OVERRIDE_MARKER in library_text:
        start = library_text.index(EGG_HATCH_EXIT_OVERRIDE_MARKER)
    else:
        if library_text.count(EGG_HATCH_EXIT_ORIGINAL_FUNCTION) != 1:
            raise ValueError("孵蛋流程库缺少唯一的骑车孵化函数，拒绝应用退页修正")
        start = library_text.index(EGG_HATCH_EXIT_ORIGINAL_FUNCTION)
    if library_text.count(EGG_HATCH_EXIT_NEXT_FUNCTION) != 1:
        raise ValueError("孵蛋流程库缺少骑车孵化后继函数，拒绝应用退页修正")
    end = library_text.index(EGG_HATCH_EXIT_NEXT_FUNCTION, start)
    replacement = override_text.rstrip() + "\n\n"
    return library_text[:start] + replacement + library_text[end:]


def _apply_togepi_hatch_cycle_override_text(
    library_text: str,
    override_text: str,
) -> str:
    """Use the shared fixed-cycle hatch execution for the static Togepi gift."""
    if TOGEPI_HATCH_CYCLE_OVERRIDE_MARKER in library_text:
        start = library_text.index(TOGEPI_HATCH_CYCLE_OVERRIDE_MARKER)
    else:
        if library_text.count(TOGEPI_HATCH_CYCLE_ORIGINAL_FUNCTION) != 1:
            raise ValueError("静态目标库缺少唯一的波克比函数，拒绝应用周期孵化修正")
        start = library_text.index(TOGEPI_HATCH_CYCLE_ORIGINAL_FUNCTION)
        comment_start = library_text.rfind("# 175:", 0, start)
        if comment_start >= 0:
            start = comment_start
    if library_text.count(TOGEPI_HATCH_CYCLE_NEXT_FUNCTION) != 1:
        raise ValueError("静态目标库缺少波克比后继函数，拒绝应用周期孵化修正")
    end = library_text.index(TOGEPI_HATCH_CYCLE_NEXT_FUNCTION, start)
    next_comment = library_text.rfind("# 243:", start, end)
    if next_comment >= 0:
        end = next_comment
    replacement = override_text.rstrip() + "\n\n"
    return library_text[:start] + replacement + library_text[end:]


def _apply_party_summary_navigation_text(
    template_text: str,
    helper_text: str,
) -> str:
    """Share party-page target selection between normal and egg reverse lookup."""
    if PARTY_SUMMARY_NAVIGATION_MARKER not in template_text:
        if template_text.count(PARTY_SUMMARY_NAVIGATION_ANCHOR) != 1:
            raise ValueError("主脚本缺少唯一的能力页入口，拒绝注入共享队伍导航")
        anchor = template_text.index(PARTY_SUMMARY_NAVIGATION_ANCHOR)
        template_text = (
            template_text[:anchor]
            + helper_text.rstrip()
            + "\n\n"
            + template_text[anchor:]
        )

    if PARTY_SUMMARY_SHARED_UP_BLOCK in template_text:
        return template_text
    if PARTY_SUMMARY_INVALID_CALL_BLOCK in template_text:
        return template_text.replace(
            PARTY_SUMMARY_INVALID_CALL_BLOCK,
            PARTY_SUMMARY_SHARED_UP_BLOCK,
            1,
        )
    if template_text.count(PARTY_SUMMARY_ORIGINAL_UP_BLOCK) != 1:
        raise ValueError("主脚本普通反查的末位导航不唯一，拒绝替换共享队伍导航")
    return template_text.replace(
        PARTY_SUMMARY_ORIGINAL_UP_BLOCK,
        PARTY_SUMMARY_SHARED_UP_BLOCK,
        1,
    )


def _apply_standard_home_buffer_runtime_override_text(
    template_text: str,
    override_text: str,
) -> str:
    """Replace the standard 1.1.8 HOME_BUFFER controller idempotently."""
    if STANDARD_HOME_BUFFER_OVERRIDE_MARKER in template_text:
        start = template_text.index(STANDARD_HOME_BUFFER_OVERRIDE_MARKER)
    else:
        if template_text.count(EGG_HOME_BUFFER_ORIGINAL_FUNCTION) != 1:
            raise ValueError("正式版模板缺少唯一的 HOME_BUFFER 函数，拒绝应用自适应覆盖")
        start = template_text.index(EGG_HOME_BUFFER_ORIGINAL_FUNCTION)
    if template_text.count(EGG_HOME_BUFFER_NEXT_FUNCTION) != 1:
        raise ValueError("正式版模板缺少 HOME_BUFFER 后继函数，拒绝应用自适应覆盖")
    end = template_text.index(EGG_HOME_BUFFER_NEXT_FUNCTION, start)
    replacement = override_text.rstrip() + "\n\n"
    return template_text[:start] + replacement + template_text[end:]


def _apply_home_buffer_adaptive_classifier_text(
    template_text: str,
    classifier_text: str,
    enabled: bool,
) -> str:
    """Install the shared classifier and set its opt-in switch."""
    global_anchor = "$HOME_BUFFER当前错误退出_NS2 = 0\n"
    if f"${HOME_BUFFER_ADAPTIVE_SWITCH} =" not in template_text:
        if template_text.count(global_anchor) != 1:
            raise ValueError("模板缺少唯一的 HOME_BUFFER 状态区，拒绝应用稳定低分自适应")
        template_text = template_text.replace(
            global_anchor,
            global_anchor + HOME_BUFFER_ADAPTIVE_GLOBALS,
            1,
        )

    classifier = classifier_text.rstrip() + "\n\n"
    controller_markers = (
        STANDARD_HOME_BUFFER_OVERRIDE_MARKER,
        EGG_HOME_BUFFER_OVERRIDE_MARKER,
    )
    if HOME_BUFFER_ADAPTIVE_CLASSIFIER_MARKER in template_text:
        start = template_text.index(HOME_BUFFER_ADAPTIVE_CLASSIFIER_MARKER)
        following = [
            template_text.index(marker, start)
            for marker in controller_markers
            if marker in template_text[start + 1 :]
        ]
        if not following:
            original_controller = re.search(
                r"(?m)^FUNC HOME_BUFFER\s*$",
                template_text[start + 1 :],
            )
            if original_controller:
                following.append(start + 1 + original_controller.start())
        if not following:
            raise ValueError("HOME_BUFFER 自适应分类器缺少后继控制器")
        end = min(following)
        template_text = template_text[:start] + classifier + template_text[end:]
    else:
        anchors = [
            template_text.index(marker)
            for marker in controller_markers
            if marker in template_text
        ]
        if not anchors:
            original_controller = re.search(
                r"(?m)^FUNC HOME_BUFFER\s*$",
                template_text,
            )
            if original_controller:
                anchors.append(original_controller.start())
        if not anchors:
            raise ValueError("模板缺少 HOME_BUFFER 控制器，拒绝插入自适应分类器")
        start = min(anchors)
        template_text = template_text[:start] + classifier + template_text[start:]

    switch_pattern = re.compile(
        rf"(?m)^\${re.escape(HOME_BUFFER_ADAPTIVE_SWITCH)}\s*=\s*[^\r\n]*$"
    )
    template_text, count = switch_pattern.subn(
        f"${HOME_BUFFER_ADAPTIVE_SWITCH} = {1 if enabled else 0}",
        template_text,
    )
    if count != 1:
        raise ValueError("HOME_BUFFER 稳定低分自适应开关应出现 1 次")
    return template_text


def _apply_egg_home_buffer_runtime_override_text(
    template_text: str,
    override_text: str,
) -> str:
    """Replace HOME_BUFFER with a bounded, NX-specific bracket search."""
    global_anchor = "$HOME_BUFFER当前错误退出_NS2 = 0\n"
    if EGG_HOME_BUFFER_GLOBALS not in template_text:
        if template_text.count(global_anchor) != 1:
            raise ValueError("孵蛋模板缺少唯一的 HOME_BUFFER 状态区，拒绝应用窗口搜索覆盖")
        template_text = template_text.replace(
            global_anchor,
            global_anchor + EGG_HOME_BUFFER_GLOBALS,
            1,
        )

    if EGG_HOME_BUFFER_OVERRIDE_MARKER in template_text:
        start = template_text.index(EGG_HOME_BUFFER_OVERRIDE_MARKER)
    else:
        if template_text.count(EGG_HOME_BUFFER_ORIGINAL_FUNCTION) != 1:
            raise ValueError("孵蛋模板缺少唯一的 HOME_BUFFER 函数，拒绝应用窗口搜索覆盖")
        start = template_text.index(EGG_HOME_BUFFER_ORIGINAL_FUNCTION)
    if template_text.count(EGG_HOME_BUFFER_NEXT_FUNCTION) != 1:
        raise ValueError("孵蛋模板缺少 HOME_BUFFER 后继函数，拒绝应用窗口搜索覆盖")
    end = template_text.index(EGG_HOME_BUFFER_NEXT_FUNCTION, start)
    replacement = override_text.rstrip() + "\n\n"
    template_text = template_text[:start] + replacement + template_text[end:]

    initial_restart = """\
    CALL 孵蛋流程_重开下一轮

    $孵蛋流程尝试次数 = 0
"""
    guarded_initial_restart = """\
    CALL 孵蛋流程_重开下一轮
    IF $孵蛋HOME_BUFFER失败 == 1
        PRINT 孵蛋流程停止：HOME_BUFFER未找到当前主机的可用延迟
        RETURN 0
    ENDIF

    $孵蛋流程尝试次数 = 0
"""
    loop_start = """\
    FOR
        $孵蛋流程尝试次数 += 1
"""
    guarded_loop_start = """\
    FOR
        IF $孵蛋HOME_BUFFER失败 == 1
            PRINT 孵蛋流程停止：HOME_BUFFER未找到当前主机的可用延迟
            RETURN 0
        ENDIF
        $孵蛋流程尝试次数 += 1
"""
    for original, guarded, description in (
        (initial_restart, guarded_initial_restart, "首次 HOME_BUFFER 结果检查"),
        (loop_start, guarded_loop_start, "重试 HOME_BUFFER 结果检查"),
    ):
        if guarded not in template_text:
            if template_text.count(original) != 1:
                raise ValueError(
                    f"孵蛋模板缺少唯一的{description}位置，拒绝应用窗口搜索覆盖"
                )
            template_text = template_text.replace(original, guarded, 1)
    return template_text


def _apply_egg_settings_runtime_override_text(
    library_text: str,
    override_text: str,
) -> str:
    """Replace only the egg settings checker in a copied 1.1.8 runtime library."""
    global_anchor = "$孵蛋库_设置结果 = 0\n"
    if EGG_SETTINGS_GLOBALS not in library_text:
        if library_text.count(global_anchor) != 1:
            raise ValueError("孵蛋流程库缺少唯一的设置结果全局变量，拒绝应用运行时修正")
        library_text = library_text.replace(
            global_anchor,
            global_anchor + EGG_SETTINGS_GLOBALS,
            1,
        )

    if EGG_SETTINGS_OVERRIDE_MARKER in library_text:
        start = library_text.index(EGG_SETTINGS_OVERRIDE_MARKER)
    else:
        original_function = "FUNC 孵蛋测试_检查校正并保存游戏设置"
        if library_text.count(original_function) != 1:
            raise ValueError("孵蛋流程库缺少唯一的游戏设置检查函数，拒绝应用运行时修正")
        start = library_text.index(original_function)
    if library_text.count(EGG_SETTINGS_NEXT_FUNCTION) != 1:
        raise ValueError("孵蛋流程库缺少唯一的前置准备函数，拒绝应用运行时修正")
    end = library_text.index(EGG_SETTINGS_NEXT_FUNCTION, start)
    replacement = override_text.rstrip() + "\n\n"
    return library_text[:start] + replacement + library_text[end:]


def _apply_egg_restart_runtime_override_text(
    library_text: str,
    override_text: str,
) -> str:
    """Replace the whole egg restart helper with the audited original flow."""
    global_anchor = "$孵蛋库_正在关闭匹配 = 0\n"
    if EGG_RESTART_GLOBALS not in library_text:
        if library_text.count(global_anchor) != 1:
            raise ValueError("孵蛋流程库缺少唯一的关闭状态全局变量，拒绝应用重启覆盖")
        library_text = library_text.replace(
            global_anchor,
            global_anchor + EGG_RESTART_GLOBALS,
            1,
        )

    if EGG_RESTART_OVERRIDE_MARKER in library_text:
        start = library_text.index(EGG_RESTART_OVERRIDE_MARKER)
    else:
        if library_text.count(EGG_RESTART_ORIGINAL_FUNCTION) != 1:
            raise ValueError("孵蛋流程库缺少唯一的关闭游戏函数，拒绝应用重启覆盖")
        start = library_text.index(EGG_RESTART_ORIGINAL_FUNCTION)
    if library_text.count(EGG_RESTART_NEXT_FUNCTION) != 1:
        raise ValueError("孵蛋流程库缺少唯一的软重启函数，拒绝应用重启覆盖")
    end = library_text.index(EGG_RESTART_NEXT_FUNCTION, start)
    replacement = override_text.rstrip() + "\n\n"
    return library_text[:start] + replacement + library_text[end:]


def _apply_egg_home_resample_fix_text(library_text: str) -> str:
    """Compatibility wrapper for the complete original-flow restart overlay."""
    override_text = EGG_RESTART_OVERRIDE_PATH.read_text(encoding="utf-8")
    return _apply_egg_restart_runtime_override_text(library_text, override_text)


def apply_egg_settings_runtime_override(library_path: str | Path) -> dict[str, str]:
    """Apply the GUI-only egg library overlays and return their fingerprints."""
    library_path = Path(library_path)
    restart_override_text = EGG_RESTART_OVERRIDE_PATH.read_text(encoding="utf-8")
    settings_override_text = EGG_SETTINGS_OVERRIDE_PATH.read_text(encoding="utf-8")
    party_slot_candy_override_text = EGG_PARTY_SLOT_CANDY_OVERRIDE_PATH.read_text(
        encoding="utf-8"
    )
    surf_battle_override_text = EGG_SURF_BATTLE_OVERRIDE_PATH.read_text(
        encoding="utf-8"
    )
    hatch_exit_override_text = EGG_HATCH_EXIT_OVERRIDE_PATH.read_text(
        encoding="utf-8"
    )
    configured = _apply_egg_restart_runtime_override_text(
        library_path.read_text(encoding="utf-8"),
        restart_override_text,
    )
    configured = _apply_egg_settings_runtime_override_text(
        configured,
        settings_override_text,
    )
    configured = _apply_egg_party_slot_candy_runtime_override_text(
        configured,
        party_slot_candy_override_text,
    )
    configured = _apply_egg_surf_battle_runtime_override_text(
        configured,
        surf_battle_override_text,
    )
    configured = _apply_egg_hatch_exit_runtime_override_text(
        configured,
        hatch_exit_override_text,
    )
    configured = _apply_egg_pond_settle_delay_text(configured)
    library_path.write_text(configured, encoding="utf-8")
    return {
        "egg_restart_original_flow_sha256": hashlib.sha256(
            restart_override_text.encode("utf-8")
        ).hexdigest(),
        "egg_settings_retry_sha256": hashlib.sha256(
            settings_override_text.encode("utf-8")
        ).hexdigest(),
        "egg_party_slot_candy_sha256": hashlib.sha256(
            party_slot_candy_override_text.encode("utf-8")
        ).hexdigest(),
        "egg_surf_battle_retry_sha256": hashlib.sha256(
            surf_battle_override_text.encode("utf-8")
        ).hexdigest(),
        "egg_hatch_exit_retry_sha256": hashlib.sha256(
            hatch_exit_override_text.encode("utf-8")
        ).hexdigest(),
    }


def materialize_easycon118_164a_fixes(source_dir: str | Path) -> dict[str, Any]:
    """Bake reviewed 1.6.4-a fixes into both direct-run 1.1.8 entries."""
    source_dir = Path(source_dir).resolve()
    standard_path = source_dir / STANDARD_TEMPLATE_NAME
    egg_path = source_dir / EGG_TEMPLATE_NAME
    if not standard_path.is_file() or not egg_path.is_file():
        raise FileNotFoundError("1.1.8 包缺少正式版或时间轴版主脚本")

    classifier_text = HOME_BUFFER_ADAPTIVE_CLASSIFIER_PATH.read_text(encoding="utf-8")
    standard_configured = _apply_standard_home_buffer_runtime_override_text(
        standard_path.read_text(encoding="utf-8"),
        STANDARD_HOME_BUFFER_OVERRIDE_PATH.read_text(encoding="utf-8"),
    )
    standard_configured = _apply_home_buffer_adaptive_classifier_text(
        standard_configured,
        classifier_text,
        False,
    )
    standard_path.write_text(standard_configured, encoding="utf-8")

    configured = _apply_egg_summary_fix_text(
        egg_path.read_text(encoding="utf-8")
    )
    configured = _apply_egg_reverse_lookup_policy_text(configured)
    configured = _apply_egg_prepared_254_runtime_override_text(configured, False)
    configured = _apply_egg_home_buffer_runtime_override_text(
        configured,
        EGG_HOME_BUFFER_OVERRIDE_PATH.read_text(encoding="utf-8"),
    )
    configured = _apply_home_buffer_adaptive_classifier_text(
        configured,
        classifier_text,
        False,
    )
    configured = _apply_egg_party_slot_main_runtime_override_text(
        configured,
        EGG_PARTY_SLOT_MAIN_OVERRIDE_PATH.read_text(encoding="utf-8"),
    )
    configured = _apply_egg_seed_controller_runtime_override_text(
        configured,
        EGG_SEED_CONTROLLER_OVERRIDE_PATH.read_text(encoding="utf-8"),
    )
    configured = _apply_egg_transient_retry_runtime_override_text(configured)
    configured = _apply_egg_terminal_stop_policy_text(configured)
    egg_path.write_text(configured, encoding="utf-8")

    party_summary_helper = PARTY_SUMMARY_NAVIGATION_PATH.read_text(
        encoding="utf-8"
    )
    for template_path in (standard_path, egg_path):
        configured = _apply_party_summary_navigation_text(
            template_path.read_text(encoding="utf-8"),
            party_summary_helper,
        )
        template_path.write_text(configured, encoding="utf-8")

    apply_wild_pid_retry_limit(standard_path)
    apply_wild_pid_retry_limit(egg_path)
    apply_ocr_runtime_fallback(source_dir / "lib" / OCR_NAME_LIBRARY_NAME)
    apply_egg_settings_runtime_override(
        source_dir / "lib" / EGG_SETTINGS_LIBRARY_NAME
    )
    static_target_path = source_dir / "lib" / "16_获取_静态目标.ecs"
    static_target_text = _apply_togepi_hatch_cycle_override_text(
        static_target_path.read_text(encoding="utf-8"),
        TOGEPI_HATCH_CYCLE_OVERRIDE_PATH.read_text(encoding="utf-8"),
    )
    static_target_path.write_text(static_target_text, encoding="utf-8")
    return inspect_script_corpus(source_dir)


def write_configured_project(
    source_dir: str | Path,
    output_dir: str | Path,
    plan: RunPlan,
    options: EasyCon118Options | None = None,
    *,
    copy_assets: bool = True,
) -> Path:
    """Create an EasyCon CLI project with ``main.ecs``, ``lib`` and labels."""
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    script_corpus = inspect_script_corpus(source_dir)
    if script_corpus["count"] != EXPECTED_SCRIPT_FILE_COUNT:
        raise ValueError(
            f"1.1.8 主脚本/lib 文件数应为 {EXPECTED_SCRIPT_FILE_COUNT}，"
            f"当前为 {script_corpus['count']}"
        )
    if not is_supported_runtime_script_sha256(script_corpus["sha256"]):
        print(
            "警告：1.1.8 主脚本/lib 指纹未登记，仍继续生成："
            + script_corpus["sha256"],
            file=sys.stderr,
        )
    template_path = source_dir / STANDARD_TEMPLATE_NAME

    output_dir.mkdir(parents=True, exist_ok=True)
    configured = configure_template_text(
        template_path.read_text(encoding="utf-8"),
        plan,
        options,
    )
    configured = _apply_standard_home_buffer_runtime_override_text(
        configured,
        STANDARD_HOME_BUFFER_OVERRIDE_PATH.read_text(encoding="utf-8"),
    )
    classifier_text = HOME_BUFFER_ADAPTIVE_CLASSIFIER_PATH.read_text(
        encoding="utf-8"
    )
    configured = _apply_home_buffer_adaptive_classifier_text(
        configured,
        classifier_text,
        (options or EasyCon118Options()).home_buffer_adaptive_threshold,
    )
    main_path = output_dir / "main.ecs"
    main_path.write_text(configured, encoding="utf-8")
    wild_pid_retry_limit_sha256 = apply_wild_pid_retry_limit(main_path)

    if copy_assets:
        for directory in ("lib", "ImgLabel"):
            source = source_dir / directory
            if not source.is_dir():
                raise FileNotFoundError(f"1.1.8 包缺少 {directory} 目录")
            target = output_dir / directory
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            if directory == "ImgLabel":
                copy_easycon118_extension_labels(target)

    ocr_fallback_sha256 = apply_ocr_runtime_fallback(
        output_dir / "lib" / OCR_NAME_LIBRARY_NAME
    )

    manifest = {
        "source": str(source_dir.resolve()),
        "template": template_path.name,
        "plan": plan.to_dict(),
        "easycon118_options": asdict(options or EasyCon118Options()),
        "labels": {
            "expected_count": EXPECTED_LABEL_COUNT,
            "expected_methods": EXPECTED_LABEL_METHODS,
            "expected_sha256": EXPECTED_LABEL_SHA256,
        },
        "scripts": {
            "expected_count": EXPECTED_SCRIPT_FILE_COUNT,
            "expected_sha256": EXPECTED_SCRIPT_SHA256,
        },
        "runtime_overrides": {
            "ocr_unavailable_fallback_sha256": ocr_fallback_sha256,
            "wild_pid_retry_limit_sha256": wild_pid_retry_limit_sha256,
            "home_buffer_adaptive_classifier_sha256": hashlib.sha256(
                classifier_text.encode("utf-8")
            ).hexdigest(),
        },
        "backend": {
            "name": EASYCON_BACKEND_NAME,
            "expected_cli_version": EXPECTED_EZCON_VERSION,
            "expected_cli_sha256": EXPECTED_EZCON_SHA256,
        },
    }
    (output_dir / "plan.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return main_path


def write_configured_egg_project(
    source_dir: str | Path,
    output_dir: str | Path,
    request: EggRunRequest,
    *,
    copy_assets: bool = True,
) -> Path:
    """Create a runnable project for the experimental same-seed egg flow."""
    request.validate()
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    script_corpus = inspect_script_corpus(source_dir)
    if script_corpus["count"] != EXPECTED_SCRIPT_FILE_COUNT:
        raise ValueError(
            f"1.1.8 正式/孵蛋主脚本及 lib 文件数应为 {EXPECTED_SCRIPT_FILE_COUNT}，"
            f"当前为 {script_corpus['count']}"
        )
    if not is_supported_runtime_script_sha256(script_corpus["sha256"]):
        print(
            "警告：1.1.8 孵蛋主脚本/lib 指纹未登记，仍继续生成："
            + script_corpus["sha256"],
            file=sys.stderr,
        )
    template_path = source_dir / EGG_TEMPLATE_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    configured = configure_egg_template_text(
        template_path.read_text(encoding="utf-8"), request
    )
    configured = _apply_egg_prepared_254_runtime_override_text(
        configured,
        request.start_from_prepared_254,
    )
    home_buffer_override_text = EGG_HOME_BUFFER_OVERRIDE_PATH.read_text(
        encoding="utf-8"
    )
    configured = _apply_egg_home_buffer_runtime_override_text(
        configured,
        home_buffer_override_text,
    )
    classifier_text = HOME_BUFFER_ADAPTIVE_CLASSIFIER_PATH.read_text(
        encoding="utf-8"
    )
    configured = _apply_home_buffer_adaptive_classifier_text(
        configured,
        classifier_text,
        request.home_buffer_adaptive_threshold,
    )
    party_slot_main_override_text = EGG_PARTY_SLOT_MAIN_OVERRIDE_PATH.read_text(
        encoding="utf-8"
    )
    configured = _apply_egg_party_slot_main_runtime_override_text(
        configured,
        party_slot_main_override_text,
    )
    seed_controller_override_text = EGG_SEED_CONTROLLER_OVERRIDE_PATH.read_text(
        encoding="utf-8"
    )
    configured = _apply_egg_seed_controller_runtime_override_text(
        configured,
        seed_controller_override_text,
    )
    configured = _apply_egg_transient_retry_runtime_override_text(configured)
    configured = _apply_egg_terminal_stop_policy_text(configured)
    main_path = output_dir / "main.ecs"
    main_path.write_text(configured, encoding="utf-8")
    wild_pid_retry_limit_sha256 = apply_wild_pid_retry_limit(main_path)

    if copy_assets:
        for directory in ("lib", "ImgLabel"):
            source = source_dir / directory
            if not source.is_dir():
                raise FileNotFoundError(f"1.1.8 包缺少 {directory} 目录")
            target = output_dir / directory
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            if directory == "ImgLabel":
                copy_easycon118_extension_labels(target)

    ocr_fallback_sha256 = apply_ocr_runtime_fallback(
        output_dir / "lib" / OCR_NAME_LIBRARY_NAME
    )
    runtime_overrides = apply_egg_settings_runtime_override(
        output_dir / "lib" / EGG_SETTINGS_LIBRARY_NAME
    )
    runtime_overrides["ocr_unavailable_fallback_sha256"] = ocr_fallback_sha256
    runtime_overrides["egg_home_buffer_refine_sha256"] = hashlib.sha256(
        home_buffer_override_text.encode("utf-8")
    ).hexdigest()
    runtime_overrides["home_buffer_adaptive_classifier_sha256"] = hashlib.sha256(
        classifier_text.encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_party_slot_main_sha256"] = hashlib.sha256(
        party_slot_main_override_text.encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_seed_controller_sha256"] = hashlib.sha256(
        seed_controller_override_text.encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_transient_retry_main_sha256"] = hashlib.sha256(
        "\n".join(
            replacement
            for _, replacement in EGG_TRANSIENT_RETRY_REPLACEMENTS
        ).encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_terminal_stop_policy_sha256"] = hashlib.sha256(
        "\n".join(
            replacement
            for _, replacement in EGG_TERMINAL_STOP_REPLACEMENTS
        ).encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_prepared_254_start_sha256"] = hashlib.sha256(
        _egg_prepared_254_override_text(request.start_from_prepared_254).encode(
            "utf-8"
        )
    ).hexdigest()
    runtime_overrides["wild_pid_retry_limit_sha256"] = wild_pid_retry_limit_sha256
    manifest = {
        "source": str(source_dir),
        "template": template_path.name,
        "egg_request": request.to_dict(),
        "experimental": True,
        "runtime_overrides": runtime_overrides,
        "labels": {
            "expected_count": EXPECTED_LABEL_COUNT,
            "expected_methods": EXPECTED_LABEL_METHODS,
            "expected_sha256": EXPECTED_LABEL_SHA256,
        },
        "scripts": {
            "expected_count": EXPECTED_SCRIPT_FILE_COUNT,
            "expected_sha256": EXPECTED_SCRIPT_SHA256,
        },
        "backend": {
            "name": EASYCON_BACKEND_NAME,
            "expected_cli_version": EXPECTED_EZCON_VERSION,
            "expected_cli_sha256": EXPECTED_EZCON_SHA256,
        },
    }
    (output_dir / "plan.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return main_path


def validate_runtime(
    ezcon_path: str | Path,
    project_main: str | Path,
) -> EasyConRuntimeCheck:
    ezcon_path = Path(ezcon_path).resolve()
    project_main = Path(project_main).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not ezcon_path.is_file():
        errors.append(f"找不到 ezcon.exe: {ezcon_path}")
    else:
        try:
            ezcon_sha256 = hashlib.sha256(ezcon_path.read_bytes()).hexdigest()
        except OSError as exc:
            errors.append(f"无法读取 ezcon.exe: {exc}")
        else:
            if ezcon_sha256 != EXPECTED_EZCON_SHA256:
                errors.append(
                    "EasyCon 1.6.4a ezcon.exe 指纹不一致，拒绝运行: "
                    + ezcon_sha256
                )
    if not project_main.is_file():
        errors.append(f"找不到生成脚本: {project_main}")
    project_dir = project_main.parent
    if not (project_dir / "lib").is_dir():
        errors.append("生成项目缺少 lib 目录")
    label_dir = project_dir / "ImgLabel"
    if not label_dir.is_dir():
        errors.append("生成项目缺少 ImgLabel 目录")
    else:
        try:
            corpus = inspect_label_corpus(label_dir)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"1.1.8 标签清单读取失败: {exc}")
        else:
            if corpus["count"] != EXPECTED_LABEL_COUNT:
                errors.append(
                    f"1.1.8 标签数量应为 {EXPECTED_LABEL_COUNT}，当前为 {corpus['count']}"
                )
            if corpus["methods"] != EXPECTED_LABEL_METHODS:
                errors.append(
                    f"1.1.8 标签方法分布不一致: {corpus['methods']}"
                )
            if corpus["sha256"] != EXPECTED_LABEL_SHA256:
                errors.append(
                    "1.1.8 标签指纹不一致，可能不是已审计的完整标签包: "
                    + corpus["sha256"]
                )

    tessdata_dir = ezcon_path.parent / "Tessdata"
    for model, expected_sha256 in EXPECTED_TESSDATA_SHA256.items():
        model_path = tessdata_dir / model
        if not model_path.is_file():
            errors.append(f"EasyCon Tessdata 缺少 {model}")
            continue
        try:
            model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
        except OSError as exc:
            errors.append(f"无法读取 EasyCon Tessdata/{model}: {exc}")
            continue
        if model_sha256 != expected_sha256:
            errors.append(f"EasyCon Tessdata/{model} 指纹不一致: {model_sha256}")

    if ezcon_path.is_file() and project_main.is_file() and not errors:
        run_options = dict(
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            version = subprocess.run(
                [str(ezcon_path), "--version"], timeout=15, **run_options
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"无法读取 EasyCon 版本: {exc}")
        else:
            version_text = (version.stdout + "\n" + version.stderr).strip()
            version_line = version_text.splitlines()[-1] if version_text else "(无版本输出)"
            if version.returncode != 0:
                errors.append(f"EasyCon 版本检查失败，退出码 {version.returncode}")
            elif version_line != EXPECTED_EZCON_VERSION:
                errors.append(
                    f"当前适配器只审计过 EasyCon {EXPECTED_EZCON_VERSION}；检测结果为: "
                    + version_line
                )
            else:
                warnings.append("EasyCon 版本: " + version_line)

        if not errors:
            try:
                formatted = subprocess.run(
                    [str(ezcon_path), "format", str(project_main)],
                    cwd=str(project_main.parent),
                    timeout=60,
                    **run_options,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(f"EasyCon 1.6.4a ECS 语法预检无法执行: {exc}")
            else:
                if formatted.returncode != 0:
                    details = (formatted.stderr or formatted.stdout).strip()
                    errors.append(
                        "EasyCon 1.6.4a ECS 语法预检失败，退出码 "
                        f"{formatted.returncode}: {details[-1000:]}"
                    )

    warnings.append(
        "已固定使用 EasyCon 1.6.4a；正式长跑前仍需完成停止、重连和识别稳定性验收。"
    )
    return EasyConRuntimeCheck(not errors, tuple(errors), tuple(warnings))


def build_run_command(
    ezcon_path: str | Path,
    project_main: str | Path,
    *,
    port: str,
    video_device: int,
    video_type: str = "DSHOW",
    verbose: bool = False,
) -> list[str]:
    if video_device < 0:
        raise ValueError("采集卡序号不能为负数")
    if not port or not port.strip():
        raise ValueError("串口不能为空")
    if video_type not in {"ANY", "DSHOW", "MSMF"}:
        raise ValueError(f"不支持的视频类型: {video_type}")
    ezcon_path = Path(ezcon_path).resolve()
    project_main = Path(project_main).resolve()
    command = [
        str(ezcon_path),
        "run",
        str(project_main),
        "--port",
        port,
        "--device",
        str(video_device),
        "--videotype",
        video_type,
    ]
    if verbose:
        command.append("--verbose")
    return command


def prepare_compat_runner(
    ezcon_path: str | Path,
    runner_path: str | Path = DEFAULT_COMPAT_RUNNER_PATH,
) -> Path:
    """Validate the pinned latest-frame CLI and sync audited local-OCR assets.

    EasyCon 1.6.4-a's GUI rounds image-label confidence upward with
    ``Math.Ceiling`` and continuously drains the capture device.  Its bundled
    ``ezcon.exe run`` truncates confidence and reads only when a label is
    evaluated, which can return buffered DSHOW transition frames.  The
    compatibility runner is built from the exact 1.6.4-a source commit and
    adds latest-frame consumption plus the GUI's rounding behavior (and .NET 9
    build-only compatibility).
    """
    ezcon_path = Path(ezcon_path).resolve()
    runner_path = Path(runner_path).resolve()
    if not ezcon_path.is_file():
        raise FileNotFoundError(f"找不到原始 EasyCon 1.6.4-a ezcon.exe: {ezcon_path}")
    if hashlib.sha256(ezcon_path.read_bytes()).hexdigest() != EXPECTED_EZCON_SHA256:
        raise ValueError("原始 EasyCon 1.6.4-a ezcon.exe 指纹不一致，拒绝准备兼容运行器")
    if not runner_path.is_file():
        raise FileNotFoundError(
            "缺少 EasyCon 1.6.4-a GUI 持续采帧兼容运行器；请先运行 "
            "tools\\build_easycon164a_compat_runner.ps1"
        )

    manifest_path = runner_path.with_name("build-manifest.json")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"兼容运行器缺少构建清单: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"兼容运行器构建清单无法读取: {exc}") from exc
    if manifest.get("source_commit") != EXPECTED_COMPAT_SOURCE_COMMIT:
        raise ValueError("兼容运行器不是从已锁定的 EasyCon 1.6.4-a commit 构建")
    if manifest.get("patch_id") != EXPECTED_COMPAT_PATCH_ID:
        raise ValueError("兼容运行器补丁标识不一致")
    runner_sha256 = hashlib.sha256(runner_path.read_bytes()).hexdigest()
    if manifest.get("sha256") != runner_sha256:
        raise ValueError(f"兼容运行器指纹不一致: {runner_sha256}")

    try:
        version = subprocess.run(
            [str(runner_path), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"兼容运行器版本检查失败: {exc}") from exc
    version_text = (version.stdout + "\n" + version.stderr).strip()
    version_line = version_text.splitlines()[-1] if version_text else ""
    if version.returncode != 0 or version_line != EXPECTED_EZCON_VERSION:
        raise ValueError(
            "兼容运行器版本不一致；期望 "
            f"{EXPECTED_EZCON_VERSION}，实际 {version_line or '(无输出)'}"
        )

    source_tessdata = ezcon_path.parent / "Tessdata"
    target_tessdata = runner_path.parent / "Tessdata"
    target_tessdata.mkdir(parents=True, exist_ok=True)
    for model, expected_sha256 in EXPECTED_TESSDATA_SHA256.items():
        source = source_tessdata / model
        if not source.is_file():
            raise FileNotFoundError(f"原始 EasyCon Tessdata 缺少 {model}")
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha256:
            raise ValueError(f"原始 EasyCon Tessdata/{model} 指纹不一致")
        target = target_tessdata / model
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha256:
            shutil.copy2(source, target)
    for relative_name, expected_sha256 in EXPECTED_COMPAT_OCR_NATIVE_SHA256.items():
        relative_path = Path(relative_name)
        native_path = runner_path.parent / relative_path
        if not native_path.is_file():
            raise FileNotFoundError(
                f"兼容运行器缺少 OCR 原生依赖 {relative_name}；请重新构建 runner"
            )
        native_sha256 = hashlib.sha256(native_path.read_bytes()).hexdigest()
        if native_sha256 != expected_sha256:
            raise ValueError(
                f"兼容运行器 OCR 原生依赖/{relative_name} 指纹不一致: {native_sha256}"
            )
    return runner_path


def launch_project(**kwargs) -> subprocess.Popen:
    """Launch only after the caller has shown and accepted preflight results."""
    command = build_run_command(**kwargs)
    return subprocess.Popen(command, cwd=str(Path(kwargs["project_main"]).parent))
