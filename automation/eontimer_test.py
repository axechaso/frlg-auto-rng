"""Opt-in GBA/Custom timing for disposable 2.0 timeline test projects.

No runner patch, mother-script mutation, or ordinary pre-calibration writeback.
The ECS port uses bounded integer arithmetic and the existing absolute waits.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

from app_paths import RESOURCE_ROOT
from fingerprint_policy import record_fingerprint_mismatch
from .eontimer_core import GBA_FPS, UPSTREAM_COMMIT
from .fixed_timeline_test import FixedTimeline

MARKER = "# EONTIMER_GBA_CUSTOM_TEST_V1"
RUNTIME_PATH = RESOURCE_ROOT / "assets" / "eontimer_test" / "runtime.ecs"
SCHEMA = "FRLG_EONTIMER_GBA_TEST_V1"


def test_options(options):
    """Separate the experimental calibration from the user's normal records."""
    return replace(options, update_precalibration=False,
                   precalibration_seed_ns1=0, precalibration_seed_ns2=0,
                   precalibration_frame_ns1=0, precalibration_frame_ns2=0,
                   frame_parity_scheme=0, debug_log_output=1)


def validate_test_request(request, options, *, advanced):
    if not advanced:
        raise ValueError("EonTimer 临时测试必须开启高级模式")
    if options.item_rng_mode:
        raise ValueError("EonTimer 临时测试不支持道具乱数")
    if options.mystery_gift_enabled:
        raise ValueError("EonTimer 临时测试暂不支持已开启神秘礼物的存档（需菜单奇偶调整）")
    if request.category in {"Roaming", "Safari Zone"} or "Safari" in request.location:
        raise ValueError("EonTimer 临时测试暂不支持游走或狩猎区")
    if request.pokemon == "Togepi":
        raise ValueError("EonTimer 临时测试暂不支持波克比孵化与反查流程")


def _block(text: str, name: str):
    matches = list(re.finditer(r"(?ms)^FUNC " + re.escape(name) + r"\(\): INT\n.*?^ENDFUNC$", text))
    if len(matches) != 1:
        raise ValueError(f"EonTimer 测试缺少唯一的 2.0 时间轴函数：{name}")
    return matches[0]


def adapt_text(text: str, fixed: FixedTimeline | None = None) -> str:
    text = text.replace("\r\n", "\n")
    if MARKER in text:
        raise ValueError("EonTimer 测试已经注入，请重新生成工程")
    for anchor in ("Seed绝对时间轴:", "F1绝对时间轴:", "F2绝对时间轴计划:",
                   "$F1阶段脚本固定帧", "$本轮真值解", "$本轮候选命中计数"):
        if anchor not in text:
            raise ValueError(f"EonTimer 测试只支持已审计的 2.0 时间轴入口：缺少 {anchor}")
    auto = _block(text, "执行自动校准与等待更新")
    block = auto.group()
    if block.count("重新计算等待参数()") != 1:
        raise ValueError("EonTimer 测试的原校准函数重算入口不唯一")
    block = block.replace("FUNC 执行自动校准与等待更新()", "FUNC EON伊机控自动校准()", 1)
    block = block.replace("重新计算等待参数()", "EON伊机控等待参数()", 1)
    text = text[:auto.start()] + block + text[auto.end():]
    wait = _block(text, "重新计算等待参数")
    block = wait.group().replace("FUNC 重新计算等待参数()", "FUNC EON伊机控等待参数()", 1)
    text = text[:wait.start()] + block + text[wait.end():]
    # Globals must be declared before the main body; functions can be appended.
    runtime = RUNTIME_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    if fixed is not None:
        fixed.validate()
        for name, value in (("固定测试模式", 1), ("固定SeedMS", fixed.seed_ms),
                            ("固定F1MS", fixed.f1_ms), ("固定F2总MS", fixed.f2_total_ms),
                            ("固定轮数上限", fixed.repeat_limit)):
            runtime, count = re.subn(r"(?m)^\$EON" + re.escape(name) + r" = \d+$",
                                    f"$EON{name} = {value}", runtime)
            if count != 1:
                raise ValueError("固定时长测试配置入口不唯一")
        anchor = "        $本轮流程结果 = 执行RNG启动与目标获取()"
        if text.count(anchor) != 1:
            raise ValueError("固定时长测试缺少唯一的轮次入口，不修改未知流程")
        text = text.replace(anchor, "        IF EON开始固定轮() == 0\n            RETURN\n        ENDIF\n" + anchor, 1)
        output_anchor = "FUNC 输出下一轮等待参数\n"
        if text.count(output_anchor) != 1:
            raise ValueError("固定时长测试缺少唯一的日志输出入口")
        text = text.replace(output_anchor, output_anchor +
                            '    PRINT 【固定时长测试：不校准】\n'
                            '    PRINT 固定请求: Seed & $EON固定SeedMS & " ms，F1 " & $EON固定F1MS & '
                            '" ms，F2总 " & $EON固定F2总MS & " ms（已包含F1）"\n'
                            '    RETURN\n', 1)
        text = text.replace("PRINT 自动校准成功，进入下一轮", "PRINT 固定时长测试已记录本轮，进入下一轮")
        text = text.replace("PRINT 识图反查成功，继续校准", "PRINT 识图反查成功，仅记录误差，不校准")
        text = text.replace("PRINT 自动校准结束，停止脚本", "PRINT 固定时长测试结束，停止脚本")
    globals_, functions = runtime.split("FUNC EON换算毫秒", 1)
    return globals_ + text + "\n\nFUNC EON换算毫秒" + functions


