# Windows Self-Updater Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe whole-package updater to the frozen Windows green release, then build, verify, push, and publish version 1.1.9 as a complete stable GitHub Release.

**Architecture:** The frozen GUI checks the public GitHub latest-release API in a background thread and downloads only after user confirmation. A separately frozen one-file updater runs from `%LOCALAPPDATA%`, waits for the GUI to exit, swaps verified sibling directories, rolls back on failure, and restarts the new GUI. Local developer tooling produces and validates the ZIP, manifest, SHA file, draft Release, and final publication.

**Tech Stack:** Python 3.12 standard library (`urllib`, `hashlib`, `zipfile`, `json`, `pathlib`, `subprocess`), Tkinter, PyInstaller 6.15, PowerShell, GitHub CLI, Windows filesystem semantics.

**Spec:** `docs/superpowers/specs/2026-08-30-windows-self-updater-design.md`

## Global Constraints

- Only frozen Windows `onedir` builds self-update; source runs never replace files.
- The update source is the latest stable Release from public repository `axechaso/frlg-auto-rng`; drafts and prereleases are rejected.
- `APP_VERSION` is `1.1.9`; `APP_VERSION_CODE` is `2026083001`; manifest schema is `1`.
- No GitHub token, publisher credential, or private key may enter the client or release ZIP.
- Automatic checks run in the background at most once every 24 hours; no update is downloaded without user confirmation.
- Installation is forbidden while `busy` is true or an EasyCon child process is running.
- `%LOCALAPPDATA%\FRLG-Auto-RNG` user profiles, settings, logs, progress, Seed tables, and label overrides are never part of the installation directory swap.
- ZIP downloads are full-package, HTTPS-only, size-checked, SHA-256-checked, and extracted with path traversal and symlink rejection.
- Directory moves and removals use exact normalized paths constrained to the intended install parent; no glob, unresolved environment variable, workspace root, drive root, or home directory is a destructive target.
- EasyCon remains locked to `1.6.4-a+9c86137`; updater work must not change Seed, frame, OCR, HOME_BUFFER, TID/SID, egg, capture, or controller behavior.
- The first updater-capable version requires manual installation; application self-update starts with subsequent Releases.
- Release creation uses the locally audited ignored assets and GitHub CLI. Incomplete uploads remain a draft Release.

---

## File Structure

- Create `app_version.py`: immutable application/repository/version constants and version JSON.
- Create `app_updater.py`: release discovery, manifest validation, cache, download, safe extraction, staging, and install-request creation.
- Create `update_installer.py`: path-constrained directory swap, health wait, rollback, result log, and cleanup logic independent of GUI/network code.
- Create `updater_entry.py`: minimal command-line entry frozen as the one-file updater.
- Create `tools/create_update_manifest.py`: deterministic release manifest and SHA writer.
- Create `tools/publish_windows_release.ps1`: verified draft-upload-publish flow through GitHub CLI.
- Create `tests/test_app_version.py`: version-contract tests.
- Create `tests/test_app_updater.py`: discovery, cache, download, ZIP, staging, cancellation, and request tests.
- Create `tests/test_update_installer.py`: success, rollback, and path-safety tests.
- Create `tests/test_package_entry.py`: `--version-json` and health-token dispatch tests.
- Create `tests/test_update_manifest_tool.py`: build-manifest output tests.
- Modify `package_entry.py`: frozen version and health modes before GUI import.
- Modify `run_auto_rng_gui.py`: update status/button, background check, confirmation, download progress, and installer handoff.
- Modify `tools/build_windows_release.ps1`: build updater, package it, generate metadata, and verify both frozen entries.
- Modify `.github/workflows/ci.yml`: compile and test new source modules without attempting a Release build.
- Modify `README.md`, `docs/WINDOWS_RELEASE.md`, and `docs/HANDOFF.md`: user flow, publisher flow, compatibility, and validation record.

---

### Task 1: Version Contract and Frozen Version Probe

