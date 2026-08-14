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

# Direct Gen 1-3 evolution relationships. Wild-origin validation walks this
# table backwards because a caught Pokemon may have evolved since encounter.
_GEN3_EVOLVES_FROM = {
    2: 1,
    3: 2,
    5: 4,
    6: 5,
    8: 7,
    9: 8,
    11: 10,
    12: 11,
    14: 13,
    15: 14,
    17: 16,
    18: 17,
    20: 19,
    22: 21,
    24: 23,
    25: 172,
    26: 25,
    28: 27,
    30: 29,
    31: 30,
    33: 32,
    34: 33,
    35: 173,
    36: 35,
    38: 37,
    39: 174,
    40: 39,
    42: 41,
    44: 43,
    45: 44,
    47: 46,
    49: 48,
    51: 50,
    53: 52,
    55: 54,
    57: 56,
    59: 58,
    61: 60,
    62: 61,
    64: 63,
    65: 64,
    67: 66,
    68: 67,
    70: 69,
    71: 70,
    73: 72,
    75: 74,
    76: 75,
    78: 77,
    80: 79,
    82: 81,
    85: 84,
    87: 86,
    89: 88,
    91: 90,
    93: 92,
    94: 93,
    97: 96,
    99: 98,
    101: 100,
    103: 102,
    105: 104,
    106: 236,
    107: 236,
    110: 109,
    112: 111,
    117: 116,
    119: 118,
    121: 120,
    124: 238,
    125: 239,
    126: 240,
    130: 129,
    134: 133,
    135: 133,
    136: 133,
    139: 138,
    141: 140,
    148: 147,
    149: 148,
    153: 152,
    154: 153,
    156: 155,
    157: 156,
    159: 158,
    160: 159,
    162: 161,
    164: 163,
    166: 165,
    168: 167,
    169: 42,
    171: 170,
    176: 175,
    178: 177,
    180: 179,
    181: 180,
    182: 44,
    183: 298,
    184: 183,
    186: 61,
    188: 187,
    189: 188,
    192: 191,
    195: 194,
    196: 133,
    197: 133,
    199: 79,
    202: 360,
    205: 204,
    208: 95,
    210: 209,
    212: 123,
    217: 216,
    219: 218,
    221: 220,
    224: 223,
    229: 228,
    230: 117,
    232: 231,
    233: 137,
    237: 236,
    242: 113,
    247: 246,
    248: 247,
    253: 252,
    254: 253,
    256: 255,
    257: 256,
    259: 258,
    260: 259,
    262: 261,
    264: 263,
    266: 265,
    267: 266,
    268: 265,
    269: 268,
    271: 270,
    272: 271,
    274: 273,
    275: 274,
    277: 276,
    279: 278,
    281: 280,
    282: 281,
    284: 283,
    286: 285,
    288: 287,
    289: 288,
    291: 290,
    292: 290,
    294: 293,
    295: 294,
    297: 296,
    301: 300,
    305: 304,
    306: 305,
    308: 307,
    310: 309,
    317: 316,
    319: 318,
    321: 320,
    323: 322,
    326: 325,
    329: 328,
    330: 329,
    332: 331,
    334: 333,
    340: 339,
    342: 341,
    344: 343,
    346: 345,
    348: 347,
    350: 349,
    354: 353,
    356: 355,
    362: 361,
    364: 363,
    365: 364,
    367: 366,
    368: 366,
    372: 371,
    373: 372,
    375: 374,
    376: 375,
}


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
        if record_type == "ATTEMPT_BEGIN":
            try:
                pokemon_index = int(values["MON"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid SIDREV attempt marker: {payload}") from exc
            observations = [
                item for item in observations if item.pokemon_index != pokemon_index
            ]
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


def _gen3_origin_species(species_id: int) -> tuple[int, ...]:
    species = [species_id]
    while species[-1] in _GEN3_EVOLVES_FROM:
        species.append(_GEN3_EVOLVES_FROM[species[-1]])
    return tuple(species)


def _wild_encounter_categories(species_id: int, location: str, game: str) -> tuple[str, ...]:
    canonical = resolve_wild_location(location, game)
    encounters = load_frlg_encounters(game)
    origin_species = set(_gen3_origin_species(species_id))
    found: list[str] = []
    for category in _CATEGORY_ORDER:
        encounter = encounters.get((canonical, category))
        if encounter is None:
            continue
        if any(slot.get("species") in origin_species for slot in encounter.get("slots", ())):
            found.append(category)
    if not found:
        checked = ", ".join(f"#{value}" for value in sorted(origin_species))
        raise ValueError(
            f"Pokemon #{species_id} or its Gen 3 pre-evolutions ({checked}) "
            f"are not present at {canonical} in {game} encounter data"
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
