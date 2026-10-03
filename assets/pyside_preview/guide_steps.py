"""Offline FRLG tutorials. IDs and anchors are independent of display text."""
from dataclasses import dataclass

GUIDE_VERSION = 1


@dataclass(frozen=True)
class GuideStep:
    step_id: str
    title: str
    body: str
    anchor_id: str
    visible_when: str = ""
    completion_check: str = ""
    risk_note: str = ""


def steps(*rows):
    return tuple(GuideStep(*row) for row in rows)


GUIDES = {
    "sid": steps(
        ("identity", "存档、语言与设备", "先点击存档信息核对当前 TID、ROM 语言和主机，再在共通设置选择串口及采集卡。", "profile_chip"),
        ("count", "实际队内闪光数量", "填写可用于反查的闪光个体数量。未使用的个体列会禁用，不需要补填。", "sid_count"),
        ("individuals", "名称、等级与六项 EV", "按实际个体填写名称、等级、来源与 EV；EV 会影响属性反查，不能把未知 EV 当作零。", "sid_party"),
        ("position", "游戏内准备", "核对页面说明与游戏站位、糖果和队伍顺序。由你勾选准备确认；引导不会向主机发键。", "sid_ack"),
        ("read", "生成与读取", "点击原功能的生成及开始按钮。读取属性、计算候选和最终确认 SID 是三个不同阶段。", "search_button", "", "devices"),
        ("result", "候选与最终确认", "到运行日志查看反查报告，再核对候选与最终确认结果；普通成功文本不构成最终命中证据。", "result_panel")),
    "tid": steps(
        ("rom", "游戏、主机与 ROM 语言", "核对火红/叶绿、Switch 机型与英文/日文；切换语言后重新核对取名及校准参数。", "tid_language"),
        ("mode", "穷举或乱数", "选择运行模式并检查目标、范围及固定延迟。穷举进度与目标乱数的验证结果分开记录。", "tid_mode", "", "", "流程会新建存档，请先保留需要的旧存档。"),
        ("timing", "范围与延迟", "毫秒延迟是实际时间。消耗帧是 RNG advance，按 120 advance/s 解释；不能用 60 Hz 画面刷新直接代换。", "tid_op_correction"),
        ("continuation", "御三家接续与 6V", "御三家接续、去噪和 6V 选项各有前提，核对实际启用条件；未开放路线不会由引导启用。", "tid_flow_check"),
        ("resume", "查看进度与续跑", "保留同目标的断点，从原功能入口续跑；不要把旧观测值当作新配置的命中证明。", "tid_progress_card"),
        ("verify", "开始、验证与保存", "由你点击开始。确认 SID 后，创建并保存存档仍是独立步骤，需要核对报告再保存。", "start_button", "", "devices")),
    "tid_records": steps(
        ("source", "实测记录来源", "这里汇总运行中的实际观测。按游戏、语言和机型区分，观测值不等于已验证命中参数。", "records_table"),
        ("columns", "列与归一化参数", "查看 Seed、TID、OP/F1/F2 与出现次数；归一化及修正条件不同的记录不要直接混用。", "records_table"),
        ("selection", "选择记录", "点击一行查看已有详情。仅使用界面实际提供的回填操作，先核对目标和设备。", "records_table"),
        ("export", "导出与日志关联", "从原导出 CSV 按钮保存筛选记录；在历史日志中按流程和路径查找当次上下文。", "records_table")),
    "wild": steps(
        ("target", "存档、类别与目标", "核对当前身份，再选择野生或静态、遭遇方式、地点和宝可梦。游走与道具分支保留各自操作顺序。", "wild_method"),
        ("conditions", "个体与筛选条件", "填写六项个体和闪光、性格等条件。没有结果时由你调整条件，工具不会自动放宽。", "wild_shiny"),
        ("advance", "Advance 与指定 Seed", "最大 Advance 限制搜索范围；指定 Seed/帧数模式要求目标参数完整。Advance 按 120/s 解释。", "wild_search_mode"),
        ("reachable", "自动可达模式", "核对 Seed 模式和脚本路线的可达条件，运行前准备以方案中的实际要求为准。", "wild_seed_mode"),
        ("traversal", "可选 SID 遍历", "启用后按同目标遍历 SID。支持范围以当前可用性说明为准；Gift 路线限制不会自动解除。", "traversal_check", "traversal"),
        ("plan", "搜索结果与运行前要求", "生成方案后阅读右侧摘要及站位、队伍、背包要求。停止入口始终在窗口底部。", "overview", "", "plan")),
    "egg": steps(
        ("parents", "蛋种与亲本投放顺序", "先填蛋种，亲本 A/B 必须与实际投放顺序一致；准备队伍、站位与必要道具。", "egg_species"),
        ("compatibility", "亲本 IV、相性与语言", "填实际亲本 IV 与相性，核对 ROM 语言。支持路线以当前业务提示为准。", "egg_compatibility"),
        ("seed", "Seed、Held 与 Pickup", "同 Seed 的 Held 是生成 ADV，Pickup 是领取 ADV；按 120 advance/s 解释，不是画面帧。", "egg_seed"),
        ("start", "254 步准备入口", "完整准备会自动走 254 步并存档。只有实机已经完成同样准备时才选择准备完成入口；菜单奇偶固定为 1。", "egg_start"),
        ("save", "保存亲本与全部配置", "使用原保存配置入口保留亲本、目标与 Seed；重新加载后再核对投放顺序。", "egg_parent_widgets"),
        ("run", "运行与反查", "由你生成、开始，再在日志查看结果与反查；未开放 ROM 路线不会由引导伪装为可运行。", "start_button", "", "devices")),
    "script_test": steps(
        ("advanced", "高级模式边界", "此页须由你主动开启高级模式。自选 ECS 不保证具有阶段监督和按键回显。", "advanced_check"),
        ("file", "选择 ECS", "选择实际脚本文件。脚本可能包含设备操作，请先阅读内容及运行前要求。", "script_path"),
        ("backend", "后端与设备", "正式目标为 EasyCon 1.6.4-a；原始 CLI 用于 A/B 对照，不自动更换后端。", "script_backend"),
        ("preflight", "预检及风险确认", "先生成并查看预检。指纹警告与损坏结构是不同问题；原有确认仍需你处理。", "search_button", "", "plan"),
        ("stop", "运行、停止与日志", "由你开始测试；停止入口在窗口底部。观察状态代表发送状态，不保证游戏接受。", "stop_button")),
    "logs": steps(
        ("summary", "本次方案摘要", "核对本次目标、设备和预检。历史记录不会改变当前运行计划。", "overview"),
        ("output", "实时日志与输出", "查看本次实时输出与报告；阶段完成和最终乱数成功分别判断。", "log_view"),
        ("input", "脚本操作卡与虚拟手柄", "两处使用同一输入会话。显示的是运行器发送状态，不保证游戏接受；失联时不保留按住。", "script_action_card"),
        ("stop", "停止当前流程", "使用窗口底部停止按钮。Esc 可收起本教程；开始和停止任务仍由你操作。", "stop_button"),
        ("repair", "标签故障与完整日志", "故障入口保留截图、条件与设备资料。先确认页面正确，再进入修复；普通重试和低分候选不等于坏标签。", "label_incident_open")),
    "history_logs": steps(
        ("loading", "后台加载与缓存", "扫描、筛选和预览独立于当前运行。缓存 30 秒；手动刷新会重新扫描，不改变运行状态。", "history_status"),
        ("filter", "流程与关键词", "按流程或文件名/完整路径筛选；输入暂停后后台计算结果。", "history_search"),
        ("select", "选择日志", "选择一行查看尾部预览。文件删除后不会替你打开另一份日志。", "history_table"),
        ("preview", "有界预览", "默认最多读取 256 KiB / 3000 行；加载更多上限 1 MiB。截断只影响预览，原件保持不变。", "history_log_view"),
        ("open", "打开文件或目录", "需要完整内容时使用表格上方的打开按钮。历史记录与当前运行分开。", "history_table")),
    "profile": steps(
        ("choose", "选择与管理存档", "选择当前实际存档；运行中禁止切档。需要新建、复制、编辑时使用管理存档入口。", "profile_selector"),
        ("identity", "身份与 ROM", "核对 TID/SID、游戏、语言和主机。切档不会改 TID 目标草稿。", "profile_game"),
        ("gift", "神秘礼物", "按实际存档记录礼物状态。礼物档方案强制菜单奇偶 1；普通档恢复偏好，孵蛋始终固定 1。", "profile_mystery_gift"),
        ("persist", "保存与再核对", "业务数据由原功能保存；教程进度不代表存档已验证。", "profile_selector")),
    "common": steps(
        ("devices", "设备与连接", "在主窗口顶部选择真实串口及采集卡，重新检测后核对设备名称。阅读教程不会建立连接。", "common_device_hint", "", "devices"),
        ("paths", "脚本包与运行时", "选择所需脚本包与固定 EasyCon 1.6.4-a；预检通过再运行。", "source"),
        ("updates", "更新源与日志", "按网络情况选更新源，查看完整日志路径；只有你点击原按钮才检查或应用更新。", "update_source"),
        ("qq", "QQ 通知教程", "点击此入口打开已有 QQ 绑定教程；绑定和保存由你使用原功能完成。", "qq_guide_entry")),
    "advanced": steps(
        ("scope", "高级设置适用范围", "先确认当前流程。开启高级模式和改变参数均由你主动操作。", "advanced_scope"),
        ("windows", "三类扩窗", "按实际目标修改三类窗口范围；留空沿用脚本默认，不能把其他目标的命中结果硬编码补偿。", "advanced_scope"),
        ("parity", "菜单奇偶", "普通存档按偏好；神秘礼物档及孵蛋固定 1。切换后以生成方案的有效值为准。", "frame_parity"),
        ("review", "重新生成预检", "参数变化后旧方案失效，使用原按钮重新生成及预检，不自动启动。", "advanced_scope")),
    "label": steps(
        ("scene", "1 · 确认现场", "先确认截图是预期且稳定的页面、语言和分辨率一致。错误页面应先修启动位置或采集设置。", "scene_confirm", "", "scene"),
        ("label", "2 · 选择实际标签", "从故障候选选择当次加载的标签，缺原图/备份时先补采集或导入。不要把最高分直接当成正确结果。", "label_choice"),
        ("edit", "3 · 编辑或导入", "圈选模板与搜索范围，或逐项导入 IL。每个候选分别校验和测试；修改会使旧测试失效。", "canvas"),
        ("original", "4 · 原图验证", "点击搜索测试，使用固定 EasyCon 原生匹配；核对实际比较符、阈值和分数。", "same_button"),
        ("fresh", "5 · 三张新帧", "使用已有兼容预览通道获取三张不同序号的新帧，不另开采集卡。没有共享通道时先启动已有预览。", "fresh_button"),
        ("negative", "6 · 排除误匹配", "测试 HOME/退出/相邻页面等负样本。没有负样本时标为未验证。", "negative_button"),
        ("save", "7 · 保存当前设备", "核对设备和修改摘要后确认覆盖。保留上一版，不修改原始母本。", "apply_button"),
        ("retest", "8 · 同目标应用与复测", "同目标重建及预检后待你手动开始。退出码 0 不足以证明故障已修复，须核对原阶段或明确人工确认。", "manual_confirm_button")),
}
