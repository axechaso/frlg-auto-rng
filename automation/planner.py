"""Automatic Ten Lines target selection and initial-seed planning."""

from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Optional

from rng.config import RNGConfig, RNGSlot
from rng.tenlines_utils import (
    IVs,
    IVsRange,
    InitialSeedResult,
    NATURES,
    SHININESS,
    SearcherResult,
    SearchWorkLimitError,
    TYPES,
    frame_to_ms,
    get_species_id,
    get_species_name,
    get_seed_time,
    initial_seed,
    ms_to_time_str,
    search_target_tiers,
)

from .support import RouteSupport, get_route_support
from .seed_modes import seed_mode_to_settings, settings_to_seed_mode
from .static_targets import is_supported_static_target


class NoMatchingTargetError(ValueError):
    """Ten Lines did not find an outcome matching the hard filters."""


class NoReachablePlanError(ValueError):
    """Matching outcomes exist, but none have an allowed initial-seed route."""


class SearchCancelledError(RuntimeError):
    """The caller cancelled a long-running tiered search."""


@dataclass(frozen=True)
class AutoSearchRequest:
    game: str
    tid: int
    sid: int
    method: str
    category: str
    location: str
    pokemon: str
    max_advances: int
    # API callers historically searched from frame 0; the GUI/CLI expose a
    # safer 3000-frame default explicitly without changing that contract.
    min_advances: int = 0
    iv_min: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)
    iv_max: tuple[int, int, int, int, int, int] = (31, 31, 31, 31, 31, 31)
    shiny: str = "Star/Square"
    nature: str = "Any"
    gender: str = "Any"
    ability: str = "Any"
    hidden_type: str = "Any"
    initial_seed_result_count: int = 1
    max_iv_combinations: int = 25_000_000
    seed_mode: Optional[int] = None
    direct_mode: bool = False
    direct_seed: Optional[str] = None
    direct_advances: Optional[int] = None

    def validate(self) -> None:
        if self.game not in {"fr_nx", "fr_nx2", "lg_nx", "lg_nx2"}:
            raise ValueError(f"首版只支持火红/叶绿 Switch 1/2，当前游戏为 {self.game!r}")
        if not (0 <= self.tid <= 65535):
            raise ValueError("TID 必须在 0-65535 之间")
        if not (0 <= self.sid <= 65535):
            raise ValueError("SID 必须在 0-65535 之间")
        if self.min_advances < 0:
            raise ValueError("最小 Advance 不能为负数")
        if self.max_advances < 0:
            raise ValueError("最大 Advance 不能为负数")
        if not self.direct_mode and self.min_advances > self.max_advances:
            raise ValueError("最小 Advance 不能大于最大 Advance")
        if self.initial_seed_result_count <= 0:
            raise ValueError("初始 Seed 候选数必须大于 0")
        if self.max_iv_combinations <= 0:
            raise ValueError("搜索工作量上限必须大于 0")
        if self.seed_mode is not None and not (0 <= self.seed_mode <= 9):
            raise ValueError("Seed 模式必须在 0-9 之间")
        if self.game.startswith("fr") and self.seed_mode == 3:
            raise ValueError("火红 NX Seed 表不包含模式 3 (stereo_r_a)，请选择自动或其他模式")
        if len(self.iv_min) != 6 or len(self.iv_max) != 6:
            raise ValueError("个体值范围必须各包含 6 项")
        for lo, hi in zip(self.iv_min, self.iv_max):
            if not (0 <= lo <= hi <= 31):
                raise ValueError("每项个体值必须满足 0 <= 最小值 <= 最大值 <= 31")
        species_id = get_species_id(self.pokemon)
        if not (1 <= species_id <= 386):
            raise ValueError("全国图鉴编号必须在 1-386 之间")
        valid_methods = {
            "Static", "Static 1", "Static 2", "Static 4",
            "Wild", "Wild 1", "Wild 2", "Wild 4", "All Wild Methods",
        }
        if self.method not in valid_methods:
            raise ValueError(f"不支持的 Ten Lines 方法: {self.method}")
        if self.shiny not in ("Any", *SHININESS):
            raise ValueError(f"不支持的闪光筛选: {self.shiny}")
        if self.nature not in ("Any", *NATURES):
            raise ValueError(f"不支持的性格筛选: {self.nature}")
        if self.gender not in {"Any", "M", "F", "-"}:
            raise ValueError(f"不支持的性别筛选: {self.gender}")
        if self.hidden_type not in ("Any", *TYPES):
            raise ValueError(f"不支持的隐藏属性筛选: {self.hidden_type}")
        if self.direct_mode:
            if self.seed_mode is None:
                raise ValueError("指定 Seed/帧数模式必须选择 Seed 模式")
            raw_seed = (self.direct_seed or "").strip().upper()
            if raw_seed.startswith("0X"):
                raw_seed = raw_seed[2:]
            if not raw_seed or len(raw_seed) > 8 or not raw_seed.isascii():
                raise ValueError("指定 Seed 必须是十六进制数")
            try:
                seed_value = int(raw_seed, 16)
            except ValueError as exc:
                raise ValueError("指定 Seed 必须是十六进制数") from exc
            if not 0 <= seed_value <= 0xFFFF:
                raise ValueError("指定 Seed 必须在 0000-FFFF 范围内")
            if self.direct_advances is None or self.direct_advances < 0:
                raise ValueError("指定消耗帧必须为非负整数")
        if "Wild" in self.method and not self.location:
            raise ValueError("野生搜索必须选择遭遇地点")
        if "Wild" not in self.method and self.category == "Roaming":
            raise ValueError(
                "首版尚未实现火叶漫游兽的截断 IV 分层和御三家存档约束，"
                "已阻止生成可能错误的方案"
            )
        if "Wild" not in self.method and not is_supported_static_target(
            self.game, self.category, get_species_name(species_id)
        ):
            raise ValueError(
                f"1.1.8 不支持该版本的静态组合: {self.category} / {self.pokemon}"
            )

    def to_ivs_range(self) -> IVsRange:
        return IVsRange(
            ivs_lower_bound=IVs(*self.iv_min),
            ivs_upper_bound=IVs(*self.iv_max),
        )


