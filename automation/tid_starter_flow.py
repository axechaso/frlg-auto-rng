"""Build the shared TID/SID-to-starter flow plan.

English and Japanese keep their audited 1.3.7 ID templates.  The controller
selects one template, adds a machine-readable success marker, and then uses a
small language-neutral route stage.  Starter target selection is shared.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import subprocess

from rng.sid_reverse import first_sid_advances
from rng.starter_sid_verification import (
    StarterSearchRequest,
    StarterTarget,
    find_earliest_shiny_starter,
    sid_advance_scan_offsets,
)

from .easycon118 import EasyConRuntimeCheck
from .tid_rng137 import (
    TidRngRequest,
    validate_tid_runtime,
    write_configured_tid_project,
)


@dataclass(frozen=True)
class TidStarterFlowRequest:
    tid_request: TidRngRequest
    version: str
    starter: str
    starter_min_advances: int = 1500
    starter_max_advances: int = 10_000
    sid_chain_search_advances: int = 10_000
    sid_retry_radius: int = 20

    def validate(self) -> None:
        self.tid_request.validate()
        if self.tid_request.mode != 1:
            raise ValueError("TID到御三家连续流程只支持目标TID乱数模式")
        if self.tid_request.calibration_check:
            raise ValueError("连续流程不能同时启用TID固定延迟检查")
        if self.tid_request.sid_random:
            raise ValueError("连续流程必须填写目标SID，不能使用随机SID")
        if self.sid_chain_search_advances <= 0:
            raise ValueError("SID生成链搜索上限必须大于0")
        if self.sid_retry_radius < 0:
            raise ValueError("SID ADV扫描半径不能为负数")
        self.to_starter_search_request().validate()

    def to_exact_tid_request(self) -> TidRngRequest:
        """Disable unrelated lucky-number exits for the exact-TID flow."""
        return replace(
            self.tid_request,
            same_id=False,
            sequential_id=False,
            include_65535=False,
            single_digit_id=False,
            sid_random=False,
        )

    def to_starter_search_request(self) -> StarterSearchRequest:
        request = self.tid_request
        return StarterSearchRequest(
            version=self.version,
            language=request.language,
            starter=self.starter,
            tid=request.target_tid,
            sid=request.target_sid,
            sound=request.sound,
            button_mode=request.button_mode,
            seed_button=request.seed_button,
            min_advances=self.starter_min_advances,
            max_advances=self.starter_max_advances,
        )


@dataclass(frozen=True)
class TidStarterFlowPlan:
    request: TidStarterFlowRequest
    earliest_sid_chain_advance: int
    starter_target: StarterTarget
    sid_retry_corrections: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": "tid_sid_starter_verification",
            "architecture": (
                "language-specific audited ID template -> shared lab route -> "
                "shared starter target verification"
            ),
            "request": {
                **asdict(self.request),
                "tid_request": self.request.tid_request.to_dict(),
            },
            "earliest_sid_chain_advance": self.earliest_sid_chain_advance,
            "runtime_sid_advance_source": "TIDFLOW|ID|SID_ADV= marker",
            "starter_target": self.starter_target.to_dict(),
            "sid_retry_corrections": list(self.sid_retry_corrections),
            "verification_rules": {
                "wrong_pid": "continue the normal starter RNG calibration",
                "target_pid_non_shiny": (
                    "the starter target was hit but SID was missed; retry SID ADV"
                ),
                "target_pid_shiny": (
                    "the starter target and SID were hit; finish the flow"
                ),
            },
        }


def build_tid_starter_flow_plan(request: TidStarterFlowRequest) -> TidStarterFlowPlan:
    request.validate()
    sid_hits = first_sid_advances(
        request.tid_request.target_tid,
        (request.tid_request.target_sid,),
        max_advances=request.sid_chain_search_advances,
    )
    if not sid_hits:
        raise LookupError(
            f"目标SID未出现在TID生成链前{request.sid_chain_search_advances} ADV"
        )
    starter_target = find_earliest_shiny_starter(request.to_starter_search_request())
    base_correction = request.tid_request.sid_advance_correction
    retry_corrections = tuple(
        base_correction + offset
        for offset in sid_advance_scan_offsets(request.sid_retry_radius)
    )
    return TidStarterFlowPlan(
        request=request,
        earliest_sid_chain_advance=sid_hits[0].advance,
        starter_target=starter_target,
        sid_retry_corrections=retry_corrections,
    )


def render_lab_bridge_ecs(starter: str) -> str:
    horizontal_steps = {
        "妙蛙种子": 2,
        "Bulbasaur": 2,
        "杰尼龟": 3,
        "Squirtle": 3,
        "小火龙": 4,
        "Charmander": 4,
    }.get(starter)
    if horizontal_steps is None:
        raise ValueError("御三家必须是妙蛙种子、小火龙或杰尼龟")
    return f"""# EasyCon 1.6.4-a TID命中后研究所桥接
