"""Discover and preview logs produced by the PySide6 workflows."""
from __future__ import annotations

import re
import os
import stat as stat_module
from functools import cached_property
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

    @cached_property
    def search_text(self):
        return f"{self.workflow}\n{self.path}".casefold()

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


def history_roots(output_root: Path, user_root: Path):
    output = Path(output_root).resolve()
    runtime = output.parent if output.name.casefold() == "pyside6" else output
    archive = (Path(user_root) / "logs").resolve()
    roots = sorted({runtime, archive}, key=lambda p: len(p.parts))
    unique = []
    for root in roots:
        if not any(root.is_relative_to(parent) for parent in unique):
            unique.append(root)
    return tuple(unique), archive


def discover_logs(output_root: Path, user_root: Path, *, cancelled=lambda: False, status=lambda _: None) -> tuple[LogHistoryEntry, ...]:
    """Return current and archived logs, newest first, without duplicates."""
    roots, archive = history_roots(output_root, user_root)
    found: dict[Path, LogHistoryEntry] = {}
    pending = list(roots)
    skipped = {"imglabel", "tessdata", "seed_backup", "node_modules", ".git", "__pycache__"}
    while pending:
        if cancelled():
            return ()
        root = pending.pop()
        try:
            with os.scandir(root) as paths:
                for item in paths:
                    if cancelled():
                        return ()
                    try:
                        stat = item.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat_module.S_ISLNK(stat.st_mode) or getattr(stat, "st_file_attributes", 0) & 0x400:
                        continue
                    path = Path(item.path)
                    if stat_module.S_ISDIR(stat.st_mode):
                        if item.name.casefold() not in skipped:
                            pending.append(path)
                    elif stat_module.S_ISREG(stat.st_mode) and item.name.casefold().endswith(".log"):
                        found[path] = LogHistoryEntry(path, _workflow_name(path), stat.st_mtime_ns,
                                                      stat.st_size, path.is_relative_to(archive))
                        if len(found) % 250 == 0:
                            status(f"后台扫描：已发现 {len(found)} 份日志")
        except OSError:
            continue
    return tuple(sorted(found.values(), key=lambda item: item.modified_ns, reverse=True))


def read_log_preview(path: Path, *, max_bytes: int = 256 * 1024, max_lines: int = 3000) -> str:
    """Read a safe tail preview while keeping the original log untouched."""
    path = Path(path)
    max_bytes = min(max(1, max_bytes), 1024 * 1024)
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        truncated = size > max_bytes
        if truncated:
            stream.seek(-max_bytes, 2)
        payload = stream.read(max_bytes)
    text = payload.decode("utf-8", errors="replace")
    # NUL padding and nonprinting control bytes have no meaning in a text log;
    # discard them in the preview only, including sparse-file padding.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f]", "", text)
    if truncated:
        # Drop a partial leading line / UTF-8 sequence at the tail boundary.
        text = text.lstrip("\ufffd")
    lines = text.splitlines()
    if len(lines) > max_lines:
        truncated = True
        text = "\n".join(lines[-max_lines:])
    if truncated:
        text = f"[日志较大，仅显示末尾 {format_log_size(max_bytes)}；可打开原文件查看全部内容。]\n\n{text}"
    return _ANSI.sub("", text)


def format_log_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"
