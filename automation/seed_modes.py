"""Mapping between Ten Lines game settings and the 1.1.8 Seed mode field."""

from rng.tenlines_utils import GameSettings


_MODE_VALUES = {
    0: ("mono", "h", "a", "none"),
    1: ("stereo", "h", "a", "none"),
    2: ("mono", "h", "start", "none"),
    3: ("stereo", "h", "start", "none"),
    4: ("mono", "h", "a", "blackout_r"),
    5: ("mono", "h", "a", "blackout_l"),
    6: ("stereo", "h", "a", "blackout_r"),
    7: ("stereo", "h", "a", "blackout_l"),
    8: ("mono", "h", "start", "blackout_r"),
    9: ("mono", "h", "start", "blackout_l"),
}


def seed_mode_to_settings(seed_mode: int) -> GameSettings:
    """Convert a 1.1.8 Seed mode number to structured game settings."""
    try:
        sound, button_mode, seed_button, extra_button = _MODE_VALUES[seed_mode]
    except KeyError as exc:
        raise ValueError("Seed 模式必须在 0-9 之间") from exc
    return GameSettings(
        sound=sound,
        button_mode=button_mode,
        seed_button=seed_button,
        extra_button=extra_button,
    )


def settings_to_seed_mode(settings: GameSettings) -> int | None:
    """Return the exact 1.1.8 mode for settings, or ``None`` if unsupported."""
    value = (
        settings.sound,
        settings.button_mode,
        settings.seed_button,
        settings.extra_button,
    )
    for seed_mode, candidate in _MODE_VALUES.items():
        if candidate == value:
            return seed_mode
    return None


def seed_mode_label(seed_mode: int) -> str:
    settings = seed_mode_to_settings(seed_mode)
    return (
        f"{seed_mode}: {settings.sound}_{settings.button_mode}_"
        f"{settings.seed_button}_{settings.extra_button}"
    )


SEED_MODE_CHOICES = tuple(seed_mode_label(i) for i in sorted(_MODE_VALUES))
