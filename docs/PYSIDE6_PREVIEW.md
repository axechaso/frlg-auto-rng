# PySide6 界面迁移预览

`pyside_preview.py` 是独立的视觉和交互原型，不替换 `run_auto_rng_gui.py`，也不会修改配置、搜索方案或启动 EasyCon。

## 设计原则

工具的目标是让人容易操作。以用户确认的 `7438e0e` 初版截图作为视觉基准：紧凑的存档/设备摘要、左侧常用条件、右侧方案与运行准备、单行底部主操作。功能映射用于核对完整性，不要求照搬 Tk 的控件排列或把全部参数同时铺开。常用输入直接显示，少用设置可展开，重要确认与警告保持可见。

## 当前范围（2026-09-05 页面核对）

- 以提交 `7438e0e` 的 `pyside_preview.py` 为初版，先完成 [逐页功能映射](PYSIDE6_PAGE_MAP.md)，再调整布局。该表列出了正式 Tk 字段、处理函数、原型缺项与接入边界。
- 侧栏顺序与 Tk 一致：SID 查找、TID 乱数、TID 实测表、野生 / 静态、孵蛋；高级模式显示脚本测试，运行日志常驻末尾。默认打开 SID。
- 恢复初版深色侧栏、白色卡片与约 7:4 的双栏比例，默认 1360×860，最小 900×620。右上角为两张紧凑摘要卡：点击存档打开选择/手动身份输入，点击设备打开共通设置；右侧集中呈现方案和三项运行准备，结果详情另开窗口。
- 底栏只突出生成和开始运行，取消/停止收进“···”菜单。窗口窄于 1180 时，通过“方案与设备”查看同一份右侧内容；实测表使用整页宽度。各页输入纵向滚动，右侧状态保持可见。表格和日志保留内部滚动。
- IV 恢复六张能力小卡，点击能力名称可重置单项。SID 按队伍顺序逐只填写，六槽仍完整保留，数量外的槽位禁用且不清除输入；孵蛋亲本 A/B 分组显示六项 IV，无须横向滚动。TID 细调、脚本路径、更多筛选和标签诊断可按需展开；折叠不删除输入。
- SID 补齐六槽、初始等级、野生地点、EV、糖果/阈值/机型/确认；TID 恢复正式七分区；实测表保留完整 11 列；野生/静态补齐身份、指定模式、觉醒力量和 SID 遍历；孵蛋补齐运行条件、亲本与四种配置操作；日志恢复设备标签诊断布局。
- 可以实际操作的内容仅为内存表单：导航、高级显隐、SID 槽位数量、IV 预设/单项重置、模式互斥、TID 条件禁用/语言默认值、野生与孵蛋的游戏/主机同步、可选参数折叠及存档/结果/共通设置窗口。
- 真实存档管理、设备检测、路径选择/校验、数据库、配置保存/载入、遭遇目录、搜索、SID 计算、预检、生成、日志尾读、标签覆盖和运行器均未接入，相应按钮禁用并有说明。没有虚构的已连接设备、已就绪计划或成功日志。Qt 不导入 Tk、计划器或乱数算法模块，只复用静态界面译名。
- 表单切换不代表业务验证通过；自动化游戏操作、冻结入口和正式 Tk 均不变。

## 启动

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-pyside-preview.txt
.\.venv\Scripts\python.exe pyside_preview.py
```

或双击 `启动-PySide6界面预览.bat`。

指定页面并输出截图：

```powershell
.\.venv\Scripts\python.exe pyside_preview.py --page wild --screenshot .build\pyside-preview.png
.\.venv\Scripts\python.exe pyside_preview.py --page tid --size 900x620 --scroll 1 --screenshot .build\pyside-tid-bottom.png
.\.venv\Scripts\python.exe pyside_preview.py --page tid --expand --scroll 1 --screenshot .build\pyside-tid-expanded.png
.\.venv\Scripts\python.exe pyside_preview.py --page egg --advanced --settings --scroll 1 --screenshot .build\pyside-settings.png
```

Windows 本地视觉验收应使用上面的正常图形后端，使 Qt 载入系统中文字体。自动化测试会单独使用 `offscreen` 后端，只验证窗口能生成合法 PNG，不把该截图当作字体视觉验收结果。

页面键为 `sid / tid / tid_records / wild / egg / script_test / logs`；`--scroll` 为 0–1 的纵向位置，`--settings` 改为打开并截图共通设置，`--advanced` 展示高级控件，`--expand` 展开可选分区便于视觉检查。`--page script_test` 会自动开启高级模式。截图命令实际 `show()` 窗口，在 Qt 布局稳定后保存 PNG 并退出；正常启动不带 `--screenshot`。

本轮已逐页启动 Windows 正常图形后端窗口并检查截图，额外核对全部七页的 900×620 底部及共通设置。图片保存在本机忽略目录 `.build/pyside-migration/`。Windows computer-use 截图接口复核后仍返回 `SetIsBorderRequired ... 0x80004002`，所以视觉证据来自已显示窗口的 Qt `grab()`，不是 offscreen 图像。检查修复了小窗口 IV 控件把整页撑宽的问题。

恢复初版设计后再次逐页启动 Windows 正常窗口检查，截图保存在 `.build/pyside-simple/`，包括 SID 分槽、A/B 亲本、整页实测表和 900×620 展开分区。

`tests/test_pyside_preview.py` 共 12 项定向检查，覆盖独立导入、PNG、页面上下文保留、六槽禁用、精确 IV 预设、野生互斥/共用身份、TID 接续/延迟、Seed 高级范围、后端按钮禁用、最小窗口与全部分区底部可达性、窄屏方案弹窗返回、折叠后输入保留。CI 安装可选 PySide6 依赖执行这些检查，正式程序依赖表不变。测试与视觉检查均不代表后端迁移或 Switch 实机验收完成。

## 后续接入顺序

1. 按页面映射逐项抽取已有输入模型、校验与服务接口，再替换预览里的默认值和目录占位。
2. 优先接入存档信息、端口/采集卡检测、TID 实测表和日志，再接入野生/静态搜索。
3. 接入 SID、TID、孵蛋与脚本运行状态机时，复用已验证业务代码；只有真实调用并验证后才启用对应按钮。
4. 保留正式 Tk 入口作为回退；目前尚未开始后端迁移，不把可编辑表单计为功能已迁移。
