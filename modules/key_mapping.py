"""
Key Mapping Panel Module - 按键映射展示和设定面板
支持查看、修改、确认和重置键盘→控制器按键映射。
默认映射存 default.yaml，用户自定义存 custom.yaml（custom 优先）。
"""

import os
import pygame
from typing import Dict, Optional, Tuple

# 默认按键映射（GamePadKey 名称 → pygame key）
DEFAULT_KEY_MAPPING = {
    'A': 'y',       'B': 'u',
    'X': 'i',       'Y': 'h',
    'L': 'g',       'R': 't',
    'ZL': 'f',      'ZR': 'r',
    'PLUS': 'k',    'MINUS': 'j',
    'CAPTURE': 'z', 'HOME': 'c',
    'LCLICK': 'q',  'RCLICK': 'e',
    'UP': 'w',      'DOWN': 's',
    'LEFT': 'a',    'RIGHT': 'd',
}

# pygame key name → constant
PYGAME_KEY_MAP = {
    'a': pygame.K_a, 'b': pygame.K_b, 'c': pygame.K_c, 'd': pygame.K_d,
    'e': pygame.K_e, 'f': pygame.K_f, 'g': pygame.K_g, 'h': pygame.K_h,
    'i': pygame.K_i, 'j': pygame.K_j, 'k': pygame.K_k, 'l': pygame.K_l,
    'm': pygame.K_m, 'n': pygame.K_n, 'o': pygame.K_o, 'p': pygame.K_p,
    'q': pygame.K_q, 'r': pygame.K_r, 's': pygame.K_s, 't': pygame.K_t,
    'u': pygame.K_u, 'v': pygame.K_v, 'w': pygame.K_w, 'x': pygame.K_x,
    'y': pygame.K_y, 'z': pygame.K_z,
    '0': pygame.K_0, '1': pygame.K_1, '2': pygame.K_2, '3': pygame.K_3,
    '4': pygame.K_4, '5': pygame.K_5, '6': pygame.K_6, '7': pygame.K_7,
    '8': pygame.K_8, '9': pygame.K_9,
    'up': pygame.K_UP, 'down': pygame.K_DOWN, 'left': pygame.K_LEFT, 'right': pygame.K_RIGHT,
    'space': pygame.K_SPACE, 'return': pygame.K_RETURN, 'tab': pygame.K_TAB,
    'lshift': pygame.K_LSHIFT, 'rshift': pygame.K_RSHIFT,
    'lctrl': pygame.K_LCTRL, 'rctrl': pygame.K_RCTRL,
    'lalt': pygame.K_LALT, 'ralt': pygame.K_RALT,
}

PYGAME_KEY_REVERSE = {v: k for k, v in PYGAME_KEY_MAP.items()}


def load_mapping_from_yaml() -> Dict[str, str]:
    """从 config（default.yaml + custom.yaml 合并）加载按键映射。
    返回 gamepad -> key_name 字典。"""
    from easycon.config import get
    km = get("key_mapping", {})
    if not isinstance(km, dict):
        return {}
    # 过滤非法项，保证 gamepad/key_name 均为字符串
    return {str(k): str(v) for k, v in km.items() if isinstance(v, str)}


def save_custom_to_yaml(custom_mapping: Dict[str, str]) -> None:
    """将自定义映射写入 custom.yaml（gamepad -> key_name，仅存与默认不同的项）。"""
    from easycon.config import set as config_set
    config_set("key_mapping", dict(custom_mapping))


# ── 配色 ──────────────────────────────────────────────────────────────────

PANEL_BG       = (28, 28, 32)
TITLE_BG       = (36, 36, 40)
PANEL_BORDER   = (65, 65, 70)
TEXT_PRIMARY   = (210, 210, 215)
TEXT_DIM       = (110, 110, 115)
TEXT_ACCENT    = (255, 200, 100)

# 手柄按钮标签色
GP_TAG_COLORS = {
    'A': (200, 70, 70),  'B': (230, 190, 50),
    'X': (50, 130, 210),  'Y': (70, 190, 70),
    'L': (145, 145, 155), 'R': (145, 145, 155),
    'ZL': (130, 130, 145), 'ZR': (130, 130, 145),
    'PLUS': (155, 155, 165), 'MINUS': (155, 155, 165),
    'CAPTURE': (120, 115, 135), 'HOME': (120, 115, 135),
    'LCLICK': (155, 135, 170), 'RCLICK': (155, 135, 170),
    'UP': (180, 180, 185), 'DOWN': (180, 180, 185),
    'LEFT': (180, 180, 185), 'RIGHT': (180, 180, 185),
}

