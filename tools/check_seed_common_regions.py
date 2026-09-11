"""Guard direct-run integration; arithmetic replay lives in the tool repository."""
from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
LIB = (ROOT / "lib/25_校准_投票决策.ecs").read_text(encoding="utf-8")
ENTRIES = ("NS火叶全自动一键乱数2.0.ecs", "NS火叶全自动一键乱数2.0-时间轴.ecs")


def function(text, name):
    return re.search(rf"(?ms)^FUNC {name}[^\n]*\n.*?^ENDFUNC", text)[0]


blocks = []
for name in ENTRIES:
    text = (ROOT / name).read_text(encoding="utf-8")
    assert text.count("# SEED_COMMON_REGION_HOOK_V2_STARTER_ONLY") == 1
    assert text.count("$投票忽略 = 共同区提交()") == 1
    assert "IF $御三家严格筛选 == 1 and $反查细分成功 == 1\n            $投票忽略 = 共同区提交()" in text
    assert "投票提交本轮Seed范围()" not in text
    reset = function(text, "重置本轮候选状态")
    assert "IF $御三家严格筛选 == 1\n        CALL 共同区开始扫描" in reset
    block = function(text, "处理匹配候选")
    assert "IF $御三家严格筛选 == 1\n        $投票忽略 = 共同区收集($游戏版本, $种子索引, $Seed累计修正索引, $当前消耗帧, $消耗帧实际执行修正量, $NXSeed平台偏移MS)" in block
    assert "IF $御三家严格筛选 == 1\n        $当前候选MSE = $当前候选MSE + 共同区候选加权距离" in block
    blocks.append(block)
assert blocks[0] == blocks[1], "两入口候选共同区必须一致"
assert LIB.count("# SEED_COMMON_REGION_V1_BEGIN") == 1
assert "$C_御三家启用 = 0" in LIB
assert "IF $C_御三家启用 == 0" in function(LIB, "共同区开始扫描")
assert "IF $C_御三家启用 == 0" in function(LIB, "共同区收集")
assert "IF $C_御三家启用 == 0" in function(LIB, "共同区收集配对")
assert "IF $C_御三家启用 == 0" in function(LIB, "共同区提交")
assert "IF $C_御三家启用 == 0" in function(LIB, "共同区候选加权距离")
assert "FUNC 投票提交Seed交叉区间" not in LIB
module = LIB.split("# SEED_COMMON_REGION_V1_BEGIN", 1)[1].split("# SEED_COMMON_REGION_V1_END", 1)[0]
assert not re.search(r"(?m)^\s*(?:WAIT|A|B|X|HOME|UP|DOWN)(?:\s|$)", module)
assert "$共同区Seed总跨度 = 100" in module
assert "$共同区ADV总跨度 = 30" in module
assert "取MS($游戏, $C_tmp)" in module
assert "IF $C_xcover != $C_cover" in module
assert "共同区记录解释包络" in module
print("Common-region checks passed: starter-only entry hooks and library fallback; paired bounded 2D module; no game actions")
