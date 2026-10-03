"""Create deterministic metadata for a verified Windows release archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from incremental_update import create_assets, verify_release_assets

from app_version import (
    APP_VERSION,
    APP_VERSION_CODE,
    GITEE_REPOSITORY,
    GITHUB_REPOSITORY,
    UPDATE_SCHEMA,
)


GITEE_PART_SIZE_BYTES = 90 * 1024 * 1024


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
    notes: str = f"FRLG Auto RNG {APP_VERSION} PySide6版。",
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


def create_gitee_release_assets(
    package: Path,
    manifest: dict[str, object],
    output_dir: Path,
    *,
    part_size: int = GITEE_PART_SIZE_BYTES,
) -> dict[str, object]:
    package = Path(package).resolve()
    output_dir = Path(output_dir).resolve()
    if not package.is_file():
        raise ValueError(f"发布包不存在：{package}")
    if not 0 < part_size <= 95 * 1024 * 1024:
        raise ValueError("Gitee 分卷大小必须大于 0 且不超过 95 MiB")
    if manifest.get("package") != package.name:
        raise ValueError("Gitee 分卷清单与发布包文件名不一致")
    if manifest.get("bytes") != package.stat().st_size:
        raise ValueError("Gitee 分卷清单与发布包大小不一致")
    if manifest.get("sha256") != _sha256(package):
        raise ValueError("Gitee 分卷清单与发布包 SHA-256 不一致")
    if output_dir.exists():
        raise ValueError(f"Gitee Release 资产目录已存在：{output_dir}")
    output_dir.mkdir(parents=True)
    parts: list[dict[str, object]] = []
    try:
        with package.open("rb") as source:
            index = 1
            while True:
                name = f"{package.name}.{index:03d}"
                path = output_dir / name
                digest = hashlib.sha256()
                written = 0
                with path.open("xb") as output:
                    while written < part_size:
                        chunk = source.read(min(1024 * 1024, part_size - written))
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                if written == 0:
                    path.unlink()
                    break
                parts.append({"name": name, "sha256": digest.hexdigest(), "bytes": written})
                index += 1
        if not parts or sum(int(part["bytes"]) for part in parts) != manifest["bytes"]:
            raise ValueError("Gitee 分卷总大小与完整更新包不一致")
        gitee_manifest = {
            **manifest,
            "source": "gitee-split",
            "repository": GITEE_REPOSITORY,
            "release_url": (
                f"https://gitee.com/{GITEE_REPOSITORY}/releases/tag/v{manifest['version']}"
            ),
            "parts": parts,
        }
        (output_dir / "gitee-update-manifest.json").write_text(
            json.dumps(gitee_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return gitee_manifest
    except BaseException:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--unpacked-root", required=True, type=Path)
    notes = parser.add_mutually_exclusive_group()
    notes.add_argument("--notes")
    notes.add_argument("--notes-file", type=Path)
    parser.add_argument("--gitee-assets-dir", type=Path)
    parser.add_argument("--incremental-assets-dir", type=Path)
    args = parser.parse_args(argv)
    if args.notes_file is not None:
        release_notes = args.notes_file.read_text(encoding="utf-8")
    else:
        release_notes = args.notes or f"FRLG Auto RNG {APP_VERSION} PySide6版。"
    manifest = create_manifest(args.package, args.unpacked_root, notes=release_notes)
    if args.gitee_assets_dir is not None:
        create_gitee_release_assets(args.package, manifest, args.gitee_assets_dir)
    if args.incremental_assets_dir is not None:
        create_assets(args.unpacked_root, manifest, args.incremental_assets_dir)
        verify_release_assets(args.package, manifest, args.incremental_assets_dir)
        if args.gitee_assets_dir is not None:
            for path in args.incremental_assets_dir.iterdir():
                shutil.copy2(path, args.gitee_assets_dir / path.name)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
