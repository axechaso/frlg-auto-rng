"""
游戏公共文本数据 — 从 assets/game_text.json 加载。
统一管理宝可梦中英文译名、地点、分类等公共映射。
"""
import json
import os


def load_game_text():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "game_text.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


game_text = load_game_text()

# ── 宝可梦译名 ──
SPECIES_EN_TO_ZH: dict = game_text["species_en_to_zh"]
SPECIES_ZH_TO_EN: dict = {v: k for k, v in SPECIES_EN_TO_ZH.items()}

# 向后兼容别名
STATIC_POKEMON_EN_TO_ZH = SPECIES_EN_TO_ZH
STATIC_POKEMON_ZH_TO_EN = SPECIES_ZH_TO_EN

# ── 遇敌分类 ──
CATEGORY_ZH_TO_EN: dict = {
    **game_text["category_zh_to_en"],
    # Accept the old UI wording in saved/external input, but keep the Gen 3
    # canonical display name below as 厉害钓竿.
    "超级钓竿": "SuperRod",
}
CATEGORY_EN_TO_ZH: dict = {
    v: k for k, v in game_text["category_zh_to_en"].items()
}

# ── 遇敌方式 ──
METHOD_ZH_TO_EN: dict = game_text["method_zh_to_en"]
METHOD_EN_TO_ZH: dict = {v: k for k, v in METHOD_ZH_TO_EN.items()}

STATIC_CATEGORIES: list = game_text["static_categories"]
WILD_CATEGORIES: list = game_text["wild_categories"]

# ── 静态宝可梦分组 ──
STATIC_POKEMON_MAP: dict = game_text["static_pokemon_map"]

# ── 地点 ──
LOCATION_EN_TO_ZH: dict = game_text["location_en_to_zh"]
LOCATION_ZH_TO_EN: dict = {v: k for k, v in LOCATION_EN_TO_ZH.items()}

# ── 游戏设置 ──
SOUND_ZH_TO_EN: dict = game_text["sound_zh_to_en"]
SOUND_EN_TO_ZH: dict = {v: k for k, v in SOUND_ZH_TO_EN.items()}

BTN_MODE_ZH_TO_EN: dict = game_text["btn_mode_zh_to_en"]
BTN_MODE_EN_TO_ZH: dict = {v: k for k, v in BTN_MODE_ZH_TO_EN.items()}

SEED_BTN_ZH_TO_EN: dict = game_text["seed_btn_zh_to_en"]
SEED_BTN_EN_TO_ZH: dict = {v: k for k, v in SEED_BTN_ZH_TO_EN.items()}

EXTRA_BTN_ZH_TO_EN: dict = game_text["extra_btn_zh_to_en"]
EXTRA_BTN_EN_TO_ZH: dict = {v: k for k, v in EXTRA_BTN_ZH_TO_EN.items()}

