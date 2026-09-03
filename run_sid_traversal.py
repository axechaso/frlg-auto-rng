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

from app_paths import DATA_ROOT, RESOURCE_ROOT
from automation import (
    AutoSearchRequest,
    DEFAULT_EZCON_PATH,
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
from device_label_overrides import apply_profile_to_projects, load_label_override_profile
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
DEFAULT_SOURCE = (
    RESOURCE_ROOT / "local_assets" / "easycon118"
    if (RESOURCE_ROOT / "local_assets" / "easycon118").is_dir()
    else Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8"
)
DEFAULT_OUTPUT = DATA_ROOT / "runtime" / "sid_traversal"
DEFAULT_PROGRESS = DATA_ROOT / "sid_traversal_progress"
DEFAULT_TARGET_MAX_ADVANCES = SID_TRAVERSAL_DEFAULT_TARGET_MAX_ADVANCES
FLASH_MARKERS = ("已识别到出闪，脚本停止", "已识别到出闪")
NON_SHINY_MARKERS = ("已命中目标，脚本停止",)


def _request_from_payload(payload: dict) -> AutoSearchRequest:
    values = payload.get("request", payload)
    if not isinstance(values, dict):
        raise ValueError("SID遍历计划缺少 request 对象")
    allowed = {field.name for field in __import__("dataclasses").fields(AutoSearchRequest)}
    filtered = {key: value for key, value in values.items() if key in allowed}
    # JSON arrays are accepted by the dataclass but tuples make the immutable
    # request and context representation explicit for callers/tests.
    for name in ("iv_min", "iv_max"):
        if name in filtered:
            filtered[name] = tuple(int(item) for item in filtered[name])
    request = AutoSearchRequest(**filtered)
    request.validate()
    if "Wild" not in request.method:
        raise ValueError("SID遍历只支持野生遭遇")
    return request


def _options_from_payload(payload: dict) -> EasyCon118Options:
    values = payload.get("easycon_options", {})
    if not isinstance(values, dict):
        raise ValueError("SID遍历计划缺少 EasyCon 选项")
    allowed = {field.name for field in __import__("dataclasses").fields(EasyCon118Options)}
    values = {key: value for key, value in values.items() if key in allowed}
    options = EasyCon118Options(**values)
    # Traversal needs the regular shiny-stop path.  Item mode would keep the
    # script running after a shiny encounter and cannot confirm the SID.
    return replace(options, item_rng_mode=False, party_empty_slots=1,
                   continue_capture_after_shiny=False)


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


def completion_kind(log_text: str) -> str | None:
    """Classify only explicit script completion markers."""
    if any(marker in log_text for marker in FLASH_MARKERS):
        return "shiny"
    if any(marker in log_text for marker in NON_SHINY_MARKERS):
        return "non-shiny"
    return None


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
    return _request_from_payload(payload), _options_from_payload(payload), payload


def _append_log(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as stream:
        stream.write(text)
        if text and not text.endswith("\n"):
            stream.write("\n")


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
    max_advances: int = DEFAULT_MAX_ADVANCES,
    target_max_advances: int = DEFAULT_TARGET_MAX_ADVANCES,
    named_rival: bool = False,
    start_advance: int | None = None,
    fingerprint_warnings: bool = False,
    label_override_profile: Path | None = None,
    preview_port: int = 0,
) -> int:
    request, options, payload = _load_plan(plan_path)
    source_dir = source_dir.resolve()
    ezcon_path = ezcon_path.resolve()
    output_dir = output_dir.resolve()
    progress_dir = progress_dir.resolve()
    max_advances = int(max_advances)
    target_max_advances = int(target_max_advances)
    if not port.strip():
        raise ValueError("串口不能为空")
    source_corpus = inspect_script_corpus(source_dir)
    resolved_start = (
        start_advance
        if start_advance is not None
        else payload.get("start_sid_advance")
    )
    context = traversal_context(
        tid=request.tid,
        named_rival=named_rival,
        wild_request=asdict(request),
        easycon_options=asdict(options),
        source_sha256=source_corpus["sha256"],
        max_advances=max_advances,
        start_advance=resolved_start,
        target_max_advances=target_max_advances,
    )
    if max_advances < int(context["start_sid_advance"]):
        raise ValueError("SID遍历最大 ADV 不能小于起点")
    expected_context = payload.get("traversal_context")
    if expected_context is not None and expected_context != context:
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
        "schema": 1,
        "status": "running",
        "context": context,
        "progress_path": str(progress_path(progress_dir, context)),
        "candidates": [],
    }
    _write_report(report_path, state_report)
    with SIDTraversalSession(progress_dir, context, resume=True) as session:
        if session.completed:
            state_report.update({"status": session.state.get("status"), "state": session.state})
            _write_report(report_path, state_report)
            _append_log(log_path, f"SID遍历已有终态：{session.state.get('last_result')}，不重复运行")
            return 0
        while session.next_sid_advance <= max_advances:
            if stop_file is not None and stop_file.is_file():
                session.pause("stop-before-candidate")
                _append_log(log_path, "SID遍历已停止，当前候选保留")
                state_report.update({"status": "paused", "state": session.state})
                _write_report(report_path, state_report)
                return 130
            advance = session.next_sid_advance
            sid = session.begin_candidate(advance)
            _append_log(log_path, f"SID遍历候选|ADV={advance}|SID={sid:05d}|已写入起点")
            candidate_request = traversal_candidate_request(
                request, sid, target_max_advances=target_max_advances
            )
            candidate_info = {
                "sid_advance": advance,
                "sid": sid,
                "status": "started",
            }
            state_report["candidates"].append(candidate_info)
            _write_report(report_path, {**state_report, "state": session.state})
            try:
                result = search_best_plan(candidate_request)
            except (NoMatchingTargetError, NoReachablePlanError, SearchWorkLimitError) as exc:
                # No target in the bounded low-frame mathematical search is a
                # confirmed non-shiny candidate and is safe to advance.
                session.complete_non_shiny("no-low-frame-shiny-target")
                candidate_info.update({"status": "non-shiny", "result": str(exc)})
                _append_log(
                    log_path,
                    f"ADV={advance} 无低帧闪光目标，起点按奇偶步长 {context['sid_advance_step']} "
                    f"更新为 {session.next_sid_advance}",
                )
                _write_report(report_path, {**state_report, "state": session.state})
                continue
            except Exception as exc:
                session.pause(f"search-error: {exc}")
                candidate_info.update({"status": "error", "result": str(exc)})
                _append_log(log_path, f"ADV={advance} 搜索异常，保留当前起点：{exc}")
                _write_report(report_path, {**state_report, "status": "paused", "state": session.state})
                return 1

            candidate_dir = output_dir / "candidates" / f"adv-{advance:05d}-sid-{sid:05d}"
            try:
                candidate_options = replace(options, nx_model=2 if candidate_request.game.endswith("nx2") else 1)
                main_path = write_configured_project(
                    source_dir,
                    candidate_dir,
                    result.plan,
                    candidate_options,
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
                candidate_info.update({"status": "error", "result": str(exc)})
                _append_log(log_path, f"ADV={advance} 工程生成/预检异常，保留当前起点：{exc}")
                _write_report(report_path, {**state_report, "status": "paused", "state": session.state})
                return 1

            candidate_log = candidate_dir / "easycon.log"
            command = build_run_command(
                runner,
                main_path,
                port=port,
                video_device=int(video),
                video_type="DSHOW",
                preview_port=preview_port,
            )
            code = run_logged(
                command,
                candidate_dir,
                candidate_log,
                tuple((*FLASH_MARKERS[:1], *NON_SHINY_MARKERS)),
                stop_file=stop_file,
            )
            candidate_text = candidate_log.read_text(encoding="utf-8", errors="replace") if candidate_log.is_file() else ""
            kind = completion_kind(candidate_text)
            candidate_info.update({"status": kind or "incomplete", "exit_code": code, "log": str(candidate_log)})
            _append_log(log_path, f"\n===== ADV={advance} SID={sid:05d} =====\n{candidate_text}")
            if kind == "shiny":
                session.hit(sid, "shiny-confirmed")
                state_report.update({"status": "completed", "state": session.state, "sid": sid, "sid_advance": advance})
                _append_log(log_path, f"SID遍历确认出闪，正确SID={sid:05d}，ADV={advance}")
                _write_report(report_path, state_report)
                return 0
            if kind == "non-shiny" and code == 0:
                session.complete_non_shiny("non-shiny-confirmed")
                _append_log(
                    log_path,
                    f"ADV={advance} 明确完成但未出闪，下一起点按奇偶步长 "
                    f"{context['sid_advance_step']} 更新为 {session.next_sid_advance}",
                )
                _write_report(report_path, {**state_report, "state": session.state})
                continue
            session.pause("stopped-before-explicit-completion" if code == 130 else "missing-completion-marker")
            _append_log(log_path, f"ADV={advance} 未取得明确完成标记，保留当前起点")
            state_report.update({"status": "paused", "state": session.state})
            _write_report(report_path, state_report)
            return 130 if code == 130 else 1

        state_report.update({"status": "exhausted", "state": session.state})
        _append_log(log_path, "SID遍历达到上限，未发现闪光")
        _write_report(report_path, state_report)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="野生 SID 遍历 worker")
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
    parser.add_argument("--max-advances", type=int, default=DEFAULT_MAX_ADVANCES)
    parser.add_argument("--target-max-advances", type=int, default=DEFAULT_TARGET_MAX_ADVANCES)
    parser.add_argument("--named-rival", action="store_true")
    parser.add_argument("--start-advance", type=int)
    parser.add_argument("--fingerprint-warnings", action="store_true")
    parser.add_argument("--label-override-profile", type=Path)
    parser.add_argument("--preview-port", type=int, default=0)
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
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"SID遍历启动失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
