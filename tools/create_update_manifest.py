"""Create deterministic metadata for a verified Windows release archive."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app_version import APP_VERSION, APP_VERSION_CODE, GITHUB_REPOSITORY, UPDATE_SCHEMA


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unpacked_bytes(root: Path) -> int:
    if not root.is_dir():
        raise ValueError(f"解压目录不存在：{root}")
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"发布目录不允许符号链接：{path}")
        if path.is_file():
            total += path.stat().st_size
    if total <= 0:
        raise ValueError("发布目录为空")
    return total


def create_manifest(
    package: Path,
    unpacked_root: Path,
    *,
    notes: str = "FRLG Auto RNG 0.2：整包更新器与近期乱数流程更新。",
    release_url: str | None = None,
) -> dict[str, object]:
    package = Path(package).resolve()
    unpacked_root = Path(unpacked_root).resolve()
    expected_name = f"FRLG-Auto-RNG-{APP_VERSION}-windows-x64.zip"
    if package.name != expected_name:
        raise ValueError(f"发布包文件名必须为 {expected_name}")
    if not package.is_file():
        raise ValueError(f"发布包不存在：{package}")
    if not notes or len(notes) > 20_000:
        raise ValueError("更新说明不能为空且不能过长")
    manifest = {
        "schema": UPDATE_SCHEMA,
        "version": APP_VERSION,
        "version_code": APP_VERSION_CODE,
        "package": package.name,
        "sha256": _sha256(package),
        "bytes": package.stat().st_size,
        "unpacked_bytes": _unpacked_bytes(unpacked_root),
        "release_url": release_url
        or f"https://github.com/{GITHUB_REPOSITORY}/releases/tag/v{APP_VERSION}",
        "notes": notes,
    }
    output = package.parent / "update-manifest.json"
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    sha_path = package.parent / f"{package.name}.sha256"
    sha_path.write_text(
        f"{manifest['sha256']}  {package.name}\n", encoding="ascii", newline="\n"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--unpacked-root", required=True, type=Path)
    parser.add_argument("--notes", default="FRLG Auto RNG 0.2：整包更新器与近期乱数流程更新。")
    args = parser.parse_args(argv)
    manifest = create_manifest(args.package, args.unpacked_root, notes=args.notes)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