@dataclass(frozen=True)
class RunPlan:
    request: AutoSearchRequest
    target: SearcherResult
    initial_seed: InitialSeedResult
    iv_total: int
    route_support: RouteSupport
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def iv_average(self) -> float:
        return self.iv_total / 6.0

    @property
    def species_id(self) -> int:
        return get_species_id(self.request.pokemon)

    @property
    def seed_mode(self) -> int:
        seed_mode = settings_to_seed_mode(self.initial_seed.settings)
        if seed_mode is None:
            raise ValueError("选中的初始 Seed 设置无法映射到 1.1.8 Seed 模式")
        return seed_mode

    def to_rng_config(
        self,
        *,
        seed_bias: int = -4000,
        advances_bias: int = -10000,
        normal_ms_min: int = 10000,
    ) -> RNGConfig:
        return RNGConfig(
            game_version=self.request.game,
            trainer_id=self.request.tid,
            secret_id=self.request.sid,
            game_settings=self.initial_seed.settings,
            pokemon_species=self.request.pokemon,
            rng_category=self.request.category,
            rng_location=self.request.location,
            rng_method=self.target.method,
            target=RNGSlot(
                int(self.initial_seed.seed, 16),
                self.initial_seed.seed_time,
                self.initial_seed.advances,
                self.target.method,
            ),
            seed_bias=seed_bias,
            advances_bias=advances_bias,
            normal_ms_min=normal_ms_min,
        )

    def to_dict(self) -> dict:
        return {
            "request": asdict(self.request),
            "target": asdict(self.target),
            "initial_seed": asdict(self.initial_seed),
            "selection": {
                "iv_total": self.iv_total,
                "iv_average": round(self.iv_average, 2),
                "rule": "highest_iv_total_then_lowest_advances",
            },
            "execution": {
                "seed_mode": self.seed_mode,
                "game_settings": asdict(self.initial_seed.settings),
            },
            "route_support": {
                "level": self.route_support.level.value,
                "summary": self.route_support.summary,
                "can_start": self.route_support.can_start,
            },
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class PlanSearchResult:
    plan: RunPlan
    matching_outcomes: int
    reachable_outcomes: int
    feasible_routes: int

    def to_dict(self) -> dict:
        result = self.plan.to_dict()
        result["search_summary"] = {
            "matching_outcomes": self.matching_outcomes,
            "reachable_outcomes": self.reachable_outcomes,
            "feasible_routes": self.feasible_routes,
        }
        return result


def _iv_total(result: SearcherResult) -> int:
    ivs = result.ivs
    return sum((
        ivs.hp,
        ivs.attack,
        ivs.defense,
        ivs.sp_attack,
        ivs.sp_defense,
        ivs.speed,
    ))


def _target_key(result: SearcherResult) -> tuple:
    return (result.target_seed, result.method, result.pid, result.pokemon, result.level)


def _candidate_key(item: tuple[SearcherResult, InitialSeedResult, int]) -> tuple:
    target, route, iv_total = item
    return (
        -iv_total,
        route.advances,
        route.seed_time,
        int(route.seed, 16),
        target.target_seed,
        target.pid,
    )


def _direct_plan(request: AutoSearchRequest) -> PlanSearchResult:
    """Build a plan from an explicit initial Seed/Advance without target search."""
    raw_seed = (request.direct_seed or "").strip().upper()
    if raw_seed.startswith("0X"):
        raw_seed = raw_seed[2:]
    seed = f"{int(raw_seed, 16):04X}"
    settings = seed_mode_to_settings(request.seed_mode)  # validated above
    try:
        seed_time = get_seed_time(seed, request.game, settings)
    except (KeyError, ValueError) as exc:
        raise ValueError(
            f"指定 Seed {seed} 不在 {request.game} 的 Seed 表/模式 {request.seed_mode} 中"
        ) from exc
    advances = int(request.direct_advances)
    console = "NX2" if request.game.endswith("nx2") else "NX"
    total_frames = (seed_time / 16) + advances
    initial = InitialSeedResult(
        seed=seed,
        advances=advances,
        total_frames=round(total_frames),
        total_time=ms_to_time_str(frame_to_ms(total_frames, console)),
        seed_time=seed_time,
        settings=settings,
    )
    method = "Wild 1" if "Wild" in request.method else "Static 1"
    target = SearcherResult(
        target_seed=seed,
        method=method,
        pokemon=get_species_name(get_species_id(request.pokemon)),
        shiny=request.shiny,
        nature=request.nature,
        ability=request.ability,
        hidden_type=request.hidden_type,
        ivs=IVs(*request.iv_min),
        gender=request.gender,
    )
    support = get_route_support(
        request.method,
        request.category,
        request.location,
        game=request.game,
        pokemon=get_species_name(get_species_id(request.pokemon)),
    )
    warnings = ["指定 Seed/帧数模式未执行筛选搜索，直接使用用户输入的目标参数。"]
    if not support.can_start:
        warnings.append(support.summary)
    return PlanSearchResult(
        plan=RunPlan(
            request=request,
            target=target,
            initial_seed=initial,
            iv_total=sum(request.iv_min),
            route_support=support,
            warnings=tuple(warnings),
        ),
        matching_outcomes=1,
        reachable_outcomes=1,
        feasible_routes=1,
    )


def search_best_plan(
    request: AutoSearchRequest,
    *,
    target_search: Optional[Callable[..., list[SearcherResult]]] = None,
    target_tier_search: Callable[..., Iterable[tuple[int, Iterable[SearcherResult]]]] = search_target_tiers,
    seed_search: Callable[..., list[InitialSeedResult]] = initial_seed,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> PlanSearchResult:
    """Select by highest IV total, then by the smallest feasible Advance."""
    request.validate()
    if request.direct_mode:
        return _direct_plan(request)
    console = "NX2" if request.game.endswith("nx2") else "NX"

    search_kwargs = dict(
        game=request.game,
        console=console,
        tid=request.tid,
        sid=request.sid,
        method=request.method,
        category=request.category,
        location=request.location,
        pokemon=request.pokemon,
        shiny=request.shiny,
        nature=request.nature,
        gender=request.gender,
        ability=request.ability,
        hidden_type=request.hidden_type,
        ivs_range=request.to_ivs_range(),
        cancel_check=cancel_check,
    )
    if target_search is None:
        result_tiers = target_tier_search(
            **search_kwargs,
            max_iv_combinations=request.max_iv_combinations,
        )
        tiered_search = True
    else:
        result_tiers = [(None, target_search(**search_kwargs))]
        tiered_search = False

    selected: Optional[tuple[SearcherResult, InitialSeedResult, int]] = None
    matching_outcomes = 0
    reachable_outcomes = 0
    feasible_routes = 0

    for _, raw_targets in result_tiers:
        if cancel_check is not None and cancel_check():
            raise SearchCancelledError("搜索已由用户取消")
        seen_targets = set()
        tier_best: Optional[tuple[SearcherResult, InitialSeedResult, int]] = None
        for target in raw_targets:
            if cancel_check is not None and cancel_check():
                raise SearchCancelledError("搜索已由用户取消")
            key = _target_key(target)
            if key in seen_targets:
                continue
            seen_targets.add(key)
            matching_outcomes += 1
            routes = seed_search(
                game=request.game,
                console=console,
                target_seed=target.target_seed,
                result_count=request.initial_seed_result_count,
                offset=0,
                settings=(
                    seed_mode_to_settings(request.seed_mode)
                    if request.seed_mode is not None else None
                ),
                cancel_check=cancel_check,
            )
            if cancel_check is not None and cancel_check():
                raise SearchCancelledError("搜索已由用户取消")
            if not routes:
                continue
            reachable_outcomes += 1
            feasible = [
                r for r in routes
                if request.min_advances <= r.advances <= request.max_advances
            ]
            if request.seed_mode is not None:
                feasible = [
                    route for route in feasible
                    if settings_to_seed_mode(route.settings) == request.seed_mode
                ]
            feasible_routes += len(feasible)
            if not feasible:
                continue
            best_route = min(
                feasible,
                key=lambda route: (route.advances, route.seed_time, route.seed),
            )
            candidate = (target, best_route, _iv_total(target))
            if tier_best is None or _candidate_key(candidate) < _candidate_key(tier_best):
                tier_best = candidate
        if tier_best is not None:
            if selected is None or _candidate_key(tier_best) < _candidate_key(selected):
                selected = tier_best
        # Tiers arrive in descending IV-total order.  Once this tier has an
        # executable route, no lower tier can beat it.
        if tiered_search and tier_best is not None:
            break

    if cancel_check is not None and cancel_check():
        raise SearchCancelledError("搜索已由用户取消")
    if selected is None:
        if cancel_check is not None and cancel_check():
            raise SearchCancelledError("搜索已由用户取消")
        if matching_outcomes == 0:
            raise NoMatchingTargetError(
                "Ten Lines 没有找到满足宝可梦、闪光、性格和个体值条件的结果"
            )
        raise NoReachablePlanError(
            f"找到了 {matching_outcomes} 个个体结果，但没有初始 Seed 方案落在 "
            f"Advance {request.min_advances}-{request.max_advances}"
        )

    target, route, iv_total = selected
    support = get_route_support(
        request.method,
        request.category,
        request.location,
        game=request.game,
        pokemon=get_species_name(get_species_id(request.pokemon)),
    )
    warnings = []
    if not support.can_start:
        warnings.append(support.summary)
    if request.seed_mode is None:
        selected_mode = settings_to_seed_mode(route.settings)
        warnings.append(
            f"已自动选择 Seed 模式 {selected_mode}；运行前必须确认游戏内 SOUND/BUTTON MODE 与该模式一致。"
        )
    if "Safari Zone" in request.location and route.advances > 14400:
        warnings.append(
            "该狩猎区路线会进入 Teachy TV 长流程；启动前确认游戏内钓竿/道具快捷键设置。"
        )

    return PlanSearchResult(
        plan=RunPlan(
            request=request,
            target=target,
            initial_seed=route,
            iv_total=iv_total,
            route_support=support,
            warnings=tuple(warnings),
        ),
        matching_outcomes=matching_outcomes,
        reachable_outcomes=reachable_outcomes,
        feasible_routes=feasible_routes,
    )