# 仅方向键用箭头符号
GAMEPAD_DISPLAY = {
    'UP': '↑', 'DOWN': '↓', 'LEFT': '←', 'RIGHT': '→',
}

# 按键映射项顺序（两列）
# 列1: ZL, L, UP, DOWN, LEFT, RIGHT, LCLICK, MINUS, CAPTURE
# 列2: ZR, R, X, B, Y, A, RCLICK, PLUS, HOME
GAMEPAD_ORDER = [
    'ZL', 'L', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'LCLICK', 'MINUS', 'CAPTURE',
    'ZR', 'R', 'X', 'B', 'Y', 'A', 'RCLICK', 'PLUS', 'HOME',
]

KEY_DISPLAY = {
    'UP': '↑', 'DOWN': '↓', 'LEFT': '←', 'RIGHT': '→',
    'SPACE': 'SPC', 'RETURN': 'ENT', 'TAB': 'TAB',
    'LSHIFT': 'LSFT', 'RSHIFT': 'RSFT',
    'LCTRL': 'LCTL', 'RCTRL': 'RCTL',
    'LALT': 'LALT', 'RALT': 'RALT',
}


# ── KeyMappingPanel ────────────────────────────────────────────────────────

class KeyMappingPanel:
    """按键映射展示和设定面板"""

    COLS    = 2
    PAD     = 8
    TITLE_H = 28
    ITEM_H  = 28
    GAP     = 8

    BTN_W = 64
    BTN_H = 28

    GP_TAG_W = 74
    GP_TAG_H = 22

    def __init__(self, x: int, y: int, width: int = 360, height: int = 398):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

        font_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assets", "NotoSansCJKsc-Regular.otf"
        )
        if not os.path.exists(font_path):
            font_path = None
        self.font        = pygame.font.Font(font_path, 14)
        self.font_small  = pygame.font.Font(font_path, 12)
        self.font_tag    = pygame.font.Font(font_path, 16)   # 手柄标签：加大字号替代加粗
        self.font_key    = pygame.font.Font(font_path, 16)   # 键盘按键：加大字号替代加粗
        self.font_arrow  = pygame.font.Font(font_path, 14)

        self.mapping: Dict[str, str] = {}
        self.load()
        self.items: list = []
        self.build_items()

        self.editing = False
        self.editing_item: Optional[int] = None
        self.editing_msg = ""

        # 按钮 —— 对齐 LabelMaker 的 X 坐标
        # LabelMaker: col1_x (capture/range/save) = 874, col2_x (clear/target/load) = 946
        # keymap: confirm=col1_x(874), reset=col2_x(946), modify=2*874-946=802
        btn_y = y + 2
        x_confirm = 874
        x_reset   = 946
        x_modify  = 2 * x_confirm - x_reset  # 802
        self.buttons = {
            'modify':  pygame.Rect(x_modify,  btn_y, self.BTN_W, self.BTN_H),
            'confirm': pygame.Rect(x_confirm, btn_y, self.BTN_W, self.BTN_H),
            'reset':   pygame.Rect(x_reset,   btn_y, self.BTN_W, self.BTN_H),
        }

    def load(self):
        self.mapping = load_mapping_from_yaml()
        self.build_items()

    def build_items(self):
        self.items = []
        for btn in GAMEPAD_ORDER:
            key_name = self.mapping.get(btn, '?')
            self.items.append((btn, key_name))

    def get_pygame_keymap(self) -> Dict[int, object]:
        from easycon import GamePadKey
        gamepad_enum = {
            'A': GamePadKey.A, 'B': GamePadKey.B, 'X': GamePadKey.X, 'Y': GamePadKey.Y,
            'L': GamePadKey.L, 'R': GamePadKey.R, 'ZL': GamePadKey.ZL, 'ZR': GamePadKey.ZR,
            'PLUS': GamePadKey.PLUS, 'MINUS': GamePadKey.MINUS,
            'CAPTURE': GamePadKey.CAPTURE, 'HOME': GamePadKey.HOME,
            'LCLICK': GamePadKey.LCLICK, 'RCLICK': GamePadKey.RCLICK,
            'UP': GamePadKey.TOP, 'DOWN': GamePadKey.DOWN,
            'LEFT': GamePadKey.LEFT, 'RIGHT': GamePadKey.RIGHT,
        }
        result = {}
        for gamepad_name, key_name in self.mapping.items():
            if key_name in PYGAME_KEY_MAP and gamepad_name in gamepad_enum:
                result[PYGAME_KEY_MAP[key_name]] = gamepad_enum[gamepad_name]
        return result

    # ── 事件处理 ──────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> Optional[str]:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            for btn_name, btn_rect in self.buttons.items():
                if btn_rect.collidepoint(mx, my):
                    if btn_name == 'modify':
                        if self.editing:
                            self.editing = False
                            self.editing_item = None
                            self.editing_msg = ""
                            return "keymap: 已取消编辑"
                        else:
                            self.editing = True
                            self.editing_item = None
                            self.editing_msg = "点击手柄按钮，再按新键"
                            return f"keymap: {self.editing_msg}"
                    elif btn_name == 'confirm':
                        return self.confirm()
                    elif btn_name == 'reset':
                        return self.reset()
                    return None

            # 编辑模式：点击映射项（支持切换选择）
            if self.editing:
                idx = self.hit_test_item(mx, my)
                if idx is not None:
                    if self.editing_item != idx:
                        self.editing_item = idx
                        gamepad, old_key = self.items[idx]
                        self.editing_msg = f"按下新按键替换 {gamepad}（当前: {old_key.upper()}）..."
                        return f"keymap: {self.editing_msg}"
                    return None  # 点击已选中的项，不做任何事

        if self.editing and self.editing_item is not None and event.type == pygame.KEYDOWN:
            key_name = PYGAME_KEY_REVERSE.get(event.key)
            if key_name:
                gamepad, _ = self.items[self.editing_item]
                self.mapping[gamepad] = key_name
                self.build_items()
                self.editing_item = None
                self.editing_msg = f"已修改: {gamepad} ← {key_name.upper()}"
                return f"keymap: {self.editing_msg}"

        return None

    def confirm(self) -> Optional[str]:
        if not self.editing:
            return None
        self.editing = False
        self.editing_item = None
        self.editing_msg = ""
        # 只保存与默认不同的项（gamepad -> key_name）
        custom = {}
        for gamepad, key_name in self.mapping.items():
            if DEFAULT_KEY_MAPPING.get(gamepad) != key_name:
                custom[gamepad] = key_name
        save_custom_to_yaml(custom)
        return "keymap: 按键映射已保存到 custom.yaml"

    def reset(self) -> Optional[str]:
        self.mapping = dict(DEFAULT_KEY_MAPPING)
        self.build_items()
        self.editing = False
        self.editing_item = None
        self.editing_msg = "已重置为默认按键映射"
        save_custom_to_yaml({})
        return f"keymap: {self.editing_msg}"

    # ── 布局 ──────────────────────────────────────────────────────────────

    def items_area_top(self) -> int:
        return self.y + self.TITLE_H + 26

    def items_area_bottom(self) -> int:
        return self.y + self.height - 26

    def item_rect(self, idx: int) -> pygame.Rect:
        items_per_col = (len(self.items) + self.COLS - 1) // self.COLS
        col = idx // items_per_col
        row = idx % items_per_col

        # 横向：两列整体居中。
        total_area_w = self.width - self.PAD * 2
        col_w = 130
        cols_w = self.COLS * col_w + self.GAP * (self.COLS - 1)
        offset_x = (total_area_w - cols_w) // 2
        item_x = self.x + self.PAD + offset_x + col * (col_w + self.GAP)

        # 纵向：充满可用空间均匀分布（整数运算）
        area_h = self.items_area_bottom() - self.items_area_top()
        rows = items_per_col
        total_item_h = rows * self.ITEM_H
        gap_v = (area_h - total_item_h) // (rows - 1) if rows > 1 else 0
        item_y = self.items_area_top() + row * (self.ITEM_H + gap_v)

        return pygame.Rect(item_x, item_y, col_w, self.ITEM_H)

    def hit_test_item(self, mx: int, my: int) -> Optional[int]:
        for idx in range(len(self.items)):
            if self.item_rect(idx).collidepoint(mx, my):
                return idx
        return None

    # ── 绘制 ──────────────────────────────────────────────────────────────

    def draw(self, screen: pygame.Surface, font=None, small_font=None):
        mx, my = pygame.mouse.get_pos()

        pygame.draw.rect(screen, PANEL_BG,
                        (self.x, self.y, self.width, self.height))

        # 标题栏
        pygame.draw.rect(screen, TITLE_BG,
                        (self.x, self.y, self.width, self.TITLE_H))
        title = "按键映射"
        if self.editing:
            title += " · 编辑中"
        title_c = TEXT_ACCENT if self.editing else TEXT_PRIMARY
        title_surf = self.font.render(title, True, title_c)
        screen.blit(title_surf, (self.x + self.PAD, self.y + 4))

        # 映射项
        for idx, (gp_name, key_name) in enumerate(self.items):
            rect = self.item_rect(idx)
            is_selected = (self.editing_item == idx)
            is_hover = rect.collidepoint(mx, my)
            can_click = self.editing and not is_selected

            if is_selected:
                pygame.draw.rect(screen, (40, 60, 90), rect, border_radius=4)
            elif is_hover and can_click:
                pygame.draw.rect(screen, (42, 42, 46), rect, border_radius=4)

            self.draw_item_row(screen, rect, gp_name, key_name,
                              is_selected=is_selected, is_hover=(is_hover and can_click))

        # 编辑提示
        if self.editing_msg:
            msg = self.font_small.render(self.editing_msg, True, TEXT_ACCENT)
            msg_y = self.items_area_bottom() - msg.get_height() - 2
            screen.blit(msg, (self.x + self.PAD, msg_y))

        # 操作按钮
        for name, rect in self.buttons.items():
            if name == 'modify':
                if self.editing:
                    color = (120, 55, 55)
                    text  = "取消"
                else:
                    color = (55, 110, 75)
                    text  = "修改"
            elif name == 'confirm':
                if self.editing:
                    color = (55, 95, 115)
                    text  = "确认"
                else:
                    color = (60, 60, 60)
                    text  = "确认"
            else:
                color = (175, 115, 35)
                text  = "重置"

            hover = rect.collidepoint(mx, my)
            c = tuple(min(255, v + 20) for v in color) if hover else color

            pygame.draw.rect(screen, c, rect, border_radius=3)
            pygame.draw.rect(screen, (150, 150, 150), rect, 1, border_radius=3)

            t = self.font_small.render(text, True, (220, 220, 220))
            screen.blit(t, t.get_rect(center=rect.center))

        # 面板边框（与标签制作、运行输出等模块风格一致）
        pygame.draw.rect(screen, (100, 100, 100),
                        (self.x, self.y, self.width, self.height), 2)

    def draw_item_row(self, screen, rect, gp_name, key_name,
                      is_selected=False, is_hover=False):
        """绘制一行：[手柄标签] → [键盘按键]"""

        # ── 手柄按钮标签（统一宽度胶囊） ──
        tag_x = rect.x + 2
        tag_y = rect.centery - self.GP_TAG_H // 2
        tag_rect = pygame.Rect(tag_x, tag_y, self.GP_TAG_W, self.GP_TAG_H)

        bg = GP_TAG_COLORS.get(gp_name, (130, 130, 140))
        if is_hover:
            bg = tuple(min(255, c + 25) for c in bg)

        r = self.GP_TAG_H // 2
        pygame.draw.rect(screen, bg,
                        (tag_x + r, tag_y, self.GP_TAG_W - 2 * r, self.GP_TAG_H))
        pygame.draw.circle(screen, bg, (tag_x + r, rect.centery), r)
        pygame.draw.circle(screen, bg, (tag_x + self.GP_TAG_W - r, rect.centery), r)

        # 手柄标签文字（加粗）
        display = GAMEPAD_DISPLAY.get(gp_name, gp_name)
        tag_text = self.font_tag.render(display, True, (255, 255, 255))
        screen.blit(tag_text, tag_text.get_rect(center=tag_rect.center))

        # ── 箭头 ──
        arrow_x = tag_rect.right + 4
        arrow_c = TEXT_ACCENT if is_selected else TEXT_DIM
        arrow = self.font_arrow.render("→", True, arrow_c)
        screen.blit(arrow, (arrow_x, rect.centery - arrow.get_height() // 2))

        # ── 键盘按键标签（加粗白色） ──
        key_x = arrow_x + arrow.get_width() + 4
        display_key = KEY_DISPLAY.get(key_name.upper(), key_name.upper())
        key_c = (255, 255, 255) if is_selected else TEXT_PRIMARY
        key_surf = self.font_key.render(display_key, True, key_c)
        screen.blit(key_surf, (key_x, rect.centery - key_surf.get_height() // 2))

    def get_rect(self) -> pygame.Rect:
        return pygame.Rect(self.x, self.y, self.width, self.height)
