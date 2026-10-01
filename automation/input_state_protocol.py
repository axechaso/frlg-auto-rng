"""Structured run/session markers shared by workers and the desktop UI."""

from __future__ import annotations

import re


_ID = r"[A-Za-z0-9_-]{1,64}"
_MARKER = re.compile(
    rf"^FRLG_INPUT_SESSION\|V=1\|RUN=(?P<run>{_ID})"
    rf"\|SESSION=(?P<session>{_ID})\|STAGE=(?P<stage>{_ID})"
    r"\|STATE=(?P<state>STARTING|SEARCHING|RUNNING|STOPPING|ENDED|FAILED)\|END=1$"
)
SESSION_STATES = frozenset({"STARTING", "SEARCHING", "RUNNING", "STOPPING", "ENDED", "FAILED"})


def format_input_session_marker(run_id: str, session_id: str, stage_id: str, state: str) -> str:
    values = (run_id, session_id, stage_id)
    if any(not isinstance(value, str) or not re.fullmatch(_ID, value) for value in values):
        raise ValueError("运行按键会话身份格式无效")
    if state not in SESSION_STATES:
        raise ValueError("运行按键会话状态无效")
    return (
        f"FRLG_INPUT_SESSION|V=1|RUN={run_id}|SESSION={session_id}|"
        f"STAGE={stage_id}|STATE={state}|END=1"
    )


def parse_input_session_marker(line: str) -> dict[str, str] | None:
    if not isinstance(line, str):
        return None
    match = _MARKER.fullmatch(line.strip())
    return match.groupdict() if match else None


__all__ = ["SESSION_STATES", "format_input_session_marker", "parse_input_session_marker"]
