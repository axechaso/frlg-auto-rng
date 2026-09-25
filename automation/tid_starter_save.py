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
TID_STARTER_SAVE_SHA256 = "116aa90e3874dc4d79a8fc7f4f178dc923bf7021f0e3fc0929716c0e734c98ec"
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
_CLOSED_HOME_MARKER = "TID关闭游戏：已连续确认主页且游戏未运行"


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


def _accept_already_closed_home(text: str) -> str:
    """Let the shared TID shutdown stage continue when no title is running."""
    if _CLOSED_HOME_MARKER in text:
        return text
    if "FUNC TID_关闭游戏(): INT\n" not in text:
        return text

    global_anchor = "$TID当前正确退出 = 0\n"
    if text.count(global_anchor) != 1:
        raise ValueError("TID关闭游戏缺少唯一的当前退出标签全局变量")
    text = text.replace(
        global_anchor,
        "$TID当前主页 = 0\n"
        "$TID当前正确退出 = 0\n"
        "$TID关闭游戏主页稳定 = 0\n",
        1,
    )

    read_function = """FUNC TID_读取当前退出标签
    IF $NS机型 == 2
        $TID当前正确退出 = @正确退出_NS2
        $TID当前HOME_BUFFER正确退出 = @HOME_BUFFER正确退出_NS2
        $TID当前错误退出 = @错误退出_NS2
    ELSE
        $TID当前正确退出 = @正确退出
        $TID当前HOME_BUFFER正确退出 = @HOME_BUFFER正确退出
        $TID当前错误退出 = @错误退出
    ENDIF
ENDFUNC"""
    read_replacement = """FUNC TID_读取当前退出标签
    IF $NS机型 == 2
        $TID当前主页 = @主页_NS2
        $TID当前正确退出 = @正确退出_NS2
        $TID当前HOME_BUFFER正确退出 = @HOME_BUFFER正确退出_NS2
        $TID当前错误退出 = @错误退出_NS2
    ELSE
        $TID当前主页 = @主页
        $TID当前正确退出 = @正确退出
        $TID当前HOME_BUFFER正确退出 = @HOME_BUFFER正确退出
        $TID当前错误退出 = @错误退出
    ENDIF
ENDFUNC"""
    if text.count(read_function) != 1:
        raise ValueError("TID关闭游戏的机型标签读取函数与审计版本不一致")
    text = text.replace(read_function, read_replacement, 1)

    stage_replacements = {
        "OR;正确退出_NS2.IL:>=:95": "OR;主页_NS2.IL:>=:95,正确退出_NS2.IL:>=:95",
        "OR;正确退出.IL:>=:95": "OR;主页.IL:>=:95,正确退出.IL:>=:95",
    }
    for old, new in stage_replacements.items():
        if text.count(old) != 1:
            raise ValueError("TID关闭游戏的阶段监视标签与审计版本不一致")
        text = text.replace(old, new, 1)

    loop_anchor = """    FOR
        $TID关闭游戏尝试 += 1"""
    if text.count(loop_anchor) != 1:
        raise ValueError("TID关闭游戏缺少唯一的重试循环")
    text = text.replace(
        loop_anchor,
        """    $TID关闭游戏主页稳定 = 0
    FOR
        $TID关闭游戏尝试 += 1""",
        1,
    )

    classify_anchor = """        CALL TID_读取当前退出标签
        IF $TID当前正确退出 < 95 and $TID当前HOME_BUFFER正确退出 < 95
            HOME DOWN"""
    classify_replacement = f"""        CALL TID_读取当前退出标签
        IF $TID当前主页 >= 95 and $TID当前正确退出 < 90 and $TID当前HOME_BUFFER正确退出 < 90 and $TID当前错误退出 < 90
            $TID关闭游戏主页稳定 += 1
            IF $TID关闭游戏主页稳定 >= 3
                PRINT {_CLOSED_HOME_MARKER}
                PRINT \"FRLG_STAGE|END|tid.close|!\"
                RETURN 1
            ENDIF
            WAIT 200
            CONTINUE
        ENDIF
        $TID关闭游戏主页稳定 = 0

        IF $TID当前主页 < 95 and $TID当前正确退出 < 95 and $TID当前HOME_BUFFER正确退出 < 95
            HOME DOWN"""
    if text.count(classify_anchor) != 1:
        raise ValueError("TID关闭游戏的主页切换入口与审计版本不一致")
    text = text.replace(classify_anchor, classify_replacement, 1)

    # A visible HOME page with a 90-94 running marker is ambiguous evidence.
    # Resample it instead of changing a timing value that cannot fix OCR.
    error_end = """            WAIT $关闭游戏延迟
            CONTINUE
        ELSE
            PRINT 关闭游戏延迟过短，+100继续尝试"""
    error_end_replacement = """            WAIT $关闭游戏延迟
            CONTINUE
        ELIF $TID当前主页 >= 95
            PRINT TID关闭游戏：主页状态未稳定，保持关闭延迟并重新识别
            WAIT 200
            CONTINUE
        ELSE
            PRINT 关闭游戏延迟过短，+100继续尝试"""
    if text.count(error_end) != 1:
        raise ValueError("TID关闭游戏的未识别分支与审计版本不一致")
    return text.replace(error_end, error_end_replacement, 1)


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
                "        $HOME_BUFFER识别状态 = TID_HOME_BUFFER识别稳定状态()\n"
                "        PRINT \"FRLG_STAGE|THRESHOLD|tid.home_buffer|\" & $HOME_BUFFER有效识图阈值 & \"|!\"\n",
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
        configured = module[:match.start()] + classifier + "\n\n" + body + module[match.end():]
        helper_end = "    ENDIF\nENDFUNC\n\nFUNC TID_HOME_BUFFER(): INT"
        if configured.count(helper_end) > 1:
            raise ValueError("TID HOME_BUFFER阶段登记函数结构不唯一")
        if configured.count(helper_end) == 1:
            configured = configured.replace(
                helper_end,
                "    ENDIF\n"
                "    PRINT \"FRLG_STAGE|THRESHOLD|tid.home_buffer|\" & $HOME_BUFFER有效识图阈值 & \"|!\"\n"
                "ENDFUNC\n\nFUNC TID_HOME_BUFFER(): INT",
                1,
            )
        return configured

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
    head = _accept_already_closed_home(head)
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


