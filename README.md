# 火红/叶绿全自动乱数工具

这是一个面向 Nintendo Switch 火红/叶绿（Gen 3）的自动乱数初步实现。当前主流程使用 Ten Lines 源码搜索目标，由 Python 自动选择方案并填写 1.1.8 ECS 参数，再交给固定版本的 EasyCon 1.6.4a 控制单片机、采集卡和本地 OCR。

新流程不需要部署 Qwen、vLLM、Ollama 或其他 AI 服务。仓库中原有的 PyEasyCon/VLM 执行链仍然保留，但与本流程相互独立。

详细开发交接请先阅读 [新设备与新对话交接文档](docs/HANDOFF.md)，功能边界和验收状态见 [自动乱数首版说明](docs/INITIAL_AUTO_RNG.md)。

开发约定：每完成一轮较大的功能改动并通过本地验证，就提交并推送到私有 `origin`，让 GitHub Actions 自动复核；零散小修改可以合并到下一轮大改一起推送。

## 当前完成情况

- GUI 依次提供“SID 查找”“TID 乱数”“野生 / 静态”“孵蛋（测试）”四个选项卡，EasyCon 设置、运行按钮和结果区共用。
- 整个页面可以纵向滚动；结果框拥有独立滚动条，较小屏幕也能看到底部。
- 野生/静态页提供六项 IV 的独立最低/最高输入框，以及不限、6V、0A、0S、0A0S 预设。
- 支持闪光、性格、性别、特性、觉醒力量、Seed 模式和最大 Advance 筛选。
- Ten Lines 搜索结果先按六项 IV 总和从高到低选择；同一总和下选择 Advance 最小的可行初始 Seed。
- 自动生成经过参数替换的 1.1.8 ECS 工程，并检查脚本、1148 个标签、OCR 模型、EasyCon 版本及 ECS 语法。
- 孵蛋页可以把 Ten Lines Egg 页得到的同 Seed、Held/生成帧、Pickup/领取帧和双亲资料写入实验性孵蛋 ECS。
- TID/SID 页接入英文/日文 1.3.7 脚本，支持乱数与穷举、中心帧/半径、固定延迟校准、取名、特殊号码和本地标签识别。
- SID 查找页逐只采集队伍闪光宝可梦，由 Python 恢复 Method 1/2/4 PID、求 PSV 交集并给出 SID 候选与最早建档 ADV。
- “检测端口/采集卡”完成后会自动填写可用串口；当前串口仍有效时保留，否则选择 COM 数字最小的端口。
- 当前自动执行后端严格锁定 EasyCon 1.6.4a；不接受 1.7.0。

以下功能仍不能视为完成实机验收：狩猎区、普通碎岩、漫游三圣兽、孵蛋长跑，以及所有路线的长期稳定性。受限路线只生成搜索计划，不开放“开始运行”。

## 硬件与软件要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows x64 |
| Python | 64 位 Python 3.12；仓库内预编译扩展为 `cp312-win_amd64` |
| 单片机 | EasyCon 兼容单片机，可被 `ezcon port --list` 枚举 |
| 视频源 | 采集卡，可被 `ezcon video --list` 枚举；1.1.8 标签以 1920×1080 为基准 |
| EasyCon | `1.6.4-a+9c86137c7e63bff842175470895727a5fa9bab52` |
| 脚本包 | 已审计的“NS火叶全自动一键乱数1.1.8”正式与孵蛋版本 |

## 新设备安装

### 1. 复制完整工作区

当前源码通过私有 GitHub 仓库 `origin` 保存。换设备时克隆私有仓库，并检出包含最新功能的已推送分支或合并后的 `main`。不要只复制 `runtime/`；它是生成目录，不是源码。

### 2. 放置外部运行包

安装脚本默认使用以下位置：

```text
%USERPROFILE%\Downloads\NS火叶全自动一键乱数1.1.8\
%USERPROFILE%\Downloads\伊机控-EasyCon-v1.6.4alpha测试版-260518\publish\ezcon.exe
%USERPROFILE%\Downloads\自定义TID SID 御三家乱数多功能包1.3\
```

1.1.8 目录必须包含：

```text
NS火叶全自动一键乱数1.1.8.ecs
NS火叶全自动一键乱数1.1.8-TV时间轴测试.ecs
NS火叶SID反查-采集测试.ecs
lib\
ImgLabel\
Tessdata\frlg_battle.traineddata
Tessdata\FRLG_EN_ALL.traineddata
```

