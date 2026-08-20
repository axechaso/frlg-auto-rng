# EasyCon 1.6.4-a CLI compatibility runner

EasyCon `1.6.4-a+9c86137` has two runtime-only CLI discrepancies:

- The GUI returns `(int)Math.Ceiling(md)` for an ImgLabel match.
- The bundled `ezcon.exe run` returns `(int)md`, which truncates the same value.
- The GUI monitor continuously drains the capture queue every 16 ms.
- The bundled CLI reads one frame only when an ImgLabel getter runs, so DSHOW
  can return buffered transition frames.

The automatic launcher needs a command-line runner, so it uses the self-contained
runner in `easycon164a-cli-gui-rounding-selfcontained/`. It is built from exact
upstream commit `9c86137c7e63bff842175470895727a5fa9bab52`. The functional patch continuously
captures frames on one reader thread, gives both label getters and EasyCon's
local OCR delegate a clone of the newest frame, logs the actual captured
dimensions, and uses `Math.Ceiling`. The
remaining source changes are compile-only compatibility for the locally
available .NET 9 SDK.

The OCR-enabled v4 executable uses a versioned filename so it can be installed
while an older automation process still has the previous runner open. New runs
select `EasyCon2.CLI-ocr-v4.exe`; an already-running older process is left alone.
It is intentionally published as a self-contained folder rather than a single
file: Tesseract 5.2's InteropDotNet loader requires a real assembly directory to
locate its `x64` native libraries.

The original `ezcon.exe` remains authoritative for version/hash checks, device
enumeration, Tessdata verification, and ECS `format` preflight. Before launch,
Python verifies `build-manifest.json`, checks the compatible runner's version,
copies the two audited OCR models from the original 1.6.4-a package, and verifies
the pinned `x64` Tesseract/Leptonica DLLs produced by the locked source build.

Do not substitute a 1.7.0 or 1.6.3 executable.
