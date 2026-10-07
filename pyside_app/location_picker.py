"""Search existing encounter locations without inserting arbitrary choices."""
from functools import cmp_to_key

from PySide6.QtCore import QCollator, QLocale, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QCompleter, QStyledItemDelegate

from assets.game_text import location_to_en, location_to_zh
from pyside_preview import APP_STYLE, CompletionPopup


SEARCH_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def sorted_location_items(locations):
    """Chinese name order, with natural numbers (Route 2 before Route 10)."""
    collator = QCollator(QLocale("zh_CN"))
    collator.setNumericMode(True)
    collator.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    items = [(location_to_zh(loc), loc) for loc in dict.fromkeys(locations)]
    return sorted(items, key=cmp_to_key(
        lambda a, b: collator.compare(a[0], b[0]) or collator.compare(a[1], b[1])
    ))


def _search_text(label, canonical):
    return " | ".join((label, canonical))


class LocationCompleter(QCompleter):
    def pathFromIndex(self, index):
        # Match the hidden Chinese/English role, but insert only the
        # canonical Chinese display label, never the concatenated search text.
        return index.data(Qt.ItemDataRole.DisplayRole) or ""


def _completer(model, parent):
    completer = LocationCompleter(model, parent)
    completer.setCompletionRole(SEARCH_ROLE)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    completer.setMaxVisibleItems(8)
    popup = CompletionPopup()
    popup.setObjectName("comboPopupList")
    popup.setStyleSheet(APP_STYLE)
    popup.setItemDelegate(QStyledItemDelegate(popup))
    popup.setMinimumWidth(360)
    popup.setUniformItemSizes(True)
    popup.setMouseTracking(True)
    popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    popup.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    popup.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    completer.setPopup(popup)
    return completer


def configure_location_combo(combo):
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.setProperty("locationSearch", True)
    combo.lineEdit().setPlaceholderText("输入地点关键字，或下拉选择")
    combo.lineEdit().setClearButtonEnabled(True)
    combo.setToolTip("可输入中文或英文关键字，再从匹配列表选择地点。旧房间编号名称不再接受。")
    combo.lineEdit().setStyleSheet("QLineEdit { border: none; background: transparent; padding: 0; min-height: 0; }")
    completer = _completer(combo.model(), combo)
    combo.setCompleter(completer)
    completer.activated[str].connect(lambda text: _commit_combo(combo, text))
    combo.lineEdit().editingFinished.connect(lambda: _commit_combo(combo, combo.currentText()))


def refresh_location_search_roles(combo):
    for index in range(combo.count()):
        canonical = combo.itemData(index)
        combo.setItemData(index, _search_text(combo.itemText(index), canonical), SEARCH_ROLE)
        combo.setItemData(index, canonical, Qt.ItemDataRole.ToolTipRole)


def selected_location(combo):
    """Return an exact listed choice; a pending search never uses the old row."""
    text = combo.currentText().strip()
    canonical = location_to_en(text)
    for index in range(combo.count()):
        if text == combo.itemText(index) or canonical == combo.itemData(index):
            return combo.itemData(index)
    return None


def _commit_combo(combo, text):
    # An unmatched keyword is left visible for the user to finish choosing;
    # it is not silently replaced with the previous or first result.
    canonical = location_to_en(text)
    index = combo.findText(text.strip())
    if index < 0:
        index = combo.findData(canonical)
    if index >= 0:
        combo.setCurrentIndex(index)
        combo.setEditText(combo.itemText(index))


def configure_location_edit(edit, locations):
    model = QStandardItemModel(edit)
    for label, canonical in sorted_location_items(locations):
        item = QStandardItem(label)
        item.setData(_search_text(label, canonical), SEARCH_ROLE)
        item.setData(canonical, Qt.ItemDataRole.ToolTipRole)
        model.appendRow(item)
    completer = _completer(model, edit)
    model.setParent(completer)
    edit.setCompleter(completer)
