# PySide6 功能页面映射

核对日期：2026-09-05。基线为 `7438e0e`；本轮开始时 HEAD 和 `pyside_preview.py` 均与该提交一致。正式行为逐项对照同提交的 `run_auto_rng_gui.py`，不以原型中的示例值推断功能。

已完整阅读目标仓库的 `HANDOFF.md`、`UI_TEXT.md`、`PYSIDE6_PREVIEW.md`。目标仓库没有 `docs/开发交接.md`，该文件实际位于 `C:\Users\axenx\Downloads\NS火叶全自动一键乱数1.1.8\docs\开发交接.md`，已按用户要求阅读。历史文档存在过时验收记录，本轮页面合同以当前 Tk 源码为准。

## 页面顺序与公共区域

| 顺序 / 区域 | Tk 来源（基线行号） | PySide6 去向 | 接入状态 |
| --- | --- | --- | --- |
| 1 SID 查找 | `_build_ui` 1538–1705 | `sid` | 表单与显隐交互；采集、反查、报告未接入 |
| 2 TID 乱数 | `_build_ui` 2066–2455 | `tid` | 七分区表单与模式交互；计划、检测、持久化、续跑未接入 |
| 3 TID 实测表 | `_build_tid_records_tab` 1230–1278 | `tid_records`，初版缺页 | 空表、筛选、详情区域；数据库、查询、导出未接入 |
| 4 野生 / 静态 | `_build_ui` 1707–1936 | `wild`，对应 Tk 模式 `normal` | 表单、IV 预设与互斥交互；遭遇目录、搜索、生成未接入 |
| 5 孵蛋 | `_build_ui` 1938–2064 | `egg` | 同 Seed 表单、亲本输入与确认；配置文件、生成未接入 |
| 条件页 脚本测试（高级） | `_build_ui` 2457–2520；`_toggle_advanced_mode` | `script_test`，初版缺页；高级模式开启后出现在日志之前 | 入口与后端选择；路径解析、预检、运行未接入 |
| 固定末页 运行日志 | `_build_ui` 1425–1536 | `logs` | 空日志及标签诊断布局；日志尾读、诊断、覆盖未接入 |
| 存档信息 | 1366–1397；`open_save_profile_manager`、`_apply_save_profile` | 顶部存档选择与管理入口 | 真实档案与管理器未接入，不展示虚构的当前档案 |
| EasyCon 与设备 | 2522–2851；`check_devices` 等 | 顶部“共通设置”窗口，所有页面共用 | 设置输入仅保存在当前窗口内；设备、文件、更新操作禁用 |
| 操作与结果 | 2853–2879；`_on_mode_tab_change` | 固定底栏与独立可展开“方案与预检结果” | 后端操作全部禁用；结果不显示示例成功 |

`tid_records` 和 `logs` 不是输入模式。切换这两页时保留前一个输入模式及其主按钮文案、公共 Seed 设置和结果，不能把“搜索”改成“导出日志”。默认启动 SID 页，与 Tk 一致。

## SID 查找

| 分区 | 应保留的输入 / 操作 | Tk 接线与边界 |
| --- | --- | --- |
| SID 查找条件 | 游戏、Switch 机型、当前 TID、队内闪光数量 1–6（默认 2）、每只最多糖果（5）、识图阈值（85）、队伍/糖果前置确认 | `collect_sid_request` → `SIDReverseRunRequest` → `generate_sid_project` |
| 队伍闪光宝可梦信息 | 6 个槽位；宝可梦名称/编号、初始等级 1–100、定点/野生来源、野生 Ten Lines 相遇地点、六项 EV 0–255 | `_refresh_sid_party_rows` 禁用数量之外整行；不是删除行；物种和地点目录需后续接入；性别不是用户输入列 |
| SID 查找脚本 | 独立 2.0 脚本包路径与选择 | `sid_source_var` 独立于公共包路径；`write_sid_reverse_project`、`write_sid_reverse_plan`；运行器 `run_sid_reverse_capture.py` |
| 输出 | 公共结果区显示 PSV 交集、8 个真实 SID 候选、建档链最早值与报告路径 | Method 1/2/4；不支持孵蛋来源；没有“取得 SID 后继续御三家”开关 |

初版多出的性别列、御三家接续及单个示例 SID 成功结果应移除；补上主机、糖果、阈值、地点、六槽和前置确认。

## TID 乱数

