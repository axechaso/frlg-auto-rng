"""Standalone PySide6 visual prototype for the FRLG automation GUI.

This module deliberately does not import or replace the production Tk entry.
It is an interaction and layout prototype used to settle the visual direction
before the existing planner and runner services are wired into Qt widgets.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_version import APP_VERSION
from assets.game_text import (
    CATEGORY_EN_TO_ZH, WILD_CATEGORIES, FILTER_SHINY_ZH_TO_EN,
    FILTER_NATURE_ZH_TO_EN, FILTER_GENDER_ZH_TO_EN, FILTER_TYPE_ZH_TO_EN,
)


WINDOW_TITLE = "火红 / 叶绿全自动乱数 · PySide6 界面初版"
NAV_ITEMS = (
    ("sid", "SID 查找", "闪光个体反查 SID"),
    ("tid", "TID 乱数", "建档与御三家计划"),
    ("tid_records", "TID 实测表", "实际观测与参数记录"),
    ("wild", "野生 / 静态", "目标筛选与方案搜索"),
    ("egg", "孵蛋", "同 Seed 生成与领取"),
    ("script_test", "脚本测试（高级）", "原地 ECS 预检与后端对照"),
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

APP_STYLE += r"""
QPushButton:disabled, QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled {
    color: #8792a5; background: #edf0f5; border-color: #dfe5ee;
}
QLabel[role="warning"] { color: #9a541b; }
QToolTip { color: #172033; background: #ffffff; border: 1px solid #c9d1df; }
QPushButton#profileChip, QPushButton#deviceChip {
    background: white; border: 1px solid #e1e7f0; border-radius: 11px;
}
QPushButton#profileChip:hover, QPushButton#deviceChip:hover { border-color: #aebaff; }
QPushButton[kind="section"] {
    border: none; background: transparent; text-align: left;
    color: #172033; font-size: 15px; font-weight: 750; padding: 0;
}
QPushButton[kind="primary"]:disabled { background: #b0b6ed; color: white; }
QPushButton[kind="success"]:disabled { background: #8dc9b9; color: white; }
QLabel#emptySymbol { color: #8595d6; background: #eff2ff; border-radius: 24px; font-size: 42px; }
QLabel#pendingBadge { color: #6675ad; background: #eef1ff; border-radius: 9px; padding: 5px 10px; }
QLabel#readyText { color: #718096; }
QSpinBox::up-button, QSpinBox::down-button { width: 15px; border: none; }
QMenu { background: white; border: 1px solid #dce2ef; padding: 6px; }
QMenu::item { padding: 8px 16px; }
QMenu::item:disabled { color: #8792a5; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #f6f8fc; color: #718096; padding: 9px 14px; margin-right: 6px; border-radius: 8px; }
QTabBar::tab:selected { background: #e9edff; color: #4f62d9; font-weight: 700; }
QTabBar::tab:disabled { color: #aab3c3; }
"""

STATS = ("HP", "攻击", "防御", "特攻", "特防", "速度")
NOT_CONNECTED = "界面预览：此操作尚未接入后端。"
# Display-only labels from automation/seed_modes.py at 7438e0e. Importing
# automation would load planner/native dependencies into this isolated preview.
SEED_MODE_LABELS = (
    "0: mono_h_a_none", "1: stereo_h_a_none", "2: mono_h_start_none",
    "3: stereo_h_start_none", "4: mono_h_a_blackout_r", "5: mono_h_a_blackout_l",
    "6: stereo_h_a_blackout_r", "7: stereo_h_a_blackout_l",
    "8: mono_h_start_blackout_r", "9: mono_h_start_blackout_l",
)


def _label(text: str, *, role: str | None = None, name: str | None = None) -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(True)
    if role:
        widget.setProperty("role", role)
    if name:
        widget.setObjectName(name)
    return widget


def _button(text: str, kind: str = "ghost", *, enabled: bool = False) -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setProperty("kind", kind)
    widget.setEnabled(enabled)
    if not enabled:
        widget.setToolTip(NOT_CONNECTED)
        widget.setProperty("backendAction", True)
    return widget


def _combo(*items: str, current: int = 0) -> QComboBox:
    widget = QComboBox()
    widget.addItems(items)
    widget.setCurrentIndex(current)
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    widget.setMinimumContentsLength(4)
    return widget


def _line(text: str = "", placeholder: str = "") -> QLineEdit:
    widget = QLineEdit(text)
    widget.setPlaceholderText(placeholder)
    widget.setMinimumWidth(0)
    return widget


class Card(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None, *, collapsible: bool = False):
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 17, 18, 18)
        outer.setSpacing(13)
        heading = QVBoxLayout()
        heading.setSpacing(3)
        if collapsible:
            self.toggle = _button(f"›  {title}", "section", enabled=True)
            self.toggle.setCheckable(True)
            self.toggle.setToolTip(subtitle)
            heading.addWidget(self.toggle)
        else:
            heading.addWidget(_label(title, name="cardTitle"))
        if subtitle and not collapsible:
            heading.addWidget(_label(subtitle, name="cardSubtitle"))
        outer.addLayout(heading)
        self.content = QWidget()
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(13)
        outer.addWidget(self.content)
        if collapsible:
            self.content.hide()
            self.toggle.toggled.connect(self.content.setVisible)
            self.toggle.toggled.connect(lambda expanded: self.toggle.setText(f"{'⌄' if expanded else '›'}  {title}"))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)


class FrlgPreviewWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(900, 620)
        self.resize(1360, 860)
        self.setStyleSheet(APP_STYLE)
        self.nav_buttons: dict[str, QPushButton] = {}
        self.page_indices: dict[str, int] = {}
        self.fields: dict[str, QWidget] = {}
        self.input_mode = "sid"

        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())
        outer.addWidget(self._build_workspace(), 1)
        self.settings_dialog = self._build_common_settings()
        self.select_page("sid")

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(208)
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
                "tid_records": "▦",
                "egg": "○",
                "script_test": "◇",
                "logs": "▤",
            }[key]
            button = QPushButton(f"  {prefix}    {title}")
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, page=key: self.select_page(page))
            self.nav_buttons[key] = button
            layout.addWidget(button)
            if key == "script_test":
                button.hide()

        layout.addStretch(1)
        status = QFrame()
        status.setObjectName("sideStatus")
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(13, 12, 13, 13)
        status_layout.setSpacing(5)
        status_layout.addWidget(_label("●  EasyCon 1.6.4-a", name="sideStatusTitle"))
        status_layout.addWidget(_label("运行时要求 · 尚未检测", name="sideStatusText"))
        status_layout.addWidget(_label("设备与运行服务尚未接入", name="sideStatusText"))
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
        self.profile_chip = self._chip("存档信息", "未选择 · 手动输入", "profileChip")
        self.profile_chip.clicked.connect(lambda: self.profile_dialog.show())
        top.addWidget(self.profile_chip)
        top.addSpacing(8)
        self.device_chip = self._chip("当前设备", "尚未检测", "deviceChip")
        self.device_chip.clicked.connect(lambda: self.settings_dialog.show())
        top.addWidget(self.device_chip)
        header_layout.addLayout(top)

        banner = QFrame()
        banner.setObjectName("previewBanner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(12, 7, 12, 7)
        banner_layout.addWidget(_label("界面预览", name="previewBannerTitle"))
        banner_layout.addWidget(
            _label("仅预览布局，搜索、设备与运行服务尚未接入。", role="muted"), 1
        )
        self.advanced_check = QCheckBox("高级模式")
        self.advanced_check.setToolTip("显示脚本测试、Seed、扩窗与奇偶设置。正式版仅放宽指纹不一致，缺文件、语法和参数错误仍阻止运行；本预览不执行检查。")
        self.advanced_check.toggled.connect(self._toggle_advanced)
        banner_layout.addWidget(self.advanced_check)
        settings = _button("共通设置", enabled=True)
        settings.clicked.connect(lambda: self.settings_dialog.show())
        banner_layout.addWidget(settings)
        header_layout.addWidget(banner)
        layout.addWidget(header)

        self.stack = QStackedWidget()
        self._add_page("wild", self._build_wild_page())
        self._add_page("sid", self._build_sid_page())
        self._add_page("tid", self._build_tid_page())
        self._add_page("egg", self._build_egg_page())
        self._add_page("logs", self._build_logs_page())
        self._add_page("tid_records", self._build_tid_records_page())
        self._add_page("script_test", self._build_script_test_page())
        body = QWidget()
        self.body_layout = QHBoxLayout(body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        self.body_layout.addWidget(self.stack, 7)
        self.overview = self._build_overview()
        self.overview_scroll = QScrollArea()
        self.overview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.overview_scroll.setWidgetResizable(True)
        self.overview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.overview_scroll.setWidget(self.overview)
        self.body_layout.addWidget(self.overview_scroll, 4)
        layout.addWidget(body, 1)
        self.result_dialog = QDialog(self)
        self.result_dialog.setWindowTitle("方案与预检详情")
        self.result_dialog.resize(700, 480)
        result_layout = QVBoxLayout(self.result_dialog)
        self.result_panel = QPlainTextEdit()
        self.result_panel.setReadOnly(True)
        self.result_panel.setPlainText("方案与预检结果\n尚未接入方案生成或预检服务。此处没有可运行的计划。")
        result_layout.addWidget(self.result_panel)
        layout.addWidget(self._build_footer())
        return workspace

    @staticmethod
    def _chip(title: str, value: str, object_name: str) -> QPushButton:
        chip = QPushButton()
        chip.setObjectName(object_name)
        chip.setFixedWidth(178)
        chip.setFixedHeight(50)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setAccessibleName(f"{title}：{value}，点击查看设置")
        chip_layout = QVBoxLayout(chip)
        chip_layout.setContentsMargins(12, 7, 12, 7)
        chip_layout.setSpacing(0)
        chip_layout.addWidget(_label(title, name="chipTitle"))
        chip_layout.addWidget(_label(value, name="chipValue"))
        for label in chip.findChildren(QLabel):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return chip

    def _build_overview(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 20, 24)
        layout.setSpacing(16)
        summary = Card("推荐方案", "生成后在这里查看目标与关键参数。")
        self.summary_title = summary.findChild(QLabel, "cardTitle")
        hero = QHBoxLayout()
        hero.setSpacing(16)
        symbol = _label("◎", name="emptySymbol")
        symbol.setFixedSize(86, 86)
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(symbol)
        words = QVBoxLayout()
        self.summary_name = _label("暂无方案", name="summaryName")
        words.addWidget(self.summary_name)
        words.addWidget(_label("完成左侧条件后生成", role="muted"))
        badge = _label("生成服务待接入", name="pendingBadge")
        badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        words.addWidget(badge)
        hero.addLayout(words, 1)
        summary.layout.addLayout(hero)
        metrics = QHBoxLayout()
        self.metric_labels = []
        for title in ("Seed", "Advance", "个体合计"):
            tile = QFrame()
            tile.setObjectName("metricTile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(11, 10, 11, 10)
            tile_layout.addWidget(_label("—", name="metricValue"))
            label = _label(title, name="metricLabel")
            self.metric_labels.append(label)
            tile_layout.addWidget(label)
            metrics.addWidget(tile, 1)
        summary.layout.addLayout(metrics)
        self.summary_note = _label("尚无可运行的计划。", role="muted")
        summary.layout.addWidget(self.summary_note)
        details = _button("查看方案与预检详情", enabled=True)
        details.clicked.connect(lambda: self.result_dialog.show())
        summary.layout.addWidget(details)
        shadow = QGraphicsDropShadowEffect(summary)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(33, 45, 76, 24))
        summary.setGraphicsEffect(shadow)
        layout.addWidget(summary)

        ready = Card("运行准备", "运行前需要确认以下三项。")
        for title, detail in (("单片机", "尚未检测"), ("采集卡", "尚未检测"), ("EasyCon", "尚未校验")):
            row = QHBoxLayout()
            dot = _label("●")
            dot.setStyleSheet("color: #b6c0cf; font-size: 11px;")
            row.addWidget(dot)
            row.addWidget(_label(title, name="chipValue"))
            row.addStretch(1)
            row.addWidget(_label(detail, role="muted"))
            ready.layout.addLayout(row)
        buttons = QHBoxLayout()
        for title in ("重新检测", "虚拟手柄", "监视窗口"):
            button = _button(title)
            button.setStyleSheet("padding-left: 7px; padding-right: 7px;")
            buttons.addWidget(button)
        ready.layout.addLayout(buttons)
        layout.addWidget(ready)
        layout.addStretch(1)
        return panel

    def _refresh_overview(self) -> None:
        titles = {
            "wild": ("推荐方案", "暂无方案", ("Seed", "Advance", "个体合计")),
            "sid": ("候选结果", "等待查找", ("PSV 交集", "SID 候选", "最早建档 ADV")),
            "tid": ("建档计划", "暂无计划", ("目标 TID", "采用 SID", "御三家 ADV")),
            "egg": ("孵蛋计划", "暂无计划", ("Seed", "Held", "Pickup")),
            "script_test": ("预检结果", "等待预检", ("脚本入口", "运行时", "预检状态")),
        }
        title, name, metrics = titles[self.input_mode]
        self.summary_title.setText(title)
        self.summary_name.setText(name)
        for label, text in zip(self.metric_labels, metrics):
            label.setText(text)
        self._adapt_workspace()

    def _adapt_workspace(self) -> None:
        if not hasattr(self, "overview_scroll") or not hasattr(self, "overview_button"):
            return
        wide = self.width() >= 1180 and getattr(self, "current_page", "sid") != "tid_records"
        self.overview_scroll.setVisible(wide)
        self.overview_button.setVisible(not wide)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._adapt_workspace()

    def _show_overview(self) -> None:
        # On narrow screens the same overview is shown in a dialog. Its widgets
        # are temporarily reparented, so there is only one summary/state view.
        dialog = QDialog(self)
        dialog.setWindowTitle("方案与运行准备")
        dialog.resize(440, 650)
        layout = QVBoxLayout(dialog)
        overview = self.overview_scroll.takeWidget()
        layout.addWidget(overview)
        dialog.exec()
        layout.removeWidget(overview)
        self.overview_scroll.setWidget(overview)

    def _add_page(self, key: str, page: QWidget) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(page)
        self.page_indices[key] = self.stack.addWidget(scroll)

    @staticmethod
    def _page_canvas() -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 8, 20, 24)
        layout.setSpacing(16)
        return page, layout

    @staticmethod
    def _field(grid: QGridLayout, row: int, column: int, title: str, widget: QWidget) -> None:
        box = QVBoxLayout()
        box.setSpacing(5)
        box.addWidget(_label(title, name="fieldLabel"))
        box.addWidget(widget)
        grid.addLayout(box, row, column)
        grid.setColumnStretch(column, 1)
        widget.setAccessibleName(title)

    def _form(self, card: Card, entries: list[tuple[str, str, QWidget]], columns: int = 3) -> None:
        grid = QGridLayout()
        grid.setSpacing(12)
        for column in range(columns):
            grid.setColumnStretch(column, 1)
        for i, (key, title, widget) in enumerate(entries):
            widget.setObjectName(key)
            self.fields[key] = widget
            self._field(grid, i // columns, i % columns, title, widget)
        card.layout.addLayout(grid)

    @staticmethod
    def _spin(value: int, minimum: int = 0, maximum: int = 999999999) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setMinimumWidth(0)
        spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        return spin

    @staticmethod
    def _check(text: str, checked: bool = False) -> QCheckBox:
        check = QCheckBox(text)
        check.setChecked(checked)
        return check

    @staticmethod
    def _actions(card: Card, *titles: str, columns: int = 3) -> None:
        grid = QGridLayout()
        for i, title in enumerate(titles):
            button = _button(title)
            button.setMaximumWidth(240)
            grid.addWidget(button, i // columns, i % columns)
        grid.setColumnStretch(columns, 1)
        card.layout.addLayout(grid)

    def _path_card(self, title: str, field_title: str, key: str) -> Card:
        card = Card(title, "路径选择与校验尚未接入。", collapsible=True)
        self._form(card, [(key, field_title, _line(placeholder="待接入路径选择与校验"))], 1)
        self._actions(card, "选择")
        return card

    @staticmethod
    def _table(headers: tuple[str, ...], rows: int = 0, height: int = 250) -> QTableWidget:
        table = QTableWidget(rows, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        table.setMinimumWidth(0)
        table.setMinimumHeight(height)
        table.horizontalHeader().setStretchLastSection(True)
        table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        return table

    def _build_wild_page(self) -> QWidget:
        page, layout = self._page_canvas()
        conditions = Card("乱数条件", "先选择游戏、遭遇方式和目标，再细化筛选范围。")
        self._form(conditions, [
            ("wild_game", "游戏版本", _combo("火红", "叶绿")),
            ("wild_method", "目标类型", _combo("野生", "静态")),
            ("wild_nx", "主机", _combo("Switch 1", "Switch 2")),
            ("wild_category", "遭遇方式", _combo()),
            ("wild_location", "地点", _combo("待载入地点")),
            ("wild_species", "宝可梦", _combo("待载入目标")),
        ])
        self.profile_dialog = QDialog(self)
        self.profile_dialog.setWindowTitle("存档信息")
        self.profile_dialog.resize(460, 340)
        profile_layout = QVBoxLayout(self.profile_dialog)
        profile = Card("存档信息", "存档服务尚未接入，以下仅为本次窗口内的手动输入。")
        selector = _combo("未选择（手动输入）")
        selector.setEnabled(False)
        profile.layout.addWidget(selector)
        self._form(profile, [
            ("wild_tid", "当前 TID", _line("58888")),
            ("wild_sid", "当前 SID", _line("12232")),
        ], 2)
        profile.layout.addWidget(_label("TID / SID 用于野生、静态与孵蛋；SID 查找和新建 TID 条件在各自页面填写。", role="muted"))
        self._actions(profile, "管理存档")
        profile_layout.addWidget(profile)
        close = _button("完成", enabled=True)
        close.clicked.connect(self.profile_dialog.hide)
        profile_layout.addWidget(close)
        self.fields["wild_location"].setEnabled(False)
        self.fields["wild_species"].setEnabled(False)
        layout.addWidget(conditions)

        iv = Card("个体值筛选", "上方为最低值，下方为最高值；点击能力名称可重置单项。")
        presets = QHBoxLayout()
        presets.addWidget(_label("Ten Lines 预设", name="fieldLabel"))
        for name in ("不限", "6V", "0A", "0S", "0A0S"):
            button = _button(name, "preset", enabled=True)
            button.clicked.connect(lambda _checked=False, preset=name: self._apply_iv_preset(preset))
            presets.addWidget(button)
        presets.addStretch(1)
        iv.layout.addLayout(presets)
        grid = QGridLayout()
        self.iv_ranges = []
        grid.setSpacing(8)
        for c, stat in enumerate(STATS):
            tile = QFrame()
            tile.setObjectName("ivTile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(7, 8, 7, 9)
            tile_layout.setSpacing(6)
            reset = _button(stat, "section", enabled=True)
            reset.setAccessibleName(f"重置 {stat} IV 为 0–31")
            reset.setToolTip("重置为 0–31")
            reset.setStyleSheet("font-size: 11px; text-align: center; color: #59677f;")
            reset.setMinimumWidth(0)
            reset.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            reset.clicked.connect(lambda _checked=False, index=c: self._reset_iv(index))
            tile_layout.addWidget(reset)
            minimum, maximum = self._spin(0, 0, 31), self._spin(31, 0, 31)
            minimum.setAccessibleName(f"{stat} 最低 IV")
            maximum.setAccessibleName(f"{stat} 最高 IV")
            self.iv_ranges.append((minimum, maximum))
            for spin in (minimum, maximum):
                spin.setStyleSheet("padding-left: 6px; padding-right: 1px;")
                tile_layout.addWidget(spin)
            grid.addWidget(tile, 0, c)
            grid.setColumnStretch(c, 1)
        iv.layout.addLayout(grid)
        self._form(iv, [
            ("wild_shiny", "闪光", _combo("不限", *[s for s in FILTER_SHINY_ZH_TO_EN if s != "不限"], current=1)),
            ("wild_nature", "性格", _combo("不限", *[s for s in FILTER_NATURE_ZH_TO_EN if s != "不限"])),
            ("wild_ability", "特性", _combo("不限（待载入）")),
            ("wild_gender", "性别", _combo(*FILTER_GENDER_ZH_TO_EN)),
        ], 4)
        self.fields["wild_ability"].setEnabled(False)
        layout.addWidget(iv)

        filters = Card("搜索范围", "选择搜索范围，或直接使用已有的 Seed 和帧数。")
        self._form(filters, [
            ("wild_search_mode", "运行模式", _combo("筛选搜索", "指定 Seed/帧数")),
            ("wild_min", "最小 Advance", _line("3000")),
            ("wild_max", "最大 Advance", _line("100000")),
            ("wild_seed_mode", "Seed 模式", _combo("自动选择", *SEED_MODE_LABELS)),
            ("wild_direct_seed", "指定初始 Seed", _line("0000")),
            ("wild_direct_adv", "指定消耗帧", _line("3000")),
        ])
        layout.addWidget(filters)

        capture = Card("更多筛选与出闪后处理", "觉醒力量、抓捕、道具与 SID 遍历。", collapsible=True)
        self._form(capture, [("wild_hidden", "觉醒力量", _combo("不限", *[s for s in FILTER_TYPE_ZH_TO_EN if s != "不限"]))], 2)
        self.capture_checks = [self._check(title) for title in ("出闪后自动抓捕", "麻痹", "点到为止")]
        row = QHBoxLayout()
        for check in self.capture_checks:
            row.addWidget(check)
        row.addStretch(1)
        capture.layout.addLayout(row)
        self.item_check = self._check("道具乱数模式")
        self.traversal_check = self._check("SID 遍历模式")
        capture.layout.addWidget(self.item_check)
        self._form(capture, [("wild_slots", "队伍空位", self._spin(1, 1, 5))])
        capture.layout.addWidget(self.traversal_check)
        self._form(capture, [
            ("wild_traversal_max", "遍历上限（ADV）", self._spin(10000, 0, 65535)),
            ("wild_traversal_start", "高级起点（ADV）", _line(placeholder="留空沿用路线默认起点")),
        ], 2)
        self.fields["wild_traversal_start"].setToolTip("生成时确认劲敌取名。未取名从奇数 1901、取名从偶数 1900 开始，每次 +2；自定义起点必须同奇偶并使用独立断点。")
        capture.layout.addWidget(_label("断点读取尚未接入；此处未检查本机 SID 遍历进度。", role="muted"))
        layout.addWidget(capture)
        self.fields["wild_method"].currentIndexChanged.connect(self._refresh_wild_type)
        self.fields["wild_search_mode"].currentIndexChanged.connect(self._refresh_wild_controls)
        self.item_check.toggled.connect(self._refresh_wild_controls)
        self.traversal_check.toggled.connect(self._refresh_wild_controls)
        self._refresh_wild_type()
        layout.addStretch(1)
        return page

    def _reset_iv(self, index: int) -> None:
        self.iv_ranges[index][0].setValue(0)
        self.iv_ranges[index][1].setValue(31)

    def _apply_iv_preset(self, preset: str) -> None:
        for index, (minimum, maximum) in enumerate(self.iv_ranges):
            value = 0 if (index == 1 and preset in {"0A", "0A0S"}) or (index == 5 and preset in {"0S", "0A0S"}) else 31
            minimum.setValue(0 if preset == "不限" else value)
            maximum.setValue(31 if preset == "不限" else value)

    def _refresh_wild_type(self) -> None:
        wild = self.fields["wild_method"].currentIndex() == 0
        categories = WILD_CATEGORIES if wild else ("Starter", "Fossil", "Gift", "GameCorner", "Stationary", "Legend", "Event")
        combo = self.fields["wild_category"]
        combo.clear()
        combo.addItems([CATEGORY_EN_TO_ZH.get(name, name) for name in categories])
        self._refresh_wild_controls()

    def _refresh_wild_controls(self) -> None:
        wild = self.fields["wild_method"].currentIndex() == 0
        if not wild:
            self.item_check.setChecked(False)
            self.traversal_check.setChecked(False)
        if self.item_check.isChecked() and self.traversal_check.isChecked():
            self.item_check.setChecked(False)
        item, traversal = self.item_check.isChecked(), self.traversal_check.isChecked()
        self.item_check.setEnabled(wild)
        self.traversal_check.setEnabled(wild and not item)
        self.fields["wild_slots"].setEnabled(wild and item)
        self.fields["wild_traversal_max"].setEnabled(wild and traversal)
        self.fields["wild_traversal_start"].setEnabled(wild and traversal and self.advanced_check.isChecked())
        direct = self.fields["wild_search_mode"].currentIndex() == 1
        self.fields["wild_direct_seed"].setEnabled(direct)
        self.fields["wild_direct_adv"].setEnabled(direct)

    def _build_sid_page(self) -> QWidget:
        page, layout = self._page_canvas()
        identity = Card("SID 查找条件", "根据队伍中的闪光宝可梦逐步缩小 SID 候选。")
        self._form(identity, [
            ("sid_game", "游戏", _combo("火红", "叶绿")),
            ("sid_nx", "主机", _combo("Switch 1", "Switch 2")),
            ("sid_tid", "当前 TID", _line("12345")),
            ("sid_count", "队内闪光数量", self._spin(2, 1, 6)),
            ("sid_candies", "每只最多糖果", self._spin(5, 0, 99)),
            ("sid_threshold", "识图阈值", self._spin(85, 0, 100)),
        ])
        self.sid_ack = QCheckBox("已核对队伍资料与糖果位置")
        self.sid_ack.setToolTip("确认队伍顺序、宝可梦、初始等级、来源和六项努力值均准确，神奇糖果位于背包第一页第一格。")
        identity.layout.addWidget(self.sid_ack)
        layout.addWidget(identity)

        party = Card("队伍闪光宝可梦", "按队伍顺序逐只填写。下方六项为努力值 EV。")
        self.sid_party = QTabWidget()
        self.sid_party_widgets = []
        for r in range(6):
            slot = QWidget()
            slot_layout = QVBoxLayout(slot)
            slot_layout.setContentsMargins(0, 14, 0, 0)
            slot_layout.setSpacing(12)
            grid = QGridLayout()
            grid.setSpacing(12)
            widgets = [_line(placeholder="名称 / 编号"), _line(placeholder="1–100"), _combo("定点", "野生"), _line(placeholder="野生来源必填")]
            widgets.extend(self._spin(0, 0, 255) for _ in STATS)
            for c, (title, widget) in enumerate(zip(("宝可梦", "初始等级", "来源", "Ten Lines 相遇地点"), widgets[:4])):
                self._field(grid, c // 2, c % 2, title, widget)
                widget.setAccessibleName(f"槽位 {r + 1} {title}")
            slot_layout.addLayout(grid)
            evs = QGridLayout()
            evs.setSpacing(8)
            for c, (stat, widget) in enumerate(zip(STATS, widgets[4:])):
                self._field(evs, 0, c, stat, widget)
                widget.setAccessibleName(f"槽位 {r + 1} {stat} EV")
            slot_layout.addLayout(evs)
            self.sid_party.addTab(slot, f"第 {r + 1} 只")
            self.sid_party_widgets.append(widgets)
        self.fields["sid_count"].valueChanged.connect(self._refresh_sid_rows)
        self._refresh_sid_rows()
        party.layout.addWidget(self.sid_party)
        party.layout.addWidget(_label("仅支持定点与野生来源；不支持孵蛋来源。", role="muted"))
        layout.addWidget(party)
        layout.addWidget(self._path_card("SID 查找脚本", "2.0 自动乱数脚本包（SID 独立路径）", "sid_source"))
        layout.addStretch(1)
        return page

    def _refresh_sid_rows(self) -> None:
        count = self.fields["sid_count"].value()
        for i, widgets in enumerate(self.sid_party_widgets):
            self.sid_party.setTabEnabled(i, i < count)
            for widget in widgets:
                widget.setEnabled(i < count)
        if self.sid_party.currentIndex() >= count:
            self.sid_party.setCurrentIndex(count - 1)

    def _build_tid_records_page(self) -> QWidget:
        page, layout = self._page_canvas()
        filters = Card("TID 实测表", "只记录实际 TID；不同游戏、机型和参数分别统计，不记录 SID、SID ADV 或 F3。")
        self._form(filters, [
            ("record_game", "游戏", _combo("全部", "火红", "叶绿")),
            ("record_nx", "机型", _combo("全部", "Switch 1", "Switch 2")),
            ("record_tid", "TID", _line(placeholder="留空查询全部")),
        ])
        self._actions(filters, "查询 / 刷新", "导出 CSV")
        self.records_table = self._table(("TID", "游戏", "机型", "语言", "OP", "F1", "F2", "出现次数", "主角名称", "OP 修正（ms）", "最近记录时间"), height=280)
        self.records_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for column, width in enumerate((90, 65, 85, 60, 65, 65, 65, 75, 90, 105, 160)):
            self.records_table.setColumnWidth(column, width)
        filters.layout.addWidget(self.records_table)
        filters.layout.addWidget(_label("数据库尚未接入，未读取本机记录。正式界面最多显示 1000 项，CSV 导出包含全部筛选结果。", role="muted"))
        layout.addWidget(filters)
        details = Card("记录详情", "选择记录后查看固定延迟、OP 机型补偿、SELECT、HOME_BUFFER 和主角/游戏设置。")
        details.layout.addWidget(_label("尚未接入记录详情。出现次数表示完整观测次数，不保证再次命中。", role="muted"))
        layout.addWidget(details)
        layout.addStretch(1)
        return page

    def _build_script_test_page(self) -> QWidget:
        page, layout = self._page_canvas()
        script = Card("直接运行 ECS 测试脚本", "所选脚本原地执行；兼容运行器与原始 CLI 用于同脚本 A/B 对照。")
        entry = _button("在共通设置中选择脚本入口", enabled=True)
        entry.clicked.connect(lambda: self.settings_dialog.show())
        script.layout.addWidget(entry)
        self._form(script, [
            ("script_path", "ECS 文件", _line(placeholder="路径解析与文件选择尚未接入")),
            ("script_backend", "运行后端", _combo("工具兼容运行器（正式工具）", "原始 EasyCon 1.6.4-a CLI（A/B 对照）")),
        ], 1)
        self._actions(script, "选择脚本")
        script.layout.addWidget(QCheckBox("输出 EasyCon 详细日志"))
        script.layout.addWidget(_label("运行前必须核对脚本内容、游戏位置和存档状态。测试脚本拥有完整手柄控制权限。", role="warning"))
        script.layout.addWidget(_label("入口未解析；预检与运行服务尚未接入。", role="muted"))
        layout.addWidget(script)
        layout.addStretch(1)
        return page

    def _build_common_settings(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("共通设置 · PySide6 界面预览")
        dialog.resize(850, 700)
        dialog.setMinimumSize(650, 480)
        body = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page, layout = self._page_canvas()
        runtime = Card("EasyCon 1.6.4-a 与设备", "所有页面共用；设备、文件及更新服务尚未接入。")
        self._form(runtime, [
            ("source", "2.0 自动乱数脚本包", _line(placeholder="路径选择尚未接入")),
            ("ezcon", "ezcon.exe", _line(placeholder="要求 1.6.4-a+9c86137")),
            ("port", "串口", _combo("尚未检测")),
            ("video", "采集卡", _combo("尚未检测（编号与名称）")),
        ], 2)
        self.fields["port"].setEnabled(False)
        self.fields["video"].setEnabled(False)
        self._actions(runtime, "选择脚本包", "选择 ezcon.exe", "检测端口/采集卡", "虚拟手柄", "监视窗口", "检查/更新 Seed 表", "检查程序更新")
        runtime.layout.addWidget(_label("源码模式不使用程序自更新。", role="muted"))
        layout.addWidget(runtime)
        options = Card("生成脚本设置", "表单交互仅保存在本窗口内，不会写入配置或 ECS。")
        self.home_buffer_check = QCheckBox("HOME_BUFFER 稳定低分自适应")
        self.home_buffer_check.setToolTip("正式版作用于 2.0、TID 和 SID，默认关闭；只接受连续稳定的唯一最高分，不影响其他 OCR。")
        options.layout.addWidget(self.home_buffer_check)
        self.precalibration_check = QCheckBox("命中后更新预校准")
        self.precalibration_check.setToolTip("正式版仅在完整命中后保存，按游戏/主机/Seed 模式/启动/模板/流程隔离；TID、SID 阶段不参与。")
        options.layout.addWidget(self.precalibration_check)
        self._form(options, [
            ("output_log", "脚本输出日志", _combo("精简日志", "完整调试日志", current=1)),
            ("seed_calibration", "Seed 校准", _combo("方案 0：原始 12 轮绝对落点众数", "方案 1：实验锁定与毫秒细调")),
            ("seed_startup", "Seed 启动", _combo("方案 0：当前 HOME_BUFFER", "方案 1：固定用户界面 HOME")),
        ], 1)
        self.fields["output_log"].setToolTip("控制生成的 2.0 脚本（普通、孵蛋、御三家阶段）；不等同直接脚本页的 EasyCon 详细日志。")
        layout.addWidget(options)
        self.entry_options = Card("脚本入口", "高级模式下选择正式版或时间轴版；自选 ECS 仅用于脚本测试页。")
        self._form(self.entry_options, [
            ("script_entry", "2.0 脚本入口", _combo("正式版脚本", "时间轴版脚本")),
        ], 1)
        layout.addWidget(self.entry_options)
        self.advanced_options = Card("高级反查设置", "每层是相对目标中心的绝对半宽，扩大窗口会增加耗时；0 层关闭。孵蛋固定菜单奇偶。")
        self._form(self.advanced_options, [
            ("parity", "奇偶调整", _combo("方案 1：菜单调整", "方案 0：F1 +1 / F2 -1")),
            ("layers", "扩窗层数", self._spin(3, 0, 3)),
        ], 2)
        self._form(self.advanced_options, [
            (f"expansion_{i}_{axis}", f"第 {i} 层 · {title}（±）", _line(placeholder="模板默认值待接入"))
            for i in range(1, 4) for axis, title in (("seed", "Seed 容差"), ("adv", "消耗帧半宽"))
        ], 2)
        layout.addWidget(self.advanced_options)
        layout.addStretch(1)
        scroll.setWidget(page)
        body.addWidget(scroll)
        close = _button("完成", enabled=True)
        close.clicked.connect(dialog.hide)
        body.addWidget(close)
        return dialog

    def _toggle_advanced(self, enabled: bool) -> None:
        self.nav_buttons["script_test"].setVisible(enabled)
        if not enabled and self.input_mode == "script_test":
            self.select_page("wild")
        if hasattr(self, "settings_dialog"):
            self._refresh_common_settings()
            self._refresh_wild_controls()

    def _refresh_common_settings(self) -> None:
        advanced = self.advanced_check.isChecked()
        egg = self.input_mode == "egg"
        calibration = self.fields["seed_calibration"]
        choices = ["方案 0：原始 12 轮绝对落点众数", "方案 1：实验锁定与毫秒细调"]
        if egg:
            choices.append("方案 2：命中保持后的方向票接续（仅孵蛋）")
        if calibration.count() != len(choices):
            previous = calibration.currentText()
            calibration.clear()
            calibration.addItems(choices)
            calibration.setCurrentText(previous if previous in choices else choices[0])
        calibration.setEnabled(advanced)
        self.fields["seed_startup"].setEnabled(advanced)
        if not advanced:
            calibration.setCurrentIndex(2 if egg else 0)
            self.fields["seed_startup"].setCurrentIndex(0)
            self.fields["script_entry"].setCurrentIndex(0)
        entries = ["正式版脚本", "时间轴版脚本"]
        if self.input_mode == "script_test":
            entries.append("自选 ECS")
        combo = self.fields["script_entry"]
        if combo.count() != len(entries):
            selected = combo.currentText()
            combo.clear()
            combo.addItems(entries)
            combo.setCurrentText(selected if selected in entries else entries[0])
        self.entry_options.setVisible(advanced)
        applies = self.input_mode in {"wild", "egg"} or (self.input_mode == "tid" and hasattr(self, "tid_flow_check") and self.tid_flow_check.isChecked())
        self.advanced_options.setVisible(advanced and applies)
        for name, widget in self.fields.items():
            if name == "layers" or name.startswith("expansion_"):
                widget.setEnabled(applies)
        self.fields["parity"].setEnabled(applies and not egg)
        if egg:
            self.fields["parity"].setCurrentIndex(0)
        self.fields["tid_pid"].setEnabled(advanced)
        if not advanced:
            self.fields["tid_pid"].setText("7942EF72")

    def _build_tid_page(self) -> QWidget:
        page, layout = self._page_canvas()
        settings = Card("TID / SID 基本条件", "支持目标乱数或从断点继续穷举。")
        self._form(settings, [
            ("tid_language", "ROM 语言", _combo("英文", "日文")),
            ("tid_game", "游戏版本", _combo("火红", "叶绿")),
            ("tid_mode", "运行模式", _combo("乱数模式", "穷举模式")),
            ("tid_nx", "主机", _combo("Switch 1", "Switch 2")),
            ("tid_gender", "主角性别", _combo("男性", "女性", current=1)),
            ("tid_name", "主角名称", _line("Alxe")),
            ("tid_target", "目标 TID", _line("00000")),
            ("tid_sid", "目标 SID", _line("38449")),
            ("tid_pid", "6V 闪 PID", _line("7942EF72")),
        ])
        self._form(settings, [("tid_sid_mode", "SID 处理", _combo("目标 SID（自动计算 ADV）", "不乱数 SID（固定 F3，采用实际 SID）"))], 1)
        self._actions(settings, "6V 闪 SID")
        settings.layout.addWidget(QCheckBox("先检测固定延迟，完成后自动运行计划"))
        settings.layout.addWidget(_label("脚本会新建存档并自动退出游戏两次；请先确认当前存档与主页状态。", role="warning"))
        layout.addWidget(settings)

        frames = Card("乱数中心 / 穷举范围", "OP / F1 / F2 按游戏画面帧填写，不是 Ten Lines 的 RNG advance。", collapsible=True)
        frame_grid = QGridLayout()
        for c, title in enumerate(("参数", "OP", "F1", "F2")):
            frame_grid.addWidget(_label(title, name="fieldLabel"), 0, c)
        for r, (key, title, values) in enumerate((
            ("target", "乱数中心帧", ("3693", "2693", "2105")),
            ("radius", "乱数搜索半径", ("0", "0", "0")),
            ("start", "穷举起点", ("0", "0", "0")),
            ("range", "穷举最大范围", ("600", "30", "300")),
        ), 1):
            frame_grid.addWidget(_label(title, name="fieldLabel"), r, 0)
            for c, (axis, value) in enumerate(zip(("op", "f1", "f2"), values), 1):
                entry = _line(value)
                entry.setAccessibleName(f"{axis.upper()} {title}")
                self.fields[f"tid_{axis}_{key}"] = entry
                frame_grid.addWidget(entry, r, c)
                frame_grid.setColumnStretch(c, 1)
        frames.layout.addLayout(frame_grid)
        layout.addWidget(frames)

        delays = Card("游戏设置与固定延迟", "延迟和 OP 修正使用 ms；测量与自动回填服务尚未接入。", collapsible=True)
        self._form(delays, [
            ("tid_sound", "Sound", _combo("MONO", "STEREO")),
            ("tid_button", "Button Mode", _combo("HELP", "LR", "L=A")),
            ("tid_seed_button", "Seed Button", _combo("A", "START", "L(L=A)")),
            ("tid_name_entry", "取名进入键", _combo("A", "B")),
        ], 2)
        self.tid_manual_delay = self._check("手动编辑固定延迟")
        delays.layout.addWidget(self.tid_manual_delay)
        self._form(delays, [
            (f"tid_{axis}_delay", f"{axis.upper()} 固定延迟（ms）", _line(value))
            for axis, value in (("op", "30600"), ("f1", "22050"), ("f2", "4250"), ("f3", "14900"))
        ], 2)
        self._form(delays, [
            ("tid_close", "关闭游戏延迟（ms）", _line("1500")),
            ("tid_home", "HOME_BUFFER（ms）", _line("1200")),
            ("tid_op_correction", "OP 修正（ms）", _line("0")),
            ("tid_sid_correction", "SID ADV 修正", _line("0")),
            ("tid_select", "SELECT 补偿", _line("0")),
        ])
        layout.addWidget(delays)

        starter = Card("御三家连续乱数", "TID → 球前存档 → 御三家；第三阶段游戏设置独立。流程尚未完成整轮实机验收。")
        self.tid_flow_check = self._check("TID 阶段完成后继续御三家", True)
        starter.layout.addWidget(self.tid_flow_check)
        self._form(starter, [
            ("starter_species", "御三家", _combo("妙蛙种子", "小火龙", "杰尼龟")),
            ("starter_min", "最低 ADV", _line("1500")),
            ("starter_max", "最高 ADV", _line("10000")),
            ("starter_sound", "Sound", _combo("MONO", "STEREO")),
            ("starter_button", "Button Mode", _combo("HELP", "LR", "L=A")),
            ("starter_seed_button", "Seed Button", _combo("A", "START", "L(L=A)")),
            ("starter_retry", "SID ADV 重试半径", _line("20")),
        ])
        self.tid_any_check = self._check("取得任意 TID 后继续")
        self.tid_denoise_check = self._check("任意 TID 仍需去噪确认", True)
        starter.layout.addWidget(self.tid_any_check)
        starter.layout.addWidget(self.tid_denoise_check)
        starter.layout.addWidget(_label("御三家 Seed 校准固定方案 0；Seed 启动与脚本入口沿用共通设置。", role="muted"))
        layout.addWidget(starter)

        filters = Card("穷举判定与高级范围", "号码开关按当前连续流程模式启用。", collapsible=True)
        self.tid_special_checks = [self._check(title, title == "65535") for title in ("豹子号", "升/降连号", "65535", "个位数 TID")]
        specials = QHBoxLayout()
        for check in self.tid_special_checks:
            specials.addWidget(check)
        filters.layout.addLayout(specials)
        self._form(filters, [
            ("tid_f2_candidate", "F2 候选阈值", _line("2000")),
            ("tid_f1_candidate", "F1 候选阈值", _line("100")),
            ("tid_hits", "去噪命中数", _line("2")),
            ("tid_window", "去噪窗口", _line("10")),
            ("tid_threshold", "识图阈值", _line("95")),
        ])
        layout.addWidget(filters)
        layout.addWidget(self._path_card("TID 1.3.7 脚本包", "脚本包（TID 独立路径）", "tid_source"))
        resume = Card("参数保存与穷举续跑", "参数保存、检查点读取与续跑服务尚未接入。", collapsible=True)
        resume.layout.addWidget(self._check("继续同参数的上次穷举进度", True))
        resume.layout.addWidget(_label("未读取本机进度；当前表单在关闭窗口后丢弃。", role="muted"))
        self._actions(resume, "刷新进度")
        layout.addWidget(resume)
        for check in (self.tid_flow_check, self.tid_any_check, self.tid_manual_delay):
            check.toggled.connect(self._refresh_tid_controls)
        for name in ("tid_mode", "tid_sid_mode"):
            self.fields[name].currentIndexChanged.connect(self._refresh_tid_controls)
        self.fields["tid_language"].currentIndexChanged.connect(self._tid_language_defaults)
        self._refresh_tid_controls()
        layout.addStretch(1)
        return page

    def _refresh_tid_controls(self) -> None:
        flow = self.tid_flow_check.isChecked()
        exhaustive = self.fields["tid_mode"].currentIndex() == 1
        if flow and exhaustive:
            combo = self.fields["tid_sid_mode"]
            combo.blockSignals(True)
            combo.setCurrentIndex(1)
            combo.blockSignals(False)
        fixed = self.fields["tid_sid_mode"].currentIndex() == 1
        any_tid = flow and exhaustive and self.tid_any_check.isChecked()
        self.fields["tid_sid_mode"].setEnabled(not (flow and exhaustive))
        self.fields["tid_sid"].setEnabled(not fixed)
        self.fields["tid_target"].setEnabled(not any_tid)
        self.tid_any_check.setEnabled(flow and exhaustive)
        self.tid_denoise_check.setEnabled(any_tid)
        for check in self.tid_special_checks:
            check.setEnabled((not flow or exhaustive) and not any_tid)
        for name, widget in self.fields.items():
            if name.startswith("starter_"):
                widget.setEnabled(flow and (name != "starter_retry" or not (exhaustive or fixed)))
        for axis in ("op", "f1", "f2", "f3"):
            self.fields[f"tid_{axis}_delay"].setEnabled(self.tid_manual_delay.isChecked())
        if hasattr(self, "settings_dialog"):
            self._refresh_common_settings()
            if self.input_mode == "tid":
                self.search_button.setText("生成 TID/SID + 御三家计划" if flow else "生成 TID/SID 脚本")

    def _tid_language_defaults(self) -> None:
        # Display defaults only, copied from Tk's language switch at 7438e0e.
        # No timing computation, calibration or request construction happens here.
        japanese = self.fields["tid_language"].currentIndex() == 1
        for name, en, jp in (
            ("tid_target", "00000", "00001"), ("tid_sid", "38449", "64506"),
            ("tid_name", "Alxe", "レット゛"), ("tid_op_delay", "30600", "30650"),
            ("tid_f1_delay", "22050", "27600"), ("tid_f2_delay", "4250", "8960"),
            ("tid_f3_delay", "14900", "15950"), ("tid_op_target", "3693", "3689"),
            ("tid_f1_target", "2693", "3323"), ("tid_f2_target", "2105", "2011"),
            ("tid_op_range", "600", "600"), ("tid_f1_range", "30", "500"),
            ("tid_f2_range", "300", "10"),
        ):
            self.fields[name].setText(jp if japanese else en)
        self.fields["tid_gender"].setCurrentIndex(0 if japanese else 1)
        for axis in ("op", "f1", "f2"):
            self.fields[f"tid_{axis}_start"].setText("0")
            self.fields[f"tid_{axis}_radius"].setText("10" if japanese else "0")
        for i, check in enumerate(self.tid_special_checks):
            check.setChecked((japanese or i == 2) and not (self.tid_flow_check.isChecked() and self.fields["tid_mode"].currentIndex() == 0))

    def _build_egg_page(self) -> QWidget:
        page, layout = self._page_canvas()
        conditions = Card("孵蛋运行条件", "游戏和主机与野生 / 静态页共用；蛋种目录与名称校验尚未接入。")
        self._form(conditions, [
            ("egg_game", "游戏", _combo("火红", "叶绿")),
            ("egg_nx", "主机", _combo("Switch 1", "Switch 2")),
            ("egg_species", "蛋种（名称/编号）", _line(placeholder="中文名 / 英文名 / 编号")),
        ])
        self._form(conditions, [
            ("egg_seed_mode", "Seed 模式", _combo("请选择", *SEED_MODE_LABELS)),
            ("egg_start", "启动准备", _combo("完整准备（自动走 254 步并存档）", "从已完成 254 步准备开始")),
        ], 2)
        self.fields["egg_start"].setToolTip("从基础档开始仅跳过一次性准备，要求已经完成并保存 254 步；之后仍执行 Seed 启动与全部校准流程。")
        layout.addWidget(conditions)

        target = Card("孵蛋目标", "先从 Ten Lines Egg 页取得同一个初始 Seed 下的 Held 和 Pickup；Pickup 至少晚 1800 ADV。")
        self._form(target, [
            ("egg_seed", "目标 Seed（同 Seed）", _line("75D1")),
            ("egg_held", "Held / 生成帧（ADV）", _line("8021")),
            ("egg_pickup", "Pickup / 领取帧（ADV）", _line("10021")),
            ("egg_compatibility", "双亲相性", _combo("20", "50", "70", current=2)),
        ])
        self.egg_parents = QWidget()
        parents_layout = QVBoxLayout(self.egg_parents)
        parents_layout.setContentsMargins(0, 0, 0, 0)
        parents_layout.setSpacing(16)
        for r, (name, choices) in enumerate((("A", ("雌", "无性别")), ("B", ("雄", "无性别")))):
            row = QHBoxLayout()
            row.addWidget(_label(f"亲本 {name}", name="chipValue"))
            gender = _combo(*choices)
            gender.setAccessibleName(f"亲本 {name} 性别")
            gender.setMaximumWidth(145)
            row.addWidget(gender)
            row.addStretch(1)
            parents_layout.addLayout(row)
            grid = QGridLayout()
            grid.setSpacing(8)
            for c, stat in enumerate(STATS):
                spin = self._spin(31, 0, 31)
                self._field(grid, 0, c, stat, spin)
                spin.setAccessibleName(f"亲本 {name} {stat} IV")
            parents_layout.addLayout(grid)
        target.layout.addWidget(_label("亲本个体值 IV", name="fieldLabel"))
        target.layout.addWidget(self.egg_parents)
        self.egg_ack = self._check("我已确认孵蛋前置条件，允许启动流程")
        self.egg_ack.setToolTip("请确认 254 步基础档、队伍空位、甜甜香气宝可梦与 Ten Lines 目标参数。确认不持久化，配置载入后需当次重新勾选。")
        target.layout.addWidget(self.egg_ack)
        target.layout.addWidget(_label("孵蛋尚未完成整轮实机验收。此预览未接入生成或运行服务。", role="warning"))
        self._actions(target, "保存亲本配置", "载入亲本配置", "保存全部配置", "载入全部配置", columns=2)
        layout.addWidget(target)
        for suffix in ("game", "nx"):
            wild, egg = self.fields[f"wild_{suffix}"], self.fields[f"egg_{suffix}"]
            wild.currentIndexChanged.connect(egg.setCurrentIndex)
            egg.currentIndexChanged.connect(wild.setCurrentIndex)
        layout.addStretch(1)
        return page

    def _build_logs_page(self) -> QWidget:
        page, layout = self._page_canvas()
        log_card = Card("当前/最近一次运行输出", "日志尾读与运行状态尚未接入；这里不展示模拟运行记录。")
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setMinimumHeight(275)
        self.log_view.setPlainText("尚未接入运行日志。\n正式界面会在进程成功启动后切换到本页。")
        log_card.layout.addWidget(self.log_view)
        layout.addWidget(log_card)
        labels = Card("设备标签诊断与覆盖", "设备覆盖按采集卡名称独立保存；日志诊断与标签文件服务尚未接入。", collapsible=True)
        labels.layout.addWidget(_label("尚未检测采集卡，未读取任何设备标签覆盖。", role="muted"))
        self.label_issues = self._table(("疑似标签", "最高分", "门槛", "连续次数", "出错阶段与原因"), height=190)
        self.label_issues.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.label_issues.setColumnWidth(0, 220)
        self.label_issues.setColumnWidth(4, 350)
        labels.layout.addWidget(self.label_issues)
        drop = _label("拖放 .IL 文件或文件夹 · 尚未接入", role="muted")
        drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop.setMinimumHeight(44)
        labels.layout.addWidget(drop)
        self._actions(labels, "选择标签文件（可多选）", "选择标签文件夹", "清除当前设备覆盖")
        clear = _button("清空诊断列表", enabled=True)
        clear.setMaximumWidth(240)
        clear.clicked.connect(lambda: self.label_issues.setRowCount(0))
        labels.layout.addWidget(clear)
        layout.addWidget(labels)
        layout.addStretch(1)
        return page

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("footerBar")
        footer.setFixedHeight(70)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)
        layout.addWidget(_label("●  界面预览 · 尚未生成方案", name="readyText"), 1)
        self.overview_button = _button("方案与设备", enabled=True)
        self.overview_button.clicked.connect(self._show_overview)
        layout.addWidget(self.overview_button)
        self.search_button = _button("搜索并生成方案", "primary")
        self.search_button.setToolTip(NOT_CONNECTED)
        layout.addWidget(self.search_button)
        layout.addWidget(_button("开始运行", "success"))
        more = _button("···", enabled=True)
        more.setAccessibleName("更多运行操作")
        more.setToolTip("取消搜索、停止 EasyCon")
        menu = QMenu(more)
        for title in ("取消搜索", "停止 EasyCon"):
            action = menu.addAction(title)
            action.setEnabled(False)
            action.setToolTip(NOT_CONNECTED)
        more.setMenu(menu)
        layout.addWidget(more)
        return footer

    def select_page(self, key: str) -> None:
        if key not in self.page_indices:
            return
        self.current_page = key
        if key == "script_test" and not self.advanced_check.isChecked():
            self.advanced_check.setChecked(True)
        if key not in {"tid_records", "logs"}:
            self.input_mode = key
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
                "tid": "生成建档与御三家计划" if self.tid_flow_check.isChecked() else "生成建档脚本",
                "egg": "生成孵蛋脚本",
                "script_test": "预检所选脚本",
            }[self.input_mode]
        )
        self._refresh_overview()
        if hasattr(self, "settings_dialog"):
            self._refresh_common_settings()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=WINDOW_TITLE)
    parser.add_argument("--page", choices=[item[0] for item in NAV_ITEMS], default="sid")
    parser.add_argument("--size", default="1360x860", help="Window size, e.g. 900x620")
    parser.add_argument("--advanced", action="store_true", help="Show advanced preview controls")
    parser.add_argument("--expand", action="store_true", help="Expand optional sections for visual checks")
    parser.add_argument("--scroll", type=float, default=0, help="Screenshot scroll fraction, 0 to 1")
    parser.add_argument("--settings", action="store_true", help="Show the shared settings window")
    parser.add_argument("--screenshot", type=Path, help="Render the selected page to a PNG and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("FRLG Auto RNG PySide6 Preview")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    window = FrlgPreviewWindow()
    width, height = (int(part) for part in args.size.lower().split("x"))
    window.resize(width, height)
    window.advanced_check.setChecked(args.advanced)
    window.select_page(args.page)
    if args.expand:
        for card in window.findChildren(Card):
            if hasattr(card, "toggle"):
                card.toggle.setChecked(True)
    window.show()
    if args.settings:
        window.settings_dialog.show()
    if args.screenshot:
        destination = args.screenshot.resolve()

        def capture() -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            target = window.settings_dialog if args.settings else window
            if not target.grab().save(str(destination), "PNG"):
                app.exit(2)
                return
            app.exit(0)

        def position() -> None:
            scroll = window.settings_dialog.findChild(QScrollArea) if args.settings else window.stack.currentWidget()
            bar = scroll.verticalScrollBar()
            bar.setValue(round(bar.maximum() * max(0, min(1, args.scroll))))
            QTimer.singleShot(250, capture)

        QTimer.singleShot(350, position)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
