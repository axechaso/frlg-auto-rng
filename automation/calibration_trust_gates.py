"""Install per-axis trust gates in the shared FRLG calibration controller."""

from __future__ import annotations


FUNCTION_SIGNATURE = "FUNC 执行自动校准与等待更新(): INT"
MARKER = "# GUI 2.0 校准可信门控：不可信维度只观察，不写窗、不下发修正"
_FRAME_HOLD_ADV_ONLY = (
    "IF $消耗帧本轮可信 == 1 and $本轮消耗帧误差 == 0"
)
_FRAME_HOLD_JOINT_HIT = (
    "IF $消耗帧本轮可信 == 1 and $命中差索引 == 0 and $本轮消耗帧误差 == 0"
)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"自动校准函数缺少唯一的{label}，实际为 {count} 处")
    return text.replace(old, new, 1)


def _function_block(text: str) -> tuple[int, int, str]:
    if text.count(FUNCTION_SIGNATURE) != 1:
        raise ValueError("主脚本缺少唯一的自动校准函数")
    start = text.index(FUNCTION_SIGNATURE)
    end = text.index("ENDFUNC", start) + len("ENDFUNC")
    return start, end, text[start:end]


def _require_joint_frame_hold_hit(block: str) -> str:
    """Start frame hold only after one trusted round hits both target axes."""
    adv_only_count = block.count(_FRAME_HOLD_ADV_ONLY)
    joint_count = block.count(_FRAME_HOLD_JOINT_HIT)
    if adv_only_count == 1 and joint_count == 0:
        return block.replace(_FRAME_HOLD_ADV_ONLY, _FRAME_HOLD_JOINT_HIT, 1)
    if adv_only_count == 0 and joint_count == 1:
        return block
    if adv_only_count == 0 and joint_count == 0:
        return block
    raise ValueError(
        "自动校准函数的帧命中保持条件不唯一："
        f"ADV单轴={adv_only_count}，Seed+ADV双轴={joint_count}"
    )


