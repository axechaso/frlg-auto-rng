"""Real clock A/B adapter, confined to disposable fixed-timeline projects."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct

from app_paths import RESOURCE_ROOT
from fingerprint_policy import record_fingerprint_mismatch
from .fixed_timeline_test import FixedTimeline

ASSETS = RESOURCE_ROOT / "assets" / "clock_test"
MARKER = "# FRLG_CLOCK_AB_TEST_V1"
DRIVERS = {"easycon": 0, "eontimer": 1}
DRIVER_LABELS = {"easycon": "A · 伊机控原生计时", "eontimer": "B · EonTimer 式高精度计时"}
SCHEMA = "FRLG_CLOCK_AB_TEST_V1"
LIB_NAME = "98_clock_test.ecs"
DLL_NAME = "frlg_clock_test.dll"
F2_LIBRARIES = ("16_获取_静态目标.ecs", "17_获取_野生目标.ecs")


def validate_driver(driver, fixed):
    if not isinstance(driver, str) or driver not in DRIVERS or not isinstance(fixed, FixedTimeline):
        raise ValueError("底层计时 A/B 必须选择有效计时器并读取固定成功时长，不允许自动校准")
    fixed.validate()


def _pe_check(path):
    data = path.read_bytes()
    try:
        offset = struct.unpack_from("<I", data, 0x3C)[0]
        machine, _, _, _, _, optional = struct.unpack_from("<HHIIIH", data, offset + 4)
        if not (data[:2] == b"MZ" and data[offset:offset + 4] == b"PE\0\0" and machine == 0x8664
                and optional >= 112 and struct.unpack_from("<H", data, offset + 24)[0] == 0x20B
                and 0 < len(data) <= 2 * 1024 * 1024):
            raise ValueError()
    except (struct.error, ValueError):
        raise ValueError("底层计时模块不是有效的 Windows x64 DLL，请重新构建或更新工具") from None


def asset_manifest():
    manifest = json.loads((ASSETS / "build-manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema") != "FRLG_CLOCK_TEST_NATIVE_V1" or manifest.get("abi") != 1
            or manifest.get("machine") != "windows-x64"
            or manifest.get("clock") != "QueryPerformanceCounter"
            or manifest.get("spin_tail_ms") != 2 or manifest.get("max_sleep_slice_ms") != 8):
        raise ValueError("底层计时模块的版本或计时语义不支持，请重新构建")
    _pe_check(ASSETS / DLL_NAME)
    return manifest


def _replace(text, old, new, count, description):
    if text.count(old) != count:
        raise ValueError(f"底层计时测试的{description}不符合已审计入口；不修改未知流程")
    return text.replace(old, new)


def adapt_main(text):
    text = text.replace("\r\n", "\n")
    if MARKER in text:
        raise ValueError("底层计时测试已注入，请重新生成工程")
    anchor = "        $本轮流程结果 = 执行RNG启动与目标获取()"
    text = _replace(text, anchor,
        "        IF CLOCK开始轮($EON固定已尝试) == 0\n            RETURN\n        ENDIF\n" +
        anchor + "\n        CALL CLOCK输出本轮", 1, "轮次")
    for stage, variable, count in ((0, "time_start", 1), (1, "time_OP", 1)):
        anchor = f"${variable} = TIME()"
        text = _replace(text, anchor,
            f"${variable} = CT_Origin({stage}, TIME())\n"
            f"    IF ${variable} < 0\n        RETURN -1\n    ENDIF", count, "计时原点")
    for stage, variable, origin, goal, count in (
        (0, "Seed时间轴结果", "time_start", "SeedMS", 2),
        (1, "F1时间轴结果", "time_OP", "F1时间轴目标MS", 1),
    ):
        anchor = f"${variable} = 执行时间轴等待到(${origin}, ${goal})"
        replacement = f"${variable} = CLOCK等待到({stage}, ${origin}, ${goal})\n"
        replacement += f"        IF ${variable} < 0\n            RETURN -1\n        ENDIF"
        text = _replace(text, anchor, replacement, count, "绝对等待")
    anchor = "    $F2时间轴设置结果 = 设置静态目标时间轴($F2时间轴模式, $F2时间轴截止, $时间轴精确尾段MS)"
    text = _replace(text, anchor,
        "    IF CT_Info(1) == 1 and $F2时间轴目标MS != CT_Get(2, 1)\n"
        "        PRINT F2固定截止不一致，直接停止并保留现场\n"
        "        RETURN -1\n    ENDIF\n" + anchor, 1, "F2固定目标")
    return text + "\n\n" + (ASSETS / "main.ecs").read_text(encoding="utf-8")


def adapt_f2(text, *, wild):
    text = text.replace("\r\n", "\n")
    name = "野生" if wild else "静态"
    stem = name + "目标时间轴"
    fn = name + "目标等待F2"
    pattern = r"(?ms)^FUNC " + re.escape(fn) + r"\(\$普通等待MS: INT\): INT\n.*?^ENDFUNC$"
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ValueError("底层计时测试缺少唯一的 F2 库函数")
    match = matches[0]
    original = match.group()
    start = original.index(f"    ${stem}当前 = TIME()\n")
    end_anchor = f"    ${stem}超时 = ${stem}当前 - ${stem}截止\n"
    if original.count(end_anchor) != 1:
        raise ValueError("底层计时测试 F2 截止入口不支持")
    end = original.index(end_anchor) + len(end_anchor)
    native = original[start:end]
    # The A branch's TIME/WAIT loop is byte-for-byte unchanged except indent.
    replacement = (
        "    IF CT_Info(1) == 1 and CT_Info(0) == 1\n"
        f"        ${stem}超时 = CLOCK精确等待(2)\n"
        f"        IF ${stem}超时 < 0\n            RETURN -1\n        ENDIF\n"
        "    ELSE\n" + "\n".join("    " + line if line else "" for line in native.splitlines()) + "\n"
        "        IF CT_Info(1) == 1\n"
        "            $CLOCK拍点结果 = CT_Mark(2, TIME())\n"
        "            IF $CLOCK拍点结果 != 1\n"
        "                PRINT F2计时观测失败，直接停止并保留现场\n"
        "                RETURN -1\n            ENDIF\n        ENDIF\n    ENDIF\n"
    )
    text = text[:match.start()] + original[:start] + replacement + original[end:] + text[match.end():]
    # Existing callers otherwise continue pressing A after an error return.
    pattern = r"(?m)^([ \t]*)\$" + re.escape(stem) + r"超时 = " + re.escape(fn) + r"\([^\n]+\)$"
    def guard(match):
        indent = match[1]
        return (match[0] + f"\n{indent}IF ${stem}超时 < 0\n{indent}    RETURN -1\n{indent}ENDIF")
    text, count = re.subn(pattern, guard, text)
    if count < 1:
        raise ValueError("底层计时测试 F2 库缺少失败传播入口")
    return MARKER + "\n" + text


def labels_digest(project):
    digest = hashlib.sha256()
    labels = sorted((Path(project).parent / "ImgLabel").glob("*.IL"), key=lambda path: path.name)
    if not labels:
        raise ValueError("底层计时 A/B 工程缺少标签，不能建立同设备比较")
    for path in labels:
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes())
    return digest.hexdigest()


def apply_clock_project(project, fixed: FixedTimeline, driver):
    validate_driver(driver, fixed)
    project = Path(project)
    manifest = asset_manifest()
    files = {"main.ecs": adapt_main(project.read_text(encoding="utf-8"))}
    for name in F2_LIBRARIES:
        files["lib/" + name] = adapt_f2((project.parent / "lib" / name).read_text(encoding="utf-8"), wild=name.startswith("17"))
    dll = project.parent / DLL_NAME
    library = (ASSETS / "runtime.ecs").read_text(encoding="utf-8")
    for token, value in (("__DLL__", dll.resolve().as_posix()), ("__DRIVER__", DRIVERS[driver]),
                         ("__SEED__", fixed.seed_ms), ("__F1__", fixed.f1_ms), ("__F2__", fixed.f2_total_ms)):
        if '"' in str(value) or "\n" in str(value):
            raise ValueError("底层计时工程路径不能包含引号或换行")
        library = library.replace(token, str(value))
    files["lib/" + LIB_NAME] = library
    label_sha = labels_digest(project)
    # Entire adapter validates before any writes. Only a newly owned UUID tree.
    shutil.copy2(ASSETS / DLL_NAME, dll)
    for relative, content in files.items():
        with (project.parent / relative).open("w", encoding="utf-8", newline="\n") as file:
            file.write(content)
    return {"schema": SCHEMA, "abi": 1, "driver": driver, "fixed": asdict(fixed),
            "native": manifest, "dll": DLL_NAME, "labels_sha256": label_sha,
            "files_sha256": {name: hashlib.sha256((project.parent / name).read_bytes()).hexdigest() for name in files},
            "measurement": "qpc_at_wait_return_not_electrical_keypress",
            "round_zero": "native_unmeasured", "auxiliary_waits": "unchanged_easycon"}


def validate_clock_project(project, *, expected_driver, fixed, warning_only=False):
    project = Path(project)
    payload = json.loads((project.parent / "plan.json").read_text(encoding="utf-8"))
    test = payload.get("eontimer_test")
    config = test.get("clock_test") if isinstance(test, dict) else None
    if expected_driver is None:
        if config is not None or MARKER in project.read_text(encoding="utf-8") or (project.parent / "lib" / LIB_NAME).exists():
            raise ValueError("非底层计时工程混入了 A/B 测试，请重新生成")
        return ()
    validate_driver(expected_driver, fixed)
    if (not isinstance(config, dict) or config.get("schema") != SCHEMA or config.get("abi") != 1
            or config.get("driver") != expected_driver or config.get("fixed") != asdict(fixed)
            or config.get("dll") != DLL_NAME
            or set(config.get("files_sha256", {})) != {"main.ecs", "lib/" + LIB_NAME, *("lib/" + name for name in F2_LIBRARIES)}):
        raise ValueError("底层计时 A/B 配置或计时器与生成时不一致，请重新生成")
    warnings = []
    for name, digest in config["files_sha256"].items():
        path = project.parent / name
        if not path.is_file() or MARKER not in path.read_text(encoding="utf-8"):
            raise ValueError("底层计时工程缺少完整入口或测试标记，请重新生成")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            record_fingerprint_mismatch(f"底层计时测试文件已变化：{name}；对照仅作诊断",
                                        warning_only=warning_only, warnings=warnings)
    library = (project.parent / "lib" / LIB_NAME).read_text(encoding="utf-8")
    library_paths = re.findall(r'(?m)^EXTERN FUNC [^\n]+ FROM "([^"\n]+)"$', library)
    if len(library_paths) != 8 or set(library_paths) != {(project.parent / DLL_NAME).resolve().as_posix()}:
        raise ValueError("底层计时模块路径不属于本次工程，请重新生成；移动工程后也须重生成")
    initializers = re.findall(r"(?m)^\$CLOCK就绪\s*=\s*CT_Init\(\s*1,\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*\)$", library)
    if len(initializers) != 1 or tuple(map(int, initializers[0])) != (
            DRIVERS[expected_driver], fixed.seed_ms, fixed.f1_ms, fixed.f2_total_ms):
        raise ValueError("底层计时 DLL 初始化参数与本次计时器/固定时长不一致，请重新生成")
    dll = project.parent / DLL_NAME
    if not dll.is_file():
        raise ValueError("底层计时工程缺少计时 DLL，请重新生成")
    _pe_check(dll)
    if (config.get("native", {}).get("schema") != "FRLG_CLOCK_TEST_NATIVE_V1"
            or config["native"].get("abi") != 1 or config["native"].get("machine") != "windows-x64"):
        raise ValueError("底层计时模块版本不支持")
    if hashlib.sha256(dll.read_bytes()).hexdigest() != config["native"].get("dll_sha256"):
        record_fingerprint_mismatch("底层计时 DLL 已变化；对照仅作诊断", warning_only=warning_only, warnings=warnings)
    if labels_digest(project) != config.get("labels_sha256"):
        record_fingerprint_mismatch("底层计时 A/B 标签已变化，请确认两组使用相同设备覆盖", warning_only=warning_only, warnings=warnings)
    return tuple(warnings)
