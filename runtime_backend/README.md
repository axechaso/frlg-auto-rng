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
captures frames on one reader thread, gives label getters a clone of the newest
frame, logs the actual captured dimensions, and uses `Math.Ceiling`. The
remaining source changes are compile-only compatibility for the locally
available .NET 9 SDK.

The original `ezcon.exe` remains authoritative for version/hash checks, device
enumeration, Tessdata verification, and ECS `format` preflight. Before launch,
Python verifies `build-manifest.json`, checks the compatible runner's version,
and copies the two audited OCR models from the original 1.6.4-a package.

Do not substitute a 1.7.0 or 1.6.3 executable.
