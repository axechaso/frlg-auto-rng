# Japanese TID OCR Capture Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only Japanese trainer-card TID screenshot collector and a deterministic dataset validator/preparer that the user can run against EasyCon 1.6.4-a's loopback preview without changing any ECS behavior.

**Architecture:** Two focused command-line tools live under `tools/`. The capture tool reads one complete JPEG at a time from the compatible runner's loopback MJPEG stream, validates/crops the fixed 1920×1080 TID ROI, and writes manually confirmed ground truth plus a JSONL manifest. The dataset tool treats that manifest as the source of truth, audits image/label integrity, deduplicates by image hash, performs a leakage-safe grouped split by `card_id`, and materializes a reproducible training/evaluation directory.

**Tech Stack:** Python 3 standard library, OpenCV (`cv2`), NumPy, `unittest`; EasyCon compatible runner PreviewV5 loopback MJPEG.

**Spec:** `docs/superpowers/specs/2026-08-31-japanese-tid-ocr-training-design.md`

## Global Constraints

- The only formal EasyCon target remains `1.6.4-a+9c86137`; this phase does not run or modify ECS.
- Do not modify the English OCR path, `FRLG_EN_ALL.traineddata`, `frlg_battle.traineddata`, OP, Seed, frame timing, routes, or controller inputs.
- The collector may connect only to `http://127.0.0.1:<port>/mjpeg` and must never open the capture device or send controller input.
- Ground truth must be manually entered as exactly five ASCII digits; OCR output must never become ground truth.
- Large screenshots and prepared datasets default to `D:\Codex\火叶乱数\frlg-auto-rng\runtime\tid_ocr_jp_dataset\`; training work later defaults to `D:\Codex\火叶乱数\frlg-auto-rng\runtime\tid_ocr_jp_training\`. Do not put large artifacts in the C-drive download package.
- `runtime/` is already Git-ignored. Commit code, tests, and small documentation only; do not commit real screenshots.
- Preserve leading zeroes in TIDs everywhere by using `str`, never `int`.
- Use `unittest`, matching the existing test suite; no new Python dependency is needed.
- This plan stops after collection and dataset preparation. It does not install Tesseract training tools, train a model, deploy a model, or integrate OCR into ECS.

## File Structure

- Create `tools/tid_ocr_jp_capture.py`: MJPEG extraction, frame validation, ROI cropping, atomic sample persistence, and interactive capture CLI.
- Create `tools/tid_ocr_jp_dataset.py`: manifest parsing, dataset audit, hash deduplication, grouped split, prepared-directory materialization, and CLI.
- Create `tests/test_tid_ocr_jp_capture.py`: unit and local-stream tests for capture behavior.
- Create `tests/test_tid_ocr_jp_dataset.py`: integrity, conflict, deduplication, split, and materialization tests.
- Create `docs/TID_OCR_JP_DATASET.md`: exact operating procedure for starting PreviewV5, checking the ROI, capturing normal/dim samples, validating, and preparing the dataset.

---

### Task 1: MJPEG frame reader and ROI validation

**Files:**
- Create: `tools/tid_ocr_jp_capture.py`
- Create: `tests/test_tid_ocr_jp_capture.py`

**Interfaces:**
- Consumes: PreviewV5 MJPEG bytes from `http://127.0.0.1:<port>/mjpeg`.
- Produces: `Roi`, `preview_url(preview_port)`, `iter_jpeg_frames(chunks)`, `decode_jpeg(jpeg)`, `validate_source_frame(frame)`, `crop_tid(frame, roi)`, and `fetch_preview_frame(preview_port, timeout=2.0, opener=urlopen)`.

- [ ] **Step 1: Write failing marker-split, port, frame, and ROI tests**

Create `tests/test_tid_ocr_jp_capture.py` with these initial tests:

