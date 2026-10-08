"""Prepare compact assets in a NEW folder; never mutate an existing release."""

import argparse
import json
import shutil
from pathlib import Path

from packed_updates import asset_names, create_assets, pack_assets, verify_release_assets


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--assets-dir", type=Path)
    source.add_argument("--unpacked-root", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--gitee-output-dir", type=Path)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.assets_dir is not None:
        verify_release_assets(args.package, manifest, args.assets_dir)
        metadata = pack_assets(args.assets_dir, args.output_dir)
    else:
        metadata = create_assets(args.unpacked_root, manifest, args.output_dir)
    verify_release_assets(args.package, manifest, args.output_dir)
    names = asset_names(metadata)
    if args.gitee_output_dir is not None:
        from tools.create_update_manifest import create_gitee_release_assets

        # Recreate and verify the five whole-package parts for old clients;
        # do not copy a possibly outdated legacy manifest from another build.
        create_gitee_release_assets(args.package, manifest, args.gitee_output_dir)
        for name in names:
            shutil.copy2(args.output_dir / name, args.gitee_output_dir / name)
    print(json.dumps({"assets": list(names), "count": len(names)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
