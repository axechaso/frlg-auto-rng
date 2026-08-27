"""Fixed-delay results shared by the GUI and the unattended TID worker."""

from dataclasses import fields, replace
import json
from pathlib import Path
import re

from .easycon118 import EasyConRuntimeCheck
from .tid_rng137 import TidRngRequest, validate_tid_runtime
from .tid_starter_flow import validate_tid_starter_flow_runtime


ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
DELAY_FIELDS = {
    "OP": "op_fixed_delay",
    "F1": "f1_fixed_delay",
    "F2": "f2_fixed_delay",
    "F3": "f3_fixed_delay",
}


def tid_request_from_dict(payload: dict) -> TidRngRequest:
    if not isinstance(payload, dict):
        raise ValueError("TID计划参数必须为对象")
    names = {field.name for field in fields(TidRngRequest)}
    request = TidRngRequest(**{key: value for key, value in payload.items() if key in names})
    request.validate()
    return request


def parse_tid_fixed_delays(text: str) -> dict[str, int]:
    """Require a complete measurement block, never mix separate runs."""
    cleaned = ANSI_RE.sub("", text)
    result = {}
    for match in re.finditer(r"(OP|F1|F2|F3)脚本固定延迟[：:]\s*(-?\d+)", cleaned):
        name, value = match.groups()
        if name == "OP":
            result = {}
        result[name] = int(value)
    missing = [name for name in DELAY_FIELDS if name not in result]
    if missing:
        raise ValueError("固定延迟日志缺少：" + "/".join(missing))
    if any(value < 0 for value in result.values()):
        raise ValueError("固定延迟测量值不能为负数")
    return result


def parse_tid_calibration_result(text: str, initial_op_correction: int) -> dict[str, int]:
    cleaned = ANSI_RE.sub("", text)
    if re.search(r"OperationCanceledException|The operation was canceled|运行终止|Exception:", cleaned):
        raise ValueError("固定延迟检测被取消或发生异常")
    result = parse_tid_fixed_delays(cleaned)
    corrections = re.findall(r"OP修正增加50ms[：:]\s*当前修正=(-?\d+)ms", cleaned)
    result["OP_CORRECTION"] = int(corrections[-1]) if corrections else initial_op_correction
    return result


def calibrated_tid_request(request: TidRngRequest, values: dict[str, int]) -> TidRngRequest:
    """Only replace measured delays/correction; preserve every other setting."""
    required = (*DELAY_FIELDS, "OP_CORRECTION")
    if not isinstance(values, dict) or any(type(values.get(name)) is not int for name in required):
        raise ValueError("固定延迟结果必须包含四项整数和实际OP修正")
    calibrated = replace(
        request,
        calibration_check=False,
        op_correction=values["OP_CORRECTION"],
        **{field: values[name] for name, field in DELAY_FIELDS.items()},
    )
    calibrated.validate()
    return calibrated


def validate_tid_plan_runtime(ezcon_path, plan_dir, *, is_flow, calibrate_first=False):
    """Preflight all available stages, including the optional calibration."""
    plan_dir = Path(plan_dir)
    if is_flow:
        payload = json.loads((plan_dir / "flow_plan.json").read_text(encoding="utf-8"))
        check = validate_tid_starter_flow_runtime(
            ezcon_path,
            plan_dir / "01_id" / "main.ecs",
            plan_dir / "02_lab_bridge" / "main.ecs",
            None if payload.get("deferred_identity") else plan_dir / "03_starter_118" / "main.ecs",
        )
    else:
        check = validate_tid_runtime(ezcon_path, plan_dir / "main.ecs")
    if not calibrate_first:
        return check
    calibration = validate_tid_runtime(ezcon_path, plan_dir / "00_calibration" / "main.ecs")
    return EasyConRuntimeCheck(
        check.ok and calibration.ok,
        check.errors + calibration.errors,
        check.warnings + calibration.warnings,
    )