```python
import io
import unittest

import cv2
import numpy as np

from tools.tid_ocr_jp_capture import (
    Roi,
    crop_tid,
    decode_jpeg,
    iter_jpeg_frames,
    preview_url,
    validate_source_frame,
)


class TidOcrJpCaptureFrameTests(unittest.TestCase):
    def test_extracts_jpeg_when_markers_cross_chunk_boundaries(self):
        frame = np.full((8, 12, 3), 127, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", frame)
        self.assertTrue(ok)
        jpeg = encoded.tobytes()
        chunks = [b"header" + jpeg[:1], jpeg[1:9], jpeg[9:-1], jpeg[-1:] + b"tail"]
        self.assertEqual(list(iter_jpeg_frames(chunks)), [jpeg])

    def test_ignores_noise_and_returns_two_complete_frames(self):
        frames = []
        for value in (20, 220):
            ok, encoded = cv2.imencode(
                ".jpg", np.full((8, 12, 3), value, dtype=np.uint8)
            )
            self.assertTrue(ok)
            frames.append(encoded.tobytes())
        chunks = [b"noise" + frames[0] + b"boundary" + frames[1] + b"end"]
        self.assertEqual(list(iter_jpeg_frames(chunks)), frames)

    def test_preview_url_accepts_only_a_real_tcp_port(self):
        self.assertEqual(preview_url(43123), "http://127.0.0.1:43123/mjpeg")
        for port in (0, -1, 65536):
            with self.subTest(port=port), self.assertRaises(ValueError):
                preview_url(port)

    def test_decode_rejects_invalid_jpeg(self):
        with self.assertRaisesRegex(ValueError, "JPEG"):
            decode_jpeg(b"not an image")

    def test_source_frame_must_be_1920_by_1080(self):
        validate_source_frame(np.zeros((1080, 1920, 3), dtype=np.uint8))
        with self.assertRaisesRegex(ValueError, "1920x1080"):
            validate_source_frame(np.zeros((720, 1280, 3), dtype=np.uint8))

    def test_crop_preserves_exact_roi_dimensions(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        roi = Roi(x=1280, y=105, width=360, height=125)
        self.assertEqual(crop_tid(frame, roi).shape, (125, 360, 3))

    def test_crop_rejects_roi_outside_source_frame(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, "ROI"):
            crop_tid(frame, Roi(x=1800, y=1000, width=360, height=125))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test module and verify the import fails**

Run:

```powershell
python -m unittest tests.test_tid_ocr_jp_capture -v
```

Expected: `ERROR` with `ModuleNotFoundError: No module named 'tools.tid_ocr_jp_capture'`.

- [ ] **Step 3: Implement the MJPEG and ROI primitives**

Create `tools/tid_ocr_jp_capture.py` with the following public behavior:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import BinaryIO, Callable, Iterable, Iterator
from urllib.request import urlopen

import cv2
import numpy as np

SOURCE_WIDTH = 1920
SOURCE_HEIGHT = 1080
DEFAULT_ROI = None  # assigned after Roi is defined


@dataclass(frozen=True)
class Roi:
    x: int
    y: int
    width: int
    height: int

    def validate(self, source_width: int, source_height: int) -> None:
        if self.x < 0 or self.y < 0 or self.width <= 0 or self.height <= 0:
            raise ValueError(f"ROI 参数无效: {asdict(self)}")
        if self.x + self.width > source_width or self.y + self.height > source_height:
            raise ValueError(
                f"ROI 超出 {source_width}x{source_height} 画面: {asdict(self)}"
            )


DEFAULT_ROI = Roi(x=1280, y=105, width=360, height=125)


def preview_url(preview_port: int) -> str:
    if preview_port < 1 or preview_port > 65535:
        raise ValueError("预览端口必须在 1..65535")
    return f"http://127.0.0.1:{preview_port}/mjpeg"


def iter_jpeg_frames(chunks: Iterable[bytes]) -> Iterator[bytes]:
    buffer = bytearray()
    for chunk in chunks:
        if not chunk:
            continue
        buffer.extend(chunk)
        while True:
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                if len(buffer) > 1:
                    del buffer[:-1]
                break
            end = buffer.find(b"\xff\xd9", start + 2)
            if end < 0:
                if start:
                    del buffer[:start]
                break
            yield bytes(buffer[start : end + 2])
            del buffer[: end + 2]


def decode_jpeg(jpeg: bytes) -> np.ndarray:
    frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        raise ValueError("无法解码预览 JPEG")
    return frame


def validate_source_frame(frame: np.ndarray) -> None:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("预览画面必须是三通道 BGR 图像")
    height, width = frame.shape[:2]
    if (width, height) != (SOURCE_WIDTH, SOURCE_HEIGHT):
        raise ValueError(
            f"预览画面必须是 1920x1080，实际为 {width}x{height}"
        )


def crop_tid(frame: np.ndarray, roi: Roi) -> np.ndarray:
    validate_source_frame(frame)
    roi.validate(frame.shape[1], frame.shape[0])
    return frame[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width].copy()
```

Add a bounded response reader rather than reading the entire endless stream:

