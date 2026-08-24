"""Reverse Gen 3 shiny Pokemon observations into PSV and SID candidates.

The PID recovery is limited to the standard GBA Method 1/2/4 PID-IV
relationships.  Once a shifted PSV is known, shiny status alone leaves the
low three bits of ``TID xor SID`` unknown, so exactly eight SIDs remain.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterable, Sequence

from .tenlines import (
    METHOD_1,
    METHOD_2,
    METHOD_4,
    get_gender,
    pokerng_jump,
    pokerng_next,
    pokerngr_next,
    recover_pokerng_iv_method12,
    recover_pokerng_iv_method4,
)


METHOD_NAMES = {
    METHOD_1: "Method1",
    METHOD_2: "Method2",
    METHOD_4: "Method4",
}
DEFAULT_SID_SEARCH_ADVANCES = 10_000


@dataclass(frozen=True, order=True)
class PIDCandidate:
    pid: int
    method: int
    origin_seed: int
    ivs: tuple[int, int, int, int, int, int]

    @property
    def method_name(self) -> str:
        return METHOD_NAMES[self.method]

    @property
    def psv(self) -> int:
        return pid_to_psv(self.pid)


@dataclass(frozen=True)
class ShinyEvidence:
    pokemon_index: int
    candidates: tuple[PIDCandidate, ...]

    @property
    def psvs(self) -> frozenset[int]:
        return frozenset(candidate.psv for candidate in self.candidates)


@dataclass(frozen=True)
class SIDAdvanceCandidate:
    sid: int
    advance: int


@dataclass(frozen=True)
class SIDReverseResult:
    tid: int
    common_psvs: tuple[int, ...]
    sid_candidates: tuple[int, ...]
    sid_advances: tuple[SIDAdvanceCandidate, ...]
    used_pokemon: int

    @property
    def psv_is_unique(self) -> bool:
        return len(self.common_psvs) == 1

    @property
    def selected_sid(self) -> int | None:
        return self.sid_advances[0].sid if self.sid_advances else None

    @property
    def selected_advance(self) -> int | None:
        return self.sid_advances[0].advance if self.sid_advances else None


def pid_to_psv(pid: int) -> int:
    """Return the conventional 13-bit Gen 3 PSV."""
    if not 0 <= pid <= 0xFFFFFFFF:
        raise ValueError("PID must be in 00000000-FFFFFFFF")
    return (((pid >> 16) ^ (pid & 0xFFFF)) >> 3) & 0x1FFF


def sid_candidates_for_psv(tid: int, psv: int) -> tuple[int, ...]:
    """Return all SIDs whose shifted TSV equals ``psv`` for ``tid``."""
    if not 0 <= tid <= 0xFFFF:
        raise ValueError("TID must be in 0-65535")
    if not 0 <= psv <= 0x1FFF:
        raise ValueError("PSV must be in 0-8191")
    return tuple(sorted(tid ^ ((psv << 3) | low_bits) for low_bits in range(8)))


def canonical_sid_for_psv(tid: int, psv: int) -> int:
    """Return the low-three-bits-cleared SID used by common Gen 3 tools."""
    if not 0 <= tid <= 0xFFFF:
        raise ValueError("TID must be in 0-65535")
    if not 0 <= psv <= 0x1FFF:
        raise ValueError("PSV must be in 0-8191")
    return (tid ^ (psv << 3)) & 0xFFF8


def first_sid_advances(
    tid: int,
    sid_candidates: Sequence[int],
    *,
    max_advances: int = DEFAULT_SID_SEARCH_ADVANCES,
) -> tuple[SIDAdvanceCandidate, ...]:
    """Return candidates first seen in the configured TID-seed ADV window.

    This follows the TID/SID 1.3.7 convention: the 32-bit LCG starts at
    ``seed = TID``; after one forward call its high 16 bits are checked as
    the SID at ADV 0.
    """
    if not 0 <= tid <= 0xFFFF:
        raise ValueError("TID must be in 0-65535")
    if max_advances <= 0:
        raise ValueError("max_advances must be positive")
    remaining = {int(sid) for sid in sid_candidates}
    if any(not 0 <= sid <= 0xFFFF for sid in remaining):
        raise ValueError("SID candidates must be in 0-65535")
    found: list[SIDAdvanceCandidate] = []
    seed = tid
    for advance in range(max_advances):
        seed = pokerng_next(seed)
        sid = seed >> 16
        if sid in remaining:
            found.append(SIDAdvanceCandidate(sid, advance))
            remaining.remove(sid)
            if not remaining:
                break
    return tuple(sorted(found, key=lambda item: (item.advance, item.sid)))


def sid_at_advance(tid: int, advance: int) -> int:
    """Return the SID produced at a TID/SID 1.3.7 ADV.

    The script treats the first LCG result after ``seed = TID`` as ADV 0,
    matching :func:`first_sid_advances`.
    """
    if not 0 <= tid <= 0xFFFF:
        raise ValueError("TID must be in 0-65535")
    if advance < 0:
        raise ValueError("SID advance must be non-negative")
    seed = pokerng_jump(tid, advance + 1)
    return (seed >> 16) & 0xFFFF


def is_shiny_for_ids(pid: int, tid: int, sid: int) -> bool:
    if not 0 <= tid <= 0xFFFF or not 0 <= sid <= 0xFFFF:
        raise ValueError("TID and SID must be in 0-65535")
    shiny_xor = tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)
    return shiny_xor < 8


def _reverse_pid_words(iv_seed: int, skipped_calls: int) -> tuple[int, int]:
    state = iv_seed
    for _ in range(skipped_calls):
        state = pokerngr_next(state)
    state = pokerngr_next(state)
    high = state >> 16
    state = pokerngr_next(state)
    low = state >> 16
    origin_seed = pokerngr_next(state)
    return ((high << 16) | low), origin_seed


def recover_pid_candidates(
    ivs: Sequence[int],
    nature: int,
    *,
    methods: Sequence[int] = (METHOD_1, METHOD_2, METHOD_4),
    gender: int | None = None,
    gender_ratio: int | None = None,
) -> tuple[PIDCandidate, ...]:
    """Recover Method 1/2/4 PIDs for exact IVs and a nature index.

    ``gender`` follows the existing searcher convention: 0 male, 1 female,
    2 genderless.  It is only applied when ``gender_ratio`` is also supplied.
    """
    if len(ivs) != 6 or any(not 0 <= int(iv) <= 31 for iv in ivs):
        raise ValueError("six IVs in 0-31 are required")
    if not 0 <= nature < 25:
        raise ValueError("nature must be in 0-24")
    unsupported = set(methods) - set(METHOD_NAMES)
    if unsupported:
        raise ValueError(f"unsupported methods: {sorted(unsupported)}")
    if (gender is None) != (gender_ratio is None):
        raise ValueError("gender and gender_ratio must be supplied together")

    exact_ivs = tuple(int(iv) for iv in ivs)
    hp, atk, defense, spa, spd, spe = exact_ivs
    method12_seeds: list[int] | None = None
    method4_seeds: list[int] | None = None
    found: set[PIDCandidate] = set()

    for method in methods:
        if method in (METHOD_1, METHOD_2):
            if method12_seeds is None:
                method12_seeds = recover_pokerng_iv_method12(
                    hp, atk, defense, spa, spd, spe
                )
            seeds = method12_seeds
            skipped_calls = 1 if method == METHOD_2 else 0
        else:
            if method4_seeds is None:
                method4_seeds = recover_pokerng_iv_method4(
                    hp, atk, defense, spa, spd, spe
                )
            seeds = method4_seeds
            skipped_calls = 0

        for iv_seed in seeds:
            pid, origin_seed = _reverse_pid_words(iv_seed, skipped_calls)
            if pid % 25 != nature:
                continue
            if gender is not None and get_gender(pid, int(gender_ratio)) != gender:
                continue
            found.add(PIDCandidate(pid, method, origin_seed, exact_ivs))

    return tuple(sorted(found))


def recover_pid_candidates_from_ranges(
    iv_min: Sequence[int],
    iv_max: Sequence[int],
    nature: int,
    *,
    methods: Sequence[int] = (METHOD_1, METHOD_2, METHOD_4),
    gender: int | None = None,
    gender_ratio: int | None = None,
    max_iv_combinations: int = 200_000,
) -> tuple[PIDCandidate, ...]:
    """Recover candidates across an inclusive six-stat IV range."""
    if len(iv_min) != 6 or len(iv_max) != 6:
        raise ValueError("six lower and upper IV bounds are required")
    ranges = []
    combinations = 1
    for lower, upper in zip(iv_min, iv_max):
        lower = int(lower)
        upper = int(upper)
        if not 0 <= lower <= upper <= 31:
            raise ValueError("IV bounds must satisfy 0 <= min <= max <= 31")
        ranges.append(range(lower, upper + 1))
        combinations *= upper - lower + 1
    if combinations > max_iv_combinations:
        raise ValueError(
            f"IV range contains {combinations} combinations; "
            "feed another Rare Candy or raise max_iv_combinations"
        )

    found: set[PIDCandidate] = set()
    for ivs in product(*ranges):
        found.update(
            recover_pid_candidates(
                ivs,
                nature,
                methods=methods,
                gender=gender,
                gender_ratio=gender_ratio,
            )
        )
    return tuple(sorted(found))


def intersect_candidate_psvs(
    evidence: Iterable[ShinyEvidence | Iterable[PIDCandidate]],
) -> tuple[int, ...]:
    common: set[int] | None = None
    used = 0
    for item in evidence:
        candidates = item.candidates if isinstance(item, ShinyEvidence) else tuple(item)
        psvs = {candidate.psv for candidate in candidates}
        if not psvs:
            return ()
        common = psvs if common is None else common & psvs
        used += 1
        if not common:
            return ()
    if used == 0 or common is None:
        return ()
    return tuple(sorted(common))


def reverse_sid(tid: int, evidence: Sequence[ShinyEvidence]) -> SIDReverseResult:
    common_psvs = intersect_candidate_psvs(evidence)
    sid_candidates: tuple[int, ...] = ()
    sid_advances: tuple[SIDAdvanceCandidate, ...] = ()
    if len(common_psvs) == 1:
        sid_candidates = sid_candidates_for_psv(tid, common_psvs[0])
        sid_advances = first_sid_advances(tid, sid_candidates)
    return SIDReverseResult(
        tid,
        common_psvs,
        sid_candidates,
        sid_advances,
        len(evidence),
    )
