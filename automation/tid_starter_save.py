"""Adapt the user's combined 164a TID/save script to the existing three stages.

Keep the selected language's timing code and the save route from one source.
The ID stage ends at the trainer card; only the bridge stage walks and saves.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tid_rng137 import TidRngRequest


TID_STARTER_SAVE_NAME = "NS火叶TID-SID到御三家球前存档-测试.ecs"
TID_STARTER_SAVE_SHA256 = "a732fbaa2726a67ce584f4cddf9bc2b5f82cf94f188b59dea760e29d77211b00"
TID_STARTER_SAVE_SUPPORTED_SHA256 = {
    TID_STARTER_SAVE_SHA256,
    # Previous unified mother before both label paths rejected >65535 and
    # first-position 7/8/9 were removed consistently.
    "143fcdcf816e5754abcc6acac68eb9e2e8ffd9b2c2dd4705dd08ac1c4381cb36",
    # Previous unified mother before English OCR-first recognition was merged.
    "b20057d7f79ac1f8a7fc0d5f8eaa983333ea4adc66fe1b2cf40b38e757682633",
    # Previous combined source before the dark HOME-closing recognition path.
    "ca12bdc6ad08db2f2fe9473c9990bea105e523863067f0de8413ceeb0ab814b8",
    # Previous combined source before NX-specific, bounded startup retries.
    "c2e6f316e2ef66d4968fb26327761d7be29fcb593d15b72c017a2d356b454504",
    # Previous combined source before the English naming page wait became 600 ms.
    "ecfeaa5d2209992711afaa17e6967c287bd657b9c38085762b785db1b081baf5",
    "3b8cb56328817dcf5adec8c6271a530fae8aab3ce6b784b29a73d22797c366c5",
    "54decdea179cf86689426444779cef90b6bedaa490932843901b83d541f97b35",
    # 2026-08-27-r4 and earlier audited revisions remain valid inputs.
    "02734f7382d6921f40e1a2de4049b4d195e2e094d5e8ca47dd67793d4a519f21",
    "ba4d1f602915d40382cb93a51b1484ba3942868945cbfa45e1d133ef59d8d383",
    "485278694b326ae9a1b4bcc3aeb37b629a9ef212fa6688a1a7fc6c5f1626b324",
    "8ccbe63e539788c72ef20219ca5b58dce124f58bbb3940cc9ed55cce8e16ce03",
    # 同一执行代码，仅英文用户区的 $ID_RNG 初值为 0。
    "711f6ceb6fd08309a92b98caa853db235ab5b25070f3813baa5011e9af89cd58",
}
_LOCAL_TID_STARTER_SAVE_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "local_assets" / "tid_rng137" / TID_STARTER_SAVE_NAME
)
_DOWNLOADED_TID_STARTER_SAVE_SOURCE = (
    Path.home() / "Downloads" / "NS火叶全自动一键乱数1.1.8" / TID_STARTER_SAVE_NAME
)
DEFAULT_TID_STARTER_SAVE_SOURCE = (
    _LOCAL_TID_STARTER_SAVE_SOURCE
    if _LOCAL_TID_STARTER_SAVE_SOURCE.is_file()
    else _DOWNLOADED_TID_STARTER_SAVE_SOURCE
)


def resolve_tid_starter_save_template(source_dir: str | Path) -> Path:
    """Resolve the unified mother for extracting its starter-route bridge."""
    path = Path(source_dir).resolve() / TID_STARTER_SAVE_NAME
    if not path.is_file():
        raise FileNotFoundError(f"TID连续流程缺少球前路线资源：{TID_STARTER_SAVE_NAME}")
    return path
_EN_MARKER = "# ===== 英文版 TID/SID 主体（顶层全局分支） ====="
_JP_MARKER = "# ===== 日文版 TID/SID 主体（顶层全局分支） ====="
_TAIL_MARKER = (
    "# =========================================================\n"
    "# 顶层入口收尾：ID 主体结束后才进入研究所桥接。"
)
_USER_END = "# ======================== 用户自定义区结束"
_COMPACT_USER_END = "\n$KeyDelay = 50\n"
_COMPACT_TAIL = "IF $连续流程_游戏版本 != 0 and $连续流程_游戏版本 != 1\n"
_ID_END = "# 工具 ID 阶段结束：桥接与存档只在第二阶段执行。\nRETURN 0\n"
_EN_NAME_PAGE_WAIT_550 = "$select基础次数 += 1\n        550"
_EN_NAME_PAGE_WAIT_600 = "$select基础次数 += 1\n        600"


def is_starter_save_template(text: str) -> bool:
    return _EN_MARKER in text and _JP_MARKER in text


def stabilize_english_name_page_wait(text: str) -> str:
    """Give the English naming page 50 ms more time before cursor movement."""
    if "FUNC EN_切换到目标页" not in text:
        return text
    old_count = text.count(_EN_NAME_PAGE_WAIT_550)
    new_count = text.count(_EN_NAME_PAGE_WAIT_600)
    if old_count == 1 and new_count == 0:
        return text.replace(_EN_NAME_PAGE_WAIT_550, _EN_NAME_PAGE_WAIT_600, 1)
    if old_count == 0 and new_count == 1:
        return text
    raise ValueError(
        "英文取名翻页等待结构不唯一："
        f"550ms={old_count}，600ms={new_count}"
    )


def split_tid_modules(text: str) -> tuple[str, str, str, str]:
    """Return global/route code, EN module, JP module and the top-level tail."""
    for marker in (_EN_MARKER, _JP_MARKER):
        if text.count(marker) != 1:
            raise ValueError("TID球前存档模板缺少唯一语言分支：" + marker)
    head, _, rest = text.partition(_EN_MARKER)
    english, _, japanese = rest.partition(_JP_MARKER)
    # 旧版注释收尾区本身也包含游戏语言检查，须优先使用完整旧标记。
    tail_marker = next((marker for marker in (_TAIL_MARKER, _COMPACT_TAIL, _ID_END) if marker in japanese), None)
    if tail_marker is None or japanese.count(tail_marker) != 1:
        raise ValueError("TID球前存档模板缺少唯一的顶层收尾区")
    japanese, _, tail = japanese.partition(tail_marker)
    return head, _EN_MARKER + english, _JP_MARKER + japanese, tail_marker + tail


def replace_user_values(module: str, values: dict[str, Any]) -> str:
    from .tid_rng137 import _ecs_literal

    boundary = _USER_END if _USER_END in module else _COMPACT_USER_END
    user, separator, rest = module.partition(boundary)
    if not separator:
        raise ValueError("TID球前存档模板缺少用户自定义区结束标记")
    for name, value in values.items():
        user, count = re.subn(
            rf"(?m)^([ \t]*){re.escape(name)}[ \t]*=[^\r\n]*$",
            lambda match: f"{match[1]}{name} = {_ecs_literal(value)}",
            user,
        )
        if count != 1:
            raise ValueError(f"TID球前存档字段 {name} 应出现1次，实际为{count}次")
    return user + separator + rest


def _blocking_buttons(text: str) -> str:
    """Use the same explicit DOWN/WAIT/UP convention as the new TID source."""
    pattern = re.compile(r"(?m)^([ \t]*)(A|B|HOME)(?:[ \t]+(\d+))?([ \t]*(?:#[^\n]*)?)$")
    return pattern.sub(
        lambda m: f"{m[1]}{m[2]} DOWN{m[4]}\n{m[1]}WAIT {m[3] or 50}\n{m[1]}{m[2]} UP",
        text,
    )


def _adaptive_home_buffer(module: str, prefix: str) -> str:
    from .tid_rng137 import TID_HOME_BUFFER_ADAPTIVE_PATH, _TID_HOME_BUFFER_ORIGINAL

    if prefix == "TID" and "FUNC TID_HOME_BUFFER(): INT\n" in module:
        # Keep r4's return values, 20-attempt limit, checked close calls and
        # 50 ms steps. Only substitute the opt-in image classifier.
        pattern = r"(?ms)^FUNC TID_HOME_BUFFER\(\): INT\n.*?^ENDFUNC"
        matches = list(re.finditer(pattern, module))
        if len(matches) != 1:
            raise ValueError("TID共享HOME_BUFFER返回值结构不唯一")
        match = matches[0]
        body = match.group()
        replacements = {
            "        CALL TID_读取当前退出标签\n":
                "        $HOME_BUFFER识别状态 = TID_HOME_BUFFER识别稳定状态()\n",
            "IF $TID当前HOME_BUFFER正确退出 >= 95 and $TID当前错误退出 < 95":
                "IF $HOME_BUFFER识别状态 == 1 and $HOME_BUFFER选中错误 < $HOME_BUFFER有效识图阈值",
            "ELIF $TID当前错误退出 >= 95": "ELIF $HOME_BUFFER识别状态 == 3",
            "ELIF $TID当前正确退出 >= 95": "ELIF $HOME_BUFFER识别状态 == 2",
        }
        for old, new in replacements.items():
            if body.count(old) != 1:
                raise ValueError("TID共享HOME_BUFFER识图分支与审计版本不一致")
            body = body.replace(old, new, 1)
        classifier = TID_HOME_BUFFER_ADAPTIVE_PATH.read_text(encoding="utf-8").split(
            "\nFUNC HOME_BUFFER\n", 1
        )[0].rstrip()
        return module[:match.start()] + classifier + "\n\n" + body + module[match.end():]

    def convert(text: str) -> str:
        return _blocking_buttons(text).replace(
            "FUNC HOME_BUFFER", f"FUNC {prefix}_HOME_BUFFER"
        ).replace("CALL 关闭游戏", f"CALL {prefix}_关闭游戏")

    original = convert(_TID_HOME_BUFFER_ORIGINAL)
    if module.count(original) != 1:
        raise ValueError(f"{prefix}同步按键HOME_BUFFER结构与审计版本不一致")
    extension = convert(TID_HOME_BUFFER_ADAPTIVE_PATH.read_text(encoding="utf-8").rstrip())
    return module.replace(original, extension, 1)


def configure_starter_save_id(
    template: str, request: TidRngRequest, *, include_flow_marker: bool = False
) -> str:
    from .tid_rng137 import _TID_HOME_BUFFER_ADAPTIVE_GLOBALS

    head, english, japanese, _tail = split_tid_modules(template)
    prefix = "EN" if request.language == "英文" else "JP"
    selected = english if prefix == "EN" else japanese
    if prefix == "EN":
        selected = stabilize_english_name_page_wait(selected)
    request.validate(selected)
    values = request.to_user_values()
    values[f"${prefix}_TARGET_TID"] = values.pop("_TARGET_TID")
    values[f"${prefix}_TARGET_SID"] = values.pop("_TARGET_SID")
    selected = replace_user_values(selected, values)
    head, count = re.subn(
        r"(?m)^\$连续流程_游戏版本 = \d+$",
        f"$连续流程_游戏版本 = {0 if prefix == 'EN' else 1}", head,
    )
    if count != 1:
        raise ValueError("TID球前存档模板缺少唯一游戏语言设置")

    if include_flow_marker:
        success = "                IF $denoise_hit_count >= $denoise_need_hit\n                    BREAK 2"
        if selected.count(success) != 5:
            raise ValueError("TID球前存档模板的五种成功退出结构与审计版本不一致")
        # 每处都在打印参数之后：$ID是刚识别的实际TID，$adv已按当前模式计算。
        selected = selected.replace(success, """                IF $denoise_hit_count >= $denoise_need_hit
                    PRINT TIDFLOW|ID|MATCH=1
                    PRINT TIDFLOW|ID|TID= & $ID
                    PRINT TIDFLOW|ID|SID_ADV= & $adv
                    PRINT TIDFLOW|ID|RIVAL_CUSTOM= & $Name_GREEN
                    BREAK 2""")
    if request.home_buffer_adaptive_threshold:
        if re.search(r"(?m)^FUNC TID_HOME_BUFFER(?:\(\): INT)?$", head):
            # r2 两种语言共用启动函数；只替换共享 HOME，不动 OP 检测/恢复。
            head = _adaptive_home_buffer(head, "TID")
        else:
            selected = _adaptive_home_buffer(selected, prefix)
        if head.count("# 唤醒设备\n") != 1:
            raise ValueError("TID球前存档模板缺少全局区结束锚点")
        head = head.replace("# 唤醒设备\n", _TID_HOME_BUFFER_ADAPTIVE_GLOBALS + "\n# 唤醒设备\n", 1)
    head = head.replace(
        "PRINT 命中后只会走到御三家球前存档，不会领取御三家",
        "PRINT 工具ID阶段：命中后停在训练家卡片，球前存档由第二阶段执行",
        1,
    )
    if prefix == "EN":
        english = selected
    else:
        japanese = selected
    return head + english + japanese + _ID_END


def set_starter_save_sid_correction(text: str, language: str, correction: int) -> str:
    """Change only the active user section, never globals or the other language."""
    head, english, japanese, tail = split_tid_modules(text)
    if language == "英文":
        english = replace_user_values(english, {"$SID_ADV修正": correction})
    else:
        japanese = replace_user_values(japanese, {"$SID_ADV修正": correction})
    return head + english + japanese + tail


def render_starter_save_bridge(template: str, starter: str) -> str:
    choices = {"妙蛙种子": 0, "Bulbasaur": 0, "杰尼龟": 1, "Squirtle": 1, "小火龙": 2, "Charmander": 2}
    if starter not in choices:
        raise ValueError("御三家必须是妙蛙种子、小火龙或杰尼龟")
    head, _, _, _ = split_tid_modules(template)
    settings = [f"$连续流程_御三家选择 = {choices[starter]}"]
    for name in ("步进间隔", "按键时长", "Oak文本推进次数"):
        matches = re.findall(rf"(?m)^\$连续流程_{name} = \d+$", head)
        if len(matches) != 1:
            raise ValueError("TID桥接缺少唯一设置：" + name)
        settings.append(matches[0])
    functions = re.findall(r"(?ms)^FUNC (FLOW_[^\s(]+)[^\n]*\n.*?^ENDFUNC", head)
    expected = {"FLOW_走一步上", "FLOW_走一步下", "FLOW_走一步左", "FLOW_走一步右", "FLOW_桥接到御三家存档点"}
    if len(functions) != 5 or set(functions) != expected:
        raise ValueError("TID桥接函数与审计版本不一致")
    bodies = [m[0] for m in re.finditer(r"(?ms)^FUNC FLOW_[^\n]*\n.*?^ENDFUNC", head)]
    return (
        "# 来自 " + TID_STARTER_SAVE_NAME + "；原样复用球前路线。\n"
        + "\n".join(settings) + "\n$连续流程_桥接完成 = 0\n\n"
        + "CALL FLOW_桥接到御三家存档点\n"
        + "IF $连续流程_桥接完成 == 1\n    PRINT TIDFLOW|BRIDGE|DONE=1\nENDIF\nRETURN 0\n\n"
        + "\n\n".join(bodies) + "\n"
    )
