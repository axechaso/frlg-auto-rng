"""Resolve the effective encounter frame parity policy."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FrameParityPolicy:
    requested: int
    effective: int
    forced: bool
    reason: str | None


def resolve_frame_parity(
    *, requested: int, mystery_gift_enabled: bool, is_egg: bool
) -> FrameParityPolicy:
    if type(requested) is not int or requested not in (0, 1):
        raise ValueError("帧奇偶方案必须是整数 0 或 1")
    if type(mystery_gift_enabled) is not bool or type(is_egg) is not bool:
        raise ValueError("神秘礼物和孵蛋状态必须是布尔值")
    if mystery_gift_enabled:
        return FrameParityPolicy(requested, 1, True, "当前存档已开启神秘礼物")
    if is_egg:
        return FrameParityPolicy(requested, 1, True, "孵蛋流程固定使用方案 1")
    return FrameParityPolicy(requested, requested, False, None)
