"""Persistent checkpoints for wild and supported static SID traversal.

SID traversal is deliberately separate from the ordinary SID reverse-capture
flow.  A traversal candidate is a destructive, real-console attempt, so the
checkpoint is written *before* launching EasyCon and is advanced only after a
normal, explicitly non-shiny completion.  This makes an interrupted run
retry the same candidate instead of silently skipping it.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from rng.sid_reverse import pid_to_psv, sid_at_advance, sid_candidates_for_psv
from automation.sid_observation import validate_observation


SCHEMA = 3
DEFAULT_START_ADVANCE = 1901
NAMED_RIVAL_START_ADVANCE = 1900
SID_ADVANCE_STEP = 2
DEFAULT_MAX_ADVANCES = 10_000
DEFAULT_TARGET_MAX_ADVANCES = 3_000
TERMINAL_STATUSES = frozenset({"completed", "exhausted", "paused"})


def sid_traversal_start_advance(
    named_rival: bool,
    override: int | None = None,
) -> int:
    """Return the default or explicitly selected first SID ADV.

    The override is intentionally opt-in for advanced users.  It is stored in
    the immutable traversal context, so a changed manual start gets a fresh
    checkpoint instead of silently taking over an existing run.
    """
    expected_parity = 0 if bool(named_rival) else 1
    if override is None:
        return NAMED_RIVAL_START_ADVANCE if bool(named_rival) else DEFAULT_START_ADVANCE
    override = int(override)
    if override < 0:
        raise ValueError("SID 遍历自定义起点不能为负数")
    if override % SID_ADVANCE_STEP != expected_parity:
        parity_name = "偶数" if expected_parity == 0 else "奇数"
        raise ValueError(
            f"SID 遍历自定义起点必须是{parity_name}（当前劲敌取名设置对应的可执行 ADV 奇偶）"
        )
    return override


def traversal_context(
    *,
    tid: int,
    named_rival: bool,
    wild_request: dict,
    easycon_options: dict,
    source_sha256: str,
    max_advances: int,
    start_advance: int | None = None,
    target_max_advances: int = DEFAULT_TARGET_MAX_ADVANCES,
    template_name: str = "NS火叶全自动一键乱数2.0.ecs",
    encounter_kind: str = "wild",
    route_key: str | None = None,
    static_category: str | None = None,
    save_context: dict | None = None,
    effective_frame_parity_scheme: int = 1,
    mystery_gift_enabled: bool = False,
    verification_protocol: int = 1,
) -> dict:
    """Build the immutable identity used to isolate progress files.

    The complete wild request and materialized script inputs are included so a
    changed target, location, template, or runtime option can never resume an
    unrelated traversal.  The returned object contains only JSON primitives.
    """
    tid = int(tid)
    max_advances = int(max_advances)
    target_max_advances = int(target_max_advances)
    if not 0 <= tid <= 0xFFFF:
        raise ValueError("TID 必须在 0-65535 之间")
    if max_advances <= 0:
        raise ValueError("SID 遍历最大 ADV 必须大于 0")
    if target_max_advances <= 0:
        raise ValueError("SID 遍历低帧目标搜索上限必须大于 0")
    if not isinstance(wild_request, dict) or not isinstance(easycon_options, dict):
        raise ValueError("SID 遍历请求和 EasyCon 选项必须是对象")
    if encounter_kind not in {"wild", "static"}:
        raise ValueError("SID 遍历遭遇类型无效")
    if type(effective_frame_parity_scheme) is not int or effective_frame_parity_scheme not in (0, 1):
        raise ValueError("SID 遍历有效帧奇偶方案必须是0或1")
    if type(mystery_gift_enabled) is not bool:
        raise ValueError("SID 遍历神秘礼物状态必须是布尔值")
    if type(verification_protocol) is not int or verification_protocol != 1:
        raise ValueError("SID 遍历目标证明协议不受支持")
    if save_context is not None and not isinstance(save_context, dict):
        raise ValueError("SID 遍历存档快照必须是对象")
    if mystery_gift_enabled and effective_frame_parity_scheme != 1:
        raise ValueError("神秘礼物已开启时，SID 遍历帧奇偶必须使用方案 1")
    option_parity = easycon_options.get("frame_parity_scheme")
    if option_parity != effective_frame_parity_scheme:
        raise ValueError("SID 遍历有效帧奇偶与 EasyCon 选项不一致")
    option_gift = easycon_options.get("mystery_gift_enabled")
    if option_gift is not None and option_gift is not mystery_gift_enabled:
        raise ValueError("SID 遍历存档礼物状态与 EasyCon 选项不一致")
    source_sha256 = str(source_sha256).lower()
    if len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256):
        raise ValueError("SID 遍历缺少有效的脚本指纹")
    # ``asdict`` and callers commonly contain tuples.  JSON loads them back
    # as lists, so canonicalize through the same serializer before hashing and
    # persisting the context; otherwise a resumed process would reject its
    # own checkpoint as a different task.
    def json_primitives(value):
        if isinstance(value, dict):
            return {
                str(key): json_primitives(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, (list, tuple)):
            return [json_primitives(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        raise ValueError("SID 遍历上下文包含不可序列化参数")

    resolved_start = sid_traversal_start_advance(named_rival, start_advance)
    if resolved_start > max_advances:
        raise ValueError("SID 遍历起点不能大于最大 ADV")
    return {
        "schema": SCHEMA,
        "kind": "sid-traversal",
        "tid": tid,
        "named_rival": bool(named_rival),
        # 1.3.7 SID计算_奇/偶 selects the route by ADV parity.  The
        # no-name route is odd, the named-rival route is even, and traversal
        # must advance by two so it never submits the other route's parity.
        "sid_advance_parity": 0 if bool(named_rival) else 1,
        "sid_advance_step": SID_ADVANCE_STEP,
        "start_sid_advance": resolved_start,
        "max_advances": max_advances,
        "target_max_advances": target_max_advances,
        "template_name": str(template_name),
        "encounter_kind": encounter_kind,
        "route_key": None if route_key is None else str(route_key),
        "static_category": None if static_category is None else str(static_category),
        "save_context": json_primitives(save_context or {}),
        "effective_frame_parity_scheme": effective_frame_parity_scheme,
        "mystery_gift_enabled": mystery_gift_enabled,
        "verification_protocol": verification_protocol,
        "wild_request": json_primitives(wild_request),
        "easycon_options": json_primitives(easycon_options),
        "source_sha256": source_sha256,
    }


def progress_path(directory: str | Path, context: dict) -> Path:
    """Return the stable, context-isolated checkpoint path."""
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    key = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return Path(directory) / (key + ".json")


def write_json_atomic(path: str | Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_state(state: dict, context: dict) -> None:
    if not isinstance(state, dict):
        raise ValueError("SID 遍历进度状态不是对象")
    max_advances = int(context["max_advances"])
    start = int(context["start_sid_advance"])
    parity = int(context.get("sid_advance_parity", start % SID_ADVANCE_STEP))
    step = int(context.get("sid_advance_step", SID_ADVANCE_STEP))
    if step != SID_ADVANCE_STEP or parity not in (0, 1):
        raise ValueError("SID 遍历奇偶步进上下文无效")
    if start % step != parity:
        raise ValueError("SID 遍历起点与奇偶约束不一致")
    next_advance = int(state.get("next_sid_advance", start))
    # max_advances is inclusive.  The exhausted cursor is the next candidate
    # after the final matching-parity ADV, which can be max+1 or max+2.
    if not start <= next_advance <= max_advances + step:
        raise ValueError("SID 遍历 next ADV 超出当前任务范围")
    if next_advance % step != parity:
        raise ValueError("SID 遍历 next ADV 与奇偶约束不一致")
    current = state.get("current_sid_advance")
    if current is not None:
        current = int(current)
        if not start <= current <= max_advances:
            raise ValueError("SID 遍历当前 ADV 超出当前任务范围")
        # A current candidate is never allowed to be behind the resume point.
        if next_advance != current:
            raise ValueError("SID 遍历当前候选与 next ADV 不一致")
        if current % step != parity:
            raise ValueError("SID 遍历当前 ADV 与奇偶约束不一致")
        sid = state.get("current_sid")
        if sid is None or not 0 <= int(sid) <= 0xFFFF:
            raise ValueError("SID 遍历当前 SID 无效")
        expected = sid_at_advance(int(context["tid"]), current)
        if int(sid) != expected:
            raise ValueError("SID 遍历当前 SID 与 ADV 不一致")
    attempts = int(state.get("attempt_count", 0))
    if attempts < 0:
        raise ValueError("SID 遍历尝试次数不能为负数")
    status = state.get("status", "paused")
    if status not in {"running", "paused", "completed", "exhausted"}:
        raise ValueError("SID 遍历状态无效")
    hit_advance = state.get("hit_sid_advance")
    if hit_advance is not None and not start <= int(hit_advance) <= max_advances:
        raise ValueError("SID 遍历命中 ADV 无效")
    if hit_advance is not None and int(hit_advance) % step != parity:
        raise ValueError("SID 遍历命中 ADV 与奇偶约束不一致")
    if type(state.get("tested_non_shiny_count", 0)) is not int or state.get("tested_non_shiny_count", 0) < 0:
        raise ValueError("SID 遍历实测非闪计数无效")
    if type(state.get("skipped_count", 0)) is not int or state.get("skipped_count", 0) < 0:
        raise ValueError("SID 遍历窗口跳过计数无效")
    candidate_phase = state.get("candidate_phase", "idle")
    if candidate_phase not in {
        "idle", "searching", "generating", "running", "validating", "paused",
        "search_work_limit", "search_cancelled", "non_target_shiny", "missing_proof",
        "runner_failed", "generation_error", "stopped",
    }:
        raise ValueError("SID 遍历候选阶段无效")
    attempt_id = state.get("attempt_id")
    if attempt_id is not None and (
        not isinstance(attempt_id, str)
        or len(attempt_id) != 32
        or any(character not in "0123456789abcdef" for character in attempt_id)
    ):
        raise ValueError("SID 遍历尝试 ID 无效")
    for key in ("target_snapshot", "last_candidate", "hit_evidence"):
        value = state.get(key)
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"SID 遍历 {key} 必须是对象")
    evidence = state.get("pid_observations", [])
    excluded = state.get("excluded_tsvs", [])
    confirmed = state.get("confirmed_tsv")
    if not isinstance(evidence, list) or not isinstance(excluded, list):
        raise ValueError("SID 遍历 TSV 证据必须是列表")
    expected_excluded, expected_confirmed, seen = set(), None, set()
    for value in evidence:
        observation = validate_observation(value)
        key = (observation.run_id, observation.attempt_id, observation.round)
        if key in seen:
            raise ValueError("SID 遍历 TSV 证据重复")
        seen.add(key)
        psv = pid_to_psv(observation.pid)
        if observation.shiny:
            if expected_confirmed is not None and expected_confirmed != psv:
                raise ValueError("SID 遍历闪光 TSV 证据冲突")
            expected_confirmed = psv
        else:
            expected_excluded.add(psv)
    if any(type(v) is not int or not 0 <= v <= 8191 for v in excluded) or len(excluded) != len(set(excluded)):
        raise ValueError("SID 遍历排除 TSV 无效")
    if set(excluded) != expected_excluded or confirmed != expected_confirmed or (
        confirmed is not None and (type(confirmed) is not int or confirmed in expected_excluded)
    ):
        raise ValueError("SID 遍历 TSV 约束与 PID 证据不一致")
    if type(state.get("evidence_skipped_count", 0)) is not int or state.get("evidence_skipped_count", 0) < 0:
        raise ValueError("SID 遍历证据跳过计数无效")


def read_progress(directory: str | Path, context: dict) -> dict | None:
    """Read a checkpoint without replacing a malformed or stale file."""
    path = progress_path(directory, context)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            raise ValueError("进度版本不支持")
        if payload.get("context") != context:
            raise ValueError("进度与当前 SID 遍历参数不一致")
        state = payload.get("state")
        _validate_state(state, context)
        if payload.get("status") not in {"running", "paused", "completed", "exhausted"}:
            raise ValueError("SID 遍历进度状态无效")
        return payload
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        raise ValueError(f"SID 遍历进度读取失败，原文件保留：{exc}") from exc


@contextmanager
def progress_lease(path: str | Path):
    """Acquire an OS lock for one traversal context."""
    path = Path(path)
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
            raise RuntimeError("同一 SID 遍历任务仍在其他窗口运行，请先停止该运行器") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class SIDTraversalSession:
    """Own one durable SID traversal checkpoint under an OS lease."""

    def __init__(self, directory: str | Path, context: dict, *, resume: bool = True, warning=print):
        self.directory = Path(directory)
        self.context = context
        self.path = progress_path(self.directory, context)
        self.resume = bool(resume)
        self.warning = warning
        self.state: dict = {}
        self.completed = False

    def _new_state(self) -> dict:
        return {
            "status": "running",
            "next_sid_advance": int(self.context["start_sid_advance"]),
            "current_sid_advance": None,
            "current_sid": None,
            "attempt_count": 0,
            "attempt_id": None,
            "candidate_phase": "idle",
            "target_snapshot": None,
            "last_candidate": None,
            "tested_non_shiny_count": 0,
            "skipped_count": 0,
            "last_result": None,
            "hit_sid": None,
            "hit_sid_advance": None,
            "hit_evidence": None,
            "pid_observations": [],
            "excluded_tsvs": [],
            "confirmed_tsv": None,
            "evidence_skipped_count": 0,
        }

    def __enter__(self):
        self.lease = progress_lease(self.path.with_suffix(".lock"))
        self.lease.__enter__()
        try:
            old = read_progress(self.directory, self.context) if self.resume else None
            if old and old.get("status") in {"completed", "exhausted"}:
                self.state = old["state"]
                self.completed = True
            elif old:
                self.state = dict(old["state"])
                # A crash can leave status=running.  It still means the same
                # current candidate must be retried, never advanced.
                self.state["status"] = "running"
            else:
                self.state = self._new_state()
            _validate_state(self.state, self.context)
            self.save(self.state.get("status") if self.completed else "running")
        except BaseException:
            self.lease.__exit__(None, None, None)
            raise
        return self

    def save(self, status: str | None = None) -> None:
        if status is not None:
            self.state["status"] = status
        _validate_state(self.state, self.context)
        payload = {
            "schema": SCHEMA,
            "context": self.context,
            "state": self.state,
            "status": self.state["status"],
            "pid": os.getpid(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json_atomic(self.path, payload)

    @property
    def next_sid_advance(self) -> int:
        return int(self.state["next_sid_advance"])

    @property
    def current_sid_advance(self) -> int | None:
        value = self.state.get("current_sid_advance")
        return None if value is None else int(value)

    def begin_candidate(self, advance: int) -> int:
        """Persist the candidate before any search, file generation, or run."""
        advance = int(advance)
        if advance != self.next_sid_advance:
            raise ValueError("SID 遍历候选必须从当前 next ADV 开始")
        step = int(self.context.get("sid_advance_step", SID_ADVANCE_STEP))
        parity = int(self.context.get("sid_advance_parity", advance % step))
        if advance % step != parity:
            raise ValueError("SID 遍历候选与奇偶约束不一致")
        # ``max_advances`` is inclusive.  The final matching-parity candidate
        # must still be allowed to run; only the exhausted cursor is blocked.
        if advance > int(self.context["max_advances"]):
            raise ValueError("SID 遍历已达到最大 ADV")
        self.state.update(
            status="running",
            current_sid_advance=advance,
            current_sid=sid_at_advance(int(self.context["tid"]), advance),
            attempt_count=int(self.state.get("attempt_count", 0)) + 1,
            attempt_id=uuid.uuid4().hex,
            candidate_phase="searching",
            target_snapshot=None,
            last_result="started",
            hit_sid=None,
            hit_sid_advance=None,
        )
        self.save()
        return int(self.state["current_sid"])

    def set_candidate_target(self, target: dict) -> None:
        if self.current_sid_advance is None:
            raise ValueError("没有正在进行的 SID 候选")
        if not isinstance(target, dict):
            raise ValueError("SID 遍历候选目标必须是对象")
        try:
            normalized = json.loads(json.dumps(target, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            raise ValueError("SID 遍历候选目标包含不可序列化字段") from exc
        self.state.update(target_snapshot=normalized)
        self.save()

    def set_candidate_phase(self, phase: str) -> None:
        if self.current_sid_advance is None:
            raise ValueError("没有正在进行的 SID 候选")
        if phase not in {"searching", "generating", "running", "validating"}:
            raise ValueError("SID 遍历候选阶段无效")
        self.state.update(status="running", candidate_phase=phase)
        self.save()

    def _advance_candidate(self, outcome: str, result: str) -> int:
        current = self.current_sid_advance
        if current is None:
            raise ValueError("没有正在进行的 SID 候选")
        if outcome not in {"tested_non_shiny", "window_skipped", "tsv_excluded"}:
            raise ValueError("SID 遍历候选结果类型无效")
        step = int(self.context.get("sid_advance_step", SID_ADVANCE_STEP))
        next_advance = current + step
        exhausted = next_advance > int(self.context["max_advances"])
        self.state.update(
            status="exhausted" if exhausted else "running",
            next_sid_advance=next_advance,
            last_candidate={
                "sid_advance": current,
                "sid": self.state.get("current_sid"),
                "attempt_id": self.state.get("attempt_id"),
                "target": self.state.get("target_snapshot"),
                "outcome": outcome,
                "result": str(result),
            },
            current_sid_advance=None,
            current_sid=None,
            attempt_id=None,
            candidate_phase="idle",
            target_snapshot=None,
            last_result=str(result),
            last_outcome=outcome,
            tested_non_shiny_count=(
                int(self.state.get("tested_non_shiny_count", 0)) + 1
                if outcome == "tested_non_shiny"
                else int(self.state.get("tested_non_shiny_count", 0))
            ),
            skipped_count=(
                int(self.state.get("skipped_count", 0)) + 1
                if outcome == "window_skipped"
                else int(self.state.get("skipped_count", 0))
            ),
            evidence_skipped_count=(
                int(self.state.get("evidence_skipped_count", 0)) + (outcome == "tsv_excluded")
            ),
        )
        if exhausted:
            self.completed = True
        self.save()
        return self.next_sid_advance

    def complete_non_shiny(self, result: str = "non-shiny") -> int:
        """Advance exactly once after a verified target non-shiny result."""
        return self._advance_candidate("tested_non_shiny", result)

    def skip_candidate(self, reason: str) -> int:
        """Advance after the complete search window had no executable target."""
        return self._advance_candidate("window_skipped", reason)

    def record_pid_observations(self, values: list[dict], *, log: str) -> None:
        """Apply a batch atomically: conflicts never partially change constraints."""
        if not isinstance(values, list):
            raise ValueError("SID PID 证据必须是列表")
        observations = list(self.state.get("pid_observations", []))
        seen = {(v["run_id"], v["attempt_id"], v["round"]): v for v in observations}
        excluded = set(self.state.get("excluded_tsvs", []))
        confirmed = self.state.get("confirmed_tsv")
        for value in values:
            observation = validate_observation(value)
            key = (observation.run_id, observation.attempt_id, observation.round)
            normalized = observation.to_dict()
            if key in seen:
                if any(seen[key].get(k) != v for k, v in normalized.items()):
                    raise ValueError("同一轮唯一 PID 证据不一致，保留现场停止")
                continue
            psv = pid_to_psv(observation.pid)
            if observation.shiny:
                if psv in excluded or (confirmed is not None and confirmed != psv):
                    raise ValueError("闪光与非闪 TSV 证据冲突，保留现场停止")
                confirmed = psv
            else:
                if psv == confirmed:
                    raise ValueError("非闪与已确认闪光 TSV 证据冲突，保留现场停止")
                excluded.add(psv)
            normalized.update(log=str(log), tsv=psv)
            seen[key] = normalized
            observations.append(normalized)
        self.state.update(pid_observations=observations, excluded_tsvs=sorted(excluded), confirmed_tsv=confirmed)
        self.save()

    def candidate_tsv_excluded(self, sid: int) -> bool:
        return ((int(self.context["tid"]) ^ sid) >> 3) in self.state.get("excluded_tsvs", [])

    def skip_excluded_candidate(self) -> int:
        if self.current_sid_advance is None or not self.candidate_tsv_excluded(int(self.state["current_sid"])):
            raise ValueError("当前 SID 的 TSV 没有可靠排除证据")
        return self._advance_candidate("tsv_excluded", "unique-pid-non-shiny-tsv-excluded")

    def resolve_confirmed_tsv(self) -> dict:
        """Finish without new console input; shiny status leaves eight full SIDs."""
        tsv = self.state.get("confirmed_tsv")
        if tsv is None:
            raise ValueError("没有可靠闪光 PID 确认的 TSV")
        tid = int(self.context["tid"])
        sids = list(sid_candidates_for_psv(tid, tsv))
        seen = set()
        advances = []
        for advance in range(int(self.context["start_sid_advance"]), int(self.context["max_advances"]) + 1, SID_ADVANCE_STEP):
            sid = sid_at_advance(tid, advance)
            if sid in sids and sid not in seen:
                advances.append({"sid": sid, "sid_advance": advance})
                seen.add(sid)
        selected = advances[0] if advances else {}
        evidence = next(v for v in self.state["pid_observations"] if v["shiny"])
        result = {"tsv": tsv, "sid_candidates": sids, "sid_advance_candidates": advances,
                  "sid": selected.get("sid"), "sid_advance": selected.get("sid_advance"),
                  "uniquely_determined": False, "hit_evidence": evidence}
        self.state.update(status="completed", candidate_phase="idle", last_result="unique-pid-shiny-tsv-confirmed",
                          hit_sid=result["sid"], hit_sid_advance=result["sid_advance"], hit_evidence=evidence)
        self.completed = True
        self.save()
        return result

    def pause(self, result: str = "paused") -> None:
        """Keep the current candidate for the next invocation."""
        result_text = str(result)
        phase = {
            "search-work-limit": "search_work_limit",
            "search-cancelled": "search_cancelled",
            "non-target-shiny": "non_target_shiny",
            "missing-proof": "missing_proof",
            "runner-failed": "runner_failed",
            "stopped": "stopped",
        }.get(result_text, "paused")
        self.state.update(status="paused", candidate_phase=phase, last_result=result_text)
        self.save()

    def hit(
        self,
        sid: int | None = None,
        result: str = "shiny",
        *,
        evidence: dict | None = None,
    ) -> None:
        current = self.current_sid_advance
        if current is None:
            raise ValueError("没有正在进行的 SID 候选")
        expected = sid_at_advance(int(self.context["tid"]), current)
        if sid is not None and int(sid) != expected:
            raise ValueError("命中 SID 与当前候选不一致")
        self.state.update(
            status="completed",
            current_sid_advance=current,
            current_sid=expected,
            hit_sid=expected,
            hit_sid_advance=current,
            last_result=str(result),
            candidate_phase="idle",
            hit_evidence=(
                json.loads(json.dumps(evidence, ensure_ascii=False))
                if evidence is not None else None
            ),
            last_candidate={
                "sid_advance": current,
                "sid": expected,
                "attempt_id": self.state.get("attempt_id"),
                "target": self.state.get("target_snapshot"),
                "outcome": "verified_shiny",
                "result": str(result),
            },
        )
        self.completed = True
        self.save()

    def __exit__(self, *args):
        try:
            if not self.completed:
                # Preserve the exact candidate if EasyCon was interrupted.
                self.state["status"] = "paused"
                self.save()
        except OSError as exc:
            self.warning(f"[SID遍历进度警告] 状态未写入：{exc}；当前候选仍需根据日志确认。")
        finally:
            self.lease.__exit__(*args)
