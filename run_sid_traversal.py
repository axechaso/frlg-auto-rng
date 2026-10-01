"""Run the wild SID traversal workflow with durable per-candidate progress.

The game-side 1.1.8 script is still responsible for timing and recognition.
This worker only chooses the SID-derived low-ADV shiny target, materializes a
fresh project for that candidate, and decides whether the candidate completed
normally.  An interrupted or ambiguous EasyCon process never advances the
checkpoint.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
from datetime import datetime
import uuid

from app_paths import DATA_ROOT, RESOURCE_ROOT
from automation import (
    AutoSearchRequest,
    DEFAULT_EZCON_PATH,
    EGG_TEMPLATE_NAME,
    EasyCon118Options,
    NoMatchingTargetError,
    NoReachablePlanError,
    SearchWorkLimitError,
    build_run_command,
    inspect_script_corpus,
    prepare_compat_runner,
    search_best_plan,
    validate_runtime,
    write_configured_project,
)
from automation.input_state_protocol import format_input_session_marker
from automation.planner import SearchCancelledError
from automation.sid_traversal_policy import validate_traversal_request
from automation.target_verification import TargetVerificationSpec, parse_target_verification
from device_label_overrides import apply_profile_to_projects, load_label_override_profile
from easycon_outcome import easycon_log_has_fatal_error
from rng.tenlines_utils import get_species_id
from process_control import StopFileWatcher, terminate_process_tree
from run_easycon_logged import run_logged
from sid_traversal import (
    DEFAULT_MAX_ADVANCES,
    DEFAULT_TARGET_MAX_ADVANCES as SID_TRAVERSAL_DEFAULT_TARGET_MAX_ADVANCES,
    SIDTraversalSession,
    progress_path,
    traversal_context,
    write_json_atomic,
)


STANDARD_TEMPLATE_NAME = "NS火叶全自动一键乱数2.0.ecs"
TEMPLATE_NAMES = frozenset({STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME})
DEFAULT_SOURCE = (
    RESOURCE_ROOT / "local_assets" / "easycon118"
    if (RESOURCE_ROOT / "local_assets" / "easycon118").is_dir()
    else Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8"
)
DEFAULT_OUTPUT = DATA_ROOT / "runtime" / "sid_traversal"
DEFAULT_PROGRESS = DATA_ROOT / "sid_traversal_progress"
DEFAULT_TARGET_MAX_ADVANCES = SID_TRAVERSAL_DEFAULT_TARGET_MAX_ADVANCES
def _request_from_payload(payload: dict) -> AutoSearchRequest:
    values = payload.get("request", payload)
    if not isinstance(values, dict):
        raise ValueError("SID遍历计划缺少 request 对象")
    allowed = {field.name for field in __import__("dataclasses").fields(AutoSearchRequest)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError("SID 遍历请求包含未知字段: " + ", ".join(sorted(unknown)))
    filtered = {key: value for key, value in values.items() if key in allowed}
    # JSON arrays are accepted by the dataclass but tuples make the immutable
    # request and context representation explicit for callers/tests.
    for name in ("iv_min", "iv_max"):
        if name in filtered:
            filtered[name] = tuple(int(item) for item in filtered[name])
    request = AutoSearchRequest(**filtered)
    request.validate()
    return request


def _options_from_payload(payload: dict) -> EasyCon118Options:
    values = payload.get("easycon_options", {})
    if not isinstance(values, dict):
        raise ValueError("SID遍历计划缺少 EasyCon 选项")
    allowed = {field.name for field in __import__("dataclasses").fields(EasyCon118Options)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError("SID 遍历选项包含未知字段: " + ", ".join(sorted(unknown)))
    required = {
        "item_rng_mode", "continue_capture_after_shiny", "frame_parity_scheme",
        "mystery_gift_enabled", "record_shiny_video", "update_precalibration",
    }
    missing = required - set(values)
    if missing:
        raise ValueError("SID 遍历计划缺少关键选项: " + ", ".join(sorted(missing)))
    return EasyCon118Options(**values)


def traversal_candidate_request(
    request: AutoSearchRequest,
    sid: int,
    *,
    target_max_advances: int = DEFAULT_TARGET_MAX_ADVANCES,
) -> AutoSearchRequest:
    """Build the low-frame shiny search request for one candidate SID.

    Keep the user's wild-page minimum Advance as the lower bound.  SID
    traversal only relaxes encounter filters; it must not silently search a
    frame prefix that the user excluded.
    """
    target_max_advances = int(target_max_advances)
    if target_max_advances <= 0:
        raise ValueError("SID遍历的低帧搜索上限必须大于0")
    target_min_advances = int(request.min_advances)
    if target_min_advances < 0:
        raise ValueError("SID遍历的低帧搜索下限不能为负数")
    if target_min_advances > target_max_advances:
        raise ValueError(
            "SID遍历的低帧搜索下限不能大于上限 "
            f"（{target_min_advances}>{target_max_advances}）"
        )
    return replace(
        request,
        sid=int(sid),
        min_advances=target_min_advances,
        max_advances=target_max_advances,
        iv_min=(0, 0, 0, 0, 0, 0),
        iv_max=(31, 31, 31, 31, 31, 31),
        shiny="Star/Square",
        nature="Any",
        gender="Any",
        ability="Any",
        hidden_type="Any",
        direct_mode=False,
        direct_seed=None,
        direct_advances=None,
    )


def _write_report(path: Path | None, payload: dict) -> None:
    if path is not None:
        write_json_atomic(path, payload)


def _load_plan(path: Path) -> tuple[AutoSearchRequest, EasyCon118Options, dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"SID遍历计划读取失败: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("SID遍历计划根结构必须是对象")
    if payload.get("mode") != "sid_traversal" or payload.get("version") != 2:
        raise ValueError("SID 遍历计划版本不受支持；请重新生成版本 2 计划")
    required = {
        "template_name", "encounter_kind", "route_key", "save_context",
        "effective_frame_parity_scheme", "verification_protocol",
        "script_fingerprint", "precalibration_store_path", "traversal_context",
        "named_rival", "start_sid_advance", "max_advances", "target_max_advances", "source",
    }
    missing = required - set(payload)
    if missing:
        raise ValueError("SID 遍历计划缺少字段: " + ", ".join(sorted(missing)))
    request = _request_from_payload(payload)
    options = _options_from_payload(payload)
    availability = validate_traversal_request(request, options, payload["template_name"])
    if payload["encounter_kind"] != availability.encounter_kind:
        raise ValueError("SID 遍历计划的遭遇类型与请求不一致")
    if payload["route_key"] != availability.route_key:
        raise ValueError("SID 遍历计划的路线标识与请求不一致")
    if payload["template_name"] not in TEMPLATE_NAMES:
        raise ValueError("SID 遍历模板不在正式版/时间轴白名单中")
    if type(payload["verification_protocol"]) is not int or payload["verification_protocol"] != 1:
        raise ValueError("SID 遍历目标证明协议不受支持")
    if type(payload["effective_frame_parity_scheme"]) is not int or payload["effective_frame_parity_scheme"] != options.frame_parity_scheme:
        raise ValueError("SID 遍历计划有效帧奇偶与选项不一致")
    save_context = payload["save_context"]
    if not isinstance(save_context, dict) or type(save_context.get("mystery_gift_enabled")) is not bool:
        raise ValueError("SID 遍历计划存档快照格式无效")
    if save_context["mystery_gift_enabled"] != options.mystery_gift_enabled:
        raise ValueError("SID 遍历计划存档礼物状态与选项不一致")
    fingerprint = payload["script_fingerprint"]
    if not isinstance(fingerprint, str) or not fingerprint.startswith("sha256:") or len(fingerprint) != 71:
        raise ValueError("SID 遍历计划脚本指纹格式无效")
    if type(payload["named_rival"]) is not bool or type(payload["max_advances"]) is not int or type(payload["target_max_advances"]) is not int:
        raise ValueError("SID 遍历计划边界或劲敌取名状态无效")
    if not isinstance(payload["precalibration_store_path"], str) or not payload["precalibration_store_path"].strip():
        raise ValueError("SID 遍历计划缺少预校准路径")
    if not isinstance(payload["traversal_context"], dict):
        raise ValueError("SID 遍历计划上下文必须是对象")
    return request, options, payload


def _append_log(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as stream:
        stream.write(text)
        if text and not text.endswith("\n"):
            stream.write("\n")


def _emit_session(run_id: str, session_id: str, stage_id: str, state: str) -> None:
    print(format_input_session_marker(run_id, session_id, stage_id, state), flush=True)


def run_traversal(
    *,
    plan_path: Path,
    source_dir: Path,
    ezcon_path: Path,
    output_dir: Path,
    progress_dir: Path,
    port: str,
    video: int,
    log_path: Path,
    report_path: Path | None = None,
    stop_file: Path | None = None,
    max_advances: int | None = None,
    target_max_advances: int | None = None,
    named_rival: bool | None = None,
    start_advance: int | None = None,
    fingerprint_warnings: bool = False,
    label_override_profile: Path | None = None,
    preview_port: int = 0,
    incident_directory: Path | None = None,
    run_id: str = "",
    workflow: str = "sid_traversal",
    capture_device_name: str = "",
    input_session_id: str = "",
    preview_video: bool = False,
) -> int:
    request, options, payload = _load_plan(plan_path)
    source_dir = source_dir.resolve()
    ezcon_path = ezcon_path.resolve()
    output_dir = output_dir.resolve()
    progress_dir = progress_dir.resolve()
    if not port.strip():
        raise ValueError("串口不能为空")
    planned_max_advances = payload["max_advances"]
    planned_target_max_advances = payload["target_max_advances"]
    planned_named_rival = payload["named_rival"]
    planned_start = payload["start_sid_advance"] if "start_sid_advance" in payload else None
    if max_advances is not None and int(max_advances) != planned_max_advances:
        raise ValueError("SID 遍历最大 ADV 与已冻结计划不一致")
    if target_max_advances is not None and int(target_max_advances) != planned_target_max_advances:
        raise ValueError("SID 遍历目标上限与已冻结计划不一致")
    if named_rival is not None and named_rival is not planned_named_rival:
        raise ValueError("SID 遍历劲敌取名状态与已确认计划不一致")
    if start_advance is not None and start_advance != planned_start:
        raise ValueError("SID 遍历起点与已冻结计划不一致")
    max_advances = planned_max_advances
    target_max_advances = planned_target_max_advances
    named_rival = planned_named_rival
    if not run_id:
        run_id = uuid.uuid4().hex
    if not input_session_id:
        input_session_id = uuid.uuid4().hex
    _emit_session(run_id, input_session_id, "sid_traversal", "STARTING")

    def emit_terminal(state: str) -> None:
        _emit_session(run_id, input_session_id, "sid_traversal_terminal", state)

    source_corpus = inspect_script_corpus(source_dir)
    resolved_start = planned_start
    availability = validate_traversal_request(request, options, payload["template_name"])
    context = traversal_context(
        tid=request.tid,
        named_rival=named_rival,
        wild_request=asdict(request),
        easycon_options=asdict(options),
        source_sha256=source_corpus["sha256"],
        max_advances=max_advances,
        start_advance=resolved_start,
        target_max_advances=target_max_advances,
        template_name=payload["template_name"],
        encounter_kind=availability.encounter_kind,
        route_key=availability.route_key,
        static_category=request.category if availability.encounter_kind == "static" else None,
        save_context=payload["save_context"],
        effective_frame_parity_scheme=payload["effective_frame_parity_scheme"],
        mystery_gift_enabled=options.mystery_gift_enabled,
        verification_protocol=payload["verification_protocol"],
    )
    if payload["script_fingerprint"] != f"sha256:{source_corpus['sha256']}":
        raise ValueError("SID 遍历计划脚本指纹与当前脚本包不一致")
    if payload["source"] and Path(payload["source"]).resolve() != source_dir:
        raise ValueError("SID 遍历计划源目录与当前源目录不一致")
    if max_advances < int(context["start_sid_advance"]):
        raise ValueError("SID遍历最大 ADV 不能小于起点")
    expected_context = payload.get("traversal_context")
    if expected_context != context:
        raise ValueError("SID遍历计划与当前源包/参数上下文不一致，请重新准备")
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _append_log(log_path, "SID遍历启动|TID=%d|起点=%d|上限=%d" % (
        request.tid, context["start_sid_advance"], max_advances
    ))
    _append_log(
        log_path,
        "SID遍历奇偶约束|仅尝试%s ADV|步长=%d"
        % (
            "偶数" if context["sid_advance_parity"] == 0 else "奇数",
            context["sid_advance_step"],
        ),
    )
    _append_log(
        log_path,
        f"SID遍历目标搜索范围|ADV={request.min_advances}-{target_max_advances}",
    )
    runner_warnings: list[str] = []
    runner = prepare_compat_runner(
        ezcon_path,
        fingerprint_warning_only=fingerprint_warnings,
        fingerprint_warnings=runner_warnings,
    )
    for warning in runner_warnings:
        _append_log(log_path, warning)

    profile = None
    if label_override_profile is not None:
        profile = load_label_override_profile(label_override_profile)

    state_report = {
        "schema": 2,
        "status": "running",
        "run_id": run_id,
        "encounter_kind": context["encounter_kind"],
        "route_key": context["route_key"],
        "template_name": context["template_name"],
        "context": context,
        "progress_path": str(progress_path(progress_dir, context)),
        "candidates": [],
    }
    _write_report(report_path, state_report)
    with SIDTraversalSession(progress_dir, context, resume=True) as session:
        def save_report(status: str | None = None) -> None:
            if status is not None:
                state_report["status"] = status
            current = session.current_sid_advance
            state_report.update({
                "state": session.state,
                "next_sid_advance": session.next_sid_advance,
                "current_candidate": (
                    {"sid_advance": current, "sid": session.state.get("current_sid"),
                     "attempt_id": session.state.get("attempt_id"),
                     "phase": session.state.get("candidate_phase"),
                     "target": session.state.get("target_snapshot")}
                    if current is not None else None
                ),
                "tested_non_shiny_count": int(session.state.get("tested_non_shiny_count", 0)),
                "skipped_count": int(session.state.get("skipped_count", 0)),
            })
            if session.state.get("last_candidate") is not None:
                state_report["last_candidate"] = session.state["last_candidate"]
            if session.state.get("hit_evidence") is not None:
                state_report["hit_evidence"] = session.state["hit_evidence"]
            _write_report(report_path, state_report)

        if session.completed:
            state_report.update({
                "status": session.state.get("status"),
                "sid": session.state.get("hit_sid"),
                "sid_advance": session.state.get("hit_sid_advance"),
                "uniquely_determined": False if session.state.get("hit_sid") is not None else None,
            })
            save_report()
            emit_terminal("ENDED")
            _append_log(log_path, f"SID遍历已有终态：{session.state.get('last_result')}，不重复运行")
            return 0
        while session.next_sid_advance <= max_advances:
            if stop_file is not None and stop_file.is_file():
                session.pause("stop-before-candidate")
                emit_terminal("STOPPING")
                _append_log(log_path, "SID遍历已停止，当前候选保留")
                save_report("paused")
                return 130
            advance = session.next_sid_advance
            sid = session.begin_candidate(advance)
            attempt_id = str(session.state["attempt_id"])
            _emit_session(run_id, attempt_id, "sid_candidate", "SEARCHING")
            _append_log(log_path, f"SID遍历候选|ADV={advance}|SID={sid:05d}|ATTEMPT={attempt_id}|已写入起点")
            candidate_request = traversal_candidate_request(
                request, sid, target_max_advances=target_max_advances
            )
            candidate_info = {
                "sid_advance": advance,
                "sid": sid,
                "attempt_id": attempt_id,
                "status": "started",
                "target": None,
            }
            state_report["candidates"].append(candidate_info)
            save_report()
            try:
                result = search_best_plan(
                    candidate_request,
                    cancel_check=lambda: stop_file is not None and stop_file.is_file(),
                )
            except SearchWorkLimitError as exc:
                session.pause("search-work-limit")
                _emit_session(run_id, attempt_id, "sid_candidate", "FAILED")
                emit_terminal("FAILED")
                candidate_info.update({"status": "paused-work-limit", "result": str(exc)})
                _append_log(log_path, f"ADV={advance} 搜索达到工作量上限，当前候选保留：{exc}")
                save_report("paused")
                return 2
            except SearchCancelledError as exc:
                session.pause("search-cancelled")
                _emit_session(run_id, attempt_id, "sid_candidate", "STOPPING")
                emit_terminal("STOPPING")
                candidate_info.update({"status": "paused-cancelled", "result": str(exc)})
                _append_log(log_path, f"ADV={advance} 搜索已取消，当前候选保留")
                save_report("paused")
                return 130
            except (NoMatchingTargetError, NoReachablePlanError) as exc:
                session.skip_candidate(
                    "no-matching-target" if isinstance(exc, NoMatchingTargetError)
                    else "no-executable-target"
                )
                _emit_session(run_id, attempt_id, "sid_candidate", "ENDED")
                candidate_info.update({"status": "window-skipped", "result": str(exc)})
                _append_log(
                    log_path,
                    f"ADV={advance} 搜索窗口内{'无匹配目标' if isinstance(exc, NoMatchingTargetError) else '无可执行目标'}，"
                    f"记为窗口跳过并推进到 {session.next_sid_advance}",
                )
                save_report("exhausted" if session.completed else "running")
                continue
            except Exception as exc:
                session.pause(f"search-error: {exc}")
                _emit_session(run_id, attempt_id, "sid_candidate", "FAILED")
                emit_terminal("FAILED")
                candidate_info.update({"status": "error", "result": str(exc)})
                _append_log(log_path, f"ADV={advance} 搜索异常，保留当前起点：{exc}")
                save_report("paused")
                return 1

            session.set_candidate_phase("generating")
            if stop_file is not None and stop_file.is_file():
                session.pause("stop-before-generation")
                _emit_session(run_id, attempt_id, "sid_candidate", "STOPPING")
                emit_terminal("STOPPING")
                _append_log(log_path, "SID遍历已停止，当前候选保留")
                save_report("paused")
                return 130
            candidate_dir = output_dir / "candidates" / f"adv-{advance:05d}-sid-{sid:05d}-attempt-{attempt_id}"
            try:
                candidate_options = replace(options, nx_model=2 if candidate_request.game.endswith("nx2") else 1)
                target = result.plan.target
                target_spec = TargetVerificationSpec(
                    run_id=run_id,
                    attempt_id=attempt_id,
                    target_seed=target.target_seed,
                    target_advances=int(result.plan.initial_seed.advances),
                    species_id=get_species_id(target.pokemon),
                    method=target.method,
                    pid_hex=target.pid,
                )
                target_snapshot = {
                    "target_seed": str(target.target_seed).upper(),
                    "target_advances": int(result.plan.initial_seed.advances),
                    "species": str(target.pokemon),
                    "species_id": get_species_id(target.pokemon),
                    "algorithm": str(target.method),
                    "pid": str(target.pid).upper(),
                }
                candidate_info.update(target_snapshot)
                candidate_info["target"] = target_snapshot
                session.set_candidate_target(target_snapshot)
                main_path = write_configured_project(
                    source_dir,
                    candidate_dir,
                    result.plan,
                    candidate_options,
                    template_name=payload["template_name"],
                    precalibration_store_path=payload["precalibration_store_path"],
                    target_verification=target_spec,
                )
                if profile is not None:
                    apply_profile_to_projects(candidate_dir, profile)
                check = validate_runtime(
                    ezcon_path,
                    main_path,
                    fingerprint_warning_only=fingerprint_warnings,
                )
                if not check.ok:
                    raise RuntimeError("\n".join(check.errors))
            except Exception as exc:
                session.pause(f"project-error: {exc}")
                _emit_session(run_id, attempt_id, "sid_candidate", "FAILED")
                emit_terminal("FAILED")
                candidate_info.update({"status": "error", "result": str(exc)})
                _append_log(log_path, f"ADV={advance} 工程生成/预检异常，保留当前起点：{exc}")
                save_report("paused")
                return 1

            candidate_log = candidate_dir / "easycon.log"
            if stop_file is not None and stop_file.is_file():
                session.pause("stop-before-run")
                _emit_session(run_id, attempt_id, "sid_candidate", "STOPPING")
                emit_terminal("STOPPING")
                _append_log(log_path, "SID遍历已停止，当前候选保留")
                save_report("paused")
                return 130
            child_session_id = uuid.uuid4().hex
            try:
                command = build_run_command(
                    runner,
                    main_path,
                    port=port,
                    video_device=int(video),
                    video_type="DSHOW",
                    preview_port=preview_port,
                    incident_directory=incident_directory,
                    run_id=run_id,
                    workflow=workflow,
                    capture_device_name=capture_device_name,
                    label_supervision=incident_directory is not None,
                    input_session_id=child_session_id,
                    input_stage_id="sid_candidate",
                    preview_video=preview_video,
                )
                session.set_candidate_phase("running")
                _emit_session(run_id, child_session_id, "sid_candidate", "STARTING")
                code = run_logged(
                    command,
                    candidate_dir,
                    candidate_log,
                    (),
                    stop_file=stop_file,
                    on_started=lambda: _emit_session(
                        run_id, child_session_id, "sid_candidate", "RUNNING",
                    ),
                )
            except Exception as exc:
                session.pause("runner-failed")
                _emit_session(run_id, child_session_id, "sid_candidate", "FAILED")
                emit_terminal("FAILED")
                candidate_info.update({"status": "paused-runner-failed", "result": str(exc)})
                _append_log(log_path, f"ADV={advance} 运行器启动异常，保留当前候选：{exc}")
                save_report("paused")
                return 1
            candidate_text = candidate_log.read_text(encoding="utf-8", errors="replace") if candidate_log.is_file() else ""
            proof = parse_target_verification(
                candidate_text, run_id=run_id, attempt_id=attempt_id,
            )
            candidate_info.update({
                "status": "proof-received" if proof else "missing-proof",
                "exit_code": code,
                "log": str(candidate_log),
                "target_verification": proof,
            })
            _append_log(log_path, f"\n===== ADV={advance} SID={sid:05d} =====\n{candidate_text}")
            stopped = stop_file is not None and stop_file.is_file()
            if stopped:
                session.pause("stopped")
                candidate_info["status"] = "paused-stopped"
                _emit_session(run_id, child_session_id, "sid_candidate", "STOPPING")
                emit_terminal("STOPPING")
                _append_log(log_path, f"ADV={advance} 收到停止请求；保留当前候选与现有证明")
                save_report("paused")
                return 130
            _emit_session(run_id, child_session_id, "sid_candidate", "ENDED" if code == 0 else "FAILED")
            if code != 0 or easycon_log_has_fatal_error(candidate_text):
                session.pause("runner-failed")
                candidate_info["status"] = "paused-runner-failed"
                _emit_session(run_id, child_session_id, "sid_candidate", "FAILED")
                emit_terminal("FAILED")
                _append_log(log_path, f"ADV={advance} 运行器退出异常（退出码 {code}），保留当前候选")
                save_report("paused")
                return code or 1
            if proof and proof["event"] == "TARGET" and proof["seed_match"] and proof["advance_match"] and proof["species_match"] and proof["shiny"]:
                hit_evidence = {
                    "target": target_snapshot,
                    "proof": proof,
                    "attempt_id": attempt_id,
                    "log": str(candidate_log),
                }
                session.hit(sid, "verified-target-shiny", evidence=hit_evidence)
                candidate_info["status"] = "verified-candidate-hit"
                state_report.update({"status": "completed", "state": session.state,
                    "sid": sid, "sid_advance": advance, "uniquely_determined": False,
                    "hit_evidence": hit_evidence})
                _append_log(log_path, f"SID遍历验证命中候选 SID={sid:05d}，ADV={advance}；该结果不单独证明唯一性")
                save_report("completed")
                emit_terminal("ENDED")
                return 0
            if proof and proof["event"] == "TARGET" and proof["seed_match"] and proof["advance_match"] and proof["species_match"] and not proof["shiny"]:
                session.complete_non_shiny("verified-target-non-shiny")
                candidate_info["status"] = "tested-non-shiny"
                _append_log(
                    log_path,
                    f"ADV={advance} 明确完成但未出闪，下一起点按奇偶步长 "
                    f"{context['sid_advance_step']} 更新为 {session.next_sid_advance}",
                )
                save_report("exhausted" if session.completed else "running")
                continue
            reason = "non-target-shiny" if proof and proof["event"] == "NON_TARGET_SHINY" else "missing-proof"
            session.pause(reason)
            candidate_info["status"] = "paused-non-target-shiny" if reason == "non-target-shiny" else "paused-missing-proof"
            _emit_session(run_id, child_session_id, "sid_candidate", "FAILED")
            emit_terminal("FAILED")
            _append_log(log_path, f"ADV={advance} 未取得匹配本候选的完整目标证明（{reason}），保留当前起点")
            save_report("paused")
            return 1

        state_report.update({"status": "exhausted", "state": session.state})
        _append_log(log_path, "SID遍历达到上限，未发现闪光")
        save_report("exhausted")
        emit_terminal("ENDED")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="野生/定点 SID 遍历 worker")
    parser.add_argument("--request-json", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--ezcon", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--progress-dir", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--port", required=True)
    parser.add_argument("--video", required=True, type=int)
    parser.add_argument("--log-path", required=True, type=Path)
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--max-advances", type=int)
    parser.add_argument("--target-max-advances", type=int)
    parser.add_argument("--named-rival", action="store_true", default=None)
    parser.add_argument("--start-advance", type=int)
    parser.add_argument("--fingerprint-warnings", action="store_true")
    parser.add_argument("--label-override-profile", type=Path)
    parser.add_argument("--preview-port", type=int, default=0)
    parser.add_argument("--incident-dir", type=Path)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--workflow", default="sid_traversal")
    parser.add_argument("--capture-device-name", default="")
    parser.add_argument("--input-session-id", default="")
    parser.add_argument("--preview-video", action="store_true")
    args = parser.parse_args(argv)
    try:
        return run_traversal(
            plan_path=args.request_json,
            source_dir=args.source,
            ezcon_path=args.ezcon,
            output_dir=args.output,
            progress_dir=args.progress_dir,
            port=args.port,
            video=args.video,
            log_path=args.log_path,
            report_path=args.report_path,
            stop_file=args.stop_file,
            max_advances=args.max_advances,
            target_max_advances=args.target_max_advances,
            named_rival=args.named_rival,
            start_advance=args.start_advance,
            fingerprint_warnings=args.fingerprint_warnings,
            label_override_profile=args.label_override_profile,
            preview_port=args.preview_port,
            incident_directory=args.incident_dir,
            run_id=args.run_id,
            workflow=args.workflow,
            capture_device_name=args.capture_device_name,
            input_session_id=args.input_session_id,
            preview_video=args.preview_video,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit_session(
            args.run_id or uuid.uuid4().hex,
            args.input_session_id or uuid.uuid4().hex,
            "sid_traversal_terminal",
            "FAILED",
        )
        print(f"SID遍历启动失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
