"""Prepare the standalone EasyCon 1.6.4-a SID observation collector."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import shutil
import sys
from pathlib import Path

from rng.tenlines_utils import get_personal

from .easycon118 import (
    EXPECTED_SCRIPT_FILE_COUNT,
    EXPECTED_SCRIPT_SHA256,
    HOME_BUFFER_ADAPTIVE_CLASSIFIER_PATH,
    HOME_BUFFER_ADAPTIVE_GLOBALS,
    copy_easycon118_extension_labels,
    inspect_script_corpus,
    is_supported_runtime_script_sha256,
)


SID_REVERSE_TEMPLATE_NAME = "NS火叶SID反查-采集测试.ecs"
SID_HOME_BUFFER_CONTROLLER_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "easycon118_extensions"
    / "sid_home_buffer_adaptive.ecs"
)
SID_HOME_BUFFER_GLOBAL_ANCHOR = "$SID反查累计SPEIV最大 = -1\n"
SID_HOME_BUFFER_GLOBALS = """\
# SID HOME_BUFFER 只读取用户选择的主机标签；稳定低分自适应默认关闭。
$NX机型 = 1
$调试日志输出 = 1
$HOME_BUFFER延迟 = 1200
$HOME_BUFFER当前正确退出 = 0
$HOME_BUFFER当前正确退出_NS2 = 0
$HOME_BUFFER当前正确退出普通 = 0
$HOME_BUFFER当前正确退出普通_NS2 = 0
$HOME_BUFFER当前错误退出 = 0
$HOME_BUFFER当前错误退出_NS2 = 0
"""
SID_HOME_BUFFER_CLASSIFIER_MARKER = "# 1.6.4-a HOME_BUFFER 稳定低分自适应"
SID_HOME_BUFFER_CONTROLLER_MARKER = "# SID 反查 HOME_BUFFER"
SID_CLOSE_FUNCTION = "FUNC SID反查关闭游戏"
SID_START_FUNCTION = "FUNC SID反查普通启动并进入存档"
SID_NEXT_FUNCTION = "FUNC SID反查选择队伍位置"
SID_START_REPLACEMENT = """\
FUNC SID反查普通启动并进入存档
    # HOME_BUFFER 成功后仍在 Switch 主界面；按 A 回到游戏后继续原来的跳 OP/进档操作。
    CALL SID反查HOME_BUFFER
    A
    WAIT 8000
    A
    WAIT 500
    A
    WAIT 500
    A DOWN
    WAIT 3000
    A UP
    WAIT 500
    A DOWN
    WAIT 1000
    A UP
    WAIT 500
    B
    WAIT 2500
