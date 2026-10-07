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
    possible_causes: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        causes = "\n".join(f"• {cause}" for cause in self.possible_causes)
        if not causes:
            causes = "仅凭当前信息还不能确定原因，需要结合原始错误与日志核对。"
        return f"{self.summary}\n\n可能原因（需核对）：\n{causes}\n\n建议排查：\n{self.action}"


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
            ("采集画面为空、暂时不可用，或采集卡被占用。", "标签范围超出了本次实际画面边界。"),
        )
    if re.search(r"invalid literal for int\(\) with base \d+:", text):
        empty = re.search(r"invalid literal for int\(\) with base \d+:\s*(['\"])\1", text)
        return ErrorExplanation(
            "integer_value",
            "读取整数失败：遇到了空值。" if empty else "读取整数失败：遇到了非整数内容。",
            "这条原始错误没有提供字段名，无法确定具体哪一项；请检查本次操作的数字输入或载入的配置。",
            ("数字输入未填写，或配置中存在非整数内容。",),
        )
    return None


def _issue(key, summary, causes, *actions):
    return ErrorExplanation(key, summary, "\n".join(f"{i}. {step}" for i, step in enumerate(actions, 1)), causes)


def explain_popup_error(text: str, *, context: str = "") -> ErrorExplanation:
    """Advice for an actual error popup, never a detector of normal log lines.

    More specific errors take precedence over generic words in their outer
    message. All diagnoses are read-only hypotheses; no paths, thresholds,
    credentials, settings or retry policy are changed here.
    """
    known = explain_error(text)
    if known is not None:
        return known
    lower = text.casefold()
    subject = (context + "\n" + text).casefold()

    def has(*markers):
        return any(marker.casefold() in lower for marker in markers)

    if has("CERTIFICATE_VERIFY_FAILED", "certificate verify failed", "unable to get local issuer certificate"):
        return _issue("network_certificate", "网络连接未通过证书验证。",
            ("系统日期/时间异常，或所需证书链不可用。", "代理、网络安全软件或网络环境改变了 HTTPS 证书链。"),
            "先核对系统日期和时间，再检查代理及网络证书设置。",
            "可换网络重试；更新失败时也可手动选择另一更新源。",
            "不要关闭证书验证。仍失败时保留原始错误、工具版本及所选更新源。")
    if has("DLL load failed", "WinError 127") or ("importerror" in lower and has("找不到指定的程序")):
        return _issue("runtime_dll", "程序运行组件未能加载。",
            ("完整包未解压，或新旧包中的 DLL 混在了一起。", "运行组件缺失、架构不一致，或受到系统软件影响。"),
            "把完整绿色版解压到新的独立目录，再启动；不要只复制 EXE 或混用旧 DLL。",
            "检查安全软件是否有隔离记录；只在确认文件来源后处理。",
            "若仍失败，把完整错误和系统/工具版本提供给开发者。")
    if has("采集卡编号或名称已改变", "设备编号或名称已变化", "采集设备已变化", "采集卡与生成时不一致"):
        return _issue("device_changed", "当前设备与生成计划时的设备不一致。",
            ("重新插拔或切换设备后，采集卡序号/名称发生了变化。",),
            "先停止当前任务，点击“重新检测”，按设备名称确认串口和采集卡。",
            "重新生成方案并通过预检，再运行；原计划不能直接复用。")
    capture_line = re.search(r"(?im)^(?=[^\r\n]*(?:采集卡|采集设备|camera))(?=[^\r\n]*(?:打开失败|连接失败|被占用|cannot open|not found))[^\r\n]*$", text)
    if capture_line or has("capture unavailable", "capture failed", "采集画面不可用"):
        return _issue("capture_connection", "视频采集设备没有成功提供画面。",
            ("选错设备或序号变化，或设备正在被其他程序占用。", "USB连接、驱动或采集输出尚未就绪。"),
            "停止当前任务并重新检测，按名称选择采集卡。",
            "关闭其他占用同一设备的程序，再在“监视窗口”确认画面正常。",
            "画面恢复后再生成/运行；此类连接错误不能靠降低标签阈值修复。")
    if re.search(r"(?im)^(?=[^\r\n]*(?:串口|单片机|\bcom\d+\b|serial))(?=[^\r\n]*(?:未检测到|连接失败|打开失败|could not open|cannot open|access|拒绝访问|not found|占用|timeout|超时))[^\r\n]*$", text):
        return _issue("serial_connection", "单片机串口连接未完成。",
            ("串口选错/已变化，或被另一个伊机控、手柄窗口或串口程序占用。", "USB连接或单片机握手暂时失败。"),
            "停止任务，关闭其他使用同一串口的程序，再点击“重新检测”选择正确串口。",
            "核对USB连接及单片机状态；重连后先确认连接，再重新生成/运行。",
            "一次超时不能证明设备损坏，需结合具体握手/端口日志判断。")
    if has("No space left on device", "disk full", "磁盘空间不足", "磁盘已满", "WinError 112"):
        return _issue("disk_space", "保存或下载时可用磁盘空间不足。",
            ("程序/临时目录或用户数据目录所在磁盘剩余空间不足。",),
            "检查报错路径所在磁盘及临时目录的剩余空间；更新解压需要额外空间。",
            "整理自己确认不再需要的文件后重试，保留配置、存档资料与日志。")
    if has("相邻页面") and has("误识别", "触发"):
        return _issue("label_false_positive", "这个标签也会在不应命中的页面触发。",
            ("模板或搜索范围包含两个页面共有的内容，没有充分区分页面。",),
            "重新圈选能区分页面的模板/范围，先通过同图与3张新帧测试。",
            "再用相邻页面检查误识别，验证通过后才应用；不能靠降低门槛解决。")
    if has("现场尚未确认", "截图确实是预期页面", "先通过同图", "尚未完成验证"):
        return _issue("label_verification_pending", "标签应用前的现场确认或验证尚未完成。",
            ("还没有确认截图是正确页面，或同图/新帧测试尚未通过。",),
            "先确认现场页面，再完成同图和3张新帧动态测试；能提供相邻页面时也检查误识别。",
            "保持未通过验证的标签为草稿，不强行应用。")
    if has("没有当次实际加载的标签备份"):
        return _issue("label_evidence_missing", "缺少这次运行实际加载的标签，暂时不能直接修复。",
            ("故障资料没有保存到当次标签，或对应备份已移动/清理。",),
            "保留故障截图和日志，核对这次运行工程的 ImgLabel 与所选设备覆盖。",
            "补充对应标签后再修复；不要用其他版本的同名标签代替当次证据。")
    if has("PermissionError", "Permission denied", "Access is denied", "拒绝访问", "read-only", "WinError 5", "WinError 32", "被占用"):
        update = "更新" in subject or "update" in subject
        return _issue("file_access", "文件/目录暂时无法访问或写入。",
            ("相关文件仍被程序、资源管理器或其他软件占用。", "目录只读、权限不足或被安全软件拦截。"),
            ("更新时先关闭绿色版程序目录的资源管理器窗口，并退出相关伊机控/监视程序。" if update
             else "检查原始错误中的文件路径，关闭正在使用该文件的窗口或程序。"),
            "确认该目录允许当前用户写入，并查看安全软件记录；不要直接删除配置或关闭安全保护。",
            "问题解除后重试；仍失败时保留错误路径和完整错误。")
    if ("标签" in subject or ".il" in subject) and has("数量", "应为", "应有", "sha256", "指纹", "JSON", "损坏", "缺少", "missing label"):
        return _issue("label_package", "标签包或标签文件未通过检查。",
            ("指向旧标签目录、历史TID子集，或包没有完整解压。", "脚本与标签版本不一致，或文件结构/内容不完整。"),
            "核对原始错误中的目录、标签名和数量，选择当前完整脚本包的 ImgLabel。",
            "重新导入完整同版本脚本包；自己的设备标签通过“设备标签诊断与覆盖”导入。",
            "不要用降低匹配阈值来绕过缺文件、结构或版本检查。")
    if has("模板字段", "模板锚点", "anchor", "应出现", "缺少所选入口", "脚本包缺少所选入口"):
        return _issue("template_version", "工具无法按当前脚本模板生成方案。",
            ("脚本更新后的字段/代码位置与当前工具不一致。", "主脚本、lib或选中的正式版/时间轴入口不是同一套版本。"),
            "核对所选脚本包路径和入口，导入完整同版本脚本包。",
            "确认工具也已更新后重新生成；仍报错时提供具体缺少的字段/锚点及脚本版本。")
    if has("指纹", "SHA-256", "SHA256", "checksum", "校验失败", "摘要不一致"):
        return _issue("integrity", "文件内容与预期版本或校验记录不一致。",
            ("文件被修改，或下载/解压/复制不完整。", "当前工具、脚本或设备覆盖不是生成/预检时的版本。"),
            "核对具体文件及来源；下载包可重新下载并完整解压，自己修改的文件需先确认改动。",
            "重新生成并预检；高级模式仍按现有指纹警告策略处理，不由此弹窗自动放宽。")
    if has("预检后文件已改变", "预检后文件已变化", "生成期间发生变化", "请先生成并通过预检", "请先通过预检"):
        return _issue("plan_preflight", "当前计划尚未通过预检，或生成内容已经改变。",
            ("尚未生成有效计划，或在生成后修改了参数、脚本、标签或设备。",),
            "按当前条件重新生成方案，查看并解决“预检未通过”中的具体项目。",
            "预检通过后再开始运行，不继续使用旧运行工程。")
    if has("No such file or directory", "FileNotFoundError", "系统找不到指定的文件", "路径不存在", "日志已经不存在", "缺少独立更新器", "请选择存在的", "不存在的目录"):
        return _issue("path_missing", "当前设置指向的文件或目录不存在。",
            ("程序/脚本包移动后仍保存着旧路径，或文件没有完整解压。", "所选日志或运行文件已移动、清理或删除。"),
            "对照原始错误中的路径，重新选择现有的脚本包、ezcon.exe或日志文件。",
            "绿色版需完整解压；不要只搬动EXE。脚本路径改变后重新生成方案。")
    if has("HTTP Error 401", "HTTP Error 403", "HTTP Error 429", "HTTP Error 404"):
        return _issue("network_http", "远端服务没有提供所请求的更新资源。",
            ("资源不存在、请求受限、服务端限流，或所选源有访问策略限制。",),
            "查看原始HTTP状态码，核对所选更新源与资源地址，稍后重试或手动换源。",
            "仅凭一次请求失败不能判断登录凭据失效；保留完整错误，不必因此重装工具。")
    network_subject = any(word in subject for word in ("更新", "网络", "http", "urlopen", "getaddrinfo", "dns", "urllib"))
    if network_subject and has("timed out", "timeout", "连接超时", "urlopen error", "connection refused", "getaddrinfo", "无法连接", "connection reset", "remote end closed"):
        return _issue("network_connection", "网络请求未能完成。",
            ("网络、代理或DNS暂时不可用，或远端服务响应较慢。",),
            "检查网络和代理设置后重试；更新问题可在设置中手动选择另一更新源。",
            "保留完整错误及所选源；一次超时不代表账号凭据已失效。")
    if has("Seed 表", "Seed表", "seed table") and has("缺少", "不存在", "未加载", "找不到文件"):
        return _issue("seed_table_missing", "当前游戏所需的 Seed 表不可用。",
            ("Seed表缺失、不完整，或当前游戏/语言没有对应数据。",),
            "核对游戏、机型和ROM语言，再使用“检查/更新 Seed 表”。",
            "确认所需模式列有数据后重新生成；不要借用其他语言或模式的表。")
    if has("所有可用 Seed 模式中均不可达", "没有初始 Seed 方案", "No reachable initial seed") or re.search(r"不在[^\r\n]*(?:Seed\s*表|种子表)", text, re.I):
        return _issue("seed_unreachable", "没有找到符合当前范围和设置的初始 Seed 方案。",
            ("当前帧范围/固定Seed模式排除了可达方案。", "该Seed不在所选游戏、机型或模式的有效表中。"),
            "核对游戏、ROM语言、机型和Seed；允许时使用自动Seed模式。",
            "检查最小/最大Advance与Seed表状态，按需求调整后重新搜索。")
    if has("没有找到满足", "没有符合", "无符合") and has("结果", "闪帧", "条件"):
        return _issue("search_no_result", "当前筛选没有找到符合条件的结果。",
            ("个体值、性格、闪光等条件的组合较严格，或搜索范围不足。", "目标、游戏/语言或身份信息可能选填不符。"),
            "先核对目标、游戏、TID/SID和地点，再按需求放宽筛选或增大最大Advance。",
            "保留必须满足的条件，修改后重新搜索；无结果本身不是设备故障。")
    if "home_buffer" in lower and has("失败", "超时", "未找到", "边界", "error", "failed", "timeout"):
        return _issue("home_buffer", "HOME_BUFFER 启动阶段没有通过判定。",
            ("实际页面/主机状态与预期不同，或退出/启动动作尚未稳定。", "设备显示差异造成相关标签分数未过门槛。"),
            "查看“监视窗口”和本轮日志，核对NS机型、主页状态及正在匹配的标签。",
            "画面正确且已稳定仍重复低分时，按引导检查低分自适应或制作同名设备标签覆盖。",
            "不要仅凭最高分认定命中；保留HOME_BUFFER分数、阈值和本轮延迟日志。")
    if has("反查") and has("无候选", "无法找到", "没有候选", "无法继续", "失败", "不唯一"):
        return _issue("reverse_search", "反查没有得到可用于继续流程的结果。",
            ("读取的等级、能力、性格、努力值或来源/地点与实际个体不一致。", "候选不唯一，或当前Seed/帧反查窗口未覆盖实际结果。"),
            "先对照截图核对识别到的等级、六项能力、性格及实际EV/来源，不要把未知EV当0。",
            "查看完整候选与反查范围日志；确认数据正确后再按对应流程检查扩窗设置。",
            "保留游戏现场和完整日志，不根据单条失败盲目修改Seed或SID。")
    if has("识图失败", "识别失败", "识图等待", "标签匹配", "匹配度不足", "最高匹配度", "匹配度未达"):
        return _issue("recognition", "当前画面没有通过该阶段的识别要求。",
            ("页面尚未到达预期位置，或采样发生在页面过渡时。", "语言、分辨率、标签来源或设备画面与模板不一致。"),
            "先对照当前画面与日志中的阶段/标签，确认处于正确页面且画面稳定。",
            "再核对ROM语言、采集分辨率和本次实际标签；可从设备标签卡片查看截图并修复同名标签。",
            "仅凭最高分或某个OR候选低分不能断定标签损坏，不自动降低门槛。")
    if has("JSONDecodeError", "Expecting value", "Expecting property name", "配置格式", "配置文件损坏"):
        return _issue("config_format", "载入的数据文件不是有效的当前配置。",
            ("选错文件、格式不一致，或文件被截断/手动编辑后损坏。",),
            "核对文件来源和类型，使用工具导出的对应配置或完好的备份。",
            "先保留原文件，不直接删除用户资料；仍失败时提供具体文件名和错误。")
    if has("仅支持搜索", "只支持搜索", "暂不支持", "当前只支持", "无法自动运行", "路线未开放"):
        return _issue("route_unsupported", "当前选择超出了这个流程已开放的范围。",
            ("目标、玩法或ROM语言没有对应的自动操作路线。",),
            "对照当前页引导和预检说明，选择受支持的类型/目标/语言。",
            "只有搜索计划的路线不能通过降低识图阈值或开启高级模式变成可执行路线。")
    if has("请检查输入", "请填写", "请先确认", "请确认", "请先停止", "仍在运行", "先等待", "不能为空", "为空", "必须", "不在当前地点列表", "地点：", "改为整数", "键位重复", "同一个", "Unknown species", "Unknown ability"):
        running = has("请先停止", "仍在运行", "先等待")
        return _issue("input_or_precondition", "输入或操作前置条件未通过检查。",
            (("当前任务尚未完成，需要先等待或停止。",) if running else ("必填项、数值范围、选项组合或前置确认尚未满足。",)),
            ("先处理当前任务，再重试本操作。" if running else "按上方原始错误点名的字段/条件修改；完整名称需从匹配列表选择，数字不含单位或小数点。"),
            "核对本页引导中的前置准备，保留不需要修改的参数。")
    if has("运行进程无法启动", "独立更新器启动失败", "FailedToStart"):
        return _issue("process_start", "后台运行程序未能启动。",
            ("运行器路径失效、完整包缺失，或文件被系统/安全软件阻止。",),
            "核对原始错误中的程序路径与完整包，检查系统/安全软件记录。",
            "保留具体启动错误和工具版本；此时不要把失败当成游戏识图问题。")
    return _issue("unknown", "本次操作未完成，当前信息不足以确定原因。", (),
        "展开详细信息查看完整原始错误；运行问题还可到“历史日志”查看本次完整日志。",
        "记录工具版本、所在页面、刚做的操作及报错截图，提供给开发者进一步定位。",
        "尚未查清前保留资料与现场，不先删除配置、改标签门槛或重置参数。")


def brief_error(text: str, *, limit: int = 500) -> str:
    """Bound only the visible excerpt; callers keep the original unchanged."""
    lines = text.splitlines()
    chosen = lines[-3:] if lines and lines[0].startswith("Traceback") else lines[:3]
    excerpt = "\n".join(chosen)
    shortened = len(lines) > 3 or len(excerpt) > limit
    return excerpt[:limit] + ("\n…完整原始错误见详细信息或完整日志。" if shortened else "")
