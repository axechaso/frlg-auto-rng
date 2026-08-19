"""PyInstaller entry point for the novice-friendly Windows release."""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
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
