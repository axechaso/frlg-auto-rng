"""Standalone PySide6 visual prototype for the FRLG automation GUI.

This module deliberately does not import or replace the production Tk entry.
It is an interaction and layout prototype used to settle the visual direction
before the existing planner and runner services are wired into Qt widgets.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_paths import RESOURCE_ROOT
from app_version import APP_VERSION


WINDOW_TITLE = "火红 / 叶绿全自动乱数 · PySide6 界面初版"
NAV_ITEMS = (
    ("sid", "SID 查找", "闪光个体反查 SID"),
    ("tid", "TID 乱数", "建档与御三家计划"),
    ("wild", "野生 / 静态", "目标筛选与方案搜索"),
    ("egg", "孵蛋", "同 Seed 生成与领取"),
    ("logs", "运行日志", "实时状态与历史输出"),
)


APP_STYLE = r"""
* {
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
    color: #172033;
}
QMainWindow, QWidget#appRoot, QScrollArea, QScrollArea > QWidget > QWidget {
    background: #f3f6fb;
}
QFrame#sidebar {
    background: #17213a;
    border: none;
}
QLabel#brandMark {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #6d7cff, stop:1 #35c5a6);
    color: white;
    border-radius: 11px;
    font-size: 18px;
    font-weight: 800;
}
QLabel#brandTitle {
    color: #ffffff;
    font-size: 18px;
    font-weight: 800;
}
QLabel#brandSub, QLabel#sideMuted {
    color: #91a0bd;
    font-size: 11px;
}
QPushButton#navButton {
    min-height: 46px;
    padding: 0 15px;
    border: none;
    border-radius: 10px;
    background: transparent;
    color: #aeb9cf;
    font-weight: 600;
    text-align: left;
}
QPushButton#navButton:hover {
    background: #202d4a;
    color: #ffffff;
}
QPushButton#navButton:checked {
    background: #2a3960;
    color: #ffffff;
    border-left: 3px solid #6f88ff;
}
QFrame#sideStatus {
    background: #202d4a;
    border: 1px solid #2f4065;
    border-radius: 12px;
}
QLabel#sideStatusTitle {
    color: #ffffff;
    font-weight: 700;
}
QLabel#sideStatusText {
    color: #9eacc6;
    font-size: 11px;
}
QLabel#pageTitle {
    font-size: 24px;
    font-weight: 800;
    color: #14203a;
}
QLabel#pageDescription, QLabel[role="muted"] {
    color: #718096;
}
QLabel[role="eyebrow"] {
    color: #5f72e8;
    font-size: 11px;
    font-weight: 800;
}
QFrame#previewBanner {
    background: #eef1ff;
    border: 1px solid #dce2ff;
    border-radius: 9px;
}
QLabel#previewBannerTitle {
    color: #485cc7;
    font-weight: 700;
}
QFrame#profileChip, QFrame#deviceChip {
    background: #ffffff;
    border: 1px solid #e1e7f0;
    border-radius: 11px;
}
QLabel#chipTitle {
    color: #6d7a90;
    font-size: 10px;
}
QLabel#chipValue {
    color: #172033;
    font-weight: 700;
}
QFrame#card {
    background: #ffffff;
    border: 1px solid #e3e8f1;
    border-radius: 14px;
}
QLabel#cardTitle {
    color: #172033;
    font-size: 16px;
    font-weight: 800;
}
QLabel#cardSubtitle {
    color: #7a879c;
    font-size: 11px;
}
QLabel#fieldLabel {
    color: #566278;
    font-size: 11px;
    font-weight: 700;
}
QLineEdit, QComboBox, QSpinBox {
    min-height: 34px;
    padding: 0 10px;
    background: #f8faff;
    border: 1px solid #dbe2ed;
    border-radius: 8px;
    selection-background-color: #6d7cff;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    background: #ffffff;
    border: 1px solid #6d7cff;
}
QComboBox::drop-down {
    width: 26px;
    border: none;
}
QCheckBox {
    spacing: 8px;
    color: #46536a;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
}
QPushButton[kind="ghost"] {
    min-height: 34px;
    padding: 0 14px;
    border: 1px solid #dbe2ed;
    border-radius: 8px;
    background: #ffffff;
    color: #42506a;
    font-weight: 650;
}
QPushButton[kind="ghost"]:hover {
    background: #f1f4ff;
    border-color: #aebaff;
}
QPushButton[kind="preset"] {
    min-height: 29px;
    padding: 0 11px;
    border: 1px solid #dce2ef;
    border-radius: 14px;
    background: #f8faff;
    color: #5a6780;
    font-weight: 700;
}
QPushButton[kind="preset"]:hover {
    color: #4f62d9;
    border-color: #9facff;
    background: #eef1ff;
}
QPushButton[kind="primary"] {
    min-height: 40px;
    padding: 0 21px;
    border: none;
    border-radius: 10px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #6177f2, stop:1 #6f5fe9);
    color: #ffffff;
    font-weight: 800;
}
QPushButton[kind="primary"]:hover {
    background: #5369e4;
}
QPushButton[kind="success"] {
    min-height: 40px;
    padding: 0 21px;
    border: none;
    border-radius: 10px;
    background: #22a785;
    color: #ffffff;
    font-weight: 800;
}
QFrame#ivTile {
    background: #f8faff;
    border: 1px solid #e3e8f1;
    border-radius: 10px;
}
QLabel#ivName {
    color: #59677f;
    font-size: 11px;
    font-weight: 800;
}
QLabel#summaryName {
    color: #172033;
    font-size: 21px;
    font-weight: 850;
}
QLabel#successBadge {
    background: #e7f8f2;
    color: #16846a;
    border-radius: 10px;
    padding: 5px 10px;
    font-weight: 750;
}
QLabel#metricValue {
    color: #172033;
    font-size: 17px;
    font-weight: 850;
}
QLabel#metricLabel {
    color: #8290a5;
    font-size: 10px;
}
QFrame#metricTile {
    background: #f6f8fc;
    border: 1px solid #e5eaf2;
    border-radius: 10px;
}
QFrame#footerBar {
    background: #ffffff;
    border-top: 1px solid #dfe5ee;
}
QLabel#readyText {
    color: #16846a;
    font-weight: 750;
}
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8faff;
    border: 1px solid #e2e7f0;
    border-radius: 9px;
    gridline-color: #edf0f5;
    selection-background-color: #e9edff;
    selection-color: #172033;
}
QHeaderView::section {
    min-height: 34px;
    background: #f3f6fb;
    color: #5d6a80;
    border: none;
    border-bottom: 1px solid #dde4ee;
    font-weight: 750;
}
QPlainTextEdit#logView {
    background: #111827;
    color: #dbe5f5;
    border: 1px solid #263249;
    border-radius: 10px;
    padding: 10px;
    font-family: "Cascadia Mono", "Consolas";
    font-size: 12px;
}
QScrollBar:vertical {
    width: 11px;
    margin: 3px;
    background: transparent;
}
QScrollBar::handle:vertical {
    min-height: 34px;
    background: #c9d1df;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""


def _label(text: str, *, role: str | None = None, name: str | None = None) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    if name:
        widget.setObjectName(name)
    return widget


def _button(text: str, kind: str = "ghost") -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setProperty("kind", kind)
    return widget


def _combo(*items: str, current: int = 0) -> QComboBox:
    widget = QComboBox()
    widget.addItems(items)
    widget.setCurrentIndex(current)
    return widget


def _line(text: str = "", placeholder: str = "") -> QLineEdit:
    widget = QLineEdit(text)
    widget.setPlaceholderText(placeholder)
    return widget


class Card(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 17, 18, 18)
        self.layout.setSpacing(13)
        heading = QVBoxLayout()
        heading.setSpacing(3)
        heading.addWidget(_label(title, name="cardTitle"))
        if subtitle:
            heading.addWidget(_label(subtitle, name="cardSubtitle"))
        self.layout.addLayout(heading)


class FrlgPreviewWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(1180, 760)
        self.resize(1360, 880)
        self.setStyleSheet(APP_STYLE)
        self.nav_buttons: dict[str, QPushButton] = {}
        self.page_indices: dict[str, int] = {}

        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())
        outer.addWidget(self._build_workspace(), 1)
        self.select_page("wild")

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 22, 16, 18)
        layout.setSpacing(8)

        brand = QHBoxLayout()
        brand.setSpacing(11)
        mark = _label("F", name="brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(42, 42)
        brand.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(_label("FRLG RNG", name="brandTitle"))
        names.addWidget(_label(f"火红 / 叶绿 · v{APP_VERSION}", name="brandSub"))
        brand.addLayout(names)
        layout.addLayout(brand)
        layout.addSpacing(23)
        layout.addWidget(_label("工作区", name="sideMuted"))

        for key, title, _description in NAV_ITEMS:
            prefix = {
                "wild": "◆",
                "sid": "◎",
                "tid": "#",
                "egg": "○",
                "logs": "▤",
            }[key]
            button = QPushButton(f"  {prefix}    {title}")
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, page=key: self.select_page(page))
            self.nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        status = QFrame()
        status.setObjectName("sideStatus")
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(13, 12, 13, 13)
        status_layout.setSpacing(5)
        status_layout.addWidget(_label("●  EasyCon 1.6.4-a", name="sideStatusTitle"))
        status_layout.addWidget(_label("COM4 · Elgato HD60 S+", name="sideStatusText"))
        status_layout.addWidget(_label("设备已检测，可以生成方案", name="sideStatusText"))
        layout.addWidget(status)
        layout.addSpacing(6)
        layout.addWidget(_label("界面初版 · 不执行真实脚本", name="sideMuted"))
        return sidebar

    def _build_workspace(self) -> QWidget:
        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(26, 18, 26, 11)
        header_layout.setSpacing(10)

        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.page_title = _label("", name="pageTitle")
        self.page_description = _label("", name="pageDescription")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_description)
        top.addLayout(titles, 1)
        top.addWidget(self._chip("存档信息", "AXE · 58888 / 12232", "profileChip"))
        top.addSpacing(8)
        top.addWidget(self._chip("当前设备", "Switch 1 · COM4", "deviceChip"))
        header_layout.addLayout(top)

        banner = QFrame()
        banner.setObjectName("previewBanner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(12, 7, 12, 7)
        banner_layout.addWidget(_label("界面预览", name="previewBannerTitle"))
        banner_layout.addWidget(
            _label("当前用于确认布局和视觉方向，不会修改配置或启动 EasyCon。", role="muted")
        )
        banner_layout.addStretch(1)
        banner_layout.addWidget(_button("返回正式 Tk 版", "ghost"))
        header_layout.addWidget(banner)
        layout.addWidget(header)

        self.stack = QStackedWidget()
        self._add_page("wild", self._build_wild_page())
        self._add_page("sid", self._build_sid_page())
        self._add_page("tid", self._build_tid_page())
        self._add_page("egg", self._build_egg_page())
        self._add_page("logs", self._build_logs_page())
        layout.addWidget(self.stack, 1)
        layout.addWidget(self._build_footer())
        return workspace

    @staticmethod
    def _chip(title: str, value: str, object_name: str) -> QFrame:
        chip = QFrame()
        chip.setObjectName(object_name)
        chip.setMinimumWidth(178)
        chip_layout = QVBoxLayout(chip)
        chip_layout.setContentsMargins(12, 7, 12, 7)
        chip_layout.setSpacing(0)
        chip_layout.addWidget(_label(title, name="chipTitle"))
        chip_layout.addWidget(_label(value, name="chipValue"))
        return chip

    def _add_page(self, key: str, page: QWidget) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        self.page_indices[key] = self.stack.addWidget(scroll)

    @staticmethod
    def _page_canvas() -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 8, 26, 26)
        layout.setSpacing(16)
        return page, layout

    @staticmethod
    def _field(grid: QGridLayout, row: int, column: int, title: str, widget: QWidget) -> None:
        box = QVBoxLayout()
        box.setSpacing(5)
        box.addWidget(_label(title, name="fieldLabel"))
        box.addWidget(widget)
        grid.addLayout(box, row, column)

    def _build_wild_page(self) -> QWidget:
        page, layout = self._page_canvas()
        columns = QHBoxLayout()
        columns.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)
        right = QVBoxLayout()
        right.setSpacing(16)
        columns.addLayout(left, 7)
        columns.addLayout(right, 4)

        conditions = Card("乱数条件", "先选择游戏、遭遇方式和目标，再细化筛选范围。")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(11)
        self._field(grid, 0, 0, "游戏版本", _combo("火红", "叶绿"))
        self._field(grid, 0, 1, "目标类型", _combo("野生", "静态", "御三家"))
        self._field(grid, 0, 2, "主机", _combo("Switch 1", "Switch 2"))
        self._field(grid, 1, 0, "遭遇方式", _combo("草丛", "冲浪", "厉害钓竿", "碎岩"))
        self._field(grid, 1, 1, "地点", _combo("常青森林", "第1岛", "狩猎地带中央区"))
        self._field(grid, 1, 2, "宝可梦", _line("皮卡丘", "输入中文名、英文名或图鉴编号"))
        conditions.layout.addLayout(grid)
        left.addWidget(conditions)

        iv_card = Card("个体值筛选", "六项能力独立输入；预设会直接回填这些范围。")
        preset_row = QHBoxLayout()
        preset_row.addWidget(_label("Ten Lines 预设", name="fieldLabel"))
        for text in ("不限", "6V", "0A", "0S", "0A0S"):
            preset_row.addWidget(_button(text, "preset"))
        preset_row.addStretch(1)
        iv_card.layout.addLayout(preset_row)
        iv_grid = QGridLayout()
        iv_grid.setHorizontalSpacing(8)
        for column, stat in enumerate(("HP", "攻击", "防御", "特攻", "特防", "速度")):
            tile = QFrame()
            tile.setObjectName("ivTile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(8, 8, 8, 9)
            tile_layout.setSpacing(5)
            name = _label(stat, name="ivName")
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile_layout.addWidget(name)
            minimum = QSpinBox()
            minimum.setRange(0, 31)
            maximum = QSpinBox()
            maximum.setRange(0, 31)
            maximum.setValue(31)
            tile_layout.addWidget(minimum)
            tile_layout.addWidget(maximum)
            iv_grid.addWidget(tile, 0, column)
        iv_card.layout.addLayout(iv_grid)
        filters = QGridLayout()
        self._field(filters, 0, 0, "闪光", _combo("星形 / 方形", "不限", "不闪"))
        self._field(filters, 0, 1, "性格", _combo("不限", "爽朗", "固执", "胆小"))
        self._field(filters, 0, 2, "特性", _combo("不限", "静电"))
        self._field(filters, 0, 3, "性别", _combo("不限", "雄", "雌"))
        iv_card.layout.addLayout(filters)
        left.addWidget(iv_card)

        advanced = Card("搜索范围", "常用设置保持简洁，高级参数可以按需展开。")
        advance_grid = QGridLayout()
        self._field(advance_grid, 0, 0, "最小 Advance", _line("3000"))
        self._field(advance_grid, 0, 1, "最大 Advance", _line("100000"))
        self._field(advance_grid, 0, 2, "Seed 模式", _combo("自动选择", "模式 0", "模式 1"))
        advanced.layout.addLayout(advance_grid)
        checks = QHBoxLayout()
        for text in ("出闪后自动抓捕", "麻痹", "点到为止", "道具乱数"):
            checks.addWidget(QCheckBox(text))
        checks.addStretch(1)
        advanced.layout.addLayout(checks)
        left.addWidget(advanced)

        summary = Card("推荐方案", "按个体总和优先，再选择最小 Advance。")
        hero = QHBoxLayout()
        sprite = QLabel()
        pixmap = QPixmap(str(RESOURCE_ROOT / "assets" / "sprites" / "shiny" / "25.png"))
        if not pixmap.isNull():
            sprite.setPixmap(
                pixmap.scaled(
                    92,
                    92,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        sprite.setFixedSize(100, 100)
        sprite.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(sprite)
        hero_text = QVBoxLayout()
        hero_text.addWidget(_label("闪光皮卡丘", name="summaryName"))
        hero_text.addWidget(_label("常青森林 · 草丛 · LV 3", role="muted"))
        badge = _label("方案已就绪", name="successBadge")
        badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        hero_text.addWidget(badge)
        hero_text.addStretch(1)
        hero.addLayout(hero_text, 1)
        summary.layout.addLayout(hero)
        metrics = QHBoxLayout()
        for title, value in (("Seed", "75D1"), ("Advance", "8,021"), ("个体合计", "186")):
            metrics.addWidget(self._metric(title, value))
        summary.layout.addLayout(metrics)
        summary.layout.addWidget(_label("IV  31 / 31 / 31 / 31 / 31 / 31", name="chipValue"))
        summary.layout.addWidget(_label("爽朗 · 静电 · 雄 · 星形闪光", role="muted"))
        shadow = QGraphicsDropShadowEffect(summary)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(33, 45, 76, 28))
        summary.setGraphicsEffect(shadow)
        right.addWidget(summary)

        device = Card("运行准备", "设备状态集中展示，避免把关键错误藏在日志里。")
        device.layout.addWidget(self._status_line("单片机", "COM4", True))
        device.layout.addWidget(self._status_line("采集卡", "3 · Elgato HD60 S+", True))
        device.layout.addWidget(self._status_line("EasyCon", "1.6.4-a+9c86137", True))
        buttons = QHBoxLayout()
        buttons.addWidget(_button("重新检测", "ghost"))
        buttons.addWidget(_button("虚拟手柄", "ghost"))
        buttons.addWidget(_button("监视窗口", "ghost"))
        device.layout.addLayout(buttons)
        right.addWidget(device)
        right.addStretch(1)
        layout.addLayout(columns)
        return page

    def _build_sid_page(self) -> QWidget:
        page, layout = self._page_canvas()
        row = QHBoxLayout()
        row.setSpacing(16)
        identity = Card("SID 查找条件", "根据队伍中的闪光宝可梦逐步缩小 SID 候选。")
        grid = QGridLayout()
        self._field(grid, 0, 0, "当前 TID", _line("58888"))
        self._field(grid, 0, 1, "游戏版本", _combo("火红", "叶绿"))
        self._field(grid, 0, 2, "闪光数量", _combo("1", "2", "3", "4", "5", "6"))
        identity.layout.addLayout(grid)
        identity.layout.addWidget(QCheckBox("取得 SID 后继续御三家普通乱数并验证闪光"))
        row.addWidget(identity, 3)
        result = Card("候选结果", "示例展示；初版尚未调用 Method 1/2/4 反查。")
        result.layout.addWidget(_label("SID 候选  38449", name="summaryName"))
        result.layout.addWidget(_label("PSV 交集：4806 · 最早建档 ADV：1900", role="muted"))
        result.layout.addWidget(_label("1 个候选", name="successBadge"))
        row.addWidget(result, 2)
        layout.addLayout(row)

        party = Card("闪光宝可梦信息", "支持名字、初始等级、性别和六项努力值；不存在的列会随数量隐藏。")
        table = QTableWidget(3, 10)
        table.setHorizontalHeaderLabels(
            ("宝可梦", "来源", "初始等级", "性别", "HP", "攻击", "防御", "特攻", "特防", "速度")
        )
        samples = (
            ("大比鸟", "野生", "48", "雄", "0", "0", "0", "0", "0", "0"),
            ("暴鲤龙", "静态", "30", "雌", "0", "0", "0", "0", "0", "0"),
            ("", "野生", "", "不限", "0", "0", "0", "0", "0", "0"),
        )
        for r, values in enumerate(samples):
            for c, value in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(value))
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        table.setMinimumHeight(184)
        party.layout.addWidget(table)
        layout.addWidget(party)
        layout.addStretch(1)
        return page

    def _build_tid_page(self) -> QWidget:
        page, layout = self._page_canvas()
        columns = QHBoxLayout()
        columns.setSpacing(16)
        settings = Card("TID / SID 基本条件", "支持目标乱数或从断点继续穷举。")
        grid = QGridLayout()
        self._field(grid, 0, 0, "ROM 语言", _combo("英文", "日文"))
        self._field(grid, 0, 1, "运行模式", _combo("穷举模式", "乱数模式"))
        self._field(grid, 1, 0, "目标 TID", _line("00000"))
        self._field(grid, 1, 1, "目标 SID", _line("38449"))
        self._field(grid, 2, 0, "主角名称", _line("AXE"))
        self._field(grid, 2, 1, "主角性别", _combo("女", "男"))
        settings.layout.addLayout(grid)
        settings.layout.addWidget(QCheckBox("取得任意合法 TID 后直接继续御三家计划"))
        settings.layout.addWidget(QCheckBox("运行前自动检测固定延迟并回填"))
        columns.addWidget(settings, 3)

        timeline = Card("自动流程", "每个阶段的状态会保留在同一张计划卡中。")
        for number, title, detail, active in (
            ("01", "固定延迟检测", "自动更新 OP / F1 / F2 / F3", True),
            ("02", "TID / SID 建档", "支持穷举断点续跑", True),
            ("03", "前往御三家球前", "复用 2.0 自动脚本路线", False),
            ("04", "御三家闪光验证", "命中后保存并保留现场", False),
        ):
            line = QFrame()
            line_layout = QHBoxLayout(line)
            line_layout.setContentsMargins(4, 5, 4, 5)
            badge = _label(number, name="successBadge" if active else "metricLabel")
            badge.setFixedWidth(34)
            line_layout.addWidget(badge)
            text = QVBoxLayout()
            text.addWidget(_label(title, name="chipValue"))
            text.addWidget(_label(detail, role="muted"))
            line_layout.addLayout(text, 1)
            timeline.layout.addWidget(line)
        columns.addWidget(timeline, 2)
        layout.addLayout(columns)
        layout.addStretch(1)
        return page

    def _build_egg_page(self) -> QWidget:
        page, layout = self._page_canvas()
        row = QHBoxLayout()
        row.setSpacing(16)
        target = Card("孵蛋目标", "Ten Lines 的同 Seed、Held 和 Pickup 直接作为运行计划。")
        grid = QGridLayout()
        self._field(grid, 0, 0, "蛋种", _line("派拉斯", "中文名、英文名或图鉴编号"))
        self._field(grid, 0, 1, "Seed 模式", _combo("模式 0", "模式 1", "模式 2"))
        self._field(grid, 1, 0, "目标 Seed", _line("EDDE"))
        self._field(grid, 1, 1, "生成帧 Held", _line("1115"))
        self._field(grid, 2, 0, "领取帧 Pickup", _line("3405"))
        self._field(grid, 2, 1, "亲本相性", _combo("50", "70", "20"))
        target.layout.addLayout(grid)
        target.layout.addWidget(QCheckBox("从已完成 254 步准备开始"))
        row.addWidget(target, 3)
        status = Card("周期与校准", "根据蛋种自动计算骑车循环。")
        status.layout.addWidget(_label("孵化周期  20", name="summaryName"))
        status.layout.addWidget(_label("领取后步数 5,375 · 骑车循环 143", role="muted"))
        status.layout.addWidget(self._status_line("Seed 预校准", "等待执行", True))
        status.layout.addWidget(self._status_line("Held / Pickup", "1115 / 3405", True))
        row.addWidget(status, 2)
        layout.addLayout(row)

        parents = Card("亲本配置", "A / B 亲本分别设置性别和六项个体值。")
        table = QTableWidget(2, 8)
        table.setHorizontalHeaderLabels(("亲本", "性别", "HP", "攻击", "防御", "特攻", "特防", "速度"))
        values = (
            ("A", "雌", "31", "31", "31", "31", "31", "31"),
            ("B", "雄", "31", "31", "31", "31", "31", "31"),
        )
        for r, row_values in enumerate(values):
            for c, value in enumerate(row_values):
                table.setItem(r, c, QTableWidgetItem(value))
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(145)
        parents.layout.addWidget(table)
        config_buttons = QHBoxLayout()
        config_buttons.addWidget(_button("载入亲本配置"))
        config_buttons.addWidget(_button("保存亲本配置"))
        config_buttons.addWidget(_button("保存全部配置"))
        config_buttons.addStretch(1)
        parents.layout.addLayout(config_buttons)
        layout.addWidget(parents)
        layout.addStretch(1)
        return page

    def _build_logs_page(self) -> QWidget:
        page, layout = self._page_canvas()
        metrics = QHBoxLayout()
        for title, value in (("当前轮次", "06"), ("命中 Seed", "+1"), ("帧误差", "0"), ("运行时间", "18:42")):
            metrics.addWidget(self._metric(title, value))
        layout.addLayout(metrics)
        log_card = Card("实时运行日志", "彩色状态和关键校准值会在这里集中显示。")
        log = QPlainTextEdit()
        log.setObjectName("logView")
        log.setReadOnly(True)
        log.setPlainText(
            "[20:47:04.209] HOME_BUFFER 校准完成：1200 ms\n"
            "[20:47:35.812] 第 6 轮 Seed 等待：30735 ms\n"
            "[20:48:12.037] 目标 Seed：75D1  命中差：+1\n"
            "[20:48:12.038] 目标 Advance：8021  剩余：0\n"
            "[20:48:12.039] 二维共同区：Seed ±34 ms / ADV ±1\n"
            "[20:48:15.201] 正在进入目标遭遇流程……"
        )
        log_card.layout.addWidget(log)
        tools = QHBoxLayout()
        tools.addWidget(_button("复制日志"))
        tools.addWidget(_button("打开日志目录"))
        tools.addWidget(_button("清空显示"))
        tools.addStretch(1)
        log_card.layout.addLayout(tools)
        layout.addWidget(log_card, 1)
        return page

    @staticmethod
    def _metric(title: str, value: str) -> QFrame:
        tile = QFrame()
        tile.setObjectName("metricTile")
        tile.setMinimumHeight(68)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(11, 9, 11, 9)
        tile_layout.setSpacing(1)
        tile_layout.addWidget(_label(value, name="metricValue"))
        tile_layout.addWidget(_label(title, name="metricLabel"))
        return tile

    @staticmethod
    def _status_line(title: str, detail: str, ready: bool) -> QFrame:
        line = QFrame()
        row = QHBoxLayout(line)
        row.setContentsMargins(0, 4, 0, 4)
        dot = _label("●")
        dot.setStyleSheet(f"color: {'#22a785' if ready else '#d69b2d'}; font-size: 12px;")
        row.addWidget(dot)
        row.addWidget(_label(title, name="chipValue"))
        row.addStretch(1)
        row.addWidget(_label(detail, role="muted"))
        return line

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("footerBar")
        footer.setFixedHeight(70)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(26, 12, 26, 12)
        layout.addWidget(_label("●  当前配置完整，可以搜索方案", name="readyText"))
        layout.addStretch(1)
        layout.addWidget(_button("保存配置", "ghost"))
        self.search_button = _button("搜索并生成方案", "primary")
        layout.addWidget(self.search_button)
        layout.addWidget(_button("开始运行", "success"))
        return footer

    def select_page(self, key: str) -> None:
        if key not in self.page_indices:
            return
        self.stack.setCurrentIndex(self.page_indices[key])
        for name, button in self.nav_buttons.items():
            button.setChecked(name == key)
        title, description = next(
            (title, description)
            for name, title, description in NAV_ITEMS
            if name == key
        )
        self.page_title.setText(title)
        self.page_description.setText(description)
        self.search_button.setText(
            {
                "wild": "搜索并生成方案",
                "sid": "准备 SID 查找",
                "tid": "生成 TID 计划",
                "egg": "生成孵蛋脚本",
                "logs": "导出运行日志",
            }[key]
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=WINDOW_TITLE)
    parser.add_argument("--page", choices=[item[0] for item in NAV_ITEMS], default="wild")
    parser.add_argument("--screenshot", type=Path, help="Render the selected page to a PNG and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("FRLG Auto RNG PySide6 Preview")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    window = FrlgPreviewWindow()
    window.select_page(args.page)
    window.show()
    if args.screenshot:
        destination = args.screenshot.resolve()

        def capture() -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(destination), "PNG"):
                app.exit(2)
                return
            app.exit(0)

        QTimer.singleShot(350, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
