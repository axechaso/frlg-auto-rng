"""Small Qt worker with cooperative cancellation and GUI-thread delivery."""
import threading
from PySide6.QtCore import QThread, Signal


class Job(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    status = Signal(str)

    def __init__(self, work, parent=None):
        super().__init__(parent)
        self.work = work
        self.cancelled = threading.Event()

    def run(self):
        try:
            result = self.work(self.cancelled.is_set, self.status.emit)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