def apply_calibration_trust_gates_text(template_text: str) -> str:
    """Freeze only an untrusted axis while keeping diagnostics and evidence scans.

    Candidate histograms and strict common-region evidence intentionally continue
    to collect every reverse-lookup candidate.  Only the selected-hit path windows,
    controller state and outgoing correction are gated here.
    """

    if FUNCTION_SIGNATURE not in template_text:
        return template_text
    start, end, block = _function_block(template_text)
    joint_block = _require_joint_frame_hold_hit(block)
    if joint_block != block:
        template_text = template_text[:start] + joint_block + template_text[end:]
        start, end, block = _function_block(template_text)
    if MARKER in block:
        configured = template_text
        replacements = {
            "Seed命中偏离路径可信窗，本轮表内命中会显示ｘ(修正仍下发)":
                "Seed命中偏离路径可信窗：Seed轴只观察，不写窗、不下发修正",
            "消耗帧至少一轴偏离路径可信窗，本轮表内命中会显示ｘ(修正仍下发)":
                "消耗帧至少一轴偏离路径可信窗：不可信帧轴只观察，不写窗、不下发修正",
            "Seed与消耗帧均偏离路径可信窗，本轮表内命中会显示ｘ(修正仍下发)":
                "Seed与消耗帧均偏离路径可信窗：各不可信轴只观察，不写窗、不下发修正",
        }
        for old, new in replacements.items():
            if old in configured:
                configured = _replace_once(configured, old, new, "校准决策日志")
            elif configured.count(new) != 1:
                raise ValueError("主脚本的校准决策日志不完整")
        return configured

    block = block.replace(
        FUNCTION_SIGNATURE,
        FUNCTION_SIGNATURE + "\n    " + MARKER,
        1,
    )

    old_samples = """\
    # 非目标Seed的±1剩余帧不喂相位簇；绝对偏差大于1和目标Seed照常。TV圈样本、Seed样本始终写入。
    IF $本轮剩余帧校准允许 == 1
        $投票忽略 = 投票设置帧窗($本轮消耗帧误差, $消耗帧实际执行修正量, $进入TV)
    ENDIF
    $投票忽略 = 投票设置Seed窗($命中差索引, $Seed累计修正索引)
    IF $Seed校准方案 == 0
        $投票忽略 = 投票设置Seed校准样本($命中差索引, $Seed累计修正索引)
    ENDIF
    $投票忽略 = 投票设置TV帧窗($本轮消耗帧误差, $消耗帧实际执行修正量, $进入TV)
"""
    new_samples = """\
    # 候选全集仍进入诊断票表/共同区；最终命中只在对应轴可信时写入路径窗和控制样本。
    IF $本轮剩余帧校准允许 == 1 and $剩余帧本轮可信 == 1
        $投票忽略 = 投票设置帧窗($本轮消耗帧误差, $消耗帧实际执行修正量, $进入TV)
    ENDIF
    IF $Seed本轮可信 == 1
        $投票忽略 = 投票设置Seed窗($命中差索引, $Seed累计修正索引)
        IF $Seed校准方案 == 0
            $投票忽略 = 投票设置Seed校准样本($命中差索引, $Seed累计修正索引)
        ENDIF
    ENDIF
    IF $TV帧本轮可信 == 1
        $投票忽略 = 投票设置TV帧窗($本轮消耗帧误差, $消耗帧实际执行修正量, $进入TV)
    ENDIF
"""
    block = _replace_once(block, old_samples, new_samples, "可信路径窗写入段")

    old_seed = """\
    IF $Seed校准方案 == 0
        $Seed本次修正索引 = 计算Seed原始众数修正()
    ELSE
        $Seed本次修正索引 = 计算Seed锁定众数修正()
        IF $Seed锁定启用 == 1
            $Seed簇内 = 1
        ELSE
            $Seed簇内 = 0
        ENDIF
    ENDIF
"""
    new_seed = """\
    IF $Seed本轮可信 == 0
        # 冻结本轴：不调用控制器，避免不可信候选消耗窗口、余数或命中保持状态。
        $Seed簇内 = 0
        $Seed本次修正索引 = 0
        $Seed本次修正原始 = 0
        $Seed本次修正限幅 = 0
        $Seed精细本轮更新 = 0
        $Seed精细本轮新增MS = 0
        $Seed锁定本轮新启用 = 0
        $Seed锁定本轮触发 = 0
        $Seed锁定本轮样本计入 = 0
        $Seed命中保持本轮刷新 = 0
        $Seed命中保持触发固定半步 = 0
        $Seed直接修正触发 = 0
        $Seed立即夹逼触发 = 0
        $Seed修正模式文本 = "本轮Seed不可信，只观察，不写窗、不修正"
    ELIF $Seed校准方案 == 0
        $Seed本次修正索引 = 计算Seed原始众数修正()
    ELSE
        $Seed本次修正索引 = 计算Seed锁定众数修正()
        IF $Seed锁定启用 == 1
            $Seed簇内 = 1
        ELSE
            $Seed簇内 = 0
        ENDIF
    ENDIF
"""
    block = _replace_once(block, old_seed, new_seed, "Seed控制器调用段")

    old_dual_branch = """\
        # 只用目标Seed建立双分支证据；非目标Seed不能单独把随机VBlank路径认成稳定双分支。
        IF $命中差索引 == 0
"""
    new_dual_branch = """\
        # 只用目标Seed且TV帧轴可信的观测建立双分支证据。
        IF $命中差索引 == 0 and $TV帧本轮可信 == 1
"""
    block = _replace_once(block, old_dual_branch, new_dual_branch, "TV双分支证据门控")

    block = _replace_once(
        block,
        """\
        $TV帧慢修正触发 = 0
        IF $TV帧慢修正参数有效 == 0 or""",
        """\
        $TV帧慢修正触发 = 0
        $TV帧慢修正当前票数 = 0
        IF $TV帧慢修正参数有效 == 0 or""",
        "TV慢修正本轮状态清零",
    )
    block = _replace_once(
        block,
        """\
            $TV帧慢修正当前票数 = 0
        ELSE
            $TV帧慢修正窗口[$TV帧慢修正窗口指针] = $圈误差""",
        """\
            $TV帧慢修正当前票数 = 0
        ELIF $TV帧本轮可信 == 1
            $TV帧慢修正窗口[$TV帧慢修正窗口指针] = $圈误差""",
        "TV慢修正样本门控",
    )

    old_tv_control = """\
        IF $TV双分支锁定 == 1 and $TV双分支跟踪等待帧 == $TV等待帧 and $圈误差绝对 <= 1 and $消耗帧归一化绝对 <= $TV双分支相位阈值
"""
    new_tv_control = """\
        IF $TV帧本轮可信 == 0
            $TV帧簇内 = 0
            $TV帧本次修正 = 0
        ELIF $TV双分支锁定 == 1 and $TV双分支跟踪等待帧 == $TV等待帧 and $圈误差绝对 <= 1 and $消耗帧归一化绝对 <= $TV双分支相位阈值
"""
    block = _replace_once(block, old_tv_control, new_tv_control, "TV帧控制门控")

    old_remainder_sample = """\
    # 剩余帧窗口只接收目标Seed；非目标Seed的VBlank相位不参与持续偏差判断。
    IF $命中差索引 == 0
"""
    new_remainder_sample = """\
    # 剩余帧窗口只接收目标Seed且本轴可信的观测。
    IF $命中差索引 == 0 and $剩余帧本轮可信 == 1
"""
    block = _replace_once(
        block,
        old_remainder_sample,
        new_remainder_sample,
        "剩余帧慢修正样本门控",
    )

    block = _replace_once(
        block,
        """\
    IF $剩余帧慢修正触发 == 1
        $剩余帧簇内 = 1""",
        """\
    IF $剩余帧本轮可信 == 0
        $剩余帧簇内 = 0
        $本次相位修正 = 0
    ELIF $剩余帧慢修正触发 == 1
        $剩余帧簇内 = 1""",
        "剩余帧控制门控",
    )

    block = _replace_once(
        block,
        """\
    IF $Seed校准方案 == 0
        IF $Seed差绝对 <= 1""",
        """\
    IF $Seed校准方案 == 0
        IF $Seed本轮可信 == 1 and $Seed差绝对 <= 1""",
        "Seed方案0收敛门控",
    )
    block = _replace_once(
        block,
        "IF $Seed锁定启用 == 1 and $Seed命中保持启用 == 1",
        "IF $Seed本轮可信 == 1 and $Seed锁定启用 == 1 and $Seed命中保持启用 == 1",
        "Seed锁定方案收敛门控",
    )
    block = _replace_once(
        block,
        "IF $本轮剩余帧校准允许 == 1 and $消耗帧真绝对 <= $直接选择接近阈值",
        "IF $消耗帧本轮可信 == 1 and $本轮剩余帧校准允许 == 1 and $消耗帧真绝对 <= $直接选择接近阈值",
        "消耗帧收敛门控",
    )

    for legacy_comment in (
        "# 锁定方案精确命中后进入5次参数保持，视为Seed轴已收敛。",
        "# 实验方案精确命中后进入10次参数保持，视为Seed轴已收敛。",
    ):
        block = block.replace(
            legacy_comment,
            "# 锁定方案精确命中后进入5次参数保持，视为Seed轴已收敛。",
        )

    configured = template_text[:start] + block + template_text[end:]
    replacements = {
        "Seed命中偏离路径可信窗，本轮表内命中会显示ｘ(修正仍下发)":
            "Seed命中偏离路径可信窗：Seed轴只观察，不写窗、不下发修正",
        "消耗帧至少一轴偏离路径可信窗，本轮表内命中会显示ｘ(修正仍下发)":
            "消耗帧至少一轴偏离路径可信窗：不可信帧轴只观察，不写窗、不下发修正",
        "Seed与消耗帧均偏离路径可信窗，本轮表内命中会显示ｘ(修正仍下发)":
            "Seed与消耗帧均偏离路径可信窗：各不可信轴只观察，不写窗、不下发修正",
    }
    for old, new in replacements.items():
        configured = _replace_once(configured, old, new, "校准决策日志")

    return configured
