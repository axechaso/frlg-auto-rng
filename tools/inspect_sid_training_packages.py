"""Read-only audit of the supplied JP/EN EV-training ZIPs; never extracts/runs them."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile


def _name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if not info.flag_bits & 0x800:
        try:
            name = name.encode("cp437").decode("gbk")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    name = name.replace("\\", "/")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in name:
        raise ValueError(f"unsafe archive member: {name}")
    return name


def _text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = data.decode(encoding)
            return text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            pass
    raise ValueError("unsupported training script encoding")


def inspect_training_archive(path: str | Path) -> dict:
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 10_000 or sum(info.file_size for info in infos) > 100 * 1024 * 1024:
            raise ValueError("training archive exceeds inspection limits")
        members = {}
        for info in infos:
            name = _name(info)
            if name in members:
                raise ValueError(f"duplicate archive member: {name}")
            members[name] = info
        mains = [name for name in members
                 if re.fullmatch(r".*全能脚本V3\.[89]\.txt", PurePosixPath(name).name)]
        efforts = [name for name in members
                   if PurePosixPath(name).name in ("努力值数据包.ecs", "日版努力值数据包.ecs")]
        if len(mains) != 1 or len(efforts) != 1:
            raise ValueError("archive must contain one supported main and one EV library")
        main = _text(archive.read(members[mains[0]]))
        effort_bytes = archive.read(members[efforts[0]])
        effort = _text(effort_bytes)
        labels = sorted(set(re.findall(r"@([\w\u4e00-\u9fff]+)", effort)))
        label_files = {PurePosixPath(name).stem for name in members if name.lower().endswith(".il")}
        libraries = {}
        for name, info in members.items():
            if name.lower().endswith(".ecs"):
                data = archive.read(info)
                libraries[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        return {
            "archive": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "entries": len(infos),
            "extensions": dict(sorted(Counter(PurePosixPath(name).suffix.lower()
                                               for name in members if not name.endswith("/")).items())),
            "language": "Japanese" if "日版" in PurePosixPath(mains[0]).name else "English",
            "main": {"path": mains[0], "lines": len(main.splitlines()),
                     "sha256": hashlib.sha256(archive.read(members[mains[0]])).hexdigest()},
            "libraries": libraries,
            "effort_library": efforts[0],
            "effort_label_references": labels,
            "missing_effort_labels": sorted(set(labels) - label_files),
            "selection_time_counter_increments": len(re.findall(
                r"\$(?P<counter>(?:count_\w+|\w+_count))\s*(?:\+=\s*1|=\s*\$(?P=counter)\s*\+\s*1)(?:\s|$)", effort,
            )),
            "confirmed_defeat_journal_supported": False,
            "notes": [
                "Species counters are incremented by selection-time label matches, not confirmed defeats.",
                "No six-stat EV journal, eligibility, multipliers or caps can be inferred from those counters.",
                "Use namespaced training labels; never replace the current common mother labels.",
                "This inspection does not execute scripts or prove hardware/runtime compatibility.",
            ],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        reports = [inspect_training_archive(path) for path in args.archives]
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"SID training archive inspection failed: {exc}\n")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
