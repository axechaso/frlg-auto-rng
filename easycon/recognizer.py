import json
import os
import time
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from .controller import EasyConController
from .image_label import ImgLabel
from .label_matcher import (
    match_prepared_label,
    matches_threshold,
    prepare_label,
)
from .protocol import GamePadKey


class ImageRecognizer:
    """Thin capture wrapper around the shared EasyCon-compatible matcher."""

    def __init__(self, capture_source: Optional[int] = None, use_dshow: bool = True):
        self.capture_source = capture_source
        self.cap_dev: Optional[cv2.VideoCapture] = None
        self.labels_list: List[ImgLabel] = []
        self.resolution = (1920, 1080)
        self.use_dshow = use_dshow

        if capture_source is not None:
            self.init_capture(capture_source)

    def init_capture(self, device_id: int):
        for _ in range(3):
            backend = cv2.CAP_DSHOW if self.use_dshow else cv2.CAP_ANY
            cap_dev = cv2.VideoCapture(device_id, backend)
            if cap_dev.isOpened():
                cap_dev.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                cap_dev.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                cap_dev.set(cv2.CAP_PROP_FPS, 60)
                ret, frame = cap_dev.read()
                if ret and frame is not None:
                    self.cap_dev = cap_dev
                    return
            cap_dev.release()
            time.sleep(0.5)
        raise RuntimeError(f"Cannot open capture device {device_id} after 3 attempts")

    @staticmethod
    def list_capture_devices() -> List[str]:
        try:
            from pygrabber.dshow_graph import FilterGraph

            return FilterGraph().get_input_devices()
        except ImportError:
            devices = []
            for device_id in range(10):
                cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW)
                if cap.isOpened():
                    devices.append(f"Device {device_id}")
                    cap.release()
            return devices

    def set_resolution(self, width: int, height: int):
        self.resolution = (width, height)
        if self.cap_dev:
            self.cap_dev.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap_dev.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def load_label(self, label: ImgLabel):
        self.labels_list.append(label)

    def load_label_from_file(self, path: str) -> ImgLabel:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        label = ImgLabel.from_dict(data)
        # EasyCon addresses a label by the filename, not a stale JSON name.
        label.name = os.path.splitext(os.path.basename(path))[0]
        label._prepared = prepare_label(data)
        self.labels_list.append(label)
        return label

    def get_frame(self) -> Optional[np.ndarray]:
        if self.cap_dev:
            ret, frame = self.cap_dev.read()
            if ret:
                return frame
        return None

    @staticmethod
    def _prepare(label: ImgLabel) -> dict:
        signature = (
            label.image_base64,
            label.range_x,
            label.range_y,
            label.range_width,
            label.range_height,
            label.search_method,
        )
        prepared = getattr(label, "_prepared", None)
        if prepared is not None and getattr(label, "_prepared_signature", None) == signature:
            return prepared
        prepared = prepare_label(label.to_dict())
        label._prepared = prepared
        label._prepared_signature = signature
        return prepared

    def search(
        self,
        label_name: str,
        frame: Optional[np.ndarray] = None,
    ) -> Tuple[bool, int, Tuple[int, int]]:
        label = next((item for item in self.labels_list if item.name == label_name), None)
        if label is None:
            raise ValueError(f"Label '{label_name}' not found")
        if frame is None:
            frame = self.get_frame()
        if frame is None:
            raise RuntimeError("No frame available")

        prepared = self._prepare(label)
        match = match_prepared_label(frame, prepared)
        template = prepared["template"]
        # Preserve this class's historical absolute-center return contract,
        # expressed in the labels' 1920x1080 reference coordinates.
        abs_x = prepared["rx"] + match.location[0] + template.shape[1] // 2
        abs_y = prepared["ry"] + match.location[1] + template.shape[0] // 2
        return (
            matches_threshold(match, label.threshold),
            match.easycon_degree,
            (abs_x, abs_y),
        )

    def search_all(self, frame: Optional[np.ndarray] = None) -> dict:
        if frame is None:
            frame = self.get_frame()
        return {label.name: self.search(label.name, frame) for label in self.labels_list}

    def release(self):
        if self.cap_dev:
            self.cap_dev.release()
            self.cap_dev = None


class EasyConScript:
    def __init__(self, controller: EasyConController, recognizer: Optional[ImageRecognizer] = None):
        self.controller = controller
        self.recognizer = recognizer

    def wait_for(self, label_name: str, timeout_ms: int = 10000, check_interval_ms: int = 100) -> bool:
        if self.recognizer is None:
            raise RuntimeError("ImageRecognizer not provided")
        start = time.time()
        timeout_sec = timeout_ms / 1000.0
        while time.time() - start < timeout_sec:
            found, _, _ = self.recognizer.search(label_name)
            if found:
                return True
            time.sleep(check_interval_ms / 1000.0)
        return False

    def click_when_found(self, label_name: str, key: GamePadKey, timeout_ms: int = 10000) -> bool:
        if self.wait_for(label_name, timeout_ms):
            self.controller.click(key)
            return True
        return False

    def loop_until_found(self, label_name: str, action: Callable, interval_ms: int = 1000):
        while True:
            found, _, _ = self.recognizer.search(label_name)
            if found:
                break
            action()
            time.sleep(interval_ms / 1000.0)
