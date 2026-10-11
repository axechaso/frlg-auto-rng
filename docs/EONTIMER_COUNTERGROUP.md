# EonTimer 临时计时对照测试

最新范围（2026-10-12）：用户希望在工具内自动完成，并同意临时接入计时以供测试。现在不需要手填 EonTimer 或运行命令。默认关闭，只改变新生成的测试工程，不替换正式算法或运行器。

## 工具内使用

1. 开启顶部“高级模式”。进入“运行日志”，展开“EonTimer 临时对照测试”，勾选“使用 EonTimer GBA / Custom 计时（临时测试）”。
2. 返回“野生 / 静态”页，正常搜索并生成，或指定同一个 Seed / 消耗帧生成。工具自动使用2.0时间轴入口，不需要另外填写 F1/F2。
3. 正常“开始运行”。确认弹窗明确标出测试模式。第0轮测量固定动作后自动生成Seed、F1、F2的Custom Target；后续实际等待使用GBA换算与Calibration。
4. 在运行日志页点“查看 EonTimer 自动对照”。窗口可在运行中打开，显示本轮采用的请求截止点、反查结果、当前校准、下轮截止，以及同观测伊机控计算的差值。

测试开关只在本次工具启动期间有效，不持久化为默认。关闭开关后重新生成，恢复原计时与用户原来的预校准选择。不能在脚本运行中切换。

本次只支持独立野生 / 静态时间轴测试，包括日版御三家。搜索最高消耗帧临时限制为14399；指定模式若达到14400则明确拒绝，不自动换目标。TV、菜单奇偶调整、已开启神秘礼物的存档、孵蛋、波克比孵化、游走、狩猎区、道具乱数、SID遍历、TID与SID采集、自选ECS均不接入。

## 自动目标与校准

采用固定桌面版EonTimer `3.0.0-rc.8` 的GBA / Custom算术：GBA59.7275 FPS；目标帧换算毫秒使用四舍六入五成双，Calibration按目标减实际逐轮累加。

| 阶段 | 自动取得的Target | 校准来源 |
| --- | --- | --- |
| Seed | 本机型、语言、设置的Seed表毫秒 | 目标Seed毫秒 − 唯一反查Seed毫秒 |
| F1 | 首轮固定帧 + 首次分配的F1等待帧，作为GBA目标帧 | 固定此目标，不伪造独立F1反查结果 |
| F2 | 首轮固定帧 + 首次分配的F2等待帧，先归一成GBA目标帧 | 最终反查ADV误差归一成GBA帧后换算毫秒 |

此模板F2的最终RNG计数每GBA帧推进2次，因此F2目标先除2并取整；反查误差也除2后换算，奇数误差保留半帧的毫秒影响。这个步骤是观测单位对齐，不是把GBA设成120FPS。F1/F2计时时长均直接由各自GBA目标帧按59.7275 FPS计算，不使用旧模板的60/120毫秒转换作为EonTimer计时核心。

```text
Seed Calibration += 目标Seed毫秒 - 命中Seed毫秒
F2 Calibration   += round((目标ADV - 命中ADV) × 1000 / 59.7275 / 2)
F1 Calibration   = 0（保持初始化的Target）
```

Seed初始Calibration沿用脚本的固定基础补偿与本次第0轮测到的命令开销修正，不读取历史预校准。用户普通预校准开关/配置的值不被改写；测试生成使用独立选项，不读取记录，也不输出普通成功写回标记。

只有候选数1且本轮真值解1才更新；非唯一候选、投票优先候选、只同Seed或只同ADV不会作为完整反查结果更新。原有识图、糖果细分和反查搜索保持不变。

校准后Seed必须为正，F1/F2截止不得早于固定操作能到达的时间。不可执行时停止，不悄悄回退普通计时；原日志和现场按已有终止流程保留。Blackout和启动模式保留原有最短时间检查。原有“停止EasyCon”、标签故障保护和非目标闪光行为不变。

