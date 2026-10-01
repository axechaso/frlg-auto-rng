# SID 定点遍历、脚本按键回显与存档选项：七项功能实现方案

编写日期：2026-10-01。

修订：2026-10-01 第二版。对照 `2026-09-30-button-emphasis-and-script-sync.md` 补齐函数级改动、字段去向、协议样例、状态转换、逐步操作和验收判据。参考文档中的既往实施结果不算本方案的验证结果。

状态：**源码实现与自动化验证已完成（定向 231 项、全量 709 项通过，`git diff --check` 通过）；按 §4.10 本阶段未构建兼容运行器，未连接设备或完成实机验收，未打包、未提交或推送，因此不标记为完整实机验收。**

工作仓库：`D:\Codex\火叶乱数\frlg-auto-rng`。

核对基线：`codex/merge-pr4-86019a7-20261001`，HEAD `31eca76`。当前本地已包含 PR #4 对应提交的合并；这是本方案的输入基线，不是本轮新完成的合并。实施前再次核对 HEAD 和工作区，不覆盖后续用户改动。现有未跟踪的 `.tmp/`、工具 `bin/obj` 不清理。

## 1. 需求范围与最终体验

| 编号 | 要求 | 交付结果 |
| --- | --- | --- |
| 1 | SID 遍历支持定点 | 在已支持的定点路线选择 SID 遍历，沿用当前存档身份、SID ADV 奇偶与续跑机制，自动寻找可执行的低帧闪光目标并逐个验证 |
| 2 | 虚拟手柄反映脚本操作 | 脚本运行中手柄进入只读观察模式，按钮、方向和摇杆跟随运行器输出；不抢占串口 |
| 3 | 日志页“运行准备”显示按键 | 改为“脚本操作”卡，与手柄使用同一状态源，显示当前按住、最近动作、阶段与连接状态 |
| 4 | 两项开关默认开启 | 新用户及缺少偏好字段时，默认启用更新预校准、出闪录像；用户关闭后持久保存 |
| 5 | 滚轮切换存档 | 鼠标位于顶部存档信息或存档选择框时，上下滚动切换相邻存档；运行期间禁止切换 |
| 6 | 神秘礼物状态与奇偶约束 | 存档可保存神秘礼物开关；开启时实际执行的帧奇偶方案强制为 1，UI、生成与运行校验一致 |
| 7 | 自选脚本测试跳转日志 | 自选 ECS 确认开始后自动进入日志页，实时显示输出、启动失败和结束结果，两种后端均覆盖 |

本轮不恢复 Tk 界面，不重做布局，不改变 Seed 表、反查算法、等待公式和逆向搜索帧窗，不扩大 TID 刷号流程职责，不擅自打包或上传 Release。

正式 GUI 入口为 `run_pyside6_gui.py` → `pyside_app.migration.CompleteWindow`。验收以此入口为准，而不是只检查 `pyside_preview.py` 的独立预览。

## 2. 已核实的现状与实现原则

### 2.1 现状

- SID 遍历被 `pyside_preview.py`、`pyside_app/migration.py` 和 `run_sid_traversal.py` 多处限定为野生；只改界面不足以支持定点。
- `traversal_candidate_request()` 已保留用户的目标 Advance 下限；`sid_traversal.py` 已实现 1900/1901 起点、步长 2 和断点续跑，这些不能回退。
- `run_sid_traversal.py` 把 `SearchWorkLimitError` 和完整搜索无结果一起推进起点；它还以普通“出闪”文本判断成功。拓展定点时必须补齐这两个安全边界。
- 当前虚拟手柄显示手动输入状态，运行前主动释放串口；运行中打开浮窗会被拒绝。没有现成的脚本按键状态流。
- EasyCon 的 `GamePadAdapter.ClickButtons()` 只是交给 `NintendoSwitch.Press()` 排程；真正按下和自动松开发生在设备报告循环中。因此不能在 Click 返回时立即把 UI 当成已松开，也不能仅靠解析 ECS 文本回显。
- “运行准备”卡通过标题和布局下标被 `window.py` 绑定，并被 `migration.py` 更新；直接改标题或复用这三行显示按键，会被旧刷新逻辑覆盖。
- 普通野生/定点已经传递 `record_shiny_video`；孵蛋请求与御三家连续流程请求尚未贯通这一偏好。
- `SaveProfile` 目前有游戏、语言、主机、TID/SID，没有神秘礼物字段；已有存档切换逻辑刻意保护 TID 页的目标 TID/SID。
- 自选脚本已通过 `easycon-log` worker 输出日志，基类 `_process_started()` 也有 `select_page("logs")`。这项应补齐生命周期与回归，不凭现象认定“完全没有跳转代码”。

### 2.2 统一规则

1. 每次运行冻结配置快照，运行过程中不能因为切页、切档或改高级设置而变更正在执行的计划。
2. 运行器独占脚本控制串口；监视画面继续复用现有单路采集，新增按键显示不建立第二路采集。
3. 手柄和操作卡共享一个按键状态模型，不分别猜按键，不互相回传控制命令。
4. 设备输出、日志输出、目标结果证明是三类数据。按键显示故障不等于脚本失败；普通文本出闪也不等于已证明当前候选正确。
5. SID 遍历保持为当前存档的独立验证功能，不读写 TID 刷号页的目标 SID、重试半径或 F3 延迟。
6. 使用现有模块做有边界的扩展；仅增加可复用的策略、目标证明和按键状态组件，不另外复制整套运行框架。

### 2.3 本版消除的实施歧义

以下选择已经在方案中确定，不留给实施者临时猜测：

| 问题 | 本轮选定做法 | 不采用的做法及原因 |
| --- | --- | --- |
| 按键数据从哪里来 | 兼容运行器最终控制报告的旁路状态采集 | 解析 ECS 行无法反映分支、自动松开和被故障保护拦截的按键 |
| 怎样传给 GUI | 复用现有 loopback 服务端口，增加 JSON 状态接口 | 不再开串口、不建另一条视频捕获、不把每个状态写进 stdout |
| 自选脚本何时跳页 | 开始确认通过、启动进程之前 | 仅等 `started` 会遗漏启动失败；仅选择文件就跳转又过早 |
| 原始后端怎么办 | 正常显示运行日志，动作卡明确提示无回显能力 | 不偷偷换成兼容后端，保留 A/B 对照的意义 |
| 默认开启是否覆盖旧选择 | 缺字段为开，显式关闭永远保留 | 不每次打开工具、切页或切档就重新勾选 |
| 神秘礼物影响什么 | 当前存档的遭遇帧奇偶修正策略 | 不改 SID ADV 奇偶，不覆盖 TID 新建目标，不执行游戏内开启礼物操作 |
| 搜索超限是否跳 SID | 暂停并保留当前候选 | 预算用尽不能证明已经完整搜索该窗口 |
| 工具是否重写自选 ECS | 不重写，前后内容哈希一致 | 默认偏好和存档策略只作用于工具生成的工程 |

下文出现“拟新增”的函数、字段和测试名称均是实施契约，不代表代码中已经存在。源位置用文件和符号定位，避免后续加代码导致行号失效。

## 3. 功能一：SID 遍历支持定点

### 3.1 开放范围与 UI

- 把卡片说明由“仅野生可用”改为“野生 / 已支持定点路线可用”。
- 删除三处仅凭 `Wild` 字符串或下拉索引判断可用性的限制，统一调用遭遇类型与路线支持检查。
- 基础范围沿用 `automation/support.py`、`automation/static_targets.py` 的游戏、目标、类别白名单，不能把工具尚不能自动运行的组合一并解禁。
- 对已有定点类别分别核对领取/捕获、识别与重启路径；御三家、礼物、化石、游戏厅、固定传说等使用自身已有路线，不统一套成野生捕获。
- 游走沿用独立截断 IV 模型，单独验收；缺少可靠终态证据的路线在生成前明确提示原因，补齐证明后才开放，不让按钮显示可用但运行到一半才失败。
- 道具模式仍与 SID 遍历互斥；直接输入 Seed/ADV 模式不能代替逐 SID 搜索。互斥应同时在 UI 和请求校验中生效。
- 切换野生/定点后失效旧计划；支持的新类型保留遍历开关，不因为下拉索引变化偷偷取消。无效类型明确显示不可用原因。
- 保留开始前 TID 与劲敌取名确认。确认信息进入运行快照与续跑上下文。

### 3.2 候选搜索规则

对每个候选 SID：

1. 按当前独立遍历上下文取得 SID ADV 与对应 SID。
2. 保留物种、游戏、地点/静态类别、算法、模板与用户目标帧下限。
3. 继续放宽 IV、性格、特性等非必要筛选，只要求该 SID 下的闪光目标，以降低验证成本。
4. 目标 Advance 区间为 `[用户填写的下限, 遍历低帧上限]`；当前默认上限 3000 不改变。下限大于上限时直接解释冲突，不自动从 0 搜索，也不暗中扩窗。
5. 复用规划器的可执行性检查。数学上有目标但实际等待不足，不能生成负等待工程。
6. 正式/时间轴模板由本次冻结配置明确传入，不能界面选择时间轴，遍历子工程却使用默认正式版。

SID ADV 规则保持原样：未给劲敌取名默认 1901，取名默认 1900，步长 2；高级自定义起点同样验证奇偶。该上限与目标宝可梦 Advance 上限是两个概念，不从 TID 页挪用配置。

### 3.3 成功、失败与跳过必须分开

为生成的遍历工程增加结构化候选结果，至少绑定：本次运行、候选 SID ADV/SID、目标、算法、目标 Seed/ADV、物种核验、实际命中状态、闪光核验状态。

复用御三家现有的“先记录闪光、再验证精确目标”的设计，但抽取独立的目标证明生成/解析函数，不让 SID 遍历依赖 TID 流程控制器。保留现有 TID 协议，避免改变其报告消费者。

| 结果 | 处理 |
| --- | --- |
| 本次候选精确命中、目标闪光成立、正常结束 | 记录验证命中与证据，结束遍历，显示候选 SID 和 SID ADV |
| 精确命中当前目标、明确非闪、正常结束 | 记录本次验证排除，起点推进 2 |
| 在已完整检查的目标窗口内没有可用验证目标 | 标记“本窗口无目标/无可执行目标，跳过”，推进 2；不得写成已实测排除该 SID |
| 搜索预算超限、被取消、内部异常 | 停止并保留当前候选；不推进 |
| 只看到普通出闪文字、非目标闪光、证据不完整 | 安全停止，保留当前候选，不确认 SID、不自动重启丢弃已出现的闪光 |
| 非零退出、手动停止、采集/设备错误 | 保留当前候选及错误，允许续跑 |

从 `SearchWorkLimitError` 的共用跳过分支中拆出超限处理。规划器的“无匹配”“无可执行”也分别记录，不伪装成实机非闪。

