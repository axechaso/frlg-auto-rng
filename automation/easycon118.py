"""Generate and launch a configured 1.1.8 project on pinned EasyCon 1.6.4a."""

import json
import hashlib
import re
import shutil
import struct
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from assets.game_text import CATEGORY_EN_TO_ZH, location_to_zh
from app_paths import RESOURCE_ROOT
from device_label_overrides import validate_project_overrides
from fingerprint_policy import record_fingerprint_mismatch
from tenlines_seed_updater import (
    apply_easycon_seed_table_overrides,
    decode_nx_seed_binary,
    upgrade_easycon_seed_mode3_tables,
)

from .planner import RunPlan
from .precalibration import (
    DEFAULT_STORE_PATH as DEFAULT_PRECALIBRATION_STORE_PATH,
    PrecalibrationContext,
    normalize_kind as normalize_precalibration_kind,
    read_record as read_precalibration_record,
)
from .seed_common_regions import apply_seed_common_regions


EXPECTED_LABEL_COUNT = 1150
EXPECTED_LABEL_METHODS = {1: 17, 3: 1, 5: 777, 11: 1, 14: 354}
EXPECTED_LABEL_SHA256 = "00d2fbfa9a3638f3cea64553e94b777ed8c5c63f813125617b50aaeed7c9d10e"
EASYCON_BACKEND_NAME = "EasyCon 1.6.4a"
EXPECTED_EZCON_VERSION = "1.6.4-a+9c86137c7e63bff842175470895727a5fa9bab52"
EXPECTED_EZCON_SHA256 = "559b81c234d2548c439926a88f5355ccac0958b8a191c1ecca48b2c7c71c1260"
EXPECTED_COMPAT_SOURCE_COMMIT = "9c86137c7e63bff842175470895727a5fa9bab52"
EXPECTED_COMPAT_PATCH_ID = "cli-latest-frame-ceiling-ocr-loopback-mjpeg-onedir-v6"
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
    / "EasyCon2.CLI.PreviewV5.exe"
)
STANDARD_TEMPLATE_NAME = "NS火叶全自动一键乱数2.0.ecs"
EGG_TEMPLATE_NAME = "NS火叶全自动一键乱数2.0-时间轴.ecs"
EGG_FORMAL_WAIT_MARKER = "# FORMAL_EGG_WAIT_V1"
EXPECTED_TEMPLATE_NAMES = (STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME)
PRECALIBRATION_RUNTIME_MARKER = "# GUI_PRECALIBRATION_V1"
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
    # Download package that keeps the completed no-egg pre-calibration after
    # a post-pickup Seed miss and retries generation/pickup directly.
    "77bea49b62c909d105dd7b81529bbb3a8046d996781d68b2ebc479cd6096c841",
    # Download package with the Ten Lines Held no-egg interval table used to
    # leave stable no-egg regions during fine calibration.
    "bdd0ecbb9644555dd9adad4834ce61fa2ab343fe90df9d429de4be5fb8da6dbc",
    # Download package with the latest egg-flow updates imported on 2026-08-25.
    "79c543b4b65cc85c3bced3e2bd15dedb26abcf4bff380d7c7c4e8b2f5cee7842",
    # Download package where target-Seed no-egg evidence is accumulated even
    # before Pickup stabilizes, allowing temporary Held no-egg interval exits.
    "92f5870f09c28b55a583a9ea5ddf4d23a55af4e847220c0aade35d7e66bb52f5",
    # Download package that preserves confirmed no-egg interval evidence across
    # intervening non-target Seed rounds while the Held request is unchanged.
    "4e00e389381ae92cf040ac1c620334b808758241e82fd50138ab3c5cb7e0c2f0",
    # Download package where the egg timeline reuses the formal F1+1/F2-1
    # parity phase for the normally parity-matched Held/Pickup deadlines.
    "355c79d87d8272524cbbda0680f30d6de0d77d61b57046458c295e12f1275ac6",
    # Download package where a residual odd Pickup phase uses the measured
    # post-daycare X/B menu action and pre-deducts its 7 advances.
    "e5a7c8312282070efe5bee72c0b3c5572c46c7ba4205a90188b39b792e228d95",
    # Download package where the post-hit Seed hold advances on every trusted
    # reverse lookup while only ±1 results vote on the correction direction.
    "af0b4b16b6b90ba89ebbec3cc37b402b37b09196ba9bbbce8c6ffe94d2212123",
    # Download package where the first valid HOME_BUFFER delay is locked for
    # the run, then unlocked only after three consecutive recognition misses.
    "5e6cc6db83a020b59d71993eff390c04681c9e251f5534412ee63c54d8b0a5f9",
    # Download package with verified HOME recovery and unknown-state-safe
    # 50 ms probing, without contradictory binary-search boundaries.
    "0b4d7fdfc4370fd84f7956e12b001e867b7cbe40e13c39baf191dfc245b279a9",
    # Mode 3 is stereo/HELP/Start; the LR/A column is no longer reused.
    "1d8dc9f0b207c4f44f5a62a72cbcc6346aa28a1f0cdaa2cf6880f191430d6db1",
    # Current download package: immediate no-egg Seed checks after Held calibration.
    "0c011cb464ff3a83a9be379d9493455c2cd0075139626f28dad6c1e2b6ec3028",
    # Egg wild verification adds one +5 Seed / +1000 upper-advance fallback.
    "c4a1ca509199d1ad3c3589bb019d286b0c2cac5e52a51c0f70e7d297597b2c8a",
    # Download package with the selectable current/fixed-user Seed startup path.
    "e82ed39b65a5b4c8ee39287906d4317e58c84334c656f08a8cad6b31d8fde0f5",
    # Download package with near-1113 Held recovery, anchor-first parity
    # calibration, and dense same-parity fallback anchors.
    "b256082acbc7823d172e0f8124fdd91e51331a08a045ad47209c8bfb950fd8e4",
    # Version 2.0 package: formal/timeline entry logs now identify their
    # version and script type explicitly.
    "71dcb35840422e97ce64652ec801e771ee57524271bd84033ddd89a1f0fe160e",
    # Version 2.0 package after renaming both entry filenames.
    "f0a14ad634c8a00d9c9d74c8afee05a59721b72618952128582acd38061c37bf",
    # Version 2.0 package with the direct timeline entry filename.
    "531bd08e5ed39abaac7d694b2ec01ff429e5e0be5df5c279fc50dc067e2b7482",
    # Version 2.0 package with the timeline-only entry removing the legacy TV
    # runtime switch from both main entry paths.
    "ac4481ebd8f0b3fd456a489b8ecf357f6fb4b583b37ac7e3ffdda66e2b5cfc1f",
)
EXPECTED_SCRIPT_SHA256 = "39a2f7a5046e2d1c7213b6689158402be8656fc5dd790bb73ed8a77c8390f15b"
# Previously materialized 1.6.4-a corpora remain accepted as audited
# compatibility inputs. This is not a general bypass for modified ECS files.
SUPPORTED_RUNTIME_SCRIPT_SHA256S = (
    # Canonical corpus before the egg flow was promoted to the formal WAIT entry.
    "36c83915f208741608d278c17754deae7951c3389b3a3f1e450694c687f66003",
    # Canonical corpus before the fixed user-selection HOME startup A/B was added.
    "bde2ffddbb42b6c71b2494968c2ccfb8d04291ea3f3c6c755fa79ac825aba923",
    # Canonical corpus before the no-egg escape switched from whole-envelope
    # fitting to a same-parity point target.
    "2ad7486f7be10e46fe57ca61d26065722340c6522907f8d7f084637161bb03f2",
    # Cross-method confirmation before no-egg destination parity was enforced.
    "208cc09726ca7f902ee1374f0103d88bd245938e028969d6e45073c84ef398c9",
    # Canonical corpus before cross-method Egg confirmation and no-egg
    # prediction-envelope jumps were added.
    "910667b1bb4f82f5ee82767db5d3b9dbf0f272c4cb2feb78cde4fbc5d5066bbf",
    # Paired, bounded 2D common regions (direct source and materialized tool).
    "c83b9a4b11c15aea37bc824f758e7f6c316b89d0dda15dbf460085e3c36925ad",
    "f0220899d797bc94b1d3cd7e30e82db24452b696e6ba3aa4345995e69b77e50c",
    "3527aaa13ac30108c93699b8566353627d740f5e9dc7dc2becfd6aa7b50da946",
    "04514280811922c6b0809c0e61f1395a0b172d6197703f4a905b92a412e84db2",
    "3df6f91b12901b488f84b07ecde2ba9a45b9ee5638f76b2b28d6fe9b906a7ccc",
    "b7d3cf56cc3018522548514a279a950176b136c938dcceda90f60b9b133d2d57",
    # In-place upgrade of the existing local cache has equivalent HOME_BUFFER
    # functions but retains its historical global-declaration ordering.
    "272406a322605609787af5dd29af9a0203e22b0aed7d2d40c38a4a870122b476",
    # Previous canonical corpus before later upstream egg-flow updates.
    "b0941989541991148e075926775f35bac301b524587048ba741a52f7f01da1b4",
    # Materialized corpus before the Held no-egg interval table was added.
    "74b4a3ecce59e3817699ee8dece2594d67f48bad08b33068358c45b74aaf6e9e",
    # Materialized corpus before post-pickup Seed failures began preserving
    # the completed no-egg pre-calibration.
    "1700ba02cc60fdfd9857f14a2a8384c5736c06908a92e468d1dfd721a9be4865",
    # Materialized corpus before the opt-in HOME_BUFFER stable-low-score
    # classifier was added to both 1.1.8 entry scripts.
    "da32012466a7349113ff166cf158c39dd721fc6e33c8d84355b9747cd7888f86",
    "1ea3bd0ba820e3cb3b1b8616f24e7e8d23b87767b23c49c77cc0a187c2037f73",
    "30fea007607c06d69efdefe256c4b4a639d865854ca94da8afe309eaf0272451",
    "4843f4044e69dc4bc0eb2f3506490651589e531fe2d3b2bad905a6b977c3eec0",
    # Importer materialization adds one controlled trailing newline to the
    # timeline entry while applying the reviewed 1.6.4-a fixes.
    "316c6aa9b6f05adeef0d7f306032b7ae553779d6a86848ae301aa981fd9a8188",
    # Materialized corpus for the latest imported egg-flow package.
    "96882c1d918d9996fc7893051941729f8bdf0a9babc3cab3d8a9eda2ebde3aac",
    # Materialized corpus with same-Held no-egg evidence retention.
    "961e7eb688ae10479a8335ae71771c3462bb3adf2ed3b8d2e27102a886e050fd",
    # Materialized corpus with the formal parity overlay in the egg timeline.
    "4a706951d032ed806c665889720cb235f72320d695dd60de3a782b23297bbd7d",
    # Materialized corpus with the Pickup 7-advance menu parity overlay.
    "4290019dc8c28deed87f647f72b0f65b56f8564cd9faf89688ec7955d41f4dc4",
    # Materialized corpus with bounded ten-observation Seed hold windows.
    "1240aeeb1e44d467f2074d1dced2ef650e1b89068f913c10b382817c45b4a79a",
    # Materialized corpus with HOME_BUFFER run locking, three-miss unlocks,
    # and a 50 ms minimum search adjustment in both entry scripts.
    "a3e6eedb7e35efcf8dc8c0ed0866a96efd66bc7e032411f296d9aa6801115a9c",
    # Local materialized corpus with cross-round Seed hit-range clustering.
    "419b599234a28c23611f60fac558f963d87d12adb641feaef115a8c1e00935bc",
    # Materialized corpus with generated near/dense Held recovery anchors and
    # anchor-first parity/numeric calibration before returning to the target.
    "e3bb467b21f14b7e16838ffdbbb67061c721f3dc5e0410ab0685196782ce1a62",
    # Materialized corpus with the static Togepi-only 14-step bicycle cycle
    # and Dex-only starter classification.
    "4a0417d61a379275e14fd6fc3df92cf9036cda8a5f8022384c96ae7043699983",
    # Version 2.0 materialized corpus with explicit formal/timeline log tags.
    "79d375baf43d0086947af4f395108ebd1ba023dee0a33e69b8b3d08060d6eb33",
    # Version 2.0 materialized corpus after renaming both entry filenames.
    "6c009e75c468e0ad224ce392c8912c2ff286f9882994055afc2b8103a12b2e59",
    # Version 2.0 materialized corpus with the direct timeline entry filename.
    "9c6d8804a76f305ae848498280c8e48d8444b288cd22a4be4bd3074f48c3294a",
    # Version 2.0 materialized corpus with the timeline-only entry removing
    # the legacy TV runtime switch from both main entry paths.
    "f307167e9c9e19e9de6910caf21f28fd83e54fd3b5f16144b78b92393a06bece",
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
# PyInstaller can preserve the bytes of non-ASCII asset names while exposing
# a mojibake filename on some Windows extraction/build paths.  The bundled
# 1.1.8 label corpus is also shipped under ``local_assets`` with the exact
# EasyCon names, so use it as a deterministic fallback for the two labels
# injected into generated projects.
EASYCON118_LOCAL_LABEL_DIR = (
    RESOURCE_ROOT / "local_assets" / "easycon118" / "ImgLabel"
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
HOME_BUFFER_RECOVERY_PATH = (
    EASYCON118_EXTENSION_LABEL_DIR / "home_buffer_recovery.ecs"
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
SEED_LOCK_CONTROLLER_OVERRIDE_PATH = (
    EASYCON118_EXTENSION_LABEL_DIR / "seed_lock_controller_main.ecs"
)
EGG_FORMAL_PARITY_OVERRIDE_PATH = (
    EASYCON118_EXTENSION_LABEL_DIR / "egg_formal_parity_main.ecs"
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
EGG_HOME_BUFFER_ORIGINAL_FUNCTION = "FUNC HOME_BUFFER\n"
EGG_HOME_BUFFER_NEXT_FUNCTION = "FUNC 各阶段脚本固定延迟转帧数"
HOME_BUFFER_ADAPTIVE_CLASSIFIER_MARKER = "# 1.6.4-a HOME_BUFFER 稳定低分自适应"
STANDARD_HOME_BUFFER_OVERRIDE_MARKER = "# 1.6.4-a 正式版 HOME_BUFFER"
HOME_BUFFER_ADAPTIVE_SWITCH = "HOME_BUFFER稳定低分自适应"
EGG_PARTY_SLOT_MAIN_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：按目标身份选择队伍末位或固定槽位"
EGG_PARTY_SLOT_MAIN_ORIGINAL_FUNCTION = "FUNC 孵蛋流程_选择队伍槽"
EGG_PARTY_SLOT_MAIN_NEXT_SECTION = "# -------------------- 野生Seed验证"
EGG_PARTY_SLOT_MAIN_EGG_FUNCTION = "FUNC 孵蛋流程_执行蛋个体反查(): INT"
EGG_PARTY_SLOT_MAIN_EGG_NEXT_SECTION = "# -------------------- 总控与重试"
EGG_REVERSE_LOOKUP_POLICY_MARKER = "# GUI 孵蛋反查覆盖：四方法候选全部合并确认"
EGG_REVERSE_LOOKUP_LEGACY_POLICY_MARKER = "# GUI 孵蛋反查覆盖：Normal 优先，方法候选不跨算法累加"
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
SEED_HOLD_OBSERVATION_MARKER = "# 保持窗口按每次可信Seed反查推进；超出±1只占观察次数，不投方向票。"
SEED_HOLD_OBSERVATION_FUNCTION = "FUNC 计算Seed锁定众数修正(): INT"
SEED_HOLD_OBSERVATION_OLD_GLOBAL = "$Seed命中保持样本数 = 10"
SEED_HOLD_OBSERVATION_GLOBAL_ANCHOR = "$Seed命中保持样本数 = 5"
SEED_HOLD_OBSERVATION_MIN_GLOBAL = "$Seed命中保持最少方向样本数 = 3"
SEED_HOLD_OBSERVATION_DIRECT_HALF_MARKER = "连续5次未命中，按±1多数方向直接固定半步微调"
SEED_HOLD_OBSERVATION_OLD_BRANCH = """\
        ELIF $Seed差绝对 == 1
            $Seed锁定本轮样本计入 = 1
            IF $Seed命中保持启用 == 1
                $Seed命中保持计数 = $Seed命中保持计数 + 1
                IF $命中差索引 > 0
                    $Seed命中保持正方向票数 = $Seed命中保持正方向票数 + 1
                ELSE
                    $Seed命中保持负方向票数 = $Seed命中保持负方向票数 + 1
                ENDIF
            ELSE
                $Seed锁定窗口[$Seed锁定窗口样本数] = $命中差索引
                $Seed锁定窗口样本数 = $Seed锁定窗口样本数 + 1
                $Seed锁定窗口指针 = $Seed锁定窗口样本数
            ENDIF
        ELSE
            # 已经收敛到±1后，偶发大偏差视为机器波动：不修正，也不占5次/10次有效样本。
            $Seed锁定本轮大波动忽略 = 1
            $Seed修正模式文本 = "Seed已锁定，忽略本轮超出±1的机器波动"
            RETURN 0
        ENDIF
"""
SEED_HOLD_OBSERVATION_CURRENT_BRANCH = """\
        ELIF $Seed命中保持启用 == 1
            # 保持窗口按每次可信Seed反查推进；超出±1只占观察次数，不投方向票。
            $Seed命中保持计数 = $Seed命中保持计数 + 1
            IF $Seed差绝对 == 1
                $Seed锁定本轮样本计入 = 1
                IF $命中差索引 > 0
                    $Seed命中保持正方向票数 = $Seed命中保持正方向票数 + 1
                ELSE
                    $Seed命中保持负方向票数 = $Seed命中保持负方向票数 + 1
                ENDIF
            ELSE
                $Seed锁定本轮大波动忽略 = 1
            ENDIF
        ELIF $Seed差绝对 == 1
            $Seed锁定本轮样本计入 = 1
            $Seed锁定窗口[$Seed锁定窗口样本数] = $命中差索引
            $Seed锁定窗口样本数 = $Seed锁定窗口样本数 + 1
            $Seed锁定窗口指针 = $Seed锁定窗口样本数
        ELSE
            # 非保持期仍只收集±1微调样本；偶发大偏差不修正，也不占5次方向窗口。
            $Seed锁定本轮大波动忽略 = 1
            $Seed修正模式文本 = "Seed已锁定，忽略本轮超出±1的机器波动"
            RETURN 0
        ENDIF
"""
SEED_HOLD_OBSERVATION_OLD_DECISION = """\
    IF $Seed命中保持启用 == 1
        IF $Seed命中保持计数 < $Seed命中保持样本数
            $Seed修正模式文本 = "目标Seed参数保持中：" & $Seed命中保持计数 & "/" & $Seed命中保持样本数
            RETURN 0
        ENDIF
        IF $Seed命中保持正方向票数 == $Seed命中保持负方向票数
            # 10次出现5比5时没有唯一最多方向，继续保持并重新收集，避免任意选边。
            $Seed命中保持计数 = 0
            $Seed命中保持正方向票数 = 0
            $Seed命中保持负方向票数 = 0
            $Seed修正模式文本 = "目标Seed保持10次后方向5比5，继续保持重新采样"
            RETURN 0
        ENDIF
"""
SEED_HOLD_OBSERVATION_CURRENT_DECISION = """\
    IF $Seed命中保持启用 == 1
        IF $Seed命中保持计数 < $Seed命中保持样本数
            IF $Seed锁定本轮大波动忽略 == 1
                $Seed修正模式文本 = "目标Seed参数保持中：" & $Seed命中保持计数 & "/" & $Seed命中保持样本数 & "；本轮大波动不投方向票"
            ELSE
                $Seed修正模式文本 = "目标Seed参数保持中：" & $Seed命中保持计数 & "/" & $Seed命中保持样本数
            ENDIF
            RETURN 0
        ENDIF
        $Seed锁定方向票数 = $Seed命中保持正方向票数 + $Seed命中保持负方向票数
        IF $Seed锁定方向票数 < $Seed命中保持最少方向样本数
            $Seed命中保持计数 = 0
            $Seed命中保持正方向票数 = 0
            $Seed命中保持负方向票数 = 0
            $Seed修正模式文本 = "目标Seed保持10次后±1方向样本不足3，继续保持重新采样"
            RETURN 0
        ENDIF
        IF $Seed命中保持正方向票数 == $Seed命中保持负方向票数
            # 大波动只占观察次数，因此任意方向平票时都继续保持，避免任意选边。
            $Seed命中保持计数 = 0
            $Seed命中保持正方向票数 = 0
            $Seed命中保持负方向票数 = 0
            $Seed修正模式文本 = "目标Seed保持10次后±1方向票相同，继续保持重新采样"
            RETURN 0
        ENDIF
"""
EGG_FORMAL_PARITY_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：生成与领取复用正式版F1/F2奇偶校准"
EGG_FORMAL_PARITY_ORIGINAL_FUNCTION = "FUNC 孵蛋流程_计算两次命中时间(): INT"
EGG_FORMAL_PARITY_NEXT_FUNCTION = "FUNC 孵蛋流程_执行Seed预校准轮(): INT"
EGG_HATCH_EXIT_OVERRIDE_MARKER = "# GUI 孵蛋运行时覆盖：孵化骑车前可靠退出能力页、队伍菜单和主菜单"
EGG_HATCH_EXIT_ORIGINAL_FUNCTION = "FUNC 孵蛋测试_执行骑车孵化"
EGG_HATCH_EXIT_NEXT_FUNCTION = "FUNC 孵蛋测试_使用神奇糖果指定槽"
TOGEPI_HATCH_CYCLE_OVERRIDE_MARKER = "# 1.6.4-a 波克比专用孵化执行：按14步循环骑车，不再读取蛋孵化标签。"
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
EGG_POST_PICKUP_RETRY_POLICY_MARKER = "# GUI 孵蛋领取后Seed失败：保留首次预校准，直接重试生成领取"
EGG_NO_EGG_EVIDENCE_OVERRIDE_MARKER = "# GUI 孵蛋无蛋区间：同一Held请求跨非目标Seed轮保留证据"
EGG_FORMAL_PARITY_GLOBAL_ANCHOR = "$孵蛋流程请求Held帧 = 0"
EGG_FORMAL_PARITY_GLOBALS = """\
$孵蛋流程请求Pickup帧 = 0
$孵蛋流程执行Held帧 = 0
$孵蛋流程执行Pickup帧 = 0
$孵蛋流程奇偶F1修正帧 = 0
$孵蛋流程奇偶F2扣除帧 = 0
$孵蛋流程奇偶增加MS = 0
$孵蛋流程本轮奇偶等待MS = 0
$孵蛋流程Pickup奇偶基准帧 = 0
$孵蛋流程Pickup菜单奇偶开关 = 0
$孵蛋流程Pickup菜单推进帧 = 0
$孵蛋流程Held已稳定 = 0
"""
EGG_FORMAL_PARITY_REAL_CALL_OLD = "$孵蛋测试结果 = 孵蛋测试_执行同Seed两次命中($Seed模式, $孵蛋Seed等待MS, $时间轴精确尾段MS, $孵蛋奇偶等待MS, $孵蛋封面长按MS, $孵蛋流程TV过帧开关, $孵蛋流程TV等待MS, $孵蛋流程生成目标截止MS, $孵蛋流程领取目标截止MS, $孵蛋出蛋检测阈值, $识图阈值, 1, $孵蛋流程无蛋复核Seed开关)"
EGG_FORMAL_PARITY_REAL_CALL_PRE_MENU = EGG_FORMAL_PARITY_REAL_CALL_OLD.replace(
    "$孵蛋奇偶等待MS",
    "$孵蛋流程本轮奇偶等待MS",
    1,
)
EGG_FORMAL_PARITY_REAL_CALL_CURRENT = EGG_FORMAL_PARITY_REAL_CALL_PRE_MENU.replace(
    "$孵蛋流程领取目标截止MS, $孵蛋出蛋检测阈值",
    "$孵蛋流程领取目标截止MS, $孵蛋流程Pickup菜单奇偶开关, $孵蛋出蛋检测阈值",
    1,
)[:-1] + ", $Seed启动方案)"
EGG_FORMAL_PARITY_REAL_CALL_WAIT_MODE = (
    EGG_FORMAL_PARITY_REAL_CALL_CURRENT[:-1]
    + ", $孵蛋使用绝对时间轴)"
)
EGG_PICKUP_PARITY_MENU_MARKER = "# GUI 孵蛋领取奇偶：确认出蛋后开关菜单增加7 advance"
EGG_PICKUP_PARITY_ORIGINAL_FUNCTION = "FUNC 孵蛋测试_执行同Seed两次命中"
EGG_PICKUP_PARITY_SIGNATURE_OLD = "FUNC 孵蛋测试_执行同Seed两次命中($Seed模式: INT, $Seed等待MS: INT, $精确尾段MS: INT, $奇偶等待MS: INT, $封面长按MS: INT, $TV开关: INT, $TV等待MS: INT, $出蛋目标MS: INT, $领蛋目标MS: INT, $出蛋识图阈值: INT, $抓捕识图阈值: INT, $出闪后继续抓捕: INT, $无蛋后复核Seed: INT): INT"
EGG_PICKUP_PARITY_SIGNATURE_CURRENT = EGG_PICKUP_PARITY_SIGNATURE_OLD.replace(
    "$领蛋目标MS: INT, $出蛋识图阈值",
    "$领蛋目标MS: INT, $Pickup菜单奇偶开关: INT, $出蛋识图阈值",
    1,
)[:-6] + ", $Seed启动方案: INT): INT"
EGG_PICKUP_PARITY_SIGNATURE_WAIT_MODE = EGG_PICKUP_PARITY_SIGNATURE_CURRENT.replace(
    "$Seed启动方案: INT): INT",
    "$Seed启动方案: INT, $使用绝对时间轴: INT): INT",
    1,
)
EGG_PICKUP_PARITY_VALIDATION_OLD = """\
    IF $无蛋后复核Seed != 0 and $无蛋后复核Seed != 1
        PRINT 孵蛋无蛋后Seed复核开关无效: & $无蛋后复核Seed
        RETURN 0
    ENDIF
    $孵蛋库_启动结果 = 孵蛋测试_启动并进入存档($Seed模式, $Seed等待MS, $精确尾段MS, $奇偶等待MS, $封面长按MS)
"""
EGG_PICKUP_PARITY_VALIDATION_CURRENT = """\
    IF $无蛋后复核Seed != 0 and $无蛋后复核Seed != 1
        PRINT 孵蛋无蛋后Seed复核开关无效: & $无蛋后复核Seed
        RETURN 0
    ENDIF
    IF $Pickup菜单奇偶开关 != 0 and $Pickup菜单奇偶开关 != 1
        PRINT 孵蛋Pickup菜单奇偶开关无效: & $Pickup菜单奇偶开关
        RETURN 0
    ENDIF
    $孵蛋库_启动结果 = 孵蛋测试_启动并进入存档($Seed模式, $Seed等待MS, $精确尾段MS, $奇偶等待MS, $封面长按MS, $Seed启动方案)
"""
EGG_PICKUP_PARITY_ACTION_OLD = """\
        RETURN 2
    ENDIF
    LS RIGHT
"""
EGG_PICKUP_PARITY_ACTION_UNMARKED = """\
        RETURN 2
    ENDIF
    IF $Pickup菜单奇偶开关 == 1
        PRINT 孵蛋领取奇偶校准: 出培育屋后开关一次菜单，物理增加7 advance
        X
        WAIT 500
        B
        WAIT 500
    ENDIF
    LS RIGHT
"""
EGG_PICKUP_PARITY_ACTION_CURRENT = EGG_PICKUP_PARITY_ACTION_UNMARKED.replace(
    "    IF $Pickup菜单奇偶开关 == 1\n",
    f"    {EGG_PICKUP_PARITY_MENU_MARKER}\n    IF $Pickup菜单奇偶开关 == 1\n",
    1,
)
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
$孵蛋HOME_BUFFER调整差 = 0
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
# 首次命中后锁定延迟；同一锁定值连续失败3次才重新校准，单次调整至少50 ms。
$HOME_BUFFER最小调整MS = 50
$HOME_BUFFER锁定失败阈值 = 3
$HOME_BUFFER锁定启用 = 0
$HOME_BUFFER锁定延迟 = 0
$HOME_BUFFER锁定连续失败 = 0
$HOME_BUFFER尝试 = 0
$HOME_BUFFER未知连续次数 = 0
$HOME_BUFFER重采样 = 0
$HOME_BUFFER本轮待确认 = 0
$HOME_BUFFER本轮延迟 = 0
$HOME_BUFFER恢复需要 = 0
$HOME_BUFFER恢复结果 = 0
$HOME_BUFFER恢复采样 = 0
$HOME_BUFFER恢复已按HOME = 0
$HOME_BUFFER恢复关闭次数 = 0
$HOME_BUFFER恢复主页 = 0
$HOME_BUFFER恢复普通 = 0
$HOME_BUFFER恢复窗口 = 0
$HOME_BUFFER恢复错误 = 0
$HOME_BUFFER恢复关闭中 = 0
$HOME_BUFFER恢复稳定 = 0
$HOME_BUFFER恢复未知 = 0
$HOME_BUFFER下一延迟 = 0
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
    PRINT 领取后野生Seed反查失败，关闭游戏并直接重试生成领取
    $孵蛋流程Seed已预校准 = 1
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
EGG_POST_PICKUP_MISS_OLD = """\
    ELIF $孵蛋流程Seed验证结果 == 2
        PRINT 领取后未命中目标Seed，本轮丢弃并重新预校准
        $孵蛋流程Seed已预校准 = 0
        $孵蛋流程Seed校正结果 = 孵蛋流程_按观测Seed校正等待($候选同一Seed值)
        IF $孵蛋流程Seed校正结果 != 1
            CALL 孵蛋流程_重开下一轮
            RETURN 0
        ENDIF
        CALL 孵蛋流程_重开下一轮
        RETURN 2
    ENDIF
"""
EGG_POST_PICKUP_MISS_CURRENT = """\
    ELIF $孵蛋流程Seed验证结果 == 2
        PRINT 领取后未命中目标Seed，本轮丢弃并校正Seed等待
        PRINT 首次不领蛋预校准已经完成，下一轮直接重新生成、领取并反查
        $孵蛋流程Seed已预校准 = 1
        $孵蛋流程Seed校正结果 = 孵蛋流程_按观测Seed校正等待($候选同一Seed值)
        IF $孵蛋流程Seed校正结果 != 1
            CALL 孵蛋流程_重开下一轮
            RETURN 0
        ENDIF
        CALL 孵蛋流程_重开下一轮
        RETURN 2
    ENDIF
"""
EGG_POST_PICKUP_FAILURE_OLD = """\
    PRINT 领取后野生Seed反查失败，关闭游戏并重新预校准
    $孵蛋流程Seed已预校准 = 0
    CALL 孵蛋流程_重开下一轮
    RETURN 2
"""
EGG_POST_PICKUP_FAILURE_CURRENT = """\
    PRINT 领取后野生Seed反查失败，关闭游戏并直接重试生成领取
    $孵蛋流程Seed已预校准 = 1
    CALL 孵蛋流程_重开下一轮
    RETURN 2
"""
EGG_NO_EGG_REQUEST_CHANGE_OLD = """\
    IF $孵蛋流程上次无蛋请求Held帧 != $孵蛋流程请求Held帧
        $孵蛋流程无蛋连续次数 = 0
        $孵蛋流程上次无蛋请求Held帧 = $孵蛋流程请求Held帧
    ENDIF
"""
EGG_NO_EGG_SEED_GATE_OLD = """\
    $孵蛋流程无蛋复核Seed开关 = 0
    IF $孵蛋流程Pickup已稳定 == 1
        $孵蛋流程无蛋复核Seed开关 = 1
    ELIF $孵蛋流程无蛋连续次数 + 1 >= $孵蛋普通无蛋复核阈值
        $孵蛋流程无蛋复核Seed开关 = 1
    ENDIF
"""
EGG_NO_EGG_SEED_GATE_CURRENT = """\
    $孵蛋流程无蛋复核Seed开关 = 0
    # 使用蛋反查留下的Held记录，不把固定预校准或当前累计修正当作已校准标志。
    IF $孵蛋流程上次确认实际Held帧 >= 0 or $孵蛋流程Pickup已稳定 == 1
        $孵蛋流程无蛋复核Seed开关 = 1
    ELIF $孵蛋流程无蛋连续次数 + 1 >= $孵蛋普通无蛋复核阈值
        $孵蛋流程无蛋复核Seed开关 = 1
    ENDIF
"""
EGG_WILD_SEED_WINDOW_INIT = """\
    # 同一只野生扩窗后，后续吃糖继续使用扩大窗口；下一只重新从默认窗口开始。
    $有效Seed容差 = $孵蛋野生Seed容差
    $有效最小消耗帧 = $孵蛋野生最小消耗帧
    $有效最大消耗帧 = $孵蛋野生最大消耗帧
"""
EGG_WILD_SEED_SCAN_OLD = """\
        $有效Seed容差 = $孵蛋野生Seed容差
        $有效最小消耗帧 = $孵蛋野生最小消耗帧
        $有效最大消耗帧 = $孵蛋野生最大消耗帧
        $孵蛋流程扫描结果 = 执行反查扫描()
        IF $孵蛋流程扫描结果 != 1
            PRINT 孵蛋野生Seed反查无候选
            RETURN 0
        ENDIF
"""
EGG_WILD_SEED_SCAN_CURRENT = """\
        $孵蛋流程扫描结果 = 执行反查扫描()
        IF $孵蛋流程扫描结果 != 1 and $有效Seed容差 == $孵蛋野生Seed容差
            # 仅默认窗口无候选时追加一档：Seed前后各5，帧上限增加1000，下限不变。
            $有效Seed容差 = $孵蛋野生Seed容差 + 5
            $有效最大消耗帧 = $孵蛋野生最大消耗帧 + 1000
            PRINT 孵蛋野生Seed反查无候选，追加一档扩窗
            PRINT 有效Seed容差: ± & $有效Seed容差 & "，有效消耗帧范围: " & $有效最小消耗帧 & "-" & $有效最大消耗帧
            $孵蛋流程扫描结果 = 执行反查扫描()
        ENDIF
        IF $孵蛋流程扫描结果 != 1
            PRINT 孵蛋野生Seed反查无候选
            RETURN 0
        ENDIF
"""
EGG_NO_EGG_REQUEST_CHANGE_CURRENT = f"""\
    {EGG_NO_EGG_EVIDENCE_OVERRIDE_MARKER}
    IF $孵蛋流程上次无蛋请求Held帧 != $孵蛋流程请求Held帧
        $孵蛋流程无蛋连续次数 = 0
        $孵蛋流程目标Seed无蛋次数 = 0
        $孵蛋流程目标Seed无蛋区间索引 = -1
        $孵蛋流程目标Seed无蛋区间确认次数 = 0
        $孵蛋流程上次无蛋请求Held帧 = $孵蛋流程请求Held帧
    ENDIF
"""
EGG_NO_EGG_REQUEST_CHANGE_FIXED_UNMARKED = EGG_NO_EGG_REQUEST_CHANGE_CURRENT.replace(
    f"    {EGG_NO_EGG_EVIDENCE_OVERRIDE_MARKER}\n",
    "",
    1,
)
EGG_NO_EGG_NON_TARGET_OLD = """\
        ELIF $孵蛋流程Seed验证结果 == 2
            PRINT 无蛋后未命中目标Seed：本轮只校正Seed等待，不累计Held无蛋区间证据
            $孵蛋流程目标Seed无蛋次数 = 0
            $孵蛋流程目标Seed无蛋区间索引 = -1
            $孵蛋流程目标Seed无蛋区间确认次数 = 0
            $孵蛋流程无蛋连续次数 = 0
"""
EGG_NO_EGG_NON_TARGET_CURRENT = """\
        ELIF $孵蛋流程Seed验证结果 == 2
            PRINT 无蛋后未命中目标Seed：本轮只校正Seed等待；保留同一Held请求已有无蛋区间证据
            $孵蛋流程无蛋连续次数 = 0
"""
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
    # 0 keeps the current HOME_BUFFER path; 1 uses the fixed user-selection
    # HOME sequence measured by the legacy standalone RNG script.
    seed_startup_scheme: int = 0
    # Temporary Japanese starter branch.  It changes only the generated
    # starter project; ordinary English 1.1.8 projects keep their corpus.
    japanese_starter: bool = False
    # The formal entry supports the two audited Seed calibration paths.  This
    # is appended after the historical fields to keep positional callers
    # compatible.
    seed_calibration_scheme: int = 0
    # Wild encounters can optionally target held-item outcomes.  The ECS
    # runtime uses the number of empty party slots as the number of item hits
    # to collect before stopping.
    item_rng_mode: bool = False
    party_empty_slots: int = 1
    # Persist a successful run's calibration for the matching game/NX/entry.
    # These fields are appended to preserve positional callers from older tools.
    update_precalibration: bool = False
    precalibration_seed_ns1: int | None = None
    precalibration_seed_ns2: int | None = None
    precalibration_frame_ns1: int | None = None
    precalibration_frame_ns2: int | None = None
    # ``STARTER`` keeps the TID -> rival starter route separate from ordinary
    # static encounters, whose preceding menu/bridge flow is different.
    precalibration_context_kind: str | None = None


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
    seed_startup_scheme: int = 0
    # The timeline entry also exposes its current scheme 2.  Keep that as the
    # backwards-compatible default while allowing advanced callers to choose
    # the audited 0/1 A/B paths explicitly.
    seed_calibration_scheme: int = 2
    update_precalibration: bool = False
    precalibration_seed_ns1: int | None = None
    precalibration_seed_ns2: int | None = None
    precalibration_held: int | None = None
    precalibration_pickup: int | None = None

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
        if self.seed_startup_scheme not in {0, 1}:
            raise ValueError("Seed启动方案只能是0（当前HOME_BUFFER）或1（固定用户界面HOME）")
        if self.seed_calibration_scheme not in {0, 1, 2}:
            raise ValueError(
                "Seed校准方案只能是0（原始12轮众数）、1（实验锁定细调）或2（成功参数保持）"
            )
        if not isinstance(self.update_precalibration, bool):
            raise ValueError("更新预校准开关必须是布尔值")
        for name, value in (
            ("Seed预校准索引_NS1", self.precalibration_seed_ns1),
            ("Seed预校准索引_NS2", self.precalibration_seed_ns2),
            ("孵蛋Held动态预校准帧", self.precalibration_held),
            ("孵蛋Pickup动态预校准帧", self.precalibration_pickup),
        ):
            _validated_optional_int(name, value)
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
            fallback = EASYCON118_LOCAL_LABEL_DIR / name
            if fallback.is_file():
                source = fallback
            else:
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


def _validated_optional_int(name: str, value: object) -> int | None:
    """Normalize an optional pre-calibration value before writing ECS."""
    if value is None:
        return None
    if type(value) is not int:
        raise ValueError(f"预校准值{name}必须是整数")
    if name.startswith("Seed预校准索引_") and not -10000 <= value <= 10000:
        raise ValueError(f"预校准值{name}超出允许范围")
    if name.startswith("消耗帧预校准修正_") and not -1_000_000 <= value <= 1_000_000:
        raise ValueError(f"预校准值{name}超出允许范围")
    if name.startswith("孵蛋") and not -1_000_000 <= value <= 1_000_000:
        raise ValueError(f"预校准值{name}超出允许范围")
    return value


def _normalized_template_name(template_name: str | None, *, default: str) -> str:
    selected = default if template_name is None else str(template_name).strip()
    if selected not in EXPECTED_TEMPLATE_NAMES:
        raise ValueError(
            "脚本模板只能选择正式版或时间轴版入口，当前为 " + repr(selected)
        )
    return selected


def _precalibration_entry(template_name: str) -> str:
    return "FORMAL" if template_name == STANDARD_TEMPLATE_NAME else "TIMELINE"


def _precalibration_frame_enabled(context: PrecalibrationContext) -> bool:
    # The ordinary formal static route has target-specific preparation whose
    # frame correction must not leak to another static target. Starter runs
    # have their own isolated context and may therefore retain their frame.
    return context.entry == "TIMELINE" or context.kind in {"WILD", "EGG", "STARTER"}


def _plan_precalibration_context(
    plan: RunPlan,
    options: EasyCon118Options,
    template_name: str,
) -> PrecalibrationContext:
    nx_model = options.nx_model
    if nx_model is None:
        nx_model = 2 if plan.request.game.endswith("nx2") else 1
    expected_kind = "WILD" if _is_wild(plan) else "STATIC"
    kind = normalize_precalibration_kind(
        options.precalibration_context_kind or expected_kind
    )
    if kind == "STARTER":
        if expected_kind != "STATIC" or plan.species_id not in {1, 4, 7}:
            raise ValueError("御三家预校准上下文只允许用于图鉴1/4/7的静态流程")
    elif kind != expected_kind:
        raise ValueError("预校准流程类型与当前生成计划不一致")
    return PrecalibrationContext(
        game=plan.request.game,
        nx_model=nx_model,
        seed_mode=10 if options.japanese_starter else plan.seed_mode,
        seed_startup_scheme=options.seed_startup_scheme,
        entry=_precalibration_entry(template_name),
        kind=kind,
    )


def _egg_precalibration_context(
    request: EggRunRequest,
    template_name: str,
) -> PrecalibrationContext:
    return PrecalibrationContext(
        game=request.game,
        nx_model=request.nx_model,
        seed_mode=request.seed_mode,
        seed_startup_scheme=request.seed_startup_scheme,
        entry=_precalibration_entry(template_name),
        kind="EGG",
    )


def _precalibration_store_path(path: str | Path | None) -> Path:
    selected = DEFAULT_PRECALIBRATION_STORE_PATH if path is None else Path(path)
    return selected.expanduser().resolve()


def _load_plan_precalibration(
    plan: RunPlan,
    options: EasyCon118Options,
    template_name: str,
    store_path: Path,
) -> tuple[EasyCon118Options, dict[str, Any]]:
    if not isinstance(options.update_precalibration, bool):
        raise ValueError("更新预校准开关必须是布尔值")
    context = _plan_precalibration_context(plan, options, template_name)
    frame_enabled = _precalibration_frame_enabled(context)
    loaded = (
        read_precalibration_record(store_path, context)
        if options.update_precalibration
        else None
    )
    effective = options
    if loaded is not None:
        replacements: dict[str, Any] = {}
        seed_field = "seed_ns1" if context.nx_model == 1 else "seed_ns2"
        seed_value = loaded.get(seed_field)
        if seed_value is not None:
            replacements[f"precalibration_{seed_field}"] = seed_value
        if frame_enabled:
            frame_field = "frame_ns1" if context.nx_model == 1 else "frame_ns2"
            frame_value = loaded.get(frame_field)
            if frame_value is not None:
                replacements[f"precalibration_{frame_field}"] = frame_value
        if replacements:
            effective = replace(options, **replacements)
    manifest = {
        "enabled": bool(options.update_precalibration),
        "context": context.to_dict(),
        "source_path": str(store_path),
        "frame_enabled": frame_enabled,
        "loaded": loaded,
    }
    return effective, manifest


def _load_egg_precalibration(
    request: EggRunRequest,
    template_name: str,
    store_path: Path,
) -> tuple[EggRunRequest, dict[str, Any]]:
    context = _egg_precalibration_context(request, template_name)
    loaded = (
        read_precalibration_record(store_path, context)
        if request.update_precalibration
        else None
    )
    effective = request
    if loaded is not None:
        replacements: dict[str, Any] = {}
        seed_field = "seed_ns1" if context.nx_model == 1 else "seed_ns2"
        seed_value = loaded.get(seed_field)
        if seed_value is not None:
            replacements[f"precalibration_{seed_field}"] = seed_value
        if loaded.get("held_pre") is not None:
            replacements["precalibration_held"] = loaded["held_pre"]
        if loaded.get("pickup_pre") is not None:
            replacements["precalibration_pickup"] = loaded["pickup_pre"]
        if replacements:
            effective = replace(request, **replacements)
    manifest = {
        "enabled": bool(request.update_precalibration),
        "context": context.to_dict(),
        "source_path": str(store_path),
        "frame_enabled": True,
        "loaded": loaded,
    }
    return effective, manifest


def _function_block(text: str, signature: str) -> tuple[int, int, str]:
    if text.count(signature) != 1:
        raise ValueError(f"1.1.8 模板缺少唯一函数: {signature}")
    start = text.index(signature)
    end_marker = "\nENDFUNC"
    end = text.index(end_marker, start) + len(end_marker)
    return start, end, text[start:end]


def _replace_function_block(text: str, signature: str, block: str) -> str:
    start, end, _ = _function_block(text, signature)
    return text[:start] + block + text[end:]


def _insert_precalibration_globals(text: str, lines: list[str]) -> str:
    if PRECALIBRATION_RUNTIME_MARKER in text:
        raise ValueError("生成脚本已经包含预校准运行时覆盖，拒绝重复注入")
    pattern = re.compile(r"(?m)^(\$Seed预校准索引_NS2\s*=\s*[^\r\n]*)$")
    addition = "\n" + PRECALIBRATION_RUNTIME_MARKER + "\n" + "\n".join(lines)
    configured, count = pattern.subn(r"\1" + addition, text, count=1)
    if count != 1:
        raise ValueError("1.1.8 模板缺少唯一的NS2 Seed预校准字段")
    return configured


def _apply_seed_precalibration_globals(
    text: str,
    *,
    seed_ns1: int | None,
    seed_ns2: int | None,
) -> str:
    """Replace the two audited advanced globals outside the user section."""
    configured = text
    for name, value in (
        ("Seed预校准索引_NS1", seed_ns1),
        ("Seed预校准索引_NS2", seed_ns2),
    ):
        normalized = _validated_optional_int(name, value)
        if normalized is None:
            continue
        pattern = re.compile(rf"(?m)^\${re.escape(name)}\s*=\s*[^\r\n]*$")
        configured, count = pattern.subn(f"${name} = {normalized}", configured)
        if count != 1:
            raise ValueError(f"1.1.8 模板字段 ${name} 应出现 1 次，实际为 {count} 次")
    return configured


def _precalibration_marker_head(context: PrecalibrationContext) -> str:
    return (
        "PRECALIBRATION_UPDATE|V=1"
        f"|GAME={context.game.upper()}"
        f"|NX={context.nx_model}"
        f"|MODE={context.seed_mode}"
        f"|STARTUP={context.seed_startup_scheme}"
        f"|ENTRY={context.entry}"
        f"|KIND={context.kind}"
        "|SEED_INDEX="
    )


def _apply_regular_precalibration_runtime_text(
    text: str,
    options: EasyCon118Options,
    config: dict[str, Any],
) -> str:
    context = PrecalibrationContext(**config["context"])
    text = _apply_seed_precalibration_globals(
        text,
        seed_ns1=options.precalibration_seed_ns1,
        seed_ns2=options.precalibration_seed_ns2,
    )
    frame_enabled = bool(config["frame_enabled"])
    frame_ns1 = options.precalibration_frame_ns1 if frame_enabled else 0
    frame_ns2 = options.precalibration_frame_ns2 if frame_enabled else 0
    frame_ns1 = 0 if frame_ns1 is None else frame_ns1
    frame_ns2 = 0 if frame_ns2 is None else frame_ns2
    frame_ns1 = _validated_optional_int("消耗帧预校准修正_NS1", frame_ns1)
    frame_ns2 = _validated_optional_int("消耗帧预校准修正_NS2", frame_ns2)
    text = _insert_precalibration_globals(
        text,
        [
            f"$更新预校准 = {1 if config['enabled'] else 0}",
            f"$消耗帧预校准修正_NS1 = {frame_ns1}",
            f"$消耗帧预校准修正_NS2 = {frame_ns2}",
            "$消耗帧预校准修正 = 0",
        ],
    )
    ns1_anchor = "    $Seed预校准索引 = $Seed预校准索引_NS1"
    ns2_anchor = "    $Seed预校准索引 = $Seed预校准索引_NS2"
    if text.count(ns1_anchor) != 1 or text.count(ns2_anchor) != 1:
        raise ValueError("1.1.8 模板的NX Seed预校准选择分支数量异常")
    text = text.replace(
        ns1_anchor,
        ns1_anchor + "\n    $消耗帧预校准修正 = $消耗帧预校准修正_NS1",
        1,
    ).replace(
        ns2_anchor,
        ns2_anchor + "\n    $消耗帧预校准修正 = $消耗帧预校准修正_NS2",
        1,
    )

    signature = "FUNC 记录固定延迟并开始自动乱数(): INT"
    _, _, block = _function_block(text, signature)
    recalc_anchor = "    $校准成功 = 重新计算等待参数()"
    if block.count(recalc_anchor) != 1:
        raise ValueError("1.1.8 固定延迟函数缺少唯一的等待参数重算入口")
    block = block.replace(
        recalc_anchor,
        "    $消耗帧实际执行修正量 += $消耗帧预校准修正\n"
        "    $消耗帧本次新增修正量 += $消耗帧预校准修正\n"
        + recalc_anchor,
        1,
    )
    text = _replace_function_block(text, signature, block)

    if not config["enabled"]:
        return text
    marker_line = (
        f'        PRINT "{_precalibration_marker_head(context)}" & '
        '$Seed累计修正索引 & "|FRAME_PRE=" & $消耗帧实际执行修正量 & '
        f'"|FRAME_ENABLED={1 if frame_enabled else 0}"'
    )
    signature = "FUNC 执行自动校准与等待更新(): INT"
    _, _, block = _function_block(text, signature)
    terminal_anchor = "        PRINT 已命中目标，脚本停止"
    if block.count(terminal_anchor) != 1:
        raise ValueError("1.1.8 自动校准函数缺少唯一的完整目标命中分支")
    block = block.replace(terminal_anchor, marker_line + "\n" + terminal_anchor, 1)
    shadow_anchor = (
        "        PRINT Seed与消耗帧精确命中，但本轮不是目标闪光；"
        "刷新成功参数保持并继续运行"
    )
    if shadow_anchor in block:
        block = block.replace(shadow_anchor, marker_line + "\n" + shadow_anchor, 1)
    return _replace_function_block(text, signature, block)


def _apply_egg_precalibration_runtime_text(
    text: str,
    request: EggRunRequest,
    config: dict[str, Any],
) -> str:
    text = _apply_seed_precalibration_globals(
        text,
        seed_ns1=request.precalibration_seed_ns1,
        seed_ns2=request.precalibration_seed_ns2,
    )
    held = 0 if request.precalibration_held is None else request.precalibration_held
    pickup = 0 if request.precalibration_pickup is None else request.precalibration_pickup
    held = _validated_optional_int("孵蛋Held动态预校准帧", held)
    pickup = _validated_optional_int("孵蛋Pickup动态预校准帧", pickup)
    text = _insert_precalibration_globals(
        text,
        [
            f"$更新预校准 = {1 if config['enabled'] else 0}",
            f"$孵蛋Held动态预校准帧 = {held}",
            f"$孵蛋Pickup动态预校准帧 = {pickup}",
        ],
    )
    signature = "FUNC 孵蛋流程_执行(): INT"
    _, _, block = _function_block(text, signature)
    init_anchor = (
        "    $孵蛋流程Seed已预校准 = 0\n"
        "    $孵蛋Held执行修正帧 = 0\n"
        "    $孵蛋Pickup执行修正帧 = 0"
    )
    init_replacement = (
        "    $孵蛋流程Seed已预校准 = 0\n"
        "    $孵蛋Held执行修正帧 = $孵蛋Held动态预校准帧\n"
        "    $孵蛋Pickup执行修正帧 = $孵蛋Pickup动态预校准帧"
    )
    if block.count(init_anchor) != 1:
        raise ValueError("1.1.8 孵蛋总控缺少唯一的Held/Pickup动态修正初始化")
    block = block.replace(init_anchor, init_replacement, 1)
    text = _replace_function_block(text, signature, block)

    if not config["enabled"]:
        return text
    context = PrecalibrationContext(**config["context"])
    marker_line = (
        f'    PRINT "{_precalibration_marker_head(context)}" & '
        '$Seed累计修正索引 & "|FRAME_PRE=0|FRAME_ENABLED=1|HELD_PRE=" & '
        '$孵蛋Held执行修正帧 & "|PICKUP_PRE=" & $孵蛋Pickup执行修正帧'
    )
    signature = "FUNC 孵蛋流程_执行孵化与个体反查(): INT"
    _, _, block = _function_block(text, signature)
    success_anchor = "    PRINT 孵蛋目标Seed、Held帧和Pickup帧全部命中，流程完成"
    if block.count(success_anchor) != 1:
        raise ValueError("1.1.8 孵蛋完成函数缺少唯一的完整目标命中分支")
    block = block.replace(success_anchor, marker_line + "\n" + success_anchor, 1)
    return _replace_function_block(text, signature, block)


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

    if options.seed_startup_scheme not in {0, 1}:
        raise ValueError("Seed启动方案只能是0（当前HOME_BUFFER）或1（固定用户界面HOME）")
    if options.seed_calibration_scheme not in {0, 1}:
        raise ValueError("正式版 Seed校准方案只能是0（原始12轮众数）或1（实验锁定细调）")
    is_wild = _is_wild(plan)
    if not isinstance(options.item_rng_mode, bool):
        raise ValueError("道具乱数模式必须是布尔值")
    if options.item_rng_mode and not is_wild:
        raise ValueError("道具乱数模式当前仅支持野生目标")
    item_rng_enabled = options.item_rng_mode and is_wild
    if item_rng_enabled:
        try:
            party_empty_slots = int(options.party_empty_slots)
        except (TypeError, ValueError) as exc:
            raise ValueError("队伍空位数量必须是 1-5 的整数") from exc
        if not 1 <= party_empty_slots <= 5:
            raise ValueError("队伍空位数量必须在 1-5 之间")
    else:
        party_empty_slots = 1
    category_zh = CATEGORY_EN_TO_ZH.get(plan.request.category, plan.request.category)
    location_zh = location_to_zh(plan.request.location)
    if options.japanese_starter and (
        plan.request.category != "Starter" or plan.species_id not in {1, 4, 7}
    ):
        raise ValueError("日版御三家临时分支仅支持静态图鉴1/4/7")
    # The Japanese NX table currently contains only mono_h_a.  Keep the
    # planner's logical setting at mode 0, but materialize it as the
    # generated-project-only mode 10 so the English table cannot be reused.
    script_seed_mode = 10 if options.japanese_starter else plan.seed_mode
    values = {
        "游戏版本文本": _game_text(plan.request.game),
        "Seed模式": script_seed_mode,
        "NX机型": nx_model,
        "Seed校准方案": options.seed_calibration_scheme,
        "Seed启动方案": options.seed_startup_scheme,
        "目标Seed": plan.initial_seed.seed.upper(),
        "目标消耗帧": plan.initial_seed.advances,
        # The ECS resolves the name before the numeric Dex field.  Generated
        # plans are authoritative, so clear any stale template name instead
        # of letting a previous target override the generated Dex number.
        "目标宝可梦名称": "",
        "目标全国图鉴编号": plan.species_id,
        "静态或野生": "野生" if is_wild else "静态",
        "宝可梦遭遇方法": category_zh if is_wild else "草丛",
        "宝可梦遭遇地点": location_zh if is_wild else "",
        "麻痹": int(options.paralysis),
        "点到为止": int(options.false_swipe),
        "出闪后继续抓捕": int(options.continue_capture_after_shiny),
        # Static and ordinary wild runs always materialize the safe defaults;
        # item mode is only meaningful for wild encounters.
        "道具乱数模式": int(item_rng_enabled),
        "队伍空位数量": party_empty_slots,
    }
    return values


def egg_request_to_user_values(request: EggRunRequest) -> dict[str, Any]:
    """Map a Ten Lines Egg result to the experimental same-seed ECS fields."""
    request.validate()
    values: dict[str, Any] = {
        "游戏版本文本": _game_text(request.game),
        "Seed模式": request.seed_mode,
        "NX机型": request.nx_model,
        "Seed校准方案": request.seed_calibration_scheme,
        "Seed启动方案": request.seed_startup_scheme,
        "目标Seed": request.normalized_seed,
        "目标消耗帧": request.held_advances,
        "目标宝可梦名称": "",
        "目标全国图鉴编号": request.species_id,
        "静态或野生": "孵蛋",
        # The timeline template is also used for item-RNG experiments and may
        # retain the author's last value. Egg generation must always disable
        # that mutually exclusive mode or runtime validation rejects the run.
        "道具乱数模式": 0,
        "队伍空位数量": 1,
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


def build_egg_held_availability(
    request: EggRunRequest,
    *,
    held_offset: int = 0,
    before: int = 100,
    after: int = 100,
) -> dict[str, Any]:
    """Build Ten Lines-compatible FRLG Held no-egg intervals."""
    request.validate()
    if held_offset < 0:
        raise ValueError("Held Offset 不能为负数")
    if before < 0 or after < 0:
        raise ValueError("Held无蛋表前后窗口不能为负数")
    range_start = max(0, request.held_advances - before)
    range_end = request.held_advances + after
    seed = int(request.normalized_seed, 16)

    # Ten Lines Egg Held判定：目标帧先加Offset，再前进1次取高16位。
    state = seed
    for _ in range(range_start + held_offset + 1):
        state = (state * 0x41C64E6D + 0x6073) & 0xFFFFFFFF

    intervals: list[tuple[int, int]] = []
    producing_frames: list[int] = []
    interval_start: int | None = None
    for frame in range(range_start, range_end + 1):
        produces_egg = (((state >> 16) * 100) // 65535) < request.compatibility
        if produces_egg:
            producing_frames.append(frame)
        if not produces_egg and interval_start is None:
            interval_start = frame
        elif produces_egg and interval_start is not None:
            intervals.append((interval_start, frame - 1))
            interval_start = None
        state = (state * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
    if interval_start is not None:
        intervals.append((interval_start, range_end))

    produced = set(producing_frames)
    near_recovery_anchors: list[int] = []
    for candidate in (request.held_advances - 2, request.held_advances + 2):
        middle = (candidate + request.held_advances) // 2
        if (
            candidate in produced
            and middle in produced
            and request.held_advances in produced
        ):
            near_recovery_anchors.append(candidate)

    def parity_run(frame: int) -> int:
        count = 1
        cursor = frame - 2
        while cursor in produced:
            count += 1
            cursor -= 2
        cursor = frame + 2
        while cursor in produced:
            count += 1
            cursor += 2
        return count

    def local_density(frame: int) -> int:
        return sum(candidate in produced for candidate in range(frame - 2, frame + 3))

    fallback_recovery_anchors = [
        frame
        for frame in producing_frames
        if frame != request.held_advances
        and frame not in near_recovery_anchors
        and frame % 2 == request.held_advances % 2
    ]
    fallback_recovery_anchors.sort(
        key=lambda frame: (
            -local_density(frame),
            -parity_run(frame),
            abs(frame - request.held_advances),
            frame,
        )
    )

    return {
        "schema": "frlg-held-availability/v2",
        "heldSeed": request.normalized_seed,
        "targetHeld": request.held_advances,
        "compatibility": request.compatibility,
        "heldOffset": held_offset,
        "rangeStart": range_start,
        "rangeEnd": range_end,
        "targetProducesEgg": not any(
            start <= request.held_advances <= end for start, end in intervals
        ),
        "noEggIntervals": intervals,
        "nearRecoveryAnchors": near_recovery_anchors,
        "fallbackRecoveryAnchors": fallback_recovery_anchors,
    }


def egg_held_availability_to_ecs_values(
    availability: dict[str, Any],
) -> dict[str, Any]:
    intervals = availability["noEggIntervals"]
    return {
        "孵蛋Held无蛋表Seed": availability["heldSeed"],
        "孵蛋Held无蛋表目标帧": availability["targetHeld"],
        "孵蛋Held无蛋表相性": availability["compatibility"],
        "孵蛋Held无蛋表Offset": availability["heldOffset"],
        "孵蛋Held无蛋表最小帧": availability["rangeStart"],
        "孵蛋Held无蛋表最大帧": availability["rangeEnd"],
        "孵蛋Held无蛋区间起点表": [start for start, _ in intervals],
        "孵蛋Held无蛋区间终点表": [end for _, end in intervals],
        "孵蛋Held近邻恢复锚点表": availability["nearRecoveryAnchors"],
        "孵蛋Held远端恢复锚点表": availability["fallbackRecoveryAnchors"],
    }


def _ecs_literal(value: Any) -> str:
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_ecs_literal(item) for item in value) + "]"
    return str(value)


def _configure_all_values(template_text: str, values: dict[str, Any]) -> str:
    configured = template_text
    for name, value in values.items():
        pattern = re.compile(rf"(?m)^\s*\${re.escape(name)}\s*=\s*[^\r\n]*$")
        configured, count = pattern.subn(f"${name} = {_ecs_literal(value)}", configured)
        if count != 1:
            raise ValueError(f"1.1.8 模板字段 ${name} 应出现 1 次，实际为 {count} 次")
    return configured


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

    return _configure_user_values(
        template_text,
        plan_to_user_values(plan, options),
        optional_names={"Seed校准方案"},
    )


def _configure_user_values(
    template_text: str,
    values: dict[str, Any],
    *,
    optional_names: set[str] | frozenset[str] = frozenset(),
) -> str:
    template_text = _apply_seed_mode3_help_start_text(template_text)
    marker = "# ============================进阶设置"
    user_section, separator, remainder = template_text.partition(marker)
    if not separator:
        raise ValueError("1.1.8 模板缺少进阶设置分界标记，拒绝在未知版本中替换参数")
    configured = user_section
    for name, value in values.items():
        pattern = re.compile(rf"(?m)^\s*\${re.escape(name)}\s*=\s*[^\r\n]*$")
        configured, count = pattern.subn(f"${name} = {_ecs_literal(value)}", configured)
        if count == 0 and name in optional_names:
            continue
        if count != 1:
            raise ValueError(f"1.1.8 模板字段 ${name} 应出现 1 次，实际为 {count} 次")
    return configured + (separator + remainder if separator else "")


def _configured_user_assignments(project_main: str | Path) -> dict[str, str]:
    """Read the generated ECS user-input assignments for consistency checks."""
    project_main = Path(project_main)
    text = project_main.read_text(encoding="utf-8-sig")
    user_section, separator, _ = text.partition("# ============================进阶设置")
    if not separator:
        raise ValueError("生成脚本缺少进阶设置分界标记，无法核对写入参数")
    assignments: dict[str, str] = {}
    pattern = re.compile(r"^\s*\$([^\s=]+)\s*=\s*(.*?)\s*$")
    for line in user_section.splitlines():
        match = pattern.match(line)
        if match:
            assignments[match.group(1)] = match.group(2)
    return assignments


def _assert_configured_user_values(
    project_main: str | Path,
    values: dict[str, Any],
) -> None:
    assignments = _configured_user_assignments(project_main)
    for name, value in values.items():
        expected = _ecs_literal(value)
        actual = assignments.get(name)
        if actual != expected:
            raise ValueError(
                f"生成脚本参数不一致: ${name} 应为 {expected}，实际为 {actual!r}"
            )


def _manifest(project_main: str | Path) -> dict[str, Any]:
    path = Path(project_main).parent / "plan.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"生成项目缺少有效 plan.json: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"生成项目 plan.json 根结构无效: {path}")
    return payload


def validate_generated_project_consistency(
    project_main: str | Path,
    plan: RunPlan,
    options: EasyCon118Options | None = None,
    *,
    template_name: str | None = None,
) -> None:
    """Reject a generated normal project whose manifest/ECS values disagree."""
    options = options or EasyCon118Options()
    selected_template = _normalized_template_name(
        template_name,
        default=STANDARD_TEMPLATE_NAME,
    )
    manifest = _manifest(project_main)
    if manifest.get("template") != selected_template:
        raise ValueError(
            "生成脚本入口不一致: "
            f"应为 {selected_template}，实际为 {manifest.get('template')!r}"
        )
    manifest_plan = manifest.get("plan")
    if not isinstance(manifest_plan, dict):
        raise ValueError("生成项目 plan.json 缺少 plan")
    request = manifest_plan.get("request")
    target = manifest_plan.get("target")
    initial = manifest_plan.get("initial_seed")
    execution = manifest_plan.get("execution")
    if not all(isinstance(item, dict) for item in (request, target, initial, execution)):
        raise ValueError("生成项目 plan.json 的计划结构不完整")
    checks = (
        ("目标宝可梦", request.get("pokemon"), plan.request.pokemon),
        ("目标结果宝可梦", target.get("pokemon"), plan.target.pokemon),
        ("目标Seed", str(target.get("target_seed", "")).upper(), plan.target.target_seed.upper()),
        ("初始Seed", str(initial.get("seed", "")).upper(), plan.initial_seed.seed.upper()),
        ("Advance", initial.get("advances"), plan.initial_seed.advances),
        ("Seed模式", execution.get("seed_mode"), plan.seed_mode),
    )
    for label, actual, expected in checks:
        if actual != expected:
            raise ValueError(f"生成项目{label}不一致: 应为 {expected!r}，实际为 {actual!r}")
    runtime_overrides = manifest.get("runtime_overrides")
    expected_controller = (
        "FORMAL" if selected_template == STANDARD_TEMPLATE_NAME else "TIMELINE"
    )
    if not isinstance(runtime_overrides, dict) or runtime_overrides.get(
        "home_buffer_controller"
    ) != expected_controller:
        raise ValueError(
            "生成项目 HOME_BUFFER 控制器与脚本入口不一致: "
            f"应为 {expected_controller}"
        )
    _assert_configured_user_values(project_main, plan_to_user_values(plan, options))


def validate_generated_egg_project_consistency(
    project_main: str | Path,
    request: EggRunRequest,
    *,
    template_name: str | None = None,
) -> None:
    """Reject a generated egg project whose manifest/ECS values disagree."""
    selected_template = _normalized_template_name(
        template_name,
        default=EGG_TEMPLATE_NAME,
    )
    manifest = _manifest(project_main)
    if manifest.get("template") != selected_template:
        raise ValueError(
            "孵蛋生成脚本入口不一致: "
            f"应为 {selected_template}，实际为 {manifest.get('template')!r}"
        )
    manifest_request = manifest.get("egg_request")
    if not isinstance(manifest_request, dict):
        raise ValueError("孵蛋生成项目 plan.json 缺少 egg_request")
    expected_request = request.to_dict()
    for key in (
        "game", "seed_mode", "target_seed", "held_advances", "pickup_advances",
        "species_id", "compatibility", "parent_a_gender", "parent_b_gender",
        "parent_a_ivs", "parent_b_ivs", "seed_startup_scheme",
        "seed_calibration_scheme",
    ):
        actual = manifest_request.get(key)
        expected = expected_request.get(key)
        if key == "target_seed":
            actual = str(actual or "").upper()
            expected = str(expected or "").upper()
        elif key in {"parent_a_ivs", "parent_b_ivs"}:
            actual = tuple(actual) if isinstance(actual, (list, tuple)) else actual
            expected = tuple(expected) if isinstance(expected, (list, tuple)) else expected
        if actual != expected:
            raise ValueError(
                f"孵蛋生成项目{key}不一致: 应为 {expected!r}，实际为 {actual!r}"
            )
    expected_wait_mode = (
        "formal_wait" if selected_template == STANDARD_TEMPLATE_NAME else "legacy_timeline"
    )
    if manifest.get("egg_wait_mode") != expected_wait_mode:
        raise ValueError(
            "孵蛋生成项目等待模式与脚本入口不一致: "
            f"应为 {expected_wait_mode}，实际为 {manifest.get('egg_wait_mode')!r}"
        )
    _assert_configured_user_values(project_main, egg_request_to_user_values(request))


def _apply_seed_mode3_help_start_text(text: str) -> str:
    """Upgrade only mode 3: stereo/HELP/Start (controller X), without disabling it."""
    text = re.sub(r"(?m)^(#\s+3\s*=\s*)stereo_r_a\b", r"\1stereo_h_start", text)
    text = text.replace(
        "# Seed模式名称中的mono/stereo和h/r分别对应Sound与Button Mode。",
        "# 模式0-9均使用HELP；mono/stereo决定Sound，模式3为STEREO/HELP/START。",
    )
    for variable in ("游戏设置目标按键", "孵蛋库_目标按键"):
        text = re.sub(
            rf"(?m)^    IF \$Seed模式 == 3\r?\n"
            rf"        \${variable} = 1\r?\n    ENDIF\r?\n",
            "", text,
        )
    text = text.replace(
        "$Seed模式 == 0 or $Seed模式 == 1 or $Seed模式 == 3 or $Seed模式 == 4",
        "$Seed模式 == 0 or $Seed模式 == 1 or $Seed模式 == 4",
    )
    return text.replace(
        "$Seed模式 == 2 or $Seed模式 == 8 or $Seed模式 == 9",
        "$Seed模式 == 2 or $Seed模式 == 3 or $Seed模式 == 8 or $Seed模式 == 9",
    )


def _apply_seed_mode3_library_mapping(library_path: Path) -> None:
    original = library_path.read_text(encoding="utf-8")
    configured = _apply_seed_mode3_help_start_text(original)
    if configured != original:
        library_path.write_text(configured, encoding="utf-8")


_JAPANESE_NATURE_LABELS = (
    "勤奋", "怕寂寞", "勇敢", "固执", "顽皮", "大胆", "坦率", "悠闲",
    "淘气", "乐天", "胆小", "急躁", "认真", "爽朗", "内敛", "慢吞吞",
    "冷静", "害羞", "马虎", "温和", "温顺", "自大", "慎重", "浮躁", "天真",
)
_JAPANESE_STAT_LABELS = (
    ("HP", "实HP", "日版HP_", (18, 19, 20, 21)),
    ("ATK", "实ATK", "日版ATTACK_", tuple(range(8, 15))),
    ("DEF", "实DEF", "日版DEFENSE_", tuple(range(8, 15))),
    ("SPA", "实SPA", "日版SP_ATK_", tuple(range(9, 15))),
    ("SPD", "实SPD", "日版SP_DEF_", tuple(range(9, 15))),
    ("SPE", "实SPE", "日版SPEED_", tuple(range(8, 15))),
)
_JAPANESE_STARTER_MARKER = "# ===== 日版御三家临时识图分支 ====="
_JAPANESE_STARTER_GUARD_MARKER = "日版御三家临时模式10仅支持静态图鉴1/4/7"


def _render_japanese_starter_ocr_helper() -> str:
    """Render the main-script-only Japanese starter OCR helper."""
    lines = [
        _JAPANESE_STARTER_MARKER,
        "# 日版御三家临时分支；日版标签随1.1.8包提供，默认英文流程不调用。",
        "FUNC 读取并输出日版御三家识图结果(): INT",
        "    $性别识图失败 = 0",
        "    $性格识图失败 = 0",
        "    $LV识图失败 = 0",
        "    $HP识图失败 = 0",
        "    $ATK识图失败 = 0",
        "    $DEF识图失败 = 0",
        "    $SPA识图失败 = 0",
        "    $SPD识图失败 = 0",
        "    $SPE识图失败 = 0",
        "    $等级表直读 = 1",
        "    $等级标签识别 = 0",
        "    $候选数字命中项数 = 0",
        "    $候选数字回退项数 = 0",
        "    $候选数字标签次数 = 0",
        "    CALL 重置候选数字标签次数",
        "",
        "    IF $道具乱数模式 == 0 and @出闪 >= $识图阈值",
        "        PRINT 已识别到出闪，脚本停止",
        "        RETURN 0",
        "    ENDIF",
        "",
        "    $日版公图标分数 = @火红公图标",
        "    $日版母图标分数 = @火红母图标",
        "    IF $日版公图标分数 < $识图阈值 and $日版母图标分数 < $识图阈值",
        "        $识图性别 = -1",
        "        $性别识图失败 = 1",
        "        PRINT 日版性别识图失败，公母标签均低于阈值",
        "    ELIF $日版公图标分数 >= $日版母图标分数",
        "        $识图性别 = 0",
        "        $当前性别 = 0",
        "        PRINT ▶ 日版性别: ♂",
        "    ELSE",
        "        $识图性别 = 1",
        "        $当前性别 = 1",
        "        $检测到性别母 = 1",
        "        PRINT ▶ 日版性别: ♀",
        "    ENDIF",
        "",
        "    $识图性格 = -1",
    ]
    for index, label in enumerate(_JAPANESE_NATURE_LABELS):
        keyword = "IF" if index == 0 else "ELIF"
        lines.extend(
            (
                f"    {keyword} @性格日版{label} > $识图阈值",
                f"        $识图性格 = {index}",
            )
        )
    lines.extend(
        (
            "    ELSE",
            "        $性格识图失败 = 1",
            "        PRINT 日版性格识图失败，日版性格标签均低于阈值",
            "    ENDIF",
            "    $当前性格 = $识图性格",
            "",
            "    $等级 = 5",
            "    RIGHT",
            "    1000",
            "",
        )
    )
    for stat_name, target_name, prefix, values in _JAPANESE_STAT_LABELS:
        lines.append(f"    ${target_name} = -1")
        for index, value in enumerate(values):
            keyword = "IF" if index == 0 else "ELIF"
            lines.extend(
                (
                    f"    {keyword} @{prefix}{value:02d} > $识图阈值",
                    f"        ${target_name} = {value}",
                )
            )
        lines.extend(
            (
                "    ELSE",
                f"        ${stat_name}识图失败 = 1",
                f"        PRINT 日版{stat_name}识图失败，标签均低于阈值",
                "    ENDIF",
                "",
            )
        )
    lines.extend(
        (
            "    $识图性别文本 = 性别文本($识图性别)",
            "    $识图性格文本 = 性格文本($识图性格)",
            "    PRINT \"\"",
            "    PRINT 【日版御三家识图】",
            "    PRINT 个体: & $识图性格文本 & \"，\" & $识图性别文本 & \"，LV\" & $等级",
            "    PRINT 能力: HP & $实HP & \" ATK \" & $实ATK & \" DEF \" & $实DEF & \" SPA \" & $实SPA & \" SPD \" & $实SPD & \" SPE \" & $实SPE",
            "",
            "    IF $性别识图失败 == 1",
            "        RETURN 0",
            "    ENDIF",
            "    IF $性格识图失败 == 1",
            "        RETURN 0",
            "    ENDIF",
        )
    )
    for stat_name, _, _, _ in _JAPANESE_STAT_LABELS:
        lines.extend(
            (
                f"    IF ${stat_name}识图失败 == 1",
                "        RETURN 0",
                "    ENDIF",
            )
        )
    lines.extend(("", "    RETURN 1", "ENDFUNC", ""))
    return "\n".join(lines)


def _apply_japanese_starter_guard_text(text: str) -> str:
    """Restrict mode 10 to the static starter encounters it can recognize."""
    if _JAPANESE_STARTER_GUARD_MARKER in text:
        return text
    anchor = "FUNC 检查运行参数(): INT\n"
    if text.count(anchor) != 1:
        raise ValueError("1.1.8 主脚本缺少唯一的运行参数检查入口")
    guard = (
        "    IF $Seed模式 == 10\n"
        "        IF $遭遇类型 != 1 or ($目标全国图鉴编号 != 1 and $目标全国图鉴编号 != 4 and $目标全国图鉴编号 != 7)\n"
        "            PRINT 日版御三家临时模式10仅支持静态图鉴1/4/7\n"
        "            RETURN 0\n"
        "        ENDIF\n"
        "    ENDIF\n\n"
    )
    return text.replace(anchor, anchor + guard, 1)


def _apply_japanese_starter_runtime_text(text: str) -> str:
    """Inject Japanese starter recognition into one generated main script."""
    text = _apply_japanese_starter_guard_text(text)
    if _JAPANESE_STARTER_MARKER in text:
        return text
    anchor = "FUNC 读取并输出识图结果(): INT\n"
    if text.count(anchor) != 1:
        raise ValueError("1.1.8 主脚本缺少唯一的识图结果入口")
    branch = (
        "    IF $Seed模式 == 10\n"
        "        RETURN 读取并输出日版御三家识图结果()\n"
        "    ENDIF\n"
    )
    configured = text.replace(anchor, anchor + branch, 1)
    configured = configured.replace(
        "#   9 = mono_h_start_blackout_l",
        "#   9 = mono_h_start_blackout_l\n#   10 = japanese_mono_h_a（临时日版御三家，仅MONO/HELP/A）",
        1,
    )
    configured = configured.replace(
        "# 模式0-9均使用HELP；mono/stereo决定Sound，模式3为STEREO/HELP/START。",
        "# 模式0-9均使用HELP；模式3为STEREO/HELP/START；模式10为日版MONO/HELP/A。",
    )
    configured = re.sub(
        r"(?m)^    IF \$Seed模式 == 0 or \$Seed模式 == 1 or \$Seed模式 == 4 or \$Seed模式 == 5 or \$Seed模式 == 6 or  \$Seed模式 == 7$",
        "    IF $Seed模式 == 0 or $Seed模式 == 1 or $Seed模式 == 4 or $Seed模式 == 5 or $Seed模式 == 6 or  $Seed模式 == 7 or $Seed模式 == 10",
        configured,
        count=1,
    )
    configured = re.sub(
        r"(?m)^    ELIF \$Seed模式 < 0 or \$Seed模式 > 9$",
        "    ELIF $Seed模式 < 0 or $Seed模式 > 10",
        configured,
        count=1,
    )
    return configured + "\n" + _render_japanese_starter_ocr_helper()


def _japanese_seed_values(game: str) -> tuple[str, ...]:
    filename = "fr_jpn_nx.bin" if game == "fr" else "lg_jpn_nx.bin"
    path = RESOURCE_ROOT / "rng" / "resources" / filename
    if not path.is_file():
        raise FileNotFoundError(f"缺少日版御三家 Seed 资源: {path}")
    table = decode_nx_seed_binary(path.read_bytes())
    values = table.modes.get("mono_h_a")
    if values is None:
        raise ValueError(f"日版 Seed 表缺少 mono_h_a: {filename}")
    return tuple("" if value is None else f"{value:04X}" for value in values)


def _apply_japanese_seed_mode10(library_path: Path, game_cn: str, game: str) -> str:
    """Add temporary mode 10 to a copied ECS table, leaving source cache intact."""
    original = library_path.read_text(encoding="utf-8-sig")
    if re.search(r"(?m)^# mode 10 = japanese_mono_h_a$", original):
        return original
    values = _japanese_seed_values(game)
    max_index = re.search(rf"(?m)^FUNC 取Seed最大索引_{re.escape(game_cn)}\(\): INT\n    RETURN (\d+)$", original)
    if max_index is None or int(max_index.group(1)) != len(values) - 1:
        raise ValueError(f"{game_cn}日版 Seed 表长度与 1.1.8 时间表不一致")
    rendered = ",".join('""' if value == "" else f'"{value}"' for value in values)
    function_anchor = f"\nFUNC 取SeedHEX_{game_cn}($idx: INT, $mode: INT): STRING\n"
    if original.count(function_anchor) != 1:
        raise ValueError(f"{game_cn} Seed 表缺少唯一的取SeedHEX入口")
    array = (
        f"\n# mode 10 = japanese_mono_h_a（临时日版御三家）\n"
        f"$Seed_HEX_{game_cn}_m10 = [{rendered}]\n"
    )
    configured = original.replace(function_anchor, array + function_anchor, 1)
    mode_anchor = f"    ELIF $mode == 9\n        RETURN $Seed_HEX_{game_cn}_m9[$idx]"
    if configured.count(mode_anchor) != 1:
        raise ValueError(f"{game_cn} Seed 表缺少模式9入口")
    configured = configured.replace(
        mode_anchor,
        mode_anchor + f"\n    ELIF $mode == 10\n        RETURN $Seed_HEX_{game_cn}_m10[$idx]",
        1,
    )
    return configured


def configure_egg_template_text(template_text: str, request: EggRunRequest) -> str:
    """Configure the 1.6.4a-only experimental same-seed egg entry."""
    configured = _configure_user_values(
        template_text,
        egg_request_to_user_values(request),
        optional_names={"Seed校准方案"},
    )
    availability = build_egg_held_availability(request)
    availability_values = egg_held_availability_to_ecs_values(availability)
    missing_fields = tuple(
        name
        for name in availability_values
        if len(
            re.findall(
                rf"(?m)^\s*\${re.escape(name)}\s*=\s*[^\r\n]*$",
                configured,
            )
        )
        != 1
    )
    if missing_fields:
        raise ValueError(
            "当前1.1.8孵蛋模板未包含Held无蛋区间字段，通常是local_assets仍为旧缓存。"
            "请重新运行安装脚本刷新1.1.8缓存，或在GUI选择更新后的1.1.8包。"
            "缺少字段：" + "、".join(f"${name}" for name in missing_fields)
        )
    configured = _configure_all_values(
        configured,
        availability_values,
    )
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
    """Preserve the current cross-method policy and upgrade raw legacy templates."""
    if EGG_REVERSE_LOOKUP_POLICY_MARKER in template_text:
        return _apply_egg_reverse_lookup_window_text(template_text)
    if EGG_REVERSE_LOOKUP_LEGACY_POLICY_MARKER in template_text:
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


def _apply_seed_hold_observation_window_text(template_text: str) -> str:
    """Install the shared five-consecutive-miss Seed scheme-1 controller."""
    configured = template_text
    if SEED_HOLD_OBSERVATION_OLD_GLOBAL in configured:
        if configured.count(SEED_HOLD_OBSERVATION_OLD_GLOBAL) != 1:
            raise ValueError("主脚本Seed命中保持样本数不唯一，拒绝升级连续未命中窗口")
        configured = configured.replace(
            SEED_HOLD_OBSERVATION_OLD_GLOBAL,
            SEED_HOLD_OBSERVATION_GLOBAL_ANCHOR,
            1,
        )
    elif configured.count(SEED_HOLD_OBSERVATION_GLOBAL_ANCHOR) != 1:
        raise ValueError("主脚本缺少唯一的Seed命中保持样本数，拒绝升级连续未命中窗口")

    if SEED_HOLD_OBSERVATION_MIN_GLOBAL not in configured:
        if configured.count(SEED_HOLD_OBSERVATION_GLOBAL_ANCHOR) != 1:
            raise ValueError("主脚本缺少唯一的Seed命中保持样本数，拒绝升级观察窗口")
        configured = configured.replace(
            SEED_HOLD_OBSERVATION_GLOBAL_ANCHOR,
            SEED_HOLD_OBSERVATION_GLOBAL_ANCHOR
            + "\n"
            + SEED_HOLD_OBSERVATION_MIN_GLOBAL,
            1,
        )

    if configured.count(SEED_HOLD_OBSERVATION_FUNCTION) != 1:
        raise ValueError("主脚本缺少唯一的Seed锁定修正函数，拒绝升级观察窗口")
    start = configured.index(SEED_HOLD_OBSERVATION_FUNCTION)
    end = configured.index("ENDFUNC", start) + len("ENDFUNC")
    override_text = SEED_LOCK_CONTROLLER_OVERRIDE_PATH.read_text(encoding="utf-8")
    override_start = override_text.index(SEED_HOLD_OBSERVATION_FUNCTION)
    replacement = override_text[override_start:].rstrip()
    if SEED_HOLD_OBSERVATION_DIRECT_HALF_MARKER not in replacement:
        raise ValueError("Seed锁定覆盖缺少连续5次未命中固定半步标记")
    return configured[:start] + replacement + configured[end:]


def _apply_egg_formal_parity_runtime_override_text(
    template_text: str,
    override_text: str,
) -> str:
    """Apply formal Held parity, then schedule Pickup's optional 7-advance menu."""
    configured = template_text
    required_globals = tuple(
        line for line in EGG_FORMAL_PARITY_GLOBALS.splitlines() if line
    )
    missing_globals = tuple(line for line in required_globals if line not in configured)
    if missing_globals:
        if configured.count(EGG_FORMAL_PARITY_GLOBAL_ANCHOR) != 1:
            raise ValueError("孵蛋模板缺少唯一的Held请求全局变量，拒绝应用奇偶校准")
        configured = configured.replace(
            EGG_FORMAL_PARITY_GLOBAL_ANCHOR,
            EGG_FORMAL_PARITY_GLOBAL_ANCHOR + "\n" + "\n".join(missing_globals),
            1,
        )

    if EGG_FORMAL_PARITY_OVERRIDE_MARKER in configured:
        start = configured.index(EGG_FORMAL_PARITY_OVERRIDE_MARKER)
    else:
        if configured.count(EGG_FORMAL_PARITY_ORIGINAL_FUNCTION) != 1:
            raise ValueError("孵蛋模板缺少唯一的两次命中时间计算函数，拒绝应用奇偶校准")
        start = configured.index(EGG_FORMAL_PARITY_ORIGINAL_FUNCTION)
    if configured.count(EGG_FORMAL_PARITY_NEXT_FUNCTION) != 1:
        raise ValueError("孵蛋模板缺少Seed预校准后继函数，拒绝应用奇偶校准")
    end = configured.index(EGG_FORMAL_PARITY_NEXT_FUNCTION, start)
    configured = configured[:start] + override_text.rstrip() + "\n\n" + configured[end:]

    uses_explicit_wait_mode = (
        EGG_FORMAL_WAIT_MARKER in configured
        or EGG_FORMAL_PARITY_REAL_CALL_WAIT_MODE in configured
    )
    desired_call = (
        EGG_FORMAL_PARITY_REAL_CALL_WAIT_MODE
        if uses_explicit_wait_mode
        else EGG_FORMAL_PARITY_REAL_CALL_CURRENT
    )
    if desired_call not in configured:
        if uses_explicit_wait_mode and configured.count(EGG_FORMAL_PARITY_REAL_CALL_CURRENT) == 1:
            configured = configured.replace(
                EGG_FORMAL_PARITY_REAL_CALL_CURRENT,
                desired_call,
                1,
            )
        elif configured.count(EGG_FORMAL_PARITY_REAL_CALL_PRE_MENU) == 1:
            configured = configured.replace(
                EGG_FORMAL_PARITY_REAL_CALL_PRE_MENU,
                desired_call,
                1,
            )
        elif configured.count(EGG_FORMAL_PARITY_REAL_CALL_OLD) == 1:
            configured = configured.replace(
                EGG_FORMAL_PARITY_REAL_CALL_OLD,
                desired_call,
                1,
            )
        else:
            raise ValueError("孵蛋模板缺少唯一的生成领取执行调用，拒绝应用奇偶校准")
    return configured


def _apply_egg_pickup_parity_menu_text(library_text: str) -> str:
    """Flip only the Pickup timing phase with the measured 7-advance menu action."""
    if library_text.count(EGG_PICKUP_PARITY_ORIGINAL_FUNCTION) != 1:
        raise ValueError("孵蛋流程库缺少唯一的同Seed两次命中函数，拒绝应用Pickup奇偶菜单")
    start = library_text.index(EGG_PICKUP_PARITY_ORIGINAL_FUNCTION)
    end = library_text.index("ENDFUNC", start) + len("ENDFUNC")
    section = library_text[start:end]
    if EGG_PICKUP_PARITY_MENU_MARKER in section:
        return library_text

    uses_explicit_wait_mode = EGG_PICKUP_PARITY_SIGNATURE_WAIT_MODE in section
    if EGG_PICKUP_PARITY_SIGNATURE_OLD in section:
        section = section.replace(
            EGG_PICKUP_PARITY_SIGNATURE_OLD,
            EGG_PICKUP_PARITY_SIGNATURE_CURRENT,
            1,
        )
    elif (
        EGG_PICKUP_PARITY_SIGNATURE_CURRENT not in section
        and not uses_explicit_wait_mode
    ):
        raise ValueError("孵蛋流程库的同Seed两次命中参数签名不受支持")

    if EGG_PICKUP_PARITY_VALIDATION_OLD in section:
        section = section.replace(
            EGG_PICKUP_PARITY_VALIDATION_OLD,
            EGG_PICKUP_PARITY_VALIDATION_CURRENT,
            1,
        )
    elif EGG_PICKUP_PARITY_VALIDATION_CURRENT not in section:
        wait_mode_validation = (
            "IF $使用绝对时间轴 != 0 and $使用绝对时间轴 != 1" in section
            and "孵蛋测试_启动并进入存档($Seed模式, $Seed等待MS, $精确尾段MS, $奇偶等待MS, $封面长按MS, $Seed启动方案, $使用绝对时间轴)" in section
        )
        if not wait_mode_validation:
            raise ValueError("孵蛋流程库缺少Pickup菜单奇偶开关校验位置")

    if EGG_PICKUP_PARITY_ACTION_OLD in section:
        section = section.replace(
            EGG_PICKUP_PARITY_ACTION_OLD,
            EGG_PICKUP_PARITY_ACTION_CURRENT,
            1,
        )
    elif EGG_PICKUP_PARITY_ACTION_UNMARKED in section:
        section = section.replace(
            EGG_PICKUP_PARITY_ACTION_UNMARKED,
            EGG_PICKUP_PARITY_ACTION_CURRENT,
            1,
        )
    else:
        raise ValueError("孵蛋流程库缺少确认出蛋后的Pickup菜单插入位置")
    return library_text[:start] + section + library_text[end:]


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


def _apply_egg_post_pickup_retry_policy_text(template_text: str) -> str:
    """Keep the completed no-egg Seed pre-calibration across pickup retries."""
    if EGG_POST_PICKUP_RETRY_POLICY_MARKER in template_text:
        return template_text

    configured = template_text
    if EGG_POST_PICKUP_MISS_OLD in configured:
        configured = configured.replace(
            EGG_POST_PICKUP_MISS_OLD,
            EGG_POST_PICKUP_MISS_CURRENT,
            1,
        )
    elif EGG_POST_PICKUP_MISS_CURRENT not in configured:
        raise ValueError("孵蛋模板缺少领取后Seed未命中分支，拒绝应用直接重试策略")

    if EGG_POST_PICKUP_FAILURE_OLD in configured:
        configured = configured.replace(
            EGG_POST_PICKUP_FAILURE_OLD,
            EGG_POST_PICKUP_FAILURE_CURRENT,
            1,
        )
    elif EGG_POST_PICKUP_FAILURE_CURRENT not in configured:
        raise ValueError("孵蛋模板缺少领取后Seed反查失败分支，拒绝应用直接重试策略")

    return configured.replace(
        EGG_POST_PICKUP_MISS_CURRENT,
        f"    {EGG_POST_PICKUP_RETRY_POLICY_MARKER}\n"
        + EGG_POST_PICKUP_MISS_CURRENT,
        1,
    )


def _apply_egg_no_egg_evidence_policy_text(template_text: str) -> str:
    """Retain target-Seed no-egg evidence while the Held request is unchanged."""
    if EGG_NO_EGG_EVIDENCE_OVERRIDE_MARKER in template_text:
        return template_text

    configured = template_text
    if EGG_NO_EGG_REQUEST_CHANGE_OLD in configured:
        configured = configured.replace(
            EGG_NO_EGG_REQUEST_CHANGE_OLD,
            EGG_NO_EGG_REQUEST_CHANGE_CURRENT,
            1,
        )
    elif EGG_NO_EGG_REQUEST_CHANGE_FIXED_UNMARKED in configured:
        configured = configured.replace(
            EGG_NO_EGG_REQUEST_CHANGE_FIXED_UNMARKED,
            EGG_NO_EGG_REQUEST_CHANGE_CURRENT,
            1,
        )
    else:
        raise ValueError("孵蛋模板缺少Held请求变化分支，拒绝应用无蛋证据策略")

    if EGG_NO_EGG_NON_TARGET_OLD in configured:
        configured = configured.replace(
            EGG_NO_EGG_NON_TARGET_OLD,
            EGG_NO_EGG_NON_TARGET_CURRENT,
            1,
        )
    elif EGG_NO_EGG_NON_TARGET_CURRENT not in configured:
        raise ValueError("孵蛋模板缺少无蛋后的非目标Seed分支，拒绝应用无蛋证据策略")
    return configured


def _apply_egg_no_egg_seed_gate_text(template_text: str) -> str:
    """Check Seed on every no-egg round after the first Held calibration."""
    old_count = template_text.count(EGG_NO_EGG_SEED_GATE_OLD)
    current_count = template_text.count(EGG_NO_EGG_SEED_GATE_CURRENT)
    if old_count == 1 and current_count == 0:
        configured = template_text.replace(
            EGG_NO_EGG_SEED_GATE_OLD, EGG_NO_EGG_SEED_GATE_CURRENT, 1
        )
    elif old_count == 0 and current_count == 1:
        configured = template_text
    else:
        raise ValueError("孵蛋模板缺少唯一的无蛋Seed复核门槛，拒绝应用Held校准后立即复核策略")
    return configured.replace(
        "# 普通阶段累计无蛋后才复核Seed；微调阶段第一次无蛋就复核。",
        "# 首次Held反查校准前才使用连续无蛋门槛；有校准记录后无蛋立即复核Seed，不要求Pickup稳定。",
    )


def _apply_egg_wild_seed_fallback_text(template_text: str) -> str:
    """Add one fallback only to egg-flow wild verification, keeping its lower bound."""
    signature = "FUNC 孵蛋流程_验证野生Seed($队伍位置: INT): INT"
    if template_text.count(signature) != 1:
        raise ValueError("孵蛋模板缺少唯一的野生Seed反查函数")
    start = template_text.index(signature)
    end = template_text.index("ENDFUNC", start) + len("ENDFUNC")
    section = template_text[start:end]
    old_count = section.count(EGG_WILD_SEED_SCAN_OLD)
    current_count = section.count(EGG_WILD_SEED_SCAN_CURRENT)
    if old_count == 1 and current_count == 0 and section.count("    FOR\n") == 1:
        section = section.replace(EGG_WILD_SEED_SCAN_OLD, EGG_WILD_SEED_SCAN_CURRENT, 1)
        section = section.replace("    FOR\n", EGG_WILD_SEED_WINDOW_INIT + "    FOR\n", 1)
    elif old_count != 0 or current_count != 1:
        raise ValueError("孵蛋野生Seed反查缺少唯一的扫描分支，拒绝应用兜底扩窗")
    if (section.count(EGG_WILD_SEED_WINDOW_INIT) != 1
            or section.index(EGG_WILD_SEED_WINDOW_INIT) > section.index("    FOR\n")):
        raise ValueError("孵蛋野生Seed反查窗口必须在吃糖循环前初始化")
    return template_text[:start] + section + template_text[end:]


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
    """Use the Togepi-only 14-step bicycle cycle for the static gift."""
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
    replacement = (
        override_text.rstrip() + "\n\n"
        + HOME_BUFFER_RECOVERY_PATH.read_text(encoding="utf-8").rstrip() + "\n\n"
    )
    return template_text[:start] + replacement + template_text[end:]


def _apply_home_buffer_adaptive_classifier_text(
    template_text: str,
    classifier_text: str,
    enabled: bool,
) -> str:
    """Install the shared classifier and set its opt-in switch."""
    global_anchor = "$HOME_BUFFER当前错误退出_NS2 = 0\n"
    missing_globals = []
    for line in HOME_BUFFER_ADAPTIVE_GLOBALS.splitlines():
        if not line:
            continue
        if line.startswith(f"${HOME_BUFFER_ADAPTIVE_SWITCH} ="):
            if not re.search(
                rf"(?m)^\${re.escape(HOME_BUFFER_ADAPTIVE_SWITCH)}\s*=",
                template_text,
            ):
                missing_globals.append(line)
        elif not re.search(rf"(?m)^{re.escape(line)}\r?$", template_text):
            missing_globals.append(line)
    if missing_globals:
        if template_text.count(global_anchor) != 1:
            raise ValueError("模板缺少唯一的 HOME_BUFFER 状态区，拒绝应用稳定低分自适应")
        template_text = template_text.replace(
            global_anchor,
            global_anchor + "\n".join(missing_globals) + "\n",
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
    missing_globals = [
        line
        for line in EGG_HOME_BUFFER_GLOBALS.splitlines()
        if line and not re.search(rf"(?m)^{re.escape(line)}\r?$", template_text)
    ]
    if missing_globals:
        if template_text.count(global_anchor) != 1:
            raise ValueError("孵蛋模板缺少唯一的 HOME_BUFFER 状态区，拒绝应用窗口搜索覆盖")
        template_text = template_text.replace(
            global_anchor,
            global_anchor + "\n".join(missing_globals) + "\n",
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
    replacement = (
        override_text.rstrip() + "\n\n"
        + HOME_BUFFER_RECOVERY_PATH.read_text(encoding="utf-8").rstrip() + "\n\n"
    )
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
    configured = _apply_egg_pickup_parity_menu_text(configured)
    configured = _apply_egg_pond_settle_delay_text(configured)
    configured = _apply_seed_mode3_help_start_text(configured)
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
        "egg_pickup_parity_menu_sha256": hashlib.sha256(
            (
                EGG_PICKUP_PARITY_SIGNATURE_CURRENT
                + EGG_PICKUP_PARITY_VALIDATION_CURRENT
                + EGG_PICKUP_PARITY_ACTION_CURRENT
            ).encode("utf-8")
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
    standard_configured = _apply_seed_hold_observation_window_text(
        standard_configured
    )
    standard_configured = _apply_seed_mode3_help_start_text(standard_configured)
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
    configured = _apply_seed_hold_observation_window_text(configured)
    configured = _apply_egg_seed_controller_runtime_override_text(
        configured,
        EGG_SEED_CONTROLLER_OVERRIDE_PATH.read_text(encoding="utf-8"),
    )
    configured = _apply_egg_formal_parity_runtime_override_text(
        configured,
        EGG_FORMAL_PARITY_OVERRIDE_PATH.read_text(encoding="utf-8"),
    )
    configured = _apply_egg_transient_retry_runtime_override_text(configured)
    configured = _apply_egg_post_pickup_retry_policy_text(configured)
    configured = _apply_egg_no_egg_evidence_policy_text(configured)
    configured = _apply_egg_no_egg_seed_gate_text(configured)
    configured = _apply_egg_wild_seed_fallback_text(configured)
    configured = _apply_egg_terminal_stop_policy_text(configured)
    configured = _apply_seed_mode3_help_start_text(configured)
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
    upgrade_easycon_seed_mode3_tables(source_dir / "lib")
    apply_seed_common_regions(source_dir)
    return inspect_script_corpus(source_dir)


def write_configured_project(
    source_dir: str | Path,
    output_dir: str | Path,
    plan: RunPlan,
    options: EasyCon118Options | None = None,
    *,
    copy_assets: bool = True,
    template_name: str | None = None,
    precalibration_store_path: str | Path | None = None,
) -> Path:
    """Create an EasyCon CLI project with ``main.ecs``, ``lib`` and labels."""
    options = options or EasyCon118Options()
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
    selected_template = _normalized_template_name(
        template_name,
        default=STANDARD_TEMPLATE_NAME,
    )
    template_path = source_dir / selected_template
    if not template_path.is_file():
        raise FileNotFoundError(f"1.1.8 包缺少所选入口: {template_path}")
    store_path = _precalibration_store_path(precalibration_store_path)
    options, precalibration = _load_plan_precalibration(
        plan,
        options,
        selected_template,
        store_path,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    configured = configure_template_text(
        template_path.read_text(encoding="utf-8"),
        plan,
        options,
    )
    # The two audited entries share the rest of the generator, but their
    # HOME_BUFFER controllers are intentionally different.  Applying the
    # formal controller to the timeline entry leaves the timeline marker in
    # place while replacing its implementation, which is exactly the stale
    # mixed-controller state that makes direct timeline runs unreliable.
    if selected_template == STANDARD_TEMPLATE_NAME:
        configured = _apply_standard_home_buffer_runtime_override_text(
            configured,
            STANDARD_HOME_BUFFER_OVERRIDE_PATH.read_text(encoding="utf-8"),
        )
        home_buffer_controller = "FORMAL"
    else:
        configured = _apply_egg_home_buffer_runtime_override_text(
            configured,
            EGG_HOME_BUFFER_OVERRIDE_PATH.read_text(encoding="utf-8"),
        )
        home_buffer_controller = "TIMELINE"
    classifier_text = HOME_BUFFER_ADAPTIVE_CLASSIFIER_PATH.read_text(
        encoding="utf-8"
    )
    configured = _apply_home_buffer_adaptive_classifier_text(
        configured,
        classifier_text,
        options.home_buffer_adaptive_threshold,
    )
    configured = _apply_seed_hold_observation_window_text(configured)
    if options.japanese_starter:
        configured = _apply_japanese_starter_runtime_text(configured)
    if precalibration["enabled"]:
        configured = _apply_regular_precalibration_runtime_text(
            configured,
            options,
            precalibration,
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

    apply_seed_common_regions(output_dir, ("main.ecs",))
    seed_table_override = apply_easycon_seed_table_overrides(output_dir / "lib")
    if options.japanese_starter:
        japanese_tables = {}
        for game_cn, game in (("火红", "fr"), ("叶绿", "lg")):
            library_path = output_dir / "lib" / (
                "02_Seed表_火红_NX.ecs" if game == "fr" else "03_Seed表_叶绿_NX.ecs"
            )
            configured_table = _apply_japanese_seed_mode10(library_path, game_cn, game)
            library_path.write_text(configured_table, encoding="utf-8")
            japanese_tables[game] = {
                "mode": 10,
                "source": "bundled " + ("fr_jpn_nx.bin" if game == "fr" else "lg_jpn_nx.bin"),
                "sha256": hashlib.sha256(configured_table.encode("utf-8")).hexdigest(),
            }
        if seed_table_override is None:
            seed_table_override = {}
        seed_table_override["temporary_japanese_mode10"] = japanese_tables
    _apply_seed_mode3_library_mapping(output_dir / "lib" / EGG_SETTINGS_LIBRARY_NAME)
    ocr_fallback_sha256 = apply_ocr_runtime_fallback(
        output_dir / "lib" / OCR_NAME_LIBRARY_NAME
    )

    manifest = {
        "source": str(source_dir.resolve()),
        "template": template_path.name,
        "plan": plan.to_dict(),
        "easycon118_options": asdict(options),
        "precalibration": precalibration,
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
            "home_buffer_controller": home_buffer_controller,
            "ocr_unavailable_fallback_sha256": ocr_fallback_sha256,
            "wild_pid_retry_limit_sha256": wild_pid_retry_limit_sha256,
            "home_buffer_adaptive_classifier_sha256": hashlib.sha256(
                classifier_text.encode("utf-8")
            ).hexdigest(),
            "home_buffer_recovery_sha256": hashlib.sha256(
                HOME_BUFFER_RECOVERY_PATH.read_bytes()
            ).hexdigest(),
            "seed_hold_observation_window_sha256": hashlib.sha256(
                (
                    SEED_HOLD_OBSERVATION_MIN_GLOBAL
                    + SEED_HOLD_OBSERVATION_CURRENT_BRANCH
                    + SEED_HOLD_OBSERVATION_CURRENT_DECISION
                ).encode("utf-8")
            ).hexdigest(),
            "seed_tables": seed_table_override,
            "temporary_japanese_starter": options.japanese_starter,
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


def _select_egg_template_path(source_dir: Path) -> Path:
    """Prefer the promoted formal WAIT entry and retain old-cache compatibility."""
    formal_path = source_dir / STANDARD_TEMPLATE_NAME
    if formal_path.is_file() and EGG_FORMAL_WAIT_MARKER in formal_path.read_text(
        encoding="utf-8"
    ):
        return formal_path
    return source_dir / EGG_TEMPLATE_NAME


def write_configured_egg_project(
    source_dir: str | Path,
    output_dir: str | Path,
    request: EggRunRequest,
    *,
    copy_assets: bool = True,
    template_name: str | None = None,
    precalibration_store_path: str | Path | None = None,
) -> Path:
    """Create a configured project for the experimental same-seed egg flow."""
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
    default_template = _select_egg_template_path(source_dir).name
    selected_template = _normalized_template_name(
        template_name,
        default=default_template,
    )
    template_path = source_dir / selected_template
    if not template_path.is_file():
        raise FileNotFoundError(f"1.1.8 包缺少所选入口: {template_path}")
    store_path = _precalibration_store_path(precalibration_store_path)
    request, precalibration = _load_egg_precalibration(
        request,
        selected_template,
        store_path,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    configured = configure_egg_template_text(
        template_path.read_text(encoding="utf-8"), request
    )
    if EGG_FORMAL_WAIT_MARKER in configured:
        if "$孵蛋使用绝对时间轴 = 0" not in configured:
            raise ValueError("孵蛋正式模板没有固定选择普通WAIT模式")
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
    configured = _apply_seed_hold_observation_window_text(configured)
    seed_controller_override_text = EGG_SEED_CONTROLLER_OVERRIDE_PATH.read_text(
        encoding="utf-8"
    )
    configured = _apply_egg_seed_controller_runtime_override_text(
        configured,
        seed_controller_override_text,
    )
    formal_parity_override_text = EGG_FORMAL_PARITY_OVERRIDE_PATH.read_text(
        encoding="utf-8"
    )
    configured = _apply_egg_formal_parity_runtime_override_text(
        configured,
        formal_parity_override_text,
    )
    configured = _apply_egg_transient_retry_runtime_override_text(configured)
    configured = _apply_egg_post_pickup_retry_policy_text(configured)
    configured = _apply_egg_no_egg_evidence_policy_text(configured)
    configured = _apply_egg_no_egg_seed_gate_text(configured)
    configured = _apply_egg_wild_seed_fallback_text(configured)
    configured = _apply_egg_terminal_stop_policy_text(configured)
    if precalibration["enabled"]:
        configured = _apply_egg_precalibration_runtime_text(
            configured,
            request,
            precalibration,
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

    apply_seed_common_regions(output_dir, ("main.ecs",))
    seed_table_override = apply_easycon_seed_table_overrides(output_dir / "lib")
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
    runtime_overrides["home_buffer_recovery_sha256"] = hashlib.sha256(
        HOME_BUFFER_RECOVERY_PATH.read_bytes()
    ).hexdigest()
    runtime_overrides["egg_party_slot_main_sha256"] = hashlib.sha256(
        party_slot_main_override_text.encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_seed_controller_sha256"] = hashlib.sha256(
        seed_controller_override_text.encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_cross_method_confirmation_sha256"] = hashlib.sha256(
        (
            EGG_REVERSE_LOOKUP_POLICY_MARKER
            + "$孵蛋流程跨方法候选总数"
            + "$孵蛋流程候选参考Held帧"
            + "$孵蛋流程无蛋跳出估计落点"
            + "$孵蛋流程无蛋预测Held帧 = $孵蛋流程无蛋跳出最佳预测落点"
            + "$孵蛋流程无蛋跳出候选预测落点 % 2"
        ).encode("utf-8")
    ).hexdigest()
    runtime_overrides["seed_hold_observation_window_sha256"] = hashlib.sha256(
        (
            SEED_HOLD_OBSERVATION_GLOBAL_ANCHOR
            + SEED_HOLD_OBSERVATION_MIN_GLOBAL
            + SEED_LOCK_CONTROLLER_OVERRIDE_PATH.read_text(encoding="utf-8")
        ).encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_formal_parity_main_sha256"] = hashlib.sha256(
        formal_parity_override_text.encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_transient_retry_main_sha256"] = hashlib.sha256(
        "\n".join(
            replacement
            for _, replacement in EGG_TRANSIENT_RETRY_REPLACEMENTS
        ).encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_post_pickup_retry_policy_sha256"] = hashlib.sha256(
        (
            EGG_POST_PICKUP_MISS_CURRENT
            + EGG_POST_PICKUP_FAILURE_CURRENT
        ).encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_no_egg_evidence_policy_sha256"] = hashlib.sha256(
        (
            EGG_NO_EGG_REQUEST_CHANGE_CURRENT
            + EGG_NO_EGG_NON_TARGET_CURRENT
        ).encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_terminal_stop_policy_sha256"] = hashlib.sha256(
        "\n".join(
            replacement
            for _, replacement in EGG_TERMINAL_STOP_REPLACEMENTS
        ).encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_no_egg_seed_gate_sha256"] = hashlib.sha256(
        EGG_NO_EGG_SEED_GATE_CURRENT.encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_wild_seed_fallback_sha256"] = hashlib.sha256(
        (EGG_WILD_SEED_WINDOW_INIT + EGG_WILD_SEED_SCAN_CURRENT).encode("utf-8")
    ).hexdigest()
    runtime_overrides["egg_prepared_254_start_sha256"] = hashlib.sha256(
        _egg_prepared_254_override_text(request.start_from_prepared_254).encode(
            "utf-8"
        )
    ).hexdigest()
    runtime_overrides["wild_pid_retry_limit_sha256"] = wild_pid_retry_limit_sha256
    runtime_overrides["seed_tables"] = seed_table_override
    manifest = {
        "source": str(source_dir),
        "template": template_path.name,
        "egg_request": request.to_dict(),
        "precalibration": precalibration,
        "experimental": True,
        "egg_wait_mode": (
            "formal_wait"
            if EGG_FORMAL_WAIT_MARKER in configured
            else "legacy_timeline"
        ),
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
    *,
    fingerprint_warning_only: bool = False,
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
                record_fingerprint_mismatch(
                    "EasyCon 1.6.4a ezcon.exe 指纹不一致: " + ezcon_sha256,
                    warning_only=fingerprint_warning_only,
                    errors=errors,
                    warnings=warnings,
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
            override_check = validate_project_overrides(
                label_dir,
                EXPECTED_LABEL_SHA256,
                fingerprint_warning_only=fingerprint_warning_only,
            )
            if override_check.recognized:
                errors.extend(override_check.errors)
                warnings.extend(override_check.warnings)
            elif corpus["sha256"] != EXPECTED_LABEL_SHA256:
                record_fingerprint_mismatch(
                    "1.1.8 标签指纹不一致，可能不是已审计的完整标签包: "
                    + corpus["sha256"],
                    warning_only=fingerprint_warning_only,
                    errors=errors,
                    warnings=warnings,
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
            record_fingerprint_mismatch(
                f"EasyCon Tessdata/{model} 指纹不一致: {model_sha256}",
                warning_only=fingerprint_warning_only,
                errors=errors,
                warnings=warnings,
            )

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
    preview_port: int = 0,
) -> list[str]:
    if video_device < 0:
        raise ValueError("采集卡序号不能为负数")
    if not port or not port.strip():
        raise ValueError("串口不能为空")
    if video_type not in {"ANY", "DSHOW", "MSMF"}:
        raise ValueError(f"不支持的视频类型: {video_type}")
    if preview_port < 0 or preview_port > 65535:
        raise ValueError("预览端口必须为 0 或 1-65535")
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
    if preview_port:
        command.extend(["--preview-port", str(preview_port)])
    return command


def prepare_compat_runner(
    ezcon_path: str | Path,
    runner_path: str | Path = DEFAULT_COMPAT_RUNNER_PATH,
    *,
    fingerprint_warning_only: bool = False,
    fingerprint_warnings: list[str] | None = None,
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
    warnings = fingerprint_warnings if fingerprint_warnings is not None else []
    ezcon_sha256 = hashlib.sha256(ezcon_path.read_bytes()).hexdigest()
    if ezcon_sha256 != EXPECTED_EZCON_SHA256:
        record_fingerprint_mismatch(
            f"原始 EasyCon 1.6.4-a ezcon.exe 指纹不一致: {ezcon_sha256}",
            warning_only=fingerprint_warning_only,
            warnings=warnings,
        )
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
        record_fingerprint_mismatch(
            f"兼容运行器指纹不一致: {runner_sha256}",
            warning_only=fingerprint_warning_only,
            warnings=warnings,
        )

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
        source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        if source_sha256 != expected_sha256:
            record_fingerprint_mismatch(
                f"原始 EasyCon Tessdata/{model} 指纹不一致: {source_sha256}",
                warning_only=fingerprint_warning_only,
                warnings=warnings,
            )
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
            record_fingerprint_mismatch(
                f"兼容运行器 OCR 原生依赖/{relative_name} 指纹不一致: {native_sha256}",
                warning_only=fingerprint_warning_only,
                warnings=warnings,
            )
    return runner_path


def launch_project(**kwargs) -> subprocess.Popen:
    """Launch only after the caller has shown and accepted preflight results."""
    command = build_run_command(**kwargs)
    return subprocess.Popen(command, cwd=str(Path(kwargs["project_main"]).parent))
