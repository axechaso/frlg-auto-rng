"""Qt editor for the existing, validated SaveProfileStore."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QListWidget, QMessageBox, QVBoxLayout,
)
from pyside_chrome import ThemedDialog as QDialog
from pyside_preview import Card, FrlgPreviewWindow, _button, _combo, _line


class ProfileManager(QDialog):
    changed = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.profile_id = None
        self.setWindowTitle("管理存档")
        self.resize(650, 580)
        layout = QVBoxLayout(self)
        card = Card("存档列表", "与正式工具共用；保存后可在存档信息中选择。")
        self.list = QListWidget()
        self.list.setMinimumHeight(120)
        self.list.setMaximumHeight(150)
        self.list.setStyleSheet("QListWidget {background: #f7f9fd; border: 1px solid #d9e2f2; border-radius: 10px; padding: 6px; color: #10243d;} QListWidget::item {padding: 9px; border-radius: 6px;} QListWidget::item:selected {background: #e9edff; color: #505df4;} QListWidget::item:hover {background: #eff2ff;}")
        card.layout.addWidget(self.list)
        self.name = _line()
        self.name.setPlaceholderText("存档名称")
        self.game = _combo("火红", "叶绿")
        self.language = _combo("英文（美版）", "日文（日版）")
        self.nx = _combo("Switch 1", "Switch 2")
        self.tid, self.sid = _line(), _line()
        self.tid.setPlaceholderText("TID：0–65535")
        self.sid.setPlaceholderText("SID：0–65535")
        for entries in ((('存档名称', self.name),), (('游戏版本', self.game), ('ROM 语言 / 地区', self.language), ('主机', self.nx)), (('当前 TID', self.tid), ('当前 SID', self.sid))):
            row = QGridLayout()
            row.setSpacing(12)
            for column, (label, widget) in enumerate(entries):
                FrlgPreviewWindow._field(row, 0, column, label, widget)
            card.layout.addLayout(row)
        actions = QHBoxLayout()
        for title, handler in (("新建", self.new), ("保存", self.save), ("复制", self.duplicate), ("删除", self.delete)):
            button = _button(title, enabled=True)
            button.clicked.connect(handler)
            actions.addWidget(button)
        card.layout.addLayout(actions)
        layout.addWidget(card)
        done = _button("完成", enabled=True)
        done.clicked.connect(self.accept)
        layout.addWidget(done)
        self.list.currentRowChanged.connect(self.select)
        self.refresh()

    def refresh(self):
        selected = self.profile_id or self.store.selected_profile_id
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems([f"{p.name} · {p.game} · {p.tid:05d} / {p.sid:05d}" for p in self.store.profiles])
        self.list.blockSignals(False)
        index = next((i for i, p in enumerate(self.store.profiles) if p.profile_id == selected), -1)
        self.list.setCurrentRow(index)
        if index == -1:
            self.new()

    def select(self, row):
        if not 0 <= row < len(self.store.profiles):
            return
        profile = self.store.profiles[row]
        self.profile_id = profile.profile_id
        self.name.setText(profile.name)
        self.game.setCurrentText(profile.game)
        self.language.setCurrentIndex(profile.language == "日文")
        self.nx.setCurrentIndex(profile.nx_model - 1)
        self.tid.setText(f"{profile.tid:05d}")
        self.sid.setText(f"{profile.sid:05d}")

    def new(self):
        self.profile_id = None
        self.list.setCurrentRow(-1)
        self.name.clear()
        self.tid.clear()
        self.sid.clear()

    def mutate(self, operation):
        try:
            operation()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "无法保存存档", str(exc))
            return
        self.refresh()
        self.changed.emit()

    def save(self):
        def commit():
            values = (self.name.text(), self.game.currentText(), self.tid.text(), self.sid.text(), self.nx.currentIndex() + 1)
            language = "日文" if self.language.currentIndex() else "英文"
            if self.profile_id:
                profile = self.store.update(self.profile_id, *values, language=language)
            else:
                profile = self.store.add(*values, language=language)
            self.profile_id = profile.profile_id
        self.mutate(commit)

    def duplicate(self):
        if self.profile_id:
            def commit():
                self.profile_id = self.store.duplicate(self.profile_id).profile_id
            self.mutate(commit)

    def delete(self):
        if self.profile_id and QMessageBox.question(self, "删除存档", "从工具中删除此存档资料？游戏存档不会被删除。") == QMessageBox.StandardButton.Yes:
            def commit():
                self.store.delete(self.profile_id)
                self.profile_id = None
            self.mutate(commit)
