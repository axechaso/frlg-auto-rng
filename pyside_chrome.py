"""Qt-only window decoration shared by the preview and functional interface."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QVBoxLayout, QWidget,
)


class CaptionButton(QAbstractButton):
    def __init__(self, action, titlebar):
        super().__init__(titlebar)
        self.action = action
        self.titlebar = titlebar
        self.setFixedSize(42, 34)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.refresh()

    def refresh(self):
        name = {"minimize": "最小化", "maximize": "还原" if self.window().isMaximized() else "最大化", "close": "关闭"}[self.action]
        self.setToolTip(name)
        self.setAccessibleName(name)
        self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = self.titlebar.dark
        hovered = self.underMouse() or self.isDown()
        background = "#17213a" if dark else "#f3f6fb"
        if hovered:
            background = "#354563" if dark else "#e2e8f4"
            if self.action == "close":
                background = "#cf344c" if self.isDown() else "#e34d62"
            painter.fillRect(self.rect(), QColor(background))
        color = "#ffffff" if dark or (hovered and self.action == "close") else "#53637e"
        painter.setPen(QPen(QColor(color), 1.2))
        cx, cy = self.width() / 2, self.height() / 2
        if self.action == "minimize":
            painter.drawLine(QPoint(int(cx - 5), int(cy + 2)), QPoint(int(cx + 5), int(cy + 2)))
        elif self.action == "close":
            painter.drawLine(QPoint(int(cx - 4), int(cy - 4)), QPoint(int(cx + 4), int(cy + 4)))
            painter.drawLine(QPoint(int(cx - 4), int(cy + 4)), QPoint(int(cx + 4), int(cy - 4)))
        elif self.window().isMaximized():
            painter.drawRect(QRectF(cx - 2, cy - 5, 8, 8))
            painter.fillRect(QRectF(cx - 5, cy - 2, 8, 8), QColor(background))
            painter.drawRect(QRectF(cx - 5, cy - 2, 8, 8))
        else:
            painter.drawRect(QRectF(cx - 5, cy - 5, 10, 10))


class TitleBar(QFrame):
    def __init__(self, window, *, dark):
        super().__init__(window)
        self.target = window
        self.dark = dark
        self.setObjectName("windowTitleBar")
        self.setFixedHeight(34)
        background, foreground = ("#17213a", "#c8d2e6") if dark else ("#f3f6fb", "#344765")
        self.setStyleSheet(f"QFrame#windowTitleBar {{background: {background}; border: none;}} QLabel {{background: transparent; color: {foreground}; font-size: 12px;}}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        self.title = QLabel()
        self.title.setMinimumWidth(0)
        for label in (self.icon, self.title):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.icon)
        layout.addWidget(self.title, 1)
        self.buttons = {}
        actions = ("minimize", "maximize", "close") if isinstance(window, QMainWindow) else ("close",)
        for action in actions:
            button = CaptionButton(action, self)
            self.buttons[action] = button
            layout.addWidget(button)
        self.buttons["close"].clicked.connect(window.close)
        if "minimize" in self.buttons:
            self.buttons["minimize"].clicked.connect(window.showMinimized)
            self.buttons["maximize"].clicked.connect(self.toggle_maximized)
        window.windowTitleChanged.connect(self.refresh_title)
        window.windowIconChanged.connect(self.refresh_icon)
        self.refresh_title()
        self.refresh_icon()

    def refresh_title(self, *_):
        title = self.target.windowTitle().removesuffix(" · PySide6")
        self.title.setText(title)

    def refresh_icon(self, *_):
        self.icon.setPixmap(self.target.windowIcon().pixmap(self.icon.size(), self.devicePixelRatioF()))

    def toggle_maximized(self):
        if self.target.isMaximized():
            self.target.showNormal()
        else:
            self.target.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.target.windowHandle():
            self.target.windowHandle().startSystemMove()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and "maximize" in self.buttons:
            self.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class ResizeEdge(QWidget):
    """Thin input-only edges delegate resizing to the actual window manager."""
    def __init__(self, window, edges, cursor):
        super().__init__(window)
        self.edges = edges
        self.setCursor(cursor)

    def mousePressEvent(self, event):
        handle = self.window().windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle:
            handle.startSystemResize(self.edges)
            event.accept()
        else:
            super().mousePressEvent(event)


class WindowChrome(QObject):
    def __init__(self, window, *, dark=False):
        super().__init__(window)
        self.window = window
        self.dark = dark
        self.content_only = False
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.titlebar = TitleBar(window, dark=dark)
        self.shell = QFrame()
        self.shell.setObjectName("windowShell")
        color = "#2f4060" if dark else "#d9e2ef"
        background = "#17213a" if dark else "#f3f6fb"
        self.normal_shell_style = f"QFrame#windowShell {{background: {background}; border: 1px solid {color};}}"
        self.shell.setStyleSheet(self.normal_shell_style)
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(1, 1, 1, 1)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self.titlebar)
        if isinstance(window, QMainWindow):
            body = window.takeCentralWidget()
            window.setCentralWidget(self.shell)
        else:
            body = QWidget()
            # QWidget.setLayout transfers the layout and its existing children;
            # handlers, input state and the dialog's accept/reject path survive.
            if window.layout():
                body.setLayout(window.layout())
            outer = QVBoxLayout(window)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(self.shell)
        shell_layout.addWidget(body, 1)
        self.edges = []
        edge = Qt.Edge
        for flags, cursor in (
            (edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
            (edge.RightEdge, Qt.CursorShape.SizeHorCursor),
            (edge.TopEdge, Qt.CursorShape.SizeVerCursor),
            (edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
            (edge.TopEdge | edge.LeftEdge, Qt.CursorShape.SizeFDiagCursor),
            (edge.TopEdge | edge.RightEdge, Qt.CursorShape.SizeBDiagCursor),
            (edge.BottomEdge | edge.LeftEdge, Qt.CursorShape.SizeBDiagCursor),
            (edge.BottomEdge | edge.RightEdge, Qt.CursorShape.SizeFDiagCursor),
        ):
            self.edges.append(ResizeEdge(window, flags, cursor))
        window.installEventFilter(self)
        self.refresh()

    def set_content_only(self, enabled):
        self.content_only = bool(enabled)
        # Reset the stylesheet as well as the layout margin: repolishing a
        # dynamic property alone leaves QFrame's old one-pixel contents inset.
        self.shell.setStyleSheet("QFrame#windowShell {background:black; border:0px;}" if self.content_only else self.normal_shell_style)
        self.refresh()

    def refresh(self):
        window = self.window
        maximized = window.isMaximized() or window.isFullScreen()
        self.shell.layout().setContentsMargins(*([0] * 4 if maximized or self.content_only else [1] * 4))
        self.titlebar.setVisible(not window.isFullScreen() and not self.content_only)
        for button in self.titlebar.buttons.values():
            button.refresh()
        w, h, grip, corner = window.width(), window.height(), 5, 12
        rects = ((0, corner, grip, h - 2 * corner), (w - grip, corner, grip, h - 2 * corner),
                 (corner, 0, w - 2 * corner, grip), (corner, h - grip, w - 2 * corner, grip),
                 (0, 0, corner, corner), (w - corner, 0, corner, corner),
                 (0, h - corner, corner, corner), (w - corner, h - corner, corner, corner))
        for handle, rect in zip(self.edges, rects):
            handle.setGeometry(*rect)
            fixed_x = window.minimumWidth() == window.maximumWidth()
            fixed_y = window.minimumHeight() == window.maximumHeight()
            blocked = (fixed_x and bool(handle.edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))) or (fixed_y and bool(handle.edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge)))
            handle.setVisible(not maximized and not blocked)
            handle.raise_()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.WindowStateChange, QEvent.Type.Show):
            self.refresh()
        return super().eventFilter(obj, event)


def decorate_window(window, *, dark=False):
    if not hasattr(window, "window_chrome"):
        window.window_chrome = WindowChrome(window, dark=dark)
    return window.window_chrome


class ThemedDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)

    def setVisible(self, visible):
        if visible:
            decorate_window(self)
        super().setVisible(visible)
