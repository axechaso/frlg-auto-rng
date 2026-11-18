"""Local image tests for the 170 label maker, never reported as CLI evidence.

The supported image-method formulas follow EasyCon.Capture Search/MatchFacts
and CVSearch at EasyConNS/EasyCon commit 76cdb216. Native CLI verification
remains separate; this module does not run a script or send game inputs.
"""
import json
import math
import operator as comparison
import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtGui import QImage

from easycon.label_matcher import decode_label_image


def image_bgr(image: QImage) -> np.ndarray:
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    pixels = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
    return cv2.cvtColor(pixels[:, :image.width() * 3].reshape(image.height(), image.width(), 3), cv2.COLOR_RGB2BGR)


def label_frame(image: QImage) -> QImage:
    """Use the script's 1920x1080 image coordinates, independent of UI zoom."""
    if image.isNull():
        raise ValueError("监视器尚未收到画面，请等待视频连接后再截图")
    bgr = image_bgr(image)
    if bgr.shape[:2] != (1080, 1920):
        bgr = cv2.resize(bgr, (1920, 1080), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return QImage(rgb.data, 1920, 1080, rgb.strides[0], QImage.Format.Format_RGB888).copy()


def verify_preview(label, *, frame, operator=">", threshold=95):
    start = time.monotonic()
    payload = json.loads(Path(label).read_text(encoding="utf-8-sig"))
    image = QImage(str(frame))
    if image.isNull():
        raise ValueError("测试截图无法解码")
    source = image_bgr(image)
    x, y, w, h = (int(payload["Range" + suffix]) for suffix in ("X", "Y", "Width", "Height"))
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > image.width() or y + h > image.height():
        raise ValueError("搜索范围超出测试截图")
    roi = source[y:y + h, x:x + w]
    template, mask = decode_label_image(payload["ImgBase64"])
    if template.shape[0] > h or template.shape[1] > w:
        raise ValueError("模板大于搜索范围")
    method = int(payload["searchMethod"])
    if method not in {1, 3, 5, 11, 14}:
        raise ValueError(f"本地测试不支持搜索方法 {method}")
    if any(payload.get(key) for key in ("UseGrayscale", "UseBinary", "UseGaussianBlur", "UseOther")):
        raise ValueError("该标签启用了额外预处理，请使用原生运行器复核；本地测试不推测其效果")
    if method == 11:
        def edge(src):
            gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
            gx = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=-1)
            gy = cv2.Sobel(gray, cv2.CV_16S, 0, 1, ksize=-1)
            gradient = cv2.addWeighted(gx, .5, gy, .5, 0)
            return np.clip(gradient, 0, 255).astype(np.uint8)
        roi, template = edge(roi), edge(template)
    mode = {1: cv2.TM_SQDIFF_NORMED, 3: cv2.TM_CCORR_NORMED, 5: cv2.TM_CCOEFF_NORMED,
            11: cv2.TM_CCOEFF_NORMED, 14: cv2.TM_SQDIFF_NORMED}[method]
    if method == 14 and (mask is None or not np.any(mask)):
        raise ValueError("透明背景匹配需要有有效像素的 Alpha 掩膜")
    try:
        result = cv2.matchTemplate(roi, template, mode, mask=mask if method == 14 else None)
        valid = np.isfinite(result)
        if not valid.any():
            raise ValueError("图像匹配无法得到有效分数")
        if not valid.all():
            result[~valid] = np.inf if method in {1, 14} else -np.inf
        minimum, maximum, min_loc, max_loc = cv2.minMaxLoc(result)
    except cv2.error as exc:
        raise ValueError(f"图像匹配失败：{exc}") from exc
    score = (1 - minimum) * 100 if method in {1, 14} else maximum * 100 if method == 3 else (maximum + 1) * 50
    location = min_loc if method in {1, 14} else max_loc
    integer = math.ceil(score)
    compare = {">": comparison.gt, ">=": comparison.ge, "<": comparison.lt, "<=": comparison.le}
    if operator not in compare:
        raise ValueError("无效的通过条件")
    return ({"frame_index": 0, "integer_score": integer, "raw_score": score,
             "passed": compare[operator](integer, threshold), "elapsed_ms": (time.monotonic() - start) * 1000,
             "width": image.width(), "height": image.height(), "location": [x + location[0], y + location[1]],
             "engine": "local-opencv-preview", "native_verified": False},)
