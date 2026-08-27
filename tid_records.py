"""Persistent, game/model-specific TID observations; never store SID data."""

from __future__ import annotations

from contextlib import contextmanager
import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid


ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


@dataclass(frozen=True)
class TidRecordContext:
    game: str
    nx_model: int
    language: str
    player_name: str
    gender: int
    sound: int
    button_mode: int
    seed_button: int
    name_entry_button: int
    op_fixed_delay: int
    f1_fixed_delay: int
    f2_fixed_delay: int
    op_correction: int
    select_correction: int
    home_buffer_delay: int

    def __post_init__(self):
        if self.game not in ("火红", "叶绿"):
            raise ValueError("TID记录必须指定火红或叶绿")
        if type(self.nx_model) is not int or self.nx_model not in (1, 2):
            raise ValueError("TID记录必须指定Switch 1或Switch 2")
        if self.language not in ("英文", "日文"):
            raise ValueError("TID记录语言必须为英文或日文")

    @classmethod
    def from_request(cls, game: str, request):
        return cls(game=game, **{
            name: getattr(request, name) for name in cls.__dataclass_fields__ if name != "game"
        })

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass(frozen=True)
class TidObservation:
    tid: int
    op: int
    f1: int
    f2: int
    select_count: int
    context: TidRecordContext

    def parameters(self) -> dict:
        return {**asdict(self.context), "OP": self.op, "F1": self.f1, "F2": self.f2, "select_count": self.select_count}


class TidLogParser:
    """Consume complete log lines, committing only complete observed-TID rows."""

    def __init__(self, context: TidRecordContext, *, flow: bool = False):
        self.base_context = context
        self.context = context
        self.active = not flow
        self.buffer = ""
        self.pending: dict = {}

    def feed(self, text: str, *, final: bool = False) -> list[TidObservation]:
        self.buffer += text
        lines = self.buffer.split("\n")
        self.buffer = lines.pop()
        if final and self.buffer:
            lines.append(self.buffer)
            self.buffer = ""
        result = []
        for raw in lines:
            row = self._line(ANSI_RE.sub("", raw).strip())
            if row is not None:
                result.append(row)
        return result

    def _line(self, line: str) -> TidObservation | None:
        stage = re.search(r"=+\s*第(\d+)阶段[：:]", line)
        if stage:
            self.active = int(stage[1]) == 1
            self.context = self.base_context
            self.pending = {}
            return None
        if not self.active:
            return None
        correction = re.search(r"OP修正增加50ms[：:]\s*当前修正=(-?\d+)ms", line)
        if correction:
            self.context = replace(self.context, op_correction=int(correction[1]))
            self.pending = {}
        if "ID识别不完整" in line:
            self.pending = {}
        tid = re.search(r"当前TID[：:]\s*(\d{1,5})\s*$", line)
        if tid:
            self.pending = {"tid": int(tid[1])} if int(tid[1]) <= 65535 else {}
            return None
        # A malformed/new TID line must never reuse the previous observation.
        if "当前TID：" in line or "当前TID:" in line:
            self.pending = {}
        frames = re.search(r"【OP】\s*(\d+)\s*【F1】\s*(\d+)\s*【F2】\s*(\d+)\s*$", line)
        if frames and "tid" in self.pending:
            self.pending.update(op=int(frames[1]), f1=int(frames[2]), f2=int(frames[3]))
        select = re.search(r"select执行次数[：:]\s*(\d+)(?:\s*[；;].*)?$", line)
        if select and all(name in self.pending for name in ("tid", "op", "f1", "f2")):
            home = re.search(r"HOME_BUFFER\(ms\)[：:]\s*(\d+)", line)
            context = replace(self.context, home_buffer_delay=int(home[1])) if home else self.context
            observation = TidObservation(**self.pending, select_count=int(select[1]), context=context)
            self.pending = {}
            return observation
        return None


class TidRecordStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Recording must not hold up reading EasyCon's output when another
        # process briefly owns the database. The session retries pending rows.
        connection = sqlite3.connect(self.path, timeout=0.05)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("""CREATE TABLE IF NOT EXISTS observations (
                run_id TEXT NOT NULL, sequence INTEGER NOT NULL, tid INTEGER NOT NULL,
                game TEXT NOT NULL, nx_model INTEGER NOT NULL, configuration_key TEXT NOT NULL,
                parameters TEXT NOT NULL, log_path TEXT NOT NULL, recorded_at TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence))""")
            connection.execute("CREATE INDEX IF NOT EXISTS observations_lookup ON observations(game,nx_model,tid)")
            with connection:
                yield connection
        finally:
            connection.close()

    def append(self, run_id: str, rows: list[tuple[int, TidObservation]], log_path: Path) -> None:
        if not rows:
            return
        values = []
        for sequence, row in rows:
            parameters = json.dumps(row.parameters(), ensure_ascii=False, sort_keys=True)
            values.append((run_id, sequence, row.tid, row.context.game, row.context.nx_model,
                           hashlib.sha256(parameters.encode("utf-8")).hexdigest(), parameters,
                           str(log_path), datetime.now().astimezone().isoformat(timespec="seconds")))
        with self._connection() as connection:
            connection.executemany("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?,?)", values)

    def rows(self, *, game=None, nx_model=None, tid=None, limit=1000) -> list[dict]:
        clauses, arguments = [], []
        for column, value in (("game", game), ("nx_model", nx_model), ("tid", tid)):
            if value is not None:
                clauses.append(column + " = ?")
                arguments.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        query = ("SELECT tid, parameters, COUNT(*) AS occurrences, MAX(recorded_at) AS last_seen "
                 "FROM observations" + where + " GROUP BY configuration_key,tid ORDER BY last_seen DESC,tid")
        if limit is not None:
            query += " LIMIT ?"
            arguments.append(limit)
        if not self.path.is_file():
            return []
        with self._connection() as connection:
            return [{**json.loads(row["parameters"]), "tid": row["tid"],
                     "occurrences": row["occurrences"], "last_seen": row["last_seen"]}
                    for row in connection.execute(query, arguments)]

    def export_csv(self, path: Path, **filters) -> int:
        rows = self.rows(**filters, limit=None)
        columns = ("game", "nx_model", "tid", "language", "OP", "F1", "F2", "occurrences",
                   "player_name", "gender", "op_correction", "op_fixed_delay", "f1_fixed_delay",
                   "f2_fixed_delay", "select_count", "select_correction", "sound", "button_mode",
                   "seed_button", "name_entry_button", "home_buffer_delay", "last_seen")
        labels = ("游戏", "Switch机型", "TID", "语言", "OP", "F1", "F2", "出现次数", "主角名称",
                  "性别(0男1女)", "OP修正ms", "OP固定延迟ms", "F1固定延迟ms", "F2固定延迟ms",
                  "SELECT执行次数", "SELECT额外补偿", "Sound", "ButtonMode", "SeedButton", "取名进入键",
                  "HOME_BUFFER延迟ms", "最近记录时间")
        with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(labels)
            for row in rows:
                values = [f"{row['tid']:05d}" if key == "tid" else row[key] for key in columns]
                writer.writerow(["'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in values])
        return len(rows)


class TidRecordingSession:
    """Runs in the worker process so recording survives closing the GUI."""

    def __init__(self, context, store, log_path, *, flow=False, warning=None):
        self.parser = TidLogParser(context, flow=flow)
        self.store = store
        self.log_path = log_path
        self.run_id = str(uuid.uuid4())
        self.sequence = 0
        self.pending = []
        self.warning = warning or (lambda message: None)
        self.warned = False
        self.retry_after = 0.0

    def feed(self, text: str, *, final=False):
        for row in self.parser.feed(text, final=final):
            self.sequence += 1
            self.pending.append((self.sequence, row))
        if not self.pending or (not final and time.monotonic() < self.retry_after):
            return
        try:
            self.store.append(self.run_id, self.pending, self.log_path)
        except (OSError, sqlite3.Error) as exc:
            self.retry_after = time.monotonic() + 1.0
            if not self.warned:
                self.warned = True
                self.warning(f"[TID_TABLE_WARNING] TID表暂时写入失败，保留待重试记录；原始日志仍保留：{exc}")
        else:
            self.pending.clear()
            self.warned = False
            self.retry_after = 0.0


@contextmanager
def recording_session(context_path, database_path, log_path, *, flow=False, warning=None):
    if context_path is None and database_path is None:
        yield None
        return
    if context_path is None or database_path is None:
        raise ValueError("TID记录必须同时提供配置快照和数据库路径")
    payload = json.loads(Path(context_path).read_text(encoding="utf-8"))
    context = TidRecordContext(**payload)
    session = TidRecordingSession(context, TidRecordStore(database_path), log_path, flow=flow, warning=warning)
    try:
        yield session
    finally:
        session.feed("", final=True)
        if session.pending:
            session.warning("[TID_TABLE_WARNING] 部分TID记录未能写入数据库，请保留本次原始日志。")
