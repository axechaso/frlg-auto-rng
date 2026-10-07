"""Shared route and request policy for independent SID traversal."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .frame_parity import resolve_frame_parity
from .support import get_route_support
from .static_targets import game_family
from . import STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME


@dataclass(frozen=True)
class TraversalAvailability:
    supported: bool
    reason: str
    route_key: str | None
    encounter_kind: str | None


def traversal_availability(
    *,
    method: str,
    category: str,
    location: str,
    game: str,
    pokemon: str,
    direct_mode: bool = False,
    item_mode: bool = False,
) -> TraversalAvailability:
    if direct_mode:
        return TraversalAvailability(False, "指定 Seed/帧数不是逐 SID 搜索。", None, None)
    if item_mode:
        return TraversalAvailability(False, "道具乱数与 SID 遍历互斥。", None, None)
    method_key = re.sub(r"[\s_-]+", "", (method or "")).lower()
    if not method_key or not category or not game or not pokemon:
        return TraversalAvailability(False, "请先选择完整的遭遇方式、类别和目标。", None, None)
    wild_methods = {"wild", "wild1", "wild2", "wild4", "allwildmethods"}
    static_methods = {"static", "static1", "static2", "static4"}
    is_wild = "wild" in method_key
    if is_wild and method_key not in wild_methods:
        return TraversalAvailability(False, "该野生方法不在 SID 遍历支持范围内。", None, "wild")
    if not is_wild and method_key not in static_methods:
        return TraversalAvailability(False, "该静态方法不在 SID 遍历支持范围内。", None, "static")
    route = get_route_support(method_key, category, location, game=game, pokemon=pokemon)
    kind = "wild" if is_wild else "static"
    if not route.can_start:
        return TraversalAvailability(False, route.summary, None, kind)
    if kind == "static" and category.strip() == "Gift":
        return TraversalAvailability(
            False,
            "礼物目标可能经过额外野生 Seed 复核；当前没有区分该复核与领取目标的终态证明。",
            None,
            kind,
        )
    family = game_family(game) or game
    route_key = ":".join((kind, family, category.strip(), pokemon.strip(), location.strip()))
    return TraversalAvailability(True, route.summary, route_key, kind)


def validate_traversal_request(request, options, template_name: str) -> TraversalAvailability:
    request.validate()
    if request.direct_mode:
        raise ValueError("SID 遍历不支持指定 Seed/帧数模式")
    if options.item_rng_mode:
        raise ValueError("道具乱数与 SID 遍历互斥")
    if options.continue_capture_after_shiny:
        raise ValueError("SID 遍历自行处理闪光抓获与反查，请关闭普通“出闪后继续抓捕”选项")
    if template_name not in {STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME}:
        raise ValueError("SID 遍历入口只能是正式版或时间轴版")
    availability = traversal_availability(
        method=request.method,
        category=request.category,
        location=request.location,
        game=request.game,
        pokemon=request.pokemon,
        direct_mode=request.direct_mode,
        item_mode=options.item_rng_mode,
    )
    if not availability.supported:
        raise ValueError(availability.reason)
    if type(options.record_shiny_video) is not bool or type(options.update_precalibration) is not bool:
        raise ValueError("录像与预校准偏好必须是布尔值")
    if type(options.mystery_gift_enabled) is not bool:
        raise ValueError("神秘礼物状态必须是布尔值")
    policy = resolve_frame_parity(
        requested=options.frame_parity_scheme,
        mystery_gift_enabled=options.mystery_gift_enabled,
        is_egg=False,
    )
    if policy.effective != options.frame_parity_scheme:
        raise ValueError("SID 遍历计划的有效帧奇偶与存档神秘礼物状态矛盾")
    return availability


__all__ = ["TraversalAvailability", "traversal_availability", "validate_traversal_request"]