ENDFUNC
"""


@dataclass(frozen=True)
class SIDReverseRunRequest:
    tid: int
    party_count: int
    game: str = "fr_nx"
    nx_model: int = 1
    start_slot: int = 1
    max_candies: int = 5
    recognition_threshold: int = 85
    home_buffer_adaptive_threshold: bool = False
    dex_overrides: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)
    initial_levels: tuple[int, int, int, int, int, int] = (1, 1, 1, 1, 1, 1)
    source_types: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)
    locations: tuple[str, str, str, str, str, str] = ("", "", "", "", "", "")
    effort_values: tuple[
        tuple[int, int, int, int, int, int],
        tuple[int, int, int, int, int, int],
        tuple[int, int, int, int, int, int],
        tuple[int, int, int, int, int, int],
        tuple[int, int, int, int, int, int],
        tuple[int, int, int, int, int, int],
    ] = (
        (0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0),
    )

    def validate(self) -> None:
        if not 0 <= self.tid <= 0xFFFF:
            raise ValueError("TID必须在0-65535之间")
        if self.game not in ("fr_nx", "lg_nx"):
            raise ValueError("游戏版本必须是fr_nx或lg_nx")
        if self.nx_model not in (1, 2):
            raise ValueError("SID查找主机必须是Switch 1或Switch 2")
        if not isinstance(self.home_buffer_adaptive_threshold, bool):
            raise ValueError("HOME_BUFFER稳定低分自适应开关必须是布尔值")
        if not 1 <= self.party_count <= 6:
            raise ValueError("队内闪光数量必须在1-6之间")
        if not 1 <= self.start_slot <= 6:
            raise ValueError("队伍起始位置必须在1-6之间")
        if self.start_slot + self.party_count - 1 > 6:
            raise ValueError("起始位置与数量超出第六个队伍槽位")
        if not 0 <= self.max_candies <= 20:
            raise ValueError("每只最多糖果必须在0-20之间")
        if not 1 <= self.recognition_threshold <= 100:
            raise ValueError("识图阈值必须在1-100之间")
        if len(self.dex_overrides) != 6:
            raise ValueError("图鉴编号覆盖必须恰好包含6项")
        if any(not 0 <= value <= 386 for value in self.dex_overrides):
            raise ValueError("图鉴编号覆盖仅支持0或1-386")
        if len(self.initial_levels) != 6:
            raise ValueError("初始等级必须恰好包含6项")
        if len(self.source_types) != 6 or any(value not in (0, 1) for value in self.source_types):
            raise ValueError("来源类型必须恰好包含6项，且0=定点、1=野生")
        if len(self.locations) != 6:
            raise ValueError("相遇地点必须恰好包含6项")
        if len(self.effort_values) != 6 or any(len(values) != 6 for values in self.effort_values):
            raise ValueError("努力值必须为6只宝可梦各6项")
        for slot, values in enumerate(self.effort_values, start=1):
            if any(not 0 <= value <= 255 for value in values):
                raise ValueError(f"队伍第{slot}位每项努力值必须在0-255之间")
            if sum(values) > 510:
                raise ValueError(f"队伍第{slot}位六项努力值总和不能超过510")
        for offset in range(self.party_count):
            index = self.start_slot - 1 + offset
            if self.dex_overrides[index] == 0:
                raise ValueError(f"队伍第{index + 1}位必须填写1-386的全国图鉴编号")
            if not 1 <= self.initial_levels[index] <= 100:
                raise ValueError(f"队伍第{index + 1}位初始等级必须在1-100之间")
            if self.source_types[index] == 1 and not self.locations[index].strip():
                raise ValueError(f"队伍第{index + 1}位是野生宝可梦，必须填写相遇地点")


def _ecs_literal(value) -> str:
    if isinstance(value, (tuple, list)):
        return "[" + ",".join(_ecs_literal(item) for item in value) + "]"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value)


def configure_sid_reverse_template(template_text: str, request: SIDReverseRunRequest) -> str:
    request.validate()
    personal = tuple(
        get_personal(species_id, request.game)
        if species_id > 0
        else {"stats": (0, 0, 0, 0, 0, 0), "gender": 127}
        for species_id in request.dex_overrides
    )
    values = {
        "SID反查TID": request.tid,
        "SID反查队内闪光数量": request.party_count,
        "SID反查每只最多糖果": request.max_candies,
        "SID反查识图阈值": request.recognition_threshold,
        "SID反查队伍起始位置": request.start_slot,
        "SID反查图鉴编号覆盖": request.dex_overrides,
        "SID反查初始等级": request.initial_levels,
        "SID反查种族HP覆盖": tuple(item["stats"][0] for item in personal),
        "SID反查种族ATK覆盖": tuple(item["stats"][1] for item in personal),
        "SID反查种族DEF覆盖": tuple(item["stats"][2] for item in personal),
        "SID反查种族SPA覆盖": tuple(item["stats"][3] for item in personal),
        "SID反查种族SPD覆盖": tuple(item["stats"][4] for item in personal),
        "SID反查种族SPE覆盖": tuple(item["stats"][5] for item in personal),
        "SID反查性别阈值覆盖": tuple(item["gender"] for item in personal),
        "SID反查来源类型": request.source_types,
        "SID反查相遇地点": request.locations,
        "SID反查努力HP": tuple(values[0] for values in request.effort_values),
        "SID反查努力ATK": tuple(values[1] for values in request.effort_values),
        "SID反查努力DEF": tuple(values[2] for values in request.effort_values),
        "SID反查努力SPA": tuple(values[3] for values in request.effort_values),
        "SID反查努力SPD": tuple(values[4] for values in request.effort_values),
        "SID反查努力SPE": tuple(values[5] for values in request.effort_values),
    }
    configured = template_text
    for name, value in values.items():
        pattern = re.compile(rf"(?m)^\${re.escape(name)}\s*=\s*[^\r\n]*$")
        configured, count = pattern.subn(f"${name} = {_ecs_literal(value)}", configured)
        if count != 1:
            raise ValueError(f"SID采集模板字段${name}应出现1次，实际为{count}次")
    return configured


def _replace_ecs_function(
    template_text: str,
    function_name: str,
    next_function_name: str,
    replacement: str,
) -> str:
    if template_text.count(function_name) != 1:
        raise ValueError(f"SID采集模板函数{function_name}应出现1次")
    if template_text.count(next_function_name) != 1:
        raise ValueError(f"SID采集模板后继函数{next_function_name}应出现1次")
    start = template_text.index(function_name)
    end = template_text.index(next_function_name, start)
    return template_text[:start] + replacement.rstrip() + "\n\n" + template_text[end:]


def apply_sid_home_buffer_runtime(
    template_text: str,
    request: SIDReverseRunRequest,
) -> str:
    """Install SID HOME_BUFFER calibration without changing its post-entry actions."""
    request.validate()
    if template_text.count(SID_HOME_BUFFER_GLOBAL_ANCHOR) != 1:
        raise ValueError("SID采集模板缺少唯一的共享状态锚点")

    globals_text = (
        SID_HOME_BUFFER_GLOBALS.replace("$NX机型 = 1", f"$NX机型 = {request.nx_model}")
        + HOME_BUFFER_ADAPTIVE_GLOBALS.replace(
            "$HOME_BUFFER稳定低分自适应 = 0",
            "$HOME_BUFFER稳定低分自适应 = "
            + ("1" if request.home_buffer_adaptive_threshold else "0"),
            1,
        )
    )
    template_text = template_text.replace(
        SID_HOME_BUFFER_GLOBAL_ANCHOR,
        SID_HOME_BUFFER_GLOBAL_ANCHOR + globals_text,
        1,
    )

    if template_text.count(SID_CLOSE_FUNCTION) != 1:
        raise ValueError("SID采集模板缺少唯一的关闭游戏函数")
    classifier_text = HOME_BUFFER_ADAPTIVE_CLASSIFIER_PATH.read_text(
        encoding="utf-8"
    ).rstrip()
    controller_text = SID_HOME_BUFFER_CONTROLLER_PATH.read_text(
        encoding="utf-8"
    ).rstrip()
    if SID_HOME_BUFFER_CLASSIFIER_MARKER not in classifier_text:
        raise ValueError("SID HOME_BUFFER共享分类器缺少版本标记")
    if SID_HOME_BUFFER_CONTROLLER_MARKER not in controller_text:
        raise ValueError("SID HOME_BUFFER控制器缺少版本标记")
    template_text = template_text.replace(
        SID_CLOSE_FUNCTION,
        classifier_text + "\n\n" + controller_text + "\n\n" + SID_CLOSE_FUNCTION,
        1,
    )
    return _replace_ecs_function(
        template_text,
        SID_START_FUNCTION,
        SID_NEXT_FUNCTION,
        SID_START_REPLACEMENT,
    )


def write_sid_reverse_plan(
    source_dir: str | Path,
    output_dir: str | Path,
    request: SIDReverseRunRequest,
    *,
    filename: str = "plan.json",
) -> Path:
    request.validate()
    plan_name = Path(filename)
    if plan_name.is_absolute() or plan_name.name != filename:
        raise ValueError("SID计划文件名必须是不含目录的相对文件名")
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "mode": "sid_reverse_observation",
        "source": str(source_dir),
        "template": SID_REVERSE_TEMPLATE_NAME,
        "request": asdict(request),
        "scripts": {
            "expected_count": EXPECTED_SCRIPT_FILE_COUNT,
            "expected_sha256": EXPECTED_SCRIPT_SHA256,
        },
    }
    plan_path = output_dir / plan_name
    plan_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return plan_path


def write_sid_reverse_project(
    source_dir: str | Path,
    output_dir: str | Path,
    request: SIDReverseRunRequest,
    *,
    copy_assets: bool = True,
    plan_filename: str = "plan.json",
) -> Path:
    request.validate()
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    corpus = inspect_script_corpus(source_dir)
    if corpus["count"] != EXPECTED_SCRIPT_FILE_COUNT:
        raise ValueError(
            f"2.0 正式/时间轴主脚本及 lib 文件数应为 {EXPECTED_SCRIPT_FILE_COUNT}，"
            f"当前为{corpus['count']}"
        )
    if not is_supported_runtime_script_sha256(corpus["sha256"]):
        print(
            "警告：2.0 主脚本/lib 指纹未登记，仍继续生成 SID 反查项目："
            + corpus["sha256"],
            file=sys.stderr,
        )
    template = source_dir / SID_REVERSE_TEMPLATE_NAME
    if not template.is_file():
        raise FileNotFoundError(f"缺少SID采集模板: {template}")

    output_dir.mkdir(parents=True, exist_ok=True)
    main_path = output_dir / "main.ecs"
    configured = configure_sid_reverse_template(
        template.read_text(encoding="utf-8"), request
    )
    configured = apply_sid_home_buffer_runtime(configured, request)
    main_path.write_text(configured, encoding="utf-8")
    if copy_assets:
        for directory in ("lib", "ImgLabel"):
            source = source_dir / directory
            target = output_dir / directory
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            if directory == "ImgLabel":
                copy_easycon118_extension_labels(target)
    write_sid_reverse_plan(
        source_dir,
        output_dir,
        request,
        filename=plan_filename,
    )
    return main_path
