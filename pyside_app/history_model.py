"""Virtual rows; at most 250 new entries are exposed per Qt event turn."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from .log_history import format_log_size


class HistoryLogModel(QAbstractTableModel):
    sortRequested = Signal(int, object)
    HEADERS = ("时间", "流程", "文件", "大小", "位置")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(row.path)
        if role == Qt.ItemDataRole.DisplayRole:
            return (row.modified_text, row.workflow, row.path.name,
                    format_log_size(row.size), row.location_text)[index.column()]
        return None

    def reset(self):
        self.beginResetModel()
        self.rows = []
        self.endResetModel()

    def append(self, rows):
        if rows:
            start = len(self.rows)
            self.beginInsertRows(QModelIndex(), start, start + len(rows) - 1)
            self.rows.extend(rows)
            self.endInsertRows()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.sortRequested.emit(column, order)
