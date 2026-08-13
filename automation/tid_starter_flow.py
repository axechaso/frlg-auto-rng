"""Build the shared TID/SID-to-starter flow plan.

English and Japanese keep their audited 1.3.7 ID templates.  The controller
selects one template, adds a machine-readable success marker, and then uses a
small language-neutral route stage.  Starter target selection is shared.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import re
import subprocess

from rng.sid_reverse import first_sid_advances
from rng.tenlines import get_hidden_power, pokerng_jump
from rng.starter_sid_verification import (
    StarterSearchRequest,
    StarterTarget,
    find_earliest_shiny_starter,
    sid_advance_scan_offsets,
)
from rng.tenlines_utils import (
    GENDERS,
    NATURES,
    SHININESS,
    TYPES,
    GameSettings,
    IVs,
    InitialSeedResult,
    SearcherResult,
    frame_to_ms,
    get_ability_name,
    get_personal,
    ms_to_time_str,
)

from .easycon118 import (
    EasyCon118Options,
    EasyConRuntimeCheck,
    validate_runtime,
    write_configured_project,
)
from .planner import AutoSearchRequest, RunPlan
from .seed_modes import settings_to_seed_mode
from .support import get_route_support
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
        if self.tid_request.language != "英文":
            raise ValueError(
                "连续御三家流程的第三阶段使用现有1.1.8；当前1.1.8只审计了英文版游戏，"
                "日文版暂时只能单独运行TID/SID脚本"
            )
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
    starter_run_plan: RunPlan
    sid_retry_corrections: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": "tid_sid_starter_verification",
            "architecture": (
                "language-specific audited ID template -> shared lab route -> "
                "configured EasyCon 1.1.8 Starter flow"
            ),
            "request": {
                **asdict(self.request),
                "tid_request": self.request.tid_request.to_dict(),
            },
            "earliest_sid_chain_advance": self.earliest_sid_chain_advance,
            "runtime_sid_advance_source": "TIDFLOW|ID|SID_ADV= marker",
            "starter_target": self.starter_target.to_dict(),
            "starter_118_plan": self.starter_run_plan.to_dict(),
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


def build_starter_run_plan(
    request: TidStarterFlowRequest,
    target: StarterTarget,
) -> RunPlan:
    """Adapt the searched starter result to the existing 1.1.8 plan format."""
    tid_request = request.tid_request
    settings = GameSettings(
        sound={0: "mono", 1: "stereo"}[tid_request.sound],
        button_mode={0: "h", 1: "r", 2: "a"}[tid_request.button_mode],
        seed_button={0: "a", 1: "start", 2: "l"}[tid_request.seed_button],
        extra_button="none",
    )
    seed_mode = settings_to_seed_mode(settings)
    if seed_mode is None:
        raise ValueError(
            "当前TID游戏设置无法映射到1.1.8的Seed模式；"
            "请改用1.1.8支持的Sound/Button Mode/Seed Button组合"
        )

    game_family = "fr" if request.version == "火红" else "lg"
    game = f"{game_family}_{'nx2' if tid_request.nx_model == 2 else 'nx'}"
    species_en = target.species_en
    search_request = AutoSearchRequest(
        game=game,
        tid=tid_request.target_tid,
        sid=tid_request.target_sid,
        method="Static 1",
        category="Starter",
        location="",
        pokemon=species_en,
        max_advances=request.starter_max_advances,
        shiny="Star/Square",
        seed_mode=seed_mode,
    )
    search_request.validate()

    hp_type, hp_power = get_hidden_power(target.ivs)
    personal = get_personal(target.species_id, game)
    ability_id = personal["abilities"][target.ability]
    target_seed = pokerng_jump(target.initial_seed, target.advances)
    search_result = SearcherResult(
        target_seed=f"{target_seed:08X}",
        method="Static 1",
        pokemon=species_en,
        level=5,
        pid=target.pid_hex,
        shiny=SHININESS[target.shiny],
        nature=NATURES[target.nature],
        ability=get_ability_name(ability_id),
        ivs=IVs(*target.ivs),
        hidden_type=TYPES[hp_type],
        hidden_power=hp_power,
        gender=GENDERS[target.gender],
    )
    console = "NX2" if tid_request.nx_model == 2 else "NX"
    total_frames = round(target.seed_time_ms / 16 + target.advances)
    initial = InitialSeedResult(
        seed=target.seed_hex,
        advances=target.advances,
        total_frames=total_frames,
        total_time=ms_to_time_str(frame_to_ms(total_frames, console)),
        seed_time=target.seed_time_ms,
        settings=settings,
    )
    support = get_route_support(
        "Static 1",
        "Starter",
        "",
        game=game,
        pokemon=species_en,
    )
    return RunPlan(
        request=search_request,
        target=search_result,
        initial_seed=initial,
        iv_total=sum(target.ivs),
        route_support=support,
        warnings=(
            "御三家执行阶段复用1.1.8现有Starter流程；进入第三阶段后由1.1.8负责领取、识别和校准。",
        ),
    )


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
    starter_run_plan = build_starter_run_plan(request, starter_target)
    base_correction = request.tid_request.sid_advance_correction
    retry_corrections = tuple(
        base_correction + offset
        for offset in sid_advance_scan_offsets(request.sid_retry_radius)
    )
    return TidStarterFlowPlan(
        request=request,
        earliest_sid_chain_advance=sid_hits[0].advance,
        starter_target=starter_target,
        starter_run_plan=starter_run_plan,
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
    *,
    starter_source_dir: str | Path,
) -> Path:
    """Write the ID, lab bridge, and configured existing 1.1.8 starter stage."""
    source_dir = Path(source_dir).resolve()
    starter_source_dir = Path(starter_source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    id_dir = output_dir / "01_id"
    bridge_dir = output_dir / "02_lab_bridge"
    starter_dir = output_dir / "03_starter_118"
    write_configured_tid_project(
        source_dir,
        id_dir,
        plan.request.to_exact_tid_request(),
        include_flow_marker=True,
    )
    id_template = (id_dir / "main.ecs").read_text(encoding="utf-8")
    correction_pattern = re.compile(r"(?m)^\$SID_ADV修正\s*=\s*[^\r\n]*$")
    for stale_attempt in id_dir.glob("main_attempt_*.ecs"):
        stale_attempt.unlink()
    for attempt_index, correction in enumerate(plan.sid_retry_corrections):
        attempt_text, replacement_count = correction_pattern.subn(
            f"$SID_ADV修正 = {correction}",
            id_template,
        )
        if replacement_count != 1:
            raise ValueError(
                "生成的TID/SID脚本中$SID_ADV修正字段数量异常，无法创建连续流程重试脚本"
            )
        (id_dir / f"main_attempt_{attempt_index:03d}.ecs").write_text(
            attempt_text,
            encoding="utf-8",
        )
    bridge_dir.mkdir(parents=True, exist_ok=True)
    bridge_path = bridge_dir / "main.ecs"
    bridge_path.write_text(
        render_lab_bridge_ecs(plan.request.starter),
        encoding="utf-8",
    )
    write_configured_project(
        starter_source_dir,
        starter_dir,
        plan.starter_run_plan,
        EasyCon118Options(
            nx_model=plan.request.tid_request.nx_model,
            continue_capture_after_shiny=False,
        ),
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
    starter_main: str | Path,
) -> EasyConRuntimeCheck:
    """Validate all three flow stages with pinned EasyCon 1.6.4-a."""
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
    starter = validate_runtime(ezcon_path, starter_main)
    errors.extend(starter.errors)
    warnings.extend(starter.warnings)
    return EasyConRuntimeCheck(not errors, tuple(errors), tuple(warnings))
