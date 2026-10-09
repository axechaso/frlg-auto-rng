# EasyCon 1.6.4-a CLI compatibility runner

EasyCon `1.6.4-a+9c86137` and the prior compatibility runner have runtime-only
CLI discrepancies:

- The GUI returns `(int)Math.Ceiling(md)` for an ImgLabel match.
- The bundled `ezcon.exe run` returns `(int)md`, which truncates the same value.
- The GUI monitor continuously drains the capture queue every 16 ms.
- The bundled CLI reads one frame only when an ImgLabel getter runs, so DSHOW
  can return buffered transition frames.

The automatic launcher needs a command-line runner, so it uses the self-contained
runner in `easycon164a-cli-gui-rounding-selfcontained/`. It is built from exact
upstream commit `9c86137c7e63bff842175470895727a5fa9bab52`. The v11 functional patch
keeps background capture draining, but every script label getter and OCR request
now performs a synchronous physical read, as the GUI does. All reads are
serialized through one shared device gate. Preview and incident snapshots still
use cloned cached frames; they never open a second capture device. Label score,
snapshot, sequence and capture timestamp belong to the same read, not a newer
background frame sampled after matching. It logs the actual captured dimensions
and keeps `Math.Ceiling`. The
remaining source changes are compile-only compatibility for the locally
available .NET 9 SDK.

The OCR-enabled executable retains the versioned `EasyCon2.CLI.PreviewV5` assembly
name. This filename is not the patch version: the v11 manifest and assembly
hash identify the new capture implementation. Restart the source tool before
using it; a process that is already running is not upgraded in place. The builder
refuses to swap the runtime directory while a current runner is active and
preserves the previous directory as a backup. It is intentionally
published as a self-contained folder rather than a single
file: Tesseract 5.2's InteropDotNet loader requires a real assembly directory to
locate its `x64` native libraries.

The PreviewV5 runner accepts `--preview-port <port>` and serves `/mjpeg` only on
`127.0.0.1`. The GUI monitor reads that stream while the script is running, so
it never opens a second `VideoCapture`. A pure button/timing script that has no
ImgLabel or OCR calls (for example, the TID-to-lab bridge stage) still opens the
capture reader when a preview port is requested, so the monitor remains usable
through every stage of a continuous flow. Without this option the runner behaves
like the prior v4 compatibility runner.

The original `ezcon.exe` remains authoritative for version/hash checks, device
enumeration, Tessdata verification, and ECS `format` preflight. Before launch,
Python verifies `build-manifest.json`, checks the compatible runner's version,
copies the two audited OCR models from the original 1.6.4-a package, and verifies
the pinned `x64` Tesseract/Leptonica DLLs produced by the locked source build.

Do not substitute a 1.7.0 or 1.6.3 executable.

Build and test details, limitations, and the read-only encounter probe are in
[the synchronized capture report](../docs/RUNNER_FRAME_FRESHNESS.md). This patch
does not change the ECS 100ms delay, image labels, matching thresholds, shiny
fallback, controller input sequence, Seed or frame calibration.
