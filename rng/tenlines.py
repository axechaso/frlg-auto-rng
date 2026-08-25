"""One-to-one Python port of ten-lines C++ searcher/initial_seed/calibration."""

from itertools import product
from typing import List, Tuple, Optional, Dict

from app_paths import DATA_ROOT, RESOURCE_ROOT
from tenlines_seed_updater import (
    FR_BINARY_NAME,
    LG_BINARY_NAME,
    active_seed_binary_path,
)

# Method enum values (matching C++ enum class Method)
METHOD_1 = 1
METHOD_1_REVERSE = 2
METHOD_2 = 3
METHOD_4 = 4

# ============================================================
# LCRNG
# ============================================================
POKERNG_MULT = 0x41C64E6D
POKERNG_ADD  = 0x6073
POKERNGR_MULT = 0xEEB9EB65
POKERNGR_ADD  = 0xA3561A1

JUMP_TABLE = [
    (0x41C64E6D, 0x6073), (0xC2A29A69, 0xE97E7B6A), (0xEE067F11, 0x31B0DDE4),
    (0xCFDDDF21, 0x67DBB608), (0x5F748241, 0xCBA72510), (0x8B2E1481, 0x1D29AE20),
    (0x76006901, 0xBA84EC40), (0x1711D201, 0x79F01880), (0xBE67A401, 0x8793100),
    (0xDDDF4801, 0x6B566200), (0x3FFE9001, 0x803CC400), (0x90FD2001, 0xA6B98800),
    (0x65FA4001, 0xE6731000), (0xDBF48001, 0x30E62000), (0xF7E90001, 0xF1CC4000),
    (0xEFD20001, 0x23988000), (0xDFA40001, 0x47310000), (0xBF480001, 0x8E620000),
    (0x7E900001, 0x1CC40000), (0xFD200001, 0x39880000), (0xFA400001, 0x73100000),
    (0xF4800001, 0xE6200000), (0xE9000001, 0xCC400000), (0xD2000001, 0x98800000),
    (0xA4000001, 0x31000000), (0x48000001, 0x62000000), (0x90000001, 0xC4000000),
    (0x20000001, 0x88000000), (0x40000001, 0x10000000), (0x80000001, 0x20000000),
    (0x1, 0x40000000), (0x1, 0x80000000),
]


def pokerng_next(seed: int) -> int:
    return (seed * POKERNG_MULT + POKERNG_ADD) & 0xFFFFFFFF


def pokerngr_next(seed: int) -> int:
    return (seed * POKERNGR_MULT + POKERNGR_ADD) & 0xFFFFFFFF


def pokerng_jump(seed: int, advances: int) -> int:
    for i in range(32):
        if advances & (1 << i):
            m, a = JUMP_TABLE[i]
            seed = (seed * m + a) & 0xFFFFFFFF
    return seed


def pokerng_distance(start: int, end: int) -> int:
    dist = 0
    mask = 1
    for m, a in JUMP_TABLE:
        if start == end:
            break
        if (start ^ end) & mask:
            start = (start * m + a) & 0xFFFFFFFF
            dist += mask
        mask <<= 1
    return dist


# ============================================================
# LCRNGReverse - recover seeds from IVs
# ============================================================
def recover_pokerng_iv_method12(hp, atk, def_, spa, spd, spe):
    add, mult = 0x6073, 0x41c64e6d
    mod, pat, inc = 0x67d3, 0xd3e, 0x4034
    first = ((hp | (atk << 5) | (def_ << 10)) << 16) & 0xFFFFFFFF
    second = ((spe | (spa << 5) | (spd << 10)) << 16) & 0xFFFFFFFF
    diff = (second - first * mult) >> 16 & 0xFFFF
    start1 = (((diff * mod + inc) >> 16) * pat) % mod
    start2 = ((((diff ^ 0x8000) * mod + inc) >> 16) * pat) % mod
    seeds = []
    for low in range(start1, 0x10000, mod):
        seed = first | low
        if ((seed * mult + add) & 0x7fff0000) == second:
            seeds.append(seed)
            seeds.append(seed ^ 0x80000000)
    for low in range(start2, 0x10000, mod):
        seed = first | low
        if ((seed * mult + add) & 0x7fff0000) == second:
            seeds.append(seed)
            seeds.append(seed ^ 0x80000000)
    return seeds


def recover_pokerng_iv_method4(hp, atk, def_, spa, spd, spe):
    add, mult = 0xe97e7b6a, 0xc2a29a69
    mod, pat, inc = 0x3a89, 0x2e4c, 0x5831
    first = ((hp | (atk << 5) | (def_ << 10)) << 16) & 0xFFFFFFFF
    second = ((spe | (spa << 5) | (spd << 10)) << 16) & 0xFFFFFFFF
    diff = (second - (first * mult + add)) >> 16 & 0xFFFF
    start1 = (((diff * mod + inc) >> 16) * pat) % mod
    start2 = ((((diff ^ 0x8000) * mod + inc) >> 16) * pat) % mod
    seeds = []
    for low in range(start1, 0x10000, mod):
        seed = first | low
        if ((seed * mult + add) & 0x7fff0000) == second:
            seeds.append(seed)
            seeds.append(seed ^ 0x80000000)
    for low in range(start2, 0x10000, mod):
        seed = first | low
        if ((seed * mult + add) & 0x7fff0000) == second:
            seeds.append(seed)
            seeds.append(seed ^ 0x80000000)
    return seeds


