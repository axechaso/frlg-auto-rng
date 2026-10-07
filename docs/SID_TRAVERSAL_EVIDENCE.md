# SID 遍历：利用校准宝可梦排除或确认 TSV

更新日期：2026-10-07。仅作用于 PySide6 野生/静态页的 SID 遍历，不改变普通乱数、孵蛋、SID 逐槽采集、TID 或 TID→御三家。

## 用户看到的变化

1. 无需新增开关。开启 SID 遍历并重新生成方案即可；已有生成工程不会自动修改。
2. 校准时捕获的宝可梦只要反查 PID 唯一、非闪状态可靠，就会排除该 TSV。不再要求它是设置的目标，也不要求 Seed、Advance 都命中目标。
3. 当前尝试 SID 的 TSV 被排除时，脚本立即结束这一候选，工具按原有奇偶步长 `+2` 继续。以后再遇到同 TSV 的 SID，会直接跳过搜索和实机运行。
4. 目标或非目标闪光会先完成抓获与反查。PID 唯一且闪光状态确认后，报告显示已确认 TSV、8 个 SID 和范围内可采用的 ADV；游戏不重启，也不自动存档。
5. 闪光已出现但抓获/识图/反查没有得到可靠证据时，保留现场停止。请检查日志、宝可梦和标签，不会重启刷掉闪光。
6. 同参数暂停后继续会保留排除证据及进度。改变游戏、TID、存档快照、目标、路线、母本或运行参数仍使用原有独立上下文，不能把不同存档的证据混用。

普通“出闪后继续抓捕”保持关闭；SID 遍历在生成副本内独立执行本次闪光抓获和反查，而不是无休止继续刷。录像开关沿用用户选择。普通流程的出闪与非目标闪光设置没有变化。

## 判断依据

第三世代：

```text
PSV = (PID高16位 XOR PID低16位) >> 3
TSV = (TID XOR SID) >> 3
闪光 ⇔ PSV == TSV
```

因此确认非闪可排除该 PSV 对应的 TSV；确认闪光则 TSV 等于该 PSV。同一 TSV 的低 3 位仍不确定，已知 TID 也有 8 个完整 SID。工具按已选 ADV 范围、劲敌取名奇偶筛出候选，每个 SID 列出最早 ADV，选择其中最早者作为可采用值；不是证明它就是存档的唯一完整 SID。范围内没有可采用值时仍报告 TSV 成功，但不虚构 SID/ADV。

### 什么算 PID 唯一

- 检查本轮完整配置反查窗口内的**所有匹配候选**，在投票/路径选择前记录每个 PID 的高低半字。
- 候选可以有多个 Seed/Advance/方法，只要它们的 PID 全部相同，仍能作为 PID 证据；不意味着 Seed/Advance 已唯一。
- 只要出现两个不同 PID，本轮不能据此排除或确认 TSV。后来再次出现第一个 PID，不会把不一致状态恢复成一致。
- “本轮真值解”、唯一 IV、共同区优先候选、投票停糖、最佳候选都不能替代上述条件。
- 识图成功且反查完成才提交。未搜到目标、无可达 Seed、搜索取消或工作量上限，不是非闪证据。

### 闪光状态保护

在原性格页、原右切能力页之前，连续采样 3 帧，间隔 50 ms，不增加手柄按键。每帧性格页须达到 `max(95, 当前识图阈值)`：

- 三帧星标均通过同一阈值：确认闪光。
- 三帧星标均不超过阈值减 5，且本轮没有战斗/其他星标出闪记录：确认非闪。
- 页标签低分、星标临界分数（例如阈值 95 时 91–94）、帧间状态变化、战斗与性格页状态冲突：不作 TSV 排除。

HOME_BUFFER 低分自适应不降低证据门槛。这些采样发生在获取后，不修改启动、Seed 等待、F2、奇偶、扩窗或校准算法。

## 实现与持久化

- `automation/sid_observation.py`：生成副本的严格锚点接线、协议解析与置信度校验。
- `assets/easycon118_extensions/sid_pid_observation.ecs`：PID 一致性、三帧状态采样和安全终止。
- `run_sid_traversal.py`：读取当前运行/尝试身份的 `SIDTRAVERSAL_OBS|V=1` 证据；整个批次校验后原子提交，发现冲突则不提交该批次并停止。旧精确目标证明仍保留，并增加 PID/状态一致性保护。
- `sid_traversal.py`：保存 `pid_observations`、`excluded_tsvs`、`confirmed_tsv`、独立的 `evidence_skipped_count`；恢复时从 PID 重新核对约束，不信任孤立 TSV 列表。
- 原进度 schema 3、上下文哈希与游标不变，缺少新字段的旧进度按空证据恢复；已有历史日志不会自动转成排除证据。
- 完整证据附带运行 ID、尝试 ID、轮次、图鉴编号、PID、匹配候选数、页面/星标分数和日志路径。运行结束读取全部完整记录；手动停止或运行器异常仍可保留已完整校验的记录，但本次不自动推进游标。强制杀掉整个 worker 不能保证尚未提交的证据已写入检查点。
- “窗口跳过”“实测目标非闪”“TSV 证据跳过”分别计数，不混为实际执行轮数。

未知结构不猜测注入。旧生成项目缺少本扩展会要求重新生成，断点不会因此清空。原始母本、共享库、标签和指纹规则未改。

## 离线验收

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_sid_observation tests.test_sid_traversal tests.test_target_verification tests.test_sid_traversal_policy
.\.venv\Scripts\python.exe tools/verify_sid_observation.py .tmp/sid-pid-observation-20261007
$projects = Get-ChildItem .tmp/sid-pid-observation-20261007 -Filter main.ecs -File -Recurse | Select-Object -ExpandProperty FullName
dotnet run --project tools/EasyCon164aSIDObservationCheck -- $projects
```

矩阵为正式/时间轴 × NS1/NS2 × 英文野生/英文定点/英文御三家/日文御三家，共 16 个完整工程。原生检查先对实际生成 ECS 做完整绑定编译，再仅对提取的实际证据函数注入分数和时间记录；禁止真实按键、WAIT、识图及设备连接。母本原 `ezcon.exe format` 也应逐份通过。

测试覆盖非目标非闪提前排除、同 TSV 未来候选不搜索/不运行、非目标闪光成功、八 SID/奇偶筛选、同 PID 多方法、串联不能恢复一致、临界与冲突分数、协议身份与重复轮次、原子冲突、停止/异常留证、旧进度和界面报告。编译/离线通过不等于实机抓获与识图已验收；首次仍需用户在自己的 NS1/标签环境检查日志。

本轮结果：全量 Python 回归 825 项通过；16 份生成工程的配置一致性、完整预检、真实 164a 编译和 format 通过；110 项原生证据检查及两条原生 PRINT→Python 解析通过；原包 47 项检查与两份入口 format 通过。未连接硬件。