# 路线来源仅采用用户提供的实机测试路线；不包含样本的旧御三家控制器。

$步进按键时长 = 200
$步进间隔 = 200

CALL 桥接到御三家存档点
RETURN 0

FUNC 走上
    LS UP
    WAIT $步进按键时长
    LS RESET
    WAIT $步进间隔
ENDFUNC

FUNC 走下
    LS DOWN
    WAIT $步进按键时长
    LS RESET
    WAIT $步进间隔
ENDFUNC

FUNC 走左
    LS LEFT
    WAIT $步进按键时长
    LS RESET
    WAIT $步进间隔
ENDFUNC

FUNC 走右
    LS RIGHT
    WAIT $步进按键时长
    LS RESET
    WAIT $步进间隔
ENDFUNC

FUNC 桥接到御三家存档点
    B
    WAIT 1400
    B
    WAIT 1000

    FOR 4
        CALL 走右
    NEXT
    FOR 4
        CALL 走上
    NEXT
    CALL 走左
    WAIT 1500

    FOR 6
        CALL 走下
    NEXT
    FOR 6
        CALL 走左
    NEXT
    CALL 走下
    WAIT 1800

    FOR 6
        CALL 走右
    NEXT
    FOR 12
        CALL 走上
    NEXT

    WAIT 6000
    FOR 30
        B
        WAIT 850
    NEXT
    WAIT 3000

    CALL 走下
    FOR {horizontal_steps}
        CALL 走右
    NEXT
    CALL 走上
    WAIT 1000

    X
    WAIT 1000
    CALL 走下
    CALL 走下
    A
    WAIT 1800
    A
    WAIT 1800
    A
    WAIT 1800
    A
    WAIT 3500
    B
    WAIT 1000

    PRINT TIDFLOW|BRIDGE|DONE=1
ENDFUNC
"""


def write_tid_starter_flow_bundle(
    source_dir: str | Path,
    output_dir: str | Path,
    plan: TidStarterFlowPlan,
) -> Path:
    """Write the audited ID stage, route stage, and shared target plan."""
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    id_dir = output_dir / "01_id"
    bridge_dir = output_dir / "02_lab_bridge"
    write_configured_tid_project(
        source_dir,
        id_dir,
        plan.request.to_exact_tid_request(),
        include_flow_marker=True,
    )
    bridge_dir.mkdir(parents=True, exist_ok=True)
    bridge_path = bridge_dir / "main.ecs"
    bridge_path.write_text(
        render_lab_bridge_ecs(plan.request.starter),
        encoding="utf-8",
    )
    plan_path = output_dir / "flow_plan.json"
    plan_path.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return plan_path


def validate_tid_starter_flow_runtime(
    ezcon_path: str | Path,
    id_main: str | Path,
    bridge_main: str | Path,
) -> EasyConRuntimeCheck:
    """Validate the ID project and the label-free bridge with EasyCon 1.6.4-a."""
    base = validate_tid_runtime(ezcon_path, id_main)
    errors = list(base.errors)
    warnings = list(base.warnings)
    ezcon_path = Path(ezcon_path).resolve()
    bridge_main = Path(bridge_main).resolve()
    if not bridge_main.is_file():
        errors.append(f"找不到研究所桥接脚本: {bridge_main}")
    elif not errors:
        try:
            formatted = subprocess.run(
                [str(ezcon_path), "format", str(bridge_main)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"研究所桥接脚本无法执行1.6.4-a语法预检: {exc}")
        else:
            if formatted.returncode != 0:
                details = (formatted.stdout + "\n" + formatted.stderr).strip()
                errors.append(
                    "研究所桥接脚本未通过EasyCon 1.6.4-a格式检查: "
                    + details[-1000:]
                )
    if not errors:
        warnings.append("研究所桥接脚本已通过EasyCon 1.6.4-a格式检查。")
    return EasyConRuntimeCheck(not errors, tuple(errors), tuple(warnings))