```python
def _response_chunks(response: BinaryIO, chunk_size: int = 65536) -> Iterator[bytes]:
    read_chunk = getattr(response, "read1", response.read)
    while True:
        chunk = read_chunk(chunk_size)
        if not chunk:
            return
        yield chunk


def fetch_preview_frame(
    preview_port: int,
    *,
    timeout: float = 2.0,
    opener: Callable = urlopen,
) -> np.ndarray:
    response = opener(preview_url(preview_port), timeout=timeout)
    try:
        for jpeg in iter_jpeg_frames(_response_chunks(response)):
            frame = decode_jpeg(jpeg)
            validate_source_frame(frame)
            return frame
    finally:
        response.close()
    raise RuntimeError("EasyCon 预览流在连接关闭前没有返回完整 JPEG")
```

- [ ] **Step 4: Add and pass a fake-response test for `fetch_preview_frame`**

Add this test and import `fetch_preview_frame`:

```python
    def test_fetch_reads_one_frame_and_closes_response(self):
        frame = np.full((1080, 1920, 3), 33, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", frame)
        self.assertTrue(ok)

        class Response(io.BytesIO):
            def __init__(self, payload):
                super().__init__(payload)
                self.was_closed = False

            def close(self):
                self.was_closed = True
                super().close()

        response = Response(b"--frame\r\n" + encoded.tobytes())
        calls = []

        def opener(url, timeout):
            calls.append((url, timeout))
            return response

        actual = fetch_preview_frame(43123, timeout=1.5, opener=opener)
        self.assertEqual(actual.shape, (1080, 1920, 3))
        self.assertEqual(calls, [("http://127.0.0.1:43123/mjpeg", 1.5)])
        self.assertTrue(response.was_closed)
```

Run:

```powershell
python -m unittest tests.test_tid_ocr_jp_capture -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the frame-reader slice**

```powershell
git add tools/tid_ocr_jp_capture.py tests/test_tid_ocr_jp_capture.py
git commit -m "feat: read Japanese TID preview frames"
```

---

### Task 2: Atomic sample persistence and interactive capture CLI

**Files:**
- Modify: `tools/tid_ocr_jp_capture.py`
- Modify: `tests/test_tid_ocr_jp_capture.py`

**Interfaces:**
- Consumes: `fetch_preview_frame()`, `Roi`, a manually entered five-digit string, `brightness`, `session_id`, and `card_id`.
- Produces: `validate_tid_text(raw) -> str`, `save_reference_images(frame, roi, session_dir) -> tuple[Path, Path]`, `save_sample(...) -> dict[str, object]`, `build_parser()`, and `main(argv=None, input_fn=input, opener=urlopen) -> int`.

- [ ] **Step 1: Write failing persistence tests**

Extend `tests/test_tid_ocr_jp_capture.py` with temporary-directory tests:

```python
import json
from pathlib import Path
import tempfile

from tools.tid_ocr_jp_capture import save_reference_images, save_sample, validate_tid_text