成功不得只由 `completion_kind()` 搜到关键字触发；还要匹配当前候选身份、完整目标证据和进程结果。报告区区分“验证命中候选”与“唯一确定”；若证据存在多个等价身份，不额外宣称已唯一反推出 SID。

### 3.4 断点续跑与结果展示

- 断点上下文加入/确认：野生或定点类型、静态类别、模板、目标区间、TID、劲敌取名、有效奇偶方案、神秘礼物状态、实际生成选项与脚本指纹。
- 明确参数变动即为不同会话，不能用同一个文件把野生的下一起点套进定点。
- 仅按用户行为或完整结果原子更新断点；搜索中、生成中、启动中退出都保留当前候选。
- 旧野生断点保留，不删除。旧上下文缺少新关键字段时不能无提示续接；展示原起点供用户确认用于新会话。
- 界面显示“当前验证 SID/ADV、已实测排除数、窗口内跳过数、下一起点”；结束报告保留证据路径。
- 找到候选不直接覆盖已保存的 SID 或 TID 页目标字段，仍由用户决定保存。

主要修改：`pyside_preview.py`、`pyside_app/migration.py`、`pyside_app/workflows.py`、`run_sid_traversal.py`、`sid_traversal.py`、`automation/easycon118.py`。目标证明公共组件作为新增小模块，复用现有 TID 实现的已验证原则。

### 3.5 逐函数施工顺序

| 顺序 | 现有位置 | 明确改动 | 改完立即检查 |
| --- | --- | --- | --- |
| S1 | `pyside_preview.py` 的遍历卡、`_refresh_wild_controls()` | 去掉定点切换时直接取消遍历的代码；可用性由路线结果决定；当前手动输入不完整时只显示未就绪，不反复弹异常框 | 野生→定点→野生不丢开关；非法目标仍不可启动 |
| S2 | `CompleteWindow.collect_workflow()` | 删除 `"Wild" not in request.method` 限制，保留 `direct_mode` 禁止；在 `extra` 中冻结 `options`、模板、当前存档策略与确认结果 | 定点请求的方法、类别、最低帧与原 `collect_inputs()` 一致 |
| S3 | `CompleteWindow._refresh_wild_controls()/refresh_state()` | 删除第二套按 `wild_method.currentIndex() == 0` 的禁用逻辑，调用同一个轻量可用性判断 | 不存在基础类放开、子类又禁用的情况 |
| S4 | `workflows._prepare_workflow_in_directory()` 的 `sid_traversal` 分支 | `project` 改取 `inputs.source / inputs.template`；计划写入模板与有效策略；上下文使用同一份冻结值 | 预检所选入口就是候选生成所选入口 |
| S5 | `run_sid_traversal._load_plan()/_request_from_payload()` | 支持野生与合法定点；校验新计划版本、模板白名单、策略一致性；不忽略关键字段后偷偷使用默认值 | 修改 JSON 为未知模板或矛盾策略时生成前失败 |
| S6 | `run_traversal()` | 将模板、预校准路径、目标证明上下文传给每个候选工程；拆分超限/无目标/不可执行分支；每个阶段前检查停止 | 模拟搜索抛出超限后没有第二个候选、没有启动 EasyCon |
| S7 | `SIDTraversalSession` | 新增语义明确的跳过方法和计数；已完成状态以原子检查点为准，报告是派生展示 | 重复完成事件不能推进两次；崩溃重启不跳过进行中候选 |

拟新增 `automation/sid_traversal_policy.py`，只提供两类校验：`traversal_availability(...)` 返回可用性/原因供 UI 轻量刷新；`validate_traversal_request(request, options, template_name)` 供生成器和 worker 做完整检查。前者不能在用户尚未输入完整数字时强行调用整个表单解析，后者不能因为 UI 曾通过就省略验证。

### 3.6 计划、断点与报告的字段契约

`traversal.json` 从当前 `version: 1` 升为 `version: 2`，新增以下字段；已有 `request`、`easycon_options`、起止帧字段继续使用原意义：

| 字段 | 类型 / 来源 | 校验与消费位置 |
| --- | --- | --- |
| `template_name` | str；`WorkflowInputs.template` | 只接受当前两份入口常量；`run_traversal()` 显式传给生成器 |
| `encounter_kind` | `wild` / `static`；从请求规范化推导 | 必须与 `request.method/category` 一致，不作为可独立篡改的第二套判断 |
| `save_context` | 当前存档快照 | 含礼物状态、来源及用于显示的存档 ID；不读取运行时 GUI |
| `effective_frame_parity_scheme` | int，0 或 1 | 与 `easycon_options.frame_parity_scheme` 和礼物规则同时校验 |
| `verification_protocol` | int，首版 1 | 不支持版本直接拒绝，不回退为文本关键字判定 |
| `traversal_context` | 规范化身份对象 | worker 重新计算并比对，而不是盲目信任文件附带的哈希 |

断点 schema 从 2 升为 3；保留 `wild_request` 这个既有存储键来容纳完整遭遇请求，避免只为了改名维护两份同义数据。新增模板、遭遇种类与存档策略维度；进度数据增加 `candidate_phase`、`attempt_id`、`tested_non_shiny_count`、`skipped_count`。

`status` 继续使用 `running/paused/completed/exhausted`，不破坏既有 UI 对终态的判断；细阶段另放在 `candidate_phase`。新会话不自动读取旧哈希路径。旧断点只读展示原起点供确认，新会话正常写 schema 3，不长期保留两套可执行续跑引擎。

每次候选开始生成新的 `attempt_id`。`begin_candidate()` 必须先落盘，再搜索、生成或启动；恢复同一个 SID ADV 也产生新的尝试 ID，不能接受上次崩溃前残留的成功日志。

拟将内部推进动作收敛到 `_advance_candidate(result, outcome)`：公开的 `complete_non_shiny()` 只表示实测排除，新增 `skip_candidate(reason)` 只表示本窗口未能验证。两者都按 +2 前进，但计数和报告不同；没有活跃候选时重复调用不得再次前进。

### 3.7 目标证明的生成锚点与解析

拟新增 `automation/target_verification.py`，包含纯数据 `TargetVerificationSpec`、生成适配与事件解析；不导入 GUI、不启动子进程、不操作存档。

当前可复用锚点来自 `enable_starter_success_markers()`：

```text
IF $道具乱数模式 == 0 and @出闪 >= $识图阈值

IF $道具乱数模式 == 0 and $命中差索引 == 0 and $本轮消耗帧误差 == 0 and $本轮物种命中 == 1
```

施工规则：

1. 每次主循环目标获取前清空本轮闪光标志和结果状态，不能沿用上一次捕获的闪光。
2. 在英/日出闪识别分支记录本轮观察，保留已有录像和非目标闪光保护；本轮候选验证不能在完成目标核验之前只凭星标报成功。
3. 只有精确 Seed/ADV/物种命中分支发出完整终态事件；“已命中目标”的普通文字继续供人阅读，但不再作为唯一机器证据。
4. 礼物/波克比等流程有额外野生 Seed 验证时，必须区分验证用野生个体与本次 SID 验证目标。野生复核中的星标不能证明所领目标闪光。
5. 目标错误、识图不全或非目标闪光发出不完整/异常状态并停止；不能触发候选推进。
6. 使用唯一注入标记 `SIDTRAVERSAL_TARGET_VERIFICATION_V1`；第二次处理幂等。锚点缺失或重复则报模板不兼容，不全局替换所有“出闪”字符串。
7. 在最终工程摘要与一致性清单计算前完成注入；不能写好 manifest 后再改 ECS，导致运行前校验把自己生成的文件判为被篡改。

候选终态事件格式定为以下结构，示意值不是真实运行结果：

```text
SIDTRAVERSAL|V=1|RUN=r1|ATTEMPT=a1|ROUND=4|EVENT=TARGET|SEED_MATCH=1|ADV_MATCH=1|SPECIES_MATCH=1|SHINY=1|END=1
```

计划另存目标 Seed、ADV、物种、算法和 PID；事件通过 `RUN + ATTEMPT` 关联目标快照。上述 MATCH 字段来源于实际目标核验分支，不能把计划值原样打印出来当作实际反查结果。完整事件必须单行闭合，枚举、布尔和数字严格校验，截断行/其他尝试/其他轮的数据不可拼接。

worker 只有在进程输出排空、退出码合格、没有手停或后续致命错误后，才将完整事件升级为最终候选结果。成功先原子提交检查点，再刷新报告；若第二步失败，续跑以检查点终态为准，不重新执行已完成候选。

### 3.8 定点逐类验收对象

| 当前类别 | 代表目标 | 除通用证明外必须核对 |
| --- | --- | --- |
| `Starter` | Bulbasaur / Charmander / Squirtle | 直接从既有球前存档运行，不插入 TID 新建游戏；英/日识图均覆盖 |
| `Fossil` | Omanyte / Kabuto / Aerodactyl | 领取后的实际队伍位置、完整取得后再核验 |
| `Gift` | Eevee / Lapras；Togepi 单列 | 领取目标与额外 Seed 复核野生个体不能混淆 |
| `GameCorner` | 火红 Scyther、叶绿 Pinsir | 版本目标白名单、兑换前置条件与领取位置 |
| `Stationary` | Snorlax / Electrode | 捕获结束和目标识别，不能看到战斗闪光就误用另一轮结果 |
| `Legend` | Mewtwo | 既有静态方法与目标帧证明 |
| `Event` | Lugia / Ho-Oh / Deoxys | 保留原有地点/事件前置条件，不因开放遍历绕过它们 |
| `Roaming` | Raikou / Entei / Suicune | 独立游走规划器、截断 IV 和存档御三家条件；不得硬转普通 Static1 |

此表是待验收范围，不代表当前所有代表目标已经实机通过。若某一路线缺少本轮目标的可靠证明，交付时必须列为未开放及具体阻塞项，不能统称“定点全支持”。

## 4. 功能二、三：一条真实按键状态流，两个显示端

### 4.1 状态来源

数据流固定为：

```text
脚本运行器 → 故障保护 → 实际控制报告发送
                             ↓
                       有界内存状态/事件
                             ↓
                       本机只读状态接口
                             ↓
                    GUI 运行按键状态模型
                       ↙           ↘
                 虚拟手柄         日志操作卡
```

在当前 EasyCon 的设备报告发送边界观察按钮、十字键、双摇杆的完整状态；保护层拒绝的按键不会出现在实际发送状态里。短按的释放由运行器真实报告更新，不由 GUI 定时器自行模拟。

这表示“软件发送的控制状态”，不是 Switch 接收回执，也不是游戏内操作成功检测。串口写入异常须反映为未知/错误，不能显示硬件已执行成功。

### 4.2 运行器改动

