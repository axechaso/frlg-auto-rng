"""Present reports produced by the unchanged RNG services."""
import re


def sid_report_summary(report):
    unique = re.search(r"结果: PSV已经唯一: (\d+)", report)
    count = re.search(r"结果: 仍有(\d+)个共同PSV", report)
    selected = re.search(r"最终SID（窗口内最早ADV）: (\d{5})；ADV: (\d+)", report)
    if unique:
        return ("候选 SID " + selected[1] if selected else "PSV 已唯一", "SID 反查报告", (unique[1], 8, selected[2] if selected else "—"),
            "8 个 SID 满足闪光公式；采用值按原有建档链窗口内的最早 ADV 选取。")
    if count:
        return ("还需补充观测", "多个 PSV 候选", (count[1], "—", "—"), "继续加入其他闪光宝可梦，缩小候选交集。")
    return ("未确定 SID", "请查看反查报告", (0 if "没有共同PSV" in report else "—", "—", "—"), "核对 OCR、努力值和来源；没有生成可采用的 SID。")


def traversal_report_summary(report):
    status = report.get("status")
    if status == "completed" and type(report.get("sid")) is int and type(report.get("sid_advance")) is int:
        return (f"确认 SID {report['sid']:05d}", "运行器已记录出闪", (f"{report['sid']:05d}", report["sid_advance"], "—"), "完整运行记录和候选过程保存在报告中。")
    state = report.get("state", {})
    return ("已到遍历上限" if status == "exhausted" else "遍历已暂停", "未确认命中 SID",
        ("—", state.get("current_sid_advance") or state.get("next_sid_advance", "—"), "—"), "同参数下次继续；仅明确未出闪才会推进到下一候选。")