EasyCon 原始 1.6.4a 压缩包不包含这两份火叶 OCR 模型。安装器会从 1.1.8 的 `Tessdata` 复制到 EasyCon 的 `publish\Tessdata` 并校验 SHA-256。

### 3. 安装并启动

在项目根目录依次双击：

```text
安装-自动乱数首版.bat
启动-自动乱数首版.bat
```

安装器会创建 `.venv`、安装 `requirements-auto.txt`、导入并校验 1.1.8 与 TID/SID 1.3.7 快照，以及准备 EasyCon 1.6.4a OCR 环境。GUI 启动失败时查看：

```text
runtime\launcher.log
```

## 使用流程

### 野生 / 静态

1. 连接单片机和视频源。
2. 选择游戏、主机、野生/静态类型、遭遇地点和目标宝可梦，并填写 TID/SID。
3. 设置六项 IV 范围、最大 Advance、闪光、性格、性别、特性和觉醒力量等条件。
4. 点击“搜索并生成方案”。
5. 检查结果、路线支持状态和 EasyCon 预检。
6. 只有路线允许启动且预检通过后，“开始运行”按钮才会启用。

预设与 Ten Lines 一致：

| 预设 | 精确含义，顺序为 HP/攻击/防御/特攻/特防/速度 |
|---|---|
| 不限 | 六项均为 0–31 |
| 6V | 31/31/31/31/31/31 |
| 0A | 31/0/31/31/31/31 |
| 0S | 31/31/31/31/31/0 |
| 0A0S | 31/0/31/31/31/0 |

### 孵蛋（测试）

1. 先在 Ten Lines Egg 页搜索，并记录目标 Seed、Held/生成帧、Pickup/领取帧和游戏设置。
2. 打开 GUI 的“孵蛋（测试）”选项卡。
3. 选择游戏、主机、与 Ten Lines 完全一致的 Seed 模式和蛋种。
4. 填写 Held、Pickup、双亲相性、双亲性别和六项 IV。
5. 勾选实验功能确认后生成脚本。

Python 当前不重复执行蛋目标搜索；它只接收 Ten Lines Egg 页已经选好的结果。孵蛋 ECS 已通过代码与 EasyCon 1.6.4a 语法检查，但尚未完成本机实机验收。

### SID 查找

1. 把用于反查的闪光宝可梦依次放到队伍前 N 位，背包第一页第一格放神奇糖果，并在游戏内保存。
2. 在第一页填写游戏、当前 TID、队伍数量、每只最多糖果和识图阈值。
3. 每个槽位填写图鉴编号覆盖（`0` 表示 OCR 英文名称）、定点/野生来源、野生相遇地点和六项努力值。
4. 点击“准备 SID 查找”生成采集脚本并预检，再点击“开始运行”。程序会逐只采集，PSV 唯一时提前结束，并把报告回显到结果区。

闪光公式只能确定 `TID xor SID` 的高 13 位，因此结果会列出 8 个真实 SID 候选；若其中某个候选出现在 TID/SID 1.3.7 建档生成链前 10000 ADV，工具再选择窗口内最早值，否则不会擅自选定。只支持第三世代 Method 1/2/4；孵蛋来源及其他生成方式暂不支持。原命令行入口 `启动-SID反查.bat` 仍可使用。

### TID 乱数

TID/SID 页使用“自定义TID SID 御三家乱数多功能包1.3”中的英文/日文 1.3.7 脚本。页面支持：

- 乱数模式或穷举模式；
- 目标 TID/SID、主角性别和名称；
- OP/F1/F2 中心帧、乱数半径、穷举起点和最大范围；
- OP/F1/F2/F3 固定延迟和固定延迟检查；
- 豹子号、升/降连号、65535 和个位数 TID；
- SID 目标、不做 SID 乱数或随机 SID。

脚本会新建存档并自动退出游戏两次。名称或性别改变后必须先重新做固定延迟检查。日文 1.3.7 原脚本的 `FOR $InputLen` 在 1.6.4-a 会触发只读临时变量错误；生成器只在运行副本中将其替换为等价的显式索引循环，原始模板不被修改。

