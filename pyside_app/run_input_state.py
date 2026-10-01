"""Read-only asynchronous client for EasyCon's local input-state endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import time
from urllib.parse import urlencode

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from automation.input_state_protocol import SESSION_STATES, parse_input_session_marker


MAX_RESPONSE_BYTES = 256 * 1024
BUTTONS = frozenset({
    "A", "B", "X", "Y", "L", "R", "ZL", "ZR", "MINUS", "PLUS",
    "HOME", "CAPTURE", "LCLICK", "RCLICK",
})
HATS = frozenset({
    "CENTER", "TOP", "TOP_RIGHT", "RIGHT", "DOWN_RIGHT", "DOWN",
    "DOWN_LEFT", "LEFT", "TOP_LEFT",
})
CONNECTIONS = frozenset({"connected", "disconnected", "error", "unknown", "mock"})
NEUTRAL_SNAPSHOT = {
    "buttons": (), "hat": "CENTER", "left_stick": (128, 128), "right_stick": (128, 128),
}


def _strict_int(value, *, minimum: int, maximum: int, name: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"按键状态 {name} 无效")
    return value


def validate_snapshot(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"buttons", "hat", "left_stick", "right_stick"}:
        raise ValueError("按键状态快照字段无效")
    buttons = value["buttons"]
    if not isinstance(buttons, list) or len(buttons) > len(BUTTONS):
        raise ValueError("按键状态按钮列表无效")
    if any(not isinstance(button, str) or button not in BUTTONS for button in buttons):
        raise ValueError("按键状态包含未知按钮")
    if len(set(buttons)) != len(buttons):
        raise ValueError("按键状态按钮重复")
    hat = value["hat"]
    if not isinstance(hat, str) or hat not in HATS:
        raise ValueError("按键状态 HAT 无效")
    result = {"buttons": tuple(buttons), "hat": hat}
    for source, target in (("left_stick", "left_stick"), ("right_stick", "right_stick")):
        stick = value[source]
        if not isinstance(stick, list) or len(stick) != 2:
            raise ValueError(f"按键状态 {source} 坐标无效")
        result[target] = tuple(
            _strict_int(axis, minimum=0, maximum=255, name=f"{source} 坐标")
            for axis in stick
        )
    return result


def validate_input_response(
    payload: object,
    *,
    run_id: str,
    session_id: str,
    stage_id: str,
    last_seq: int,
) -> dict:
    if not isinstance(payload, dict) or type(payload.get("protocol")) is not int or payload.get("protocol") != 1:
        raise ValueError("按键状态协议版本不受支持")
    if payload.get("run_id") != run_id or payload.get("session_id") != session_id:
        raise ValueError("按键状态运行或子进程会话不匹配")
    if payload.get("stage_id") != stage_id:
        raise ValueError("按键状态阶段不匹配")
    seq = _strict_int(payload.get("seq"), minimum=0, maximum=2**63 - 1, name="序列号")
    server_ms = _strict_int(payload.get("server_ms"), minimum=0, maximum=2**63 - 1, name="单调时间")
    if seq < last_seq:
        raise ValueError("按键状态序列号倒退")
    source = payload.get("source")
    if source not in {"device_report", "mock"}:
        raise ValueError("按键状态来源无效")
    connection = payload.get("connection")
    if connection not in CONNECTIONS:
        raise ValueError("按键状态连接状态无效")
    history_gap = payload.get("history_gap")
    if type(history_gap) is not bool:
        raise ValueError("按键状态历史缺口标志无效")
    snapshot = validate_snapshot(payload.get("snapshot"))
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > 256:
        raise ValueError("按键状态事件列表无效")
    normalized_events = []
    prior = max(last_seq, 0)
    for event in events:
        if not isinstance(event, dict) or set(event) != {"seq", "at_ms", "snapshot"}:
            raise ValueError("按键状态事件字段无效")
        event_seq = _strict_int(event["seq"], minimum=1, maximum=seq, name="事件序列号")
        if event_seq != prior + 1:
            if not history_gap:
                raise ValueError("按键状态事件序列存在缺口")
            raise ValueError("历史缺口响应不得包含可重放事件")
        at_ms = _strict_int(event["at_ms"], minimum=0, maximum=server_ms, name="事件时间")
        normalized_events.append({
            "seq": event_seq,
            "at_ms": at_ms,
            "snapshot": validate_snapshot(event["snapshot"]),
        })
        prior = event_seq
    if events and normalized_events[-1]["seq"] != seq:
        raise ValueError("按键状态事件与最新序列号不一致")
    if events and not history_gap and snapshot != normalized_events[-1]["snapshot"]:
        raise ValueError("按键状态快照与最新事件不一致")
    if seq > max(last_seq, 0) and not events and not history_gap:
        raise ValueError("按键状态序列前进但没有事件或历史缺口标志")
    return {
        "seq": seq,
        "server_ms": server_ms,
        "source": source,
        "connection": connection,
        "snapshot": snapshot,
        "events": normalized_events,
        "history_gap": history_gap,
    }


def _transition(old: dict, new: dict) -> str:
    changes = []
    old_buttons = set(old["buttons"])
    new_buttons = set(new["buttons"])
    changes.extend(f"按下 {key}" for key in new["buttons"] if key not in old_buttons)
    changes.extend(f"松开 {key}" for key in old["buttons"] if key not in new_buttons)
    if old["hat"] != new["hat"]:
        changes.append(f"十字 {new['hat']}")
    for key, title in (("left_stick", "左摇杆"), ("right_stick", "右摇杆")):
        if old[key] != new[key]:
            changes.append(f"{title} ({new[key][0]}, {new[key][1]})")
    return "；".join(changes) or "控制状态更新"


@dataclass(frozen=True)
class RunInputView:
    run_id: str
    session_id: str
    stage_id: str
    phase: str
    connection: str
    source: str
    seq: int
    snapshot: dict
    recent_action: str
    recent_action_at: float
    recent_action_time: str
    history_gap: bool
    message: str


class RunInputStateModel:
    def __init__(self):
        self.run_id = ""
        self.session_id = ""
        self.stage_id = ""
        self.phase = "idle"
        self.connection = "unknown"
        self.source = "unknown"
        self.seq = -1
        self.snapshot = dict(NEUTRAL_SNAPSHOT)
        self.recent_action = ""
        self.recent_action_at = 0.0
        self.recent_action_time = ""
        self.history_gap = False
        self.message = "等待脚本运行"
        self.last_response_at = 0.0
        self.seen_sessions = set()
        self.session_state = ""

    def begin(self, run_id: str, session_id: str, stage_id: str = "run") -> None:
        self.run_id, self.session_id, self.stage_id = run_id, session_id, stage_id
        self.seen_sessions = {(session_id, stage_id)}
        self.session_state = ""
        self.phase = "starting"
        self.connection = "unknown"
        self.source = "unknown"
        self.seq = -1
        self.snapshot = dict(NEUTRAL_SNAPSHOT)
        self.recent_action = ""
        self.recent_action_at = 0.0
        self.recent_action_time = ""
        self.history_gap = False
        self.message = "正在启动"
        self.last_response_at = 0.0

    def set_session(self, marker: dict[str, str]) -> bool:
        if marker.get("run") != self.run_id or marker.get("state") not in SESSION_STATES:
            return False
        session_id, stage_id, state = marker["session"], marker["stage"], marker["state"]
        identity = (session_id, stage_id)
        current_identity = (self.session_id, self.stage_id)
        if identity != current_identity and identity in self.seen_sessions:
            return False
        rank = {"STARTING": 0, "SEARCHING": 0, "RUNNING": 1, "STOPPING": 2, "ENDED": 3, "FAILED": 3}
        if identity == current_identity and self.session_state and rank[state] < rank[self.session_state]:
            return False
        if identity != current_identity:
            self.session_id, self.stage_id = session_id, stage_id
            self.seen_sessions.add(identity)
            self.seq = -1
            self.snapshot = dict(NEUTRAL_SNAPSHOT)
            self.connection = "unknown"
            self.source = "unknown"
            self.recent_action = ""
            self.recent_action_at = 0.0
            self.recent_action_time = ""
            self.history_gap = False
            self.last_response_at = 0.0
        self.phase = state.casefold()
        self.session_state = state
        self.message = {
            "STARTING": "正在切换脚本阶段",
            "SEARCHING": "计算中，无按键输出",
            "RUNNING": "运行中",
            "STOPPING": "正在停止",
            "ENDED": "阶段已结束",
            "FAILED": "阶段失败",
        }[state]
        if state in {"SEARCHING", "ENDED", "FAILED"}:
            self.snapshot = dict(NEUTRAL_SNAPSHOT)
            self.connection = "unknown"
            self.source = "unknown"
            if state != "SEARCHING":
                self.recent_action = ""
                self.recent_action_at = 0.0
                self.recent_action_time = ""
        return True

    def apply_payload(self, payload: object) -> None:
        checked = validate_input_response(
            payload,
            run_id=self.run_id,
            session_id=self.session_id,
            stage_id=self.stage_id,
            last_seq=self.seq,
        )
        if checked["history_gap"]:
            self.history_gap = True
            self.recent_action = "近期操作记录不完整"
            self.recent_action_at = time.monotonic()
            self.recent_action_time = datetime.now().strftime("%H:%M:%S")
        elif checked["events"]:
            previous = self.snapshot
            recent_action = ""
            for event in checked["events"]:
                action = _transition(previous, event["snapshot"])
                if action != "控制状态更新":
                    recent_action = action
                previous = event["snapshot"]
            if recent_action:
                self.recent_action = recent_action
                self.recent_action_at = time.monotonic()
                self.recent_action_time = datetime.now().strftime("%H:%M:%S")
        self.seq = checked["seq"]
        self.source = checked["source"]
        self.connection = checked["connection"]
        if self.connection in {"error", "disconnected", "unknown"}:
            self.snapshot = dict(NEUTRAL_SNAPSHOT)
            self.message = "设备状态未知；显示已清除"
        else:
            self.snapshot = checked["snapshot"]
            self.message = "模拟状态" if self.source == "mock" else "正在接收设备报告"
        self.phase = "running"
        self.last_response_at = time.monotonic()

    def mark_unavailable(self, message: str, *, phase: str = "unknown") -> None:
        self.phase = phase
        self.connection = "unknown"
        self.snapshot = dict(NEUTRAL_SNAPSHOT)
        self.message = message

    def mark_stale(self) -> None:
        self.phase = "stale"
        self.connection = "unknown"
        self.snapshot = dict(NEUTRAL_SNAPSHOT)
        self.message = "状态未知；正在重连"

    def end(self, message: str = "运行已结束", *, phase: str = "ended") -> None:
        self.phase = phase
        self.connection = "unknown"
        self.snapshot = dict(NEUTRAL_SNAPSHOT)
        self.message = message

    def view(self) -> RunInputView:
        return RunInputView(
            self.run_id, self.session_id, self.stage_id, self.phase, self.connection,
            self.source, self.seq, dict(self.snapshot), self.recent_action,
            self.recent_action_at, self.recent_action_time, self.history_gap, self.message,
        )


class RunInputStateClient(QObject):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = RunInputStateModel()
        self.manager = QNetworkAccessManager(self)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(50)
        self.poll_timer.timeout.connect(self._poll)
        self.health_timer = QTimer(self)
        self.health_timer.setInterval(250)
        self.health_timer.timeout.connect(self._check_stale)
        self.timeout_timer = QTimer(self)
        self.timeout_timer.setSingleShot(True)
        self.timeout_timer.timeout.connect(self._timeout)
        self.base_url = QUrl()
        self._pending = None
        self._pending_identity = None
        self._pending_kind = ""
        self._generation = 0
        self._retry_after = 0.0
        self._capabilities_ok = False
        self._stopped = True
        self._visible = True

    def _emit(self):
        self.changed.emit(self.model.view())

    def start(self, url: str, run_id: str, session_id: str, stage_id: str = "run") -> None:
        self.stop()
        self.model.begin(run_id, session_id, stage_id)
        self.base_url = QUrl(url)
        self._capabilities_ok = False
        if (
            not self.base_url.isValid()
            or self.base_url.scheme() != "http"
            or self.base_url.host() not in {"127.0.0.1", "localhost", "::1"}
        ):
            self.model.mark_unavailable("此后端不提供按键回显", phase="unsupported")
            self._emit()
            return
        self._stopped = False
        self._generation += 1
        self._retry_after = 0.0
        self.poll_timer.setInterval(50 if self._visible else 250)
        self.poll_timer.start()
        self.health_timer.start()
        self._request("capabilities")
        self._emit()

    def stop(self, *, message: str | None = None, phase: str = "ended") -> None:
        self._stopped = True
        self._generation += 1
        self.poll_timer.stop()
        self.health_timer.stop()
        self.timeout_timer.stop()
        if self._pending is not None:
            self._pending.abort()
            self._pending = None
            self._pending_identity = None
        if message:
            self.model.end(message, phase=phase)
            self._emit()

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        if not self._stopped:
            self.poll_timer.setInterval(50 if self._visible else 250)

    def expect_session(self, line: str) -> bool:
        marker = parse_input_session_marker(line)
        previous_identity = (self.model.run_id, self.model.session_id, self.model.stage_id)
        if marker is None or not self.model.set_session(marker):
            return False
        identity = (self.model.run_id, self.model.session_id, self.model.stage_id)
        if identity != previous_identity:
            self._generation += 1
            self._capabilities_ok = False
            self._retry_after = 0.0
            self._abort_pending()
        state = marker["state"]
        if state in {"SEARCHING", "ENDED", "FAILED"}:
            self.poll_timer.stop()
            self._abort_pending()
        elif not self._stopped:
            self.poll_timer.setInterval(50 if self._visible else 250)
            self.poll_timer.start()
            self._poll()
        if state == "ENDED":
            self.model.end("阶段已结束")
        elif state == "FAILED":
            self.model.end("阶段失败", phase="failed")
        self._emit()
        return True

    def _abort_pending(self) -> None:
        if self._pending is None:
            return
        reply, self._pending = self._pending, None
        self._pending_identity = None
        self.timeout_timer.stop()
        reply.abort()

    def _request(self, kind: str) -> None:
        if self._stopped or self._pending is not None:
            return
        if kind == "input-state" and self.model.phase in {"searching", "ended", "failed"}:
            return
        url = QUrl(self.base_url)
        url.setPath("/capabilities" if kind == "capabilities" else "/input-state")
        if kind == "input-state":
            url.setQuery(urlencode({"after_seq": max(0, self.model.seq)}))
        request = QNetworkRequest(url)
        request.setTransferTimeout(1000)
        reply = self.manager.get(request)
        self._pending = reply
        self._pending_kind = kind
        self._pending_identity = (
            self.model.run_id, self.model.session_id, self.model.stage_id, self._generation,
        )
        reply.finished.connect(lambda current=reply: self._finished(current))
        self.timeout_timer.start(1000)

    def _poll(self) -> None:
        if self._stopped or self._pending is not None or time.monotonic() < self._retry_after:
            return
        self._request("input-state" if self._capabilities_ok else "capabilities")

    def _timeout(self) -> None:
        if self._pending is not None:
            self._pending.abort()

    def _finished(self, reply) -> None:
        if reply is not self._pending:
            reply.deleteLater()
            return
        kind = self._pending_kind
        expected = self._pending_identity
        self._pending = None
        self._pending_identity = None
        self.timeout_timer.stop()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        data = bytes(reply.readAll())
        error = reply.error()
        reply.deleteLater()
        if expected != (
            self.model.run_id, self.model.session_id, self.model.stage_id, self._generation,
        ):
            return
        if status == 404:
            self._stopped = True
            self.poll_timer.stop()
            self.model.mark_unavailable("此后端不提供按键回显", phase="unsupported")
            self._emit()
            return
        if error != QNetworkReply.NetworkError.NoError or status != 200:
            self._retry_after = time.monotonic() + 0.25
            self.model.mark_unavailable("按键状态连接中断；文本日志仍在运行", phase="disconnected")
            self._emit()
            return
        if len(data) > MAX_RESPONSE_BYTES:
            self._retry_after = time.monotonic() + 0.25
            self.model.mark_unavailable("按键状态响应超过容量限制", phase="error")
            self._emit()
            return
        try:
            payload = json.loads(data.decode("utf-8"))
            if kind == "capabilities":
                if (
                    not isinstance(payload, dict)
                    or type(payload.get("input_state_protocol")) is not int
                    or payload.get("input_state_protocol") != 1
                ):
                    raise ValueError("按键状态协议版本不受支持")
                self._capabilities_ok = True
            else:
                self.model.apply_payload(payload)
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self._retry_after = time.monotonic() + 0.25
            self.model.mark_unavailable(f"按键状态无效：{exc}", phase="error")
        else:
            self._retry_after = 0.0
        self._emit()

    def _check_stale(self) -> None:
        if (
            not self._stopped
            and self.model.phase == "running"
            and self.model.last_response_at
            and time.monotonic() - self.model.last_response_at > 1.5
        ):
            self.model.mark_stale()
            self._emit()


__all__ = [
    "BUTTONS", "HATS", "MAX_RESPONSE_BYTES", "RunInputStateClient",
    "RunInputStateModel", "RunInputView", "validate_input_response", "validate_snapshot",
]
