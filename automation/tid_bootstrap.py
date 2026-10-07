"""Install the user-accepted no-save preparation into generated TID ID stages.

The mother, its normal input timeline and the lab bridge remain unchanged.
Only the selected language's OP guard gains the preparation/verification path.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_PATH = ROOT / "assets/tid_rng137_extensions/no_save_bootstrap.ecs"
MARKER = "# TID_AUTO_BOOTSTRAP_V1"
GUARD_BEGIN = "# TID_AUTO_BOOTSTRAP_ENTRY_BEGIN"
GUARD_END = "# TID_AUTO_BOOTSTRAP_ENTRY_END"


def entry_guard(prefix: str, *, indent: str = "    ") -> str:
    """Run once on confirmed no-save; next original loop verifies the new save."""
    lines = f"""{GUARD_BEGIN}
IF $OP新建存档检查 == -1
    PRINT "FRLG_STAGE|FAIL|tid.new_save_entry|存档与无存档同时达到95；保留画面，不创建存档|!"
    RETURN
ELIF $OP新建存档检查 == 2
    PRINT "FRLG_STAGE|END|tid.new_save_entry|!"
    IF $TID建档已尝试 == 1 or $TID建档等待验证 == 1
        PRINT TID自动建档失败：保存后重启仍是无存档；不重复创建，保留画面
        PRINT "FRLG_STAGE|FAIL|tid.bootstrap.verify|保存后重启仍无存档|!"
        RETURN
    ENDIF
    $TID建档已尝试 = 1
    PRINT TID自动建档：确认无存档，先创建临时基础身份并设置文字速度FAST
    PRINT 临时身份不会作为目标TID/SID结果；成功验证后重新开始原TID计时
    CALL TID建档_创建新游戏
    IF $连续流程_游戏版本 == 1
        PRINT "FRLG_STAGE|BEGIN|tid.bootstrap.text_speed|tid.bootstrap.text_speed|30000|main.ecs|TID建档_设置语速并首次保存|tid.bootstrap.options|manual_prepare_then_restart|OR;日版TEXT_SPEED_FAST.IL:>=:95,日版TEXT_SPEED_MID.IL:>=:95,日版TEXT_SPEED_SLOW.IL:>=:95|!"
    ELSE
        PRINT "FRLG_STAGE|BEGIN|tid.bootstrap.text_speed|tid.bootstrap.text_speed|30000|main.ecs|TID建档_设置语速并首次保存|tid.bootstrap.options|manual_prepare_then_restart|OR;TEXT_SPEED_FAST.IL:>=:95,TEXT_SPEED_MID.IL:>=:95,TEXT_SPEED_SLOW.IL:>=:95|!"
    ENDIF
    $TID建档结果 = TID建档_设置语速并首次保存()
    IF $TID建档结果 != 1
        PRINT TID自动建档停止：语速页面或FAST未确认，不保存、不重启，保留画面
        PRINT "FRLG_STAGE|FAIL|tid.bootstrap.text_speed|语速页面或FAST未确认；FAST=" & $TID建档FAST分 & ",MID=" & $TID建档MID分 & ",SLOW=" & $TID建档SLOW分 & "|!"
        RETURN
    ENDIF
    PRINT "FRLG_STAGE|END|tid.bootstrap.text_speed|!"
    $TID建档等待验证 = 1
    CALL {prefix}_清空窗口
    $denoise_hit_count = 0
    PRINT TID自动建档：首次保存操作完成，重启验证后继续原搜索点
    CONTINUE
ENDIF
IF $TID建档等待验证 == 1
    $TID建档等待验证 = 0
    PRINT TID自动建档验证成功：重启后有存档，开始原TID流程
ENDIF
{GUARD_END}
"""
    return "".join(indent + line + "\n" for line in lines.splitlines())


def install_tid_bootstrap(text: str, language: str) -> str:
    from .tid_starter_save import split_tid_modules

    head, english, japanese, tail = split_tid_modules(text)
    prefix = "EN" if language == "英文" else "JP"
    selected = english if prefix == "EN" else japanese
    call = "$OP新建存档检查 = TID_检测新建存档()"
    if call not in selected:
        # Historical templates without the bounded common detector remain
        # historical; do not guess their timing or add an unverified entry.
        return text
    if GUARD_BEGIN in selected:
        if MARKER not in head or selected.count(GUARD_BEGIN) != 1:
            raise ValueError("TID自动建档扩展不完整或重复，请重新生成")
        return text

    if MARKER not in head:
        extension = EXTENSION_PATH.read_text(encoding="utf-8")
        detector_pattern = r"(?ms)^FUNC TID_检测新建存档\(\): INT\n.*?^ENDFUNC\n"
        detectors = list(re.finditer(detector_pattern, head))
        replacement = re.search(detector_pattern, extension)
        if len(detectors) != 1 or replacement is None:
            raise ValueError("TID自动建档需要唯一的原OP存档检测函数")
        original = detectors[0].group()
        for required in ("$OP检查截止 = 400", "500 - $OP检查耗时", "@存档", "$OP连续匹配 >= 2"):
            if required not in original:
                raise ValueError("TID自动建档的原OP检测结构与审计版本不一致")
        head = head.replace(original, replacement.group(), 1)
        extension = extension.replace(replacement.group(), "", 1)
        anchor = "# 唤醒设备\n"
        if head.count(anchor) != 1:
            raise ValueError("TID自动建档缺少唯一的全局唤醒锚点")
        head = head.replace(anchor, extension.rstrip() + "\n\n" + anchor, 1)

    pattern = (
        r"(?ms)^(?P<indent>[ \t]*)\$OP新建存档检查 = TID_检测新建存档\(\)\n"
        r"(?P=indent)IF \$OP新建存档检查 == 0\n.*?^(?P=indent)ENDIF\n"
    )
    guards = list(re.finditer(pattern, selected))
    if len(guards) != 1:
        raise ValueError("TID自动建档需要唯一的原OP失败重试入口")
    guard = guards[0]
    if f"CALL {prefix}_清空窗口" not in guard.group() or "TID_增加OP修正()" not in guard.group() or "CONTINUE" not in guard.group():
        raise ValueError("TID自动建档不能替代缺失的原OP恢复路径")
    selected = selected[:guard.end()] + entry_guard(prefix, indent=guard["indent"]) + selected[guard.end():]
    # The supervisor must accept either menu. Bootstrap itself still requires
    # a unique 95-point result; OR here is not permission to skip that guard.
    selected = selected.replace(
        'OR;存档.IL:>=:" & $识图判断阈值 & "|!"',
        'OR;存档.IL:>=:95,无存档.IL:>=:95|!"',
    )
    return head + (selected if prefix == "EN" else english) + (selected if prefix == "JP" else japanese) + tail
