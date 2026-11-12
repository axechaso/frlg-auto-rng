"""Verify the selected source-install backend without operating devices."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from automation import DEFAULT_EZCON_PATH, prepare_compat_runner
from automation.easycon170 import enabled, verify_cli


def main():
    if enabled():
        if not DEFAULT_EZCON_PATH.is_file():
            raise FileNotFoundError(
                "尚未导入170修复运行包。请先执行：\n"
                '  .venv\\Scripts\\python.exe -m tools.import_easycon170_runtime "修复运行包目录"\n'
                "运行包需要 .NET 10 x64；详见 docs/EASYCON170.md。"
            )
        print(verify_cli(DEFAULT_EZCON_PATH)[0])
        return
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "tools/prepare_easycon164a.py")], check=True)
    legacy = root / "runtime_backend/easycon164a-cli-gui-rounding-selfcontained/EasyCon2.CLI.PreviewV5.exe"
    if not legacy.is_file():
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(root / "tools/build_easycon164a_compat_runner.ps1")], check=True)
    print(prepare_compat_runner(DEFAULT_EZCON_PATH))


if __name__ == "__main__":
    main()
