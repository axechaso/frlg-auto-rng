"""Declared hardware-support scope for encounter routes.

The status is deliberately conservative.  Having route coordinates in source
is not the same as completing repeated real-hardware acceptance.
"""

from dataclasses import dataclass
from enum import Enum

from .static_targets import is_supported_static_target


class RouteSupportLevel(str, Enum):
    BASELINE_118 = "baseline_118"
    EXPERIMENTAL = "experimental"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class RouteSupport:
    level: RouteSupportLevel
    summary: str
    can_start: bool


_SAFARI_AREA_ALIASES = {
    "safari zone center": "center",
    "kanto safari zone middle": "center",
    "狩猎地带 中央区": "center",
    "safari zone east": "east",
    "kanto safari zone area 1 east": "east",
    "狩猎地带 第1区东部": "east",
    "safari zone north": "north",
    "kanto safari zone area 2 north": "north",
    "狩猎地带 第2区北部": "north",
    "safari zone west": "west",
    "kanto safari zone area 3 west": "west",
    "狩猎地带 第3区西部": "west",
}


def _safari_area(location: str) -> str | None:
    normalized = (location or "").strip().lower()
    for alias, area in _SAFARI_AREA_ALIASES.items():
        if normalized == alias.lower():
            return area
    return None


def get_route_support(
    method: str,
    category: str,
    location: str,
    *,
    game: str | None = None,
    pokemon: str | None = None,
) -> RouteSupport:
    """Return the conservative first-release support status for a route."""
    method_key = (method or "").strip().lower()
    is_wild = method_key == "wild" or method_key.startswith("wild ") or "wild" in method_key
    if not is_wild:
        if category == "Roaming":
            return RouteSupport(
                RouteSupportLevel.EXPERIMENTAL,
                "漫游兽截断 IV 分层与存档御三家约束尚未实现；不开放自动运行。",
                False,
            )
        if not game or not pokemon or not is_supported_static_target(game, category, pokemon):
            return RouteSupport(
                RouteSupportLevel.UNSUPPORTED,
                "该游戏版本、静态类别与宝可梦组合不在 1.1.8 支持白名单中。",
                False,
            )
        return RouteSupport(
            RouteSupportLevel.BASELINE_118,
            "1.1.8 定点流程基线；仍需按具体目标完成实机验收。",
            True,
        )

    category_key = (category or "").lower()
    if category_key == "rocksmash":
        return RouteSupport(
            RouteSupportLevel.UNSUPPORTED,
            "1.1.8 主脚本明确暂不支持碎岩；只允许搜索，不开放自动运行。",
            False,
        )

    area = _safari_area(location)
    if area is None:
        return RouteSupport(
            RouteSupportLevel.BASELINE_118,
            "1.1.8 普通野生流程基线；仍需按地点完成实机验收。",
            True,
        )

    is_rod = category_key in {"oldrod", "goodrod", "superrod", "rod"}

    if category_key == "grass":
        return RouteSupport(
            RouteSupportLevel.EXPERIMENTAL,
            "新版 1.1.8 已包含中央/东/北/西区草丛路线，但尚未完成本机实机验收；只允许生成计划。",
            False,
        )

    if is_rod:
        return RouteSupport(
            RouteSupportLevel.EXPERIMENTAL,
            "新版 1.1.8 已包含狩猎区钓鱼路线，但尚未完成本机实机验收；只允许生成计划。",
            False,
        )

    if category_key == "surfing":
        return RouteSupport(
            RouteSupportLevel.EXPERIMENTAL,
            "新版 1.1.8 未把狩猎区冲浪列入已声明范围；只允许生成计划，不开放运行。",
            False,
        )

    return RouteSupport(
        RouteSupportLevel.UNSUPPORTED,
        "该狩猎区地点与遭遇方式目前没有可验证的自动路线。",
        False,
    )
