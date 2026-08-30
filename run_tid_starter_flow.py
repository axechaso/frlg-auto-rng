# -*- coding: utf-8 -*-
"""Run the generated TID -> lab bridge -> existing 1.1.8 starter stages."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime
import json
import hashlib
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tempfile
from typing import TextIO

from device_label_overrides import (
    PROJECT_OVERRIDE_FILENAME,
    LabelOverrideProfile,
    apply_profile_to_projects,
    load_label_override_profile,
)
from tid_records import recording_session
from process_control import StopFileWatcher, terminate_process_tree
from tid_session import TidProgressSession, progress_context, progress_lease
from automation.tid_checkpoint import instrument_tid_checkpoint
from automation.tid_calibration import (
    calibrated_tid_request,
    parse_tid_calibration_result,
    tid_request_from_dict,
    validate_tid_plan_runtime,
)
from automation.tid_rng137 import validate_tid_runtime, verify_tid_package, write_configured_tid_project

from automation.easycon118 import build_run_command, prepare_compat_runner, validate_runtime
from automation.tid_starter_flow import (
    build_tid_starter_flow_plan,
    resolve_exhaustive_starter_plan,
    tid_starter_flow_request_from_dict,
    write_resolved_exhaustive_starter_project,
    write_tid_starter_flow_bundle,
)


ID_MARKER = "TIDFLOW|ID|MATCH=1"
BRIDGE_MARKER = "TIDFLOW|BRIDGE|DONE=1"
STARTER_SHINY_MARKER = "已识别到出闪，脚本停止"
STARTER_SID_MISS_MARKER = "已命中目标，脚本停止"
ID_TID_PATTERN = re.compile(r"TIDFLOW\|ID\|TID=(\d{1,5})")
ID_SID_ADV_PATTERN = re.compile(r"TIDFLOW\|ID\|SID_ADV=(-?\d+)")


def classify_starter_output(lines: list[str]) -> str:
    """Classify the two terminal messages already emitted by 1.1.8."""
    if any(STARTER_SHINY_MARKER in line for line in lines):
        return "shiny"
    if any(STARTER_SID_MISS_MARKER in line for line in lines):
        return "sid_miss"
    return "unknown"


def parse_id_identity(lines: list[str]) -> tuple[int, int]:
    """Read the actual TID and SID ADV emitted by the completed ID stage."""
    tid: int | None = None
    sid_advance: int | None = None
    for line in lines:
        tid_match = ID_TID_PATTERN.search(line)
        if tid_match is not None:
            tid = int(tid_match.group(1))
        advance_match = ID_SID_ADV_PATTERN.search(line)
        if advance_match is not None:
            sid_advance = int(advance_match.group(1))
    if tid is None or sid_advance is None:
        raise ValueError("TID阶段没有输出完整的实际TID和SID ADV")
    if not 0 <= tid <= 65535:
        raise ValueError(f"TID阶段输出了非法TID：{tid}")
    if sid_advance < 0:
        raise ValueError(f"TID阶段输出了非法SID ADV：{sid_advance}")
    return tid, sid_advance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--flow-dir")
    source.add_argument("--tid-dir")
    parser.add_argument("--ezcon", required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--video", required=True, type=int)
    parser.add_argument("--log-path")
    parser.add_argument("--tid-context", type=Path)
    parser.add_argument("--tid-records", type=Path)
    parser.add_argument("--preview-port", type=int, default=0)
    parser.add_argument("--calibrate-first", action="store_true")
    parser.add_argument("--calibration-result", type=Path)
    parser.add_argument("--tid-progress-dir", type=Path)
    parser.add_argument("--tid-game", choices=("火红", "叶绿"))
    parser.add_argument("--fresh-exhaustive", action="store_true")
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--label-override-profile", type=Path)
    parser.add_argument(
        "--fingerprint-warnings",
        action="store_true",
        help="仅将已审计文件的指纹不一致记录为警告",
    )
    return parser.parse_args()


class FlowRunner:
    def __init__(
        self,
        runner_path: Path,
        *,
        port: str,
        video_device: int,
        log: TextIO,
        recording=None,
        preview_port: int = 0,
    ) -> None:
        self.runner_path = runner_path
        self.port = port
        self.video_device = video_device
        self.log = log
        self.recording = recording
        self.preview_port = preview_port
        self.current_process: subprocess.Popen[str] | None = None
        self.stop_requested = False
        self.stage_lines: list[str] = []
        self.progress = None
        self.active_stage = None
        self.id_main_override: Path | None = None

    def output(self, message: str) -> None:
        try:
            print(message, flush=True)
        except UnicodeEncodeError:
            encoding = getattr(sys.stdout, "encoding", None) or "ascii"
            safe_message = message.encode(encoding, errors="replace").decode(encoding)
            print(safe_message, flush=True)
        self.log.write(message + "\n")
        self.log.flush()
        if self.recording is not None:
            self.recording.feed(message + "\n")
        if self.progress is not None and self.active_stage == 1:
            self.progress.feed(message)

    def request_stop(self, _signum=None, _frame=None) -> None:
        self.stop_requested = True
        process = self.current_process
        if process is None or process.poll() is not None:
            return
        try:
            terminate_process_tree(process)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            self.output(f"[停止警告] 子进程未退出，等待工具清理本次进程树：{exc}")

    def run_stage(
        self,
        number: int,
        name: str,
        main_path: Path,
        *,
        required_marker: str | None = None,
    ) -> int:
        if self.stop_requested:
            self.output("[流程停止] 已收到用户停止请求，不启动下一阶段。")
            return 130
        self.active_stage = number
        if number == 1 and self.id_main_override is not None:
            main_path = self.id_main_override
        if not main_path.is_file():
            self.output(f"[流程错误] 找不到第{number}阶段脚本：{main_path}")
            return 2
        self.output("")
        self.output(f"========== 第{number}阶段：{name} ==========")
        self.output(f"脚本：{main_path}")
        command = build_run_command(
            self.runner_path,
            main_path,
            port=self.port,
            video_device=self.video_device,
            video_type="DSHOW",
            preview_port=self.preview_port,
        )
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        marker_seen = required_marker is None
        self.stage_lines = []
        try:
            self.current_process = subprocess.Popen(
                command,
                cwd=str(main_path.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=flags,
            )
            assert self.current_process.stdout is not None
            if self.stop_requested:
                self.request_stop()
            for raw_line in self.current_process.stdout:
                line = raw_line.rstrip("\r\n")
                self.stage_lines.append(line)
                self.output(line)
                if required_marker is not None and required_marker in line:
                    marker_seen = True
                if self.stop_requested:
                    self.request_stop()
            exit_code = self.current_process.wait()
        except OSError as exc:
            self.output(f"[流程错误] 第{number}阶段无法启动：{exc}")
            return 2
        finally:
            if self.current_process is not None and self.current_process.stdout is not None:
                self.current_process.stdout.close()
            self.current_process = None

        if self.stop_requested:
            self.output("[流程停止] 已收到用户停止请求。")
            return 130
        if exit_code != 0:
            self.output(f"[流程错误] 第{number}阶段退出码：{exit_code}")
            return exit_code or 1
        if not marker_seen:
            self.output(
                f"[流程错误] 第{number}阶段正常退出，但没有看到成功标记：{required_marker}"
            )
            return 3
        self.output(f"[流程完成] 第{number}阶段已完成。")
        return 0


def run_flow_attempts(flow: FlowRunner, flow_dir: Path, corrections: list[int]) -> int:
    """Run complete save attempts until 1.1.8 confirms a shiny starter."""
    bridge_main = flow_dir / "02_lab_bridge" / "main.ecs"
    starter_main = flow_dir / "03_starter_118" / "main.ecs"
    for attempt_index, correction in enumerate(corrections):
        flow.output("")
        flow.output(
            f"########## 建档尝试 {attempt_index + 1}/{len(corrections)}："
            f"SID ADV修正 {correction:+d} ##########"
        )
        id_main = flow_dir / "01_id" / f"main_attempt_{attempt_index:03d}.ecs"
        code = flow.run_stage(1, "TID/SID 1.3.7", id_main, required_marker=ID_MARKER)
        if code != 0:
            return code
        code = flow.run_stage(2, "研究所桥接与存档", bridge_main, required_marker=BRIDGE_MARKER)
        if code != 0:
            return code
        code = flow.run_stage(3, "1.1.8 御三家全自动乱数", starter_main)
        if code != 0:
            return code

        starter_result = classify_starter_output(flow.stage_lines)
        if starter_result == "shiny":
            flow.output("")
            flow.output(
                f"[流程完成] 已确认闪光御三家；成功使用SID ADV修正 {correction:+d}。"
            )
            return 0
        if starter_result == "sid_miss":
            flow.output(
                "[SID未命中] 1.1.8已精确命中目标Seed/帧，但御三家不闪；"
                "将使用下一个SID ADV修正重新建档。"
            )
            continue
        flow.output(
            "[流程错误] 1.1.8已退出，但没有看到闪光成功或精确目标非闪标记。"
        )
        return 4

    flow.output("[流程结束] 已用完SID ADV重试范围，仍未得到闪光御三家。")
    return 5


def run_exhaustive_flow(
    flow: FlowRunner,
    flow_dir: Path,
    payload: dict[str, object],
    ezcon_path: Path,
    *,
    fingerprint_warning_only: bool = False,
    label_profile: LabelOverrideProfile | None = None,
) -> int:
    """Continue from an exhaustive TID hit using its real TID and SID ADV."""
    id_main = flow_dir / "01_id" / "main_attempt_000.ecs"
    bridge_main = flow_dir / "02_lab_bridge" / "main.ecs"
    starter_main = flow_dir / "03_starter_118" / "main.ecs"

    code = flow.run_stage(1, "TID 1.3.7穷举", id_main, required_marker=ID_MARKER)
    if code != 0:
        return code
    try:
        actual_tid, sid_advance = parse_id_identity(flow.stage_lines)
        request_payload = payload["request"]
        if not isinstance(request_payload, dict):
            raise ValueError("flow_plan.json中的request格式无效")
        request = tid_starter_flow_request_from_dict(request_payload)
        resolved = resolve_exhaustive_starter_plan(
            request,
            actual_tid=actual_tid,
            sid_advance=sid_advance,
        )
        starter_source_dir = Path(str(payload["starter_source_dir"])).resolve()
        write_resolved_exhaustive_starter_project(
            starter_source_dir,
            starter_main.parent,
            resolved,
        )
        if label_profile is not None:
            apply_profile_to_projects(starter_main.parent, label_profile)
    except (KeyError, OSError, TypeError, ValueError, LookupError) as exc:
        flow.output(f"[流程错误] 无法根据实际TID/SID ADV生成御三家目标：{exc}")
        return 2

    target = resolved.starter_target
    flow.output(
        f"[穷举衔接] 实际TID={resolved.tid:05d} / SID ADV={resolved.sid_advance} / "
        f"计算SID={resolved.sid:05d}"
    )
    flow.output(
        f"[穷举衔接] 御三家目标 Seed={target.seed_hex} / "
        f"ADV={target.advances} / PID={target.pid_hex}"
    )
    try:
        check = (
            validate_runtime(
                ezcon_path,
                starter_main,
                fingerprint_warning_only=True,
            )
            if fingerprint_warning_only
            else validate_runtime(ezcon_path, starter_main)
        )
    except (OSError, ValueError, RuntimeError) as exc:
        flow.output(f"[流程错误] 动态御三家工程预检异常：{exc}")
        return 2
    if not check.ok:
        for error in check.errors:
            flow.output(f"[流程错误] 动态御三家工程预检失败：{error}")
        return 2

    code = flow.run_stage(2, "研究所桥接与存档", bridge_main, required_marker=BRIDGE_MARKER)
    if code != 0:
        return code
    code = flow.run_stage(3, "1.1.8 御三家全自动乱数", starter_main)
    if code != 0:
        return code
    starter_result = classify_starter_output(flow.stage_lines)
    if starter_result == "shiny":
        flow.output("[流程完成] 已按穷举获得的实际TID/SID确认闪光御三家。")
        return 0
    if starter_result == "sid_miss":
        flow.output(
            "[流程结束] 已精确命中御三家目标PID但没有出闪；"
            "实际SID ADV与实机结果可能存在偏差，保留日志停止。"
        )
        return 5
    flow.output("[流程错误] 御三家阶段没有看到闪光成功或精确目标非闪标记。")
    return 4


def run_tid_plan(
    flow: FlowRunner,
    plan_dir: Path,
    ezcon_path: Path,
    *,
    is_flow: bool,
    calibrate_first: bool = False,
    result_path: Path | None = None,
    progress_dir: Path | None = None,
    game: str | None = None,
    resume: bool = True,
    fingerprint_warning_only: bool = False,
    label_profile: LabelOverrideProfile | None = None,
) -> int:
    """Own calibration and continuation even if the GUI has been closed."""
    try:
        if flow.stop_requested:
            return 130
        if label_profile is not None:
            applied = apply_profile_to_projects(plan_dir, label_profile)
            if applied:
                flow.output(
                    f"[设备标签] 已验证并应用 {label_profile.capture_device}："
                    f"{sum(len(item.installed) for item in applied)} 个工程标签覆盖"
                )
        if is_flow:
            payload = json.loads((plan_dir / "flow_plan.json").read_text(encoding="utf-8"))
            flow_request = tid_starter_flow_request_from_dict(payload["request"])
            request = flow_request.tid_request
            id_dir = plan_dir / "01_id"
        else:
            payload = None
            id_dir = plan_dir
            request = tid_request_from_dict(
                json.loads((id_dir / "plan.json").read_text(encoding="utf-8"))["tid_request"]
            )

        if calibrate_first:
            if result_path is None:
                raise ValueError("检测后自动运行需要独立的固定延迟结果文件")
            calibration_dir = plan_dir / "00_calibration"
            calibration_manifest = json.loads(
                (calibration_dir / "plan.json").read_text(encoding="utf-8")
            )
            initial = tid_request_from_dict(calibration_manifest["tid_request"])
            if not initial.calibration_check or replace(initial, calibration_check=False) != request:
                raise ValueError("固定延迟检测与正式计划的参数快照不一致，请重新生成")
            check = (
                validate_tid_runtime(
                    ezcon_path,
                    calibration_dir / "main.ecs",
                    fingerprint_warning_only=True,
                )
                if fingerprint_warning_only
                else validate_tid_runtime(ezcon_path, calibration_dir / "main.ecs")
            )
            if not check.ok:
                raise ValueError("固定延迟脚本预检失败：" + "; ".join(check.errors))
            code = flow.run_stage(0, "固定延迟检测（完成后自动执行计划）", calibration_dir / "main.ecs")
            if code != 0:
                return code
            if flow.stop_requested:
                return 130
            values = parse_tid_calibration_result("\n".join(flow.stage_lines), initial.op_correction)
            request = calibrated_tid_request(initial, values)
            result = {"schema": 1, "initial_request": initial.to_dict(),
                      "values": values, "request": request.to_dict()}
            result_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_result = result_path.with_suffix(result_path.suffix + ".tmp")
            temporary_result.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary_result.replace(result_path)
            flow.output(
                f"[固定延迟完成] OP={values['OP']} / F1={values['F1']} / F2={values['F2']} / "
                f"F3={values['F3']} / OP修正={values['OP_CORRECTION']} ms；正在重新生成正式计划。"
            )
            if flow.stop_requested:
                return 130
            source = Path(calibration_manifest["source"])
            # JSON stringifies numeric label-method keys in the saved manifest.
            fingerprint_warnings: list[str] = []
            current_manifest = json.loads(json.dumps(verify_tid_package(
                source,
                fingerprint_warning_only=fingerprint_warning_only,
                fingerprint_warnings=fingerprint_warnings,
            )))
            for warning in fingerprint_warnings:
                flow.output(warning)
            if current_manifest != calibration_manifest["source_manifest"]:
                raise ValueError("检测期间TID源包发生变化，请重新生成计划")
            # A new directory protects the original plan and all previous runs.
            plan_dir = Path(tempfile.mkdtemp(prefix="tid-calibrated-", dir=result_path.parent))
            if is_flow:
                updated_plan = build_tid_starter_flow_plan(replace(flow_request, tid_request=request))
                write_tid_starter_flow_bundle(
                    source, plan_dir, updated_plan,
                    starter_source_dir=Path(payload["starter_source_dir"]),
                    fingerprint_warning_only=fingerprint_warning_only,
                    fingerprint_warnings=fingerprint_warnings,
                )
                payload = json.loads((plan_dir / "flow_plan.json").read_text(encoding="utf-8"))
            else:
                write_configured_tid_project(
                    source,
                    plan_dir,
                    request,
                    fingerprint_warning_only=fingerprint_warning_only,
                    fingerprint_warnings=fingerprint_warnings,
                )
            if label_profile is not None:
                apply_profile_to_projects(plan_dir, label_profile)
            if flow.stop_requested:
                return 130
            for warning in dict.fromkeys(fingerprint_warnings):
                flow.output(warning)
            check = validate_tid_plan_runtime(
                ezcon_path,
                plan_dir,
                is_flow=is_flow,
                **(
                    {"fingerprint_warning_only": True}
                    if fingerprint_warning_only
                    else {}
                ),
            )
            if not check.ok:
                raise ValueError("测量值回填后的正式计划预检失败：" + "; ".join(check.errors))
            if flow.stop_requested:
                return 130
            if flow.recording is not None:
                flow.recording.update_request(request)
            flow.output(f"[固定延迟衔接] 新计划已通过1.6.4-a预检，自动继续：{plan_dir}")

        if flow.stop_requested:
            return 130
        if progress_dir is not None and request.mode == 0:
            id_dir = plan_dir / "01_id" if is_flow else plan_dir
            manifest = json.loads((id_dir / "plan.json").read_text(encoding="utf-8"))
            actual_request = tid_request_from_dict(manifest["tid_request"])
            template_hash = manifest["source_manifest"]["scripts"][actual_request.language]["sha256"]
            context = progress_context(
                actual_request, game, template_hash,
                payload["request"] if is_flow else None,
            )
            # Acquire the lease before any new ID game operation. The worker,
            # not the GUI, owns writes even when its parent window is closed.
            with TidProgressSession(progress_dir, context, resume=resume) as progress:
                source_main = id_dir / ("main_attempt_000.ecs" if is_flow else "main.ecs")
                configured = instrument_tid_checkpoint(
                    source_main.read_text(encoding="utf-8-sig"), actual_request, progress.state
                )
                runtime_dir = Path(tempfile.mkdtemp(prefix="tid-resume-", dir=plan_dir.parent))
                main = runtime_dir / "main.ecs"
                main.write_text(configured, encoding="utf-8")
                shutil.copytree(id_dir / "ImgLabel", runtime_dir / "ImgLabel")
                override_sidecar = id_dir / PROJECT_OVERRIDE_FILENAME
                if override_sidecar.is_file():
                    shutil.copy2(
                        override_sidecar,
                        runtime_dir / PROJECT_OVERRIDE_FILENAME,
                    )
                (runtime_dir / "progress_context.json").write_text(
                    json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                check = (
                    validate_tid_runtime(
                        ezcon_path,
                        main,
                        fingerprint_warning_only=True,
                    )
                    if fingerprint_warning_only
                    else validate_tid_runtime(ezcon_path, main)
                )
                if not check.ok:
                    raise ValueError("穷举续跑脚本预检失败：" + "; ".join(check.errors))
                if flow.stop_requested:
                    return 130
                flow.id_main_override = main
                flow.progress = progress
                if progress.state:
                    state = progress.state
                    flow.output(f"[TID续跑] 恢复搜索层级{state['STAGE']}，OP/F1/F2偏移="
                                f"{state['OP']}/{state['F1']}/{state['F2']}；当前点重新进行去噪观察。")
                else:
                    flow.output("[TID进度] 从所填起点开始，逐轮自动保存穷举进度。")
                flow.output(f"[TID进度] {progress.path}")
                try:
                    if is_flow:
                        return run_exhaustive_flow(
                            flow,
                            plan_dir,
                            payload,
                            ezcon_path,
                            fingerprint_warning_only=fingerprint_warning_only,
                            label_profile=label_profile,
                        )
                    return flow.run_stage(1, "TID/SID正式计划", main)
                finally:
                    flow.progress = None
                    flow.id_main_override = None
        if not is_flow:
            return flow.run_stage(1, "TID/SID正式计划", plan_dir / "main.ecs")
        corrections = [int(value) for value in payload["sid_retry_corrections"]]
        if not corrections:
            raise ValueError("SID ADV重试计划为空")
        if bool(payload.get("deferred_identity")):
            return run_exhaustive_flow(
                flow,
                plan_dir,
                payload,
                ezcon_path,
                fingerprint_warning_only=fingerprint_warning_only,
                label_profile=label_profile,
            )
        return run_flow_attempts(flow, plan_dir, corrections)
    except (OSError, KeyError, TypeError, ValueError, RuntimeError, LookupError) as exc:
        flow.output(f"[流程错误] 不启动后续脚本：{exc}")
        return 2


def main() -> int:
    args = parse_args()
    flow_dir = Path(args.flow_dir or args.tid_dir).resolve()
    log_path = (
        Path(args.log_path).resolve()
        if args.log_path
        else flow_dir / f"tid-starter-{datetime.now():%Y%m%d_%H%M%S}.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        label_profile = (
            load_label_override_profile(args.label_override_profile)
            if args.label_override_profile is not None
            else None
        )
        runner_warnings: list[str] = []
        runner_path = (
            prepare_compat_runner(
                Path(args.ezcon),
                fingerprint_warning_only=True,
                fingerprint_warnings=runner_warnings,
            )
            if args.fingerprint_warnings
            else prepare_compat_runner(Path(args.ezcon))
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[流程错误] EasyCon 1.6.4-a 兼容运行器检查失败：{exc}")
        return 2

    with log_path.open("w", encoding="utf-8") as log, recording_session(
        args.tid_context, args.tid_records, log_path, flow=True,
        warning=lambda message: log.write(message + "\n"),
    ) as recording, ExitStack() as leases:
        if args.tid_progress_dir is not None:
            port_key = hashlib.sha256(args.port.strip().upper().encode("utf-8")).hexdigest()
            try:
                leases.enter_context(progress_lease(args.tid_progress_dir / ("device-" + port_key + ".lock")))
            except (OSError, RuntimeError) as exc:
                log.write(f"[流程停止] {exc}\n")
                print(f"[流程停止] {exc}")
                return 2
        flow = FlowRunner(
            runner_path,
            port=args.port.strip().upper(),
            video_device=args.video,
            log=log,
            recording=recording,
            preview_port=args.preview_port,
        )
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, flow.request_stop)
        signal.signal(signal.SIGINT, flow.request_stop)
        flow.output("TID/SID → 研究所 → 1.1.8 御三家连续流程" if args.flow_dir else "TID/SID计划")
        flow.output(f"日志：{log_path}")
        for warning in runner_warnings:
            flow.output(warning)

        with StopFileWatcher(args.stop_file, flow.request_stop) as stop:
            if stop.requested:
                flow.request_stop()
            return run_tid_plan(
                flow, flow_dir, Path(args.ezcon).resolve(),
                is_flow=bool(args.flow_dir), calibrate_first=args.calibrate_first,
                result_path=args.calibration_result,
                progress_dir=args.tid_progress_dir, game=args.tid_game,
                resume=not args.fresh_exhaustive,
                fingerprint_warning_only=args.fingerprint_warnings,
                label_profile=label_profile,
            )


if __name__ == "__main__":
    raise SystemExit(main())
