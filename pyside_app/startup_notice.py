"""Startup credits and donation notice for the PySide6 application."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app_paths import RESOURCE_ROOT
from tid_session import write_json_atomic


NOTICE_TITLE = "本工具完全开源免费！！！但是钱包空了求打赏..."
NOTICE_FILE = "startup_notice.json"

FUNCTION_SUMMARY = (
    "本工具面向《宝可梦 火红／叶绿》的自动乱数流程，集中提供 SID 查找、"
    "TID/SID 建档、野生与定点乱数、孵蛋、目标搜索、脚本生成、设备连接、"
    "运行监视及日志诊断等功能。\n\n"
    "填写必要的游戏与目标信息并生成方案后，工具将调用 EasyCon 和自动乱数脚本"
    "执行后续流程。项目仍在持续开发与实机验证中；如遇问题，请保留完整日志以便排查。"
)

CREDITS_HTML = """
<p>本工具基于
<a href="https://github.com/EasyConNS/EasyCon">EasyCon（伊机控）</a>
与 <a href="https://github.com/zhangjf-nlp/PyEasyCon">PyEasyCon</a>
的开源成果开发。</p>
<p>
EasyCon 原作者：<a href="https://github.com/nukieberry">铃落（nukieberry）</a><br>
EasyCon 维护者：<a href="https://github.com/ca1e">ca1e</a>、
<a href="https://github.com/elmagnificogi">elmagnifico</a> 及 EasyConNS 团队<br>
PyEasyCon 作者：<a href="https://github.com/zhangjf-nlp">zhangjf-nlp</a>
</p>
<p>脚本部分基于冰与路飞数字君制作的自动乱数脚本进行整理与适配。衷心感谢各位原作者、维护者及参与测试和反馈的朋友。</p>
"""


def should_show_startup_notice(user_dir: str | Path, *, automated: bool = False) -> bool:
    """Return whether an interactive launch should display the notice."""
    if automated:
        return False
    try:
        payload = json.loads((Path(user_dir) / NOTICE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return True
    return not (
        isinstance(payload, dict)
        and payload.get("schema") == 1
        and payload.get("hidden") is True
    )


class StartupNoticeDialog(QDialog):
    def __init__(self, user_dir: str | Path, parent=None):
        super().__init__(parent)
        self.user_dir = Path(user_dir)
        self.setObjectName("startupNoticeDialog")
        self.setWindowTitle(NOTICE_TITLE)
        self.setModal(True)
        self.resize(880, 780)
        self.setMinimumSize(720, 620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        heading = QLabel(NOTICE_TITLE)
        heading.setObjectName("startupNoticeHeading")
        heading.setWordWrap(True)
        heading.setStyleSheet("font-size: 20px; font-weight: 700; color: #20283a;")
        outer.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        content = QVBoxLayout(body)
        content.setContentsMargins(4, 2, 8, 4)
        content.setSpacing(10)

        content.addWidget(self._section_title("功能简介"))
        summary = QLabel(FUNCTION_SUMMARY)
        summary.setObjectName("startupNoticeSummary")
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.addWidget(summary)

        content.addWidget(self._section_title("感谢与致谢"))
        credits = QLabel(CREDITS_HTML)
        credits.setObjectName("startupNoticeCredits")
        credits.setWordWrap(True)
        credits.setTextFormat(Qt.TextFormat.RichText)
        credits.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        credits.setOpenExternalLinks(True)
        content.addWidget(credits)

        support = QLabel("如果这个工具帮你节省了时间，也欢迎量力支持。")
        support.setWordWrap(True)
        support.setStyleSheet("font-weight: 600; color: #34405a;")
        content.addWidget(support)

        images = QHBoxLayout()
        images.setSpacing(18)
        images.addWidget(self._donation_image(
            "支付宝", "donate-alipay.jpg", "alipayDonationImage"
        ))
        images.addWidget(self._donation_image(
            "微信", "donate-wechat.png", "wechatDonationImage"
        ))
        content.addLayout(images)

        footer = QLabel(
            "您的赞助将全部用于本工具及其他乱数工具的持续开发、测试与维护。感谢支持！"
        )
        footer.setObjectName("startupNoticeFooter")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setWordWrap(True)
        footer.setStyleSheet("font-weight: 600; color: #34405a; padding: 8px 0;")
        content.addWidget(footer)
        content.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        controls = QHBoxLayout()
        self.hide_checkbox = QCheckBox("下次启动不再显示")
        self.hide_checkbox.setObjectName("hideStartupNotice")
        controls.addWidget(self.hide_checkbox)
        controls.addStretch(1)
        enter = QPushButton("进入工具")
        enter.setObjectName("enterToolButton")
        enter.setDefault(True)
        enter.clicked.connect(self.accept)
        controls.addWidget(enter)
        outer.addLayout(controls)

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 15px; font-weight: 700; color: #20283a;")
        return label

    @staticmethod
    def _donation_image(title: str, filename: str, object_name: str) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame { background: #f6f8fc; border: 1px solid #dce2ee; border-radius: 10px; }"
            "QLabel { border: none; background: transparent; }"
        )
        layout = QVBoxLayout(panel)
        caption = QLabel(title)
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setStyleSheet("font-weight: 700;")
        layout.addWidget(caption)
        image = QLabel()
        image.setObjectName(object_name)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(RESOURCE_ROOT / "assets" / "pyside_preview" / filename))
        if pixmap.isNull():
            image.setText(f"{title}赞助图加载失败")
        else:
            image.setPixmap(pixmap.scaled(
                300,
                420,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        layout.addWidget(image)
        return panel

    def accept(self) -> None:
        if self.hide_checkbox.isChecked():
            try:
                write_json_atomic(
                    self.user_dir / NOTICE_FILE,
                    {"schema": 1, "hidden": True},
                )
            except OSError as exc:
                QMessageBox.warning(self, "公告设置未保存", str(exc))
        super().accept()
