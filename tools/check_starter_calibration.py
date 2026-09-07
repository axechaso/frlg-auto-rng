"""Guard paired starter selection, unchanged controllers and measured menu timing."""
from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
ENTRIES = ("NS火叶全自动一键乱数2.0.ecs", "NS火叶全自动一键乱数2.0-时间轴.ecs")


def function(text, name):
    return re.search(rf"(?ms)^FUNC {name}[^\n]*\n.*?^ENDFUNC", text)[0]


texts = [(ROOT / name).read_text(encoding="utf-8") for name in ENTRIES]
for text in texts:
    assert text.count("# STARTER_CALIBRATION_V1") == 1
    assert text.index("共同区提交()") < text.index("$御三家筛选结果 = 御三家应用共同候选()")
    assert "IF $御三家筛选结果 != 1\n                $循环计数 += 1\n                BREAK" in text
    assert "CALL 投票重置Seed校准\nCALL 共同区重置" in text
    scan = function(text, "执行识图反查直到候选唯一")
    assert scan.index("御三家完整候选保留") < scan.index("尝试收束候选()")
    assert "$有效最小消耗帧 = $御三家预测帧 - 500" in scan
    assert "$有效最大消耗帧 = $御三家预测帧 + 500" in scan
    assert "IF $当前扩窗层 >= 1\n                    BREAK" in scan
    selection = function(text, "御三家应用共同候选")
    assert "共同区选择本轮配对()" in selection
    assert "CALL 按算法生成个体\n    CALL 检查是否匹配" in selection
    assert "$当前消耗帧 = $御三家候选归一帧 - $消耗帧实际执行修正量" in selection
    assert "IF $本轮候选命中计数 == 1\n        $本轮真值解 = 1" in selection
    diagnostics = function(text, "御三家刷新候选距离")
    assert "共同区收集(" not in diagnostics and "投票投候选(" not in diagnostics
    calibration = function(text, "执行自动校准与等待更新")
    assert "IF $本轮剩余帧校准允许 == 1\n            $剩余帧本轮可信 = 1" in calibration

for name in re.findall(r"(?m)^FUNC (御三家\w+)", texts[0]):
    assert function(texts[0], name) == function(texts[1], name), name
formal = function(texts[0], "执行RNG启动与目标获取")
timeline = function(texts[1], "执行RNG启动与目标获取")
assert "$御三家菜单耗时MS = TIME() - $御三家菜单起始MS" in formal
assert formal.count("$遭遇地点, $御三家F2执行等待MS, $TV等待MS") == 2
assert "$御三家F2执行等待MS" not in timeline
assert "$F2时间轴截止" in timeline
lib = (ROOT / "lib/25_校准_投票决策.ecs").read_text(encoding="utf-8")
assert "IF $C_严格 == 0\n        CALL 共同区重置" in function(lib, "投票重置")
print("Starter checks passed: current paired batch first, ADV priority, ambiguity freezes, bounded window, measured formal menu; shared helpers match")
