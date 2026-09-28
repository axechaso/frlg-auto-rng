"""Classify EasyCon output independently of its unreliable process exit code."""

EASYCON_FATAL_MARKERS = (
    "!!意外错误!!",
    "-- 运行出错 --",
    "脚本编译出错",
    "脚本编译错误",
    "Index was outside the bounds of the array",
    "Unhandled exception",
)


def easycon_log_has_fatal_error(text: str) -> bool:
    """Return true for failures that some EasyCon builds still exit with code 0."""
    folded = text.casefold()
    return any(marker.casefold() in folded for marker in EASYCON_FATAL_MARKERS)
