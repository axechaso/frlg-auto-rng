"""GBA/Custom arithmetic ported from EonTimer 3.0.0-rc.8 (MIT).

Reference: DasAmpharos/EonTimer @ ead211d6e4251c4f08345cc9e56e76d3cb2a29bd.
See third_party/EonTimer-LICENSE.md. No Qt clock or controller is involved here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum

UPSTREAM_COMMIT = "ead211d6e4251c4f08345cc9e56e76d3cb2a29bd"
GBA_FPS = 59.7275
GBA_FRAME_MS = 1000 / GBA_FPS
INT_MAX = 2**31 - 1  # EonTimer Custom input field range


class Unit(StrEnum):
    MILLISECONDS = "ms"
    ADVANCES = "Advances"
    HEX = "Seed (Hex)"


def to_milliseconds(advances: int) -> int:
    if type(advances) is not int or abs(advances) > INT_MAX:
        raise ValueError("目标帧或帧差必须为 32 位有符号整数")
    # Upstream Calibrator.to_milliseconds uses ties-to-even, not truncation.
    return round(GBA_FRAME_MS * advances)


@dataclass(frozen=True)
class CustomPhase:
    unit: Unit
    target: int
    calibration_ms: float = 0

    def duration_ms(self) -> float:
        if not isinstance(self.unit, Unit):
            raise ValueError("未知 Custom 单位")
        if type(self.target) is not int or not 0 <= self.target <= INT_MAX:
            raise ValueError("阶段目标必须为 0–2147483647 的整数")
        if type(self.calibration_ms) not in (int, float) or not math.isfinite(self.calibration_ms) or abs(self.calibration_ms) > INT_MAX:
            raise ValueError("校准毫秒必须是 EonTimer 输入范围内的有限值")
        target_ms = self.target if self.unit == Unit.MILLISECONDS else to_milliseconds(self.target)
        return target_ms + self.calibration_ms

    def calibrated(self, hit: int) -> CustomPhase:
        self.duration_ms()
        if type(hit) is not int or not 0 <= hit <= INT_MAX:
            raise ValueError("实测命中值必须是非负整数")
        difference = self.target - hit
        delta = difference if self.unit == Unit.MILLISECONDS else to_milliseconds(difference)
        return CustomPhase(self.unit, self.target, self.calibration_ms + delta)


@dataclass(frozen=True)
class Countergroup:
    """Manual EonTimer settings only. No runner, ECS edits or game inputs.

    F1/F2 are the user's separate GBA Custom targets. The final reverse-search
    target is explicit: do not assume it equals F2, or silently sum F1+F2.
    """
    seed_ms: int
    f1_frames: int
    f2_frames: int
    target_advances: int
    seed_calibration_ms: float = 0
    f1_calibration_ms: float = 0
    f2_calibration_ms: float = 0

    def validate(self) -> None:
        if type(self.target_advances) is not int or not 0 <= self.target_advances <= INT_MAX:
            raise ValueError("反查目标消耗帧必须是非负整数")
        for name, phase in self.phases():
            duration = phase.duration_ms()
            if not math.isfinite(duration) or duration < 0:
                raise ValueError(f"{name} 校准后的时长不能为负或非有限值")

    def phases(self) -> tuple[tuple[str, CustomPhase], ...]:
        return (
            ("Seed", CustomPhase(Unit.MILLISECONDS, self.seed_ms, self.seed_calibration_ms)),
            ("F1", CustomPhase(Unit.ADVANCES, self.f1_frames, self.f1_calibration_ms)),
            ("F2", CustomPhase(Unit.ADVANCES, self.f2_frames, self.f2_calibration_ms)),
        )

    def calibrated(self, hit_seed_ms: int, hit_advances: int, *, candidates: int) -> Countergroup:
        self.validate()
        if type(candidates) is not int or candidates != 1:
            raise ValueError("反查结果不是唯一候选，请先缩小 IV 范围；不更新校准")
        if type(hit_advances) is not int or not 0 <= hit_advances <= INT_MAX:
            raise ValueError("命中消耗帧必须是非负整数")
        seed = self.phases()[0][1].calibrated(hit_seed_ms)
        updated = replace(self, seed_calibration_ms=seed.calibration_ms,
                          f2_calibration_ms=self.f2_calibration_ms + to_milliseconds(self.target_advances - hit_advances))
        updated.validate()
        return updated

    def settings(self) -> list[dict]:
        self.validate()
        elapsed = 0
        rows = []
        for name, phase in self.phases():
            duration = phase.duration_ms()
            elapsed += duration
            rows.append({"phase": name, "unit": phase.unit.value, "target": phase.target,
                         "calibration_ms": phase.calibration_ms, "duration_ms": duration,
                         "from_start_ms": elapsed})
        return rows
