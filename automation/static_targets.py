"""Exact static-target whitelist implemented by EasyCon FRLG 1.1.8."""

STATIC_CATEGORIES_118 = (
    "Starter",
    "Fossil",
    "Gift",
    "GameCorner",
    "Stationary",
    "Legend",
    "Event",
    "Roaming",
)

# FRLG roamers use the Gen 3 truncated-IV bug and also depend on the save's
# starter choice.  The first-release ranker only handles normal six-IV states.
PLANNER_STATIC_CATEGORIES = tuple(
    category for category in STATIC_CATEGORIES_118 if category != "Roaming"
)

_COMMON_TARGETS = {
    "Starter": ("Bulbasaur", "Charmander", "Squirtle"),
    "Fossil": ("Omanyte", "Kabuto", "Aerodactyl"),
    "Gift": ("Hitmonlee", "Hitmonchan", "Magikarp", "Lapras", "Eevee", "Togepi"),
    "Stationary": ("Hypno", "Electrode", "Snorlax"),
    "Legend": ("Articuno", "Zapdos", "Moltres", "Mewtwo"),
    "Event": ("Lugia", "Ho-Oh", "Deoxys"),
    "Roaming": ("Raikou", "Entei", "Suicune"),
}

STATIC_TARGETS_BY_GAME = {
    "fr": {
        **_COMMON_TARGETS,
        "GameCorner": ("Abra", "Clefairy", "Scyther", "Dratini", "Porygon"),
    },
    "lg": {
        **_COMMON_TARGETS,
        "GameCorner": ("Abra", "Clefairy", "Pinsir", "Dratini", "Porygon"),
    },
}


def game_family(game: str) -> str | None:
    normalized = (game or "").lower()
    if normalized.startswith("fr"):
        return "fr"
    if normalized.startswith("lg"):
        return "lg"
    return None


def get_static_targets(game: str, category: str) -> tuple[str, ...]:
    family = game_family(game)
    if family is None:
        return ()
    return STATIC_TARGETS_BY_GAME[family].get(category, ())


def is_supported_static_target(game: str, category: str, pokemon: str) -> bool:
    return pokemon in get_static_targets(game, category)