def recover_pokerng_iv(hp, atk, def_, spa, spd, spe, method):
    if method == METHOD_4:
        return recover_pokerng_iv_method4(hp, atk, def_, spa, spd, spe)
    return recover_pokerng_iv_method12(hp, atk, def_, spa, spd, spe)


# ============================================================
# Utilities
# ============================================================
def get_shiny(pid, tsv):
    psv = (pid >> 16) ^ (pid & 0xFFFF)
    if tsv == psv:
        return 2
    if (tsv ^ psv) < 8:
        return 1
    return 0


def get_gender(pid, gender_ratio):
    if gender_ratio == 255:
        return 2
    if gender_ratio == 254:
        return 1
    if gender_ratio == 0:
        return 0
    return 1 if (pid & 255) < gender_ratio else 0


def get_hidden_power(ivs):
    # C++ uses order[6] = { 0, 1, 2, 5, 3, 4 } to remap IV indices
    order = [0, 1, 2, 5, 3, 4]
    h = sum((ivs[order[i]] & 1) << i for i in range(6))
    p = sum(((ivs[order[i]] >> 1) & 1) << i for i in range(6))
    type_val = h * 15 // 63
    power = 30 + p * 40 // 63
    return type_val, power


# ============================================================
# Encounter slot tables (Gen3 hSlot)
# ============================================================
GRASS_SLOT_TABLE = [0]*20 + [1]*20 + [2]*10 + [3]*10 + [4]*10 + [5]*10 + [6]*5 + [7]*5 + [8]*4 + [9]*4 + [10]*1 + [11]*1
SURFING_SLOT_TABLE = [0]*60 + [1]*30 + [2]*5 + [3]*4 + [4]*1
OLD_ROD_SLOT_TABLE = [0]*70 + [1]*30
GOOD_ROD_SLOT_TABLE = [0]*60 + [1]*20 + [2]*20
SUPER_ROD_SLOT_TABLE = [0]*40 + [1]*40 + [2]*15 + [3]*4 + [4]*1

ENCOUNTER_SLOT_TABLES = {
    0: GRASS_SLOT_TABLE,     # Grass
    1: SURFING_SLOT_TABLE,   # Surfing
    2: OLD_ROD_SLOT_TABLE,   # OldRod
    3: GOOD_ROD_SLOT_TABLE,  # GoodRod
    4: SUPER_ROD_SLOT_TABLE, # SuperRod
    5: SURFING_SLOT_TABLE,   # RockSmash
}

# String aliases for convenience
ENCOUNTER_TYPE_ALIASES = {
    "Grass": 0, "Surfing": 1, "OldRod": 2, "GoodRod": 3,
    "SuperRod": 4, "RockSmash": 5,
}


def hslot(rand_val, encounter_type):
    if isinstance(encounter_type, str):
        encounter_type = ENCOUNTER_TYPE_ALIASES.get(encounter_type, 0)
    table = ENCOUNTER_SLOT_TABLES.get(encounter_type)
    if table is None:
        return 0
    return table[rand_val % len(table)]


# ============================================================
# Filter
# ============================================================
class SearcherFilter:
    __slots__ = ('natures', 'shiny', 'gender', 'hp_type', 'iv_min', 'iv_max', 'slots', 'ability')
    def __init__(self, natures=None, shiny=None, gender=None, hp_type=None,
                 iv_min=None, iv_max=None, slots=None, ability=None):
        self.natures = natures
        self.shiny = shiny
        self.gender = gender
        self.hp_type = hp_type
        self.iv_min = iv_min or [0]*6
        self.iv_max = iv_max or [31]*6
        self.slots = slots
        self.ability = ability  # None or 0 or 1

    def compare_nature(self, nature):
        if self.natures is None:
            return True
        return nature in self.natures

    def compare_state(
        self,
        ivs,
        nature,
        shiny,
        gender,
        hp_type,
        encounter_slot=None,
        ability=None,
    ):
        for i in range(6):
            if ivs[i] < self.iv_min[i] or ivs[i] > self.iv_max[i]:
                return False
        if self.natures is not None and nature not in self.natures:
            return False
        if self.shiny is not None and self.shiny != 255:
            if self.shiny == 3:
                if shiny not in (1, 2):
                    return False
            elif shiny != self.shiny:
                return False
        if self.gender is not None and self.gender != 255 and gender != self.gender:
            return False
        if self.hp_type is not None and hp_type != self.hp_type:
            return False
        if encounter_slot is not None and self.slots is not None and encounter_slot not in self.slots:
            return False
        if ability is not None and self.ability is not None and ability != self.ability:
            return False
        return True


