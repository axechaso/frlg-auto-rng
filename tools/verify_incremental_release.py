"""Verify incremental release assets before publishing, returning an exact list."""

import argparse
import json
from pathlib import Path

from packed_updates import asset_names, verify_release_assets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--assets-dir", required=True, type=Path)
    args = parser.parse_args()
    package_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest = verify_release_assets(args.package, package_manifest, args.assets_dir)
    print(json.dumps(asset_names(manifest)))


if __name__ == "__main__":
    main()