| Tk 分区 | 应保留的输入 / 操作 |
| --- | --- |
| 1 TID / SID 基本条件 | 英/日 ROM、火红/叶绿、乱数/穷举、主机、主角性别/名称、目标 TID/SID、SID 处理两模式、6V 闪 SID、PID（普通固定 `7942EF72`，高级可编辑）、先检测固定延迟；新建存档警告常驻 |
| 2 乱数中心 / 穷举范围 | OP/F1/F2 三列 × 中心帧、搜索半径、穷举起点、最大范围；这是游戏画面帧，不是 RNG ADV；起点默认 0 |
| 3 游戏设置与固定延迟 | Sound、Button Mode、Seed Button、取名进入键；OP/F1/F2/F3 固定延迟（ms）、关闭延迟、HOME_BUFFER、OP 修正（ms）、SID ADV 修正、SELECT 补偿；手动编辑固定延迟默认关闭 |
| 4 御三家连续乱数 | 完成 TID 后继续（默认开启）、御三家、最低/最高 ADV、独立 Sound/Button/Seed 设置、SID ADV 重试半径、任意 TID 接续、任意 TID 去噪 |
| 5 穷举判定与高级范围 | 豹子号、升/降连号、65535、个位数 TID；F2/F1 候选阈值、去噪命中数/窗口、识图阈值；此分区在 Tk 中并非仅高级模式可见 |
| 6 TID 1.3.7 脚本包 | 独立包路径及选择 |
| 7 参数保存与穷举续跑 | 继续同参数的上次穷举进度（默认开启）、进度状态、刷新；Tk 自动保存，Qt 目前不保存 |

接线：`collect_tid_request` → `TidRngRequest`；`collect_tid_starter_flow_request` → `TidStarterFlowRequest`；`generate_tid_project` → `write_configured_tid_project` / `build_tid_starter_flow_plan` / `write_tid_starter_flow_bundle`；`run_tid_starter_flow.py` 执行。6V 闪 SID 使用 `calculate_tid_shiny_sid` 和 `rng.sid_reverse`，不能在布局层复制计算。

模式规则来自 `_update_tid_flow_controls`：连续穷举固定为“不乱数 SID（固定 F3，采用实际 SID）”；任意 TID 仅连续穷举可用，开启后禁用目标 TID/特殊号码并允许独立去噪；固定 F3 禁用目标 SID，延后身份路径禁用目标 SID 重试半径。关闭连续流程时禁用御三家设置。语言默认值由 `_apply_tid_language_defaults` 定义；后续抽取输入服务时复用。初版的阶段示意不能取代这七区，也不能声称御三家出闪后已自动保存。

## TID 实测表

保留游戏/机型/TID 筛选、查询/刷新、导出 CSV、记录状态与详情。11 列：TID、游戏、机型、语言、OP、F1、F2、出现次数、主角名称、OP 修正（ms）、最近记录时间。详情包含固定延迟、OP 机型补偿、SELECT、HOME_BUFFER、声音/按键/取名设置。

未来复用 `TidRecordStore`（`tid_records.py`）的 `rows` / `export_csv`。真实记录按游戏、机型、参数隔离，最多显示 1000 项而导出不限；TID 显示为五位字符串；不记录 SID、SID ADV、F3，不提供导入或一键回填。Qt 空表必须写“数据库未接入”，不能把空白说成用户没有记录。

## 野生 / 静态

| 分区 | 应保留的输入 / 操作 | 接线 / 边界 |
| --- | --- | --- |
| 乱数条件 | 游戏、主机、TID、SID；类型仅野生/静态；遭遇方式/静态类别、地点、宝可梦 | `_populate_categories/locations/pokemon/abilities` 依次联动；御三家属于静态类别 Starter |
| 个体值范围 | 六项最低/最高 0–31、单项重置、不限/6V/0A/0S/0A0S | `apply_iv_preset`；0A/0S 等是其余项精确 31，不是其余任意 |
| 筛选与范围 | 筛选搜索/指定 Seed/帧数、最小/最大 Advance、闪光、性格、性别、特性、觉醒力量、Seed 模式、指定 Seed/ADV | `collect_request` → `AutoSearchRequest` → `search_best_plan`；指定模式跳过搜索且必须手选 Seed 模式；完整目录仍待接入 |
| 出闪后处理 | 自动抓捕、麻痹、点到为止、道具乱数、队伍空位 1–5 | 道具模式仅野生可用 |
| SID 遍历 | 开关、遍历上限、高级起点、断点状态；生成时询问 TID 和劲敌取名 | `_update_item_rng_controls` 限定野生且道具/遍历互斥；`generate_sid_traversal_plan` → `sid_traversal.py`，不是 TID 页功能 |