# ============================================================
# StaticSearcher3 - 1:1 port of C++ StaticSearcher3::search
# ============================================================
def iter_iv_combinations(iv_min, iv_max, iv_total=None):
    """Yield IV tuples, optionally restricted to one exact total.

    The exact-total branch uses bounded composition pruning.  It lets the
    automatic planner inspect high-IV tiers first without expanding a broad
    six-dimensional range.
    """
    if iv_total is None:
        yield from product(*(range(lo, hi + 1) for lo, hi in zip(iv_min, iv_max)))
        return

    def visit(index, remaining, prefix):
        if index == 5:
            value = remaining
            if iv_min[index] <= value <= iv_max[index]:
                yield tuple(prefix + [value])
            return
        rest_min = sum(iv_min[index + 1:])
        rest_max = sum(iv_max[index + 1:])
        lower = max(iv_min[index], remaining - rest_max)
        upper = min(iv_max[index], remaining - rest_min)
        for value in range(upper, lower - 1, -1):
            yield from visit(index + 1, remaining - value, prefix + [value])

    yield from visit(0, iv_total, [])


def search_static(iv_min, iv_max, method, tsv, gender_ratio=127,
                  bugged_roamer=False, filter_obj=None, iv_total=None,
                  cancel_check=None):
    """Yields dicts: seed, pid, ivs, ability, gender, nature, shiny, hidden_type, hidden_power"""
    iv_advance = (method == METHOD_2)
    for hp, atk, def_, spa, spd, spe in iter_iv_combinations(iv_min, iv_max, iv_total):
        if cancel_check is not None and cancel_check():
            return
        if bugged_roamer:
            ivs = (hp, atk & 7, 0, 0, 0, 0)
        else:
            ivs = (hp, atk, def_, spa, spd, spe)
        seeds = recover_pokerng_iv(hp, atk, def_, spa, spd, spe, method)
        for seed in seeds:
            rng = seed
            if iv_advance:
                rng = pokerngr_next(rng)
            # C++: pid = rng.nextUShort() << 16; pid |= rng.nextUShort();
            rng = pokerngr_next(rng); pid_high = rng >> 16
            rng = pokerngr_next(rng); pid_low = rng >> 16
            pid = (pid_high << 16) | pid_low
            nature = pid % 25
            if filter_obj and not filter_obj.compare_nature(nature):
                continue
            state_seed = pokerngr_next(rng)
            ability = pid & 1
            gender = get_gender(pid, gender_ratio)
            shiny = get_shiny(pid, tsv)
            hp_type, hp_power = get_hidden_power(ivs)
            if filter_obj and not filter_obj.compare_state(
                    ivs, nature, shiny, gender, hp_type,
                    ability=ability):
                continue
            yield {
                "seed": state_seed, "pid": pid, "ivs": ivs,
                "ability": ability, "gender": gender, "nature": nature,
                "shiny": shiny, "hidden_type": hp_type, "hidden_power": hp_power,
            }


# ============================================================
# WildSearcher3 - 1:1 port of C++ WildSearcher3::search (Lead::None only)
# ============================================================
def search_wild(iv_min, iv_max, method, tsv, encounter_slots,
                encounter_type=0, filter_obj=None, iv_total=None,
                cancel_check=None):
    """Yields dicts: seed, pid, ivs, ability, gender, level, nature, shiny,
    hidden_type, hidden_power, encounter_slot, species, form"""
    if isinstance(encounter_type, str):
        encounter_type = ENCOUNTER_TYPE_ALIASES.get(encounter_type, 0)
    iv_advance = (method == METHOD_2)
    for hp, atk, def_, spa, spd, spe in iter_iv_combinations(iv_min, iv_max, iv_total):
        if cancel_check is not None and cancel_check():
            return
        ivs = (hp, atk, def_, spa, spd, spe)
        seeds = recover_pokerng_iv(hp, atk, def_, spa, spd, spe, method)
        for seed in seeds:
            rng = seed
            if iv_advance:
                rng = pokerngr_next(rng)
            # C++ (non-tanoby): pid = rng.nextUShort() << 16; pid |= rng.nextUShort();
            rng = pokerngr_next(rng); pid_high = rng >> 16
            rng = pokerngr_next(rng); pid_low = rng >> 16
            pid = (pid_high << 16) | pid_low
            nature = pid % 25
            if filter_obj and not filter_obj.compare_nature(nature):
                continue
            rng = pokerngr_next(rng); next_rng = rng >> 16
            rng = pokerngr_next(rng); next_rng2 = rng >> 16
            # do-while loop matching C++ WildSearcher3::search for Lead::None
            while True:
                if (next_rng % 25) == nature:
                    test0 = rng
                    enc_rand = pokerngr_next(test0) >> 16
                    test0 = pokerngr_next(test0)
                    enc_slot = hslot(enc_rand % 100, encounter_type)
                    slot_valid = filter_obj is None or filter_obj.slots is None or enc_slot in filter_obj.slots
                    if slot_valid and enc_slot < len(encounter_slots):
                        slot_info = encounter_slots[enc_slot]
                        species = slot_info.get("species", 0)
                        form = slot_info.get("form", 0)
                        gender_ratio = slot_info.get("gender_ratio", 127)
                        min_lv = slot_info.get("min_level", 1)
                        max_lv = slot_info.get("max_level", 1)
                        level = min_lv + (next_rng2 % (max_lv - min_lv + 1))
                        ability = pid & 1
                        gender = get_gender(pid, gender_ratio)
                        shiny = get_shiny(pid, tsv)
                        hp_type, hp_power = get_hidden_power(ivs)
                        if filter_obj is None or filter_obj.compare_state(
                                ivs, nature, shiny, gender, hp_type, enc_slot,
                                ability=ability):
                            state_seed = pokerngr_next(test0)
                            yield {
                                "seed": state_seed, "pid": pid, "ivs": ivs,
                                "ability": ability, "gender": gender, "level": level,
                                "nature": nature, "shiny": shiny,
                                "hidden_type": hp_type, "hidden_power": hp_power,
                                "encounter_slot": enc_slot,
                                "species": species, "form": form,
                            }
                hunt_nature = ((next_rng << 16) | next_rng2) % 25
                if hunt_nature == nature:
                    break
                rng = pokerngr_next(rng); next_rng = rng >> 16
                rng = pokerngr_next(rng); next_rng2 = rng >> 16


