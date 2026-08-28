"""Install only the reviewed common-region hooks; preserve a runnable baseline."""

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation.seed_common_regions import ENTRIES, LIBRARY, upgrade_entry, upgrade_library


def functions(text):
    return {m[1]: m[0] for m in re.finditer(r"(?ms)^FUNC (\w+)[^\n]*\n.*?^ENDFUNC", text)}


def prepare(root):
    originals = {name: (root / name).read_text(encoding="utf-8") for name in (*ENTRIES, LIBRARY)}
    changed = {name: upgrade_entry(text) if name in ENTRIES else upgrade_library(text)
               for name, text in originals.items()}
    allowed = {"重置本轮候选状态", "处理匹配候选", "执行识图反查直到候选唯一", "执行自动校准与等待更新"}
    for name in ENTRIES:
        old, new = functions(originals[name]), functions(changed[name])
        for fn, body in old.items():
            if fn not in allowed and body != new.get(fn):
                raise AssertionError(f"非目标函数发生变化: {name}/{fn}")
        # Controller formula text is unchanged; only an extra history reset may
        # follow its existing vote-reset calls.
        fn = "执行自动校准与等待更新"
        if fn in old:
            stripped = re.sub(r"(?m)^\s*CALL 共同区重置\n", "", new[fn])
            # Compare nonblank lines, because insertion preserves caller indentation.
            assert [s for s in stripped.splitlines() if s.strip()] == [s for s in old[fn].splitlines() if s.strip()]
    return originals, changed


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.project.resolve()
    originals, configured = prepare(root)
    for name, text in configured.items():
        print(name, hashlib.sha256(text.encode("utf-8")).hexdigest())
    if not args.apply:
        print("Dry run; no files changed.")
        return
    backup = args.backup.resolve()
    if backup.exists():
        raise FileExistsError(f"保留已有对照副本，不覆盖: {backup}")
    backup.mkdir(parents=True)
    for name in ENTRIES:
        shutil.copy2(root / name, backup / name)
    for name in ("lib", "ImgLabel"):
        if (root / name).is_dir():
            shutil.copytree(root / name, backup / name)
    for name, text in configured.items():
        if originals[name] != text:
            (root / name).write_text(text, encoding="utf-8")
    print("Installed; unchanged baseline:", backup)


if __name__ == "__main__":
    main()