def apply_test_project(project: Path, plan, options, *, advanced: bool,
                       fixed: FixedTimeline | None = None, clock_driver: str | None = None) -> None:
    validate_test_request(plan.request, options, advanced=advanced)
    if plan.initial_seed.advances >= 14400:
        raise ValueError("EonTimer 临时测试本次不使用 TV，请选择消耗帧小于 14400 的目标")
    path = Path(project)
    manifest_path = path.parent / "plan.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("template") != "NS火叶全自动一键乱数2.0-时间轴.ecs":
        raise ValueError("EonTimer 临时测试只支持 2.0 时间轴入口")
    if payload.get("precalibration", {}).get("enabled") is not False:
        raise ValueError("EonTimer 临时测试不能复用或写回普通预校准")
    if fixed is not None:
        fixed.validate_plan(plan, options)
    if clock_driver is not None:
        from .clock_test import validate_driver
        validate_driver(clock_driver, fixed)
    configured = adapt_text(path.read_text(encoding="utf-8"), fixed)
    data = configured.encode("utf-8")
    payload["eontimer_test"] = {
        "schema": SCHEMA, "upstream_commit": UPSTREAM_COMMIT, "console": "GBA",
        "fps": GBA_FPS, "script_sha256": hashlib.sha256(data).hexdigest(),
        "runtime_sha256": hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest(),
        "menu": False, "tv": False, "ordinary_precalibration": False,
        "calibration": "unique_only_custom_update",
        "comparison": "same_observation_easycon_calculation_not_executed",
        "mode": "fixed" if fixed is not None else "eontimer",
        "initialization": "nearest_even_fixed_frames_before_parity",
    }
    if fixed is not None:
        from dataclasses import asdict
        payload["eontimer_test"].update(fixed=asdict(fixed), calibration="disabled",
                                        comparison="unique_reverse_observation_only")
    if clock_driver is not None:
        from .clock_test import apply_clock_project
        # Only the freshly generated project and its two F2 libraries change.
        # The shipped runner, source mothers and ordinary projects do not.
        with path.open("w", encoding="utf-8", newline="\n") as file:
            file.write(configured)
        payload["eontimer_test"]["clock_test"] = apply_clock_project(path, fixed, clock_driver)
        configured = path.read_text(encoding="utf-8")
        payload["eontimer_test"]["script_sha256"] = hashlib.sha256(configured.encode("utf-8")).hexdigest()
        payload["eontimer_test"]["comparison"] = "real_clock_fixed_deadline_ab"
    # Called only inside a new UUID output directory owned by this generation.
    with path.open("w", encoding="utf-8", newline="\n") as file:
        file.write(configured)
    with manifest_path.open("w", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def validate_test_project(project: Path, *, expected: bool, fixed: FixedTimeline | None = None,
                          clock_driver: str | None = None,
                          fingerprint_warning_only: bool = False) -> tuple[str, ...]:
    path = Path(project)
    payload = json.loads((path.parent / "plan.json").read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")
    test = payload.get("eontimer_test")
    from .clock_test import validate_clock_project
    if not expected:
        if test is not None or MARKER in text:
            raise ValueError("普通方案混入了 EonTimer 测试，请重新生成")
        return validate_clock_project(path, expected_driver=None, fixed=None)
    if not isinstance(test, dict) or test.get("schema") != SCHEMA or MARKER not in text:
        raise ValueError("EonTimer 测试工程缺少明确的测试标记")
    if payload.get("precalibration", {}).get("enabled") is not False:
        raise ValueError("EonTimer 测试工程不能写入普通预校准")
    if fixed is not None:
        from dataclasses import asdict
        fixed.validate()
        if test.get("mode") != "fixed" or test.get("fixed") != asdict(fixed) or test.get("calibration") != "disabled":
            raise ValueError("固定时长测试工程与生成时配置不一致，请重新生成")
    elif test.get("mode", "eontimer") != "eontimer":
        raise ValueError("EonTimer 自动校准工程混入固定时长模式，请重新生成")
    warnings = []
    if hashlib.sha256(path.read_bytes()).hexdigest() != test.get("script_sha256"):
        record_fingerprint_mismatch("EonTimer 测试工程在生成后发生变化，建议重新生成；对照仅作诊断",
                                    warning_only=fingerprint_warning_only, warnings=warnings)
    if test.get("runtime_sha256") != hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest():
        record_fingerprint_mismatch("EonTimer 测试逻辑已更新，建议重新生成；对照仅作诊断",
                                    warning_only=fingerprint_warning_only, warnings=warnings)
    warnings.extend(validate_clock_project(path, expected_driver=clock_driver, fixed=fixed,
                                          warning_only=fingerprint_warning_only))
    return tuple(warnings)