# ============================================================
# Sorted initial seeds table (lazy init)
# ============================================================
sorted_initial_seeds_table: Optional[List[Tuple[int, int]]] = None


def build_sorted_initial_seeds():
    global sorted_initial_seeds_table
    if sorted_initial_seeds_table is not None:
        return sorted_initial_seeds_table
    data = []
    for seed in range(0x10000):
        dist = pokerng_distance(seed, 0)
        data.append((dist, seed))
    data.sort(key=lambda x: x[0])
    sorted_initial_seeds_table = data
    return sorted_initial_seeds_table


def find_closest_initial_seed_index(target_seed):
    data = build_sorted_initial_seeds()
    distance_from_base = pokerng_distance(0, target_seed)
    target = 0xFFFFFFFF - distance_from_base
    left, right = 0, len(data) - 1
    while left < right:
        mid = (left + right) // 2
        if data[mid][0] <= target:
            left = mid + 1
        else:
            right = mid
    if data[left][0] > target:
        return left
    return 0


# ============================================================
# Initial seed - painting_seeds (RSE)
# ============================================================
def painting_seeds(target_seed, result_count=10, offset=0):
    """1:1 port of C++ painting_seeds(). Returns list of dicts."""
    target_seed = pokerng_jump(target_seed, -offset & 0xFFFFFFFF)
    distance_from_base = pokerng_distance(0, target_seed)
    result_index = find_closest_initial_seed_index(target_seed)
    data = build_sorted_initial_seeds()
    results = []
    n = len(data)
    for i in range(result_count):
        offset_advances, seed = data[(result_index + i) % n]
        advances = (offset_advances + distance_from_base) & 0xFFFFFFFF
        results.append({
            "advances": advances,
            "seed_time": seed * 16,
            "key": "",
            "initial_seed": seed,
        })
    return results


