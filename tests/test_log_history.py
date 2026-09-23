import tempfile
import unittest
from pathlib import Path

from pyside_app.log_history import discover_logs, format_log_size, read_log_preview


class LogHistoryTests(unittest.TestCase):
    def test_discovers_current_and_archived_workflow_logs_newest_first(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "runtime"
            user = root / "user"
            current = output / ("wild-" + "a" * 32) / "project" / "easycon.log"
            archived = user / "logs" / "generated-plans" / ("tid-" + "b" * 32) / "run.log"
            current.parent.mkdir(parents=True)
            archived.parent.mkdir(parents=True)
            current.write_text("wild", encoding="utf-8")
            archived.write_text("tid", encoding="utf-8")
            current.touch()
            archived.touch()

            rows = discover_logs(output, user)

            self.assertEqual({row.workflow for row in rows}, {"野生 / 静态", "TID 乱数"})
            self.assertEqual({row.location_text for row in rows}, {"运行工程", "归档"})
            self.assertEqual({row.path for row in rows}, {current.resolve(), archived.resolve()})

    def test_discovers_legacy_runtime_siblings_without_duplicate_current_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = root / "runtime" / "pyside6" / ("egg-" + "a" * 32) / "run.log"
            legacy = root / "runtime" / "sid_reverse" / "sid-reverse-old.log"
            current.parent.mkdir(parents=True)
            legacy.parent.mkdir(parents=True)
            current.write_text("egg", encoding="utf-8")
            legacy.write_text("sid", encoding="utf-8")

            rows = discover_logs(root / "runtime" / "pyside6", root / "user")

            self.assertEqual(len(rows), 2)
            self.assertEqual({row.path for row in rows}, {current.resolve(), legacy.resolve()})

    def test_preview_removes_ansi_and_truncates_only_display_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "run.log"
            path.write_bytes(b"old line\n\x1b[31mnew line\x1b[0m\n")

            preview = read_log_preview(path, max_bytes=18)

            self.assertIn("仅显示末尾", preview)
            self.assertIn("new line", preview)
            self.assertNotIn("\x1b[", preview)
            self.assertIn(b"old line", path.read_bytes())

    def test_size_labels(self):
        self.assertEqual(format_log_size(12), "12 B")
        self.assertEqual(format_log_size(1536), "1.5 KiB")
        self.assertEqual(format_log_size(2 * 1024 * 1024), "2.0 MiB")

    def test_sid_traversal_filename_is_not_classified_as_sid_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log = root / "runtime" / "sid_traversal-session.log"
            log.parent.mkdir(parents=True)
            log.write_text("traversal", encoding="utf-8")

            rows = discover_logs(root / "runtime", root / "user")

            self.assertEqual(rows[0].workflow, "SID 遍历")


if __name__ == "__main__":
    unittest.main()
