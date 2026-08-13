"""Plan and evaluate the starter check after FRLG TID/SID manipulation.

The TID scripts remain language-specific EasyCon templates.  This module is
the shared controller layer: it finds one reachable shiny Method 1 starter
target, then checks SID only after normal starter RNG hits that target.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from .tenlines import (
    METHOD_1,
    SearcherFilter,
    calibration_static,
    get_contiguous_seed_list,
    load_frlg_seed_data,
)
from .tenlines_utils import get_personal


STARTER_SPECIES = {
    "Bulbasaur": 1,
    "Charmander": 4,
    "Squirtle": 7,
    "妙蛙种子": 1,
    "小火龙": 4,
    "杰尼龟": 7,
}
STARTER_NAMES = {
    1: ("妙蛙种子", "Bulbasaur"),
    4: ("小火龙", "Charmander"),
    7: ("杰尼龟", "Squirtle"),
}
_SOUND_CODES = {0: "mono", 1: "stereo"}
_BUTTON_MODE_CODES = {0: "h", 1: "r", 2: "a"}
_SEED_BUTTON_CODES = {0: "a", 1: "start", 2: "l"}


class StarterVerificationStatus(str, Enum):
    CONTINUE_STARTER_RNG = "continue_starter_rng"
    SID_MISS = "sid_miss"
    SID_HIT = "sid_hit"


@dataclass(frozen=True)
class StarterSearchRequest:
    version: str
    language: str
    starter: str
    tid: int
    sid: int
    sound: int = 0
    button_mode: int = 0
    seed_button: int = 0
    min_advances: int = 1500
    max_advances: int = 10_000
    min_seed_time_ms: int = 0
    chunk_size: int = 128

    @property
    def game_code(self) -> str:
        version_code = {"火红": "fr", "叶绿": "lg"}.get(self.version)
        if version_code is None:
            raise ValueError("游戏版本必须是火红或叶绿")
        language_suffix = {"英文": "", "日文": "_jpn"}.get(self.language)
        if language_suffix is None:
            raise ValueError("ROM语言必须是英文或日文")
        return f"{version_code}{language_suffix}_nx"

    @property
    def species_id(self) -> int:
        try:
            return STARTER_SPECIES[self.starter]
        except KeyError as exc:
            raise ValueError("御三家必须是妙蛙种子、小火龙或杰尼龟") from exc

    @property
    def setting_key(self) -> str:
        try:
            return "_".join(
                (
                    _SOUND_CODES[self.sound],
                    _BUTTON_MODE_CODES[self.button_mode],
                    _SEED_BUTTON_CODES[self.seed_button],
                )
            )
        except KeyError as exc:
            raise ValueError("游戏设置参数超出TID 1.3.7支持范围") from exc

    def validate(self) -> None:
        _ = self.game_code
        _ = self.species_id
        _ = self.setting_key
        if not 0 <= self.tid <= 0xFFFF:
            raise ValueError("TID必须在0-65535之间")
        if not 0 <= self.sid <= 0xFFFF:
            raise ValueError("SID必须在0-65535之间")
        if self.min_advances < 1500:
            raise ValueError("御三家闪光搜索下限不能小于1500 ADV")
        if self.max_advances < self.min_advances:
            raise ValueError("最大ADV不能小于最小ADV")
        if self.min_seed_time_ms < 0:
            raise ValueError("最小Seed时间不能为负数")
        if self.chunk_size <= 0:
            raise ValueError("搜索分块必须大于0")


@dataclass(frozen=True)
class StarterTarget:
    game_code: str
    language: str
    species_id: int
    species_zh: str
    species_en: str
    tid: int
    sid: int
    setting_key: str
    initial_seed: int
    seed_time_ms: int
    advances: int
    pid: int
    ivs: tuple[int, int, int, int, int, int]
    nature: int
    gender: int
    ability: int
    shiny: int

    @property
    def pid_hex(self) -> str:
        return f"{self.pid:08X}"

    @property
    def seed_hex(self) -> str:
        return f"{self.initial_seed:04X}"

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["pid_hex"] = self.pid_hex
        result["seed_hex"] = self.seed_hex
        return result


@dataclass(frozen=True)
class StarterVerificationResult:
    status: StarterVerificationStatus
    target_pid_hit: bool
    shiny_detected: bool


def find_earliest_shiny_starter(request: StarterSearchRequest) -> StarterTarget:
    """Return the lowest reachable shiny Method 1 starter at or after ADV 1500."""
    request.validate()
    seed_data = load_frlg_seed_data(request.game_code)
    available_settings = set(seed_data[1])
    if request.setting_key not in available_settings:
        choices = "、".join(sorted(available_settings)) or "无"
        raise ValueError(
            f"TenLines的{request.language}{request.version} Switch Seed表不支持"
            f"设置{request.setting_key}；可用设置：{choices}"
        )
    seeds = get_contiguous_seed_list(
        seed_data,
        request.setting_key,
        request.game_code,
        "none",
    )
    seeds = [seed for seed in seeds if seed["seed_time"] >= request.min_seed_time_ms]
    if not seeds:
        raise ValueError("当前设置下没有满足最小Seed时间的可达Seed")

    gender_ratio = get_personal(request.species_id, request.game_code)["gender"]
    shiny_filter = SearcherFilter(shiny=3)
    tsv = request.tid ^ request.sid
    chunk_start = request.min_advances
    while chunk_start <= request.max_advances:
        chunk_end = min(chunk_start + request.chunk_size - 1, request.max_advances)
        rows = calibration_static(
            seeds,
            chunk_start,
            chunk_end,
            0,
            METHOD_1,
            tsv,
            gender_ratio=gender_ratio,
            filter_obj=shiny_filter,
            ttv_advances_range=(0, 0),
        )
        if rows:
            row = min(
                rows,
                key=lambda item: (
                    item["advances"],
                    item["seed_time"],
                    item["initial_seed"],
                    item["pid"],
                ),
            )
            species_zh, species_en = STARTER_NAMES[request.species_id]
            return StarterTarget(
                game_code=request.game_code,
                language=request.language,
                species_id=request.species_id,
                species_zh=species_zh,
                species_en=species_en,
                tid=request.tid,
                sid=request.sid,
                setting_key=request.setting_key,
                initial_seed=row["initial_seed"],
                seed_time_ms=row["seed_time"],
                advances=row["advances"],
                pid=row["pid"],
                ivs=tuple(row["ivs"]),
                nature=row["nature"],
                gender=row["gender"],
                ability=row["ability"],
                shiny=row["shiny"],
            )
        chunk_start = chunk_end + 1
    raise LookupError(
        f"ADV {request.min_advances}-{request.max_advances} 内没有可达的闪光御三家"
    )


def sid_advance_scan_offsets(radius: int) -> tuple[int, ...]:
    """Return a deterministic correction order: 0,+1,-1,+2,-2,..."""
    if radius < 0:
        raise ValueError("SID ADV扫描半径不能为负数")
    result = [0]
    for distance in range(1, radius + 1):
        result.extend((distance, -distance))
    return tuple(result)


def evaluate_starter_verification(
    target: StarterTarget,
    observed_pid: int,
    shiny_detected: bool,
) -> StarterVerificationResult:
    """Check SID only after the normal starter RNG has hit its target PID."""
    target_pid_hit = observed_pid == target.pid
    if not target_pid_hit:
        return StarterVerificationResult(
            status=StarterVerificationStatus.CONTINUE_STARTER_RNG,
            target_pid_hit=False,
            shiny_detected=shiny_detected,
        )
    if not shiny_detected:
        return StarterVerificationResult(
            status=StarterVerificationStatus.SID_MISS,
            target_pid_hit=True,
            shiny_detected=False,
        )

    return StarterVerificationResult(
        status=StarterVerificationStatus.SID_HIT,
        target_pid_hit=True,
        shiny_detected=True,
    )
