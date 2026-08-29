"""Run the EasyCon SID collector one party slot at a time and analyze it."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from process_control import StopFileWatcher, terminate_process_tree
import sys
from typing import Callable

from automation.easycon118 import (
    DEFAULT_EZCON_PATH,
    build_run_command,
    prepare_compat_runner,
    probe_easycon_devices,
    validate_runtime,
)
from automation.sid_reverse118 import (
    SIDReverseRunRequest,
    write_sid_reverse_plan,
    write_sid_reverse_project,
)
from rng.sid_reverse_workflow import (
    analyze_observed_pokemon,
    parse_sid_reverse_log,
    resolve_wild_location,
)
from run_sid_reverse import build_report


DEFAULT_SOURCE = Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "runtime" / "sid_reverse"
ZERO_EVS = (0, 0, 0, 0, 0, 0)


def _safe_print(message="", *, file=None, end="\n") -> None:
    """Print Chinese status text even when a Windows console uses cp1252."""
    target = file or sys.stdout
    text = str(message)
    try:
        print(text, file=target, end=end)
    except UnicodeEncodeError:
        encoding = getattr(target, "encoding", None) or "ascii"
        safe_text = text.encode(encoding, errors="replace").decode(encoding)
        print(safe_text, file=target, end=end)


def load_sid_reverse_request(path: Path) -> SIDReverseRunRequest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("request", payload)
    try:
        request = SIDReverseRunRequest(
            tid=int(values["tid"]),
            party_count=int(values["party_count"]),
            game=str(values.get("game", "fr_nx")),
            nx_model=int(values.get("nx_model", 1)),
            start_slot=int(values.get("start_slot", 1)),
            max_candies=int(values.get("max_candies", 5)),
            recognition_threshold=int(values.get("recognition_threshold", 85)),
            home_buffer_adaptive_threshold=values.get(
                "home_buffer_adaptive_threshold", False
            ),
            dex_overrides=tuple(int(item) for item in values.get("dex_overrides", (0,) * 6)),
            initial_levels=tuple(int(item) for item in values["initial_levels"]),
            source_types=tuple(int(item) for item in values.get("source_types", (0,) * 6)),
            locations=tuple(str(item) for item in values.get("locations", ("",) * 6)),
            effort_values=tuple(
                tuple(int(item) for item in slot)
                for slot in values.get("effort_values", (ZERO_EVS,) * 6)
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"无效的 SID 查找请求文件: {path}") from exc
    request.validate()
    return request


def _ask_int(prompt: str, minimum: int, maximum: int) -> int:
    while True:
        try:
            value = int(input(prompt).strip())
        except ValueError:
            _safe_print("请输入整数。")
            continue
        if minimum <= value <= maximum:
            return value
        _safe_print(f"请输入{minimum}-{maximum}。")


def _parse_dex_overrides(
    value: str | None, count: int
) -> tuple[int, int, int, int, int, int]:
    if value:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) not in (count, 6):
            raise ValueError("--dex项数必须等于队内闪光数量，或完整填写6项")
        try:
            values = [int(part) for part in parts]
        except ValueError as exc:
            raise ValueError("--dex必须填写全国图鉴编号整数") from exc
    else:
        values = [
            _ask_int(f"队伍第{slot}位全国图鉴编号 (1-386): ", 1, 386)
            for slot in range(1, count + 1)
        ]
    if any(not 1 <= item <= 386 for item in values[:count]):
        raise ValueError("活动队伍槽位的--dex必须填写1-386")
    if any(not 0 <= item <= 386 for item in values[count:]):
        raise ValueError("未使用槽位的--dex仅支持0或1-386")
    values.extend([0] * (6 - len(values)))
    result = tuple(values)
    return result  # type: ignore[return-value]


def _parse_initial_levels(
    value: str | None, count: int
) -> tuple[int, int, int, int, int, int]:
    if value:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != count:
            raise ValueError("--levels项数必须等于队内闪光数量")
        levels = [int(part) for part in parts]
    else:
        levels = [
            _ask_int(f"队伍第{slot}位初始等级 (1-100): ", 1, 100)
            for slot in range(1, count + 1)
        ]
    if any(not 1 <= level <= 100 for level in levels):
        raise ValueError("活动队伍槽位的--levels必须填写1-100")
    levels.extend([1] * (6 - len(levels)))
    result = tuple(levels)
    return result  # type: ignore[return-value]


def _parse_source(value: str) -> int:
    normalized = value.strip().lower()
    if normalized in ("0", "1", "static", "定点"):
        return 0
    if normalized in ("2", "wild", "野生"):
        return 1
    raise ValueError("来源只能填写1/定点/static或2/野生/wild")


def _parse_effort_row(value: str) -> tuple[int, int, int, int, int, int]:
    if not value.strip():
        return ZERO_EVS
    parts = [part for part in re.split(r"[/,\s]+", value.strip()) if part]
    if len(parts) != 6:
        raise ValueError("努力值必须按HP/ATK/DEF/SPA/SPD/SPE填写6项")
    result = tuple(int(part) for part in parts)
    if any(not 0 <= item <= 255 for item in result):
        raise ValueError("每项努力值必须在0-255之间")
    if sum(result) > 510:
        raise ValueError("六项努力值总和不能超过510")
    return result  # type: ignore[return-value]


def _collect_origins(
    count: int,
    game: str,
    *,
    sources_arg: str | None,
    locations_arg: str | None,
    evs_arg: str | None,
) -> tuple[
    tuple[int, int, int, int, int, int],
    tuple[str, str, str, str, str, str],
    tuple[
        tuple[int, int, int, int, int, int],
        tuple[int, int, int, int, int, int],
        tuple[int, int, int, int, int, int],
        tuple[int, int, int, int, int, int],
        tuple[int, int, int, int, int, int],
        tuple[int, int, int, int, int, int],
    ],
]:
    if sources_arg is not None:
        source_parts = [part.strip() for part in sources_arg.split(",")]
        if len(source_parts) != count:
            raise ValueError("--sources项数必须等于队内闪光数量")
        source_types = [_parse_source(part) for part in source_parts]
    else:
        source_types = []
        for slot in range(1, count + 1):
            while True:
                try:
                    source_types.append(
                        _parse_source(input(f"队伍第{slot}位来源 (1=定点, 2=野生): "))
                    )
                    break
                except ValueError as exc:
                    _safe_print(exc)

    location_parts = locations_arg.split(";") if locations_arg is not None else None
    if location_parts is not None and len(location_parts) != count:
        raise ValueError("--locations项数必须等于队内闪光数量，以分号分隔；定点项留空")
    locations: list[str] = []
    for index, source_type in enumerate(source_types):
        raw_location = location_parts[index].strip() if location_parts is not None else ""
        if source_type == 1:
            while True:
                if not raw_location:
                    raw_location = input(
                        f"队伍第{index + 1}位相遇地点 (TenLines中/英文地点名): "
                    ).strip()
                try:
                    locations.append(resolve_wild_location(raw_location, game))
                    break
                except ValueError as exc:
                    if locations_arg is not None:
                        raise
                    _safe_print(exc)
                    raw_location = ""
        else:
            locations.append("")

    effort_parts = evs_arg.split(";") if evs_arg is not None else None
    if effort_parts is not None and len(effort_parts) != count:
        raise ValueError("--evs项数必须等于队内闪光数量，以分号分隔")
    efforts: list[tuple[int, int, int, int, int, int]] = []
    for index in range(count):
        if effort_parts is not None:
            efforts.append(_parse_effort_row(effort_parts[index]))
            continue
        while True:
            raw = input(
                f"队伍第{index + 1}位努力值 HP/ATK/DEF/SPA/SPD/SPE "
                "(无努力值直接回车): "
            )
            try:
                efforts.append(_parse_effort_row(raw))
                break
            except ValueError as exc:
                _safe_print(exc)

    source_types.extend([0] * (6 - count))
    locations.extend([""] * (6 - count))
    efforts.extend([ZERO_EVS] * (6 - count))
    return (
        tuple(source_types),  # type: ignore[return-value]
        tuple(locations),  # type: ignore[return-value]
        tuple(efforts),  # type: ignore[return-value]
    )


def _select_device(
    ports: set[str], videos: set[int], port: str | None, video: int | None
) -> tuple[str, int]:
    selected_port = port.upper() if port else None
    if selected_port is None:
        if len(ports) == 1:
            selected_port = next(iter(ports))
        else:
            selected_port = input(f"串口{sorted(ports)}: ").strip().upper()
    selected_video = video
    if selected_video is None:
        if len(videos) == 1:
            selected_video = next(iter(videos))
        else:
            selected_video = _ask_int(f"采集卡序号{sorted(videos)}: ", 0, 99)
    if selected_port not in ports:
        raise ValueError(f"未检测到串口{selected_port}")
    if selected_video not in videos:
        raise ValueError(f"未检测到采集卡序号{selected_video}")
    return selected_port, selected_video


def _find_unique_pid(
    output: str,
    *,
    pokemon_index: int,
    game: str,
) -> tuple[int, int] | None:
    """Return the PID and observation count once the current slot is unique."""
    try:
        _, observations = parse_sid_reverse_log(output)
        current = [
            item for item in observations if item.pokemon_index == pokemon_index
        ]
        if not current:
            return None
        summary = analyze_observed_pokemon(current, game=game)
    except ValueError:
        # Early observations can have too many IV combinations to enumerate.
        return None

    unique_pids = {candidate.pid for candidate in summary.candidates}
    if len(unique_pids) != 1:
        return None
    return next(iter(unique_pids)), summary.observations


def _run_easycon(
    command: list[str],
    cwd: Path,
    *,
    pokemon_index: int,
    game: str,
    output_callback: Callable[[str], None] | None = None,
    stop_file: Path | None = None,
) -> tuple[int, str, bool]:
    if stop_file is not None and stop_file.is_file():
        return 130, "[SID_DIAGNOSTIC] 用户已请求停止\n", False
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lines: list[str] = []
    stopped_for_unique_pid = False
    assert process.stdout is not None
    stop = StopFileWatcher(stop_file, lambda: terminate_process_tree(process))
    stop.__enter__()
    try:
        for line in process.stdout:
            _safe_print(line, end="")
            lines.append(line)
            if output_callback is not None:
                output_callback(line)
            if "SIDREV|OBS|" not in line:
                continue
            unique = _find_unique_pid(
                "".join(lines),
                pokemon_index=pokemon_index,
                game=game,
            )
            if unique is None:
                continue
            pid, observation_count = unique
            marker = (
                f"SIDREV|PID_UNIQUE|MON={pokemon_index}|PID={pid:08X}|"
                f"OBS={observation_count}\n"
            )
            _safe_print(marker, end="")
            lines.append(marker)
            if output_callback is not None:
                output_callback(marker)
            stopped_for_unique_pid = True
            process.terminate()
            break
    except KeyboardInterrupt:
        process.terminate()
        raise
    finally:
        stop.__exit__(None, None, None)
        close_output = getattr(process.stdout, "close", None)
        if close_output is not None:
            close_output()
    code = process.wait()
    return (130 if stop.requested else code), "".join(lines), stopped_for_unique_pid and not stop.requested


def _write_slot_project(
    source_dir: Path,
    output_dir: Path,
    base_request: SIDReverseRunRequest,
    slot: int,
) -> Path:
    request = replace(base_request, party_count=1, start_slot=slot)
    return write_sid_reverse_project(
        source_dir,
        output_dir,
        request,
        copy_assets=slot == 1,
        plan_filename=f"slot-{slot}-plan.json",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EasyCon 1.6.4-a Gen 3 SID reverse")
    parser.add_argument("--tid", type=int)
    parser.add_argument("--count", type=int)
    parser.add_argument("--candies", type=int, default=5)
    parser.add_argument("--threshold", type=int, default=85)
    parser.add_argument(
        "--dex",
        help="active party slots' National Dex numbers, comma-separated and required",
    )
    parser.add_argument(
        "--levels",
        help="active party slots' initial levels, comma-separated and required",
    )
    parser.add_argument("--game", choices=("fr_nx", "lg_nx"))
    parser.add_argument("--nx-model", type=int, choices=(1, 2), default=1)
    parser.add_argument(
        "--sources",
        help="one source per Pokemon, comma-separated: static/wild",
    )
    parser.add_argument(
        "--locations",
        help="one TenLines location per Pokemon, semicolon-separated; static entries empty",
    )
    parser.add_argument(
        "--evs",
        help="six EVs per Pokemon separated by '/', Pokemon separated by ';'",
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--ezcon", type=Path, default=DEFAULT_EZCON_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port")
    parser.add_argument("--video", type=int)
    parser.add_argument("--preview-port", type=int, default=0)
    parser.add_argument("--request-json", type=Path, help="GUI 生成的 SID plan.json")
    parser.add_argument("--log-path", type=Path)
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument(
        "--fingerprint-warnings",
        action="store_true",
        help="仅将已审计文件的指纹不一致记录为警告",
    )
    args = parser.parse_args(argv)

    try:
        game = args.game
        if args.request_json is not None:
            base_request = load_sid_reverse_request(args.request_json)
            if game is None:
                raise ValueError("使用 --request-json 时必须同时指定 --game")
            base_request = replace(base_request, game=game)
        else:
            tid = args.tid if args.tid is not None else _ask_int("TID (0-65535): ", 0, 65535)
            count = args.count if args.count is not None else _ask_int("队内闪光宝可梦数量 (1-6): ", 1, 6)
            if game is None:
                game = "fr_nx" if _ask_int("游戏版本 (1=火红, 2=叶绿): ", 1, 2) == 1 else "lg_nx"
            overrides = _parse_dex_overrides(args.dex, count)
            initial_levels = _parse_initial_levels(args.levels, count)
            source_types, locations, effort_values = _collect_origins(
                count,
                game,
                sources_arg=args.sources,
                locations_arg=args.locations,
                evs_arg=args.evs,
            )
            base_request = SIDReverseRunRequest(
                tid=tid,
                party_count=count,
                game=game,
                nx_model=args.nx_model,
                max_candies=args.candies,
                recognition_threshold=args.threshold,
                dex_overrides=overrides,
                initial_levels=initial_levels,
                source_types=source_types,
                locations=locations,
                effort_values=effort_values,
            )
        base_request.validate()
        tid = base_request.tid
        count = base_request.party_count
        ports, videos, device_output = probe_easycon_devices(args.ezcon)
        _safe_print(device_output)
        port, video = _select_device(ports, videos, args.port, args.video)
        runner_warnings: list[str] = []
        runner = prepare_compat_runner(
            args.ezcon,
            fingerprint_warning_only=args.fingerprint_warnings,
            fingerprint_warnings=runner_warnings,
        )
        for warning in runner_warnings:
            _safe_print(warning, file=sys.stderr)
    except (OSError, RuntimeError, ValueError) as exc:
        _safe_print(f"SID反查启动失败: {exc}", file=sys.stderr)
        return 1

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = args.log_path or args.output / f"sid-reverse-{timestamp}.log"
    report_path = args.report_path or args.output / f"sid-reverse-{timestamp}.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    all_output: list[str] = []
    try:
        with log_path.open("w", encoding="utf-8", newline="") as log_file:
            def persist_output(text: str) -> None:
                log_file.write(text)
                log_file.flush()

            write_sid_reverse_plan(args.source, args.output, base_request)
            for slot in range(1, count + 1):
                if args.stop_file is not None and args.stop_file.is_file():
                    raise RuntimeError("用户已请求停止，不继续下一个队伍槽位")
                _safe_print(f"\n=== 采集队伍第{slot}位 ===")
                main_path = _write_slot_project(
                    args.source,
                    args.output,
                    base_request,
                    slot,
                )
                check = validate_runtime(
                    args.ezcon,
                    main_path,
                    fingerprint_warning_only=args.fingerprint_warnings,
                )
                if not check.ok:
                    raise RuntimeError("\n".join(check.errors))
                for warning in getattr(check, "warnings", ()):
                    if warning.startswith("高级模式指纹警告："):
                        _safe_print(warning, file=sys.stderr)
                command = build_run_command(
                    runner,
                    main_path,
                    port=port,
                    video_device=video,
                    video_type="DSHOW",
                    preview_port=args.preview_port,
                )
                code, output, stopped_for_unique_pid = _run_easycon(
                    command,
                    main_path.parent,
                    pokemon_index=slot,
                    game=game,
                    output_callback=persist_output,
                    stop_file=args.stop_file,
                )
                all_output.append(output)
                if "SIDREV|ERROR|" in output or (
                    code != 0 and not stopped_for_unique_pid
                ):
                    raise RuntimeError(f"队伍第{slot}位采集失败，EasyCon退出码{code}")

                if stopped_for_unique_pid:
                    _safe_print(f"队伍第{slot}位PID已经唯一，停止继续喂糖。")
                else:
                    _safe_print(f"队伍第{slot}位采集完成，继续处理用户指定的后续槽位。")

        report = build_report("".join(all_output), tid_override=tid, game=game)
        report_path.write_text(report, encoding="utf-8")
        _safe_print("\n" + report)
        _safe_print(f"\n完整日志: {log_path}")
        _safe_print(f"结果报告: {report_path}")
    except (KeyboardInterrupt, OSError, RuntimeError, ValueError) as exc:
        diagnostic = f"\n[SID_DIAGNOSTIC] SID反查失败: {exc}\n"
        try:
            with log_path.open("a", encoding="utf-8", newline="") as log_file:
                log_file.write(diagnostic)
        except OSError:
            pass
        _safe_print(f"SID反查失败: {exc}", file=sys.stderr)
        _safe_print(f"已保留日志: {log_path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
