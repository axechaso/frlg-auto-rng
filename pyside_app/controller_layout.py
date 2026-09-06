"""Physical controller layout and Qt-only keyboard mapping."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QKeySequenceEdit, QLineEdit, QPushButton, QWidget

DEFAULT_KEYS = {
    "A": "c", "B": "x", "X": "v", "Y": "z", "L": "q", "R": "e", "ZL": "r", "ZR": "t",
    "MINUS": "o", "PLUS": "p", "CAPTURE": "n", "HOME": "b", "LCLICK": "f", "RCLICK": "g",
    "TOP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right",
    "LS_UP": "w", "LS_DOWN": "s", "LS_LEFT": "a", "LS_RIGHT": "d",
    "RS_UP": "i", "RS_DOWN": "k", "RS_LEFT": "j", "RS_RIGHT": "l",
    "TOP_LEFT": "", "TOP_RIGHT": "", "DOWN_LEFT": "", "DOWN_RIGHT": "",
}
DIAGONALS = {"TOP_LEFT", "TOP_RIGHT", "DOWN_LEFT", "DOWN_RIGHT"}
LEGACY_KEYS = {key for key in DEFAULT_KEYS if not key.startswith(("LS_", "RS_"))} - DIAGONALS
LABELS = {"MINUS": "−", "PLUS": "+", "CAPTURE": "截图", "HOME": "HOME", "LCLICK": "L 按下", "RCLICK": "R 按下",
          "TOP": "十字 ↑", "DOWN": "十字 ↓", "LEFT": "十字 ←", "RIGHT": "十字 →",
          "TOP_LEFT": "十字 ↖", "TOP_RIGHT": "十字 ↗", "DOWN_LEFT": "十字 ↙", "DOWN_RIGHT": "十字 ↘"}
for prefix, title in (("LS", "左"), ("RS", "右")):
    LABELS.update({f"{prefix}_{direction}": f"{title} {arrow}" for direction, arrow in (("UP", "↑"), ("DOWN", "↓"), ("LEFT", "←"), ("RIGHT", "→"))})
# Button centers in a 760 x 440 controller diagram, matching the hardware.
POSITIONS = {
    "ZL": (180, 28), "ZR": (600, 28), "L": (180, 78), "R": (600, 78),
    "LS_UP": (180, 134), "LS_LEFT": (114, 184), "LCLICK": (180, 184), "LS_RIGHT": (246, 184), "LS_DOWN": (180, 234),
    "X": (600, 134), "Y": (534, 184), "A": (666, 184), "B": (600, 234),
    "MINUS": (324, 134), "PLUS": (456, 134), "CAPTURE": (346, 204), "HOME": (434, 204),
    "TOP": (282, 284), "LEFT": (216, 334), "RIGHT": (348, 334), "DOWN": (282, 384),
    "TOP_LEFT": (216, 284), "TOP_RIGHT": (348, 284), "DOWN_LEFT": (216, 384), "DOWN_RIGHT": (348, 384),
    "RS_UP": (494, 262), "RS_LEFT": (428, 312), "RCLICK": (494, 312), "RS_RIGHT": (560, 312), "RS_DOWN": (494, 362),
}


def normalize_key(value):
    if not isinstance(value, str):
        raise ValueError("键位必须是键盘按键名称")
    if not value.strip():
        return ""
    sequence = QKeySequence.fromString(str(value).strip(), QKeySequence.SequenceFormat.PortableText)
    if sequence.count() != 1 or sequence[0].key() in (
        Qt.Key.Key_unknown, Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
    ):
        raise ValueError("每项请填写一个键盘按键或组合键")
    if sequence[0].key() == Qt.Key.Key_Escape:
        raise ValueError("Esc 用于关闭手柄浮窗，请选择其他按键")
    return sequence.toString(QKeySequence.SequenceFormat.PortableText).casefold()


def validate_mapping(mapping):
    if not isinstance(mapping, dict) or set(mapping) != set(DEFAULT_KEYS):
        raise ValueError("键位配置不完整")
    values = {key: normalize_key(value) for key, value in mapping.items()}
    assigned = [value for value in values.values() if value]
    if len(set(assigned)) != len(assigned):
        raise ValueError("键盘按键不能重复映射")
    return values


def load_mapping_values(mapping):
    if not isinstance(mapping, dict) or set(mapping) not in (LEGACY_KEYS, set(DEFAULT_KEYS) - DIAGONALS):
        return validate_mapping(mapping)
    # Keep every existing binding. New axes use their preferred key when free,
    # otherwise an unused function key. Saving writes a separate Qt config.
    values = {key: normalize_key(value) for key, value in mapping.items()}
    used = set(values.values())
    for key, preferred in DEFAULT_KEYS.items():
        if key not in values:
            if not preferred:
                values[key] = ""
                continue
            value = next(value for value in (preferred, *(f"f{i}" for i in range(1, 25))) if value not in used)
            values[key] = value
            used.add(value)
    return validate_mapping(values)


class MappingEdit(QKeySequenceEdit):
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.clear()
            event.accept()
            return
        super().keyPressEvent(event)


class ControllerLayout(QWidget):
    def __init__(self, mapping, parent=None, *, editing=False):
        super().__init__(parent)
        self.editing = editing
        self.controls = {}
        self.setMinimumSize(650, 376)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
        for key in POSITIONS:
            if editing:
                widget = MappingEdit(QKeySequence(mapping[key]), self)
                widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                widget.setMaximumSequenceLength(1)
                widget.setToolTip("点击后按下要映射的键；Esc 清空此项。")
                line = widget.findChild(QLineEdit)
                line.setPlaceholderText("未分配")
                line.setAlignment(Qt.AlignmentFlag.AlignCenter)
                widget.setStyleSheet("QKeySequenceEdit {padding:2px; border:1px solid #cbd6eb; border-radius:6px; background:white;} QKeySequenceEdit:focus {border-color:#6177f2; background:#f2f5ff;} QLineEdit {border:none; padding:0; background:transparent; font-size:12px; color:#314965;}")
            else:
                widget = QPushButton(self)
                widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                widget.setProperty("padKey", True)
                widget.setAutoDefault(False)
            widget.setAccessibleName(LABELS.get(key, key))
            self.controls[key] = widget
        if not editing:
            self.refresh(mapping, set())

    def sizeHint(self):
        return QSize(760, 440)

    def transform(self):
        scale = min(self.width() / 760, self.height() / 440)
        return scale, (self.width() - 760 * scale) / 2, (self.height() - 440 * scale) / 2

    def resizeEvent(self, event):
        scale, dx, dy = self.transform()
        for key, (x, y) in POSITIONS.items():
            top = y - 20 + (15 if self.editing else 0)
            height = 28 if self.editing else 44
            self.controls[key].setGeometry(QRect(round(dx + (x - 30) * scale), round(dy + top * scale), round(60 * scale), round(height * scale)))
        super().resizeEvent(event)

    def refresh(self, mapping, pressed):
        for key, button in self.controls.items():
            button.setText(f"{LABELS.get(key, key)}\n{QKeySequence(mapping[key]).toString() or '未分配'}")
            active = key in pressed
            if button.property("active") != active:
                button.setProperty("active", active)
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, dx, dy = self.transform()
        p.translate(dx, dy)
        p.scale(scale, scale)
        body = QPainterPath()
        body.moveTo(170, 95)
        body.cubicTo(110, 95, 86, 125, 68, 210)
        body.lineTo(35, 355)
        body.cubicTo(18, 431, 105, 453, 143, 395)
        body.lineTo(171, 353)
        body.lineTo(589, 353)
        body.lineTo(617, 395)
        body.cubicTo(655, 453, 742, 431, 725, 355)
        body.lineTo(692, 210)
        body.cubicTo(674, 125, 650, 95, 590, 95)
        body.closeSubpath()
        p.setPen(QPen(QColor("#b9c7df"), 2))
        p.setBrush(QColor("#e7edf8"))
        p.drawPath(body)
        p.setBrush(QColor("#d8e1f1"))
        for x, y in ((180, 184), (494, 312)):
            p.drawEllipse(QRectF(x - 49, y - 49, 98, 98))
        p.drawRoundedRect(QRectF(265, 297, 34, 74), 5, 5)
        p.drawRoundedRect(QRectF(245, 317, 74, 34), 5, 5)
        if self.editing:
            p.setPen(QColor("#526680"))
            p.setFont(QFont("Microsoft YaHei UI", 8))
            for key, (x, y) in POSITIONS.items():
                p.drawText(QRectF(x - 38, y - 20, 76, 16), Qt.AlignmentFlag.AlignCenter, LABELS.get(key, key))
        p.end()