# ============================================================
# Initial seed - FRLG seeds
# ============================================================
HELD_BUTTON_OFFSETS = {
    "fr": [
        ('a', "startup_select", -1), ('a', "startup_a", -8), ('a', "blackout_r", -23),
        ('a', "blackout_a", -31), ('a', "blackout_l", 2), ('a', "blackout_al", -33),
        ('a', "none", 0),
        ('h', "startup_select", 7), ('h', "startup_a", 3), ('h', "blackout_r", -23),
        ('h', "blackout_a", -23), ('h', "none", 0),
        ('r', "startup_select", -1), ('r', "startup_a", -18), ('r', "blackout_r", -23),
        ('r', "blackout_a", -39), ('r', "none", 0),
    ],
    "lg": [
        ('a', "startup_select", -1), ('a', "startup_a", -8), ('a', "blackout_r", -23),
        ('a', "blackout_a", -31), ('a', "blackout_l", 2), ('a', "blackout_al", -33),
        ('a', "none", 0),
        ('h', "startup_select", 7), ('h', "startup_a", 3), ('h', "blackout_r", -23),
        ('h', "blackout_a", -23), ('h', "none", 0),
        ('r', "startup_select", -1), ('r', "startup_a", -18), ('r', "blackout_r", -23),
        ('r', "blackout_a", -39), ('r', "none", 0),
    ],
    "fr_eu": [('a', "startup_select", 8), ('a', "none", -1),
              ('h', "startup_select", 7), ('h', "none", 0),
              ('r', "startup_select", -9), ('r', "none", -8)],
    "lg_eu": [('a', "startup_select", 8), ('a', "none", -1),
              ('h', "startup_select", 7), ('h', "none", 0),
              ('r', "startup_select", -9), ('r', "none", -8)],
    "fr_jpn_1_0": [
        ('a', "startup_select", -1), ('a', "startup_a", 1), ('a', "blackout_r", -10),
        ('a', "blackout_a", -18), ('a', "blackout_l", -3), ('a', "none", 0),
        ('h', "startup_select", 7), ('h', "startup_a", 3), ('h', "blackout_r", -27),
        ('h', "blackout_a", -24), ('h', "none", 0),
        ('r', "startup_select", 0), ('r', "startup_a", -18), ('r', "blackout_r", -23),
        ('r', "blackout_a", -40), ('r', "none", 0),
    ],
    "fr_jpn_1_1": [
        ('a', "startup_select", 10), ('a', "startup_a", -9), ('a', "blackout_r", -23),
        ('a', "blackout_a", -31), ('a', "blackout_l", -6), ('a', "none", 0),
        ('h', "startup_select", -7), ('h', "startup_a", -19), ('h', "blackout_r", -21),
        ('h', "blackout_a", -29), ('h', "none", 0),
        ('r', "startup_select", -7), ('r', "startup_a", -4), ('r', "blackout_r", -29),
        ('r', "blackout_a", -38), ('r', "none", 0),
    ],
    "lg_jpn": [
        ('a', "startup_select", -1), ('a', "startup_a", -9), ('a', "blackout_r", -22),
        ('a', "blackout_a", -40), ('a', "blackout_l", -7), ('a', "none", 0),
        ('h', "startup_select", -1), ('h', "startup_a", -18), ('h', "blackout_r", -23),
        ('h', "blackout_a", -31), ('h', "none", 0),
        ('r', "startup_select", -1), ('r', "startup_a", -23), ('r', "blackout_r", -23),
        ('r', "blackout_a", -39), ('r', "none", 0),
    ],
    "fr_mgba": [('a', "none", 0), ('h', "none", 0), ('r', "none", 0)],
    "lg_mgba": [('a', "none", 0), ('h', "none", 0), ('r', "none", 0)],
    "fr_nx":   [('a', "none", 0), ('h', "none", 0), ('h', "blackout_r", -36), ('h', "blackout_l", -36), ('r', "none", 0)],
    "lg_nx":   [('a', "none", 0), ('h', "none", 0), ('h', "blackout_r", -36), ('h', "blackout_l", -36), ('r', "none", 0)],
    "fr_jpn_nx": [('h', "none", 0)],
    "lg_jpn_nx": [('h', "none", 0)],
    "fr_nx2":  [('a', "none", 0), ('h', "none", 0), ('h', "blackout_r", -36), ('h', "blackout_l", -36), ('r', "none", 0)],
    "lg_nx2":  [('a', "none", 0), ('h', "none", 0), ('h', "blackout_r", -36), ('h', "blackout_l", -36), ('r', "none", 0)],
}