def _validate_bridge_save_confirmation(route: str) -> None:
    """Require the current mother script's language-specific save branch."""
    if "PRINT >>> 开始保存 >>>" not in route:
        return

    lines = route.splitlines(keepends=True)
    save_start = next(
        index for index, line in enumerate(lines)
        if "PRINT >>> 开始保存 >>>" in line
    )
    save_end = next(
        index for index in range(save_start + 1, len(lines))
        if "$连续流程_桥接完成 = 1" in lines[index]
    )
    pairs = [
        index for index in range(save_start + 1, save_end - 1)
        if lines[index].strip() == "A" and lines[index + 1].strip() == "WAIT 1500"
    ]
    save_block = "".join(lines[save_start + 1:save_end])
    conditional = re.findall(
        r"(?m)^[ \t]*IF \$连续流程_游戏版本 == 1\r?\n"
        r"[ \t]+A\r?\n[ \t]+WAIT 1500\r?\n[ \t]*ENDIF$",
        save_block,
    )
    if len(conditional) != 1 or len(pairs) != 7:
        raise ValueError("TID桥接覆盖存档缺少当前美版6次、日版7次的语言分支")


def render_starter_save_bridge(
    template: str, starter: str, *, language: str
) -> str:
    choices = {"妙蛙种子": 0, "Bulbasaur": 0, "杰尼龟": 1, "Squirtle": 1, "小火龙": 2, "Charmander": 2}
    if starter not in choices:
        raise ValueError("御三家必须是妙蛙种子、小火龙或杰尼龟")
    if language not in {"英文", "日文"}:
        raise ValueError("TID桥接游戏语言必须是英文或日文")
    head, _, _, _ = split_tid_modules(template)
    settings = [
        f"$连续流程_游戏版本 = {0 if language == '英文' else 1}",
        f"$连续流程_御三家选择 = {choices[starter]}",
    ]
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
    bridge_route = next(
        body for body in bodies
        if body.startswith("FUNC FLOW_桥接到御三家存档点")
    )
    _validate_bridge_save_confirmation(bridge_route)
    return (
        "# 来自 " + TID_STARTER_SAVE_NAME + "；原样复用球前路线。\n"
        + "\n".join(settings) + "\n$连续流程_桥接完成 = 0\n\n"
        + "CALL FLOW_桥接到御三家存档点\n"
        + "IF $连续流程_桥接完成 == 1\n    PRINT TIDFLOW|BRIDGE|DONE=1\nENDIF\nRETURN 0\n\n"
        + "\n\n".join(bodies) + "\n"
    )