- 在实际发送点只复制固定大小的状态和单调时间、序列号到有界缓冲。不能在按键线程/设备锁内格式化 JSON、写日志、访问网络或回调 GUI。
- 使用现有本机 HTTP 服务承载独立输入状态接口；例如新增 `/input-state?after_seq=...`，返回最新快照、尚未消费的状态转换和心跳。
- 状态服务生命周期独立于监视窗口及视频订阅。关闭监视、没有打开虚拟手柄、TID 去研究所桥接未使用识图，都不应关闭它。
- 每个响应包含协议版本、主运行 ID、子进程会话 ID、序列号、单调时间、按钮掩码、HAT、双摇杆坐标、连接/停止状态。阶段信息沿用现有结构化阶段消息，不把无来源的阶段名猜出来。
- 缓冲有上限，溢出不阻塞设备线程；返回快照及“历史有缺口”标志。GUI 可恢复当前状态，但不补造遗漏动作。
- 服务仅绑定 loopback，不新增远程控制接口。原始 `ezcon.exe` 后端无此协议时显示“不支持按键回显”，不能拿普通日志冒充实时状态。
- 不改变 `NintendoSwitch` 现有发送间隔、按键保持时间、等待算法或脚本 WAIT。

涉及当前构建源码中的 `EasyCon.Core/GamePadAdapter.cs`、`EasyCon.Device/NintendoSwitchPriv.cs`、`NintendoSwitchCmd.cs`、CLI 的 `MjpegPreviewServer.cs` 与 `LabelFaultSupervisor.cs`。最终改动必须形成仓库内可重放补丁，通过 `tools/build_easycon164a_compat_runner.ps1` 构建并更新运行器 manifest/校验；只改 `.build` 或替换一个 EXE 不算完成。

### 4.3 GUI 接收与状态模型

新增一个小型 `pyside_app/run_input_state.py` 组件，负责：

- 活跃运行身份、最新输出状态、最近动作、心跳时间和连接状态。
- 异步请求状态接口，初始建议 50 ms 间隔、至多一个请求在途；界面重绘合并到最多 30 Hz。数值作为首版调优起点，必须用本地压测验证，不承诺零延迟。
- 只接收当前主运行及当前子进程会话的数据。阶段换进程可重连，旧请求晚到必须丢弃。
- 收到序列缺口时应用最新快照，提示近期历史不完整，不把缺失的释放事件变成长按。
- 超时、运行器异常退出时清除“已确认按住”的显示并标注未知/失联；只有收到复位快照才能称“已复位”。
- 正常结束、手动停止、新运行、窗口关闭时清理订阅、定时器和旧状态。

连续短按用“最近动作”显示；当前状态已经松开时，手柄不能为动画效果继续高亮为持续按住。最近动作可以短暂保留，但要与当前持有状态区分。

### 4.4 虚拟手柄两种模式

| 模式 | 输入权限 | 显示来源 |
| --- | --- | --- |
| 空闲手动控制 | 用户明确连接后可发键 | 原有鼠标/键盘控制状态 |
| 脚本运行只读观察 | 鼠标、键盘均不向设备发送按键 | 运行按键状态模型 |

- 运行前保留 `release_for_run()` 释放手动串口的现有职责。
- 运行中允许打开/关闭手柄窗口或浮窗，但只订阅状态，不再次连接 COM。
- 观察态使用独立的 `observed_state`；不把它写入手动 `pressed` 集合，避免 `release_all()` 在关闭浮窗时向脚本的串口发送释放。
- 显示 A/B/X/Y、L/R/ZL/ZR、HOME、截图、加减键、方向及双摇杆/摇杆按下；摇杆按实际坐标显示，不只画四个方向。
- 运行结束回到空闲未连接状态，不擅自重新抢串口；原手动操作入口仍可用。

修改 `pyside_app/manual.py`、`accessories.py`、`controller_layout.py`，统一复用控件更新方法，避免每条输入重建窗口或重算全套样式。

### 4.5 日志页“脚本操作”卡

仅将日志页对应卡替换为明确引用的动作组件，移除该卡对 `ready_values/ready_dots` 布局下标的依赖；设备准备检查本身仍保留在开始前的流程中。

建议四类内容：

- 当前按键：例如 `A + ZL`，无输出则显示“当前无按键输出”。
- 方向/摇杆：十字方向、左/右摇杆状态。
- 最近操作：例如“松开 A”，带时间；不是不断追加到普通运行日志的高频文本。
- 运行状态：阶段、运行中/切换阶段/失联/结束。

在没有脚本 WAIT 事件时，不把“没有按键”写成“正在 WAIT 1500”。脚本可能在识图、计算或等待，显示事实即可。

同一状态必须同步更新手柄和操作卡。操作卡关闭或切页后应停止无意义重绘，但保留轻量状态模型；返回日志页立即显示最新快照。

### 4.6 性能与时序验收

- 使用模拟串口/设备输出测试状态序列，确认启用回显前后实际控制报告序列、保持/释放顺序不变。
- 分别测“不显示 UI”“只开操作卡”“手柄与监视同时开”；观察端网络断开、卡顿、缓冲溢出均不得拖住运行器。
- 记录显示延迟与发送时间分布，目标为本机通常不超过约 100 ms 的可见反馈；此为验收目标，达不到时优化传输/重绘，不调整脚本时序掩盖问题。
- 长时间运行内存必须有界；拖动窗口不能触发每条按键全局重绘。
- 无硬件测试仅能证明软件控制序列与性能，真实乱数命中稳定性需单列实机验收。

### 4.7 输出协议、容量和失联口径

首版固定协议版本 1。服务端增加 `/capabilities` 和 `/input-state?after_seq=N`，现有 `/health`、`/mjpeg` 路径保持原语义。能力响应声明 `input_state_protocol: 1`；404 或不支持的版本仅禁用动作显示，不停止脚本、不切换后端。

状态响应示例（仅为协议样例）：

```json
{
  "protocol": 1,
  "run_id": "r1",
  "session_id": "s2",
  "stage_id": "lab_bridge",
  "server_ms": 15420,
  "seq": 42,
  "source": "device_report",
  "connection": "connected",
  "snapshot": {
    "buttons": ["A", "ZL"],
    "hat": "CENTER",
    "left_stick": [128, 128],
    "right_stick": [128, 128]
  },
  "events": [],
  "history_gap": false
}
```

- `server_ms` 是该子进程单调时钟的毫秒数，不是墙上时钟；不能拿它与 GUI 的本地 epoch 直接相减。
- `seq` 随报告状态转换递增；没有变化时可保持不变，响应仍是有效心跳。长按 30 秒时不能因没有新事件而误判断线。
- `buttons` 使用现有控件键名：`A/B/X/Y/L/R/ZL/ZR/MINUS/PLUS/HOME/CAPTURE/LCLICK/RCLICK`；HAT 单独映射到 `TOP/DOWN/LEFT/RIGHT` 及四个斜向，不混成左摇杆。
- 摇杆为原始 0～255 坐标，中点 128。UI 只做绘制坐标归一化，不向运行器回写、舍入或修正摇杆值。
- `events` 每项含 `seq/at_ms/snapshot`，以完整状态转换为准。服务端环形缓冲固定 512 条，响应最多返回最近 256 条；有遗漏时 `history_gap=true`，并始终附上最新快照。
- GUI 拒绝超大响应（首版上限 256 KiB）、非法枚举、越界坐标、倒退序列和不匹配的运行身份。一次坏响应只影响显示，不作为自动停止游戏的依据。
- 正常可见时 50 ms 异步请求一次，最多一个在途请求；超时 1000 ms，失败后 250 ms 再试。所有显示端隐藏时降为 250 ms，不持有无限事件历史。
- 超过 1500 ms 未取得有效响应时显示“状态未知”，去掉确定按住的高亮；收到新快照即可恢复。这里清理的是 UI，不调用 `release_all()`。
- 最近操作文字保留 1 秒便于阅读；当前按键立即按最新快照更新。重复短按可显示最近次数，但不延长实际按下状态。

`source=mock` 的测试数据必须显示为模拟来源；开发用模拟后端不得在正式窗口冒充真实串口发送结果。

### 4.8 后端接线的实际漏点

已核实 `Program.cs` 目前在采集卡首帧成功之后才创建 `MjpegPreviewServer`。新增服务必须移到独立生命周期中：先建立本机只读服务，帧提供器无画面时返回空；状态接口不等待 JPEG 编码，也不获取 `latestFrameLock`。采集线程数、首帧失败对脚本本身的既有策略不变。

`NintendoSwitch.Loop()` 负责执行定时释放，再调用 `WriteReport()`。在提交报告后将固定大小状态写入专用非阻塞缓冲；不注册会在设备锁内执行任意订阅者代码的通用事件。缓冲异常必须隔离，不能吞掉原有串口异常，也不能阻断 Reset。

Python 接线需一起改，不能只改 C#：

| 位置 | 修改 |
| --- | --- |
| `RunCommand` | 末尾新增默认空的 `input_state_url`、`input_session_id`；调用处使用关键字，保留旧位置参数语义 |
| `services.prepare_run()` | 兼容运行器填写状态 URL 和初始会话 ID；运行前冻结，不从监视窗口反向取得端口 |
| `workflows.prepare_workflow_run()` | 所有兼容工作流无条件传运行身份；原始后端 URL 留空，不传新增 CLI 参数 |
| `automation.easycon118.build_run_command()` | `run_id/workflow` 的传递不再依赖 `label_supervision`；故障目录与保护开关仍按原条件；增加可选子会话/阶段参数 |
| `FlowRunner.run_stage()` | 每次启动子进程建立新会话，先通知 GUI 切换阶段，再启动该子进程 |
| `run_sid_reverse_capture._run_easycon()` | 每只采集/阶段独立会话，主运行 ID 不变 |
| `run_sid_traversal.run_traversal()` | 每个候选的执行子进程独立会话；搜索期间显示“计算中，无按键”，不残留上个候选的按键 |

现有 `build_run_command()` 即使收到 `run_id`，关闭标签保护时仍不把它加进实际 CLI 参数。因此“标签保护开/关 × 按键回显”必须单列回归，否则会出现只有打开故障保护才有手柄回显。

多阶段 worker 在启动子进程前输出一条低频生命周期标记：

```text
FRLG_INPUT_SESSION|V=1|RUN=r1|SESSION=s2|STAGE=lab_bridge|STATE=STARTING|END=1
```

GUI 从当前 QProcess 的完整行接收该标记，建立预期会话，再接受 HTTP 数据。根运行 ID 匹配但子会话不匹配时丢弃响应，不能因先前请求晚到而重新亮起旧阶段的按键。结束/搜索阶段也有对应低频标记；这些不是每次按键日志。

### 4.9 虚拟手柄与操作卡的状态表