**Files:**
- Create: `app_version.py`
- Modify: `package_entry.py`
- Create: `tests/test_app_version.py`
- Create: `tests/test_package_entry.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `APP_VERSION: str`, `APP_VERSION_CODE: int`, `UPDATE_SCHEMA: int`, `GITHUB_REPOSITORY: str`, `version_payload() -> dict[str, object]`.
- Produces: `package_entry.main(argv: list[str] | None = None) -> int`, accepting `--version-json` and internal `--update-health-file PATH --update-health-token TOKEN`.
- Consumes: no updater code; later tasks import only this task's constants and `version_payload()`.

- [ ] **Step 1: Write failing version tests**

```python
class AppVersionTests(unittest.TestCase):
    def test_release_contract_is_stable(self):
        self.assertEqual(app_version.APP_VERSION, "1.1.9")
        self.assertEqual(app_version.APP_VERSION_CODE, 2026083001)
        self.assertEqual(app_version.UPDATE_SCHEMA, 1)
        self.assertEqual(app_version.GITHUB_REPOSITORY, "axechaso/frlg-auto-rng")
        self.assertEqual(app_version.version_payload(), {
            "version": "1.1.9",
            "version_code": 2026083001,
            "update_schema": 1,
            "repository": "axechaso/frlg-auto-rng",
        })
```

- [ ] **Step 2: Write failing package-entry tests**

Patch `sys.stdout` and assert `package_entry.main(["--version-json"])` returns `0` and emits the exact JSON payload. In a temporary directory, call the internal health arguments and assert the resulting JSON file is atomically written as `{"token": "abc", "version_code": 2026083001}` without importing `run_auto_rng_gui`.

- [ ] **Step 3: Run the focused tests and observe missing-module/interface failures**

Run: `\.\.venv\Scripts\python.exe -m unittest -v tests.test_app_version tests.test_package_entry`

Expected: FAIL because `app_version.py` and the parameterized `package_entry.main()` modes do not exist.

- [ ] **Step 4: Implement the minimal version module**

```python
APP_VERSION = "1.1.9"
APP_VERSION_CODE = 2026083001
UPDATE_SCHEMA = 1
GITHUB_REPOSITORY = "axechaso/frlg-auto-rng"

def version_payload() -> dict[str, object]:
    return {
        "version": APP_VERSION,
        "version_code": APP_VERSION_CODE,
        "update_schema": UPDATE_SCHEMA,
        "repository": GITHUB_REPOSITORY,
    }
```

Update `package_entry.main()` to accept an optional argument list, handle `--version-json` before worker/GUI imports, and atomically write the health file with a temporary sibling plus `Path.replace()`. Reject missing or extra health arguments with exit code `2`.

- [ ] **Step 5: Add the modules/tests to CI compile and unittest lists**

Add `app_version.py`, `app_updater.py`, `update_installer.py`, and `updater_entry.py` to the compile list as they are created. Add all five new test modules to the repository-independent unittest step.

- [ ] **Step 6: Run tests and compile checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_app_version tests.test_package_entry
.\.venv\Scripts\python.exe -m py_compile app_version.py package_entry.py
```

Expected: all tests PASS; compilation exits `0`.

- [ ] **Step 7: Commit the version contract**

```powershell
git add app_version.py package_entry.py tests/test_app_version.py tests/test_package_entry.py .github/workflows/ci.yml
git commit -m "feat: define application update version contract"
```

---

### Task 2: Release Discovery, Manifest Validation, and Check Cache

**Files:**
- Create: `app_updater.py`
- Create: `tests/test_app_updater.py`

**Interfaces:**
- Consumes: Task 1 constants.
- Produces: immutable `UpdateManifest`, `UpdateCandidate`, and `UpdateCheckResult` dataclasses.
- Produces: `parse_manifest(payload: bytes) -> UpdateManifest`.
- Produces: `candidate_from_release(release: dict[str, object], manifest: UpdateManifest) -> UpdateCandidate`.
- Produces: `check_for_update(*, current_version_code: int, cache_dir: Path, force: bool = False, opener: Callable = urllib.request.urlopen, now: float | None = None) -> UpdateCheckResult`.

- [ ] **Step 1: Write failing manifest validation tests**

Use a helper returning the exact schema-1 object and assert acceptance of version `1.1.9`, code `2026083001`, package `FRLG-Auto-RNG-1.1.9-windows-x64.zip`, 64-character lowercase SHA-256, positive `bytes`/`unpacked_bytes`, HTTPS release URL, and notes. Add independent rejection tests for unknown/missing keys, schema other than `1`, non-integer or non-positive codes/sizes, uppercase or malformed hash, path separators in package name, HTTP URL, and package names not ending in `.zip`.