def parse_frlg_seed_data(data: bytes, is_nx_format: bool):
    """Parse FRLG binary seed data. Returns (seed_map, contiguous)."""
    import struct
    seed_map: Dict[int, list] = {}
    contiguous: Dict[str, list] = {}
    ptr = 0
    seed_times = []
    if is_nx_format:
        count = struct.unpack_from("<I", data, ptr)[0]; ptr += 4
        for _ in range(count):
            seed_times.append(struct.unpack_from("<H", data, ptr)[0]); ptr += 2
    while ptr < len(data):
        key_end = data.index(0, ptr)
        key = data[ptr:key_end].decode('ascii')
        ptr = key_end + 1
        button_mode = key.split('_')[1] if '_' in key else 'a'
        starting_frame, frame_size = 0, 1
        if not is_nx_format:
            starting_frame = struct.unpack_from("<H", data, ptr)[0]; ptr += 2
            frame_size = data[ptr]; ptr += 1
        entries_count = struct.unpack_from("<I", data, ptr)[0]; ptr += 4
        contiguous_entries = []
        prev_seed = None
        for i in range(entries_count):
            seed = struct.unpack_from("<H", data, ptr)[0]; ptr += 2
            is_invalid = data[ptr]; ptr += 1
            if is_invalid:
                continue
            if seed == prev_seed:
                continue
            prev_seed = seed
            if is_nx_format:
                seed_time = (seed_times[i] + 5737) if i < len(seed_times) else 0
            else:
                seed_time = (starting_frame + i // frame_size) * 16
            entry = {"key": key, "button_mode": button_mode, "seed_time": seed_time, "initial_seed": seed}
            contiguous_entries.append(entry)
            if seed not in seed_map:
                seed_map[seed] = []
            seed_map[seed].append(entry)
        contiguous[key] = contiguous_entries
    return seed_map, contiguous


SEED_BASE_URL = "https://lincoln-lm.github.io/ten-lines/generated"
_FRLG_SEED_CACHE = {}


def clear_frlg_seed_cache():
    """Discard parsed tables after the GUI atomically activates an update."""
    _FRLG_SEED_CACHE.clear()


def download_seed_file(filename, local_path):
    import os
    import urllib.request
    url = f"{SEED_BASE_URL}/{filename}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "EasyCon/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(data)
        return data
    except Exception:
        return None


def load_frlg_seed_data(game: str = "fr_nx", refresh: bool = False):
    """Load validated user-updated FRLG data before the bundled fallback.

    The automatic planner remains reproducible and usable offline.  The GUI
    updater activates both NX binaries and both EasyCon tables together; a
    legacy ``refresh=True`` call only downloads a temporary one-file copy and
    never mutates that validated active set.
    """
    seed_files = {
        "fr": "fr_eng.bin", "fr_eu": "fr_eng.bin", "fr_nx": "fr_eng_nx.bin",
        "lg": "lg_eng.bin", "lg_eu": "lg_eng.bin", "lg_nx": "lg_eng_nx.bin",
        "fr_jpn_1_0": "fr_jpn_1_0.bin", "fr_jpn_1_1": "fr_jpn_1_1.bin",
        "lg_jpn": "lg_jpn.bin", "fr_mgba": "fr_eng_mgba.bin", "lg_mgba": "lg_eng_mgba.bin",
        "fr_jpn_nx": "fr_jpn_nx.bin", "lg_jpn_nx": "lg_jpn_nx.bin",
        "fr_nx2": "fr_eng_nx.bin", "lg_nx2": "lg_eng_nx.bin",
    }
    if game not in seed_files:
        return {}, {}
    if not refresh and game in _FRLG_SEED_CACHE:
        return _FRLG_SEED_CACHE[game]
    filename = seed_files[game]
    bundled_path = RESOURCE_ROOT / "rng" / "resources" / filename
    if refresh:
        refresh_path = DATA_ROOT / "seed_tables" / "manual_refresh" / filename
        data = download_seed_file(filename, refresh_path)
        local_path = refresh_path
    else:
        override_path = (
            active_seed_binary_path(filename)
            if filename in (FR_BINARY_NAME, LG_BINARY_NAME)
            else None
        )
        local_path = override_path or bundled_path
        data = local_path.read_bytes() if local_path.is_file() else None
    if data is None:
        fallback_path = DATA_ROOT / "seed_tables" / "manual_refresh" / filename
        data = download_seed_file(filename, fallback_path)
        local_path = fallback_path
    if data is None:
        raise FileNotFoundError(f"Unable to load FRLG seed data: {local_path}")
    parsed = parse_frlg_seed_data(data, game.endswith("nx") or game.endswith("nx2"))
    _FRLG_SEED_CACHE[game] = parsed
    return parsed


def frlg_seeds(target_seed, result_count=10, offset=0, game_version="fr",
               ttv_frames_out=0, seed_data=None, key_filter=None,
               cancel_check=None):
    """1:1 port of C++ frlg_seeds(). Returns list of dicts."""
    target_seed = pokerng_jump(target_seed, -offset & 0xFFFFFFFF)
    if seed_data is None:
        seed_data = load_frlg_seed_data(game_version)
    seed_map, contiguous = seed_data
    held_button_offsets = HELD_BUTTON_OFFSETS.get(game_version, [('a', "none", 0), ('h', "none", 0), ('r', "none", 0)])
    distance_from_base = pokerng_distance(0, target_seed)
    result_index = find_closest_initial_seed_index(target_seed)
    data = build_sorted_initial_seeds()
    results = []
    n = len(data)
    valid_results = 0
    i = 0
    seen_results = set()
    # One complete 16-bit cycle contains every unique initial seed.  Continuing
    # into a second cycle can only pad the response with duplicate routes.
    while valid_results < result_count and i < n:
        if cancel_check is not None and i % 256 == 0 and cancel_check():
            return results
        idx = (result_index + i) % n
        offset_advances, seed = data[idx]
        advances = (offset_advances + distance_from_base) & 0xFFFFFFFF
        i += 1
        if advances >= ttv_frames_out:
            for button_mode, held_button, hb_offset in held_button_offsets:
                unoffset_seed = (seed - hb_offset) & 0xFFFF
                if unoffset_seed not in seed_map:
                    continue
                for entry in seed_map[unoffset_seed]:
                    if entry['button_mode'] != button_mode:
                        continue
                    valid_results += 1
                    key_str = f"{entry['key']}_{held_button}"
                    if key_filter is not None and key_str not in key_filter:
                        valid_results -= 1
                        continue
                    result_key = (seed, advances, entry['seed_time'], key_str)
                    if result_key in seen_results:
                        valid_results -= 1
                        continue
                    seen_results.add(result_key)
                    results.append({
                        "advances": advances,
                        "seed_time": entry['seed_time'],
                        "key": key_str,
                        "initial_seed": seed,
                    })
                    if valid_results >= result_count:
                        break
                if valid_results >= result_count:
                    break
    if not results and not (cancel_check is not None and cancel_check()):
        raise ValueError(
            f"No reachable initial seed for game/settings: {game_version}"
        )
    return results


# ============================================================
# Calibration - StaticGenerator3 / WildGenerator3
# ============================================================
def extract_ivs(iv1, iv2):
    return (iv1 & 31, (iv1 >> 5) & 31, (iv1 >> 10) & 31,
            (iv2 >> 5) & 31, (iv2 >> 10) & 31, iv2 & 31)


# ============================================================
# High-level wrapper: calibration
# ============================================================
def calibration_static(seeds, initial_advances, max_advances, offset, method, tsv,
                       gender_ratio=127, bugged_roamer=False, filter_obj=None,
                       ttv_advances_range=None):
    """Calibration for static encounters. Processes multiple seeds with optional TTV.
    seeds: list of {initial_seed, seed_time} dicts
    ttv_advances_range: (min, max) tuple or None
    Returns list of result dicts with added initial_seed, seed_time, ttv_advances.
    Uses pybind11 C++ acceleration."""
    if ttv_advances_range is None:
        ttv_advances_range = (0, 0)
    return calibration_static_pybind(
        seeds, initial_advances, max_advances, offset, method, tsv,
        gender_ratio, bugged_roamer, filter_obj, ttv_advances_range
    )


def calibration_static_pybind(seeds, initial_advances, max_advances, offset, method, tsv,
                                gender_ratio, bugged_roamer, filter_obj, ttv_advances_range):
    """Pybind11 C++ accelerated calibration_static."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src', 'pybind'))
    import calibration_bind

    # Convert seeds from dict list to tuple list
    seed_tuples = [(s["initial_seed"], s.get("seed_time", 0)) for s in seeds]

    # Build IV ranges from filter
    iv_ranges = [(0, 31)] * 6
    if filter_obj is not None:
        iv_ranges = [(filter_obj.iv_min[i], filter_obj.iv_max[i]) for i in range(6)]

    # Extract filter params
    shininess = 255
    nature = -1
    gender = 255
    ability = 255
    if filter_obj is not None:
        shininess = filter_obj.shiny if filter_obj.shiny is not None else 255
        if filter_obj.natures is not None and len(filter_obj.natures) == 1:
            nature = next(iter(filter_obj.natures))
        gender = filter_obj.gender if filter_obj.gender is not None else 255
        ability = filter_obj.ability if filter_obj.ability is not None else 255

    # Call C++ function - returns numpy structured array
    arr = calibration_bind.check_seeds_static(
        seeds=seed_tuples,
        advances_range=(initial_advances, max_advances),
        ttv_range=ttv_advances_range,
        offset=offset,
        trainer_id=0,  # tsv is passed directly
        secret_id=tsv,  # we abuse secret_id to pass tsv directly
        method=method,
        shininess=shininess,
        nature=nature,
        gender=gender,
        iv_ranges=iv_ranges,
        gender_ratio=gender_ratio,
        bugged_roamer=bugged_roamer,
        filter_ability=ability,
    )

    # Convert numpy array to list of dicts
    results = []
    for row in arr:
        results.append({
            "advances": int(row["f0"]),
            "pid": int(row["f1"]),
            "ivs": (int(row["f2"]), int(row["f3"]), int(row["f4"]),
                    int(row["f5"]), int(row["f6"]), int(row["f7"])),
            "ability": int(row["f8"]),
            "gender": int(row["f9"]),
            "nature": int(row["f10"]),
            "shiny": int(row["f11"]),
            "hidden_type": int(row["f12"]),
            "hidden_power": int(row["f13"]),
            "initial_seed": int(row["f14"]),
            "seed_time": int(row["f15"]),
            "ttv_advances": int(row["f16"]),
        })
    return results


def calibration_wild(seeds, initial_advances, max_advances, offset, method, tsv,
                     encounter_slots, encounter_type=0, filter_obj=None,
                     ttv_advances_range=None, level_min=1, level_max=100):
    """Calibration for wild encounters. Processes multiple seeds with optional TTV.
    seeds: list of {initial_seed, seed_time} dicts
    ttv_advances_range: (min, max) tuple or None
    Returns list of result dicts with added initial_seed, seed_time, ttv_advances, method.
    Uses pybind11 C++ acceleration."""
    if isinstance(encounter_type, str):
        encounter_type = ENCOUNTER_TYPE_ALIASES.get(encounter_type, 0)
    if ttv_advances_range is None:
        ttv_advances_range = (0, 0)
    return calibration_wild_pybind(
        seeds, initial_advances, max_advances, offset, method, tsv,
        encounter_slots, encounter_type, filter_obj, ttv_advances_range,
        level_min, level_max
    )


def calibration_wild_pybind(seeds, initial_advances, max_advances, offset, method, tsv,
                              encounter_slots, encounter_type, filter_obj, ttv_advances_range,
                              level_min=0, level_max=0):
    """Pybind11 C++ accelerated calibration_wild."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src', 'pybind'))
    import calibration_bind

    # Convert seeds from dict list to tuple list
    seed_tuples = [(s["initial_seed"], s.get("seed_time", 0)) for s in seeds]

    # Build IV ranges from filter
    iv_ranges = [(0, 31)] * 6
    if filter_obj is not None:
        iv_ranges = [(filter_obj.iv_min[i], filter_obj.iv_max[i]) for i in range(6)]

    # Extract filter params
    shininess = 255
    nature = -1
    gender = 255
    ability = 255
    if filter_obj is not None:
        shininess = filter_obj.shiny if filter_obj.shiny is not None else 255
        if filter_obj.natures is not None and len(filter_obj.natures) == 1:
            nature = next(iter(filter_obj.natures))
        gender = filter_obj.gender if filter_obj.gender is not None else 255
        ability = filter_obj.ability if filter_obj.ability is not None else 255

    filter_level = level_min if level_min == level_max else 0

    # Call C++ function - returns numpy structured array
    arr = calibration_bind.check_seeds_wild(
        seeds=seed_tuples,
        advances_range=(initial_advances, max_advances),
        ttv_range=ttv_advances_range,
        offset=offset,
        trainer_id=0,
        secret_id=tsv,
        method=method,
        shininess=shininess,
        nature=nature,
        gender=gender,
        iv_ranges=iv_ranges,
        encounter_type=encounter_type,
        encounter_slots=encounter_slots,
        filter_ability=ability,
        filter_level=filter_level,
    )

    # Convert numpy array to list of dicts
    filter_slots = filter_obj.slots if filter_obj is not None and hasattr(filter_obj, 'slots') else None
    results = []
    for row in arr:
        enc_slot = int(row["f18"])
        if filter_slots is not None and enc_slot not in filter_slots:
            continue
        results.append({
            "advances": int(row["f0"]),
            "pid": int(row["f1"]),
            "ivs": (int(row["f2"]), int(row["f3"]), int(row["f4"]),
                    int(row["f5"]), int(row["f6"]), int(row["f7"])),
            "ability": int(row["f8"]),
            "gender": int(row["f9"]),
            "nature": int(row["f10"]),
            "shiny": int(row["f11"]),
            "hidden_type": int(row["f12"]),
            "hidden_power": int(row["f13"]),
            "initial_seed": int(row["f14"]),
            "seed_time": int(row["f15"]),
            "ttv_advances": int(row["f16"]),
            "level": int(row["f17"]),
            "encounter_slot": enc_slot,
            "species": int(row["f19"]),
            "form": int(row["f20"]),
            "method": int(row["f21"]),
        })
    return results


def get_contiguous_seed_list(seed_data, setting_key, game_version, held_button):
    """1:1 port of C++ get_contiguous_seed_list().
    Returns list of {initial_seed, seed_time} dicts for the given setting key,
    with held_button offset applied."""
    seed_map, contiguous = seed_data
    if setting_key not in contiguous:
        return []
    offsets_list = HELD_BUTTON_OFFSETS.get(game_version, [('a', "none", 0)])
    button_mode = setting_key.split('_')[1] if '_' in setting_key else 'a'
    hb_offset = 0
    for bm, hb, off in offsets_list:
        if bm == button_mode and hb == held_button:
            hb_offset = off
            break
    result = []
    for entry in contiguous[setting_key]:
        result.append({
            "initial_seed": (entry["initial_seed"] + hb_offset) & 0xFFFF,
            "seed_time": entry["seed_time"],
        })
    return result


# ============================================================
# System timing
# ============================================================
SYSTEM_TIMING = {
    "GBA": {"frame_rate": 16777216 / 280896, "offset_ms": -260},
    "GBP": {"frame_rate": 16777216 / 280896, "offset_ms": 200},
    "NDS": {"frame_rate": 16756991 / 280896, "offset_ms": 788},
    "3DS": {"frame_rate": 16756991 / 280896, "offset_ms": 1558},
    "NX":  {"frame_rate": 16777216 / 280896, "offset_ms": 0},
    "NX2": {"frame_rate": 16777216 / 280896, "offset_ms": -750},
}


def frame_to_ms(frame, system="GBA"):
    t = SYSTEM_TIMING.get(system, SYSTEM_TIMING["GBA"])
    return (frame / t["frame_rate"]) * 1000 + t["offset_ms"]


def ms_to_time_str(ms):
    total_s = ms / 1000
    h = int(total_s // 3600)
    m = int((total_s % 3600) // 60)
    s = total_s % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def hex_seed(seed, bits):
    return format(seed & ((1 << bits) - 1), f'0{bits // 4}X')