| 软件状态 | 手柄 | 操作卡 | 是否允许 GUI 发键 |
| --- | --- | --- | --- |
| 空闲、未连接 | 原有未连接显示 | 等待运行 | 否 |
| 空闲、用户已连接 | 显示手动键位 | 等待脚本运行，不把手动输入称为脚本输入 | 是 |
| 正在释放手动控制/启动 | 只读，清除旧手动显示 | 正在启动 | 否 |
| 搜索候选/切换子阶段 | 只读，中性显示 | 计算中/切换阶段，当前无输出 | 否 |
| 有效运行状态 | 按快照高亮 | 按键、摇杆、最近动作与阶段 | 否 |
| 接口失联 | 灰态“状态未知” | 状态连接中断，脚本状态单独显示 | 否 |
| 原始后端运行 | 可打开，只读提示不支持 | 此后端不提供按键回显；下方日志照常 | 否 |
| 停止中 | 保留仍有依据的状态，停止后清理 | 正在停止 | 否 |
| 已退出 | 未连接、中性显示 | 已结束及最近终态 | 否，须用户重新连接 |

具体控件改动：`ControllerWindow.open_overlay()` 不再一律拒绝运行中打开；`press/release/keyboard_transition` 在观察态直接忽略输入；`ControllerOverlay.exit_control()/hideEvent()/closeEvent()` 区分模式。空闲手动模式原有失焦松键与断开逻辑仍保留，不能为只读观察把它们全部删掉。

日志卡显式保存 `self.script_action_card` 及其标签引用，不再按中文标题搜索布局项。首版四行标签固定为“当前按键 / 方向摇杆 / 最近操作 / 执行状态”；较长组合键允许换行，空闲时不隐藏整卡引发页面跳动。颜色沿用现有主题，不另建一套按钮配色。

### 4.10 补丁、构建与时序对照

新增可重放补丁 `tools/patches/easycon164a-input-state-v1.patch`，接在现有 v9 补丁之后；源 commit 仍是 `9c86137c7e63bff842175470895727a5fa9bab52`。新的整体 `patch_id` 在构建脚本、`EXPECTED_COMPAT_PATCH_ID` 与 manifest 同步为 `easycon164a-label-supervision-v9-input-state-v1`，不能只改一个常量绕过一致性检查。

实施后构建命令为：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\build_easycon164a_compat_runner.ps1
```

该命令会更新本地开发运行器，属于本功能必要编译；不是生成应用分发包，也不上传 Release。本方案阶段不执行它。

对照同一套模拟输入，保存改动前后发送报告序列、相对发送时间分布、状态缓冲耗时与 GUI 延迟。报告序列必须一致；任何新增串口发送、Reset、WAIT 或采集线程都判失败。观测缓冲写入以 10,000 次本地样本记录 p50/p95/p99，不能只用“体感不卡”验收。GUI 反馈目标约 100 ms，乱数时序是否受影响仍需实机记录，不用显示目标替代时序验收。

## 5. 功能四：默认开启更新预校准与出闪录像

### 5.1 默认值与持久化

应用偏好新增或统一保存：

```json
{
  "update_precalibration": true,
  "record_shiny_video": true
}
```

- 新安装或旧设置缺字段：默认 `true`。
- 用户明确保存 `false`：关闭后重启仍为 `false`。
- 合并 `window.py` 与 `migration.py` 的设置序列化入口，避免子类最后一次写入把字段丢掉。
- 切模式、切档、开关高级模式均不重置这两个用户偏好。
- 已生成的计划是冻结快照，旧计划中的 `false` 不被静默改写；修改开关后要求重新生成。
- 不单纯把所有 dataclass 默认改成 `true`，以免旧 JSON 缺字段在 worker 中变成与生成时不同的行为。新 GUI 生成时显式传值，旧计划按其版本与原语义读取。

### 5.2 参数必须贯穿到最终脚本

| 流程 | 要求 |
| --- | --- |
| 野生/普通定点 | 复用 `EasyCon118Options`，核对生成 ECS 的最终赋值 |
| SID 遍历野生/定点 | 每个候选继承冻结偏好；子工程明确接入正确预校准记录路径与结果回填 |
| 孵蛋 | 增加录像请求字段、序列化和生成映射；遵循该流程已有出闪事件，不顺带新增孵化/抓捕行为 |
| TID → 御三家 | 连续流程请求增加御三家录像偏好，静态预生成和实际 TID/SID 得出后的动态生成两条路径都传入 |
| TID 刷号/SID 采集 | 不创造不存在的出闪或 2.0 命中事件，不把队伍内既有闪光当作本次新出闪 |
| 自选 ECS | 原地执行用户脚本，不因工具默认值开启而改写其参数 |

录像使用脚本现有的 Switch 出闪录像动作，不引入电脑持续录屏，避免新增采集占用和持续存储负担。

### 5.3 预校准边界不变

- Seed 预校准继续按当前游戏、机型、Seed 模式、正式/时间轴、流程类型、启动方案隔离；尤其不能跨启动方案套用。
- 正式版普通定点不应用帧数预校准；时间轴版野生/定点/孵蛋可用，御三家也可用。
- 仍只接受完整可信的本轮目标命中事件；普通识图成功、候选增多、看到出闪文字都不足以写入。
- SID 遍历的错误/未完成候选不写预校准。若完整目标已命中但非闪，只有 Seed/ADV/物种证明独立于猜测 SID 才可按既有规则更新，不把“SID 正确”当成已经证明。
- 本轮不调整修正量公式，不扩大反查窗口，不清空用户预校准文件。神秘礼物导致的帧作用域处理见下一节。

### 5.4 字段从控件到脚本的完整去向

`precalibration_check` 与 `capture_checks[3]` 分别是当前两个开关。实现时为后者增加具名引用 `record_shiny_video_check`，仍指向同一个控件，避免后续插入复选框后下标错位；迁移引用后不维护两份状态。

| 层次 | 更新预校准 | 出闪录像 |
| --- | --- | --- |
| GUI 默认 | `precalibration_check.setChecked(True)`，再恢复合法保存偏好 | `record_shiny_video_check.setChecked(True)`，再恢复合法保存偏好 |
| 应用配置 | `pyside6_settings.json.update_precalibration` | `pyside6_settings.json.record_shiny_video` |
| 普通野生/定点 | `EasyCon118Options.update_precalibration` | `EasyCon118Options.record_shiny_video` |
| 孵蛋 | 现有 `EggRunRequest.update_precalibration` | 拟新增 `EggRunRequest.record_shiny_video`，旧 worker 计划缺字段保留原语义 |
| 御三家连续请求 | 现有 `TidStarterFlowRequest.update_precalibration` | 拟新增 `TidStarterFlowRequest.starter_record_shiny_video` |
| 御三家静态生成 | `write_tid_starter_flow_bundle()` 现有传值 | 同一个 `EasyCon118Options(...)` 中新增录像传值 |
| 御三家动态生成 | `write_resolved_exhaustive_starter_project()` 现有传值 | 同样传值，不仅修改静态生成分支 |
| SID 遍历 | `extra.options` → `easycon_options` → 每次候选的 options | 同左，不能每次重新用 dataclass 默认值覆盖 |
| 最终 ECS | `$更新预校准 = 1/0` 与正确的写回标记 | `$出闪录像 = 1/0` |

新增字段必须同时进入请求校验、`to_dict/from_dict`、参数修正后 `replace()` 派生请求和计划 fingerprint。传布尔值，不接受字符串或 `1/0` 自动混作 bool；具体 ECS 输出才转换为整数。

**孵蛋完整配置也是一条独立链：**`CompleteWindow.egg_payload(full=True)` → `build_egg_full_config_payload()` → 配置读取校验 → `apply_egg_config(full=True)`。保存完整配置时两项偏好都写入；仅亲本配置不包含它们。旧完整配置缺字段时保持当前应用偏好，不能导入亲本或旧配置后把两个开关突然关掉。这里“供用户编辑的完整配置”与“已经冻结的 worker 运行计划”必须分开：前者缺字段继承当前偏好，后者缺字段遵守原版本语义。

### 5.5 设置读写只保留一个实际落盘入口

当前 `FrlgWindow.closeEvent()` 与 `CompleteWindow.closeEvent()` 都会写同一个设置文件。改为：

1. 拟新增 `FrlgWindow.settings_payload()`，返回公共路径、更新源、标签保护及两个偏好。
2. 子类仅覆盖 `settings_payload()` 并调用 `super()` 合并 SID/TID 源路径，不再第二次覆盖写文件。
3. 基类在确实允许关闭、任务已收尾时调用一次 `write_json_atomic()`。第一次因运行中而忽略关闭事件时不提前写出半状态。
4. `_load_settings()` 对两个字段区分“缺失”“合法 false”“非法类型”：缺失用 true，合法 bool 原样恢复，非法类型提示该偏好无效并保留原文件，不使用 `bool("false")`。
5. 初始化恢复时阻断开关信号，完成后统一刷新一次；不能在恢复一半时失效计划或打开设备。

验收例子：新数据目录首次启动两项都开；关闭录像、保留预校准后重启，仍为 `true/false`；之后导入仅亲本配置，仍为 `true/false`；生成御三家工程，最终 `$出闪录像 = 0`。这个连续操作用例比单独断言默认值更重要。

## 6. 功能五、六：存档滚轮切换与神秘礼物

### 6.1 数据与编辑界面

`SaveProfile` 增加 `mystery_gift_enabled: bool = False`；`create/from_dict/to_dict`、Store 的新增/更新/复制、编辑器与运行快照全部接通。

- 新建默认未开启；旧存档缺字段按未开启读取，不把字符串 `"false"` 当作真值。
- 保留当前存档文件版本的可选字段扩展；新增字段不要求重建旧文件。损坏字段明确报错并保留原文件。
- 管理存档弹窗增加“神秘礼物已开启”复选框，顶部摘要显示“神秘礼物：开/关”。此项记录游戏存档事实，不在游戏里自动开启功能。
- 复制存档保留该状态；由新建游戏流程生成的新存档草稿默认未开启，不能继承当前旧存档的礼物状态。
- 手动模式也可在存档信息内声明当前草稿的礼物状态；不选择已保存存档时，不让之前选过的存档状态残留。
- 保存继续使用原子写入，失败时 UI 与内存恢复到提交前状态，不产生“显示改了、文件没改”的半成功。

### 6.2 唯一的有效奇偶策略

新增纯函数解析有效方案，输入为流程上下文、用户非强制偏好与当前存档礼物状态，输出方案编号及强制原因：

1. 当前流程使用的存档开启神秘礼物 → 方案 1。
2. 孵蛋等已有强制方案 1 的流程 → 方案 1。
3. 其他情况 → 保留当前高级模式/默认规则下用户选中的方案。

界面组合框通过 `itemData` 保存真实 0/1 值，不继续散落 `1 - currentIndex()` 的转换。

- 强制时显示“方案 1：菜单调整”并禁用更改；悬停解释原因。
- 独立保存用户的非强制偏好。切回未开启礼物的存档时恢复偏好，不永远改成 1。
- GUI 生成层计算有效值，序列化到计划；worker/脚本生成层再次校验与存档快照一致。
- 配置导入声明礼物开启但方案 0 时，生成前规范化成 1并失效旧方案；已经生成的计划若出现矛盾，运行前拒绝并要求重新生成，不能运行时悄悄改参数。
- 最终 ECS 的 `$帧奇偶修正方案` 必须为 1；正式与时间轴都验收。
- 这里控制的是遭遇流程“帧奇偶修正方案”，不是 SID ADV 的奇偶。开启礼物不改变 SID 遍历的 1900/1901 和步长 2。

TID 新建游戏是另一份存档上下文。旧存档神秘礼物不能覆盖 TID 页目标 TID/SID、SID 搜索范围，也不能污染新游戏接续的御三家配置。直接针对既有存档运行御三家时，则使用该存档的状态。

### 6.3 与预校准的配合

不改 Seed 修正公式和现有启动方案索引。帧偏移的可复用范围增加有效奇偶方案及神秘礼物状态，防止切换后把不同菜单路径学到的帧值混用。

保持现有 Seed 记录键，将帧值改为其下按 `{effective_parity_scheme, mystery_gift_enabled}` 区分的小型子记录；规范化/读取/写回集中在 `automation/precalibration.py`，ECS 仍接收普通数值。具体结构与迁移见第 6.7 节。

- 新结果只更新本次帧子记录；Seed 值仍沿原上下文更新，不跨启动方案。
- 旧记录保留，旧 Seed 按原校验规则可读；缺少作用域证明的旧帧值保留为历史，不自动认定属于方案 1 或开启/关闭礼物。
- 如需文件 schema 升级，用显式迁移、备份及原子替换；迁移失败不覆盖原文件。
- 计划指纹与遍历断点包含实际策略，旧工程不会继续使用切档前的帧值。

这只是复用作用域隔离，不调整原来预校准误差的正负、计算方式或启用范围。

### 6.4 滚轮行为

- 监听顶部 `profile_chip`、其文字子控件和对话框 `profile_selector`，复用统一的 `select_profile/apply_profile` 路径。
- 鼠标向上选上一存档，向下选下一存档；按当前列表顺序，到头停止、不循环。
- 无存档不操作；手动输入状态首次滚动，向下选首项、向上选末项。滚轮不自动切进“未选择”占位项。
- 触控板细碎滚动累计到一个步进才切一次；不要对每个微小事件都持久化。
- 仅在指针位于指定控件时消费事件，不抢页面滚动或其他下拉框的滚轮。
- 生成、预检、启动、运行、停止收尾过程中禁止切档，顶部 chip 与选择框使用同一锁定判断。
- 若存在未保存手动草稿，先保留其快照供用户返回手动模式恢复；不把草稿自动写入旧存档。
- 切档原子更新摘要、当前身份、语言、主机、礼物状态及有效奇偶方案，并一次性使旧计划失效，避免信号连锁重复生成。
- **TID 页的目标 TID/SID 和延迟保持不变**，这项必须做回归测试。

### 6.5 存档字段的实际修改位置

| 文件 / 符号 | 施工内容 |
| --- | --- |
| `SaveProfile` | 末尾追加 `mystery_gift_enabled: bool = False`，不改变既有位置参数 |
| `SaveProfile.create()` | 新增仅关键字参数；严格验证 bool；合法 `false` 不被默认值替换 |
| `SaveProfile.from_dict()/to_dict()` | 缺字段默认 false、序列化总是写 bool；不丢语言/地区字段 |
| `SaveProfileStore.add()/update()` | 明确透传；写失败继续使用 `_commit()` 原有内存回滚 |
| `SaveProfileStore.duplicate()` | 使用原对象值，不通过新建默认把礼物状态变成关闭 |
| `ProfileManager.__init__()/select()/new()/save()` | 新增复选框、载入、重置及保存；`new()` 必须重置礼物状态，不能残留上一条 |
| `ProfileManager.prefill_new()` | TID 连续流程创建的新档草稿显式 false；取消窗口不保存 |
| `FrlgWindow.apply_profile()` | 同步当前存档礼物状态后统一解析有效奇偶，阻断中间信号 |
| `FrlgWindow._profile_summary()` | 判断是否仍匹配已保存档时增加礼物状态，修改草稿后不能仍显示完全匹配原档 |
| `collect_inputs()/FormReader.egg()/flow()` | 普通/孵蛋取当前存档快照；TID 新建链用新档上下文，不取顶部旧档 |

保存条目示例（演示数据）：

```json
{
  "id": "profile-1",
  "name": "日版火红",
  "game": "火红",
  "language": "日文",
  "nx_model": 2,
  "tid": 12345,
  "sid": 23456,
  "mystery_gift_enabled": true
}
```

字段的含义是用户声明的存档属性，不是工具检测结果。开始确认框显示“存档：日版火红；神秘礼物：已开启；有效帧奇偶：方案 1（强制）”，避免用户误以为只是一个不影响运行的备注。

### 6.6 策略解析接口及恢复例子

拟新增 `automation/frame_parity.py`：

```python
@dataclass(frozen=True)
class FrameParityPolicy:
    requested: int
    effective: int
    forced: bool
    reason: str | None

