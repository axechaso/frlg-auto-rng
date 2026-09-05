"""Build the shared TID/SID-to-starter flow plan.

English and Japanese keep their audited 1.3.7 ID templates.  The controller
selects one template, adds a machine-readable success marker, and then uses a
small language-neutral route stage.  Starter target selection is shared.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
import json
from pathlib import Path
import re
import shutil
import subprocess

from rng.sid_reverse import (
    DEFAULT_TID_SID_SEARCH_ADVANCES,
    first_sid_advances,
    sid_at_advance,
)
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
    EGG_TEMPLATE_NAME,
    STANDARD_TEMPLATE_NAME,
    EasyCon118Options,
    EasyConRuntimeCheck,
    reverse_expansion_to_ecs_values,
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
from .tid_starter_save import (
    is_starter_save_template,
    render_starter_save_bridge,
    set_starter_save_sid_correction,
)


# The starter stage keeps the currently audited formal Seed calibration path.
# Its startup path remains selectable independently through the GUI request.
STARTER_SEED_CALIBRATION_SCHEME = 0


@dataclass(frozen=True)
class TidStarterFlowRequest:
    tid_request: TidRngRequest
    version: str
    starter: str
    starter_min_advances: int = 1500
    starter_max_advances: int = 10_000
    # The previous 10,000-ADV cutoff rejected valid later SIDs. One million is
    # wide enough for normal use while avoiding a potentially multi-billion
    # iteration full-cycle scan. Explicit programmatic callers may still pass
    # ``None`` to request the complete TID-seeded LCG chain.
    sid_chain_search_advances: int | None = DEFAULT_TID_SID_SEARCH_ADVANCES
    sid_retry_radius: int = 20
    starter_sound: int = 0
    starter_button_mode: int = 0
    starter_seed_button: int = 0
    accept_any_tid: bool = False
    any_tid_require_denoise: bool = True
    starter_seed_startup_scheme: int = 0
    starter_template_name: str = STANDARD_TEMPLATE_NAME
    update_precalibration: bool = False
    starter_debug_log_output: int = 1
    starter_frame_parity_scheme: int = 1
    starter_reverse_expansion_layers: int | None = None
    starter_reverse_expansion_seed_tolerances: tuple[int, int, int] | None = None
    starter_reverse_expansion_frame_half_widths: tuple[int, int, int] | None = None

    def validate(self) -> None:
        self.tid_request.validate()
        if not isinstance(self.accept_any_tid, bool):
            raise ValueError("任意TID衔接开关必须为布尔值")
        if not isinstance(self.any_tid_require_denoise, bool):
            raise ValueError("任意TID去噪开关必须为布尔值")
        if self.starter_seed_startup_scheme not in {0, 1}:
            raise ValueError("御三家 Seed启动方案只能是0（当前HOME_BUFFER）或1（固定用户界面HOME）")
        if self.starter_template_name not in {STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME}:
            raise ValueError("御三家脚本模板只能选择正式版或时间轴版入口")
        if not isinstance(self.update_precalibration, bool):
            raise ValueError("御三家更新预校准开关必须是布尔值")
        if self.starter_debug_log_output not in {0, 1}:
            raise ValueError("御三家输出日志模式只能是0（精简）或1（完整调试）")
        if self.starter_frame_parity_scheme not in {0, 1}:
            raise ValueError("御三家奇偶调整方案只能是0（F1/F2）或1（菜单）")
        expansion = EasyCon118Options(
            reverse_expansion_layers=self.starter_reverse_expansion_layers,
            reverse_expansion_seed_tolerances=self.starter_reverse_expansion_seed_tolerances,
            reverse_expansion_frame_half_widths=self.starter_reverse_expansion_frame_half_widths,
        )
        reverse_expansion_to_ecs_values(expansion)
        if self.starter_sound not in {0, 1}:
            raise ValueError("御三家 Sound 只能是 MONO 或 STEREO")
        if self.starter_button_mode not in {0, 1, 2}:
            raise ValueError("御三家 Button Mode 只能是 HELP、LR 或 L=A")
        if self.starter_seed_button not in {0, 1, 2}:
            raise ValueError("御三家 Seed Button 只能是 A、START 或 L(L=A)")
        if self.accept_any_tid and self.tid_request.mode != 0:
            raise ValueError("任意TID衔接仅适用于穷举模式")
        if self.tid_request.calibration_check:
            raise ValueError("连续流程不能同时启用TID固定延迟检查")
        if self.tid_request.mode == 0 and not self.tid_request.sid_random:
            raise ValueError("穷举连续流程必须使用固定F3延迟取得实际SID")
        if self.tid_request.language == "日文":
            if (self.starter_sound, self.starter_button_mode, self.starter_seed_button) != (0, 0, 0):
                raise ValueError(
                    "日文版御三家临时分支目前只支持 MONO + HELP + A（Seed模式10）"
                )
        if (
            self.sid_chain_search_advances is not None
            and self.sid_chain_search_advances <= 0
        ):
            raise ValueError("SID生成链搜索上限必须大于0，或留空使用完整链")
        if self.sid_retry_radius < 0:
            raise ValueError("SID ADV扫描半径不能为负数")
        self.to_starter_search_request().validate()

    @property
    def deferred_identity(self) -> bool:
        """Whether the starter search needs the stage-1 runtime SID.

        Exhaustive mode does not know either identity in advance.  Random TID
        mode with SID randomization disabled likewise knows the target TID but
        only obtains the actual SID after its fixed-F3 stage has run.
        """
        return self.tid_request.mode == 0 or self.tid_request.sid_random

    @property
    def starter_settings(self) -> GameSettings:
        """Return the independent 2.0 settings used by the starter stage."""
        return GameSettings(
            sound={0: "mono", 1: "stereo"}[self.starter_sound],
            button_mode={0: "h", 1: "r", 2: "a"}[self.starter_button_mode],
            seed_button={0: "a", 1: "start", 2: "l"}[self.starter_seed_button],
            extra_button="none",
        )

    def to_flow_tid_request(self) -> TidRngRequest:
        """Return the stage-1 request appropriate for the selected flow."""
        if self.deferred_identity:
            return replace(
                self.tid_request,
                sid_random=True,
                f3_random_range=0,
            )
        return replace(
            self.tid_request,
            same_id=False,
            sequential_id=False,
            include_65535=False,
            single_digit_id=False,
            sid_random=False,
            f3_random_range=0,
        )

    def to_starter_search_request(
        self,
        *,
        tid: int | None = None,
        sid: int | None = None,
    ) -> StarterSearchRequest:
        request = self.tid_request
        return StarterSearchRequest(
            version=self.version,
            language=request.language,
            starter=self.starter,
            tid=request.target_tid if tid is None else tid,
            sid=request.target_sid if sid is None else sid,
            sound=self.starter_sound,
            button_mode=self.starter_button_mode,
            seed_button=self.starter_seed_button,
            min_advances=self.starter_min_advances,
            max_advances=self.starter_max_advances,
        )


def tid_starter_flow_request_from_dict(payload: dict[str, object]) -> TidStarterFlowRequest:
    """Rebuild a flow request from ``flow_plan.json`` without UI state."""
    raw_tid = payload.get("tid_request")
    if not isinstance(raw_tid, dict):
        raise ValueError("flow_plan.json缺少tid_request")
    tid_names = {item.name for item in fields(TidRngRequest)}
    tid_request = TidRngRequest(
        **{name: value for name, value in raw_tid.items() if name in tid_names}
    )
    return TidStarterFlowRequest(
        tid_request=tid_request,
        version=str(payload["version"]),
        starter=str(payload["starter"]),
        starter_min_advances=int(payload.get("starter_min_advances", 1500)),
        starter_max_advances=int(payload.get("starter_max_advances", 10_000)),
        sid_chain_search_advances=(
            None
            if payload.get(
                "sid_chain_search_advances", DEFAULT_TID_SID_SEARCH_ADVANCES
            )
            is None
            else int(
                payload.get(
                    "sid_chain_search_advances", DEFAULT_TID_SID_SEARCH_ADVANCES
                )
            )
        ),
        sid_retry_radius=int(payload.get("sid_retry_radius", 20)),
        starter_sound=int(payload.get("starter_sound", 0)),
        starter_button_mode=int(payload.get("starter_button_mode", 0)),
        starter_seed_button=int(payload.get("starter_seed_button", 0)),
        accept_any_tid=payload.get("accept_any_tid", False),
        any_tid_require_denoise=payload.get("any_tid_require_denoise", True),
        starter_seed_startup_scheme=int(payload.get("starter_seed_startup_scheme", 0)),
        starter_template_name=str(
            payload.get("starter_template_name", STANDARD_TEMPLATE_NAME)
        ),
        update_precalibration=payload.get("update_precalibration", False),
        starter_debug_log_output=int(payload.get("starter_debug_log_output", 1)),
        starter_frame_parity_scheme=int(payload.get("starter_frame_parity_scheme", 1)),
        starter_reverse_expansion_layers=(
            None
            if payload.get("starter_reverse_expansion_layers") is None
            else int(payload["starter_reverse_expansion_layers"])
        ),
        starter_reverse_expansion_seed_tolerances=(
            None
            if payload.get("starter_reverse_expansion_seed_tolerances") is None
            else tuple(int(value) for value in payload["starter_reverse_expansion_seed_tolerances"])
        ),
        starter_reverse_expansion_frame_half_widths=(
            None
            if payload.get("starter_reverse_expansion_frame_half_widths") is None
            else tuple(int(value) for value in payload["starter_reverse_expansion_frame_half_widths"])
        ),
    )


@dataclass(frozen=True)
class TidStarterFlowPlan:
    request: TidStarterFlowRequest
    earliest_sid_chain_advance: int | None
    starter_target: StarterTarget | None
    starter_run_plan: RunPlan | None
    sid_retry_corrections: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        if self.request.deferred_identity:
            verification_rules = {
                "wrong_pid": "continue the normal starter RNG calibration",
                "target_pid_non_shiny": (
                    "stop and preserve the log because the actual SID chain may differ"
                ),
                "target_pid_shiny": (
                    "the dynamically resolved starter target was hit; finish the flow"
                ),
            }
        else:
            verification_rules = {
                "wrong_pid": "continue the normal starter RNG calibration",
                "target_pid_non_shiny": (
                    "the starter target was hit but SID was missed; retry SID ADV"
                ),
                "target_pid_shiny": (
                    "the starter target and SID were hit; finish the flow"
                ),
            }
        return {
            "mode": "tid_sid_starter_verification",
            "architecture": (
                "language-specific audited ID template -> shared lab route -> "
                "configured EasyCon 2.0 Starter flow"
            ),
            "request": {
                **asdict(self.request),
                "tid_request": self.request.tid_request.to_dict(),
                "starter_seed_calibration_scheme": STARTER_SEED_CALIBRATION_SCHEME,
            },
            "earliest_sid_chain_advance": self.earliest_sid_chain_advance,
            "runtime_sid_advance_source": "TIDFLOW|ID|SID_ADV= marker",
            "deferred_identity": self.request.deferred_identity,
            "starter_target": (
                self.starter_target.to_dict()
                if self.starter_target is not None
                else None
            ),
            "starter_118_plan": (
                self.starter_run_plan.to_dict()
                if self.starter_run_plan is not None
                else None
            ),
            "sid_retry_corrections": list(self.sid_retry_corrections),
            "verification_rules": verification_rules,
        }


def build_starter_run_plan(
    request: TidStarterFlowRequest,
    target: StarterTarget,
) -> RunPlan:
    """Adapt the searched starter result to the existing 2.0 plan format."""
    tid_request = request.tid_request
    settings = request.starter_settings
    seed_mode = settings_to_seed_mode(settings)
    if seed_mode is None:
        raise ValueError(
            "当前 TID 游戏设置无法映射到 2.0 的 Seed 模式；"
            "请改用 2.0 支持的 Sound / Button Mode / Seed Button 组合"
        )

    game_family = "fr" if request.version == "火红" else "lg"
    language_suffix = "_jpn" if tid_request.language == "日文" else ""
    game = f"{game_family}{language_suffix}_{'nx2' if tid_request.nx_model == 2 else 'nx'}"
    species_en = target.species_en
    search_request = AutoSearchRequest(
        game=game,
        tid=target.tid,
        sid=target.sid,
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
            "御三家执行阶段复用 2.0 现有 Starter 流程；进入第三阶段后由 2.0 负责领取、识别和校准。",
        ),
    )


def build_tid_starter_flow_plan(request: TidStarterFlowRequest) -> TidStarterFlowPlan:
    request.validate()
    if request.deferred_identity:
        return TidStarterFlowPlan(
            request=request,
            earliest_sid_chain_advance=None,
            starter_target=None,
            starter_run_plan=None,
            sid_retry_corrections=(request.tid_request.sid_advance_correction,),
        )
    sid_hits = first_sid_advances(
        request.tid_request.target_tid,
        (request.tid_request.target_sid,),
        max_advances=request.sid_chain_search_advances,
    )
    if not sid_hits:
        if request.sid_chain_search_advances is None:
            detail = "完整TID生成链"
        else:
            detail = f"前{request.sid_chain_search_advances} ADV"
        raise LookupError(f"目标SID未出现在{detail}")
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


@dataclass(frozen=True)
class ResolvedTidStarterPlan:
    """Starter target resolved from the identity produced by exhaustive mode."""

    tid: int
    sid_advance: int
    sid: int
    request: TidStarterFlowRequest
    starter_target: StarterTarget
    starter_run_plan: RunPlan

    def to_dict(self) -> dict[str, object]:
        return {
            "tid": self.tid,
            "sid_advance": self.sid_advance,
            "sid": self.sid,
            "starter_target": self.starter_target.to_dict(),
            "starter_118_plan": self.starter_run_plan.to_dict(),
        }


def resolve_exhaustive_starter_plan(
    request: TidStarterFlowRequest,
    *,
    actual_tid: int,
    sid_advance: int,
) -> ResolvedTidStarterPlan:
    """Resolve the real SID and starter target after a deferred ID stage."""
    request.validate()
    if not request.deferred_identity:
        raise ValueError("当前连续流程不需要运行时解析实际TID/SID")
    actual_sid = sid_at_advance(actual_tid, sid_advance)
    runtime_tid_request = replace(
        request.tid_request,
        target_tid=actual_tid,
        target_sid=actual_sid,
    )
    runtime_request = replace(request, tid_request=runtime_tid_request)
    starter_target = find_earliest_shiny_starter(
        runtime_request.to_starter_search_request(tid=actual_tid, sid=actual_sid)
    )
    starter_run_plan = build_starter_run_plan(runtime_request, starter_target)
    return ResolvedTidStarterPlan(
        tid=actual_tid,
        sid_advance=sid_advance,
        sid=actual_sid,
        request=runtime_request,
        starter_target=starter_target,
        starter_run_plan=starter_run_plan,
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


def enable_any_tid_handoff(template: str, *, require_denoise: bool = True) -> str:
    """Opt-in early handoff after original digit validation and denoising.

    Leave all timing, recognition and search helpers unchanged. The original
    print helper computes the actual SID ADV before emitting identity markers.
    """
    prefix = "EN_" if re.search(r"(?m)^FUNC EN_匹配\s*$", template) else ""
    anchor = f"            CALL {prefix}匹配\n"
    if template.count(anchor) != 1 or f"FUNC {prefix}打印参数\n" not in template:
        raise ValueError("任意TID衔接缺少唯一的匹配/参数输出结构")
    before = template.partition(anchor)[0]
    guard = "            IF $digits_ok == 0\n"
    denoise = f"            CALL {prefix}去噪\n"
    if guard not in before or denoise not in before or before.rfind(guard) > before.rfind(denoise):
        raise ValueError("任意TID衔接必须位于完整识别和原版去噪之后")
    confirmation = "$denoise_hit_count >= $denoise_need_hit and " if require_denoise else ""
    description = "通过去噪确认" if require_denoise else "首次完整识别，不等待去噪"
    block = f"""            # TIDFLOW_ANY_TID_BEGIN
            IF $ID_RNG == 0 and $脚本固定延迟检查开关 == 0
                IF {confirmation}$ID >= 0 and $ID <= 65535
                    PRINT 已取得实际TID（{description}），忽略目标TID和特殊号码筛选，继续御三家计划
                    CALL {prefix}打印参数
                    PRINT TIDFLOW|ID|MATCH=1
                    PRINT TIDFLOW|ID|TID= & $ID
                    PRINT TIDFLOW|ID|SID_ADV= & $adv
                    BREAK 2
                ENDIF
            ENDIF
            # TIDFLOW_ANY_TID_END
