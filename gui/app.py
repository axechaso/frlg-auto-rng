"""
EasyCon GUI - 模块化版本
布局：
- 左上：游戏画面（VideoModule）
- 右上：标签制作（LabelMaker）
- 按钮行：Run / Stop / Record / Save Video
- 左下：运行输出（OutputPanel）
- 右下：按键映射（KeyMappingPanel）
"""

import gc
import inspect
import os
import time
os.environ['SDL_VIDEO_CENTERED'] = '1'

import pygame
import cv2
import json
import numpy as np
import threading
from typing import Optional, Tuple

from modules.video_module import VideoModule
from modules.label_maker import LabelMaker
from modules.output_panel import OutputPanel
from modules.key_mapping import KeyMappingPanel

current_gui = None

from easycon import EasyConController, GamePadKey, ScriptContext
from easycon.config import get, set as config_set
from easycon.label_matcher import match_prepared_label, matches_threshold, prepare_label

from .script_engine import ScriptEngine

from vision import (
    ocr_skills as ocr_skills,
    check_service as check_service,
    check_vllm_service as check_vllm_service,
    check_ollama_service as check_ollama_service,
    check_siliconflow_service as check_siliconflow_service,
    set_model_type as set_model_type,
    get_current_model_type as get_current_model_type,
    get_available_model_types as get_available_model_types,
    get_vllm_model as get_vllm_model,
    identify_pokemon as identify_pokemon_vision,
    preload_sprites as preload_sprites,
    MODEL_TYPE_VLLM,
    MODEL_TYPE_OLLAMA,
    MODEL_TYPE_SILICONFLOW,
    OLLAMA_MODEL_NAME,
    SILICONFLOW_MODEL,
    VLLM_MODEL_NAME,
)