# Ten Lines keeps these values in English for its search API.  The GUI uses
# Chinese display labels and maps them back before constructing a request.
FILTER_SHINY_ZH_TO_EN = {
    "星形/方形闪光": "Star/Square",
    "星形闪光": "Star",
    "方形闪光": "Square",
    "不限": "Any",
}
FILTER_GENDER_ZH_TO_EN = {"不限": "Any", "雄": "M", "雌": "F", "无性别": "-"}
FILTER_NATURE_ZH_TO_EN = {
    "勤奋": "Hardy", "怕寂寞": "Lonely", "勇敢": "Brave", "固执": "Adamant", "调皮": "Naughty",
    "大胆": "Bold", "直率": "Docile", "悠闲": "Relaxed", "淘气": "Impish", "乐天": "Lax",
    "胆小": "Timid", "急躁": "Hasty", "认真": "Serious", "爽朗": "Jolly", "天真": "Naive",
    "内敛": "Modest", "慢吞吞": "Mild", "冷静": "Quiet", "害羞": "Bashful", "马虎": "Rash",
    "沉着": "Calm", "温和": "Gentle", "自大": "Sassy", "慎重": "Careful", "浮躁": "Quirky",
    "不限": "Any",
}
FILTER_TYPE_ZH_TO_EN = {
    "格斗": "Fighting", "飞行": "Flying", "毒": "Poison", "地面": "Ground",
    "岩石": "Rock", "虫": "Bug", "幽灵": "Ghost", "钢": "Steel", "火": "Fire",
    "水": "Water", "草": "Grass", "电": "Electric", "超能力": "Psychic", "冰": "Ice",
    "龙": "Dragon", "恶": "Dark", "不限": "Any",
}
ABILITY_EN_TO_ZH = {
    "Stench": "恶臭", "Drizzle": "降雨", "Speed Boost": "加速", "Battle Armor": "战斗盔甲",
    "Sturdy": "坚硬", "Damp": "湿气", "Limber": "柔软", "Sand Veil": "沙隐", "Static": "静电",
    "Volt Absorb": "蓄电", "Water Absorb": "储水", "Oblivious": "迟钝", "Cloud Nine": "无关天气",
    "Compound Eyes": "复眼", "Insomnia": "不眠", "Color Change": "变色", "Immunity": "免疫",
    "Flash Fire": "引火", "Shield Dust": "鳞粉", "Own Tempo": "我行我素", "Suction Cups": "吸盘",
    "Intimidate": "威吓", "Shadow Tag": "踩影", "Rough Skin": "粗糙皮肤", "Wonder Guard": "神奇守护",
    "Levitate": "飘浮", "Effect Spore": "孢子", "Synchronize": "同步", "Clear Body": "恒净之躯",
    "Natural Cure": "自然回复", "Lightning Rod": "避雷针", "Serene Grace": "天恩", "Swift Swim": "悠游自如",
    "Chlorophyll": "叶绿素", "Illuminate": "发光", "Trace": "复制", "Huge Power": "大力士",
    "Poison Point": "毒刺", "Inner Focus": "精神力", "Magma Armor": "熔岩铠甲", "Water Veil": "水幕",
    "Magnet Pull": "磁力", "Soundproof": "隔音", "Rain Dish": "雨盘", "Sand Stream": "扬沙",
    "Pressure": "压迫感", "Thick Fat": "厚脂肪", "Early Bird": "早起", "Flame Body": "火焰之躯",
    "Run Away": "逃跑", "Keen Eye": "锐利目光", "Hyper Cutter": "怪力钳", "Pickup": "捡拾",
    "Truant": "懒惰", "Hustle": "活力", "Cute Charm": "迷人之躯", "Plus": "正电", "Minus": "负电",
    "Forecast": "阴晴不定", "Sticky Hold": "黏着", "Shed Skin": "蜕皮", "Guts": "毅力",
    "Marvel Scale": "神奇鳞片", "Liquid Ooze": "污泥浆", "Overgrow": "茂盛", "Blaze": "猛火",
    "Torrent": "激流", "Swarm": "虫之预感", "Rock Head": "坚硬脑袋", "Drought": "日照",
    "Arena Trap": "沙穴", "Vital Spirit": "干劲", "White Smoke": "白烟", "Pure Power": "瑜伽之力",
    "Shell Armor": "硬壳盔甲", "Air Lock": "气闸",
}
ABILITY_ZH_TO_EN = {"不限": "Any", **{v: k for k, v in ABILITY_EN_TO_ZH.items()}}


# ── 努力值属性 ──
STAT_ZH_MAP: dict = game_text["stat_zh_map"]
ALL_STATS: list = game_text["all_stats"]


# ── 辅助函数 ──

def location_to_zh(en_name: str) -> str:
    """英文地点名 → 中文"""
    return LOCATION_EN_TO_ZH.get(en_name, en_name)


def location_to_en(zh_name: str) -> str:
    """中文地点名 → 英文"""
    return LOCATION_ZH_TO_EN.get(zh_name, zh_name)


def species_to_zh(en_name: str) -> str:
    """英文宝可梦名 → 中文"""
    return SPECIES_EN_TO_ZH.get(en_name, en_name)


def species_to_en(zh_name: str) -> str:
    """中文宝可梦名 → 英文"""
    return SPECIES_ZH_TO_EN.get(zh_name, zh_name)
