"""Remaining Qt workflows reuse the formal generators and worker CLIs."""
from __future__ import annotations

import hashlib
import json
import socket
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from app_paths import DATA_ROOT, RESOURCE_ROOT
from automation import (
    EasyConRuntimeCheck, STANDARD_TEMPLATE_NAME, SCRIPT_TEST_BACKEND_COMPAT,
    SCRIPT_TEST_BACKEND_ORIGINAL, build_run_command, prepare_compat_runner,
    probe_easycon_devices, prepare_script_test_runtime, validate_runtime,
    validate_generated_egg_project_consistency, write_configured_egg_project,
    write_sid_reverse_project, write_sid_reverse_plan, write_configured_tid_project,
    build_tid_starter_flow_plan, write_tid_starter_flow_bundle, inspect_script_corpus,
    SearchCancelledError,
)
from automation.tid_calibration import validate_tid_plan_runtime
from automation.tid_search import progress_supported
from device_label_overrides import LabelOverrideStore, apply_profile_to_projects
from sid_traversal import traversal_context, DEFAULT_TARGET_MAX_ADVANCES
from tid_records import TidRecordContext
from tid_session import write_json_atomic
from worker_commands import build_worker_command
from .services import AppPaths, RunCommand


@dataclass(frozen=True)
class WorkflowInputs:
    mode: str
    request: object
    source: Path
    ezcon: Path
    advanced: bool = False
    template: str = STANDARD_TEMPLATE_NAME
    capture_name: str = ""
    extra: dict = field(default_factory=dict)

    def fingerprint(self):
        return json.dumps(asdict(self), default=str, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class PreparedWorkflow:
    inputs: WorkflowInputs
    directory: Path
    project: Path
    check: EasyConRuntimeCheck
    snapshot: dict[str, str]
    details: str
    metrics: tuple
    profile: Path | None = None


def _snapshot(project, directory):
    files = {project, *project.parent.glob("lib/*.ecs"), *project.parent.glob("ImgLabel/*"),
             *directory.rglob("*.ecs"), *directory.rglob("*.json"), *directory.rglob("*.IL")}
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()}


def _check_snapshot(prepared):
    for name, digest in prepared.snapshot.items():
        path = Path(name)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"预检后文件已改变，请重新生成 / 预检：{path.name}")


def check_workflow(inputs, project, directory):
    if inputs.mode == "egg":
        validate_generated_egg_project_consistency(project, inputs.request, template_name=inputs.template)
    if inputs.mode == "tid":
        return validate_tid_plan_runtime(inputs.ezcon, directory,
            is_flow=bool(inputs.extra.get("flow")), calibrate_first=inputs.request.calibration_check,
            fingerprint_warning_only=inputs.advanced)
    if inputs.mode in ("script_test", "sid_traversal"):
        backend = inputs.extra.get("backend", SCRIPT_TEST_BACKEND_COMPAT)
        return prepare_script_test_runtime(inputs.ezcon, project, backend,
            fingerprint_warning_only=inputs.advanced).check
    return validate_runtime(inputs.ezcon, project, fingerprint_warning_only=inputs.advanced)


