"""Operator-facing explanations; retain the original exception separately."""
from dataclasses import dataclass
import re


def parse_integer(text: str, label: str) -> int:
    value = text.strip()
    if not value:
        raise ValueError(f"“{label}”为空，请填写整数。")
    try:
        return int(value)
    except ValueError:
        shown = value if len(value) <= 40 else value[:40] + "…"
        raise ValueError(f"“{label}”填写了“{shown}”，请改为整数（不含小数点）。") from None


@dataclass(frozen=True)
class ErrorExplanation:
    key: str
    summary: str
    action: str

    @property
    def message(self) -> str:
        return f"{self.summary}\n\n{self.action}"


def explain_error(text: str) -> ErrorExplanation | None:
    compact = re.sub(r"\s+", "", text)
    # Match the actual OpenCV rectangle assertion, not ordinary low scores or
    # a generic search failure. The assertion does not report frame dimensions.
    if any(
        f"0<=roi.{axis}" in compact and f"roi.{axis}+roi.{size}<=m.{bound}" in compact
        for axis, size, bound in (("x", "width", "cols"), ("y", "height", "rows"))
    ):
        match = re.search(r"搜图标签\s*\[([^\]\r\n]+)\]", text)
        label = match[1] if match else ""
        subject = f"（标签：{label}）" if label else ""
        return ErrorExplanation(
            "capture_roi:" + label,
            f"采集画面不可用或识图范围不匹配{subject}。",
            "1. 优先检查采集卡是否被其他程序占用，关闭占用程序。\n"
            "   在“监视窗口”重新连接，确认采集卡选对、画面正常。\n"
            "2. 画面正常仍报错时，核对采集分辨率与标签识图范围。\n"
            "采集卡占用、画面无效和标签越界都可能触发此错误。\n"
            "仅凭此错误无法区分根因；调整识图阈值不能修复。",
        )
    if re.search(r"invalid literal for int\(\) with base \d+:", text):
        empty = re.search(r"invalid literal for int\(\) with base \d+:\s*(['\"])\1", text)
        return ErrorExplanation(
            "integer_value",
            "读取整数失败：遇到了空值。" if empty else "读取整数失败：遇到了非整数内容。",
            "这条原始错误没有提供字段名，无法确定具体哪一项；请检查本次操作的数字输入或载入的配置。",
        )
    return None
