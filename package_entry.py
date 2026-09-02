"""PyInstaller entry point for the novice-friendly Windows release."""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

from app_version import APP_VERSION_CODE, version_payload


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_stdout(text: str) -> bool:
    if sys.stdout is not None:
        sys.stdout.write(text)
        sys.stdout.flush()
        return True
    try:
        os.write(1, text.encode("utf-8"))
        return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--version-json"]:
        return 0 if _write_stdout(json.dumps(version_payload(), sort_keys=True) + "\n") else 1
    if argv[:1] == ["--version-json-file"]:
        if len(argv) != 2:
            return 2
        _atomic_json(Path(argv[1]).resolve(), version_payload())
        return 0
    if argv[:1] == ["--update-health-file"]:
        if (
            len(argv) != 4
            or argv[2] != "--update-health-token"
            or re.fullmatch(r"[0-9a-f]{32}", argv[3]) is None
        ):
            return 2
        _atomic_json(
            Path(argv[1]).resolve(),
            {"token": argv[3], "version_code": APP_VERSION_CODE},
        )
        argv = []
    if argv[:1] == ["--worker"]:
        if len(argv) < 2:
            print("缺少后台工作模式", file=sys.stderr)
            return 2
        worker = argv[1]
        worker_argv = argv[2:]
        sys.argv = [sys.argv[0], *worker_argv]
        if worker == "sid-capture":
            from run_sid_reverse_capture import main as worker_main

            return int(worker_main(worker_argv) or 0)
        if worker == "sid-traversal":
            from run_sid_traversal import main as worker_main

            return int(worker_main(worker_argv) or 0)
        if worker == "tid-flow":
            from run_tid_starter_flow import main as worker_main

            return int(worker_main() or 0)
        if worker == "easycon-log":
            from run_easycon_logged import main as worker_main

            return int(worker_main(worker_argv) or 0)
        print(f"未知后台工作模式: {worker}", file=sys.stderr)
        return 2

    from run_auto_rng_gui import main as gui_main

    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
