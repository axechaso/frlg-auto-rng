"""Observation and log layer for the Gen 3 SID reverse helper."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Sequence

from assets.game_text import location_to_en

from .sid_reverse import (
    PIDCandidate,
    ShinyEvidence,
    SIDReverseResult,
    recover_pid_candidates_from_ranges,
    reverse_sid,
)
from .tenlines_utils import (
    IVsObservation,
    NATURES,
    get_personal,
    get_species_name,
    iv_calculator,
    load_frlg_encounters,
)


SIDREV_PREFIX = "SIDREV|"
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_STAT_KEYS = ("HP", "ATK", "DEF", "SPA", "SPD", "SPE")
_EV_KEYS = ("EVHP", "EVATK", "EVDEF", "EVSPA", "EVSPD", "EVSPE")
SOURCE_STATIC = "STATIC"
SOURCE_WILD = "WILD"
_CATEGORY_ORDER = ("Grass", "Surfing", "OldRod", "GoodRod", "SuperRod", "RockSmash")


@dataclass(frozen=True)
class SIDObservation:
    pokemon_index: int
    species_id: int
    nature: int
    level: int
    stats: tuple[int, int, int, int, int, int]
    gender: int | None = None
    source_type: str = SOURCE_STATIC
    location: str = ""
    effort_values: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)


@dataclass(frozen=True)
class PokemonReverseSummary:
    pokemon_index: int
    species_id: int
    species_name: str
    nature: int
    iv_min: tuple[int, int, int, int, int, int]
    iv_max: tuple[int, int, int, int, int, int]
    observations: int
    candidates: tuple[PIDCandidate, ...]
    source_type: str
    location: str
    effort_values: tuple[int, int, int, int, int, int]
    encounter_categories: tuple[str, ...]

    @property
    def psvs(self) -> tuple[int, ...]:
        return tuple(sorted({candidate.psv for candidate in self.candidates}))


@dataclass(frozen=True)
class TeamReverseSummary:
    pokemon: tuple[PokemonReverseSummary, ...]
    result: SIDReverseResult


def parse_sid_reverse_log(lines: str | Iterable[str]) -> tuple[int | None, list[SIDObservation]]:
    if isinstance(lines, str):
        lines = lines.splitlines()
    tid: int | None = None
    observations: list[SIDObservation] = []
    for raw_line in lines:
        marker = raw_line.find(SIDREV_PREFIX)
        if marker < 0:
            continue
        # EasyCon CLI wraps printed lines in ANSI colour resets.  Remove them
        # before parsing the final numeric field (usually SPE).
        payload = _ANSI_ESCAPE_RE.sub("", raw_line[marker:]).strip()
        parts = payload.split("|")
        record_type = parts[1] if len(parts) > 1 else ""
        values: dict[str, str] = {}
        for part in parts[2:]:
            key, separator, value = part.partition("=")
            if separator:
                values[key.strip().upper()] = value.strip()
        if record_type == "META":
            if "TID" in values:
                tid = int(values["TID"])
            continue
        if record_type != "OBS":
            continue
        try:
            pokemon_index = int(values["MON"])
            species_id = int(values.get("DEX", "0"))
            if species_id <= 0:
                species_id = _species_id_from_ocr(values.get("NAME", ""))
            nature = int(values["NATURE"])
            level = int(values["LEVEL"])
            stats = tuple(int(values[key]) for key in _STAT_KEYS)
            gender_text = values.get("GENDER")
            gender_value = int(gender_text) if gender_text is not None else None
            source_type = _normalize_source_type(values.get("SOURCE", SOURCE_STATIC))
            location = values.get("LOCATION", "").strip()
            effort_values = tuple(int(values.get(key, "0")) for key in _EV_KEYS)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid SIDREV observation: {payload}") from exc
        if gender_value is not None and gender_value not in (0, 1, 2):
            raise ValueError(f"invalid SIDREV gender observation: {gender_value}")
        gender = gender_value
        observations.append(
            SIDObservation(
                pokemon_index=pokemon_index,
                species_id=species_id,
                nature=nature,
                level=level,
                stats=stats,  # type: ignore[arg-type]
                gender=gender,
                source_type=source_type,
                location=location,
                effort_values=effort_values,  # type: ignore[arg-type]
            )
        )
    return tid, observations


def _normalize_source_type(value: str) -> str:
    normalized = value.strip().upper()
    aliases = {
        "0": SOURCE_STATIC,
        "STATIC": SOURCE_STATIC,
        "定点": SOURCE_STATIC,
        "1": SOURCE_WILD,
        "WILD": SOURCE_WILD,
        "野生": SOURCE_WILD,
    }
    if normalized not in aliases:
        raise ValueError(f"unsupported Pokemon source type: {value!r}")
    return aliases[normalized]


def resolve_wild_location(location: str, game: str) -> str:
    """Resolve a Chinese or English TenLines location to its canonical name."""
    requested = location_to_en(location.strip())
    available = {key[0] for key in load_frlg_encounters(game)}
    for candidate in available:
        if candidate.casefold() == requested.casefold():
            return candidate
    raise ValueError(f"unknown TenLines wild encounter location: {location!r}")


def _wild_encounter_categories(species_id: int, location: str, game: str) -> tuple[str, ...]:
    canonical = resolve_wild_location(location, game)
    encounters = load_frlg_encounters(game)
    found: list[str] = []
    for category in _CATEGORY_ORDER:
        encounter = encounters.get((canonical, category))
        if encounter is None:
            continue
        if any(slot.get("species") == species_id for slot in encounter.get("slots", ())):
            found.append(category)
    if not found:
        raise ValueError(
            f"Pokemon #{species_id} is not present at {canonical} in {game} encounter data"
        )
    return tuple(found)


def _species_id_from_ocr(value: str) -> int:
    def normalize(name: str) -> str:
        name = name.strip().upper().replace("♀", "F").replace("♂", "M")
        return re.sub(r"[^A-Z0-9]", "", name)

    cleaned = normalize(value)
    for species_id in range(1, 387):
        if normalize(get_species_name(species_id)) == cleaned:
            return species_id
    raise ValueError(
        f"cannot identify Pokemon name {value!r}; set the slot's Dex override"
    )


def _tuple_from_ivs(ivs) -> tuple[int, int, int, int, int, int]:
    return (
        ivs.hp,
        ivs.attack,
        ivs.defense,
        ivs.sp_attack,
        ivs.sp_defense,
        ivs.speed,
    )


def analyze_observed_pokemon(
    observations: Sequence[SIDObservation],
    *,
    game: str = "fr_nx",
    max_iv_combinations: int = 200_000,
) -> PokemonReverseSummary:
    if not observations:
        raise ValueError("at least one observation is required")
    first = observations[0]
    if any(item.pokemon_index != first.pokemon_index for item in observations):
        raise ValueError("observations from different party Pokemon were mixed")
    if any(item.species_id != first.species_id for item in observations):
        raise ValueError("species changed within one Pokemon's observations")
    if any(item.nature != first.nature for item in observations):
        raise ValueError("nature changed within one Pokemon's observations")
    source_type = _normalize_source_type(first.source_type)
    if any(_normalize_source_type(item.source_type) != source_type for item in observations):
        raise ValueError("source type changed within one Pokemon's observations")
    if any(item.location != first.location for item in observations):
        raise ValueError("encounter location changed within one Pokemon's observations")
    if any(item.effort_values != first.effort_values for item in observations):
        raise ValueError("effort values changed within one Pokemon's observations")
    if not 1 <= first.species_id <= 386:
        raise ValueError(f"unsupported National Dex number: {first.species_id}")
    if not 0 <= first.nature < 25:
        raise ValueError(f"invalid nature index: {first.nature}")
    if len(first.effort_values) != 6:
        raise ValueError("six effort values are required")
    if any(not 0 <= value <= 255 for value in first.effort_values):
        raise ValueError("each effort value must be in 0-255")
    if sum(first.effort_values) > 510:
        raise ValueError("the six effort values must total no more than 510")

    location = ""
    encounter_categories: tuple[str, ...] = ()
    if source_type == SOURCE_WILD:
        if not first.location.strip():
            raise ValueError("wild Pokemon requires a TenLines encounter location")
        location = resolve_wild_location(first.location, game)
        encounter_categories = _wild_encounter_categories(
            first.species_id,
            location,
            game,
        )

    nature_name = NATURES[first.nature]
    iv_observations = [
        IVsObservation(
            pokemon=get_species_name(item.species_id),
            nature=nature_name,
            level=item.level,
            hp=item.stats[0],
            attack=item.stats[1],
            defense=item.stats[2],
            sp_attack=item.stats[3],
            sp_defense=item.stats[4],
            speed=item.stats[5],
        )
        for item in observations
    ]
    if not all(item.is_valid for item in iv_observations):
        raise ValueError(f"Pokemon {first.pokemon_index} contains an invalid OCR observation")

    personal = get_personal(first.species_id, game)
    iv_range = iv_calculator(
        iv_observations,
        personal["stats"],
        effort_values=first.effort_values,
    )
    iv_min = _tuple_from_ivs(iv_range.ivs_lower_bound)
    iv_max = _tuple_from_ivs(iv_range.ivs_upper_bound)
    if any(lower > upper for lower, upper in zip(iv_min, iv_max)):
        raise ValueError(
            f"Pokemon {first.pokemon_index} observations have no common IV range "
            "for the supplied effort values"
        )
    genders = {item.gender for item in observations if item.gender is not None}
    if len(genders) > 1:
        raise ValueError(f"Pokemon {first.pokemon_index} gender recognition changed")
    gender = next(iter(genders)) if genders else None
    gender_ratio = personal["gender"] if gender is not None else None
    candidates = recover_pid_candidates_from_ranges(
        iv_min,
        iv_max,
        first.nature,
        gender=gender,
        gender_ratio=gender_ratio,
        max_iv_combinations=max_iv_combinations,
    )
    return PokemonReverseSummary(
        first.pokemon_index,
        first.species_id,
        get_species_name(first.species_id),
        first.nature,
        iv_min,
        iv_max,
        len(observations),
        candidates,
        source_type,
        location,
        first.effort_values,
        encounter_categories,
    )


def analyze_shiny_team(
    tid: int,
    observations: Sequence[SIDObservation],
    *,
    game: str = "fr_nx",
    max_iv_combinations: int = 200_000,
) -> TeamReverseSummary:
    if not 0 <= tid <= 0xFFFF:
        raise ValueError("TID must be in 0-65535")
    grouped: dict[int, list[SIDObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.pokemon_index, []).append(observation)
    summaries: list[PokemonReverseSummary] = []
    evidence: list[ShinyEvidence] = []
    for pokemon_index in sorted(grouped):
        summary = analyze_observed_pokemon(
            grouped[pokemon_index],
            game=game,
            max_iv_combinations=max_iv_combinations,
        )
        if not summary.candidates:
            raise ValueError(
                f"Pokemon {pokemon_index} has no Method 1/2/4 PID candidate; "
                "check OCR, EVs, origin game, or breeding method"
            )
        summaries.append(summary)
        evidence.append(ShinyEvidence(pokemon_index, summary.candidates))
    return TeamReverseSummary(tuple(summaries), reverse_sid(tid, tuple(evidence)))
