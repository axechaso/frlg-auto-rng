"""Runtime checks and device discovery for the in-process EasyCon engine."""

from __future__ import annotations

from pathlib import Path

from easycon.native import EasyConScriptEngine, ScriptCompileError
from easycon.native.device import PySerialUnavailableError, list_ports
from .easycon118 import EasyConRuntimeCheck


def probe_native_devices(*, include_video_names: bool = False, max_video_devices: int = 10):
    """Enumerate serial ports and OpenCV capture indexes without EasyCon CLI."""
    serial_error = None
    try:
        ports = set(list_ports())
    except PySerialUnavailableError as exc:
        ports = set()
        serial_error = str(exc)
    videos: dict[int, str] = {}
    diagnostics = ["端口（原生串口枚举）："]
    if serial_error:
        diagnostics.append(f"  {serial_error}")
    diagnostics.extend(f"  {port}" for port in sorted(ports))
    try:
        from cv2_enumerate_cameras import enumerate_cameras
        # Enumerate DirectShow monikers without opening capture drivers.  The
        # index and friendly name are the same identity used for execution.
        for camera in enumerate_cameras(700):
            videos[int(camera.index)] = camera.name or f"视频设备 {camera.index}"
    except (ImportError, OSError, RuntimeError, NotImplementedError) as exc:
        diagnostics.append(f"无法枚举采集设备：{exc}")
    diagnostics.append("采集设备（OpenCV 原生枚举）：")
    diagnostics.extend(f"  [{index}] {name}" for index, name in sorted(videos.items()))
    if not ports:
        diagnostics.append("未检测到伊机控串口。")
    if not videos:
        diagnostics.append("未检测到采集设备。")
    return ports, videos if include_video_names else set(videos), "\n".join(diagnostics)


def validate_native_runtime(project_main: str | Path, *, fingerprint_warning_only: bool = False) -> EasyConRuntimeCheck:
    """Compile, bind image labels, and validate OCR before opening hardware."""
    from easycon.native.image_labels import load_image_labels, SearchMethod, _decode_template
    from easycon.native.tesseract import TesseractRuntime, resolve_tessdata_root
    from fingerprint_policy import record_fingerprint_mismatch
    from .easycon118 import EXPECTED_TESSDATA_SHA256
    import hashlib

    main = Path(project_main).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not main.is_file():
        return EasyConRuntimeCheck(False, (f"找不到生成脚本: {main}",), ())
    try:
        program = EasyConScriptEngine().load_file(main)
    except (OSError, UnicodeError, ScriptCompileError, ValueError) as exc:
        return EasyConRuntimeCheck(False, (f"原生 ECS 语法预检失败: {exc}",), ())
    labels = load_image_labels((main.parent,))
    missing = sorted(program.external_labels.difference(labels.labels))
    if missing:
        errors.append("找不到搜图标签: " + ", ".join(missing))
    if labels.failed_files:
        errors.append("标签结构异常: " + ", ".join(path.name for path in labels.failed_files))
    languages = set(program.ocr_languages)
    for label in labels.labels.values():
        try:
            if label.search_method is SearchMethod.TESSER_DETECT:
                languages.add("chi_sim")
            else:
                template, mask = _decode_template(label.image_base64, label.name)
                if min(*label.range_rect[2:], *label.target_rect[2:]) <= 0:
                    raise ValueError("标签区域必须大于 0")
                if template.shape[1] > label.range_rect[2] or template.shape[0] > label.range_rect[3]:
                    raise ValueError("模板大于搜索区域")
                if label.search_method is SearchMethod.MASKED_SQ_DIFF_NORMED and mask is None:
                    raise ValueError("method 14 缺少 Alpha 蒙版")
        except Exception as exc:
            errors.append(f"标签 {label.name} 无法使用: {exc}")
    for language in sorted(languages):
        try:
            root = resolve_tessdata_root(language, main.parent)
            model = root / "Tessdata" / f"{language}.traineddata"
            if not model.is_file():
                raise FileNotFoundError(f"Tessdata 缺少 {language}.traineddata: {root}")
            expected = EXPECTED_TESSDATA_SHA256.get(model.name)
            if expected and hashlib.sha256(model.read_bytes()).hexdigest() != expected:
                record_fingerprint_mismatch(f"OCR 模型指纹不一致: {model.name}",
                    warning_only=fingerprint_warning_only, errors=errors, warnings=warnings)
            TesseractRuntime(root, language=language).validate_model()
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"原生 OCR 预检失败: {exc}")
    return EasyConRuntimeCheck(not errors, tuple(errors), tuple(warnings))


__all__ = ["probe_native_devices", "validate_native_runtime"]
