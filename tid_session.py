"""Durable TID UI drafts and worker-owned exhaustive search checkpoints."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from automation.tid_calibration import tid_request_from_dict
from automation.tid_checkpoint import ANSI, DONE_MARKER, parse_checkpoint, validate_checkpoint


def write_json_atomic(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_tid_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != 1 or not isinstance(payload.get("values"), dict):
            raise ValueError("格式或版本不支持")
        if any(not isinstance(key, str) or type(value) not in (str, bool) for key, value in payload["values"].items()):
            raise ValueError("参数类型不支持")
        return payload
    except (OSError, ValueError) as exc:
        raise ValueError(f"TID参数读取失败，原文件保留：{exc}") from exc


def progress_context(request, game: str, template_sha256: str, flow_request: dict | None = None) -> dict:
    if game not in ("火红", "叶绿"):
        raise ValueError("TID进度必须区分火红/叶绿")
    if not isinstance(template_sha256, str) or len(template_sha256) != 64:
        raise ValueError("TID进度缺少模板指纹")
    request.validate()
    return {"schema": 1, "game": game, "request": request.to_dict(),
            "template_sha256": template_sha256, "flow_request": flow_request}


def progress_path(directory: Path, context: dict) -> Path:
    key = hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return Path(directory) / (key + ".json")


def read_progress(directory: Path, context: dict) -> dict | None:
    path = progress_path(directory, context)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != 1 or payload.get("context") != context:
            raise ValueError("进度与当前参数不一致")
        if payload.get("status") not in ("running", "paused", "completed"):
            raise ValueError("进度状态无效")
        if payload.get("state") is not None:
            validate_checkpoint(payload["state"], tid_request_from_dict(context["request"]))
        return payload
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"TID进度读取失败，未覆盖原文件：{exc}") from exc


@contextmanager
def progress_lease(path: Path):
    """OS lock released even if the worker/console is forcibly terminated."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("同一TID穷举任务仍在其他窗口运行，请先停止该运行器") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class TidProgressSession:
    def __init__(self, directory: Path, context: dict, *, resume: bool = True, warning=print):
        self.directory = Path(directory)
        self.context = context
        self.request = tid_request_from_dict(context["request"])
        self.path = progress_path(self.directory, context)
        self.resume = resume
        self.warning = warning
        self.state = None
        self.completed = False
        self.failed = False

    def __enter__(self):
        self.lease = progress_lease(self.path.with_suffix(".lock"))
        self.lease.__enter__()
        try:
            old = read_progress(self.directory, self.context) if self.resume else None
            if self.resume and old and old["status"] != "completed":
                self.state = old["state"]
            self.save("running")
        except BaseException:
            self.lease.__exit__(None, None, None)
            raise
        return self

    def save(self, status):
        write_json_atomic(self.path, {"schema": 1, "context": self.context,
            "state": self.state, "status": status, "pid": os.getpid(),
            "updated_at": datetime.now(timezone.utc).isoformat()})

    def feed(self, line: str):
        try:
            state = parse_checkpoint(line, self.request)
            if state is not None and not self.completed:
                self.state = state
                self.save("running")
            if DONE_MARKER in ANSI.sub("", line):
                self.completed = True
                self.save("completed")
        except (OSError, ValueError) as exc:
            if not self.failed:
                self.warning(f"[TID进度警告] 本次进度未能保存：{exc}；请保留运行日志。")
            self.failed = True

    def __exit__(self, *args):
        try:
            self.save("completed" if self.completed else "paused")
        except OSError as exc:
            self.warning(f"[TID进度警告] 停止状态未写入：{exc}；此前完整检查点仍保留。")
        finally:
            self.lease.__exit__(*args)
