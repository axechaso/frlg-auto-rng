# 火叶搜索性能与行为验证

2026-09-30，基于远端默认分支 `5a5383ff226059cbf85f0b531c9de283f7b76c45`
移植 `auto-poke-rng` 提交 `0c47bf6bb985daa0fcf9b02c119633f74d8356f4` 的 Python 计算优化。

## 改动与语义边界

- 定点和野生 IV→PID/目标 Seed 搜索，在 PID 确定后提前筛选性格、闪光和特性。
  野生性别继续依据实际遭遇槽位的物种计算，混合性别比不会被提前误筛。
- 隐藏力量直接提取六项 IV 的低位，每组 IV 只计算一次并提前筛选。
  IV 档位计数使用滑动窗口和最多 64 项的不可变键缓存；枚举预计算后缀上下界。
- 初始 Seed 距离索引遍历完整低 16 位周期，通过高位步长的模逆求整周期距离。
  以原距离算法逐项检查全部 65536 个 Seed，包括排序与 32 位回绕。
- 指定 Seed 查询复用 Seed 表已有反向索引，保留出现顺序、重复时刻、按键偏移和模式平手规则。
  不缓存表查询结果，因此替换 Seed 表后不会保留旧时刻。

保持同档完整搜索、最高 IV 合计优先/同档最小可达 Advance、结果顺序、工作量限制和取消语义。
`get_contiguous_seed_list` 的 `initial_seed` 为可选参数；校准与御三家消费者的四参数全表查询仍兼容。
原有 `calibration_bind`、校准包装及 C++ 源码未改变，原版真实搜索→校准往返测试通过。
本次没有新增 C++ 计算内核，也未执行硬件或游戏验收。

## 同输入实测

环境：Windows x64、Intel i7-11800H、Python 3.12.10。同一解释器串行测量优化前后，
不启用 cProfile。计时仅覆盖计算调用；方案计时为 `search_best_plan(...).to_dict()`，
不包含进程启动、导入、GUI 或设备操作。每个方案场景各起新进程，后两次复用该进程缓存。

| 方案 | 优化前（秒） | 优化后（秒） | 相同结果 |
| --- | ---: | ---: | --- |
| 默认野生首次 | 0.689 | 0.177 | 7422 / 25296 / IV 181 |
| 默认野生重复两次 | 0.125 / 0.111 | 0.016 / 0.017 | 同上 |
| 默认定点首次 | 0.680 | 0.172 | 7422 / 25359 / IV 181 |
| 默认定点重复两次 | 0.024 / 0.021 | 0.007 / 0.005 | 同上 |
| 野生 Advance 0–10000 首次 | 74.007 | 9.009 | BFBD / 212 / IV 165 |

野生输入：火红 Switch 1，TID 0 / SID 38448，华蓝洞窟 1F，大嘴蝠，全部野生方法，
星形/方形闪光，其他筛选不限；默认 Advance 3000–100000。定点为 Static 1 妙蛙种子，
其余公共条件相同。完整请求与结果见 `tests/fixtures/frlg-*-plan.json`。
三类方案优化前后全部 JSON 字段一致，包括目标、初始 Seed、执行设置、搜索统计与警告。

| 计算入口 | 优化前（毫秒/次） | 优化后（毫秒/次） |
| --- | ---: | ---: |
| 野生反查，全部方法，闪光，六项 IV 27–31 | 3505.133 | 401.857 |
| 定点反查，Static 1，闪光，六项 IV 27–31 | 337.091 | 127.604 |
| 野生反查，不限闪光，六项 IV 29–31 | 182.650 | 176.909 |
| 定点反查，不限闪光，六项 IV 29–31 | 54.272 | 43.077 |
| 初始 Seed 索引首次构建 | 551.505 | 142.803 |
| 指定 Seed 7422 自动选择模式 | 4.999 | 0.036 |
| 六项 IV 0–31 的全部 187 档计数 | 234.335 | 0.212 |
| IV 合计 178 的完整枚举 | 1.808 | 1.892 |
| 索引已构建后的初始 Seed 路线查询 | 0.198 | 0.226 |
| 能力值反推 IV 范围 | 0.056 | 0.069 |

路线/指定 Seed 查询重复 100 次，计数/枚举重复 3 次，能力值反推重复 1000 次取均值；
其余为一次完整调用。IV 档位计数均值包含首次填充缓存。所有结果摘要（含列表顺序）一致。
微小差异与单次计时受机器负载影响；本次枚举和原本很快的查询不宣称加速，也不承诺固定倍数。

## 回归与复现

参考数据与重建方式见 [计算对照数据](../tests/fixtures/frlg-compute-reference.md)。
新回归已接入 Windows/Python 3.12 CI。两项调用次数回归在锚点上确认失败：
被闪光条件排除的野生 PID 仍执行 15217 次反向推进；64 组定点 IV 重复计算隐藏力量 260 次。
优化后通过，CI 不使用易受机器负载影响的秒数门槛。

本次完整发现测试共 662 项：616 通过、43 因本地资源条件跳过、3 项基线错误。
3 项均在干净锚点上重现：`test_label_wait_stages` 的两项测试缺少未随 Git 提交的
`local_assets/easycon118` 脚本；`test_pyside_diagnostics` 的可选遍历起点测试因
“第 1 层 Seed 容差”为空失败。本次未修改这些无关资产或界面逻辑，也未弱化断言。
按 CI 工作流逐项执行的仓库测试共 620 项：578 通过、42 按资源条件跳过，无失败。
CI 编译检查和 21 项离线 QQ 通知测试通过。

在仓库根目录使用安装了项目依赖的 Python：

```powershell
python -m unittest tests.test_tenlines_fixes tests.test_auto_planner tests.test_compute_regressions
python -m unittest discover -s tests
python tests/frlg-compute-cases.py --benchmark
python tools/profile-frlg-planner.py --timing-only --repeat 3
python tools/profile-frlg-planner.py --timing-only --min-advances 0 --max-advances 10000 --repeat 1
python tools/profile-frlg-planner.py --request tests/fixtures/frlg-starter-plan.json --timing-only
# 可选：热点分析（时间含分析器开销，不能当作正常搜索耗时）
python tools/profile-frlg-planner.py --stats-dir .build/frlg-profile
# 可选：显式指定干净旧版本 checkout，逐字段比较三类完整方案
python tools/compare-frlg-planner.py .build/perf-reference --include-slow --output-dir .build/perf-results
```

工具只读指定 checkout 并写可选报告。普通运行、单元测试和 CI 不需要其他项目、Node 或 Electron。
