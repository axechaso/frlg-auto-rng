"""Observed round results and BINGO data, independent of the log display."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import re
import unicodedata


_ANSI = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_TIMESTAMP = re.compile(r"^\s*\[\d{2}:\d{2}:\d{2}(?:\.\d+)?\]\s*")
_ROUND = re.compile(r"^(?:孵蛋同Seed实战)?第\s*(\d+)\s*轮(?:开始)?$")
_COMPACT = re.compile(
    r"^本轮结果[：:]\s*Seed\s*([0-9a-fA-F]{4,8})\s*[（(]偏差\s*([+-]?\d+)[）)]"
    r"[，,]\s*消耗帧\s*(\d+)\s*[（(]偏差\s*([+-]?\d+)[）)]$"
)
_EGG = re.compile(
    r"^蛋帧结果[：:]\s*Held\s*(\d+)\s*[（(]偏差\s*([+-]?\d+)[）)]"
    r"[，,]\s*Pickup\s*(\d+)\s*[（(]偏差\s*([+-]?\d+)[）)]$"
)
_CELLS = set("0123456789０１２３４５６７８９①②③④⑤⑥⑦⑧⑨＋+＠@ｘxｏo．.·")


def clean_script_line(line: str) -> str:
    return _TIMESTAMP.sub("", _ANSI.sub("", line)).strip()


@dataclass
class RoundResult:
    segment: int
    number: int
    seed: str = ""
    seed_delta: int | None = None
    advances: int | None = None
    frame_delta: int | None = None
    normalized_delta: int | None = None
    seed_trusted: bool | None = None
    frame_trusted: bool | None = None
    note: str = ""

    @property
    def label(self) -> str:
        return str(self.number) if self.segment == 1 else f"{self.segment} / {self.number}"

    @property
    def axes_confirmed(self) -> bool:
        return self.seed_trusted is True and self.frame_trusted is True

    @property
    def result(self) -> str:
        if self.note:
            return self.note
        if self.seed_delta is None or self.frame_delta is None:
            return "等待本轮结果"
        if self.seed_trusted is False or self.frame_trusted is False:
            return "候选待确认"
        if self.seed_delta == self.frame_delta == 0:
            return "Seed / 帧命中" if self.axes_confirmed else "Seed / 帧零偏差待确认"
        return "存在偏差"


class RunSummary:
    """Only complete recognized records become visible results; no raw-line fallback."""
    def __init__(self, *, limit=1000):
        self.limit = limit
        self.rounds: OrderedDict[tuple[int, int], RoundResult] = OrderedDict()
        self.segment = 1
        self.current: RoundResult | None = None
        self.section = ""
        self.script_grid: tuple[tuple[str, ...], ...] | None = None
        self.tv_cells: tuple[str, ...] | None = None
        self._grid_rows = None
        self.version = 0

    def _round(self, number=None):
        if number is None:
            number = self.current.number if self.current else 1
        if self.current and number < self.current.number:
            self.segment += 1
            self.script_grid = self.tv_cells = None
            self._grid_rows = None
        key = self.segment, number
        if key not in self.rounds:
            self.rounds[key] = RoundResult(*key)
            if len(self.rounds) > self.limit:
                self.rounds.popitem(last=False)
        self.current = self.rounds[key]
        return self.current

    def _update(self, **values):
        row = self._round()
        changed = any(getattr(row, key) != value for key, value in values.items())
        if changed:
            for key, value in values.items():
                setattr(row, key, value)
            if ("note" not in values and row.note == "本轮未取得唯一结果"
                    and row.axes_confirmed and row.seed_delta is not None and row.frame_delta is not None):
                row.note = ""
            self.version += 1
        return changed

    def consume(self, raw: str) -> bool:
        if len(raw) > 8192:
            return False
        line = clean_script_line(raw)
        if not line:
            return False
        match = _ROUND.fullmatch(line)
        if match:
            if int(match[1]) == 0:
                return False
            before = len(self.rounds), id(self.current)
            self._round(int(match[1]))
            self.section = ""
            changed = before != (len(self.rounds), id(self.current))
            self.version += int(changed)
            return changed
        if re.search(r"=+\s*第\d+阶段[：:]", line):
            if self.current:
                self.segment += 1
                self.current = None
                self.script_grid = self.tv_cells = None
            self._grid_rows = None
            self.section = ""
            return True
        if line == "【BINGO】":
            self._grid_rows = {}
            return False
        if self._grid_rows is not None:
            match = re.fullmatch(r"([＋+－-]?[０-４0-4])\s+(.+)", line)
            if match:
                cells = tuple(char for char in match[2] if not char.isspace())
                offset = int(unicodedata.normalize("NFKC", match[1]))
                if len(cells) == 9 and all(char in _CELLS for char in cells):
                    self._grid_rows[offset] = cells
                    if len(self._grid_rows) == 9:
                        self.script_grid = tuple(self._grid_rows[i] for i in range(-4, 5))
                        self._grid_rows = None
                        self.version += 1
                        return True
                return False
            if line.startswith("【"):
                self._grid_rows = None
        match = re.fullmatch(r"TV帧\s+(.+)", line)
        if match:
            cells = tuple(char for char in match[1] if not char.isspace())
            if len(cells) == 9 and all(char in _CELLS for char in cells):
                self.tv_cells = cells
                self.version += 1
                return True
        if line in {"【Seed校准】", "【消耗帧校准】"}:
            self.section = line
            return False
        if line.startswith("【"):
            self.section = ""
        match = _COMPACT.fullmatch(line)
        if match:
            return self._update(seed=match[1].upper(), seed_delta=int(match[2]),
                                advances=int(match[3]), frame_delta=int(match[4]))
        match = re.fullmatch(r"(Seed可信|消耗帧最终可信)[：:]\s*([01])", line)
        if match:
            field = "seed_trusted" if match[1] == "Seed可信" else "frame_trusted"
            return self._update(**{field: match[2] == "1"})
        if line == "已命中目标，脚本停止":
            return self._update(note="脚本已确认目标", seed_trusted=True, frame_trusted=True)
        for pattern, field, convert in (
            (r"^命中Seed[：:]\s*([0-9a-fA-F]{4,8})$", "seed", str.upper),
            (r"^与目标Seed差[：:]\s*([+-]?\d+)\s*个seed$", "seed_delta", int),
            (r"^命中消耗帧[：:]\s*(\d+)\s*帧$", "advances", int),
            (r"^真实消耗帧误差[：:]\s*([+-]?\d+)\s*帧.*$", "frame_delta", int),
            (r"^归一化帧偏移[：:]\s*([+-]?\d+)\s*帧$", "normalized_delta", int),
        ):
            match = re.fullmatch(pattern, line)
            if match:
                return self._update(**{field: convert(match[1])})
        if self.section == "【消耗帧校准】":
            match = re.fullmatch(r"误差[：:]\s*([+-]?\d+)\s*帧", line)
            if match:
                return self._update(frame_delta=int(match[1]))
        match = re.search(r"剩余帧误差[：:]?\s*([+-]?\d+)\s*帧", line)
        if match:
            return self._update(normalized_delta=int(match[1]))
        match = _EGG.fullmatch(line)
        if match:
            return self._update(note=f"Held {match[1]}（{int(match[2]):+d}） / Pickup {match[3]}（{int(match[4]):+d}）")
        match = re.fullmatch(r"Seed结果[：:]\s*偏差\s*([+-]?\d+)[，,]未命中目标", line)
        if match:
            return self._update(seed_delta=int(match[1]), note="Seed 存在偏差")
        if line == "Seed结果: 命中目标Seed":
            return self._update(seed_delta=0, note="Seed 命中，等待蛋帧结果")
        match = re.fullmatch(r"当前TID[：:]\s*(\d{1,5})", line)
        if match and int(match[1]) <= 65535:
            number = self.current.number + 1 if self.current and self.current.note.startswith("识别到 TID") else None
            self._round(number)
            return self._update(note=f"识别到 TID {int(match[1]):05d}")
        if ((line.endswith("反查无候选") or "反查仍跨多个Seed" in line or "本轮结果不唯一" in line)
                and "追加" not in line and "重试" not in line):
            return self._update(note="本轮未取得唯一结果")
        if "已识别到出闪" in line or "时差检测到出闪" in line:
            return self._update(note="检测到闪光，等待目标核对")
        if line.startswith("SIDTRAVERSAL|") and line.endswith("|END=1"):
            fields = dict(part.split("=", 1) for part in line.split("|")[1:] if "=" in part)
            if fields.get("ROUND", "").isdigit():
                self._round(int(fields["ROUND"]))
                if (fields.get("EVENT") == "TARGET" and all(fields.get(name) == "1"
                        for name in ("SEED_MATCH", "ADV_MATCH", "SPECIES_MATCH"))):
                    return self._update(note="脚本已确认目标", seed_delta=0, frame_delta=0,
                                        seed_trusted=True, frame_trusted=True)
                if fields.get("EVENT") in {"NON_TARGET_SHINY", "INCOMPLETE"}:
                    return self._update(note="非目标闪光" if fields["EVENT"] == "NON_TARGET_SHINY" else "目标证据不完整")
        return False

    def bingo(self):
        if self.script_grid is not None:
            return self.script_grid, "脚本 BINGO 观测表"
        counts = [[0] * 9 for _ in range(9)]
        last = None
        last_exact = False
        for row in self.rounds.values():
            frame = row.normalized_delta if row.normalized_delta is not None else row.frame_delta
            if row.segment != self.segment or row.seed_delta is None or frame is None:
                continue
            last = None
            if (-4 <= row.seed_delta <= 4 and -4 <= frame <= 4
                    and row.seed_trusted is not False and row.frame_trusted is not False
                    and row.note != "本轮未取得唯一结果"):
                last = row.seed_delta + 4, frame + 4
                last_exact = row.axes_confirmed and row.seed_delta == row.frame_delta == 0
                counts[last[0]][last[1]] += 1
        cells = [[str(value) if value else "·" for value in row] for row in counts]
        cells[4][4] = "＋"
        if last == (4, 4):
            if last_exact:
                cells[4][4] = "＠"
        elif last:
            y, x = last
            count = counts[y][x]
            cells[y][x] = "①②③④⑤⑥⑦⑧⑨"[count - 1] if count <= 9 else f"({count})"
        normalized = any(row.segment == self.segment and row.normalized_delta is not None
                         for row in self.rounds.values())
        axis = "归一化帧偏差" if normalized else "原始帧偏差"
        return tuple(tuple(row) for row in cells), f"按当前结果表统计 · {axis}"