- [ ] **Step 2: Write failing GitHub Release selection tests**

Feed `candidate_from_release()` a public API-shaped dictionary. Assert it rejects `draft=True`, `prerelease=True`, repository-external asset URLs, a missing manifest asset, duplicate package assets, mismatched package names, and releases whose `tag_name` is not `v{manifest.version}`. Assert accepted candidates retain the API-provided package asset URL rather than trusting a download URL from manifest text.

- [ ] **Step 3: Write failing cache/check tests**

Create a fake opener returning queued byte responses plus headers. Cover:

- first successful latest-release and manifest fetch;
- `version_code <= current_version_code` returning `status="current"`;
- newer version returning `status="available"`;
- automatic recheck within 86,400 seconds using cache and making zero network calls;
- `force=True` bypassing age cache;
- network error returning `status="error"` without deleting the last good cache;
- corrupt cache ignored safely;
- atomic cache JSON with `last_checked`, ETag, release URL, and candidate fields.

- [ ] **Step 4: Run focused tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m unittest -v tests.test_app_updater`

Expected: FAIL because `app_updater` interfaces are absent.

- [ ] **Step 5: Implement immutable models and strict parsers**

Define `UpdateManifest` fields exactly as the manifest schema, `UpdateCandidate(manifest, package_url, published_at)`, and `UpdateCheckResult(status, message, candidate=None, from_cache=False)`. Parse JSON with exact type checks that reject Python `bool` where an integer is required. Normalize no user-provided path during discovery; package remains a leaf filename only.

- [ ] **Step 6: Implement cached GitHub discovery**

Use `https://api.github.com/repos/axechaso/frlg-auto-rng/releases/latest`, a 15-second timeout, explicit `Accept: application/vnd.github+json`, and a product `User-Agent`. Store cache under the provided directory with an atomic sibling replacement. Catch network/JSON/schema errors into `UpdateCheckResult(status="error")`; do not raise into the GUI thread.

