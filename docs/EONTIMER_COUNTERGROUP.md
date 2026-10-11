# EonTimer 独立对照测试

本测试只用来比较 **EonTimer 校准后的时间轴** 与 **伊机控校准后的时间轴**。不接入正式流程，不生成或改写 ECS，不更换运行器，不连接单片机，也不读取或写回普通预校准配置。之前试作的第三运行后端、原生计时补丁和自动执行接线已撤回。

## 先在 EonTimer 中设置

使用桌面版 EonTimer，设置 Console 为 **GBA**，打开 **Custom** 页。保持同一目标 Seed、消耗帧、游戏设置与计时原点，本次不加菜单调整，也不使用 TV 过帧。

| 阶段 | Unit | Target 填什么 | 结束动作 |
| --- | --- | --- | --- |
| Seed | ms | 对应 Seed 表查到的目标毫秒 | 封面确认 |
| F1 | Advances | 手工分配的 F1 目标帧 | 进入存档 |
| F2 | Advances | 手工分配的 F2 目标帧 | 触发目标 |

F1/F2 用用户给定的目标帧，按 EonTimer 的 GBA 规则换算，不套伊机控旧的 60/120 换算。**不要把完整目标消耗帧又作为额外 F2，加到一个已包含它的 F1 后面。** 最终反查目标消耗帧另外记录，不根据 F1/F2 的名字或数值自动猜测。

教程使用 Seed 毫秒 + Advances 两段。若不需要单列 F1，助手中设置 `--f1 0`，EonTimer 中省略 F1 这一行；F2 使用完整目标 Advances。需要三段对照时，由用户先确定 F1/F2 的分配与对应动作。

两边均以脚本 **Seed 计时开始的位置** 为0（对应 `$time_start`），不是按 NS 电源键的时刻。HOME_BUFFER 校准、关闭游戏和额外预备倒计时不计入这个原点；必须在相同动作上启动两边的 Seed 计时，才能比较后续截止。

Seed 的 Target **不是十六进制 Seed 本身**。比如 Seed `EDDE` 的毫秒必须查对应表，不能把 `EDDE` 当作 Custom 的数值帧数。

## 用反查结果校准

先取得唯一反查结果，再记下实际 Seed 对应的毫秒与实际消耗帧。每次基于 EonTimer **当前 Calibration** 累加，不把之前的修正清零。

```text
Seed新Calibration = 当前Calibration + (目标Seed毫秒 - 实际Seed毫秒)
F2新Calibration   = 当前Calibration + round((目标消耗帧 - 实际消耗帧) × 1000 / 59.7275)
F1Calibration     = 保持当前手工设置
```

`round` 与桌面版源码一致，使用四舍六入五成双。实际偏晚就减等待，偏早就加等待。

在 EonTimer 中直接使用 Update 时：

- Seed 的 Hit 填实际 Seed 毫秒。
- 两段测试且 `F2 Target = 最终目标消耗帧` 时，F2 的 Hit 直接填实际消耗帧。
- 已经单列 F1 时，F2 的等效 Hit 为 `F2 Target + 实际消耗帧 - 最终目标消耗帧`。不要把最终总消耗帧误当成 F2 这一段的 Hit。也可以直接填写上式算出的新 Calibration。
- 最终反查只给出总帧偏差，不能独立推算 F1 实测帧；本次固定 F1，把最终帧偏差用于 F2 校准。候选不唯一时先细分 IV，不使用“优先候选”当作唯一结果。

## 独立计算助手

源码根目录运行以下命令即可列出应填数值、各段时长与相对共同起点的累计截止。它只打印结果，不启动游戏或计时器。

```powershell
.\.venv\Scripts\python.exe tools\eontimer_comparison.py --seed-ms 30000 --f1 0 --f2 2000 --target-advances 2000
```

以上是演示数值，请替换为实际目标。三段测试时填写自己分配的 `--f1`、`--f2`。已有修正用 `--seed-cal`、`--f1-cal`、`--f2-cal` 填当前 Calibration（单位均为毫秒）。

例如唯一反查得到 Seed `30020 ms`、消耗帧 `2002`：

```powershell
.\.venv\Scripts\python.exe tools\eontimer_comparison.py --seed-ms 30000 --f1 0 --f2 2000 --target-advances 2000 --hit-seed-ms 30020 --hit-advances 2002 --candidates 1
```

本例输出 Seed 新校准 `-20 ms`、F2 新校准 `-33 ms`。下轮须把这些当前校准值带上，再输入下一轮实际结果；助手不会自行持久化或自动执行。

## 对比伊机控的已校准时间轴

从同目标的无菜单/TV时间轴日志选择校准完成后的样本：

```powershell
.\.venv\Scripts\python.exe tools\eontimer_comparison.py --seed-ms 30000 --f1 0 --f2 2000 --target-advances 2000 --seed-cal -20 --f2-cal -33 --easycon-log 'D:\实际工程\easycon.log' --round 5
```

`--round` 指日志中第几个 **完整 Seed/F1/F2 时间轴样本**，从1开始；不是含第0轮设置检测的游戏轮号。日志有多个完整样本时必须指定，不能默认拿最后一条就当作校准完成。原日志保持只读。可用 `--output 'D:\测试\对照.json'` 另存一份新记录；已有文件拒绝覆盖。

伊机控当前日志的三个计划值分别为：

```text
Seed绝对时间轴: 请求...ms               相对于Seed计时开始
F1绝对时间轴: 目标...ms                 相对于Seed确认
F2绝对时间轴计划: 自Seed确认起...ms      同样相对于Seed确认
```

助手统一到“Seed计时开始为0”的截止点再比较。F2 计划已含 F1，**不能再加一次 F1**。输出正差值表示 EonTimer 计划更晚，负值表示更早。不会用不同轮的残缺行拼出假时间轴，也不会把缺少完整三项的旧日志强行换算。

这只能回答两套校准最后落在什么计划时间点、相差多少毫秒；不能把软件计划当成 Switch 收键时间，也不能只凭时间接近宣称命中率已提高。下一步是否改正式算法，应由同条件实测的收敛轮数、稳定误差和命中结果决定。

## 对照来源

- [Retail RNG 火红/叶绿定点教程](https://retailrng.com/frlg/beginner/frlgstatic/)：Custom 以 Seed 毫秒、Advances 设置计时，唯一反查后 Update；接近后只在持续偏早/偏晚时继续调校。
- [EonTimer GBA 设置](https://github.com/DasAmpharos/EonTimer/blob/ead211d6e4251c4f08345cc9e56e76d3cb2a29bd/eon_timer/settings/timer/model.py)、[换算核心](https://github.com/DasAmpharos/EonTimer/blob/ead211d6e4251c4f08345cc9e56e76d3cb2a29bd/eon_timer/timers/calibrator.py)、[Custom 校准](https://github.com/DasAmpharos/EonTimer/blob/ead211d6e4251c4f08345cc9e56e76d3cb2a29bd/eon_timer/timers/custom/custom_phase_widget.py)：固定桌面版 `3.0.0-rc.8` 提交，GBA 为59.7275 FPS，校准累加目标减实测的毫秒差。只参考算术，不移植计时执行器。
- MIT 原许可与归属见 [EonTimer-LICENSE.md](../third_party/EonTimer-LICENSE.md)。