英文 1.3.7 的用户区结束标记之后保持与原版逐字一致，`HOME_BUFFER` 等函数不会被生成器改写。EasyCon 1.6.4-a 自带 GUI 对 ImgLabel 置信度使用 `Math.Ceiling`，但同包 `ezcon.exe run` 使用直接整数截断；95 分边界会因此出现 GUI 能识别而 CLI 识别不到的情况。自动启动现在使用由同一 `9c86137` 源码构建的兼容 runner，只把 CLI 取整改为与 GUI 一致。原始 `ezcon.exe` 仍负责版本/哈希、设备、Tessdata 与 `format` 预检，视频后端仍为 DSHOW。

TID 到御三家的连续流程不采用把英日两套完整 ECS 拼接起来的单体结构。`automation/tid_starter_flow.py` 选择并生成一份原版语言模板，成功时输出结构化标记，再执行独立的研究所桥接路线；共同的 `rng/starter_sid_verification.py` 使用 TenLines Seed 表从 ADV 1500 起搜索最早可达的闪光 Method 1 御三家目标。集合样本只作为研究所路线和日版 1.6.4-a 取名循环修正的依据，样本中的旧御三家 OP/F12 控制器没有导入。

御三家阶段按普通乱数目标处理：尚未命中目标 PID 时继续原有自动校准，不判断也不修正 SID；命中目标 PID 后，不闪表示本次 SID 未命中，闪光表示 SID 命中并结束。SID 未命中后，以当前 `$SID_ADV修正` 为中心按 `当前、+1、-1、+2、-2...` 尝试。当前已完成目标搜索、ID 标记、研究所桥接工程和判定模型；GUI 连续启动三个阶段及实机验收仍未完成。

## 命令行计划器

只生成计划、不启动硬件：

```powershell
.\.venv\Scripts\python.exe run_auto_planner.py `
  --game fr_nx --tid 58888 --sid 12232 `
  --method Static --category Starter --pokemon Bulbasaur `
  --max-advances 100000 `
  --iv-min 29/31/27/29/29/30 `
  --iv-max 29/31/27/29/29/30
```

只有显式增加 `--run` 才会把控制权交给兼容 runner。换设备后如未复制 `runtime_backend` 中的可执行文件，可运行 `tools\build_easycon164a_compat_runner.ps1` 重新构建。

## 测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m py_compile run_auto_rng_gui.py
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

截至 2026-08-13，现有测试共 76 项，使用项目 `.venv` 全部通过。它们覆盖计划择优、IV 输入、SID 采集请求与反查、御三家最低闪光目标和 SID 判定、Seed 模式、静态目标白名单、路线边界、1.1.8 参数替换、孵蛋参数、TID/SID 1.3.7 日英模板与标签、标签兼容、EasyCon 1.6.4a 预检和 GUI/CLI 识图取整兼容 runner。测试通过不等于 Switch 实机长跑已经验收。

## 目录结构

```text
automation/                 自动搜索、择优、路线支持和 ECS 适配
assets/                     中文文本与现有资源
docs/                       首版说明和跨设备交接文档
easycon/                    原 PyEasyCon 协议、识图和标签兼容层
rng/                        Ten Lines Python/C++ 搜索代码
tests/                      单元测试
tools/                      1.1.8 导入、标签审计、EasyCon 准备工具
run_auto_rng_gui.py         当前 GUI 主入口
run_auto_planner.py         命令行计划器
requirements-auto.txt       新自动流程最小依赖
local_assets/easycon118/    导入的 1.1.8 快照，Git 忽略
local_assets/tid_rng137/    导入的 TID/SID 1.3.7 快照，Git 忽略
runtime/easycon118/         当前生成的 ECS 工程，Git 忽略
runtime/sid_reverse/        SID 采集工程、日志与结果报告，Git 忽略
rng_logs/plans/             计划记录，Git 忽略
```

## 原 PyEasyCon/VLM 执行链

仓库原有 `examples/`、`script_*.py`、`vision/` 和 Pygame GUI 等功能仍可使用 `requirements.txt`，可能依赖 Qwen/VLM。它们不属于本文的 EasyCon 1.6.4a + 1.1.8 新流程。排查问题时先确认正在使用哪条执行链，避免把旧 AI OCR 配置与新本地 Tesseract 流程混在一起。

## 许可证

仓库主体沿用原项目许可证；`rng/` 中移植的 Ten Lines 代码保留其自身 GPLv3 说明。外部 EasyCon 和 1.1.8 包不随本文重新授权。
