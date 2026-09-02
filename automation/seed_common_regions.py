"""Idempotently install bounded Seed/ADV evidence, without changing controllers.

The ECS asset is canonical (also used by direct EasyCon). No Python process is
needed while the script runs. Legacy connected-component code is removed only
at its known hooks; the existing vote/controller functions remain intact.
"""

from pathlib import Path
import re

from app_paths import RESOURCE_ROOT

ASSET = RESOURCE_ROOT / "assets/easycon118_extensions/seed_common_regions.ecs"
LIBRARY = "lib/25_校准_投票决策.ecs"
ENTRIES = ("NS火叶全自动一键乱数2.0.ecs", "NS火叶全自动一键乱数2.0-时间轴.ecs")


def _function(text: str, name: str) -> str:
    match = re.search(rf"(?ms)^FUNC {re.escape(name)}(?:\([^\n]*\))?(?:: INT)?\n.*?^ENDFUNC", text)
    if match is None:
        raise ValueError(f"共同区升级缺少函数：{name}")
    return match[0]


def upgrade_library(text: str) -> str:
    text = text.replace("\r\n", "\n")
    settings = dict(re.findall(r"(?m)^\$(共同区Seed总跨度|共同区ADV总跨度|共同区参与排序|共同区输出配对) = (\d+)$", text))
    text = re.sub(r"(?ms)^# SEED_COMMON_REGION_V1_BEGIN\n.*?^# SEED_COMMON_REGION_V1_END\n*", "", text)
    if "FUNC 投票提交Seed交叉区间" in text:
        text, count = re.subn(r"(?ms)^\$V_交叉最大轮数 = 12\n.*?(?=^# 注入配置)", "", text)
        if count != 1:
            raise ValueError("旧跨轮全局区无法安全定位")
        for name in ("投票重置本轮Seed范围", "投票提交Seed交叉区间", "投票重排Seed交叉簇", "投票提交本轮Seed范围", "投票取Seed交叉候选距离", "投票取Seed交叉覆盖", "投票打印Seed交叉"):
            text = text.replace(_function(text, name), "")
        old = _function(text, "投票重置")
        new, count = re.subn(r"(?ms)^    # 跨轮范围属于当前目标/路径.*?(?=^    \$V_上次帧最优槽)", "", old)
        if count != 1:
            raise ValueError("旧跨轮重置区无法安全定位")
        text = text.replace(old, new)
        old = _function(text, "投票投候选")
        header = old.splitlines()[0].replace(", $SeedMS输入: INT, $消耗帧输入: INT", "")
        body = old[old.index("    $V_帧绝对 ="):]
        text = text.replace(old, header + "\n" + body)
        text = text.replace("    $V_打印交叉结果 = 投票打印Seed交叉()\n", "")
        if re.search(r"\$V_交叉|投票取Seed交叉候选距离\(", text):
            raise ValueError("仍有未识别的旧跨轮代码，未覆盖原文件")
    if "FUNC 投票重置\n" in text:
        old = _function(text, "投票重置")
        if "CALL 共同区重置" not in old:
            text = text.replace(old, old.replace("ENDFUNC", "    CALL 共同区重置\nENDFUNC"))
    asset = ASSET.read_text(encoding="utf-8").rstrip()
    for name, value in settings.items():
        asset = re.sub(rf"(?m)^\${name} = \d+$", f"${name} = {value}", asset)
    # Keep all new globals before functions: 1.6.4-a has file-scoped globals.
    pos = re.search(r"(?m)^FUNC ", text).start()
    return text[:pos] + asset + "\n\n" + text[pos:]


def upgrade_entry(text: str) -> str:
    text = text.replace("\r\n", "\n")
    if "FUNC 处理匹配候选" not in text:
        return text  # Minimal fixtures / unrelated standalone scripts.
    if "# SEED_COMMON_REGION_HOOK_V1" in text:
        return text
    text = re.sub(r"(?m)^\s*\$投票忽略 = 投票(?:重置本轮Seed范围|提交本轮Seed范围)\(\)\n", "", text)
    text = re.sub(r"(?m)^(    \$投票忽略 = 投票投候选\([^\n]*), \$当前MS, \$当前消耗帧\)$", r"\1)", text)
    text, _ = re.subn(r"(?ms)^    \$当前候选交叉Seed绝对 = .*?^    ENDIF\n", "", text)
    # History reset is inside the library's existing 投票重置; no controller edits.
    old = _function(text, "重置本轮候选状态")
    text = text.replace(old, old.replace("\n", "\n    CALL 共同区开始扫描\n", 1))
    old = _function(text, "处理匹配候选")
    anchor = "    $当前候选帧原始 = $当前消耗帧 - $目标消耗帧\n"
    if old.count(anchor) != 1:
        raise ValueError("无法定位候选收集入口")
    new = old.replace(anchor, anchor + "    $投票忽略 = 共同区收集($游戏版本, $种子索引, $Seed累计修正索引, $当前消耗帧, $消耗帧实际执行修正量, $NXSeed平台偏移MS)\n")
    anchor = "    # NPC离群过滤："
    pos = new.index(anchor)
    new = new[:pos] + "    $当前候选MSE = $当前候选MSE + 共同区候选加权距离($种子索引 + $Seed累计修正索引, $当前消耗帧 + $消耗帧实际执行修正量, $候选权重Seed, $候选权重帧)\n" + new[pos:]
    text = text.replace(old, new)
    # Exactly once per acquired Pokemon, after candy refinement, before calibration.
    anchor = "        $反查细分成功 = 执行识图反查直到候选唯一()\n"
    if text.count(anchor) != 1:
        raise ValueError("无法定位最终候选提交点")
    text = text.replace(anchor, anchor + "        IF $反查细分成功 == 1\n            $投票忽略 = 共同区提交()\n        ENDIF\n")
    return "# SEED_COMMON_REGION_HOOK_V1\n" + text


def apply_seed_common_regions(project_dir: str | Path, entries=ENTRIES) -> bool:
    root = Path(project_dir)
    originals = {root / name: (root / name).read_text(encoding="utf-8") for name in entries}
    if not any("FUNC 处理匹配候选" in text for text in originals.values()):
        return False
    configured = {path: upgrade_entry(text) for path, text in originals.items()}
    library = root / LIBRARY
    configured[library] = upgrade_library(library.read_text(encoding="utf-8"))
    # All compatibility checks above finish before any write.
    for path, text in configured.items():
        if path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
    return True
