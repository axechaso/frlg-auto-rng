# 新设备与新对话交接文档

本文是当前火红/叶绿全自动乱数初步实现的开发快照。换设备或新建 Codex 对话时，先让新对话完整阅读本文件、根目录 `README.md` 和 `docs/INITIAL_AUTO_RNG.md`，再检查工作区实际状态。

快照日期：2026-08-13。

## 最重要的迁移提醒

当前旧设备工作区：

```text
C:\Users\axenx\Documents\火叶乱数\frlg-auto-rng
```

当前分支和基准提交：

```text
branch: codex/initial-auto-planner
base commit: 22f1e856eeab6a6e2b7f689459a3657f15528086
```

但自动计划器、EasyCon 1.6.4a 接入、新 GUI、测试和文档主要仍是未提交的修改或新增文件。当前 `origin` 还是旧设备上的本地 `.codex-review\PyEasyCon` 路径，不是新设备可访问的网络远端。

因此：

- 直接换设备时，复制整个项目工作区最稳妥；
- 若走 Git，必须先在旧设备提交当前改动并推送到真正可访问的远端；
- 新对话不得执行 `git reset --hard`、`git clean` 或用旧提交覆盖工作区；
- `local_assets/`、`runtime/`、`rng_logs/` 和 `.venv/` 被 Git 忽略，不会随普通提交迁移；
- 外部 1.1.8 和 EasyCon 安装包也必须单独复制或重新取得。

在新设备首先运行：

```powershell
git status --short
git branch --show-current
git log -1 --oneline
```

如果 `automation/`、`run_auto_rng_gui.py`、`tests/` 等文件不存在，说明拿到的是旧提交而不是当前工作区。

## 项目目标和当前决策

目标是让用户只进行必要信息输入，然后由工具自动完成目标搜索、方案选择、1.1.8 参数填写、预检和 EasyCon 启动。

当前已经确定的设计决策：

1. 自动执行后端先固定 EasyCon 1.6.4a，不接 1.7.0。
2. 新流程不部署 AI；OCR 由 EasyCon 1.6.4a 的本地 Tesseract 和 1.1.8 标签完成。
3. Python 负责 Ten Lines 搜索、候选排序、参数生成和启动编排。
4. 1.1.8 ECS 目前继续负责命中、OCR、IV 反查、吃糖缩小区间、跨轮投票、校准、抓捕和重试。
5. “ECS 只读能力值，IV/Seed 反查与校准状态机迁到 Python”只作为后续方案，用户已明确要求现在暂不实施。
6. 最大搜索范围使用最大 Advance，不使用“5 分钟/10 分钟”时间预设。
7. 选优规则是先取六项 IV 总和最高的结果，再取 Advance 最小的可行初始 Seed。
8. 孵蛋作为独立选项卡，不放在野生/静态类型下拉框中。
9. TID/SID 使用独立选项卡和独立 1.3.7 模板/标签包，不混入 1.1.8 主 ECS。

## 当前运行链

```mermaid
flowchart LR
    A["GUI 输入"] --> B["Ten Lines 搜索"]
    B --> C["最高 IV 总和 / 最小 Advance"]
    C --> D["生成 1.1.8 main.ecs"]
    D --> E["版本、标签、Tessdata、format 预检"]
    E --> F["1.6.4-a CLI 兼容 runner"]
    F --> G["单片机 + 采集卡 + 本地 OCR"]
```

边界非常重要：

- `run_auto_rng_gui.py` 和 `run_auto_planner.py` 调用 `automation/`，再调用外部 `ezcon.exe`；
- `easycon/controller.py` 等旧 PyEasyCon 直连串口代码属于另一条执行链；
- 新流程不需要启动 vLLM、Ollama 或 ModelScope；
- EasyCon 1.6.4a 不含 1.7.0 的 `ir` 命令，语法预检必须使用 `ezcon format <main.ecs>`。
- 1.6.4-a GUI 对 ImgLabel 分数使用 `Math.Ceiling`，原始 `ezcon.exe run` 却用整数截断。自动启动使用固定 commit `9c86137` 构建的兼容 runner，将 CLI 取整恢复为 GUI 行为；视频后端仍为 DSHOW，英文 TID ECS 的 `HOME_BUFFER` 没有被改。

