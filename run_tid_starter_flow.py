# -*- coding: utf-8 -*-
"""Run the generated TID -> lab bridge -> existing 1.1.8 starter stages."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import signal
import subprocess
import sys
from typing import TextIO

from automation.easycon118 import build_run_command, prepare_compat_runner


ID_MARKER = "TIDFLOW|ID|MATCH=1"
BRIDGE_MARKER = "TIDFLOW|BRIDGE|DONE=1"
STARTER_SHINY_MARKER = "已识别到出闪，脚本停止"
STARTER_SID_MISS_MARKER = "已命中目标，脚本停止"


def classify_starter_output(lines: list[str]) -> str:
    """Classify the two terminal messages already emitted by 1.1.8."""
    if any(STARTER_SHINY_MARKER in line for line in lines):
        return "shiny"
    if any(STARTER_SID_MISS_MARKER in line for line in lines):
        return "sid_miss"
    return "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow-dir", required=True)
    parser.add_argument("--ezcon", required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--video", required=True, type=int)
    parser.add_argument("--log-path")
    return parser.parse_args()


class FlowRunner:
    def __init__(
        self,
        runner_path: Path,
        *,
        port: str,
        video_device: int,
        log: TextIO,
    ) -> None:
        self.runner_path = runner_path
        self.port = port
        self.video_device = video_device
        self.log = log
        self.current_process: subprocess.Popen[str] | None = None
        self.stop_requested = False
        self.stage_lines: list[str] = []

    def output(self, message: str) -> None:
        try:
            print(message, flush=True)
        except UnicodeEncodeError:
            encoding = getattr(sys.stdout, "encoding", None) or "ascii"
            safe_message = message.encode(encoding, errors="replace").decode(encoding)
            print(safe_message, flush=True)
        self.log.write(message + "\n")
        self.log.flush()

    def request_stop(self, _signum=None, _frame=None) -> None:
        self.stop_requested = True
        process = self.current_process
        if process is None or process.poll() is not None:
            return
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, AttributeError):
            process.terminate()

    def run_stage(
        self,
        number: int,
        name: str,
        main_path: Path,
        *,
        required_marker: str | None = None,
    ) -> int:
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


def main() -> int:
    args = parse_args()
    flow_dir = Path(args.flow_dir).resolve()
    log_path = (
        Path(args.log_path).resolve()
        if args.log_path
        else flow_dir / f"tid-starter-{datetime.now():%Y%m%d_%H%M%S}.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        runner_path = prepare_compat_runner(Path(args.ezcon))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[流程错误] EasyCon 1.6.4-a 兼容运行器检查失败：{exc}")
        return 2

    with log_path.open("w", encoding="utf-8") as log:
        flow = FlowRunner(
            runner_path,
            port=args.port.strip().upper(),
            video_device=args.video,
            log=log,
        )
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, flow.request_stop)
        signal.signal(signal.SIGINT, flow.request_stop)
        flow.output("TID/SID → 研究所 → 1.1.8 御三家连续流程")
        flow.output(f"日志：{log_path}")

        plan_path = flow_dir / "flow_plan.json"
        try:
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            corrections = [int(value) for value in payload["sid_retry_corrections"]]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            flow.output(f"[流程错误] 无法读取SID ADV重试计划：{exc}")
            return 2
        if not corrections:
            flow.output("[流程错误] SID ADV重试计划为空。")
            return 2

        return run_flow_attempts(flow, flow_dir, corrections)


if __name__ == "__main__":
    raise SystemExit(main())
