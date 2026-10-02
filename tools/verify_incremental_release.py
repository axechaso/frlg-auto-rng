"""Verify incremental release assets before publishing, returning an exact list."""

import argparse
import json
from pathlib import Path

from incremental_update import MANIFEST_NAME, verify_release_assets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--assets-dir", required=True, type=Path)
    args = parser.parse_args()
    package_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest = verify_release_assets(args.package, package_manifest, args.assets_dir)
    print(json.dumps([MANIFEST_NAME, *(bundle.name for bundle in manifest.bundles)]))


if __name__ == "__main__":
    main()
