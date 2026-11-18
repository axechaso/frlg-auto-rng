"""Native Qt round table and BINGO chart; no script console on this surface."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QGridLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from .run_summary import RunSummary


class RunSummaryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.round_table = QTableWidget(0, 6)
        self.round_table.setObjectName("roundResultsTable")
        self.round_table.setAccessibleName("每轮命中结果")
        self.round_table.setHorizontalHeaderLabels(("轮次", "命中 Seed", "Seed 差", "命中帧", "帧差", "本轮结果"))
        self.round_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.round_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.round_table.verticalHeader().hide()
        self.round_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.round_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.round_table.setMinimumHeight(290)
        layout.addWidget(self.round_table, 0, 0)
        chart = QWidget()
        chart_layout = QVBoxLayout(chart)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        self.bingo_label = QLabel("BINGO · 等待观测数据")
        self.bingo_label.setWordWrap(True)
        chart_layout.addWidget(self.bingo_label)
        self.bingo_table = QTableWidget(9, 9)
        self.bingo_table.setAccessibleName("BINGO 命中分布图")
        self.bingo_table.setObjectName("bingoTable")
        headers = [f"{i:+d}" if i else "0" for i in range(-4, 5)]
        self.bingo_table.setHorizontalHeaderLabels(headers)
        self.bingo_table.setVerticalHeaderLabels(headers)
        self.bingo_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.bingo_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.bingo_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bingo_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.bingo_table.setMinimumSize(310, 270)
        chart_layout.addWidget(self.bingo_table, 1)
        self.tv_label = QLabel()
        self.tv_label.setWordWrap(True)
        self.tv_label.hide()
        chart_layout.addWidget(self.tv_label)
        legend = QLabel("横轴：帧偏差 · 纵轴：Seed 偏差\n＋目标中心　＠命中中心　带圈数字为本轮\n数字为累计　ｏ预测　ｘ未计入")
        legend.setWordWrap(True)
        legend.setObjectName("cardSubtitle")
        chart_layout.addWidget(legend)
        layout.addWidget(chart, 0, 1)
        layout.setColumnStretch(0, 3)
        layout.setColumnStretch(1, 2)
        self._row_cache = []
        self._grid_cache = None
        self.reset()

    def reset(self):
        self.round_table.setRowCount(0)
        self._row_cache = []
        self._grid_cache = None
        self.tv_label.hide()
        self.bingo_label.setText("BINGO · 等待观测数据")
        self.sync(RunSummary())

    def sync(self, summary):
        rows = list(summary.rounds.values())
        bar = self.round_table.verticalScrollBar()
        following = bar.value() >= bar.maximum() - 2
        self.round_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = (row.label, row.seed or "—",
                      f"{row.seed_delta:+d}" if row.seed_delta is not None else "—",
                      str(row.advances) if row.advances is not None else "—",
                      f"{row.frame_delta:+d}" if row.frame_delta is not None else "—", row.result)
            if index < len(self._row_cache) and self._row_cache[index] == values:
                continue
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.round_table.setItem(index, column, item)
        self._row_cache = [tuple(self.round_table.item(i, j).text() for j in range(6)) for i in range(len(rows))]
        if following and rows:
            self.round_table.scrollToBottom()
        grid, source = summary.bingo()
        if grid != self._grid_cache:
            for y, row in enumerate(grid):
                for x, glyph in enumerate(row):
                    item = QTableWidgetItem(glyph)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setToolTip(f"Seed 偏差 {y - 4:+d}，帧偏差 {x - 4:+d}：{glyph}")
                    if glyph in "＠@①②③④⑤⑥⑦⑧⑨" or glyph.startswith("("):
                        color = "#d1fae5"
                    elif glyph in "ｏo":
                        color = "#dbeafe"
                    elif glyph in "ｘx":
                        color = "#fee2e2"
                    elif glyph.isdecimal():
                        color = "#e0e7ff"
                    else:
                        color = "#f1f5f9" if (y, x) != (4, 4) else "#fef3c7"
                    item.setBackground(QColor(color))
                    item.setForeground(QColor("#25334b"))
                    self.bingo_table.setItem(y, x, item)
            self._grid_cache = grid
        self.bingo_label.setText("BINGO · " + (source if rows or summary.script_grid else "等待观测数据"))
        self.tv_label.setVisible(summary.tv_cells is not None)
        if summary.tv_cells:
            self.tv_label.setText("TV 帧（-4～+4）：" + "  ".join(summary.tv_cells))