def resolve_frame_parity(
    *, requested: int, mystery_gift_enabled: bool, is_egg: bool
) -> FrameParityPolicy: ...
```

`requested` 是按现有高级模式规则得到的用户偏好，不是控件被强制显示后的数值。普通模式先按原规则得到 1；高级模式取组合框的 `itemData()`。resolver 不读 Qt、不访问存档文件；非法 requested 先报错，不能因礼物强制而掩盖非法输入。

GUI 单独记住 `preferred_frame_parity_scheme`，拟作为应用设置中的 0/1 字段保存：

1. 高级模式在普通存档选方案 0 → 偏好为 0、有效值为 0。
2. 切到礼物开启档 → 偏好仍为 0、显示/有效值为 1、控件禁用。
3. 重启仍选礼物档 → 继续强制 1，但偏好仍保留 0。
4. 切回礼物关闭档 → 恢复 0。
5. 进入孵蛋 → 有效 1；返回原模式 → 再按存档规则恢复，不能把偏好永久写成 1。

仅当用户可操作组合框并主动更改时更新偏好；程序设置显示值用 `QSignalBlocker`，不把强制值当作用户新偏好保存。

普通选项拟新增 `EasyCon118Options.mystery_gift_enabled`，孵蛋请求也显式携带该状态。生成时断言 options 中的有效方案与 resolver 一致。TID 连续流程的 `starter_frame_parity_scheme` 仍走用户偏好/原默认规则，但礼物输入取新建存档的 false；不为新建链复制顶部旧档的状态。

### 6.7 帧预校准格式与兼容边界

这里涉及的不是第 4 项“默认开启”本身，而是第 6 项切换菜单策略后避免复用错误帧值的配套改动。需要单独提交、单独验收；不得顺带改变 Seed 计算或自动清零记录。

拟将预校准文件升为 schema 2，概念结构如下；示意键与数值仅用于说明：

```json
{
  "schema": 2,
  "records": {
    "原有context哈希": {
      "context": {"game":"fr","nx_model":2,"seed_mode":0,"entry":"TIMELINE","kind":"STATIC","seed_startup_scheme":0},
      "seed_ns1": null,
      "seed_ns2": 12,
      "frames": {
        "parity=1;gift=0": {"frame_ns1":null,"frame_ns2":-3,"held_pre":null,"pickup_pre":null}
      },
      "legacy_frames": {"frame_ns1":null,"frame_ns2":-2,"held_pre":null,"pickup_pre":null}
    }
  }
}
```

Seed 上下文键和 `seed_ns1/seed_ns2` 的语义保持不变；`frame_ns1/frame_ns2/held_pre/pickup_pre` 均属于帧值，一起隔离，不能只隔离普通帧却遗漏孵蛋 Held/Pickup。

实施接口：

- `load_store()` 接受 schema 1/2；schema 1 只做内存规范化，不因为打开工具就重写文件。
- `read_record(..., frame_scope=...)` 从指定子记录返回原生成器需要的平铺值；没有该作用域时帧字段为 `None`，表示没有可复用记录，不是假造已学习的 0。
- `update_record(..., frame_scope=...)` 只合并当前作用域和此次明确提供的字段，不覆盖别的帧子记录。无作用域时不允许写帧值。
- 首次真实更新旧文件前生成不覆盖已有文件的原始备份，再原子写 schema 2。备份或替换失败时原文件保持可恢复，不报告“已更新”。
- 旧文件不能证明帧值来自哪种奇偶/礼物状态，原值放 `legacy_frames` 原样保留，不随意归入默认方案。这意味着旧帧可能需要重新学习一次；日志必须明确说明，不能让用户以为数值丢了。
- 新工程的预校准 manifest 增加 `frame_scope`，成功标记升级 `V=2` 并包含 `PARITY/GIFT`；`update_from_manifest()` 验证两边一致后写回。
- 老工程 `V=1` 结果仍可按旧上下文校验 Seed，但不能覆盖新建的有作用域帧记录。这里是必要的数据读取边界，不恢复旧版本生成逻辑。

迁移前后必须对比：所有 Seed 值和启动方案键相同、所有旧帧值可在备份及 legacy 中找到、其他存档文件未写入。回退旧程序使用备份需要用户明确选择，不能直接用旧备份覆盖之后新学到的记录。

### 6.8 滚轮事件和切档事务

拟在 `pyside_app/profiles.py` 增加 `ProfileWheelFilter`，只负责把事件转换为步数；实际切档仍由主窗口执行。不要直接在过滤器里同时写 JSON、重建物种列表和改表单。

确定的输入规则：普通滚轮累计 `angleDelta().y()` 到 120 为一步；仅有 `pixelDelta()` 的触控板以 40 个垂直像素为一步。向上为上一条，向下为下一条；一个事件跨多步时直接计算最终索引，只提交一次。横向滚动忽略，指针离开或 300 ms 无事件后清除余量，防止下一次悬停突然跳档。上述阈值是本轮 UI 设计值，不是游戏参数。

主窗口拟增加 `select_profile_id(profile_id, *, source)`，原下拉槽和滚轮都调用它：

1. 检查统一 busy 状态：`job/running/closing`，以及生成和启动准备状态；被锁定时消费目标控件上的切档滚轮但不改变当前值。
2. ID 与当前相同时直接返回，不写磁盘、不使计划失效。
3. 读取并校验目标条目，预先计算待应用的字段、下拉选项及有效策略，保存当前草稿和选择快照。
4. 调用 Store 选择提交；写失败恢复选择框并展示错误，不先把一半字段切到新档。
5. 使用信号阻断一次性应用已验证字段；最后统一刷新类别、摘要、奇偶状态和计划失效。异常时以可验证的已保存选择恢复一致界面，不隐瞒回滚失败。

草稿仅保存在当前 GUI 会话，不因为滚轮切换产生一批临时存档。选择“未选择（手动输入）”时恢复草稿；关闭程序是否持久化其他手动字段沿用原规则，不借此增加一套完整表单自动保存。

## 7. 功能七：自选脚本测试自动跳日志并实时显示

### 7.1 启动时机

本项不另建运行器，也不要求把用户 ECS 转成内置工程。

统一生命周期为：

1. 选择 ECS → 原有参数/路径/后端预检。
2. 用户确认开始 → 创建本次运行身份、日志路径，清理上次显示状态。
3. **在调用 `QProcess.start()` 前切到运行日志页**，显示“正在启动”、脚本路径及所选后端。
4. `started` 只更新为运行中，不重复抢回用户手动切走的页面。
5. 输出实时追加；退出时排空剩余缓冲并记录完成/失败/手停状态。

前置校验失败或取消确认不跳页，留在参数页便于修正；已接受启动后发生找不到程序、权限错误等，日志页直接展示失败原因。

需要同时收敛 `window.request_start()` 与 `migration.request_start()` 的重复初始化逻辑，提供一个小型共用启动准备函数，避免只有普通模式提前跳页。

### 7.2 日志与后端覆盖

- 兼容运行器与原始 `ezcon.exe` 均继续走 `run_easycon_logged.py`；没有按键状态协议也必须有日志。
- 保留 stdout/stderr 汇合、增量 UTF-8 解码、无换行片段实时显示与最后一行补齐。
- 包含中文/空格路径、启动即退出、仅 stderr、异常但退出码为 0 的既有识别规则都要覆盖。
- 启动时的日志标题只描述当前运行；换自选文件后不能复用上一份日志或上一份预览地址。
- 日志滚动保留“用户查看旧行时不强拉到底”的现有行为。
- 自选脚本的代码和参数原地保持，不因默认录像、预校准、神秘礼物策略而静默改写。对无法声明存档上下文的手写脚本，不声称已经替用户强制奇偶方案。
- 运行结果继续落盘，错误/完成摘要在日志页可见；按键卡无数据时明确显示后端不支持/正在等待状态，不影响文本日志。

主要修改：`pyside_app/window.py`、`migration.py`、`workflows.py`；`run_easycon_logged.py` 仅在测试暴露缺口时修改，不重复造一套日志通道。

### 7.3 共用启动函数的调用次序

拟新增 `FrlgWindow.begin_accepted_run(command, *, prepared_wild=None, prepared_workflow=None)`，两个现有 `request_start().ready(...)` 在确认通过后调用。它不是新的 worker，而是收敛目前两处重复的 GUI 初始化。

执行顺序固定为：

```text
再次比对冻结 fingerprint
→ 绑定本次 prepared / RunCommand
→ 初始化通知去重、输出解码器和残行缓存
→ 清理本次日志显示，重置终态已处理标志
→ 初始化只读手柄和输入状态会话
→ running=True，锁定输入
→ 切到 logs，写“正在启动 + 脚本路径 + 后端”
→ 调用现有 before_workflow_start（仅工作流需要）
→ 设置工作目录并启动 QProcess
```

这里使用 `RunCommand.run_id` 关联计划、日志和状态协议；窗口 `_run_id` 的通知用途若继续独立，必须明确区分，不能顺手把两个 UUID 混用导致报告匹配失败。

QProcess 启动的是 Python worker/打包 worker，`started` 只能说明这个工作进程启动成功，不能提前宣称 EasyCon 或游戏已经开始执行。后续 EasyCon 启动异常由既有日志包装器输出，仍显示在同一页。

### 7.4 终态与异常处理必须只执行一次

| 情形 | 页面与日志 | 清理行为 |
| --- | --- | --- |
| 预检失败、用户取消确认 | 保留配置页，原有错误提示 | 不清上次日志、不创建假运行 |
| QProcess `FailedToStart` | 已在日志页；显示具体启动路径及错误 | 解除输入锁、清空观察状态；不能等待永远不会来的正常 finished |
| worker 启动但 EasyCon 失败 | 展示包装器 stdout/stderr 和退出结果 | 按已有错误判定收尾，不当作正常完成 |
| 子进程瞬间正常退出 | 启动提示、实际输出、完成结果都能看见 | 排空输出后收尾；不漏最后一行 |
| 用户手停 | 显示“用户停止” | 沿现有停止机制，不报脚本成功；取消未完成的状态请求 |
| finished/error 重复到达 | 不重复追加终态、通知或弹窗 | 用本次运行 ID 与终态已处理标志去重 |
| 用户运行中切到别页 | 保持用户选择 | 后续 started/输出/状态事件不强制重新跳 logs |

对 QProcess 本身未能启动、因而 worker 根本没创建日志文件的情况，在已确认没有 worker 写入的前提下，将启动错误保存到本次 `log_path`；不能为了记启动提示而让 GUI 与 worker 同时写一个日志文件。

### 7.5 本项的最短可复现验收

复用 `tests/test_pyside_remaining.py` 已有 `test_actual_child_process_completes_and_releases_workflow_inputs` 的 QEventLoop + 真实无设备子进程方式，新增完整 `script_test` 入口用例，而不是只手工调用 `_process_started()`。

测试准备使用临时目录里的自选脚本，记录开始前 SHA-256；模拟设备预检和确认框，实际启动测试用子进程，依次输出中文、stderr、一段不带换行的文本、最后半行。通过事件等待断言：第一段输出时页面已经是 logs；后续增量可见；退出后最后半行存在；控件解锁；自选 ECS 哈希未变。

然后分别替换为不存在的可执行程序、立即退出的程序、可停止的等待程序，覆盖三类终态。兼容/原始后端各跑一遍命令构建与生命周期用例；原始后端状态 URL 必须为空，但日志不为空。

## 8. 分阶段实施顺序

| 阶段 | 工作 | 完成门槛 |
| --- | --- | --- |
| A | 固定当前合并基线与现有配置样本；补失败用例 | 不改用户数据，先能复现限制与日志生命周期缺口 |
| B | 存档礼物字段、有效策略、偏好持久化与滚轮 | 数据迁移、TID 隔离、锁定与回滚测试通过 |
| C | SID 定点、模板传递、结构化目标证明与断点 | 搜索/生成/运行报告的模拟闭环通过，不误跳超限候选 |
| D | 录像/预校准参数贯通 | 野生、定点、孵蛋、御三家和遍历生成工程均核对实际参数 |
| E | 后端按键状态补丁、构建、协议测试 | 可从固定源重建；无设备状态序列/缓冲/异常测试通过 |
| F | GUI 状态模型、手柄观察态与操作卡 | 不二次连接串口，阶段切换和异常收尾不残留按键 |
| G | 自选脚本日志生命周期统一 | 两种后端及启动失败/快速退出/无尾换行均通过 |
| H | 完整回归、离线脚本检查与用户实机验收 | 分开报告软件验证和实际设备验证；未经验证的路线不写“已通过” |

B～G 各阶段使用可独立审阅的提交边界，避免把后端二进制、业务策略和 UI 混成难回退的大提交。不删除旧日志、用户存档或断点。

## 9. 测试与验收清单

### 9.1 自动化测试

优先扩展现有测试，不用只检查源码字符串的断言代替行为验收：

| 范围 | 关键用例 |
| --- | --- |
| SID 请求 | 野生/定点有效组合；非法路线；方法不被改写；下限保留；上下限冲突；正式/时间轴一致 |
| SID 奇偶/断点 | 1900/1901、每次 +2；自定义错误奇偶拒绝；停止/超限不前进；类型/模板/礼物变化不混断点 |
| SID 证明 | 只有文字出闪不得成功；非目标闪光暂停；精确非闪才实测排除；正常退出也不能替代证据；旧运行证据忽略 |
| 生成参数 | 两默认缺字段为真；显式 false 保留；孵蛋与两种御三家生成路径均传入；自选 ECS 字节不变 |
| 预校准 | 正式普通定点不应用帧值；时间轴/御三家可用；启动方案隔离；帧作用域隔离；不完整结果不更新 |
| 存档 | 旧字段兼容、严格 bool、新建/编辑/复制、保存失败回滚、草稿保留、TID 目标不被覆盖 |
| 奇偶策略 | 礼物强制 1、退出强制恢复偏好、孵蛋仍强制、导入矛盾处理、worker 不可绕过、SID ADV 规则不变 |
| 滚轮 | 顶部文字子控件、上下边界、无/单存档、手动状态、细粒度触控板、运行/生成/预检锁定 |
| 输入状态 | 单键/组合键、短按自动松开、长按、双摇杆、Reset、故障保护拒绝、序列缺口、失联、旧会话晚到 |
| 手柄 | 运行中打开只观察；开关浮窗不发送释放；空闲手动仍可用；结束不自动抢串口 |
| 日志操作卡 | 与手柄同源；切页返回最新状态；原始后端降级；无按键不冒称 WAIT；重绘有界 |
| 自选测试 | 两后端、启动失败、瞬间退出、中文路径、stderr、无换行、无尾换行、手停、切页不被反复抢回 |

相关既有测试：`tests/test_sid_traversal.py`、`test_save_profiles.py`、`test_precalibration.py`、`test_tid_starter_flow.py`、`test_easycon118_egg.py`、`test_pyside_controller.py`、`test_pyside_backend.py`、`test_pyside_remaining.py`、`test_pyside_monitor.py`、`test_script_test.py`、`test_easycon_logged.py`、`test_worker_commands.py`、`test_easycon164a_backend.py`。状态协议与策略解析可新增针对性的测试文件。

### 9.2 离线检查

实施后执行，不把本方案中的命令当作已运行结果：

```powershell
Set-Location -LiteralPath 'D:\Codex\火叶乱数\frlg-auto-rng'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -m unittest tests.test_sid_traversal tests.test_save_profiles tests.test_precalibration tests.test_pyside_controller tests.test_pyside_backend tests.test_pyside_remaining tests.test_script_test tests.test_easycon_logged tests.test_worker_commands tests.test_easycon164a_backend tests.test_tid_starter_flow tests.test_easycon118_egg -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
git diff --check
```

- 使用项目实际可用解释器；若 `.venv` 位置不同先核对，不安装与任务无关的环境。
- 新增后端补丁按现有构建脚本重新构建，并运行对应 .NET 协议/报告测试。
- 分别生成正式/时间轴代表工程；覆盖英/日、NS1/NS2 的当前已支持组合，不能拿一份英文野生工程代替全流程验收。
- 用真实 EasyCon `format` 或项目已有运行时预检验证生成脚本，不连接单片机，不启动游戏。
- 正式 GUI 以独立测试数据目录做界面验收，避免改写日常配置。没有日志/设备状态时用模拟事件验证布局。

### 9.3 实机验收

由用户确认可测试后再操作设备，至少检查：

1. 一条已支持野生与一条普通定点的 SID 候选验证，含中途停止和继续。
2. 不同领取/捕获型定点逐类补验；不能以普通定点通过推断游走、礼物等全部通过。
3. TID → 去研究所 → 球前存档 → 御三家整条链的按键回显与监视并开，跨子进程不丢状态。
4. 运行时打开/关闭手柄浮窗、拖动主窗口、切日志页，脚本操作不被打断。
5. 神秘礼物开/关存档的最终脚本参数与实际菜单路径相符；TID 新建存档不继承旧档状态。
6. 出闪录像触发与现有抓捕/停止策略一致；预校准只在合法命中后更新。

本方案没有执行这些实机操作，也不引用此前“若干测试通过”作为本轮新增功能已验证的证据。

## 10. 交付与回退

- 本次交付仅为本文，功能代码保持不变；当前不提交、不推送、不打包。
- 后续明确开始实施后，先保存基线与会修改的配置备份，按阶段提交。若届时仍有“本地测试后再推送”的限制，继续本地交付；否则完成相关检查后按仓库既定流程推送功能分支/PR 触发 Actions，不顺便发布 Release。
- 后端改动保留上一个 manifest 与补丁基线，发生时序/性能回归可单独撤回状态回显。无状态协议时 UI 明确降级，脚本日志不能随之失效。
- 配置迁移保留原文件备份，回退时只处理新增字段/帧子记录，不覆盖期间产生的新存档和有效断点。
- 交接列出七项逐项结果、实际测试数量、未验收路由、实机待办和文件清单。不得只写“都完成了”而遗漏第 7 项。

## 11. 文件、函数和字段的施工矩阵

这一节把“要改哪里”固定到当前仓库的真实符号。函数名是实施锚点，不是要求把所有逻辑塞进这些函数；如果实施前上游已经重命名，必须先更新本表和测试引用，再开始改动，不能静默绕过。

### 11.1 GUI 和工作流层

| 文件 | 当前符号 | 本轮操作 | 禁止的顺手改动 |
| --- | --- | --- | --- |
| `pyside_preview.py` | `FrlgPreviewWindow._build_wild_page()` | 增加定点遍历可见状态、定点可用原因、脚本操作卡的稳定对象引用；保留现有布局键 | 不把定点所有类别直接标成可用；不删除现有野生输入 |
| `pyside_preview.py` | `_refresh_wild_type()`、`_refresh_wild_controls()` | 统一调用 `automation.support.get_route_support()` 的轻量结果；区分“未填写”“不支持”“可生成” | 不用 `currentIndex()` 或显示文本作为唯一业务判定 |
| `pyside_preview.py` | `_build_logs_page()`、`_build_script_test_page()` | 给日志页动作卡、脚本测试页准备稳定控件引用和空态文案 | 不再用布局下标猜控件；不让动作卡接管普通日志文本 |
| `pyside_app/migration.py` | `collect_workflow()` | 将静态类别、模板、有效奇偶、录像/预校准、存档快照写入 `WorkflowInputs.extra`；定点请求不再被野生条件拒绝 | 不从全局当前控件重新读取已冻结的运行参数 |
| `pyside_app/migration.py` | `_refresh_wild_controls()`、`refresh_state()` | 复用同一个可用性结果；显示明确阻塞原因；保留 TID/SID 页字段 | 不在刷新 UI 时改变断点、清空目标 TID/SID 或写磁盘 |
| `pyside_app/migration.py` | `request_start()`、`before_workflow_start()`、`_process_started()`、`_process_finished()` | 接入统一运行生命周期；自选脚本在确认后、启动前切日志页；动态御三家阶段重建输入会话 | 不在 `_process_started()` 再次无条件抢回用户已切换的页面 |
| `pyside_app/migration.py` | `egg_payload()`、`apply_egg_config()` | 完整孵蛋配置透传两个默认开关和神秘礼物策略；亲本配置不携带运行偏好 | 不因读取旧亲本配置把录像/预校准改为关闭 |
| `pyside_app/window.py` | `collect_inputs()`、`_lock_run_inputs()` | 将具名开关、存档快照、有效奇偶和按键观察会话加入冻结指纹/锁定范围 | 不在运行中允许滚轮切档或改有效奇偶 |
| `pyside_app/window.py` | `_load_settings()`、`closeEvent()` | 缺字段默认开启、显式 `false` 保留；公共设置只写一次并原子替换 | 不用 `bool(value)` 解析字符串 `"false"` |
| `pyside_app/window.py` | `apply_profile()`、`select_profile()`、`_profile_summary()` | 一次性应用存档字段并刷新有效策略；滚轮与下拉复用同一事务；保留 TID 目标草稿 | 不让切换存档覆盖 TID 页目标 TID/SID、SID ADV 或延迟 |
| `pyside_app/manual.py` | `ControllerWindow.open_overlay()`、`press()`、`release()`、`keyboard_transition()`、`release_all()` | 运行中允许只读观察；观察态所有输入写入直接忽略；空闲手动释放逻辑保留 | 不为打开浮窗重新连接 COM，不在关闭观察窗时发送释放 |
| `pyside_app/manual.py` | `ControllerOverlay.set_active()`、`hideEvent()`、`closeEvent()` | 观察态和手动态分离；结束运行清空观察状态但不抢回串口 | 不把观察到的按键写回手动 `pressed` 集合 |
| `pyside_app/controller_layout.py` | `ControllerLayout.refresh()` | 接受按钮/HAT/摇杆的只读快照；当前按住和最近动作分开渲染 | 不按固定四方向替代真实摇杆坐标 |
| `pyside_app/accessories.py` | `run_started()`、`run_finished()`、`release_for_run()` | 管理观察会话生命周期，维持已有视频监视单路采集 | 不新增第二个采集线程或串口连接 |
| `pyside_app/workflows.py` | `WorkflowInputs.fingerprint()`、`_prepare_workflow_in_directory()`、`prepare_workflow_run()` | 将模板、静态类别、有效策略、预校准作用域和输入会话 ID 进入计划；每个 SID 候选创建独立子会话 | 不让 `label_supervision` 开关决定是否传递 `run_id` |

### 11.2 乱数、计划和持久化层

| 文件 | 当前符号 | 本轮操作 | 输出/错误要求 |
| --- | --- | --- | --- |
| `automation/support.py`、`automation/static_targets.py` | `RouteSupport`、`get_route_support()` 及目标白名单 | 为野生/定点返回 `supported/reason/route_key`；静态目标按路线逐类放行 | UI 与 worker 使用同一结果；不支持时在生成前报出类别和原因 |
| `sid_traversal.py` | `traversal_context()`、`SIDTraversalSession.begin_candidate()`、`complete_non_shiny()`、`pause()`、`hit()` | 升级上下文/断点版本；新增 `skip_candidate()`、尝试 ID、候选阶段和超限不推进规则 | `SearchWorkLimitError`、用户停止和设备错误必须留下当前候选 |
| `run_sid_traversal.py` | `_load_plan()`、`_request_from_payload()`、`run_traversal()` | 校验模板、静态类别、策略、目标下限和目标证明；拆开无目标/非闪排除/超限暂停 | 事件必须匹配 `RUN + ATTEMPT`，不能用关键字出闪判定成功 |
| `automation/easycon118.py` | `EasyCon118Options`、`EggRunRequest`、`build_run_command()` | 增加明确布尔字段和有效奇偶；命令始终传运行 ID/阶段，原始后端不传不支持参数 | 旧计划缺字段按版本语义；非法 bool/策略拒绝，不静默默认 |
| `automation/tid_starter_flow.py` | `TidStarterFlowRequest.validate()`、`to_starter_search_request()`、`build_starter_run_plan()`、`write_*_starter_project()` | 御三家静态/动态两条生成路径都接入录像、预校准作用域和存档快照 | TID 新建上下文明确礼物关闭；不继承顶部旧存档状态 |
| `automation/precalibration.py` | `PrecalibrationContext`、`load_store()`、`read_record()`、`update_record()`、`update_from_manifest()` | schema 1/2 规范化；帧值按启动方案/正式时间轴/奇偶/礼物作用域隔离 | 写入前备份、原子替换；不完整命中不能更新；Seed 与帧分别校验 |
| `save_profiles.py` | `SaveProfile.create/from_dict/to_dict()`、`SaveProfileStore.add/update/duplicate()` | 增加严格 bool 的 `mystery_gift_enabled`；旧文件缺字段默认 false | 写失败恢复内存和选择；不覆盖旧文件，不把字符串当 bool |
| `pyside_app/profiles.py` | `ProfileManager.prefill_new()`、`new()`、`save()`、`select()` | 增加复选框和草稿字段；滚轮只发出选择请求，不直接写 Store | TID 预填取消不落盘；复制保留状态，新建重置状态 |
| `run_easycon_logged.py` | `run_logged()`、`consume_text()`、`main()` | 保留 stdout/stderr 解码和末行排空；仅在状态协议缺口有测试证据时扩展 | 脚本测试不丢中文、stderr、无换行尾部；不重复建日志通道 |

### 11.3 EasyCon 兼容运行器层

| 源文件 | 观察点 | 具体约束 |
| --- | --- | --- |
| `.build/easycon164a-clean/src/EasyCon.Core/GamePadAdapter.cs` | `ClickButtons()` 进入设备排程的位置 | 只传递固定大小状态，不在设备锁内序列化、HTTP 或调用 GUI |
| `.build/easycon164a-clean/src/EasyCon.Device/NintendoSwitchPriv.cs` | `Loop()`、`WriteReport()`、自动释放 | 观测发生在实际报告提交后；报告序列、保持时长和 Reset 不改变 |
| `.build/easycon164a-clean/src/EasyCon.Device/JoyStickDevice.cs`、`Utils/SwitchReport.cs` | 按钮/HAT/摇杆编码 | 使用真实报告值，摇杆保留 0～255 原始坐标，HAT 与摇杆不混淆 |
| `.build/easycon164a-clean/src/EasyCon2.CLI/Program.cs`、`MjpegPreviewServer.cs` | HTTP 服务生命周期 | `/capabilities`、`/input-state` 与视频首帧解耦；服务只绑定 loopback |
| `tools/patches/easycon164a-input-state-v1.patch` | 可重放补丁 | 固定源 commit、patch id、manifest 三者一致；不能只替换 EXE 或修改期望哈希 |

## 12. 运行数据契约和示例

下面的示例用于测试夹具和日志审阅。示例中的 ID、时间和数值是占位数据，实施时不能把示例值写入真实计划。

### 12.1 SID 定点遍历计划

```json
{
  "version": 2,
  "mode": "sid_traversal",
  "run_id": "run-uuid",
  "source": "formal",
  "template_name": "NS火叶全自动一键乱数2.0.ecs",
  "encounter_kind": "static",
  "route_key": "starter_bulbasaur",
  "request": {
    "game": "fr_nx",
    "target_species": "BULBASAUR",
    "method": "Static1",
    "min_advance": 1901,
    "max_advance": 3000,
    "named_rival": false
  },
  "easycon_options": {
    "frame_parity_scheme": 1,
    "mystery_gift_enabled": false,
    "record_shiny_video": true,
    "update_precalibration": true
  },
  "verification_protocol": 1,
  "script_fingerprint": "sha256:..."
}
```

生成前必须重新计算 `route_key`、`encounter_kind` 和有效奇偶，不能只相信 JSON 里的派生字段。`min_advance` 是用户下限；`max_advance` 是目标个体搜索上限；SID ADV 的起点和步长由 `named_rival` 决定，二者不能互相替代。

### 12.2 SID 断点状态

```json
{
  "schema": 3,
  "context_hash": "sha256:...",
  "status": "paused",
  "next_sid_advance": 1905,
  "current_candidate": {
    "sid_advance": 1903,
    "sid": 1342,
    "attempt_id": "attempt-uuid",
    "candidate_phase": "search_work_limit"
  },
  "tested_non_shiny_count": 4,
  "skipped_count": 1,
  "last_result": "search budget exhausted",
  "context": {
    "encounter_kind": "static",
    "route_key": "starter_bulbasaur",
    "template_name": "formal",
    "named_rival": false,
    "effective_frame_parity_scheme": 1,
    "mystery_gift_enabled": false
  }
}
```

`current_candidate` 存在时，恢复首先展示它并要求继续/重新验证；只有 `complete_non_shiny` 或 `skip_candidate` 已原子提交后才允许 `next_sid_advance` 前进。恢复不能根据最后一行日志猜测是否已经完成。

### 12.3 按键状态响应

```json
{
  "protocol": 1,
  "run_id": "run-uuid",
  "session_id": "session-uuid",
  "stage_id": "sid_candidate",
  "seq": 17,
  "source": "device_report",
  "connection": "connected",
  "snapshot": {
    "buttons": ["A"],
    "hat": "CENTER",
    "left_stick": [128, 128],
    "right_stick": [128, 128]
  },
  "events": [
    {"seq": 17, "at_ms": 1200, "snapshot": {"buttons": ["A"], "hat": "CENTER"}}
  ],
  "history_gap": false
}
```

GUI 接受条件按顺序为：JSON 大小不超过 256 KiB → `protocol` 支持 → `run_id/session_id` 匹配 → `seq` 不倒退 → 枚举和坐标合法。任一条件失败只清理观察显示并保留文本日志，不停止运行器。`history_gap=true` 时只使用最新快照，禁止补造按键事件。

### 12.4 设置、存档和预校准的兼容规则

| 数据 | 缺字段 | 合法关闭值 | 非法值 | 写入时机 |
| --- | --- | --- | --- | --- |
| 应用设置 `update_precalibration` | `true` | 保留 `false` | 报告无效并保留原文件 | 窗口正常关闭时一次原子写入 |
| 应用设置 `record_shiny_video` | `true` | 保留 `false` | 报告无效并保留原文件 | 同上 |
| 存档 `mystery_gift_enabled` | `false` | 保留 `false` | 拒绝该条目，原文件不变 | 用户明确保存时 |
| 预校准帧作用域 | 无可复用帧 | `null` 仍表示无记录 | 该字段/作用域拒绝 | 完整合法命中后备份+原子更新 |

## 13. 七项功能的实际执行顺序

### 13.1 先建立可回退基线

1. 记录 `git rev-parse HEAD`、工作区状态、原始脚本/标签/运行器 manifest 摘要。
2. 复制 `save_profiles.json`、`pyside6_settings.json`、`precalibration.json`、SID 断点目录到带时间戳的验证目录；复制只读，不修改用户日常文件。
3. 运行当前与本轮相关的失败用例，记录“现状失败”而不是先修改断言。
4. 建立功能分支内的阶段提交边界：数据模型 → SID → 运行器协议 → GUI → 测试/文档。

若第 1～3 步无法完成，停止实现并先修正测试夹具或路径；不能用“测试环境不同”掩盖无法建立基线。

### 13.2 数据模型阶段

1. 先改 `SaveProfile`、应用设置读取和纯函数 `resolve_frame_parity()`。
2. 为旧 JSON、显式 false、非法字符串、写入失败分别建立夹具。
3. 改 `WorkflowInputs.fingerprint()`，确认新增字段变化会使旧准备结果失效，未变化不会产生伪失效。
4. 在没有 GUI 的情况下验证 TID 新建上下文始终 `mystery_gift_enabled=false`，当前存档流程使用保存值。

完成门槛：单元测试通过；旧配置文件字节内容未被打开工具自动重写；手动回退可恢复原文件。

### 13.3 SID 定点阶段

1. 把路线支持结果做成纯函数，先为每个类别列出允许/拒绝样例。
2. 升级 `traversal_context` 和断点 schema；先实现读旧断点只展示、不自动续跑。
3. 将 `SearchWorkLimitError`、无目标、精确非闪、目标闪光分别映射到四个结果枚举。
4. 用模拟目标验证同一 SID ADV 重试不会重复推进；模拟崩溃验证 `begin_candidate()` 已写入当前候选。
5. 注入结构化目标证明，运行前检查锚点数量和幂等性；格式检查失败不得生成半成品工程。
6. 最后接入 GUI 的定点开关与报告显示。

完成门槛：野生旧路径的断点与结果不变；定点非法路线在生成前拒绝；超限不会跳过；结构化证明缺失不会报成功。

### 13.4 EasyCon 按键状态阶段

1. 在模拟 `NintendoSwitch` 报告循环中先保存改动前的报告序列和时间分布。
2. 增加无锁/有界状态缓冲和 HTTP 能力探测；运行无 GUI 订阅时设备行为必须一致。
3. 建立多阶段 session 标记；先测旧 session 晚到被丢弃，再测新 session 的首个快照。
4. 仅在协议测试通过后构建兼容运行器；核对 patch id、manifest 和实际二进制。
5. Python 端先接收并记录状态，再接手柄和日志卡渲染，避免 UI 问题污染协议诊断。

完成门槛：模拟 10,000 次状态写入不阻塞控制线程，报告序列完全一致；接口 404 时脚本仍正常执行、UI 明确降级。

### 13.5 GUI、滚轮和自选脚本阶段

1. 将日志动作卡改为稳定对象引用，加入空态/失联/原始后端提示。
2. 将手柄改成空闲手动与运行观察两个显式状态；运行观察不能调用串口连接或释放。
3. 把 `select_profile_id()` 作为下拉和滚轮唯一入口，补写失败回滚和运行中锁定。
4. 合并 `window.py` 与 `migration.py` 的启动准备，确认预检失败不跳页、确认后启动失败留在日志页。
5. 自选脚本分别覆盖兼容后端、原始后端、中文路径、立即退出和最后半行输出。

完成门槛：用户运行中拖动窗口、切换日志页、打开/关闭观察窗均不改变脚本控制；自选脚本页面不丢首行或末行。

### 13.6 集成和交付阶段

1. 先跑数据模型和 SID 定向测试，再跑 Python GUI 测试。
2. 构建 EasyCon 兼容运行器并重新跑协议/格式检查。
3. 用独立 `--data-dir` 运行正式 GUI 截图验收，不连接设备、不写日常配置。
4. 运行完整测试和 `git diff --check`，把失败分为代码回归、环境缺件、实机未验收三类。
5. 最后由用户确认实机窗口和路线；未实测类别在交付报告中保持“未验收”。

## 14. 验收用例到预期证据的映射

| 用例 | 最小输入 | 必须观察到的证据 | 失败时不能声称 |
| --- | --- | --- | --- |
| 定点有效性 | 一个已支持静态目标、一个不支持事件目标 | UI 与生成器给出同一 `route_key`/原因 | “所有定点都支持” |
| SID 下限 | 起点 1901 与起点 1900 各一组 | 首候选、断点和报告一致；每次 +2 | “从 0 开始搜索” |
| SID 超限 | 模拟搜索抛 `SearchWorkLimitError` | 状态 paused、当前候选保留、无下一候选 | “该 SID 已验证失败” |
| SID 证明 | 普通出闪文本、非目标闪、完整目标事件各一组 | 只有完整事件可命中；其他均暂停或排除 | “看到出闪就是 SID 正确” |
| 按键协议 | A 按下/释放、斜向 HAT、摇杆非中点 | seq 单调、坐标不变、GUI 两端一致 | “游戏收到了按键” |
| 协议失联 | 404、超时、历史缺口、旧 session | 显示未知/缺口，文本日志继续 | “脚本失败”或“仍按住” |
| 默认值 | 空设置目录、显式 false 设置 | 首次 true；重启 false 仍 false | “每次启动都自动打开” |
| 神秘礼物 | 普通档/礼物档/孵蛋/TID 新档 | 有效方案分别正确；TID 新档不继承 | “SID ADV 奇偶也被强制” |
| 滚轮事务 | 多步滚轮、边界、运行中、写失败 | 一次切换、边界不循环、失败回滚 | “只改了下拉框显示” |
| 自选脚本 | 确认、启动失败、立即退出、尾部半行 | 启动前日志页、完整输出、终态一次 | “选择文件就算开始” |

每个证据都要包含测试名称、输入快照、实际输出摘要和是否使用模拟设备。截图只能证明界面，不替代 JSON/日志/协议断言；格式检查只能证明脚本可解析，不替代实机路线验收。

## 15. 提交、评审与回退边界

建议按以下边界提交，方便用户逐项审阅和撤回：

| 提交边界 | 内容 | 可独立回退的条件 |
| --- | --- | --- |
| A | 存档神秘礼物、设置默认值、奇偶纯函数、schema 兼容 | 不影响旧配置读取；没有 GUI 依赖 |
| B | SID 定点策略、断点和目标证明 | 不包含 EasyCon 二进制；可只回退定点开关 |
| C | 兼容运行器输入状态协议及可重放补丁 | UI 404 降级，控制报告序列不变 |
| D | Python 状态客户端、手柄观察态、日志操作卡 | 删除客户端不影响脚本运行和普通日志 |
| E | 滚轮切档、自选脚本统一启动、全量回归 | 可单独回退 GUI 交互，不回退存档数据 |
| F | 文档、迁移报告、构建 manifest | 不修改业务行为，只更新证据 |

每次提交前执行 `git diff --check`，提交信息写明实际测试数量和未完成的实机项。除用户明确要求外，本方案完成不会自动打包、创建 Release 或推送 main；只有实施和本地验收完成后再按仓库流程提交/推送。

## 16. 完成定义

只有同时满足以下条件，才可以把本方案状态从“方案阶段”改为“已实现”：

1. 七项需求各有代码变更、自动化测试和至少一条失败路径证据。
2. SID 定点的开放范围来自真实路线支持，不是删除 UI 限制后的全量放行。
3. 按键显示来自实际控制报告或明确降级，不能由 ECS 文本猜测。
4. 默认开关、神秘礼物奇偶、滚轮切档和 TID 隔离在重启/失败/取消后仍一致。
5. 自选脚本确认前不跳日志，确认后无论进程成功、失败或瞬退都能看到完整终态。
6. 兼容运行器从固定源码可重建，patch id、manifest、命令行参数和 GUI 会话字段一致。
7. 自动化测试、离线格式检查和实机验收分开报告；未连接设备或未执行的部分不得写成“通过”。
