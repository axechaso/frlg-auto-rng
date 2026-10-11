"""Read context-bound TID checkpoints from existing logs, without game actions."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
import time

from automation.tid_calibration import tid_request_from_dict
from automation.tid_checkpoint import ANSI, DONE_MARKER, SEARCH_STATE_VARIABLES, parse_checkpoint, validate_checkpoint
from pyside_app.log_history import discover_logs, LogHistoryEntry
from tid_session import progress_lease, progress_path, read_progress, write_json_atomic


_SCOPE = re.compile(r"^\[TID进度\]\s+.*?([0-9a-f]{64})\.json$", re.IGNORECASE)
_STAGE = re.compile(r"^=+\s*第(\d+)阶段：")
_LINE_LIMIT = 64 * 1024


@dataclass(frozen=True)
class LogProgress:
    context: dict
    state: dict
    completed: bool
    log_path: Path
    modified_ns: int


@dataclass
class _Cursor:
    identity: tuple
    modified_ns: int = 0
    offset: int = 0
    active: str | None = None
    records: dict = field(default_factory=dict)


class TidProgressLogReader:
    """Worker-only incremental reader; complete lines and exact contexts only."""

    def __init__(self):
        self._roots = None
        self._discovered_at = float("-inf")
        self._rows = ()
        self._contexts = None
        self._files = {}

    def scan(self, output: Path, user: Path, contexts: tuple[dict, ...], *,
             extra_logs=(), cancelled=lambda: False) -> tuple[LogProgress, ...]:
        roots = (Path(output), Path(user))
        signature = tuple(progress_path(Path(), context).stem for context in contexts)
        if signature != self._contexts or roots != self._roots:
            self._files.clear()
            self._contexts = signature
            self._discovered_at = float("-inf")
        self._roots = roots
        if time.monotonic() - self._discovered_at >= 30:
            rows = discover_logs(output, user, cancelled=cancelled)
            if cancelled():
                return ()
            self._rows = tuple(row for row in rows if row.workflow == "TID 乱数")
            self._discovered_at = time.monotonic()
        rows = {row.path: row for row in self._rows}
        for path in extra_logs:
            path = Path(path)
            rows[path] = LogHistoryEntry(path, "TID 乱数", 0, 0, False)
        requests = {key: tid_request_from_dict(context["request"])
                    for key, context in zip(signature, contexts)}
        found = {}
        files = []
        for path in rows:
            if cancelled():
                return ()
            try:
                stat = path.stat()
                if path.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                    continue
                files.append((path, stat))
            except OSError:
                continue
        files.sort(key=lambda item: item[1].st_mtime_ns, reverse=True)
        existing = {path for path, _stat in files}
        for path, stat in files:
            if cancelled():
                return ()
            try:
                cursor = self._read(path, stat, requests, cancelled)
            except OSError:
                continue
            for key, (state, completed) in cursor.records.items():
                if state is None:
                    continue
                candidate = LogProgress(contexts[signature.index(key)], state, completed,
                                        path, stat.st_mtime_ns)
                previous = found.get(key)
                if previous is None or candidate.modified_ns > previous.modified_ns:
                    found[key] = candidate
            if len(found) == len(requests):
                break  # Older logs cannot replace any of these contexts.
        cached = sorted(((path, cursor) for path, cursor in self._files.items() if path in existing),
                        key=lambda item: item[1].modified_ns, reverse=True)
        self._files = dict(cached[:256])
        return tuple(found.values()) if not cancelled() else ()

    def _read(self, path, stat, requests, cancelled):
        identity = (stat.st_dev, stat.st_ino)
        cursor = self._files.get(path)
        if (cursor is None or cursor.identity != identity or stat.st_size < cursor.offset
                or (stat.st_mtime_ns != cursor.modified_ns and stat.st_size == cursor.offset)):
            cursor = self._files[path] = _Cursor(identity)
        if stat.st_mtime_ns == cursor.modified_ns and stat.st_size == cursor.offset:
            return cursor
        with path.open("rb") as stream:
            stream.seek(cursor.offset)
            while not cancelled():
                position = stream.tell()
                raw = stream.readline(_LINE_LIMIT + 1)
                if not raw:
                    break
                if len(raw) > _LINE_LIMIT:
                    # An oversized line is not a checkpoint. Don't turn its
                    # continuation into a new, apparently complete marker.
                    while raw and not raw.endswith(b"\n") and not cancelled():
                        raw = stream.readline(_LINE_LIMIT + 1)
                    if not raw.endswith(b"\n"):
                        stream.seek(position)
                        break
                elif not raw.endswith(b"\n"):
                    # A live writer may only have flushed half the marker.
                    stream.seek(position)
                    break
                else:
                    line = ANSI.sub("", raw.decode("utf-8-sig", errors="replace")).strip()
                    scope = _SCOPE.fullmatch(line)
                    stage = _STAGE.match(line)
                    if scope:
                        cursor.active = scope[1].lower() if scope[1].lower() in requests else None
                        if cursor.active:
                            cursor.records[cursor.active] = (None, False)
                    elif stage and stage[1] != "1":
                        cursor.active = None
                    elif cursor.active:
                        key = cursor.active
                        state, completed = cursor.records[key]
                        try:
                            parsed = parse_checkpoint(line, requests[key])
                        except ValueError:
                            parsed = None
                        if (parsed is not None and not completed
                                and set(parsed) == set(SEARCH_STATE_VARIABLES)):
                            state = parsed
                        if line.endswith(DONE_MARKER) and state is not None:
                            completed = True
                        cursor.records[key] = (state, completed)
                cursor.offset = stream.tell()
        cursor.modified_ns = stat.st_mtime_ns
        return cursor


def recover_log_progress(directory: Path, record: LogProgress) -> bool:
    """Restore a lost/stale checkpoint under the same worker lease.

    A fresh run's empty state and completed checkpoints are authoritative.
    Existing invalid JSON is not overwritten. Old/touched logs cannot move a
    valid checkpoint backwards; equal-count conflicts are not guessed at.
    """
    validate_checkpoint(record.state, tid_request_from_dict(record.context["request"]))
    if set(record.state) != set(SEARCH_STATE_VARIABLES):
        return False
    path = progress_path(directory, record.context)
    try:
        with progress_lease(path.with_suffix(".lock")):
            previous = read_progress(directory, record.context)
            if previous is not None:
                old = previous.get("state")
                if old is None or previous["status"] == "completed":
                    return False
                try:
                    updated = datetime.fromisoformat(previous["updated_at"])
                    if updated.tzinfo is None or record.modified_ns / 1e9 <= updated.timestamp():
                        return False
                except (ValueError, KeyError, TypeError):
                    return False
                if record.state["COUNT"] < old["COUNT"]:
                    return False
                if record.state["COUNT"] == old["COUNT"] and (
                    record.state != old or not record.completed
                ):
                    return False
            write_json_atomic(path, {"schema": 1, "context": record.context,
                "state": record.state, "status": "completed" if record.completed else "paused",
                "updated_at": datetime.fromtimestamp(record.modified_ns / 1e9, timezone.utc).isoformat(),
                "source_log": str(record.log_path)})
            return True
    except RuntimeError:
        # An active worker owns the search. Its JSON remains the live source.
        return False