class TidOcrJpSampleTests(unittest.TestCase):
    def test_tid_validation_preserves_leading_zero(self):
        self.assertEqual(validate_tid_text("00042"), "00042")
        for value in ("42", "123456", "12a45", "１２３４５"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_tid_text(value)

    def test_save_sample_writes_png_gt_and_manifest(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[105:230, 1280:1640] = 211
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = save_sample(
                frame,
                "00042",
                output_root=root,
                session_id="session-a",
                card_id="card-a",
                brightness="dim",
                roi=Roi(1280, 105, 360, 125),
                preview_port=43123,
                captured_at="2026-08-31T12:00:00.000000Z",
                sample_id="sample-a",
            )
            image_path = root / record["image_path"]
            gt_path = root / record["gt_path"]
            self.assertTrue(image_path.is_file())
            self.assertEqual(gt_path.read_text(encoding="utf-8"), "00042\n")
            self.assertEqual(cv2.imread(str(image_path)).shape, (125, 360, 3))
            lines = (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(lines[0]), record)
            self.assertEqual(record["ground_truth_source"], "manual")
            self.assertEqual(record["source_width"], 1920)
            self.assertEqual(record["source_height"], 1080)

    def test_invalid_tid_or_brightness_writes_nothing(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                save_sample(
                    frame, "1234", output_root=root, session_id="s", card_id="c",
                    brightness="normal", roi=DEFAULT_ROI, preview_port=43123,
                )
            with self.assertRaises(ValueError):
                save_sample(
                    frame, "12345", output_root=root, session_id="s", card_id="c",
                    brightness="auto", roi=DEFAULT_ROI, preview_port=43123,
                )
            self.assertFalse((root / "manifest.jsonl").exists())
```

- [ ] **Step 2: Run the focused tests and verify the new imports fail**

Run:

```powershell
python -m unittest tests.test_tid_ocr_jp_capture.TidOcrJpSampleTests -v
```

Expected: `ImportError` for the not-yet-defined persistence functions.

- [ ] **Step 3: Implement validation, atomic writes, references, and manifest records**

Add imports for `argparse`, `hashlib`, `json`, `os`, `Path`, `datetime`, `timezone`, and `uuid`. Define the D-workspace-relative default:

```python
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "runtime" / "tid_ocr_jp_dataset"
VALID_BRIGHTNESS = frozenset({"normal", "dim"})


def validate_tid_text(raw: str) -> str:
    value = raw.strip()
    if len(value) != 5 or any(character not in "0123456789" for character in value):
        raise ValueError("TID 必须是恰好五位 ASCII 数字，例如 00042")
    return value


def _encode_png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("无法编码 PNG")
    return encoded.tobytes()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)
```

Implement `save_reference_images()` so it writes `full-frame-reference.png` and `full-frame-roi.png` only when absent. The ROI preview is a copy of the full frame with a two-pixel red rectangle around the crop.

Implement `save_sample()` with this exact signature:

```python
def save_sample(
    frame: np.ndarray,
    tid_text: str,
    *,
    output_root: Path,
    session_id: str,
    card_id: str,
    brightness: str,
    roi: Roi,
    preview_port: int,
    captured_at: str | None = None,
    sample_id: str | None = None,
) -> dict[str, object]:
```

Validation occurs before any write. Reject empty `session_id`/`card_id`, brightness outside `normal|dim`, an invalid port, invalid source dimensions, invalid ROI, and an invalid TID. Encode the crop once, hash those PNG bytes with SHA256, and default IDs as follows:

```python
captured_at = captured_at or datetime.now(timezone.utc).isoformat(
    timespec="microseconds"
).replace("+00:00", "Z")
sample_id = sample_id or (
    captured_at.replace(":", "").replace("-", "").replace(".", "")
    + "-"
    + uuid.uuid4().hex[:8]
)
```

Write `raw/<session_id>/<sample_id>.png`, then its `.gt.txt`, then append one UTF-8 JSON line to `manifest.jsonl`. Include every spec field plus POSIX-style `image_path` and `gt_path`. Use `json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"` and flush/fsync the manifest file before returning. Refuse to overwrite an existing sample path.

- [ ] **Step 4: Add and pass reference-image and CLI argument tests**

Add tests asserting that:

```python
    def test_reference_images_are_saved_once(self):
        first = np.zeros((1080, 1920, 3), dtype=np.uint8)
        second = np.full((1080, 1920, 3), 255, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "raw" / "session-a"
            reference, preview = save_reference_images(first, DEFAULT_ROI, session)
            first_bytes = reference.read_bytes()
            save_reference_images(second, DEFAULT_ROI, session)
            self.assertEqual(reference.read_bytes(), first_bytes)
            self.assertTrue(preview.is_file())

    def test_parser_defaults_to_d_workspace_runtime(self):
        args = build_parser().parse_args(
            ["--preview-port", "43123", "--brightness", "normal"]
        )
        self.assertEqual(args.output_root, DEFAULT_OUTPUT_ROOT)
        self.assertEqual(DEFAULT_OUTPUT_ROOT.drive.upper(), "D:")
```

Implement `build_parser()` with:

- required `--preview-port` and `--brightness normal|dim`;
- optional `--output-root`, defaulting to `DEFAULT_OUTPUT_ROOT`;
- optional `--session-id` and `--card-id`, each defaulting to a newly generated stable value for that invocation;
- `--x`, `--y`, `--width`, and `--height`, defaulting to `1280, 105, 360, 125`;
- `--yes-roi` for an explicit non-interactive ROI confirmation used only in tests/automation.

Implement `main()` with dependency-injected `input_fn` and `opener`. It must:

1. Fetch one initial frame.
2. Save the two session reference images and print both absolute paths.
3. Unless `--yes-roi` is present, require the user to type exactly `y` after viewing the ROI preview; otherwise exit `2` without a sample.
4. Repeatedly prompt `输入当前画面五位TID（q退出）:`.
5. Validate the text before fetching a new frame.
6. Fetch one current frame, save exactly one sample, and print its absolute PNG path and `card_id`.
7. On `q`, return `0`. On connection/decoding/write errors, print one concise error to stderr and return `1` without synthesizing a record.

Use this entry point:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

Run:

```powershell
python -m unittest tests.test_tid_ocr_jp_capture -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the usable collector**

```powershell
git add tools/tid_ocr_jp_capture.py tests/test_tid_ocr_jp_capture.py
git commit -m "feat: collect Japanese TID ground truth"
```

---

### Task 3: Dataset integrity audit and hash deduplication

**Files:**
- Create: `tools/tid_ocr_jp_dataset.py`
- Create: `tests/test_tid_ocr_jp_dataset.py`

**Interfaces:**
- Consumes: `runtime/tid_ocr_jp_dataset/manifest.jsonl` and its referenced PNG/GT pairs.
- Produces: immutable `SampleRecord`, `ValidationReport`, `load_manifest(root)`, and `validate_dataset(root)`. Validation does not mutate the dataset.

- [ ] **Step 1: Write failing valid-pair, duplicate, and conflict tests**

Create `tests/test_tid_ocr_jp_dataset.py`. Use `save_sample()` to make real records rather than hand-writing structurally invalid fixtures:

```python
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tools.tid_ocr_jp_capture import DEFAULT_ROI, save_sample
from tools.tid_ocr_jp_dataset import DatasetValidationError, validate_dataset


def write_sample(root: Path, sample_id: str, tid: str, value: int, card_id: str):
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[105:230, 1280:1640] = value
    return save_sample(
        frame,
        tid,
        output_root=root,
        session_id="session-a",
        card_id=card_id,
        brightness="normal",
        roi=DEFAULT_ROI,
        preview_port=43123,
        captured_at=f"2026-08-31T12:00:0{value % 10}.000000Z",
        sample_id=sample_id,
    )


class TidOcrJpDatasetValidationTests(unittest.TestCase):
    def test_valid_dataset_returns_canonical_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_sample(root, "a", "00042", 20, "card-a")
            report = validate_dataset(root)
            self.assertEqual(report.errors, ())
            self.assertEqual([record.tid_text for record in report.canonical], ["00042"])

    def test_identical_image_and_tid_is_one_canonical_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_sample(root, "a", "12345", 20, "card-a")
            write_sample(root, "b", "12345", 20, "card-a")
            report = validate_dataset(root)
            self.assertEqual(len(report.canonical), 1)
            self.assertEqual(report.duplicate_sample_ids, (("a", "b"),))

    def test_identical_image_with_conflicting_tid_is_hard_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_sample(root, "a", "12345", 20, "card-a")
            write_sample(root, "b", "12346", 20, "card-a")
            with self.assertRaisesRegex(DatasetValidationError, "真值冲突"):
                validate_dataset(root, raise_on_error=True)

    def test_gt_text_must_equal_manifest_tid_including_leading_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = write_sample(root, "a", "00042", 20, "card-a")
            (root / record["gt_path"]).write_text("42\n", encoding="utf-8")
            with self.assertRaisesRegex(DatasetValidationError, "gt.txt"):
                validate_dataset(root, raise_on_error=True)
```

- [ ] **Step 2: Run the dataset tests and verify the module import fails**

Run:

```powershell
python -m unittest tests.test_tid_ocr_jp_dataset -v
```

Expected: `ModuleNotFoundError: No module named 'tools.tid_ocr_jp_dataset'`.

- [ ] **Step 3: Implement typed manifest parsing and read-only validation**

Create `tools/tid_ocr_jp_dataset.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

import cv2

from tools.tid_ocr_jp_capture import Roi, validate_tid_text


class DatasetValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SampleRecord:
    sample_id: str
    session_id: str
    card_id: str
    tid_text: str
    brightness: str
    roi: Roi
    source_width: int
    source_height: int
    image_sha256: str
    captured_at: str
    preview_port: int
    ground_truth_source: str
    image_path: str
    gt_path: str


@dataclass(frozen=True)
class ValidationReport:
    canonical: tuple[SampleRecord, ...]
    duplicate_sample_ids: tuple[tuple[str, ...], ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
```

`load_manifest(root)` reads non-empty lines in order and validates required fields/types. Convert `roi` to `Roi`; keep `tid_text` as a string. Invalid JSON and missing/type-invalid fields become line-numbered `DatasetValidationError` messages.

`validate_dataset(root, *, raise_on_error=False)` must audit each record in this order:

1. `sample_id`, `session_id`, and `card_id` are non-empty and `sample_id` is unique.
2. `tid_text` passes `validate_tid_text()`; brightness is `normal|dim`; ground truth source is `manual`.
3. `image_path` and `gt_path` are relative, contain no `..`, and resolve under `root`.
4. Both files exist; GT content after removing one trailing newline equals `tid_text` exactly.
5. SHA256 of PNG bytes equals `image_sha256`.
6. OpenCV decodes the PNG and its dimensions equal `roi.width × roi.height`.
7. Source dimensions are `1920×1080`; ROI is valid inside them.
8. Every sample-like `.png`/`.gt.txt` under `raw/*/` is referenced exactly once. Exclude only `full-frame-reference.png` and `full-frame-roi.png` from this orphan check.

Group records by `image_sha256`. A group with more than one `tid_text` adds a hard `真值冲突` error. A group with one TID keeps its first manifest record as canonical and records all sample IDs as one duplicate tuple. Sort final errors/warnings for stable test output while preserving canonical manifest order. If `raise_on_error=True` and errors exist, raise one `DatasetValidationError` containing all errors separated by newlines.

- [ ] **Step 4: Add corruption, orphan, ROI, and path-escape tests**

Add tests for these exact failures:

- change one byte of a valid PNG and expect `SHA256` or decode error;
- edit manifest ROI width from `360` to `359` and expect dimension mismatch;
- add `raw/session-a/orphan.gt.txt` without PNG and expect pair error;
- replace `image_path` with `../outside.png` and expect path escape rejection;
- duplicate a `sample_id` and expect uniqueness rejection;
- delete `manifest.jsonl` and expect a clear missing-manifest error.

Run:

```powershell
python -m unittest tests.test_tid_ocr_jp_dataset.TidOcrJpDatasetValidationTests -v
```

Expected: all integrity tests pass.

- [ ] **Step 5: Commit the audit slice**

```powershell
git add tools/tid_ocr_jp_dataset.py tests/test_tid_ocr_jp_dataset.py
git commit -m "feat: validate Japanese TID datasets"
```

---

### Task 4: Leakage-safe grouped split and prepared dataset output

**Files:**
- Modify: `tools/tid_ocr_jp_dataset.py`
- Modify: `tests/test_tid_ocr_jp_dataset.py`

**Interfaces:**
- Consumes: `ValidationReport.canonical` only; duplicate frames never enter the split twice.
- Produces: `DatasetSplit`, `grouped_split(records, eval_fraction=0.2, seed=20260831)`, `prepare_dataset(root, output_dir=None, eval_fraction=0.2, seed=20260831, replace=False)`, `build_parser()`, and `main(argv=None) -> int`.

- [ ] **Step 1: Write failing deterministic grouped-split tests**

Extend `tests/test_tid_ocr_jp_dataset.py`:

```python
from tools.tid_ocr_jp_dataset import grouped_split, prepare_dataset


class TidOcrJpDatasetSplitTests(unittest.TestCase):
    def _records(self, root: Path):
        for index in range(10):
            record = write_sample(
                root,
                f"sample-{index}",
                f"{index:05d}",
                10 + index,
                f"card-{index // 2}",
            )
            if index % 2:
                lines = (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
                payload = json.loads(lines[-1])
                payload["brightness"] = "dim"
                lines[-1] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                (root / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return validate_dataset(root, raise_on_error=True).canonical

    def test_split_is_deterministic_and_never_leaks_card_id(self):
        with tempfile.TemporaryDirectory() as directory:
            records = self._records(Path(directory))
            first = grouped_split(records, eval_fraction=0.2, seed=20260831)
            second = grouped_split(records, eval_fraction=0.2, seed=20260831)
            self.assertEqual(first, second)
            train_cards = {record.card_id for record in first.train}
            eval_cards = {record.card_id for record in first.eval}
            self.assertTrue(train_cards)
            self.assertTrue(eval_cards)
            self.assertTrue(train_cards.isdisjoint(eval_cards))

    def test_both_sides_keep_normal_and_dim_when_groups_allow_it(self):
        with tempfile.TemporaryDirectory() as directory:
            records = self._records(Path(directory))
            split = grouped_split(records, eval_fraction=0.4, seed=7)
            self.assertEqual({record.brightness for record in split.train}, {"normal", "dim"})
            self.assertEqual({record.brightness for record in split.eval}, {"normal", "dim"})

    def test_one_card_cannot_be_split_without_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_sample(root, "a", "12345", 20, "only-card")
            records = validate_dataset(root, raise_on_error=True).canonical
            with self.assertRaisesRegex(ValueError, "至少两张"):
                grouped_split(records)
```

- [ ] **Step 2: Run the split tests and verify the functions are absent**

Run:

```powershell
python -m unittest tests.test_tid_ocr_jp_dataset.TidOcrJpDatasetSplitTests -v
```

Expected: import failure for `grouped_split` or `prepare_dataset`.

- [ ] **Step 3: Implement deterministic group selection**

Add:

```python
@dataclass(frozen=True)
class DatasetSplit:
    train: tuple[SampleRecord, ...]
    eval: tuple[SampleRecord, ...]
    seed: int
    eval_fraction: float
```

`grouped_split()` must:

1. Reject `eval_fraction <= 0` or `>= 1`, empty records, and fewer than two unique `card_id` values.
2. Group records by `card_id`.
3. Set `eval_group_count = min(group_count - 1, max(1, round(group_count * eval_fraction)))`.
4. Shuffle sorted card IDs with `random.Random(seed)` to produce a deterministic tie rank.
5. Count how many card groups contain each brightness state.
6. Select eval cards greedily. Prefer the candidate adding the largest number of brightness states still absent from eval. A candidate is feasible only if selecting it leaves at least one training card for every state that occurs in two or more card groups. Break ties by the shuffled rank.
7. If no candidate is feasible, choose the first remaining shuffled card; the final report must then warn that perfect brightness coverage was impossible.
8. Preserve original record order inside `train` and `eval`.
9. Assert train/eval `card_id` sets are non-empty and disjoint before returning.

- [ ] **Step 4: Write failing preparation-output and replace-safety tests**

Add tests that call `prepare_dataset()` and assert:

```python
    def test_prepare_copies_pairs_and_writes_split_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = self._records(root)
            prepared = prepare_dataset(root, eval_fraction=0.4, seed=9)
            payload = json.loads((prepared / "split-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["seed"], 9)
            self.assertEqual(payload["canonical_sample_count"], len(records))
            self.assertTrue(list((prepared / "train").glob("*.png")))
            self.assertTrue(list((prepared / "eval").glob("*.png")))
            self.assertFalse(
                set(payload["train_card_ids"]) & set(payload["eval_card_ids"])
            )

    def test_prepare_refuses_to_replace_existing_output_without_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._records(root)
            prepare_dataset(root)
            with self.assertRaisesRegex(FileExistsError, "--replace"):
                prepare_dataset(root)
```

- [ ] **Step 5: Implement safe materialization and the dataset CLI**

`prepare_dataset()` defaults `output_dir` to `root / "prepared"`. It first runs `validate_dataset(root, raise_on_error=True)`, calls `grouped_split()`, and writes to a temporary sibling named `.<prepared-name>-<uuid>.tmp`. For every canonical record, copy the PNG and GT pair into `train/` or `eval/` using `<sample_id>.png` and `<sample_id>.gt.txt`.

Write `split-manifest.json` containing:

- schema `frlg-tid-ocr-jp-split/v1`;
- UTC creation timestamp;
- source manifest SHA256;
- seed and eval fraction;
- canonical and duplicate counts;
- train/eval sample IDs and card IDs;
- brightness counts for each side;
- relative source paths and prepared paths for every sample.

If `output_dir` exists and `replace=False`, remove only the temporary directory and raise `FileExistsError` mentioning `--replace`. If `replace=True`, verify `output_dir.resolve()` is under `root.resolve()`, rename the old output to a sibling backup, atomically rename the temporary directory into place, then delete only that validated backup. On any rename failure, restore the backup. Never accept `root`, a drive root, or a path outside the dataset root as `output_dir`.

Add a CLI with subcommands:

```text
python tools/tid_ocr_jp_dataset.py validate --root <dataset>
python tools/tid_ocr_jp_dataset.py prepare --root <dataset> --eval-fraction 0.2 --seed 20260831
python tools/tid_ocr_jp_dataset.py prepare --root <dataset> --replace
```

`build_parser()` imports `DEFAULT_OUTPUT_ROOT` from the capture module and uses it as the default for every subcommand's `--root`, so the shorter commands in the operator guide always target the D-workspace dataset. `main()` must accept an optional argument list, return `0` on success and `1` on validation/filesystem errors, and the module entry point must raise `SystemExit(main())`.

The `validate` command prints canonical count, duplicate count, warnings, and errors; return `0` only when there are no errors. The `prepare` command prints the absolute prepared path and train/eval card/sample counts; return `1` on validation or filesystem failure.

Run:

```powershell
python -m unittest tests.test_tid_ocr_jp_dataset -v
```

Expected: all dataset tests pass.

- [ ] **Step 6: Commit the split/preparation slice**

```powershell
git add tools/tid_ocr_jp_dataset.py tests/test_tid_ocr_jp_dataset.py
git commit -m "feat: prepare Japanese TID OCR datasets"
```

---

### Task 5: Operator documentation and complete phase verification

**Files:**
- Create: `docs/TID_OCR_JP_DATASET.md`
- Modify only if verification exposes a defect: `tools/tid_ocr_jp_capture.py`, `tools/tid_ocr_jp_dataset.py`, `tests/test_tid_ocr_jp_capture.py`, `tests/test_tid_ocr_jp_dataset.py`

**Interfaces:**
- Consumes: the two finished CLIs.
- Produces: a hardware-safe operating guide and verification evidence for the phase-1 deliverable.

- [ ] **Step 1: Write the operator guide with exact commands and stopping rules**

Create `docs/TID_OCR_JP_DATASET.md` with these sections and commands:

1. State that PreviewV5/EasyCon must already be running with a nonzero preview port; the collector never controls the game.
2. State the default large-file path on D:

```text
D:\Codex\火叶乱数\frlg-auto-rng\runtime\tid_ocr_jp_dataset\
```

3. Normal-brightness capture:

```powershell
Set-Location 'D:\Codex\火叶乱数\frlg-auto-rng'
python tools\tid_ocr_jp_capture.py --preview-port 43123 --brightness normal
```

4. Dim-state capture reusing the printed `card_id`:

```powershell
python tools\tid_ocr_jp_capture.py --preview-port 43123 --brightness dim --card-id '<previous-card-id>'
```

5. Instruct the user to open `full-frame-roi.png`, verify the red box contains all five TID digits and no neighboring text, then type `y`. If wrong, type anything else, stop without a sample, and rerun with `--x/--y/--width/--height`.
6. State that the entered TID must be visually verified and preserve leading zeroes; do not guess obscured digits.
7. Validation and preparation:

```powershell
python tools\tid_ocr_jp_dataset.py validate
python tools\tid_ocr_jp_dataset.py prepare --seed 20260831 --eval-fraction 0.2
```

8. Explain that duplicate warnings are acceptable, conflicts/errors are not, one `card_id` must never appear in both sets, and fewer than two cards cannot produce a safe split.
9. State the initial data target: about 100 distinct `card_id` values, with normal and dim captures; a smaller set tests only the tooling and is not sufficient to publish a model.
10. State explicitly that this phase performs no OCR training and changes no ECS behavior.

- [ ] **Step 2: Run both focused test modules**

Run:

```powershell
python -m unittest tests.test_tid_ocr_jp_capture tests.test_tid_ocr_jp_dataset -v
```

Expected: every new test passes with no skips.

- [ ] **Step 3: Run the entire repository unit suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: exit code `0`; all existing tests pass. If an unrelated pre-existing failure occurs, capture its exact name/output and confirm it also occurs on the parent commit before changing unrelated code.

- [ ] **Step 4: Verify CLI help and failure behavior without hardware**

Run:

```powershell
python tools\tid_ocr_jp_capture.py --help
python tools\tid_ocr_jp_dataset.py --help
python tools\tid_ocr_jp_dataset.py validate
```

Expected:

- both help commands exit `0` and document all options;
- `validate` exits nonzero with a clear missing-dataset/manifest message if no real dataset exists;
- no C-drive screenshot directory is created;
- no ECS, OCR model, or EasyCon runtime file changes.

- [ ] **Step 5: Review the final diff and repository cleanliness**

Run:

```powershell
git diff --check
git diff --stat HEAD
git status --short
```

Expected: only the two tools, two tests, operator guide, and any already-known unrelated untracked files appear. `runtime/tid_ocr_jp_dataset/` must remain ignored. Do not stage `tools/EasyCon164aCommonRegionCheck/bin/`, `tools/EasyCon164aCommonRegionCheck/obj/`, or the existing unrelated JSON files.

- [ ] **Step 6: Commit documentation or verification fixes**

```powershell
git add docs/TID_OCR_JP_DATASET.md tools/tid_ocr_jp_capture.py tools/tid_ocr_jp_dataset.py tests/test_tid_ocr_jp_capture.py tests/test_tid_ocr_jp_dataset.py
git commit -m "docs: explain Japanese TID OCR collection"
```

- [ ] **Step 7: Hardware handoff, not automated execution**

Report the exact collector command with the user's active preview port. Ask the user to inspect the saved ROI preview before confirming the first sample. Do not claim the ROI is correct or the collector works on hardware until the user reports a successful real capture.