class EasyConGUI:
    """EasyCon 主GUI类 - 整合所有模块"""
    
    def __init__(self, script_path=None, controller=None):
        # 初始化pygame
        pygame.init()
        pygame.display.init()
        pygame.key.set_repeat(300, 50)
        
        # 窗口设置
        self.window_width = 1030
        self.window_height = 790
        self.screen = pygame.display.set_mode(
            (self.window_width, self.window_height),
            pygame.DOUBLEBUF
        )
        pygame.display.set_caption("PyEasyCon")

        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sprites", "shiny", "137.png")
        if os.path.exists(icon_path):
            icon_surf = pygame.image.load(icon_path).convert_alpha()
            min_x, min_y = icon_surf.get_width(), icon_surf.get_height()
            max_x, max_y = 0, 0
            w, h = icon_surf.get_size()
            pad = 4
            for y in range(0, h, pad):
                for x in range(0, w, pad):
                    if icon_surf.get_at((x, y)).a > 0:
                        min_x, min_y = min(min_x, x), min(min_y, y)
                        max_x, max_y = max(max_x, x), max(max_y, y)
            min_x = max(0, min_x - pad)
            min_y = max(0, min_y - pad)
            max_x = min(w-1, max_x + pad)
            max_y = min(h-1, max_y + pad)
            crop_w = max_x - min_x + 1
            crop_h = max_y - min_y + 1
            cropped = icon_surf.subsurface((min_x, min_y, crop_w, crop_h))
            icon_final = pygame.transform.smoothscale(cropped, (64, 64))
            pygame.display.set_icon(icon_final)

        # 字体（等宽字体，用于输出面板和按键映射对齐显示）
        font_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
        mono_path = os.path.join(font_dir, "NotoSansMonoCJKsc-Regular.otf")
        sans_path = os.path.join(font_dir, "NotoSansCJKsc-Regular.otf")
        self.font_mono = pygame.font.Font(mono_path, 15) if os.path.exists(mono_path) else pygame.font.Font(sans_path, 15)
        self.font_mono_small = pygame.font.Font(mono_path, 12) if os.path.exists(mono_path) else pygame.font.Font(sans_path, 12)
        # 标题用普通字体
        self.font = pygame.font.Font(sans_path, 14)
        self.font_small = pygame.font.Font(sans_path, 12)
        
        # 控制器
        self.controller: Optional[EasyConController] = None

        self.button_map = {
            'A': GamePadKey.A, 'B': GamePadKey.B, 'X': GamePadKey.X, 'Y': GamePadKey.Y,
            'L': GamePadKey.L, 'R': GamePadKey.R, 'ZL': GamePadKey.ZL, 'ZR': GamePadKey.ZR,
            'PLUS': GamePadKey.PLUS, 'MINUS': GamePadKey.MINUS,
            'HOME': GamePadKey.HOME, 'CAPTURE': GamePadKey.CAPTURE,
            'UP': GamePadKey.TOP, 'DOWN': GamePadKey.DOWN,
            'LEFT': GamePadKey.LEFT, 'RIGHT': GamePadKey.RIGHT,
        }
        
        # ============== 模块初始化 ==============
        
        # 左上：游戏画面
        self.video_module = VideoModule(10, 10, 640, 360)
        
        # 右上：标签制作
        self.label_maker = LabelMaker(660, 10, 360, 360)
        self.label_maker.capture_callback = self.capture_for_label
        
        # 左下：运行输出
        self.output_panel = OutputPanel(10, 382, 640, 398)
        
        # 右下：按键映射
        self.key_mapping = KeyMappingPanel(660, 382, 360, 398)
        # 同步按键映射到 VideoModule
        self.sync_keymap_to_video()
        
        # 初始时视频模块聚焦，停止SDL文本输入以兼容中文输入法
        self.video_module.set_focused(True)

        self.script_code = ""
        self.label_debug_saved = set()
        
        # 运行状态
        self.running = False
        self.clock = pygame.time.Clock()
        self.focused_module = 'video'
        self.module_clicked = True  # 是否点击过子模块（用于控制边框显示），默认已点击游戏画面
        
        # ============== 录像状态 ==============
        self.recording = False
        self.script_running = False

        # 缩放后帧缓存（避免 OCR 反复调用时重复 cv2.resize）
        self.cached_1080p_frame: Optional[np.ndarray] = None
        self.cached_1080p_token: float = -1.0

        # ============== 按钮（LabelMaker 风格：64x28, border_radius=3，放在输出面板标题行右侧） ==============
        btn_w = 64
        btn_h = 28
        gap = 8
        # 输出面板标题栏：x=10, y=382, title_h=30
        btn_y = 388
        # LabelMaker 风格：等间距右对齐（switch 在最右，其余左移一个按钮宽度+间距）
        btn_right = 10 + 640 - 10  # 输出面板右边界
        positions = [btn_right - (btn_w + gap) * (i + 1) + gap for i in range(5)]
        self.btn_rects = {
            'switch': pygame.Rect(positions[0], btn_y, btn_w, btn_h),
            'save':   pygame.Rect(positions[1], btn_y, btn_w, btn_h),
            'record': pygame.Rect(positions[2], btn_y, btn_w, btn_h),
            'stop':   pygame.Rect(positions[3], btn_y, btn_w, btn_h),
            'run':    pygame.Rect(positions[4], btn_y, btn_w, btn_h),
        }
        self.btn_pressed = None
        self.btn_pressed_frames = 0

        # ============== 视频源切换状态 ==============
        self.current_device_id = get("capture.device_id", 0)
        self.manual_device_switch = False  # 用户手动切换后置 True，run 后持久化
        self.switching_device = False
        
        # 脚本引擎
        self.script_engine = ScriptEngine(log_func=self.output_panel.log)
        self.script_engine.set_code_getter(lambda: self.script_code)
        self.script_engine.set_on_running_change(self.on_script_running_change)

        if script_path and os.path.exists(script_path):
            with open(script_path, 'r', encoding='utf-8') as f:
                self.script_code = f.read()

        # 如果注入了已有 controller，直接使用，避免重复连接
        if controller is not None:
            self.controller = controller
            self.video_module.set_controller(self.controller)
            self.output_panel.log(f"已复用外部控制器: {controller.port_name}")
        else:
            self.controller = None

        # 初始化控制器和视频（在模块创建之后）
        # 如果已有 controller（外部注入），跳过自动连接
        if self.controller is None:
            self.init_controller()
        self.init_vllm_status()
        
        # 创建脚本执行上下文
        self.ctx = ScriptContext(
            controller=self.controller,
            get_frame=self.get_video_frame,
            log_func=self.log,
            is_running_func=self.script_engine.is_running,
            ocr_func=self.ocr,
            identify_pokemon_func=self.identify_pokemon,
            ocr_name_func=self.ocr_name,
        )
        
        # 注册为全局 GUI 实例，使模块级 API 函数可用
        global current_gui
        current_gui = self
    
    def sync_keymap_to_video(self):
        """将按键映射面板的当前映射同步到 VideoModule"""
        km = self.key_mapping.get_pygame_keymap()
        self.video_module.key_map = km

    # ============== 录像 ==============
    
    def start_recording(self):
        """开始录制视频"""
        if self.recording:
            self.output_panel.log("已在录制中")
            return

        frame = self.video_module.get_raw_frame()
        if frame is None:
            self.output_panel.log("无法开始录制：采集卡未就绪")
            return

        record_cfg = get("record", {})
        out_w = record_cfg.get("width", 640)
        out_h = record_cfg.get("height", 360)
        self.record_fps = record_cfg.get("fps", 30)

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.record_path = os.path.join(os.getcwd(), f"easycon_record_{ts}.mp4")
        self.video_writer = cv2.VideoWriter(self.record_path, fourcc, self.record_fps, (out_w, out_h))
        if not self.video_writer.isOpened():
            self.output_panel.log("录制失败：无法创建视频文件")
            self.video_writer = None
            return

        self.recording = True
        self.record_frame_interval = 1.0 / self.record_fps
        self.record_out_size = (out_w, out_h)
        self.output_panel.log(f"开始录制: {self.record_path} ({out_w}x{out_h} @ {self.record_fps}fps)")

    def stop_and_save(self):
        """停止录制并保存视频"""
        if not self.recording:
            self.output_panel.log("未在录制中")
            return

        self.recording = False
        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None
        self.output_panel.log(f"视频已保存: {self.record_path}")
    
    def init_controller(self):
        """初始化控制器（后台线程）"""
        def controller_worker():
            try:
                self.output_panel.log("正在搜索EasyCon控制器...")
                
                self.controller = EasyConController()
                self.video_module.set_controller(self.controller)
                if hasattr(self, 'ctx') and self.ctx is not None:
                    self.ctx.controller_ref = self.controller
                
                # 直接调用 connect() 自动搜索，内置 USB/蓝牙端口分离优化
                if self.controller.connect(timeout=2.0):
                    self.output_panel.log(f"控制器已连接: {self.controller.port_name}")
                    self.video_module.update_connection_status()
                    return
                
                self.output_panel.log("未找到EasyCon控制器，按键时将自动重连")
            except Exception as e:
                self.output_panel.log(f"控制器错误: {e}")
        
        threading.Thread(target=controller_worker, daemon=True).start()
    
    def init_vllm_status(self):
        """检查 VL 模型服务状态"""
        def check_worker():
            vllm_ok = check_vllm_service()
            ollama_ok = check_ollama_service()
            siliconflow_ok = check_siliconflow_service()

            vllm_short = VLLM_MODEL_NAME.replace('\\', '/').split('/')[-1]
            ollama_short = OLLAMA_MODEL_NAME
            siliconflow_short = SILICONFLOW_MODEL

            if vllm_ok:
                self.output_panel.log(f"vLLM ({vllm_short}) 可用")
            else:
                self.output_panel.log(f"vLLM (无) 不可用")

            if ollama_ok:
                self.output_panel.log(f"Ollama ({ollama_short}) 可用")
            else:
                self.output_panel.log(f"Ollama (无) 不可用")

            if siliconflow_ok:
                self.output_panel.log(f"SiliconFlow ({siliconflow_short}) 可用")
            else:
                self.output_panel.log(f"SiliconFlow (无) 不可用")

            available = get_available_model_types()
            if MODEL_TYPE_VLLM in available:
                set_model_type(MODEL_TYPE_VLLM)
                self.output_panel.log(f"VL模型: vLLM ({vllm_short})")
            elif MODEL_TYPE_OLLAMA in available:
                set_model_type(MODEL_TYPE_OLLAMA)
                self.output_panel.log(f"VL模型: {ollama_short} (Ollama)")
            elif MODEL_TYPE_SILICONFLOW in available:
                set_model_type(MODEL_TYPE_SILICONFLOW)
                self.output_panel.log(f"VL模型: {siliconflow_short} (SiliconFlow)")
            else:
                self.output_panel.log("VL模型: 无可用")

        threading.Thread(target=check_worker, daemon=True).start()
    
    # ============== 脚本执行 ==============
    
    def on_script_running_change(self, is_running: bool):
        self.script_running = is_running
    
    def run_script(self):
        if self.ctx.controller_ref is None and self.controller is not None:
            self.ctx.controller_ref = self.controller
        frame = self.video_module.get_raw_frame()
        if frame is not None:
            cap_w = get("capture", {}).get("width", 1920)
            cap_h = get("capture", {}).get("height", 1080)
            self.output_panel.log(f"采集卡原始分辨率: {frame.shape[1]}x{frame.shape[0]}")
            if (frame.shape[1], frame.shape[0]) != (cap_w, cap_h):
                self.ctx.log(f"自动缩放画面至: {cap_w}x{cap_h}")
                self.ctx.log(f"若脚本出错请检查标签匹配度")
        # 用户手动切换过视频源 -> 持久化到 custom.yaml（custom 优先级高于 default）
        if self.manual_device_switch:
            try:
                config_set("capture.device_id", self.current_device_id)
                self.output_panel.log(f"已保存视频设备 #{self.current_device_id} 到 custom.yaml")
                self.manual_device_switch = False
            except Exception as e:
                self.output_panel.log(f"保存视频设备配置失败: {e}")
        self.script_engine.run(self.ctx)

    def stop_script(self):
        self.script_engine.stop()

    # ============== 视频源切换 ==============

    def switch_video_source(self):
        """切换到下一个可用的视频设备（采集卡/摄像头）。
        同步执行：DSHOW 后端对 COM 线程模型敏感，跨线程操作 cap 会导致主线程
        画面卡死，因此切换期间短暂阻塞主循环（可接受，切换是低频用户操作）。"""
        if self.switching_device:
            self.output_panel.log("正在切换视频源，请稍候")
            return
        self.switching_device = True

        # 抑制 OpenCV DSHOW 枚举时的警告
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except Exception:
            pass

        try:
            current_id = self.current_device_id

            # 先释放当前 cap：DSHOW 不允许同一设备被同时打开两次，
            # 不释放的话当前设备枚举不到，candidates 会少一个
            old_cap = self.video_module.cap
            if old_cap is not None:
                try:
                    if old_cap.isOpened():
                        old_cap.release()
                except Exception:
                    pass
                self.video_module.cap = None
                self.cached_1080p_frame = None

            # 枚举 0-7 号设备（DSHOW 优先，失败回退默认 API）
            candidates = []
            for idx in range(8):
                try:
                    c = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                    if not c.isOpened():
                        c = cv2.VideoCapture(idx)
                    if c.isOpened():
                        ret, frame = c.read()
                        c.release()
                        if ret and frame is not None:
                            candidates.append(idx)
                except Exception:
                    pass

            if not candidates:
                self.output_panel.log("未找到任何可用视频设备，恢复原设备")
                self.apply_video_device(current_id)
                return

            # 只有当前设备 -> 不切换
            other = [d for d in candidates if d != current_id]
            if not other:
                self.output_panel.log(
                    f"仅有当前设备 #{current_id}，无其它设备可切换（可用: {candidates}）")
                self.apply_video_device(current_id)
                return

            # 切到下一个（按列表顺序循环）
            try:
                pos = candidates.index(current_id)
            except ValueError:
                pos = -1
            next_id = candidates[(pos + 1) % len(candidates)]

            self.apply_video_device(next_id)
            self.manual_device_switch = True
            self.current_device_id = next_id
            self.output_panel.log(
                f"已切换到视频设备 #{next_id}（可用: {candidates}）"
                + "，Run 后将保存到 custom.yaml")
        except Exception as e:
            self.output_panel.log(f"切换视频源失败: {e}")
        finally:
            self.switching_device = False

    def apply_video_device(self, device_id: int):
        """实际切换 VideoModule 的采集设备。"""
        old_cap = self.video_module.cap
        if old_cap is not None:
            try:
                if old_cap.isOpened():
                    old_cap.release()
            except Exception:
                pass
            self.video_module.cap = None

        new_cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW)
        if not new_cap.isOpened():
            new_cap = cv2.VideoCapture(device_id)
        if new_cap.isOpened():
            new_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.video_module.cap = new_cap
        self.cached_1080p_frame = None
    
    # ============== 脚本API ==============
    
    def press(self, button: str, duration_ms: int = 50):
        """按下按钮"""
        if self.controller and self.controller.is_connected:
            try:
                key = self.button_map.get(button.upper())
                if key:
                    self.controller.click(key, duration_ms)
            except Exception as e:
                self.output_panel.log(f"按键失败: {e}")

    def hold(self, button: str):
        """按住按钮（不释放）"""
        if self.controller and self.controller.is_connected:
            key = self.button_map.get(button.upper())
            if key:
                self.controller.press(key)

    def release(self, button: str):
        """释放按钮"""
        if self.controller and self.controller.is_connected:
            key = self.button_map.get(button.upper())
            if key:
                self.controller.release(key)

    def lstick(self, x: int, y: int, duration_ms: int = 50):
        """左摇杆"""
        if self.controller and self.controller.is_connected:
            self.controller.lstick(x, y, duration_ms)

    def capture(self):
        """截图"""
        if self.controller and self.controller.is_connected:
            self.controller.capture()
    
    def wait(self, ms: int):
        deadline = time.time() + ms / 1000.0
        while time.time() < deadline:
            if not self.script_engine.is_running():
                raise SystemExit("脚本已停止")
            time.sleep(0.05)

    def log(self, msg: str):
        """输出日志"""
        self.output_panel.log(msg)
    
    def search_label(self, label_name: str, threshold: int = 80, debug: bool = False):
        """搜索标签。threshold=-1 返回匹配度(int)，否则返回是否找到(bool)。"""
        try:
            import os
            label_path = os.path.join("assets", "labels", f"{label_name}.IL")
            if not os.path.exists(label_path):
                if debug: self.output_panel.log(f"  [label] {label_name} -> 文件不存在")
                return 0 if threshold == -1 else False

            with open(label_path, 'r', encoding='utf-8') as f:
                label_data = json.load(f)

            # 优先复用 update() 缓存的原始帧，避免重复 IO
            frame = self.video_module.get_raw_frame()
            if frame is None:
                cap = self.video_module.cap
                if cap is None or not cap.isOpened():
                    return 0 if threshold == -1 else False
                ret, frame = cap.read()
                if not ret:
                    return 0 if threshold == -1 else False

            if not label_data.get('ImgBase64'):
                return 0 if threshold == -1 else False

            prepared = prepare_label(label_data)
            match = match_prepared_label(frame, prepared)
            template = prepared['template']
            roi = match.roi
            frame = match.normalized_frame
            match_degree = match.degree
            found = matches_threshold(match, threshold)
            degree_int = match.easycon_degree

            # 极低匹配度时才保存调试截图（纯 hash 文件名避免乱码）
            if debug and match_degree < 30 and label_name not in self.label_debug_saved:
                self.label_debug_saved.add(label_name)
                import os as _os, hashlib
                _os.makedirs("debug_label", exist_ok=True)
                ts = time.strftime("%Y%m%d_%H%M%S")
                h = hashlib.md5(label_name.encode()).hexdigest()[:8]
                roi_path = f"debug_label/{ts}_{h}_roi_{match_degree:.0f}pct.png"
                tpl_path = f"debug_label/{ts}_{h}_tpl.png"
                frm_path = f"debug_label/{ts}_{h}_frame.png"
                cv2.imencode('.png', roi)[1].tofile(roi_path)
                cv2.imencode('.png', template)[1].tofile(tpl_path)
                cv2.imencode('.png', frame)[1].tofile(frm_path)
                self.output_panel.log(f"  [debug] saved: {h} ({label_name})")

            if debug:
                marker = "*" if found else " "
                self.output_panel.log(f"  [{marker}] {label_name} = {match_degree:.1f}% (threshold={threshold})")
            return degree_int if threshold == -1 else found

        except Exception as e:
            if debug: self.output_panel.log(f"  [label] {label_name} -> 错误: {e}")
            return 0 if threshold == -1 else False
    
    def get_video_frame(self, fresh: bool = False):
        """获取采集卡帧，统一规范化为 1920×1080。
        
        缓存缩放后的帧：同一次 OCR 周期内反复调用不重复 resize。
        fresh=True 时强制重新读取。
        """
        raw_age = self.video_module.get_raw_frame_age()
        raw_token = self.video_module.last_frame_time

        # 缓存在有效期内直接复用
        if not fresh and 0 <= raw_age < 0.05:
            if self.cached_1080p_frame is not None and self.cached_1080p_token == raw_token:
                return self.cached_1080p_frame

        # 需要新建帧
        if not fresh and 0 <= raw_age < 0.05:
            frame, raw_token = self.video_module.get_raw_frame_snapshot()
        else:
            cap = self.video_module.cap
            if cap is None or not cap.isOpened():
                return None
            ret, frame = cap.read()
            if not ret or frame is None:
                return None
            raw_token = time.time()

        if frame.shape[1] != 1920 or frame.shape[0] != 1080:
            self.cached_1080p_frame = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_LINEAR)
        else:
            self.cached_1080p_frame = frame
        self.cached_1080p_token = raw_token
        return self.cached_1080p_frame
    
    def identify_pokemon(self, candidates=None, threshold=0.0):
        """识别画面中的宝可梦。返回 (species_id, score, is_shiny)。"""
        frame = self.get_video_frame()
        if frame is None:
            self.output_panel.log("识别失败: 采集卡未就绪")
            return None, 0.0, False
        result = identify_pokemon_vision(
            frame, candidates=candidates, threshold=threshold
        )
        species_id, score, is_shiny = result[0], result[1], result[2]
        if species_id is not None:
            shiny_str = "异色" if is_shiny else "普通"
            self.output_panel.log(f"识别结果: #{species_id} ({shiny_str}), 分数={score:.3f}")
        return species_id, score, is_shiny
    
    def ocr_name(self, candidates=None):
        """OCR 识别画面中的宝可梦英文名。"""
        frame = self.get_video_frame()
        if frame is None:
            return None
        task = ocr_skills.get("POKEMON_NAME")
        if task is None:
            return None
        result = task.run(frame, candidates=candidates or [], debug=False)
        name = result.get('name')
        if name and name.upper() != 'NONE':
            self.output_panel.log(f"OCR 验证: {name}")
        return name if name and name.upper() != 'NONE' else None
    
    def ocr(self, screen_type: str, save_path: Optional[str] = None, **kwargs):
        """通用 OCR 入口：根据 screen_type 执行对应 ScreenOCRTask。**kwargs 传递到各 func。"""
        frame = self.get_video_frame()
        if frame is None:
            self.output_panel.log("OCR 失败: 采集卡未就绪")
            return None
        if screen_type not in ocr_skills:
            self.output_panel.log(f"OCR 失败: 未知类型 {screen_type}")
            return None
        task = ocr_skills[screen_type]
        result = task.run(frame, **kwargs)
        if save_path:
            task.save_annotated(frame, save_path)
        return result

    def log_ocr_result(self, result: dict):
        screen_type = result.get('screen', '')
        if screen_type:
            self.output_panel.log(f"Screen: {screen_type}")

        order = ['level', 'gender', 'nature', 'ability',
                 'hp', 'attack', 'defense', 'sp_atk', 'sp_def', 'speed']
        labels = {
            'level': '等级', 'gender': '性别', 'nature': '性格', 'ability': '特性',
            'hp': 'HP', 'attack': '攻击', 'defense': '防御',
            'sp_atk': '特攻', 'sp_def': '特防', 'speed': '速度',
        }
        iv_keys = ['hp', 'attack', 'defense', 'sp_atk', 'sp_def', 'speed']
        iv_parts = []
        for key in order:
            val = result.get(key)
            if val:
                if key in iv_keys:
                    iv_parts.append(f"{labels[key]}: {val}")
                else:
                    self.output_panel.log(f"  {labels[key]}: {val}")
        if iv_parts:
            self.output_panel.log(f"  个体值: {' | '.join(iv_parts)}")
    
    def toggle_model_type(self):
        """切换VL模型类型"""
        cur = get_current_model_type()
        available = get_available_model_types()

        if len(available) <= 1:
            self.output_panel.log("只有一个模型可用，无法切换")
            return

        current_index = available.index(cur) if cur in available else -1
        next_index = (current_index + 1) % len(available)
        next_model = available[next_index]

        set_model_type(next_model)
        vllm_short = VLLM_MODEL_NAME.replace('\\', '/').split('/')[-1]
        if next_model == MODEL_TYPE_VLLM:
            self.output_panel.log(f"VL模型: vLLM ({vllm_short})")
        elif next_model == MODEL_TYPE_OLLAMA:
            self.output_panel.log(f"VL模型: {OLLAMA_MODEL_NAME} (Ollama)")
        elif next_model == MODEL_TYPE_SILICONFLOW:
            self.output_panel.log(f"VL模型: {SILICONFLOW_MODEL} (SiliconFlow)")
    
    def capture_for_label(self):
        """为标签制作模块截图 - 使用规范化后的 1920×1080 帧，确保跨分辨率兼容"""
        frame = self.get_video_frame()
        if frame is not None:
            result = self.label_maker.capture_frame(frame)
            if result:
                self.output_panel.log("已截图到标签制作区")
            return
        self.output_panel.log("截图失败")
    
    # ============== 按钮绘制 ==============
    
    def draw_button(self, screen: pygame.Surface, font: pygame.font.Font, btn_name: str, text: str):
        """绘制按钮（LabelMaker 风格：64x28, border_radius=3, 1px border）。
        根据运行/录制状态自动配色；不适用的状态灰化但可点击。"""
        rect = self.btn_rects[btn_name]
        mx, my = pygame.mouse.get_pos()

        # 根据状态决定基础颜色
        if btn_name == 'run':
            if not self.video_module.controller_connected:
                color = (80, 80, 80)  # 控制器未连接，灰色不可用
            elif self.script_running:
                color = (80, 80, 80)
            else:
                color = (60, 120, 80)
        elif btn_name == 'stop':
            color = (120, 60, 60) if self.script_running else (80, 80, 80)
        elif btn_name == 'record':
            if self.recording:
                color = (200, 60, 60)
            else:
                color = (180, 120, 40)
        elif btn_name == 'save':
            color = (60, 80, 120) if self.recording else (80, 80, 80)
        elif btn_name == 'switch':
            color = (80, 110, 130)
        else:
            color = (60, 60, 60)

        # 悬停加亮
        c = tuple(min(255, v + 20) for v in color) if rect.collidepoint(mx, my) else color

        # 按压加亮更多
        if self.btn_pressed == btn_name and self.btn_pressed_frames > 0:
            c = tuple(min(255, v + 40) for v in c)

        pygame.draw.rect(screen, c, rect, border_radius=3)
        pygame.draw.rect(screen, (150, 150, 150), rect, 1, border_radius=3)

        # 录制中状态：Record 按钮文字闪烁
        if btn_name == 'record' and self.recording:
            text_to_show = "Stop" if int(time.time() * 2) % 2 == 0 else "Record"
        else:
            text_to_show = text

        text_surf = font.render(text_to_show, True, (220, 220, 220))
        text_rect = text_surf.get_rect(center=rect.center)
        screen.blit(text_surf, text_rect)

    # ============== 主循环 ==============
    
    def run(self):
        self.running = True
        frame_count = 0
        last_record_frame = 0
        last_gc = time.time()
        last_cap_restart = time.time()

        self.output_panel.log("EasyCon GUI 已启动")
        self.output_panel.log("F5运行 | F6停止 | F9切换模型 | ESC退出")

        while self.running:
            # 每 60 秒强制 GC，释放累积的临时 numpy 数组
            now = time.time()
            if now - last_gc > 60:
                gc.collect()
                last_gc = now

            # 每 10 分钟重启采集卡，防止 DShow 内部缓冲区缓慢泄漏
            if now - last_cap_restart > 600 and not self.script_running:
                self.apply_video_device(self.current_device_id)
                last_cap_restart = now
            # 始终采集 raw_frame 供脚本 OCR 使用；可见时才渲染 pygame Surface
            window_active = pygame.display.get_active()
            if frame_count % 2 == 0:
                self.video_module.update(render=window_active)

            events = pygame.event.get()
            mouse_x, mouse_y = pygame.mouse.get_pos()
            mouse_pressed = pygame.mouse.get_pressed()

            # ========= 全局键盘事件 =========
            for event in events:
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key == pygame.K_F5:
                        if not self.video_module.controller_connected:
                            self.output_panel.log("控制器未连接，无法运行")
                        else:
                            self.run_script()
                    elif event.key == pygame.K_F6:
                        self.stop_script()
                    elif event.key == pygame.K_F9:
                        self.toggle_model_type()

            # ========= 按钮和焦点切换 =========
            for event in events:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos
                    prev = self.focused_module

                    # 焦点区域
                    in_module = False
                    if 10 <= mx <= 650 and 10 <= my <= 370:
                        self.focused_module = 'video'
                        self.module_clicked = True
                        in_module = True
                    elif 660 <= mx <= 1020 and 10 <= my <= 370:
                        self.focused_module = 'label'
                        self.module_clicked = True
                        in_module = True
                    elif 10 <= mx <= 650 and 382 <= my <= 780:
                        self.focused_module = 'output'
                        self.module_clicked = True
                        in_module = True
                    elif 660 <= mx <= 1020 and 382 <= my <= 780:
                        self.focused_module = 'keymap'
                        self.module_clicked = True
                        in_module = True

                    if not in_module:
                        # 点击了非子模块区域，取消高亮
                        self.module_clicked = False
                        self.video_module.set_focused(False)

                    if self.focused_module != prev:
                        self.video_module.set_focused(self.focused_module == 'video')

                    # 按钮逻辑
                    for btn_name, btn_rect in self.btn_rects.items():
                        if btn_rect.collidepoint(mx, my):
                            self.btn_pressed = btn_name
                            self.btn_pressed_frames = 10
                            if btn_name == 'run':
                                if not self.video_module.controller_connected:
                                    self.output_panel.log("控制器未连接，无法运行")
                                else:
                                    self.run_script()
                            elif btn_name == 'stop':
                                self.stop_script()
                            elif btn_name == 'record':
                                if self.recording:
                                    self.stop_and_save()
                                else:
                                    self.start_recording()
                            elif btn_name == 'save':
                                if self.recording:
                                    self.stop_and_save()
                                else:
                                    self.output_panel.log("当前未在录制，无需保存")
                            elif btn_name == 'switch':
                                self.switch_video_source()

            # ========= LabelMaker 事件 =========
            for event in events:
                result = self.label_maker.handle_event(event)
                if result == 'capture':
                    self.capture_for_label()
                elif isinstance(result, str):
                    self.output_panel.log(result)

            # ========= VideoModule 事件 =========
            if self.focused_module == 'video':
                for event in events:
                    self.video_module.handle_event(event)

            # ========= KeyMapping 事件 =========
            for event in events:
                keymap_result = self.key_mapping.handle_event(event)
                if keymap_result:
                    if keymap_result.startswith("keymap:"):
                        msg = keymap_result[len("keymap:"):].strip()
                        if msg:
                            self.output_panel.log(f"[按键映射] {msg}")
                        # 同步到 VideoModule
                        self.sync_keymap_to_video()

            # ========= OutputPanel 滚动事件 =========
            for event in events:
                output_rect = self.output_panel.get_rect()
                if output_rect.collidepoint(pygame.mouse.get_pos()):
                    self.output_panel.handle_event(event)

            # ========= 录像写入 =========
            if self.recording and self.video_writer and self.video_writer.isOpened():
                raw = self.video_module.get_raw_frame()
                if raw is not None:
                    now_ts = time.time()
                    if now_ts - last_record_frame >= self.record_frame_interval:
                            out_size = getattr(self, 'record_out_size', None)
                            if out_size and (raw.shape[1], raw.shape[0]) != out_size:
                                raw = cv2.resize(raw, out_size)
                            self.video_writer.write(raw)
                            last_record_frame = now_ts

            # ========= 按钮按压状态递减 =========
            if self.btn_pressed_frames > 0:
                self.btn_pressed_frames -= 1
                if self.btn_pressed_frames <= 0:
                    self.btn_pressed = None

            # ========= 绘制 =========
            self.screen.fill((35, 35, 40))

            # 视频模块
            self.video_module.draw(self.screen, self.font)

            # 标签制作
            self.label_maker.draw(self.screen, self.font, self.font_small)

            # 输出面板
            self.output_panel.draw(self.screen, self.font, self.font_mono_small)

            # 按键映射面板
            self.key_mapping.draw(self.screen, self.font, self.font_mono_small)

            # 五个按钮（LabelMaker 风格，覆盖在输出面板标题行右侧）
            self.draw_button(self.screen, self.font_mono_small, 'run',    "Run")
            self.draw_button(self.screen, self.font_mono_small, 'stop',   "Stop")
            self.draw_button(self.screen, self.font_mono_small, 'record', "Record")
            self.draw_button(self.screen, self.font_mono_small, 'save',   "Save")
            self.draw_button(self.screen, self.font_mono_small, 'switch', "Switch")

            # 焦点边框：仅当用户点击过子模块后才显示，绿色，线宽8
            if self.module_clicked:
                focus_color = (0, 200, 0)
                focus_rects = {
                    'video':  (10, 10, 640, 360),
                    'label':  (660, 10, 360, 360),
                    'output': (10, 382, 640, 398),
                    'keymap': (660, 382, 360, 398),
                }
                if self.focused_module in focus_rects:
                    pygame.draw.rect(self.screen, focus_color,
                                   focus_rects[self.focused_module], 8)

            pygame.display.flip()
            frame_count += 1
            self.clock.tick(60)

        # 停止录制（如果还在录制中）
        if self.recording:
            self.stop_and_save()
        self.cleanup()
    
    def cleanup(self):
        """清理资源"""
        self.script_running = False
        self.cached_1080p_frame = None
        
        if self.controller:
            try:
                self.controller.release_all()
                self.controller.disconnect()
            except:
                pass
        
        self.video_module.release()
        gc.collect()
        
        pygame.quit()


