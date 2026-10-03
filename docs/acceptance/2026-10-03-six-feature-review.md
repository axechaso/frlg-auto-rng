# 六项新功能验收报告

日期：2026-10-03。代码基线：`1f4f7ec`（`0.9.4.2`）。

结论：**未通过整体验收。第 1、2、3 项有实际链路阻断，第 4 项部分完成，第 5、6 项通过本次离线交互检查。**

本次仅验收，没有修改产品代码、重建运行器、同步母本、推送或发布。测试 GUI 使用独立数据目录，不修改用户日常配置；真实 EasyCon CLI 测试均使用 `--port mock`，测试脚本只执行 PRINT/WAIT，不连接或操作 NS。离线通过不代表实机长跑已经验收。

## 1. 逐项结果

| 用户要求 | 结果 | 核实内容 |
| --- | --- | --- |
| 1. SID 遍历支持定点 | 未通过 | 正式 `CompleteWindow` 能选择静态杰尼龟并生成 `sid_traversal / Static 1` 请求，原来的仅野生限制已解除；但实际结果标记的生成和日志解析各有一处错误，命中/非闪排除均不能正常完成 |
| 2. 虚拟手柄显示脚本按键 | 未通过 | 注入协议规定的合法状态时，控件 A/ZL 能高亮且进入只读观察；当前运行器真实 HTTP 响应的摇杆类型却不符合客户端协议，所有状态都被拒绝 |
| 3. 日志页运行准备改为脚本操作 | 布局通过，实际数据未通过 | 日志页已隐藏“运行准备”、显示“脚本操作”，能够渲染合法按键状态；受到第 2 项同一协议问题影响，真实运行时无法正常显示 |
| 4. 默认开启更新预校准和出闪录像 | 部分完成 | 全新目录首次启动：录像为开、更新预校准为关；已有空设置文件缺字段时两者为开；显式保存关闭时两者仍保持关闭 |
| 5. 鼠标滚轮切换存档 | 离线交互通过 | 给顶部存档栏发送真实 Qt 滚轮事件后切换到下一存档并回填 TID/礼物状态；运行期间滚轮不切档；现有存档存储测试通过 |
| 6. 存档记录神秘礼物，开启时强制方案 1 | 离线交互通过 | 存档模型与管理窗口已增加字段；选择开启的存档后，界面锁定方案 1，收集到的实际请求也是 1；关闭礼物后恢复原方案 0 偏好；存储、复制与旧数据兼容相关测试通过 |

定点开放仍有明确边界：当前 `automation/sid_traversal_policy.py` 对整个 `Gift` 类别禁止遍历，包括伊布、拉普拉斯、波克比，原因是尚未建立领取目标与额外野生 Seed 复核的独立终态证明。不能将目前实现描述为所有定点路线均支持。

## 2. 必须处理的问题

### P1：运行器的摇杆坐标被序列化为 Base64 字符串

位置：

- `tools/patches/easycon164a-input-state-v1.patch:142`：`InputStateSnapshotPayload` 将坐标定义为 `byte[]`。
- 同一补丁 `:281`：HTTP 接口直接使用 `JsonSerializer.SerializeToUtf8Bytes(state)`。
- `pyside_app/run_input_state.py:54`：客户端要求坐标是恰好两个整数的数组。

本机实际使用的运行器摘要与其 manifest 一致：

```text
patch_id = easycon164a-label-supervision-v10-stage-log-filter-input-state-v1
sha256 = 0f959a351238292b19a1255891f30eb410071486afa642e5caff2b4dff8cd140
```

不是“还没构建新版运行器”。已构建的实际 `/input-state` 响应如下：

```json
{"buttons": [], "hat": "CENTER", "left_stick": "gIA=", "right_stick": "gIA="}
```

`System.Text.Json` 对 `byte[]` 输出 Base64，而客户端期待 `[128, 128]`。调用真实校验函数得到 `按键状态 left_stick 坐标无效`，不是仅仅摇杆不显示：整条快照被拒绝，普通按键同样不显示。

修复方向：统一发送端和接收端的数据契约。优先让发送端输出协议约定的整数数组，并重建、检查运行器及打包资产；不要把客户端异常吞掉后伪装为无按键。补充读取实际运行器 HTTP 响应的集成测试，不能只手写符合预期的 Python 字典。

证据：工作区 `.tmp/acceptance-20261003/native-input.json`、`native-probe.log`、`results.json`。另用实际 `EasyCon.Device.dll` 调用发布函数，A 键配合坐标也得到相同 Base64 类型；没有向设备发出控制报告。

### P1：SID 遍历解析器忽略 EasyCon 的时间戳与 ANSI 前缀

位置：`automation/target_verification.py:195`。

当前解析器仅接受去空白后直接以 `SIDTRAVERSAL|` 开头的整行。实际 CLI 的 ECS `PRINT` 带 ANSI 颜色码和 `[HH:mm:ss.fff]` 时间戳；`run_easycon_logged.py` 保留原始输出写入日志，`run_sid_traversal.py` 又直接把该日志交给解析器。

