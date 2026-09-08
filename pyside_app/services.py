"""UI-independent service boundary; never imports or instantiates Tk."""
from __future__ import annotations

import json
import re
import socket
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from app_paths import DATA_ROOT, RESOURCE_ROOT, USER_DATA_ROOT
from automation import (
    AutoSearchRequest, EasyCon118Options, EasyConRuntimeCheck, PlanSearchResult,
    DEFAULT_EZCON_PATH, DEFAULT_TID_SOURCE_PATH, STANDARD_TEMPLATE_NAME,
    EGG_TEMPLATE_NAME, SearchCancelledError, search_best_plan,
    write_configured_project, validate_runtime, validate_generated_project_consistency,
    prepare_compat_runner, build_run_command, probe_easycon_devices,
)
from device_label_overrides import LabelOverrideStore, apply_profile_to_projects


@dataclass(frozen=True)
class AppPaths:
    user: Path = USER_DATA_ROOT
    output: Path = DATA_ROOT / "runtime" / "pyside6"
    source: Path = RESOURCE_ROOT / "local_assets" / "easycon118"
    ezcon: Path = DEFAULT_EZCON_PATH
    tid_source: Path = DEFAULT_TID_SOURCE_PATH


@dataclass(frozen=True)
class WildInputs:
    request: AutoSearchRequest
    options: EasyCon118Options
    source: Path
    ezcon: Path
    template_name: str = STANDARD_TEMPLATE_NAME
    advanced: bool = False
    capture_name: str = ""

    def fingerprint(self) -> str:
        return json.dumps(asdict(self), default=str, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class PreparedWild:
    inputs: WildInputs
    result: PlanSearchResult
    project: Path | None
    plan_path: Path
    check: EasyConRuntimeCheck


@dataclass(frozen=True)
class RunCommand:
    program: str
    arguments: tuple[str, ...]
    log_path: Path
    stop_path: Path
    preview_url: str
    check: EasyConRuntimeCheck


def validate_wild_inputs(inputs: WildInputs) -> None:
    inputs.request.validate()
    if not inputs.source.is_dir():
        raise ValueError("请选择存在的 2.0 自动乱数脚本包目录")
    if inputs.template_name not in (STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME):
        raise ValueError("野生 / 静态只能使用正式版或时间轴版入口")
    if not (inputs.source / inputs.template_name).is_file():
        raise ValueError(f"脚本包缺少所选入口：{inputs.template_name}")
    if inputs.options.item_rng_mode and not 1 <= inputs.options.party_empty_slots <= 5:
        raise ValueError("道具乱数的队伍空位必须在 1–5 之间")
    if inputs.options.item_rng_mode and "Wild" not in inputs.request.method:
        raise ValueError("道具乱数仅适用于野生目标")
    options = inputs.options
    if options.reverse_expansion_layers is not None:
        if not 0 <= options.reverse_expansion_layers <= 3:
            raise ValueError("反查扩窗层数必须在 0–3 之间")
        for values in (options.reverse_expansion_seed_tolerances, options.reverse_expansion_frame_half_widths):
            if values is None or len(values) != 3 or any(value < 0 for value in values):
                raise ValueError("三层扩窗参数必须是非负整数")
    if (options.togepi_seed_reverse_frame_half_width is not None
            and options.togepi_seed_reverse_frame_half_width < 0):
        raise ValueError("波克比 Seed 反查帧半宽不能为负数")


def prepare_wild(
    inputs: WildInputs, paths: AppPaths, *, cancel: Callable[[], bool],
    progress: Callable[[str], None] = lambda _text: None,
) -> PreparedWild:
    validate_wild_inputs(inputs)
    if cancel():
        raise SearchCancelledError("已取消搜索")
    progress("正在搜索目标与可行路线……")
    result = search_best_plan(inputs.request, cancel_check=cancel)
    if cancel():
        raise SearchCancelledError("已取消搜索")
    # Each attempt owns a new directory. Neither the Tk runtime nor previous
    # generated plans/logs can be overwritten by a failed or cancelled job.
    output = paths.output / ("wild-" + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    plan_path = output / "search-result.json"
    plan_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    if not result.plan.route_support.can_start:
        return PreparedWild(inputs, result, None, plan_path,
                            EasyConRuntimeCheck(False, ("此路线只支持搜索，正式服务不允许自动运行。",), ()))
    project = None
    try:
        progress("已找到方案，正在生成脚本并执行正式预检……")
        project = write_configured_project(inputs.source, output / "project", result.plan,
                                           inputs.options, template_name=inputs.template_name,
                                           precalibration_store_path=paths.user / "precalibration.json")
        if inputs.capture_name:
            store = LabelOverrideStore(paths.user / "device_label_overrides")
            profile = store.profile(inputs.capture_name)
            if profile.manifest_path.is_file():
                store.load_manifest(profile)
                apply_profile_to_projects(project.parent, profile)
        if cancel():
            raise SearchCancelledError("已取消生成")
        validate_generated_project_consistency(project, result.plan, inputs.options,
                                               template_name=inputs.template_name)
        check = validate_runtime(inputs.ezcon, project, fingerprint_warning_only=inputs.advanced)
    except SearchCancelledError:
        raise
    except Exception as exc:
        check = EasyConRuntimeCheck(False, (f"生成 / 预检失败：{exc}",), ())
    if cancel():
        raise SearchCancelledError("已取消操作")
    return PreparedWild(inputs, result, project, plan_path, check)


def prepare_run(prepared: PreparedWild, port: str, video: int, capture_name: str) -> RunCommand:
    """Revalidate devices and generated content immediately before execution."""
    if not prepared.project or not prepared.check.ok:
        raise ValueError("请先生成并通过预检")
    inputs = prepared.inputs
    if inputs.capture_name != capture_name:
        raise ValueError("采集卡与生成时不一致，请重新生成以应用正确的设备标签")
    ports, videos, _output = probe_easycon_devices(inputs.ezcon, include_video_names=True)
    if port not in ports:
        raise ValueError(f"未检测到串口 {port}，请重新检测设备")
    if video not in videos or videos[video] != capture_name:
        raise ValueError("采集卡编号或名称已改变，请重新检测并生成方案")
    validate_generated_project_consistency(prepared.project, prepared.result.plan, inputs.options,
                                           template_name=inputs.template_name)
    check = validate_runtime(inputs.ezcon, prepared.project, fingerprint_warning_only=inputs.advanced)
    if not check.ok:
        raise ValueError("\n".join(check.errors))
    warnings = list(check.warnings)
    runner = prepare_compat_runner(inputs.ezcon, fingerprint_warning_only=inputs.advanced,
                                   fingerprint_warnings=warnings)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        preview_port = sock.getsockname()[1]
    run_id = uuid.uuid4().hex
    log_path = prepared.project.parent / f"easycon-{run_id}.log"
    stop_path = log_path.with_suffix(".stop")
    command = build_run_command(runner, prepared.project, port=port, video_device=video,
                                video_type="DSHOW", preview_port=preview_port)
    arguments = ("-u", str(RESOURCE_ROOT / "run_easycon_logged.py"),
                 "--log-path", str(log_path), "--cwd", str(prepared.project.parent),
                 "--stop-file", str(stop_path), "--", *command)
    # pythonw has no stdout even when QProcess supplies pipes. The log wrapper
    # needs the console interpreter; QProcess still owns its hidden process.
    interpreter = Path(sys.executable)
    if interpreter.name.lower() == "pythonw.exe":
        interpreter = interpreter.with_name("python.exe")
    return RunCommand(str(interpreter), arguments, log_path, stop_path,
                      f"http://127.0.0.1:{preview_port}/mjpeg",
                      EasyConRuntimeCheck(True, (), tuple(warnings)))


_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CHECKPOINT = re.compile(
    r"^(?:\[\d{2}:\d{2}:\d{2}(?:\.\d+)?\]\s*)?"
    r"TIDPROGRESS\|V=[123]\|(?:[A-Z0-9_]+=-?[0-9]+\|)+END=1[ \t]*$"
)


def display_log_line(line: str) -> str | None:
    """Called for complete lines only; original files retain every byte."""
    cleaned = _ANSI.sub("", line.rstrip("\r\n"))
    return None if _CHECKPOINT.fullmatch(cleaned) else cleaned