- [ ] **Step 7: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_app_updater
git add app_updater.py tests/test_app_updater.py
git commit -m "feat: discover verified application releases"
```

---

### Task 3: Verified Download and Safe Staging

**Files:**
- Modify: `app_updater.py`
- Modify: `tests/test_app_updater.py`

**Interfaces:**
- Consumes: `UpdateCandidate` from Task 2 and Task 1's version probe contract.
- Produces: `UpdateCancelled`, `UpdatePreparationError`, and immutable `PreparedUpdate(request_id, updates_root, install_dir, stage_dir, package_path, updater_source, expected_version_code, token)`.
- Produces: `required_free_bytes(manifest: UpdateManifest) -> int`.
- Produces: `prepare_update(candidate: UpdateCandidate, *, updates_root: Path, install_dir: Path, updater_source: Path, cancel_event: threading.Event | None = None, progress: Callable[[int, int], None] | None = None, opener: Callable = urllib.request.urlopen, version_probe: Callable[[Path], dict[str, object]] | None = None) -> PreparedUpdate`.
- Produces: `write_install_request(prepared: PreparedUpdate, *, current_pid: int, result_path: Path, health_path: Path) -> Path`.

- [ ] **Step 1: Write failing disk and streaming-download tests**

Assert required space equals `bytes + unpacked_bytes + max(268435456, unpacked_bytes // 10)`. Use a chunked fake response and assert `.part` is renamed only after exact byte count and SHA match, progress is monotonic, cancellation raises `UpdateCancelled`, and short/long/hash-mismatched downloads never create the final ZIP.

- [ ] **Step 2: Write failing safe-ZIP tests**

Construct in-memory ZIPs and independently reject entries containing `..`, absolute paths, drive prefixes, backslash traversal, NULs, Unix symlink mode bits, duplicate normalized names, and extraction outside the stage root. Accept a root-layout package containing `FRLG-Auto-RNG.exe`, `FRLG-Auto-RNG-Updater.exe`, `_internal/`, and the batch launcher.

- [ ] **Step 3: Write failing staging and request tests**

Patch disk usage and the version probe. Assert staging is a hidden direct child of `install_dir.parent`, is new/nonexistent before extraction, contains `.frlg-update-stage.json` with request ID/token/version, and is rejected if the frozen version probe disagrees. Assert `write_install_request()` writes absolute normalized paths, a direct-child backup name, expected PID/version/token, and no environment variables or globs.

- [ ] **Step 4: Run the new tests and confirm failure**

Run: `.\.venv\Scripts\python.exe -m unittest -v tests.test_app_updater`

Expected: new download/staging cases FAIL.

- [ ] **Step 5: Implement streaming validation and extraction**

Download in 1 MiB chunks while updating `hashlib.sha256`; check cancellation between chunks. Validate ZIP members before writing any file, then extract each member manually under the resolved stage root. Do not call `ZipFile.extractall()`. Create the stage marker only after structure and frozen `--version-json` validation succeed.

- [ ] **Step 6: Implement installation-request writer**

Write `install-request.json` atomically below `updates_root/requests/{request_id}`. Backup and stage names must be deterministic leaf prefixes containing the request ID; include no arbitrary command line from the manifest.

- [ ] **Step 7: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_app_updater
git add app_updater.py tests/test_app_updater.py
git commit -m "feat: stage verified full-package updates"
```

---

### Task 4: Independent Installer, Directory Swap, and Rollback

**Files:**
- Create: `update_installer.py`
- Create: `updater_entry.py`
- Create: `tests/test_update_installer.py`

**Interfaces:**
- Consumes: the Task 3 install-request JSON and stage marker.
- Produces: `InstallRequest.from_path(path: Path) -> InstallRequest` with exact path and token validation.
- Produces: `InstallResult(status: str, message: str, launched_pid: int | None)`.
- Produces: `apply_update(request: InstallRequest, *, wait_pid: Callable[[int, float], bool], launch: Callable[[Path, list[str]], subprocess.Popen], wait_health: Callable[[Path, str, float], bool]) -> InstallResult`.
- Produces: `updater_entry.main(argv: list[str] | None = None) -> int`, accepting only `--request PATH`.

- [ ] **Step 1: Write failing request-safety tests**

Create valid sibling install/stage/backup directories in a temporary parent. Independently reject relative paths, drive/parent mismatches, install roots, stage/backup names without the exact request ID prefix, existing backup paths, marker token/version mismatch, missing frozen executables, and request/result/health paths outside `%LOCALAPPDATA%\FRLG-Auto-RNG\updates` as supplied through an injectable allowed-root argument.

- [ ] **Step 2: Write failing successful-swap test**

Use small text executables as markers and injected PID/launch/health functions. Assert the old install is renamed to backup, stage becomes the original install path, launch receives only the new executable plus health path/token, a valid health payload leads to backup removal, and the result JSON says `status="installed"`.

- [ ] **Step 3: Write failing rollback matrix**

Parameterize failures at old-directory rename, stage rename, process launch, health timeout, and result write. For every point after backup creation, assert the old directory returns to the exact original path. When a failed new directory must move aside, constrain its destination to a request-ID direct sibling. Assert unrelated sibling directories/files remain byte-identical.

- [ ] **Step 4: Write failing PID timeout and CLI tests**

Assert the installer refuses to swap if the old PID remains alive after 60 seconds. Assert updater CLI parse errors return `2`, install/rollback errors return `1`, and installed result returns `0`; all diagnostics go to the request's log/result files without requiring a console.

- [ ] **Step 5: Run tests and confirm failure**

Run: `.\.venv\Scripts\python.exe -m unittest -v tests.test_update_installer`

Expected: FAIL because the installer modules do not exist.

- [ ] **Step 6: Implement constrained swap and rollback**

Resolve and validate every path before mutation. Set updater CWD outside the install parent. Wait for the exact PID, rename old to backup, rename stage to install, launch the new executable with the health token, and wait up to 30 seconds for exact health JSON. Delete only the validated backup after health success. On failure, terminate only the newly launched PID if present, move the validated failed-new directory aside, and rename backup back to install.

- [ ] **Step 7: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_update_installer
git add update_installer.py updater_entry.py tests/test_update_installer.py
git commit -m "feat: install updates with transactional rollback"
```

---

### Task 5: GUI Update Check, Confirmation, Download, and Handoff

**Files:**
- Modify: `run_auto_rng_gui.py`
- Modify: `tests/test_gui_inputs.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `check_for_update()`, `prepare_update()`, `write_install_request()`, Task 1 constants, and the packaged updater path.
- Produces: `AutoRngApp.check_app_update(force: bool = False) -> None`, `_finish_app_update_check(result) -> None`, `download_app_update(candidate) -> None`, `_finish_app_update_download(prepared=None, error=None) -> None`, and `install_prepared_update(prepared) -> None`.
- Produces: no changes to existing hardware-worker interfaces.

- [ ] **Step 1: Write failing source/frozen and UI-state tests**

Use `SimpleNamespace`/mocks rather than opening a real Tk window. Assert source mode reports “源码模式不使用程序自更新” and makes no network call. Assert frozen mode schedules automatic `force=False`, manual button uses `force=True`, update button state follows `not busy and not _process_running()`, and busy state may complete a check but cannot start download/install.

- [ ] **Step 2: Write failing result/prompt tests**

Cover current, cached current, network error during automatic check (no messagebox), network error during manual check (one error), and available update. Available results must show current/new version, publication date, size, notes, and an explicit confirmation before download. Ensure prerelease/draft behavior stays in Task 2 and cannot be overridden by GUI state.

- [ ] **Step 3: Write failing download/handoff tests**

Assert progress callbacks are marshalled through `root.after()`, cancellation never launches updater, validation errors restore normal controls, and successful preparation copies only `FRLG-Auto-RNG-Updater.exe` to the exact update request directory. Assert handoff starts that copied updater hidden with `--request`, stores no secret, sets an “installing” close state, and invokes normal GUI shutdown without killing the updater.

- [ ] **Step 4: Run focused GUI tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m unittest -v tests.test_gui_inputs`

Expected: new updater GUI tests FAIL.

- [ ] **Step 5: Add compact GUI controls and background workers**

Add `v1.1.9` text plus “检查程序更新” beside the existing Seed update button. Schedule the automatic check after initial window creation, never on the Tk thread. Reuse `set_busy()` only for user-triggered download/preparation, not for silent startup checking. Keep update status in its own `StringVar` so normal run status remains unchanged.

- [ ] **Step 6: Implement confirmed handoff and safe close**

Before download and again before handoff, require `not self.busy` and `not self._process_running()`. Copy the updater to the request directory, launch with Windows hidden-process flags, and close only after successful `Popen`. Add a narrowly scoped flag allowing this updater-initiated close while retaining existing cancel/keep-running prompts for every other close path.

- [ ] **Step 7: Document end-user behavior and run tests**

Document the once-per-day check, manual button, 545+ MB full download expectation, untouched LocalAppData, manual first install, and rollback. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_gui_inputs tests.test_app_updater tests.test_update_installer
.\.venv\Scripts\python.exe -m py_compile run_auto_rng_gui.py
```

- [ ] **Step 8: Commit GUI integration**

```powershell
git add run_auto_rng_gui.py tests/test_gui_inputs.py README.md
git commit -m "feat: add guided whole-package updates"
```

---

### Task 6: Build the Updater and Deterministic Release Metadata

**Files:**
- Create: `tools/create_update_manifest.py`
- Create: `tests/test_update_manifest_tool.py`
- Modify: `tools/build_windows_release.ps1`
- Modify: `docs/WINDOWS_RELEASE.md`

**Interfaces:**
- Consumes: Task 1 constants, `updater_entry.py`, current local audited assets, and current EasyCon publish directory.
- Produces: `create_manifest(package: Path, unpacked_root: Path) -> dict[str, object]`.
- Produces: `update-manifest.json`, `<zip>.sha256`, `FRLG-Auto-RNG-Updater.exe`, and `FRLG-Auto-RNG-1.1.9-windows-x64.zip`.

- [ ] **Step 1: Write failing manifest-tool tests**

Create a temporary package/root and assert exact schema/version/code/package/hash/bytes/unpacked-bytes values, deterministic UTF-8 JSON with LF newline, lowercase hash, and SHA file format `<hash>  <filename>\n`. Assert a wrong ZIP suffix, missing package, empty root, or filename inconsistent with `APP_VERSION` is rejected.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `.\.venv\Scripts\python.exe -m unittest -v tests.test_update_manifest_tool`

Expected: FAIL because the tool does not exist.

- [ ] **Step 3: Implement manifest generation**

Stream the ZIP hash with 1 MiB reads; sum only regular unpacked files; emit `notes` from a required build argument and `release_url` from the exact `v1.1.9` tag. Reuse `parse_manifest()` to self-validate the generated JSON before returning success.

- [ ] **Step 4: Extend the build script**

Build `updater_entry.py` as PyInstaller `--onefile --windowed --name FRLG-Auto-RNG-Updater` in a separate work/dist path. Copy it into the release root before compression. Name the release root and ZIP `FRLG-Auto-RNG-1.1.9-windows-x64`. After compression, call the manifest tool and preserve ZIP/manifest/SHA in the unique `-BuildTag` root.

- [ ] **Step 5: Add frozen smoke checks**

Run the main frozen executable with `--version-json` under `CREATE_NO_WINDOW` and assert exact Task 1 payload. Run the frozen updater with an invalid temp request and assert controlled nonzero exit plus result log, then run a full temporary-directory simulated swap with no hardware. Verify ZIP CRC and assert updater/main executables and `_internal/app_version.pyc` archive entry are present.

- [ ] **Step 6: Run tests and document publisher prerequisites**

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_update_manifest_tool tests.test_package_entry tests.test_update_installer
.\.venv\Scripts\python.exe -m py_compile tools/create_update_manifest.py
```

Update `docs/WINDOWS_RELEASE.md` with exact outputs, local asset prerequisites, disk-space expectations, and frozen checks.

- [ ] **Step 7: Commit build support**

```powershell
git add tools/create_update_manifest.py tests/test_update_manifest_tool.py tools/build_windows_release.ps1 docs/WINDOWS_RELEASE.md
git commit -m "build: produce self-updating Windows releases"
```

---

### Task 7: Safe Local GitHub Release Publisher

**Files:**
- Create: `tools/publish_windows_release.ps1`
- Create: `tests/test_windows_release_scripts.py`
- Modify: `docs/WINDOWS_RELEASE.md`

**Interfaces:**
- Consumes: a clean tracked `main` commit already pushed to `origin`, successful CI, and Task 6's verified ZIP/manifest/SHA.
- Produces: draft then stable tag/Release `v1.1.9` with exactly the three expected assets.

- [ ] **Step 1: Write failing script-contract tests**

Read the PowerShell source as text and assert it requires exact tag `v$APP_VERSION`, checks `git diff --quiet`, compares local/remote commit IDs, calls `gh api user --jq .login` before declaring authentication failure, verifies successful CI for HEAD, creates a draft Release, uploads three explicit literal paths, reads assets back by API, checks names/sizes, and publishes only after all checks. Assert no token literal, wildcard upload, `Remove-Item` on release assets, or automatic overwrite of an existing tag.

- [ ] **Step 2: Run focused test and observe failure**

Run: `.\.venv\Scripts\python.exe -m unittest -v tests.test_windows_release_scripts`

Expected: FAIL because publisher script is absent.

- [ ] **Step 3: Implement preflight and draft creation**

Accept `-BuildRoot`, `-Tag`, and `-Title`; resolve and validate all paths under repository `.build`. Require `main`, no tracked diff, `origin/main == HEAD`, exact version/tag/manifest agreement, and an existing successful GitHub Actions run for the commit. Use the mandated direct `gh api user --jq .login` check to distinguish authentication failure from keyring/network timeout.

- [ ] **Step 4: Implement upload verification and publication**

Refuse an existing tag/Release. Create a draft Release, upload the exact ZIP, manifest, and SHA paths, fetch Release asset JSON, and compare the three expected leaf names and byte sizes. Only then edit `draft=false` and `make_latest=true`. On failure, print the draft URL and leave it draft for inspection.

- [ ] **Step 5: Run tests and dry-run preflight**

Add `-DryRun` so tests can execute every preflight against their temporary fixture and capture the intended `gh` actions without creating a tag or Release. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v tests.test_windows_release_scripts
```

Expected: unit tests PASS, including a fixture-backed dry-run that records no external mutation.

- [ ] **Step 6: Commit publisher**

```powershell
git add tools/publish_windows_release.ps1 tests/test_windows_release_scripts.py docs/WINDOWS_RELEASE.md
git commit -m "build: publish verified Windows release assets"
```

---

### Task 8: Full Verification, Push, Build, and Publish v1.1.9

**Files:**
- Modify: `docs/HANDOFF.md`
- Generated/ignored: `.build/windows-release-updater-1-1-9/`
- Release assets: ZIP, `update-manifest.json`, and `.sha256`

**Interfaces:**
- Consumes: all prior tasks, real EasyCon `1.6.4-a+9c86137`, current local audited assets, public GitHub repository, and explicit user authorization to publish.
- Produces: pushed `main`, successful CI, stable GitHub Release `v1.1.9`, and locally retained verification evidence.

- [ ] **Step 1: Run all Python tests without hardware**

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m py_compile app_version.py app_updater.py update_installer.py updater_entry.py package_entry.py run_auto_rng_gui.py tools/create_update_manifest.py
```

Expected: every test PASS; compile exits `0`. If Windows process-tree tests are sandbox-blocked, rerun the unchanged suite outside the sandbox and record both outcomes rather than skipping tests.

- [ ] **Step 2: Run all 1.1.8 source checks and real EasyCon format checks**

Run every `C:\Users\axenx\Downloads\NS火叶全自动一键乱数1.1.8\Tools\check_*.py`. Run the pinned `ezcon.exe format` on the formal and timeline source entries plus freshly generated formal and egg runtime entries. Expected: all checks and all four formats PASS; no hardware is opened.

- [ ] **Step 3: Run repository and security checks**

```powershell
git diff --check
git status --short
```

Review every tracked diff. Confirm unrelated untracked `bin/`, `obj/`, and user JSON files remain untracked and unstaged. Search built source/release content for `ghp_`, `github_pat_`, `Authorization: token`, and local usernames/absolute build paths; expected: no credential and no unintended machine-specific path in client assets.

- [ ] **Step 4: Update pre-release handoff evidence and commit**

Record version, test counts, EasyCon format checks, updater transaction tests, and the fact that hardware was not run. Commit only updater-related tracked files:

```powershell
git add docs/HANDOFF.md
git commit -m "docs: record updater release validation"
```

- [ ] **Step 5: Push main and wait for CI**

```powershell
git push origin main
$releaseCommit = git rev-parse HEAD
$runId = gh run list --commit $releaseCommit --limit 5 --json databaseId --jq '.[0].databaseId'
gh run watch $runId --exit-status
```

Expected: push succeeds and the Windows Python 3.12 CI run completes successfully. Do not publish if CI is pending or failed.

- [ ] **Step 6: Build the unique final package**

```powershell
.\tools\build_windows_release.ps1 `
  -BuildTag updater-1-1-9 `
  -OutputName FRLG-Auto-RNG-1.1.9-windows-x64 `
  -LocalAssets .\local_assets `
  -EasyConPublish 'C:\Users\axenx\Downloads\伊机控-EasyCon-v1.6.4alpha测试版-260518\publish'
```

Expected: unique build directory exists; old packages are unchanged; frozen main/updater smoke, simulated swap, ZIP CRC, manifest self-validation, and SHA checks PASS.

- [ ] **Step 7: Publish the complete draft then stable Release**

```powershell
.\tools\publish_windows_release.ps1 `
  -BuildRoot .build\windows-release-updater-1-1-9 `
  -Tag v1.1.9 `
  -Title "FRLG Auto RNG 1.1.9 整包更新器版"
```

Expected: three assets upload to a draft; asset names/sizes are read back and verified; only then Release becomes stable/latest.

- [ ] **Step 8: Verify the public Release as an unauthenticated client**

Use an unauthenticated HTTPS request to `/repos/axechaso/frlg-auto-rng/releases/latest`, download the published manifest, and assert repository, tag, package URL, size, and hash equal local build evidence. Download or range-check the ZIP asset as allowed by the server, then compare the full local ZIP SHA with manifest and Release asset metadata.

- [ ] **Step 9: Record published evidence and push the documentation follow-up**

Add the final public Release URL, three asset names/sizes, manifest hash, ZIP hash, frozen smoke results, and unauthenticated verification result to `docs/HANDOFF.md`. Commit and push only that documentation update:

```powershell
git add docs/HANDOFF.md
git commit -m "docs: record v1.1.9 release evidence"
git push origin main
```

- [ ] **Step 10: Final handoff**

Provide the public Release link, direct ZIP link, size, SHA-256, version code, verification counts, and installation note: existing versions need this one manual update; future stable Releases can update in-app. State clearly that updater tests did not operate the Switch, capture card, serial port, or game save.