用正确的完整标记运行 PRINT/WAIT 测试：CLI 退出码为 0，但 `parse_target_verification()` 返回 `None`；仅在诊断代码中去除 ANSI 和时间戳后，同一条标记才能解析为有效结果。

影响：即使脚本正确产生目标命中证据，遍历也会走 `missing-proof` 暂停，而不会确认 SID 或推进明确非闪的候选。该问题同时影响野生和定点，不仅是新开放的定点。

修复方向：按明确的 EasyCon 日志格式规范化前缀，再严格验证完整事件。保留 run/attempt/round/END 校验，不改成宽松的“日志里包含出闪就成功”。增加真实格式日志和不完整/错误身份日志的回放测试。

证据：`.tmp/acceptance-20261003/native-probe.log`；`results.json` 的 `native_sid_terminal_log` 同时记录原始解析与诊断规范化后的解析结果。

### P1：生成的目标结果标记末尾多一个引号

位置：`automation/target_verification.py:81`。

`_event_line()` 在 `shiny` 数值后直接拼接 `|END=1"`，缺少 ECS 的字符串拼接边界。当前生成内容相当于：

```text
... "|SHINY=" & 1|END=1"
```

真实 EasyCon `format` 会接受它，但运行后实际输出为：

```text
SIDTRAVERSAL|V=1|RUN=audit-run|ATTEMPT=audit-attempt|ROUND=1|EVENT=TARGET|SEED_MATCH=1|ADV_MATCH=1|SPECIES_MATCH=1|SHINY=1|END=1"
```

末尾引号不属于协议。即使先修好 ANSI/时间戳问题，这条结果仍然不能匹配以 `|END=1` 结束的严格正则。因此两处 SID 协议问题必须分别修复、分别回归，不能只处理其中一处。

复现脚本逐字断言其 PRINT 行与当前 `_event_line()` 输出一致，随后使用实际运行器 mock 执行。退出码 0、格式通过都不能替代结果协议验收。

修复方向：正确拼接字符串终止字段，验证 SHINY=0 和 SHINY=1 两条分支；增加“生成语句 → 实际 CLI 输出 → 日志解析”的往返测试。

证据：`.tmp/acceptance-20261003/probe-injected.ecs`、`injected-terminal.log`、`event-terminal-result.json`。

### P2：首次启动更新预校准没有默认开启

位置：`pyside_preview.py:879`；随后 `:891` 才调用 `setCheckable(True)`。

`setChecked(True)` 调用时按钮还不是可勾选按钮，这次设置没有生效。全新数据目录没有设置文件，`pyside_app/window.py:1186` 又直接返回，导致正式窗口实际状态为：

```text
update_precalibration = False
record_shiny_video = True
```

已有设置文件缺字段时，加载代码能补为 True，所以只测“空 JSON 文件”会漏掉真正第一次启动。显式保存 False 的用户偏好没有被覆盖，这一行为应保留。

修复方向：在按钮成为可勾选状态、状态文字回调接好之后设置默认值；分别覆盖“完全没有文件”“文件缺字段”“显式关闭”。恢复配置时也应同步勾选文字，不能仅靠 `QSignalBlocker` 改内部值而保留关闭态文案。

证据：`results.json` 的 `fresh_defaults`、`missing-fields` 和 `explicit-off`。

## 3. 自动化结果与测试缺口

- 本次完整回归：**712 项，711 项通过、1 项失败**，耗时约 239 秒。
- 失败项：`test_label_wait_stages.LabelWaitStageMaterializationTests.test_current_source_and_materialized_script_corpora_are_audited`。
- 测试硬编码旧缓存指纹 `04a0cdda…`；当前缓存实际为 `2cd606b7…`，与缓存 manifest 一致，且已列入代码的受支持集合。当前源指纹为 `abedc36a…`。这是同步后测试基线没有更新，不能因此把用户脚本回退或改回旧缓存。
- 新增本地验收探针共 13 项：9 项通过，4 项失败。失败分别为真实状态接口、真实 SID 日志解析、生成的结果尾引号、无配置首次启动默认值。
- `git diff --check` 通过；本次没有产品代码差异。

现有自动化为什么没有发现前三个 P1：按键测试手工构造数字数组，未消费 .NET 实际 JSON；结果标记测试手工构造不带时间戳的标准字符串；注入测试主要检查标记计数和幂等性，未执行生成的 PRINT 并解析其输出。

## 4. 后续重新验收条件

1. 修复并重建按键状态运行器后，实际 HTTP 响应直接通过客户端校验；确认 A/B、方向、摇杆、松开和阶段切换，不允许串口由浮窗抢占。
2. 修正 SID 两处协议问题后，真实运行器输出能闭环：目标闪光确认、目标非闪推进、证据缺失保留候选，三种结果明确分开。
3. 首次启动两个默认开关均为开，手动关闭后重启仍保持关闭。
4. 更新已审计脚本的测试基线，完整回归无失败。
5. 保留本次已通过的滚轮与神秘礼物行为，再在用户指定的实机安全起点完成代表性定点遍历和按键回显检查；未做这一步前不能声明实机全部验收完成。
