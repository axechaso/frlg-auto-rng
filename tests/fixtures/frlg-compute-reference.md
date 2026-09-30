# 计算与完整方案对照数据

行为锚点为本仓库提交 `5a5383ff226059cbf85f0b531c9de283f7b76c45`。
优化移植自 `auto-poke-rng` 的 `0c47bf6bb985daa0fcf9b02c119633f74d8356f4`；
测试、工具和运行时均只依赖本仓库与 Python 环境，不需要该来源项目。

`frlg-compute-reference.json` 保存 467 组原始计算的结果数量和完整结果的 SHA-256。
序列化仅排序字典键，保留列表顺序；错误类型与消息也在摘要内。
本次重新对干净的锚点 checkout 生成语料，并逐项确认与移植的参考文件相同。
覆盖 Static/Wild 1、2、4、六种野生遭遇、混合物种性别比、各筛选条件、
游走 IV 缺陷、4096 组隐藏力量低位、全部 65536 初始 Seed、IV 枚举与计数、
英日版火红/叶绿及两种主机的路线/精确模式查询。

`frlg-golbat-plan.json`、`frlg-starter-plan.json` 是相同锚点的默认野生、定点完整方案。
`frlg-golbat-restricted-plan.json` 由本次干净锚点 checkout 的
Advance 0–10000 搜索生成，保留全部请求、目标、初始 Seed、执行设置、统计和警告。
`test_compute_regressions.py` 将完整方案逐字段比较，同时独立穷举距离和 IV 计数，
检查工作量边界、中途取消、缓存边界、重复时刻/偏移/表替换与计算调用次数。

只在需要重建锚点数据时运行（从仓库根目录，使用安装了项目依赖的 Python）：

```powershell
git worktree add --detach .build/perf-reference 5a5383ff226059cbf85f0b531c9de283f7b76c45
python tests/frlg-compute-cases.py --source-root .build/perf-reference --output .build/reference.json
python tools/compare-frlg-planner.py .build/perf-reference --include-slow --output-dir .build/perf-results
```

慢案例的原始完整方案在 `restricted-range-before.json` 的第二项 `result` 中。
不要用优化后的实现重新生成期望数据来消除测试失败。日常回归直接执行
`python -m unittest tests.test_compute_regressions`，无需锚点 checkout。