## GUI 当前状态

主入口：`run_auto_rng_gui.py`。

页面使用完整纵向滚动容器，默认窗口 1100×880，最小 900×620。右侧滚动条滚动整页；鼠标位于结果文本框时只滚动结果。

GUI 有三个选项卡：

### 野生 / 静态

- 游戏：火红/叶绿；主机：Switch 1/2；TID/SID；
- 类型下拉框只有野生和静态；
- 遭遇方式、地点和目标宝可梦联动；
- 六项 IV 分别填写最低/最高值；
- 不限、6V、0A、0S、0A0S 预设和单项重置；
- 闪光、性格、性别、特性、觉醒力量、Seed 模式、最大 Advance；
- 自动抓捕、麻痹、点到为止选项。

Ten Lines 预设是精确 IV，不是“其余任意”：

```text
6V    = 31/31/31/31/31/31
0A    = 31/0/31/31/31/31
0S    = 31/31/31/31/31/0
0A0S  = 31/0/31/31/31/0
```

### 孵蛋（测试）

- 独立显示游戏、主机、Seed 模式和蛋种；
- 目标 Seed、Held/生成帧、Pickup/领取帧；
- 双亲相性 20/50/70；
- 双亲性别和六项 IV；
- 必须勾选实验性时间轴确认。

孵蛋页不负责搜索蛋目标。用户必须先从 Ten Lines Egg 页取得同一初始 Seed 下的 Held 和 Pickup。Pickup 至少比 Held 晚 1800 帧。

### TID / SID

- 英文/日文 ROM、乱数/穷举、Switch 1/2、主角性别和名称；
- 目标 TID/SID 与三种 SID 处理模式；
- OP/F1/F2 中心帧、搜索半径、穷举起点和范围；
- 固定延迟、游戏设置、去噪与特殊号码判定；
- 独立脚本包路径，默认是 `%USERPROFILE%\Downloads\自定义TID SID 御三家乱数多功能包1.3`。

适配器位于 `automation/tid_rng137.py`。它锁定英文/日文 1.3.7 脚本指纹和 328 个标签。日文原脚本 `FOR $InputLen` 在 1.6.4-a 会报三次只读 `_tmpL$0`；生成副本会按 ECS 约束改为先算有效末索引再使用显式索引 `FOR`。该修正不改 Seed/帧轴，不改用户原包。

## 代码导航

| 文件 | 作用 |
|---|---|
| `run_auto_rng_gui.py` | 两个选项卡、输入校验、后台搜索、方案展示、预检和启动/停止 |
| `run_auto_planner.py` | 普通野生/静态命令行计划器；默认只生成，`--run` 才启动 |
| `automation/planner.py` | `AutoSearchRequest`、分层搜索、最高 IV 总和、同分最小 Advance |
| `automation/seed_modes.py` | 1.1.8 Seed 模式 0–9 与 Ten Lines 游戏设置映射 |
| `automation/static_targets.py` | 静态类别和版本限定白名单 |
| `automation/support.py` | 路线启动边界；狩猎区/碎岩等保守阻止 |
| `automation/easycon118.py` | 1.1.8 参数替换、指纹、EasyCon 预检、设备枚举和运行命令 |
| `automation/tid_rng137.py` | TID/SID 1.3.7 模板/标签锁定、参数替换、日版 1.6.4-a 兼容和预检 |
| `rng/tenlines_utils.py` | Ten Lines 搜索、IV 分层、资源读取和 C++ 接口 |
| `easycon/label_matcher.py` | 方法 1/5/14 的统一标签匹配兼容层 |
| `tools/import_easycon118.py` | 从外部 1.1.8 包导入已审计快照 |
| `tools/import_tid_rng137.py` | 从外部多功能包导入已审计的 TID/SID 1.3.7 日英模板与标签 |
| `tools/prepare_easycon164a.py` | 锁定 ezcon 版本/哈希并安装两份火叶 Tessdata |
| `tools/build_easycon164a_compat_runner.ps1` | 从固定 1.6.4-a commit 重建 GUI 识图取整兼容 runner |
| `runtime_backend/README.md` | 兼容 runner 的原因、边界和校验方式 |
| `tools/audit_easycon118_labels.py` | 标签审计工具 |
| `tests/` | 计划、GUI 输入、孵蛋、标签和 1.6.4a 后端测试 |