## 对照含义与记录

共同原点为脚本Seed计时开始（`time_start`），不是NS电源键。F1、F2原日志都相对Seed确认；F2已经包含F1，不能重复相加。报告统一到共同原点：

报告中的时间轴是已采用/待采用的请求截止点，不是按键实际发送时间戳；超时和实际观测仍以原日志为证据。

```text
Seed截止 = Seed请求
F1截止   = Seed请求 + F1阶段时长
F2截止   = Seed请求 + F1阶段时长 + F2阶段时长
```

测试保留原伊机控控制器，只用同一批观测计算对照值，不执行它输出的等待。因此“伊机控对照”不等于另一组普通模式的实机已校准结果，不证明新计时更稳定。真正A/B须用相同目标、存档、机型、语言、设置、标签和设备，分别运行普通模式与测试模式，再比较收敛轮数、误差和命中。

结束后自动在原日志旁新建`*.eontimer.json`，绑定本次run ID。原日志、计划和普通预校准不覆盖；已有同名报告拒绝覆盖并在窗口提示。原始`EONTEST|V=1`标记含完整参数和轮次，GUI按完整行增量解析，重复轮次、残缺/冲突字段、错误校准或时间点不一致均显示证据无效，不把它当作已校准成功。界面保留最近500轮，原日志保留完整证据。

## 实现与验收

- `automation/eontimer_test.py`仅在新UUID工程中注入`assets/eontimer_test/runtime.ecs`；母本、库、标签、正式运行器不变。生成后登记脚本与扩展摘要，开始前校验。指纹差异沿用用户已有的高级模式“只警告”规则；缺少测试标记、混入普通模式、无效配置仍拒绝，不能把它们当成指纹警告。
- 使用原时间轴的绝对等待执行器，新增的是GBA目标/Custom校准算术，不移植外部Qt倒计时、提示音或新单片机协议。
- Native检查器完整绑定编译实际生成工程，再以无硬件ECS执行验证换算、累加、唯一门控、不可执行停止；生产PRINT标记再交Python解析。测试夹具不是实际搜索到的闪光目标，不用于实机结果证明。

2026-10-12离线验收：全量1060项回归通过（1070.747秒），最终指纹政策另经136项定向回归通过，最终文案与报告字段另经6项解析回归通过；当前语料、同步前备份各生成英版野生/定点及日版御三家×两机型，共12份工程通过固定164a完整绑定编译，每组436项纯ECS断言与跨语言协议解析通过；运行日志页和对照窗完成离屏布局核对。未连接单片机或采集卡，实机稳定性与命中率尚未验收。

开发复验命令（不是用户操作步骤）：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_eontimer_test tests.test_eontimer_comparison
.\.venv\Scripts\python.exe tools\verify_eontimer_test.py --output .tmp\新的验收目录
```

早先`tools/eontimer_comparison.py`手工CLI仍保留为离线数值诊断，已不再是本功能入口。它接受用户明确指定的阶段目标/观测单位，不替代这里的自动目标归一或运行接线。

## 来源

- [Retail RNG火红/叶绿定点教程](https://retailrng.com/frlg/beginner/frlgstatic/)：Custom用Seed毫秒和Advances设置计时，唯一反查后Update。
- [EonTimer换算核心](https://github.com/DasAmpharos/EonTimer/blob/ead211d6e4251c4f08345cc9e56e76d3cb2a29bd/eon_timer/timers/calibrator.py)、[Custom校准](https://github.com/DasAmpharos/EonTimer/blob/ead211d6e4251c4f08345cc9e56e76d3cb2a29bd/eon_timer/timers/custom/custom_phase_widget.py)、[GBA设置](https://github.com/DasAmpharos/EonTimer/blob/ead211d6e4251c4f08345cc9e56e76d3cb2a29bd/eon_timer/settings/timer/model.py)。
- MIT原许可与归属见 [EonTimer-LICENSE.md](../third_party/EonTimer-LICENSE.md)。