def prepare_workflow(inputs: WorkflowInputs, paths: AppPaths, *, cancel, progress=lambda text: None):
    if cancel():
        raise SearchCancelledError("已取消")
    directory = paths.output / f"{inputs.mode}-{uuid.uuid4().hex}"
    directory.mkdir(parents=True, exist_ok=False)
    progress("正在生成并执行正式预检……")
    warnings = []
    request = inputs.request
    profile = None
    if inputs.capture_name:
        store = LabelOverrideStore(paths.user / "device_label_overrides")
        selected = store.profile(inputs.capture_name)
        if selected.manifest_path.is_file():
            store.list_overrides(inputs.capture_name)
            profile = selected
    if inputs.mode == "egg":
        request.validate()
        project = write_configured_egg_project(inputs.source, directory, request,
            template_name=inputs.template, precalibration_store_path=paths.user / "precalibration.json")
        metrics = (request.normalized_seed, request.held_advances, request.pickup_advances)
        details = f"孵蛋目标：{request.normalized_seed}；Held {request.held_advances} / Pickup {request.pickup_advances}\n同一个初始 Seed；亲本资料已写入。"
    elif inputs.mode == "sid":
        request.validate()
        project = write_sid_reverse_project(inputs.source, directory, request)
        write_sid_reverse_plan(inputs.source, directory, request)
        metrics = ("—", "—", "—")
        details = f"SID 逐只采集已准备：TID {request.tid:05d}，共 {request.party_count} 只。\n运行完成后显示真实反查报告；目前没有 SID 结果。"
    elif inputs.mode == "tid":
        flow = inputs.extra.get("flow")
        plan = None
        if flow:
            plan = build_tid_starter_flow_plan(flow)
            if cancel():
                raise SearchCancelledError("已取消搜索御三家")
            write_tid_starter_flow_bundle(inputs.source, directory, plan,
                starter_source_dir=inputs.extra["starter_source"],
                precalibration_store_path=paths.user / "precalibration.json",
                fingerprint_warning_only=inputs.advanced, fingerprint_warnings=warnings)
            project = directory / "01_id/main.ecs"
        else:
            project = write_configured_tid_project(inputs.source, directory, replace(request, calibration_check=False),
                fingerprint_warning_only=inputs.advanced, fingerprint_warnings=warnings)
        if request.calibration_check:
            write_configured_tid_project(inputs.source, directory / "00_calibration", request,
                fingerprint_warning_only=inputs.advanced, fingerprint_warnings=warnings)
        metrics = ("实测后确定" if flow and flow.accept_any_tid else f"{request.target_tid:05d}",
            "实测后确定" if request.sid_random else f"{request.target_sid:05d}",
            plan.starter_run_plan.initial_seed.advances if plan and plan.starter_run_plan else "—")
        details = ("TID → 球前存档 → 御三家" if flow else "TID / SID 建档") + f"\n{request.language} · Switch {request.nx_model} · {'穷举' if request.mode == 0 else '乱数'}\n"
        details += "将先检测固定延迟，回填后重新生成并继续。" if request.calibration_check else "使用当前固定延迟。"
        details += "\n运行器负责恢复同参数的进度与记录实测 TID。"
    elif inputs.mode == "script_test":
        project = Path(inputs.extra["script"]).resolve()
        metrics = ("原地执行", "1.6.4-a", "待预检")
        details = f"脚本测试：{project}\n后端：{inputs.extra['backend']}\n原地执行所选脚本，不替换参数。"
    elif inputs.mode == "sid_traversal":
        request.validate()
        options = inputs.extra["options"]
        context = traversal_context(tid=request.tid, named_rival=inputs.extra["named_rival"],
            wild_request=asdict(request), easycon_options=asdict(options),
            source_sha256=inspect_script_corpus(inputs.source)["sha256"],
            max_advances=inputs.extra["max_advances"], start_advance=inputs.extra.get("start_advance"),
            target_max_advances=DEFAULT_TARGET_MAX_ADVANCES)
        payload = {"mode": "sid_traversal", "version": 1, "source": str(inputs.source),
            "request": asdict(request), "easycon_options": asdict(options),
            "named_rival": inputs.extra["named_rival"], "start_sid_advance": context["start_sid_advance"],
            "max_advances": inputs.extra["max_advances"], "target_max_advances": DEFAULT_TARGET_MAX_ADVANCES,
            "traversal_context": context}
        write_json_atomic(directory / "traversal.json", payload)
        project = inputs.source / STANDARD_TEMPLATE_NAME
        metrics = ("遍历中确定", "—", "—")
        details = f"SID 遍历：TID {request.tid:05d}；起点 {context['start_sid_advance']} / 上限 {context['max_advances']}\n每个 SID 搜索 {request.min_advances}–{DEFAULT_TARGET_MAX_ADVANCES} ADV；只有明确未出闪才推进。"
        from sid_traversal import read_progress
        saved = read_progress(inputs.extra["progress_dir"], context)
        if saved:
            state = saved["state"]
            details += f"\n上次状态：{saved['status']}；继续 ADV {state.get('current_sid_advance') or state.get('next_sid_advance', context['start_sid_advance'])}。"
        else:
            details += "\n没有同参数检查点，将从所填起点开始。"
    else:
        raise ValueError(f"未知功能：{inputs.mode}")
    if profile and inputs.mode not in ("script_test", "sid_traversal"):
        apply_profile_to_projects(directory, profile)
    if cancel():
        raise SearchCancelledError("已取消生成")
    check = check_workflow(inputs, project, directory)
    check = replace(check, warnings=tuple(dict.fromkeys((*warnings, *check.warnings))))
    if inputs.mode == "script_test":
        metrics = ("原地执行", "1.6.4-a", "通过" if check.ok else "未通过")
    details += f"\n工程：{project}\n" + "\n".join((*check.errors, *check.warnings))
    if cancel():
        raise SearchCancelledError("已取消预检")
    snapshot = _snapshot(project, directory)
    sources = [] if inputs.mode == "script_test" else [inputs.source]
    if inputs.extra.get("flow"):
        sources.append(inputs.extra["starter_source"])
    if profile:
        sources.append(profile.directory)
    for source in sources:
        for path in Path(source).rglob("*"):
            if path.is_file() and path.suffix.lower() in (".ecs", ".il", ".json"):
                snapshot[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return PreparedWorkflow(inputs, directory, project, check, snapshot,
                            details, metrics, profile.directory if profile else None)


def prepare_workflow_run(prepared: PreparedWorkflow, paths: AppPaths, port, video, capture_name):
    inputs = prepared.inputs
    if not prepared.check.ok:
        raise ValueError("请先通过预检")
    if capture_name != inputs.capture_name:
        raise ValueError("采集设备已变化，请重新生成")
    ports, videos, _ = probe_easycon_devices(inputs.ezcon, include_video_names=True)
    if port not in ports or videos.get(video) != capture_name:
        raise ValueError("设备编号或名称已变化，请重新检测")
    _check_snapshot(prepared)
    check = check_workflow(inputs, prepared.project, prepared.directory)
    if not check.ok:
        raise ValueError("\n".join(check.errors))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        preview_port = sock.getsockname()[1]
    tag = uuid.uuid4().hex
    log = prepared.directory / f"run-{tag}.log"
    stop = log.with_suffix(".stop")
    common = ["--ezcon", str(inputs.ezcon), "--port", port, "--video", str(video),
              "--log-path", str(log), "--stop-file", str(stop), "--preview-port", str(preview_port)]
    if inputs.advanced:
        common.append("--fingerprint-warnings")
    request = inputs.request
    if inputs.mode == "sid":
        worker = "sid-capture"
        args = ["--request-json", str(prepared.directory / "plan.json"), "--game", request.game,
                "--source", str(inputs.source), "--output", str(prepared.directory),
                "--report-path", str(log.with_suffix(".report.txt")), *common]
        if prepared.profile:
            args += ["--label-override-profile", str(prepared.profile)]
    elif inputs.mode == "tid":
        worker = "tid-flow"
        context = log.with_suffix(".tid-context.json")
        TidRecordContext.from_request(inputs.extra["game"], request).save(context)
        args = ["--flow-dir" if inputs.extra.get("flow") else "--tid-dir", str(prepared.directory),
                "--tid-context", str(context), "--tid-records", str(paths.user / "tid_records.sqlite3"), *common]
        if progress_supported(replace(request, calibration_check=False)):
            args += ["--tid-progress-dir", str(paths.user / "tid_progress"), "--tid-game", inputs.extra["game"]]
            if not inputs.extra["resume"]:
                args += ["--fresh-exhaustive"]
        if request.calibration_check:
            args += ["--calibrate-first", "--calibration-result", str(log.with_suffix(".calibration.json"))]
        if prepared.profile:
            args += ["--label-override-profile", str(prepared.profile)]
    elif inputs.mode == "sid_traversal":
        worker = "sid-traversal"
        args = ["--request-json", str(prepared.directory / "traversal.json"), "--source", str(inputs.source),
                "--output", str(prepared.directory / "attempts"), "--progress-dir", str(inputs.extra["progress_dir"]),
                "--max-advances", str(inputs.extra["max_advances"]),
                "--target-max-advances", str(DEFAULT_TARGET_MAX_ADVANCES),
                "--report-path", str(log.with_suffix(".report.json")), *common]
        if inputs.extra["named_rival"]:
            args.append("--named-rival")
        if inputs.extra.get("start_advance") is not None:
            args += ["--start-advance", str(inputs.extra["start_advance"])]
        if prepared.profile:
            args += ["--label-override-profile", str(prepared.profile)]
    else:
        worker = "easycon-log"
        backend = inputs.extra.get("backend", SCRIPT_TEST_BACKEND_COMPAT)
        if backend == SCRIPT_TEST_BACKEND_ORIGINAL:
            runner, preview_port = inputs.ezcon, 0
        else:
            runner = prepare_compat_runner(inputs.ezcon, fingerprint_warning_only=inputs.advanced)
        command = build_run_command(runner, prepared.project, port=port, video_device=video,
                                   video_type="DSHOW", preview_port=preview_port, verbose=inputs.extra.get("verbose", False))
        args = ["--log-path", str(log), "--cwd", str(prepared.project.parent), "--stop-file", str(stop)]
        if inputs.mode == "egg":
            for marker in ("孵蛋流程完成", "孵蛋流程失败", "孵蛋流程测试完成", "孵蛋流程测试失败"):
                args += ["--expected-marker", marker]
        args += ["--", *command]
        if inputs.mode == "script_test":
            write_json_atomic(log.with_suffix(".json"), {"script": str(prepared.project),
                "script_sha256": hashlib.sha256(prepared.project.read_bytes()).hexdigest(),
                "backend": backend, "runner": str(runner), "port": port, "video": video, "command": command})
    command = build_worker_command(worker, args)
    return RunCommand(command[0], tuple(command[1:]), log, stop,
                      f"http://127.0.0.1:{preview_port}/mjpeg" if preview_port else "", check)