本机运行目录：

```text
local_assets/easycon118/   经审计的外部脚本快照
local_assets/tid_rng137/   经审计的 TID/SID 1.3.7 快照
runtime/easycon118/        最近一次生成的 main.ecs、lib、ImgLabel、plan.json
rng_logs/plans/            每次普通或孵蛋生成的 JSON 记录
runtime/launcher.log        BAT 启动日志
```

这些目录都不能被当作源文件修改入口。模板应从外部 1.1.8 包重新审计导入，生成工程由 Python 重新产生。

## 固定版本与资产指纹

### EasyCon 1.6.4a

```text
version: 1.6.4-a+9c86137c7e63bff842175470895727a5fa9bab52
ezcon.exe SHA-256: 559b81c234d2548c439926a88f5355ccac0958b8a191c1ecca48b2c7c71c1260
default path: %USERPROFILE%\Downloads\伊机控-EasyCon-v1.6.4alpha测试版-260518\publish\ezcon.exe
```

自动执行兼容 runner 同样来自 commit `9c86137c7e63bff842175470895727a5fa9bab52`，功能补丁标识为 `cli-image-label-ceiling-v1`。当前自包含构建 SHA-256 为 `5f0f83deb164aaa3328ae1f79f5fa9128999d15b4a79fd017af6fdf6d6d317c7`；可执行文件因体积较大被 Git 忽略，复制完整工作区时会保留，只用 Git 迁移时须运行 `tools\build_easycon164a_compat_runner.ps1` 重建。

### 1.1.8 正式/孵蛋脚本

```text
主 ECS + lib 文件数: 33
脚本语料 SHA-256: bc0845d23f47805b1c6f46cd861deb69c01c7605a72d92ad7e00f538cee6f52e
```

不要把曾经的旧快照指纹 `db50e6...` 或有 `$调试日志输出` 编译问题的其他快照直接替换进来。

### 标签

```text
总数: 871
方法 1: 15
方法 5: 502
方法 14: 354
标签语料 SHA-256: 934060b2cf40ac30b461bcf59fddcb375eeaceae75a809ec294920cc7d6fe0b8
```

方法 14 必须保留原 Alpha 通道作为 `TM_SQDIFF_NORMED` 的 mask。

### 火叶 OCR 模型

```text
frlg_battle.traineddata:
7abcaef4936727b33717656b38fd5b5027823e1cafec21abb06cc8ef1f7ff758

FRLG_EN_ALL.traineddata:
3272f23a6f259518813025d89be77d706574ccdf163132ccf6f5be15ca19cfa0
```

EasyCon 1.6.4a 的 OCR 是本地 Tesseract，不依赖外部 AI 服务。原始 1.6.4a 压缩包只有通用数据时，必须由安装器补齐以上两份模型。

## 新设备安装核对

1. 安装 Windows x64 Python 3.12。
2. 确认 `rng/src/pybind/calibration_bind.cp312-win_amd64.pyd` 存在。
3. 把 1.1.8 包放到 `%USERPROFILE%\Downloads\NS火叶全自动一键乱数1.1.8`。
4. 把 EasyCon 1.6.4a 放到默认目录，或后续显式调整准备脚本和 GUI 路径。
5. 运行 `安装-自动乱数首版.bat`。
6. 运行 `启动-自动乱数首版.bat`。
7. 在 GUI 点击“检测端口/采集卡”，不要照搬旧设备的 COM 号和采集卡序号。

若安装器已经创建旧的错误 `.venv`，应先人工确认没有需要保留的内容，再删除 `.venv` 并用 64 位 Python 3.12 重装；不要由新对话擅自删除用户目录。

