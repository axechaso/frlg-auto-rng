"""Bundled Tesseract 5 runtime used by EasyCon ``TesserDetect`` labels."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app_paths import RESOURCE_ROOT


class TesseractRuntimeError(RuntimeError):
    """Raised when the bundled EasyCon OCR runtime cannot be loaded or used."""


_DLL_NAME = "tesseract50.dll"
_LEPTONICA_DLL_NAME = "leptonica-1.82.0.dll"
_DEFAULT_LANGUAGE = "chi_sim"
_LANGUAGE_ALIASES = {
    "frlg_battle": "frlg_battle",
    "FRLG_BATTLE": "frlg_battle",
    "frlg_en_all": "FRLG_EN_ALL",
    "FRLG_EN_ALL": "FRLG_EN_ALL",
    "eng": "eng",
    "chi_sim": "chi_sim",
}
_PAGE_SEG_MODE_SINGLE_LINE = 7
_runtime_lock = threading.Lock()
_runtime: "TesseractRuntime | None" = None


def _model_exists(root: Path, language: str) -> bool:
    return (root / "Tessdata" / f"{language}.traineddata").is_file()


def bundled_runtime_root(language: str = _DEFAULT_LANGUAGE) -> Path:
    """Find models in bundled assets or the imported FRLG script package."""

    packaged = RESOURCE_ROOT / "assets" / "easycon_native"
    if _model_exists(packaged, language):
        return packaged
    # Development assets are supplied beside the generated EasyCon package.
    local_assets = RESOURCE_ROOT / "local_assets" / "easycon118"
    if _model_exists(local_assets, language):
        return local_assets
    return packaged


def resolve_tessdata_root(language: str, script_dir: Path | None = None) -> Path:
    if script_dir is not None:
        for candidate in (script_dir, script_dir.parent):
            if _model_exists(candidate, language):
                return candidate.resolve()
    return bundled_runtime_root(language)


def native_library_directory(root: Path) -> Path:
    architecture = "x64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "x86"
    candidates = (root / architecture, RESOURCE_ROOT / "assets" / "easycon_native" / architecture,
                  RESOURCE_ROOT / "local_assets" / "easycon_native" / architecture)
    for candidate in candidates:
        if all((candidate / name).is_file() for name in (_DLL_NAME, _LEPTONICA_DLL_NAME)):
            return candidate.resolve()
    raise TesseractRuntimeError("缺少原生 OCR DLL；请运行 tools/prepare_easycon164a.py 检查 assets/easycon_native/x64")


class TesseractRuntime:
    """Small ctypes binding for the Tesseract C API shipped by EasyCon.

    EasyCon creates one engine for each ``TesserDetect`` lookup. We preserve
    that behavior while caching only the loaded DLL. Frames are converted from
    the Broker's BGR24 format to contiguous RGB24 before entering Tesseract.
    """

    def __init__(self, root: str | Path | None = None, *, language: str = _DEFAULT_LANGUAGE,
                 library: Any | None = None) -> None:
        requested = str(language or _DEFAULT_LANGUAGE).strip()
        self.language = _LANGUAGE_ALIASES.get(requested, requested)
        self.root = (Path(root) if root is not None else bundled_runtime_root(self.language)).resolve()
        self.tessdata = self.root / "Tessdata"
        traineddata = self.tessdata / f"{self.language}.traineddata"
        if not traineddata.is_file():
            raise TesseractRuntimeError(f"缺少 EasyCon OCR 语言数据: {traineddata}")
        self._dll_directory: Any | None = None
        self._leptonica: Any | None = None
        self._library = library if library is not None else self._load_library()
        self._bind_api()

    def _load_library(self) -> Any:
        if sys.platform == "win32":
            dll_dir = native_library_directory(self.root)
            tesseract_dll = dll_dir / _DLL_NAME
            leptonica_dll = dll_dir / _LEPTONICA_DLL_NAME
            if not tesseract_dll.is_file() or not leptonica_dll.is_file():
                raise TesseractRuntimeError(f"缺少 EasyCon OCR DLL: {dll_dir}")
            add_directory = getattr(os, "add_dll_directory", None)
            if callable(add_directory):
                self._dll_directory = add_directory(str(dll_dir))
            try:
                # Load Leptonica first so Windows resolves Tesseract's sibling
                # dependency even on hosts with a restrictive DLL policy.
                self._leptonica = ctypes.WinDLL(str(leptonica_dll))
                return ctypes.WinDLL(str(tesseract_dll))
            except OSError as exc:
                raise TesseractRuntimeError(f"无法加载 EasyCon OCR DLL: {exc}") from exc

        library_name = ctypes.util.find_library("tesseract")
        if not library_name:
            raise TesseractRuntimeError("当前系统没有可用的 Tesseract 运行时")
        try:
            return ctypes.CDLL(library_name)
        except OSError as exc:
            raise TesseractRuntimeError(f"无法加载 Tesseract: {exc}") from exc

    def _bind_api(self) -> None:
        api = self._library
        try:
            api.TessBaseAPICreate.argtypes = []
            api.TessBaseAPICreate.restype = ctypes.c_void_p
            api.TessBaseAPIDelete.argtypes = [ctypes.c_void_p]
            api.TessBaseAPIDelete.restype = None
            api.TessBaseAPIEnd.argtypes = [ctypes.c_void_p]
            api.TessBaseAPIEnd.restype = None
            api.TessBaseAPIInit3.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
            api.TessBaseAPIInit3.restype = ctypes.c_int
            api.TessBaseAPISetPageSegMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
            api.TessBaseAPISetPageSegMode.restype = None
            api.TessBaseAPISetImage.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
            ]
            api.TessBaseAPISetImage.restype = None
            api.TessBaseAPIGetUTF8Text.argtypes = [ctypes.c_void_p]
            api.TessBaseAPIGetUTF8Text.restype = ctypes.c_void_p
            api.TessBaseAPIMeanTextConf.argtypes = [ctypes.c_void_p]
            api.TessBaseAPIMeanTextConf.restype = ctypes.c_int
            api.TessDeleteText.argtypes = [ctypes.c_void_p]
            api.TessDeleteText.restype = None
        except AttributeError as exc:
            raise TesseractRuntimeError(f"EasyCon OCR DLL 缺少 C API: {exc}") from exc

    def _initialize(self, handle: int) -> None:
        result = self._library.TessBaseAPIInit3(
            handle, os.fsencode(self.tessdata), self.language.encode("ascii"),
        )
        if int(result) != 0:
            raise TesseractRuntimeError(f"Tesseract 初始化失败 (code={result})")

    def validate_model(self) -> None:
        """Load the model before hardware is opened, without recognizing an image."""
        api = self._library
        handle = api.TessBaseAPICreate()
        if not handle:
            raise TesseractRuntimeError("无法创建 Tesseract 引擎")
        try:
            self._initialize(handle)
        finally:
            api.TessBaseAPIEnd(handle)
            api.TessBaseAPIDelete(handle)

    def read(self, frame: np.ndarray) -> tuple[str, float]:
        image = np.asarray(frame)
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise TesseractRuntimeError("TesserDetect 需要 uint8 BGR 图像")
        rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        height, width = rgb.shape[:2]
        stride = int(rgb.strides[0])

        api = self._library
        handle = api.TessBaseAPICreate()
        if not handle:
            raise TesseractRuntimeError("无法创建 Tesseract 引擎")
        text_pointer: int | None = None
        try:
            self._initialize(handle)
            api.TessBaseAPISetPageSegMode(handle, _PAGE_SEG_MODE_SINGLE_LINE)
            pixels = rgb.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte))
            api.TessBaseAPISetImage(handle, pixels, width, height, 3, stride)
            text_pointer = api.TessBaseAPIGetUTF8Text(handle)
            if not text_pointer:
                raise TesseractRuntimeError("Tesseract 没有返回文本")
            raw = ctypes.string_at(text_pointer)
            confidence = max(0.0, min(1.0, int(api.TessBaseAPIMeanTextConf(handle)) / 100.0))
            return raw.decode("utf-8", errors="replace").strip(), confidence
        except TesseractRuntimeError:
            raise
        except Exception as exc:
            raise TesseractRuntimeError(f"TesserDetect 执行失败: {exc}") from exc
        finally:
            if text_pointer:
                api.TessDeleteText(text_pointer)
            api.TessBaseAPIEnd(handle)
            api.TessBaseAPIDelete(handle)


def read_tesseract(frame: np.ndarray, *, language: str = _DEFAULT_LANGUAGE,
                   root: str | Path | None = None) -> tuple[str, float]:
    global _runtime
    with _runtime_lock:
        requested = _LANGUAGE_ALIASES.get(str(language or _DEFAULT_LANGUAGE).strip(), str(language or _DEFAULT_LANGUAGE).strip())
        if _runtime is None or _runtime.language != requested or (root is not None and _runtime.root != Path(root)):
            _runtime = TesseractRuntime(root, language=requested)
        runtime = _runtime
    return runtime.read(frame)


def reset_cached_runtime() -> None:
    """Clear the process cache; intended for tests and controlled shutdown."""

    global _runtime
    with _runtime_lock:
        _runtime = None


__all__ = [
    "TesseractRuntime",
    "TesseractRuntimeError",
    "bundled_runtime_root",
    "read_tesseract",
    "reset_cached_runtime",
]
