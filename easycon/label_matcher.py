"""EasyCon image-label matching semantics used by the pinned 1.6.4a backend.

EasyCon label coordinates are authored against a 1920x1080 frame.  Frames from
capture devices are normalized to that reference size before cropping so the
template itself is never resized.
"""

import base64
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import cv2
import numpy as np


REFERENCE_WIDTH = 1920
REFERENCE_HEIGHT = 1080


@dataclass(frozen=True)
class LabelMatch:
    degree: float
    location: tuple[int, int]
    normalized_frame: np.ndarray
    roi: np.ndarray

    @property
    def easycon_degree(self) -> int:
        """Return EasyCon's integer degree (ceiling, not truncation)."""
        return math.ceil(self.degree)


@lru_cache(maxsize=128)
def decode_label_image(image_base64: str) -> tuple[np.ndarray, np.ndarray | None]:
    """Decode a PNG/BMP IL payload and preserve an optional alpha mask."""
    image_bytes = base64.b64decode(image_base64)
    encoded = np.frombuffer(image_bytes, np.uint8)
    decoded = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if decoded is None or decoded.size == 0:
        raise ValueError("标签图像无法解码")

    if decoded.ndim == 2:
        return cv2.cvtColor(decoded, cv2.COLOR_GRAY2BGR), None
    if decoded.shape[2] == 4:
        return decoded[:, :, :3], decoded[:, :, 3]
    if decoded.shape[2] == 3:
        return decoded, None
    raise ValueError(f"不支持的标签图像通道数: {decoded.shape}")


def prepare_label(label_data: dict[str, Any]) -> dict[str, Any]:
    """Prepare one IL JSON object for repeated matching."""
    image_base64 = label_data.get("ImgBase64", "")
    if not image_base64:
        raise ValueError("标签缺少 ImgBase64")
    template, alpha_mask = decode_label_image(image_base64)
    return {
        "template": template,
        "mask": alpha_mask,
        "rx": int(label_data.get("RangeX", 0)),
        "ry": int(label_data.get("RangeY", 0)),
        "rw": int(label_data.get("RangeWidth", REFERENCE_WIDTH)),
        "rh": int(label_data.get("RangeHeight", REFERENCE_HEIGHT)),
        "search_method": int(label_data.get("searchMethod", 5)),
    }


def normalize_frame(frame: np.ndarray) -> np.ndarray:
    if frame is None or frame.size == 0:
        raise ValueError("采集帧为空")
    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    elif frame.shape[2] == 4:
        frame = frame[:, :, :3]
    aspect_ratio = frame.shape[1] / frame.shape[0]
    if abs(aspect_ratio - (16 / 9)) > 0.01:
        raise ValueError(
            f"标签只支持 16:9 采集画面，当前为 {frame.shape[1]}x{frame.shape[0]}"
        )
    if (frame.shape[1], frame.shape[0]) != (REFERENCE_WIDTH, REFERENCE_HEIGHT):
        frame = cv2.resize(
            frame,
            (REFERENCE_WIDTH, REFERENCE_HEIGHT),
            interpolation=cv2.INTER_LINEAR,
        )
    return frame


def _finite_result(result: np.ndarray, *, lower_is_better: bool) -> np.ndarray:
    fill = 1.0 if lower_is_better else -1.0
    if np.isfinite(result).all():
        return result
    return np.nan_to_num(result, nan=fill, posinf=fill, neginf=fill)


def match_prepared_label(frame: np.ndarray, label: dict[str, Any]) -> LabelMatch:
    """Match one prepared label using EasyCon's search-method numbering."""
    normalized = normalize_frame(frame)
    template = label["template"]
    mask = label.get("mask")

    rx = max(0, min(int(label.get("rx", 0)), REFERENCE_WIDTH - 1))
    ry = max(0, min(int(label.get("ry", 0)), REFERENCE_HEIGHT - 1))
    rw = max(1, min(int(label.get("rw", REFERENCE_WIDTH)), REFERENCE_WIDTH - rx))
    rh = max(1, min(int(label.get("rh", REFERENCE_HEIGHT)), REFERENCE_HEIGHT - ry))
    roi = normalized[ry:ry + rh, rx:rx + rw]

    th, tw = template.shape[:2]
    if roi.shape[0] < th or roi.shape[1] < tw:
        raise ValueError(
            f"标签模板 {tw}x{th} 大于搜索区域 {roi.shape[1]}x{roi.shape[0]}"
        )

    search_method = int(label.get("search_method", 5))
    if search_method == 14:
        if mask is None:
            raise ValueError("EasyCon 方法 14 要求标签图片包含 Alpha 通道")
        result = cv2.matchTemplate(
            roi,
            template,
            cv2.TM_SQDIFF_NORMED,
            mask=mask,
        )
        result = _finite_result(result, lower_is_better=True)
        min_value, _, min_location, _ = cv2.minMaxLoc(result)
        degree = (1.0 - min_value) * 100.0
        location = min_location
    elif search_method in (0, 1):
        mode = cv2.TM_SQDIFF if search_method == 0 else cv2.TM_SQDIFF_NORMED
        result = cv2.matchTemplate(roi, template, mode)
        result = _finite_result(result, lower_is_better=True)
        min_value, _, min_location, _ = cv2.minMaxLoc(result)
        degree = (1.0 - min_value) * 100.0
        location = min_location
    elif search_method in (2, 3):
        mode = cv2.TM_CCORR if search_method == 2 else cv2.TM_CCORR_NORMED
        result = cv2.matchTemplate(roi, template, mode)
        result = _finite_result(result, lower_is_better=False)
        _, max_value, _, max_location = cv2.minMaxLoc(result)
        degree = max_value * 100.0
        location = max_location
    elif search_method in (4, 5):
        mode = cv2.TM_CCOEFF if search_method == 4 else cv2.TM_CCOEFF_NORMED
        result = cv2.matchTemplate(roi, template, mode)
        result = _finite_result(result, lower_is_better=False)
        _, max_value, _, max_location = cv2.minMaxLoc(result)
        degree = (max_value + 1.0) * 50.0
        location = max_location
    else:
        raise ValueError(f"不支持的 EasyCon 标签搜索方法: {search_method}")

    return LabelMatch(
        degree=degree,
        location=location,
        normalized_frame=normalized,
        roi=roi,
    )


def matches_threshold(match: LabelMatch, threshold: int | float) -> bool:
    return match.easycon_degree >= threshold
