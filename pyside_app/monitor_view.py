"""Switch preview surface; capture buffers are never resized or cropped here."""
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget


ZOOM_WIDTHS = (320, 480, 640, 800, 960, 1120, 1280)


def video_rect(width, height):
    # Match the formal monitor's Switch 16:9 display, including capture cards
    # that deliver an anamorphic 640x480 buffer for a widescreen HDMI signal.
    width, height = max(0, width), max(0, height)
    fitted_width = min(width, height * 16 / 9)
    fitted_height = fitted_width * 9 / 16
    return QRectF((width - fitted_width) / 2, (height - fitted_height) / 2, fitted_width, fitted_height)


class VideoSurface(QWidget):
    double_clicked = Signal()
    wheel_scrolled = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = None
        self.content_only = False
        self.drag_offset = None
        self.setMinimumSize(160, 90)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("双击：仅画面 / 恢复窗口\n滚轮：放大 / 缩小\n仅画面时可拖动画面移动窗口，Esc 恢复窗口")

    def sizeHint(self):
        return QSize(640, 360)

    def set_frame(self, frame):
        if self.frame is not None and self.frame.cacheKey() == frame.cacheKey():
            return
        self.frame = frame
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))
        if self.frame is None or self.frame.isNull():
            painter.setPen(QColor("#c7d4e9"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "等待采集画面")
        else:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(video_rect(self.width(), self.height()), self.frame)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = None
            self.double_clicked.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        self.wheel_scrolled.emit(event.angleDelta().y() or event.pixelDelta().y() * 4)
        event.accept()

    def mousePressEvent(self, event):
        if self.content_only and event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.window().pos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None
        super().mouseReleaseEvent(event)