# ============== 模块级 API 函数（供脚本 from gui import ...） ==============

def press(button: str, duration_ms: int = 50):
    if current_gui:
        current_gui.press(button, duration_ms)

def hold(button: str):
    if current_gui:
        current_gui.hold(button)

def release(button: str):
    if current_gui:
        current_gui.release(button)

def lstick(x: int, y: int, duration_ms: int = 50):
    if current_gui:
        current_gui.lstick(x, y, duration_ms)

def capture():
    if current_gui:
        current_gui.capture()

def wait(ms: int):
    if current_gui:
        current_gui.wait(ms)

def log(msg: str):
    if current_gui:
        current_gui.log(msg)

def search_label(label_name: str, threshold: int = 80, debug: bool = False):
    if current_gui:
        return current_gui.search_label(label_name, threshold, debug)
    return 0 if threshold == -1 else False

def get_frame():
    if current_gui:
        return current_gui.get_video_frame()
    return None

def is_running():
    if current_gui is None:
        return False
    return current_gui.script_engine.is_running()

def ocr(screen_type: str, save_path: Optional[str] = None):
    if current_gui:
        return current_gui.ocr(screen_type, save_path)
    return None

def identify_pokemon(candidates=None, threshold=0.0):
    if current_gui:
        return current_gui.identify_pokemon(candidates=candidates, threshold=threshold)
    return None, 0.0, False

def ocr_name_api(candidates=None):
    if current_gui:
        return current_gui.ocr_name(candidates=candidates)
    return None

def run_script(script_func, controller=None):
    """运行脚本。

    Args:
        script_func: 脚本主函数，签名为 func(ctx: ScriptContext)
        controller: 可选，外部已连接的 EasyConController 实例。
                   如果提供，将复用该连接，避免重复握手。
    """
    caller_path = inspect.stack()[1].filename
    script_path = caller_path if os.path.isfile(caller_path) and caller_path.endswith('.py') else None
    gui = EasyConGUI(script_path=script_path, controller=controller)
    gui.script_engine.set_script_func(script_func)
    if script_path:
        gui.output_panel.log(f"已加载: {os.path.basename(script_path)}")
    gui.output_panel.log("按 F5 运行 | F6 停止 | ESC 退出")
    gui.run()

def main():
    """启动 GUI 编辑器模式（python gui.py）"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_path = os.path.join(project_root, "demo_script.py")
    gui = EasyConGUI(script_path=script_path if os.path.exists(script_path) else None)
    gui.run()

if __name__ == "__main__":
    main()
