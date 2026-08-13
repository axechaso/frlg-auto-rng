import json
import os
import time
import threading
from typing import Optional, Callable, Dict

import cv2
import numpy as np

from .controller import EasyConController
from .protocol import GamePadKey
from .label_matcher import match_prepared_label, matches_threshold, prepare_label


class HoldContext:
    def __init__(self, ctx: "ScriptContext", button: str):
        self.ctx_ref = ctx
        self.button_name = button

    def __enter__(self):
        pass

    def __exit__(self, *args):
        self.ctx_ref.release(self.button_name)


class ScriptContext:
    def __init__(
        self,
        controller: Optional[EasyConController] = None,
        get_frame: Optional[Callable[[], Optional[np.ndarray]]] = None,
        log_func: Optional[Callable[[str], None]] = None,
        is_running_func: Optional[Callable[[], bool]] = None,
        ocr_func: Optional[Callable] = None,
        identify_pokemon_func: Optional[Callable] = None,
        ocr_name_func: Optional[Callable] = None,
        labels_dir: str = "assets/labels",
    ):
        self.controller_ref = controller
        self.get_frame_func = get_frame
        self.log_func = log_func
        self.is_running_func = is_running_func
        self.ocr_func = ocr_func
        self.identify_pokemon_func = identify_pokemon_func
        self.ocr_name_func = ocr_name_func
        self.labels_dir = labels_dir
        self.label_cache = {}

        # 屏幕录制
        self.recording_flag = False
        self.record_thread: Optional[threading.Thread] = None
        self.record_frames: list = []

        self.button_map = {
            'A': GamePadKey.A, 'B': GamePadKey.B, 'X': GamePadKey.X, 'Y': GamePadKey.Y,
            'L': GamePadKey.L, 'R': GamePadKey.R, 'ZL': GamePadKey.ZL, 'ZR': GamePadKey.ZR,
            'PLUS': GamePadKey.PLUS, 'MINUS': GamePadKey.MINUS,
            'HOME': GamePadKey.HOME, 'CAPTURE': GamePadKey.CAPTURE,
            'UP': GamePadKey.TOP, 'DOWN': GamePadKey.DOWN,
            'LEFT': GamePadKey.LEFT, 'RIGHT': GamePadKey.RIGHT,
        }

    def press(self, button: str, duration_ms: int = 50):
        if self.controller_ref and self.controller_ref.is_connected and duration_ms >= 0:
            key = self.button_map.get(button.upper())
            if key:
                self.controller_ref.click(key, duration_ms)

    def hold(self, button: str):
        if self.controller_ref and self.controller_ref.is_connected:
            key = self.button_map.get(button.upper())
            if key:
                self.controller_ref.press(key)
        return HoldContext(self, button)

    def release(self, button: str):
        if self.controller_ref and self.controller_ref.is_connected:
            key = self.button_map.get(button.upper())
            if key:
                self.controller_ref.release(key)

    def lstick(self, x: int, y: int, duration_ms: int = 50):
        if self.controller_ref and self.controller_ref.is_connected:
            self.controller_ref.lstick(x, y, duration_ms)

    def capture(self):
        if self.controller_ref and self.controller_ref.is_connected:
            self.controller_ref.capture()

    def log(self, msg: str):
        if self.log_func:
            self.log_func(msg)

    def is_running(self) -> bool:
        if self.is_running_func:
            return self.is_running_func()
        return False

    def get_frame(self) -> Optional[np.ndarray]:
        if self.get_frame_func:
            return self.get_frame_func()
        return None

    def screenshot(self, save_path: str) -> bool:
        """保存当前截图到文件"""
        frame = self.get_frame()
        if frame is None:
            self.log("截图失败: 无法获取画面")
            return False
        save_dir = os.path.dirname(save_path)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
        cv2.imwrite(save_path, frame)
        self.log(f"截图已保存: {save_path}")
        return True

    def load_label(self, label_name):
        label_path = os.path.join(self.labels_dir, f"{label_name}.IL")
        if not os.path.exists(label_path):
            self.label_cache.pop(label_name, None)
            return None

        with open(label_path, 'r', encoding='utf-8') as f:
            label_data = json.load(f)

        if not label_data.get('ImgBase64'):
            self.label_cache.pop(label_name, None)
            return None

        cached = prepare_label(label_data)
        stat = os.stat(label_path)
        self.label_cache[label_name] = (stat.st_mtime_ns, stat.st_size, cached)
        return cached

    def search_label(self, label_name: str, threshold: int = 80, seconds: float = None, debug: bool = False):
        if seconds:
            if self.search_label(label_name, threshold):
                time.sleep(seconds)
                return self.search_label(label_name, threshold)
            return False

        try:
            label_path = os.path.join(self.labels_dir, f"{label_name}.IL")
            entry = self.label_cache.get(label_name)
            cached = None
            if entry is not None and os.path.exists(label_path):
                stat = os.stat(label_path)
                if entry[:2] == (stat.st_mtime_ns, stat.st_size):
                    cached = entry[2]
            if cached is None:
                cached = self.load_label(label_name)
                if cached is None:
                    return 0 if threshold == -1 else False

            frame = self.get_frame()
            if frame is None:
                return 0 if threshold == -1 else False

            match = match_prepared_label(frame, cached)
            match_degree = match.degree
            found = matches_threshold(match, threshold)
            degree_int = match.easycon_degree

            if debug:
                marker = "*" if found else " "
                self.log(f"  [{marker}] {label_name} = {match_degree:.1f}% (threshold={threshold})")
            return degree_int if threshold == -1 else found

        except Exception as e:
            if debug:
                self.log(f"  [label] {label_name} -> 错误: {e}")
            return 0 if threshold == -1 else False

    def vlm_available(self) -> bool:
        """VLM/OCR 是否可用"""
        return self.ocr_func is not None

    def ocr(self, screen_type: str, save_path: Optional[str] = None, **kwargs) -> Optional[Dict[str, object]]:
        """通用 OCR 入口：根据 screen_type 执行对应 ScreenOCRTask。**kwargs 传递到各 func。"""
        if self.ocr_func:
            return self.ocr_func(screen_type, save_path, **kwargs)
        return None

    def identify_pokemon(self, candidates=None, threshold=0.0):
        if self.identify_pokemon_func:
            return self.identify_pokemon_func(candidates=candidates, threshold=threshold)
        return None, 0.0, False

    def ocr_name(self, candidates=None):
        if self.ocr_name_func:
            return self.ocr_name_func(candidates=candidates)
        return None

    def screen_record_start(self):
        """开始录制GUI显示的游戏画面"""
        if self.recording_flag:
            return
        self.recording_flag = True
        self.record_frames = []
        self.record_thread = threading.Thread(target=self.record_worker, daemon=True)
        self.record_thread.start()

    def record_worker(self):
        """录制线程：按配置的 fps 录制，用绝对时间戳避免累积误差"""
        from .config import get
        record_cfg = get("record", {})
        fps = record_cfg.get("fps", 30)
        max_frames = record_cfg.get("max_frames", 0)
        interval = 1.0 / fps
        start_time = time.time()
        frame_count = 0

        while self.recording_flag:
            target_time = start_time + frame_count * interval
            delay = target_time - time.time()
            if delay > 0:
                time.sleep(delay)

            frame = self.get_frame()
            if frame is not None:
                self.record_frames.append(frame.copy())
                if max_frames > 0:
                    self.record_frames = self.record_frames[-max_frames:]

            frame_count += 1

    def screen_record_save(self, save_path: str = None):
        """结束录制，保存录制的视频，默认保存至 screen_record/{timestamp}.mp4"""
        self.recording_flag = False
        if self.record_thread:
            self.record_thread.join(timeout=2.0)
            self.record_thread = None
        if not self.record_frames:
            self.log("没有录制帧可保存")
            return

        if save_path is None:
            ts = time.strftime("%Y%m%d_%H%M%S")
            save_path = f"screen_record/{ts}.mp4"

        save_dir = os.path.dirname(save_path)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)

        from .config import get
        record_cfg = get("record", {})
        out_w = record_cfg.get("width", 640)
        out_h = record_cfg.get("height", 360)
        fps = record_cfg.get("fps", 30)

        fourcc = cv2.VideoWriter_fourcc(*'avc1')
        out = cv2.VideoWriter(save_path, fourcc, fps, (out_w, out_h))

        for frame in self.record_frames:
            if (frame.shape[1], frame.shape[0]) != (out_w, out_h):
                frame = cv2.resize(frame, (out_w, out_h))
            out.write(frame)
        out.release()

        self.log(f"视频已保存: {save_path} ({len(self.record_frames)} 帧)")
        self.record_frames.clear()