"""
    return template.replace(anchor, anchor + block, 1)


def write_tid_starter_flow_bundle(
    source_dir: str | Path,
    output_dir: str | Path,
    plan: TidStarterFlowPlan,
    *,
    starter_source_dir: str | Path,
    fingerprint_warning_only: bool = False,
    fingerprint_warnings: list[str] | None = None,
    precalibration_store_path: str | Path | None = None,
) -> Path:
    """Write the ID, lab bridge, and configured existing 2.0 starter stage."""
    source_dir = Path(source_dir).resolve()
    starter_source_dir = Path(starter_source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    id_dir = output_dir / "01_id"
    bridge_dir = output_dir / "02_lab_bridge"
    starter_dir = output_dir / "03_starter_118"
    write_configured_tid_project(
        source_dir,
        id_dir,
        plan.request.to_flow_tid_request(),
        include_flow_marker=True,
        fingerprint_warning_only=fingerprint_warning_only,
        fingerprint_warnings=fingerprint_warnings,
    )
    id_template = (id_dir / "main.ecs").read_text(encoding="utf-8")
    if plan.request.accept_any_tid:
        plan.request.validate()
        id_template = enable_any_tid_handoff(id_template, require_denoise=plan.request.any_tid_require_denoise)
        (id_dir / "main.ecs").write_text(id_template, encoding="utf-8")
    starter_save_template = is_starter_save_template(id_template)
    correction_pattern = re.compile(r"(?m)^\$SID_ADV修正\s*=\s*[^\r\n]*$")
    for stale_attempt in id_dir.glob("main_attempt_*.ecs"):
        stale_attempt.unlink()
    for attempt_index, correction in enumerate(plan.sid_retry_corrections):
        if starter_save_template:
            attempt_text = set_starter_save_sid_correction(
                id_template, plan.request.tid_request.language, correction
            )
        else:
            attempt_text, replacement_count = correction_pattern.subn(
                f"$SID_ADV修正 = {correction}", id_template,
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
        (
            render_starter_save_bridge(id_template, plan.request.starter)
            if starter_save_template else render_lab_bridge_ecs(plan.request.starter)
        ),
        encoding="utf-8",
    )
    if plan.starter_run_plan is not None:
        write_configured_project(
            starter_source_dir,
            starter_dir,
            plan.starter_run_plan,
            EasyCon118Options(
                nx_model=plan.request.tid_request.nx_model,
                continue_capture_after_shiny=False,
                japanese_starter=plan.request.tid_request.language == "日文",
                seed_startup_scheme=plan.request.starter_seed_startup_scheme,
                seed_calibration_scheme=STARTER_SEED_CALIBRATION_SCHEME,
                update_precalibration=plan.request.update_precalibration,
                precalibration_context_kind="STARTER",
                debug_log_output=plan.request.starter_debug_log_output,
                frame_parity_scheme=plan.request.starter_frame_parity_scheme,
                reverse_expansion_layers=plan.request.starter_reverse_expansion_layers,
                reverse_expansion_seed_tolerances=plan.request.starter_reverse_expansion_seed_tolerances,
                reverse_expansion_frame_half_widths=plan.request.starter_reverse_expansion_frame_half_widths,
            ),
            template_name=plan.request.starter_template_name,
            precalibration_store_path=precalibration_store_path,
        )
    elif starter_dir.exists():
        shutil.rmtree(starter_dir)
    plan_path = output_dir / "flow_plan.json"
    payload = plan.to_dict()
    payload["starter_source_dir"] = str(starter_source_dir)
    id_manifest = json.loads((id_dir / "plan.json").read_text(encoding="utf-8"))
    payload["tid_source_template"] = id_manifest["template"]
    payload["lab_bridge_source"] = (
        id_manifest["template"] if starter_save_template else "legacy_shared_lab_bridge"
    )
    plan_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return plan_path


def write_resolved_exhaustive_starter_project(
    starter_source_dir: str | Path,
    starter_dir: str | Path,
    resolved: ResolvedTidStarterPlan,
    *,
    precalibration_store_path: str | Path | None = None,
) -> Path:
    """Materialize the 2.0 starter stage after stage 1 reveals the IDs."""
    starter_dir = Path(starter_dir).resolve()
    main_path = write_configured_project(
        Path(starter_source_dir).resolve(),
        starter_dir,
        resolved.starter_run_plan,
        EasyCon118Options(
            nx_model=resolved.request.tid_request.nx_model,
            continue_capture_after_shiny=False,
            japanese_starter=resolved.request.tid_request.language == "日文",
            seed_startup_scheme=resolved.request.starter_seed_startup_scheme,
            seed_calibration_scheme=STARTER_SEED_CALIBRATION_SCHEME,
            update_precalibration=resolved.request.update_precalibration,
            precalibration_context_kind="STARTER",
            debug_log_output=resolved.request.starter_debug_log_output,
            frame_parity_scheme=resolved.request.starter_frame_parity_scheme,
            reverse_expansion_layers=resolved.request.starter_reverse_expansion_layers,
            reverse_expansion_seed_tolerances=resolved.request.starter_reverse_expansion_seed_tolerances,
            reverse_expansion_frame_half_widths=resolved.request.starter_reverse_expansion_frame_half_widths,
        ),
        template_name=resolved.request.starter_template_name,
        precalibration_store_path=precalibration_store_path,
    )
    (starter_dir.parent / "resolved_identity.json").write_text(
        json.dumps(resolved.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return main_path


def validate_tid_starter_flow_runtime(
    ezcon_path: str | Path,
    id_main: str | Path,
    bridge_main: str | Path,
    starter_main: str | Path | None,
    *,
    fingerprint_warning_only: bool = False,
) -> EasyConRuntimeCheck:
    """Validate available flow stages with pinned EasyCon 1.6.4-a."""
    base = (
        validate_tid_runtime(
            ezcon_path,
            id_main,
            fingerprint_warning_only=True,
        )
        if fingerprint_warning_only
        else validate_tid_runtime(ezcon_path, id_main)
    )
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
    if starter_main is None:
        warnings.append(
            "穷举模式将在取得实际TID和SID ADV后生成御三家工程，并在运行前立即预检。"
        )
    else:
        starter = (
            validate_runtime(
                ezcon_path,
                Path(starter_main).resolve(),
                fingerprint_warning_only=True,
            )
            if fingerprint_warning_only
            else validate_runtime(ezcon_path, Path(starter_main).resolve())
        )
        errors.extend(starter.errors)
        warnings.extend(starter.warnings)
    return EasyConRuntimeCheck(not errors, tuple(errors), tuple(warnings))
