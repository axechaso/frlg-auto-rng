"""Verified battle EV journals for SID reverse observations.

This module does not drive a controller or infer victory from encounter counts.
The caller must confirm both defeat/experience and the target's eligibility.
Vectors use the application's HP / Atk / Def / SpA / SpD / Spe order.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Mapping

from .tenlines_utils import get_data_dir

EVVector = tuple[int, int, int, int, int, int]
EV_KEYS = ("EVHP", "EVATK", "EVDEF", "EVSPA", "EVSPD", "EVSPE")
TRAINING_PREFIX = "SIDTRAIN|"
MAX_JOURNAL_DEFEATS = 10_000
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
# MonGainEVs visits native stat order, which differs from UI order. This
# matters when several EV yields compete for the last points below 510.
_NATIVE_STAT_ORDER = (0, 1, 2, 5, 3, 4)


def validate_evs(values: tuple[int, ...]) -> None:
    if len(values) != 6 or any(type(value) is not int for value in values):
        raise ValueError("six integer effort values are required")
    if any(not 0 <= value <= 255 for value in values):
        raise ValueError("each effort value must be in 0-255")
    if sum(values) > 510:
        raise ValueError("the six effort values must total no more than 510")


@lru_cache(maxsize=1)
def _gen3_ev_yields() -> tuple[EVVector, ...]:
    # Reuse the bundled Gen 3 personal table, not a modern-generation table.
    data = (Path(get_data_dir()) / "Personal/Gen3/personal_rsefrlg.bin").read_bytes()
    if len(data) % 0x1C or len(data) < 387 * 0x1C:
        raise ValueError("invalid Gen 3 personal table for effort yields")
    result = []
    for offset in range(0, len(data), 0x1C):
        packed = int.from_bytes(data[offset + 10:offset + 12], "little")
        native = tuple((packed >> shift) & 3 for shift in range(0, 12, 2))
        result.append((native[0], native[1], native[2], native[4], native[5], native[3]))
    return tuple(result)


def gen3_ev_yield(species_id: int) -> EVVector:
    if type(species_id) is not int or not 1 <= species_id <= 386:
        raise ValueError("defeated species must have a National Dex number in 1-386")
    values = _gen3_ev_yields()[species_id]
    if not 1 <= sum(values) <= 3:
        raise ValueError(f"invalid Gen 3 effort yield for species {species_id}")
    return values


def award_defeat_evs(
    current: EVVector, species_id: int, *, macho_brace: bool = False,
    had_pokerus: bool = False,
) -> EVVector:
    """Award one eligible defeat with Gen 3 stat/total caps and stat order.

    Exp. Share affects eligibility, not the EV quantity. Pokerus remains a
    multiplier after recovery (the game checks whether the mon has had it).
    """
    validate_evs(current)
    if type(macho_brace) is not bool or type(had_pokerus) is not bool:
        raise ValueError("EV multipliers must be explicit boolean values")
    gain = gen3_ev_yield(species_id)
    multiplier = (2 if macho_brace else 1) * (2 if had_pokerus else 1)
    values = list(current)
    total = sum(values)
    for index in _NATIVE_STAT_ORDER:
        if total >= 510:
            break
        increase = min(gain[index] * multiplier, 255 - values[index], 510 - total)
        values[index] += increase
        total += increase
    return tuple(values)  # type: ignore[return-value]


@dataclass(frozen=True)
class EVTrainingContext:
    session_id: str
    pokemon_index: int
    species_id: int
    initial_level: int
    initial_evs: EVVector
    source_type: str = "STATIC"
    location: str = ""
    recipient: str = "PARTICIPANT"
    macho_brace: bool = False
    had_pokerus: bool = False

    def validate(self) -> None:
        if not isinstance(self.session_id, str) or not _SESSION_ID.fullmatch(self.session_id):
            raise ValueError("invalid training session identifier")
        if type(self.pokemon_index) is not int or not 1 <= self.pokemon_index <= 6:
            raise ValueError("training party slot must be in 1-6")
        if type(self.species_id) is not int or not 1 <= self.species_id <= 386:
            raise ValueError("training target Dex number must be in 1-386")
        if type(self.initial_level) is not int or not 1 <= self.initial_level <= 100:
            raise ValueError("training initial level must be in 1-100")
        validate_evs(self.initial_evs)
        if self.source_type not in ("STATIC", "WILD"):
            raise ValueError("training source must be STATIC or WILD")
        if self.source_type == "WILD" and not self.location.strip():
            raise ValueError("wild training target requires its original encounter location")
        if self.recipient not in ("PARTICIPANT", "EXP_SHARE"):
            raise ValueError("unsupported training experience recipient mode")
        if self.macho_brace and self.recipient == "EXP_SHARE":
            raise ValueError("Exp. Share and Macho Brace cannot be held simultaneously")
        if type(self.macho_brace) is not bool or type(self.had_pokerus) is not bool:
            raise ValueError("EV multipliers must be explicit boolean values")


@dataclass(frozen=True)
class EVTrainingSnapshot:
    context: EVTrainingContext
    defeated_species: tuple[int, ...]
    level: int

    @property
    def sequence(self) -> int:
        return len(self.defeated_species)

    @property
    def effort_values(self) -> EVVector:
        self.context.validate()
        if not isinstance(self.defeated_species, tuple) or self.sequence > MAX_JOURNAL_DEFEATS:
            raise ValueError("invalid or overlong training defeat journal")
        if type(self.level) is not int or not self.context.initial_level <= self.level <= 100:
            raise ValueError("invalid training observation level")
        if (self.sequence == 0 and self.level != self.context.initial_level) or (
            self.sequence > 0 and self.level <= self.context.initial_level
        ):
            raise ValueError("training stats require an initial sample or confirmed level-up")
        values = self.context.initial_evs
        for species_id in self.defeated_species:
            values = award_defeat_evs(
                values, species_id, macho_brace=self.context.macho_brace,
                had_pokerus=self.context.had_pokerus,
            )
        return values


class EVTrainingLedger:
    def __init__(self, context: EVTrainingContext):
        context.validate()
        self.context = context
        self.defeated_species: list[int] = []
        self.effort_values = context.initial_evs
        self._last_observation: EVTrainingSnapshot | None = None

    def commit_defeat(
        self, species_id: int, *, sequence: int,
        experience_confirmed: bool, recipient_confirmed: bool,
    ) -> None:
        if experience_confirmed is not True or recipient_confirmed is not True:
            raise ValueError("defeat requires confirmed experience and an eligible recipient")
        if type(sequence) is not int or sequence != len(self.defeated_species) + 1:
            raise ValueError("duplicate, missing or out-of-order training defeat")
        if sequence > MAX_JOURNAL_DEFEATS:
            raise ValueError("training defeat journal limit reached")
        values = award_defeat_evs(
            self.effort_values, species_id, macho_brace=self.context.macho_brace,
            had_pokerus=self.context.had_pokerus,
        )
        self.defeated_species.append(species_id)
        self.effort_values = values

    def observe(self, *, level: int, sequence: int, recalculation: str) -> EVTrainingSnapshot:
        if type(sequence) is not int or sequence != len(self.defeated_species):
            raise ValueError("observation does not refer to the current defeat journal")
        expected = "INITIAL" if sequence == 0 else "LEVEL_UP"
        if recalculation != expected:
            raise ValueError("training stats must be sampled after confirmed stat recalculation")
        snapshot = EVTrainingSnapshot(self.context, tuple(self.defeated_species), level)
        snapshot.effort_values  # Validate before updating any observation cursor.
        previous = self._last_observation
        if previous is None and sequence != 0:
            raise ValueError("training journal is missing the initial stat observation")
        if previous is not None:
            if level < previous.level or (sequence > previous.sequence and level <= previous.level):
                raise ValueError("EV gains without a level-up cannot be used as refreshed stats")
            if sequence == previous.sequence and level != previous.level:
                raise ValueError("level changed without a recorded training defeat")
        self._last_observation = snapshot
        return snapshot


def _integer(values: Mapping[str, str], key: str) -> int:
    try:
        return int(values[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"training record requires integer {key}") from exc


def _flag(values: Mapping[str, str], key: str) -> bool:
    value = _integer(values, key)
    if value not in (0, 1):
        raise ValueError(f"training record requires 0/1 {key}")
    return bool(value)


def _evs(values: Mapping[str, str]) -> EVVector:
    result = tuple(_integer(values, key) for key in EV_KEYS)
    validate_evs(result)
    return result  # type: ignore[return-value]


class EVTrainingLog:
    """Fail-closed v1 protocol consumer; old encounter counters are not events."""

    def __init__(self):
        self.ledgers: dict[str, EVTrainingLedger] = {}
        self.party_sessions: dict[int, str] = {}

    def consume(self, record_type: str, values: Mapping[str, str]) -> EVTrainingSnapshot | None:
        if _integer(values, "V") != 1:
            raise ValueError("unsupported SID training protocol version")
        session_id = values.get("SESSION", "")
        pokemon_index = _integer(values, "MON")
        if record_type == "BEGIN":
            context = EVTrainingContext(
                session_id=session_id, pokemon_index=pokemon_index,
                species_id=_integer(values, "DEX"), initial_level=_integer(values, "LEVEL"),
                initial_evs=_evs(values), source_type=values.get("SOURCE", ""),
                location=values.get("LOCATION", ""), recipient=values.get("RECIPIENT", ""),
                macho_brace=_flag(values, "MACHO_BRACE"), had_pokerus=_flag(values, "POKERUS"),
            )
            if session_id in self.ledgers or pokemon_index in self.party_sessions:
                raise ValueError("duplicate or mixed training sessions for one party slot")
            self.ledgers[session_id] = EVTrainingLedger(context)
            self.party_sessions[pokemon_index] = session_id
            return None
        ledger = self.ledgers.get(session_id)
        if ledger is None or ledger.context.pokemon_index != pokemon_index:
            raise ValueError("training record has no matching session/party slot")
        if record_type == "DEFEAT":
            if values.get("RESULT") != "DEFEATED":
                raise ValueError("flee/capture/unknown outcomes must not commit effort values")
            ledger.commit_defeat(
                _integer(values, "FOE"), sequence=_integer(values, "SEQ"),
                experience_confirmed=_flag(values, "XP_CONFIRMED"),
                recipient_confirmed=_flag(values, "RECIPIENT_CONFIRMED"),
            )
            return None
        if record_type != "OBS":
            raise ValueError(f"unknown SID training record type: {record_type}")
        if _integer(values, "DEX") != ledger.context.species_id:
            raise ValueError("training target evolved or a different Pokemon was observed")
        if values.get("SOURCE") != ledger.context.source_type or values.get("LOCATION", "") != ledger.context.location:
            raise ValueError("training target's original encounter information changed")
        if _evs(values) != ledger.effort_values:
            raise ValueError("observation effort values disagree with the confirmed defeat journal")
        return ledger.observe(
            level=_integer(values, "LEVEL"), sequence=_integer(values, "SEQ"),
            recalculation=values.get("RECALC", ""),
        )
