"""Generate an offline formal-TID bootstrap acceptance matrix; never run keys."""

import argparse
from itertools import product
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.tid_bootstrap import GUARD_BEGIN, MARKER
from automation.tid_rng137 import (
    DEFAULT_TID_SOURCE_PATH, TidRngRequest, configure_tid_template_text,
    verify_tid_package, write_configured_tid_project,
)
from automation.tid_starter_save import TID_STARTER_SAVE_NAME, split_tid_modules


def generate_matrix(source: Path, destination: Path) -> list[Path]:
    verify_tid_package(source)
    template = (source / TID_STARTER_SAVE_NAME).read_text(encoding="utf-8-sig")
    destination.mkdir(parents=True, exist_ok=True)
    write_configured_tid_project(source, destination, TidRngRequest())
    paths = []
    for language, model, mode, calibration, adaptive in product(("英文", "日文"), (1, 2), (0, 1), (False, True), (False, True)):
        request = TidRngRequest(language=language, player_name="Alxe" if language == "英文" else "レット゛",
                                nx_model=model, mode=mode, calibration_check=calibration,
                                home_buffer_adaptive_threshold=adaptive)
        configured = configure_tid_template_text(template, request, include_flow_marker=True)
        assert configured.count(MARKER) == 1
        assert configured.count(GUARD_BEGIN) == 1
        active = split_tid_modules(configured)[1 if language == "英文" else 2]
        assert f"$脚本固定延迟检查开关 = {int(calibration)}" in active
        assert f"$NS机型 = {model}" in active
        assert active.count("CALL TID建档_创建新游戏") == 1
        assert configured.count("TIDFLOW|ID|MATCH=1") == 5
        name = f"{'EN' if language == '英文' else 'JP'}-ns{model}-mode{mode}-cal{int(calibration)}-adaptive{int(adaptive)}.ecs"
        target = destination / name
        target.write_text(configured, encoding="utf-8")
        paths.append(target)
    (destination / "matrix.json").write_text(json.dumps({"source": str(source.resolve()),
        "count": len(paths), "files": [path.name for path in paths], "hardware_access": False},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source", type=Path, default=DEFAULT_TID_SOURCE_PATH)
    args = parser.parse_args()
    paths = generate_matrix(args.source, args.destination)
    print(f"Generated {len(paths)} formal TID variants; full ImgLabel retained; no hardware run.")


if __name__ == "__main__":
    main()
