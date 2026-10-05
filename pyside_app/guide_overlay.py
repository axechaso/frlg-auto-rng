"""Qt spotlight and a non-modal reading card; business controls stay usable."""
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QScrollArea


class Spotlight(QWidget):
    def __init__(self, host):
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.target = QRect()
        self.safe = QRect()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRect(self.rect())
        for rect in (self.target, self.safe):
            if not rect.isEmpty():
                hole = QPainterPath()
                hole.addRoundedRect(rect, 5, 5)
                path = path.subtracted(hole)
        painter.fillPath(path, QColor(20, 32, 50, 85))
        painter.setPen(QPen(QColor("#e69a19"), 3))
        if not self.target.isEmpty():
            painter.drawRoundedRect(self.target, 5, 5)


class GuideOverlay(QDialog):
    def __init__(self, controller, host):
        super().__init__(host, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.controller, self.host = controller, host
        self.setModal(False)
        self.setObjectName("guideCard")
        self.setStyleSheet("QDialog#guideCard { background:#fffaf0; border:2px solid #d99828; border-radius:8px; } QPushButton { padding:7px; } QLabel { color:#29384d; }")
        layout = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.body = QLabel()
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setWordWrap(True)
        self.body.setMargin(6)
        scroll.setWidget(self.body)
        layout.addWidget(scroll, 1)
        self.state = QLabel()
        self.state.setWordWrap(True)
        self.state.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.state)
        self.buttons = {}
        for row in (("上一步", "下一步"), ("暂时收起", "本页不再提示")):
            line = QHBoxLayout()
            for title in row:
                button = QPushButton(title)
                button.setAutoDefault(False)
                self.buttons[title] = button
                line.addWidget(button)
            layout.addLayout(line)
        self.buttons["上一步"].clicked.connect(lambda: controller.move(-1))
        self.buttons["下一步"].clicked.connect(lambda: controller.move(1))
        self.buttons["暂时收起"].clicked.connect(controller.minimize)
        self.buttons["本页不再提示"].clicked.connect(controller.opt_out)
        self.spot = Spotlight(host)
        self.destroyed.connect(self.spot.deleteLater)
        self.anchor = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.reposition)

    def present(self, step, anchor, index, count, status):
        self.anchor = anchor
        self.title.setText(f"{index + 1} / {count} · {step.title}")
        self.body.setText(step.body + (f"\n\n提示：{step.risk_note}" if step.risk_note else ""))
        self.state.setText(status)
        self.buttons["上一步"].setEnabled(index > 0)
        self.buttons["下一步"].setText("阅读完成" if index == count - 1 else "下一步")
        self.resize(min(420, max(280, self.host.width()//2)), min(300, max(210, self.host.height()-160)))
        self.spot.show()
        self.spot.raise_()
        self.show()
        self.reposition()
        self.timer.start()

    def reposition(self):
        if not self.host.isVisible():
            self.controller.minimize()
            return
        self.spot.setGeometry(self.host.rect())
        rect = QRect()
        if self.anchor and self.anchor.isVisible() and self.anchor.window() is self.host:
            rect = QRect(self.anchor.mapTo(self.host, QPoint()), self.anchor.size())
            parent = self.anchor.parentWidget()
            while parent and parent is not self.host:
                rect = rect.intersected(QRect(parent.mapTo(self.host, QPoint()), parent.size()))
                parent = parent.parentWidget()
            rect = rect.adjusted(-4, -4, 4, 4).intersected(self.host.rect())
        self.spot.target = rect
        stop = self.controller.w.stop_button
        self.spot.safe = QRect(stop.mapTo(self.host, QPoint()), stop.size()).adjusted(-5,-5,5,5) if stop.window() is self.host else QRect()
        # Keep the card away from the explained control and the bottom stop bar.
        left,right = 18,self.host.width()-self.width()-18
        reserve = 100 if not self.spot.safe.isEmpty() else 18
        bottom=max(12,self.host.height()-self.height()-reserve)
        choices=[(left,bottom),(right,bottom),(left,14),(right,14)]
        choices.sort(key=lambda p: abs(p[0]+self.width()/2-rect.center().x()),reverse=True)
        position=next((p for p in choices if not QRect(*p,self.width(),self.height()).intersects(rect)),None)
        if position is None:
            # Small settings dialogs have no stop bar. Use the free band above
            # or below a field, instead of covering it with the 300px card.
            bands = ((14, rect.top()-12), (rect.bottom()+12, self.host.height()-reserve))
            for start,end in sorted(bands,key=lambda band:band[1]-band[0],reverse=True):
                if end-start>=210:
                    self.resize(self.width(),min(self.height(),end-start))
                    candidate=QRect(left,start,self.width(),self.height())
                    if candidate.bottom()<=end and not candidate.intersects(rect):
                        position=(left,start)
                        break
        if position is None:
            # A table or middle-of-dialog field may leave only a narrow side
            # band. The body stays scrollable, as on the main-window sidebar.
            bands=((14,rect.left()-12),(rect.right()+12,self.host.width()-18))
            for start,end in sorted(bands,key=lambda band:band[1]-band[0],reverse=True):
                if end-start>=200:
                    self.resize(min(self.width(),end-start),self.height())
                    candidate=QRect(start,bottom,self.width(),self.height())
                    if candidate.right()<=end and not candidate.intersects(rect):
                        position=(start,bottom)
                        break
        x,y=position or (left,14)
        self.move(self.host.mapToGlobal(QPoint(max(10,x), y)))
        self.spot.update()
        self.controller.update_status()

    def hideEvent(self, event):
        self.timer.stop()
        self.spot.hide()
        super().hideEvent(event)

    def reject(self):
        self.controller.minimize()

    def closeEvent(self, event):
        self.controller.minimize()
        event.accept()
