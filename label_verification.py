"""Native EasyCon 1.6.4-a label verification through the pinned runner."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def verify_label(
    runner: str | Path,
    label: str | Path,
    *,
    frame: str | Path | None = None,
    device: int = 0,
    video_type: str = "DSHOW",
    frames: int = 3,
    interval_ms: int = 250,
    operator: str = ">",
    threshold: int = 95,
    save_frame: str | Path | None = None,
    save_frames_directory: str | Path | None = None,
) -> tuple[dict[str, object], ...]:
    """Run the compatibility runner's exact ImgLabel.Search implementation.

    An offline invocation tests one source PNG. A live invocation opens one
    EasyCon capture owner and evaluates distinct incoming frames without
    attaching a gamepad or running an ECS.
    """
    runner = Path(runner).resolve()
    label = Path(label).resolve()
    if not runner.is_file():
        raise FileNotFoundError(f"找不到固定版 EasyCon 兼容运行器: {runner}")
    if not label.is_file():
        raise FileNotFoundError(f"找不到标签文件: {label}")
    if operator not in {">", ">=", "<", "<="}:
        raise ValueError("标签判定条件必须是 >、>=、< 或 <=")
    if not 1 <= frames <= 100 or not 0 <= interval_ms <= 10000:
        raise ValueError("动态测试帧数须为 1–100，帧间隔须为 0–10000 ms")
    command = [
        str(runner), "verify-label", str(label),
        "--device", str(device), "--videotype", video_type,
        "--frames", str(frames), "--interval-ms", str(interval_ms),
        "--operator", operator, "--threshold", str(threshold),
    ]
    if frame is not None:
        frame = Path(frame).resolve()
        if not frame.is_file():
            raise FileNotFoundError(f"找不到原始画面: {frame}")
        command += ["--frame", str(frame)]
    if save_frame is not None:
        command += ["--save-frame", str(Path(save_frame).resolve())]
    if save_frames_directory is not None:
        command += ["--save-frames-dir", str(Path(save_frames_directory).resolve())]
    timeout = max(30, 15 + frames * (interval_ms / 1000))
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"固定版 EasyCon 原生标签测试启动失败: {exc}") from exc
    records: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    if result.returncode != 0:
        detail = next((str(item["error"]) for item in records if item.get("error")), result.stderr.strip())
        raise RuntimeError(detail or f"原生标签测试退出码 {result.returncode}")
    if not records or any(item.get("error") for item in records):
        detail = next((str(item["error"]) for item in records if item.get("error")), "原生标签测试没有返回结果")
        raise RuntimeError(detail)
    if frame is not None and len(records) != 1:
        raise RuntimeError(f"离线标签测试返回了 {len(records)} 条结果，预期 1 条")
    if frame is None and len(records) != frames:
        raise RuntimeError(f"动态标签测试只得到 {len(records)}/{frames} 张有效新画面")
    return tuple(records)
