"""
Video Module - 游戏画面显示模块
负责实时显示游戏画面和键盘控制
"""

import os
import time
import pygame
import cv2
import numpy as np
import threading
from typing import Optional, Tuple, Dict
from easycon import EasyConController, GamePadKey
from easycon.config import get


class VideoModule:
    """游戏画面显示模块"""
    
    # 默认按键映射（类级别，可通过 key_map 实例属性覆盖）
    DEFAULT_KEY_MAP = {
        pygame.K_y: GamePadKey.A, pygame.K_u: GamePadKey.B,
        pygame.K_i: GamePadKey.X, pygame.K_h: GamePadKey.Y,
        pygame.K_g: GamePadKey.L, pygame.K_t: GamePadKey.R,
        pygame.K_f: GamePadKey.ZL, pygame.K_r: GamePadKey.ZR,
        pygame.K_k: GamePadKey.PLUS, pygame.K_j: GamePadKey.MINUS,
        pygame.K_z: GamePadKey.CAPTURE, pygame.K_c: GamePadKey.HOME,
        pygame.K_q: GamePadKey.LCLICK, pygame.K_e: GamePadKey.RCLICK,
        pygame.K_w: GamePadKey.TOP, pygame.K_s: GamePadKey.DOWN,
        pygame.K_a: GamePadKey.LEFT, pygame.K_d: GamePadKey.RIGHT,
    }
    
    def __init__(self, x: int, y: int, width: int = 640, height: int = 360):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        
        # 实例级按键映射（默认使用类级别的 DEFAULT_KEY_MAP）
        self.key_map: Dict[int, GamePadKey] = dict(VideoModule.DEFAULT_KEY_MAP)
        self.cap: Optional[cv2.VideoCapture] = None
        self.current_frame: Optional[pygame.Surface] = None
        self.raw_frame: Optional = None  # 原始 numpy 帧（供 OCR 等使用）
        self.last_frame_time = 0.0  # 上次更新 raw_frame 的时间戳
        self.frame_lock = threading.Lock()
        self.flip_vertical = get("capture.flip_vertical", False)
        self.flip_horizontal = get("capture.flip_horizontal", False)
        
        # 控制器
        self.controller: Optional[EasyConController] = None
        self.controller_connected = False
        self.controller_status = "未连接"
        self.last_reconnect_time = 0
        
        # 状态
        self.pressed_keys: set = set()
        self.focused = False  # 初始未聚焦，由GUI统一设置以正确控制SDL文本输入
        self.last_unmapped_key = None  # 最后按下的未映射按键
        self.unmapped_key_timer = 0  # 未映射按键提示计时器
        
        # FPS计算
        self.fps = 0
        self.frame_count = 0
        self.fps_timer = pygame.time.get_ticks()
        
        # VL模型类型显示
        self.model_type = "未知"
        
        # 初始化
        self.init_video()
    
    def init_video(self):
        """初始化视频捕获"""
        device_id = get("capture.device_id", 0)
        def init_worker():
            try:
                self.cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW)
                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(device_id)
                if self.cap.isOpened():
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception as e:
                print(f"视频初始化错误: {e}")
                self.cap = None
        
        threading.Thread(target=init_worker, daemon=True).start()
    
    def set_controller(self, controller: EasyConController):
        """设置控制器"""
        self.controller = controller
        self.update_connection_status()
    
    def update_connection_status(self):
        """更新连接状态"""
        if self.controller and self.controller.is_connected:
            self.controller_connected = True
            self.controller_status = "已连接"
        else:
            self.controller_connected = False
            self.controller_status = "未连接"
    
    def check_and_reconnect(self):
        """检查连接状态并尝试重连"""
        current_time = pygame.time.get_ticks()
        
        # 每3秒检查一次连接状态
        if current_time - self.last_reconnect_time < 3000:
            return
        
        self.last_reconnect_time = current_time
        
        # 检查当前连接状态
        self.update_connection_status()
        if self.controller_connected:
            return
        
        # 尝试重连
        self.controller_status = "连接中..."
        
        def reconnect_worker():
            try:
                if self.controller is None:
                    self.controller = EasyConController()
                
                # 直接调用 connect() 自动搜索，内置 USB/蓝牙端口分离优化
                if self.controller.connect(timeout=2.0):
                    self.update_connection_status()
                    return
                
                self.update_connection_status()
            except Exception as e:
                self.update_connection_status()
        
        threading.Thread(target=reconnect_worker, daemon=True).start()
    
    def update(self, render: bool = True):
        """更新视频帧。render=False 时仅更新 raw_frame（供脚本 OCR 使用），不刷新 pygame Surface。"""
        if self.cap and self.cap.isOpened():
            try:
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    now = time.time()
                    with self.frame_lock:
                        self.raw_frame = frame
                        self.last_frame_time = now

                    if render:
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        if self.flip_vertical:
                            frame_rgb = cv2.flip(frame_rgb, 0)
                        if self.flip_horizontal:
                            frame_rgb = cv2.flip(frame_rgb, 1)
                        frame_resized = cv2.resize(frame_rgb, (self.width, self.height))
                        # 复用 Surface 避免 frombuffer 频繁创建导致内存碎片
                        if self.current_frame is None:
                            self.current_frame = pygame.Surface(
                                (self.width, self.height), 0, 24)
                        pygame.surfarray.blit_array(
                            self.current_frame,
                            np.transpose(frame_resized, (1, 0, 2)))

                        # 计算FPS
                        self.frame_count += 1
                        current_time = pygame.time.get_ticks()
                        if current_time - self.fps_timer >= 1000:
                            self.fps = self.frame_count
                            self.frame_count = 0
                            self.fps_timer = current_time

                            # 更新模型类型显示
                            try:
                                from vision.vlm import get_current_model_type, OLLAMA_MODEL_NAME, SILICONFLOW_MODEL
                                model_type = get_current_model_type()
                                if model_type == "vllm":
                                    self.model_type = "vLLM(本地)"
                                elif model_type == "ollama":
                                    self.model_type = f"{OLLAMA_MODEL_NAME}(Ollama)"
                                elif model_type == "siliconflow":
                                    self.model_type = f"{SILICONFLOW_MODEL.split('/')[-1]}(SiliconFlow)"
                                else:
                                    self.model_type = "未知"
                            except Exception:
                                pass
            except Exception as e:
                pass

    def get_raw_frame(self):
        """获取原始采集卡帧（线程安全，供 OCR 使用）"""
        with self.frame_lock:
            if self.raw_frame is not None:
                return self.raw_frame.copy()
        return None

    def get_raw_frame_age(self) -> float:
        """获取 raw_frame 的年龄（秒）。-1 表示无帧。"""
        with self.frame_lock:
            if self.raw_frame is not None:
                return time.time() - self.last_frame_time
        return -1.0

    def get_raw_frame_snapshot(self):
        """Return one frame copy and its stable update timestamp."""
        with self.frame_lock:
            if self.raw_frame is not None:
                return self.raw_frame.copy(), self.last_frame_time
        return None, -1.0
    
    def set_focused(self, focused: bool):
        """设置焦点状态，同时控制SDL文本输入以兼容中文输入法"""
        if focused == self.focused:
            return
        self.focused = focused
        try:
            if focused:
                # 聚焦时停止SDL文本输入，使KEYDOWN事件正常触发（兼容中文输入法）
                pygame.key.stop_text_input()
            else:
                # 失焦时恢复文本输入
                pygame.key.start_text_input()
                pygame.key.set_text_input_rect(
                    pygame.Rect(0, 0, pygame.display.get_surface().get_width(),
                               pygame.display.get_surface().get_height()))
        except Exception:
            pass

    def handle_event(self, event: pygame.event.Event) -> bool:
        """
        处理事件
        Returns: 是否处理了该事件
        """
        # 鼠标点击视频区域获得焦点
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                mx, my = event.pos
                if self.x <= mx <= self.x + self.width and self.y <= my <= self.y + self.height:
                    self.set_focused(True)
                    return True
                else:
                    self.set_focused(False)
        
        # 只有获得焦点时才处理键盘事件
        if self.focused:
            if event.type == pygame.KEYDOWN:
                if event.key in self.key_map:
                    key = self.key_map[event.key]
                    self.pressed_keys.add(key)
                    
                    # 检查控制器连接状态
                    if self.controller and self.controller.is_connected:
                        try:
                            self.controller.press(key)
                        except:
                            self.controller_connected = False
                            self.controller_status = "未连接"
                    else:
                        # 未连接时尝试重连
                        self.check_and_reconnect()
                else:
                    # 未映射的按键：记录并显示提示
                    self.last_unmapped_key = pygame.key.name(event.key)
                    self.unmapped_key_timer = pygame.time.get_ticks()
                
                return True
            
            elif event.type == pygame.KEYUP:
                if event.key in self.key_map:
                    key = self.key_map[event.key]
                    self.pressed_keys.discard(key)
                    if self.controller and self.controller.is_connected:
                        try:
                            self.controller.release(key)
                        except:
                            pass
                return True
        
        return False
    
    def draw(self, screen: pygame.Surface, font: pygame.font.Font):
        """绘制视频区域"""
        # 背景
        pygame.draw.rect(screen, (25, 25, 30), (self.x, self.y, self.width, self.height))
        
        # 视频帧
        if self.current_frame:
            screen.blit(self.current_frame, (self.x, self.y))
        else:
            # 等待画面
            text = font.render("等待视频...", True, (150, 150, 150))
            rect = text.get_rect(center=(self.x + self.width // 2, self.y + self.height // 2))
            screen.blit(text, rect)
        
        # 未聚焦时绘制水印提示
        if not self.focused:
            # 使用半透明黑色底色让水印更清晰
            watermark_bg = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            watermark_bg.fill((0, 0, 0, 80))
            screen.blit(watermark_bg, (self.x, self.y))
            # 渲染水印文字（两行）
            wm_font = pygame.font.Font(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "assets", "NotoSansCJKsc-Regular.otf"
            ), 20) if os.path.exists(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "assets", "NotoSansCJKsc-Regular.otf"
            )) else pygame.font.SysFont(None, 20)
            line1 = wm_font.render("点击游戏画面", True, (255, 255, 255))
            line2 = wm_font.render("启用按键映射", True, (255, 255, 255))
            cx = self.x + self.width // 2
            cy = self.y + self.height // 2
            screen.blit(line1, line1.get_rect(center=(cx, cy - 15)))
            screen.blit(line2, line2.get_rect(center=(cx, cy + 15)))

        # 默认边框（与标签制作、运行输出等模块风格一致，始终显示）
        pygame.draw.rect(screen, (100, 100, 100), (self.x, self.y, self.width, self.height), 2)

        # 未映射按键提示（始终显示，触发了就可见2秒）
        if self.last_unmapped_key and pygame.time.get_ticks() - self.unmapped_key_timer < 2000:
            unmapped_text = font.render(f"未定义按键: [{self.last_unmapped_key}]", True, (255, 180, 50))
            unmapped_rect = unmapped_text.get_rect()
            unmapped_rect.bottomright = (self.x + self.width - 10, self.y + self.height - 10)
            screen.blit(unmapped_text, unmapped_rect)
    
    def get_rect(self) -> pygame.Rect:
        """获取区域矩形"""
        return pygame.Rect(self.x, self.y, self.width, self.height)
    
    def release(self):
        """释放资源"""
        if self.cap:
            try:
                self.cap.release()
            except:
                pass
            self.cap = None
        self.current_frame = None
        self.raw_frame = None
