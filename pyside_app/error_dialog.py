"""One read-only error presentation shared by formal PySide6 dialogs."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from .diagnostics import brief_error, explain_popup_error


def create_error_dialog(parent, title, text):
    original = str(text)
    explanation = explain_popup_error(original, context=title)
    dialog = QMessageBox(QMessageBox.Icon.Warning, title, explanation.summary,
                         QMessageBox.StandardButton.Ok, parent)
    dialog.setObjectName("diagnosticErrorDialog")
    dialog.setTextFormat(Qt.TextFormat.PlainText)
    dialog.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
    # The short original error stays visible even for a generic diagnosis;
    # full tracebacks, paths and field names remain available in Details.
    advice = explanation.message.removeprefix(explanation.summary + "\n\n")
    dialog.setInformativeText("原始错误：\n" + brief_error(original) + "\n\n" + advice)
    dialog.setDetailedText(original)
    dialog.button(QMessageBox.StandardButton.Ok).setText("确定")
    for button in dialog.buttons():
        if dialog.buttonRole(button) == QMessageBox.ButtonRole.ActionRole:
            button.setText("查看详细信息")
            expanded = False

            def toggle_details_label(checked=False, *, details_button=button):
                nonlocal expanded
                expanded = not expanded
                details_button.setText("收起详细信息" if expanded else "查看详细信息")

            button.clicked.connect(toggle_details_label)
    return dialog


def show_error_dialog(parent, title, text):
    dialog = create_error_dialog(parent, title, text)
    try:
        return dialog.exec()
    finally:
        dialog.deleteLater()