## 验证命令和当前基线

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m py_compile run_auto_rng_gui.py
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe tools\prepare_easycon164a.py --check-only
```

2026-08-13 的代码基线：48 项单元测试全部通过；下载包 `Tools/check_*.py` 共 22 项全部通过。另做过透明 Tk 窗口冒烟检查，确认：

- 三个选项卡可以切换；
- 普通类型下拉框不再包含孵蛋；
- 孵蛋参数可收集成 `EggRunRequest`；
- 900×620 窗口可滚动到页面底部；
- “隐藏属性”文案已经改为“觉醒力量”。
- TID/SID 日英参数可收集，日文生成副本可通过真实 1.6.4-a `format`。

本机曾验证 1.6.4a 可以枚举串口和视频设备，并可用 `format` 解析当前 ECS。换设备后设备编号必然可能变化，必须重新检测。

## 已知边界和禁止误报

| 功能 | 当前状态 |
|---|---|
| 普通野生路线 | 搜索/生成/启动链已接通；仍需按地点实机验收 |
| 静态目标 | 7 类、每版 27 个 GUI 目标；已接通但仍需实机验收 |
| 普通碎岩 | 1.1.8 明确未完成，只搜索，不启动 |
| 狩猎区 | 新脚本虽增加路线，但本机未验收，只搜索，不启动 |
| 漫游三圣兽 | 截断 IV bug 与存档御三家约束未实现，不开放 |
| 孵蛋 | 同 Seed ECS 代码/语法测试通过，尚未实机验收 |
| EasyCon 1.7.0 | 不支持；接口/标签差异待以后重新核对 |
| Python 接管 IV/Seed 反查 | 已调研，用户要求暂缓 |
| AI/VLM | 新流程不需要；旧 PyEasyCon 链仍可能需要 |

不要把“单元测试通过”“ECS format 通过”描述为“实机全自动稳定完成”。

## 建议的下一步

按风险从低到高：

1. 在新设备重新跑安装、48 项测试、EasyCon `--check-only` 和设备枚举。
2. 用不会影响存档的短 ECS 验证单片机控制、停止和重新连接。
3. 选一个普通野生基线路线做单轮命中、OCR、反查和校准日志验收。
4. 再做重复循环、抓捕和长时间稳定性。
5. 单独验收孵蛋前置条件、Held/Pickup 两次命中和孵化反查。
6. 最后才考虑开放狩猎区或迁移 Python 反查状态机。

如果继续改善软件而不接硬件，优先事项可以是：增加 GUI 自动化测试、把外部包路径做成持久配置、完善错误日志与恢复，以及为实机验收建立黄金日志/截图集。

## 可直接粘贴到新对话的提示

```text
请接手这个火红/叶绿全自动乱数项目。先完整阅读 README.md、docs/HANDOFF.md 和 docs/INITIAL_AUTO_RNG.md，然后运行 git status --short，确认不要覆盖或清理现有未提交改动。

当前主入口是 run_auto_rng_gui.py：GUI 有“野生 / 静态”“孵蛋（测试）”和“TID / SID”三个选项卡，整页可滚动。普通流程由 Ten Lines 搜索，按最高 IV 总和、再按最小 Advance 选择方案，生成 1.1.8 ECS 后交给固定 EasyCon 1.6.4a。本流程不部署 AI。孵蛋只接收 Ten Lines Egg 页已经得到的同 Seed、Held 和 Pickup，尚未实机验收。TID/SID 页使用锁定的英文/日文 1.3.7 脚本和独立标签包。

EasyCon 必须锁定 1.6.4-a+9c86137...，预检使用 ezcon format，不要改成 1.7.0 的 ir。狩猎区、碎岩、漫游兽和孵蛋不能宣称已实机完成。IV/Seed 反查迁到 Python 是以后方案，当前不要实施。

先运行：
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m py_compile run_auto_rng_gui.py
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe tools\prepare_easycon164a.py --check-only

测试基线是 48 项，ECS Tools 静态检查是 22 项。完成环境核对后，请根据我接下来的要求继续，不要自行扩大到实机运行或修改外部 1.1.8/TID/EasyCon 原包。
```
