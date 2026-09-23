"""Discover and preview logs produced by the PySide6 workflows."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_WORKFLOW_NAMES = {
    "wild": "野生 / 静态",
    "egg": "孵蛋",
    "sid": "SID 查找",
    "tid": "TID 乱数",
    "sid_traversal": "SID 遍历",
    "script_test": "脚本测试",
}
_RUN_DIRECTORY = re.compile(
    r"^(wild|egg|sid|tid|sid_traversal|script_test)-[0-9a-f]{32}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LogHistoryEntry:
    path: Path
    workflow: str
    modified_ns: int
    size: int
    archived: bool

    @property
    def modified_text(self) -> str:
        return datetime.fromtimestamp(self.modified_ns / 1_000_000_000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    @property
    def location_text(self) -> str:
        return "归档" if self.archived else "运行工程"


def _workflow_name(path: Path) -> str:
    for part in reversed(path.parts):
        match = _RUN_DIRECTORY.fullmatch(part)
        if match:
            return _WORKFLOW_NAMES[match.group(1).lower()]
    lowered = path.name.casefold()
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered)
    # Check longer names first: ``sid_traversal`` must not be swallowed by
    # the generic ``sid_`` prefix.
    for key in sorted(_WORKFLOW_NAMES, key=len, reverse=True):
        title = _WORKFLOW_NAMES[key]
        if normalized.startswith(key + "_") or ("_" + key + "_") in normalized:
            return title
    return "其他"


def discover_logs(output_root: Path, user_root: Path) -> tuple[LogHistoryEntry, ...]:
    """Return current and archived logs, newest first, without duplicates."""
    output_root = Path(output_root)
    runtime_roots = [output_root]
    # Source and normal portable builds use ``runtime/pyside6`` now.  Include
    # sibling legacy runtime directories so logs created before the migration
    # remain visible on the same history page.
    if output_root.name.casefold() == "pyside6":
        runtime_roots.append(output_root.parent)
    roots = tuple((root, False) for root in runtime_roots) + (
        (Path(user_root) / "logs", True),
    )
    found: dict[Path, LogHistoryEntry] = {}
    for root, archived in roots:
        if not root.is_dir():
            continue
        try:
            paths = root.rglob("*.log")
            for path in paths:
                try:
                    resolved = path.resolve()
                    stat = resolved.stat()
                except OSError:
                    continue
                if not resolved.is_file():
                    continue
                entry = LogHistoryEntry(
                    resolved,
                    _workflow_name(resolved),
                    stat.st_mtime_ns,
                    stat.st_size,
                    archived,
                )
                previous = found.get(resolved)
                if previous is None or entry.modified_ns > previous.modified_ns:
                    found[resolved] = entry
        except OSError:
            continue
    return tuple(sorted(found.values(), key=lambda item: item.modified_ns, reverse=True))


def read_log_preview(path: Path, *, max_bytes: int = 4 * 1024 * 1024) -> str:
    """Read a safe tail preview while keeping the original log untouched."""
    path = Path(path)
    size = path.stat().st_size
    truncated = size > max_bytes
    with path.open("rb") as stream:
        if truncated:
            stream.seek(-max_bytes, 2)
        payload = stream.read()
    text = payload.decode("utf-8", errors="replace")
    if truncated:
        text = f"[日志较大，仅显示末尾 {format_log_size(max_bytes)}；可打开原文件查看全部内容。]\n\n{text}"
    return _ANSI.sub("", text)


def format_log_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"
