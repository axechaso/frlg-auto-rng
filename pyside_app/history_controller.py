"""Independent, bounded history workers with last-request-wins delivery."""
import time
from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QTextCursor
from .jobs import Job
from .log_history import discover_logs, history_roots, read_log_preview


class HistoryController(QObject):
    delivery = Signal(str, str, int, object)
    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.jobs, self.pending, self.ids = {}, {}, {}
        self.handlers = {}
        self.delivery.connect(self._delivery)
        self.cache, self.cache_key, self.cache_at = (), None, 0
        self.preview_cache = {}
        self.closing = False
        self.selected_path = None
        self.first_selection = True
        self.applying = False
        self.batch_id = 0
        self.column, self.order = 0, Qt.SortOrder.DescendingOrder
        self.budget = 256 * 1024
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(180)
        self.debounce.timeout.connect(self.filter)
        window.history_table.model().sortRequested.connect(self.sort)
        window.history_more_button.clicked.connect(self.more)

    @property
    def busy(self):
        return bool(self.jobs or self.pending or self.applying or self.debounce.isActive())

    def _submit(self, kind, work, apply):
        token = self.ids.get(kind, 0) + 1
        self.ids[kind] = token
        request = (token, work, apply)
        if kind in self.jobs:
            self.jobs[kind].cancelled.set()
            self.pending[kind] = request
        else:
            self._launch(kind, request)

    def _launch(self, kind, request):
        token, work, apply = request
        job = Job(work, self)
        self.jobs[kind] = job
        self.handlers[kind] = apply
        job.succeeded.connect(lambda result: self.delivery.emit(kind, "result", token, result))
        job.failed.connect(lambda error: self.delivery.emit(kind, "error", token, error))
        job.status.connect(lambda message: self.delivery.emit(kind, "status", token, message))
        job.finished.connect(lambda: self.delivery.emit(kind, "finished", token, None))
        job.start()

    @Slot(str, str, int, object)
    def _delivery(self, kind, event, token, data):
        if event == "finished":
            job = self.jobs.pop(kind, None)
            if job:
                job.deleteLater()
            request = self.pending.pop(kind, None)
            if request and not self.closing:
                self._launch(kind, request)
            if self.closing and not self.jobs:
                QTimer.singleShot(0, self.w.close)
        elif not self.closing and token == self.ids[kind]:
            if event == "result":
                self.handlers[kind](data)
            elif event == "status":
                self.w.history_status.setText(data)
            else:
                self.w.history_status.setText(f"历史日志{kind}失败：{data}")
                if kind == "preview":
                    self.w.history_log_view.setPlainText(f"日志已失效或不可读：{data}")

    def refresh(self, *, force=False):
        key = history_roots(self.w.paths.output, self.w.paths.user)[0]
        if not force and key == self.cache_key and time.monotonic() - self.cache_at < 30:
            self.filter()
            return
        self.w.history_status.setText("正在后台扫描历史日志……")
        output, user = self.w.paths.output, self.w.paths.user
        def scanned(rows):
            self.cache, self.cache_key, self.cache_at = rows, key, time.monotonic()
            self.w.all_history_rows = rows
            self.filter()
        self._submit("scan", lambda cancel, status: discover_logs(output, user, cancelled=cancel, status=status), scanned)

    def invalidate(self):
        self.cache_at = 0

    def schedule_filter(self, *_):
        self.debounce.start()
        self.ids["filter"] = self.ids.get("filter", 0) + 1
        self.batch_id += 1
        self.applying = False

    def sort(self, column, order):
        if (column, order) == (self.column, self.order):
            return
        self.column, self.order = column, order
        self.schedule_filter()

    def filter(self):
        if self.closing:
            return
        rows = self.cache
        workflow = self.w.fields["history_workflow"].currentText()
        query = self.w.fields["history_search"].text().strip().casefold()
        column, reverse = self.column, self.order == Qt.SortOrder.DescendingOrder
        def work(cancel, _status):
            matches = []
            for row in rows:
                if cancel():
                    return ()
                if (workflow == "全部" or row.workflow == workflow) and (not query or query in row.search_text):
                    matches.append(row)
            keys = (lambda r: r.modified_ns, lambda r: r.workflow, lambda r: r.path.name.casefold(),
                    lambda r: r.size, lambda r: r.location_text)
            return tuple(sorted(matches, key=keys[column], reverse=reverse))
        self._submit("filter", work, self._apply_rows)

    def _apply_rows(self, rows):
        self.batch_id += 1
        token = self.batch_id
        model = self.w.history_table.model()
        scroll = self.w.history_table.verticalScrollBar().value()
        selected = self.selected_path
        self.applying = True
        self.w.history_rows = rows
        model.reset()
        def batch(offset=0):
            if token != self.batch_id or self.closing:
                return
            model.append(rows[offset:offset + 250])
            if offset + 250 < len(rows):
                QTimer.singleShot(0, lambda: batch(offset + 250))
                return
            index = next((i for i, row in enumerate(rows) if row.path == selected), None)
            if index is None and self.first_selection and rows:
                index = 0
                self.first_selection = False
            if index is not None:
                self.w.history_table.selectRow(index)
            elif selected:
                self.w.history_log_view.setPlainText("原选日志已被删除或不符合筛选；未选择其他文件。")
            else:
                self.w.history_log_view.setPlainText("没有找到符合条件的历史日志。" if not rows else "请选择日志查看尾部预览。")
            self.w.history_table.verticalScrollBar().setValue(scroll)
            self.applying = False
            self.w.history_status.setText(f"已显示 {len(rows)} / {len(self.cache)} 份日志；后台扫描缓存 30 秒。")
            self.preview()
        batch()

    def preview(self, *_):
        if self.applying or self.closing or self.w.current_page != "history_logs":
            return
        entry = self.w._selected_history_log()
        self.ids["preview"] = self.ids.get("preview", 0) + 1
        if entry is None:
            return
        if self.selected_path != entry.path:
            self.budget = 256 * 1024
        self.selected_path = entry.path
        budget, path = self.budget, entry.path
        def read(cancel, _status):
            stat = path.stat()
            key = (path, stat.st_mtime_ns, stat.st_size, budget)
            text = self.preview_cache.get(key)
            if text is None and not cancel():
                text = read_log_preview(path, max_bytes=budget, max_lines=3000 if budget == 256*1024 else 12000)
            return key, text
        def display(result):
            key, text = result
            if text is None or self.w.current_page != "history_logs" or self.selected_path != path:
                return
            self.preview_cache = {key: text}
            self.w.history_log_view.setPlainText(text)
            self.w.history_log_view.moveCursor(QTextCursor.MoveOperation.End)
            self.w.history_more_button.setEnabled(budget < 1024 * 1024 and key[2] > budget)
        self._submit("preview", read, display)

    def more(self):
        self.budget = min(1024*1024, self.budget + 256*1024)
        self.preview()

    def leave(self):
        self.ids["preview"] = self.ids.get("preview", 0) + 1
        if "preview" in self.jobs:
            self.jobs["preview"].cancelled.set()

    def shutdown(self):
        self.closing = True
        self.debounce.stop()
        self.batch_id += 1
        self.applying = False
        self.pending.clear()
        for job in self.jobs.values():
            job.cancelled.set()
        return not self.jobs
