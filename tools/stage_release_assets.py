"""Stage release assets without unrelated upstream OCR experiments."""
import argparse
import hashlib
import shutil
from pathlib import Path

from automation.easycon118 import EXPECTED_TESSDATA_SHA256


def stage_assets(source: Path, destination: Path) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Release staging must be outside the source asset tree")
    models = source / "easycon118" / "Tessdata"
    for name, expected in EXPECTED_TESSDATA_SHA256.items():
        if hashlib.sha256((models / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Release OCR model fingerprint mismatch: {name}")

    def ignore(directory: str, names: list[str]) -> list[str]:
        if Path(directory).resolve() == models:
            return [name for name in names if name not in EXPECTED_TESSDATA_SHA256]
        return []

    shutil.copytree(source, destination, ignore=ignore)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(stage_assets(args.source, args.destination))


if __name__ == "__main__":
    main()
