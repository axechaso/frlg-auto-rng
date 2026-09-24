"""Pixel-accurate canvas for EasyCon label range and target selection."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QFileDialog, QWidget


class LabelCanvas(QWidget):
    selectionFinished = Signal(str, QRect)
    imageOpenRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._image = QImage()
        self._range = QRect()
        self._target = QRect()
        self._mode = ""
        self._drag_start: QPointF | None = None
        self._drag_end: QPointF | None = None
        self._pan_start: QPointF | None = None
        self._offset = QPointF(0, 0)
        self._zoom = 1.0

    def set_image(self, image: QImage) -> None:
        self._image = image.copy()
        self._offset = QPointF(0, 0)
        self._zoom = 1.0
        self.update()

    def set_overlays(self, search_range: QRect, target: QRect) -> None:
        self._range = QRect(search_range)
        self._target = QRect(target)
        self.update()

    def set_selection_mode(self, mode: str) -> None:
        self._mode = mode if mode in {"range", "target"} else ""
        self._drag_start = None
        self._drag_end = None
        self.setCursor(Qt.CursorShape.CrossCursor if self._mode else Qt.CursorShape.OpenHandCursor)

    def _scale(self) -> float:
        if self._image.isNull():
            return 1.0
        fit = min(self.width() / self._image.width(), self.height() / self._image.height())
        return max(0.01, fit * self._zoom)

    def _origin(self) -> QPointF:
        scale = self._scale()
        return QPointF(
            (self.width() - self._image.width() * scale) / 2 + self._offset.x(),
            (self.height() - self._image.height() * scale) / 2 + self._offset.y(),
        )

    def _image_to_widget(self, point: QPointF) -> QPointF:
        origin = self._origin()
        scale = self._scale()
        return QPointF(origin.x() + point.x() * scale, origin.y() + point.y() * scale)

    def _widget_to_image(self, point: QPointF) -> QPointF:
        origin = self._origin()
        scale = self._scale()
        return QPointF((point.x() - origin.x()) / scale, (point.y() - origin.y()) / scale)

    def _image_rect_to_widget(self, rect: QRect) -> QRectF:
        if rect.isNull() or rect.isEmpty():
            return QRectF()
        top_left = self._image_to_widget(QPointF(rect.x(), rect.y()))
        scale = self._scale()
        return QRectF(top_left.x(), top_left.y(), rect.width() * scale, rect.height() * scale)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111827"))
        if self._image.isNull():
            painter.setPen(QColor("#d7dfeb"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "载入故障原图或本地截图")
            return
        origin = self._origin()
        scale = self._scale()
        image_rect = QRectF(origin.x(), origin.y(), self._image.width() * scale, self._image.height() * scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(image_rect, self._image)
        for rect, color, title in ((self._range, QColor("#f04452"), "搜索范围"),
                                   (self._target, QColor("#36d889"), "模板目标")):
            display = self._image_rect_to_widget(rect)
            if display.isNull():
                continue
            pen = QPen(color)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(display)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(display.topLeft() + QPointF(5, 16), title)
        if self._drag_start is not None and self._drag_end is not None:
            start = self._image_to_widget(self._drag_start)
            end = self._image_to_widget(self._drag_end)
            pen = QPen(QColor("#f04452" if self._mode == "range" else "#36d889"))
            pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(QRectF(start, end).normalized())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    def mousePressEvent(self, event):
        point = event.position()
        if event.button() == Qt.MouseButton.RightButton and self._mode:
            image_point = self._widget_to_image(point)
            image_point.setX(min(max(0, image_point.x()), max(0, self._image.width() - 1)))
            image_point.setY(min(max(0, image_point.y()), max(0, self._image.height() - 1)))
            self._drag_start = image_point
            self._drag_end = image_point
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._pan_start = point
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = event.position()
        if self._drag_start is not None:
            image_point = self._widget_to_image(point)
            image_point.setX(min(max(0, image_point.x()), max(0, self._image.width() - 1)))
            image_point.setY(min(max(0, image_point.y()), max(0, self._image.height() - 1)))
            self._drag_end = image_point
            self.update()
        elif self._pan_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = point - self._pan_start
            self._offset += delta
            self._pan_start = point
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self._drag_start is not None:
            start, end = self._drag_start, self._drag_end or self._drag_start
            left = max(0, min(self._image.width(), int(min(start.x(), end.x()))))
            top = max(0, min(self._image.height(), int(min(start.y(), end.y()))))
            right = max(0, min(self._image.width(), int(max(start.x(), end.x())) + 1))
            bottom = max(0, min(self._image.height(), int(max(start.y(), end.y())) + 1))
            rect = QRect(left, top, max(0, right - left), max(0, bottom - top))
            mode = self._mode
            self._drag_start = None
            self._drag_end = None
            if rect.width() > 0 and rect.height() > 0:
                self.selectionFinished.emit(mode, rect)
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._pan_start = None
            self.setCursor(Qt.CursorShape.CrossCursor if self._mode else Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self._image.isNull():
            return
        cursor = event.position()
        fixed = self._widget_to_image(cursor)
        self._zoom = min(12.0, max(0.1, self._zoom * (1.15 if event.angleDelta().y() > 0 else 1 / 1.15)))
        projected = self._image_to_widget(fixed)
        self._offset += cursor - projected
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.imageOpenRequested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