未来复用 `write_configured_project`、参数一致性校验、`validate_runtime` 和现有生成暂存/切换流程。路线支持取当前 `automation/support.py`，本轮不据历史交接扩大支持范围。取消虚构皮卡丘 Seed/IV 成功卡，用公共真实空结果区域。

## 孵蛋

保留“孵蛋运行条件”（游戏、主机、Seed 模式、可编辑蛋种、完整准备/从已完成 254 步开始）与“孵蛋目标”（同 Seed、Held、Pickup、相性 20/50/70、双亲性别/六 IV、前置确认）。A 性别仅雌/无性别，B 仅雄/无性别。游戏和主机在 Tk 与野生/静态共用，Qt 表单也保持同步。

四按钮必须齐全：保存亲本配置、载入亲本配置、保存全部配置、载入全部配置。未来复用 `_egg_parent_config_payload`、`_egg_full_config_payload`、对应载入校验、`collect_egg_request` → `EggRunRequest` → `write_configured_egg_project`。亲本配置和全部配置作用域不同，确认不持久化。

本页不搜索蛋目标，也不提供任意不同 Seed 模式；从 Ten Lines Egg 页取得同 Seed Held/Pickup，Pickup 至少晚 1800 ADV。整轮实机未验收说明保留，取消初版虚构的孵化周期/骑车次数成功卡。公共奇偶在本模式固定菜单方案。

## 脚本测试（高级）

正式版/时间轴版/自选 ECS 入口、ECS 文件及选择、兼容/原始 CLI 后端、输出 EasyCon 详细日志、解析状态、常驻人工核对提示。Tk 的入口选择器位于公共区；Qt 也复用公共入口选择，页内提供前往共通设置的入口，避免两个不同步的选择器。

未来复用 `resolve_script_test_entry` / `identify_script_test_entry` / `prepare_script_test_runtime`；原地运行，不搜索、不替换参数、不生成 main.ecs。缺文件/标签/格式或不支持运行时仍阻止，不能把高级模式解释成关闭检查。初版没有该页；已撤回的冲浪探针不恢复。

## 日志、公共设置与结果

- 日志：只读、不换行、双向滚动；`poll_process` 读取各模式独立日志，仅进程创建成功自动转日志页，结果区保留。
- 标签：设备名称覆盖状态；疑似标签/最高分/门槛/连续次数/阶段原因五列；多文件、文件夹、拖放、清除设备覆盖、清空诊断。未来复用 `diagnose_label_log`、`LabelOverrideStore`；Qt 不接受文件拖入，不声称已诊断设备。
- 存档：未来复用 `SaveProfileStore`；管理器新建/编辑/复制/删除/设为当前；手动模式不覆盖输入。原型仅保留禁用的管理入口。
- 设备：公共 2.0 包、ezcon 路径、串口、带编号名称的采集卡；检测、虚拟手柄、监视窗口、Seed 表更新、程序更新。真实设备选择与枚举未接入；未来复用 `probe_easycon_devices`、`ManualToolsManager`、`tenlines_seed_updater`、`app_updater`。
- 运行设置：高级模式、HOME_BUFFER 自适应、Seed 校准/启动、正式/时间轴入口、脚本输出日志、命中后更新预校准。高级三层扩窗包含层数 0–3 和各层 Seed/ADV 绝对半宽；仅普通、孵蛋或连续御三家适用，孵蛋菜单奇偶固定。
- Seed 合同：普通模式关闭高级时普通/御三家校准 0、孵蛋 2、启动 0、正式入口；当前 Tk 普通高级只提供校准 0/1、孵蛋 0/1/2。御三家请求始终锁定校准 0。Qt 不读取 ECS 默认窗口，扩窗值留空并提示模板默认值待接入，避免把回退示例当成实际模板值。
- 公共底栏：准备/生成、取消搜索、开始运行、停止 EasyCon；结果独立且为空。初版“保存配置”“返回正式 Tk 版”“导出日志”等无正式对应/无接线按钮不冒充完成能力。

## 本轮验收口径

页面映射先于布局修改落盘。逐页修改后启动 Windows 正常 Qt 窗口，检查中文、密度、滚动到底、条件显示和固定操作栏；最小窗口另外检查。自动化的 offscreen PNG 只作构造冒烟，不当作视觉验收。

可运行的本地交互与业务接入分开记录：页面切换、显隐、互斥、IV 预设和内存字段同步属于布局交互；数据库、设备、搜索、反查、预检、ECS 生成、运行、配置保存均未接入。所有依赖这些能力的按钮保持禁用并提供原因。
