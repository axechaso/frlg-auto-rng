"""Verify the English training ZIP and its exact script/label manifests.

No controller, camera or game process is opened. Optional ezcon invocation
uses only its `format` command, not the runner.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_sid_training_test import sha


def verify_project(project: Path) -> dict:
    manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
    script = (project / "main.ecs").read_bytes()
    if sha(script) != manifest["script_sha256"]:
        raise ValueError("script manifest hash mismatch")
    refs = set(re.findall(r"@([\w\u4e00-\u9fff]+)", script.decode("utf-8")))
    if refs != set(manifest["labels"]) or manifest["label_count"] != len(refs):
        raise ValueError("script label references differ from manifest")
    if {p.stem for p in (project / "ImgLabel").glob("*.IL")} != refs:
        raise ValueError("unexpected or missing training label")
    for name, info in manifest["labels"].items():
        raw = (project / "ImgLabel" / (name + ".IL")).read_bytes()
        payload = json.loads(raw)
        if sha(raw) != info["sha256"] or payload["name"] != name:
            raise ValueError(f"label manifest mismatch: {name}")
    return {"project": project.name, "labels": len(refs), "manifest_verified": True}


def verify_zip(root: Path) -> dict:
    path = root.with_suffix(".zip")
    # ezcon format adds debug output copies; they are never part of the ZIP.
    files = {p.relative_to(root).as_posix(): p for p in root.rglob("*")
             if p.is_file() and "_format_" not in p.name}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        expected = {root.name + "/" + name for name in files}
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError("ZIP file set differs from generated bundle")
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC failure")
        for name, source in files.items():
            if archive.read(root.name + "/" + name) != source.read_bytes():
                raise ValueError(f"ZIP content mismatch: {name}")
    return {"zip": str(path), "bytes": path.stat().st_size, "files": len(files),
            "sha256": sha(path.read_bytes())}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--ezcon", type=Path)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    projects = sorted(p for p in args.bundle.iterdir() if (p / "main.ecs").exists())
    if {p.name for p in projects} != {"美版-自己战斗", "美版-学习装置"}:
        raise ValueError("expected exactly two English ROM standalone test projects")
    reports = [verify_project(p) for p in projects]
    if args.ezcon:
        for project, report in zip(projects, reports):
            process = subprocess.run([str(args.ezcon.resolve()), "format", str((project / "main.ecs").resolve())],
                                     cwd=args.ezcon.resolve().parent, capture_output=True, timeout=60)
            output = process.stdout.decode("utf-8", errors="replace") + process.stderr.decode("utf-8", errors="replace")
            if process.returncode != 0 or "期望结束但多余" in output or "错误:" in output:
                raise ValueError(f"format failed: {project.name}: {output[-2000:]}")
            report["format_exit"] = process.returncode
    print(json.dumps({"projects": reports, "archive": verify_zip(args.bundle),
                      "hardware": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
